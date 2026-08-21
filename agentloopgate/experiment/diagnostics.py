"""Conservative formal-run diagnostics derived from admitted τ³ evidence."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from agentloopgate.adapters import OutcomeDiagnostics
from agentloopgate.contracts import canonical_digest
from agentloopgate.diagnosis import DiagnosticSignals, FailureDiagnoser, RankedFailureBundle
from agentloopgate.schemas import ArtifactId, Digest, RunRecord, RunValidity
from agentloopgate.schemas.models import StrictModel
from agentloopgate.splits.models import TaskDescriptor


class FormalDiagnosisArtifact(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    batch_id: ArtifactId
    snapshot_id: ArtifactId
    signals: list[DiagnosticSignals]
    ranked_bundles: list[RankedFailureBundle]
    diagnosis_digest: Digest


def diagnose_formal_records(
    *,
    batch_id: str,
    records: list[RunRecord],
    diagnostics: list[OutcomeDiagnostics],
    tasks: list[TaskDescriptor],
) -> FormalDiagnosisArtifact:
    by_run = {item.run_id: item for item in diagnostics}
    by_task = {item.task_id: item for item in tasks}
    if len(by_run) != len(diagnostics):
        raise ValueError("formal diagnostics contain duplicate run ids")
    if len(by_task) != len(tasks):
        raise ValueError("formal task descriptors contain duplicate ids")
    failures: list[DiagnosticSignals] = []
    snapshot_ids = {record.snapshot_id for record in records}
    for record in records:
        if record.success is True:
            continue
        diagnostic = by_run.get(record.run_id)
        task = by_task.get(record.task_id)
        if diagnostic is None or task is None:
            raise ValueError("formal diagnosis evidence population is incomplete")
        failures.append(_signals(record, diagnostic, task))
    if len(snapshot_ids) != 1:
        raise ValueError("formal diagnosis records must belong to one snapshot")
    ranked = FailureDiagnoser().build_bundles(failures) if failures else []
    payload = {
        "schema_version": "1.0",
        "batch_id": batch_id,
        "snapshot_id": next(iter(snapshot_ids)),
        "signals": failures,
        "ranked_bundles": ranked,
    }
    return FormalDiagnosisArtifact.model_validate(
        {**payload, "diagnosis_digest": canonical_digest(payload)}
    )


def _signals(
    record: RunRecord,
    diagnostic: OutcomeDiagnostics,
    task: TaskDescriptor,
) -> DiagnosticSignals:
    observed = set(diagnostic.observed_tool_names)
    expected = {item.name for item in diagnostic.action_checks}
    tool_required = bool(diagnostic.action_checks)
    tool_discovered = bool(observed) if tool_required else None
    selected_correctly = bool(observed & expected) if tool_discovered else None
    parameters_correct = (
        any(item.matched for item in diagnostic.action_checks)
        if selected_correctly
        else None
    )
    return DiagnosticSignals(
        schema_version="1.0",
        run_id=record.run_id,
        task_id=record.task_id,
        snapshot_id=record.snapshot_id,
        pool=record.pool,
        run_validity=record.run_validity,
        success=record.success,
        evidence_ref=f"runs/diagnostics/{record.run_id}.json",
        # The admitted τ³ result does not expose retrieval coverage without also
        # exposing protected Gold document identity, so formal classification is
        # deliberately conservative here. Retrieval subclasses remain supported
        # by the generic diagnostic contract and audited fixtures.
        retrieval_required=False,
        retrieval_attempted=False,
        retrieved_document_count=0,
        required_document_count=diagnostic.required_document_count,
        gold_document_coverage=None,
        cross_document_reasoning_correct=None,
        policy_application_correct=None,
        tool_required=tool_required,
        tool_discovered=tool_discovered,
        tool_selected_correctly=selected_correctly,
        tool_parameters_correct=parameters_correct,
        action_order_correct=None,
        terminal_state_verified=(
            diagnostic.db_match
            if record.run_validity is RunValidity.VALID
            else None
        ),
        recovery_required=False,
        recovery_succeeded=None,
        user_claim_overtrust=False,
        evaluator_conflict=False,
        user_value_loss=Decimal(1),
        risk_weight=Decimal(2 if task.high_risk else 1),
        fixability=Decimal(1),
    )
