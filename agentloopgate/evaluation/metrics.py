"""Strict Pass^k aggregation and symmetric baseline comparison."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from agentloopgate.schemas import ArtifactId, Digest, Pool, RunRecord, RunValidity
from agentloopgate.schemas.models import StrictModel


class EvaluationIntegrityError(ValueError):
    """Evaluation records conflict with their frozen execution context."""


class EvaluationContext(StrictModel):
    pool: Pool
    snapshot_id: ArtifactId
    candidate_id: ArtifactId | None
    expected_task_ids: list[ArtifactId] = Field(min_length=1)
    trials: int = Field(ge=1)

    @model_validator(mode="after")
    def task_ids_are_unique(self) -> EvaluationContext:
        if len(self.expected_task_ids) != len(set(self.expected_task_ids)):
            raise ValueError("expected_task_ids must be unique")
        return self


class EvaluationSummary(StrictModel):
    schema_version: Literal["1.0", "1.1"]
    pool: Pool
    snapshot_id: ArtifactId
    candidate_id: ArtifactId | None
    trials: int
    expected_task_count: int
    valid_run_count: int
    infra_invalid_count: int
    pass_1_numerator: int
    pass_1_denominator: int
    stable_success_task_count: int
    stable_task_outcomes: dict[ArtifactId, bool]
    task_success_counts: dict[ArtifactId, int]
    critical_violation_count: int
    mean_cost: Decimal = Field(ge=0)
    cost_source: Literal["direct_task_attempt_model_calls"] | None = None
    cost_status: Literal["exact", "partial", "unavailable"] | None = None
    cost_digest: Digest | None = None
    p50_latency_ms: Decimal
    integrity_complete: bool
    integrity_issues: list[str]

    @model_validator(mode="after")
    def task_metrics_are_consistent(self) -> EvaluationSummary:
        if set(self.stable_task_outcomes) != set(self.task_success_counts):
            raise ValueError("task outcome and success-count populations differ")
        for task_id, count in self.task_success_counts.items():
            if not 0 <= count <= self.trials:
                raise ValueError("task success count is outside the trial range")
            if self.stable_task_outcomes[task_id] != (count == self.trials):
                raise ValueError("stable task outcome conflicts with success count")
        cost_evidence = (self.cost_source, self.cost_status, self.cost_digest)
        if self.schema_version == "1.1" and any(item is None for item in cost_evidence):
            raise ValueError("evaluation summary 1.1 requires direct cost evidence")
        if self.schema_version == "1.0" and any(item is not None for item in cost_evidence):
            raise ValueError("evaluation summary 1.0 cannot contain direct cost evidence")
        return self


class EvaluationComparison(StrictModel):
    schema_version: Literal["1.0"]
    pool: Pool
    baseline_snapshot_id: ArtifactId
    candidate_id: ArtifactId
    stable_task_net: int
    catastrophic_regressions: int
    catastrophic_task_ids: list[ArtifactId]
    mean_cost_ratio: Decimal | None
    p50_latency_ratio: Decimal | None


class EvaluationAuditor:
    def summarize(
        self,
        records: list[RunRecord],
        context: EvaluationContext,
        *,
        evidence_verified_run_ids: set[str],
    ) -> EvaluationSummary:
        expected_tasks = set(context.expected_task_ids)
        valid_by_pair: dict[tuple[str, int], RunRecord] = {}
        infra_count = 0
        issues: set[str] = set()
        seen_run_ids: set[str] = set()
        for record in records:
            if record.run_id in seen_run_ids:
                raise EvaluationIntegrityError(f"duplicate run id: {record.run_id}")
            seen_run_ids.add(record.run_id)
            if (
                record.pool is not context.pool
                or record.snapshot_id != context.snapshot_id
                or record.candidate_id != context.candidate_id
            ):
                raise EvaluationIntegrityError("run context does not match evaluation context")
            if record.task_id not in expected_tasks:
                raise EvaluationIntegrityError(f"unexpected task in evaluation: {record.task_id}")
            if not 1 <= record.trial_index <= context.trials:
                raise EvaluationIntegrityError("run trial index is outside the frozen range")
            if record.run_id not in evidence_verified_run_ids:
                issues.add("unverified_evidence")
            if record.run_validity is RunValidity.INFRA_INVALID:
                infra_count += 1
                continue
            pair = (record.task_id, record.trial_index)
            if pair in valid_by_pair:
                raise EvaluationIntegrityError(
                    f"duplicate valid task trial: {record.task_id}/{record.trial_index}"
                )
            valid_by_pair[pair] = record

        expected_pairs = {
            (task_id, trial)
            for task_id in context.expected_task_ids
            for trial in range(1, context.trials + 1)
        }
        if set(valid_by_pair) != expected_pairs:
            issues.add("missing_valid_trials")
        valid_records = list(valid_by_pair.values())
        pass_numerator = sum(record.success is True for record in valid_records)
        stable = {
            task_id: all(
                valid_by_pair.get((task_id, trial)) is not None
                and valid_by_pair[(task_id, trial)].success is True
                for trial in range(1, context.trials + 1)
            )
            for task_id in sorted(context.expected_task_ids)
        }
        success_counts = {
            task_id: sum(
                valid_by_pair.get((task_id, trial)) is not None
                and valid_by_pair[(task_id, trial)].success is True
                for trial in range(1, context.trials + 1)
            )
            for task_id in sorted(context.expected_task_ids)
        }
        costs = [record.cost for record in valid_records]
        latencies = sorted(Decimal(record.latency_ms) for record in valid_records)
        return EvaluationSummary(
            schema_version="1.0",
            pool=context.pool,
            snapshot_id=context.snapshot_id,
            candidate_id=context.candidate_id,
            trials=context.trials,
            expected_task_count=len(context.expected_task_ids),
            valid_run_count=len(valid_records),
            infra_invalid_count=infra_count,
            pass_1_numerator=pass_numerator,
            pass_1_denominator=len(valid_records),
            stable_success_task_count=sum(stable.values()),
            stable_task_outcomes=stable,
            task_success_counts=success_counts,
            critical_violation_count=sum(
                len(record.critical_violations) for record in valid_records
            ),
            mean_cost=(sum(costs, Decimal(0)) / len(costs) if costs else Decimal(0)),
            p50_latency_ms=self._median(latencies),
            integrity_complete=not issues,
            integrity_issues=sorted(issues),
        )

    @staticmethod
    def compare(
        baseline: EvaluationSummary,
        candidate: EvaluationSummary,
    ) -> EvaluationComparison:
        if baseline.pool is not candidate.pool:
            raise EvaluationIntegrityError("baseline and candidate pools differ")
        if baseline.trials != candidate.trials:
            raise EvaluationIntegrityError("baseline and candidate trial counts differ")
        if set(baseline.stable_task_outcomes) != set(candidate.stable_task_outcomes):
            raise EvaluationIntegrityError("baseline and candidate task populations differ")
        if set(baseline.task_success_counts) != set(candidate.task_success_counts):
            raise EvaluationIntegrityError(
                "baseline and candidate success-count populations differ"
            )
        if candidate.candidate_id is None:
            raise EvaluationIntegrityError("candidate summary is missing candidate_id")
        catastrophic = sorted(
            task_id
            for task_id, baseline_stable in baseline.stable_task_outcomes.items()
            if baseline_stable and candidate.task_success_counts[task_id] == 0
        )
        return EvaluationComparison(
            schema_version="1.0",
            pool=candidate.pool,
            baseline_snapshot_id=baseline.snapshot_id,
            candidate_id=candidate.candidate_id,
            stable_task_net=(
                candidate.stable_success_task_count - baseline.stable_success_task_count
            ),
            catastrophic_regressions=len(catastrophic),
            catastrophic_task_ids=catastrophic,
            mean_cost_ratio=_ratio(candidate.mean_cost, baseline.mean_cost),
            p50_latency_ratio=_ratio(
                candidate.p50_latency_ms,
                baseline.p50_latency_ms,
            ),
        )

    @staticmethod
    def _median(values: list[Decimal]) -> Decimal:
        if not values:
            return Decimal(0)
        middle = len(values) // 2
        if len(values) % 2:
            return values[middle]
        return (values[middle - 1] + values[middle]) / 2


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return Decimal(1) if numerator == 0 else None
    return numerator / denominator
