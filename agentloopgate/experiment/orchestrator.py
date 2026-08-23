"""End-to-end, resumable P0 experiment from A0 evidence to one governed decision."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from itertools import combinations
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import Field, model_validator

from agentloopgate.adapters import OutcomeDiagnostics, load_pilot_pricing
from agentloopgate.adapters.evidence import BenchmarkEvidenceStore
from agentloopgate.candidates import CandidateRegistry
from agentloopgate.contracts import (
    canonical_digest,
    canonical_json_bytes,
    file_digest,
    load_contract,
)
from agentloopgate.evaluation import EvaluationAuditor, EvaluationSummary
from agentloopgate.gates import (
    BaselineSelectionInput,
    CandidateSelectionInput,
    DualSelection,
    DualSelector,
    GateAssessment,
    GateEngine,
    GateOutcome,
    SelectionPolicy,
)
from agentloopgate.mutation import (
    CandidateChecker,
    TrustKernelSnapshot,
    freeze_trust_kernel,
    load_asset_manifest,
    load_mutation_policy,
)
from agentloopgate.reporting import DecisionReportBuilder
from agentloopgate.reporting.models import (
    CandidateCurvePoint,
    FailureFunnelPoint,
    PoolComparisonPoint,
    ReportData,
)
from agentloopgate.runtime.tau3_evidence import verified_task_attempt_events
from agentloopgate.schemas import (
    ArtifactId,
    CandidateRecord,
    CandidateStatus,
    DecisionValue,
    Digest,
    FailureType,
    GateName,
    NonEmpty,
    Pool,
    RunRecord,
)
from agentloopgate.schemas.models import StrictModel
from agentloopgate.snapshots import SnapshotManager
from agentloopgate.splits.models import PoolManifest
from agentloopgate.updaters import AheAdapter, AheExternalRunner

from .batch import FormalBatchArtifact, FormalBatchRunner, FormalBatchSpec, FormalStage
from .diagnosis_ablation import (
    DiagnosisDirectionAblationArtifact,
    build_diagnosis_direction_ablation,
)
from .diagnostics import FormalDiagnosisArtifact, diagnose_formal_records
from .ledger import CostStatus, ExperimentAttemptLedger, FormalCostAccounting
from .protocol import load_execution_protocol
from .service import FormalExperimentService, _code_revision, _under
from .statistics import (
    PublicationStatisticsArtifact,
    SelectorAblationArtifact,
    build_publication_statistics,
    build_selector_ablation,
)
from .study import BankingStudyPlan, load_study_plan

T = TypeVar("T")


class FormalWorkflowBlocked(RuntimeError):
    """The experiment retained valid progress but cannot honestly continue."""


class FormalSelectionArtifact(StrictModel):
    schema_version: Literal["1.0", "1.1"] = "1.0"
    inputs: list[CandidateSelectionInput] = Field(min_length=1)
    baseline: BaselineSelectionInput | None = None
    policy: SelectionPolicy | None = None
    selection: DualSelection
    selection_digest: Digest

    @model_validator(mode="after")
    def amended_selection_is_complete(self) -> FormalSelectionArtifact:
        if self.schema_version == "1.1":
            if self.baseline is None or self.policy is None:
                raise ValueError("selection 1.1 requires baseline and policy evidence")
            if self.selection.schema_version != "1.1":
                raise ValueError("selection artifact and decision versions differ")
        elif self.baseline is not None or self.policy is not None:
            raise ValueError("legacy selection cannot contain baseline-bound policy")
        return self


class FormalLineageArtifact(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    experiment_id: ArtifactId
    pilot_evidence_join_ids: list[ArtifactId] = Field(min_length=3)
    batch_ids: list[ArtifactId] = Field(min_length=1)
    candidate_ids: list[ArtifactId] = Field(min_length=3)
    snapshot_ids: list[ArtifactId] = Field(min_length=4)
    lineage_digest: Digest


class FormalDecisionArtifact(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    selector: Literal["native", "agentloopgate"]
    assessment: GateAssessment
    outcome: GateOutcome
    decision_digest: Digest


class FormalRoleAssignmentArtifact(StrictModel):
    """Bind logical study roles to physical snapshots without double-counting runs."""

    schema_version: Literal["1.0"] = "1.0"
    experiment_id: ArtifactId
    protocol_digest: Digest
    study_digest: Digest
    source_revision: str
    baseline_snapshot_id: ArtifactId
    updater_native_candidate_id: ArtifactId
    updater_native_snapshot_id: ArtifactId
    agentloopgate_candidate_id: ArtifactId
    agentloopgate_snapshot_id: ArtifactId
    selector_role_alias_policy: Literal[
        "reuse_identical_snapshot_evidence_and_report_null_contrast"
    ]
    role_alias: bool
    contrast_kind: Literal[
        "independent_selected_snapshots", "null_contrast_identical_snapshot"
    ]
    reused_evidence_roles: dict[Literal["agentloopgate"], Literal["updater_native"]]
    logical_core_trial_count: int = Field(ge=1)
    unique_executed_core_trial_count: int = Field(ge=1)
    reused_role_trial_count: int = Field(ge=0)
    role_assignment_digest: Digest

    @model_validator(mode="after")
    def counts_and_alias_are_consistent(self) -> FormalRoleAssignmentArtifact:
        if (
            self.unique_executed_core_trial_count + self.reused_role_trial_count
            != self.logical_core_trial_count
        ):
            raise ValueError("role-assignment trial counts do not reconcile")
        if self.role_alias != bool(self.reused_evidence_roles):
            raise ValueError("role alias and evidence-reuse mapping differ")
        expected = (
            "null_contrast_identical_snapshot"
            if self.role_alias
            else "independent_selected_snapshots"
        )
        if self.contrast_kind != expected:
            raise ValueError("role alias and contrast kind differ")
        return self


class FormalExperimentOutcome(StrictModel):
    schema_version: Literal["1.0", "1.1"] = "1.0"
    experiment_id: ArtifactId
    baseline_snapshot_id: ArtifactId
    candidate_ids: list[ArtifactId] = Field(min_length=3)
    candidate_snapshot_ids: list[ArtifactId] = Field(min_length=3)
    native_candidate_id: ArtifactId
    agentloopgate_candidate_id: ArtifactId
    native_decision: DecisionValue
    final_decision: DecisionValue
    external_rejection_count: int = Field(ge=0)
    held_or_rejected_candidate_count: int = Field(ge=0)
    asset_family_count: int = Field(ge=1)
    p0_requirements_met: bool
    lineage_digest: Digest
    role_assignment_digest: Digest | None = None
    statistics_digest: Digest | None = None
    selector_ablation_digest: Digest | None = None
    diagnosis_ablation_digest: Digest | None = None
    logical_core_trial_count: int | None = Field(default=None, ge=1)
    unique_executed_core_trial_count: int | None = Field(default=None, ge=1)
    reused_role_trial_count: int | None = Field(default=None, ge=0)
    report_digest: Digest
    report_file_digests: dict[str, Digest]
    outcome_digest: Digest

    @model_validator(mode="after")
    def versioned_analysis_is_complete(self) -> FormalExperimentOutcome:
        analysis = (
            self.role_assignment_digest,
            self.statistics_digest,
            self.selector_ablation_digest,
            self.diagnosis_ablation_digest,
            self.logical_core_trial_count,
            self.unique_executed_core_trial_count,
            self.reused_role_trial_count,
        )
        if self.schema_version == "1.1" and any(item is None for item in analysis):
            raise ValueError("versioned outcome requires role, statistics, and reuse evidence")
        if self.schema_version == "1.0" and any(item is not None for item in analysis):
            raise ValueError("legacy outcome cannot contain R2 analysis fields")
        if (
            self.logical_core_trial_count is not None
            and self.unique_executed_core_trial_count is not None
            and self.reused_role_trial_count is not None
            and self.unique_executed_core_trial_count
            + self.reused_role_trial_count
            != self.logical_core_trial_count
        ):
            raise ValueError("outcome logical/executed/reused trial counts do not reconcile")
        return self


class FormalSelectionHoldOutcome(StrictModel):
    """Normal terminal outcome when governance refuses to nominate a release candidate."""

    schema_version: Literal["1.0"] = "1.0"
    outcome_kind: Literal["selection_hold"] = "selection_hold"
    experiment_id: ArtifactId
    protocol_digest: Digest
    study_digest: Digest
    source_revision: NonEmpty
    baseline_snapshot_id: ArtifactId
    candidate_ids: list[ArtifactId] = Field(min_length=3)
    candidate_snapshot_ids: list[ArtifactId] = Field(min_length=3)
    native_candidate_id: ArtifactId
    agentloopgate_candidate_id: None = None
    final_decision: Literal[DecisionValue.HOLD] = DecisionValue.HOLD
    decision_reason: NonEmpty
    selection_digest: Digest
    lineage_digest: Digest
    batch_ids: list[ArtifactId] = Field(min_length=1)
    candidate_statuses: dict[ArtifactId, Literal["held"]]
    batch_model_cost_usd: Decimal = Field(ge=0)
    updater_model_cost_usd: Decimal = Field(ge=0)
    total_known_model_cost_usd: Decimal = Field(ge=0)
    cost_status: Literal["exact", "partial", "unavailable"]
    unresolved_updater_model_call_count: int = Field(ge=0)
    unknown_cost_scope: list[NonEmpty]
    cost_artifact_refs: list[NonEmpty] = Field(min_length=1)
    release_batch_count: Literal[0] = 0
    model_calls_after_selection: Literal[0] = 0
    report_digest: Digest
    report_file_digests: dict[NonEmpty, Digest] = Field(min_length=2)
    outcome_digest: Digest

    @model_validator(mode="after")
    def terminal_cost_and_candidates_are_consistent(self) -> FormalSelectionHoldOutcome:
        if (
            len(set(self.candidate_ids)) != len(self.candidate_ids)
            or len(set(self.candidate_snapshot_ids))
            != len(self.candidate_snapshot_ids)
            or len(set(self.batch_ids)) != len(self.batch_ids)
            or len(set(self.cost_artifact_refs)) != len(self.cost_artifact_refs)
        ):
            raise ValueError("Selection HOLD identities and references must be unique")
        if self.native_candidate_id not in self.candidate_ids:
            raise ValueError("Selection HOLD native candidate is outside the ladder")
        if self.total_known_model_cost_usd != (
            self.batch_model_cost_usd + self.updater_model_cost_usd
        ):
            raise ValueError("selection HOLD model costs do not reconcile")
        if set(self.candidate_statuses) != set(self.candidate_ids):
            raise ValueError("selection HOLD statuses do not cover every candidate")
        if len(self.candidate_snapshot_ids) != len(self.candidate_ids):
            raise ValueError("selection HOLD candidate/snapshot populations differ")
        if self.cost_status == "exact" and (
            self.unresolved_updater_model_call_count or self.unknown_cost_scope
        ):
            raise ValueError("exact Selection HOLD cost cannot have unknown scope")
        if self.cost_status != "exact" and not self.unknown_cost_scope:
            raise ValueError("non-exact Selection HOLD cost must disclose unknown scope")
        return self


class FormalExperimentOrchestrator:
    """Credentialed orchestration; all expensive stages are independently resumable."""

    def __init__(self, project_root: Path, *, config_path: Path) -> None:
        self.root = project_root.resolve()
        self.config_path = config_path
        self.service = FormalExperimentService(self.root, config_path=config_path)
        self.config = self.service.config
        self.store = BenchmarkEvidenceStore(self.root)
        self.experiment_root = (
            self.root / "runs/experiments" / self.config.experiment_id
        )

    def ensure_evaluation_baseline(
        self,
        *,
        command: list[str] | None = None,
    ) -> str:
        """Create or verify a non-active evaluation baseline with a ledger event."""

        return self._record_no_model_operation(
            operation="ensure_evaluation_baseline",
            action=self.service.ensure_baseline,
            artifact_paths=lambda snapshot_id: [
                self.root / "snapshots" / snapshot_id / "manifest.json"
            ],
            command=command,
        )

    def run(self) -> FormalExperimentOutcome | FormalSelectionHoldOutcome:
        existing = self.experiment_root / "outcome.json"
        existing_hold = self.experiment_root / "selection_hold_outcome.json"
        if existing.is_file() and existing_hold.is_file():
            raise FormalWorkflowBlocked(
                "experiment has conflicting release and Selection-HOLD outcomes"
            )
        if existing_hold.exists():
            return self._record_no_model_operation(
                operation="verify_existing_selection_hold",
                action=lambda: self._load_verified_selection_hold(existing_hold),
                artifact_paths=lambda outcome: [
                    existing_hold,
                    *[
                        self.root / relative
                        for relative in outcome.report_file_digests
                    ],
                ],
            )
        if existing.exists():
            return self._record_no_model_operation(
                operation="verify_existing_outcome",
                action=lambda: self._load_verified_outcome(existing),
                artifact_paths=lambda _outcome: [existing],
            )
        baseline_id = self.ensure_evaluation_baseline()

        baseline = SnapshotManager(self.root).verify(baseline_id)
        update_source = self._completed_stage(
            FormalStage.UPDATE_SOURCE,
            snapshot_id=baseline_id,
        )
        diagnosis = self._record_no_model_operation(
            operation="diagnosis",
            action=lambda: self._diagnose(update_source),
            artifact_paths=lambda _artifact: [self.experiment_root / "diagnosis.json"],
        )
        candidates = self._propose(baseline_id, diagnosis)
        candidate_snapshots = self._record_no_model_operation(
            operation="materialize_candidate_snapshots",
            action=lambda: self._materialize(candidates),
            artifact_paths=lambda snapshot_ids: [
                self.root / "snapshots" / snapshot_id / "manifest.json"
                for snapshot_id in snapshot_ids
            ],
        )

        update_check: dict[str, FormalBatchArtifact] = {
            baseline_id: self._completed_stage(
                FormalStage.UPDATE_CHECK,
                snapshot_id=baseline_id,
            )
        }
        for candidate, snapshot_id in zip(candidates, candidate_snapshots, strict=True):
            update_check[snapshot_id] = self._completed_stage(
                FormalStage.UPDATE_CHECK,
                snapshot_id=snapshot_id,
            )
            self._advance(
                candidate.candidate_id,
                CandidateStatus.UPDATE_EVALUATED,
                sources=[_batch_ref(self.config.experiment_id, update_check[snapshot_id])],
            )

        selection_batches: dict[str, FormalBatchArtifact] = {}
        if self.config.schema_version == "1.2":
            selection_batches[baseline_id] = self._completed_stage(
                FormalStage.SELECTION,
                snapshot_id=baseline_id,
            )
        for candidate, snapshot_id in zip(candidates, candidate_snapshots, strict=True):
            selection_batches[snapshot_id] = self._completed_stage(
                FormalStage.SELECTION,
                snapshot_id=snapshot_id,
            )
            self._advance(
                candidate.candidate_id,
                CandidateStatus.SELECTION_EVALUATED,
                sources=[
                    _batch_ref(self.config.experiment_id, selection_batches[snapshot_id])
                ],
            )
        selection = self._record_no_model_operation(
            operation="dual_selector",
            action=lambda: self._select(
                baseline_id, candidates, candidate_snapshots, selection_batches
            ),
            artifact_paths=lambda _artifact: [self.experiment_root / "selection.json"],
        )
        if selection.selection.agentloopgate_decision == "HOLD":
            lineage = self._record_no_model_operation(
                operation="seal_selection_hold_lineage",
                action=lambda: self._lineage(
                    candidates,
                    candidate_snapshots,
                    [
                        update_source,
                        *update_check.values(),
                        *selection_batches.values(),
                    ],
                ),
                artifact_paths=lambda _artifact: [
                    self.experiment_root / "lineage.json"
                ],
            )
            for candidate in candidates:
                self._advance(
                    candidate.candidate_id,
                    CandidateStatus.HELD,
                    sources=[
                        f"runs/experiments/{self.config.experiment_id}/selection.json",
                        f"runs/experiments/{self.config.experiment_id}/lineage.json",
                    ],
                )
            return self._record_no_model_operation(
                operation="seal_selection_hold_outcome",
                action=lambda: self._seal_selection_hold_outcome(
                    path=existing_hold,
                    baseline_snapshot_id=baseline_id,
                    candidates=candidates,
                    candidate_snapshot_ids=candidate_snapshots,
                    batches=[
                        update_source,
                        *update_check.values(),
                        *selection_batches.values(),
                    ],
                    selection=selection,
                    lineage=lineage,
                ),
                artifact_paths=lambda outcome: [
                    existing_hold,
                    *[
                        self.root / relative
                        for relative in outcome.report_file_digests
                    ],
                ],
            )
        diagnosis_ablation = (
            self._record_no_model_operation(
                operation="diagnosis_direction_ablation",
                action=lambda: self._diagnosis_direction_ablation(
                    diagnosis,
                    candidates,
                    candidate_snapshots,
                    update_check,
                    selection_batches,
                    selection,
                ),
                artifact_paths=lambda _artifact: [
                    self._research_ablation_path("diagnosis_direction_v2.json")
                ],
            )
            if self.config.schema_version in {"1.1", "1.2"}
            else None
        )
        by_candidate = {
            candidate.candidate_id: snapshot_id
            for candidate, snapshot_id in zip(candidates, candidate_snapshots, strict=True)
        }
        role_assignment = (
            self._record_no_model_operation(
                operation="assign_study_roles",
                action=lambda: self._role_assignment(selection, by_candidate),
                artifact_paths=lambda _artifact: [
                    self.experiment_root / "role_assignment.json"
                ],
            )
            if self.config.schema_version in {"1.1", "1.2"}
            else None
        )
        release_snapshot_ids = [
            baseline_id,
            *dict.fromkeys(
                [
                    by_candidate[selection.selection.native_candidate_id],
                    by_candidate[selection.selection.agentloopgate_candidate_id],
                ]
            ),
        ]
        release = {
            snapshot_id: {
                stage: self._completed_stage(stage, snapshot_id=snapshot_id)
                for stage in (
                    FormalStage.RELEASE_ID,
                    FormalStage.RELEASE_OOD,
                    FormalStage.REPLAY,
                )
            }
            for snapshot_id in release_snapshot_ids
        }
        for candidate_id in {
            selection.selection.native_candidate_id,
            selection.selection.agentloopgate_candidate_id,
        }:
            snapshot_id = by_candidate[candidate_id]
            self._advance(
                candidate_id,
                CandidateStatus.RELEASE_EVALUATED,
                sources=[
                    _batch_ref(self.config.experiment_id, item)
                    for item in release[snapshot_id].values()
                ],
            )
        statistics = None
        selector_ablation = None
        if role_assignment is not None:
            statistics, selector_ablation = self._record_no_model_operation(
                operation="publication_statistics_and_selector_ablation",
                action=lambda: self._publication_analysis(
                    selection,
                    role_assignment,
                    release,
                ),
                artifact_paths=lambda _artifacts: [
                    self.experiment_root / "statistics.json",
                    self._research_ablation_path("selector_v2.json"),
                ],
            )
        lineage = self._record_no_model_operation(
            operation="seal_lineage",
            action=lambda: self._lineage(
                candidates,
                candidate_snapshots,
                [
                    update_source,
                    *update_check.values(),
                    *selection_batches.values(),
                    *(batch for stages in release.values() for batch in stages.values()),
                ],
            ),
            artifact_paths=lambda _artifact: [self.experiment_root / "lineage.json"],
        )
        decisions: dict[str, FormalDecisionArtifact] = {}
        for selector, candidate_id in (
            ("native", selection.selection.native_candidate_id),
            ("agentloopgate", selection.selection.agentloopgate_candidate_id),
        ):
            snapshot_id = by_candidate[candidate_id]
            decisions[selector] = self._record_no_model_operation(
                operation=f"gate_decision_{selector}",
                action=partial(
                    self._decide_selected,
                    selector,
                    candidate_id,
                    snapshot_id,
                    baseline_id,
                    release,
                    lineage,
                ),
                artifact_paths=lambda _artifact, selector=selector: [
                    self.experiment_root / "decisions" / f"{selector}.json"
                ],
            )
        unique_decisions = {
            item.outcome.record.candidate_id: item for item in decisions.values()
        }
        for artifact in unique_decisions.values():
            target = {
                DecisionValue.SHIP_RECOMMENDED: CandidateStatus.SHIP_RECOMMENDED,
                DecisionValue.HOLD: CandidateStatus.HELD,
                DecisionValue.REJECT: CandidateStatus.REJECTED,
            }[artifact.outcome.record.decision]
            self._advance(
                artifact.outcome.record.candidate_id,
                target,
                sources=[
                    f"runs/experiments/{self.config.experiment_id}/decisions/"
                    f"{artifact.selector}.json"
                ],
            )

        governed = decisions["agentloopgate"]
        report = self._record_no_model_operation(
            operation="build_decision_report",
            action=lambda: self._report(
                governed.outcome,
                diagnosis,
                baseline_id,
                candidates,
                candidate_snapshots,
                release,
                selection,
            ),
            artifact_paths=lambda artifact: [
                artifact.decision_json,
                artifact.decision_markdown,
                *artifact.chart_paths,
            ],
        )
        rejected_count = len(
            list((self.root / "runs/updaters/ahe/rejected").glob("*/rejection.json"))
        )
        held_or_rejected = sum(
            self._registry().load(candidate.candidate_id).status
            in {CandidateStatus.HELD, CandidateStatus.REJECTED}
            for candidate in candidates
        )
        family_count = len({family for item in candidates for family in item.asset_families})
        p0_met = (
            len(candidates) >= self.config.candidate_count
            and family_count >= self.config.min_asset_families
            and rejected_count + held_or_rejected
            >= self.config.min_rejected_or_held_candidates
        )
        payload = {
            "schema_version": "1.1" if role_assignment is not None else "1.0",
            "experiment_id": self.config.experiment_id,
            "baseline_snapshot_id": baseline.snapshot_id,
            "candidate_ids": [item.candidate_id for item in candidates],
            "candidate_snapshot_ids": candidate_snapshots,
            "native_candidate_id": selection.selection.native_candidate_id,
            "agentloopgate_candidate_id": selection.selection.agentloopgate_candidate_id,
            "native_decision": decisions["native"].outcome.record.decision,
            "final_decision": governed.outcome.record.decision,
            "external_rejection_count": rejected_count,
            "held_or_rejected_candidate_count": held_or_rejected,
            "asset_family_count": family_count,
            "p0_requirements_met": p0_met,
            "lineage_digest": lineage.lineage_digest,
            "report_digest": report.report_digest,
            "report_file_digests": {
                path.relative_to(self.root).as_posix(): file_digest(path)
                for path in [
                    report.decision_json,
                    report.decision_markdown,
                    *report.chart_paths,
                ]
            },
        }
        if role_assignment is not None:
            payload.update(
                {
                    "role_assignment_digest": (
                        role_assignment.role_assignment_digest
                    ),
                    "statistics_digest": statistics.statistics_digest,
                    "selector_ablation_digest": selector_ablation.artifact_digest,
                    "diagnosis_ablation_digest": (
                        diagnosis_ablation.artifact_digest
                    ),
                    "logical_core_trial_count": (
                        role_assignment.logical_core_trial_count
                    ),
                    "unique_executed_core_trial_count": (
                        role_assignment.unique_executed_core_trial_count
                    ),
                    "reused_role_trial_count": (
                        role_assignment.reused_role_trial_count
                    ),
                }
            )
        outcome = FormalExperimentOutcome.model_validate(
            {**payload, "outcome_digest": canonical_digest(payload)}
        )
        return self._record_no_model_operation(
            operation="seal_formal_outcome",
            action=lambda: self._seal_outcome(existing, outcome),
            artifact_paths=lambda _artifact: [existing],
        )

    def _seal_outcome(
        self,
        path: Path,
        outcome: FormalExperimentOutcome,
    ) -> FormalExperimentOutcome:
        self._write_once(path, outcome.model_dump(mode="json"))
        return outcome

    def _seal_selection_hold_outcome(
        self,
        *,
        path: Path,
        baseline_snapshot_id: str,
        candidates: list[CandidateRecord],
        candidate_snapshot_ids: list[str],
        batches: list[FormalBatchArtifact],
        selection: FormalSelectionArtifact,
        lineage: FormalLineageArtifact,
    ) -> FormalSelectionHoldOutcome:
        if (
            selection.selection.agentloopgate_decision != "HOLD"
            or selection.selection.agentloopgate_candidate_id is not None
        ):
            raise FormalWorkflowBlocked(
                "Selection HOLD outcome requires an abstaining selector decision"
            )
        if any(
            batch.stage
            in {FormalStage.RELEASE_ID, FormalStage.RELEASE_OOD, FormalStage.REPLAY}
            for batch in batches
        ):
            raise FormalWorkflowBlocked(
                "Selection HOLD outcome cannot contain a Release or Replay batch"
            )
        protocol, study = self._versioned_protocol_and_study()
        batch_cost, batch_refs = self._exact_batch_model_cost(batches)
        (
            updater_cost,
            updater_status,
            updater_unresolved,
            updater_unknown,
            updater_refs,
        ) = self._updater_model_cost()
        total_cost = batch_cost + updater_cost
        report_root = self.experiment_root / "reports"
        report_json = report_root / "selection_hold.json"
        report_markdown = report_root / "selection_hold.md"
        report_payload = _selection_hold_report_payload(
            experiment_id=self.config.experiment_id,
            baseline_snapshot_id=baseline_snapshot_id,
            selection=selection,
            lineage_digest=lineage.lineage_digest,
            batch_cost=batch_cost,
            updater_cost=updater_cost,
            total_cost=total_cost,
            cost_status=updater_status,
            updater_unresolved=updater_unresolved,
            updater_unknown=updater_unknown,
        )
        report_digest = canonical_digest(report_payload)
        self._write_once(
            report_json,
            {**report_payload, "report_digest": report_digest},
        )
        self._write_text_once(
            report_markdown,
            _selection_hold_markdown(
                experiment_id=self.config.experiment_id,
                baseline_snapshot_id=baseline_snapshot_id,
                selection=selection,
                batch_cost=batch_cost,
                updater_cost=updater_cost,
                total_cost=total_cost,
                cost_status=updater_status,
                updater_unknown=updater_unknown,
                lineage_digest=lineage.lineage_digest,
            ),
        )
        report_file_digests = {
            report_json.relative_to(self.root).as_posix(): file_digest(report_json),
            report_markdown.relative_to(self.root).as_posix(): file_digest(
                report_markdown
            ),
        }
        payload = {
            "schema_version": "1.0",
            "outcome_kind": "selection_hold",
            "experiment_id": self.config.experiment_id,
            "protocol_digest": protocol.protocol_digest,
            "study_digest": study.study_digest,
            "source_revision": SnapshotManager(self.root)
            .verify(baseline_snapshot_id)
            .code_revision,
            "baseline_snapshot_id": baseline_snapshot_id,
            "candidate_ids": [candidate.candidate_id for candidate in candidates],
            "candidate_snapshot_ids": candidate_snapshot_ids,
            "native_candidate_id": selection.selection.native_candidate_id,
            "agentloopgate_candidate_id": None,
            "final_decision": DecisionValue.HOLD,
            "decision_reason": selection.selection.decision_reason,
            "selection_digest": selection.selection_digest,
            "lineage_digest": lineage.lineage_digest,
            "batch_ids": sorted(batch.batch_id for batch in batches),
            "candidate_statuses": {
                candidate.candidate_id: "held" for candidate in candidates
            },
            "batch_model_cost_usd": batch_cost,
            "updater_model_cost_usd": updater_cost,
            "total_known_model_cost_usd": total_cost,
            "cost_status": updater_status,
            "unresolved_updater_model_call_count": updater_unresolved,
            "unknown_cost_scope": updater_unknown,
            "cost_artifact_refs": [*batch_refs, *updater_refs],
            "release_batch_count": 0,
            "model_calls_after_selection": 0,
            "report_digest": report_digest,
            "report_file_digests": report_file_digests,
        }
        outcome = FormalSelectionHoldOutcome.model_validate(
            {**payload, "outcome_digest": canonical_digest(payload)}
        )
        self._write_once(path, outcome.model_dump(mode="json"))
        return outcome

    def _versioned_protocol_and_study(self):
        if (
            self.config.execution_protocol_config is None
            or self.config.study_plan_config is None
        ):
            raise FormalWorkflowBlocked(
                "Selection HOLD requires frozen Protocol and Study bindings"
            )
        protocol = load_execution_protocol(
            _under(self.root, Path(self.config.execution_protocol_config))
        )
        study = load_study_plan(
            _under(self.root, Path(self.config.study_plan_config))
        )
        if study.protocol_digest != protocol.protocol_digest:
            raise FormalWorkflowBlocked(
                "Selection HOLD Protocol and Study bindings differ"
            )
        return protocol, study

    def _exact_batch_model_cost(
        self,
        batches: list[FormalBatchArtifact],
    ) -> tuple[Decimal, list[str]]:
        total = Decimal(0)
        refs: list[str] = []
        for batch in batches:
            path = self.experiment_root / "costs" / f"{batch.batch_id}.json"
            try:
                cost = FormalCostAccounting.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise FormalWorkflowBlocked(
                    f"Selection HOLD cost is unavailable for {batch.batch_id}"
                ) from exc
            if (
                cost.accounting_status is not CostStatus.EXACT
                or cost.total_cost_lower_bound_usd is None
                or cost.unresolved_agent_call_count
                or (cost.unresolved_user_call_count or 0)
            ):
                raise FormalWorkflowBlocked(
                    f"Selection HOLD batch cost is not exact for {batch.batch_id}"
                )
            total += cost.total_cost_lower_bound_usd
            refs.append(path.relative_to(self.root).as_posix())
        return total, refs

    def _updater_model_cost(
        self,
    ) -> tuple[Decimal, str, int, list[str], list[str]]:
        total = Decimal(0)
        unresolved = 0
        unknown: list[str] = []
        refs: list[str] = []
        matched = 0
        attempts = self.root / "runs/updaters/ahe/attempts"
        for directory in sorted(attempts.glob("AHEATT_*")):
            started_path = directory / "started.json"
            terminal_path = directory / "terminal.json"
            try:
                started = json.loads(started_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if started.get("experiment_id") != self.config.experiment_id:
                continue
            matched += 1
            try:
                _verify_embedded_digest(started, "attempt_digest")
            except ValueError as exc:
                raise FormalWorkflowBlocked(
                    f"updater start evidence is corrupt: {directory.name}"
                ) from exc
            if (
                started.get("attempt_id") != directory.name
                or started.get("state") != "started"
            ):
                raise FormalWorkflowBlocked(
                    f"updater start identity is invalid: {directory.name}"
                )
            refs.append(started_path.relative_to(self.root).as_posix())
            if not terminal_path.is_file():
                unknown.append(f"unterminated_updater_attempt:{directory.name}")
                unresolved += 1
                continue
            try:
                terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
                _verify_embedded_digest(terminal, "attempt_digest")
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                raise FormalWorkflowBlocked(
                    f"updater attempt evidence is corrupt: {directory.name}"
                ) from exc
            if terminal.get("attempt_id") != directory.name:
                raise FormalWorkflowBlocked(
                    f"updater terminal identity is invalid: {directory.name}"
                )
            refs.append(terminal_path.relative_to(self.root).as_posix())
            known = terminal.get("known_cost_usd")
            if known is not None:
                try:
                    amount = Decimal(str(known))
                except (ArithmeticError, ValueError) as exc:
                    raise FormalWorkflowBlocked(
                        f"updater known cost is invalid: {directory.name}"
                    ) from exc
                if not amount.is_finite() or amount < 0:
                    raise FormalWorkflowBlocked(
                        f"updater known cost is invalid: {directory.name}"
                    )
                total += amount
            try:
                attempt_unresolved = int(
                    terminal.get("unresolved_model_call_count", 0)
                )
            except (TypeError, ValueError) as exc:
                raise FormalWorkflowBlocked(
                    f"updater unresolved-call count is invalid: {directory.name}"
                ) from exc
            if attempt_unresolved < 0:
                raise FormalWorkflowBlocked(
                    f"updater unresolved-call count is invalid: {directory.name}"
                )
            unresolved += attempt_unresolved
            status = terminal.get("cost_status")
            if status not in {"exact", "partial", "unavailable"}:
                raise FormalWorkflowBlocked(
                    f"updater cost status is invalid: {directory.name}"
                )
            if status == "exact" and (known is None or attempt_unresolved):
                raise FormalWorkflowBlocked(
                    f"updater exact cost is incomplete: {directory.name}"
                )
            if status != "exact" or attempt_unresolved:
                unknown.append(f"non_exact_updater_attempt:{directory.name}")
        if not matched:
            return (
                Decimal(0),
                "unavailable",
                0,
                ["no_experiment_bound_updater_attempt_evidence"],
                refs,
            )
        return (
            total,
            "partial" if unknown else "exact",
            unresolved,
            unknown,
            refs,
        )

    def _record_no_model_operation(
        self,
        *,
        operation: str,
        action: Callable[[], T],
        artifact_paths: Callable[[T], list[Path]],
        command: list[str] | None = None,
    ) -> T:
        """Fail closed around deterministic workflow steps and hash every output."""

        if self.config.schema_version not in {"1.1", "1.2"}:
            return action()
        if (
            self.config.execution_protocol_config is None
            or self.config.study_plan_config is None
        ):
            raise FormalWorkflowBlocked(
                "versioned no-model operation requires protocol and study bindings"
            )
        protocol = load_execution_protocol(
            _under(self.root, Path(self.config.execution_protocol_config))
        )
        study = load_study_plan(
            _under(self.root, Path(self.config.study_plan_config))
        )
        if study.protocol_digest != protocol.protocol_digest:
            raise FormalWorkflowBlocked(
                "versioned no-model operation protocol and study bindings differ"
            )
        revision = _code_revision(self.root)
        if revision is None:
            raise FormalWorkflowBlocked(
                "versioned no-model operation requires a source revision"
            )
        ledger = ExperimentAttemptLedger(self.root, self.config.experiment_id)
        handle = ledger.begin(
            operation=operation,
            protocol_digest=protocol.protocol_digest,
            study_digest=study.study_digest,
            source_revision=revision,
            command=command
            or [
                "agentloopgate",
                "experiment",
                "run",
                "--config",
                str(self.config_path),
            ],
            recovery_action=(
                "preserve the immutable terminal event and outputs; repair only "
                "implementation code, then resume the same frozen workflow"
            ),
        )
        try:
            result = action()
            paths = artifact_paths(result)
            missing = [path for path in paths if not path.is_file()]
            if missing:
                raise FormalWorkflowBlocked(
                    "no-model operation did not seal expected artifacts: "
                    + ", ".join(path.relative_to(self.root).as_posix() for path in missing)
                )
            artifacts = {
                path.relative_to(self.root).as_posix(): file_digest(path)
                for path in paths
            }
            ledger.complete_no_model_operation(
                handle,
                exit_code=0,
                result_artifacts=artifacts,
                counters={"model_calls": 0, "artifact_count": len(artifacts)},
            )
            return result
        except BaseException as exc:
            ledger.fail(
                handle,
                exc,
                cost_status=CostStatus.NOT_APPLICABLE,
                known_cost_usd=0,
                recovery_action=(
                    "preserve the immutable failed event and any outputs; repair only "
                    "implementation code, then resume the same frozen workflow"
                ),
            )
            raise

    def _completed_stage(
        self,
        stage: FormalStage,
        *,
        snapshot_id: str,
    ) -> FormalBatchArtifact:
        artifact = self.service.run_stage(stage, snapshot_id=snapshot_id).artifact
        if artifact.disposition == "hold":
            raise FormalWorkflowBlocked(
                f"formal batch {artifact.batch_id} sealed HOLD: "
                + ", ".join(artifact.hold_reasons)
            )
        return artifact

    def _research_ablation_path(self, filename: str) -> Path:
        root = Path(
            self.config.research_artifact_root
            or "artifacts/research/banking_r2"
        )
        return _under(self.root, root / "ablations" / filename)

    def _diagnose(self, batch: FormalBatchArtifact) -> FormalDiagnosisArtifact:
        records = [self._record(run_id) for run_id in batch.tau_run_ids]
        diagnostics = [self._diagnostic(run_id) for run_id in batch.tau_run_ids]
        split = self.service.splits.verify()
        path = _under(
            self.root,
            Path(split.pools[Pool.UPDATE_SOURCE].manifest),
        )
        manifest = PoolManifest.model_validate_json(path.read_text(encoding="utf-8"))
        artifact = diagnose_formal_records(
            batch_id=batch.batch_id,
            records=records,
            diagnostics=diagnostics,
            tasks=manifest.tasks,
        )
        self._write_once(
            self.experiment_root / "diagnosis.json",
            artifact.model_dump(mode="json"),
        )
        for item in artifact.ranked_bundles:
            self._write_once(
                self.experiment_root
                / "failure_bundles"
                / f"{item.bundle.failure_bundle_id}.json",
                item.bundle.model_dump(mode="json"),
            )
        return artifact

    def _propose(
        self,
        baseline_id: str,
        diagnosis: FormalDiagnosisArtifact,
    ) -> list[CandidateRecord]:
        if diagnosis.unresolved_evaluation_incident_run_ids:
            raise FormalWorkflowBlocked(
                "candidate generation is blocked by unresolved evaluation incidents: "
                + ", ".join(diagnosis.unresolved_evaluation_incident_run_ids)
            )
        eligible_bundles = [
            item.bundle
            for item in diagnosis.ranked_bundles
            if item.bundle.failure_type
            not in {FailureType.INFRA_FAILURE, FailureType.SPEC_OR_EVALUATOR_ISSUE}
        ]
        if not eligible_bundles:
            raise FormalWorkflowBlocked(
                "Update-Source produced no actionable, non-infrastructure FailureBundle"
            )
        if self.config.schema_version == "1.2":
            self.service.verify_updater_generation_authorization(
                snapshot_id=baseline_id
            )
        manifest = load_asset_manifest(self.root / "configs/harness_assets.yaml")
        policy = load_mutation_policy(self.root / "configs/mutation_policy.yaml")
        registry = self._registry()
        baseline = SnapshotManager(self.root).verify(baseline_id)
        pricing = load_pilot_pricing(
            _under(self.root, Path(self.config.pricing_config))
        )
        protocol = self.service._protocol(
            objective_digest=baseline.objective_digest,
            split_digest=baseline.split_digest,
            pricing=pricing,
        )
        if protocol is None:
            raise FormalWorkflowBlocked("AHE formal execution requires a frozen protocol")
        if self.config.study_plan_config is None:
            raise FormalWorkflowBlocked("AHE formal execution requires a frozen study plan")
        study = load_study_plan(
            _under(self.root, Path(self.config.study_plan_config))
        )
        updater = AheAdapter(
            self.root,
            registry=registry,
            experiment_id=self.config.experiment_id,
            protocol_digest=protocol.protocol_digest,
            study_digest=study.study_digest,
            source_revision=baseline.code_revision,
            runner=AheExternalRunner(
                _under(self.root, Path(self.config.ahe_checkout)),
                project_root=self.root,
                timeout_seconds=protocol.updater_timeout_seconds or 3600,
                max_iterations=protocol.updater_max_iterations or 80,
                max_output_tokens=protocol.updater_max_output_tokens or 8000,
                temperature=protocol.updater_temperature or Decimal("0.3"),
                max_retries=(
                    protocol.updater_max_retries
                    if protocol.updater_max_retries is not None
                    else 0
                ),
                retry_delay_seconds=protocol.updater_retry_delay_seconds or Decimal(1),
                input_price_per_million=pricing.input_cache_miss,
                cache_read_price_per_million=pricing.input_cache_hit,
                output_price_per_million=pricing.output,
                network_route_policy=(protocol.network_route_policy or "inherit"),
            ),
        )
        counts: Counter[str] = Counter()
        ordered: list[CandidateRecord] = []
        seen: set[str] = set()
        if protocol.updater_proposal_budget is None:
            raise FormalWorkflowBlocked("frozen updater proposal budget is unavailable")
        for proposal_index in range(protocol.updater_proposal_budget):
            bundle = eligible_bundles[proposal_index % len(eligible_bundles)]
            counts[bundle.failure_bundle_id] += 1
            records = updater.propose(
                baseline,
                bundle,
                manifest,
                policy,
                counts[bundle.failure_bundle_id],
                created_at=datetime.now(UTC),
            )
            for record in records:
                if record.candidate_id not in seen:
                    seen.add(record.candidate_id)
                    ordered.append(record)
            executable = [
                item
                for item in ordered
                if item.status
                not in {
                    CandidateStatus.HELD,
                    CandidateStatus.REJECTED,
                    CandidateStatus.ROLLED_BACK,
                }
            ]
            families = {family for item in executable for family in item.asset_families}
            if (
                len(executable) >= self.config.candidate_count
                and len(families) >= self.config.min_asset_families
            ):
                selected = _diverse_subset(
                    executable,
                    count=self.config.candidate_count,
                    min_families=self.config.min_asset_families,
                )
                self._write_proposal_plan(selected)
                return selected
        raise FormalWorkflowBlocked(
            "AHE exhausted the six-proposal P0 budget without producing the required "
            f"{self.config.candidate_count} executable candidates across "
            f"{self.config.min_asset_families} asset families"
        )

    def _write_proposal_plan(self, candidates: list[CandidateRecord]) -> None:
        payload = {
            "schema_version": "1.0",
            "signal_kind": "ahe_emission_order",
            "candidate_ids": [item.candidate_id for item in candidates],
            "signal_refs": [
                f"runs/updaters/ahe/{item.candidate_id}/run_metadata.json"
                for item in candidates
            ],
        }
        self._write_once(
            self.experiment_root / "proposal_plan.json",
            {**payload, "plan_digest": canonical_digest(payload)},
        )

    def _materialize(self, candidates: list[CandidateRecord]) -> list[str]:
        manager = SnapshotManager(self.root)
        snapshots = []
        for candidate in candidates:
            snapshot = manager.create_child(
                candidate,
                model_id=f"{self.config.provider}/{self.config.agent_model}",
                code_revision=manager.verify(candidate.parent_snapshot_id).code_revision,
                runtime_host="deepseek_harness",
                runtime_version="deepseek-harness@0.1.0-rc.8",
                created_at=candidate.created_at,
            )
            snapshots.append(snapshot.snapshot_id)
        return snapshots

    def _select(
        self,
        baseline_snapshot_id: str,
        candidates: list[CandidateRecord],
        snapshot_ids: list[str],
        batches: dict[str, FormalBatchArtifact],
    ) -> FormalSelectionArtifact:
        amended = self.config.schema_version == "1.2"
        inputs = [
            CandidateSelectionInput(
                candidate_id=candidate.candidate_id,
                native_score=None,
                native_rank=index,
                native_signal_ref=(
                    f"runs/experiments/{self.config.experiment_id}/proposal_plan.json"
                ),
                evaluation_complete=batches[snapshot_id].summary.integrity_complete,
                stable_success_task_count=(
                    batches[snapshot_id].summary.stable_success_task_count
                ),
                critical_violations=batches[snapshot_id].summary.critical_violation_count,
                mean_cost=batches[snapshot_id].summary.mean_cost,
                p50_latency_ms=batches[snapshot_id].summary.p50_latency_ms,
                **(
                    {
                        "stable_task_outcomes": (
                            batches[snapshot_id].summary.stable_task_outcomes
                        ),
                        **self._selection_operational_evidence(
                            batches[snapshot_id]
                        ),
                    }
                    if amended
                    else {}
                ),
            )
            for index, (candidate, snapshot_id) in enumerate(
                zip(candidates, snapshot_ids, strict=True),
                start=1,
            )
        ]
        baseline = None
        policy = None
        if amended:
            baseline_batch = batches.get(baseline_snapshot_id)
            if baseline_batch is None:
                raise FormalWorkflowBlocked(
                    "amended Selection requires an A0 batch on the same frozen pool"
                )
            baseline = BaselineSelectionInput(
                snapshot_id=baseline_snapshot_id,
                evaluation_complete=baseline_batch.summary.integrity_complete,
                stable_success_task_count=(
                    baseline_batch.summary.stable_success_task_count
                ),
                stable_task_outcomes=baseline_batch.summary.stable_task_outcomes,
                critical_violations=(
                    baseline_batch.summary.critical_violation_count
                ),
                mean_cost=baseline_batch.summary.mean_cost,
                p50_latency_ms=baseline_batch.summary.p50_latency_ms,
                **self._selection_operational_evidence(baseline_batch),
            )
            if self.config.study_plan_config is None:
                raise FormalWorkflowBlocked(
                    "amended Selection requires a frozen study policy"
                )
            study = load_study_plan(
                _under(self.root, Path(self.config.study_plan_config))
            )
            if study.schema_version != "1.2":
                raise FormalWorkflowBlocked(
                    "formal config 1.2 requires a study 1.2 Selection amendment"
                )
            policy = SelectionPolicy(
                whole_attempt_cost_ratio_max=(
                    study.selection_whole_attempt_cost_ratio_max
                ),
                p95_latency_ratio_max=study.selection_p95_latency_ratio_max,
                max_retry_increase=study.selection_max_retry_increase,
                max_timeout_increase=study.selection_max_timeout_increase,
            )
        selected = DualSelector().select(inputs, baseline=baseline, policy=policy)
        payload = {
            "schema_version": "1.1" if amended else "1.0",
            "inputs": inputs,
            "selection": selected,
        }
        if amended:
            payload.update({"baseline": baseline, "policy": policy})
        artifact = FormalSelectionArtifact.model_validate(
            {**payload, "selection_digest": canonical_digest(payload)}
        )
        self._write_once(
            self.experiment_root / "selection.json",
            artifact.model_dump(mode="json"),
        )
        return artifact

    def _selection_operational_evidence(
        self,
        batch: FormalBatchArtifact,
    ) -> dict[str, object]:
        cost_path = self.experiment_root / "costs" / f"{batch.batch_id}.json"
        attempts_path = (
            self.experiment_root / "task_attempts" / f"{batch.batch_id}.jsonl"
        )
        try:
            cost = FormalCostAccounting.model_validate_json(
                cost_path.read_text(encoding="utf-8")
            )
            events = verified_task_attempt_events(attempts_path)
        except (OSError, ValueError) as exc:
            raise FormalWorkflowBlocked(
                f"Selection operational evidence is unavailable for {batch.batch_id}"
            ) from exc
        if (
            cost.accounting_status is not CostStatus.EXACT
            or cost.total_cost_lower_bound_usd is None
            or cost.unresolved_agent_call_count
            or (cost.unresolved_user_call_count or 0)
        ):
            raise FormalWorkflowBlocked(
                f"Selection whole-attempt cost is not exact for {batch.batch_id}"
            )
        started = [event for event in events if event.get("state") == "started"]
        expected_positions = len(batch.summary.stable_task_outcomes) * batch.summary.trials
        retry_count = len(started) - expected_positions
        if retry_count < 0:
            raise FormalWorkflowBlocked(
                f"Selection task-attempt evidence is incomplete for {batch.batch_id}"
            )
        terminal = [
            event
            for event in events
            if event.get("state") in {"completed", "failed"}
        ]
        timeout_count = sum(
            "timeout" in str(event.get("termination_reason", "")).lower()
            or "timeout" in str(event.get("error_type", "")).lower()
            for event in terminal
        )
        latencies = sorted(
            Decimal(self._record(run_id).latency_ms) for run_id in batch.tau_run_ids
        )
        if not latencies:
            raise FormalWorkflowBlocked(
                f"Selection latency evidence is empty for {batch.batch_id}"
            )
        return {
            "whole_attempt_cost_usd": cost.total_cost_lower_bound_usd,
            "task_attempt_count": len(started),
            "retry_count": retry_count,
            "timeout_count": timeout_count,
            "p95_latency_ms": _nearest_rank(latencies, 95),
            "max_latency_ms": latencies[-1],
            "operational_evidence_refs": [
                f"runs/experiments/{self.config.experiment_id}/batches/"
                f"{batch.batch_id}.json",
                f"runs/experiments/{self.config.experiment_id}/costs/"
                f"{batch.batch_id}.json",
                f"runs/experiments/{self.config.experiment_id}/task_attempts/"
                f"{batch.batch_id}.jsonl",
            ],
        }

    def _lineage(
        self,
        candidates: list[CandidateRecord],
        snapshots: list[str],
        batches: list[FormalBatchArtifact],
    ) -> FormalLineageArtifact:
        joins: list[str] = []
        pilot_tasks: set[str] = set()
        for path in sorted((self.root / "runs/evidence_joins").glob("PEJ_*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            tau = self._record(payload["tau_run_id"])
            if tau.pool is Pool.PILOT:
                joins.append(path.stem)
                pilot_tasks.add(tau.task_id)
        if not 3 <= len(pilot_tasks) <= 7:
            raise FormalWorkflowBlocked("verified 3-7 task Pilot lineage is unavailable")
        payload = {
            "schema_version": "1.0",
            "experiment_id": self.config.experiment_id,
            "pilot_evidence_join_ids": joins,
            "batch_ids": sorted({item.batch_id for item in batches}),
            "candidate_ids": [item.candidate_id for item in candidates],
            "snapshot_ids": [self.config.baseline_snapshot_id, *snapshots],
        }
        artifact = FormalLineageArtifact.model_validate(
            {**payload, "lineage_digest": canonical_digest(payload)}
        )
        self._write_once(
            self.experiment_root / "lineage.json",
            artifact.model_dump(mode="json"),
        )
        return artifact

    def _role_assignment(
        self,
        selection: FormalSelectionArtifact,
        by_candidate: dict[str, str],
    ) -> FormalRoleAssignmentArtifact:
        if self.config.study_plan_config is None:
            raise FormalWorkflowBlocked(
                "versioned role assignment requires a frozen study"
            )
        study = load_study_plan(
            _under(self.root, Path(self.config.study_plan_config))
        )
        revision = _code_revision(self.root)
        if revision is None:
            raise FormalWorkflowBlocked(
                "versioned role assignment requires a source revision"
            )
        baseline = SnapshotManager(self.root).verify(self.config.baseline_snapshot_id)
        if baseline.code_revision != revision:
            raise FormalWorkflowBlocked(
                "source changed after the evaluation baseline was frozen"
            )
        artifact = _build_role_assignment(
            experiment_id=self.config.experiment_id,
            protocol_digest=study.protocol_digest,
            study=study,
            source_revision=revision,
            baseline_snapshot_id=self.config.baseline_snapshot_id,
            updater_native_candidate_id=selection.selection.native_candidate_id,
            updater_native_snapshot_id=by_candidate[
                selection.selection.native_candidate_id
            ],
            agentloopgate_candidate_id=(
                selection.selection.agentloopgate_candidate_id
            ),
            agentloopgate_snapshot_id=by_candidate[
                selection.selection.agentloopgate_candidate_id
            ],
        )
        self._write_once(
            self.experiment_root / "role_assignment.json",
            artifact.model_dump(mode="json"),
        )
        return artifact

    def _publication_analysis(
        self,
        selection: FormalSelectionArtifact,
        roles: FormalRoleAssignmentArtifact,
        release: dict[str, dict[FormalStage, FormalBatchArtifact]],
    ) -> tuple[PublicationStatisticsArtifact, SelectorAblationArtifact]:
        if self.config.study_plan_config is None:
            raise FormalWorkflowBlocked(
                "versioned publication analysis requires a frozen study"
            )
        study = load_study_plan(
            _under(self.root, Path(self.config.study_plan_config))
        )
        if (
            study.study_digest != roles.study_digest
            or study.protocol_digest != roles.protocol_digest
        ):
            raise FormalWorkflowBlocked(
                "role assignment is not bound to the frozen study"
            )
        statistics = build_publication_statistics(
            experiment_id=self.config.experiment_id,
            study=study,
            source_revision=roles.source_revision,
            role_alias=roles.role_alias,
            release=release,
            baseline_snapshot_id=roles.baseline_snapshot_id,
            updater_native_snapshot_id=roles.updater_native_snapshot_id,
            agentloopgate_snapshot_id=roles.agentloopgate_snapshot_id,
        )
        selector = build_selector_ablation(
            experiment_id=self.config.experiment_id,
            study=study,
            source_revision=roles.source_revision,
            selection_digest=selection.selection_digest,
            updater_native_candidate_id=roles.updater_native_candidate_id,
            updater_native_snapshot_id=roles.updater_native_snapshot_id,
            agentloopgate_candidate_id=roles.agentloopgate_candidate_id,
            agentloopgate_snapshot_id=roles.agentloopgate_snapshot_id,
            release=release,
        )
        self._write_once(
            self.experiment_root / "statistics.json",
            statistics.model_dump(mode="json"),
        )
        self._write_once(
            self._research_ablation_path("selector_v2.json"),
            selector.model_dump(mode="json"),
        )
        return statistics, selector

    def _diagnosis_direction_ablation(
        self,
        diagnosis: FormalDiagnosisArtifact,
        candidates: list[CandidateRecord],
        candidate_snapshots: list[str],
        update_check: dict[str, FormalBatchArtifact],
        selection_batches: dict[str, FormalBatchArtifact],
        selection: FormalSelectionArtifact,
    ) -> DiagnosisDirectionAblationArtifact:
        if self.config.study_plan_config is None:
            raise FormalWorkflowBlocked("diagnosis ablation requires a frozen study")
        study = load_study_plan(
            _under(self.root, Path(self.config.study_plan_config))
        )
        revision = _code_revision(self.root)
        if revision is None:
            raise FormalWorkflowBlocked("diagnosis ablation requires a source revision")
        artifact = build_diagnosis_direction_ablation(
            experiment_id=self.config.experiment_id,
            study=study,
            source_revision=revision,
            diagnosis=diagnosis,
            candidates=candidates,
            candidate_snapshots=candidate_snapshots,
            baseline_update_check=update_check[self.config.baseline_snapshot_id],
            candidate_update_check=update_check,
            selection_batches=selection_batches,
            selection=selection,
        )
        self._write_once(
            self._research_ablation_path("diagnosis_direction_v2.json"),
            artifact.model_dump(mode="json"),
        )
        return artifact

    def _decide(
        self,
        *,
        selector: Literal["native", "agentloopgate"],
        candidate: CandidateRecord,
        baseline: dict[FormalStage, FormalBatchArtifact],
        candidate_batches: dict[FormalStage, FormalBatchArtifact],
        lineage: FormalLineageArtifact,
    ) -> FormalDecisionArtifact:
        comparisons = {
            stage: EvaluationAuditor.compare(
                baseline[stage].summary,
                candidate_batches[stage].summary,
            )
            for stage in (
                FormalStage.RELEASE_ID,
                FormalStage.RELEASE_OOD,
                FormalStage.REPLAY,
            )
        }
        baseline_cost, baseline_latency = self._runtime_metrics(list(baseline.values()))
        candidate_cost, candidate_latency = self._runtime_metrics(
            list(candidate_batches.values())
        )
        release_critical = sum(
            candidate_batches[stage].summary.critical_violation_count
            for stage in (FormalStage.RELEASE_ID, FormalStage.RELEASE_OOD)
        )
        def batch_ref(stage: FormalStage) -> str:
            return (
                f"runs/experiments/{self.config.experiment_id}/batches/"
                f"{candidate_batches[stage].batch_id}.json"
            )
        assessment = GateAssessment(
            schema_version="1.0",
            candidate_id=candidate.candidate_id,
            baseline_snapshot_id=candidate.parent_snapshot_id,
            evaluation_integrity_complete=all(
                item.summary.integrity_complete
                for item in [*baseline.values(), *candidate_batches.values()]
            ),
            leakage_hits=0,
            mutates_trust_kernel=False,
            risk_tier=candidate.risk_tier,
            release_critical_violations=release_critical,
            id_stable_task_net=comparisons[FormalStage.RELEASE_ID].stable_task_net,
            ood_stable_task_net=comparisons[FormalStage.RELEASE_OOD].stable_task_net,
            replay_stable_task_net=comparisons[FormalStage.REPLAY].stable_task_net,
            catastrophic_regressions=sum(
                item.catastrophic_regressions for item in comparisons.values()
            ),
            reliability_complete=all(
                item.summary.trials == self.config.release_trials
                and item.summary.integrity_complete
                for item in [*baseline.values(), *candidate_batches.values()]
            ),
            reliability_trials=self.config.release_trials,
            stable_success_required=self.config.stable_success_required,
            baseline_mean_cost=baseline_cost,
            candidate_mean_cost=candidate_cost,
            baseline_p50_latency_ms=baseline_latency,
            candidate_p50_latency_ms=candidate_latency,
            evidence_refs={
                GateName.EVALUATION_INTEGRITY: (
                    f"runs/experiments/{self.config.experiment_id}/lineage.json"
                ),
                GateName.LEAKAGE: f"candidates/{candidate.candidate_id}/check.json",
                GateName.CRITICAL_VIOLATION: batch_ref(FormalStage.RELEASE_ID),
                GateName.ID_EFFECT: batch_ref(FormalStage.RELEASE_ID),
                GateName.OOD_NONINFERIORITY: batch_ref(FormalStage.RELEASE_OOD),
                GateName.REPLAY: batch_ref(FormalStage.REPLAY),
                GateName.RELIABILITY: batch_ref(FormalStage.RELEASE_ID),
                GateName.COST: batch_ref(FormalStage.RELEASE_ID),
                GateName.LATENCY: batch_ref(FormalStage.RELEASE_ID),
            },
        )
        outcome = GateEngine(load_contract(self.root / "configs/objective_contract.yaml")).decide(
            assessment,
            created_at=candidate.created_at,
        )
        payload = {
            "schema_version": "1.0",
            "selector": selector,
            "assessment": assessment,
            "outcome": outcome,
        }
        artifact = FormalDecisionArtifact.model_validate(
            {**payload, "decision_digest": canonical_digest(payload)}
        )
        self._write_once(
            self.experiment_root / "decisions" / f"{selector}.json",
            artifact.model_dump(mode="json"),
        )
        return artifact

    def _decide_selected(
        self,
        selector: Literal["native", "agentloopgate"],
        candidate_id: str,
        snapshot_id: str,
        baseline_id: str,
        release: dict[str, dict[FormalStage, FormalBatchArtifact]],
        lineage: FormalLineageArtifact,
    ) -> FormalDecisionArtifact:
        return self._decide(
            selector=selector,
            candidate=self._registry().load(candidate_id),
            baseline=release[baseline_id],
            candidate_batches=release[snapshot_id],
            lineage=lineage,
        )

    def _report(
        self,
        outcome: GateOutcome,
        diagnosis: FormalDiagnosisArtifact,
        baseline_id: str,
        candidates: list[CandidateRecord],
        snapshots: list[str],
        release: dict[str, dict[FormalStage, FormalBatchArtifact]],
        selection: FormalSelectionArtifact,
    ):
        by_candidate = {
            candidate.candidate_id: snapshot_id
            for candidate, snapshot_id in zip(candidates, snapshots, strict=True)
        }
        role_snapshots = [
            ("baseline", baseline_id),
            (
                "updater_native",
                by_candidate[selection.selection.native_candidate_id],
            ),
            (
                "agentloopgate",
                by_candidate[selection.selection.agentloopgate_candidate_id],
            ),
        ]
        candidate_curve = [
            _curve_point(
                role,
                release[snapshot_id][FormalStage.RELEASE_ID].summary,
            )
            for role, snapshot_id in role_snapshots
        ]
        counts = Counter(
            _funnel_stage(item.bundle.failure_type)
            for item in diagnosis.ranked_bundles
        )
        funnel = [
            FailureFunnelPoint(stage=stage, count=counts[stage])
            for stage in ("retrieval", "policy", "tool", "correct_state")
        ]
        pool_comparison = [
            PoolComparisonPoint(
                candidate_id=role,
                pool=batch.summary.pool,
                stable_tasks=batch.summary.stable_success_task_count,
            )
            for role, snapshot_id in role_snapshots
            for stages in [release[snapshot_id]]
            for batch in stages.values()
        ]
        return DecisionReportBuilder(self.root).build(
            ReportData(
                schema_version="1.0",
                experiment_id=self.config.experiment_id,
                decision=outcome,
                candidate_curve=candidate_curve,
                failure_funnel=funnel,
                pool_comparison=pool_comparison,
            )
        )

    def _advance(
        self,
        candidate_id: str,
        target: CandidateStatus,
        *,
        sources: list[str],
    ) -> None:
        lifecycle_payload = {
            "schema_version": "1.0",
            "candidate_id": candidate_id,
            "target_status": target.value,
            "sources": sorted(sources),
        }
        lifecycle = (
            self.experiment_root
            / "lifecycle"
            / candidate_id
            / f"{target.value}.json"
        )
        self._write_once(
            lifecycle,
            {
                **lifecycle_payload,
                "evidence_digest": canonical_digest(lifecycle_payload),
            },
        )
        registry = self._registry()
        current = registry.load(candidate_id)
        if current.status is target:
            return
        progress = [
            CandidateStatus.CHECKED,
            CandidateStatus.UPDATE_EVALUATED,
            CandidateStatus.SELECTION_EVALUATED,
            CandidateStatus.RELEASE_EVALUATED,
        ]
        if current.status is CandidateStatus.HELD and target in progress:
            held_lifecycle = (
                self.experiment_root
                / "lifecycle"
                / candidate_id
                / f"{CandidateStatus.HELD.value}.json"
            )
            try:
                sealed = json.loads(held_lifecycle.read_text(encoding="utf-8"))
                _verify_embedded_digest(sealed, "evidence_digest")
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                raise FormalWorkflowBlocked(
                    "terminally held candidate lacks resumable lifecycle evidence"
                ) from exc
            if (
                sealed.get("candidate_id") != candidate_id
                or sealed.get("target_status") != CandidateStatus.HELD.value
            ):
                raise FormalWorkflowBlocked(
                    "terminally held candidate lifecycle identity is invalid"
                )
            return
        if current.status in progress and target in progress:
            if progress.index(current.status) > progress.index(target):
                return
            if progress.index(target) != progress.index(current.status) + 1:
                raise FormalWorkflowBlocked("candidate lifecycle evidence has a stage gap")
        registry.transition(
            candidate_id,
            target,
            evidence_refs=[lifecycle.relative_to(self.root).as_posix()],
        )

    def _registry(self) -> CandidateRegistry:
        policy = load_mutation_policy(self.root / "configs/mutation_policy.yaml")
        trust_path = self.experiment_root / "trust_kernel.json"
        if trust_path.exists():
            try:
                trust = TrustKernelSnapshot.model_validate_json(
                    trust_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise FormalWorkflowBlocked(
                    "frozen experiment trust-kernel artifact is corrupt"
                ) from exc
        else:
            trust = freeze_trust_kernel(self.root, policy)
            self._write_once(trust_path, trust.model_dump(mode="json"))
        return CandidateRegistry(
            self.root,
            CandidateChecker(
                self.root,
                load_asset_manifest(self.root / "configs/harness_assets.yaml"),
                policy,
                trust,
            ),
        )

    def _runtime_metrics(
        self,
        batches: list[FormalBatchArtifact],
    ) -> tuple[Decimal, Decimal]:
        if any(
            batch.summary.schema_version != "1.1"
            or batch.summary.cost_source != "direct_task_attempt_model_calls"
            or batch.summary.cost_status != "exact"
            for batch in batches
        ):
            raise FormalWorkflowBlocked(
                "formal decision requires exact direct Agent+User batch cost"
            )
        records = [
            self._record(run_id)
            for batch in batches
            for run_id in batch.tau_run_ids
        ]
        if not records:
            return Decimal(0), Decimal(0)
        scored_count = sum(batch.summary.valid_run_count for batch in batches)
        if not scored_count:
            raise FormalWorkflowBlocked("formal decision requires scored valid runs")
        mean_cost = sum(
            (
                batch.summary.mean_cost * batch.summary.valid_run_count
                for batch in batches
            ),
            Decimal(0),
        ) / scored_count
        latencies = sorted(Decimal(item.latency_ms) for item in records)
        middle = len(latencies) // 2
        median = (
            latencies[middle]
            if len(latencies) % 2
            else (latencies[middle - 1] + latencies[middle]) / 2
        )
        return mean_cost, median

    def _record(self, run_id: str) -> RunRecord:
        return RunRecord.model_validate_json(
            self.store.path_for("normalized", run_id).read_text(encoding="utf-8")
        )

    def _diagnostic(self, run_id: str) -> OutcomeDiagnostics:
        return OutcomeDiagnostics.model_validate_json(
            self.store.path_for("diagnostics", run_id).read_text(encoding="utf-8")
        )

    def _load_verified_selection_hold(
        self,
        path: Path,
    ) -> FormalSelectionHoldOutcome:
        self.service.ensure_baseline(require_active=False)
        try:
            outcome = FormalSelectionHoldOutcome.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise FormalWorkflowBlocked(
                "formal Selection-HOLD outcome is unavailable"
            ) from exc
        payload = outcome.model_dump(mode="python", exclude={"outcome_digest"})
        if canonical_digest(payload) != outcome.outcome_digest:
            raise FormalWorkflowBlocked("formal Selection-HOLD outcome digest mismatch")
        protocol, study = self._versioned_protocol_and_study()
        baseline = SnapshotManager(self.root).verify(outcome.baseline_snapshot_id)
        if (
            outcome.protocol_digest != protocol.protocol_digest
            or outcome.study_digest != study.study_digest
            or outcome.source_revision != baseline.code_revision
        ):
            raise FormalWorkflowBlocked(
                "formal Selection-HOLD identity conflicts with frozen inputs"
            )
        selection_path = self.experiment_root / "selection.json"
        lineage_path = self.experiment_root / "lineage.json"
        try:
            selection = FormalSelectionArtifact.model_validate_json(
                selection_path.read_text(encoding="utf-8")
            )
            lineage = FormalLineageArtifact.model_validate_json(
                lineage_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise FormalWorkflowBlocked(
                "formal Selection-HOLD selection or lineage is unavailable"
            ) from exc
        if (
            canonical_digest(
                selection.model_dump(mode="python", exclude={"selection_digest"})
            )
            != selection.selection_digest
            or selection.selection_digest != outcome.selection_digest
            or selection.selection.agentloopgate_decision != "HOLD"
            or selection.selection.agentloopgate_candidate_id is not None
            or selection.selection.native_candidate_id != outcome.native_candidate_id
            or sorted(item.candidate_id for item in selection.inputs)
            != sorted(outcome.candidate_ids)
            or selection.baseline is None
            or selection.baseline.snapshot_id != outcome.baseline_snapshot_id
        ):
            raise FormalWorkflowBlocked(
                "formal Selection-HOLD selector evidence conflicts with outcome"
            )
        if (
            canonical_digest(
                lineage.model_dump(mode="python", exclude={"lineage_digest"})
            )
            != lineage.lineage_digest
            or lineage.lineage_digest != outcome.lineage_digest
            or sorted(lineage.batch_ids) != sorted(outcome.batch_ids)
            or sorted(lineage.candidate_ids) != sorted(outcome.candidate_ids)
            or sorted(lineage.snapshot_ids)
            != sorted(
                [outcome.baseline_snapshot_id, *outcome.candidate_snapshot_ids]
            )
        ):
            raise FormalWorkflowBlocked(
                "formal Selection-HOLD lineage conflicts with outcome"
            )
        batches: list[FormalBatchArtifact] = []
        for batch_id in outcome.batch_ids:
            batch_path = self.experiment_root / "batches" / f"{batch_id}.json"
            try:
                batch = FormalBatchArtifact.model_validate_json(
                    batch_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise FormalWorkflowBlocked(
                    f"formal Selection-HOLD batch is unavailable: {batch_id}"
                ) from exc
            if batch.stage in {
                FormalStage.RELEASE_ID,
                FormalStage.RELEASE_OOD,
                FormalStage.REPLAY,
            }:
                raise FormalWorkflowBlocked(
                    "formal Selection-HOLD lineage contains post-Selection evidence"
                )
            verified = FormalBatchRunner(self.root, _NoExecute()).run(batch.spec)
            if verified.artifact.batch_id != batch_id or not verified.resumed:
                raise FormalWorkflowBlocked(
                    "formal Selection-HOLD batch did not verify as immutable"
                )
            batches.append(batch)
        for candidate_id, snapshot_id in zip(
            outcome.candidate_ids,
            outcome.candidate_snapshot_ids,
            strict=True,
        ):
            SnapshotManager(self.root).verify(snapshot_id)
            if self._registry().load(candidate_id).status is not CandidateStatus.HELD:
                raise FormalWorkflowBlocked(
                    f"Selection-HOLD candidate is not terminally held: {candidate_id}"
                )
        batch_cost, batch_refs = self._exact_batch_model_cost(batches)
        (
            updater_cost,
            updater_status,
            updater_unresolved,
            updater_unknown,
            updater_refs,
        ) = self._updater_model_cost()
        if (
            batch_cost != outcome.batch_model_cost_usd
            or updater_cost != outcome.updater_model_cost_usd
            or batch_cost + updater_cost != outcome.total_known_model_cost_usd
            or updater_status != outcome.cost_status
            or updater_unresolved != outcome.unresolved_updater_model_call_count
            or updater_unknown != outcome.unknown_cost_scope
            or sorted([*batch_refs, *updater_refs])
            != sorted(outcome.cost_artifact_refs)
        ):
            raise FormalWorkflowBlocked(
                "formal Selection-HOLD cost evidence conflicts with outcome"
            )
        release_batches = []
        for batch_path in sorted((self.experiment_root / "batches").glob("B_*.json")):
            try:
                batch = FormalBatchArtifact.model_validate_json(
                    batch_path.read_text(encoding="utf-8")
                )
            except ValueError as exc:
                raise FormalWorkflowBlocked(
                    f"formal batch is corrupt: {batch_path.stem}"
                ) from exc
            if batch.stage in {
                FormalStage.RELEASE_ID,
                FormalStage.RELEASE_OOD,
                FormalStage.REPLAY,
            }:
                release_batches.append(batch.batch_id)
        if release_batches:
            raise FormalWorkflowBlocked(
                "Selection-HOLD outcome falsely claims zero Release batches: "
                + ", ".join(release_batches)
            )
        expected_report_paths = {
            (self.experiment_root / "reports/selection_hold.json")
            .relative_to(self.root)
            .as_posix(),
            (self.experiment_root / "reports/selection_hold.md")
            .relative_to(self.root)
            .as_posix(),
        }
        if set(outcome.report_file_digests) != expected_report_paths:
            raise FormalWorkflowBlocked(
                "formal Selection-HOLD report references are incomplete"
            )
        for relative, expected_digest in outcome.report_file_digests.items():
            report_path = _under(self.root, Path(relative))
            if not report_path.is_file() or file_digest(report_path) != expected_digest:
                raise FormalWorkflowBlocked(
                    f"formal Selection-HOLD report drifted: {relative}"
                )
        report_json = self.experiment_root / "reports/selection_hold.json"
        try:
            report = json.loads(report_json.read_text(encoding="utf-8"))
            declared = report.pop("report_digest")
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            raise FormalWorkflowBlocked(
                "formal Selection-HOLD report is unavailable"
            ) from exc
        expected_report = _selection_hold_report_payload(
            experiment_id=self.config.experiment_id,
            baseline_snapshot_id=outcome.baseline_snapshot_id,
            selection=selection,
            lineage_digest=lineage.lineage_digest,
            batch_cost=batch_cost,
            updater_cost=updater_cost,
            total_cost=batch_cost + updater_cost,
            cost_status=updater_status,
            updater_unresolved=updater_unresolved,
            updater_unknown=updater_unknown,
        )
        if (
            report != json.loads(canonical_json_bytes(expected_report))
            or canonical_digest(report) != declared
            or declared != outcome.report_digest
        ):
            raise FormalWorkflowBlocked("formal Selection-HOLD report digest mismatch")
        markdown_path = self.experiment_root / "reports/selection_hold.md"
        expected_markdown = _selection_hold_markdown(
            experiment_id=self.config.experiment_id,
            baseline_snapshot_id=outcome.baseline_snapshot_id,
            selection=selection,
            batch_cost=batch_cost,
            updater_cost=updater_cost,
            total_cost=batch_cost + updater_cost,
            cost_status=updater_status,
            updater_unknown=updater_unknown,
            lineage_digest=lineage.lineage_digest,
        )
        try:
            actual_markdown = markdown_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise FormalWorkflowBlocked(
                "formal Selection-HOLD Markdown report is unavailable"
            ) from exc
        if actual_markdown != expected_markdown:
            raise FormalWorkflowBlocked(
                "formal Selection-HOLD Markdown report conflicts with evidence"
            )
        return outcome

    def _load_verified_outcome(self, path: Path) -> FormalExperimentOutcome:
        self.service.ensure_baseline(require_active=False)
        outcome = FormalExperimentOutcome.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        payload = outcome.model_dump(mode="python", exclude={"outcome_digest"})
        if outcome.schema_version == "1.0":
            payload = {
                key: value
                for key, value in payload.items()
                if key
                not in {
                    "role_assignment_digest",
                    "statistics_digest",
                    "selector_ablation_digest",
                    "diagnosis_ablation_digest",
                    "logical_core_trial_count",
                    "unique_executed_core_trial_count",
                    "reused_role_trial_count",
                }
            }
        if canonical_digest(payload) != outcome.outcome_digest:
            raise FormalWorkflowBlocked("formal experiment outcome digest mismatch")
        lineage_path = self.experiment_root / "lineage.json"
        try:
            lineage = FormalLineageArtifact.model_validate_json(
                lineage_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise FormalWorkflowBlocked("formal experiment lineage is unavailable") from exc
        lineage_payload = lineage.model_dump(
            mode="python",
            exclude={"lineage_digest"},
        )
        if (
            canonical_digest(lineage_payload) != lineage.lineage_digest
            or lineage.lineage_digest != outcome.lineage_digest
        ):
            raise FormalWorkflowBlocked("formal experiment lineage digest mismatch")
        for batch_id in lineage.batch_ids:
            batch_path = self.experiment_root / "batches" / f"{batch_id}.json"
            try:
                batch = FormalBatchArtifact.model_validate_json(
                    batch_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise FormalWorkflowBlocked(
                    f"formal batch is unavailable: {batch_id}"
                ) from exc
            verified = FormalBatchRunner(self.root, _NoExecute()).run(batch.spec)
            if verified.artifact.batch_id != batch_id or not verified.resumed:
                raise FormalWorkflowBlocked("formal batch replay did not resume exactly")
        for snapshot_id in outcome.candidate_snapshot_ids:
            SnapshotManager(self.root).verify(snapshot_id)
        decisions = {
            selector: self._load_decision(selector)
            for selector in ("native", "agentloopgate")
        }
        if (
            decisions["native"].outcome.record.decision != outcome.native_decision
            or decisions["agentloopgate"].outcome.record.decision
            != outcome.final_decision
        ):
            raise FormalWorkflowBlocked("formal decision artifacts conflict with outcome")
        if outcome.role_assignment_digest is not None:
            try:
                roles = FormalRoleAssignmentArtifact.model_validate_json(
                    (self.experiment_root / "role_assignment.json").read_text(
                        encoding="utf-8"
                    )
                )
            except (OSError, ValueError) as exc:
                raise FormalWorkflowBlocked(
                    "formal role-assignment artifact is unavailable"
                ) from exc
            role_payload = roles.model_dump(
                mode="python", exclude={"role_assignment_digest"}
            )
            if (
                canonical_digest(role_payload) != roles.role_assignment_digest
                or roles.role_assignment_digest != outcome.role_assignment_digest
                or roles.logical_core_trial_count
                != outcome.logical_core_trial_count
                or roles.unique_executed_core_trial_count
                != outcome.unique_executed_core_trial_count
                or roles.reused_role_trial_count != outcome.reused_role_trial_count
            ):
                raise FormalWorkflowBlocked(
                    "formal role-assignment artifact conflicts with outcome"
                )
            try:
                statistics = PublicationStatisticsArtifact.model_validate_json(
                    (self.experiment_root / "statistics.json").read_text(
                        encoding="utf-8"
                    )
                )
                selector = SelectorAblationArtifact.model_validate_json(
                    self._research_ablation_path("selector_v2.json").read_text(
                        encoding="utf-8"
                    )
                )
                diagnosis_ablation = (
                    DiagnosisDirectionAblationArtifact.model_validate_json(
                        self._research_ablation_path(
                            "diagnosis_direction_v2.json"
                        ).read_text(encoding="utf-8")
                    )
                )
            except (OSError, ValueError) as exc:
                raise FormalWorkflowBlocked(
                    "formal publication statistics or selector ablation is unavailable"
                ) from exc
            statistics_payload = statistics.model_dump(
                mode="python", exclude={"statistics_digest"}
            )
            selector_payload = selector.model_dump(
                mode="python", exclude={"artifact_digest"}
            )
            if (
                canonical_digest(statistics_payload) != statistics.statistics_digest
                or canonical_digest(selector_payload) != selector.artifact_digest
                or statistics.statistics_digest != outcome.statistics_digest
                or selector.artifact_digest != outcome.selector_ablation_digest
                or diagnosis_ablation.artifact_digest
                != outcome.diagnosis_ablation_digest
                or canonical_digest(
                    diagnosis_ablation.model_dump(
                        mode="python", exclude={"artifact_digest"}
                    )
                )
                != diagnosis_ablation.artifact_digest
            ):
                raise FormalWorkflowBlocked(
                    "formal publication statistics conflict with outcome"
                )
        for relative, expected in outcome.report_file_digests.items():
            report_file = self.store.resolve_artifact_uri(f"artifact:{relative}")
            if not report_file.is_file() or file_digest(report_file) != expected:
                raise FormalWorkflowBlocked(f"formal report file drifted: {relative}")
        return outcome

    def _load_decision(
        self,
        selector: Literal["native", "agentloopgate"],
    ) -> FormalDecisionArtifact:
        path = self.experiment_root / "decisions" / f"{selector}.json"
        try:
            artifact = FormalDecisionArtifact.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise FormalWorkflowBlocked(
                f"formal {selector} decision is unavailable"
            ) from exc
        payload = artifact.model_dump(mode="python", exclude={"decision_digest"})
        if canonical_digest(payload) != artifact.decision_digest:
            raise FormalWorkflowBlocked(f"formal {selector} decision digest mismatch")
        return artifact

    @staticmethod
    def _write_once(path: Path, payload: object) -> None:
        encoded = canonical_json_bytes(payload) + b"\n"
        if path.exists():
            try:
                existing = canonical_json_bytes(
                    json.loads(path.read_text(encoding="utf-8"))
                ) + b"\n"
            except (OSError, json.JSONDecodeError) as exc:
                raise FormalWorkflowBlocked(
                    f"existing workflow artifact is corrupt: {path}"
                ) from exc
            if existing != encoded:
                raise FormalWorkflowBlocked(f"workflow artifact conflict: {path}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)

    @staticmethod
    def _write_text_once(path: Path, content: str) -> None:
        encoded = content.encode("utf-8")
        if path.exists():
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise FormalWorkflowBlocked(
                    f"existing workflow report is unreadable: {path}"
                ) from exc
            if existing != encoded:
                raise FormalWorkflowBlocked(f"workflow report conflict: {path}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)


def _curve_point(label: str, summary: EvaluationSummary) -> CandidateCurvePoint:
    pass_1 = (
        Decimal(summary.pass_1_numerator) / summary.pass_1_denominator
        if summary.pass_1_denominator
        else Decimal(0)
    )
    pass_k = (
        Decimal(summary.stable_success_task_count) / summary.expected_task_count
        if summary.expected_task_count
        else Decimal(0)
    )
    return CandidateCurvePoint(
        label=label,
        pass_1=pass_1,
        pass_k=pass_k,
        mean_cost=summary.mean_cost,
    )


def _build_role_assignment(
    *,
    experiment_id: str,
    protocol_digest: str,
    study: BankingStudyPlan,
    source_revision: str,
    baseline_snapshot_id: str,
    updater_native_candidate_id: str,
    updater_native_snapshot_id: str,
    agentloopgate_candidate_id: str,
    agentloopgate_snapshot_id: str,
) -> FormalRoleAssignmentArtifact:
    release_stages = {
        FormalStage.RELEASE_ID,
        FormalStage.RELEASE_OOD,
        FormalStage.REPLAY,
    }
    release_rows = [row for row in study.matrix if row.stage in release_stages]
    if len(release_rows) != 3 or any(row.variant_count != 3 for row in release_rows):
        raise ValueError(
            "versioned role assignment requires three logical release roles"
        )
    trials_per_physical_snapshot = sum(
        row.task_count * row.trials for row in release_rows
    )
    logical_release_trials = sum(row.target_trials for row in release_rows)
    nonrelease_trials = study.core_target_trial_count - logical_release_trials
    role_alias = updater_native_snapshot_id == agentloopgate_snapshot_id
    physical_release_snapshot_count = 1 + len(
        {updater_native_snapshot_id, agentloopgate_snapshot_id}
    )
    unique_executed = (
        nonrelease_trials
        + physical_release_snapshot_count * trials_per_physical_snapshot
    )
    reused = study.core_target_trial_count - unique_executed
    expected_reused = trials_per_physical_snapshot if role_alias else 0
    if reused != expected_reused:
        raise ValueError("role reuse count conflicts with the frozen matrix")
    if study.selector_role_alias_policy is None:
        raise ValueError("versioned role assignment requires an alias policy")
    payload = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "protocol_digest": protocol_digest,
        "study_digest": study.study_digest,
        "source_revision": source_revision,
        "baseline_snapshot_id": baseline_snapshot_id,
        "updater_native_candidate_id": updater_native_candidate_id,
        "updater_native_snapshot_id": updater_native_snapshot_id,
        "agentloopgate_candidate_id": agentloopgate_candidate_id,
        "agentloopgate_snapshot_id": agentloopgate_snapshot_id,
        "selector_role_alias_policy": study.selector_role_alias_policy,
        "role_alias": role_alias,
        "contrast_kind": (
            "null_contrast_identical_snapshot"
            if role_alias
            else "independent_selected_snapshots"
        ),
        "reused_evidence_roles": (
            {"agentloopgate": "updater_native"} if role_alias else {}
        ),
        "logical_core_trial_count": study.core_target_trial_count,
        "unique_executed_core_trial_count": unique_executed,
        "reused_role_trial_count": reused,
    }
    return FormalRoleAssignmentArtifact.model_validate(
        {**payload, "role_assignment_digest": canonical_digest(payload)}
    )


def _nearest_rank(values: list[Decimal], percentile: int) -> Decimal:
    if not values or not 1 <= percentile <= 100:
        raise ValueError("nearest-rank percentile requires values and a 1-100 rank")
    rank = (len(values) * percentile + 99) // 100
    return values[rank - 1]


def _verify_embedded_digest(payload: dict, field: str) -> None:
    declared = payload.get(field)
    if not isinstance(declared, str):
        raise ValueError(f"artifact lacks {field}")
    body = {key: value for key, value in payload.items() if key != field}
    if canonical_digest(body) != declared:
        raise ValueError(f"artifact {field} mismatch")


def _selection_hold_report_payload(
    *,
    experiment_id: str,
    baseline_snapshot_id: str,
    selection: FormalSelectionArtifact,
    lineage_digest: str,
    batch_cost: Decimal,
    updater_cost: Decimal,
    total_cost: Decimal,
    cost_status: str,
    updater_unresolved: int,
    updater_unknown: list[str],
) -> dict:
    return {
        "schema_version": "1.0",
        "report_kind": "selection_hold",
        "experiment_id": experiment_id,
        "decision": DecisionValue.HOLD,
        "decision_reason": selection.selection.decision_reason,
        "baseline_snapshot_id": baseline_snapshot_id,
        "native_candidate_id": selection.selection.native_candidate_id,
        "agentloopgate_candidate_id": None,
        "selection_digest": selection.selection_digest,
        "lineage_digest": lineage_digest,
        "governance_findings": selection.selection.governance_findings,
        "batch_model_cost_usd": batch_cost,
        "updater_model_cost_usd": updater_cost,
        "total_known_model_cost_usd": total_cost,
        "cost_status": cost_status,
        "unresolved_updater_model_call_count": updater_unresolved,
        "unknown_cost_scope": updater_unknown,
        "release_batch_count": 0,
        "model_calls_after_selection": 0,
    }


def _selection_hold_markdown(
    *,
    experiment_id: str,
    baseline_snapshot_id: str,
    selection: FormalSelectionArtifact,
    batch_cost: Decimal,
    updater_cost: Decimal,
    total_cost: Decimal,
    cost_status: str,
    updater_unknown: list[str],
    lineage_digest: str,
) -> str:
    findings = selection.selection.governance_findings or {}
    lines = [
        f"# {experiment_id} Selection HOLD",
        "",
        "AgentLoopGate completed Selection and abstained from nominating a release "
        "candidate. This is a normal governed terminal outcome, not an "
        "infrastructure failure.",
        "",
        "- Decision: `HOLD`",
        f"- Reason: `{selection.selection.decision_reason}`",
        f"- Baseline: `{baseline_snapshot_id}`",
        f"- Updater-native candidate: `{selection.selection.native_candidate_id}`",
        "- AgentLoopGate candidate: `null`",
        "- Release/OOD/Replay batches started after Selection: `0`",
        f"- Batch model cost: USD `{batch_cost}`",
        f"- Updater known model cost: USD `{updater_cost}`",
        f"- Total known model cost: USD `{total_cost}`",
        f"- Overall cost status: `{cost_status}`",
        f"- Selection digest: `{selection.selection_digest}`",
        f"- Lineage digest: `{lineage_digest}`",
        "",
        "## Candidate findings",
        "",
    ]
    for candidate_id in sorted(findings):
        lines.append(f"- `{candidate_id}`: " + ", ".join(findings[candidate_id]))
    if updater_unknown:
        lines.extend(
            [
                "",
                "## Unknown cost scope",
                "",
                *[f"- `{item}`" for item in updater_unknown],
            ]
        )
    lines.extend(
        [
            "",
            "No deployment, promotion, publication, or release action was performed.",
            "",
        ]
    )
    return "\n".join(lines)


def _funnel_stage(failure: FailureType) -> str:
    if failure in {
        FailureType.RETRIEVAL_MISS,
        FailureType.DOCUMENT_SELECTION_ERROR,
        FailureType.CROSS_DOCUMENT_REASONING_ERROR,
    }:
        return "retrieval"
    if failure in {
        FailureType.POLICY_APPLICATION_ERROR,
        FailureType.USER_CLAIM_OVERTRUST,
    }:
        return "policy"
    if failure in {
        FailureType.TOOL_DISCOVERY_ERROR,
        FailureType.TOOL_SELECTION_ERROR,
        FailureType.TOOL_PARAMETER_ERROR,
        FailureType.ACTION_ORDER_ERROR,
        FailureType.RECOVERY_ERROR,
    }:
        return "tool"
    return "correct_state"


def _batch_ref(experiment_id: str, batch: FormalBatchArtifact) -> str:
    return f"runs/experiments/{experiment_id}/batches/{batch.batch_id}.json"


def _diverse_subset(
    candidates: list[CandidateRecord],
    *,
    count: int,
    min_families: int,
) -> list[CandidateRecord]:
    for subset in combinations(candidates, count):
        families = {family for item in subset for family in item.asset_families}
        if len(families) >= min_families:
            return list(subset)
    raise FormalWorkflowBlocked("no candidate subset satisfies the frozen asset-family minimum")


class _NoExecute:
    def execute(self, spec: FormalBatchSpec):
        raise FormalWorkflowBlocked(
            f"formal batch unexpectedly attempted re-execution: {spec.batch_id}"
        )
