# AgentLoopGate open-source and paper readiness

Status date: 2026-08-25

Current paid-evidence checkpoint: terminal `EXP_BANKING_R15` Selection-HOLD.
It completed all 125 authorized pre-Release positions: 25 Update-Source, 40
Update-Check, and 60 baseline-bound Selection positions. All nine batches have
complete integrity, exact cost accounting, and zero Infra Invalid runs. AHE
produced three candidates. Selection scores were A0 6/15, candidate 1 6/15,
candidate 2 5/15, and candidate 3 6/15. Every candidate regressed the same A0
successes `task_062` and `task_095`; candidate 2 also regressed `task_056`.
AgentLoopGate held all three candidates under the frozen strict-gain,
zero-regression and operational-evidence policy. Release, Promote, visibility
change, and publication remained at zero.

The terminal outcome is
`827ed2…bdc3`; exact known model cost is USD `3.9086647880000000116`,
with no unknown model-cost scope. A sanitized 18-file local result package has
independently verified at manifest `79e9a8…364c8` with zero Secret/direct-PII
findings and `publication_authorized: false`. This completes the corrected
governance story but does not establish a positive AHE self-evolution result.
The repository must remain private until a separate Owner publication action.

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
| Positive self-evolution direction | NOT ESTABLISHED / GOVERNANCE DIRECTION ESTABLISHED | R15 candidates scored 6/15, 5/15, 6/15 versus A0 6/15; all regressed 062/095 and were held | Test any new guided updater only under a new frozen identity and untouched confirmation split |
| A0-bound Selection with abstention | PASS IN REAL R15 EXECUTION | Selection `b5e800…00466`; paired task surface, whole-attempt cost, retry/timeout and p95 policy produced terminal HOLD | Preserve as the primary governance result |
| Candidate semantic and runtime applicability | PASS / R15 FROZEN | Post-patch isolated validation rejects both malformed real R14 routing candidates; R15 calibration `5280db…9f16` binds prospective bytes, partial HOLD/exact cost, and verify-only resume | Preserve exact bytes through private CI and paid authorization |
| Selection-HOLD normal terminal | PASS IN REAL R15 EXECUTION | Outcome `827ed2…bdc3`; all candidates HELD; Release batches and post-Selection model calls zero; exact cost and lineage sealed | Preserve and independently verify from the sanitized package |
| Position-level permanent-Infra fail-fast | PASS IN REAL R14 EXECUTION | Trigger `c3a8e4…f5052`; two failed attempts retained; next position and post-trigger calls zero; 79 later authorized positions did not start | Preserve R14; carry the control into the successor |
| Exact paid-execution authorization | PASS / CONSUMED | R15 machine capability `AUTH_B5C002E677E9EBADF70D` bound exactly 25+40+60 positions and external Updater; no Release scope | Do not reuse or broaden it |
| DeepSeek Harness native Trace/Persistence/Telemetry coexistence | PASS FOR SYSTEM/FIXTURE EVIDENCE | Bundle lifecycle and headless conformance; JSONL/SQLite/OTel coexistence tests | Retain exact pin and rerun final clean-room |
| Full source/release-artifact clean-room | PASS LOCAL + PRIVATE LINUX FOR R15 | Latest private CI: 216 Python passed + 2 skipped, 13 TypeScript; Ruff, sdist→wheel, DSH conformance/build/pack passed | Repeat for the final publication commit |
| Secret and direct-PII audit | PASS FOR R15 FROZEN TREE | Latest private CI scanned 348 files with zero findings and withheld paths/values | Repeat for the final publication commit |
| Corrected pre-Release paid checkpoint | R15 TERMINAL HOLD | 125/125 positions, 125 valid, zero Infra Invalid; exact known model cost USD `3.9086647880000000116`; outcome `827ed2…bdc3` | No paid continuation is required or permitted under R15 |
| Real Release-ID/OOD/Replay | CONDITIONAL UNDER STANDING PRIVATE MANDATE | Software paths and deterministic Gate fixtures exist | Run only if corrected Selection returns `SELECT` and a separately bound machine capability verifies; skip on HOLD |
| Minimal ablations and uncertainty | PASS FOR HOLD STORY / LIMITED | R15 integrity `4ccbf1…1720`; DSH `7ae1a9…b66c`; three 10,000-resample paired Selection intervals sealed at statistics `8bc2da…5b8ba` | Treat fixture overhead and the three dependent candidates as descriptive, not causal |
| Sanitized public Banking result package | PASS LOCALLY / NOT PUBLISHED | 18 files including four Selection-only figures and a technical report; manifest `79e9a8…364c8`; independent verification and Secret/PII scan passed; publication flag false | Re-run at the final publication commit |
| README, license, and third-party declarations | PASS LOCALLY | `README.md`, Apache-2.0 `LICENSE`, `THIRD_PARTY_NOTICES.md` | Recheck packaged archives and links |
| Private GitHub repository | PASS | `jiaoyangli-shadow7day/AgentLoopGate`, private visibility | Keep private until explicit Owner authorization |
| Version-controlled private CI seal | PASS FOR R15 FROZEN IDENTITY | Commit `4f4c70c`, run `32755701628`, job `97522620797`; 216 Python passed/2 skips, 13 TypeScript, 348-file scan zero findings; repository remained private | Repeat for the v1.1 evidence package commit |
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

R15 supplies the corrected terminal result. It completed the entire authorized
pre-Release surface and shows that all three AHE candidates gained `task_017`
while all three lost `task_062` and `task_095`. Two aggregate ties therefore
hid ability exchanges. AgentLoopGate's paired zero-regression gate correctly
abstained, produced no Release calls, and retained exact cost and latency
evidence. This establishes useful evidence-governance behavior, not positive
candidate evolution or cross-domain generalization.

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
- R15 exact known Provider/model cost is USD `3.9086647880000000116`: nine
  formal batches cost `3.8830976464000000116` and external Updater calls cost
  `0.0255671416`. Unknown model-cost scope and unresolved Updater calls are
  zero. The formal process wall time was 52,591.59 seconds.
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
4. Preserve the R14 incident and terminal seal. R15 has frozen the repaired
   post-patch candidate validator, partial Batch-HOLD/exact-cost path, new
   Protocol, Study, source revision, baseline, and preregistration.
5. Preserve the terminal R15 HOLD, its consumed pre-Release capability, exact
   cost evidence, publication-tool incidents, and the verified sanitized package.
6. Run final clean-checkout build/install/test, Secret/PII audit and private CI
   at the intended open-source commit; finish report prose and limitations.
7. Ask the Owner separately before changing repository visibility, publishing
   a Release, or submitting a paper/report.
