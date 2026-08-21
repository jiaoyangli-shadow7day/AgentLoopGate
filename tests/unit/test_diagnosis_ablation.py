from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from agentloopgate.contracts import canonical_digest
from agentloopgate.diagnosis import RankedFailureBundle
from agentloopgate.evaluation import EvaluationSummary
from agentloopgate.experiment.diagnosis_ablation import (
    build_diagnosis_direction_ablation,
)
from agentloopgate.experiment.diagnostics import FormalDiagnosisArtifact
from agentloopgate.experiment.study import load_study_plan
from agentloopgate.gates import CandidateSelectionInput, DualSelection
from agentloopgate.schemas import CandidateRecord, FailureBundle, Pool

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def test_diagnosis_direction_is_descriptive_bound_and_no_model() -> None:
    study = load_study_plan(Path("configs/banking_r2_study_v2.yaml"))
    prompt_bundle = _bundle("FB_PROMPT", "policy_application_error", "prompt_instruction")
    tool_bundle = _bundle("FB_TOOL", "tool_selection_error", "tool_contract_routing")
    candidates = [
        _candidate("C_1", prompt_bundle, "prompt_instruction"),
        _candidate("C_2", tool_bundle, "tool_contract_routing"),
        _candidate("C_3", prompt_bundle, "prompt_instruction"),
    ]
    snapshots = ["S_1", "S_2", "S_3"]
    diagnosis_payload = {
        "schema_version": "1.0",
        "batch_id": "B_UPDATE_SOURCE",
        "snapshot_id": "R2_A0",
        "signals": [],
        "ranked_bundles": [
            RankedFailureBundle(
                schema_version="1.0",
                priority=2,
                affected_task_count=1,
                bundle=prompt_bundle,
            ),
            RankedFailureBundle(
                schema_version="1.0",
                priority=1,
                affected_task_count=1,
                bundle=tool_bundle,
            ),
        ],
    }
    diagnosis = FormalDiagnosisArtifact.model_validate(
        {
            **diagnosis_payload,
            "diagnosis_digest": canonical_digest(diagnosis_payload),
        }
    )
    baseline = _batch("B_UC_A0", "R2_A0", None, Pool.UPDATE_CHECK, 1)
    update_check = {
        snapshot: _batch(
            f"B_UC_{index}",
            snapshot,
            candidate.candidate_id,
            Pool.UPDATE_CHECK,
            1 + (index % 2),
        )
        for index, (candidate, snapshot) in enumerate(
            zip(candidates, snapshots, strict=True), start=1
        )
    }
    selection_batches = {
        snapshot: _batch(
            f"B_SEL_{index}",
            snapshot,
            candidate.candidate_id,
            Pool.SELECTION,
            3 - index,
        )
        for index, (candidate, snapshot) in enumerate(
            zip(candidates, snapshots, strict=True), start=1
        )
    }
    inputs = [
        CandidateSelectionInput(
            candidate_id=candidate.candidate_id,
            native_score=None,
            native_rank=index,
            native_signal_ref="runs/proposal_plan.json",
            evaluation_complete=True,
            stable_success_task_count=(
                selection_batches[snapshot].summary.stable_success_task_count
            ),
            critical_violations=0,
            mean_cost="0.01",
            p50_latency_ms="100",
        )
        for index, (candidate, snapshot) in enumerate(
            zip(candidates, snapshots, strict=True), start=1
        )
    ]
    selection = SimpleNamespace(
        inputs=inputs,
        selection=DualSelection(
            schema_version="1.0",
            native_candidate_id="C_1",
            agentloopgate_candidate_id="C_1",
            ladder_digest=DIGEST_A,
        ),
        selection_digest=DIGEST_B,
    )

    artifact = build_diagnosis_direction_ablation(
        experiment_id="EXP_BANKING_R2",
        study=study,
        source_revision="tree:sha256:" + "d" * 64,
        diagnosis=diagnosis,
        candidates=candidates,
        candidate_snapshots=snapshots,
        baseline_update_check=baseline,
        candidate_update_check=update_check,
        selection_batches=selection_batches,
        selection=selection,
    )

    assert artifact.additional_model_calls is False
    assert artifact.causal_claim_supported is False
    assert len(artifact.candidate_results) == 3
    assert len(artifact.family_summaries) == 2
    assert all(item.target_alignment for item in artifact.candidate_results)
    assert artifact.candidate_results[0].observed_transition == (
        "selected_by_agentloopgate"
    )


def _bundle(bundle_id: str, failure_type: str, family: str) -> FailureBundle:
    return FailureBundle.model_validate(
        {
            "schema_version": "1.0",
            "failure_bundle_id": bundle_id,
            "snapshot_id": "R2_A0",
            "source_pool": "update_source",
            "failure_type": failure_type,
            "affected_run_ids": [f"R_{bundle_id}"],
            "evidence_refs": [f"runs/{bundle_id}.json"],
            "redacted_summary": "redacted failure",
            "target_asset_families": [family],
            "expected_behavior_change": "improve stable success",
            "must_not_change": ["objective"],
            "budget": {"max_files": 1, "max_changed_lines": 10},
        }
    )


def _candidate(candidate_id: str, bundle: FailureBundle, family: str) -> CandidateRecord:
    return CandidateRecord.model_validate(
        {
            "schema_version": "1.0",
            "candidate_id": candidate_id,
            "parent_snapshot_id": "R2_A0",
            "failure_bundle_digest": canonical_digest(bundle),
            "updater": {"name": "ahe", "version": "test"},
            "hypothesis": "one falsifiable change",
            "asset_families": [family],
            "risk_tier": "L",
            "patch_path": f"candidates/{candidate_id}/candidate.patch",
            "patch_digest": DIGEST_A,
            "changed_files": ["harness/system_prompt.md"],
            "predicted_effect": {
                "metric": "stable_success_task_count",
                "direction": "increase",
            },
            "status": "selection_evaluated",
            "created_at": "2026-08-21T00:00:00Z",
        }
    )


def _batch(
    batch_id: str,
    snapshot_id: str,
    candidate_id: str | None,
    pool: Pool,
    stable_count: int,
) -> SimpleNamespace:
    tasks = {"T1": stable_count >= 1, "T2": stable_count >= 2}
    summary = EvaluationSummary(
        schema_version="1.0",
        pool=pool,
        snapshot_id=snapshot_id,
        candidate_id=candidate_id,
        trials=1,
        expected_task_count=2,
        valid_run_count=2,
        infra_invalid_count=0,
        pass_1_numerator=sum(tasks.values()),
        pass_1_denominator=2,
        stable_success_task_count=sum(tasks.values()),
        stable_task_outcomes=tasks,
        task_success_counts={key: int(value) for key, value in tasks.items()},
        critical_violation_count=0,
        mean_cost=Decimal("0.01"),
        p50_latency_ms=Decimal("100"),
        integrity_complete=True,
        integrity_issues=[],
    )
    return SimpleNamespace(
        batch_id=batch_id,
        batch_digest=canonical_digest({"batch_id": batch_id}),
        summary=summary,
    )
