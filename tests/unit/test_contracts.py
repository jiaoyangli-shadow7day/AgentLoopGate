from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agentloopgate.cli import app
from agentloopgate.contracts import (
    canonical_digest,
    freeze_contract,
    load_contract,
    verify_contract_digest,
)
from agentloopgate.schemas import ObjectiveContract

runner = CliRunner()


def test_canonical_digest_is_order_independent_and_detects_drift() -> None:
    left = {"b": [2, 3], "a": {"value": 1}}
    right = {"a": {"value": 1}, "b": [2, 3]}

    assert canonical_digest(left) == canonical_digest(right)
    assert canonical_digest(left) != canonical_digest({**right, "b": [2, 4]})


def test_freeze_and_verify_contract_digest() -> None:
    contract = load_contract(Path("configs/objective_contract.yaml"))
    frozen = freeze_contract(
        contract,
        frozen_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert frozen.frozen_at is not None
    assert frozen.contract_digest is not None
    verify_contract_digest(frozen)

    drifted = ObjectiveContract.model_validate(
        {
            **frozen.model_dump(mode="python"),
            "gates": {
                **frozen.gates.model_dump(mode="python"),
                "mean_cost_ratio_max": 9,
            },
        }
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_contract_digest(drifted)


def test_contract_validate_cli_returns_stable_json() -> None:
    result = runner.invoke(
        app,
        ["contract", "validate", "configs/objective_contract.yaml", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["frozen"] is True
    assert payload["project"] == "AgentLoopGate"
    assert payload["computed_digest"].startswith("sha256:")


def test_contract_freeze_cli_requires_confirmation_and_writes_verified_digest(
    tmp_path: Path,
) -> None:
    contract = tmp_path / "objective.yaml"
    unfrozen = load_contract(Path("configs/objective_contract.yaml")).model_copy(
        update={"frozen_at": None, "contract_digest": None}
    )
    contract.write_text(
        yaml.safe_dump(unfrozen.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )

    refused = runner.invoke(app, ["contract", "freeze", str(contract), "--confirm", "no"])
    assert refused.exit_code == 3
    assert load_contract(contract).frozen_at is None

    result = runner.invoke(
        app,
        [
            "contract",
            "freeze",
            str(contract),
            "--confirm",
            "FREEZE OBJECTIVE",
            "--json",
        ],
    )
    assert result.exit_code == 0
    frozen = load_contract(contract)
    verify_contract_digest(frozen)
    assert json.loads(result.stdout)["contract_digest"] == frozen.contract_digest
