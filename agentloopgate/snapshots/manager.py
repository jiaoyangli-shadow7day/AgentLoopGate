"""Immutable snapshots with explicit human promotion and parent rollback."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from agentloopgate.contracts import canonical_digest, canonical_json_bytes, file_digest
from agentloopgate.schemas import (
    CandidateRecord,
    CandidateStatus,
    DecisionRecord,
    DecisionValue,
    RuntimeHost,
    SnapshotManifest,
)
from agentloopgate.schemas.models import SnapshotRuntime
from agentloopgate.snapshots.models import (
    ActivationAction,
    ApprovalAction,
    PromotionApproval,
    SnapshotActivation,
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class SnapshotIntegrityError(ValueError):
    """Snapshot bytes or parent relationships are invalid."""


class SnapshotAuthorizationError(PermissionError):
    """A promote/rollback request lacks valid human authorization."""


class SnapshotManager:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.store_root = self.project_root / "snapshots"

    def create_baseline(
        self,
        *,
        snapshot_id: str,
        harness_paths: list[str],
        model_id: str,
        objective_digest: str,
        split_digest: str,
        asset_manifest_digest: str,
        code_revision: str,
        runtime_host: str,
        runtime_version: str,
        created_at: datetime,
    ) -> SnapshotManifest:
        self._safe_id(snapshot_id)
        if self._activation_paths():
            raise SnapshotIntegrityError("a baseline snapshot is already active")
        expected = sorted(set(harness_paths))
        actual = self._live_harness_paths()
        if actual != expected:
            raise SnapshotIntegrityError(
                "baseline harness_paths must exactly cover the live harness tree"
            )
        manifest = SnapshotManifest(
            schema_version="1.0",
            snapshot_id=snapshot_id,
            parent_snapshot_id=None,
            candidate_id=None,
            model_id=model_id,
            objective_digest=objective_digest,
            split_digest=split_digest,
            asset_manifest_digest=asset_manifest_digest,
            code_revision=code_revision,
            harness_files={path: file_digest(self.project_root / path) for path in expected},
            runtime=SnapshotRuntime(
                host=RuntimeHost(runtime_host),
                version=runtime_version,
            ),
            created_at=created_at,
        )
        self._store_snapshot(manifest, source_root=self.project_root)
        self._append_activation(
            SnapshotActivation(
                schema_version="1.0",
                ordinal=1,
                action=ActivationAction.BASELINE,
                snapshot_id=snapshot_id,
                previous_snapshot_id=None,
                decision_id=None,
                approval_digest=None,
                actor="human-baseline-capture",
                activated_at=created_at,
            )
        )
        return manifest

    def create_evaluation_baseline(
        self,
        *,
        snapshot_id: str,
        harness_paths: list[str],
        model_id: str,
        objective_digest: str,
        split_digest: str,
        asset_manifest_digest: str,
        code_revision: str,
        runtime_host: str,
        runtime_version: str,
        created_at: datetime,
        allow_reviewed_harness_revision: bool = False,
    ) -> SnapshotManifest:
        """Capture a non-active baseline for a new evaluation revision.

        The deployment activation registry remains untouched. Legacy callers
        may only revise non-harness execution identity. A corrected formal
        experiment may explicitly capture reviewed source bytes that differ
        from the deployed snapshot without activating those bytes.
        """

        self._safe_id(snapshot_id)
        active = (
            self.active_snapshot()
            if allow_reviewed_harness_revision
            else self.verify_active_live()
        )
        expected = sorted(set(harness_paths))
        actual = self._live_harness_paths()
        if actual != expected:
            raise SnapshotIntegrityError(
                "evaluation baseline must exactly cover the reviewed live harness tree"
            )
        if (
            not allow_reviewed_harness_revision
            and expected != sorted(active.harness_files)
        ):
            raise SnapshotIntegrityError(
                "legacy evaluation baseline must cover the active harness tree"
            )
        manifest = SnapshotManifest(
            schema_version="1.0",
            snapshot_id=snapshot_id,
            parent_snapshot_id=None,
            candidate_id=None,
            model_id=model_id,
            objective_digest=objective_digest,
            split_digest=split_digest,
            asset_manifest_digest=asset_manifest_digest,
            code_revision=code_revision,
            harness_files={path: file_digest(self.project_root / path) for path in expected},
            runtime=SnapshotRuntime(
                host=RuntimeHost(runtime_host),
                version=runtime_version,
            ),
            created_at=created_at,
        )
        if (
            not allow_reviewed_harness_revision
            and manifest.harness_files != active.harness_files
        ):
            raise SnapshotIntegrityError(
                "evaluation baseline harness bytes differ from the active snapshot"
            )
        self._store_snapshot(manifest, source_root=self.project_root)
        return manifest

    def create_child(
        self,
        candidate: CandidateRecord,
        *,
        model_id: str,
        code_revision: str,
        runtime_host: str,
        runtime_version: str,
        created_at: datetime,
    ) -> SnapshotManifest:
        if candidate.status in {
            CandidateStatus.DRAFT,
            CandidateStatus.REJECTED,
            CandidateStatus.HELD,
            CandidateStatus.ROLLED_BACK,
        }:
            raise SnapshotIntegrityError(
                f"candidate status cannot materialize a child snapshot: {candidate.status.value}"
            )
        parent = self.verify(candidate.parent_snapshot_id)
        patch = self._project_path(candidate.patch_path)
        if not patch.is_file() or file_digest(patch) != candidate.patch_digest:
            raise SnapshotIntegrityError("candidate patch is missing or has drifted")
        with TemporaryDirectory(prefix="agentloopgate-snapshot-") as temporary:
            staging = Path(temporary).resolve()
            self._copy_snapshot_files(parent, staging)
            check = subprocess.run(
                ["git", "apply", "--check", str(patch)],
                cwd=staging,
                capture_output=True,
                text=True,
            )
            if check.returncode != 0:
                raise SnapshotIntegrityError(f"candidate patch cannot apply: {check.stderr[:300]}")
            subprocess.run(
                ["git", "apply", str(patch)],
                cwd=staging,
                check=True,
                capture_output=True,
            )
            files = self._tree_digests(staging)
            changed = sorted(
                path
                for path in set(parent.harness_files) | set(files)
                if parent.harness_files.get(path) != files.get(path)
            )
            if changed != sorted(candidate.changed_files):
                raise SnapshotIntegrityError(
                    "materialized child changes do not match CandidateRecord.changed_files"
                )
            identity = canonical_digest(
                {
                    "parent_snapshot_id": parent.snapshot_id,
                    "candidate_id": candidate.candidate_id,
                    "patch_digest": candidate.patch_digest,
                    "harness_files": files,
                }
            ).removeprefix("sha256:")[:16].upper()
            manifest = SnapshotManifest(
                schema_version="1.0",
                snapshot_id=f"S_{identity}",
                parent_snapshot_id=parent.snapshot_id,
                candidate_id=candidate.candidate_id,
                model_id=model_id,
                objective_digest=parent.objective_digest,
                split_digest=parent.split_digest,
                asset_manifest_digest=parent.asset_manifest_digest,
                code_revision=code_revision,
                harness_files=files,
                runtime=SnapshotRuntime(
                    host=RuntimeHost(runtime_host),
                    version=runtime_version,
                ),
                created_at=created_at,
            )
            self._store_snapshot(manifest, source_root=staging)
        return manifest

    def promote(
        self,
        snapshot_id: str,
        decision: DecisionRecord,
        *,
        approval: PromotionApproval | None,
    ) -> SnapshotActivation:
        target = self.verify(snapshot_id)
        if approval is None:
            raise SnapshotAuthorizationError("human approval is required for promotion")
        self._require_approval(approval, ApprovalAction.PROMOTE, snapshot_id)
        if decision.decision is not DecisionValue.SHIP_RECOMMENDED:
            raise SnapshotAuthorizationError(
                "promotion requires a SHIP_RECOMMENDED DecisionRecord"
            )
        if target.candidate_id != decision.candidate_id:
            raise SnapshotAuthorizationError("decision candidate does not match target snapshot")
        if target.parent_snapshot_id != decision.baseline_snapshot_id:
            raise SnapshotAuthorizationError("decision baseline does not match snapshot parent")
        active = self.active_snapshot()
        if active.snapshot_id == target.snapshot_id:
            previous = self._last_activation()
            if (
                previous.action is ActivationAction.PROMOTE
                and previous.decision_id == decision.decision_id
                and previous.approval_digest == canonical_digest(approval)
            ):
                self._require_live_matches(target)
                return previous
            raise SnapshotAuthorizationError(
                "target is already active under different promotion evidence"
            )
        if active.snapshot_id != target.parent_snapshot_id:
            raise SnapshotAuthorizationError("target parent is not the active snapshot")
        self._require_live_matches(active)
        self._materialize_live(target)
        activation = SnapshotActivation(
            schema_version="1.0",
            ordinal=len(self._activation_paths()) + 1,
            action=ActivationAction.PROMOTE,
            snapshot_id=target.snapshot_id,
            previous_snapshot_id=active.snapshot_id,
            decision_id=decision.decision_id,
            approval_digest=canonical_digest(approval),
            actor=approval.actor,
            activated_at=approval.approved_at,
        )
        self._append_activation(activation)
        return activation

    def rollback(
        self,
        snapshot_id: str,
        *,
        approval: PromotionApproval | None,
    ) -> SnapshotActivation:
        target = self.verify(snapshot_id)
        if approval is None:
            raise SnapshotAuthorizationError("human approval is required for rollback")
        self._require_approval(approval, ApprovalAction.ROLLBACK, snapshot_id)
        active = self.active_snapshot()
        if active.snapshot_id == target.snapshot_id:
            previous = self._last_activation()
            if (
                previous.action is ActivationAction.ROLLBACK
                and previous.approval_digest == canonical_digest(approval)
            ):
                self._require_live_matches(target)
                return previous
            raise SnapshotAuthorizationError(
                "rollback target is already active under different evidence"
            )
        if active.parent_snapshot_id != target.snapshot_id:
            raise SnapshotAuthorizationError("rollback target is not the active snapshot parent")
        self._require_live_matches(active)
        self._materialize_live(target)
        activation = SnapshotActivation(
            schema_version="1.0",
            ordinal=len(self._activation_paths()) + 1,
            action=ActivationAction.ROLLBACK,
            snapshot_id=target.snapshot_id,
            previous_snapshot_id=active.snapshot_id,
            decision_id=None,
            approval_digest=canonical_digest(approval),
            actor=approval.actor,
            activated_at=approval.approved_at,
        )
        self._append_activation(activation)
        return activation

    def active_snapshot(self) -> SnapshotManifest:
        paths = self._activation_paths()
        if not paths:
            raise SnapshotIntegrityError("no active snapshot is registered")
        try:
            event = SnapshotActivation.model_validate_json(
                paths[-1].read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise SnapshotIntegrityError("activation registry is corrupt") from exc
        return self.verify(event.snapshot_id)

    def verify_active_live(self) -> SnapshotManifest:
        active = self.active_snapshot()
        self._require_live_matches(active)
        return active

    def verify_live(self, snapshot_id: str) -> SnapshotManifest:
        """Verify live harness bytes against any immutable snapshot."""

        snapshot = self.verify(snapshot_id)
        self._require_live_matches(snapshot)
        return snapshot

    def verify(self, snapshot_id: str) -> SnapshotManifest:
        directory = self._snapshot_dir(snapshot_id)
        try:
            manifest = SnapshotManifest.model_validate_json(
                (directory / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise SnapshotIntegrityError(f"snapshot is unavailable: {snapshot_id}") from exc
        if manifest.snapshot_id != snapshot_id:
            raise SnapshotIntegrityError("snapshot manifest identity mismatch")
        actual = self._tree_digests(directory / "files")
        if actual != manifest.harness_files:
            raise SnapshotIntegrityError("snapshot harness digest mismatch")
        return manifest

    def _store_snapshot(self, manifest: SnapshotManifest, *, source_root: Path) -> None:
        directory = self._snapshot_dir(manifest.snapshot_id)
        if directory.exists():
            existing = self.verify(manifest.snapshot_id)
            if canonical_digest(existing) != canonical_digest(manifest):
                raise SnapshotIntegrityError("snapshot id already exists with different bytes")
            return
        files_root = directory / "files"
        for relative, expected_digest in manifest.harness_files.items():
            source = (source_root / relative).resolve()
            if not source.is_file() or source.is_symlink():
                raise SnapshotIntegrityError(f"snapshot source is invalid: {relative}")
            if file_digest(source) != expected_digest:
                raise SnapshotIntegrityError(f"snapshot source drifted: {relative}")
            destination = files_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        self._write_once(
            directory / "manifest.json",
            manifest.model_dump(mode="json"),
        )

    def _copy_snapshot_files(self, manifest: SnapshotManifest, destination: Path) -> None:
        source_root = self._snapshot_dir(manifest.snapshot_id) / "files"
        for relative in manifest.harness_files:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_root / relative, target)

    def _materialize_live(self, target: SnapshotManifest) -> None:
        source_root = self._snapshot_dir(target.snapshot_id) / "files"
        existing = set(self._live_harness_paths())
        desired = set(target.harness_files)
        for relative in sorted(existing - desired):
            (self.project_root / relative).unlink()
        for relative, expected_digest in target.harness_files.items():
            source = source_root / relative
            destination = self.project_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".alg.tmp")
            temporary.write_bytes(source.read_bytes())
            temporary.replace(destination)
            if file_digest(destination) != expected_digest:
                raise SnapshotIntegrityError(f"live snapshot write failed: {relative}")
        self._require_live_matches(target)

    def _require_live_matches(self, manifest: SnapshotManifest) -> None:
        if self._live_harness_paths() != sorted(manifest.harness_files):
            raise SnapshotAuthorizationError("live harness file set has drifted")
        for relative, expected_digest in manifest.harness_files.items():
            path = self.project_root / relative
            if not path.is_file() or file_digest(path) != expected_digest:
                raise SnapshotAuthorizationError(f"live harness drift detected: {relative}")

    @staticmethod
    def _require_approval(
        approval: PromotionApproval,
        action: ApprovalAction,
        snapshot_id: str,
    ) -> None:
        if approval.action is not action or approval.target_snapshot_id != snapshot_id:
            raise SnapshotAuthorizationError("approval action or target does not match request")

    def _live_harness_paths(self) -> list[str]:
        root = self.project_root / "harness"
        if not root.is_dir():
            return []
        if any(path.is_symlink() for path in root.rglob("*")):
            raise SnapshotIntegrityError("live harness cannot contain symlinks")
        return sorted(
            path.relative_to(self.project_root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        )

    @staticmethod
    def _tree_digests(root: Path) -> dict[str, str]:
        if not root.is_dir():
            return {}
        if any(path.is_symlink() for path in root.rglob("*")):
            raise SnapshotIntegrityError("snapshot tree cannot contain symlinks")
        return {
            path.relative_to(root).as_posix(): file_digest(path)
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def _append_activation(self, event: SnapshotActivation) -> None:
        expected = len(self._activation_paths()) + 1
        if event.ordinal != expected:
            raise SnapshotIntegrityError("activation ordinal is not append-only")
        self._write_once(
            self.store_root / "activations" / f"{event.ordinal:04d}.json",
            event.model_dump(mode="json"),
        )

    def _activation_paths(self) -> list[Path]:
        return sorted((self.store_root / "activations").glob("*.json"))

    def _last_activation(self) -> SnapshotActivation:
        paths = self._activation_paths()
        if not paths:
            raise SnapshotIntegrityError("no snapshot activation is registered")
        try:
            return SnapshotActivation.model_validate_json(
                paths[-1].read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise SnapshotIntegrityError("activation registry is corrupt") from exc

    def _snapshot_dir(self, snapshot_id: str) -> Path:
        self._safe_id(snapshot_id)
        return self.store_root / snapshot_id

    def _project_path(self, relative: str) -> Path:
        path = (self.project_root / relative).resolve()
        try:
            path.relative_to(self.project_root)
        except ValueError as exc:
            raise SnapshotIntegrityError("project artifact path escapes the root") from exc
        return path

    @staticmethod
    def _safe_id(value: str) -> None:
        if not _SAFE_ID.fullmatch(value):
            raise SnapshotIntegrityError("unsafe snapshot id")

    @staticmethod
    def _write_once(path: Path, payload: object) -> None:
        encoded = canonical_json_bytes(payload) + b"\n"
        if path.exists():
            try:
                existing = canonical_json_bytes(
                    json.loads(path.read_text(encoding="utf-8"))
                ) + b"\n"
            except (OSError, json.JSONDecodeError) as exc:
                raise SnapshotIntegrityError(
                    f"existing snapshot artifact is corrupt: {path}"
                ) from exc
            if existing != encoded:
                raise SnapshotIntegrityError(f"snapshot artifact conflict: {path}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
