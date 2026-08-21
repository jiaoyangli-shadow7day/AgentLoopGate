"""Immutable, resumable formal evaluation batches over DSH-backed τ³ runs."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, model_validator

from agentloopgate.adapters import (
    BenchmarkRunContext,
    BenchmarkRunRequest,
    BenchmarkUnavailableError,
    DshTau3Adapter,
    DshTau3PilotResult,
)
from agentloopgate.adapters.evidence import BenchmarkEvidenceStore
from agentloopgate.bridge import BridgeService
from agentloopgate.contracts import canonical_digest, canonical_json_bytes
from agentloopgate.evaluation import EvaluationAuditor, EvaluationContext, EvaluationSummary
from agentloopgate.schemas import (
    ArtifactId,
    Digest,
    EvidenceReceipt,
    EvidenceStatus,
    PilotEvidenceJoin,
    Pool,
    RunRecord,
    SourceTraceRef,
)
from agentloopgate.schemas.models import NonEmpty, StrictModel

from .ledger import (
    CostStatus,
    ExperimentAttemptLedger,
    artifact_hashes,
    observed_usage_cost,
    reconcile_formal_costs,
    write_cost_accounting_once,
)


class FormalBatchError(ValueError):
    """A formal batch conflicts with its immutable execution evidence."""


class FormalStage(StrEnum):
    UPDATE_SOURCE = "update_source"
    UPDATE_CHECK = "update_check"
    SELECTION = "selection"
    RELEASE_ID = "release_id"
    RELEASE_OOD = "release_ood"
    REPLAY = "replay"


class FormalBatchSpec(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    experiment_id: ArtifactId
    stage: FormalStage
    pool: Pool
    snapshot_id: ArtifactId
    candidate_id: ArtifactId | None
    task_ids: list[ArtifactId] = Field(min_length=1)
    trials: int = Field(ge=1)
    agent_model: NonEmpty
    user_model: NonEmpty
    objective_digest: Digest
    split_digest: Digest
    benchmark_commit: NonEmpty
    initial_state_digests: dict[ArtifactId, Digest]
    protocol_digest: Digest | None = None

    @model_validator(mode="after")
    def execution_population_is_coherent(self) -> FormalBatchSpec:
        if len(self.task_ids) != len(set(self.task_ids)):
            raise ValueError("formal batch task ids must be unique")
        if set(self.initial_state_digests) != set(self.task_ids):
            raise ValueError("initial state digests must exactly cover formal batch tasks")
        expected_pool = {
            FormalStage.UPDATE_SOURCE: Pool.UPDATE_SOURCE,
            FormalStage.UPDATE_CHECK: Pool.UPDATE_CHECK,
            FormalStage.SELECTION: Pool.SELECTION,
            FormalStage.RELEASE_ID: Pool.RELEASE_ID,
            FormalStage.RELEASE_OOD: Pool.RELEASE_OOD,
            FormalStage.REPLAY: Pool.UPDATE_SOURCE,
        }[self.stage]
        if self.pool is not expected_pool:
            raise ValueError("formal stage does not match its frozen evidence pool")
        return self

    @property
    def spec_digest(self) -> str:
        return canonical_digest(self.digest_payload())

    def digest_payload(self) -> dict:
        payload = self.model_dump(mode="python")
        if "protocol_digest" not in self.model_fields_set:
            payload.pop("protocol_digest", None)
        return payload

    @property
    def batch_id(self) -> str:
        suffix = self.spec_digest.removeprefix("sha256:")[:20].upper()
        return f"B_{suffix}"

    @property
    def run_name(self) -> str:
        return f"ALG_{self.batch_id}"


class FormalBatchArtifact(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    batch_id: ArtifactId
    experiment_id: ArtifactId
    stage: FormalStage
    spec: FormalBatchSpec
    spec_digest: Digest
    result_artifact: NonEmpty
    tau_source_trace_id: ArtifactId
    tau_run_ids: list[ArtifactId] = Field(min_length=1)
    dsh_run_ids: list[ArtifactId] = Field(min_length=1)
    evidence_join_ids: list[ArtifactId] = Field(min_length=1)
    summary: EvaluationSummary
    disposition: Literal["complete", "hold"] = "complete"
    hold_reasons: list[NonEmpty] = Field(default_factory=list)
    batch_digest: Digest

    @model_validator(mode="after")
    def disposition_matches_summary(self) -> FormalBatchArtifact:
        must_hold = self.summary.infra_invalid_count > 0 or not self.summary.integrity_complete
        if must_hold and self.disposition != "hold":
            raise ValueError("incomplete or infra-invalid formal evidence must be HOLD")
        if self.disposition == "hold" and not self.hold_reasons:
            raise ValueError("held formal batches require explicit reasons")
        if self.disposition == "complete" and self.hold_reasons:
            raise ValueError("complete formal batches cannot carry HOLD reasons")
        return self


@dataclass(frozen=True)
class FormalBatchExecution:
    result_path: Path
    result: DshTau3PilotResult


@dataclass(frozen=True)
class FormalBatchRunResult:
    artifact: FormalBatchArtifact
    resumed: bool


class FormalBatchExecutor(Protocol):
    def execute(self, spec: FormalBatchSpec) -> FormalBatchExecution: ...


class DshFormalBatchExecutor:
    """Execute one batch and copy raw τ³ evidence into the formal artifact tree."""

    def __init__(
        self,
        project_root: Path,
        adapter: DshTau3Adapter,
        *,
        existing_only: bool = False,
        max_concurrency: int = 1,
        max_retries: int = 1,
        retry_delay_seconds: str = "1",
        seed: int = 300,
        max_steps: int = 200,
        max_errors: int = 10,
        simulation_timeout_seconds: int = 1800,
        agent_temperature: str = "0",
        user_temperature: str = "0",
        user_model_max_retries: int = 1,
    ) -> None:
        self.project_root = project_root.resolve()
        self.adapter = adapter
        self.existing_only = existing_only
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.seed = seed
        self.max_steps = max_steps
        self.max_errors = max_errors
        self.simulation_timeout_seconds = simulation_timeout_seconds
        self.agent_temperature = agent_temperature
        self.user_temperature = user_temperature
        self.user_model_max_retries = user_model_max_retries

    def execute(self, spec: FormalBatchSpec) -> FormalBatchExecution:
        retained = (
            self.project_root
            / "runs/experiments"
            / spec.experiment_id
            / "raw"
            / f"{spec.batch_id}.json"
        )
        if retained.is_file():
            context = self._context(spec)
            return FormalBatchExecution(
                result_path=retained,
                result=self.adapter.ingest_and_link(retained, context),
            )
        if self.existing_only:
            raise FormalBatchError(
                f"retained raw result is unavailable for existing-only seal: {retained}"
            )
        health = self.adapter.doctor()
        if not health.ready:
            raise BenchmarkUnavailableError(health.remediation)
        request = self._request(spec)
        context = self._context(spec)
        upstream = self.adapter.run(request)
        self._copy_once(upstream, retained)
        return FormalBatchExecution(
            result_path=retained,
            result=self.adapter.ingest_and_link(retained, context),
        )

    def execution_command(self, spec: FormalBatchSpec) -> list[str]:
        """Return the exact secret-free command before any paid execution."""

        return self.adapter.build_command(self._request(spec))

    def model_usage_path(self, spec: FormalBatchSpec) -> Path:
        return (
            self.project_root
            / "runs/experiments"
            / spec.experiment_id
            / "model_usage"
            / f"{spec.batch_id}.jsonl"
        )

    def _request(self, spec: FormalBatchSpec) -> BenchmarkRunRequest:
        return BenchmarkRunRequest(
            task_ids=spec.task_ids,
            trials=spec.trials,
            agent_model=spec.agent_model,
            user_model=spec.user_model,
            run_name=spec.run_name,
            max_concurrency=self.max_concurrency,
            max_retries=self.max_retries,
            retry_delay_seconds=self.retry_delay_seconds,
            seed=self.seed,
            max_steps=self.max_steps,
            max_errors=self.max_errors,
            simulation_timeout_seconds=self.simulation_timeout_seconds,
            agent_temperature=self.agent_temperature,
            user_temperature=self.user_temperature,
            user_model_max_retries=self.user_model_max_retries,
            resume=True,
            model_usage_ledger=self.model_usage_path(spec),
        )

    @staticmethod
    def _context(spec: FormalBatchSpec) -> BenchmarkRunContext:
        return BenchmarkRunContext(
            pool=spec.pool,
            snapshot_id=spec.snapshot_id,
            candidate_id=spec.candidate_id,
            objective_digest=spec.objective_digest,
            split_digest=spec.split_digest,
            benchmark_commit=spec.benchmark_commit,
            model_id=spec.agent_model,
            expected_task_ids=spec.task_ids,
            initial_state_digests=spec.initial_state_digests,
            expected_trials=spec.trials,
        )

    @staticmethod
    def _copy_once(source: Path, destination: Path) -> None:
        payload = source.read_bytes()
        if destination.exists():
            if destination.read_bytes() != payload:
                raise FormalBatchError("retained raw result conflicts with an existing batch")
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


class FormalBatchRunner:
    """Run once or verify-and-resume; never silently repeat a paid model batch."""

    def __init__(self, project_root: Path, executor: FormalBatchExecutor) -> None:
        self.project_root = project_root.resolve()
        self.executor = executor
        self.store = BenchmarkEvidenceStore(self.project_root)

    def run(self, spec: FormalBatchSpec) -> FormalBatchRunResult:
        path = self._artifact_path(spec)
        ledger = (
            ExperimentAttemptLedger(self.project_root, spec.experiment_id)
            if spec.protocol_digest is not None
            else None
        )
        usage_path = self._model_usage_path(spec)
        handle = None
        if ledger is not None:
            handle = ledger.begin(
                operation="formal_batch",
                protocol_digest=spec.protocol_digest,
                study_digest=self._study_digest(spec),
                source_revision=self._source_revision(spec),
                stage=spec.stage.value,
                batch_id=spec.batch_id,
                snapshot_id=spec.snapshot_id,
                candidate_id=spec.candidate_id,
                spec_digest=spec.spec_digest,
                command=self._execution_command(spec),
                recovery_action=(
                    "verify immutable batch and cost evidence; do not rerun paid calls blindly"
                ),
            )
        try:
            if path.exists():
                artifact = self._load(path)
                self._verify(artifact, spec)
                if ledger is None:
                    return FormalBatchRunResult(artifact=artifact, resumed=True)
                raw_path = self.store.resolve_artifact_uri(
                    f"artifact:{artifact.result_artifact}"
                )
                cost, cost_path = self._seal_costs(
                    spec,
                    raw_path=raw_path,
                    records=[self._run_record(run_id) for run_id in artifact.tau_run_ids],
                    usage_path=usage_path,
                )
                if ledger is not None and handle is not None:
                    ledger.complete(
                        handle,
                        exit_code=0,
                        resumed=True,
                        cost=cost,
                        cost_artifact=cost_path,
                        result_artifacts=artifact_hashes(
                            {"raw": raw_path, "batch": path, "cost": cost_path}
                        ),
                        counters=self._cost_counters(cost),
                        attempt_cost_status=CostStatus.NOT_APPLICABLE,
                        attempt_known_cost_usd=Decimal(0),
                    )
                return FormalBatchRunResult(artifact=artifact, resumed=True)
            execution = self.executor.execute(spec)
            result_artifact = self.store.relative_path(execution.result_path)
            summary = self._summarize_and_verify(execution.result, spec)
            hold_reasons = list(summary.integrity_issues)
            if summary.infra_invalid_count:
                hold_reasons.append(f"infra_invalid:{summary.infra_invalid_count}")
            cost = cost_path = None
            if ledger is not None:
                cost, cost_path = self._seal_costs(
                    spec,
                    raw_path=execution.result_path,
                    records=execution.result.records,
                    usage_path=usage_path,
                )
                if cost.accounting_status is not CostStatus.EXACT:
                    hold_reasons.append(
                        f"cost_accounting:{cost.accounting_status.value}"
                    )
            hold_reasons = sorted(set(hold_reasons))
            payload = {
                "schema_version": "1.0",
                "batch_id": spec.batch_id,
                "experiment_id": spec.experiment_id,
                "stage": spec.stage,
                "spec": spec.digest_payload(),
                "spec_digest": spec.spec_digest,
                "result_artifact": result_artifact,
                "tau_source_trace_id": execution.result.source_trace_ref.source_trace_id,
                "tau_run_ids": sorted(record.run_id for record in execution.result.records),
                "dsh_run_ids": sorted(
                    record.run_id for record in execution.result.dsh_records
                ),
                "evidence_join_ids": sorted(
                    join.join_id for join in execution.result.evidence_joins
                ),
                "summary": summary,
                "disposition": "hold" if hold_reasons else "complete",
                "hold_reasons": hold_reasons,
            }
            artifact = FormalBatchArtifact.model_validate(
                {**payload, "batch_digest": canonical_digest(payload)}
            )
            serialized = artifact.model_dump(mode="json")
            if "protocol_digest" not in artifact.spec.model_fields_set:
                serialized["spec"].pop("protocol_digest", None)
            self._write_once(path, serialized)
            self._verify(artifact, spec)
            if ledger is None:
                return FormalBatchRunResult(artifact=artifact, resumed=False)
            if (
                ledger is not None
                and handle is not None
                and cost is not None
                and cost_path is not None
            ):
                ledger.complete(
                    handle,
                    exit_code=0,
                    resumed=False,
                    cost=cost,
                    cost_artifact=cost_path,
                    result_artifacts=artifact_hashes(
                        {
                            "raw": execution.result_path,
                            "batch": path,
                            "cost": cost_path,
                            "model_usage": usage_path,
                        }
                    ),
                    counters=self._cost_counters(cost),
                )
            return FormalBatchRunResult(artifact=artifact, resumed=False)
        except BaseException as exc:
            if ledger is not None and handle is not None:
                cost_status, known_cost = observed_usage_cost(usage_path)
                ledger.fail(
                    handle,
                    exc,
                    cost_status=cost_status,
                    known_cost_usd=known_cost,
                    result_artifacts=artifact_hashes(
                        {"batch": path, "model_usage": usage_path}
                    ),
                    recovery_action=(
                        "inspect the immutable attempt and usage ledgers, reconcile billing, "
                        "then resume by batch id; never discard or overwrite this attempt"
                    ),
                )
            raise

    def _seal_costs(
        self,
        spec: FormalBatchSpec,
        *,
        raw_path: Path,
        records: list[RunRecord],
        usage_path: Path,
    ):
        cost = reconcile_formal_costs(
            batch_id=spec.batch_id,
            raw_result_path=raw_path,
            records=records,
            model_usage_path=usage_path,
        )
        path = (
            self.project_root
            / "runs/experiments"
            / spec.experiment_id
            / "costs"
            / f"{spec.batch_id}.json"
        )
        write_cost_accounting_once(path, cost)
        return cost, path

    def _model_usage_path(self, spec: FormalBatchSpec) -> Path:
        method = getattr(self.executor, "model_usage_path", None)
        if callable(method):
            return method(spec)
        return (
            self.project_root
            / "runs/experiments"
            / spec.experiment_id
            / "model_usage"
            / f"{spec.batch_id}.jsonl"
        )

    def _execution_command(self, spec: FormalBatchSpec) -> list[str]:
        method = getattr(self.executor, "execution_command", None)
        return list(method(spec)) if callable(method) else []

    def _source_revision(self, spec: FormalBatchSpec) -> str:
        manifest = self.project_root / "snapshots" / spec.snapshot_id / "manifest.json"
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            revision = payload["code_revision"]
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise FormalBatchError(
                "protocol-bound attempt requires a readable snapshot code revision"
            ) from exc
        if not isinstance(revision, str) or not revision:
            raise FormalBatchError("snapshot code revision must be non-empty")
        return revision

    def _study_digest(self, spec: FormalBatchSpec) -> str | None:
        for path in sorted((self.project_root / "configs").glob("*study*.yaml")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            experiment = next(
                (
                    line.split(":", 1)[1].strip()
                    for line in text.splitlines()
                    if line.startswith("experiment_id:")
                ),
                None,
            )
            protocol = next(
                (
                    line.split(":", 1)[1].strip()
                    for line in text.splitlines()
                    if line.startswith("protocol_digest:")
                ),
                None,
            )
            study = next(
                (
                    line.split(":", 1)[1].strip()
                    for line in text.splitlines()
                    if line.startswith("study_digest:")
                ),
                None,
            )
            if experiment == spec.experiment_id and protocol == spec.protocol_digest:
                return study
        return None

    @staticmethod
    def _cost_counters(cost) -> dict[str, int]:
        return {
            "valid_runs": cost.valid_run_count,
            "infra_invalid_runs": cost.infra_invalid_count,
            "agent_model_calls": cost.agent_model_call_count,
            "unresolved_agent_calls": cost.unresolved_agent_call_count,
            "unretained_agent_calls": cost.unretained_agent_call_count,
            "agent_provider_retries": cost.agent_provider_retry_count,
            "agent_input_tokens": cost.agent_input_tokens,
            "agent_cache_read_tokens": cost.agent_cache_read_tokens,
            "agent_output_tokens": cost.agent_output_tokens,
            "user_model_calls_retained": cost.user_model_call_count_retained,
            "user_input_tokens_retained": cost.user_input_tokens_retained,
            "user_cache_read_tokens_retained": cost.user_cache_read_tokens_retained,
            "user_output_tokens_retained": cost.user_output_tokens_retained,
        }

    def _verify(self, artifact: FormalBatchArtifact, spec: FormalBatchSpec) -> None:
        if (
            artifact.batch_id != spec.batch_id
            or artifact.spec_digest != spec.spec_digest
            or artifact.spec != spec
        ):
            raise FormalBatchError("formal batch artifact does not match the requested spec")
        payload = artifact.model_dump(mode="python", exclude={"batch_digest"})
        if canonical_digest(payload) != artifact.batch_digest:
            legacy_payload = artifact.model_dump(mode="python", exclude={"batch_digest"})
            if "protocol_digest" not in artifact.spec.model_fields_set:
                legacy_payload["spec"].pop("protocol_digest", None)
            if "disposition" not in artifact.model_fields_set:
                legacy_payload.pop("disposition", None)
            if "hold_reasons" not in artifact.model_fields_set:
                legacy_payload.pop("hold_reasons", None)
            legacy_valid = canonical_digest(legacy_payload) == artifact.batch_digest
            if not legacy_valid:
                raise FormalBatchError("formal batch digest mismatch")
        tau_records = [self._run_record(run_id) for run_id in artifact.tau_run_ids]
        dsh_records = [self._run_record(run_id) for run_id in artifact.dsh_run_ids]
        joins = [self._join(join_id) for join_id in artifact.evidence_join_ids]
        tau_ref = self._trace_ref(artifact.tau_source_trace_id)
        result = DshTau3PilotResult(
            schema_version="1.0",
            source_trace_ref=tau_ref,
            receipts=[self._receipt(record.evidence_receipt_ref) for record in tau_records],
            records=tau_records,
            diagnostics=[self._diagnostic(record.run_id) for record in tau_records],
            dsh_receipts=[
                self._receipt(record.evidence_receipt_ref) for record in dsh_records
            ],
            dsh_records=dsh_records,
            evidence_joins=joins,
        )
        retained = self.store.resolve_artifact_uri(
            f"artifact:{artifact.result_artifact}"
        )
        if not retained.is_file():
            raise FormalBatchError("retained formal raw result is unavailable")
        summary = self._summarize_and_verify(result, spec)
        if canonical_digest(summary) != canonical_digest(artifact.summary):
            raise FormalBatchError("formal batch summary no longer matches its run evidence")

    def _summarize_and_verify(
        self,
        result: DshTau3PilotResult,
        spec: FormalBatchSpec,
    ) -> EvaluationSummary:
        expected_count = len(spec.task_ids) * spec.trials
        if len(result.records) != expected_count or len(result.dsh_records) != expected_count:
            raise FormalBatchError("formal batch does not contain every expected task trial")
        self._verify_receipts(result.records, result.receipts)
        self._verify_receipts(result.dsh_records, result.dsh_receipts)
        if self.store.verify(result.source_trace_ref) is not EvidenceStatus.VERIFIED:
            raise FormalBatchError("τ³ source trace is not verified")
        joins = {(join.task_id, join.trial_index): join for join in result.evidence_joins}
        if len(joins) != expected_count:
            raise FormalBatchError("formal batch evidence joins are incomplete")
        tau_by_pair = {(record.task_id, record.trial_index): record for record in result.records}
        dsh_by_pair = {
            (record.task_id, record.trial_index): record for record in result.dsh_records
        }
        if set(joins) != set(tau_by_pair) or set(joins) != set(dsh_by_pair):
            raise FormalBatchError("formal batch evidence planes have different task trials")
        for pair, join in joins.items():
            tau = tau_by_pair[pair]
            dsh = dsh_by_pair[pair]
            if (
                join.tau_run_id != tau.run_id
                or join.dsh_run_id != dsh.run_id
                or join.outcome_success != tau.success
                or dsh.success != tau.success
            ):
                raise FormalBatchError("formal batch evidence join conflicts with its runs")
            verified = BridgeService(self.project_root).verify_trace(
                join.dsh_source_trace_ref
            )
            if verified.get("evidence_status") != EvidenceStatus.VERIFIED.value:
                raise FormalBatchError("DeepSeek Harness source trace is not verified")
        summary = EvaluationAuditor().summarize(
            result.records,
            EvaluationContext(
                pool=spec.pool,
                snapshot_id=spec.snapshot_id,
                candidate_id=spec.candidate_id,
                expected_task_ids=spec.task_ids,
                trials=spec.trials,
            ),
            evidence_verified_run_ids={record.run_id for record in result.records},
        )
        return summary

    @staticmethod
    def _verify_receipts(
        records: list[RunRecord],
        receipts: list[EvidenceReceipt],
    ) -> None:
        by_run = {receipt.run_id: receipt for receipt in receipts}
        if len(by_run) != len(records):
            raise FormalBatchError("formal batch receipt population is incomplete")
        for record in records:
            receipt = by_run.get(record.run_id)
            if (
                receipt is None
                or receipt.receipt_id != record.evidence_receipt_ref
                or receipt.source_trace_id != record.source_trace_ref
                or receipt.normalized_record_digest != canonical_digest(record)
            ):
                raise FormalBatchError("formal batch receipt does not authenticate its run")

    def _artifact_path(self, spec: FormalBatchSpec) -> Path:
        return (
            self.project_root
            / "runs/experiments"
            / spec.experiment_id
            / "batches"
            / f"{spec.batch_id}.json"
        )

    def _run_record(self, run_id: str) -> RunRecord:
        return self._model(self.store.path_for("normalized", run_id), RunRecord)

    def _receipt(self, receipt_id: str) -> EvidenceReceipt:
        return self._model(self.store.path_for("receipts", receipt_id), EvidenceReceipt)

    def _trace_ref(self, trace_id: str) -> SourceTraceRef:
        return self._model(self.store.path_for("trace_refs", trace_id), SourceTraceRef)

    def _join(self, join_id: str) -> PilotEvidenceJoin:
        return self._model(self.store.path_for("evidence_joins", join_id), PilotEvidenceJoin)

    def _diagnostic(self, run_id: str):
        from agentloopgate.adapters import OutcomeDiagnostics

        return self._model(self.store.path_for("diagnostics", run_id), OutcomeDiagnostics)

    @staticmethod
    def _model(path: Path, model):
        try:
            return model.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FormalBatchError(
                f"formal batch artifact is unavailable or corrupt: {path}"
            ) from exc

    @staticmethod
    def _load(path: Path) -> FormalBatchArtifact:
        try:
            return FormalBatchArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FormalBatchError("formal batch registry is unavailable or corrupt") from exc

    @staticmethod
    def _write_once(path: Path, payload: object) -> None:
        encoded = canonical_json_bytes(payload) + b"\n"
        if path.exists():
            try:
                existing = canonical_json_bytes(
                    json.loads(path.read_text(encoding="utf-8"))
                ) + b"\n"
            except (OSError, json.JSONDecodeError) as exc:
                raise FormalBatchError("existing formal batch artifact is corrupt") from exc
            if existing != encoded:
                raise FormalBatchError("formal batch artifact conflict")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
