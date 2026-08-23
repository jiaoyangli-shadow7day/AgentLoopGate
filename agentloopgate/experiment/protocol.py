"""Frozen, content-addressed execution protocol for formal experiments."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator

from agentloopgate.contracts import canonical_digest
from agentloopgate.schemas import ArtifactId, Digest
from agentloopgate.schemas.models import NonEmpty, StrictModel, UtcDateTime


class FormalExecutionProtocol(StrictModel):
    """Every runtime choice that can change formal evidence or its denominator."""

    schema_version: Literal[
        "1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "1.9"
    ]
    protocol_id: ArtifactId
    experiment_id: ArtifactId
    objective_digest: Digest
    split_digest: Digest
    benchmark_commit: NonEmpty
    agent_model: NonEmpty
    user_model: NonEmpty
    pricing_digest: Digest
    max_concurrency: Literal[1]
    max_retries: Literal[1]
    retry_delay_seconds: Decimal = Field(ge=0)
    turn_timeout_seconds: int = Field(ge=1)
    benchmark_seed: int | None = None
    max_steps: int | None = Field(default=None, ge=1)
    max_errors: int | None = Field(default=None, ge=1)
    simulation_timeout_seconds: int | None = Field(default=None, ge=1)
    agent_temperature: Decimal | None = Field(default=None, ge=0)
    user_temperature: Decimal | None = Field(default=None, ge=0)
    user_model_max_retries: int | None = Field(default=None, ge=0)
    dsh_provider_max_retries: int | None = Field(default=None, ge=0)
    dsh_provider_retry_delay_ms: int | None = Field(default=None, ge=1)
    agent_max_output_tokens: int | None = Field(default=None, ge=1)
    dsh_tau3_protocol_version: Literal["dsh-tau3/1.1"] | None = None
    reply_normalization_policy: Literal[
        "bounded_allow_list_v3_plain_content_and_flattened_arguments",
        "bounded_allow_list_v4_redundant_allow_listed_name",
        "bounded_allow_list_v5_missing_name_and_discoverable_wrapper_alias",
    ] | None = None
    runner_failure_usage_policy: Literal["recover_verified_envelope"] | None = None
    execution_calibration_artifact: NonEmpty | None = None
    execution_calibration_digest: Digest | None = None
    global_task_attempt_limit: int | None = Field(default=None, ge=1)
    resume_retry_budget_policy: Literal["global_task_position_attempt_cap"] | None = None
    network_route_policy: Literal["direct_no_proxy"] | None = None
    user_failure_usage_policy: Literal["append_only_model_call_ledger"] | None = None
    cost_gate_scope: Literal["valid_runs_exact_whole_attempt_reported"] | None = None
    dsh_stream_idle_timeout_ms: int | None = Field(default=None, ge=1)
    empty_final_repair_policy: Literal[
        "bounded_same_session_final_only_v1"
    ] | None = None
    empty_final_repair_limit: Literal[1] | None = None
    user_empty_final_repair_policy: Literal[
        "bounded_same_call_context_final_only_v1"
    ] | None = None
    user_empty_final_repair_limit: Literal[1] | None = None
    updater_sandbox_output_policy: Literal[
        "attempt_local_runtime_only_v1"
    ] | None = None
    successor_integrity_calibration_artifact: NonEmpty | None = None
    successor_integrity_calibration_digest: Digest | None = None
    reply_lineage_calibration_artifact: NonEmpty | None = None
    reply_lineage_calibration_digest: Digest | None = None
    task_attempt_ledger_schema_version: Literal["1.1"] | None = None
    model_usage_ledger_schema_version: Literal["1.2"] | None = None
    task_attempt_session_binding_policy: Literal[
        "append_before_first_agent_call_v1"
    ] | None = None
    model_call_task_identity_policy: Literal[
        "direct_task_trial_seed_attempt_v1"
    ] | None = None
    cost_lineage_calibration_artifact: NonEmpty | None = None
    cost_lineage_calibration_digest: Digest | None = None
    cost_authority_policy: Literal[
        "verified_tokens_times_frozen_prices_v1"
    ] | None = None
    valid_cost_lineage_policy: Literal[
        "direct_final_task_attempt_calls_v1"
    ] | None = None
    raw_cost_evidence_policy: Literal["comparison_only_v1"] | None = None
    positive_token_zero_cost_policy: Literal[
        "reject_positive_frozen_contribution_v1"
    ] | None = None
    cost_gate_input_policy: Literal[
        "direct_valid_agent_plus_user_mean_v1"
    ] | None = None
    evaluator_conflict_policy: Literal[
        "all_expected_actions_matched_db_mismatch_hold_v1"
    ] | None = None
    evaluator_correction_policy: Literal[
        "versioned_overlay_symmetric_affected_rerun_v1"
    ] | None = None
    evaluator_overlay_artifact: NonEmpty | None = None
    evaluator_overlay_digest: Digest | None = None
    eval_incident_artifact: NonEmpty | None = None
    eval_incident_digest: Digest | None = None
    evaluator_correction_calibration_artifact: NonEmpty | None = None
    evaluator_correction_calibration_digest: Digest | None = None
    updater_max_retries: int | None = Field(default=None, ge=0)
    updater_retry_delay_seconds: Decimal | None = Field(default=None, ge=0)
    updater_timeout_seconds: int | None = Field(default=None, ge=1)
    updater_max_iterations: int | None = Field(default=None, ge=1)
    updater_max_output_tokens: int | None = Field(default=None, ge=1)
    updater_temperature: Decimal | None = Field(default=None, ge=0)
    updater_proposal_budget: int | None = Field(default=None, ge=1)
    resume: Literal[True]
    timezone: Literal["UTC"]
    valid_cost_policy: Literal["exact_required"]
    infra_invalid_cost_policy: Literal["null_excluded"]
    latency_policy: Literal["retained_duration_plus_trace_recovery"]
    status: Literal["frozen"]
    frozen_at: UtcDateTime
    protocol_digest: Digest

    @model_validator(mode="after")
    def versioned_runtime_surface_is_complete(self) -> FormalExecutionProtocol:
        version_1_1 = (
            "benchmark_seed",
            "max_steps",
            "max_errors",
            "simulation_timeout_seconds",
            "agent_temperature",
            "user_temperature",
            "user_model_max_retries",
            "dsh_provider_max_retries",
            "dsh_provider_retry_delay_ms",
            "agent_max_output_tokens",
            "updater_max_retries",
            "updater_retry_delay_seconds",
            "updater_timeout_seconds",
            "updater_max_iterations",
            "updater_max_output_tokens",
            "updater_temperature",
            "updater_proposal_budget",
        )
        version_1_2 = (
            "dsh_tau3_protocol_version",
            "reply_normalization_policy",
            "runner_failure_usage_policy",
            "execution_calibration_artifact",
            "execution_calibration_digest",
        )
        version_1_3 = (
            "global_task_attempt_limit",
            "resume_retry_budget_policy",
            "network_route_policy",
            "user_failure_usage_policy",
            "cost_gate_scope",
        )
        version_1_4 = (
            "dsh_stream_idle_timeout_ms",
            "empty_final_repair_policy",
            "empty_final_repair_limit",
        )
        version_1_5 = (
            "reply_lineage_calibration_artifact",
            "reply_lineage_calibration_digest",
            "task_attempt_ledger_schema_version",
            "model_usage_ledger_schema_version",
            "task_attempt_session_binding_policy",
            "model_call_task_identity_policy",
        )
        version_1_6 = (
            "cost_lineage_calibration_artifact",
            "cost_lineage_calibration_digest",
            "cost_authority_policy",
            "valid_cost_lineage_policy",
            "raw_cost_evidence_policy",
            "positive_token_zero_cost_policy",
        )
        version_1_7 = ("cost_gate_input_policy",)
        version_1_8 = (
            "evaluator_conflict_policy",
            "evaluator_correction_policy",
            "evaluator_overlay_artifact",
            "evaluator_overlay_digest",
            "eval_incident_artifact",
            "eval_incident_digest",
            "evaluator_correction_calibration_artifact",
            "evaluator_correction_calibration_digest",
        )
        version_1_9 = (
            "user_empty_final_repair_policy",
            "user_empty_final_repair_limit",
            "updater_sandbox_output_policy",
            "successor_integrity_calibration_artifact",
            "successor_integrity_calibration_digest",
        )
        runtime_present = [getattr(self, field) is not None for field in version_1_1]
        compatibility_present = [
            getattr(self, field) is not None for field in version_1_2
        ]
        recovery_present = [getattr(self, field) is not None for field in version_1_3]
        integrity_present = [getattr(self, field) is not None for field in version_1_4]
        lineage_present = [getattr(self, field) is not None for field in version_1_5]
        cost_present = [getattr(self, field) is not None for field in version_1_6]
        gate_cost_present = [getattr(self, field) is not None for field in version_1_7]
        evaluator_present = [getattr(self, field) is not None for field in version_1_8]
        user_empty_final_present = [
            getattr(self, field) is not None for field in version_1_9
        ]
        if self.schema_version in {
            "1.2",
            "1.3",
            "1.4",
            "1.5",
            "1.6",
            "1.7",
            "1.8",
            "1.9",
        } and not (
            all(runtime_present) and all(compatibility_present)
        ):
            raise ValueError(
                "protocol 1.2+ requires runtime pins and DSH compatibility evidence"
            )
        if self.schema_version in {
            "1.3",
            "1.4",
            "1.5",
            "1.6",
            "1.7",
            "1.8",
            "1.9",
        } and not all(recovery_present):
            raise ValueError(
                "protocol 1.3+ requires global resume, route, user usage, and "
                "cost-gate pins"
            )
        if self.schema_version not in {
            "1.3",
            "1.4",
            "1.5",
            "1.6",
            "1.7",
            "1.8",
            "1.9",
        } and any(recovery_present):
            raise ValueError(
                "only protocol 1.3+ can contain recovery and cost-gate pins"
            )
        if self.schema_version in {"1.4", "1.5", "1.6", "1.7", "1.8", "1.9"}:
            if not all(integrity_present):
                raise ValueError(
                    "protocol 1.4+ requires DSH idle-timeout and bounded empty-final "
                    "repair pins"
                )
            if self.turn_timeout_seconds * 1000 <= self.dsh_stream_idle_timeout_ms:
                raise ValueError(
                    "protocol 1.4+ outer turn timeout must exceed the DSH stream idle "
                    "timeout so DSH can persist its native termination evidence"
                )
        elif any(integrity_present):
            raise ValueError("only protocol 1.4+ can contain R6 integrity pins")
        if self.schema_version in {"1.5", "1.6", "1.7", "1.8", "1.9"}:
            if not all(lineage_present):
                raise ValueError(
                    "protocol 1.5 requires reply-lineage calibration and direct "
                    "task/session evidence pins"
                )
            if self.reply_normalization_policy != (
                "bounded_allow_list_v5_missing_name_and_discoverable_wrapper_alias"
            ):
                raise ValueError("protocol 1.5 requires Reply Policy v5")
        elif any(lineage_present):
            raise ValueError("only protocol 1.5 can contain R7 lineage pins")
        if self.schema_version in {"1.6", "1.7", "1.8", "1.9"}:
            if not all(cost_present):
                raise ValueError(
                    "protocol 1.6 requires frozen-price direct cost-lineage pins"
                )
        elif any(cost_present):
            raise ValueError("only protocol 1.6+ can contain direct cost-authority pins")
        if self.schema_version in {"1.7", "1.8", "1.9"}:
            if not all(gate_cost_present):
                raise ValueError(
                    "protocol 1.7+ requires a direct Agent+User Cost Gate input pin"
                )
        elif any(gate_cost_present):
            raise ValueError("only protocol 1.7+ can contain the Cost Gate input pin")
        if self.schema_version in {"1.8", "1.9"}:
            if not all(evaluator_present):
                raise ValueError(
                    "protocol 1.8 requires evaluator-conflict, incident, and overlay pins"
                )
        elif any(evaluator_present):
            raise ValueError("only protocol 1.8+ can contain evaluator correction pins")
        if self.schema_version == "1.9":
            if not all(user_empty_final_present):
                raise ValueError(
                    "protocol 1.9 requires bounded User Simulator empty-final repair "
                    "and attempt-local Updater sandbox output pins"
                )
        elif any(user_empty_final_present):
            raise ValueError(
                "only protocol 1.9+ can contain User Simulator empty-final repair pins"
            )
        if self.schema_version == "1.1" and not all(runtime_present):
            raise ValueError("protocol 1.1 requires every benchmark and updater runtime pin")
        if self.schema_version == "1.1" and any(compatibility_present):
            raise ValueError("protocol 1.1 cannot contain protocol 1.2 compatibility pins")
        if self.schema_version == "1.0" and any(
            [
                *runtime_present,
                *compatibility_present,
                *recovery_present,
                *integrity_present,
                *lineage_present,
                *cost_present,
                *gate_cost_present,
                *evaluator_present,
                *user_empty_final_present,
            ]
        ):
            raise ValueError("protocol 1.0 cannot contain protocol 1.1/1.2 pins")
        return self


class ReplyLineageCalibration(StrictModel):
    """Fail-closed no-model evidence for one reply and lineage protocol revision."""

    schema_version: Literal["1.0"]
    artifact_id: ArtifactId
    source_experiment_id: ArtifactId
    source_diagnosis_artifact: NonEmpty
    source_diagnosis_digest: Digest
    contains_raw_customer_data: Literal[False]
    reply_normalization_policy: Literal[
        "bounded_allow_list_v5_missing_name_and_discoverable_wrapper_alias"
    ]
    task_attempt_ledger_schema_version: Literal["1.1"]
    model_usage_ledger_schema_version: Literal["1.2"]
    task_attempt_session_binding_policy: Literal[
        "append_before_first_agent_call_v1"
    ]
    model_call_task_identity_policy: Literal[
        "direct_task_trial_seed_attempt_v1"
    ]
    accepted_reply_shapes: list[NonEmpty] = Field(min_length=2)
    rejected_reply_shapes: list[NonEmpty] = Field(min_length=5)
    lineage_assertions: list[NonEmpty] = Field(min_length=4)
    runtime_bindings: dict[NonEmpty, Digest] = Field(min_length=5)
    no_model_acceptance: dict[NonEmpty, Any]
    limitations: list[NonEmpty] = Field(min_length=1)
    artifact_digest: Digest

    @model_validator(mode="after")
    def acceptance_is_publication_grade(self) -> ReplyLineageCalibration:
        acceptance = self.no_model_acceptance
        if acceptance.get("status") != "passed":
            raise ValueError("reply-lineage calibration requires passed acceptance")
        if acceptance.get("external_model_calls") != 0:
            raise ValueError("reply-lineage calibration must be no-model")
        if acceptance.get("known_model_cost_usd") != "0":
            raise ValueError("no-model calibration requires zero known model cost")
        attempts = acceptance.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise ValueError("reply-lineage calibration requires recorded attempts")
        if not any(
            isinstance(attempt, dict)
            and attempt.get("scope") == "full_clean_room"
            and attempt.get("status") == "passed"
            for attempt in attempts
        ):
            raise ValueError("reply-lineage calibration requires a passed clean-room attempt")
        return self


class CostLineageCalibration(StrictModel):
    """No-model evidence for frozen-price, direct-lineage cost authority."""

    schema_version: Literal["1.0", "1.1", "1.2"]
    artifact_id: ArtifactId
    source_experiment_id: ArtifactId
    source_incident_artifact: NonEmpty
    source_incident_digest: Digest
    contains_raw_customer_data: Literal[False]
    pricing_digest: Digest
    cost_authority_policy: Literal["verified_tokens_times_frozen_prices_v1"]
    valid_cost_lineage_policy: Literal["direct_final_task_attempt_calls_v1"]
    raw_cost_evidence_policy: Literal["comparison_only_v1"]
    positive_token_zero_cost_policy: Literal[
        "reject_positive_frozen_contribution_v1"
    ]
    cost_gate_input_policy: Literal[
        "direct_valid_agent_plus_user_mean_v1"
    ] | None = None
    assertions: list[NonEmpty] = Field(min_length=5)
    runtime_bindings: dict[NonEmpty, Digest] = Field(min_length=4)
    no_model_acceptance: dict[NonEmpty, Any]
    limitations: list[NonEmpty] = Field(min_length=1)
    artifact_digest: Digest

    @model_validator(mode="after")
    def acceptance_is_publication_grade(self) -> CostLineageCalibration:
        acceptance = self.no_model_acceptance
        if acceptance.get("status") != "passed":
            raise ValueError("cost-lineage calibration requires passed acceptance")
        if acceptance.get("external_model_calls") != 0:
            raise ValueError("cost-lineage calibration must be no-model")
        if acceptance.get("known_model_cost_usd") != "0":
            raise ValueError("no-model cost-lineage calibration requires zero model cost")
        fixtures = acceptance.get("fixtures")
        required = {
            "provider_false_zero_recomputed",
            "missing_price_pre_call_rejected",
            "direct_lineage_overrides_raw",
            "positive_token_exact_zero_rejected",
        }
        if self.schema_version in {"1.1", "1.2"}:
            if self.cost_gate_input_policy is None:
                raise ValueError(
                    "cost-lineage calibration 1.1+ requires the Cost Gate input policy"
                )
            required.add("direct_total_mean_reaches_gate")
        elif self.cost_gate_input_policy is not None:
            raise ValueError(
                "cost-lineage calibration 1.0 cannot contain a Cost Gate input policy"
            )
        if self.schema_version == "1.2":
            required.add("infra_invalid_failed_attempt_lineage_sealed")
        if not isinstance(fixtures, dict) or not all(
            fixtures.get(name) == "passed" for name in required
        ):
            raise ValueError("cost-lineage calibration lacks required passed fixtures")
        attempts = acceptance.get("attempts")
        if not isinstance(attempts, list) or not any(
            isinstance(attempt, dict)
            and attempt.get("scope") == "full_clean_room"
            and attempt.get("status") == "passed"
            for attempt in attempts
        ):
            raise ValueError("cost-lineage calibration requires a passed clean-room attempt")
        return self


class EvaluatorCorrectionCalibration(StrictModel):
    """No-model evidence for conflict detection and a scoped evaluator overlay."""

    schema_version: Literal["1.0"]
    artifact_id: ArtifactId
    source_experiment_id: ArtifactId
    source_incident_artifact: NonEmpty
    source_incident_digest: Digest
    evaluator_overlay_artifact: NonEmpty
    evaluator_overlay_digest: Digest
    contains_raw_customer_data: Literal[False]
    evaluator_conflict_policy: Literal[
        "all_expected_actions_matched_db_mismatch_hold_v1"
    ]
    evaluator_correction_policy: Literal[
        "versioned_overlay_symmetric_affected_rerun_v1"
    ]
    affected_task_ids: list[ArtifactId] = Field(min_length=1)
    assertions: list[NonEmpty] = Field(min_length=5)
    runtime_bindings: dict[NonEmpty, Digest] = Field(min_length=5)
    no_model_acceptance: dict[NonEmpty, Any]
    limitations: list[NonEmpty] = Field(min_length=1)
    artifact_digest: Digest

    @model_validator(mode="after")
    def acceptance_is_publication_grade(self) -> EvaluatorCorrectionCalibration:
        acceptance = self.no_model_acceptance
        if acceptance.get("status") != "passed":
            raise ValueError("evaluator correction calibration requires passed acceptance")
        if acceptance.get("external_model_calls") != 0:
            raise ValueError("evaluator correction calibration must be no-model")
        if acceptance.get("known_model_cost_usd") != "0":
            raise ValueError("no-model evaluator calibration requires zero model cost")
        fixtures = acceptance.get("fixtures")
        required = {
            "conflict_detected",
            "candidate_generation_blocked",
            "upstream_checkout_unchanged",
            "overlay_source_digest_verified",
            "immutable_trajectory_regrade_passes",
            "unrelated_task_scope_unchanged",
        }
        if not isinstance(fixtures, dict) or not all(
            fixtures.get(name) == "passed" for name in required
        ):
            raise ValueError(
                "evaluator correction calibration lacks required passed fixtures"
            )
        attempts = acceptance.get("attempts")
        if not isinstance(attempts, list) or not any(
            isinstance(attempt, dict)
            and attempt.get("scope") == "full_clean_room"
            and attempt.get("status") == "passed"
            for attempt in attempts
        ):
            raise ValueError(
                "evaluator correction calibration requires a passed clean-room attempt"
            )
        return self


class SuccessorIntegrityCalibration(StrictModel):
    """No-model evidence for User final repair and Updater sandbox routing."""

    schema_version: Literal["1.0"]
    artifact_id: ArtifactId
    source_experiment_id: ArtifactId
    source_incident_artifact: NonEmpty
    source_incident_digest: Digest
    contains_raw_customer_data: Literal[False]
    user_empty_final_repair_policy: Literal[
        "bounded_same_call_context_final_only_v1"
    ]
    user_empty_final_repair_limit: Literal[1]
    updater_sandbox_output_policy: Literal["attempt_local_runtime_only_v1"]
    assertions: list[NonEmpty] = Field(min_length=6)
    runtime_bindings: dict[NonEmpty, Digest] = Field(min_length=6)
    no_model_acceptance: dict[NonEmpty, Any]
    limitations: list[NonEmpty] = Field(min_length=1)
    artifact_digest: Digest

    @model_validator(mode="after")
    def acceptance_is_publication_grade(self) -> SuccessorIntegrityCalibration:
        acceptance = self.no_model_acceptance
        if acceptance.get("status") != "passed":
            raise ValueError("successor integrity calibration requires passed acceptance")
        if acceptance.get("external_model_calls") != 0:
            raise ValueError("successor integrity calibration must be no-model")
        if acceptance.get("known_model_cost_usd") != "0":
            raise ValueError("no-model successor calibration requires zero model cost")
        fixtures = acceptance.get("fixtures")
        required = {
            "user_empty_final_single_repair",
            "user_empty_final_second_empty_fails_closed",
            "user_usage_and_cost_aggregation",
            "user_calls_separately_ledgered",
            "invalid_policy_or_limit_rejected",
            "ahe_runtime_paths_attempt_local",
            "ahe_long_tool_output_attempt_local",
            "nexau_bash_inside_formal_sandbox",
        }
        if not isinstance(fixtures, dict) or not all(
            fixtures.get(name) == "passed" for name in required
        ):
            raise ValueError(
                "successor integrity calibration lacks required passed fixtures"
            )
        attempts = acceptance.get("attempts")
        if not isinstance(attempts, list) or not any(
            isinstance(attempt, dict)
            and attempt.get("scope") == "full_clean_room"
            and attempt.get("status") == "passed"
            for attempt in attempts
        ):
            raise ValueError(
                "successor integrity calibration requires a passed clean-room attempt"
            )
        return self


def protocol_digest_payload(protocol: FormalExecutionProtocol) -> dict[str, Any]:
    payload = protocol.model_dump(mode="json", exclude={"protocol_digest"})
    for key in set(payload) - protocol.model_fields_set:
        payload.pop(key, None)
    return payload


def computed_protocol_digest(protocol: FormalExecutionProtocol) -> str:
    return canonical_digest(protocol_digest_payload(protocol))


def verify_execution_protocol(protocol: FormalExecutionProtocol) -> None:
    computed = computed_protocol_digest(protocol)
    if computed != protocol.protocol_digest:
        raise ValueError(
            "execution protocol digest mismatch: "
            f"expected {protocol.protocol_digest}, got {computed}"
        )


def load_execution_protocol(path: Path) -> FormalExecutionProtocol:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read formal execution protocol: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("formal execution protocol must be a YAML object")
    protocol = FormalExecutionProtocol.model_validate(raw)
    verify_execution_protocol(protocol)
    return protocol


def reply_lineage_calibration_digest_payload(
    calibration: ReplyLineageCalibration,
) -> dict[str, Any]:
    return calibration.model_dump(mode="json", exclude={"artifact_digest"})


def computed_reply_lineage_calibration_digest(
    calibration: ReplyLineageCalibration,
) -> str:
    return canonical_digest(reply_lineage_calibration_digest_payload(calibration))


def verify_reply_lineage_calibration(
    calibration: ReplyLineageCalibration,
) -> None:
    computed = computed_reply_lineage_calibration_digest(calibration)
    if computed != calibration.artifact_digest:
        raise ValueError(
            "reply-lineage calibration digest mismatch: "
            f"expected {calibration.artifact_digest}, got {computed}"
        )


def load_reply_lineage_calibration(path: Path) -> ReplyLineageCalibration:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read reply-lineage calibration: {path}") from exc
    calibration = ReplyLineageCalibration.model_validate(raw)
    verify_reply_lineage_calibration(calibration)
    return calibration


def cost_lineage_calibration_digest_payload(
    calibration: CostLineageCalibration,
) -> dict[str, Any]:
    payload = calibration.model_dump(mode="json", exclude={"artifact_digest"})
    for key in set(payload) - calibration.model_fields_set:
        payload.pop(key, None)
    return payload


def computed_cost_lineage_calibration_digest(
    calibration: CostLineageCalibration,
) -> str:
    return canonical_digest(cost_lineage_calibration_digest_payload(calibration))


def verify_cost_lineage_calibration(calibration: CostLineageCalibration) -> None:
    computed = computed_cost_lineage_calibration_digest(calibration)
    if computed != calibration.artifact_digest:
        raise ValueError(
            "cost-lineage calibration digest mismatch: "
            f"expected {calibration.artifact_digest}, got {computed}"
        )


def load_cost_lineage_calibration(path: Path) -> CostLineageCalibration:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read cost-lineage calibration: {path}") from exc
    calibration = CostLineageCalibration.model_validate(raw)
    verify_cost_lineage_calibration(calibration)
    return calibration


def evaluator_correction_calibration_digest_payload(
    calibration: EvaluatorCorrectionCalibration,
) -> dict[str, Any]:
    return calibration.model_dump(mode="json", exclude={"artifact_digest"})


def computed_evaluator_correction_calibration_digest(
    calibration: EvaluatorCorrectionCalibration,
) -> str:
    return canonical_digest(evaluator_correction_calibration_digest_payload(calibration))


def verify_evaluator_correction_calibration(
    calibration: EvaluatorCorrectionCalibration,
) -> None:
    computed = computed_evaluator_correction_calibration_digest(calibration)
    if computed != calibration.artifact_digest:
        raise ValueError(
            "evaluator correction calibration digest mismatch: "
            f"expected {calibration.artifact_digest}, got {computed}"
        )


def load_evaluator_correction_calibration(
    path: Path,
) -> EvaluatorCorrectionCalibration:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read evaluator correction calibration: {path}") from exc
    calibration = EvaluatorCorrectionCalibration.model_validate(raw)
    verify_evaluator_correction_calibration(calibration)
    return calibration


def successor_integrity_calibration_digest_payload(
    calibration: SuccessorIntegrityCalibration,
) -> dict[str, Any]:
    return calibration.model_dump(mode="json", exclude={"artifact_digest"})


def computed_successor_integrity_calibration_digest(
    calibration: SuccessorIntegrityCalibration,
) -> str:
    return canonical_digest(successor_integrity_calibration_digest_payload(calibration))


def verify_successor_integrity_calibration(
    calibration: SuccessorIntegrityCalibration,
) -> None:
    computed = computed_successor_integrity_calibration_digest(calibration)
    if computed != calibration.artifact_digest:
        raise ValueError(
            "successor integrity calibration digest mismatch: "
            f"expected {calibration.artifact_digest}, got {computed}"
        )


def load_successor_integrity_calibration(
    path: Path,
) -> SuccessorIntegrityCalibration:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read successor integrity calibration: {path}") from exc
    calibration = SuccessorIntegrityCalibration.model_validate(raw)
    verify_successor_integrity_calibration(calibration)
    return calibration
