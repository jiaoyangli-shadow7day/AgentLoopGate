"""Updater-native and governance selector comparison over one frozen ladder."""

from __future__ import annotations

from agentloopgate.contracts import canonical_digest
from agentloopgate.gates.models import (
    BaselineSelectionInput,
    CandidateSelectionInput,
    DualSelection,
    SelectionPolicy,
)


class SelectionError(ValueError):
    """The frozen candidate ladder has no eligible selection."""


class DualSelector:
    def select(
        self,
        ladder: list[CandidateSelectionInput],
        *,
        baseline: BaselineSelectionInput | None = None,
        policy: SelectionPolicy | None = None,
    ) -> DualSelection:
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
        if (baseline is None) != (policy is None):
            raise SelectionError("baseline and selection policy must be supplied together")
        if baseline is not None and policy is not None:
            return self._select_with_baseline(
                ladder,
                native_candidate_id=native_winner.candidate_id,
                baseline=baseline,
                policy=policy,
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

    @staticmethod
    def _select_with_baseline(
        ladder: list[CandidateSelectionInput],
        *,
        native_candidate_id: str,
        baseline: BaselineSelectionInput,
        policy: SelectionPolicy,
    ) -> DualSelection:
        if not baseline.evaluation_complete or baseline.critical_violations:
            raise SelectionError("selection baseline is incomplete or unsafe")
        baseline_tasks = set(baseline.stable_task_outcomes)
        findings: dict[str, list[str]] = {}
        eligible: list[CandidateSelectionInput] = []
        for item in ladder:
            reasons: list[str] = []
            if item.stable_task_outcomes is None:
                raise SelectionError(
                    f"candidate {item.candidate_id} lacks enhanced selection evidence"
                )
            if set(item.stable_task_outcomes) != baseline_tasks:
                raise SelectionError(
                    f"candidate {item.candidate_id} and baseline task populations differ"
                )
            if not item.evaluation_complete:
                reasons.append("evaluation_incomplete")
            if item.critical_violations:
                reasons.append("critical_violation")
            regressed = sorted(
                task_id
                for task_id, succeeded in baseline.stable_task_outcomes.items()
                if succeeded and not item.stable_task_outcomes[task_id]
            )
            if regressed:
                reasons.append("stable_task_regression:" + ",".join(regressed))
            if item.stable_success_task_count <= baseline.stable_success_task_count:
                reasons.append("no_stable_success_gain")
            if not _within_ratio(
                item.whole_attempt_cost_usd,
                baseline.whole_attempt_cost_usd,
                policy.whole_attempt_cost_ratio_max,
            ):
                reasons.append("whole_attempt_cost_noninferiority")
            if not _within_ratio(
                item.p95_latency_ms,
                baseline.p95_latency_ms,
                policy.p95_latency_ratio_max,
            ):
                reasons.append("p95_latency_noninferiority")
            if item.retry_count > baseline.retry_count + policy.max_retry_increase:
                reasons.append("retry_increase")
            if item.timeout_count > baseline.timeout_count + policy.max_timeout_increase:
                reasons.append("timeout_increase")
            findings[item.candidate_id] = reasons or ["eligible_strict_improvement"]
            if not reasons:
                eligible.append(item)

        selected = (
            min(
                eligible,
                key=lambda item: (
                    -item.stable_success_task_count,
                    item.timeout_count,
                    item.retry_count,
                    item.p95_latency_ms,
                    item.max_latency_ms,
                    item.whole_attempt_cost_usd,
                    item.mean_cost,
                    item.p50_latency_ms,
                    item.candidate_id,
                ),
            )
            if eligible
            else None
        )
        return DualSelection(
            schema_version="1.1",
            native_candidate_id=native_candidate_id,
            agentloopgate_candidate_id=(selected.candidate_id if selected else None),
            ladder_digest=canonical_digest(ladder),
            agentloopgate_decision="SELECT" if selected else "HOLD",
            decision_reason=(
                "strict_no-regression_selection_improvement"
                if selected
                else "no_candidate_passed_baseline_bound_selection_policy"
            ),
            baseline_snapshot_id=baseline.snapshot_id,
            baseline_digest=canonical_digest(baseline),
            policy_digest=canonical_digest(policy),
            governance_findings=findings,
        )


def _within_ratio(value, baseline, maximum) -> bool:
    if baseline == 0:
        return value == 0
    return value / baseline <= maximum
