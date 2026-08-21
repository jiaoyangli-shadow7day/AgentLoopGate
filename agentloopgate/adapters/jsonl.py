"""Strict import surface for community-owned deterministic evaluators."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from agentloopgate.adapters.base import (
    AdapterHealth,
    BenchmarkIngestResult,
    BenchmarkRunContext,
    BenchmarkRunRequest,
    BenchmarkUnavailableError,
    OutcomeDiagnostics,
    OutcomeImportError,
)
from agentloopgate.adapters.evidence import BenchmarkEvidenceStore
from agentloopgate.contracts import file_digest
from agentloopgate.schemas import (
    ArtifactId,
    Digest,
    EvidenceStatus,
    NonEmpty,
    PersistenceKind,
    Pool,
    RunRecord,
    RunSource,
    RuntimeHost,
    RunValidity,
    SourceTraceRef,
    UtcDateTime,
    ViolationCode,
)
from agentloopgate.schemas.models import StrictModel


class EvaluatorIdentity(StrictModel):
    evaluator_id: NonEmpty
    evaluated_system_id: NonEmpty
    authority: Literal["independent"]
    version: NonEmpty
    config_digest: Digest

    @model_validator(mode="after")
    def evaluator_is_independent(self) -> EvaluatorIdentity:
        if self.evaluator_id == self.evaluated_system_id:
            raise ValueError("self-evaluation is not admissible")
        return self


class EvaluatorEvidence(StrictModel):
    artifact_uri: NonEmpty
    artifact_digest: Digest


class JsonlOutcome(StrictModel):
    schema_version: Literal["1.0"]
    run_id: ArtifactId
    attempt_id: ArtifactId
    task_id: ArtifactId
    pool: Pool
    snapshot_id: ArtifactId
    candidate_id: ArtifactId | None
    trial_index: int = Field(ge=1)
    model_id: NonEmpty
    runtime_version: NonEmpty
    initial_state_digest: Digest
    terminal_state_digest: Digest
    success: bool
    critical_violations: list[ViolationCode]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    cost: Decimal = Field(ge=0)
    evaluator: EvaluatorIdentity
    evidence: EvaluatorEvidence
    created_at: UtcDateTime


class JsonlOutcomeAdapter:
    """Import externally evaluated outcomes without trusting agent self-scores."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.store = BenchmarkEvidenceStore(self.project_root)

    def doctor(self) -> AdapterHealth:
        return AdapterHealth(
            status="ready",
            benchmark="community-jsonl-outcome",
            expected_commit="provided-by-run-context",
            actual_commit=None,
            version="1.0",
            task_count=None,
            remediation="No action required.",
        )

    def build_command(self, request: BenchmarkRunRequest) -> list[str]:
        raise BenchmarkUnavailableError(
            "JSONL Outcome Adapter imports evaluator output and does not execute a benchmark"
        )

    def run(self, request: BenchmarkRunRequest) -> Path:
        raise BenchmarkUnavailableError(
            "Run the community evaluator, then import its JSONL outcome artifact"
        )

    def ingest(
        self,
        result_path: Path,
        context: BenchmarkRunContext,
    ) -> BenchmarkIngestResult:
        outcomes = self._read_outcomes(result_path)
        self._validate_context(outcomes, context)
        ref = self.store.attach(
            result_path,
            runtime_host=RuntimeHost.PYTHON_CLI,
            persistence_kind=PersistenceKind.JSONL,
            event_count=len(outcomes),
            session_identity={
                "source_digest": file_digest(result_path),
                "run_ids": sorted(outcome.run_id for outcome in outcomes),
            },
            created_at=min(outcome.created_at for outcome in outcomes),
        )
        records: list[RunRecord] = []
        receipts = []
        diagnostics: list[OutcomeDiagnostics] = []
        for index, outcome in enumerate(sorted(outcomes, key=lambda item: item.run_id)):
            evidence_path = self.store.resolve_artifact_uri(outcome.evidence.artifact_uri)
            if not evidence_path.is_file():
                raise OutcomeImportError("evaluator evidence artifact is missing")
            if file_digest(evidence_path) != outcome.evidence.artifact_digest:
                raise OutcomeImportError("evaluator evidence digest mismatch")
            record, receipt, diagnostic = self.store.persist_run(
                ref=ref,
                event_index=index,
                record_factory=lambda receipt_id, outcome=outcome: self._record(
                    outcome,
                    ref=ref,
                    receipt_id=receipt_id,
                    context=context,
                ),
                diagnostic_factory=lambda receipt_id, outcome=outcome: OutcomeDiagnostics(
                    schema_version="1.0",
                    run_id=outcome.run_id,
                    evidence_ref=receipt_id,
                    termination_reason="external_evaluator_complete",
                    reward=Decimal(1) if outcome.success else Decimal(0),
                    reward_basis=["EXTERNAL_EVALUATOR"],
                    db_match=None,
                    required_document_count=0,
                    action_checks=[],
                    observed_tool_names=[],
                    evaluator_evidence_digest=outcome.evidence.artifact_digest,
                ),
                collected_at=outcome.created_at,
            )
            records.append(record)
            receipts.append(receipt)
            diagnostics.append(diagnostic)
        return BenchmarkIngestResult(
            schema_version="1.0",
            source_trace_ref=ref,
            receipts=receipts,
            records=records,
            diagnostics=diagnostics,
        )

    def verify(self, ref: SourceTraceRef) -> EvidenceStatus:
        if self.store.verify(ref) is not EvidenceStatus.VERIFIED:
            return EvidenceStatus.UNAVAILABLE
        try:
            source = self.store.resolve_artifact_uri(ref.source_locator)
            for outcome in self._read_outcomes(source):
                evidence = self.store.resolve_artifact_uri(outcome.evidence.artifact_uri)
                if (
                    not evidence.is_file()
                    or file_digest(evidence) != outcome.evidence.artifact_digest
                ):
                    return EvidenceStatus.UNAVAILABLE
        except (OSError, OutcomeImportError):
            return EvidenceStatus.UNAVAILABLE
        return EvidenceStatus.VERIFIED

    @staticmethod
    def _record(
        outcome: JsonlOutcome,
        *,
        ref: SourceTraceRef,
        receipt_id: str,
        context: BenchmarkRunContext,
    ) -> RunRecord:
        return RunRecord(
            schema_version="1.0",
            run_id=outcome.run_id,
            attempt_id=outcome.attempt_id,
            task_id=outcome.task_id,
            pool=outcome.pool,
            snapshot_id=outcome.snapshot_id,
            candidate_id=outcome.candidate_id,
            source=RunSource.JSONL,
            runtime_host=RuntimeHost.PYTHON_CLI,
            runtime_version=outcome.runtime_version,
            model_id=outcome.model_id,
            benchmark_commit=context.benchmark_commit,
            objective_digest=context.objective_digest,
            split_digest=context.split_digest,
            initial_state_digest=outcome.initial_state_digest,
            terminal_state_digest=outcome.terminal_state_digest,
            trial_index=outcome.trial_index,
            run_validity=RunValidity.VALID,
            success=outcome.success,
            critical_violations=outcome.critical_violations,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            latency_ms=outcome.latency_ms,
            cost=outcome.cost,
            source_trace_ref=ref.source_trace_id,
            evidence_receipt_ref=receipt_id,
            created_at=outcome.created_at,
        )

    @staticmethod
    def _read_outcomes(path: Path) -> list[JsonlOutcome]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise OutcomeImportError(f"cannot read community outcome JSONL: {path}") from exc
        outcomes: list[JsonlOutcome] = []
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                outcomes.append(JsonlOutcome.model_validate_json(line))
            except ValidationError as exc:
                raise OutcomeImportError(
                    f"invalid community outcome at line {line_number}: {exc}"
                ) from exc
        if not outcomes:
            raise OutcomeImportError("community outcome JSONL contains no evidence records")
        return outcomes

    @staticmethod
    def _validate_context(
        outcomes: list[JsonlOutcome],
        context: BenchmarkRunContext,
    ) -> None:
        expected = {
            (task_id, trial)
            for task_id in context.expected_task_ids
            for trial in range(1, context.expected_trials + 1)
        }
        actual: set[tuple[str, int]] = set()
        run_ids: set[str] = set()
        for outcome in outcomes:
            if outcome.pool is not context.pool:
                raise OutcomeImportError("community outcome pool does not match the run context")
            if outcome.snapshot_id != context.snapshot_id:
                raise OutcomeImportError(
                    "community outcome snapshot does not match the run context"
                )
            if outcome.candidate_id != context.candidate_id:
                raise OutcomeImportError(
                    "community outcome candidate does not match the run context"
                )
            if outcome.model_id != context.model_id:
                raise OutcomeImportError("community outcome model does not match the run context")
            if outcome.initial_state_digest != context.initial_state_digests.get(outcome.task_id):
                raise OutcomeImportError("community outcome initial-state evidence does not match")
            pair = (outcome.task_id, outcome.trial_index)
            if pair in actual or outcome.run_id in run_ids:
                raise OutcomeImportError("community outcome contains a duplicate run")
            actual.add(pair)
            run_ids.add(outcome.run_id)
        if actual != expected:
            raise OutcomeImportError(
                "community outcome does not exactly cover expected task trials"
            )
