"""Pre-registered Banking R2 matrix and minimal publication ablations."""

from __future__ import annotations

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


class BankingR2StudyPlan(StrictModel):
    schema_version: Literal["1.0", "1.1"]
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
    matrix: list[StudyMatrixRow] = Field(min_length=6, max_length=6)
    core_target_trial_count: Literal[560]
    ablations: list[StudyAblation] = Field(min_length=4, max_length=4)
    statistics: StudyStatistics
    study_digest: Digest

    @model_validator(mode="after")
    def design_is_complete(self) -> BankingR2StudyPlan:
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
            raise ValueError("study matrix does not total 560 target trials")
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
        if self.schema_version == "1.1" and not version_1_1:
            raise ValueError("study 1.1 requires supersession and selector alias policy")
        if self.schema_version == "1.0" and (
            self.supersedes_study_digest is not None
            or self.selector_role_alias_policy is not None
        ):
            raise ValueError("study 1.0 cannot contain study 1.1 fields")
        return self


def study_digest_payload(plan: BankingR2StudyPlan) -> dict[str, Any]:
    payload = plan.model_dump(mode="json", exclude={"study_digest"})
    if plan.schema_version == "1.0":
        for key in set(payload) - plan.model_fields_set:
            payload.pop(key, None)
    return payload


def computed_study_digest(plan: BankingR2StudyPlan) -> str:
    return canonical_digest(study_digest_payload(plan))


def load_study_plan(path: Path) -> BankingR2StudyPlan:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read Banking R2 study plan: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Banking R2 study plan must be a YAML object")
    plan = BankingR2StudyPlan.model_validate(raw)
    computed = computed_study_digest(plan)
    if computed != plan.study_digest:
        raise ValueError(
            f"study plan digest mismatch: expected {plan.study_digest}, got {computed}"
        )
    return plan
