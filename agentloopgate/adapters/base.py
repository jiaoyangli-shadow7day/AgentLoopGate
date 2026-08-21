"""Host-independent benchmark adapter contracts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import Field, model_validator

from agentloopgate.schemas import (
    ArtifactId,
    Digest,
    EvidenceReceipt,
    EvidenceStatus,
    NonEmpty,
    Pool,
    RunRecord,
    SourceTraceRef,
)
from agentloopgate.schemas.models import StrictModel


class OutcomeImportError(ValueError):
    """A benchmark result cannot be admitted as governance evidence."""


class BenchmarkUnavailableError(RuntimeError):
    """The pinned benchmark runtime is not healthy enough to execute."""


class BenchmarkRunRequest(StrictModel):
    task_ids: list[ArtifactId] = Field(min_length=1)
    trials: int = Field(ge=1)
    agent_model: NonEmpty
    user_model: NonEmpty
    run_name: ArtifactId
    retrieval_config: Literal["bm25"] = "bm25"
    max_concurrency: int = Field(default=1, ge=1)
    max_retries: int = Field(default=1, ge=0)
    retry_delay_seconds: Decimal = Field(default=Decimal("1"), ge=0)
    seed: int = 300
    max_steps: int = Field(default=200, ge=1)
    max_errors: int = Field(default=10, ge=1)
    simulation_timeout_seconds: int = Field(default=1800, ge=1)
    agent_temperature: Decimal = Field(default=Decimal(0), ge=0)
    user_temperature: Decimal = Field(default=Decimal(0), ge=0)
    user_model_max_retries: int = Field(default=1, ge=0)
    resume: bool = False
    model_usage_ledger: Path | None = None

    @model_validator(mode="after")
    def tasks_are_unique(self) -> BenchmarkRunRequest:
        if len(self.task_ids) != len(set(self.task_ids)):
            raise ValueError("task_ids must be unique")
        return self


class BenchmarkRunContext(StrictModel):
    pool: Pool
    snapshot_id: ArtifactId
    candidate_id: ArtifactId | None
    objective_digest: Digest
    split_digest: Digest
    benchmark_commit: NonEmpty
    model_id: NonEmpty
    expected_task_ids: list[ArtifactId] = Field(min_length=1)
    initial_state_digests: dict[ArtifactId, Digest]
    expected_trials: int = Field(ge=1)

    @model_validator(mode="after")
    def task_context_is_complete(self) -> BenchmarkRunContext:
        if len(self.expected_task_ids) != len(set(self.expected_task_ids)):
            raise ValueError("expected_task_ids must be unique")
        if set(self.initial_state_digests) != set(self.expected_task_ids):
            raise ValueError("initial_state_digests must exactly cover expected_task_ids")
        return self


class AdapterHealth(StrictModel):
    status: Literal["ready", "unavailable", "version_mismatch", "data_mismatch"]
    benchmark: NonEmpty
    expected_commit: NonEmpty
    actual_commit: str | None
    version: str | None
    task_count: int | None
    remediation: NonEmpty

    @property
    def ready(self) -> bool:
        return self.status == "ready"


class ActionDiagnostic(StrictModel):
    name: NonEmpty
    matched: bool
    tool_type: str | None = None


class OutcomeDiagnostics(StrictModel):
    schema_version: Literal["1.0"]
    run_id: ArtifactId
    evidence_ref: NonEmpty
    termination_reason: NonEmpty
    reward: Decimal | None
    reward_basis: list[NonEmpty]
    db_match: bool | None
    required_document_count: int = Field(ge=0)
    action_checks: list[ActionDiagnostic]
    observed_tool_names: list[NonEmpty]
    evaluator_evidence_digest: Digest | None = None


class BenchmarkIngestResult(StrictModel):
    schema_version: Literal["1.0"]
    source_trace_ref: SourceTraceRef
    receipts: list[EvidenceReceipt]
    records: list[RunRecord]
    diagnostics: list[OutcomeDiagnostics]

    @model_validator(mode="after")
    def artifacts_align(self) -> BenchmarkIngestResult:
        run_ids = [record.run_id for record in self.records]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("ingested run ids must be unique")
        if {item.run_id for item in self.receipts} != set(run_ids):
            raise ValueError("every run must have exactly one evidence receipt")
        if {item.run_id for item in self.diagnostics} != set(run_ids):
            raise ValueError("every run must have diagnostics")
        return self

    @property
    def valid_denominator(self) -> int:
        return sum(record.run_validity.value == "valid" for record in self.records)


@runtime_checkable
class BenchmarkAdapter(Protocol):
    def doctor(self) -> AdapterHealth: ...

    def build_command(self, request: BenchmarkRunRequest) -> list[str]: ...

    def run(self, request: BenchmarkRunRequest) -> Path: ...

    def ingest(
        self,
        result_path: Path,
        context: BenchmarkRunContext,
    ) -> BenchmarkIngestResult: ...

    def verify(self, ref: SourceTraceRef) -> EvidenceStatus: ...
