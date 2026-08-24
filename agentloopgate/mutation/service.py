"""Unified-diff validation, leakage scanning, and trust-kernel checks."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

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
    added_by_file: dict[str, list[str]]
    deleted_by_file: dict[str, list[str]]


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
        semantic_error = self._runtime_capability_error(patch_path, parsed, assets)
        if semantic_error is not None:
            return self._result(
                CandidateCheckCode.REJECT_UNBOUND_CAPABILITY,
                semantic_error,
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
        parsed = parsed or ParsedPatch([], 0, 0, "", {}, {})
        assets = assets or []
        risk = (
            max((asset.risk_tier for asset in assets), key=_RISK_ORDER.__getitem__)
            if assets
            else None
        )
        return CandidateCheckResult(
            schema_version=(
                "1.1"
                if self.manifest.schema_version == "1.1"
                and self.policy.schema_version == "1.1"
                else "1.0"
            ),
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
            **(
                {
                    "semantic_tags": _semantic_tags(parsed),
                    "semantic_fingerprint": _semantic_fingerprint(
                        parsed,
                        assets,
                    ),
                }
                if self.manifest.schema_version == "1.1"
                and self.policy.schema_version == "1.1"
                else {}
            ),
        )

    def _runtime_capability_error(
        self,
        patch_path: Path,
        parsed: ParsedPatch,
        assets: list[HarnessAsset],
    ) -> str | None:
        guarded = {
            changed_file
            for changed_file, asset in zip(parsed.changed_files, assets, strict=True)
            if asset.semantic_validator == "runtime_capability_routing_v1"
        }
        if not guarded:
            return None
        with TemporaryDirectory(prefix="agentloopgate-candidate-check-") as temporary:
            staging = Path(temporary).resolve()
            for relative in parsed.changed_files:
                source = self.project_root / relative
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.is_file():
                    shutil.copy2(source, destination)
            check = subprocess.run(
                ["git", "apply", "--check", str(patch_path.resolve())],
                cwd=staging,
                capture_output=True,
                text=True,
            )
            if check.returncode != 0:
                return "candidate tool-routing patch cannot be applied to frozen source"
            applied = subprocess.run(
                ["git", "apply", str(patch_path.resolve())],
                cwd=staging,
                capture_output=True,
                text=True,
            )
            if applied.returncode != 0:
                return "candidate tool-routing patch cannot be materialized for validation"
            for relative in guarded:
                try:
                    prospective = yaml.safe_load(
                        (staging / relative).read_text(encoding="utf-8")
                    )
                except (OSError, yaml.YAMLError):
                    return "candidate tool routing is not readable YAML after patch"
                binding = (
                    prospective.get("capability_binding")
                    if isinstance(prospective, dict)
                    else None
                )
                if binding != {
                    "source": "runtime_tool_schema",
                    "reject_unknown_route_targets": True,
                }:
                    return (
                        "candidate tool routing is not exactly bound to the runtime "
                        "tool schema after patch"
                    )
                deleted = "\n".join(parsed.deleted_by_file.get(relative, []))
                if "capability_binding" in deleted or "runtime_tool_schema" in deleted:
                    return "candidate cannot remove the runtime capability binding"
                for line in parsed.added_by_file.get(relative, []):
                    if re.match(r"^\s*(?:-\s*)?capability\s*:", line):
                        return (
                            "static capability targets are not portable; use a runtime "
                            "capability_ref resolved against the current tool schema"
                        )
        return None

    @staticmethod
    def _parse_patch(path: Path) -> ParsedPatch:
        text = path.read_text(encoding="utf-8")
        changed_files: list[str] = []
        additions = 0
        deletions = 0
        added_lines: list[str] = []
        added_by_file: dict[str, list[str]] = {}
        deleted_by_file: dict[str, list[str]] = {}
        current_file: str | None = None
        for line in text.splitlines():
            match = _DIFF_HEADER.fullmatch(line)
            if match:
                old_path, new_path = match.groups()
                if old_path != new_path:
                    raise MutationConfigError("rename patches are not supported in P0")
                _validate_relative_path(new_path)
                changed_files.append(new_path)
                current_file = new_path
                added_by_file[current_file] = []
                deleted_by_file[current_file] = []
                continue
            if line.startswith("Binary files ") or line == "GIT binary patch":
                raise MutationConfigError("binary patches are not supported")
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
                added_lines.append(line[1:])
                if current_file is not None:
                    added_by_file[current_file].append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1
                if current_file is not None:
                    deleted_by_file[current_file].append(line[1:])
        if not changed_files:
            raise MutationConfigError("patch contains no diff --git file headers")
        if len(changed_files) != len(set(changed_files)):
            raise MutationConfigError("patch contains duplicate file sections")
        return ParsedPatch(
            changed_files=sorted(changed_files),
            additions=additions,
            deletions=deletions,
            added_text="\n".join(added_lines),
            added_by_file=added_by_file,
            deleted_by_file=deleted_by_file,
        )


def _semantic_tags(parsed: ParsedPatch) -> list[str]:
    text = parsed.added_text.lower().replace("_", "-")
    rules = {
        "read_after_write": r"(?:read-after-write|read back|read-back|re-read)",
        "terminal_state_verification": r"terminal state",
        "gated_success_claim": r"(?:success claim|claim completion|reporting completion)",
        "exact_capability_match": r"(?:exact match|exactly one registered capability)",
        "fail_closed_routing": r"(?:unmatched|unroutable|unregistered).{0,40}reject",
        "runtime_capability_binding": r"(?:runtime[-_ ]tool[-_ ]schema|capability-ref)",
    }
    return sorted(tag for tag, pattern in rules.items() if re.search(pattern, text))


def _semantic_fingerprint(
    parsed: ParsedPatch,
    assets: list[HarnessAsset],
) -> str:
    tags = _semantic_tags(parsed)
    normalized = [
        re.sub(r"\s+", " ", line.strip().lower())
        for line in parsed.added_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    behavior = tags if len(tags) >= 2 else normalized
    return canonical_digest(
        {
            "asset_families": sorted({asset.family.value for asset in assets}),
            "behavior": behavior,
        }
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
