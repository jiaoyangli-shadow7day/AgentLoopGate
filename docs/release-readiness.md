# AgentLoopGate open-source and paper readiness

Status date: 2026-08-23

Current paid-evidence checkpoint: immutable `EXP_BANKING_R10`, stopped after
candidate C2 Selection, plus immutable `EXP_BANKING_R11` Update-Source evidence.
R11 has 24 valid runs and one Infra Invalid and is sealed as a batch `HOLD`;
it cannot advance to Update-Check or Selection. Current execution policy:
`PAID_HOLD` pending a new successor identity and explicit Owner authorization.

This is the requirement-to-evidence checklist for the v1 release. Passing local
tests proves software behavior, not a positive self-evolution effect. A real
`HOLD/ABSTAIN` can complete the governance story when it is produced by the
corrected, baseline-bound Selection policy and all evidence is sealed.

## Acceptance matrix

| Requirement | State | Authoritative evidence | Remaining work |
|---|---|---|---|
| Preserve all historical attempts and incidents | PASS | R2–R11 immutable Snapshot/Batch/Raw/Trace/Attempt/Cost artifacts and append-only journals | Recheck hashes in the final publication seal |
| R10 execution through C2 Selection | SEALED HISTORICAL EVIDENCE | 25 Update-Source + 40 Update-Check + 30 Selection positions; C3 Selection and all Release stages absent | Never rewrite or resume under the corrected selector identity |
| Complete cost accounting through R10 C2 | PASS | Exact known model cost USD `3.0651904832`; batch, updater, task-attempt, Agent/User usage and retry evidence retained | Local compute monetary cost remains `unmetered_unknown` |
| Positive self-evolution direction | NOT ESTABLISHED | C1 and C2 both 7/15 with different success sets; C1/C3 semantic duplicate; C2 unbound capability | A new corrected experiment is required before any positive claim |
| A0-bound Selection with abstention | IMPLEMENTED / ZERO-MODEL VERIFIED | Study schema 1.2; strict stable gain, zero stable regression, whole-attempt cost, retry/timeout and p95/max latency policy | Run only under a new frozen paid identity after Owner authorization |
| Candidate semantic and runtime applicability | IMPLEMENTED / ZERO-MODEL VERIFIED | Semantic fingerprint/dedup and runtime Tool Schema capability binding | New external Updater must produce three distinct, bound candidates |
| Selection-HOLD normal terminal | IMPLEMENTED / ZERO-MODEL VERIFIED | Successful CLI outcome; immutable outcome/report/lineage/cost bindings; all candidates HELD; Release and post-Selection model calls fixed at zero; resume is verify-only | Exercise with real corrected Selection evidence |
| Explicit paid-execution authorization | IMPLEMENTED / PAID_HOLD | Formal config 1.2 authorization root; preflight + Service double-check; first scope covers 125 formal positions and separately metered external Updater; Selection-bound 450-position Release scope is separate; HOLD blocks Release | No authorization artifact exists; wait for explicit Owner scope approval |
| DeepSeek Harness native Trace/Persistence/Telemetry coexistence | PASS FOR SYSTEM/FIXTURE EVIDENCE | Bundle lifecycle and headless conformance; JSONL/SQLite/OTel coexistence tests | Retain exact pin and rerun final clean-room |
| Full source/release-artifact clean-room | PASS LOCAL + PRIVATE LINUX | Post-result-package local check: 185 Python and 13 TypeScript tests; sdist→wheel, archive guard, Bundle build/pack and DSH conformance passed. Commit `9a48956` passed private CI run `32620190226`, job `97147090957`, in 58 s | Rerun after any later execution-source change |
| Secret and direct-PII audit | PASS FOR CURRENT TREE | Post-result-package audit scanned 272 files with zero findings and withheld paths/values | Rerun for the final public result package |
| Corrected pre-Release paid checkpoint | R12 FROZEN / PAID_HOLD | R12 Protocol `6c86b4…d3f2`, Study `423ca8…32a4`, source `d7f8e3…65bd`, Evaluation Baseline `R12_A0`; Cost-Lineage Calibration 1.2 binds the R11 incident and repair | Obtain explicit Owner authorization before the R12 Updater or any formal position |
| Real Release-ID/OOD/Replay | CONDITIONAL / NOT AUTHORIZED | Software paths and deterministic Gate fixtures exist | Run only if corrected Selection returns `SELECT`, after a second Owner review; skip on HOLD |
| Minimal ablations and uncertainty | PARTIAL | Integrity and plugin-coexistence ablations exist; corrected selector behavior is fixture-tested | Derive selector/diagnosis statistics from the next sealed evidence without causal overclaim |
| Sanitized public Banking result package | BUILDER READY / RESULTS MISSING | Configuration-driven, fail-closed builder/verifier supports both a verified full formal Outcome and the distinct Selection-HOLD terminal | Build only from the terminal result, then rerun the independent verifier and public-tree audit |
| README, license, and third-party declarations | PASS LOCALLY | `README.md`, Apache-2.0 `LICENSE`, `THIRD_PARTY_NOTICES.md` | Recheck packaged archives and links |
| Private GitHub repository | PASS | `jiaoyangli-shadow7day/AgentLoopGate`, private visibility | Keep private until explicit Owner authorization |
| Version-controlled private CI seal | PASS | Commits `f6bd641` and `9a48956`; latest clean-room run `32620190226`, job `97147090957`; machine record `banking_r11/private_ci_validation.json`; repository remained private | Preserve the runs; require another green run for future execution-source changes |
| Public visibility, Release, or submission | NOT AUTHORIZED | Active Goal and SPEC trust boundary | Requires a separate explicit Owner instruction after final acceptance |

## What the current evidence proves

R10 and the R11 Source HOLD support the engineering claim that AgentLoopGate
can preserve DeepSeek Harness native traces, retain failure/retry/time/cost
evidence, recover and seal immutable evidence, fail closed on integrity
problems, and audit candidate decisions. They do not support the scientific
claim that an observed candidate found the correct self-evolution direction.
The corrected selector exists precisely because continuing the old experiment
would have manufactured a winner without showing improvement over A0.

## Cost interpretation

- Known provider/model cost through R10 C2: exact USD `3.0651904832`.
- R11 Source observed-attempt provider-cost lower bound: USD
  `0.7266205472000000021`; direct valid Agent/User costs are USD
  `0.5385791880` and USD `0.08244740`. It is a held, incomplete batch, not a
  cross-stage result or an effectiveness claim.
- Model cost for the Selection correction, evidence sealing, and clean-room work:
  USD `0`; those operations made zero external model calls.
- Local CPU, filesystem, package, and wall-clock monetary cost:
  `unmetered_unknown`, never represented as zero.
- Any future partial or unavailable cost must remain a lower bound with named
  unknown scope; it cannot participate as an exact ranking value.

## Required completion order

1. Keep R10, R11, and every prior failure immutable; preserve their artifacts,
   cost records, recovery records, and private-CI seals.
2. Do not rerun or extend R11. Preserve the frozen R12 Protocol, Study,
   Experiment, `R12_A0`, semantic candidate plan, and paid-scope estimate; any
   execution-source change supersedes this identity rather than editing it.
3. If authorized, run only the R12 125-position pre-Release checkpoint plus the
   separately metered external Updater. Current sequential estimate is 15–25
   hours; actual token, retry, time, path, and cost records remain mandatory.
4. Review the corrected Selection result. On `HOLD`, seal the normal terminal
   result and stop. On `SELECT`, audit evidence first and request separate
   authorization for the 450-position Release-ID/OOD/Replay tail.
5. Generate the minimum ablations, uncertainty, four figures, limitations, and
   the terminal-kind-appropriate sanitized result package from sealed artifacts
   only; rerun clean-room, Secret/PII audit, and private CI.
6. Ask the Owner separately before changing repository visibility, publishing
   a Release, or submitting a paper/report.
