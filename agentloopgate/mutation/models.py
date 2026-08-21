"""Machine-readable harness assets, mutation policy, and check results."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from agentloopgate.schemas import ArtifactId, AssetFamily, Digest, NonEmpty, RiskTier
from agentloopgate.schemas.models import StrictModel


class AssetOperation(StrEnum):
    PROPOSE = "propose"
    PATCH = "patch"
    EVALUATE = "evaluate"
    ROLLBACK = "rollback"


class HarnessAsset(StrictModel):
    asset_id: ArtifactId
    family: AssetFamily
    path_patterns: list[NonEmpty] = Field(min_length=1)
    risk_tier: RiskTier
    allowed_operations: list[AssetOperation] = Field(min_length=1)
    rollback_unit: ArtifactId

    @model_validator(mode="after")
    def patterns_are_safe_and_operations_unique(self) -> HarnessAsset:
        for pattern in self.path_patterns:
            if pattern.startswith("/") or ".." in pattern.split("/"):
                raise ValueError("asset path patterns must be safe project-relative paths")
        if len(self.allowed_operations) != len(set(self.allowed_operations)):
            raise ValueError("asset allowed_operations must be unique")
        return self


class HarnessAssetManifest(StrictModel):
    schema_version: Literal["1.0"]
    assets: list[HarnessAsset] = Field(min_length=1)

    @model_validator(mode="after")
    def asset_ids_are_unique(self) -> HarnessAssetManifest:
        ids = [asset.asset_id for asset in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("asset ids must be unique")
        patterns = [pattern for asset in self.assets for pattern in asset.path_patterns]
        if len(patterns) != len(set(patterns)):
            raise ValueError("asset path patterns must be unique")
        return self


class MutationPolicy(StrictModel):
    schema_version: Literal["1.0"]
    max_files: int = Field(ge=1)
    max_changed_lines: int = Field(ge=1)
    auto_executable_risks: list[RiskTier] = Field(min_length=1)
    hold_risks: list[RiskTier] = Field(min_length=1)
    protected_paths: list[NonEmpty] = Field(min_length=1)
    trust_kernel_paths: list[NonEmpty] = Field(min_length=1)
    forbidden_content_patterns: list[NonEmpty] = Field(min_length=1)

    @model_validator(mode="after")
    def risk_and_paths_are_safe(self) -> MutationPolicy:
        if set(self.auto_executable_risks) & set(self.hold_risks):
            raise ValueError("risk tiers cannot be both auto-executable and held")
        if set(self.auto_executable_risks) | set(self.hold_risks) != set(RiskTier):
            raise ValueError("mutation policy must account for every risk tier")
        for pattern in self.protected_paths + self.trust_kernel_paths:
            if pattern.startswith("/") or ".." in pattern.split("/"):
                raise ValueError("policy paths must be safe project-relative patterns")
        return self


class TrustKernelSnapshot(StrictModel):
    schema_version: Literal["1.0"]
    files: dict[NonEmpty, Digest]
    trust_kernel_digest: Digest


class CheckDisposition(StrEnum):
    PASS = "pass"
    HOLD = "hold"
    REJECT = "reject"


class CandidateCheckCode(StrEnum):
    PASS = "PASS"
    HOLD_RISK_H = "HOLD_RISK_H"
    REJECT_MALFORMED_PATCH = "REJECT_MALFORMED_PATCH"
    REJECT_PROTECTED_PATH = "REJECT_PROTECTED_PATH"
    REJECT_UNREGISTERED_PATH = "REJECT_UNREGISTERED_PATH"
    REJECT_OPERATION = "REJECT_OPERATION"
    REJECT_LEAKAGE = "REJECT_LEAKAGE"
    REJECT_CHANGE_BUDGET = "REJECT_CHANGE_BUDGET"
    REJECT_TRUST_KERNEL_DRIFT = "REJECT_TRUST_KERNEL_DRIFT"


class CandidateCheckResult(StrictModel):
    schema_version: Literal["1.0"]
    disposition: CheckDisposition
    code: CandidateCheckCode
    message: NonEmpty
    patch_digest: Digest
    changed_files: list[NonEmpty]
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    changed_lines: int = Field(ge=0)
    asset_families: list[AssetFamily]
    risk_tier: RiskTier | None
    rollback_units: list[ArtifactId]
    auto_executable: bool

