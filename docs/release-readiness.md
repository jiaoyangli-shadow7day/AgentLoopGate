# AgentLoopGate open-source and paper readiness

Status date: 2026-08-23

Current paid-evidence checkpoint: immutable `EXP_BANKING_R12`, stopped after
25 valid Update-Source positions, three external AHE candidates, and a 9/10-valid
A0 Update-Check anchor. It is terminal `HOLD` and cannot advance. The R13
successor integrity repair and local clean-room are complete. Its Protocol,
Study, source, `R13_A0` baseline, isolated Harness profile, and machine
preregistration (`2e6ed6…1961`) are frozen; only its exact paid machine
authorization remains absent, so paid execution remains fail-closed. The standing private-experiment
mandate permits the delegated operator to create the exact machine authorization
after every frozen input verifies; it does not permit publication or Promote.

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
| A0-bound Selection with abstention | IMPLEMENTED / ZERO-MODEL VERIFIED | Study schema 1.2; strict stable gain, zero stable regression, whole-attempt cost, retry/timeout and p95/max latency policy | Run only under a new frozen paid identity and exact machine authorization |
| Candidate semantic and runtime applicability | IMPLEMENTED / ZERO-MODEL VERIFIED | Semantic fingerprint/dedup and runtime Tool Schema capability binding | New external Updater must produce three distinct, bound candidates |
| Selection-HOLD normal terminal | IMPLEMENTED / ZERO-MODEL VERIFIED | Successful CLI outcome; immutable outcome/report/lineage/cost bindings; all candidates HELD; Release and post-Selection model calls fixed at zero; resume is verify-only | Exercise with real corrected Selection evidence |
| Exact paid-execution authorization | IMPLEMENTED / NOT YET CREATED FOR R13 | Frozen R13 preregistration `2e6ed6…1961`; Formal config 1.2 authorization root; preflight + Service double-check; first scope covers 125 formal positions and separately metered external Updater; Selection-bound Release scope is separate; HOLD blocks Release; standing mandate governs delegated creation | Verify final private CI, then create the exact capability artifact |
| DeepSeek Harness native Trace/Persistence/Telemetry coexistence | PASS FOR SYSTEM/FIXTURE EVIDENCE | Bundle lifecycle and headless conformance; JSONL/SQLite/OTel coexistence tests | Retain exact pin and rerun final clean-room |
| Full source/release-artifact clean-room | PASS LOCAL FOR R13 REPAIR SOURCE | 199 Python and 13 TypeScript tests; Ruff; sdist→wheel; Bundle tests/build/pack and DSH conformance passed in 22.38 s | Rerun after the final frozen R13 source and in private Linux CI |
| Secret and direct-PII audit | PASS FOR CURRENT TREE | 295 files scanned with zero findings and withheld paths/values | Rerun for frozen R13 and the final public result package |
| Corrected pre-Release paid checkpoint | R12 TERMINAL HOLD / R13 FROZEN PAID HOLD | R12 terminal seal `73457f…383e`; R13 incident `552d0c…ab65`; Protocol `645374…8488`, Study `5a629b…f011`, source `acf909…9c1a`, baseline `166954…ad2c`, preregistration `2e6ed6…1961` | Run final private CI, create exact authorization, then execute the bounded checkpoint |
| Real Release-ID/OOD/Replay | CONDITIONAL UNDER STANDING PRIVATE MANDATE | Software paths and deterministic Gate fixtures exist | Run only if corrected Selection returns `SELECT` and a separately bound machine capability verifies; skip on HOLD |
| Minimal ablations and uncertainty | PARTIAL / TWO NO-MODEL ABLATIONS SEALED | R12 integrity fixture proves an unsupported `SHIP_RECOMMENDED` is converted to `HOLD`; DSH fixture preserves JSONL/SQLite event hashes, persistence and OTel, with measured local p95 overhead 4.110417/0.740291 ms | Derive selector/diagnosis statistics and uncertainty from sealed R12 paid evidence without causal overclaim |
| Sanitized public Banking result package | BUILDER READY / RESULTS MISSING | Configuration-driven, fail-closed builder/verifier supports both a verified full formal Outcome and the distinct Selection-HOLD terminal | Build only from the terminal result, then rerun the independent verifier and public-tree audit |
| README, license, and third-party declarations | PASS LOCALLY | `README.md`, Apache-2.0 `LICENSE`, `THIRD_PARTY_NOTICES.md` | Recheck packaged archives and links |
| Private GitHub repository | PASS | `jiaoyangli-shadow7day/AgentLoopGate`, private visibility | Keep private until explicit Owner authorization |
| Version-controlled private CI seal | PASS FOR R12 EXECUTION SOURCE | R12 commit `ba75710`; clean-room run `32632677850`, job `97177688962`; 189 Python passed/1 platform skip, 13 TypeScript passed, 282-file scan zero findings; machine record `banking_r12/private_ci_validation.json`; repository remained private | Rerun for the final public commit and sanitized result package |
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
2. Do not rerun or extend R11 or R12. Preserve their terminal identities and
   all retained evidence. R13 is the only frozen successor execution identity;
   any execution-source change supersedes it rather than editing it.
3. After its exact machine capability verifies, run only the R13 125-position pre-Release checkpoint plus the
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
