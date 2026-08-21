"""Frozen task-paired publication statistics for Banking R2."""

from __future__ import annotations

import math
import random
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from agentloopgate.contracts import canonical_digest
from agentloopgate.evaluation import EvaluationSummary
from agentloopgate.schemas import ArtifactId, Digest, Pool
from agentloopgate.schemas.models import NonEmpty, StrictModel

from .batch import FormalBatchArtifact, FormalStage
from .study import BankingR2StudyPlan

StudyRole = Literal["baseline", "updater_native", "agentloopgate"]


class PairedTaskBootstrapComparison(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    comparison_id: NonEmpty
    reference_role: StudyRole
    candidate_role: StudyRole
    stage: FormalStage
    pool: Pool
    reference_snapshot_id: ArtifactId
    candidate_snapshot_id: ArtifactId
    reference_candidate_id: ArtifactId | None
    candidate_candidate_id: ArtifactId | None
    reference_batch_id: ArtifactId
    candidate_batch_id: ArtifactId
    reference_batch_digest: Digest
    candidate_batch_digest: Digest
    reference_summary_digest: Digest
    candidate_summary_digest: Digest
    task_count: int = Field(ge=1)
    observed_stable_task_net: int
    observed_rate_difference: Decimal = Field(ge=-1, le=1)
    confidence_level: Literal["0.95"]
    interval_method: Literal["paired_task_bootstrap_nearest_rank"]
    bootstrap_resamples: int = Field(ge=10_000)
    bootstrap_seed: int = Field(ge=0)
    effective_seed: int = Field(ge=0)
    ci_lower: Decimal = Field(ge=-1, le=1)
    ci_upper: Decimal = Field(ge=-1, le=1)
    invalid_run_policy: Literal[
        "report_separately_and_hold_incomplete_batches"
    ]
    reference_infra_invalid_count: int = Field(ge=0)
    candidate_infra_invalid_count: int = Field(ge=0)
    integrity_complete: bool
    comparison_digest: Digest

    @model_validator(mode="after")
    def interval_and_integrity_are_consistent(self) -> PairedTaskBootstrapComparison:
        if self.ci_lower > self.ci_upper:
            raise ValueError("bootstrap confidence interval is reversed")
        if not self.integrity_complete:
            raise ValueError("publication bootstrap cannot include incomplete evidence")
        if self.reference_infra_invalid_count or self.candidate_infra_invalid_count:
            raise ValueError("publication bootstrap cannot hide Infra Invalid runs")
        return self


class PublicationStatisticsArtifact(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    experiment_id: ArtifactId
    protocol_digest: Digest
    study_digest: Digest
    source_revision: NonEmpty
    statistical_unit: Literal["task"]
    primary_endpoint: Literal["stable_success_task_count"]
    paired_comparison: Literal[True]
    confidence_level: Literal["0.95"]
    interval_method: Literal["paired_task_bootstrap_nearest_rank"]
    bootstrap_resamples: int = Field(ge=10_000)
    bootstrap_seed: int = Field(ge=0)
    role_alias: bool
    comparisons: list[PairedTaskBootstrapComparison] = Field(
        min_length=6, max_length=6
    )
    statistics_digest: Digest


class SelectorAblationArtifact(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    ablation_id: Literal["selector"] = "selector"
    experiment_id: ArtifactId
    protocol_digest: Digest
    study_digest: Digest
    source_revision: NonEmpty
    selection_digest: Digest
    evidence_mode: Literal["core_matrix"] = "core_matrix"
    additional_model_calls: Literal[False] = False
    formal_decision: Literal[False] = False
    updater_native_candidate_id: ArtifactId
    updater_native_snapshot_id: ArtifactId
    agentloopgate_candidate_id: ArtifactId
    agentloopgate_snapshot_id: ArtifactId
    role_alias: bool
    evidence_reused: bool
    contrast_kind: Literal[
        "independent_selected_snapshots", "null_contrast_identical_snapshot"
    ]
    comparisons: list[PairedTaskBootstrapComparison] = Field(
        min_length=3, max_length=3
    )
    interpretation: NonEmpty
    artifact_digest: Digest


def paired_task_bootstrap(
    *,
    comparison_id: str,
    reference_role: StudyRole,
    candidate_role: StudyRole,
    stage: FormalStage,
    reference: FormalBatchArtifact,
    candidate: FormalBatchArtifact,
    study: BankingR2StudyPlan,
) -> PairedTaskBootstrapComparison:
    """Compute a deterministic paired bootstrap over stable task outcomes."""

    reference_summary = reference.summary
    candidate_summary = candidate.summary
    _verify_pair(reference_summary, candidate_summary, stage=stage)
    task_ids = sorted(reference_summary.stable_task_outcomes)
    differences = [
        int(candidate_summary.stable_task_outcomes[task_id])
        - int(reference_summary.stable_task_outcomes[task_id])
        for task_id in task_ids
    ]
    seed_payload = {
        "bootstrap_seed": study.statistics.bootstrap_seed,
        "comparison_id": comparison_id,
        "stage": stage.value,
        "reference_batch_digest": reference.batch_digest,
        "candidate_batch_digest": candidate.batch_digest,
    }
    effective_seed = int(
        canonical_digest(seed_payload).removeprefix("sha256:")[:16], 16
    )
    rng = random.Random(effective_seed)
    n = len(task_ids)
    resampled_nets = sorted(
        sum(differences[rng.randrange(n)] for _ in range(n))
        for _ in range(study.statistics.bootstrap_resamples)
    )
    lower_net = _nearest_rank(resampled_nets, Decimal("0.025"))
    upper_net = _nearest_rank(resampled_nets, Decimal("0.975"))
    observed_net = sum(differences)
    payload = {
        "schema_version": "1.0",
        "comparison_id": comparison_id,
        "reference_role": reference_role,
        "candidate_role": candidate_role,
        "stage": stage,
        "pool": candidate_summary.pool,
        "reference_snapshot_id": reference_summary.snapshot_id,
        "candidate_snapshot_id": candidate_summary.snapshot_id,
        "reference_candidate_id": reference_summary.candidate_id,
        "candidate_candidate_id": candidate_summary.candidate_id,
        "reference_batch_id": reference.batch_id,
        "candidate_batch_id": candidate.batch_id,
        "reference_batch_digest": reference.batch_digest,
        "candidate_batch_digest": candidate.batch_digest,
        "reference_summary_digest": canonical_digest(reference_summary),
        "candidate_summary_digest": canonical_digest(candidate_summary),
        "task_count": n,
        "observed_stable_task_net": observed_net,
        "observed_rate_difference": Decimal(observed_net) / n,
        "confidence_level": study.statistics.confidence_level,
        "interval_method": "paired_task_bootstrap_nearest_rank",
        "bootstrap_resamples": study.statistics.bootstrap_resamples,
        "bootstrap_seed": study.statistics.bootstrap_seed,
        "effective_seed": effective_seed,
        "ci_lower": Decimal(lower_net) / n,
        "ci_upper": Decimal(upper_net) / n,
        "invalid_run_policy": study.statistics.invalid_run_policy,
        "reference_infra_invalid_count": reference_summary.infra_invalid_count,
        "candidate_infra_invalid_count": candidate_summary.infra_invalid_count,
        "integrity_complete": (
            reference_summary.integrity_complete
            and candidate_summary.integrity_complete
        ),
    }
    return PairedTaskBootstrapComparison.model_validate(
        {**payload, "comparison_digest": canonical_digest(payload)}
    )


def build_publication_statistics(
    *,
    experiment_id: str,
    study: BankingR2StudyPlan,
    source_revision: str,
    role_alias: bool,
    release: dict[str, dict[FormalStage, FormalBatchArtifact]],
    baseline_snapshot_id: str,
    updater_native_snapshot_id: str,
    agentloopgate_snapshot_id: str,
) -> PublicationStatisticsArtifact:
    comparisons = [
        paired_task_bootstrap(
            comparison_id=f"baseline_vs_{role}:{stage.value}",
            reference_role="baseline",
            candidate_role=role,
            stage=stage,
            reference=release[baseline_snapshot_id][stage],
            candidate=release[snapshot_id][stage],
            study=study,
        )
        for role, snapshot_id in (
            ("updater_native", updater_native_snapshot_id),
            ("agentloopgate", agentloopgate_snapshot_id),
        )
        for stage in (
            FormalStage.RELEASE_ID,
            FormalStage.RELEASE_OOD,
            FormalStage.REPLAY,
        )
    ]
    payload = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "protocol_digest": study.protocol_digest,
        "study_digest": study.study_digest,
        "source_revision": source_revision,
        "statistical_unit": study.statistics.statistical_unit,
        "primary_endpoint": study.statistics.primary_endpoint,
        "paired_comparison": study.statistics.paired_comparison,
        "confidence_level": study.statistics.confidence_level,
        "interval_method": "paired_task_bootstrap_nearest_rank",
        "bootstrap_resamples": study.statistics.bootstrap_resamples,
        "bootstrap_seed": study.statistics.bootstrap_seed,
        "role_alias": role_alias,
        "comparisons": comparisons,
    }
    return PublicationStatisticsArtifact.model_validate(
        {**payload, "statistics_digest": canonical_digest(payload)}
    )


def build_selector_ablation(
    *,
    experiment_id: str,
    study: BankingR2StudyPlan,
    source_revision: str,
    selection_digest: str,
    updater_native_candidate_id: str,
    updater_native_snapshot_id: str,
    agentloopgate_candidate_id: str,
    agentloopgate_snapshot_id: str,
    release: dict[str, dict[FormalStage, FormalBatchArtifact]],
) -> SelectorAblationArtifact:
    role_alias = updater_native_snapshot_id == agentloopgate_snapshot_id
    comparisons = [
        paired_task_bootstrap(
            comparison_id=f"updater_native_vs_agentloopgate:{stage.value}",
            reference_role="updater_native",
            candidate_role="agentloopgate",
            stage=stage,
            reference=release[updater_native_snapshot_id][stage],
            candidate=release[agentloopgate_snapshot_id][stage],
            study=study,
        )
        for stage in (
            FormalStage.RELEASE_ID,
            FormalStage.RELEASE_OOD,
            FormalStage.REPLAY,
        )
    ]
    if role_alias and any(
        comparison.observed_stable_task_net != 0
        or comparison.ci_lower != 0
        or comparison.ci_upper != 0
        for comparison in comparisons
    ):
        raise ValueError("identical selector snapshots must produce a null contrast")
    payload = {
        "schema_version": "1.0",
        "ablation_id": "selector",
        "experiment_id": experiment_id,
        "protocol_digest": study.protocol_digest,
        "study_digest": study.study_digest,
        "source_revision": source_revision,
        "selection_digest": selection_digest,
        "evidence_mode": "core_matrix",
        "additional_model_calls": False,
        "formal_decision": False,
        "updater_native_candidate_id": updater_native_candidate_id,
        "updater_native_snapshot_id": updater_native_snapshot_id,
        "agentloopgate_candidate_id": agentloopgate_candidate_id,
        "agentloopgate_snapshot_id": agentloopgate_snapshot_id,
        "role_alias": role_alias,
        "evidence_reused": role_alias,
        "contrast_kind": (
            "null_contrast_identical_snapshot"
            if role_alias
            else "independent_selected_snapshots"
        ),
        "comparisons": comparisons,
        "interpretation": (
            "Both selectors chose the same physical snapshot; release evidence was "
            "reused exactly and the selector contrast is [0, 0], not an independent "
            "second experiment."
            if role_alias
            else "Selectors chose different physical snapshots; paired release-pool "
            "contrasts quantify their observed difference without extra model calls."
        ),
    }
    return SelectorAblationArtifact.model_validate(
        {**payload, "artifact_digest": canonical_digest(payload)}
    )


def _verify_pair(
    reference: EvaluationSummary,
    candidate: EvaluationSummary,
    *,
    stage: FormalStage,
) -> None:
    if reference.pool is not candidate.pool:
        raise ValueError("paired bootstrap pools differ")
    expected_pool = (
        Pool.UPDATE_SOURCE if stage is FormalStage.REPLAY else Pool(stage.value)
    )
    if reference.pool is not expected_pool:
        raise ValueError("paired bootstrap stage does not match its pool")
    if reference.trials != candidate.trials:
        raise ValueError("paired bootstrap trial counts differ")
    if set(reference.stable_task_outcomes) != set(candidate.stable_task_outcomes):
        raise ValueError("paired bootstrap task populations differ")
    if not reference.stable_task_outcomes:
        raise ValueError("paired bootstrap has no tasks")
    if not reference.integrity_complete or not candidate.integrity_complete:
        raise ValueError("paired bootstrap requires complete evidence")
    if reference.infra_invalid_count or candidate.infra_invalid_count:
        raise ValueError("paired bootstrap cannot include Infra Invalid runs")


def _nearest_rank(values: list[int], probability: Decimal) -> int:
    if not values:
        raise ValueError("cannot take a bootstrap percentile of no samples")
    rank = max(1, math.ceil(float(probability * len(values))))
    return values[min(rank - 1, len(values) - 1)]
