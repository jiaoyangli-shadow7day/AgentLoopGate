"""Objective Contract loading, freezing, and drift verification."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from agentloopgate.contracts.hashing import canonical_digest
from agentloopgate.schemas import ObjectiveContract


def load_contract(path: Path) -> ObjectiveContract:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("objective contract must be a YAML object")
    return ObjectiveContract.model_validate(raw)


def contract_digest_payload(contract: ObjectiveContract) -> dict[str, Any]:
    return contract.model_dump(mode="json", exclude={"contract_digest"})


def computed_contract_digest(contract: ObjectiveContract) -> str:
    return canonical_digest(contract_digest_payload(contract))


def freeze_contract(contract: ObjectiveContract, *, frozen_at: datetime) -> ObjectiveContract:
    if contract.frozen_at is not None or contract.contract_digest is not None:
        verify_contract_digest(contract)
        return contract
    pending = contract.model_copy(update={"frozen_at": frozen_at, "contract_digest": None})
    return pending.model_copy(update={"contract_digest": computed_contract_digest(pending)})


def verify_contract_digest(contract: ObjectiveContract) -> None:
    if contract.frozen_at is None or contract.contract_digest is None:
        raise ValueError("objective contract is not frozen")
    computed = computed_contract_digest(contract)
    if computed != contract.contract_digest:
        raise ValueError(
            "objective contract digest mismatch: "
            f"expected {contract.contract_digest}, got {computed}"
        )
