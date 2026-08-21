"""Descriptive diagnosis-direction ablation derived from the frozen core matrix."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Literal

from pydantic import Field

from agentloopgate.contracts import canonical_digest
from agentloopgate.evaluation import EvaluationAuditor
from agentloopgate.schemas import (
    ArtifactId,
    AssetFamily,
    CandidateRecord,
    Digest,
    FailureType,
)
from agentloopgate.schemas.models import NonEmpty, StrictModel

from .batch import FormalBatchArtifact
from .diagnostics import FormalDiagnosisArtifact
from .orchestrator_types import SelectionView
from .study import BankingR2StudyPlan


class DiagnosisDirectionCandidateResult(StrictModel):
    candidate_id: ArtifactId
    snapshot_id: ArtifactId
    failure_bundle_digest: Digest
    source_failure_type: FailureType
    source_target_asset_families: list[AssetFamily] = Field(min_length=1)
    candidate_asset_families: list[AssetFamily] = Field(min_length=1)
    target_alignment: bool
    update_check_batch_id: ArtifactId
    update_check_batch_digest: Digest
    update_check_stable_task_net_vs_a0: int
    update_check_stable_rate_net_vs_a0: Decimal = Field(ge=-1, le=1)
    selection_batch_id: ArtifactId
    selection_batch_digest: Digest
    selection_stable_success_task_count: int = Field(ge=0)
    selection_task_count: int = Field(ge=1)
    selection_stable_rate: Decimal = Field(ge=0, le=1)
    updater_native_rank: int = Field(ge=1)
    governance_rank: int | None = Field(default=None, ge=1)
    selected_by_updater_native: bool
    selected_by_agentloopgate: bool
    observed_transition: Literal[
        "selected_by_agentloopgate",
        "eligible_not_selected",
        "ineligible_critical_or_incomplete",
    ]


class AssetFamilyDirectionSummary(StrictModel):
    asset_family: AssetFamily
    candidate_count: int = Field(ge=1)
    mean_update_check_stable_rate_net_vs_a0: Decimal = Field(ge=-1, le=1)
    mean_selection_stable_rate: Decimal = Field(ge=0, le=1)
    agentloopgate_selection_count: int = Field(ge=0)


class DiagnosisDirectionAblationArtifact(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    ablation_id: Literal["diagnosis_direction"] = "diagnosis_direction"
    experiment_id: ArtifactId
    protocol_digest: Digest
    study_digest: Digest
    source_revision: NonEmpty
    diagnosis_digest: Digest
    selection_digest: Digest
    evidence_mode: Literal["core_matrix"] = "core_matrix"
    additional_model_calls: Literal[False] = False
    formal_decision: Literal[False] = False
    causal_claim_supported: Literal[False] = False
    candidate_results: list[DiagnosisDirectionCandidateResult] = Field(
        min_length=3, max_length=6
    )
    family_summaries: list[AssetFamilyDirectionSummary] = Field(min_length=2)
    interpretation: NonEmpty
    limitations: list[NonEmpty] = Field(min_length=2)
    artifact_digest: Digest


def build_diagnosis_direction_ablation(
    *,
    experiment_id: str,
    study: BankingR2StudyPlan,
    source_revision: str,
    diagnosis: FormalDiagnosisArtifact,
    candidates: list[CandidateRecord],
    candidate_snapshots: list[str],
    baseline_update_check: FormalBatchArtifact,
    candidate_update_check: dict[str, FormalBatchArtifact],
    selection_batches: dict[str, FormalBatchArtifact],
    selection: SelectionView,
) -> DiagnosisDirectionAblationArtifact:
    """Describe whether targeted changes survive Update-Check into Selection."""

    if len(candidates) != len(candidate_snapshots):
        raise ValueError("diagnosis ablation candidate/snapshot populations differ")
    bundles = {
        canonical_digest(item.bundle): item.bundle for item in diagnosis.ranked_bundles
    }
    inputs = {item.candidate_id: item for item in selection.inputs}
    eligible = [
        item
        for item in selection.inputs
        if item.evaluation_complete and item.critical_violations == 0
    ]
    governed_order = sorted(
        eligible,
        key=lambda item: (
            -item.stable_success_task_count,
            item.mean_cost,
            item.p50_latency_ms,
            item.candidate_id,
        ),
    )
    governed_ranks = {
        item.candidate_id: index for index, item in enumerate(governed_order, start=1)
    }
    results: list[DiagnosisDirectionCandidateResult] = []
    for candidate, snapshot_id in zip(candidates, candidate_snapshots, strict=True):
        bundle = bundles.get(candidate.failure_bundle_digest)
        if bundle is None:
            raise ValueError("candidate is not linked to the frozen diagnosis bundles")
        selection_input = inputs.get(candidate.candidate_id)
        if selection_input is None or selection_input.native_rank is None:
            raise ValueError("candidate is missing from the frozen dual-selector inputs")
        update_batch = candidate_update_check[snapshot_id]
        selection_batch = selection_batches[snapshot_id]
        update_comparison = EvaluationAuditor.compare(
            baseline_update_check.summary,
            update_batch.summary,
        )
        selection_summary = selection_batch.summary
        selection_rate = Decimal(
            selection_summary.stable_success_task_count
        ) / selection_summary.expected_task_count
        governance_rank = governed_ranks.get(candidate.candidate_id)
        selected_by_agentloopgate = (
            candidate.candidate_id == selection.selection.agentloopgate_candidate_id
        )
        if selected_by_agentloopgate:
            transition = "selected_by_agentloopgate"
        elif governance_rank is not None:
            transition = "eligible_not_selected"
        else:
            transition = "ineligible_critical_or_incomplete"
        results.append(
            DiagnosisDirectionCandidateResult(
                candidate_id=candidate.candidate_id,
                snapshot_id=snapshot_id,
                failure_bundle_digest=candidate.failure_bundle_digest,
                source_failure_type=bundle.failure_type,
                source_target_asset_families=bundle.target_asset_families,
                candidate_asset_families=candidate.asset_families,
                target_alignment=set(candidate.asset_families).issubset(
                    set(bundle.target_asset_families)
                ),
                update_check_batch_id=update_batch.batch_id,
                update_check_batch_digest=update_batch.batch_digest,
                update_check_stable_task_net_vs_a0=(
                    update_comparison.stable_task_net
                ),
                update_check_stable_rate_net_vs_a0=(
                    Decimal(update_comparison.stable_task_net)
                    / update_batch.summary.expected_task_count
                ),
                selection_batch_id=selection_batch.batch_id,
                selection_batch_digest=selection_batch.batch_digest,
                selection_stable_success_task_count=(
                    selection_summary.stable_success_task_count
                ),
                selection_task_count=selection_summary.expected_task_count,
                selection_stable_rate=selection_rate,
                updater_native_rank=selection_input.native_rank,
                governance_rank=governance_rank,
                selected_by_updater_native=(
                    candidate.candidate_id == selection.selection.native_candidate_id
                ),
                selected_by_agentloopgate=selected_by_agentloopgate,
                observed_transition=transition,
            )
        )
    by_family: dict[AssetFamily, list[DiagnosisDirectionCandidateResult]] = defaultdict(
        list
    )
    for result in results:
        for family in result.candidate_asset_families:
            by_family[family].append(result)
    family_summaries = [
        AssetFamilyDirectionSummary(
            asset_family=family,
            candidate_count=len(items),
            mean_update_check_stable_rate_net_vs_a0=(
                sum(
                    (item.update_check_stable_rate_net_vs_a0 for item in items),
                    Decimal(0),
                )
                / len(items)
            ),
            mean_selection_stable_rate=(
                sum((item.selection_stable_rate for item in items), Decimal(0))
                / len(items)
            ),
            agentloopgate_selection_count=sum(
                item.selected_by_agentloopgate for item in items
            ),
        )
        for family, items in sorted(by_family.items(), key=lambda pair: pair[0].value)
    ]
    payload = {
        "schema_version": "1.0",
        "ablation_id": "diagnosis_direction",
        "experiment_id": experiment_id,
        "protocol_digest": study.protocol_digest,
        "study_digest": study.study_digest,
        "source_revision": source_revision,
        "diagnosis_digest": diagnosis.diagnosis_digest,
        "selection_digest": selection.selection_digest,
        "evidence_mode": "core_matrix",
        "additional_model_calls": False,
        "formal_decision": False,
        "causal_claim_supported": False,
        "candidate_results": results,
        "family_summaries": family_summaries,
        "interpretation": (
            "This descriptive ablation traces each diagnosed failure type through its "
            "targeted asset family, Update-Check net effect, frozen Selection result, "
            "and both selector outcomes without additional model calls."
        ),
        "limitations": [
            "Only three generated candidates are compared and asset-family assignment "
            "is not randomized, so family-level differences are not causal effects.",
            "Selection has no A0 arm in the frozen matrix; its stable rate is reported "
            "descriptively rather than as a baseline-relative improvement.",
        ],
    }
    return DiagnosisDirectionAblationArtifact.model_validate(
        {**payload, "artifact_digest": canonical_digest(payload)}
    )
