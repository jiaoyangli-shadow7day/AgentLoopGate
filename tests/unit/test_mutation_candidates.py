from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentloopgate.candidates import CandidateRegistry, CandidateStateError
from agentloopgate.contracts import canonical_digest
from agentloopgate.mutation import (
    CandidateCheckCode,
    CandidateChecker,
    CheckDisposition,
    HarnessAssetManifest,
    MutationPolicy,
    freeze_trust_kernel,
)
from agentloopgate.schemas import (
    AssetFamily,
    CandidateStatus,
    FailureBundle,
    FailureType,
    Pool,
)

DIGEST_A = "sha256:" + "a" * 64


def manifest() -> HarnessAssetManifest:
    return HarnessAssetManifest.model_validate(
        {
            "schema_version": "1.0",
            "assets": [
                {
                    "asset_id": "prompt",
                    "family": "prompt_instruction",
                    "path_patterns": ["harness/system_prompt.md"],
                    "risk_tier": "L",
                    "allowed_operations": ["patch", "evaluate", "rollback"],
                    "rollback_unit": "prompt-unit",
                },
                {
                    "asset_id": "retrieval",
                    "family": "retrieval_search_policy",
                    "path_patterns": ["harness/retrieval/**"],
                    "risk_tier": "M",
                    "allowed_operations": ["patch", "evaluate", "rollback"],
                    "rollback_unit": "retrieval-unit",
                },
                {
                    "asset_id": "middleware",
                    "family": "middleware_runtime_code",
                    "path_patterns": ["harness/middleware/**"],
                    "risk_tier": "H",
                    "allowed_operations": ["propose", "evaluate", "rollback"],
                    "rollback_unit": "middleware-unit",
                },
            ],
        }
    )


def policy() -> MutationPolicy:
    return MutationPolicy.model_validate(
        {
            "schema_version": "1.0",
            "max_files": 4,
            "max_changed_lines": 160,
            "auto_executable_risks": ["L", "M"],
            "hold_risks": ["H"],
            "protected_paths": [
                "SPEC.md",
                "configs/objective_contract.yaml",
                "configs/splits.yaml",
                "agentloopgate/gates/**",
                "tests/evaluators/**",
            ],
            "trust_kernel_paths": ["SPEC.md", "configs/objective_contract.yaml"],
            "forbidden_content_patterns": [
                "(?i)required_documents",
                "(?i)expected[_ -]?action",
                "(?i)gold(en)?",
                "sk-[A-Za-z0-9]{20,}",
            ],
        }
    )


def patch_file(root: Path, body: str, *, name: str = "candidate.patch") -> Path:
    target = root / name
    target.write_text(body, encoding="utf-8")
    return target


def unified(path: str, added: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        f"+{added}\n"
    )


def project(root: Path) -> None:
    (root / "configs").mkdir(parents=True)
    (root / "harness/retrieval").mkdir(parents=True)
    (root / "harness/middleware").mkdir(parents=True)
    (root / "SPEC.md").write_text("spec", encoding="utf-8")
    (root / "configs/objective_contract.yaml").write_text("objective", encoding="utf-8")
    (root / "harness/system_prompt.md").write_text("old", encoding="utf-8")
    (root / "harness/retrieval/policy.yaml").write_text("old", encoding="utf-8")
    (root / "harness/middleware/hook.py").write_text("old", encoding="utf-8")


def failure_bundle() -> FailureBundle:
    return FailureBundle.model_validate(
        {
            "schema_version": "1.0",
            "failure_bundle_id": "FB_001",
            "snapshot_id": "S_A0",
            "source_pool": Pool.UPDATE_SOURCE,
            "failure_type": FailureType.POLICY_APPLICATION_ERROR,
            "affected_run_ids": ["R_001"],
            "evidence_refs": ["runs/diagnostics/R_001.json"],
            "redacted_summary": "A policy prerequisite was missed.",
            "target_asset_families": [AssetFamily.PROMPT_INSTRUCTION],
            "expected_behavior_change": "Check prerequisites before acting.",
            "must_not_change": ["objective", "grader", "split", "final_access"],
            "budget": {"max_files": 4, "max_changed_lines": 160},
        }
    )


def test_legal_l_and_m_patch_passes_and_reports_atomic_units(tmp_path: Path) -> None:
    project(tmp_path)
    trust = freeze_trust_kernel(tmp_path, policy())
    patch = patch_file(
        tmp_path,
        unified("harness/system_prompt.md", "check prerequisites")
        + unified("harness/retrieval/policy.yaml", "top_k: 8"),
    )

    result = CandidateChecker(tmp_path, manifest(), policy(), trust).check(patch)

    assert result.disposition is CheckDisposition.PASS
    assert result.code is CandidateCheckCode.PASS
    assert result.risk_tier.value == "M"
    assert result.changed_files == [
        "harness/retrieval/policy.yaml",
        "harness/system_prompt.md",
    ]
    assert result.rollback_units == ["prompt-unit", "retrieval-unit"]


@pytest.mark.parametrize(
    ("path", "added", "expected"),
    [
        ("configs/splits.yaml", "changed", CandidateCheckCode.REJECT_PROTECTED_PATH),
        ("unknown/file.md", "changed", CandidateCheckCode.REJECT_UNREGISTERED_PATH),
        (
            "harness/system_prompt.md",
            "read required_documents from evaluator",
            CandidateCheckCode.REJECT_LEAKAGE,
        ),
        (
            "tests/evaluators/grader.py",
            "changed",
            CandidateCheckCode.REJECT_PROTECTED_PATH,
        ),
    ],
)
def test_protected_unregistered_and_gold_feature_patches_are_rejected(
    tmp_path: Path,
    path: str,
    added: str,
    expected: CandidateCheckCode,
) -> None:
    project(tmp_path)
    checker = CandidateChecker(
        tmp_path,
        manifest(),
        policy(),
        freeze_trust_kernel(tmp_path, policy()),
    )

    result = checker.check(patch_file(tmp_path, unified(path, added)))

    assert result.disposition is CheckDisposition.REJECT
    assert result.code is expected


def test_risk_h_is_recordable_but_never_auto_executable(tmp_path: Path) -> None:
    project(tmp_path)
    checker = CandidateChecker(
        tmp_path,
        manifest(),
        policy(),
        freeze_trust_kernel(tmp_path, policy()),
    )

    result = checker.check(
        patch_file(tmp_path, unified("harness/middleware/hook.py", "raise RuntimeError"))
    )

    assert result.disposition is CheckDisposition.HOLD
    assert result.code is CandidateCheckCode.HOLD_RISK_H
    assert result.auto_executable is False


def test_budget_and_trust_kernel_drift_are_rejected(tmp_path: Path) -> None:
    project(tmp_path)
    trust = freeze_trust_kernel(tmp_path, policy())
    checker = CandidateChecker(tmp_path, manifest(), policy(), trust)
    oversized = (
        "diff --git a/harness/system_prompt.md b/harness/system_prompt.md\n"
        "--- a/harness/system_prompt.md\n"
        "+++ b/harness/system_prompt.md\n"
        "@@ -1 +1,161 @@\n"
        "-old\n"
        + "".join(f"+line {i}\n" for i in range(161))
    )
    assert (
        checker.check(patch_file(tmp_path, oversized)).code
        is CandidateCheckCode.REJECT_CHANGE_BUDGET
    )

    (tmp_path / "SPEC.md").write_text("tampered", encoding="utf-8")
    legal = patch_file(tmp_path, unified("harness/system_prompt.md", "safe"), name="legal.patch")
    assert checker.check(legal).code is CandidateCheckCode.REJECT_TRUST_KERNEL_DRIFT


def test_candidate_registry_is_append_only_and_enforces_state_machine(tmp_path: Path) -> None:
    project(tmp_path)
    checker = CandidateChecker(
        tmp_path,
        manifest(),
        policy(),
        freeze_trust_kernel(tmp_path, policy()),
    )
    patch = patch_file(tmp_path, unified("harness/system_prompt.md", "check prerequisites"))
    registry = CandidateRegistry(tmp_path, checker)

    record = registry.register(
        candidate_id="C_001",
        parent_snapshot_id="S_A0",
        failure_bundle=failure_bundle(),
        updater_name="fixture-updater",
        updater_version="1.0@abc123",
        hypothesis="Checking prerequisites reduces policy application failures.",
        patch_path=patch,
        predicted_metric="stable_success_task_count",
        predicted_direction="increase",
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert record.status is CandidateStatus.CHECKED
    assert record.failure_bundle_digest == canonical_digest(failure_bundle())
    assert registry.load("C_001") == record
    assert len(list((tmp_path / "candidates/C_001/events").glob("*.json"))) == 1
    transitioned = registry.transition("C_001", CandidateStatus.UPDATE_EVALUATED)
    assert transitioned.status is CandidateStatus.UPDATE_EVALUATED
    assert len(list((tmp_path / "candidates/C_001/events").glob("*.json"))) == 2

    with pytest.raises(CandidateStateError, match="transition"):
        registry.transition("C_001", CandidateStatus.SHIPPED)
    with pytest.raises(CandidateStateError, match="already exists"):
        registry.register(
            candidate_id="C_001",
            parent_snapshot_id="S_A0",
            failure_bundle=failure_bundle(),
            updater_name="fixture-updater",
            updater_version="1.0@abc123",
            hypothesis="Duplicate.",
            patch_path=patch,
            predicted_metric="stable_success_task_count",
            predicted_direction="increase",
            created_at=datetime(2026, 8, 20, tzinfo=UTC),
        )
