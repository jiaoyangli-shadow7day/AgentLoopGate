"""Deterministic public demo proving software behavior without a model key."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agentloopgate.contracts import (
    canonical_digest,
    canonical_json_bytes,
    file_digest,
    freeze_contract,
    load_contract,
)
from agentloopgate.gates import GateAssessment, GateEngine, GateOutcome
from agentloopgate.reporting import (
    CandidateCurvePoint,
    DecisionReportBuilder,
    FailureFunnelPoint,
    PoolComparisonPoint,
    ReportData,
)
from agentloopgate.schemas import (
    EvidenceReceipt,
    GateName,
    RunRecord,
    SourceTraceRef,
)

_DEMO_TIME = datetime(2026, 8, 20, tzinfo=UTC)
_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64
_DIGEST_C = "sha256:" + "c" * 64
_DIGEST_D = "sha256:" + "d" * 64


def build_public_demo(project_root: Path, output_root: Path) -> Path:
    """Build an idempotent, explicitly synthetic evidence and gate package."""
    root = project_root.resolve()
    output = output_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    trace_path = output / "native_session.jsonl"
    trace_text = (
        '{"data":{"task_id":"banking_fixture_001"},"seq":0,'
        '"timestamp":"2026-08-20T00:00:00Z","type":"turn/start"}\n'
        '{"data":{"name":"lookup_policy","status":"ok"},"seq":1,'
        '"timestamp":"2026-08-20T00:00:01Z","type":"tool/result"}\n'
        '{"data":{"reason":"completed"},"seq":2,'
        '"timestamp":"2026-08-20T00:00:02Z","type":"turn/end"}\n'
    )
    _write_once(trace_path, trace_text.encode())

    ref = SourceTraceRef.model_validate(
        {
            "schema_version": "1.0",
            "source_trace_id": "DSH_PUBLIC_DEMO",
            "runtime_host": "deepseek_harness",
            "source_locator": (
                f"artifact:{trace_path.relative_to(root).as_posix()}"
                if trace_path.is_relative_to(root)
                else "artifact:native_session.jsonl"
            ),
            "session_id_hash": canonical_digest({"session": "public-demo"}),
            "event_seq_start": 0,
            "event_seq_end": 2,
            "event_count": 3,
            "source_revision": file_digest(trace_path),
            "persistence_kind": "jsonl",
            "ingest_mode": "reference",
            "mirror_path": None,
            "mirror_digest": None,
            "cursor_complete": True,
            "evidence_status": "verified",
            "created_at": _DEMO_TIME,
        }
    )
    record = RunRecord.model_validate(
        {
            "schema_version": "1.0",
            "run_id": "R_PUBLIC_DEMO",
            "attempt_id": "A_PUBLIC_DEMO",
            "task_id": "banking_fixture_001",
            "pool": "pilot",
            "snapshot_id": "S_A0",
            "candidate_id": None,
            "source": "dsh",
            "runtime_host": "deepseek_harness",
            "runtime_version": "deepseek-harness@0.1.0-rc.8",
            "runtime_profile": "headless",
            "composition_digest": canonical_digest({"profile": "public-demo"}),
            "model_id": "fixture-model-no-network",
            "benchmark_commit": "fixture-only",
            "objective_digest": _DIGEST_A,
            "split_digest": _DIGEST_B,
            "initial_state_digest": _DIGEST_C,
            "terminal_state_digest": _DIGEST_D,
            "trial_index": 1,
            "run_validity": "valid",
            "success": False,
            "critical_violations": [],
            "input_tokens": 12,
            "output_tokens": 3,
            "latency_ms": 24,
            "cost": "0.000004",
            "source_trace_ref": ref.source_trace_id,
            "evidence_receipt_ref": "ER_PUBLIC_DEMO",
            "created_at": _DEMO_TIME,
        }
    )
    receipt = EvidenceReceipt.model_validate(
        {
            "schema_version": "1.0",
            "receipt_id": "ER_PUBLIC_DEMO",
            "source_trace_id": ref.source_trace_id,
            "run_id": record.run_id,
            "event_seq_start": 0,
            "event_seq_end": 2,
            "event_count": 3,
            "redaction_policy_digest": canonical_digest({"policy": "public-demo"}),
            "normalized_record_digest": canonical_digest(record),
            "collected_at": _DEMO_TIME,
            "error_count": 0,
        }
    )
    _write_json(output / "source_trace_ref.json", ref)
    _write_json(output / "evidence_receipt.json", receipt)
    _write_json(output / "normalized_run.json", record)

    contract = freeze_contract(
        load_contract(root / "configs/objective_contract.yaml"),
        frozen_at=_DEMO_TIME,
    )
    engine = GateEngine(contract)
    ood = engine.decide(
        _assessment("C_DEMO_OOD", ood_stable_task_net=-2),
        created_at=_DEMO_TIME,
    )
    cost = engine.decide(
        _assessment("C_DEMO_COST", candidate_mean_cost="1.30"),
        created_at=_DEMO_TIME,
    )
    _build_report(output, "EXP_DEMO_OOD", ood)
    _build_report(output, "EXP_DEMO_COST", cost)

    manifest = {
        "schema_version": "1.0",
        "fixture_id": "public_demo",
        "description": (
            "No-key software-behavior fixture; these are synthetic outcomes, not real results."
        ),
        "real_experiment": False,
        "runs": [record.model_dump(mode="json")],
        "candidates": [
            {
                "candidate_id": "C_DEMO_OOD",
                "development_effect": "improved",
                "decision": ood.record.decision.value,
                "failed_gate": ood.failed_gate.value if ood.failed_gate else None,
            },
            {
                "candidate_id": "C_DEMO_COST",
                "development_effect": "improved",
                "decision": cost.record.decision.value,
                "failed_gate": cost.failed_gate.value if cost.failed_gate else None,
            },
        ],
        "artifacts": {
            "source_trace_ref": "source_trace_ref.json",
            "evidence_receipt": "evidence_receipt.json",
            "normalized_run": "normalized_run.json",
            "reports": ["reports/EXP_DEMO_OOD", "reports/EXP_DEMO_COST"],
        },
    }
    demo_path = output / "demo.json"
    _write_json(demo_path, manifest)
    return demo_path


def _assessment(candidate_id: str, **updates: object) -> GateAssessment:
    values: dict[str, object] = {
        "schema_version": "1.0",
        "candidate_id": candidate_id,
        "baseline_snapshot_id": "S_A0",
        "evaluation_integrity_complete": True,
        "leakage_hits": 0,
        "mutates_trust_kernel": False,
        "risk_tier": "M",
        "release_critical_violations": 0,
        "id_stable_task_net": 1,
        "ood_stable_task_net": 0,
        "replay_stable_task_net": 0,
        "catastrophic_regressions": 0,
        "reliability_complete": True,
        "reliability_trials": 3,
        "stable_success_required": 3,
        "baseline_mean_cost": "1.00",
        "candidate_mean_cost": "1.10",
        "baseline_p50_latency_ms": "100",
        "candidate_p50_latency_ms": "110",
        "evidence_refs": {
            gate.value: f"fixture:gates/{candidate_id}/{gate.value}" for gate in GateName
        },
    }
    values.update(updates)
    return GateAssessment.model_validate(values)


def _build_report(output: Path, experiment_id: str, decision: GateOutcome) -> None:
    DecisionReportBuilder(output).build(
        ReportData(
            schema_version="1.0",
            experiment_id=experiment_id,
            decision=decision,
            candidate_curve=[
                CandidateCurvePoint(
                    label="A0", pass_1="0.50", pass_k="0.40", mean_cost="1.00"
                ),
                CandidateCurvePoint(
                    label=decision.record.candidate_id,
                    pass_1="0.60",
                    pass_k="0.50",
                    mean_cost=("1.30" if "COST" in decision.record.candidate_id else "1.10"),
                ),
            ],
            failure_funnel=[
                FailureFunnelPoint(stage="retrieval", count=5),
                FailureFunnelPoint(stage="policy", count=3),
                FailureFunnelPoint(stage="tool", count=2),
                FailureFunnelPoint(stage="correct_state", count=1),
            ],
            pool_comparison=[
                PoolComparisonPoint(
                    candidate_id="A0", pool="release_id", stable_tasks=10
                ),
                PoolComparisonPoint(
                    candidate_id=decision.record.candidate_id,
                    pool="release_id",
                    stable_tasks=11,
                ),
                PoolComparisonPoint(
                    candidate_id="A0", pool="release_ood", stable_tasks=9
                ),
                PoolComparisonPoint(
                    candidate_id=decision.record.candidate_id,
                    pool="release_ood",
                    stable_tasks=(7 if "OOD" in decision.record.candidate_id else 9),
                ),
            ],
        )
    )


def _write_json(path: Path, payload: object) -> None:
    _write_once(path, canonical_json_bytes(payload) + b"\n")


def _write_once(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"public demo artifact conflict: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
