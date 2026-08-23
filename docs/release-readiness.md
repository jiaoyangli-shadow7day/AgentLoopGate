# AgentLoopGate open-source and paper readiness

Status date: 2026-08-23

Current paid-evidence checkpoint: immutable `EXP_BANKING_R13`. It executed all
25 Update-Source positions, retained 24 valid positions, and sealed terminal
`HOLD` because `task_048` remained Infra Invalid after its frozen retry. The
external Updater, Update-Check, Selection, Release, and Promote all remained at
zero. R13 also exposed a batch-internal fail-fast defect: 12 later positions ran
after the permanent failure. The Protocol 2.0 position-level stop control,
experiment-scoped candidate diagnostic, and DNS-only Provider precheck now pass
no-model fault injection and clean-room. Successor `EXP_BANKING_R14` now binds
Protocol `8c6baf…53de1`, Study `e2afe1…35d96`, source `0e2b2e…5abe`, and
evaluation baseline `R14_A0`. Its exact private CI has passed, while the paid
machine capability remains pending, so paid calls are still zero. The standing
private-experiment mandate permits bounded private experiments after all exact
machine gates pass; it does not permit publication, repository visibility
changes, or Promote.

This is the requirement-to-evidence checklist for the v1 release. Passing local
tests proves software behavior, not a positive self-evolution effect. A real
`HOLD/ABSTAIN` can complete the governance story when it is produced by the
corrected, baseline-bound Selection policy and all evidence is sealed.

## Acceptance matrix

| Requirement | State | Authoritative evidence | Remaining work |
|---|---|---|---|
| Preserve all historical attempts and incidents | PASS | R2–R12 immutable Snapshot/Batch/Raw/Trace/Attempt/Cost artifacts and append-only journals | Recheck hashes in the final publication seal |
| R10 execution through C2 Selection | SEALED HISTORICAL EVIDENCE | 25 Update-Source + 40 Update-Check + 30 Selection positions; C3 Selection and all Release stages absent | Never rewrite or resume under the corrected selector identity |
| Complete cost accounting through R10 C2 | PASS | Exact known model cost USD `3.0651904832`; batch, updater, task-attempt, Agent/User usage and retry evidence retained | Local compute monetary cost remains `unmetered_unknown` |
| Positive self-evolution direction | NOT ESTABLISHED | C1 and C2 both 7/15 with different success sets; C1/C3 semantic duplicate; C2 unbound capability | A new corrected experiment is required before any positive claim |
| A0-bound Selection with abstention | FROZEN IN R14 / ZERO-MODEL VERIFIED | Study `e2afe1…35d96`; strict stable gain, zero stable regression, whole-attempt cost, retry/timeout and p95/max latency policy | Run only after exact R14 private CI and machine authorization |
| Candidate semantic and runtime applicability | IMPLEMENTED / ZERO-MODEL VERIFIED | Semantic fingerprint/dedup and runtime Tool Schema capability binding | New external Updater must produce three distinct, bound candidates |
| Selection-HOLD normal terminal | IMPLEMENTED / ZERO-MODEL VERIFIED | Successful CLI outcome; immutable outcome/report/lineage/cost bindings; all candidates HELD; Release and post-Selection model calls fixed at zero; resume is verify-only | Exercise with real corrected Selection evidence |
| Position-level permanent-Infra fail-fast | FROZEN IN R14 / ZERO-MODEL VERIFIED | Protocol 2.0; injected non-final permanent failure; next positions and resume calls zero; prior/failed Attempt retained; calibration `b098b6…e573` | Exercise under the exact R14 paid identity |
| Exact paid-execution authorization | IMPLEMENTED / R14 PENDING | R13 authorization is consumed and terminal; R14 Protocol/Study/source/A0 and preregistration `a704e9…5a3f9` are frozen; exact-source CI passed | Create and verify the exact R14 pre-Release capability before any model call |
| DeepSeek Harness native Trace/Persistence/Telemetry coexistence | PASS FOR SYSTEM/FIXTURE EVIDENCE | Bundle lifecycle and headless conformance; JSONL/SQLite/OTel coexistence tests | Retain exact pin and rerun final clean-room |
| Full source/release-artifact clean-room | PASS LOCAL FOR FROZEN R14 | 208 Python and 13 TypeScript tests; Ruff, sdist→wheel, DSH conformance/build/pack and audit passed in 20.33 s | Pass exact-source private Linux CI and repeat for the final public tree |
| Secret and direct-PII audit | PASS FOR FROZEN R14 LOCAL TREE | 315 files scanned with zero findings and withheld paths/values | Repeat in private CI and for the final public result package |
| Corrected pre-Release paid checkpoint | R14 FROZEN / NOT STARTED | Protocol `8c6baf…53de1`; Study `e2afe1…35d96`; source `0e2b2e…5abe`; A0 `5c1873…024b`; external Updater and formal positions zero | Pass exact-source private CI, mint exact capability, then run 25/40/60; never resume R13 |
| Real Release-ID/OOD/Replay | CONDITIONAL UNDER STANDING PRIVATE MANDATE | Software paths and deterministic Gate fixtures exist | Run only if corrected Selection returns `SELECT` and a separately bound machine capability verifies; skip on HOLD |
| Minimal ablations and uncertainty | PARTIAL / TWO NO-MODEL ABLATIONS SEALED | R12 integrity fixture proves an unsupported `SHIP_RECOMMENDED` is converted to `HOLD`; DSH fixture preserves JSONL/SQLite event hashes, persistence and OTel, with measured local p95 overhead 4.110417/0.740291 ms | Derive selector/diagnosis statistics and uncertainty from sealed R12 paid evidence without causal overclaim |
| Sanitized public Banking result package | BUILDER READY / RESULTS MISSING | Configuration-driven, fail-closed builder/verifier supports both a verified full formal Outcome and the distinct Selection-HOLD terminal | Build only from the terminal result, then rerun the independent verifier and public-tree audit |
| README, license, and third-party declarations | PASS LOCALLY | `README.md`, Apache-2.0 `LICENSE`, `THIRD_PARTY_NOTICES.md` | Recheck packaged archives and links |
| Private GitHub repository | PASS | `jiaoyangli-shadow7day/AgentLoopGate`, private visibility | Keep private until explicit Owner authorization |
| Version-controlled private CI seal | PASS FOR EXACT R14 SOURCE | Commit `f176e24`, run `32660507957`, job `97245844684`; 206 Python passed/2 platform skips, 13 TypeScript passed, packaging/conformance passed, 316-file scan zero findings; machine record `frozen_identity_private_ci_validation.json` digest `60b4ba…a557b`; repository remained private | Repeat for terminal result package and final public tree |
| Public visibility, Release, or submission | NOT AUTHORIZED | Active Goal and SPEC trust boundary | Requires a separate explicit Owner instruction after final acceptance |

## What the current evidence proves

R10 and the R11 Source HOLD support the engineering claim that AgentLoopGate
can preserve DeepSeek Harness native traces, retain failure/retry/time/cost
evidence, recover and seal immutable evidence, fail closed on integrity
problems, and audit candidate decisions. They do not support the scientific
claim that an observed candidate found the correct self-evolution direction.
The corrected selector exists precisely because continuing the old experiment
would have manufactured a winner without showing improvement over A0.

R13 strengthens the engineering evidence: all 25 native DeepSeek Harness trace
references verified, independent attempt/cost ledgers retained an incomplete
Provider-cost scope, and the incomplete Source denominator blocked every
downstream stage. It still does not establish candidate effectiveness or a
positive self-evolution direction because no R13 candidate was generated or
evaluated.

R14 is preparation evidence only: its Protocol 2.0 identity, independent A0,
calibrations, timeouts, waste-control policy, and local clean-room are frozen.
Its exact-source private CI passed. Until the exact machine capability passes,
it has made no Updater or formal model call and cannot contribute an
effectiveness claim.

## Cost interpretation

- Known provider/model cost through R10 C2: exact USD `3.0651904832`.
- R11 Source observed-attempt provider-cost lower bound: USD
  `0.7266205472000000021`; direct valid Agent/User costs are USD
  `0.5385791880` and USD `0.08244740`. It is a held, incomplete batch, not a
  cross-stage result or an effectiveness claim.
- Model cost for the Selection correction, evidence sealing, and clean-room work:
  USD `0`; those operations made zero external model calls.
- R13 valid-run exact Provider cost: USD `0.6636430192`; whole-attempt observed
  lower bound: USD `0.6692124248000000062`, with one named unavailable
  `task_048` User Provider scope. Of the known amount, USD `0.4686327800` was
  spent by 12 positions after the permanent Infra Invalid had already made the
  Source batch ineligible for completion.
- Local CPU, filesystem, package, and wall-clock monetary cost:
  `unmetered_unknown`, never represented as zero.
- Any future partial or unavailable cost must remain a lower bound with named
  unknown scope; it cannot participate as an exact ranking value.

## Required completion order

1. Keep R10, R11, and every prior failure immutable; preserve their artifacts,
   cost records, recovery records, and private-CI seals.
2. Do not rerun or extend R11, R12, or R13. Preserve their terminal identities
   and all retained evidence.
3. Preserve the completed Protocol 2.0 fail-fast calibration `b098b6…e573`,
   including experiment-scoped candidate diagnostics and the
   DNS-only Provider precheck; any runtime-byte change requires recalibration.
4. Preserve frozen R14 Protocol, Study, source, baseline, preregistration, and
   local clean-room. Pass exact-source private CI, then create and verify the
   exact machine capability before any paid call. Run only its bounded
   pre-Release checkpoint with complete token, cost, retry, time, path, trace,
   and lineage evidence.
5. Review the corrected Selection result. On `HOLD`, seal the normal terminal
   result and stop. On `SELECT`, audit evidence first and request separate
   authorization for the 450-position Release-ID/OOD/Replay tail.
6. Generate the minimum ablations, uncertainty, four figures, limitations, and
   the terminal-kind-appropriate sanitized result package from sealed artifacts
   only; rerun clean-room, Secret/PII audit, and private CI.
7. Ask the Owner separately before changing repository visibility, publishing
   a Release, or submitting a paper/report.
