# ADR 0002: Version the formal execution protocol for Banking R2

- Status: accepted
- Date: 2026-08-21
- Supersedes for release claims: `EXP_BANKING_P0`
- Does not replace: its immutable raw evidence, HOLD artifact, or Incident record

## Context

The original frozen Spec allowed at most one automatic retry per task. The
formal τ³ command did not pass `--max-retries`, so pinned τ³ used its upstream
default of three retries. The operator journal confirms successful results on
retry 2/3 and retry exhaustion after retry 3. This is useful engineering
evidence, but the protocol/implementation mismatch prevents publication-grade
release claims from that experiment.

## Decision

1. Preserve `EXP_BANKING_P0` byte-for-byte as a superseded HOLD experiment.
2. Use new experiment identity `EXP_BANKING_R2` and baseline identity `R2_A0`.
3. Require a content-addressed, frozen execution protocol before every new paid
   formal run. Legacy configurations remain available only for existing-evidence
   verification.
4. Explicitly pass one retry, one-second retry delay, concurrency one, and a
   180-second DSH turn timeout. Record valid costs exactly; retain null cost only
   for infrastructure-invalid runs and exclude it from valid cost denominators.
5. Bind every R2 `FormalBatchSpec` and batch ID to the protocol digest.
6. Pre-register the full A0-to-Decision matrix and four minimal ablations before
   running R2. The matrix totals 560 target task-trials before retries.
7. Do not alter the frozen Objective, Split, Gate order, or thresholds based on
   observed P0 or R2 outcomes.

## Consequences

R2 must rerun the complete Update-Source, Update-Check, Selection, Release-ID,
Release-OOD, and Replay pipeline rather than reuse P0 scores as its formal
result. P0 remains reportable as an incident and motivating case. R2 cannot
start until the protocol, study plan, dependencies, plugin profile, banking
pilot evidence, code revision, and process credential all pass preflight.

## Protocol v2 audit addendum

Before any paid R2 core work began, a second audit found retry layers below the
whole-task τ³ retry: DeepSeek Harness provider retries, the user-simulator
provider, Nexau/AHE, and the OpenAI SDK. Protocol v1 and its no-model evidence
remain immutable but are superseded for paid execution by
`BANKING_R2_PROTOCOL_2` and `BANKING_R2_STUDY_2`.

Protocol v2 pins all internal provider/updater retries to zero while retaining
one observable whole-task recovery retry. It also pins benchmark seed,
temperatures, token ceilings, step/error limits, simulation/updater timeouts,
and updater proposal/iteration limits. DSH turn protocol v1.1 exposes
`provider_retry_count`; any retry changes cost accounting to a lower-bound
`partial` state. R2 AHE writes a durable attempt before execution, journals each
model call, preserves raw output after failures/timeouts, and never maps missing
usage to zero.

The first v2 source freeze created evaluation-only `R2_A0`. Before paid work,
clean-room conformance exposed that its headless test fixture did not inject the
new v2 environment pins and still asserted turn protocol v1.0. `R2_A0` and its
manifest remain immutable incident evidence. After fixing only that acceptance
contract and passing the entire clean-room workflow, the same objective, split,
protocol, study, pricing, and plugin runtime were rebound to `R2_A1` in
`runs/experiments/EXP_BANKING_R2/freeze_manifest_a1.json`. Deployment activation
remains `A0`; paid R2 core execution must use the A1 identity.

After that freeze and still before paid work, release-artifact clean-room found
that the Python sdist omitted the configured local build backend. ADR 0003
preserves A1 as incident evidence and supersedes its execution identity with
R2_A2. ADR 0004 later preserves A2/A3 failures and selects R2_A4 after clean
checkout Linux verification. The protocol and study decisions in this ADR
remain unchanged; paid R2 core execution must use the latest accepted A4
identity.
