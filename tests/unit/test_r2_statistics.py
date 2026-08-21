from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from agentloopgate.contracts import canonical_digest
from agentloopgate.evaluation import EvaluationSummary
from agentloopgate.experiment.batch import (
    FormalBatchArtifact,
    FormalBatchSpec,
    FormalStage,
)
from agentloopgate.experiment.statistics import (
    build_selector_ablation,
    paired_task_bootstrap,
)
from agentloopgate.experiment.study import load_study_plan
from agentloopgate.schemas import Pool

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def test_paired_bootstrap_is_deterministic_and_task_paired() -> None:
    study = load_study_plan(Path("configs/banking_r2_study_v2.yaml"))
    reference = _batch(
        stage=FormalStage.RELEASE_ID,
        snapshot_id="R2_A0",
        candidate_id=None,
        outcomes={"T1": False, "T2": False, "T3": True},
        suffix="REF",
    )
    candidate = _batch(
        stage=FormalStage.RELEASE_ID,
        snapshot_id="S_C1",
        candidate_id="C_1",
        outcomes={"T1": True, "T2": False, "T3": True},
        suffix="CAND",
    )

    first = paired_task_bootstrap(
        comparison_id="baseline_vs_agentloopgate:release_id",
        reference_role="baseline",
        candidate_role="agentloopgate",
        stage=FormalStage.RELEASE_ID,
        reference=reference,
        candidate=candidate,
        study=study,
    )
    second = paired_task_bootstrap(
        comparison_id="baseline_vs_agentloopgate:release_id",
        reference_role="baseline",
        candidate_role="agentloopgate",
        stage=FormalStage.RELEASE_ID,
        reference=reference,
        candidate=candidate,
        study=study,
    )

    assert first == second
    assert first.task_count == 3
    assert first.observed_stable_task_net == 1
    assert first.observed_rate_difference == Decimal(1) / 3
    assert first.bootstrap_resamples == 10_000
    assert first.ci_lower <= first.observed_rate_difference <= first.ci_upper


def test_selector_alias_reuses_evidence_and_reports_exact_null_contrast() -> None:
    study = load_study_plan(Path("configs/banking_r2_study_v2.yaml"))
    release = {
        "S_SHARED": {
            stage: _batch(
                stage=stage,
                snapshot_id="S_SHARED",
                candidate_id="C_SHARED",
                outcomes={"T1": True, "T2": False, "T3": True},
                suffix=stage.value.upper(),
            )
            for stage in (
                FormalStage.RELEASE_ID,
                FormalStage.RELEASE_OOD,
                FormalStage.REPLAY,
            )
        }
    }

    artifact = build_selector_ablation(
        experiment_id="EXP_BANKING_R2",
        study=study,
        source_revision="tree:sha256:" + "d" * 64,
        selection_digest=DIGEST_A,
        updater_native_candidate_id="C_SHARED",
        updater_native_snapshot_id="S_SHARED",
        agentloopgate_candidate_id="C_SHARED",
        agentloopgate_snapshot_id="S_SHARED",
        release=release,
    )

    assert artifact.role_alias is True
    assert artifact.evidence_reused is True
    assert artifact.contrast_kind == "null_contrast_identical_snapshot"
    assert all(item.observed_stable_task_net == 0 for item in artifact.comparisons)
    assert all(item.ci_lower == item.ci_upper == 0 for item in artifact.comparisons)


def _batch(
    *,
    stage: FormalStage,
    snapshot_id: str,
    candidate_id: str | None,
    outcomes: dict[str, bool],
    suffix: str,
) -> FormalBatchArtifact:
    pool = Pool.UPDATE_SOURCE if stage is FormalStage.REPLAY else Pool(stage.value)
    trials = 3
    counts = {task_id: trials if success else 0 for task_id, success in outcomes.items()}
    summary = EvaluationSummary(
        schema_version="1.0",
        pool=pool,
        snapshot_id=snapshot_id,
        candidate_id=candidate_id,
        trials=trials,
        expected_task_count=len(outcomes),
        valid_run_count=len(outcomes) * trials,
        infra_invalid_count=0,
        pass_1_numerator=sum(counts.values()),
        pass_1_denominator=len(outcomes) * trials,
        stable_success_task_count=sum(outcomes.values()),
        stable_task_outcomes=outcomes,
        task_success_counts=counts,
        critical_violation_count=0,
        mean_cost="0.01",
        p50_latency_ms="100",
        integrity_complete=True,
        integrity_issues=[],
    )
    spec = FormalBatchSpec(
        experiment_id="EXP_BANKING_R2",
        stage=stage,
        pool=pool,
        snapshot_id=snapshot_id,
        candidate_id=candidate_id,
        task_ids=list(outcomes),
        trials=trials,
        agent_model="deepseek-official/deepseek-v4-flash",
        user_model="deepseek/deepseek-v4-flash",
        objective_digest=DIGEST_A,
        split_digest=DIGEST_B,
        benchmark_commit="fc0055dc4e0a316c3f83133267fbd6faaa770992",
        initial_state_digests={task_id: DIGEST_C for task_id in outcomes},
        protocol_digest=DIGEST_A,
    )
    payload = {
        "schema_version": "1.0",
        "batch_id": f"B_{suffix}",
        "experiment_id": "EXP_BANKING_R2",
        "stage": stage,
        "spec": spec,
        "spec_digest": spec.spec_digest,
        "result_artifact": f"runs/raw/{suffix}.json",
        "tau_source_trace_id": f"STR_{suffix}",
        "tau_run_ids": [f"TAU_{suffix}"],
        "dsh_run_ids": [f"DSH_{suffix}"],
        "evidence_join_ids": [f"PEJ_{suffix}"],
        "summary": summary,
        "disposition": "complete",
        "hold_reasons": [],
    }
    return FormalBatchArtifact.model_validate(
        {**payload, "batch_digest": canonical_digest(payload)}
    )
