"""Strict v1 data contracts shared by the CLI, adapters, and plugin bridge."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("datetime must include the UTC offset")
    return value.astimezone(UTC)


UtcDateTime = Annotated[datetime, AfterValidator(_require_utc)]
Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ArtifactId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"),
]
SchemaVersion = Literal["1.0"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Pool(StrEnum):
    PILOT = "pilot"
    UPDATE_SOURCE = "update_source"
    UPDATE_CHECK = "update_check"
    SELECTION = "selection"
    RELEASE_ID = "release_id"
    RELEASE_OOD = "release_ood"


class RuntimeHost(StrEnum):
    PYTHON_CLI = "python_cli"
    TAU3 = "tau3"
    DEEPSEEK_HARNESS = "deepseek_harness"
    FIXTURE = "fixture"


class PersistenceKind(StrEnum):
    TAU_RAW = "tau_raw"
    JSONL = "jsonl"
    SQLITE = "sqlite"
    MEMORY = "memory"
    UNKNOWN = "unknown"


class IngestMode(StrEnum):
    REFERENCE = "reference"
    MIRROR = "mirror"


class EvidenceStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    INCOMPLETE = "incomplete"
    UNAVAILABLE = "unavailable"


class RunSource(StrEnum):
    TAU3 = "tau3"
    DSH = "dsh"
    JSONL = "jsonl"
    FIXTURE = "fixture"


class RunValidity(StrEnum):
    VALID = "valid"
    INFRA_INVALID = "infra_invalid"


class ViolationCode(StrEnum):
    POLICY_VIOLATION = "policy_violation"
    UNSUPPORTED_ACTION = "unsupported_action"
    USER_CLAIM_OVERTRUST = "user_claim_overtrust"
    HIGH_RISK_STATE_CHANGE = "high_risk_state_change"


class FailureType(StrEnum):
    RETRIEVAL_MISS = "retrieval_miss"
    DOCUMENT_SELECTION_ERROR = "document_selection_error"
    CROSS_DOCUMENT_REASONING_ERROR = "cross_document_reasoning_error"
    POLICY_APPLICATION_ERROR = "policy_application_error"
    TOOL_DISCOVERY_ERROR = "tool_discovery_error"
    TOOL_SELECTION_ERROR = "tool_selection_error"
    TOOL_PARAMETER_ERROR = "tool_parameter_error"
    ACTION_ORDER_ERROR = "action_order_error"
    STATE_VERIFICATION_ERROR = "state_verification_error"
    RECOVERY_ERROR = "recovery_error"
    USER_CLAIM_OVERTRUST = "user_claim_overtrust"
    SPEC_OR_EVALUATOR_ISSUE = "spec_or_evaluator_issue"
    INFRA_FAILURE = "infra_failure"
    UNKNOWN = "unknown"


class AssetFamily(StrEnum):
    PROMPT_INSTRUCTION = "prompt_instruction"
    CONTEXT_MEMORY_SKILL = "context_memory_skill"
    RETRIEVAL_SEARCH_POLICY = "retrieval_search_policy"
    TOOL_CONTRACT_ROUTING = "tool_contract_routing"
    ORCHESTRATION_STATE = "orchestration_state"
    MIDDLEWARE_RUNTIME_CODE = "middleware_runtime_code"


class RiskTier(StrEnum):
    L = "L"
    M = "M"
    H = "H"


class CandidateStatus(StrEnum):
    DRAFT = "draft"
    REGISTERED = "registered"
    CHECKED = "checked"
    UPDATE_EVALUATED = "update_evaluated"
    SELECTION_EVALUATED = "selection_evaluated"
    RELEASE_EVALUATED = "release_evaluated"
    SHIP_RECOMMENDED = "ship_recommended"
    HELD = "held"
    REJECTED = "rejected"
    SHIPPED = "shipped"
    ROLLED_BACK = "rolled_back"


class DecisionValue(StrEnum):
    SHIP_RECOMMENDED = "SHIP_RECOMMENDED"
    HOLD = "HOLD"
    REJECT = "REJECT"


class GateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_EVALUATED = "not_evaluated"


class GateName(StrEnum):
    EVALUATION_INTEGRITY = "evaluation_integrity"
    LEAKAGE = "leakage"
    CRITICAL_VIOLATION = "critical_violation"
    ID_EFFECT = "id_effect"
    OOD_NONINFERIORITY = "ood_noninferiority"
    REPLAY = "replay"
    RELIABILITY = "reliability"
    COST = "cost"
    LATENCY = "latency"


class BenchmarkConfig(StrictModel):
    name: NonEmpty
    suite: NonEmpty
    commit: NonEmpty


class ReliabilityConfig(StrictModel):
    trials: int = Field(ge=1)
    stable_success_required: int = Field(ge=1)

    @model_validator(mode="after")
    def stable_success_fits_trials(self) -> ReliabilityConfig:
        if self.stable_success_required > self.trials:
            raise ValueError("stable_success_required cannot exceed trials")
        return self


class GateThresholds(StrictModel):
    leakage_hits_max: int = Field(ge=0)
    critical_violations_max: int = Field(ge=0)
    id_stable_task_net_min: int
    ood_stable_task_net_min: int
    replay_stable_task_net_min: int
    catastrophic_regressions_max: int = Field(ge=0)
    mean_cost_ratio_max: float = Field(gt=0)
    p50_latency_ratio_max: float = Field(gt=0)


class ObjectiveContract(StrictModel):
    contract_version: Literal["1.0"]
    project: Literal["AgentLoopGate"]
    primary_metric: Literal["reliable_policy_compliant_resolution"]
    benchmark: BenchmarkConfig
    reliability: ReliabilityConfig
    gates: GateThresholds
    decision_order: list[GateName]
    frozen_at: UtcDateTime | None
    contract_digest: Digest | None

    @model_validator(mode="after")
    def decision_order_is_complete_and_fixed(self) -> ObjectiveContract:
        expected = list(GateName)
        if self.decision_order != expected:
            raise ValueError("decision_order must contain every v1 gate in the frozen order")
        return self


class SourceTraceRef(StrictModel):
    schema_version: SchemaVersion
    source_trace_id: ArtifactId
    runtime_host: RuntimeHost
    source_locator: NonEmpty
    session_id_hash: Digest
    event_seq_start: int = Field(ge=0)
    event_seq_end: int = Field(ge=0)
    event_count: int = Field(ge=1)
    source_revision: NonEmpty
    persistence_kind: PersistenceKind
    ingest_mode: IngestMode
    mirror_path: str | None
    mirror_digest: Digest | None
    cursor_complete: bool
    evidence_status: EvidenceStatus
    created_at: UtcDateTime

    @model_validator(mode="after")
    def evidence_range_and_mode_are_consistent(self) -> SourceTraceRef:
        expected_count = self.event_seq_end - self.event_seq_start + 1
        if expected_count <= 0:
            raise ValueError("event sequence range must be increasing")
        if self.cursor_complete and self.event_count != expected_count:
            raise ValueError("complete cursor count must match the inclusive event sequence range")
        if not self.cursor_complete and self.event_count >= expected_count:
            raise ValueError("incomplete cursor must contain fewer events than its sequence span")
        if self.ingest_mode is IngestMode.MIRROR:
            if not self.mirror_path or not self.mirror_digest:
                raise ValueError("mirror mode requires mirror_path and mirror_digest")
        elif self.mirror_path is not None or self.mirror_digest is not None:
            raise ValueError("reference mode cannot claim mirror artifacts")
        if self.evidence_status is EvidenceStatus.VERIFIED and not self.cursor_complete:
            raise ValueError("verified evidence requires a complete cursor")
        return self


class EvidenceReceipt(StrictModel):
    schema_version: SchemaVersion
    receipt_id: ArtifactId
    source_trace_id: ArtifactId
    run_id: ArtifactId
    event_seq_start: int = Field(ge=0)
    event_seq_end: int = Field(ge=0)
    event_count: int = Field(ge=1)
    redaction_policy_digest: Digest
    normalized_record_digest: Digest
    collected_at: UtcDateTime
    error_count: int = Field(ge=0)

    @model_validator(mode="after")
    def event_count_matches_range(self) -> EvidenceReceipt:
        if self.event_count != self.event_seq_end - self.event_seq_start + 1:
            raise ValueError("event_count must match the inclusive event sequence range")
        return self


class RunRecord(StrictModel):
    schema_version: SchemaVersion
    run_id: ArtifactId
    attempt_id: ArtifactId
    task_id: ArtifactId
    pool: Pool
    snapshot_id: ArtifactId
    candidate_id: ArtifactId | None
    source: RunSource
    runtime_host: RuntimeHost
    runtime_version: NonEmpty
    runtime_profile: str | None = None
    composition_digest: Digest | None = None
    model_id: NonEmpty
    benchmark_commit: NonEmpty
    objective_digest: Digest
    split_digest: Digest
    initial_state_digest: Digest
    terminal_state_digest: Digest
    trial_index: int = Field(ge=1)
    run_validity: RunValidity
    success: bool | None
    critical_violations: list[ViolationCode]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    cost: Decimal | None = Field(default=None, ge=0)
    source_trace_ref: ArtifactId
    evidence_receipt_ref: ArtifactId
    created_at: UtcDateTime

    @model_validator(mode="after")
    def runtime_and_validity_are_consistent(self) -> RunRecord:
        if self.source is RunSource.DSH and (
            not self.runtime_profile or not self.composition_digest
        ):
            raise ValueError("dsh runs require runtime_profile and composition_digest")
        if self.run_validity is RunValidity.VALID and self.success is None:
            raise ValueError("valid runs require a success value")
        if self.run_validity is RunValidity.VALID and self.cost is None:
            raise ValueError("valid runs require exact cost evidence")
        if self.run_validity is RunValidity.INFRA_INVALID and self.success is not None:
            raise ValueError("infra_invalid runs cannot be scored as success or failure")
        return self


class PilotEvidenceJoin(StrictModel):
    """Auditable join between one DSH model session and one τ³ outcome."""

    schema_version: SchemaVersion
    join_id: ArtifactId
    task_id: ArtifactId
    trial_index: int = Field(ge=1)
    dsh_run_id: ArtifactId
    tau_run_id: ArtifactId
    dsh_source_trace_ref: ArtifactId
    dsh_evidence_receipt_ref: ArtifactId
    tau_source_trace_ref: ArtifactId
    tau_evidence_receipt_ref: ArtifactId
    session_id_hash: Digest
    outcome_success: bool | None
    evidence_digest: Digest
    created_at: UtcDateTime

    @model_validator(mode="after")
    def sides_are_distinct(self) -> PilotEvidenceJoin:
        if self.dsh_run_id == self.tau_run_id:
            raise ValueError("DSH and τ³ run ids must be distinct")
        if self.dsh_source_trace_ref == self.tau_source_trace_ref:
            raise ValueError("DSH and τ³ source trace references must be distinct")
        return self


class ChangeBudget(StrictModel):
    max_files: int = Field(ge=1)
    max_changed_lines: int = Field(ge=1)


class ProtectedField(StrEnum):
    OBJECTIVE = "objective"
    GRADER = "grader"
    EVALUATOR = "evaluator"
    SPLIT = "split"
    GATE = "gate"
    FINAL_ACCESS = "final_access"


class FailureBundle(StrictModel):
    schema_version: SchemaVersion
    failure_bundle_id: ArtifactId
    snapshot_id: ArtifactId
    source_pool: Literal[Pool.UPDATE_SOURCE]
    failure_type: FailureType
    affected_run_ids: list[ArtifactId] = Field(min_length=1)
    evidence_refs: list[NonEmpty] = Field(min_length=1)
    redacted_summary: NonEmpty
    target_asset_families: list[AssetFamily] = Field(min_length=1)
    expected_behavior_change: NonEmpty
    must_not_change: list[ProtectedField] = Field(min_length=1)
    budget: ChangeBudget


class UpdaterIdentity(StrictModel):
    name: NonEmpty
    version: NonEmpty


class EffectMetric(StrEnum):
    STABLE_SUCCESS_TASK_COUNT = "stable_success_task_count"
    CRITICAL_VIOLATIONS = "critical_violations"
    MEAN_COST = "mean_cost"
    P50_LATENCY = "p50_latency"


class EffectDirection(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"
    NONINFERIOR = "noninferior"


class PredictedEffect(StrictModel):
    metric: EffectMetric
    direction: EffectDirection


class CandidateRecord(StrictModel):
    schema_version: SchemaVersion
    candidate_id: ArtifactId
    parent_snapshot_id: ArtifactId
    failure_bundle_digest: Digest
    updater: UpdaterIdentity
    hypothesis: NonEmpty
    asset_families: list[AssetFamily] = Field(min_length=1)
    risk_tier: RiskTier
    patch_path: NonEmpty
    patch_digest: Digest
    changed_files: list[NonEmpty] = Field(min_length=1)
    predicted_effect: PredictedEffect
    status: CandidateStatus
    created_at: UtcDateTime


class SnapshotRuntime(StrictModel):
    host: RuntimeHost
    version: NonEmpty


class SnapshotManifest(StrictModel):
    schema_version: SchemaVersion
    snapshot_id: ArtifactId
    parent_snapshot_id: ArtifactId | None
    candidate_id: ArtifactId | None
    model_id: NonEmpty
    objective_digest: Digest
    split_digest: Digest
    asset_manifest_digest: Digest
    code_revision: NonEmpty
    harness_files: dict[NonEmpty, Digest]
    runtime: SnapshotRuntime
    created_at: UtcDateTime


class GateEvidence(StrictModel):
    name: GateName
    status: GateStatus
    evidence_ref: NonEmpty


class HumanApproval(StrictModel):
    approval_id: NonEmpty
    actor: NonEmpty
    approved_at: UtcDateTime


class DecisionRecord(StrictModel):
    schema_version: SchemaVersion
    decision_id: ArtifactId
    candidate_id: ArtifactId
    baseline_snapshot_id: ArtifactId
    decision: DecisionValue
    gates: list[GateEvidence] = Field(min_length=1)
    summary: NonEmpty
    human_approval: HumanApproval | None
    created_at: UtcDateTime
