"""Pre-registered Banking matrix and minimal publication ablations."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator

from agentloopgate.contracts import canonical_digest
from agentloopgate.schemas import ArtifactId, Digest
from agentloopgate.schemas.models import NonEmpty, StrictModel, UtcDateTime

from .batch import FormalStage


class StudyMatrixRow(StrictModel):
    stage: FormalStage
    task_count: int = Field(ge=1)
    trials: int = Field(ge=1)
    variant_count: int = Field(ge=1)
    target_trials: int = Field(ge=1)

    @model_validator(mode="after")
    def target_count_is_exact(self) -> StudyMatrixRow:
        expected = self.task_count * self.trials * self.variant_count
        if self.target_trials != expected:
            raise ValueError(f"study row target_trials must equal {expected}")
        return self


class StudyAblation(StrictModel):
    ablation_id: ArtifactId
    question: NonEmpty
    evidence_mode: Literal["core_matrix", "artifact_replay", "headless_fixture"]
    additional_model_calls: Literal[False]
    measurements: list[NonEmpty] = Field(min_length=1)


class StudyStatistics(StrictModel):
    statistical_unit: Literal["task"]
    primary_endpoint: Literal["stable_success_task_count"]
    paired_comparison: Literal[True]
    interval_method: Literal["paired_task_bootstrap"]
    confidence_level: Literal["0.95"]
    bootstrap_resamples: int = Field(ge=10_000)
    bootstrap_seed: int = Field(ge=0)
    invalid_run_policy: Literal["report_separately_and_hold_incomplete_batches"]


class BankingStudyPlan(StrictModel):
    schema_version: Literal["1.0", "1.1", "1.2"]
    study_id: ArtifactId
    experiment_id: ArtifactId
    protocol_digest: Digest
    status: Literal["frozen"]
    frozen_at: UtcDateTime
    claim_scope: Literal["governance_selection_and_evidence_integrity"]
    variant_roles: list[
        Literal["baseline", "updater_native", "agentloopgate"]
    ]
    supersedes_study_digest: Digest | None = None
    selector_role_alias_policy: Literal[
        "reuse_identical_snapshot_evidence_and_report_null_contrast"
    ] | None = None
    selection_baseline_policy: Literal[
        "same_pool_same_tasks_same_trials_required"
    ] | None = None
    selection_abstain_policy: Literal[
        "hold_unless_strict_stable_gain_without_stable_regression"
    ] | None = None
    selection_operational_evidence_policy: Literal[
        "whole_attempt_retry_timeout_p95_max_v1"
    ] | None = None
    candidate_semantic_policy: Literal[
        "runtime_capability_bound_and_semantically_distinct_v1"
    ] | None = None
    selection_whole_attempt_cost_ratio_max: Decimal | None = Field(
        default=None, gt=0
    )
    selection_p95_latency_ratio_max: Decimal | None = Field(default=None, gt=0)
    selection_max_retry_increase: int | None = Field(default=None, ge=0)
    selection_max_timeout_increase: int | None = Field(default=None, ge=0)
    matrix: list[StudyMatrixRow] = Field(min_length=6, max_length=6)
    core_target_trial_count: int = Field(ge=1)
    ablations: list[StudyAblation] = Field(min_length=4, max_length=4)
    statistics: StudyStatistics
    study_digest: Digest

    @model_validator(mode="after")
    def design_is_complete(self) -> BankingStudyPlan:
        expected_stages = [
            FormalStage.UPDATE_SOURCE,
            FormalStage.UPDATE_CHECK,
            FormalStage.SELECTION,
            FormalStage.RELEASE_ID,
            FormalStage.RELEASE_OOD,
            FormalStage.REPLAY,
        ]
        if [row.stage for row in self.matrix] != expected_stages:
            raise ValueError("study matrix must preserve the frozen stage order")
        if sum(row.target_trials for row in self.matrix) != self.core_target_trial_count:
            raise ValueError("study matrix does not match core_target_trial_count")
        if self.variant_roles != ["baseline", "updater_native", "agentloopgate"]:
            raise ValueError("study must compare baseline, updater-native, and AgentLoopGate")
        required_ablations = {
            "selector",
            "integrity_gate",
            "diagnosis_direction",
            "plugin_coexistence_overhead",
        }
        if {item.ablation_id for item in self.ablations} != required_ablations:
            raise ValueError("study must contain the four frozen minimal ablations")
        version_1_1 = (
            self.supersedes_study_digest is not None
            and self.selector_role_alias_policy is not None
        )
        if self.schema_version in {"1.1", "1.2"} and not version_1_1:
            raise ValueError("study 1.1 requires supersession and selector alias policy")
        if self.schema_version == "1.0" and (
            self.supersedes_study_digest is not None
            or self.selector_role_alias_policy is not None
        ):
            raise ValueError("study 1.0 cannot contain study 1.1 fields")
        selection_revision = (
            self.selection_baseline_policy,
            self.selection_abstain_policy,
            self.selection_operational_evidence_policy,
            self.candidate_semantic_policy,
            self.selection_whole_attempt_cost_ratio_max,
            self.selection_p95_latency_ratio_max,
            self.selection_max_retry_increase,
            self.selection_max_timeout_increase,
        )
        selection_row = next(
            row for row in self.matrix if row.stage is FormalStage.SELECTION
        )
        if self.schema_version == "1.2":
            if any(item is None for item in selection_revision):
                raise ValueError(
                    "study 1.2 requires baseline, abstention, semantic, and "
                    "operational selection policies"
                )
            if (
                selection_row.variant_count != 4
                or selection_row.target_trials
                != selection_row.task_count * selection_row.trials * 4
            ):
                raise ValueError(
                    "study 1.2 Selection must execute A0 plus three candidates"
                )
            if self.core_target_trial_count != 575:
                raise ValueError("study 1.2 core matrix must total 575 trials")
        else:
            if any(item is not None for item in selection_revision):
                raise ValueError("only study 1.2 can contain amended selection policy")
            if self.core_target_trial_count != 560:
                raise ValueError("legacy Banking study matrix must total 560 trials")
        return self


def study_digest_payload(plan: BankingStudyPlan) -> dict[str, Any]:
    payload = plan.model_dump(mode="json", exclude={"study_digest"})
    for key in set(payload) - plan.model_fields_set:
        payload.pop(key, None)
    return payload


def computed_study_digest(plan: BankingStudyPlan) -> str:
    return canonical_digest(study_digest_payload(plan))


def load_study_plan(path: Path) -> BankingStudyPlan:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read Banking study plan: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Banking study plan must be a YAML object")
    plan = BankingStudyPlan.model_validate(raw)
    computed = computed_study_digest(plan)
    if computed != plan.study_digest:
        raise ValueError(
            f"study plan digest mismatch: expected {plan.study_digest}, got {computed}"
        )
    return plan


# Backward-compatible import for R2 callers and retained artifacts.
BankingR2StudyPlan = BankingStudyPlan
