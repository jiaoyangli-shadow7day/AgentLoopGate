"""Updater-native and governance selector comparison over one frozen ladder."""

from __future__ import annotations

from agentloopgate.contracts import canonical_digest
from agentloopgate.gates.models import (
    CandidateSelectionInput,
    DualSelection,
)


class SelectionError(ValueError):
    """The frozen candidate ladder has no eligible selection."""


class DualSelector:
    def select(self, ladder: list[CandidateSelectionInput]) -> DualSelection:
        if not ladder:
            raise SelectionError("candidate ladder is empty")
        ids = [item.candidate_id for item in ladder]
        if len(ids) != len(set(ids)):
            raise SelectionError("candidate ladder contains duplicate ids")
        uses_scores = all(item.native_score is not None for item in ladder)
        uses_ranks = all(item.native_rank is not None for item in ladder)
        if not (uses_scores or uses_ranks):
            raise SelectionError("candidate ladder mixes updater-native signal kinds")
        if uses_scores:
            native_winner = min(
                ladder,
                key=lambda item: (-item.native_score, item.candidate_id),
            )
        else:
            ranks = [item.native_rank for item in ladder]
            if len(ranks) != len(set(ranks)):
                raise SelectionError("updater-native ranks must be unique")
            native_winner = min(
                ladder,
                key=lambda item: (item.native_rank, item.candidate_id),
            )
        governed = [
            item
            for item in ladder
            if item.evaluation_complete and item.critical_violations == 0
        ]
        if not governed:
            raise SelectionError("candidate ladder has no governance-eligible candidate")
        governed_winner = min(
            governed,
            key=lambda item: (
                -item.stable_success_task_count,
                item.mean_cost,
                item.p50_latency_ms,
                item.candidate_id,
            ),
        )
        return DualSelection(
            schema_version="1.0",
            native_candidate_id=native_winner.candidate_id,
            agentloopgate_candidate_id=governed_winner.candidate_id,
            ladder_digest=canonical_digest(ladder),
        )
