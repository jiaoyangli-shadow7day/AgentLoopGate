"""Secret-free append-only usage events for individual model invocations."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from agentloopgate.contracts import canonical_digest, canonical_json_bytes
from agentloopgate.schemas import ArtifactId, Digest
from agentloopgate.schemas.models import NonEmpty, StrictModel, UtcDateTime


class AttemptState(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class CostStatus(StrEnum):
    PENDING = "pending"
    EXACT = "exact"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class ModelCallUsageEvent(StrictModel):
    """One append-only lifecycle event for one model invocation."""

    schema_version: Literal["1.0", "1.1"] = "1.0"
    event_id: ArtifactId
    call_id: ArtifactId
    state: AttemptState
    recorded_at: UtcDateTime
    session_id_hash: Digest
    model: NonEmpty
    duration_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    cache_read_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    provider_retry_count: int | None = Field(default=None, ge=0)
    cost_usd: Decimal | None = Field(default=None, ge=0)
    cost_status: CostStatus
    exit_code: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    event_digest: Digest

    @model_validator(mode="after")
    def lifecycle_is_consistent(self) -> ModelCallUsageEvent:
        if self.state is AttemptState.STARTED and self.cost_status is not CostStatus.PENDING:
            raise ValueError("started model calls require pending cost status")
        if self.cost_status is CostStatus.EXACT and self.cost_usd is None:
            raise ValueError("exact model-call cost requires a value")
        if self.state is AttemptState.FAILED and not self.error_type:
            raise ValueError("failed model calls require an error type")
        if self.schema_version == "1.1" and self.provider_retry_count is None:
            raise ValueError("model-call usage 1.1 requires provider_retry_count")
        if self.schema_version == "1.0" and self.provider_retry_count is not None:
            raise ValueError("model-call usage 1.0 cannot contain provider_retry_count")
        return self


def append_model_call_event(path: Path, event: ModelCallUsageEvent) -> None:
    """Append one event with one atomic O_APPEND write and durable flush."""

    verify_model_call_event(event)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = event.model_dump(mode="json")
    if event.schema_version == "1.0" and event.provider_retry_count is None:
        payload.pop("provider_retry_count", None)
    encoded = canonical_json_bytes(payload) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)


def make_model_call_event(**payload: Any) -> ModelCallUsageEvent:
    if payload.get("provider_retry_count", 0) is None:
        payload["schema_version"] = "1.0"
        payload.pop("provider_retry_count", None)
    else:
        payload.setdefault("schema_version", "1.1")
        payload.setdefault("provider_retry_count", 0)
    payload["recorded_at"] = datetime.now(UTC)
    draft = ModelCallUsageEvent.model_validate(
        {
            **payload,
            "event_id": "MCE_" + "0" * 24,
            "event_digest": "sha256:" + "0" * 64,
        }
    )
    normalized = draft.model_dump(
        mode="python", exclude={"event_id", "event_digest"}
    )
    if draft.schema_version == "1.0" and "provider_retry_count" not in draft.model_fields_set:
        normalized.pop("provider_retry_count", None)
    digest = canonical_digest(normalized)
    return draft.model_copy(
        update={
            "event_id": f"MCE_{digest.removeprefix('sha256:')[:24].upper()}",
            "event_digest": digest,
        }
    )


def verify_model_call_event(event: ModelCallUsageEvent) -> None:
    payload = event.model_dump(
        mode="python", exclude={"event_id", "event_digest"}
    )
    if event.schema_version == "1.0" and event.provider_retry_count is None:
        payload.pop("provider_retry_count", None)
    if canonical_digest(payload) != event.event_digest:
        raise ValueError("model call event digest mismatch")
