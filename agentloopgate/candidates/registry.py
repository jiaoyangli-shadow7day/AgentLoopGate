"""Append-only CandidateRecord registry and state machine."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from agentloopgate.contracts import canonical_digest, canonical_json_bytes, file_digest
from agentloopgate.mutation import CandidateChecker, CheckDisposition
from agentloopgate.schemas import CandidateRecord, CandidateStatus, FailureBundle
from agentloopgate.schemas.models import (
    EffectDirection,
    EffectMetric,
    NonEmpty,
    PredictedEffect,
    StrictModel,
    UpdaterIdentity,
    UtcDateTime,
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class CandidateStateError(ValueError):
    """Candidate registration or lifecycle transition is invalid."""


class CandidateRejectedError(CandidateStateError):
    """Candidate Check rejected the proposed patch."""


class CandidateLifecycleEvent(StrictModel):
    schema_version: str = "1.0"
    ordinal: int = Field(ge=1)
    previous_status: CandidateStatus | None
    next_status: CandidateStatus
    actor: NonEmpty
    evidence_refs: list[NonEmpty] = Field(min_length=1)
    occurred_at: UtcDateTime
    record: CandidateRecord


_TRANSITIONS: dict[CandidateStatus, set[CandidateStatus]] = {
    CandidateStatus.DRAFT: {CandidateStatus.REGISTERED, CandidateStatus.REJECTED},
    CandidateStatus.REGISTERED: {
        CandidateStatus.CHECKED,
        CandidateStatus.HELD,
        CandidateStatus.REJECTED,
    },
    CandidateStatus.CHECKED: {
        CandidateStatus.UPDATE_EVALUATED,
        CandidateStatus.HELD,
        CandidateStatus.REJECTED,
    },
    CandidateStatus.UPDATE_EVALUATED: {
        CandidateStatus.SELECTION_EVALUATED,
        CandidateStatus.HELD,
        CandidateStatus.REJECTED,
    },
    CandidateStatus.SELECTION_EVALUATED: {
        CandidateStatus.RELEASE_EVALUATED,
        CandidateStatus.HELD,
        CandidateStatus.REJECTED,
    },
    CandidateStatus.RELEASE_EVALUATED: {
        CandidateStatus.SHIP_RECOMMENDED,
        CandidateStatus.HELD,
        CandidateStatus.REJECTED,
    },
    CandidateStatus.SHIP_RECOMMENDED: {
        CandidateStatus.SHIPPED,
        CandidateStatus.HELD,
    },
    CandidateStatus.SHIPPED: {CandidateStatus.ROLLED_BACK},
    CandidateStatus.HELD: set(),
    CandidateStatus.REJECTED: set(),
    CandidateStatus.ROLLED_BACK: set(),
}


class CandidateRegistry:
    def __init__(self, project_root: Path, checker: CandidateChecker) -> None:
        self.project_root = project_root.resolve()
        self.checker = checker

    def register(
        self,
        *,
        candidate_id: str,
        parent_snapshot_id: str,
        failure_bundle: FailureBundle,
        updater_name: str,
        updater_version: str,
        hypothesis: str,
        patch_path: Path,
        predicted_metric: str,
        predicted_direction: str,
        created_at: datetime,
    ) -> CandidateRecord:
        directory = self._candidate_dir(candidate_id)
        if directory.exists():
            raise CandidateStateError(f"candidate {candidate_id} already exists")
        check = self.checker.check(patch_path, budget=failure_bundle.budget)
        if check.disposition is CheckDisposition.REJECT:
            raise CandidateRejectedError(
                f"candidate rejected by {check.code.value}: {check.message}"
            )
        if check.risk_tier is None or not check.asset_families:
            raise CandidateStateError("candidate check did not resolve assets and risk")
        directory.mkdir(parents=True)
        stored_patch = directory / "candidate.patch"
        stored_patch.write_bytes(patch_path.read_bytes())
        if file_digest(stored_patch) != check.patch_digest:
            raise CandidateStateError("stored candidate patch digest mismatch")
        self._write_once(
            directory / "check.json",
            check.model_dump(mode="json"),
        )
        status = (
            CandidateStatus.CHECKED
            if check.disposition is CheckDisposition.PASS
            else CandidateStatus.HELD
        )
        record = CandidateRecord(
            schema_version="1.0",
            candidate_id=candidate_id,
            parent_snapshot_id=parent_snapshot_id,
            failure_bundle_digest=canonical_digest(failure_bundle),
            updater=UpdaterIdentity(name=updater_name, version=updater_version),
            hypothesis=hypothesis,
            asset_families=check.asset_families,
            risk_tier=check.risk_tier,
            patch_path=stored_patch.relative_to(self.project_root).as_posix(),
            patch_digest=check.patch_digest,
            changed_files=check.changed_files,
            predicted_effect=PredictedEffect(
                metric=EffectMetric(predicted_metric),
                direction=EffectDirection(predicted_direction),
            ),
            status=status,
            created_at=created_at,
        )
        self._append_event(
            directory,
            record,
            previous_status=None,
            actor=updater_name,
            evidence_refs=[
                f"failure_bundle:{record.failure_bundle_digest}",
                f"candidate_check:{check.code.value}",
            ],
            occurred_at=created_at,
        )
        return record

    def load(self, candidate_id: str) -> CandidateRecord:
        events = sorted((self._candidate_dir(candidate_id) / "events").glob("*.json"))
        if not events:
            raise CandidateStateError(f"candidate {candidate_id} is not registered")
        try:
            event = CandidateLifecycleEvent.model_validate_json(
                events[-1].read_text(encoding="utf-8")
            )
            return event.record
        except (OSError, ValueError) as exc:
            raise CandidateStateError(f"candidate {candidate_id} registry is corrupt") from exc

    def transition(
        self,
        candidate_id: str,
        next_status: CandidateStatus,
        *,
        actor: str = "agentloopgate-core",
        evidence_refs: list[str] | None = None,
        occurred_at: datetime | None = None,
    ) -> CandidateRecord:
        current = self.load(candidate_id)
        if next_status not in _TRANSITIONS[current.status]:
            raise CandidateStateError(
                f"invalid candidate transition {current.status.value} -> {next_status.value}"
            )
        updated = current.model_copy(update={"status": next_status})
        self._append_event(
            self._candidate_dir(candidate_id),
            updated,
            previous_status=current.status,
            actor=actor,
            evidence_refs=evidence_refs or [f"candidate:{candidate_id}:{next_status.value}"],
            occurred_at=occurred_at or datetime.now(UTC),
        )
        return updated

    def _candidate_dir(self, candidate_id: str) -> Path:
        if not _SAFE_ID.fullmatch(candidate_id):
            raise CandidateStateError("candidate id is unsafe")
        return self.project_root / "candidates" / candidate_id

    def _append_event(
        self,
        directory: Path,
        record: CandidateRecord,
        *,
        previous_status: CandidateStatus | None,
        actor: str,
        evidence_refs: list[str],
        occurred_at: datetime,
    ) -> None:
        events = directory / "events"
        events.mkdir(parents=True, exist_ok=True)
        ordinal = len(list(events.glob("*.json"))) + 1
        event = CandidateLifecycleEvent(
            ordinal=ordinal,
            previous_status=previous_status,
            next_status=record.status,
            actor=actor,
            evidence_refs=evidence_refs,
            occurred_at=occurred_at,
            record=record,
        )
        self._write_once(
            events / f"{ordinal:04d}.json",
            event.model_dump(mode="json"),
        )

    @staticmethod
    def _write_once(path: Path, payload: object) -> None:
        encoded = canonical_json_bytes(payload) + b"\n"
        if path.exists():
            try:
                existing = canonical_json_bytes(
                    json.loads(path.read_text(encoding="utf-8"))
                ) + b"\n"
            except (OSError, json.JSONDecodeError) as exc:
                raise CandidateStateError(
                    f"existing candidate artifact is corrupt: {path}"
                ) from exc
            if existing != encoded:
                raise CandidateStateError(f"candidate artifact conflict: {path}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
