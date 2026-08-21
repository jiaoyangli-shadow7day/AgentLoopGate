from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentloopgate.contracts import canonical_digest, file_digest
from agentloopgate.gates import GateOutcome
from agentloopgate.reporting import (
    CandidateCurvePoint,
    DecisionReportBuilder,
    FailureFunnelPoint,
    PoolComparisonPoint,
    ReportData,
)
from agentloopgate.schemas import CandidateRecord, DecisionRecord
from agentloopgate.snapshots import (
    ApprovalAction,
    PromotionApproval,
    SnapshotAuthorizationError,
    SnapshotManager,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def candidate(root: Path) -> CandidateRecord:
    patch = root / "candidates/C_001/candidate.patch"
    patch.parent.mkdir(parents=True)
    patch.write_text(
        "diff --git a/harness/system_prompt.md b/harness/system_prompt.md\n"
        "--- a/harness/system_prompt.md\n"
        "+++ b/harness/system_prompt.md\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n",
        encoding="utf-8",
    )
    return CandidateRecord.model_validate(
        {
            "schema_version": "1.0",
            "candidate_id": "C_001",
            "parent_snapshot_id": "S_A0",
            "failure_bundle_digest": DIGEST_A,
            "updater": {"name": "ahe", "version": "0.1.0@commit"},
            "hypothesis": "A precise instruction improves stable success.",
            "asset_families": ["prompt_instruction"],
            "risk_tier": "L",
            "patch_path": "candidates/C_001/candidate.patch",
            "patch_digest": file_digest(patch),
            "changed_files": ["harness/system_prompt.md"],
            "predicted_effect": {
                "metric": "stable_success_task_count",
                "direction": "increase",
            },
            "status": "ship_recommended",
            "created_at": "2026-08-20T00:00:00Z",
        }
    )


def decision(value: str = "SHIP_RECOMMENDED") -> DecisionRecord:
    return DecisionRecord.model_validate(
        {
            "schema_version": "1.0",
            "decision_id": "D_001",
            "candidate_id": "C_001",
            "baseline_snapshot_id": "S_A0",
            "decision": value,
            "gates": [
                {
                    "name": name,
                    "status": "pass" if value == "SHIP_RECOMMENDED" else "fail",
                    "evidence_ref": f"reports/gates/{name}.json",
                }
                for name in (
                    "evaluation_integrity",
                    "leakage",
                    "critical_violation",
                    "id_effect",
                    "ood_noninferiority",
                    "replay",
                    "reliability",
                    "cost",
                    "latency",
                )
            ],
            "summary": f"{value}: fixture reason",
            "human_approval": None,
            "created_at": "2026-08-20T00:00:00Z",
        }
    )


def approval(action: ApprovalAction, target: str) -> PromotionApproval:
    return PromotionApproval(
        schema_version="1.0",
        approval_id=f"APPROVAL_{action.value.upper()}",
        action=action,
        target_snapshot_id=target,
        actor="human-owner",
        confirmation="I understand this changes the active harness snapshot.",
        approved_at=datetime(2026, 8, 20, tzinfo=UTC),
    )


def test_promote_requires_human_approval_and_rollback_restores_parent(tmp_path: Path) -> None:
    prompt = tmp_path / "harness/system_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("old\n", encoding="utf-8")
    manager = SnapshotManager(tmp_path)
    baseline = manager.create_baseline(
        snapshot_id="S_A0",
        harness_paths=["harness/system_prompt.md"],
        model_id="fixture-model",
        objective_digest=DIGEST_A,
        split_digest=DIGEST_B,
        asset_manifest_digest=DIGEST_C,
        code_revision="fixture-revision",
        runtime_host="python_cli",
        runtime_version="fixture@1",
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    child = manager.create_child(
        candidate(tmp_path),
        model_id="fixture-model",
        code_revision="fixture-revision",
        runtime_host="python_cli",
        runtime_version="fixture@1",
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert baseline.snapshot_id == "S_A0"
    assert child.parent_snapshot_id == "S_A0"
    assert prompt.read_text(encoding="utf-8") == "old\n"
    with pytest.raises(SnapshotAuthorizationError, match="approval"):
        manager.promote(child.snapshot_id, decision(), approval=None)
    with pytest.raises(SnapshotAuthorizationError, match="SHIP_RECOMMENDED"):
        manager.promote(
            child.snapshot_id,
            decision("HOLD"),
            approval=approval(ApprovalAction.PROMOTE, child.snapshot_id),
        )

    activation = manager.promote(
        child.snapshot_id,
        decision(),
        approval=approval(ApprovalAction.PROMOTE, child.snapshot_id),
    )
    assert activation.snapshot_id == child.snapshot_id
    assert prompt.read_text(encoding="utf-8") == "new\n"
    assert manager.active_snapshot().snapshot_id == child.snapshot_id
    assert manager.promote(
        child.snapshot_id,
        decision(),
        approval=approval(ApprovalAction.PROMOTE, child.snapshot_id),
    ) == activation

    rolled_back = manager.rollback(
        baseline.snapshot_id,
        approval=approval(ApprovalAction.ROLLBACK, baseline.snapshot_id),
    )
    assert rolled_back.snapshot_id == baseline.snapshot_id
    assert prompt.read_text(encoding="utf-8") == "old\n"
    assert manager.verify(baseline.snapshot_id) == baseline
    assert manager.rollback(
        baseline.snapshot_id,
        approval=approval(ApprovalAction.ROLLBACK, baseline.snapshot_id),
    ) == rolled_back


def test_snapshot_rejects_live_harness_drift_before_promotion(tmp_path: Path) -> None:
    prompt = tmp_path / "harness/system_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("old\n", encoding="utf-8")
    manager = SnapshotManager(tmp_path)
    manager.create_baseline(
        snapshot_id="S_A0",
        harness_paths=["harness/system_prompt.md"],
        model_id="fixture-model",
        objective_digest=DIGEST_A,
        split_digest=DIGEST_B,
        asset_manifest_digest=DIGEST_C,
        code_revision="fixture-revision",
        runtime_host="python_cli",
        runtime_version="fixture@1",
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    child = manager.create_child(
        candidate(tmp_path),
        model_id="fixture-model",
        code_revision="fixture-revision",
        runtime_host="python_cli",
        runtime_version="fixture@1",
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    prompt.write_text("manual drift\n", encoding="utf-8")

    with pytest.raises(SnapshotAuthorizationError, match="drift"):
        manager.promote(
            child.snapshot_id,
            decision(),
            approval=approval(ApprovalAction.PROMOTE, child.snapshot_id),
        )


def test_evaluation_baseline_does_not_change_deployment_activation(tmp_path: Path) -> None:
    prompt = tmp_path / "harness/system_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("old\n", encoding="utf-8")
    manager = SnapshotManager(tmp_path)
    manager.create_baseline(
        snapshot_id="S_A0",
        harness_paths=["harness/system_prompt.md"],
        model_id="fixture-model",
        objective_digest=DIGEST_A,
        split_digest=DIGEST_B,
        asset_manifest_digest=DIGEST_C,
        code_revision="old-revision",
        runtime_host="python_cli",
        runtime_version="fixture@1",
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    evaluation = manager.create_evaluation_baseline(
        snapshot_id="R2_A0",
        harness_paths=["harness/system_prompt.md"],
        model_id="fixture-model",
        objective_digest=DIGEST_A,
        split_digest=DIGEST_B,
        asset_manifest_digest=DIGEST_C,
        code_revision="reviewed-r2-revision",
        runtime_host="deepseek_harness",
        runtime_version="deepseek-harness@fixture",
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
    )

    assert evaluation.snapshot_id == "R2_A0"
    assert evaluation.code_revision == "reviewed-r2-revision"
    assert manager.active_snapshot().snapshot_id == "S_A0"
    assert len(list((tmp_path / "snapshots/activations").glob("*.json"))) == 1


def test_decision_report_contains_json_markdown_and_exactly_four_core_charts(
    tmp_path: Path,
) -> None:
    record = decision("HOLD")
    outcome = GateOutcome(
        schema_version="1.0",
        record=record,
        failed_gate="ood_noninferiority",
        reason="OOD stable-task effect is below the frozen margin",
    )
    data = ReportData(
        schema_version="1.0",
        experiment_id="EXP_001",
        decision=outcome,
        candidate_curve=[
            CandidateCurvePoint(label="A0", pass_1="0.50", pass_k="0.40", mean_cost="1.0"),
            CandidateCurvePoint(label="A1", pass_1="0.60", pass_k="0.50", mean_cost="1.1"),
        ],
        failure_funnel=[
            FailureFunnelPoint(stage="retrieval", count=5),
            FailureFunnelPoint(stage="policy", count=3),
            FailureFunnelPoint(stage="tool", count=2),
            FailureFunnelPoint(stage="correct_state", count=1),
        ],
        pool_comparison=[
            PoolComparisonPoint(candidate_id="A0", pool="release_id", stable_tasks=10),
            PoolComparisonPoint(candidate_id="C_001", pool="release_id", stable_tasks=11),
            PoolComparisonPoint(candidate_id="A0", pool="release_ood", stable_tasks=9),
            PoolComparisonPoint(candidate_id="C_001", pool="release_ood", stable_tasks=7),
        ],
    )

    artifact = DecisionReportBuilder(tmp_path).build(data)

    assert artifact.decision_json.is_file()
    assert artifact.decision_markdown.is_file()
    assert len(artifact.chart_paths) == 4
    assert all(
        path.is_file() and path.read_text().startswith("<svg")
        for path in artifact.chart_paths
    )
    assert "HOLD" in artifact.decision_markdown.read_text(encoding="utf-8")
    assert canonical_digest(record) in artifact.decision_markdown.read_text(encoding="utf-8")
