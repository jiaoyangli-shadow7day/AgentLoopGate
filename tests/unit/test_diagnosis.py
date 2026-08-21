from __future__ import annotations

from decimal import Decimal

import pytest

from agentloopgate.diagnosis import (
    DiagnosisError,
    DiagnosticSignals,
    FailureDiagnoser,
)
from agentloopgate.schemas import FailureType, Pool, RunValidity


def signals(**overrides: object) -> DiagnosticSignals:
    values: dict[str, object] = {
        "schema_version": "1.0",
        "run_id": "R_001",
        "task_id": "task_001",
        "snapshot_id": "S_A0",
        "pool": "update_source",
        "run_validity": "valid",
        "success": False,
        "evidence_ref": "runs/diagnostics/R_001.json",
        "retrieval_required": True,
        "retrieval_attempted": True,
        "retrieved_document_count": 2,
        "required_document_count": 2,
        "gold_document_coverage": True,
        "cross_document_reasoning_correct": True,
        "policy_application_correct": True,
        "tool_required": False,
        "tool_discovered": None,
        "tool_selected_correctly": None,
        "tool_parameters_correct": None,
        "action_order_correct": None,
        "terminal_state_verified": True,
        "recovery_required": False,
        "recovery_succeeded": None,
        "user_claim_overtrust": False,
        "evaluator_conflict": False,
        "user_value_loss": "1.0",
        "risk_weight": "1.0",
        "fixability": "1.0",
    }
    values.update(overrides)
    return DiagnosticSignals.model_validate(values)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {"retrieval_attempted": False, "retrieved_document_count": 0},
            FailureType.RETRIEVAL_MISS,
        ),
        ({"gold_document_coverage": False}, FailureType.DOCUMENT_SELECTION_ERROR),
        (
            {"cross_document_reasoning_correct": False},
            FailureType.CROSS_DOCUMENT_REASONING_ERROR,
        ),
        ({"policy_application_correct": False}, FailureType.POLICY_APPLICATION_ERROR),
        (
            {"tool_required": True, "tool_discovered": False},
            FailureType.TOOL_DISCOVERY_ERROR,
        ),
        (
            {
                "tool_required": True,
                "tool_discovered": True,
                "tool_selected_correctly": False,
            },
            FailureType.TOOL_SELECTION_ERROR,
        ),
        (
            {
                "tool_required": True,
                "tool_discovered": True,
                "tool_selected_correctly": True,
                "tool_parameters_correct": False,
            },
            FailureType.TOOL_PARAMETER_ERROR,
        ),
    ],
)
def test_known_failure_funnel_classification(
    overrides: dict[str, object],
    expected: FailureType,
) -> None:
    assert FailureDiagnoser().classify(signals(**overrides)) is expected


def test_infra_invalid_is_not_misclassified_as_agent_failure() -> None:
    result = FailureDiagnoser().classify(
        signals(run_validity=RunValidity.INFRA_INVALID, success=None)
    )
    assert result is FailureType.INFRA_FAILURE


def test_failure_bundle_is_ranked_redacted_and_update_source_only() -> None:
    diagnoser = FailureDiagnoser()
    failures = [
        signals(run_id="R_001", task_id="task_001", policy_application_correct=False),
        signals(
            run_id="R_002",
            task_id="task_002",
            evidence_ref="runs/diagnostics/R_002.json",
            policy_application_correct=False,
            user_value_loss="2.0",
            risk_weight="3.0",
            fixability="0.5",
        ),
    ]

    ranked = diagnoser.build_bundles(failures, protected_terms={"private-gold-document"})

    assert len(ranked) == 1
    assert ranked[0].priority == Decimal("6.00")
    bundle = ranked[0].bundle
    assert bundle.failure_type is FailureType.POLICY_APPLICATION_ERROR
    assert bundle.source_pool is Pool.UPDATE_SOURCE
    assert bundle.affected_run_ids == ["R_001", "R_002"]
    serialized = bundle.model_dump_json()
    assert "private-gold-document" not in serialized
    assert "expected_action" not in serialized.casefold()

    with pytest.raises(DiagnosisError, match="update_source"):
        diagnoser.build_bundles([signals(pool="pilot")])


def test_successful_run_cannot_be_turned_into_a_failure_bundle() -> None:
    with pytest.raises(DiagnosisError, match="successful"):
        FailureDiagnoser().classify(signals(success=True))
