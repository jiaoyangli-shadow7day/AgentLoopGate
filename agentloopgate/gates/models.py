"""Promotion-gate and dual-selector inputs."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from agentloopgate.schemas import (
    ArtifactId,
    DecisionRecord,
    GateName,
    NonEmpty,
    RiskTier,
)
from agentloopgate.schemas.models import StrictModel


class GateAssessment(StrictModel):
    schema_version: Literal["1.0"]
    candidate_id: ArtifactId
    baseline_snapshot_id: ArtifactId
    evaluation_integrity_complete: bool
    leakage_hits: int = Field(ge=0)
    mutates_trust_kernel: bool
    risk_tier: RiskTier
    release_critical_violations: int = Field(ge=0)
    id_stable_task_net: int
    ood_stable_task_net: int
    replay_stable_task_net: int
    catastrophic_regressions: int = Field(ge=0)
    reliability_complete: bool
    reliability_trials: int = Field(default=3, ge=1)
    stable_success_required: int = Field(default=3, ge=1)
    baseline_mean_cost: Decimal = Field(ge=0)
    candidate_mean_cost: Decimal = Field(ge=0)
    baseline_p50_latency_ms: Decimal = Field(ge=0)
    candidate_p50_latency_ms: Decimal = Field(ge=0)
    evidence_refs: dict[GateName, NonEmpty]

    @model_validator(mode="after")
    def evidence_is_complete(self) -> GateAssessment:
        if set(self.evidence_refs) != set(GateName):
            raise ValueError("evidence_refs must contain every gate")
        return self


class GateOutcome(StrictModel):
    schema_version: Literal["1.0"]
    record: DecisionRecord
    failed_gate: GateName | None
    reason: NonEmpty


class CandidateSelectionInput(StrictModel):
    candidate_id: ArtifactId
    native_score: Decimal | None
    native_rank: int | None = Field(default=None, ge=1)
    native_signal_ref: str | None = None
    evaluation_complete: bool
    stable_success_task_count: int = Field(ge=0)
    critical_violations: int = Field(ge=0)
    mean_cost: Decimal = Field(ge=0)
    p50_latency_ms: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def native_signal_is_unambiguous(self) -> CandidateSelectionInput:
        if (self.native_score is None) == (self.native_rank is None):
            raise ValueError("exactly one native score or native rank is required")
        if self.native_rank is not None and not self.native_signal_ref:
            raise ValueError("native rank requires its external signal reference")
        return self


class DualSelection(StrictModel):
    schema_version: Literal["1.0"]
    native_candidate_id: ArtifactId
    agentloopgate_candidate_id: ArtifactId
    ladder_digest: NonEmpty
