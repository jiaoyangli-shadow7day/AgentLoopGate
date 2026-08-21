"""Frozen split manifests and ACL data contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentloopgate.schemas.models import ArtifactId, Digest, NonEmpty, Pool, UtcDateTime


class StrictSplitModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SplitStatus(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"


class TaskDescriptor(StrictSplitModel):
    task_id: ArtifactId
    workflow_family: ArtifactId
    high_risk: bool
    document_count: int = Field(ge=1)
    tool_complexity: int = Field(ge=1)


class PoolManifest(StrictSplitModel):
    schema_version: Literal["1.0"]
    pool: Pool
    benchmark_commit: NonEmpty
    tasks: list[TaskDescriptor]

    @model_validator(mode="after")
    def task_ids_are_unique(self) -> PoolManifest:
        ids = [task.task_id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("task ids must be unique within a pool")
        return self


class SplitBenchmark(StrictSplitModel):
    name: NonEmpty
    commit: NonEmpty


class PoolSpec(StrictSplitModel):
    manifest: NonEmpty
    expected_count: int = Field(ge=1)
    manifest_digest: Digest | None


class SplitConfig(StrictSplitModel):
    schema_version: Literal["1.0"]
    benchmark: SplitBenchmark
    status: SplitStatus
    frozen_at: UtcDateTime | None
    split_digest: Digest | None
    pools: dict[Pool, PoolSpec]
    replay_task_ids: list[ArtifactId]


class ActorRole(StrEnum):
    OWNER = "owner"
    UPDATER = "updater"
    UPDATE_EVALUATOR = "update_evaluator"
    SELECTOR = "selector"
    RELEASE_EVALUATOR = "release_evaluator"
    REPORTER = "reporter"


class AccessKind(StrEnum):
    TASKS = "tasks"
    TRACE = "trace"
    AGGREGATE = "aggregate"

