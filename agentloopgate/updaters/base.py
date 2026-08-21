"""External updater contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from agentloopgate.mutation import HarnessAssetManifest, MutationPolicy
from agentloopgate.schemas import CandidateRecord, FailureBundle, NonEmpty, SnapshotManifest
from agentloopgate.schemas.models import StrictModel


class UpdaterHealth(StrictModel):
    status: Literal["ready", "missing_credentials", "unavailable", "version_mismatch"]
    name: NonEmpty
    expected_commit: NonEmpty
    actual_commit: str | None
    version: str | None
    credentials_configured: bool
    sandbox_available: bool
    remediation: NonEmpty

    @property
    def ready(self) -> bool:
        return self.status == "ready"


class UpdaterError(RuntimeError):
    """External updater could not produce an admissible proposal."""


@runtime_checkable
class UpdaterAdapter(Protocol):
    name: str
    version: str

    def doctor(self) -> UpdaterHealth: ...

    def propose(
        self,
        parent_snapshot: SnapshotManifest,
        failure_bundle: FailureBundle,
        asset_manifest: HarnessAssetManifest,
        mutation_policy: MutationPolicy,
        count: int,
        *,
        created_at: datetime | None = None,
    ) -> list[CandidateRecord]: ...

