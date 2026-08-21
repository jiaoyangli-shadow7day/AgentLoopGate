"""Deterministic trial reset and infrastructure validity assessment."""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agentloopgate.contracts import canonical_digest, file_digest
from agentloopgate.schemas import EvidenceStatus, RunValidity
from agentloopgate.schemas.models import ArtifactId, Digest, UtcDateTime

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class ResetIntegrityError(ValueError):
    """A reset source or recreated trial state failed integrity checks."""


class StrictResetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ResetReceipt(StrictResetModel):
    schema_version: Literal["1.0"]
    run_id: ArtifactId
    attempt_id: ArtifactId
    initial_state_digest: Digest
    workspace: Path
    created_at: UtcDateTime


class InfraInvalidReason(StrEnum):
    RESET_DIGEST_MISMATCH = "reset_digest_mismatch"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    EVALUATOR_CRASH = "evaluator_crash"
    TRACE_MISSING = "trace_missing"
    SHARED_RESOURCE_FAILURE = "shared_resource_failure"
    PROVIDER_SYSTEM_ERROR = "provider_system_error"


class InfraAssessment(StrictResetModel):
    schema_version: Literal["1.0"]
    run_validity: RunValidity
    reasons: list[InfraInvalidReason]
    retry_allowed: bool


class ResetManager:
    def __init__(self, work_root: Path) -> None:
        self.work_root = work_root.resolve()

    def reset(
        self,
        fixture: Path,
        *,
        run_id: str,
        attempt_id: str,
        expected_digest: str | None = None,
    ) -> ResetReceipt:
        self._safe_id(run_id)
        self._safe_id(attempt_id)
        source = fixture.resolve()
        if not source.is_dir():
            raise ResetIntegrityError(f"reset fixture is not a directory: {fixture}")
        if any(path.is_symlink() for path in source.rglob("*")):
            raise ResetIntegrityError("reset fixture cannot contain symbolic links")
        source_digest = self.directory_digest(source)
        if expected_digest is not None and source_digest != expected_digest:
            raise ResetIntegrityError(
                f"reset source digest mismatch: expected {expected_digest}, got {source_digest}"
            )

        workspace = (self.work_root / run_id / attempt_id).resolve()
        try:
            workspace.relative_to(self.work_root)
        except ValueError as exc:
            raise ResetIntegrityError("trial workspace escapes the reset root") from exc
        if workspace.exists():
            raise ResetIntegrityError("trial workspace already exists; attempts are append-only")
        workspace.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, workspace)
        copied_digest = self.directory_digest(workspace)
        if copied_digest != source_digest:
            raise ResetIntegrityError(
                f"copied reset digest mismatch: expected {source_digest}, got {copied_digest}"
            )
        return ResetReceipt(
            schema_version="1.0",
            run_id=run_id,
            attempt_id=attempt_id,
            initial_state_digest=copied_digest,
            workspace=workspace,
            created_at=datetime.now(UTC),
        )

    @staticmethod
    def directory_digest(directory: Path) -> str:
        root = directory.resolve()
        if not root.is_dir():
            raise ResetIntegrityError(f"state directory does not exist: {directory}")
        files: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ResetIntegrityError("state directory cannot contain symbolic links")
            if path.is_file():
                files[path.relative_to(root).as_posix()] = file_digest(path)
        return canonical_digest({"files": files})

    @staticmethod
    def _safe_id(value: str) -> None:
        if not _SAFE_ID.fullmatch(value):
            raise ResetIntegrityError("run and attempt ids must be path-safe artifact ids")


def assess_infrastructure(
    *,
    expected_initial_digest: str,
    actual_initial_digest: str,
    dependencies_ok: bool,
    evaluator_ok: bool,
    trace_status: EvidenceStatus,
    shared_resources_ok: bool,
    provider_error: bool,
    retry_count: int,
) -> InfraAssessment:
    reasons: list[InfraInvalidReason] = []
    if expected_initial_digest != actual_initial_digest:
        reasons.append(InfraInvalidReason.RESET_DIGEST_MISMATCH)
    if not dependencies_ok:
        reasons.append(InfraInvalidReason.DEPENDENCY_UNAVAILABLE)
    if not evaluator_ok:
        reasons.append(InfraInvalidReason.EVALUATOR_CRASH)
    if trace_status is not EvidenceStatus.VERIFIED:
        reasons.append(InfraInvalidReason.TRACE_MISSING)
    if not shared_resources_ok:
        reasons.append(InfraInvalidReason.SHARED_RESOURCE_FAILURE)
    if provider_error:
        reasons.append(InfraInvalidReason.PROVIDER_SYSTEM_ERROR)
    validity = RunValidity.INFRA_INVALID if reasons else RunValidity.VALID
    return InfraAssessment(
        schema_version="1.0",
        run_validity=validity,
        reasons=reasons,
        retry_allowed=bool(reasons) and retry_count < 1,
    )

