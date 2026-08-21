"""Frozen, content-addressed execution protocol for formal experiments."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator

from agentloopgate.contracts import canonical_digest
from agentloopgate.schemas import ArtifactId, Digest
from agentloopgate.schemas.models import NonEmpty, StrictModel, UtcDateTime


class FormalExecutionProtocol(StrictModel):
    """Every runtime choice that can change formal evidence or its denominator."""

    schema_version: Literal["1.0", "1.1"]
    protocol_id: ArtifactId
    experiment_id: ArtifactId
    objective_digest: Digest
    split_digest: Digest
    benchmark_commit: NonEmpty
    agent_model: NonEmpty
    user_model: NonEmpty
    pricing_digest: Digest
    max_concurrency: Literal[1]
    max_retries: Literal[1]
    retry_delay_seconds: Decimal = Field(ge=0)
    turn_timeout_seconds: int = Field(ge=1)
    benchmark_seed: int | None = None
    max_steps: int | None = Field(default=None, ge=1)
    max_errors: int | None = Field(default=None, ge=1)
    simulation_timeout_seconds: int | None = Field(default=None, ge=1)
    agent_temperature: Decimal | None = Field(default=None, ge=0)
    user_temperature: Decimal | None = Field(default=None, ge=0)
    user_model_max_retries: int | None = Field(default=None, ge=0)
    dsh_provider_max_retries: int | None = Field(default=None, ge=0)
    dsh_provider_retry_delay_ms: int | None = Field(default=None, ge=1)
    agent_max_output_tokens: int | None = Field(default=None, ge=1)
    updater_max_retries: int | None = Field(default=None, ge=0)
    updater_retry_delay_seconds: Decimal | None = Field(default=None, ge=0)
    updater_timeout_seconds: int | None = Field(default=None, ge=1)
    updater_max_iterations: int | None = Field(default=None, ge=1)
    updater_max_output_tokens: int | None = Field(default=None, ge=1)
    updater_temperature: Decimal | None = Field(default=None, ge=0)
    updater_proposal_budget: int | None = Field(default=None, ge=1)
    resume: Literal[True]
    timezone: Literal["UTC"]
    valid_cost_policy: Literal["exact_required"]
    infra_invalid_cost_policy: Literal["null_excluded"]
    latency_policy: Literal["retained_duration_plus_trace_recovery"]
    status: Literal["frozen"]
    frozen_at: UtcDateTime
    protocol_digest: Digest

    @model_validator(mode="after")
    def versioned_runtime_surface_is_complete(self) -> FormalExecutionProtocol:
        version_1_1 = (
            "benchmark_seed",
            "max_steps",
            "max_errors",
            "simulation_timeout_seconds",
            "agent_temperature",
            "user_temperature",
            "user_model_max_retries",
            "dsh_provider_max_retries",
            "dsh_provider_retry_delay_ms",
            "agent_max_output_tokens",
            "updater_max_retries",
            "updater_retry_delay_seconds",
            "updater_timeout_seconds",
            "updater_max_iterations",
            "updater_max_output_tokens",
            "updater_temperature",
            "updater_proposal_budget",
        )
        present = [getattr(self, field) is not None for field in version_1_1]
        if self.schema_version == "1.1" and not all(present):
            raise ValueError("protocol 1.1 requires every benchmark and updater runtime pin")
        if self.schema_version == "1.0" and any(present):
            raise ValueError("protocol 1.0 cannot contain protocol 1.1 runtime pins")
        return self


def protocol_digest_payload(protocol: FormalExecutionProtocol) -> dict[str, Any]:
    payload = protocol.model_dump(mode="json", exclude={"protocol_digest"})
    if protocol.schema_version == "1.0":
        for key in set(payload) - protocol.model_fields_set:
            payload.pop(key, None)
    return payload


def computed_protocol_digest(protocol: FormalExecutionProtocol) -> str:
    return canonical_digest(protocol_digest_payload(protocol))


def verify_execution_protocol(protocol: FormalExecutionProtocol) -> None:
    computed = computed_protocol_digest(protocol)
    if computed != protocol.protocol_digest:
        raise ValueError(
            "execution protocol digest mismatch: "
            f"expected {protocol.protocol_digest}, got {computed}"
        )


def load_execution_protocol(path: Path) -> FormalExecutionProtocol:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read formal execution protocol: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("formal execution protocol must be a YAML object")
    protocol = FormalExecutionProtocol.model_validate(raw)
    verify_execution_protocol(protocol)
    return protocol
