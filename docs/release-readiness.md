# AgentLoopGate open-source and paper readiness

Status date: 2026-08-23

Current paid-evidence checkpoint: `EXP_BANKING_R10`, stopped after candidate C2
Selection. Current execution policy: `PAID_HOLD`.

This is the requirement-to-evidence checklist for the v1 release. Passing local
tests proves software behavior, not a positive self-evolution effect. A real
`HOLD/ABSTAIN` can complete the governance story when it is produced by the
corrected, baseline-bound Selection policy and all evidence is sealed.

## Acceptance matrix

| Requirement | State | Authoritative evidence | Remaining work |
|---|---|---|---|
| Preserve all historical attempts and incidents | PASS | R2–R10 immutable Snapshot/Batch/Raw/Trace/Attempt/Cost artifacts and append-only journals | Recheck hashes in the final publication seal |
| R10 execution through C2 Selection | SEALED HISTORICAL EVIDENCE | 25 Update-Source + 40 Update-Check + 30 Selection positions; C3 Selection and all Release stages absent | Never rewrite or resume under the corrected selector identity |
| Complete cost accounting through R10 C2 | PASS | Exact known model cost USD `3.0651904832`; batch, updater, task-attempt, Agent/User usage and retry evidence retained | Local compute monetary cost remains `unmetered_unknown` |
| Positive self-evolution direction | NOT ESTABLISHED | C1 and C2 both 7/15 with different success sets; C1/C3 semantic duplicate; C2 unbound capability | A new corrected experiment is required before any positive claim |
| A0-bound Selection with abstention | IMPLEMENTED / ZERO-MODEL VERIFIED | Study schema 1.2; strict stable gain, zero stable regression, whole-attempt cost, retry/timeout and p95/max latency policy | Run only under a new frozen paid identity after Owner authorization |
| Candidate semantic and runtime applicability | IMPLEMENTED / ZERO-MODEL VERIFIED | Semantic fingerprint/dedup and runtime Tool Schema capability binding | New external Updater must produce three distinct, bound candidates |
| Selection-HOLD normal terminal | IMPLEMENTED / ZERO-MODEL VERIFIED | Successful CLI outcome; immutable outcome/report/lineage/cost bindings; all candidates HELD; Release and post-Selection model calls fixed at zero; resume is verify-only | Exercise with real corrected Selection evidence |
| DeepSeek Harness native Trace/Persistence/Telemetry coexistence | PASS FOR SYSTEM/FIXTURE EVIDENCE | Bundle lifecycle and headless conformance; JSONL/SQLite/OTel coexistence tests | Retain exact pin and rerun final clean-room |
| Full source/release-artifact clean-room | PASS LOCALLY | 176 Python tests, 13 TypeScript tests, sdist→wheel install, Bundle build/pack, DSH headless conformance | Require green private GitHub CI after final source commit |
| Secret and direct-PII audit | PASS FOR CURRENT TREE | 256 files scanned, zero findings; paths/values withheld | Rerun after public result package is assembled |
| Corrected pre-Release paid checkpoint | NOT RUN / NOT AUTHORIZED | Planned 25 Update-Source + 40 Update-Check + 60 Selection = 125 positions, plus separately metered Updater | Freeze a new Protocol/Study/Experiment/Baseline and obtain explicit Owner authorization |
| Real Release-ID/OOD/Replay | CONDITIONAL / NOT AUTHORIZED | Software paths and deterministic Gate fixtures exist | Run only if corrected Selection returns `SELECT`, after a second Owner review; skip on HOLD |
| Minimal ablations and uncertainty | PARTIAL | Integrity and plugin-coexistence ablations exist; corrected selector behavior is fixture-tested | Derive selector/diagnosis statistics from the next sealed evidence without causal overclaim |
| Sanitized public Banking result package | BUILDER READY / RESULTS MISSING | Fail-closed builder/verifier and package contract | Build only from the next valid terminal result, including a valid Selection-HOLD if that is the outcome |
| README, license, and third-party declarations | PASS LOCALLY | `README.md`, Apache-2.0 `LICENSE`, `THIRD_PARTY_NOTICES.md` | Recheck packaged archives and links |
| Private GitHub repository | PASS | `jiaoyangli-shadow7day/AgentLoopGate`, private visibility | Keep private until explicit Owner authorization |
| Public visibility, Release, or submission | NOT AUTHORIZED | Active Goal and SPEC trust boundary | Requires a separate explicit Owner instruction after final acceptance |

## What the current evidence proves

R10 supports the engineering claim that AgentLoopGate can preserve DeepSeek
Harness native traces, retain failure/retry/time/cost evidence, fail closed on
integrity problems, and audit candidate decisions. It does not support the
scientific claim that the observed candidates found the correct self-evolution
direction. The corrected selector exists precisely because continuing the old
experiment would have manufactured a winner without showing improvement over
A0.

## Cost interpretation

- Known provider/model cost through R10 C2: exact USD `3.0651904832`.
- Model cost for the Selection correction and current clean-room work: USD `0`;
  all such operations made zero external model calls.
- Local CPU, filesystem, package, and wall-clock monetary cost:
  `unmetered_unknown`, never represented as zero.
- Any future partial or unavailable cost must remain a lower bound with named
  unknown scope; it cannot participate as an exact ranking value.

## Required completion order

1. Keep R10 and every prior failure immutable; finish the current no-model
   documentation, artifact, and private-CI seal.
2. Prepare a new content-addressed Protocol, Study, Experiment, A0, semantic
   candidate plan, and paid-scope estimate. Do not start it without explicit
   Owner authorization.
3. If authorized, run only the 125-position pre-Release checkpoint plus the
   separately metered external Updater. Current sequential estimate is 15–25
   hours; actual token, retry, time, path, and cost records remain mandatory.
4. Review the corrected Selection result. On `HOLD`, seal the normal terminal
   result and stop. On `SELECT`, audit evidence first and request separate
   authorization for the 450-position Release-ID/OOD/Replay tail.
5. Generate the minimum ablations, uncertainty, four figures, limitations, and
   sanitized result package from sealed artifacts only; rerun clean-room,
   Secret/PII audit, and private CI.
6. Ask the Owner separately before changing repository visibility, publishing
   a Release, or submitting a paper/report.
