from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from agentloopgate.adapters import (
    DshTau3PilotResult,
    OutcomeDiagnostics,
    load_pilot_pricing,
)
from agentloopgate.adapters.base import ActionDiagnostic
from agentloopgate.adapters.evidence import BenchmarkEvidenceStore
from agentloopgate.bridge import BridgeRequest, BridgeService
from agentloopgate.contracts import canonical_digest
from agentloopgate.experiment import (
    BankingStudyPlan,
    CostLineageCalibration,
    EvaluatorCorrectionCalibration,
    ExperimentAttemptLedger,
    FormalBatchError,
    FormalBatchExecution,
    FormalBatchRunner,
    FormalBatchSpec,
    FormalExecutionProtocol,
    FormalStage,
    PaidExecutionAuthorization,
    PaidExecutionAuthorizationError,
    ReplyLineageCalibration,
    computed_cost_lineage_calibration_digest,
    computed_evaluator_correction_calibration_digest,
    computed_paid_execution_authorization_digest,
    computed_protocol_digest,
    computed_reply_lineage_calibration_digest,
    computed_study_digest,
    diagnose_formal_records,
    load_cost_lineage_calibration,
    load_evaluator_correction_calibration,
    load_execution_protocol,
    load_reply_lineage_calibration,
    load_study_plan,
    verify_paid_execution_authorization,
)
from agentloopgate.experiment import ledger as ledger_module
from agentloopgate.experiment import orchestrator as orchestrator_module
from agentloopgate.experiment.orchestrator import (
    FormalExperimentOrchestrator,
    FormalSelectionHoldOutcome,
    FormalWorkflowBlocked,
    _build_role_assignment,
    _diverse_subset,
)
from agentloopgate.experiment.service import (
    _code_revision,
    _verified_protocol,
    load_formal_config,
)
from agentloopgate.runtime.tau3_evidence import _append_task_event
from agentloopgate.runtime.usage import (
    AttemptState,
    CostStatus,
    append_model_call_event,
    make_model_call_event,
)
from agentloopgate.schemas import (
    CandidateRecord,
    EvidenceReceipt,
    FailureType,
    PilotEvidenceJoin,
    RunRecord,
    RunSource,
    RuntimeHost,
)
from agentloopgate.splits.models import TaskDescriptor

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def test_formal_config_pins_reliability_models_and_candidate_floor(tmp_path: Path) -> None:
    source = Path("configs/formal_experiment.yaml")
    config = load_formal_config(source)

    assert config.candidate_count == 3
    assert config.release_trials == config.stable_success_required == 3
    assert config.agent_model == "deepseek-v4-flash"
    assert config.user_model == "deepseek/deepseek-v4-flash"

    invalid = yaml.safe_load(source.read_text(encoding="utf-8"))
    invalid["candidate_count"] = 2
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(invalid), encoding="utf-8")
    with pytest.raises(ValidationError, match="greater than or equal to 3"):
        load_formal_config(path)


def test_formal_config_1_2_requires_a_paid_authorization_root(
    tmp_path: Path,
) -> None:
    payload = yaml.safe_load(
        Path("configs/formal_experiment_r10.yaml").read_text(encoding="utf-8")
    )
    payload["schema_version"] = "1.2"
    missing = tmp_path / "missing-authorization-root.yaml"
    missing.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="paid_execution_authorization_root"):
        load_formal_config(missing)

    payload["paid_execution_authorization_root"] = (
        "runs/authorizations/EXP_BANKING_R10"
    )
    configured = tmp_path / "configured.yaml"
    configured.write_text(yaml.safe_dump(payload), encoding="utf-8")

    assert load_formal_config(configured).schema_version == "1.2"


def test_paid_authorization_binds_source_study_scope_and_task_positions(
    tmp_path: Path,
) -> None:
    config = load_formal_config(Path("configs/formal_experiment_r10.yaml")).model_copy(
        update={
            "schema_version": "1.2",
            "paid_execution_authorization_root": "runs/authorizations/EXP_FIXTURE",
        }
    )
    protocol = SimpleNamespace(protocol_digest=DIGEST_A)
    study = SimpleNamespace(
        study_digest=DIGEST_B,
        matrix=[
            SimpleNamespace(stage=FormalStage.UPDATE_SOURCE, target_trials=25),
            SimpleNamespace(stage=FormalStage.UPDATE_CHECK, target_trials=40),
            SimpleNamespace(stage=FormalStage.SELECTION, target_trials=60),
            SimpleNamespace(stage=FormalStage.RELEASE_ID, target_trials=180),
            SimpleNamespace(stage=FormalStage.RELEASE_OOD, target_trials=180),
            SimpleNamespace(stage=FormalStage.REPLAY, target_trials=90),
        ],
    )
    authorization = PaidExecutionAuthorization(
        authorization_id="AUTH_PRE_RELEASE_FIXTURE",
        experiment_id=config.experiment_id,
        scope="pre_release_checkpoint",
        protocol_digest=DIGEST_A,
        study_digest=DIGEST_B,
        source_revision="tree:fixture",
        authorized_stages=[
            FormalStage.UPDATE_SOURCE,
            FormalStage.UPDATE_CHECK,
            FormalStage.SELECTION,
        ],
        authorized_task_positions=125,
        external_updater_generation_authorized=True,
        authorized_by="owner",
        authorized_at="2026-08-23T00:00:00Z",
        confirmation="OWNER_AUTHORIZED_PRE_RELEASE_CHECKPOINT",
        authorization_digest=DIGEST_C,
    )
    authorization = authorization.model_copy(
        update={
            "authorization_digest": computed_paid_execution_authorization_digest(
                authorization
            )
        }
    )
    path = tmp_path / "pre_release_checkpoint.json"
    path.write_text(authorization.model_dump_json(), encoding="utf-8")

    verified = verify_paid_execution_authorization(
        path,
        config=config,
        protocol=protocol,
        study=study,
        source_revision="tree:fixture",
        required_stage=FormalStage.SELECTION,
    )

    assert verified.authorization_digest == authorization.authorization_digest
    drifted = authorization.model_copy(update={"authorized_task_positions": 124})
    drifted = drifted.model_copy(
        update={
            "authorization_digest": computed_paid_execution_authorization_digest(
                drifted
            )
        }
    )
    path.write_text(drifted.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="task-position scope mismatch"):
        verify_paid_execution_authorization(
            path,
            config=config,
            protocol=protocol,
            study=study,
            source_revision="tree:fixture",
            required_stage=FormalStage.UPDATE_SOURCE,
        )


def test_release_authorization_requires_a_bound_select_not_hold(
    tmp_path: Path,
) -> None:
    config = load_formal_config(Path("configs/formal_experiment_r10.yaml")).model_copy(
        update={
            "schema_version": "1.2",
            "paid_execution_authorization_root": "runs/authorizations/EXP_FIXTURE",
        }
    )
    protocol = SimpleNamespace(protocol_digest=DIGEST_A)
    study = SimpleNamespace(
        study_digest=DIGEST_B,
        matrix=[
            SimpleNamespace(stage=FormalStage.UPDATE_SOURCE, target_trials=25),
            SimpleNamespace(stage=FormalStage.UPDATE_CHECK, target_trials=40),
            SimpleNamespace(stage=FormalStage.SELECTION, target_trials=60),
            SimpleNamespace(stage=FormalStage.RELEASE_ID, target_trials=180),
            SimpleNamespace(stage=FormalStage.RELEASE_OOD, target_trials=180),
            SimpleNamespace(stage=FormalStage.REPLAY, target_trials=90),
        ],
    )
    selection_body = {
        "schema_version": "1.1",
        "inputs": [{"candidate_id": "C_1"}],
        "selection": {
            "agentloopgate_decision": "SELECT",
            "agentloopgate_candidate_id": "C_1",
        },
    }
    selection_digest = canonical_digest(selection_body)
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(
        json.dumps({**selection_body, "selection_digest": selection_digest}),
        encoding="utf-8",
    )
    authorization = PaidExecutionAuthorization(
        authorization_id="AUTH_RELEASE_FIXTURE",
        experiment_id=config.experiment_id,
        scope="release_tail",
        protocol_digest=DIGEST_A,
        study_digest=DIGEST_B,
        source_revision="tree:fixture",
        authorized_stages=[
            FormalStage.RELEASE_ID,
            FormalStage.RELEASE_OOD,
            FormalStage.REPLAY,
        ],
        authorized_task_positions=450,
        external_updater_generation_authorized=False,
        selection_digest=selection_digest,
        governed_candidate_id="C_1",
        authorized_by="owner",
        authorized_at="2026-08-23T00:00:00Z",
        confirmation="OWNER_AUTHORIZED_RELEASE_TAIL",
        authorization_digest=DIGEST_C,
    )
    authorization = authorization.model_copy(
        update={
            "authorization_digest": computed_paid_execution_authorization_digest(
                authorization
            )
        }
    )
    authorization_path = tmp_path / "release_tail.json"
    authorization_path.write_text(authorization.model_dump_json(), encoding="utf-8")

    assert (
        verify_paid_execution_authorization(
            authorization_path,
            config=config,
            protocol=protocol,
            study=study,
            source_revision="tree:fixture",
            required_stage=FormalStage.RELEASE_ID,
            selection_path=selection_path,
        ).scope
        == "release_tail"
    )

    held_body = {
        **selection_body,
        "selection": {
            "agentloopgate_decision": "HOLD",
            "agentloopgate_candidate_id": None,
        },
    }
    held_digest = canonical_digest(held_body)
    selection_path.write_text(
        json.dumps({**held_body, "selection_digest": held_digest}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="requires a verified SELECT result"):
        verify_paid_execution_authorization(
            authorization_path,
            config=config,
            protocol=protocol,
            study=study,
            source_revision="tree:fixture",
            required_stage=FormalStage.RELEASE_ID,
            selection_path=selection_path,
        )


def test_study_1_2_requires_a0_selection_and_abstention_policy() -> None:
    payload = yaml.safe_load(
        Path("configs/banking_r10_study_v1.yaml").read_text(encoding="utf-8")
    )
    payload.update(
        {
            "schema_version": "1.2",
            "study_id": "BANKING_R11_STUDY_DRAFT_FIXTURE",
            "experiment_id": "EXP_BANKING_R11_FIXTURE",
            "supersedes_study_digest": payload["study_digest"],
            "selection_baseline_policy": (
                "same_pool_same_tasks_same_trials_required"
            ),
            "selection_abstain_policy": (
                "hold_unless_strict_stable_gain_without_stable_regression"
            ),
            "selection_operational_evidence_policy": (
                "whole_attempt_retry_timeout_p95_max_v1"
            ),
            "candidate_semantic_policy": (
                "runtime_capability_bound_and_semantically_distinct_v1"
            ),
            "selection_whole_attempt_cost_ratio_max": "1.2",
            "selection_p95_latency_ratio_max": "1.2",
            "selection_max_retry_increase": 0,
            "selection_max_timeout_increase": 0,
            "core_target_trial_count": 575,
            "study_digest": DIGEST_A,
        }
    )
    selection = next(row for row in payload["matrix"] if row["stage"] == "selection")
    selection.update({"variant_count": 4, "target_trials": 60})

    study = BankingStudyPlan.model_validate(payload)

    assert study.core_target_trial_count == 575
    assert study.selection_baseline_policy == (
        "same_pool_same_tasks_same_trials_required"
    )
    drifted = study.model_dump(mode="python")
    selection = next(row for row in drifted["matrix"] if row["stage"] == "selection")
    selection.update({"variant_count": 3, "target_trials": 45})
    drifted["core_target_trial_count"] = 560
    with pytest.raises(ValidationError, match="A0 plus three candidates"):
        BankingStudyPlan.model_validate(drifted)


def test_banking_r2_config_requires_a_matching_frozen_protocol(tmp_path: Path) -> None:
    config = load_formal_config(Path("configs/formal_experiment_r2.yaml"))
    protocol = load_execution_protocol(
        Path(config.execution_protocol_config or "missing")
    )
    study = load_study_plan(Path(config.study_plan_config or "missing"))

    assert config.schema_version == "1.1"
    assert config.experiment_id == protocol.experiment_id == "EXP_BANKING_R2"
    assert protocol.max_concurrency == 1
    assert protocol.max_retries == 1
    assert protocol.turn_timeout_seconds == 180
    assert computed_protocol_digest(protocol) == protocol.protocol_digest
    assert study.protocol_digest == protocol.protocol_digest
    assert study.core_target_trial_count == 560
    assert computed_study_digest(study) == study.study_digest

    drifted = yaml.safe_load(
        Path("configs/experiment_protocol_banking_r2.yaml").read_text(encoding="utf-8")
    )
    drifted["max_retries"] = 2
    path = tmp_path / "drifted-protocol.yaml"
    path.write_text(yaml.safe_dump(drifted), encoding="utf-8")
    with pytest.raises((ValidationError, ValueError)):
        load_execution_protocol(path)


def test_banking_r3_freezes_calibrated_dsh_compatibility_protocol() -> None:
    config = load_formal_config(Path("configs/formal_experiment_r3.yaml"))
    protocol = load_execution_protocol(
        Path(config.execution_protocol_config or "missing")
    )
    study = load_study_plan(Path(config.study_plan_config or "missing"))

    assert config.experiment_id == protocol.experiment_id == "EXP_BANKING_R3"
    assert config.baseline_snapshot_id == "R3_A1"
    assert config.research_artifact_root == "artifacts/research/banking_r3"
    assert protocol.schema_version == "1.2"
    assert protocol.agent_max_output_tokens == 8192
    assert protocol.turn_timeout_seconds == 300
    assert protocol.dsh_tau3_protocol_version == "dsh-tau3/1.1"
    assert protocol.reply_normalization_policy == (
        "bounded_allow_list_v3_plain_content_and_flattened_arguments"
    )
    assert protocol.runner_failure_usage_policy == "recover_verified_envelope"
    assert protocol.execution_calibration_digest == (
        "sha256:123e8f8be4988b09acf894143ce836a844b908c8f08e68d32be7ef7a639c2690"
    )
    assert computed_protocol_digest(protocol) == protocol.protocol_digest
    assert study.protocol_digest == protocol.protocol_digest
    assert study.core_target_trial_count == 560
    assert computed_study_digest(study) == study.study_digest


def test_banking_r4_freezes_global_resume_and_cost_observability_protocol() -> None:
    config = load_formal_config(Path("configs/formal_experiment_r4.yaml"))
    protocol = load_execution_protocol(
        Path(config.execution_protocol_config or "missing")
    )
    study = load_study_plan(Path(config.study_plan_config or "missing"))

    assert config.experiment_id == protocol.experiment_id == "EXP_BANKING_R4"
    assert config.baseline_snapshot_id == "R4_A0"
    assert config.research_artifact_root == "artifacts/research/banking_r4"
    assert protocol.schema_version == "1.3"
    assert protocol.agent_max_output_tokens == 32768
    assert protocol.global_task_attempt_limit == 2
    assert protocol.resume_retry_budget_policy == "global_task_position_attempt_cap"
    assert protocol.network_route_policy == "direct_no_proxy"
    assert protocol.user_failure_usage_policy == "append_only_model_call_ledger"
    assert protocol.cost_gate_scope == "valid_runs_exact_whole_attempt_reported"
    assert protocol.execution_calibration_digest == (
        "sha256:bbde5c453f7896e981a0c7224e8a44b22d0ae75d0dfb1b6b99bb271c8afae210"
    )
    assert computed_protocol_digest(protocol) == protocol.protocol_digest
    assert study.protocol_digest == protocol.protocol_digest
    assert study.supersedes_study_digest == (
        "sha256:1447fb959dbbfb87994001a020f75abfcc72be801760ebe963d0e22b3cced1c2"
    )
    assert computed_study_digest(study) == study.study_digest


def test_banking_r5_freezes_bounded_reply_compatibility_protocol() -> None:
    config = load_formal_config(Path("configs/formal_experiment_r5.yaml"))
    protocol = load_execution_protocol(
        Path(config.execution_protocol_config or "missing")
    )
    study = load_study_plan(Path(config.study_plan_config or "missing"))

    assert config.experiment_id == protocol.experiment_id == "EXP_BANKING_R5"
    assert config.baseline_snapshot_id == "R5_A0"
    assert config.research_artifact_root == "artifacts/research/banking_r5"
    assert protocol.schema_version == "1.3"
    assert protocol.reply_normalization_policy == (
        "bounded_allow_list_v4_redundant_allow_listed_name"
    )
    assert protocol.agent_max_output_tokens == 32768
    assert protocol.global_task_attempt_limit == 2
    assert protocol.network_route_policy == "direct_no_proxy"
    assert protocol.execution_calibration_digest == (
        "sha256:faf997e978ff721b56d561f9734ebbc64806cbdea80e413fcf02e36752c0196e"
    )
    assert computed_protocol_digest(protocol) == protocol.protocol_digest
    assert study.protocol_digest == protocol.protocol_digest
    assert study.supersedes_study_digest == (
        "sha256:2e96cd2bdc07e14830bb6ecbbca1a63995c586adf63a154775988239004c2f0a"
    )
    assert computed_study_digest(study) == study.study_digest


def test_protocol_1_4_requires_timeout_ordering_and_bounded_empty_final_repair(
    tmp_path: Path,
) -> None:
    payload = yaml.safe_load(
        Path("configs/experiment_protocol_banking_r5_v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    payload.update(
        {
            "schema_version": "1.4",
            "turn_timeout_seconds": 360,
            "dsh_stream_idle_timeout_ms": 300_000,
            "empty_final_repair_policy": "bounded_same_session_final_only_v1",
            "empty_final_repair_limit": 1,
        }
    )

    protocol = FormalExecutionProtocol.model_validate(payload)

    assert protocol.turn_timeout_seconds * 1000 > protocol.dsh_stream_idle_timeout_ms
    assert protocol.empty_final_repair_limit == 1

    unordered = dict(payload, turn_timeout_seconds=300)
    with pytest.raises(ValidationError, match="outer turn timeout must exceed"):
        FormalExecutionProtocol.model_validate(unordered)

    missing_repair = dict(payload)
    missing_repair.pop("empty_final_repair_policy")
    with pytest.raises(ValidationError, match="bounded empty-final repair"):
        FormalExecutionProtocol.model_validate(missing_repair)


def test_banking_r6_freezes_empty_final_and_timeout_integrity_protocol() -> None:
    config = load_formal_config(Path("configs/formal_experiment_r6.yaml"))
    protocol = load_execution_protocol(
        Path(config.execution_protocol_config or "missing")
    )
    study = load_study_plan(Path(config.study_plan_config or "missing"))

    assert config.experiment_id == protocol.experiment_id == "EXP_BANKING_R6"
    assert config.baseline_snapshot_id == "R6_A0"
    assert config.research_artifact_root == "artifacts/research/banking_r6"
    assert protocol.schema_version == "1.4"
    assert protocol.turn_timeout_seconds == 360
    assert protocol.dsh_stream_idle_timeout_ms == 300_000
    assert protocol.empty_final_repair_policy == (
        "bounded_same_session_final_only_v1"
    )
    assert protocol.empty_final_repair_limit == 1
    assert protocol.reply_normalization_policy == (
        "bounded_allow_list_v4_redundant_allow_listed_name"
    )
    assert protocol.execution_calibration_digest == (
        "sha256:ae732aa052bda8103be44b2d37f23135c449825efa904d950d207b43a6b0d7d3"
    )
    assert computed_protocol_digest(protocol) == protocol.protocol_digest
    assert study.protocol_digest == protocol.protocol_digest
    assert study.supersedes_study_digest == (
        "sha256:cccb819ae858b15d3f1ae9e8847ff084a92195967683b60a07dc901c30eaf7b7"
    )
    assert study.core_target_trial_count == 560
    assert computed_study_digest(study) == study.study_digest


def test_protocol_1_5_requires_reply_v5_and_direct_lineage_pins() -> None:
    payload = yaml.safe_load(
        Path("configs/experiment_protocol_banking_r6_v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    payload.update(
        {
            "schema_version": "1.5",
            "reply_normalization_policy": (
                "bounded_allow_list_v5_missing_name_and_discoverable_wrapper_alias"
            ),
            "reply_lineage_calibration_artifact": "artifacts/calibration.json",
            "reply_lineage_calibration_digest": DIGEST_A,
            "task_attempt_ledger_schema_version": "1.1",
            "model_usage_ledger_schema_version": "1.2",
            "task_attempt_session_binding_policy": (
                "append_before_first_agent_call_v1"
            ),
            "model_call_task_identity_policy": (
                "direct_task_trial_seed_attempt_v1"
            ),
        }
    )

    protocol = FormalExecutionProtocol.model_validate(payload)

    assert protocol.schema_version == "1.5"
    assert protocol.task_attempt_ledger_schema_version == "1.1"
    assert protocol.model_usage_ledger_schema_version == "1.2"

    missing_binding = dict(payload)
    missing_binding.pop("task_attempt_session_binding_policy")
    with pytest.raises(ValidationError, match="direct task/session evidence pins"):
        FormalExecutionProtocol.model_validate(missing_binding)

    old_reply = dict(
        payload,
        reply_normalization_policy=(
            "bounded_allow_list_v4_redundant_allow_listed_name"
        ),
    )
    with pytest.raises(ValidationError, match="requires Reply Policy v5"):
        FormalExecutionProtocol.model_validate(old_reply)


def test_reply_lineage_calibration_requires_passed_no_model_clean_room() -> None:
    payload = {
        "schema_version": "1.0",
        "artifact_id": "BANKING_R7_REPLY_LINEAGE_CALIBRATION",
        "source_experiment_id": "EXP_BANKING_R6",
        "source_diagnosis_artifact": "artifacts/source.json",
        "source_diagnosis_digest": DIGEST_A,
        "contains_raw_customer_data": False,
        "reply_normalization_policy": (
            "bounded_allow_list_v5_missing_name_and_discoverable_wrapper_alias"
        ),
        "task_attempt_ledger_schema_version": "1.1",
        "model_usage_ledger_schema_version": "1.2",
        "task_attempt_session_binding_policy": "append_before_first_agent_call_v1",
        "model_call_task_identity_policy": "direct_task_trial_seed_attempt_v1",
        "accepted_reply_shapes": ["missing fixed name label", "explicit wrapper alias"],
        "rejected_reply_shapes": [
            "unknown tool",
            "mixed reply",
            "multiple calls",
            "partial arguments",
            "unsafe subtool identifier",
        ],
        "lineage_assertions": [
            "task start precedes binding",
            "binding precedes first agent call",
            "terminal preserves binding",
            "model calls carry direct task identity",
        ],
        "runtime_bindings": {
            f"runtime/file_{index}.py": DIGEST_A for index in range(5)
        },
        "no_model_acceptance": {
            "status": "passed",
            "external_model_calls": 0,
            "known_model_cost_usd": "0",
            "attempts": [
                {
                    "scope": "full_clean_room",
                    "status": "passed",
                }
            ],
        },
        "limitations": ["no-model fixtures do not prove provider frequency"],
        "artifact_digest": DIGEST_B,
    }
    draft = ReplyLineageCalibration.model_validate(payload)
    digest = computed_reply_lineage_calibration_digest(draft)
    calibration = draft.model_copy(update={"artifact_digest": digest})

    assert computed_reply_lineage_calibration_digest(calibration) == digest

    paid = dict(payload)
    paid["no_model_acceptance"] = dict(
        payload["no_model_acceptance"], external_model_calls=1
    )
    with pytest.raises(ValidationError, match="must be no-model"):
        ReplyLineageCalibration.model_validate(paid)

    no_clean_room = dict(payload)
    no_clean_room["no_model_acceptance"] = {
        "status": "passed",
        "external_model_calls": 0,
        "known_model_cost_usd": "0",
        "attempts": [{"scope": "focused", "status": "passed"}],
    }
    with pytest.raises(ValidationError, match="passed clean-room"):
        ReplyLineageCalibration.model_validate(no_clean_room)


def test_protocol_1_6_requires_frozen_price_direct_cost_pins() -> None:
    payload = yaml.safe_load(
        Path("configs/experiment_protocol_banking_r7_v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    payload.update(
        {
            "schema_version": "1.6",
            "cost_lineage_calibration_artifact": "artifacts/cost-calibration.json",
            "cost_lineage_calibration_digest": DIGEST_A,
            "cost_authority_policy": "verified_tokens_times_frozen_prices_v1",
            "valid_cost_lineage_policy": "direct_final_task_attempt_calls_v1",
            "raw_cost_evidence_policy": "comparison_only_v1",
            "positive_token_zero_cost_policy": (
                "reject_positive_frozen_contribution_v1"
            ),
        }
    )

    protocol = FormalExecutionProtocol.model_validate(payload)

    assert protocol.schema_version == "1.6"
    assert protocol.valid_cost_lineage_policy == (
        "direct_final_task_attempt_calls_v1"
    )
    missing = dict(payload)
    missing.pop("cost_authority_policy")
    with pytest.raises(ValidationError, match="direct cost-lineage pins"):
        FormalExecutionProtocol.model_validate(missing)


def test_protocol_1_7_requires_direct_agent_user_gate_input() -> None:
    payload = yaml.safe_load(
        Path("configs/experiment_protocol_banking_r8_v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    payload.update(
        {
            "schema_version": "1.7",
            "cost_gate_input_policy": "direct_valid_agent_plus_user_mean_v1",
        }
    )

    protocol = FormalExecutionProtocol.model_validate(payload)

    assert protocol.cost_gate_input_policy == "direct_valid_agent_plus_user_mean_v1"
    missing = dict(payload)
    missing.pop("cost_gate_input_policy")
    with pytest.raises(ValidationError, match="Cost Gate input pin"):
        FormalExecutionProtocol.model_validate(missing)


def test_cost_lineage_calibration_requires_all_no_model_fixtures() -> None:
    payload = {
        "schema_version": "1.1",
        "artifact_id": "BANKING_R8_COST_LINEAGE_CALIBRATION",
        "source_experiment_id": "EXP_BANKING_R7",
        "source_incident_artifact": "artifacts/cost-incident.json",
        "source_incident_digest": DIGEST_A,
        "contains_raw_customer_data": False,
        "pricing_digest": DIGEST_A,
        "cost_authority_policy": "verified_tokens_times_frozen_prices_v1",
        "valid_cost_lineage_policy": "direct_final_task_attempt_calls_v1",
        "raw_cost_evidence_policy": "comparison_only_v1",
        "positive_token_zero_cost_policy": (
            "reject_positive_frozen_contribution_v1"
        ),
        "cost_gate_input_policy": "direct_valid_agent_plus_user_mean_v1",
        "assertions": [
            "prices load before paid calls",
            "verified counters determine cost",
            "raw values are comparisons",
            "direct task lineage determines valid cost",
            "positive priced usage cannot be exact zero",
        ],
        "runtime_bindings": {
            f"runtime/file_{index}.py": DIGEST_A for index in range(4)
        },
        "no_model_acceptance": {
            "status": "passed",
            "external_model_calls": 0,
            "known_model_cost_usd": "0",
            "fixtures": {
                "provider_false_zero_recomputed": "passed",
                "missing_price_pre_call_rejected": "passed",
                "direct_lineage_overrides_raw": "passed",
                "positive_token_exact_zero_rejected": "passed",
                "direct_total_mean_reaches_gate": "passed",
            },
            "attempts": [{"scope": "full_clean_room", "status": "passed"}],
        },
        "limitations": ["no-model fixtures do not prove provider billing"],
        "artifact_digest": DIGEST_B,
    }
    draft = CostLineageCalibration.model_validate(payload)
    digest = computed_cost_lineage_calibration_digest(draft)
    calibration = draft.model_copy(update={"artifact_digest": digest})

    assert computed_cost_lineage_calibration_digest(calibration) == digest
    incomplete = dict(payload)
    incomplete["no_model_acceptance"] = dict(payload["no_model_acceptance"])
    incomplete["no_model_acceptance"]["fixtures"] = {
        "provider_false_zero_recomputed": "passed"
    }
    with pytest.raises(ValidationError, match="lacks required passed fixtures"):
        CostLineageCalibration.model_validate(incomplete)


def test_evaluator_correction_calibration_requires_fail_closed_fixtures(
    tmp_path: Path,
) -> None:
    payload = {
        "schema_version": "1.0",
        "artifact_id": "EVAL_CALIBRATION_FIXTURE",
        "source_experiment_id": "EXP_FIXTURE",
        "source_incident_artifact": "artifacts/incident.json",
        "source_incident_digest": DIGEST_A,
        "evaluator_overlay_artifact": "configs/overlay.json",
        "evaluator_overlay_digest": DIGEST_B,
        "contains_raw_customer_data": False,
        "evaluator_conflict_policy": (
            "all_expected_actions_matched_db_mismatch_hold_v1"
        ),
        "evaluator_correction_policy": (
            "versioned_overlay_symmetric_affected_rerun_v1"
        ),
        "affected_task_ids": ["task_001"],
        "assertions": [f"assertion-{index}" for index in range(5)],
        "runtime_bindings": {f"runtime-{index}.py": DIGEST_C for index in range(5)},
        "no_model_acceptance": {
            "status": "passed",
            "external_model_calls": 0,
            "known_model_cost_usd": "0",
            "fixtures": {
                "conflict_detected": "passed",
                "candidate_generation_blocked": "passed",
                "upstream_checkout_unchanged": "passed",
                "overlay_source_digest_verified": "passed",
                "immutable_trajectory_regrade_passes": "passed",
                "unrelated_task_scope_unchanged": "passed",
            },
            "attempts": [{"scope": "full_clean_room", "status": "passed"}],
        },
        "limitations": ["fixture calibration"],
        "artifact_digest": DIGEST_A,
    }
    draft = EvaluatorCorrectionCalibration.model_validate(payload)
    digest = computed_evaluator_correction_calibration_digest(draft)
    calibration = draft.model_copy(update={"artifact_digest": digest})
    path = tmp_path / "evaluator-calibration.json"
    path.write_text(calibration.model_dump_json(), encoding="utf-8")

    assert load_evaluator_correction_calibration(path) == calibration
    incomplete = dict(payload)
    incomplete["no_model_acceptance"] = dict(payload["no_model_acceptance"])
    incomplete["no_model_acceptance"]["fixtures"] = {"conflict_detected": "passed"}
    with pytest.raises(ValidationError, match="lacks required passed fixtures"):
        EvaluatorCorrectionCalibration.model_validate(incomplete)


def test_banking_r7_freezes_reply_v5_and_direct_lineage_protocol() -> None:
    config = load_formal_config(Path("configs/formal_experiment_r7.yaml"))
    protocol = load_execution_protocol(
        Path(config.execution_protocol_config or "missing")
    )
    study = load_study_plan(Path(config.study_plan_config or "missing"))
    calibration = load_reply_lineage_calibration(
        Path(protocol.reply_lineage_calibration_artifact or "missing")
    )

    assert config.experiment_id == protocol.experiment_id == "EXP_BANKING_R7"
    assert config.baseline_snapshot_id == "R7_A0"
    assert config.dsh_home == "runs/dsh/r7-home"
    assert config.research_artifact_root == "artifacts/research/banking_r7"
    assert protocol.schema_version == "1.5"
    assert protocol.reply_normalization_policy == (
        "bounded_allow_list_v5_missing_name_and_discoverable_wrapper_alias"
    )
    assert protocol.task_attempt_ledger_schema_version == "1.1"
    assert protocol.model_usage_ledger_schema_version == "1.2"
    assert protocol.task_attempt_session_binding_policy == (
        "append_before_first_agent_call_v1"
    )
    assert protocol.model_call_task_identity_policy == (
        "direct_task_trial_seed_attempt_v1"
    )
    assert calibration.artifact_digest == (
        "sha256:91b9c5de24dd65b66cad9925607c0c032823e5464a843b94601439a1e0dcf80f"
    )
    assert computed_protocol_digest(protocol) == (
        "sha256:06b880c8c58ce510ba28137f3bdc87861b51d91428f038e88bce2f612fc42afd"
    )
    assert study.protocol_digest == protocol.protocol_digest
    assert study.supersedes_study_digest == (
        "sha256:971b7fbfc2c993692be74aa45c621e4420c7139fad33f2a9354bacb1cae8845a"
    )
    assert computed_study_digest(study) == (
        "sha256:f614c59406632a5f044e0ffe826ba174586dcfffa21f7fdb90fa5be8fb4a6316"
    )
    assert study.core_target_trial_count == 560

    pricing = load_pilot_pricing(Path(config.pricing_config))
    with pytest.raises(ValueError, match="reply-lineage runtime binding mismatch"):
        _verified_protocol(
            Path(".").resolve(),
            config,
            objective_digest=protocol.objective_digest,
            split_digest=protocol.split_digest,
            pricing=pricing,
        )


def test_banking_r11_existing_only_allows_runtime_repair_but_keeps_artifacts_pinned() -> None:
    config = load_formal_config(Path("configs/formal_experiment_r11.yaml"))
    protocol = load_execution_protocol(
        Path(config.execution_protocol_config or "missing")
    )
    pricing = load_pilot_pricing(Path(config.pricing_config))

    verified = _verified_protocol(
        Path(".").resolve(),
        config,
        objective_digest=protocol.objective_digest,
        split_digest=protocol.split_digest,
        pricing=pricing,
        allow_runtime_binding_mismatch=True,
    )

    assert verified is not None
    assert verified.protocol_digest == protocol.protocol_digest


def test_banking_r7_rejects_tampered_reply_lineage_calibration(
    tmp_path: Path,
) -> None:
    source = Path("artifacts/research/banking_r7/reply_lineage_calibration.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["accepted_reply_shapes"][0] += " with an unreviewed relaxation"
    target = tmp_path / "tampered.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="calibration digest mismatch"):
        load_reply_lineage_calibration(target)


def test_banking_r8_freezes_direct_frozen_price_cost_authority() -> None:
    config = load_formal_config(Path("configs/formal_experiment_r8.yaml"))
    protocol = load_execution_protocol(
        Path(config.execution_protocol_config or "missing")
    )
    study = load_study_plan(Path(config.study_plan_config or "missing"))
    reply = load_reply_lineage_calibration(
        Path(protocol.reply_lineage_calibration_artifact or "missing")
    )
    cost = load_cost_lineage_calibration(
        Path(protocol.cost_lineage_calibration_artifact or "missing")
    )

    assert config.experiment_id == protocol.experiment_id == "EXP_BANKING_R8"
    assert config.baseline_snapshot_id == "R8_A0"
    assert config.dsh_home == "runs/dsh/r8-home"
    assert config.research_artifact_root == "artifacts/research/banking_r8"
    assert protocol.schema_version == "1.6"
    assert protocol.cost_authority_policy == (
        "verified_tokens_times_frozen_prices_v1"
    )
    assert protocol.valid_cost_lineage_policy == (
        "direct_final_task_attempt_calls_v1"
    )
    assert protocol.raw_cost_evidence_policy == "comparison_only_v1"
    assert protocol.positive_token_zero_cost_policy == (
        "reject_positive_frozen_contribution_v1"
    )
    assert reply.artifact_digest == (
        "sha256:36c9b5a07ff823a822fdd8d0cbd6a298207479fe7426736a681886a552437bb5"
    )
    assert cost.artifact_digest == (
        "sha256:d02c62c61e2106a1812ac1e20cd9b9fab6e2c3f1feac40b85d59c2287e8cb82e"
    )
    assert computed_protocol_digest(protocol) == (
        "sha256:666ea21df159b32aaeefb7b61ccab054be074c832c9d4c61dd82535a9b912939"
    )
    assert study.protocol_digest == protocol.protocol_digest
    assert study.supersedes_study_digest == (
        "sha256:f614c59406632a5f044e0ffe826ba174586dcfffa21f7fdb90fa5be8fb4a6316"
    )
    assert computed_study_digest(study) == (
        "sha256:a0083f246521cfe1a3a4a208d5b81491ef9dfdd9d94582b9d6b50b6d483cf3bc"
    )
    assert study.core_target_trial_count == 560

    pricing = load_pilot_pricing(Path(config.pricing_config))
    with pytest.raises(ValueError, match="reply-lineage runtime binding mismatch"):
        _verified_protocol(
            Path(".").resolve(),
            config,
            objective_digest=protocol.objective_digest,
            split_digest=protocol.split_digest,
            pricing=pricing,
        )


def test_banking_r9_binds_direct_agent_user_cost_to_gate() -> None:
    config = load_formal_config(Path("configs/formal_experiment_r9.yaml"))
    protocol = load_execution_protocol(
        Path(config.execution_protocol_config or "missing")
    )
    study = load_study_plan(Path(config.study_plan_config or "missing"))
    cost = load_cost_lineage_calibration(
        Path(protocol.cost_lineage_calibration_artifact or "missing")
    )

    assert config.experiment_id == protocol.experiment_id == "EXP_BANKING_R9"
    assert protocol.schema_version == "1.7"
    assert protocol.cost_gate_input_policy == (
        "direct_valid_agent_plus_user_mean_v1"
    )
    assert cost.schema_version == "1.1"
    assert cost.cost_gate_input_policy == protocol.cost_gate_input_policy
    assert computed_protocol_digest(protocol) == (
        "sha256:be118f2fc3b2d2cbba5a70f3ad819bbafd8711234dab9bb8160c5702eef669f3"
    )
    assert study.protocol_digest == protocol.protocol_digest
    assert study.supersedes_study_digest == (
        "sha256:a0083f246521cfe1a3a4a208d5b81491ef9dfdd9d94582b9d6b50b6d483cf3bc"
    )
    assert computed_study_digest(study) == (
        "sha256:d471e383ad8f7084c345cb025a022f43671c10ff6b50db0a713571dee2200766"
    )
    assert study.core_target_trial_count == 560

    pricing = load_pilot_pricing(Path(config.pricing_config))
    with pytest.raises(ValueError, match="reply-lineage runtime binding mismatch"):
        _verified_protocol(
            Path(".").resolve(),
            config,
            objective_digest=protocol.objective_digest,
            split_digest=protocol.split_digest,
            pricing=pricing,
        )


def test_banking_r10_binds_scoped_evaluator_correction_and_core560() -> None:
    config = load_formal_config(Path("configs/formal_experiment_r10.yaml"))
    protocol = load_execution_protocol(
        Path(config.execution_protocol_config or "missing")
    )
    study = load_study_plan(Path(config.study_plan_config or "missing"))
    reply = load_reply_lineage_calibration(
        Path(protocol.reply_lineage_calibration_artifact or "missing")
    )
    cost = load_cost_lineage_calibration(
        Path(protocol.cost_lineage_calibration_artifact or "missing")
    )
    evaluator = load_evaluator_correction_calibration(
        Path(protocol.evaluator_correction_calibration_artifact or "missing")
    )

    assert config.experiment_id == protocol.experiment_id == "EXP_BANKING_R10"
    assert config.baseline_snapshot_id == "R10_A0"
    assert config.dsh_home == "runs/dsh/r10-home"
    assert protocol.schema_version == "1.8"
    assert protocol.evaluator_conflict_policy == (
        "all_expected_actions_matched_db_mismatch_hold_v1"
    )
    assert protocol.evaluator_correction_policy == (
        "versioned_overlay_symmetric_affected_rerun_v1"
    )
    assert protocol.evaluator_overlay_digest == (
        "sha256:1f4c96e3ee85862e1fa3ed4e1d2fd7be00844ca88cbb9f583d64b0867921b62d"
    )
    assert evaluator.affected_task_ids == ["task_053"]
    assert reply.artifact_digest == protocol.reply_lineage_calibration_digest
    assert cost.artifact_digest == protocol.cost_lineage_calibration_digest
    assert evaluator.artifact_digest == (
        protocol.evaluator_correction_calibration_digest
    )
    assert computed_protocol_digest(protocol) == (
        "sha256:ab548c787da64f2ae3326753eca5f7c7b159c159ec84a96e9b287cb1459a8672"
    )
    assert study.protocol_digest == protocol.protocol_digest
    assert study.supersedes_study_digest == (
        "sha256:d471e383ad8f7084c345cb025a022f43671c10ff6b50db0a713571dee2200766"
    )
    assert computed_study_digest(study) == (
        "sha256:188c4bec10d842208c3adb173c9a824b2660d251a794b6a38fb2ae954773395a"
    )
    assert study.core_target_trial_count == 560

    pricing = load_pilot_pricing(Path(config.pricing_config))
    with pytest.raises(ValueError, match="runtime binding mismatch"):
        _verified_protocol(
            Path(".").resolve(),
            config,
            objective_digest=protocol.objective_digest,
            split_digest=protocol.split_digest,
            pricing=pricing,
        )


def test_banking_r11_freezes_corrected_selection_and_paid_scope() -> None:
    config = load_formal_config(Path("configs/formal_experiment_r11.yaml"))
    protocol = load_execution_protocol(
        Path(config.execution_protocol_config or "missing")
    )
    study = load_study_plan(Path(config.study_plan_config or "missing"))

    assert config.schema_version == "1.2"
    assert config.experiment_id == protocol.experiment_id == "EXP_BANKING_R11"
    assert config.baseline_snapshot_id == "R11_A2"
    assert config.paid_execution_authorization_root == (
        "runs/authorizations/EXP_BANKING_R11"
    )
    assert protocol.schema_version == "1.8"
    assert study.schema_version == "1.2"
    assert study.protocol_digest == protocol.protocol_digest
    assert study.supersedes_study_digest == (
        "sha256:188c4bec10d842208c3adb173c9a824b2660d251a794b6a38fb2ae954773395a"
    )
    assert study.core_target_trial_count == 575
    assert sum(row.target_trials for row in study.matrix[:3]) == 125
    assert sum(row.target_trials for row in study.matrix[3:]) == 450
    selection = next(
        row for row in study.matrix if row.stage is FormalStage.SELECTION
    )
    assert selection.variant_count == 4
    assert selection.target_trials == 60
    assert study.selection_whole_attempt_cost_ratio_max == Decimal("1.2")
    assert study.selection_p95_latency_ratio_max == Decimal("1.2")
    assert study.selection_max_retry_increase == 0
    assert study.selection_max_timeout_increase == 0

    assert protocol.protocol_digest == (
        "sha256:68b03d74f7195b80928c61fdd79f713fe3bcbba0c0df3b054763c4d88bb663ea"
    )
    assert study.study_digest == (
        "sha256:97de7e47fd2328f568b74b70f23cc6347adae477d9bc1db81984ec641ca05ebb"
    )


def test_banking_r3_ablation_outputs_are_isolated_from_r2() -> None:
    orchestrator = FormalExperimentOrchestrator(
        Path("."),
        config_path=Path("configs/formal_experiment_r3.yaml"),
    )

    path = orchestrator._research_ablation_path("selector_v2.json")

    assert path == (
        Path.cwd() / "artifacts/research/banking_r3/ablations/selector_v2.json"
    )
    assert "banking_r2" not in path.as_posix()


def test_banking_r3_rejects_tampered_execution_calibration(tmp_path: Path) -> None:
    config = load_formal_config(Path("configs/formal_experiment_r3.yaml"))
    protocol_source = Path(config.execution_protocol_config or "missing")
    protocol_target = tmp_path / protocol_source
    protocol_target.parent.mkdir(parents=True)
    protocol_target.write_bytes(protocol_source.read_bytes())

    calibration_source = Path("artifacts/research/banking_r3/execution_calibration.json")
    calibration_target = tmp_path / calibration_source
    calibration_target.parent.mkdir(parents=True)
    calibration = json.loads(calibration_source.read_text(encoding="utf-8"))
    calibration["accepted_controls"]["agent_max_output_tokens"] = 4096
    calibration_target.write_text(
        json.dumps(calibration, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    pricing = load_pilot_pricing(Path(config.pricing_config))
    protocol = load_execution_protocol(protocol_source)
    with pytest.raises(ValueError, match="execution calibration evidence digest mismatch"):
        _verified_protocol(
            tmp_path,
            config,
            objective_digest=protocol.objective_digest,
            split_digest=protocol.split_digest,
            pricing=pricing,
        )


def test_formal_batch_identity_is_bound_to_execution_protocol() -> None:
    legacy = _batch_spec()
    r2 = legacy.model_copy(update={"protocol_digest": DIGEST_C})

    assert legacy.batch_id != r2.batch_id
    assert legacy.protocol_digest is None
    assert r2.protocol_digest == DIGEST_C


def test_code_revision_hashes_uncommitted_public_tree_without_committing(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    source = tmp_path / "agentloopgate/source.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")

    first = _code_revision(tmp_path)
    source.write_text("value = 2\n", encoding="utf-8")
    second = _code_revision(tmp_path)

    harness = tmp_path / "harness/system_prompt.md"
    harness.parent.mkdir()
    harness.write_text("mutable harness\n", encoding="utf-8")
    after_harness_change = _code_revision(tmp_path)
    artifact = tmp_path / "artifacts/result.json"
    artifact.parent.mkdir()
    artifact.write_text("{}\n", encoding="utf-8")
    after_artifact_change = _code_revision(tmp_path)

    assert first is not None and first.startswith("tree:sha256:")
    assert second is not None and second != first
    assert after_harness_change == second
    assert after_artifact_change == second


class _FakeBatchExecutor:
    def __init__(self, execution: FormalBatchExecution) -> None:
        self.execution = execution
        self.calls = 0

    def execute(self, spec: FormalBatchSpec) -> FormalBatchExecution:
        self.calls += 1
        assert spec.task_ids == ["task_001"]
        return self.execution


def test_formal_batch_runs_once_then_verifies_and_resumes(tmp_path: Path) -> None:
    execution = _formal_execution(tmp_path)
    executor = _FakeBatchExecutor(execution)
    runner = FormalBatchRunner(tmp_path, executor)
    spec = _batch_spec()

    first = runner.run(spec)
    second = runner.run(spec)

    assert first.resumed is False
    assert second.resumed is True
    assert executor.calls == 1
    assert first.artifact.summary.stable_success_task_count == 1
    assert first.artifact.batch_digest == second.artifact.batch_digest

    record_path = tmp_path / "runs/normalized/R_TAU_001.json"
    record_path.write_text(record_path.read_text().replace('"success":true', '"success":false'))
    with pytest.raises(FormalBatchError, match="receipt"):
        runner.run(spec)


def test_protocol_bound_batch_records_attempt_usage_and_cost_before_resume(
    tmp_path: Path,
) -> None:
    execution = _formal_execution(tmp_path)
    executor = _FakeBatchExecutor(execution)
    runner = FormalBatchRunner(tmp_path, executor)
    spec = _batch_spec().model_copy(update={"protocol_digest": DIGEST_C})
    manifest = tmp_path / "snapshots/A0/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"code_revision": "tree:sha256:" + "d" * 64}),
        encoding="utf-8",
    )

    first = runner.run(spec)
    second = runner.run(spec)

    assert first.resumed is False
    assert second.resumed is True
    cost_path = tmp_path / f"runs/experiments/EXP_TEST/costs/{spec.batch_id}.json"
    cost = json.loads(cost_path.read_text(encoding="utf-8"))
    assert cost["accounting_status"] == "partial"
    assert cost["total_cost_lower_bound_usd"] == "0.0012"
    assert cost["agent_input_tokens"] == 8
    assert cost["agent_cache_read_tokens"] == 2
    assert cost["agent_output_tokens"] == 2
    assert first.artifact.disposition == "hold"
    assert first.artifact.hold_reasons == ["cost_accounting:partial"]
    events = ExperimentAttemptLedger(tmp_path, "EXP_TEST").events_for_batch(
        spec.batch_id
    )
    assert [event.state.value for event in events].count("started") == 2
    completed = [event for event in events if event.state.value == "completed"]
    assert len(completed) == 2
    assert completed[0].cost_status.value == "partial"
    assert completed[1].resumed is True
    assert completed[1].cost_status.value == "not_applicable"


def test_valid_cost_gate_reports_partial_whole_attempt_without_holding_valid_batch(
    tmp_path: Path,
) -> None:
    execution = _formal_execution(tmp_path)

    class _EnhancedExecutor(_FakeBatchExecutor):
        cost_gate_scope = "valid_runs"

        def user_model_usage_path(self, spec):
            return (
                tmp_path
                / "runs/experiments/EXP_TEST/user_model_usage"
                / f"{spec.batch_id}.jsonl"
            )

    executor = _EnhancedExecutor(execution)
    runner = FormalBatchRunner(tmp_path, executor)
    spec = _batch_spec().model_copy(update={"protocol_digest": DIGEST_C})
    manifest = tmp_path / "snapshots/A0/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"code_revision": "tree:sha256:" + "d" * 64}),
        encoding="utf-8",
    )
    agent_usage = (
        tmp_path
        / "runs/experiments/EXP_TEST/model_usage"
        / f"{spec.batch_id}.jsonl"
    )
    user_usage = executor.user_model_usage_path(spec)
    _append_usage_pair(agent_usage, "MC_AGENT", Decimal("0.0012"))
    _append_usage_pair(user_usage, "MC_USER_OK", Decimal("0.0002"))
    base = {
        "call_id": "MC_USER_FAILED",
        "session_id_hash": DIGEST_A,
        "model": "deepseek/deepseek-v4-flash",
        "provider_retry_count": 0,
    }
    append_model_call_event(
        user_usage,
        make_model_call_event(
            **base,
            state=AttemptState.STARTED,
            cost_status=CostStatus.PENDING,
        ),
    )
    append_model_call_event(
        user_usage,
        make_model_call_event(
            **base,
            state=AttemptState.FAILED,
            cost_status=CostStatus.UNAVAILABLE,
            error_type="FixtureError",
        ),
    )

    result = runner.run(spec)

    cost_path = tmp_path / f"runs/experiments/EXP_TEST/costs/{spec.batch_id}.json"
    cost = json.loads(cost_path.read_text(encoding="utf-8"))
    assert cost["schema_version"] == "1.2"
    assert cost["valid_cost_status"] == "exact"
    assert cost["accounting_status"] == "partial"
    assert cost["user_model_call_count"] == 2
    assert result.artifact.disposition == "complete"
    assert result.artifact.hold_reasons == []


def test_valid_cost_uses_direct_task_attempt_calls_not_raw_display_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _formal_execution(tmp_path)

    class _DirectExecutor(_FakeBatchExecutor):
        cost_gate_scope = "valid_runs"

        def model_usage_path(self, spec):
            return (
                tmp_path
                / "runs/experiments/EXP_TEST/model_usage"
                / f"{spec.batch_id}.jsonl"
            )

        def user_model_usage_path(self, spec):
            return (
                tmp_path
                / "runs/experiments/EXP_TEST/user_model_usage"
                / f"{spec.batch_id}.jsonl"
            )

        def task_attempt_path(self, spec):
            return (
                tmp_path
                / "runs/experiments/EXP_TEST/task_attempts"
                / f"{spec.batch_id}.jsonl"
            )

        def frozen_token_prices(self):
            return (Decimal("100"), Decimal("0"), Decimal("200"))

    executor = _DirectExecutor(execution)
    spec = _batch_spec().model_copy(update={"protocol_digest": DIGEST_C})
    manifest = tmp_path / "snapshots/A0/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"code_revision": "tree:sha256:" + "d" * 64}),
        encoding="utf-8",
    )
    identity = {
        "task_id": "task_001",
        "trial": 0,
        "seed": 300,
        "task_attempt_index": 1,
    }
    _append_usage_pair(
        executor.model_usage_path(spec),
        "MC_DIRECT_AGENT",
        Decimal("0.0012"),
        **identity,
    )
    _append_usage_pair(
        executor.user_model_usage_path(spec),
        "MC_DIRECT_USER",
        Decimal("0.0002"),
        input_tokens=0,
        cache_read_tokens=0,
        output_tokens=1,
        **identity,
    )
    monkeypatch.setenv("AGENTLOOPGATE_TASK_ATTEMPT_LEDGER_SCHEMA_VERSION", "1.1")
    task_path = executor.task_attempt_path(spec)
    task_fields = {
        "task_id": "task_001",
        "trial": 0,
        "seed": 300,
        "attempt_index": 1,
    }
    _append_task_event(task_path, state="started", **task_fields)
    _append_task_event(
        task_path,
        state="session_bound",
        session_id_hash=DIGEST_A,
        source_locator=f"dsh-session:{DIGEST_A}",
        **task_fields,
    )
    _append_task_event(
        task_path,
        state="completed",
        duration_ms=100,
        simulation_id="SIM_001",
        termination_reason="TerminationReason.AGENT_STOP",
        agent_cost_usd=Decimal("0.001"),
        user_cost_usd=Decimal("0.0002"),
        message_count=2,
        session_binding_status="bound",
        session_id_hash=DIGEST_A,
        source_locator=f"dsh-session:{DIGEST_A}",
        **task_fields,
    )

    result = FormalBatchRunner(tmp_path, executor).run(spec)

    cost_path = tmp_path / f"runs/experiments/EXP_TEST/costs/{spec.batch_id}.json"
    cost = json.loads(cost_path.read_text(encoding="utf-8"))
    assert cost["schema_version"] == "1.4"
    assert cost["valid_cost_source"] == "direct_task_attempt_model_calls"
    assert cost["valid_agent_cost_usd"] == "0.0012"
    assert cost["valid_user_cost_usd"] == "0.0002"
    assert cost["scored_valid_mean_total_cost_usd"] == "0.0014"
    assert cost["raw_valid_agent_cost_usd"] == "0.001"
    assert cost["raw_direct_cost_mismatch_count"] == 1
    assert cost["valid_cost_status"] == "exact"
    assert result.artifact.disposition == "complete"
    assert result.artifact.summary.schema_version == "1.1"
    assert result.artifact.summary.cost_source == "direct_task_attempt_model_calls"
    assert result.artifact.summary.cost_status == "exact"
    assert result.artifact.summary.cost_digest == cost["cost_digest"]
    assert result.artifact.summary.mean_cost == Decimal("0.0014")

    orchestrator = object.__new__(FormalExperimentOrchestrator)
    orchestrator._record = lambda run_id: execution.result.records[0]
    mean_cost, _ = orchestrator._runtime_metrics([result.artifact])
    assert mean_cost == Decimal("0.0014")
    assert mean_cost != execution.result.records[0].cost


def test_direct_cost_rejects_positive_tokens_encoded_as_exact_zero(
    tmp_path: Path,
) -> None:
    usage = tmp_path / "false-zero.jsonl"
    identity = {
        "task_id": "task_001",
        "trial": 0,
        "seed": 300,
        "task_attempt_index": 1,
    }
    _append_usage_pair(
        usage,
        "MC_FALSE_ZERO",
        Decimal(0),
        input_tokens=1,
        cache_read_tokens=0,
        output_tokens=0,
        **identity,
    )

    with pytest.raises(ValueError, match="does not match frozen token prices"):
        ledger_module._direct_channel_cost(
            usage,
            {("task_001", 0, 300, 1): False},
            frozen_token_prices=(Decimal("0.14"), Decimal("0.014"), Decimal("0.28")),
            channel="user",
        )


def test_direct_cost_retains_infra_invalid_final_failed_task_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _formal_execution(tmp_path, infrastructure_error=True)

    class _DirectExecutor(_FakeBatchExecutor):
        cost_gate_scope = "valid_runs"

        def model_usage_path(self, spec):
            return (
                tmp_path
                / "runs/experiments/EXP_TEST/model_usage"
                / f"{spec.batch_id}.jsonl"
            )

        def user_model_usage_path(self, spec):
            return (
                tmp_path
                / "runs/experiments/EXP_TEST/user_model_usage"
                / f"{spec.batch_id}.jsonl"
            )

        def task_attempt_path(self, spec):
            return (
                tmp_path
                / "runs/experiments/EXP_TEST/task_attempts"
                / f"{spec.batch_id}.jsonl"
            )

        def frozen_token_prices(self):
            return (Decimal("100"), Decimal("0"), Decimal("200"))

    executor = _DirectExecutor(execution)
    spec = _batch_spec().model_copy(update={"protocol_digest": DIGEST_C})
    manifest = tmp_path / "snapshots/A0/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"code_revision": "tree:sha256:" + "d" * 64}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTLOOPGATE_TASK_ATTEMPT_LEDGER_SCHEMA_VERSION", "1.1")
    task_path = executor.task_attempt_path(spec)
    task_fields = {
        "task_id": "task_001",
        "trial": 0,
        "seed": 300,
        "attempt_index": 2,
    }
    _append_task_event(task_path, state="started", **task_fields)
    _append_task_event(
        task_path,
        state="session_bound",
        session_id_hash=DIGEST_A,
        source_locator=f"dsh-session:{DIGEST_A}",
        **task_fields,
    )
    _append_task_event(
        task_path,
        state="failed",
        duration_ms=100,
        error_type="Tau3PilotError",
        error_message="fixture infrastructure failure",
        session_binding_status="bound",
        session_id_hash=DIGEST_A,
        source_locator=f"dsh-session:{DIGEST_A}",
        **task_fields,
    )

    result = FormalBatchRunner(tmp_path, executor).run(spec)

    cost_path = tmp_path / f"runs/experiments/EXP_TEST/costs/{spec.batch_id}.json"
    cost = json.loads(cost_path.read_text(encoding="utf-8"))
    assert cost["infra_invalid_count"] == 1
    assert cost["valid_run_count"] == 0
    assert result.artifact.disposition == "hold"
    assert "infra_invalid:1" in result.artifact.hold_reasons


def test_protocol_bound_batch_failure_is_logged_with_unknown_cost(tmp_path: Path) -> None:
    class _FailingExecutor:
        def execute(self, spec):
            raise RuntimeError("fixture execution failed")

    spec = _batch_spec().model_copy(update={"protocol_digest": DIGEST_C})
    manifest = tmp_path / "snapshots/A0/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"code_revision": "tree:sha256:" + "d" * 64}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="fixture execution failed"):
        FormalBatchRunner(tmp_path, _FailingExecutor()).run(spec)

    events = ExperimentAttemptLedger(tmp_path, "EXP_TEST").events_for_batch(
        spec.batch_id
    )
    assert [event.state.value for event in events] == ["started", "failed"]
    assert events[-1].cost_status.value == "unavailable"
    assert events[-1].known_cost_usd is None
    assert events[-1].error_type == "RuntimeError"


def test_failed_batch_recovers_raw_user_and_agent_cost_lower_bound(tmp_path: Path) -> None:
    spec = _batch_spec().model_copy(update={"protocol_digest": DIGEST_C})

    class _FailingAfterRawExecutor:
        def execute(self, _spec):
            raw = (
                tmp_path
                / "runs/experiments/EXP_TEST/raw"
                / f"{spec.batch_id}.json"
            )
            raw.parent.mkdir(parents=True)
            raw.write_text(
                json.dumps({"simulations": [{"user_cost": "0.25"}]}) + "\n",
                encoding="utf-8",
            )
            usage = (
                tmp_path
                / "runs/experiments/EXP_TEST/model_usage"
                / f"{spec.batch_id}.jsonl"
            )
            base = {
                "call_id": "MC_FIXTURE",
                "session_id_hash": DIGEST_A,
                "model": "fixture/model",
            }
            append_model_call_event(
                usage,
                make_model_call_event(
                    **base,
                    state=AttemptState.STARTED,
                    cost_status=CostStatus.PENDING,
                ),
            )
            append_model_call_event(
                usage,
                make_model_call_event(
                    **base,
                    state=AttemptState.FAILED,
                    input_tokens=10,
                    cache_read_tokens=2,
                    output_tokens=3,
                    provider_retry_count=0,
                    cost_usd=Decimal("0.50"),
                    cost_status=CostStatus.EXACT,
                    error_type="FixtureError",
                ),
            )
            raise RuntimeError("ingest failed after raw result was retained")

    manifest = tmp_path / "snapshots/A0/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"code_revision": "tree:sha256:" + "d" * 64}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="ingest failed"):
        FormalBatchRunner(tmp_path, _FailingAfterRawExecutor()).run(spec)

    terminal = ExperimentAttemptLedger(tmp_path, "EXP_TEST").events_for_batch(
        spec.batch_id
    )[-1]
    assert terminal.cost_status is CostStatus.PARTIAL
    assert terminal.known_cost_usd == Decimal("0.75")
    assert set(terminal.result_artifacts) == {"model_usage", "raw"}


def test_formal_batch_seals_retry_exhausted_infra_evidence_as_hold(
    tmp_path: Path,
) -> None:
    execution = _formal_execution(tmp_path, infrastructure_error=True)
    runner = FormalBatchRunner(tmp_path, _FakeBatchExecutor(execution))

    result = runner.run(_batch_spec())

    assert result.artifact.disposition == "hold"
    assert result.artifact.hold_reasons == ["infra_invalid:1", "missing_valid_trials"]
    assert result.artifact.summary.valid_run_count == 0
    assert result.artifact.summary.infra_invalid_count == 1
    assert result.artifact.summary.integrity_complete is False
    assert result.artifact.summary.mean_cost == 0


def test_orchestrator_stops_when_a_formal_batch_is_held(tmp_path: Path) -> None:
    execution = _formal_execution(tmp_path, infrastructure_error=True)
    held = FormalBatchRunner(tmp_path, _FakeBatchExecutor(execution)).run(
        _batch_spec()
    )

    class _HeldStageService:
        def run_stage(self, stage, *, snapshot_id):
            assert stage == "release_id"
            assert snapshot_id == "A0"
            return held

    orchestrator = object.__new__(FormalExperimentOrchestrator)
    orchestrator.service = _HeldStageService()

    with pytest.raises(FormalWorkflowBlocked, match="sealed HOLD"):
        orchestrator._completed_stage("release_id", snapshot_id="A0")


def test_selection_hold_is_normal_terminal_and_starts_no_release_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Snapshots:
        def __init__(self, _root: Path) -> None:
            pass

        @staticmethod
        def verify(snapshot_id: str) -> SimpleNamespace:
            return SimpleNamespace(snapshot_id=snapshot_id, code_revision="tree:fixture")

    monkeypatch.setattr(orchestrator_module, "SnapshotManager", _Snapshots)
    orchestrator = object.__new__(FormalExperimentOrchestrator)
    orchestrator.root = tmp_path
    orchestrator.experiment_root = tmp_path / "runs/experiments/EXP_HOLD"
    orchestrator.config = SimpleNamespace(
        schema_version="1.2", experiment_id="EXP_HOLD"
    )
    orchestrator.ensure_evaluation_baseline = lambda: "A0"
    stage_calls: list[tuple[str, str]] = []

    def completed_stage(stage, *, snapshot_id):
        stage_calls.append((str(stage), snapshot_id))
        return SimpleNamespace(batch_id=f"B_{len(stage_calls):02d}")

    orchestrator._completed_stage = completed_stage
    orchestrator._diagnose = lambda _batch: SimpleNamespace()
    candidates = [
        _candidate(f"C_{index}", ["prompt_instruction"]) for index in range(1, 4)
    ]
    orchestrator._propose = lambda _baseline, _diagnosis: candidates
    orchestrator._materialize = lambda _candidates: ["S_1", "S_2", "S_3"]
    transitions: list[tuple[str, str]] = []
    orchestrator._advance = lambda candidate_id, status, **_kwargs: transitions.append(
        (candidate_id, str(status))
    )
    hold_selection = SimpleNamespace(
        selection=SimpleNamespace(agentloopgate_decision="HOLD"),
        selection_digest=DIGEST_A,
    )
    orchestrator._select = lambda *_args: hold_selection
    orchestrator._lineage = lambda *_args: SimpleNamespace(lineage_digest=DIGEST_B)
    expected = SimpleNamespace(
        outcome_kind="selection_hold", report_file_digests={}
    )
    orchestrator._seal_selection_hold_outcome = lambda **_kwargs: expected
    orchestrator._record_no_model_operation = (
        lambda **kwargs: kwargs["action"]()
    )

    outcome = orchestrator.run()

    assert outcome is expected
    assert [stage for stage, _snapshot in stage_calls].count("update_source") == 1
    assert [stage for stage, _snapshot in stage_calls].count("update_check") == 4
    assert [stage for stage, _snapshot in stage_calls].count("selection") == 4
    assert not {
        "release_id",
        "release_ood",
        "replay",
    }.intersection(stage for stage, _snapshot in stage_calls)
    assert transitions[-3:] == [
        ("C_1", "held"),
        ("C_2", "held"),
        ("C_3", "held"),
    ]


def test_selection_hold_seals_reports_and_reconciles_model_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Snapshots:
        def __init__(self, _root: Path) -> None:
            pass

        @staticmethod
        def verify(_snapshot_id: str) -> SimpleNamespace:
            return SimpleNamespace(code_revision="tree:fixture")

    monkeypatch.setattr(orchestrator_module, "SnapshotManager", _Snapshots)
    orchestrator = object.__new__(FormalExperimentOrchestrator)
    orchestrator.root = tmp_path
    orchestrator.experiment_root = tmp_path / "runs/experiments/EXP_HOLD"
    orchestrator.config = SimpleNamespace(experiment_id="EXP_HOLD")
    orchestrator._versioned_protocol_and_study = lambda: (
        SimpleNamespace(protocol_digest=DIGEST_A),
        SimpleNamespace(study_digest=DIGEST_B),
    )
    orchestrator._exact_batch_model_cost = lambda _batches: (
        Decimal("1.25"),
        ["runs/experiments/EXP_HOLD/costs/B_01.json"],
    )
    orchestrator._updater_model_cost = lambda: (
        Decimal("0.125"),
        "exact",
        0,
        [],
        ["runs/updaters/ahe/attempts/AHEATT_1/terminal.json"],
    )
    selection = SimpleNamespace(
        selection=SimpleNamespace(
            agentloopgate_decision="HOLD",
            agentloopgate_candidate_id=None,
            native_candidate_id="C_1",
            decision_reason="no_candidate_passed_baseline_bound_selection_policy",
            governance_findings={
                "C_1": ["no_stable_success_gain"],
                "C_2": ["stable_task_regression:task_001"],
                "C_3": ["p95_latency_noninferiority"],
            },
        ),
        selection_digest=DIGEST_C,
    )
    candidates = [
        _candidate(f"C_{index}", ["prompt_instruction"]) for index in range(1, 4)
    ]
    batches = [SimpleNamespace(batch_id="B_01", stage="selection")]
    outcome_path = orchestrator.experiment_root / "selection_hold_outcome.json"

    outcome = orchestrator._seal_selection_hold_outcome(
        path=outcome_path,
        baseline_snapshot_id="A0",
        candidates=candidates,
        candidate_snapshot_ids=["S_1", "S_2", "S_3"],
        batches=batches,
        selection=selection,
        lineage=SimpleNamespace(lineage_digest=DIGEST_A),
    )

    assert isinstance(outcome, FormalSelectionHoldOutcome)
    assert outcome.final_decision.value == "HOLD"
    assert outcome.agentloopgate_candidate_id is None
    assert outcome.batch_model_cost_usd == Decimal("1.25")
    assert outcome.updater_model_cost_usd == Decimal("0.125")
    assert outcome.total_known_model_cost_usd == Decimal("1.375")
    assert outcome.cost_status == "exact"
    assert outcome.release_batch_count == outcome.model_calls_after_selection == 0
    assert canonical_digest(
        outcome.model_dump(mode="python", exclude={"outcome_digest"})
    ) == outcome.outcome_digest
    assert outcome_path.is_file()
    for relative, digest in outcome.report_file_digests.items():
        report = tmp_path / relative
        assert report.is_file()
        assert orchestrator_module.file_digest(report) == digest


def test_selection_hold_updater_cost_accounts_for_all_bound_attempts(
    tmp_path: Path,
) -> None:
    orchestrator = object.__new__(FormalExperimentOrchestrator)
    orchestrator.root = tmp_path
    orchestrator.config = SimpleNamespace(experiment_id="EXP_HOLD")
    attempts = tmp_path / "runs/updaters/ahe/attempts"

    def write_attempt(
        attempt_id: str,
        *,
        known_cost: str,
        status: str,
        unresolved: int,
    ) -> None:
        destination = attempts / attempt_id
        destination.mkdir(parents=True)
        started = {
            "schema_version": "1.0",
            "attempt_id": attempt_id,
            "experiment_id": "EXP_HOLD",
            "state": "started",
        }
        terminal = {
            "schema_version": "1.0",
            "attempt_id": attempt_id,
            "known_cost_usd": known_cost,
            "cost_status": status,
            "unresolved_model_call_count": unresolved,
        }
        (destination / "started.json").write_text(
            json.dumps({**started, "attempt_digest": canonical_digest(started)}),
            encoding="utf-8",
        )
        (destination / "terminal.json").write_text(
            json.dumps({**terminal, "attempt_digest": canonical_digest(terminal)}),
            encoding="utf-8",
        )

    write_attempt("AHEATT_1", known_cost="0.10", status="exact", unresolved=0)
    write_attempt("AHEATT_2", known_cost="0.03", status="partial", unresolved=1)

    known, status, unresolved, unknown, refs = orchestrator._updater_model_cost()

    assert known == Decimal("0.13")
    assert status == "partial"
    assert unresolved == 1
    assert unknown == ["non_exact_updater_attempt:AHEATT_2"]
    assert len(refs) == 4


def test_selection_hold_rejects_exact_updater_cost_without_known_amount(
    tmp_path: Path,
) -> None:
    orchestrator = object.__new__(FormalExperimentOrchestrator)
    orchestrator.root = tmp_path
    orchestrator.config = SimpleNamespace(experiment_id="EXP_HOLD")
    destination = tmp_path / "runs/updaters/ahe/attempts/AHEATT_1"
    destination.mkdir(parents=True)
    started = {
        "attempt_id": "AHEATT_1",
        "experiment_id": "EXP_HOLD",
        "state": "started",
    }
    terminal = {
        "attempt_id": "AHEATT_1",
        "known_cost_usd": None,
        "cost_status": "exact",
        "unresolved_model_call_count": 0,
    }
    (destination / "started.json").write_text(
        json.dumps({**started, "attempt_digest": canonical_digest(started)}),
        encoding="utf-8",
    )
    (destination / "terminal.json").write_text(
        json.dumps({**terminal, "attempt_digest": canonical_digest(terminal)}),
        encoding="utf-8",
    )

    with pytest.raises(FormalWorkflowBlocked, match="exact cost is incomplete"):
        orchestrator._updater_model_cost()


def test_selection_hold_lifecycle_can_resume_after_terminal_transition(
    tmp_path: Path,
) -> None:
    orchestrator = object.__new__(FormalExperimentOrchestrator)
    orchestrator.root = tmp_path
    orchestrator.experiment_root = tmp_path / "runs/experiments/EXP_HOLD"
    held_payload = {
        "schema_version": "1.0",
        "candidate_id": "C_1",
        "target_status": "held",
        "sources": ["selection.json", "lineage.json"],
    }
    held = orchestrator.experiment_root / "lifecycle/C_1/held.json"
    held.parent.mkdir(parents=True)
    held.write_text(
        json.dumps(
            {**held_payload, "evidence_digest": canonical_digest(held_payload)}
        ),
        encoding="utf-8",
    )

    class _Registry:
        transitioned = False

        @staticmethod
        def load(_candidate_id: str) -> SimpleNamespace:
            return SimpleNamespace(status=orchestrator_module.CandidateStatus.HELD)

        def transition(self, *_args, **_kwargs) -> None:
            self.transitioned = True

    registry = _Registry()
    orchestrator._registry = lambda: registry

    orchestrator._advance(
        "C_1",
        orchestrator_module.CandidateStatus.UPDATE_EVALUATED,
        sources=["update_check.json"],
    )

    assert registry.transitioned is False


def test_formal_diagnosis_is_conservative_and_redacts_expected_action(
    tmp_path: Path,
) -> None:
    execution = _formal_execution(tmp_path)
    record = execution.result.records[0].model_copy(update={"success": False})
    diagnostic = execution.result.diagnostics[0].model_copy(
        update={
            "db_match": False,
            "action_checks": [
                ActionDiagnostic(
                    name="private_expected_action",
                    matched=False,
                    tool_type="write",
                )
            ],
            "observed_tool_names": [],
        }
    )
    artifact = diagnose_formal_records(
        batch_id="B_TEST",
        records=[record],
        diagnostics=[diagnostic],
        tasks=[
            TaskDescriptor(
                task_id="task_001",
                workflow_family="credit_card",
                high_risk=True,
                document_count=2,
                tool_complexity=1,
            )
        ],
    )

    assert artifact.ranked_bundles[0].bundle.failure_type is FailureType.TOOL_DISCOVERY_ERROR
    assert artifact.unresolved_evaluation_incident_run_ids == []
    assert "private_expected_action" not in artifact.model_dump_json()


def test_formal_diagnosis_holds_all_matched_actions_with_db_mismatch(
    tmp_path: Path,
) -> None:
    execution = _formal_execution(tmp_path)
    record = execution.result.records[0].model_copy(update={"success": False})
    diagnostic = execution.result.diagnostics[0].model_copy(
        update={
            "db_match": False,
            "action_checks": [
                ActionDiagnostic(name="expected_action", matched=True, tool_type="write")
            ],
            "observed_tool_names": ["expected_action"],
        }
    )
    artifact = diagnose_formal_records(
        batch_id="B_CONFLICT",
        records=[record],
        diagnostics=[diagnostic],
        tasks=[
            TaskDescriptor(
                task_id=record.task_id,
                workflow_family="credit_card",
                high_risk=True,
                document_count=1,
                tool_complexity=1,
            )
        ],
    )

    assert artifact.schema_version == "1.1"
    assert artifact.unresolved_evaluation_incident_run_ids == [record.run_id]
    assert artifact.signals[0].evaluator_conflict is True
    assert (
        artifact.ranked_bundles[0].bundle.failure_type
        is FailureType.SPEC_OR_EVALUATOR_ISSUE
    )

    orchestrator = object.__new__(FormalExperimentOrchestrator)
    with pytest.raises(FormalWorkflowBlocked, match="unresolved evaluation incidents"):
        orchestrator._propose("A0", artifact)


def test_formal_candidate_subset_enforces_asset_family_diversity() -> None:
    candidates = [
        _candidate("C_1", ["prompt_instruction"]),
        _candidate("C_2", ["prompt_instruction"]),
        _candidate("C_3", ["prompt_instruction"]),
        _candidate("C_4", ["tool_contract_routing"]),
    ]

    selected = _diverse_subset(candidates, count=3, min_families=2)

    assert [item.candidate_id for item in selected] == ["C_1", "C_2", "C_4"]


def test_r11_candidate_generation_requires_paid_updater_authorization(
    tmp_path: Path,
) -> None:
    orchestrator = object.__new__(FormalExperimentOrchestrator)
    orchestrator.root = tmp_path
    orchestrator.config = SimpleNamespace(schema_version="1.2")

    class _DeniedService:
        @staticmethod
        def verify_updater_generation_authorization(*, snapshot_id: str) -> None:
            assert snapshot_id == "R11_A0"
            raise PaidExecutionAuthorizationError("fixture Owner authorization missing")

    orchestrator.service = _DeniedService()
    diagnosis = SimpleNamespace(
        unresolved_evaluation_incident_run_ids=[],
        ranked_bundles=[
            SimpleNamespace(
                bundle=SimpleNamespace(
                    failure_type=FailureType.TOOL_DISCOVERY_ERROR
                )
            )
        ],
    )

    with pytest.raises(PaidExecutionAuthorizationError, match="Owner authorization"):
        orchestrator._propose("R11_A0", diagnosis)


def test_r2_role_assignment_reports_logical_execution_and_reuse_counts() -> None:
    study = load_study_plan(Path("configs/banking_r2_study_v2.yaml"))

    aliased = _build_role_assignment(
        experiment_id="EXP_BANKING_R2",
        protocol_digest=study.protocol_digest,
        study=study,
        source_revision="tree:sha256:" + "d" * 64,
        baseline_snapshot_id="R2_A0",
        updater_native_candidate_id="C_1",
        updater_native_snapshot_id="S_1",
        agentloopgate_candidate_id="C_1",
        agentloopgate_snapshot_id="S_1",
    )
    independent = _build_role_assignment(
        experiment_id="EXP_BANKING_R2",
        protocol_digest=study.protocol_digest,
        study=study,
        source_revision="tree:sha256:" + "d" * 64,
        baseline_snapshot_id="R2_A0",
        updater_native_candidate_id="C_1",
        updater_native_snapshot_id="S_1",
        agentloopgate_candidate_id="C_2",
        agentloopgate_snapshot_id="S_2",
    )

    assert aliased.logical_core_trial_count == 560
    assert aliased.unique_executed_core_trial_count == 410
    assert aliased.reused_role_trial_count == 150
    assert aliased.role_alias is True
    assert independent.unique_executed_core_trial_count == 560
    assert independent.reused_role_trial_count == 0
    assert independent.role_alias is False


def test_r2_no_model_workflow_steps_record_success_and_failure(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    source = tmp_path / "agentloopgate/source.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    configs = tmp_path / "configs"
    configs.mkdir()
    for name in (
        "formal_experiment_r2.yaml",
        "banking_r2_study_v2.yaml",
        "experiment_protocol_banking_r2_v2.yaml",
    ):
        (configs / name).write_text(
            (Path("configs") / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    orchestrator = object.__new__(FormalExperimentOrchestrator)
    orchestrator.root = tmp_path
    orchestrator.config_path = Path("configs/formal_experiment_r2.yaml")
    orchestrator.config = load_formal_config(configs / "formal_experiment_r2.yaml")
    output = tmp_path / "artifacts/result.json"

    def succeed() -> str:
        output.parent.mkdir()
        output.write_text("{}\n", encoding="utf-8")
        return "ok"

    assert orchestrator._record_no_model_operation(
        operation="fixture_success",
        action=succeed,
        artifact_paths=lambda _result: [output],
    ) == "ok"

    def fail() -> str:
        raise RuntimeError("synthetic deterministic-step failure")

    with pytest.raises(RuntimeError, match="deterministic-step failure"):
        orchestrator._record_no_model_operation(
            operation="fixture_failure",
            action=fail,
            artifact_paths=lambda _result: [],
        )

    event_paths = sorted(
        (
            tmp_path / "runs/experiments/EXP_BANKING_R2/attempt_ledger"
        ).glob("ATT_*/*.json")
    )
    events = [json.loads(path.read_text(encoding="utf-8")) for path in event_paths]
    assert {event["operation"] for event in events} == {
        "fixture_success",
        "fixture_failure",
    }
    assert {event["state"] for event in events} == {
        "started",
        "completed",
        "failed",
    }
    completed = next(event for event in events if event["state"] == "completed")
    failed = next(event for event in events if event["state"] == "failed")
    assert completed["cost_status"] == failed["cost_status"] == "not_applicable"
    assert completed["counters"]["model_calls"] == 0
    assert completed["result_artifacts"]["artifacts/result.json"].startswith(
        "sha256:"
    )
    assert failed["error_type"] == "RuntimeError"


def _candidate(candidate_id: str, families: list[str]) -> CandidateRecord:
    return CandidateRecord.model_validate(
        {
            "schema_version": "1.0",
            "candidate_id": candidate_id,
            "parent_snapshot_id": "A0",
            "failure_bundle_digest": DIGEST_A,
            "updater": {"name": "ahe", "version": "0.1.0@commit"},
            "hypothesis": "one falsifiable change",
            "asset_families": families,
            "risk_tier": "L",
            "patch_path": f"candidates/{candidate_id}/candidate.patch",
            "patch_digest": DIGEST_B,
            "changed_files": ["harness/system_prompt.md"],
            "predicted_effect": {
                "metric": "stable_success_task_count",
                "direction": "increase",
            },
            "status": "checked",
            "created_at": "2026-08-20T00:00:00Z",
        }
    )


def _batch_spec() -> FormalBatchSpec:
    return FormalBatchSpec(
        experiment_id="EXP_TEST",
        stage="update_source",
        pool="update_source",
        snapshot_id="A0",
        candidate_id=None,
        task_ids=["task_001"],
        trials=1,
        agent_model="deepseek-official/deepseek-v4-flash",
        user_model="deepseek/deepseek-v4-flash",
        objective_digest=DIGEST_A,
        split_digest=DIGEST_B,
        benchmark_commit="fc0055dc4e0a316c3f83133267fbd6faaa770992",
        initial_state_digests={"task_001": DIGEST_C},
    )


def _append_usage_pair(
    path: Path,
    call_id: str,
    cost: Decimal,
    input_tokens: int = 8,
    cache_read_tokens: int = 2,
    output_tokens: int = 2,
    **identity,
) -> None:
    base = {
        "call_id": call_id,
        "session_id_hash": DIGEST_A,
        "model": "deepseek/deepseek-v4-flash",
        "provider_retry_count": 0,
        **identity,
    }
    append_model_call_event(
        path,
        make_model_call_event(
            **base,
            state=AttemptState.STARTED,
            cost_status=CostStatus.PENDING,
        ),
    )
    append_model_call_event(
        path,
        make_model_call_event(
            **base,
            state=AttemptState.COMPLETED,
            input_tokens=input_tokens,
            cache_read_tokens=cache_read_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            cost_status=CostStatus.EXACT,
        ),
    )


def _formal_execution(
    root: Path,
    *,
    infrastructure_error: bool = False,
) -> FormalBatchExecution:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    raw = root / "runs/experiments/EXP_TEST/raw/source.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(
        json.dumps(
            {
                "simulations": [
                    {
                        "id": "SIM_001",
                        "task_id": "task_001",
                        "trial": 0,
                        "seed": 300,
                        "termination_reason": (
                            "infrastructure_error"
                            if infrastructure_error
                            else "agent_stop"
                        ),
                        "agent_cost": None if infrastructure_error else 0.001,
                        "user_cost": None if infrastructure_error else 0.0002,
                        "messages": (
                            []
                            if infrastructure_error
                            else [
                                {
                                    "role": "assistant",
                                    "usage": {
                                        "prompt_tokens": 8,
                                        "cache_read_tokens": 2,
                                        "completion_tokens": 2,
                                    },
                                },
                                {
                                    "role": "user",
                                    "usage": {
                                        "prompt_tokens": 3,
                                        "completion_tokens": 1,
                                    },
                                },
                            ]
                        ),
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    store = BenchmarkEvidenceStore(root)
    tau_ref = store.attach(
        raw,
        runtime_host=RuntimeHost.TAU3,
        persistence_kind="tau_raw",
        event_count=1,
        session_identity={"task": "task_001"},
        created_at=now,
    )

    def record_factory(receipt_id: str) -> RunRecord:
        return RunRecord(
            schema_version="1.0",
            run_id="R_TAU_001",
            attempt_id="R_TAU_001:T1",
            task_id="task_001",
            pool="update_source",
            snapshot_id="A0",
            candidate_id=None,
            source=RunSource.TAU3,
            runtime_host=RuntimeHost.TAU3,
            runtime_version="tau2-bench@1.0.1",
            model_id="deepseek-official/deepseek-v4-flash",
            benchmark_commit="fc0055dc4e0a316c3f83133267fbd6faaa770992",
            objective_digest=DIGEST_A,
            split_digest=DIGEST_B,
            initial_state_digest=DIGEST_C,
            terminal_state_digest=DIGEST_A,
            trial_index=1,
            run_validity="infra_invalid" if infrastructure_error else "valid",
            success=None if infrastructure_error else True,
            critical_violations=[],
            input_tokens=10,
            output_tokens=2,
            latency_ms=100,
            cost=None if infrastructure_error else Decimal("0.001"),
            source_trace_ref=tau_ref.source_trace_id,
            evidence_receipt_ref=receipt_id,
            created_at=now,
        )

    def diagnostic_factory(receipt_id: str) -> OutcomeDiagnostics:
        return OutcomeDiagnostics(
            schema_version="1.0",
            run_id="R_TAU_001",
            evidence_ref=receipt_id,
            termination_reason=(
                "infrastructure_error" if infrastructure_error else "agent_stop"
            ),
            reward=None if infrastructure_error else Decimal(1),
            reward_basis=[] if infrastructure_error else ["DB"],
            db_match=None if infrastructure_error else True,
            required_document_count=1,
            action_checks=[],
            observed_tool_names=["lookup"],
        )

    tau, tau_receipt, diagnostic = store.persist_run(
        ref=tau_ref,
        event_index=0,
        record_factory=record_factory,
        diagnostic_factory=diagnostic_factory,
        collected_at=now,
    )
    config = root / "configs/trace_redaction.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("schema_version: '1.0'\n", encoding="utf-8")
    bridge = BridgeService(root)
    session_id = "EXP_TEST:task_001:42"
    assert bridge.handle(
        BridgeRequest(
            protocol_version="1.0",
            request_id="INGEST_001",
            method="events.ingest",
            payload={
                "batch_id": "DSH_BATCH_001",
                "session_id": session_id,
                "persistence_kind": "jsonl",
                "ingest_mode": "reference",
                "events": [
                    {
                        "seq": 0,
                        "timestamp": "2026-08-20T00:00:00Z",
                        "event_type": "turn/end",
                        "data": {"reason": "completed"},
                    }
                ],
            },
        )
    ).ok
    synchronized = bridge.handle(
        BridgeRequest(
            protocol_version="1.0",
            request_id="SYNC_001",
            method="trace.sync",
            payload={
                "session_id": session_id,
                "source_revision": "deepseek-harness@0.1.0-rc.8",
                "persistence_kind": "jsonl",
                "ingest_mode": "reference",
            },
        )
    )
    assert synchronized.ok and synchronized.result is not None
    dsh_ref_id = synchronized.result["source_trace_id"]
    dsh = tau.model_copy(
        update={
            "run_id": "DSH_001",
            "attempt_id": "DSH_001:T1",
            "source": RunSource.DSH,
            "runtime_host": RuntimeHost.DEEPSEEK_HARNESS,
            "runtime_version": "deepseek-harness@0.1.0-rc.8",
            "runtime_profile": "headless",
            "composition_digest": DIGEST_C,
            "source_trace_ref": dsh_ref_id,
            "evidence_receipt_ref": "ER_DSH_001",
        }
    )
    dsh_receipt = EvidenceReceipt(
        schema_version="1.0",
        receipt_id="ER_DSH_001",
        source_trace_id=dsh_ref_id,
        run_id=dsh.run_id,
        event_seq_start=0,
        event_seq_end=0,
        event_count=1,
        redaction_policy_digest=DIGEST_A,
        normalized_record_digest=canonical_digest(dsh),
        collected_at=now,
        error_count=0,
    )
    join = PilotEvidenceJoin(
        schema_version="1.0",
        join_id="PEJ_001",
        task_id="task_001",
        trial_index=1,
        dsh_run_id=dsh.run_id,
        tau_run_id=tau.run_id,
        dsh_source_trace_ref=dsh_ref_id,
        dsh_evidence_receipt_ref=dsh_receipt.receipt_id,
        tau_source_trace_ref=tau_ref.source_trace_id,
        tau_evidence_receipt_ref=tau_receipt.receipt_id,
        session_id_hash=canonical_digest({"session_id": session_id}),
        outcome_success=None if infrastructure_error else True,
        evidence_digest=canonical_digest({"tau": tau.run_id, "dsh": dsh.run_id}),
        created_at=now,
    )
    for family, artifact_id, payload in (
        ("normalized", dsh.run_id, dsh),
        ("receipts", dsh_receipt.receipt_id, dsh_receipt),
        ("evidence_joins", join.join_id, join),
    ):
        store.write_json_once(store.path_for(family, artifact_id), payload.model_dump(mode="json"))
    result = DshTau3PilotResult(
        schema_version="1.0",
        source_trace_ref=tau_ref,
        receipts=[tau_receipt],
        records=[tau],
        diagnostics=[diagnostic],
        dsh_receipts=[dsh_receipt],
        dsh_records=[dsh],
        evidence_joins=[join],
    )
    return FormalBatchExecution(result_path=raw, result=result)
