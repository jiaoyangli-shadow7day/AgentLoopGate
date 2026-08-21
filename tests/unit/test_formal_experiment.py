from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agentloopgate.adapters import DshTau3PilotResult, OutcomeDiagnostics
from agentloopgate.adapters.base import ActionDiagnostic
from agentloopgate.adapters.evidence import BenchmarkEvidenceStore
from agentloopgate.bridge import BridgeRequest, BridgeService
from agentloopgate.contracts import canonical_digest
from agentloopgate.experiment import (
    ExperimentAttemptLedger,
    FormalBatchError,
    FormalBatchExecution,
    FormalBatchRunner,
    FormalBatchSpec,
    computed_protocol_digest,
    computed_study_digest,
    diagnose_formal_records,
    load_execution_protocol,
    load_study_plan,
)
from agentloopgate.experiment.orchestrator import (
    FormalExperimentOrchestrator,
    FormalWorkflowBlocked,
    _build_role_assignment,
    _diverse_subset,
)
from agentloopgate.experiment.service import _code_revision, load_formal_config
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
    assert "private_expected_action" not in artifact.model_dump_json()


def test_formal_candidate_subset_enforces_asset_family_diversity() -> None:
    candidates = [
        _candidate("C_1", ["prompt_instruction"]),
        _candidate("C_2", ["prompt_instruction"]),
        _candidate("C_3", ["prompt_instruction"]),
        _candidate("C_4", ["tool_contract_routing"]),
    ]

    selected = _diverse_subset(candidates, count=3, min_families=2)

    assert [item.candidate_id for item in selected] == ["C_1", "C_2", "C_4"]


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
