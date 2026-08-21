"""Deterministic failure funnel and redacted FailureBundle builder."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from agentloopgate.contracts import canonical_digest
from agentloopgate.diagnosis.models import DiagnosticSignals, RankedFailureBundle
from agentloopgate.schemas import (
    AssetFamily,
    FailureBundle,
    FailureType,
    Pool,
    RunValidity,
)
from agentloopgate.schemas.models import ChangeBudget, ProtectedField


class DiagnosisError(ValueError):
    """Diagnostic evidence cannot safely produce an updater-visible bundle."""


_BUNDLE_POLICY: dict[
    FailureType,
    tuple[str, list[AssetFamily], str, ChangeBudget],
] = {
    FailureType.RETRIEVAL_MISS: (
        "The agent did not obtain the policy evidence needed before deciding.",
        [AssetFamily.RETRIEVAL_SEARCH_POLICY, AssetFamily.CONTEXT_MEMORY_SKILL],
        "Require retrieval and evidence confirmation before policy application.",
        ChangeBudget(max_files=4, max_changed_lines=160),
    ),
    FailureType.DOCUMENT_SELECTION_ERROR: (
        "The retrieved evidence set did not cover all required policy conditions.",
        [AssetFamily.RETRIEVAL_SEARCH_POLICY, AssetFamily.CONTEXT_MEMORY_SKILL],
        "Improve evidence selection without exposing protected evaluation content.",
        ChangeBudget(max_files=4, max_changed_lines=160),
    ),
    FailureType.CROSS_DOCUMENT_REASONING_ERROR: (
        "The agent found supporting evidence but failed to combine its conditions correctly.",
        [AssetFamily.CONTEXT_MEMORY_SKILL, AssetFamily.PROMPT_INSTRUCTION],
        "Make multi-source condition checks explicit before any consequential action.",
        ChangeBudget(max_files=4, max_changed_lines=160),
    ),
    FailureType.POLICY_APPLICATION_ERROR: (
        "The agent had sufficient evidence but applied a policy condition incorrectly.",
        [AssetFamily.CONTEXT_MEMORY_SKILL, AssetFamily.PROMPT_INSTRUCTION],
        "Require explicit prerequisite and exception checks before acting.",
        ChangeBudget(max_files=4, max_changed_lines=160),
    ),
    FailureType.TOOL_DISCOVERY_ERROR: (
        "The agent did not discover an available capability required by the task.",
        [AssetFamily.TOOL_CONTRACT_ROUTING, AssetFamily.CONTEXT_MEMORY_SKILL],
        "Make capability discovery deterministic before declaring an action unavailable.",
        ChangeBudget(max_files=3, max_changed_lines=120),
    ),
    FailureType.TOOL_SELECTION_ERROR: (
        "The agent selected a capability that did not match the intended operation.",
        [AssetFamily.TOOL_CONTRACT_ROUTING],
        "Route intents to the correct registered capability and preserve policy checks.",
        ChangeBudget(max_files=3, max_changed_lines=120),
    ),
    FailureType.TOOL_PARAMETER_ERROR: (
        "The selected capability received incomplete or invalid parameters.",
        [AssetFamily.TOOL_CONTRACT_ROUTING, AssetFamily.PROMPT_INSTRUCTION],
        "Validate required arguments and evidence-derived values before execution.",
        ChangeBudget(max_files=3, max_changed_lines=120),
    ),
    FailureType.ACTION_ORDER_ERROR: (
        "The agent executed valid operations in an unsafe or semantically incorrect order.",
        [AssetFamily.ORCHESTRATION_STATE, AssetFamily.TOOL_CONTRACT_ROUTING],
        "Enforce prerequisite transitions before consequential operations.",
        ChangeBudget(max_files=4, max_changed_lines=180),
    ),
    FailureType.STATE_VERIFICATION_ERROR: (
        "The agent did not verify the terminal state before reporting completion.",
        [AssetFamily.ORCHESTRATION_STATE, AssetFamily.PROMPT_INSTRUCTION],
        "Require read-after-write verification before a success claim.",
        ChangeBudget(max_files=4, max_changed_lines=160),
    ),
    FailureType.RECOVERY_ERROR: (
        "The agent failed to recover safely after a detectable execution error.",
        [AssetFamily.ORCHESTRATION_STATE, AssetFamily.MIDDLEWARE_RUNTIME_CODE],
        "Add bounded recovery with verification and an explicit stop condition.",
        ChangeBudget(max_files=5, max_changed_lines=200),
    ),
    FailureType.USER_CLAIM_OVERTRUST: (
        "The agent accepted an unverified user claim for a consequential decision.",
        [AssetFamily.PROMPT_INSTRUCTION, AssetFamily.CONTEXT_MEMORY_SKILL],
        "Require authoritative evidence for consequential user claims.",
        ChangeBudget(max_files=3, max_changed_lines=120),
    ),
    FailureType.SPEC_OR_EVALUATOR_ISSUE: (
        "The observed outcome conflicts with available evaluator evidence.",
        [AssetFamily.MIDDLEWARE_RUNTIME_CODE],
        "Hold candidate generation until the evaluation incident is resolved.",
        ChangeBudget(max_files=1, max_changed_lines=40),
    ),
    FailureType.INFRA_FAILURE: (
        "The run was invalidated by infrastructure rather than agent behavior.",
        [AssetFamily.MIDDLEWARE_RUNTIME_CODE],
        "Restore infrastructure integrity and rerun symmetrically.",
        ChangeBudget(max_files=3, max_changed_lines=120),
    ),
    FailureType.UNKNOWN: (
        "The available evidence is insufficient for a narrower failure class.",
        [AssetFamily.PROMPT_INSTRUCTION],
        "Collect additional verified evidence before making a targeted change.",
        ChangeBudget(max_files=2, max_changed_lines=80),
    ),
}


class FailureDiagnoser:
    def classify(self, signals: DiagnosticSignals) -> FailureType:
        if signals.run_validity is RunValidity.INFRA_INVALID:
            return FailureType.INFRA_FAILURE
        if signals.success:
            raise DiagnosisError("successful runs cannot enter the failure funnel")
        if signals.evaluator_conflict:
            return FailureType.SPEC_OR_EVALUATOR_ISSUE
        if signals.user_claim_overtrust:
            return FailureType.USER_CLAIM_OVERTRUST
        if signals.retrieval_required:
            if not signals.retrieval_attempted or signals.retrieved_document_count == 0:
                return FailureType.RETRIEVAL_MISS
            if signals.gold_document_coverage is False:
                return FailureType.DOCUMENT_SELECTION_ERROR
            if (
                signals.required_document_count > 1
                and signals.cross_document_reasoning_correct is False
            ):
                return FailureType.CROSS_DOCUMENT_REASONING_ERROR
        if signals.policy_application_correct is False:
            return FailureType.POLICY_APPLICATION_ERROR
        if signals.tool_required:
            if signals.tool_discovered is False:
                return FailureType.TOOL_DISCOVERY_ERROR
            if signals.tool_selected_correctly is False:
                return FailureType.TOOL_SELECTION_ERROR
            if signals.tool_parameters_correct is False:
                return FailureType.TOOL_PARAMETER_ERROR
        if signals.action_order_correct is False:
            return FailureType.ACTION_ORDER_ERROR
        if signals.terminal_state_verified is False:
            return FailureType.STATE_VERIFICATION_ERROR
        if signals.recovery_required and signals.recovery_succeeded is False:
            return FailureType.RECOVERY_ERROR
        return FailureType.UNKNOWN

    def build_bundles(
        self,
        signals: Iterable[DiagnosticSignals],
        *,
        protected_terms: Iterable[str] = (),
    ) -> list[RankedFailureBundle]:
        grouped: dict[tuple[str, FailureType], list[DiagnosticSignals]] = defaultdict(list)
        for item in signals:
            if item.pool is not Pool.UPDATE_SOURCE:
                raise DiagnosisError("FailureBundle inputs must come only from update_source")
            grouped[(item.snapshot_id, self.classify(item))].append(item)
        ranked = [
            self._build_group(snapshot_id, failure_type, items, protected_terms)
            for (snapshot_id, failure_type), items in grouped.items()
        ]
        return sorted(
            ranked,
            key=lambda item: (-item.priority, item.bundle.failure_bundle_id),
        )

    @staticmethod
    def _build_group(
        snapshot_id: str,
        failure_type: FailureType,
        items: list[DiagnosticSignals],
        protected_terms: Iterable[str],
    ) -> RankedFailureBundle:
        summary, families, expected, budget = _BUNDLE_POLICY[failure_type]
        run_ids = sorted({item.run_id for item in items})
        task_count = len({item.task_id for item in items})
        impact = max(
            item.user_value_loss * item.risk_weight * item.fixability for item in items
        )
        priority = task_count * impact
        identity = canonical_digest(
            {
                "snapshot_id": snapshot_id,
                "failure_type": failure_type,
                "run_ids": run_ids,
            }
        ).removeprefix("sha256:")[:16].upper()
        bundle = FailureBundle(
            schema_version="1.0",
            failure_bundle_id=f"FB_{identity}",
            snapshot_id=snapshot_id,
            source_pool=Pool.UPDATE_SOURCE,
            failure_type=failure_type,
            affected_run_ids=run_ids,
            evidence_refs=sorted({item.evidence_ref for item in items}),
            redacted_summary=summary,
            target_asset_families=families,
            expected_behavior_change=expected,
            must_not_change=list(ProtectedField),
            budget=budget,
        )
        serialized = bundle.model_dump_json().casefold()
        leaked = sorted(
            {
                term.strip()
                for term in protected_terms
                if term.strip() and term.strip().casefold() in serialized
            }
        )
        if leaked:
            raise DiagnosisError("FailureBundle contains protected evaluation terms")
        return RankedFailureBundle(
            schema_version="1.0",
            priority=priority,
            affected_task_count=task_count,
            bundle=bundle,
        )

