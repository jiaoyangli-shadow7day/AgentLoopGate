"""Minimal evidence needed for one decision card and four core charts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from agentloopgate.gates import GateOutcome
from agentloopgate.schemas import ArtifactId, NonEmpty, Pool
from agentloopgate.schemas.models import StrictModel


class CandidateCurvePoint(StrictModel):
    label: ArtifactId
    pass_1: Decimal = Field(ge=0, le=1)
    pass_k: Decimal = Field(ge=0, le=1)
    mean_cost: Decimal = Field(ge=0)


class FailureFunnelPoint(StrictModel):
    stage: Literal["retrieval", "policy", "tool", "correct_state"]
    count: int = Field(ge=0)


class PoolComparisonPoint(StrictModel):
    candidate_id: ArtifactId
    pool: Pool
    stable_tasks: int = Field(ge=0)


class ReportData(StrictModel):
    schema_version: Literal["1.0"]
    experiment_id: ArtifactId
    decision: GateOutcome
    candidate_curve: list[CandidateCurvePoint] = Field(min_length=1)
    failure_funnel: list[FailureFunnelPoint] = Field(min_length=1)
    pool_comparison: list[PoolComparisonPoint] = Field(min_length=1)

    @model_validator(mode="after")
    def funnel_stages_are_unique(self) -> ReportData:
        stages = [point.stage for point in self.failure_funnel]
        if len(stages) != len(set(stages)):
            raise ValueError("failure funnel stages must be unique")
        return self


class ReportArtifact(StrictModel):
    schema_version: Literal["1.0"]
    experiment_id: ArtifactId
    decision_json: Path
    decision_markdown: Path
    chart_paths: list[Path]
    report_digest: NonEmpty

