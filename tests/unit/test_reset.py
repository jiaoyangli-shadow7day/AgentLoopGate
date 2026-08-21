from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentloopgate.cli import app
from agentloopgate.evaluation.reset import (
    InfraInvalidReason,
    ResetManager,
    assess_infrastructure,
)
from agentloopgate.schemas import EvidenceStatus, RunValidity

runner = CliRunner()
RESET_FIXTURE = Path("tests/fixtures/reset")


def test_repeated_trial_resets_have_the_same_initial_digest(tmp_path: Path) -> None:
    manager = ResetManager(tmp_path / "trials")

    first = manager.reset(RESET_FIXTURE, run_id="R_001", attempt_id="A_001")
    (first.workspace / "state.json").write_text("changed", encoding="utf-8")
    second = manager.reset(RESET_FIXTURE, run_id="R_001", attempt_id="A_002")

    assert first.initial_state_digest == second.initial_state_digest
    assert manager.directory_digest(first.workspace) != first.initial_state_digest
    assert manager.directory_digest(second.workspace) == second.initial_state_digest


def test_infrastructure_failures_are_invalid_and_retry_is_bounded() -> None:
    assessment = assess_infrastructure(
        expected_initial_digest="sha256:" + "a" * 64,
        actual_initial_digest="sha256:" + "b" * 64,
        dependencies_ok=False,
        evaluator_ok=True,
        trace_status=EvidenceStatus.INCOMPLETE,
        shared_resources_ok=True,
        provider_error=False,
        retry_count=0,
    )

    assert assessment.run_validity is RunValidity.INFRA_INVALID
    assert set(assessment.reasons) == {
        InfraInvalidReason.RESET_DIGEST_MISMATCH,
        InfraInvalidReason.DEPENDENCY_UNAVAILABLE,
        InfraInvalidReason.TRACE_MISSING,
    }
    assert assessment.retry_allowed is True

    no_second_retry = assess_infrastructure(
        expected_initial_digest="sha256:" + "a" * 64,
        actual_initial_digest="sha256:" + "b" * 64,
        dependencies_ok=False,
        evaluator_ok=True,
        trace_status=EvidenceStatus.INCOMPLETE,
        shared_resources_ok=True,
        provider_error=False,
        retry_count=1,
    )
    assert no_second_retry.retry_allowed is False


def test_reset_check_cli_is_stable_json() -> None:
    result = runner.invoke(
        app,
        ["eval", "reset-check", "--fixture", str(RESET_FIXTURE), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["consistent"] is True
    assert payload["initial_state_digest"].startswith("sha256:")

