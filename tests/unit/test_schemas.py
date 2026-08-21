from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agentloopgate.schemas import (
    CandidateRecord,
    DecisionRecord,
    EvidenceReceipt,
    FailureBundle,
    ObjectiveContract,
    RunRecord,
    SnapshotManifest,
    SourceTraceRef,
)

UTC_NOW = datetime(2026, 8, 20, tzinfo=UTC)
DIGEST_A = f"sha256:{'a' * 64}"
DIGEST_B = f"sha256:{'b' * 64}"


def objective_payload() -> dict:
    return {
        "contract_version": "1.0",
        "project": "AgentLoopGate",
        "primary_metric": "reliable_policy_compliant_resolution",
        "benchmark": {
            "name": "tau3-bench",
            "suite": "banking_knowledge",
            "commit": "PIN_BEFORE_PILOT",
        },
        "reliability": {"trials": 3, "stable_success_required": 3},
        "gates": {
            "leakage_hits_max": 0,
            "critical_violations_max": 0,
            "id_stable_task_net_min": 0,
            "ood_stable_task_net_min": -1,
            "replay_stable_task_net_min": -1,
            "catastrophic_regressions_max": 0,
            "mean_cost_ratio_max": 1.2,
            "p50_latency_ratio_max": 1.25,
        },
        "decision_order": [
            "evaluation_integrity",
            "leakage",
            "critical_violation",
            "id_effect",
            "ood_noninferiority",
            "replay",
            "reliability",
            "cost",
            "latency",
        ],
        "frozen_at": None,
        "contract_digest": None,
    }


def trace_payload() -> dict:
    return {
        "schema_version": "1.0",
        "source_trace_id": "STR_001",
        "runtime_host": "deepseek_harness",
        "source_locator": "binding:TB_001",
        "session_id_hash": DIGEST_A,
        "event_seq_start": 0,
        "event_seq_end": 2,
        "event_count": 3,
        "source_revision": DIGEST_B,
        "persistence_kind": "jsonl",
        "ingest_mode": "reference",
        "mirror_path": None,
        "mirror_digest": None,
        "cursor_complete": True,
        "evidence_status": "verified",
        "created_at": UTC_NOW,
    }


def test_models_forbid_extra_fields_and_invalid_enums() -> None:
    with pytest.raises(ValidationError):
        ObjectiveContract.model_validate({**objective_payload(), "unexpected": True})

    with pytest.raises(ValidationError):
        SourceTraceRef.model_validate({**trace_payload(), "ingest_mode": "copy_everything"})


def test_source_trace_enforces_range_and_mirror_evidence() -> None:
    with pytest.raises(ValidationError):
        SourceTraceRef.model_validate({**trace_payload(), "event_count": 4})

    with pytest.raises(ValidationError):
        SourceTraceRef.model_validate(
            {
                **trace_payload(),
                "ingest_mode": "mirror",
                "mirror_path": "runs/mirror/STR_001.jsonl",
                "mirror_digest": None,
            }
        )


def test_evidence_receipt_and_run_record_are_strict() -> None:
    receipt = EvidenceReceipt.model_validate(
        {
            "schema_version": "1.0",
            "receipt_id": "ER_001",
            "source_trace_id": "STR_001",
            "run_id": "R_001",
            "event_seq_start": 0,
            "event_seq_end": 2,
            "event_count": 3,
            "redaction_policy_digest": DIGEST_A,
            "normalized_record_digest": DIGEST_B,
            "collected_at": UTC_NOW,
            "error_count": 0,
        }
    )
    assert receipt.event_count == 3

    run = RunRecord.model_validate(
        {
            "schema_version": "1.0",
            "run_id": "R_001",
            "attempt_id": "A_001",
            "task_id": "banking_xxx",
            "pool": "update_source",
            "snapshot_id": "S_A0",
            "candidate_id": None,
            "source": "dsh",
            "runtime_host": "deepseek_harness",
            "runtime_version": "git:abc",
            "runtime_profile": "headless",
            "composition_digest": DIGEST_A,
            "model_id": "deepseek-chat",
            "benchmark_commit": "abc",
            "objective_digest": DIGEST_A,
            "split_digest": DIGEST_B,
            "initial_state_digest": DIGEST_A,
            "terminal_state_digest": DIGEST_B,
            "trial_index": 1,
            "run_validity": "valid",
            "success": False,
            "critical_violations": [],
            "input_tokens": 12,
            "output_tokens": 3,
            "latency_ms": 24,
            "cost": "0.000004",
            "source_trace_ref": "STR_001",
            "evidence_receipt_ref": "ER_001",
            "created_at": UTC_NOW,
        }
    )
    assert run.cost == Decimal("0.000004")
    assert run.model_dump(mode="json")["cost"] == "0.000004"

    with pytest.raises(ValidationError):
        RunRecord.model_validate(
            {
                **run.model_dump(mode="python"),
                "source": "dsh",
                "runtime_profile": None,
            }
        )

    with pytest.raises(ValidationError):
        RunRecord.model_validate(
            {
                **run.model_dump(mode="python"),
                "run_validity": "infra_invalid",
                "success": False,
            }
        )


def test_remaining_core_records_validate() -> None:
    failure = FailureBundle.model_validate(
        {
            "schema_version": "1.0",
            "failure_bundle_id": "FB_001",
            "snapshot_id": "S_A0",
            "source_pool": "update_source",
            "failure_type": "policy_application_error",
            "affected_run_ids": ["R_001"],
            "evidence_refs": ["runs/normalized/R_001.json"],
            "redacted_summary": "Agent missed a required exception check.",
            "target_asset_families": ["context_memory_skill"],
            "expected_behavior_change": "Check exceptions before action.",
            "must_not_change": ["objective", "grader", "split", "final_access"],
            "budget": {"max_files": 4, "max_changed_lines": 160},
        }
    )
    assert failure.source_pool == "update_source"

    candidate = CandidateRecord.model_validate(
        {
            "schema_version": "1.0",
            "candidate_id": "C_001",
            "parent_snapshot_id": "S_A0",
            "failure_bundle_digest": DIGEST_A,
            "updater": {"name": "ahe", "version": "commit_sha"},
            "hypothesis": "Exception checks improve policy compliance.",
            "asset_families": ["context_memory_skill"],
            "risk_tier": "L",
            "patch_path": "candidates/C_001.patch",
            "patch_digest": DIGEST_B,
            "changed_files": ["harness/skills/policy_check.md"],
            "predicted_effect": {
                "metric": "stable_success_task_count",
                "direction": "increase",
            },
            "status": "registered",
            "created_at": UTC_NOW,
        }
    )
    assert candidate.risk_tier == "L"

    snapshot = SnapshotManifest.model_validate(
        {
            "schema_version": "1.0",
            "snapshot_id": "S_A1",
            "parent_snapshot_id": "S_A0",
            "candidate_id": "C_001",
            "model_id": "deepseek-chat",
            "objective_digest": DIGEST_A,
            "split_digest": DIGEST_B,
            "asset_manifest_digest": DIGEST_A,
            "code_revision": "git:abc",
            "harness_files": {"harness/system_prompt.md": DIGEST_B},
            "runtime": {"host": "python_cli", "version": "0.1.0"},
            "created_at": UTC_NOW,
        }
    )
    assert snapshot.parent_snapshot_id == "S_A0"

    decision = DecisionRecord.model_validate(
        {
            "schema_version": "1.0",
            "decision_id": "D_001",
            "candidate_id": "C_001",
            "baseline_snapshot_id": "S_A0",
            "decision": "HOLD",
            "gates": [
                {
                    "name": "ood_noninferiority",
                    "status": "fail",
                    "evidence_ref": "artifacts/gates/ood.json",
                }
            ],
            "summary": "OOD noninferiority failed.",
            "human_approval": None,
            "created_at": UTC_NOW,
        }
    )
    assert decision.decision == "HOLD"
