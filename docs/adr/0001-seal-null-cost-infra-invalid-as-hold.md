# ADR 0001: Seal null-cost infrastructure-invalid evidence as HOLD

- Status: accepted for evidence-only adjudication
- Date: 2026-08-21
- Incident: `EI_RELEASE_ID_NULL_COST_20260821`
- Scope: evidence representation and batch disposition only

## Context

A0 Release-ID batch `B_7A2507E605C0BC8B5158` completed all 60 target
task-trials. Four retry-exhausted upstream simulations correctly used
`termination_reason=infrastructure_error`, empty messages, zero τ³ duration,
and `agent_cost: null`. The other 56 simulations had complete cost and outcome
evidence.

The importer recognized the infrastructure status but required numeric cost
for every record. It therefore stopped before a formal batch artifact could be
sealed. This preserved the no-fabrication rule, but it also made the evidence
pipeline unable to distinguish a failed evaluation from a failure to record
that evaluation.

## Decision

1. A valid run still requires an exact, non-negative `agent_cost`.
2. An infrastructure-invalid run may carry `cost: null`. Null means unknown,
   never zero.
3. Infrastructure-invalid runs remain outside the business-success and valid-
   run cost denominators.
4. A formal batch containing a retry-exhausted infrastructure-invalid target
   is sealed with disposition `hold`, its integrity issues, and all available
   τ³/DSH evidence. It is not promoted to a complete batch.
5. Existing immutable raw bytes may be re-ingested without a model call when
   the correction changes only evidence representation. The raw digest and
   prior snapshot identity must remain unchanged.
6. DeepSeek Harness trace usage and elapsed/retry evidence may be reported as
   recovery cost, but may not be copied into the missing τ³ `agent_cost` field.
7. End-to-end orchestration stops when it encounters a held batch.

## Consequences

This fast path produces an honest HOLD artifact and preserves the completed
experiment as evidence. It does not create decision-grade replacement trials,
does not improve the measured business result, and does not authorize Ship.
A later decision-grade experiment still requires symmetric execution for A0
and every compared candidate.
