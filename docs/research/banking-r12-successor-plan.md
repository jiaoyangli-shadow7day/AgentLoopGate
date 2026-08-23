# Banking R12 successor plan

Status: terminal immutable `HOLD`. Protocol, Study, Evaluation Baseline,
calibrations, isolated DeepSeek Harness profile, preregistration, paid scope,
and all retained execution evidence verify. R12 must not be rerun, supplemented,
or extended.

Frozen identity:

- Experiment: `EXP_BANKING_R12`
- Protocol: `BANKING_R12_PROTOCOL_1`,
  `sha256:6c86b494bad7766a8b25477c7e0a73217bc5a7f552e995824ed0ee538dcbd3f2`
- Study: `BANKING_R12_STUDY_1`,
  `sha256:423ca8b74d38998c038e2824f9d9582275cae9630a6f85c201afa628301732a4`
- Execution source:
  `tree:sha256:d7f8e3a0b8a9004fcb1778d90bb773360dda6a5fa1eb7ad68ca9a64eece265bd`
- Evaluation Baseline: `R12_A0`,
  `sha256:f4af003bf938583b134e6a1eab42bcb0abcf9f10b730e8f1411c61b443922c36`
- Machine preregistration:
  `sha256:2c331639045313568fac9cf91dd350731805df666244e2717840523a46ed439e`

## Purpose

R12 is the next possible Banking reference-validation identity after the
immutable R11 Update-Source `HOLD`. It has one job: produce a complete,
auditable terminal result for the corrected A0-bound selection policy, without
rewriting, excluding, or extending R11.

The resulting open-source conclusion must be conditional on the terminal kind:

- A complete `HOLD/ABSTAIN` supports the systems claim that AgentLoopGate
  prevents unsupported self-evolution from advancing to release while retaining
  trace, cost, latency, retry, and integrity evidence. It does **not** support
  a positive-improvement claim.
- A complete `SELECT`, followed by separately authorized and sealed
  Release-ID/OOD/Replay evidence, may support the narrower claim that one
  governed candidate improved the frozen Banking reference setting subject to
  its stated gates and limitations.
- Any Infra Invalid, incomplete denominator, unresolved cost, or evidence gap
  remains an explicit `HOLD`; it is never repaired by hiding a position or
  extending the same experiment identity.

## Actual terminal outcome

R12 executed 25/25 Update-Source positions and produced three separately
metered AHE candidate snapshots. It then executed only the 10-position
independent `R12_A0` Update-Check anchor. Nine positions were valid; `task_073`
failed both frozen attempts with the same empty-`UserMessage` infrastructure
error. The anchor therefore sealed `HOLD` for `infra_invalid:1` and
`missing_valid_trials` before any candidate evaluation.

- Update-Source: 25 valid, Pass@1 `9/25`.
- A0 Update-Check anchor: 9 valid, 1 Infra Invalid, Pass@1 `3/9`.
- External Updater: 3 candidates, 36 calls, exact cost USD `0.0120033368`.
- Executed formal positions: 35 of the planned 125.
- Candidate Update-Check, Selection, Release-ID/OOD/Replay, Decision, and
  Promote: zero.
- Total observed Provider-call cost lower bound: exact known scope USD
  `1.1970712488`; local compute monetary cost remains `unmetered_unknown`.

The content-addressed terminal record is
`artifacts/research/banking_r12/formal_execution_seal.json`, digest
`sha256:73457f10b7a7f8e2347b7d06cf24680ff46805546290b3ba89432bbca5ad383e`.
R12 supports a fail-closed and independent-cost-governance claim. It does not
support candidate-effectiveness or positive self-evolution claims.

## Frozen inputs required before execution

Before any model call, create a fresh experiment identity (provisionally
`EXP_BANKING_R12`) that content-addresses all of the following:

1. The execution tree containing the two R11 recovery fixes, including
   `763597c` and `5d8fd86`, plus its clean working-tree digest.
2. A new Evaluation Baseline, Snapshot manifest, Harness package/profile,
   Objective Contract, split manifests, τ³ commit, evaluator overlay, pricing,
   and execution calibrations.
3. A new Protocol and Study which explicitly supersede R11 only for future
   execution. R11 raw, task-attempt, usage, batch, cost, and operator-journal
   evidence remain immutable historical context.
4. The exact external-Updater request contract, candidate semantic-dedup rule,
   runtime Tool-Schema capability binding, model IDs, retry limits, timeouts,
   price table, cost-lineage policy, and trace-redaction policy.
5. A machine-readable preregistration and a no-key clean-room record produced
   from the exact frozen execution source.

The new configuration must reject reuse of R11 task results as decision-grade
R12 evidence. Existing-only recovery may only seal already retained evidence;
it must never start or supplement a paid batch.

## Required pre-Release checkpoint

The first paid scope is intentionally complete and bounded:

| Stage | Positions | Required record |
|---|---:|---|
| External AHE Updater | separately metered | prompt/request digest, token/price/cost, retry, duration, path, candidate lineage |
| Update-Source | 25 | raw τ³ result, Agent/User usage, task attempts, receipts/joins, cost and batch artifact |
| Update-Check | 40 | A0 plus three executable, semantically distinct candidates over the frozen pool |
| Selection | 60 | A0 plus the same three candidates, decisions, full cost/latency/retry/integrity inputs |

No stage may begin until the preceding evidence is sealed and verifies as
complete. R12 ran under its exact content-addressed machine authorization.
Future private experiments use the standing Owner mandate while retaining an
exact per-scope authorization artifact; credentials, a frozen config, or a
green preflight alone remain insufficient.

## Terminal branches

1. **Selection HOLD:** seal the Selection-HOLD outcome and prove that no
   Release-stage model calls occurred. Build the HOLD-appropriate sanitized
   public package and report a governance/fail-closed result.
2. **Selection SELECT:** first audit the Decision and Candidate lineage. Under
   the standing private-experiment mandate, the operator may create the exact
   bound Release-tail capability and run Release-ID, Release-OOD, and Replay.
   A release claim then requires all corresponding gates to pass.
3. **Integrity HOLD before Selection:** seal the failed stage and its full cost
   scope, report it as incomplete evidence, and prepare another successor only
   after diagnosing whether the cause is implementation, Harness, environment,
   or protocol.

## Publication acceptance criteria

The repository is ready to be made public only when the terminal branch has:

1. A verified sanitized result package and independent package verification.
2. Complete cost, retry, timeout, wall-clock, execution-path, trace-lineage,
   and Infra Invalid disclosure with named unknown scopes.
3. Minimal registered ablations, uncertainty analysis, four core figures,
   limitations, and a report whose claims match the terminal kind.
4. Fresh source and release-artifact clean-room verification, DeepSeek Harness
   conformance, public-tree Secret/direct-PII audit, and green private CI.
5. Community-release files (`CONTRIBUTING.md`, `SECURITY.md`,
   `CODE_OF_CONDUCT.md`, `CITATION.cff`, and `CHANGELOG.md`) plus verified
   license and third-party notices.
6. A separate Owner instruction to change repository visibility or publish a
   Release. Publication and paper submission are never automatic consequences
   of a successful Gate.
