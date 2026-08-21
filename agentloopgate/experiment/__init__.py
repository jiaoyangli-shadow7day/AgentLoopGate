"""Credentialed formal experiment orchestration, evidence, and analysis."""

from .ablations import (
    IntegrityGateAblation,
    run_integrity_gate_ablation,
    run_plugin_coexistence_ablation,
)
from .batch import (
    DshFormalBatchExecutor,
    FormalBatchArtifact,
    FormalBatchError,
    FormalBatchExecution,
    FormalBatchRunner,
    FormalBatchRunResult,
    FormalBatchSpec,
    FormalStage,
)
from .diagnosis_ablation import (
    DiagnosisDirectionAblationArtifact,
    build_diagnosis_direction_ablation,
)
from .diagnostics import FormalDiagnosisArtifact, diagnose_formal_records
from .ledger import (
    ExperimentAttemptEvent,
    ExperimentAttemptLedger,
    FormalCostAccounting,
)
from .orchestrator import (
    FormalDecisionArtifact,
    FormalExperimentOrchestrator,
    FormalExperimentOutcome,
    FormalLineageArtifact,
    FormalRoleAssignmentArtifact,
    FormalSelectionArtifact,
    FormalWorkflowBlocked,
)
from .protocol import (
    FormalExecutionProtocol,
    computed_protocol_digest,
    load_execution_protocol,
    verify_execution_protocol,
)
from .service import (
    FormalExperimentConfig,
    FormalExperimentService,
    FormalPreflightReport,
    inspect_formal_preflight,
)
from .statistics import (
    PairedTaskBootstrapComparison,
    PublicationStatisticsArtifact,
    SelectorAblationArtifact,
    build_publication_statistics,
    build_selector_ablation,
    paired_task_bootstrap,
)
from .study import BankingR2StudyPlan, computed_study_digest, load_study_plan

__all__ = [
    "DshFormalBatchExecutor",
    "BankingR2StudyPlan",
    "FormalBatchArtifact",
    "FormalBatchError",
    "FormalBatchExecution",
    "FormalBatchRunner",
    "FormalBatchRunResult",
    "FormalBatchSpec",
    "FormalDiagnosisArtifact",
    "DiagnosisDirectionAblationArtifact",
    "FormalDecisionArtifact",
    "FormalExperimentOrchestrator",
    "FormalExperimentOutcome",
    "FormalExperimentConfig",
    "FormalExecutionProtocol",
    "FormalCostAccounting",
    "FormalExperimentService",
    "FormalPreflightReport",
    "FormalLineageArtifact",
    "FormalRoleAssignmentArtifact",
    "FormalSelectionArtifact",
    "FormalStage",
    "FormalWorkflowBlocked",
    "IntegrityGateAblation",
    "PairedTaskBootstrapComparison",
    "PublicationStatisticsArtifact",
    "SelectorAblationArtifact",
    "ExperimentAttemptEvent",
    "ExperimentAttemptLedger",
    "computed_protocol_digest",
    "computed_study_digest",
    "build_diagnosis_direction_ablation",
    "build_publication_statistics",
    "build_selector_ablation",
    "diagnose_formal_records",
    "inspect_formal_preflight",
    "load_execution_protocol",
    "load_study_plan",
    "paired_task_bootstrap",
    "run_integrity_gate_ablation",
    "run_plugin_coexistence_ablation",
    "verify_execution_protocol",
]
