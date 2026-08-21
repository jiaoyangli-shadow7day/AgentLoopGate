"""Strict JSONL protocol models for the DeepSeek Harness bridge."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from agentloopgate.schemas import (
    ArtifactId,
    Digest,
    IngestMode,
    NonEmpty,
    PersistenceKind,
)
from agentloopgate.schemas.models import StrictModel, UtcDateTime


class BridgeActor(StrictModel):
    type: Literal["dsh_plugin"]
    session_id_hash: Digest | None = None


class BridgeRequest(StrictModel):
    protocol_version: Literal["1.0"]
    request_id: ArtifactId
    method: NonEmpty
    payload: dict[str, Any] = Field(default_factory=dict)
    actor: BridgeActor | None = None


class BridgeError(StrictModel):
    code: NonEmpty
    message: NonEmpty
    remediation: NonEmpty


class BridgeResponse(StrictModel):
    protocol_version: Literal["1.0"] = "1.0"
    request_id: ArtifactId
    ok: bool
    result: dict[str, Any] | None = None
    error: BridgeError | None = None

    @model_validator(mode="after")
    def result_and_error_are_exclusive(self) -> BridgeResponse:
        if self.ok and (self.result is None or self.error is not None):
            raise ValueError("successful responses require only result")
        if not self.ok and (self.error is None or self.result is not None):
            raise ValueError("failed responses require only error")
        return self


class EmptyPayload(StrictModel):
    pass


class CandidateCheckPayload(StrictModel):
    candidate_id: ArtifactId


class DecisionExplainPayload(StrictModel):
    decision_id: ArtifactId


class DshEvent(StrictModel):
    seq: int = Field(ge=0)
    timestamp: UtcDateTime
    event_type: NonEmpty
    data: dict[str, Any] = Field(default_factory=dict)


class EventBatchPayload(StrictModel):
    batch_id: ArtifactId
    session_id: NonEmpty
    persistence_kind: PersistenceKind
    ingest_mode: IngestMode = IngestMode.MIRROR
    events: list[DshEvent] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def sequence_numbers_are_unique(self) -> EventBatchPayload:
        sequence = [event.seq for event in self.events]
        if len(sequence) != len(set(sequence)):
            raise ValueError("event sequence numbers must be unique within a batch")
        return self


class TraceSyncPayload(StrictModel):
    session_id: NonEmpty
    source_revision: NonEmpty
    persistence_kind: PersistenceKind
    ingest_mode: IngestMode


class TraceVerifyPayload(StrictModel):
    source_trace_id: ArtifactId


class StoredBridgeRequest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    request_digest: NonEmpty
    response: BridgeResponse


class StoredEventBatch(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    batch_id: ArtifactId
    session_id_hash: NonEmpty
    persistence_kind: PersistenceKind
    ingest_mode: IngestMode
    events: list[DshEvent]


class BridgeContract(StrictModel):
    request: BridgeRequest
    response: BridgeResponse


def utc_timestamp(value: datetime) -> str:
    """Serialize an already validated UTC timestamp for bridge results."""
    return value.isoformat().replace("+00:00", "Z")
