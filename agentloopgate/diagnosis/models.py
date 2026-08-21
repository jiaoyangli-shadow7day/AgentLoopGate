"""Protected diagnostic signals and ranked failure output."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from agentloopgate.schemas import ArtifactId, FailureBundle, NonEmpty, Pool, RunValidity
from agentloopgate.schemas.models import StrictModel


class DiagnosticSignals(StrictModel):
    """Derived offline signals; raw Gold names and expected actions are intentionally absent."""

    schema_version: Literal["1.0"]
    run_id: ArtifactId
    task_id: ArtifactId
    snapshot_id: ArtifactId
    pool: Pool
    run_validity: RunValidity
    success: bool | None
    evidence_ref: NonEmpty
    retrieval_required: bool
    retrieval_attempted: bool
    retrieved_document_count: int = Field(ge=0)
    required_document_count: int = Field(ge=0)
    gold_document_coverage: bool | None
    cross_document_reasoning_correct: bool | None
    policy_application_correct: bool | None
    tool_required: bool
    tool_discovered: bool | None
    tool_selected_correctly: bool | None
    tool_parameters_correct: bool | None
    action_order_correct: bool | None
    terminal_state_verified: bool | None
    recovery_required: bool
    recovery_succeeded: bool | None
    user_claim_overtrust: bool
    evaluator_conflict: bool
    user_value_loss: Decimal = Field(ge=0)
    risk_weight: Decimal = Field(gt=0)
    fixability: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def state_is_coherent(self) -> DiagnosticSignals:
        if self.run_validity is RunValidity.VALID and self.success is None:
            raise ValueError("valid diagnostic signals require success")
        if self.run_validity is RunValidity.INFRA_INVALID and self.success is not None:
            raise ValueError("infra_invalid diagnostic signals cannot report agent success")
        if self.tool_required and self.tool_discovered is None:
            raise ValueError("tool-required signals must report discovery")
        if self.tool_discovered and self.tool_selected_correctly is None:
            raise ValueError("discovered tool signals must report selection correctness")
        if self.tool_selected_correctly and self.tool_parameters_correct is None:
            raise ValueError("selected tool signals must report parameter correctness")
        if self.recovery_required and self.recovery_succeeded is None:
            raise ValueError("recovery-required signals must report recovery outcome")
        return self


class RankedFailureBundle(StrictModel):
    schema_version: Literal["1.0"]
    priority: Decimal = Field(ge=0)
    affected_task_count: int = Field(ge=1)
    bundle: FailureBundle

