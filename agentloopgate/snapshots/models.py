"""Human authorization and active-snapshot audit records."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from agentloopgate.schemas import ArtifactId, Digest, NonEmpty, UtcDateTime
from agentloopgate.schemas.models import StrictModel


class ApprovalAction(StrEnum):
    PROMOTE = "promote"
    ROLLBACK = "rollback"


class PromotionApproval(StrictModel):
    schema_version: Literal["1.0"]
    approval_id: ArtifactId
    action: ApprovalAction
    target_snapshot_id: ArtifactId
    actor: NonEmpty
    confirmation: Literal["I understand this changes the active harness snapshot."]
    approved_at: UtcDateTime


class ActivationAction(StrEnum):
    BASELINE = "baseline"
    PROMOTE = "promote"
    ROLLBACK = "rollback"


class SnapshotActivation(StrictModel):
    schema_version: Literal["1.0"]
    ordinal: int = Field(ge=1)
    action: ActivationAction
    snapshot_id: ArtifactId
    previous_snapshot_id: ArtifactId | None
    decision_id: ArtifactId | None
    approval_digest: Digest | None
    actor: NonEmpty
    activated_at: UtcDateTime

