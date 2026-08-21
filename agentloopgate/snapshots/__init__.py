"""Immutable harness snapshots and human-controlled activation."""

from agentloopgate.snapshots.manager import (
    SnapshotAuthorizationError,
    SnapshotIntegrityError,
    SnapshotManager,
)
from agentloopgate.snapshots.models import (
    ActivationAction,
    ApprovalAction,
    PromotionApproval,
    SnapshotActivation,
)

__all__ = [
    "ActivationAction",
    "ApprovalAction",
    "PromotionApproval",
    "SnapshotActivation",
    "SnapshotAuthorizationError",
    "SnapshotIntegrityError",
    "SnapshotManager",
]
