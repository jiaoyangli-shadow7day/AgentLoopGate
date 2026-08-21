from __future__ import annotations

import json
from pathlib import Path

import pytest

import agentloopgate.experiment.ablations as ablations
from agentloopgate.experiment import run_integrity_gate_ablation
from agentloopgate.schemas import DecisionValue, GateName


def test_integrity_ablation_is_deterministic_and_never_a_formal_decision(
    tmp_path: Path,
) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    for name in ("banking_r2_study.yaml", "objective_contract.yaml"):
        (configs / name).write_text(
            (Path("configs") / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    output = Path("artifacts/integrity.json")

    first = run_integrity_gate_ablation(
        tmp_path,
        study_path=Path("configs/banking_r2_study.yaml"),
        output_path=output,
    )
    second = run_integrity_gate_ablation(
        tmp_path,
        study_path=Path("configs/banking_r2_study.yaml"),
        output_path=output,
    )

    assert first == second
    assert first.synthetic_control is True
    assert first.formal_decision is False
    assert first.production_decision is DecisionValue.HOLD
    assert first.production_failed_gate is GateName.EVALUATION_INTEGRITY
    assert first.counterfactual_decision is DecisionValue.SHIP_RECOMMENDED
    assert first.unsupported_admission_prevented is True
    assert json.loads((tmp_path / output).read_text())["artifact_digest"] == (
        first.artifact_digest
    )


def test_integrity_ablation_records_failed_terminal_after_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    for name in (
        "banking_r2_study_v2.yaml",
        "experiment_protocol_banking_r2_v2.yaml",
    ):
        (configs / name).write_text(
            (Path("configs") / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    monkeypatch.setattr(
        "agentloopgate.experiment.service._code_revision",
        lambda _root: "tree:sha256:" + "a" * 64,
    )

    def fail_after_start(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("synthetic post-start failure")

    monkeypatch.setattr(ablations, "_execute_integrity_gate_ablation", fail_after_start)

    with pytest.raises(RuntimeError, match="synthetic post-start failure"):
        run_integrity_gate_ablation(
            tmp_path,
            study_path=Path("configs/banking_r2_study_v2.yaml"),
            protocol_path=Path("configs/experiment_protocol_banking_r2_v2.yaml"),
            output_path=Path("artifacts/integrity.json"),
        )

    events = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(
            (
                tmp_path
                / "runs/experiments/EXP_BANKING_R2/attempt_ledger"
            ).glob("ATT_*/*.json")
        )
    ]
    assert {event["state"] for event in events} == {"started", "failed"}
    failed = next(event for event in events if event["state"] == "failed")
    assert failed["cost_status"] == "not_applicable"
    assert failed["error_type"] == "RuntimeError"
    assert failed["duration_ms"] is not None
