"""Promotion-gate and dual-selector inputs."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from agentloopgate.schemas import (
    ArtifactId,
    DecisionRecord,
    Digest,
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
    stable_task_outcomes: dict[ArtifactId, bool] | None = None
    whole_attempt_cost_usd: Decimal | None = Field(default=None, ge=0)
    task_attempt_count: int | None = Field(default=None, ge=1)
    retry_count: int | None = Field(default=None, ge=0)
    timeout_count: int | None = Field(default=None, ge=0)
    p95_latency_ms: Decimal | None = Field(default=None, ge=0)
    max_latency_ms: Decimal | None = Field(default=None, ge=0)
    operational_evidence_refs: list[NonEmpty] | None = None

    @model_validator(mode="after")
    def native_signal_is_unambiguous(self) -> CandidateSelectionInput:
        if (self.native_score is None) == (self.native_rank is None):
            raise ValueError("exactly one native score or native rank is required")
        if self.native_rank is not None and not self.native_signal_ref:
            raise ValueError("native rank requires its external signal reference")
        enhanced = (
            self.stable_task_outcomes,
            self.whole_attempt_cost_usd,
            self.task_attempt_count,
            self.retry_count,
            self.timeout_count,
            self.p95_latency_ms,
            self.max_latency_ms,
            self.operational_evidence_refs,
        )
        if any(item is not None for item in enhanced) and not all(
            item is not None for item in enhanced
        ):
            raise ValueError("enhanced selection evidence must be complete")
        if self.stable_task_outcomes is not None:
            if sum(self.stable_task_outcomes.values()) != self.stable_success_task_count:
                raise ValueError("stable outcomes conflict with stable success count")
            if not self.operational_evidence_refs:
                raise ValueError("enhanced selection requires evidence references")
            if self.task_attempt_count < len(self.stable_task_outcomes):
                raise ValueError("task attempt count cannot be smaller than task count")
            if self.retry_count > self.task_attempt_count - len(
                self.stable_task_outcomes
            ):
                raise ValueError("retry count conflicts with task attempt count")
            if not (
                self.p50_latency_ms <= self.p95_latency_ms <= self.max_latency_ms
            ):
                raise ValueError("selection latency quantiles are not monotonic")
        return self


class BaselineSelectionInput(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    snapshot_id: ArtifactId
    evaluation_complete: bool
    stable_success_task_count: int = Field(ge=0)
    stable_task_outcomes: dict[ArtifactId, bool] = Field(min_length=1)
    critical_violations: int = Field(ge=0)
    mean_cost: Decimal = Field(ge=0)
    whole_attempt_cost_usd: Decimal = Field(ge=0)
    task_attempt_count: int = Field(ge=1)
    retry_count: int = Field(ge=0)
    timeout_count: int = Field(ge=0)
    p50_latency_ms: Decimal = Field(ge=0)
    p95_latency_ms: Decimal = Field(ge=0)
    max_latency_ms: Decimal = Field(ge=0)
    operational_evidence_refs: list[NonEmpty] = Field(min_length=3)

    @model_validator(mode="after")
    def evidence_is_consistent(self) -> BaselineSelectionInput:
        if sum(self.stable_task_outcomes.values()) != self.stable_success_task_count:
            raise ValueError("baseline outcomes conflict with stable success count")
        if self.task_attempt_count < len(self.stable_task_outcomes):
            raise ValueError("baseline task attempt count is too small")
        if self.retry_count > self.task_attempt_count - len(
            self.stable_task_outcomes
        ):
            raise ValueError("baseline retry count conflicts with task attempts")
        if not self.p50_latency_ms <= self.p95_latency_ms <= self.max_latency_ms:
            raise ValueError("baseline latency quantiles are not monotonic")
        return self


class SelectionPolicy(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    correctness_policy: Literal[
        "strict_stable_gain_no_stable_regression"
    ] = "strict_stable_gain_no_stable_regression"
    whole_attempt_cost_ratio_max: Decimal = Field(gt=0)
    p95_latency_ratio_max: Decimal = Field(gt=0)
    max_retry_increase: int = Field(ge=0)
    max_timeout_increase: int = Field(ge=0)
    ranking_policy: Literal[
        "correctness_then_timeout_retry_tail_cost_v1"
    ] = "correctness_then_timeout_retry_tail_cost_v1"


class DualSelection(StrictModel):
    schema_version: Literal["1.0", "1.1"]
    native_candidate_id: ArtifactId
    agentloopgate_candidate_id: ArtifactId | None
    ladder_digest: NonEmpty
    agentloopgate_decision: Literal["SELECT", "HOLD"] | None = None
    decision_reason: NonEmpty | None = None
    baseline_snapshot_id: ArtifactId | None = None
    baseline_digest: Digest | None = None
    policy_digest: Digest | None = None
    governance_findings: dict[ArtifactId, list[NonEmpty]] | None = None

    @model_validator(mode="after")
    def decision_matches_schema(self) -> DualSelection:
        governed = (
            self.agentloopgate_decision,
            self.decision_reason,
            self.baseline_snapshot_id,
            self.baseline_digest,
            self.policy_digest,
            self.governance_findings,
        )
        if self.schema_version == "1.0":
            if self.agentloopgate_candidate_id is None:
                raise ValueError("legacy selection requires a governed candidate")
            if any(item is not None for item in governed):
                raise ValueError("legacy selection cannot contain abstention evidence")
            return self
        if any(item is None for item in governed):
            raise ValueError("selection 1.1 requires baseline, policy, and findings")
        if self.agentloopgate_decision == "SELECT":
            if self.agentloopgate_candidate_id is None:
                raise ValueError("SELECT requires a governed candidate")
        elif self.agentloopgate_candidate_id is not None:
            raise ValueError("HOLD cannot name a governed candidate")
        return self
