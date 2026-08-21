"""Lexicographic promotion gate; hard failures cannot be averaged away."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from agentloopgate.contracts import canonical_digest, verify_contract_digest
from agentloopgate.gates.models import GateAssessment, GateOutcome
from agentloopgate.schemas import (
    DecisionRecord,
    DecisionValue,
    GateName,
    GateStatus,
    ObjectiveContract,
    RiskTier,
)
from agentloopgate.schemas.models import GateEvidence


class GateEngine:
    def __init__(self, contract: ObjectiveContract) -> None:
        verify_contract_digest(contract)
        self.contract = contract

    def decide(self, assessment: GateAssessment, *, created_at: datetime) -> GateOutcome:
        results: list[GateEvidence] = []
        failed_gate: GateName | None = None
        reason = "all frozen promotion gates passed"
        for gate in self.contract.decision_order:
            if failed_gate is not None:
                status = GateStatus.NOT_EVALUATED
            else:
                passed, gate_reason = self._evaluate(gate, assessment)
                status = GateStatus.PASS if passed else GateStatus.FAIL
                if not passed:
                    failed_gate = gate
                    reason = gate_reason
            results.append(
                GateEvidence(
                    name=gate,
                    status=status,
                    evidence_ref=assessment.evidence_refs[gate],
                )
            )
        if failed_gate is None:
            decision = DecisionValue.SHIP_RECOMMENDED
        elif failed_gate is GateName.LEAKAGE:
            decision = DecisionValue.REJECT
        else:
            decision = DecisionValue.HOLD
        identity = canonical_digest(
            {
                "contract": self.contract.contract_digest,
                "assessment": assessment,
                "decision": decision,
            }
        ).removeprefix("sha256:")[:16].upper()
        record = DecisionRecord(
            schema_version="1.0",
            decision_id=f"D_{identity}",
            candidate_id=assessment.candidate_id,
            baseline_snapshot_id=assessment.baseline_snapshot_id,
            decision=decision,
            gates=results,
            summary=f"{decision.value}: {reason}",
            human_approval=None,
            created_at=created_at,
        )
        return GateOutcome(
            schema_version="1.0",
            record=record,
            failed_gate=failed_gate,
            reason=reason,
        )

    def _evaluate(
        self,
        gate: GateName,
        assessment: GateAssessment,
    ) -> tuple[bool, str]:
        thresholds = self.contract.gates
        if gate is GateName.EVALUATION_INTEGRITY:
            return (
                assessment.evaluation_integrity_complete,
                "evaluation evidence is incomplete",
            )
        if gate is GateName.LEAKAGE:
            passed = (
                not assessment.mutates_trust_kernel
                and assessment.leakage_hits <= thresholds.leakage_hits_max
            )
            return passed, "candidate crosses the trust boundary or leaks evaluation data"
        if gate is GateName.CRITICAL_VIOLATION:
            passed = (
                assessment.risk_tier is not RiskTier.H
                and assessment.release_critical_violations
                <= thresholds.critical_violations_max
            )
            return passed, "candidate is Risk-H or has a release critical violation"
        if gate is GateName.ID_EFFECT:
            return (
                assessment.id_stable_task_net >= thresholds.id_stable_task_net_min,
                "independent ID stable-task effect is below the frozen minimum",
            )
        if gate is GateName.OOD_NONINFERIORITY:
            return (
                assessment.ood_stable_task_net >= thresholds.ood_stable_task_net_min,
                "OOD stable-task effect is below the frozen noninferiority margin",
            )
        if gate is GateName.REPLAY:
            passed = (
                assessment.replay_stable_task_net >= thresholds.replay_stable_task_net_min
                and assessment.catastrophic_regressions
                <= thresholds.catastrophic_regressions_max
            )
            return passed, "replay regressed or a catastrophic regression was detected"
        if gate is GateName.RELIABILITY:
            passed = (
                assessment.reliability_complete
                and assessment.reliability_trials == self.contract.reliability.trials
                and assessment.stable_success_required
                == self.contract.reliability.stable_success_required
            )
            return passed, "Pass^k reliability evidence is incomplete or mismatched"
        if gate is GateName.COST:
            ratio = _ratio(
                assessment.candidate_mean_cost,
                assessment.baseline_mean_cost,
            )
            passed = ratio is not None and ratio <= Decimal(
                str(thresholds.mean_cost_ratio_max)
            )
            return passed, "mean cost ratio exceeds the frozen limit"
        if gate is GateName.LATENCY:
            ratio = _ratio(
                assessment.candidate_p50_latency_ms,
                assessment.baseline_p50_latency_ms,
            )
            passed = ratio is not None and ratio <= Decimal(
                str(thresholds.p50_latency_ratio_max)
            )
            return passed, "p50 latency ratio exceeds the frozen limit"
        raise AssertionError(f"unhandled gate: {gate}")


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return Decimal(1) if numerator == 0 else None
    return numerator / denominator

