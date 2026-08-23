from __future__ import annotations

import json
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from agentloopgate import cli as cli_module
from agentloopgate.cli import app
from agentloopgate.experiment import (
    FormalSelectionHoldOutcome,
    FormalWorkflowBlocked,
    PaidExecutionAuthorizationError,
)

runner = CliRunner()


def test_version_is_an_eager_top_level_option() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_doctor_is_no_key_and_does_not_expose_secret(monkeypatch) -> None:
    secret = "do-not-print-this-value"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)

    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == 0
    assert secret not in result.stdout
    assert json.loads(result.stdout) == {
        "no_key_mode": True,
        "project": "AgentLoopGate",
        "python_supported": True,
        "schema_version": "1.0",
        "status": "ready",
        "version": "0.1.0",
    }


def test_demo_loads_public_fixture_without_model_access() -> None:
    fixture = Path("tests/fixtures/public_demo")

    result = runner.invoke(app, ["demo", "--fixture", str(fixture), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "fixture_ready"
    assert payload["fixture_id"] == "public_demo"
    assert payload["real_experiment"] is False
    assert payload["run_count"] == 1
    assert payload["candidate_count"] == 2


def test_demo_rejects_an_empty_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "demo.json"
    fixture.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "fixture_id": "empty",
                "real_experiment": False,
                "runs": [],
                "candidates": [],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["demo", "--fixture", str(fixture), "--json"])

    assert result.exit_code == 5
    assert json.loads(result.stdout)["code"] == "fixture_incomplete"


def test_demo_builds_full_no_key_evidence_and_gate_package(tmp_path: Path) -> None:
    output = tmp_path / "public-demo"

    result = runner.invoke(
        app,
        [
            "demo",
            "--fixture",
            "tests/fixtures/public_demo",
            "--build-output",
            str(output),
            "--project",
            ".",
            "--json",
        ],
    )
    repeated = runner.invoke(
        app,
        [
            "demo",
            "--fixture",
            "tests/fixtures/public_demo",
            "--build-output",
            str(output),
            "--project",
            ".",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert repeated.exit_code == 0, repeated.stdout
    payload = json.loads(result.stdout)
    assert payload["run_count"] == 1
    assert payload["candidate_count"] == 2
    manifest = json.loads((output / "demo.json").read_text(encoding="utf-8"))
    assert manifest["real_experiment"] is False
    assert {item["failed_gate"] for item in manifest["candidates"]} == {
        "cost",
        "ood_noninferiority",
    }
    assert len(list((output / "reports").glob("*/*.svg"))) == 8


def test_demo_rejects_missing_fixture_with_stable_error() -> None:
    result = runner.invoke(
        app,
        ["demo", "--fixture", "tests/fixtures/does-not-exist", "--json"],
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout) == {
        "code": "fixture_not_found",
        "message": "Fixture file does not exist: tests/fixtures/does-not-exist/demo.json",
        "remediation": "Pass a directory containing demo.json.",
    }


def test_banking_pilot_requires_three_to_seven_frozen_tasks() -> None:
    result = runner.invoke(
        app,
        [
            "pilot",
            "run",
            "--task-id",
            "task_077",
            "--task-id",
            "task_024",
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout)["code"] == "pilot_tasks_invalid"


def test_installed_console_script_runs_outside_source_tree(tmp_path: Path) -> None:
    executable = shutil.which("agentloopgate")
    assert executable is not None

    result = subprocess.run(
        [executable, "doctor", "--json"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "ready"


def test_formal_selection_hold_is_a_successful_cli_outcome(
    tmp_path: Path,
    monkeypatch,
) -> None:
    digest = "sha256:" + "a" * 64
    payload = {
        "schema_version": "1.0",
        "outcome_kind": "selection_hold",
        "experiment_id": "EXP_HOLD",
        "protocol_digest": digest,
        "study_digest": digest,
        "source_revision": "tree:fixture",
        "baseline_snapshot_id": "A0",
        "candidate_ids": ["C_1", "C_2", "C_3"],
        "candidate_snapshot_ids": ["S_1", "S_2", "S_3"],
        "native_candidate_id": "C_1",
        "agentloopgate_candidate_id": None,
        "final_decision": "HOLD",
        "decision_reason": "no_candidate_passed_baseline_bound_selection_policy",
        "selection_digest": digest,
        "lineage_digest": digest,
        "batch_ids": ["B_1"],
        "candidate_statuses": {"C_1": "held", "C_2": "held", "C_3": "held"},
        "batch_model_cost_usd": Decimal("1.25"),
        "updater_model_cost_usd": Decimal("0.125"),
        "total_known_model_cost_usd": Decimal("1.375"),
        "cost_status": "exact",
        "unresolved_updater_model_call_count": 0,
        "unknown_cost_scope": [],
        "cost_artifact_refs": ["runs/experiments/EXP_HOLD/costs/B_1.json"],
        "release_batch_count": 0,
        "model_calls_after_selection": 0,
        "report_digest": digest,
        "report_file_digests": {"report.json": digest, "report.md": digest},
        "outcome_digest": digest,
    }
    outcome = FormalSelectionHoldOutcome.model_validate(payload)

    class _Orchestrator:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        @staticmethod
        def run() -> FormalSelectionHoldOutcome:
            return outcome

    monkeypatch.setattr(
        cli_module,
        "inspect_formal_preflight",
        lambda *_args, **_kwargs: SimpleNamespace(ready=True, missing=[]),
    )
    monkeypatch.setattr(cli_module, "FormalExperimentOrchestrator", _Orchestrator)

    result = runner.invoke(
        app,
        [
            "experiment",
            "run",
            "--project",
            str(tmp_path),
            "--config",
            "unused.yaml",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    emitted = json.loads(result.stdout)
    assert emitted["outcome_kind"] == "selection_hold"
    assert emitted["final_decision"] == "HOLD"
    assert emitted["release_batch_count"] == 0


def test_formal_run_reports_missing_paid_scope_as_policy_denial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class _Orchestrator:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        @staticmethod
        def run():
            raise PaidExecutionAuthorizationError("release_tail authorization absent")

    monkeypatch.setattr(
        cli_module,
        "inspect_formal_preflight",
        lambda *_args, **_kwargs: SimpleNamespace(ready=True, missing=[]),
    )
    monkeypatch.setattr(cli_module, "FormalExperimentOrchestrator", _Orchestrator)

    result = runner.invoke(
        app,
        [
            "experiment",
            "run",
            "--project",
            str(tmp_path),
            "--config",
            "unused.yaml",
            "--json",
        ],
    )

    assert result.exit_code == 3
    assert json.loads(result.stdout)["code"] == "paid_authorization_required"


def test_formal_hold_forbids_rerunning_the_same_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class _Orchestrator:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        @staticmethod
        def run():
            raise FormalWorkflowBlocked("formal batch sealed HOLD")

    monkeypatch.setattr(
        cli_module,
        "inspect_formal_preflight",
        lambda *_args, **_kwargs: SimpleNamespace(ready=True, missing=[]),
    )
    monkeypatch.setattr(cli_module, "FormalExperimentOrchestrator", _Orchestrator)

    result = runner.invoke(
        app,
        [
            "experiment",
            "run",
            "--project",
            str(tmp_path),
            "--config",
            "unused.yaml",
            "--json",
        ],
    )

    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["code"] == "formal_workflow_blocked"
    assert "Do not rerun or extend the same formal experiment identity" in payload[
        "remediation"
    ]
    assert "freeze a new successor identity" in payload["remediation"]


def test_deepseek_init_is_idempotent_and_does_not_touch_governance_files(
    tmp_path: Path,
) -> None:
    objective = tmp_path / "configs/objective_contract.yaml"
    objective.parent.mkdir(parents=True)
    objective.write_text("frozen-user-content\n", encoding="utf-8")

    first = runner.invoke(
        app,
        [
            "init",
            "--runtime",
            "deepseek-harness",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )
    second = runner.invoke(
        app,
        [
            "init",
            "--runtime",
            "deepseek-harness",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    assert first.exit_code == 0
    assert json.loads(first.stdout)["created"] == [
        "configs/runtime_dsh.yaml",
        "configs/trace_redaction.yaml",
    ]
    assert json.loads(second.stdout)["created"] == []
    assert objective.read_text(encoding="utf-8") == "frozen-user-content\n"


def test_deepseek_doctor_reports_independent_observe_check_and_govern_gaps(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner.invoke(
        app,
        [
            "init",
            "--runtime",
            "deepseek-harness",
            "--project",
            str(tmp_path),
        ],
    )
    (tmp_path / "configs/objective_contract.yaml").write_text(
        Path("configs/objective_contract.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "configs/harness_assets.yaml").write_text(
        Path("configs/harness_assets.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "configs/mutation_policy.yaml").write_text(
        Path("configs/mutation_policy.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "configs/splits.yaml").write_text(
        Path("configs/splits.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "dsh-home"))

    result = runner.invoke(
        app,
        [
            "doctor",
            "--runtime",
            "deepseek-harness",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    assert payload["observe_ready"]["ready"] is False
    assert payload["check_ready"]["ready"] is True
    assert payload["govern_ready"]["ready"] is False
    assert payload["status"] == "check_ready"
    assert "dsh_executable" in payload["observe_ready"]["missing"]
    assert "profile_bundle" in payload["observe_ready"]["missing"]
