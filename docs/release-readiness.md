# AgentLoopGate open-source and paper readiness

Status date: 2026-08-24

Current paid-evidence checkpoint: immutable `EXP_BANKING_R14`. It executed 46
of 125 authorized positions: 25 valid Update-Source, 10 valid A0 Update-Check,
10 valid first-candidate Update-Check, and one second-candidate Infra Invalid.
Protocol 2.0 fail-fast stopped before the next position and made zero model
calls after the trigger. The external Updater completed four exact-cost proposal
attempts and selected three candidates. A0 scored 4/10; the only complete
candidate scored 3/10 and regressed `task_052`. The next candidate revealed that
Candidate Check validated baseline routing bytes rather than post-patch bytes.
Selection, Release, and Promote remained at zero. R14 is therefore terminal
`HOLD`, not a positive self-evolution result. The standing private-experiment
mandate permits a newly frozen successor after all exact machine gates pass; it
does not permit publication, repository visibility changes, or Promote.

This is the requirement-to-evidence checklist for the v1 release. Passing local
tests proves software behavior, not a positive self-evolution effect. A real
`HOLD/ABSTAIN` can complete the governance story when it is produced by the
corrected, baseline-bound Selection policy and all evidence is sealed.

## Acceptance matrix

| Requirement | State | Authoritative evidence | Remaining work |
|---|---|---|---|
| Preserve all historical attempts and incidents | PASS | R2–R14 immutable Snapshot/Batch/Raw/Trace/Attempt/Cost artifacts and append-only journals, including explicit absent Batch/Cost for the R14 terminal incident | Recheck hashes in the final publication seal |
| R10 execution through C2 Selection | SEALED HISTORICAL EVIDENCE | 25 Update-Source + 40 Update-Check + 30 Selection positions; C3 Selection and all Release stages absent | Never rewrite or resume under the corrected selector identity |
| Complete cost accounting through R10 C2 | PASS | Exact known model cost USD `3.0651904832`; batch, updater, task-attempt, Agent/User usage and retry evidence retained | Local compute monetary cost remains `unmetered_unknown` |
| Positive self-evolution direction | NOT ESTABLISHED | R14 A0 was 4/10; only complete candidate was 3/10 and regressed `task_052`; remaining candidates incomplete; Selection zero | A newly frozen successor is required before any positive claim |
| A0-bound Selection with abstention | IMPLEMENTED / NOT REACHED IN R14 | Study `e2afe1…35d96`; strict stable gain, zero stable regression, whole-attempt cost, retry/timeout and p95/max latency policy | Exercise only after successor candidate precheck and terminal-sealing repairs pass |
| Candidate semantic and runtime applicability | R14 GAPS REPAIRED / SUCCESSOR NOT FROZEN | Post-patch isolated validation rejects both malformed real R14 routing candidates; R14-shaped partial fail-fast fixture seals HOLD/exact cost and resumes without execution | Run full clean-room, then freeze successor source |
| Selection-HOLD normal terminal | IMPLEMENTED / ZERO-MODEL VERIFIED | Successful CLI outcome; immutable outcome/report/lineage/cost bindings; all candidates HELD; Release and post-Selection model calls fixed at zero; resume is verify-only | Exercise with real corrected Selection evidence |
| Position-level permanent-Infra fail-fast | PASS IN REAL R14 EXECUTION | Trigger `c3a8e4…f5052`; two failed attempts retained; next position and post-trigger calls zero; 79 later authorized positions did not start | Preserve R14; carry the control into the successor |
| Exact paid-execution authorization | PASS / R14 CONSUMED AND TERMINAL | `AUTH_5FA037EDA2B6782B4C57`, digest `d21a92…d9dd8`, bound exact R14 25/40/60 scope | Never reuse it; mint a new exact capability only after successor freeze |
| DeepSeek Harness native Trace/Persistence/Telemetry coexistence | PASS FOR SYSTEM/FIXTURE EVIDENCE | Bundle lifecycle and headless conformance; JSONL/SQLite/OTel coexistence tests | Retain exact pin and rerun final clean-room |
| Full source/release-artifact clean-room | PASS LOCAL FOR SUCCESSOR REPAIR SOURCE | 213 Python and 13 TypeScript tests; Ruff, sdist→wheel, DSH conformance/build/pack and audit passed in 17.57 s; content-addressed repair validation included | Pass exact-source private Linux CI and repeat for the final public tree |
| Secret and direct-PII audit | PASS FOR SUCCESSOR REPAIR TREE | 321 files scanned with zero findings and withheld paths/values | Repeat in private CI and for the final public result package |
| Corrected pre-Release paid checkpoint | R14 TERMINAL HOLD | 46 positions, 45 valid; total exact cost USD `1.4876297096000000032`; incident `adc163…1f26`; seal `b82bdb…23e5` | Never resume R14; repair and freeze a successor identity |
| Real Release-ID/OOD/Replay | CONDITIONAL UNDER STANDING PRIVATE MANDATE | Software paths and deterministic Gate fixtures exist | Run only if corrected Selection returns `SELECT` and a separately bound machine capability verifies; skip on HOLD |
| Minimal ablations and uncertainty | PARTIAL / TWO NO-MODEL ABLATIONS SEALED | R12 integrity fixture proves an unsupported `SHIP_RECOMMENDED` is converted to `HOLD`; DSH fixture preserves JSONL/SQLite event hashes, persistence and OTel, with measured local p95 overhead 4.110417/0.740291 ms | Derive selector/diagnosis statistics and uncertainty from sealed R12 paid evidence without causal overclaim |
| Sanitized public Banking result package | BUILDER READY / SUCCESSOR RESULTS MISSING | Configuration-driven, fail-closed builder/verifier supports verified full formal Outcome, Selection-HOLD, and candidate-invalid Batch-HOLD terminal evidence | Build only from the successor terminal result, then rerun the independent verifier and public-tree audit |
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

R14 adds real systems evidence. It completed a full Source, external Updater,
the A0 Check, and one paired candidate Check with exact costs; fail-fast then
stopped a malformed second candidate before any later position. This validates
position-level waste control and exposes a prospective-byte validation gap. It
still cannot contribute a positive effectiveness claim because the only full
candidate underperformed A0 and Selection never ran.

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
- R14 exact Provider/model cost: USD `1.4876297096000000032`, comprising Source
  `0.8244735576`, Updater `0.0140907872`, A0 Check `0.2986731776`, first-candidate
  Check `0.3498881872000000032`, and the terminal invalid candidate's two User
  calls `0.000504`. Unknown and unresolved model-cost scopes are zero.
- Local CPU, filesystem, package, and wall-clock monetary cost:
  `unmetered_unknown`, never represented as zero.
- Any future partial or unavailable cost must remain a lower bound with named
  unknown scope; it cannot participate as an exact ranking value.

## Required completion order

1. Keep R10, R11, and every prior failure immutable; preserve their artifacts,
   cost records, recovery records, and private-CI seals.
2. Do not rerun or extend R11, R12, R13, or R14. Preserve their terminal identities
   and all retained evidence.
3. Preserve the completed Protocol 2.0 fail-fast calibration `b098b6…e573`,
   including experiment-scoped candidate diagnostics and the
   DNS-only Provider precheck; any runtime-byte change requires recalibration.
4. Preserve the R14 incident and terminal seal. Keep the repaired post-patch
   candidate validator and candidate-specific Batch-HOLD/exact-cost path;
   finish the full no-model clean-room and real-candidate regression fixtures.
5. Freeze a new Protocol, Study, source revision, evaluation baseline, private
   CI record, and exact machine capability. Review its Selection result. On `HOLD`, seal the normal terminal
   result and stop. On `SELECT`, audit evidence first and request separate
   authorization for the 450-position Release-ID/OOD/Replay tail.
6. Generate the minimum ablations, uncertainty, four figures, limitations, and
   the terminal-kind-appropriate sanitized result package from sealed artifacts
   only; rerun clean-room, Secret/PII audit, and private CI.
7. Ask the Owner separately before changing repository visibility, publishing
   a Release, or submitting a paper/report.
