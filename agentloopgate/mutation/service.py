"""Unified-diff validation, leakage scanning, and trust-kernel checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml
from pydantic import ValidationError

from agentloopgate.contracts import canonical_digest, file_digest
from agentloopgate.mutation.models import (
    AssetOperation,
    CandidateCheckCode,
    CandidateCheckResult,
    CheckDisposition,
    HarnessAsset,
    HarnessAssetManifest,
    MutationPolicy,
    TrustKernelSnapshot,
)
from agentloopgate.schemas import RiskTier
from agentloopgate.schemas.models import ChangeBudget

_RISK_ORDER = {RiskTier.L: 0, RiskTier.M: 1, RiskTier.H: 2}
_DIFF_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")


class MutationConfigError(ValueError):
    """Mutation configuration or a patch artifact is malformed."""


@dataclass(frozen=True)
class ParsedPatch:
    changed_files: list[str]
    additions: int
    deletions: int
    added_text: str


def load_asset_manifest(path: Path) -> HarnessAssetManifest:
    try:
        return HarnessAssetManifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, ValidationError, yaml.YAMLError) as exc:
        raise MutationConfigError(f"invalid harness asset manifest: {exc}") from exc


def load_mutation_policy(path: Path) -> MutationPolicy:
    try:
        return MutationPolicy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, ValidationError, yaml.YAMLError) as exc:
        raise MutationConfigError(f"invalid mutation policy: {exc}") from exc


def freeze_trust_kernel(project_root: Path, policy: MutationPolicy) -> TrustKernelSnapshot:
    root = project_root.resolve()
    files: dict[str, str] = {}
    for pattern in policy.trust_kernel_paths:
        matches = _matching_files(root, pattern)
        if not _has_glob(pattern) and not matches:
            raise MutationConfigError(f"trust-kernel file is missing: {pattern}")
        for path in matches:
            if path.is_symlink():
                raise MutationConfigError(f"trust-kernel file cannot be a symlink: {path}")
            relative = path.relative_to(root).as_posix()
            files[relative] = file_digest(path)
    if not files:
        raise MutationConfigError("trust kernel did not resolve to any files")
    ordered = dict(sorted(files.items()))
    return TrustKernelSnapshot(
        schema_version="1.0",
        files=ordered,
        trust_kernel_digest=canonical_digest(ordered),
    )


class CandidateChecker:
    def __init__(
        self,
        project_root: Path,
        manifest: HarnessAssetManifest,
        policy: MutationPolicy,
        trust_kernel: TrustKernelSnapshot,
    ) -> None:
        self.project_root = project_root.resolve()
        self.manifest = manifest
        self.policy = policy
        self.trust_kernel = trust_kernel
        self._leakage_patterns = [
            re.compile(pattern) for pattern in policy.forbidden_content_patterns
        ]

    def check(
        self,
        patch_path: Path,
        *,
        budget: ChangeBudget | None = None,
    ) -> CandidateCheckResult:
        digest = file_digest(patch_path)
        try:
            parsed = self._parse_patch(patch_path)
        except (OSError, MutationConfigError) as exc:
            return self._result(
                CandidateCheckCode.REJECT_MALFORMED_PATCH,
                str(exc),
                digest,
            )
        if not self._trust_kernel_matches():
            return self._result(
                CandidateCheckCode.REJECT_TRUST_KERNEL_DRIFT,
                "governance trust-kernel files drifted from the frozen digest",
                digest,
                parsed=parsed,
            )
        protected = [
            item
            for item in parsed.changed_files
            if any(_path_matches(item, pattern) for pattern in self.policy.protected_paths)
        ]
        if protected:
            return self._result(
                CandidateCheckCode.REJECT_PROTECTED_PATH,
                f"patch touches protected path: {protected[0]}",
                digest,
                parsed=parsed,
            )
        assets: list[HarnessAsset] = []
        for changed_file in parsed.changed_files:
            matches = [
                asset
                for asset in self.manifest.assets
                if any(_path_matches(changed_file, pattern) for pattern in asset.path_patterns)
            ]
            if len(matches) != 1:
                return self._result(
                    CandidateCheckCode.REJECT_UNREGISTERED_PATH,
                    f"path must match exactly one registered asset: {changed_file}",
                    digest,
                    parsed=parsed,
                )
            assets.append(matches[0])
        if any(
            AssetOperation.PATCH not in asset.allowed_operations
            and not (
                asset.risk_tier is RiskTier.H
                and AssetOperation.PROPOSE in asset.allowed_operations
            )
            for asset in assets
        ):
            return self._result(
                CandidateCheckCode.REJECT_OPERATION,
                "registered asset does not permit patch operations",
                digest,
                parsed=parsed,
                assets=assets,
            )
        if any(pattern.search(parsed.added_text) for pattern in self._leakage_patterns):
            return self._result(
                CandidateCheckCode.REJECT_LEAKAGE,
                "patch contains a forbidden evaluation or secret feature",
                digest,
                parsed=parsed,
                assets=assets,
            )
        effective_budget = budget or ChangeBudget(
            max_files=self.policy.max_files,
            max_changed_lines=self.policy.max_changed_lines,
        )
        max_files = min(self.policy.max_files, effective_budget.max_files)
        max_lines = min(self.policy.max_changed_lines, effective_budget.max_changed_lines)
        if len(parsed.changed_files) > max_files or (
            parsed.additions + parsed.deletions > max_lines
        ):
            return self._result(
                CandidateCheckCode.REJECT_CHANGE_BUDGET,
                f"patch exceeds the {max_files}-file/{max_lines}-line change budget",
                digest,
                parsed=parsed,
                assets=assets,
            )
        risk = max((asset.risk_tier for asset in assets), key=_RISK_ORDER.__getitem__)
        if risk in self.policy.hold_risks:
            return self._result(
                CandidateCheckCode.HOLD_RISK_H,
                "Risk-H proposals are recordable but not executable in P0",
                digest,
                disposition=CheckDisposition.HOLD,
                parsed=parsed,
                assets=assets,
            )
        return self._result(
            CandidateCheckCode.PASS,
            "patch is within registered L/M assets and frozen mutation policy",
            digest,
            disposition=CheckDisposition.PASS,
            parsed=parsed,
            assets=assets,
        )

    def _trust_kernel_matches(self) -> bool:
        try:
            current = {
                relative: file_digest(self.project_root / relative)
                for relative in self.trust_kernel.files
            }
        except OSError:
            return False
        return (
            current == self.trust_kernel.files
            and canonical_digest(dict(sorted(current.items())))
            == self.trust_kernel.trust_kernel_digest
        )

    def _result(
        self,
        code: CandidateCheckCode,
        message: str,
        patch_digest: str,
        *,
        disposition: CheckDisposition = CheckDisposition.REJECT,
        parsed: ParsedPatch | None = None,
        assets: list[HarnessAsset] | None = None,
    ) -> CandidateCheckResult:
        parsed = parsed or ParsedPatch([], 0, 0, "")
        assets = assets or []
        risk = (
            max((asset.risk_tier for asset in assets), key=_RISK_ORDER.__getitem__)
            if assets
            else None
        )
        return CandidateCheckResult(
            schema_version="1.0",
            disposition=disposition,
            code=code,
            message=message,
            patch_digest=patch_digest,
            changed_files=sorted(parsed.changed_files),
            additions=parsed.additions,
            deletions=parsed.deletions,
            changed_lines=parsed.additions + parsed.deletions,
            asset_families=sorted(
                {asset.family for asset in assets},
                key=lambda family: family.value,
            ),
            risk_tier=risk,
            rollback_units=sorted({asset.rollback_unit for asset in assets}),
            auto_executable=(
                disposition is CheckDisposition.PASS
                and risk is not None
                and risk in self.policy.auto_executable_risks
            ),
        )

    @staticmethod
    def _parse_patch(path: Path) -> ParsedPatch:
        text = path.read_text(encoding="utf-8")
        changed_files: list[str] = []
        additions = 0
        deletions = 0
        added_lines: list[str] = []
        for line in text.splitlines():
            match = _DIFF_HEADER.fullmatch(line)
            if match:
                old_path, new_path = match.groups()
                if old_path != new_path:
                    raise MutationConfigError("rename patches are not supported in P0")
                _validate_relative_path(new_path)
                changed_files.append(new_path)
                continue
            if line.startswith("Binary files ") or line == "GIT binary patch":
                raise MutationConfigError("binary patches are not supported")
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
                added_lines.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1
        if not changed_files:
            raise MutationConfigError("patch contains no diff --git file headers")
        if len(changed_files) != len(set(changed_files)):
            raise MutationConfigError("patch contains duplicate file sections")
        return ParsedPatch(
            changed_files=sorted(changed_files),
            additions=additions,
            deletions=deletions,
            added_text="\n".join(added_lines),
        )


def _validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        raise MutationConfigError("patch path must be a safe project-relative path")


def _path_matches(path: str, pattern: str) -> bool:
    _validate_relative_path(path)
    return PurePosixPath(path).match(pattern)


def _has_glob(pattern: str) -> bool:
    return any(character in pattern for character in "*?[")


def _matching_files(root: Path, pattern: str) -> list[Path]:
    _validate_relative_path(pattern.replace("**", "placeholder").replace("*", "x"))
    if pattern.endswith("/**"):
        base = root / pattern.removesuffix("/**")
        return sorted(path for path in base.rglob("*") if path.is_file()) if base.is_dir() else []
    if _has_glob(pattern):
        return sorted(path for path in root.glob(pattern) if path.is_file())
    path = root / pattern
    return [path] if path.is_file() else []
