"""Synthetic no-model source evidence for promotion integration tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from agentloopgate.adapters import DshTau3PilotResult, OutcomeDiagnostics
from agentloopgate.adapters.evidence import BenchmarkEvidenceStore
from agentloopgate.bridge import BridgeRequest, BridgeService
from agentloopgate.contracts import canonical_digest
from agentloopgate.experiment.batch import FormalBatchExecution, FormalBatchRunner, FormalBatchSpec
from agentloopgate.runtime.tau3_evidence import _append_task_event
from agentloopgate.runtime.usage import append_model_call_event, make_model_call_event
from agentloopgate.schemas import (
    EvidenceReceipt,
    PilotEvidenceJoin,
    RunRecord,
    RunSource,
    RuntimeHost,
)

DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 20, tzinfo=UTC)


class FixtureExecutor:
    cost_gate_scope = "valid_runs"

    def __init__(self, root: Path, spec: FormalBatchSpec):
        self.root = root
        self.spec = spec
        self.calls = 0

    def model_usage_path(self, spec):
        return self.root / "runs/experiments/EXP_TEST/model_usage" / f"{spec.batch_id}.jsonl"

    def user_model_usage_path(self, spec):
        return self.root / "runs/experiments/EXP_TEST/user_model_usage" / f"{spec.batch_id}.jsonl"

    def task_attempt_path(self, spec):
        return self.root / "runs/experiments/EXP_TEST/task_attempts" / f"{spec.batch_id}.jsonl"

    def frozen_token_prices(self):
        return (Decimal("100"), Decimal("0"), Decimal("200"))

    def execute(self, spec):
        assert spec == self.spec
        self.calls += 1
        return create_execution(self.root, spec, self)


def create_execution(root: Path, spec: FormalBatchSpec, executor: FixtureExecutor):
    """Generate canonical, internally consistent synthetic trace and cost artifacts."""
    suffix = spec.batch_id.removeprefix("B_")
    raw = root / "runs/experiments/EXP_TEST/raw" / f"source_{suffix}.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    simulations = []
    for index in range(spec.trials):
        simulations.append(
            {
                "id": f"SIM_{index}",
                "task_id": "task_001",
                "trial": index,
                "seed": 300 + index,
                "termination_reason": "agent_stop",
                "agent_cost": 0.001,
                "user_cost": 0.0002,
                "messages": [
                    {
                        "role": "assistant",
                        "usage": {
                            "prompt_tokens": 8,
                            "cache_read_tokens": 2,
                            "completion_tokens": 2,
                        },
                    },
                    {"role": "user", "usage": {"prompt_tokens": 0, "completion_tokens": 1}},
                ],
            }
        )
    raw.write_text(json.dumps({"simulations": simulations}) + "\n")
    store = BenchmarkEvidenceStore(root)
    ref = store.attach(
        raw,
        runtime_host=RuntimeHost.TAU3,
        persistence_kind="tau_raw",
        event_count=spec.trials,
        session_identity={"batch": spec.batch_id},
        created_at=NOW,
    )
    session = f"fixture-{suffix}"
    bridge = BridgeService(root)

    def bridge_request(method, payload):
        return bridge.handle(
            BridgeRequest(
                protocol_version="1.0",
                request_id=f"REQ_{method.replace('.', '_')}_{suffix}",
                method=method,
                payload=payload,
            )
        )

    assert bridge_request(
        "events.ingest",
        {
            "batch_id": f"BATCH_{suffix}",
            "session_id": session,
            "persistence_kind": "jsonl",
            "ingest_mode": "reference",
            "events": [
                {"seq": 0, "timestamp": NOW.isoformat(), "event_type": "turn/end", "data": {}}
            ],
        },
    ).ok
    synced = bridge_request(
        "trace.sync",
        {
            "session_id": session,
            "source_revision": "fixture",
            "persistence_kind": "jsonl",
            "ingest_mode": "reference",
        },
    )
    assert synced.ok
    dsh_ref = synced.result["source_trace_id"]
    records, receipts, diagnostics, dsh_records, dsh_receipts, joins = [], [], [], [], [], []
    for index in range(spec.trials):
        run_id = f"R_{suffix}_{index}"

        def make_record(receipt_id, run_id=run_id, index=index):
            return RunRecord(
                schema_version="1.0",
                run_id=run_id,
                attempt_id=f"{run_id}:T1",
                task_id="task_001",
                pool=spec.pool,
                snapshot_id=spec.snapshot_id,
                candidate_id=spec.candidate_id,
                source=RunSource.TAU3,
                runtime_host=RuntimeHost.TAU3,
                runtime_version="tau@fixture",
                model_id=spec.agent_model,
                benchmark_commit=spec.benchmark_commit,
                objective_digest=spec.objective_digest,
                split_digest=spec.split_digest,
                initial_state_digest=spec.initial_state_digests["task_001"],
                terminal_state_digest=DIGEST,
                trial_index=index + 1,
                run_validity="valid",
                success=True,
                critical_violations=[],
                input_tokens=10,
                output_tokens=2,
                latency_ms=100,
                cost=Decimal("0.001"),
                source_trace_ref=ref.source_trace_id,
                evidence_receipt_ref=receipt_id,
                created_at=NOW,
            )

        def make_diagnostic(receipt_id, run_id=run_id):
            return OutcomeDiagnostics(
                schema_version="1.0",
                run_id=run_id,
                evidence_ref=receipt_id,
                termination_reason="agent_stop",
                reward=Decimal(1),
                reward_basis=["DB"],
                db_match=True,
                required_document_count=1,
                action_checks=[],
                observed_tool_names=["lookup"],
            )

        tau, tau_receipt, diagnostic = store.persist_run(
            ref=ref,
            event_index=index,
            record_factory=make_record,
            diagnostic_factory=make_diagnostic,
            collected_at=NOW,
        )
        dsh = tau.model_copy(
            update={
                "run_id": f"DSH_{suffix}_{index}",
                "attempt_id": f"DSH_{suffix}_{index}:T1",
                "source": RunSource.DSH,
                "runtime_host": RuntimeHost.DEEPSEEK_HARNESS,
                "runtime_version": "dsh@fixture",
                "runtime_profile": "headless",
                "composition_digest": DIGEST,
                "source_trace_ref": dsh_ref,
                "evidence_receipt_ref": f"ER_DSH_{suffix}_{index}",
            }
        )
        receipt = EvidenceReceipt(
            schema_version="1.0",
            receipt_id=dsh.evidence_receipt_ref,
            source_trace_id=dsh_ref,
            run_id=dsh.run_id,
            event_seq_start=0,
            event_seq_end=0,
            event_count=1,
            redaction_policy_digest=DIGEST,
            normalized_record_digest=canonical_digest(dsh),
            collected_at=NOW,
            error_count=0,
        )
        join = PilotEvidenceJoin(
            schema_version="1.0",
            join_id=f"PEJ_{suffix}_{index}",
            task_id="task_001",
            trial_index=index + 1,
            dsh_run_id=dsh.run_id,
            tau_run_id=tau.run_id,
            dsh_source_trace_ref=dsh_ref,
            dsh_evidence_receipt_ref=receipt.receipt_id,
            tau_source_trace_ref=ref.source_trace_id,
            tau_evidence_receipt_ref=tau_receipt.receipt_id,
            session_id_hash=canonical_digest({"session_id": session}),
            outcome_success=True,
            evidence_digest=canonical_digest({"tau": tau.run_id, "dsh": dsh.run_id}),
            created_at=NOW,
        )
        for family, identity, value in (
            ("normalized", dsh.run_id, dsh),
            ("receipts", receipt.receipt_id, receipt),
            ("evidence_joins", join.join_id, join),
        ):
            store.write_json_once(store.path_for(family, identity), value.model_dump(mode="json"))
        records.append(tau)
        receipts.append(tau_receipt)
        diagnostics.append(diagnostic)
        dsh_records.append(dsh)
        dsh_receipts.append(receipt)
        joins.append(join)
        identity = {
            "task_id": "task_001",
            "trial": index,
            "seed": 300 + index,
            "task_attempt_index": 1,
        }
        for channel, path, input_tokens, cached, output, cost in (
            ("A", executor.model_usage_path(spec), 8, 2, 2, Decimal("0.0012")),
            ("U", executor.user_model_usage_path(spec), 0, 0, 1, Decimal("0.0002")),
        ):
            fields = {
                "call_id": f"MC_{suffix}_{index}_{channel}",
                "session_id_hash": DIGEST,
                "model": "fixture",
                "provider_retry_count": 0,
                **identity,
            }
            append_model_call_event(
                path, make_model_call_event(**fields, state="started", cost_status="pending")
            )
            append_model_call_event(
                path,
                make_model_call_event(
                    **fields,
                    state="completed",
                    input_tokens=input_tokens,
                    cache_read_tokens=cached,
                    output_tokens=output,
                    cost_usd=cost,
                    cost_status="exact",
                ),
            )
        task_fields = {
            "task_id": "task_001",
            "trial": index,
            "seed": 300 + index,
            "attempt_index": 1,
        }
        task_path = executor.task_attempt_path(spec)
        _append_task_event(task_path, state="started", **task_fields)
        _append_task_event(
            task_path,
            state="session_bound",
            session_id_hash=DIGEST,
            source_locator=f"dsh-session:{DIGEST}",
            **task_fields,
        )
        _append_task_event(
            task_path,
            state="completed",
            duration_ms=100,
            simulation_id=f"SIM_{index}",
            termination_reason="TerminationReason.AGENT_STOP",
            agent_cost_usd=Decimal("0.001"),
            user_cost_usd=Decimal("0.0002"),
            message_count=2,
            session_binding_status="bound",
            session_id_hash=DIGEST,
            source_locator=f"dsh-session:{DIGEST}",
            **task_fields,
        )
    result = DshTau3PilotResult(
        schema_version="1.0",
        source_trace_ref=ref,
        receipts=receipts,
        records=records,
        diagnostics=diagnostics,
        dsh_receipts=dsh_receipts,
        dsh_records=dsh_records,
        evidence_joins=joins,
    )
    return FormalBatchExecution(result_path=raw, result=result)


def generate_batch(root: Path, spec: FormalBatchSpec):
    executor = FixtureExecutor(root, spec)
    runner = FormalBatchRunner(root, executor)
    result = runner.run(spec)
    assert result.artifact.disposition == "complete"
    return runner, executor, result.artifact
