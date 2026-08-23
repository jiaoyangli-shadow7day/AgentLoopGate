from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from agentloopgate.contracts import freeze_contract, load_contract
from agentloopgate.evaluation import EvaluationAuditor, EvaluationContext, EvaluationIntegrityError
from agentloopgate.gates import (
    BaselineSelectionInput,
    CandidateSelectionInput,
    DualSelector,
    GateAssessment,
    GateEngine,
    SelectionError,
    SelectionPolicy,
)
from agentloopgate.schemas import (
    DecisionValue,
    GateName,
    GateStatus,
    Pool,
    RunRecord,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def run_record(
    *,
    run_id: str,
    task_id: str,
    trial: int,
    success: bool | None,
    validity: str = "valid",
    snapshot_id: str = "S_C1",
    candidate_id: str | None = "C_001",
    pool: Pool = Pool.RELEASE_ID,
    cost: str | None = "1.0",
    latency_ms: int = 100,
    critical: list[str] | None = None,
) -> RunRecord:
    return RunRecord.model_validate(
        {
            "schema_version": "1.0",
            "run_id": run_id,
            "attempt_id": f"{run_id}:A",
            "task_id": task_id,
            "pool": pool,
            "snapshot_id": snapshot_id,
            "candidate_id": candidate_id,
            "source": "fixture",
            "runtime_host": "fixture",
            "runtime_version": "fixture@1",
            "model_id": "fixture-model",
            "benchmark_commit": "benchmark-commit",
            "objective_digest": DIGEST_A,
            "split_digest": DIGEST_B,
            "initial_state_digest": DIGEST_C,
            "terminal_state_digest": DIGEST_A,
            "trial_index": trial,
            "run_validity": validity,
            "success": success,
            "critical_violations": critical or [],
            "input_tokens": 10,
            "output_tokens": 5,
            "latency_ms": latency_ms,
            "cost": cost,
            "source_trace_ref": f"STR_{run_id}",
            "evidence_receipt_ref": f"ER_{run_id}",
            "created_at": "2026-08-20T00:00:00Z",
        }
    )


def evaluation_context() -> EvaluationContext:
    return EvaluationContext(
        pool=Pool.RELEASE_ID,
        snapshot_id="S_C1",
        candidate_id="C_001",
        expected_task_ids=["task_001", "task_002"],
        trials=3,
    )


def test_pass_k_excludes_infra_invalid_and_keeps_strict_task_reliability() -> None:
    records = [
        run_record(
            run_id=f"R_1_{trial}",
            task_id="task_001",
            trial=trial,
            success=True,
        )
        for trial in range(1, 4)
    ]
    records += [
        run_record(
            run_id="R_2_INFRA",
            task_id="task_002",
            trial=1,
            success=None,
            validity="infra_invalid",
            cost=None,
        ),
        run_record(run_id="R_2_1", task_id="task_002", trial=1, success=True),
        run_record(run_id="R_2_2", task_id="task_002", trial=2, success=False),
        run_record(run_id="R_2_3", task_id="task_002", trial=3, success=True),
    ]
    verified = {record.run_id for record in records}

    summary = EvaluationAuditor().summarize(
        records,
        evaluation_context(),
        evidence_verified_run_ids=verified,
    )

    assert summary.integrity_complete is True
    assert summary.valid_run_count == 6
    assert summary.infra_invalid_count == 1
    assert summary.pass_1_numerator == 5
    assert summary.pass_1_denominator == 6
    assert summary.stable_success_task_count == 1
    assert summary.stable_task_outcomes == {"task_001": True, "task_002": False}
    assert summary.task_success_counts == {"task_001": 3, "task_002": 2}
    assert summary.mean_cost == Decimal("1.0")


def test_missing_trial_or_evidence_makes_evaluation_incomplete() -> None:
    records = [
        run_record(run_id="R_1_1", task_id="task_001", trial=1, success=True),
    ]
    summary = EvaluationAuditor().summarize(
        records,
        evaluation_context(),
        evidence_verified_run_ids=set(),
    )
    assert summary.integrity_complete is False
    assert "missing_valid_trials" in summary.integrity_issues
    assert "unverified_evidence" in summary.integrity_issues

    duplicate = records + [
        run_record(run_id="R_DUP", task_id="task_001", trial=1, success=False)
    ]
    with pytest.raises(EvaluationIntegrityError, match="duplicate valid"):
        EvaluationAuditor().summarize(
            duplicate,
            evaluation_context(),
            evidence_verified_run_ids={"R_1_1", "R_DUP"},
        )


def test_baseline_comparison_detects_catastrophic_regression() -> None:
    auditor = EvaluationAuditor()
    baseline_records = [
        run_record(
            run_id=f"B_{task}_{trial}",
            task_id=task,
            trial=trial,
            success=True,
            snapshot_id="S_A0",
            candidate_id=None,
        )
        for task in ("task_001", "task_002")
        for trial in range(1, 4)
    ]
    candidate_records = [
        run_record(
            run_id=f"C_{task}_{trial}",
            task_id=task,
            trial=trial,
            success=task == "task_002",
        )
        for task in ("task_001", "task_002")
        for trial in range(1, 4)
    ]
    baseline = auditor.summarize(
        baseline_records,
        evaluation_context().model_copy(
            update={"snapshot_id": "S_A0", "candidate_id": None}
        ),
        evidence_verified_run_ids={record.run_id for record in baseline_records},
    )
    candidate = auditor.summarize(
        candidate_records,
        evaluation_context(),
        evidence_verified_run_ids={record.run_id for record in candidate_records},
    )

    comparison = auditor.compare(baseline, candidate)

    assert comparison.stable_task_net == -1
    assert comparison.catastrophic_regressions == 1
    assert comparison.catastrophic_task_ids == ["task_001"]


def test_baseline_stable_to_partial_success_is_not_catastrophic() -> None:
    auditor = EvaluationAuditor()
    baseline_records = [
        run_record(
            run_id=f"B_task_001_{trial}",
            task_id="task_001",
            trial=trial,
            success=True,
            snapshot_id="S_A0",
            candidate_id=None,
        )
        for trial in range(1, 4)
    ]
    candidate_records = [
        run_record(
            run_id=f"C_task_001_{trial}",
            task_id="task_001",
            trial=trial,
            success=trial < 3,
        )
        for trial in range(1, 4)
    ]
    one_task = evaluation_context().model_copy(update={"expected_task_ids": ["task_001"]})
    baseline = auditor.summarize(
        baseline_records,
        one_task.model_copy(update={"snapshot_id": "S_A0", "candidate_id": None}),
        evidence_verified_run_ids={record.run_id for record in baseline_records},
    )
    candidate = auditor.summarize(
        candidate_records,
        one_task,
        evidence_verified_run_ids={record.run_id for record in candidate_records},
    )

    comparison = auditor.compare(baseline, candidate)

    assert comparison.stable_task_net == -1
    assert comparison.catastrophic_regressions == 0
    assert comparison.catastrophic_task_ids == []


def frozen_contract():
    return freeze_contract(
        load_contract(Path("configs/objective_contract.yaml")),
        frozen_at=datetime(2026, 8, 20, tzinfo=UTC),
    )


def gate_assessment(**overrides: object) -> GateAssessment:
    values: dict[str, object] = {
        "schema_version": "1.0",
        "candidate_id": "C_001",
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
        "baseline_mean_cost": "1.0",
        "candidate_mean_cost": "1.1",
        "baseline_p50_latency_ms": "100",
        "candidate_p50_latency_ms": "110",
        "evidence_refs": {gate.value: f"reports/gates/{gate.value}.json" for gate in GateName},
    }
    values.update(overrides)
    return GateAssessment.model_validate(values)


@pytest.mark.parametrize(
    ("override", "failed_gate", "decision"),
    [
        ({"evaluation_integrity_complete": False}, GateName.EVALUATION_INTEGRITY, "HOLD"),
        ({"leakage_hits": 1}, GateName.LEAKAGE, "REJECT"),
        ({"release_critical_violations": 1}, GateName.CRITICAL_VIOLATION, "HOLD"),
        ({"id_stable_task_net": -1}, GateName.ID_EFFECT, "HOLD"),
        ({"ood_stable_task_net": -2}, GateName.OOD_NONINFERIORITY, "HOLD"),
        ({"replay_stable_task_net": -2}, GateName.REPLAY, "HOLD"),
        ({"reliability_complete": False}, GateName.RELIABILITY, "HOLD"),
        ({"candidate_mean_cost": "1.3"}, GateName.COST, "HOLD"),
        ({"candidate_p50_latency_ms": "130"}, GateName.LATENCY, "HOLD"),
    ],
)
def test_each_gate_failure_is_lexicographic_and_stable(
    override: dict[str, object],
    failed_gate: GateName,
    decision: str,
) -> None:
    outcome = GateEngine(frozen_contract()).decide(
        gate_assessment(**override),
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert outcome.record.decision.value == decision
    assert outcome.failed_gate is failed_gate
    assert [gate.name for gate in outcome.record.gates] == list(GateName)
    failed = next(gate for gate in outcome.record.gates if gate.name is failed_gate)
    assert failed.status is GateStatus.FAIL
    following = outcome.record.gates[list(GateName).index(failed_gate) + 1 :]
    assert all(gate.status is GateStatus.NOT_EVALUATED for gate in following)


def test_gate_pass_recommends_ship_but_does_not_claim_human_approval() -> None:
    outcome = GateEngine(frozen_contract()).decide(
        gate_assessment(),
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    assert outcome.record.decision is DecisionValue.SHIP_RECOMMENDED
    assert outcome.record.human_approval is None
    assert all(gate.status is GateStatus.PASS for gate in outcome.record.gates)

    unsafe = gate_assessment(leakage_hits=1, id_stable_task_net=20)
    assert GateEngine(frozen_contract()).decide(
        unsafe,
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    ).record.decision is DecisionValue.REJECT


def test_dual_selectors_read_same_ladder_but_can_choose_different_candidates() -> None:
    ladder = [
        CandidateSelectionInput(
            candidate_id="C_NATIVE",
            native_score="0.95",
            evaluation_complete=True,
            stable_success_task_count=8,
            critical_violations=0,
            mean_cost="1.4",
            p50_latency_ms="120",
        ),
        CandidateSelectionInput(
            candidate_id="C_GOVERNED",
            native_score="0.90",
            evaluation_complete=True,
            stable_success_task_count=9,
            critical_violations=0,
            mean_cost="1.0",
            p50_latency_ms="100",
        ),
    ]

    result = DualSelector().select(ladder)

    assert result.native_candidate_id == "C_NATIVE"
    assert result.agentloopgate_candidate_id == "C_GOVERNED"
    assert result.ladder_digest.startswith("sha256:")


def test_dual_selector_uses_external_emission_order_when_score_is_unsupported() -> None:
    ladder = [
        CandidateSelectionInput(
            candidate_id="C_FIRST",
            native_score=None,
            native_rank=1,
            native_signal_ref="runs/updaters/ahe/C_FIRST/run_metadata.json",
            evaluation_complete=True,
            stable_success_task_count=7,
            critical_violations=0,
            mean_cost="1.0",
            p50_latency_ms="100",
        ),
        CandidateSelectionInput(
            candidate_id="C_BETTER",
            native_score=None,
            native_rank=2,
            native_signal_ref="runs/updaters/ahe/C_BETTER/run_metadata.json",
            evaluation_complete=True,
            stable_success_task_count=9,
            critical_violations=0,
            mean_cost="1.0",
            p50_latency_ms="100",
        ),
    ]

    result = DualSelector().select(ladder)

    assert result.native_candidate_id == "C_FIRST"
    assert result.agentloopgate_candidate_id == "C_BETTER"


def selection_baseline(**overrides: object) -> BaselineSelectionInput:
    values: dict[str, object] = {
        "snapshot_id": "S_A0",
        "evaluation_complete": True,
        "stable_success_task_count": 1,
        "stable_task_outcomes": {
            "task_001": True,
            "task_002": False,
            "task_003": False,
        },
        "critical_violations": 0,
        "mean_cost": "1.0",
        "whole_attempt_cost_usd": "3.0",
        "task_attempt_count": 3,
        "retry_count": 0,
        "timeout_count": 0,
        "p50_latency_ms": "100",
        "p95_latency_ms": "200",
        "max_latency_ms": "250",
        "operational_evidence_refs": [
            "batch:B_A0",
            "cost:B_A0",
            "attempts:B_A0",
        ],
    }
    values.update(overrides)
    return BaselineSelectionInput.model_validate(values)


def selection_policy() -> SelectionPolicy:
    return SelectionPolicy(
        whole_attempt_cost_ratio_max="1.2",
        p95_latency_ratio_max="1.2",
        max_retry_increase=0,
        max_timeout_increase=0,
    )


def governed_candidate(
    candidate_id: str,
    outcomes: dict[str, bool],
    **overrides: object,
) -> CandidateSelectionInput:
    values: dict[str, object] = {
        "candidate_id": candidate_id,
        "native_score": None,
        "native_rank": 1,
        "native_signal_ref": f"updater:{candidate_id}",
        "evaluation_complete": True,
        "stable_success_task_count": sum(outcomes.values()),
        "stable_task_outcomes": outcomes,
        "critical_violations": 0,
        "mean_cost": "1.0",
        "whole_attempt_cost_usd": "3.0",
        "task_attempt_count": 3,
        "retry_count": 0,
        "timeout_count": 0,
        "p50_latency_ms": "100",
        "p95_latency_ms": "200",
        "max_latency_ms": "250",
        "operational_evidence_refs": [
            f"batch:{candidate_id}",
            f"cost:{candidate_id}",
            f"attempts:{candidate_id}",
        ],
    }
    values.update(overrides)
    return CandidateSelectionInput.model_validate(values)


def test_baseline_bound_selector_abstains_when_no_candidate_improves() -> None:
    candidate = governed_candidate(
        "C_TIED",
        {"task_001": True, "task_002": False, "task_003": False},
    )

    result = DualSelector().select(
        [candidate], baseline=selection_baseline(), policy=selection_policy()
    )

    assert result.schema_version == "1.1"
    assert result.native_candidate_id == "C_TIED"
    assert result.agentloopgate_decision == "HOLD"
    assert result.agentloopgate_candidate_id is None
    assert result.governance_findings == {"C_TIED": ["no_stable_success_gain"]}


def test_baseline_bound_selector_rejects_regression_despite_positive_net() -> None:
    baseline = selection_baseline(
        stable_success_task_count=1,
        stable_task_outcomes={
            "task_001": True,
            "task_002": False,
            "task_003": False,
            "task_004": False,
        },
        task_attempt_count=4,
    )
    candidate = governed_candidate(
        "C_NET_POSITIVE",
        {
            "task_001": False,
            "task_002": True,
            "task_003": True,
            "task_004": False,
        },
        task_attempt_count=4,
    )

    result = DualSelector().select(
        [candidate], baseline=baseline, policy=selection_policy()
    )

    assert result.agentloopgate_decision == "HOLD"
    assert "stable_task_regression:task_001" in result.governance_findings[
        "C_NET_POSITIVE"
    ]


def test_baseline_bound_selector_selects_strict_gain_and_uses_tail_evidence() -> None:
    outcomes = {"task_001": True, "task_002": True, "task_003": False}
    slower = governed_candidate(
        "C_SLOWER",
        outcomes,
        native_rank=1,
        p95_latency_ms="220",
        max_latency_ms="260",
    )
    faster = governed_candidate(
        "C_FASTER",
        outcomes,
        native_rank=2,
        p95_latency_ms="180",
        max_latency_ms="240",
    )

    result = DualSelector().select(
        [slower, faster], baseline=selection_baseline(), policy=selection_policy()
    )

    assert result.native_candidate_id == "C_SLOWER"
    assert result.agentloopgate_decision == "SELECT"
    assert result.agentloopgate_candidate_id == "C_FASTER"


def test_baseline_bound_selector_holds_retry_or_whole_cost_regression() -> None:
    outcomes = {"task_001": True, "task_002": True, "task_003": False}
    retried = governed_candidate(
        "C_RETRY",
        outcomes,
        task_attempt_count=4,
        retry_count=1,
    )
    expensive = governed_candidate(
        "C_EXPENSIVE",
        outcomes,
        native_rank=2,
        whole_attempt_cost_usd="3.61",
    )

    result = DualSelector().select(
        [retried, expensive], baseline=selection_baseline(), policy=selection_policy()
    )

    assert result.agentloopgate_decision == "HOLD"
    assert "retry_increase" in result.governance_findings["C_RETRY"]
    assert "whole_attempt_cost_noninferiority" in result.governance_findings[
        "C_EXPENSIVE"
    ]


def test_baseline_bound_selector_requires_complete_enhanced_evidence() -> None:
    legacy = CandidateSelectionInput(
        candidate_id="C_LEGACY",
        native_score="1",
        evaluation_complete=True,
        stable_success_task_count=2,
        critical_violations=0,
        mean_cost="1",
        p50_latency_ms="100",
    )

    with pytest.raises(SelectionError, match="enhanced selection evidence"):
        DualSelector().select(
            [legacy], baseline=selection_baseline(), policy=selection_policy()
        )
