from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

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
    for gate in decision().gates:
        evidence = root / gate.evidence_ref
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text('{}\n', encoding="utf-8")
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


def test_promote_requires_human_approval_and_rollback_restores_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    with pytest.raises(SnapshotAuthorizationError, match="matching formal report"):
        manager.promote(
            child.snapshot_id, decision(),
            approval=approval(ApprovalAction.PROMOTE, child.snapshot_id),
        )
    monkeypatch.setattr(manager, "_verify_formal_promotion", lambda *_args: None)
    with pytest.raises(SnapshotAuthorizationError, match="approval"):
        manager.promote(child.snapshot_id, decision(), approval=None)
    with pytest.raises(SnapshotAuthorizationError, match="SHIP_RECOMMENDED"):
        manager.promote(
            child.snapshot_id,
            decision("HOLD"),
            approval=approval(ApprovalAction.PROMOTE, child.snapshot_id),
        )

    contradictory = decision()
    contradictory.gates[0].status = "fail"
    with pytest.raises(SnapshotAuthorizationError, match="every gate"):
        manager.promote(
            child.snapshot_id,
            contradictory,
            approval=approval(ApprovalAction.PROMOTE, child.snapshot_id),
        )

    missing = tmp_path / decision().gates[0].evidence_ref
    missing.unlink()
    with pytest.raises(SnapshotAuthorizationError, match="evidence is unavailable"):
        manager.promote(
            child.snapshot_id, decision(),
            approval=approval(ApprovalAction.PROMOTE, child.snapshot_id),
        )
    missing.write_text('{}\n', encoding="utf-8")

    activation = manager.promote(
        child.snapshot_id,
        decision(),
        approval=approval(ApprovalAction.PROMOTE, child.snapshot_id),
    )
    assert activation.snapshot_id == child.snapshot_id
    assert prompt.read_text(encoding="utf-8") == "new\n"
    assert manager.active_snapshot().snapshot_id == child.snapshot_id
    assert (
        manager.promote(
            child.snapshot_id,
            decision(),
            approval=approval(ApprovalAction.PROMOTE, child.snapshot_id),
        )
        == activation
    )

    rolled_back = manager.rollback(
        baseline.snapshot_id,
        approval=approval(ApprovalAction.ROLLBACK, baseline.snapshot_id),
    )
    assert rolled_back.snapshot_id == baseline.snapshot_id
    assert prompt.read_text(encoding="utf-8") == "old\n"
    assert manager.verify(baseline.snapshot_id) == baseline
    assert (
        manager.rollback(
            baseline.snapshot_id,
            approval=approval(ApprovalAction.ROLLBACK, baseline.snapshot_id),
        )
        == rolled_back
    )


def test_interrupted_promotion_recovers_parent_before_retry(tmp_path: Path, monkeypatch) -> None:
    prompt = tmp_path / "harness/system_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("old\n", encoding="utf-8")
    manager = SnapshotManager(tmp_path)
    monkeypatch.setattr(manager, "_verify_formal_promotion", lambda *_args: None)
    manager.create_baseline(
        snapshot_id="S_A0",
        harness_paths=["harness/system_prompt.md"],
        model_id="fixture",
        objective_digest=DIGEST_A,
        split_digest=DIGEST_B,
        asset_manifest_digest=DIGEST_C,
        code_revision="fixture",
        runtime_host="python_cli",
        runtime_version="fixture",
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    child = manager.create_child(
        candidate(tmp_path),
        model_id="fixture",
        code_revision="fixture",
        runtime_host="python_cli",
        runtime_version="fixture",
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    original = manager._materialize_live

    def interrupted(target):
        prompt.write_text("partial\n", encoding="utf-8")
        raise OSError("simulated interruption")

    monkeypatch.setattr(manager, "_materialize_live", interrupted)
    with pytest.raises(OSError, match="interruption"):
        manager.promote(
            child.snapshot_id,
            decision(),
            approval=approval(ApprovalAction.PROMOTE, child.snapshot_id),
        )
    monkeypatch.setattr(manager, "_materialize_live", original)
    assert manager.active_snapshot().snapshot_id == "S_A0"
    assert prompt.read_text(encoding="utf-8") == "old\n"
    manager.promote(
        child.snapshot_id, decision(), approval=approval(ApprovalAction.PROMOTE, child.snapshot_id)
    )
    assert prompt.read_text(encoding="utf-8") == "new\n"


def test_snapshot_journal_write_failure_leaves_no_partial_file(tmp_path: Path, monkeypatch) -> None:
    def fail_link(*_args):
        raise OSError("simulated link failure")

    monkeypatch.setattr("agentloopgate.snapshots.manager.os.link", fail_link)
    destination = tmp_path / "pending_activation.json"
    with pytest.raises(OSError, match="link failure"):
        SnapshotManager._write_once(destination, {"fixture": True})
    assert not destination.exists()
    assert not list(tmp_path.glob(".snapshot-write-*"))


@pytest.mark.parametrize("phase", ["before_journal_link", "after_first_file", "after_activation"])
def test_process_death_recovers_snapshot_transaction(tmp_path: Path, phase: str) -> None:
    prompt = tmp_path / "harness/system_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("old\n", encoding="utf-8")
    (prompt.parent / "z.md").write_text("unchanged\n", encoding="utf-8")
    manager = SnapshotManager(tmp_path)
    now = datetime(2026, 8, 20, tzinfo=UTC)
    manager.create_baseline(
        snapshot_id="S_A0", harness_paths=["harness/system_prompt.md", "harness/z.md"],
        model_id="fixture", objective_digest=DIGEST_A, split_digest=DIGEST_B,
        asset_manifest_digest=DIGEST_C, code_revision="fixture", runtime_host="python_cli",
        runtime_version="fixture", created_at=now,
    )
    child = manager.create_child(
        candidate(tmp_path), model_id="fixture", code_revision="fixture",
        runtime_host="python_cli", runtime_version="fixture", created_at=now,
    )
    (tmp_path / "decision.json").write_text(decision().model_dump_json(), encoding="utf-8")
    (tmp_path / "approval.json").write_text(
        approval(ApprovalAction.PROMOTE, child.snapshot_id).model_dump_json(), encoding="utf-8"
    )
    script = r'''
import os, sys
from pathlib import Path
from agentloopgate.schemas import DecisionRecord
from agentloopgate.snapshots import PromotionApproval, SnapshotManager
root, target, phase = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
manager = SnapshotManager(root)
manager._verify_formal_promotion = lambda *_args: None
if phase == "before_journal_link":
    original = os.link
    def crash(source, destination):
        if Path(destination).name == "pending_activation.json":
            os._exit(73)
        return original(source, destination)
    os.link = crash
elif phase == "after_first_file":
    original = Path.replace
    def crash(path, destination):
        result = original(path, destination)
        if path.name.endswith(".alg.tmp"):
            os._exit(73)
        return result
    Path.replace = crash
else:
    original = manager._append_activation
    def crash(event):
        original(event)
        os._exit(73)
    manager._append_activation = crash
manager.promote(target, DecisionRecord.model_validate_json((root / "decision.json").read_text()),
    approval=PromotionApproval.model_validate_json((root / "approval.json").read_text()))
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), child.snapshot_id, phase],
        cwd=Path.cwd(), env={"PATH": os.defpath, "PYTHONPATH": str(Path.cwd())},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 73, result.stderr
    journal = tmp_path / "snapshots/pending_activation.json"
    assert journal.is_file() == (phase != "before_journal_link")
    active = manager.active_snapshot()
    expected = child.snapshot_id if phase == "after_activation" else "S_A0"
    assert active.snapshot_id == expected
    expected_prompt = "new\n" if phase == "after_activation" else "old\n"
    assert prompt.read_text(encoding="utf-8") == expected_prompt
    assert (prompt.parent / "z.md").read_text(encoding="utf-8") == "unchanged\n"
    assert not journal.exists()


def test_formal_promotion_requires_matching_candidate_and_paired_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentloopgate.experiment import batch as batch_module
    from agentloopgate.experiment import orchestrator as orchestrator_module
    from agentloopgate.experiment import service as service_module
    from agentloopgate.experiment.batch import FormalStage
    from agentloopgate.mutation import (
        CandidateChecker,
        HarnessAssetManifest,
        MutationPolicy,
        freeze_trust_kernel,
    )
    from agentloopgate.schemas import AssetFamily, CandidateStatus

    record = decision()
    report = tmp_path / "reports/EXP_TEST/decision.json"
    report.parent.mkdir(parents=True)
    report.write_text(record.model_dump_json(), encoding="utf-8")
    config = tmp_path / "configs/formal_experiment_test.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("fixture", encoding="utf-8")
    root = tmp_path / "runs/experiments/EXP_TEST"
    (root / "batches").mkdir(parents=True)
    (root / "trust_kernel.json").write_text("{}", encoding="utf-8")
    (tmp_path / "SPEC.md").write_text("frozen governance", encoding="utf-8")
    manifest = HarnessAssetManifest.model_validate({
        "schema_version": "1.0", "assets": [{"asset_id": "prompt",
        "family": "prompt_instruction", "path_patterns": ["harness/system_prompt.md"],
        "risk_tier": "L", "allowed_operations": ["patch"], "rollback_unit": "U_1"}],
    })
    policy = MutationPolicy.model_validate({
        "schema_version": "1.0", "max_files": 2, "max_changed_lines": 10,
        "auto_executable_risks": ["L", "M"], "hold_risks": ["H"],
        "protected_paths": ["SPEC.md"], "trust_kernel_paths": ["SPEC.md"],
        "forbidden_content_patterns": ["forbidden-content"],
    })
    checker = CandidateChecker(tmp_path, manifest, policy, freeze_trust_kernel(tmp_path, policy))
    candidate_record = candidate(tmp_path)
    check = checker.check(tmp_path / candidate_record.patch_path)
    check_path = tmp_path / "candidates/C_001/check.json"
    check_path.write_text(check.model_dump_json(), encoding="utf-8")
    ids = [f"B_{i}" for i in range(9)]
    (root / "lineage.json").write_text(json.dumps({
        "schema_version": "1.0", "experiment_id": "EXP_TEST",
        "pilot_evidence_join_ids": ["J_1", "J_2", "J_3"], "batch_ids": ids,
        "candidate_ids": ["C_001", "C_002", "C_003"],
        "snapshot_ids": ["S_A0", "S_CHILD", "S_2", "S_3"],
        "lineage_digest": DIGEST_A,
    }), encoding="utf-8")
    stages = [FormalStage.RELEASE_ID, FormalStage.RELEASE_OOD, FormalStage.REPLAY]
    for i, batch_id in enumerate(ids):
        snapshot = ("S_A0" if i < 3 else "S_CHILD") if i < 6 else [
            "S_CHILD", "S_2", "S_3"
        ][i - 6]
        (root / "batches" / f"{batch_id}.json").write_text(json.dumps({
            "snapshot": snapshot,
            "stage": stages[i % 3].value if i < 6 else FormalStage.SELECTION.value,
        }), encoding="utf-8")
    monkeypatch.setattr(service_module, "load_formal_config", lambda _: SimpleNamespace(
        experiment_id="EXP_TEST", baseline_snapshot_id="S_A0",
    ))
    monkeypatch.setattr(batch_module.FormalBatchArtifact, "model_validate_json", lambda raw: (
        lambda data: SimpleNamespace(spec=SimpleNamespace(snapshot_id=data["snapshot"]),
                                     stage=FormalStage(data["stage"]))
    )(json.loads(raw)))
    formal = SimpleNamespace(outcome=SimpleNamespace(record=record))
    selection = SimpleNamespace(selection=SimpleNamespace(
        native_candidate_id="C_001", agentloopgate_candidate_id="C_001",
        agentloopgate_decision=None,
    ))
    (root / "selection.json").write_text("{}")
    monkeypatch.setattr(orchestrator_module.FormalSelectionArtifact, "model_validate_json",
                        lambda _: selection)
    outcome = SimpleNamespace(
        p0_requirements_met=True, final_decision=record.decision,
        agentloopgate_candidate_id="C_001", baseline_snapshot_id="S_A0",
        report_file_digests={"reports/EXP_TEST/decision.json": file_digest(report)},
        candidate_ids=["C_001", "C_002", "C_003"],
        candidate_snapshot_ids=["S_CHILD", "S_2", "S_3"],
        asset_family_count=2, held_or_rejected_candidate_count=1,
        external_rejection_count=0,
        native_candidate_id="C_001",
    )
    proposal = {"schema_version": "1.0", "signal_kind": "ahe_emission_order",
        "candidate_ids": outcome.candidate_ids, "signal_refs": [
            f"runs/updaters/ahe/{candidate_id}/run_metadata.json"
            for candidate_id in outcome.candidate_ids
        ]}
    (root / "proposal_plan.json").write_text(json.dumps({
        **proposal, "plan_digest": canonical_digest(proposal),
    }))
    for reference in proposal["signal_refs"]:
        metadata = tmp_path / reference
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text("{}")

    class FakeOrchestrator:
        def __init__(self, project_root, *, config_path):
            self.experiment_root = project_root / "runs/experiments/EXP_TEST"
            self.config = SimpleNamespace(candidate_count=3, min_asset_families=2,
                min_rejected_or_held_candidates=1, schema_version="1.0")

        def _registry(self):
            return SimpleNamespace(
                load=lambda candidate_id: {
                    "C_001": candidate_record,
                    "C_002": candidate_record.model_copy(update={
                        "candidate_id": "C_002",
                        "asset_families": [AssetFamily.TOOL_CONTRACT_ROUTING],
                    }),
                    "C_003": candidate_record.model_copy(update={
                        "candidate_id": "C_003", "status": CandidateStatus.HELD,
                    }),
                }[candidate_id],
                checker=checker,
            )

        def _load_verified_outcome(self, _path):
            return outcome

        def _load_decision(self, _selector):
            return formal

        def _select(self, *_args, **_kwargs):
            return selection

        def _decide_selected(self, selector, candidate_id, snapshot_id, baseline, batches,
                             lineage, *, persist):
            assert selector == "agentloopgate" and candidate_id == "C_001"
            assert snapshot_id == "S_CHILD" and baseline == "S_A0" and persist is False
            assert all(set(group) == set(stages) for group in batches.values())
            return formal

    monkeypatch.setattr(orchestrator_module, "FormalExperimentOrchestrator", FakeOrchestrator)
    manager = SnapshotManager(tmp_path)
    monkeypatch.setattr(manager, "verify", lambda snapshot_id: SimpleNamespace(
        candidate_id={"S_CHILD": "C_001", "S_2": "C_002", "S_3": "C_003"}.get(snapshot_id),
        parent_snapshot_id="S_A0",
    ))
    target = SimpleNamespace(snapshot_id="S_CHILD", parent_snapshot_id="S_A0")
    manager._verify_formal_promotion(target, record)
    outcome.report_file_digests = {}
    with pytest.raises(SnapshotAuthorizationError, match="does not authorize"):
        manager._verify_formal_promotion(target, record)
    outcome.report_file_digests = {"reports/EXP_TEST/decision.json": file_digest(report)}
    check_path.write_text(check.model_copy(update={"patch_digest": DIGEST_B}).model_dump_json())
    with pytest.raises(SnapshotAuthorizationError, match="candidate safety check"):
        manager._verify_formal_promotion(target, record)
    check_path.write_text(check.model_dump_json())
    (tmp_path / "SPEC.md").write_text("changed governance", encoding="utf-8")
    with pytest.raises(SnapshotAuthorizationError, match="candidate safety check"):
        manager._verify_formal_promotion(target, record)
    (tmp_path / "SPEC.md").write_text("frozen governance", encoding="utf-8")
    outcome.candidate_snapshot_ids[0] = "S_OTHER"
    with pytest.raises(SnapshotAuthorizationError, match="does not authorize"):
        manager._verify_formal_promotion(target, record)
    outcome.candidate_snapshot_ids[0] = "S_CHILD"
    (root / "batches/B_5.json").unlink()
    with pytest.raises(SnapshotAuthorizationError, match="verification failed"):
        manager._verify_formal_promotion(target, record)


def test_snapshot_rejects_live_harness_drift_before_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = tmp_path / "harness/system_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("old\n", encoding="utf-8")
    manager = SnapshotManager(tmp_path)
    monkeypatch.setattr(manager, "_verify_formal_promotion", lambda *_args: None)
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


def test_reviewed_evaluation_baseline_can_differ_without_activation(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "harness/system_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("deployed\n", encoding="utf-8")
    manager = SnapshotManager(tmp_path)
    manager.create_baseline(
        snapshot_id="S_A0",
        harness_paths=["harness/system_prompt.md"],
        model_id="fixture-model",
        objective_digest=DIGEST_A,
        split_digest=DIGEST_B,
        asset_manifest_digest=DIGEST_C,
        code_revision="deployed-revision",
        runtime_host="python_cli",
        runtime_version="fixture@1",
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    prompt.write_text("reviewed evaluation revision\n", encoding="utf-8")

    evaluation = manager.create_evaluation_baseline(
        snapshot_id="R11_A0",
        harness_paths=["harness/system_prompt.md"],
        model_id="fixture-model",
        objective_digest=DIGEST_A,
        split_digest=DIGEST_B,
        asset_manifest_digest=DIGEST_C,
        code_revision="reviewed-r11-revision",
        runtime_host="deepseek_harness",
        runtime_version="deepseek-harness@fixture",
        created_at=datetime(2026, 8, 23, tzinfo=UTC),
        allow_reviewed_harness_revision=True,
    )

    assert evaluation.harness_files != manager.active_snapshot().harness_files
    assert manager.verify_live(evaluation.snapshot_id) == evaluation
    assert manager.active_snapshot().snapshot_id == "S_A0"
    assert len(list((tmp_path / "snapshots/activations").glob("*.json"))) == 1
    with pytest.raises(SnapshotAuthorizationError, match="drift"):
        manager.verify_active_live()


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
        path.is_file() and path.read_text().startswith("<svg") for path in artifact.chart_paths
    )
    assert "HOLD" in artifact.decision_markdown.read_text(encoding="utf-8")
    assert canonical_digest(record) in artifact.decision_markdown.read_text(encoding="utf-8")


def test_synthetic_release_decision_and_promotion_integrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay synthetic batch evidence through the real verifier before promotion."""
    import yaml

    from agentloopgate.candidates import CandidateRegistry
    from agentloopgate.experiment.batch import FormalBatchSpec, FormalStage
    from agentloopgate.experiment.orchestrator import (
        FormalExperimentOrchestrator,
        FormalExperimentOutcome,
        FormalLineageArtifact,
    )
    from agentloopgate.experiment.service import FormalExperimentService
    from agentloopgate.mutation import (
        CandidateChecker,
        freeze_trust_kernel,
        load_asset_manifest,
        load_mutation_policy,
    )
    from agentloopgate.schemas import AssetFamily, CandidateStatus

    config_root = tmp_path / "configs"
    config_root.mkdir()
    (config_root / "objective_contract.yaml").write_bytes(
        Path("configs/objective_contract.yaml").read_bytes()
    )
    formal_config = yaml.safe_load(Path("configs/formal_experiment.yaml").read_text())
    formal_config.update(experiment_id="EXP_TEST", baseline_snapshot_id="S_A0")
    config_path = config_root / "formal_experiment_test.yaml"
    config_path.write_text(yaml.safe_dump(formal_config))
    manifest_data = {"schema_version": "1.0", "assets": [{"asset_id": "prompt",
        "family": "prompt_instruction", "path_patterns": ["harness/system_prompt.md"],
        "risk_tier": "L", "allowed_operations": ["patch"], "rollback_unit": "U_1"}]}
    policy_data = {"schema_version": "1.0", "max_files": 2, "max_changed_lines": 10,
        "auto_executable_risks": ["L", "M"], "hold_risks": ["H"],
        "protected_paths": ["SPEC.md"], "trust_kernel_paths": ["SPEC.md"],
        "forbidden_content_patterns": ["forbidden-content"]}
    (config_root / "harness_assets.yaml").write_text(yaml.safe_dump(manifest_data))
    (config_root / "mutation_policy.yaml").write_text(yaml.safe_dump(policy_data))
    (tmp_path / "SPEC.md").write_text("frozen governance")
    prompt = tmp_path / "harness/system_prompt.md"
    prompt.parent.mkdir()
    prompt.write_text("old\n")
    manager = SnapshotManager(tmp_path)
    now = datetime(2026, 8, 20, tzinfo=UTC)
    manager.create_baseline(snapshot_id="S_A0", harness_paths=["harness/system_prompt.md"],
        model_id="fixture", objective_digest=DIGEST_A, split_digest=DIGEST_B,
        asset_manifest_digest=DIGEST_C, code_revision="fixture", runtime_host="python_cli",
        runtime_version="fixture", created_at=now)
    selected = candidate(tmp_path)
    policy = load_mutation_policy(config_root / "mutation_policy.yaml")
    trust = freeze_trust_kernel(tmp_path, policy)
    checker = CandidateChecker(tmp_path, load_asset_manifest(config_root / "harness_assets.yaml"),
                               policy, trust)
    checked = checker.check(tmp_path / selected.patch_path)
    (tmp_path / "candidates/C_001/check.json").write_text(checked.model_dump_json())
    registry = CandidateRegistry(tmp_path, checker)
    registry._append_event(tmp_path / "candidates/C_001", selected, previous_status=None,
                           actor="fixture", evidence_refs=["fixture"], occurred_at=now)
    children = []
    for index in range(1, 4):
        item = selected.model_copy(update={"candidate_id": f"C_00{index}"})
        children.append(manager.create_child(item, model_id="fixture", code_revision="fixture",
            runtime_host="python_cli", runtime_version="fixture", created_at=now))
        if index > 1:
            item = item.model_copy(update=(
                {"asset_families": [AssetFamily.TOOL_CONTRACT_ROUTING]} if index == 2
                else {"status": CandidateStatus.HELD}
            ))
            registry._append_event(tmp_path / f"candidates/C_00{index}", item,
                previous_status=None, actor="fixture", evidence_refs=["fixture"], occurred_at=now)
    experiment_root = tmp_path / "runs/experiments/EXP_TEST"
    experiment_root.mkdir(parents=True)
    (experiment_root / "trust_kernel.json").write_text(trust.model_dump_json())
    stages = {FormalStage.RELEASE_ID: "release_id", FormalStage.RELEASE_OOD: "release_ood",
              FormalStage.REPLAY: "update_source"}
    batches = {"S_A0": {}, **{item.snapshot_id: {} for item in children}}
    candidate_by_snapshot = {item.snapshot_id: f"C_00{index}"
                             for index, item in enumerate(children, start=1)}
    lookup = {}
    from formal_promotion_fixture import generate_batch

    (config_root / "trace_redaction.yaml").write_bytes(
        Path("configs/trace_redaction.yaml").read_bytes()
    )
    monkeypatch.setenv("AGENTLOOPGATE_TASK_ATTEMPT_LEDGER_SCHEMA_VERSION", "1.1")
    runners = {}
    executors = {}
    for snapshot_id in batches:
        is_candidate = snapshot_id != "S_A0"
        applicable = dict(stages) if snapshot_id in {"S_A0", children[0].snapshot_id} else {}
        if is_candidate:
            applicable[FormalStage.SELECTION] = "selection"
        for stage, pool in applicable.items():
            spec = FormalBatchSpec(experiment_id="EXP_TEST", stage=stage, pool=pool,
                snapshot_id=snapshot_id, candidate_id=candidate_by_snapshot.get(snapshot_id),
                task_ids=["task_001"], trials=3, agent_model="fixture", user_model="fixture",
                objective_digest=DIGEST_A, split_digest=DIGEST_B, benchmark_commit="fixture",
                initial_state_digests={"task_001": DIGEST_C}, protocol_digest=DIGEST_C)
            runner, executor, artifact = generate_batch(tmp_path, spec)
            batches[snapshot_id][stage] = artifact
            lookup[(stage, snapshot_id)] = artifact
            runners[(stage, snapshot_id)] = runner
            executors[(stage, snapshot_id)] = executor

    def fixture_stage(_service, stage, *, snapshot_id, existing_only, verify_only):
        assert existing_only and verify_only
        return runners[(stage, snapshot_id)].verify_existing(lookup[(stage, snapshot_id)].spec)

    monkeypatch.setattr(FormalExperimentService, "ensure_baseline",
                        lambda _self, require_active: "S_A0")
    monkeypatch.setattr(FormalExperimentService, "run_stage", fixture_stage)
    orchestrator = FormalExperimentOrchestrator(tmp_path, config_path=config_path)
    lineage_data = {"schema_version": "1.0", "experiment_id": "EXP_TEST",
        "pilot_evidence_join_ids": ["J_1", "J_2", "J_3"],
        "batch_ids": [item.batch_id for item in lookup.values()],
        "candidate_ids": ["C_001", "C_002", "C_003"],
        "snapshot_ids": ["S_A0", *(item.snapshot_id for item in children)]}
    lineage = FormalLineageArtifact.model_validate({**lineage_data,
        "lineage_digest": canonical_digest(lineage_data)})
    (experiment_root / "lineage.json").write_text(lineage.model_dump_json())
    selection_batches = {item.snapshot_id: batches[item.snapshot_id][FormalStage.SELECTION]
                         for item in children}
    selection_candidates = [registry.load(f"C_00{index}") for index in range(1, 4)]
    orchestrator._write_proposal_plan(selection_candidates)
    for item in selection_candidates:
        metadata = tmp_path / "runs/updaters/ahe" / item.candidate_id / "run_metadata.json"
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text("{}")
    selection = orchestrator._select("S_A0", selection_candidates,
                                     [item.snapshot_id for item in children], selection_batches)
    assert selection.selection.agentloopgate_candidate_id == "C_001"
    for selector in ("native", "agentloopgate"):
        formal = orchestrator._decide_selected(selector, "C_001", children[0].snapshot_id,
                                               "S_A0", batches, lineage)
    record = formal.outcome.record
    assert record.decision.value == "SHIP_RECOMMENDED"
    report = tmp_path / "reports/EXP_TEST/decision.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(record.model_dump_json())
    outcome_data = {"schema_version": "1.0", "experiment_id": "EXP_TEST",
        "baseline_snapshot_id": "S_A0", "candidate_ids": lineage.candidate_ids,
        "candidate_snapshot_ids": [item.snapshot_id for item in children],
        "native_candidate_id": "C_001", "agentloopgate_candidate_id": "C_001",
        "native_decision": "SHIP_RECOMMENDED", "final_decision": "SHIP_RECOMMENDED",
        "external_rejection_count": 0, "held_or_rejected_candidate_count": 1,
        "asset_family_count": 2, "p0_requirements_met": True,
        "lineage_digest": lineage.lineage_digest, "report_digest": DIGEST_A,
        "report_file_digests": {"reports/EXP_TEST/decision.json": file_digest(report)}}
    outcome = FormalExperimentOutcome.model_validate({**outcome_data,
        "outcome_digest": canonical_digest(outcome_data)})
    (experiment_root / "outcome.json").write_text(outcome.model_dump_json())
    record_path = experiment_root / "batches" / f"{next(iter(lookup.values())).batch_id}.json"
    original = record_path.read_text()
    changed = json.loads(original)
    changed["summary"]["mean_cost"] = "50"
    record_path.write_text(json.dumps(changed))
    with pytest.raises(SnapshotAuthorizationError, match="verification failed"):
        manager.promote(children[0].snapshot_id, record,
                        approval=approval(ApprovalAction.PROMOTE, children[0].snapshot_id))
    assert prompt.read_text() == "old\n"
    record_path.write_text(original)
    raw = tmp_path / next(iter(lookup.values())).result_artifact
    raw_original = raw.read_text()
    raw.write_text(raw_original.replace('"agent_cost": 0.001', '"agent_cost": 0.02'))
    with pytest.raises(SnapshotAuthorizationError, match="verification failed"):
        manager.promote(children[0].snapshot_id, record,
                        approval=approval(ApprovalAction.PROMOTE, children[0].snapshot_id))
    raw.write_text(raw_original)
    selection_path = experiment_root / "selection.json"
    selection_original = selection_path.read_text()
    selection_changed = json.loads(selection_original)
    selection_changed["selection"]["agentloopgate_candidate_id"] = "C_002"
    selection_path.write_text(json.dumps(selection_changed))
    with pytest.raises(SnapshotAuthorizationError, match="selection does not match"):
        manager.promote(children[0].snapshot_id, record,
                        approval=approval(ApprovalAction.PROMOTE, children[0].snapshot_id))
    selection_path.write_text(selection_original)
    plan_path = experiment_root / "proposal_plan.json"
    plan_original = plan_path.read_text()
    bad_plan = json.loads(plan_original)
    bad_plan["candidate_ids"] = list(reversed(bad_plan["candidate_ids"]))
    bad_plan["plan_digest"] = canonical_digest({
        key: value for key, value in bad_plan.items() if key != "plan_digest"
    })
    plan_path.write_text(json.dumps(bad_plan))
    with pytest.raises(SnapshotAuthorizationError, match="proposal order evidence"):
        manager.promote(children[0].snapshot_id, record,
                        approval=approval(ApprovalAction.PROMOTE, children[0].snapshot_id))
    plan_path.write_text(plan_original)
    bad_outcome_data = {**outcome_data, "asset_family_count": 1}
    bad_outcome = FormalExperimentOutcome.model_validate({**bad_outcome_data,
        "outcome_digest": canonical_digest(bad_outcome_data)})
    (experiment_root / "outcome.json").write_text(bad_outcome.model_dump_json())
    with pytest.raises(SnapshotAuthorizationError, match="candidate diversity"):
        manager.promote(children[0].snapshot_id, record,
                        approval=approval(ApprovalAction.PROMOTE, children[0].snapshot_id))
    (experiment_root / "outcome.json").write_text(outcome.model_dump_json())
    activation = manager.promote(children[0].snapshot_id, record,
                                 approval=approval(ApprovalAction.PROMOTE, children[0].snapshot_id))
    assert activation.snapshot_id == children[0].snapshot_id
    assert manager.active_snapshot().snapshot_id == children[0].snapshot_id
    assert prompt.read_text() == "new\n"
    repeated = manager.promote(children[0].snapshot_id, record,
                               approval=approval(ApprovalAction.PROMOTE, children[0].snapshot_id))
    assert repeated == activation
    assert all(executor.calls == 1 for executor in executors.values())
