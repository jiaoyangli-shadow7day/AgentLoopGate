# Banking R11 corrected checkpoint preregistration

Status: immutable partial execution and sealed Update-Source `HOLD`.

R11 is the first experiment identity that implements the corrected,
baseline-bound Selection policy discovered after R10 C2. It does not erase or
reinterpret R10. R10 remains immutable historical and engineering evidence;
none of its model outcomes is a decision-grade R11 input.

## Execution record and terminal boundary

Under a narrowly scoped Owner authorization, only the existing 25-position
Update-Source batch was run. Its immutable batch ID is
`B_669A312AC9B41B2F6207`; the batch contains 24 valid runs and one Infra Invalid
(`task_020`) and is sealed as `HOLD` for `infra_invalid:1` and
`missing_valid_trials`. Exact valid-run direct costs are Agent USD
`0.5385791880` and User Simulator USD `0.08244740`; the whole observed-attempt
provider-cost lower bound is USD `0.7266205472000000021`. Local-compute
monetary cost remains `unmetered_unknown`.

No external Updater, Update-Check, Selection, Release-ID, Release-OOD, or Replay
call was made. The batch cannot advance to another R11 stage and must never be
rerun under the same identity. A lineage-recovery implementation defect was
fixed and the existing evidence was sealed without model calls; the repair does
not alter the frozen Protocol, Study, raw evidence, or result meaning. Any
complete successor study must use a new frozen experiment identity and a new
Owner authorization.

## Frozen identity

| Input | Frozen value |
|---|---|
| Experiment | `EXP_BANKING_R11` |
| Formal config | `configs/formal_experiment_r11.yaml`, schema 1.2 |
| Protocol | `BANKING_R11_PROTOCOL_1`, schema 1.8, `sha256:68b03d74f7195b80928c61fdd79f713fe3bcbba0c0df3b054763c4d88bb663ea` |
| Study | `BANKING_R11_STUDY_1`, schema 1.2, `sha256:97de7e47fd2328f568b74b70f23cc6347adae477d9bc1db81984ec641ca05ebb` |
| Execution source | `tree:sha256:c392a3af0afadd566bd21169d11e63684312921c1e1fbab24f13cefb88bebee0` |
| Evaluation baseline | `R11_A2`, `sha256:c65cec1e852e1840d04a556f595b99e788bc7099b3afd084e6401209ccf5a2bb` |
| Active deployment | `A0`; unchanged |

`R11_A0` and `R11_A1` are retained as superseded preparation baselines. A0 was
captured before the external-Updater authorization boundary; A1 preceded the
bounded sdist builder correction described below. Neither they nor A2 were
activated.

## Exact paid checkpoint

The first Owner scope contains 125 formal task positions:

| Stage | Variants | Tasks × trials | Positions |
|---|---:|---:|---:|
| Update-Source | A0 | 25 × 1 | 25 |
| Update-Check | A0 + 3 candidates | 10 × 1 | 40 |
| Selection | A0 + 3 candidates | 15 × 1 | 60 |

External AHE generation is included in the same Owner scope but is separately
metered and is not counted as a formal task position. The orchestrator verifies
`external_updater_generation_authorized=true` immediately before the first AHE
call. The six-proposal ceiling is frozen. Candidate Check must yield exactly
three executable, semantically distinct siblings across at least two asset
families. Tool-routing candidates must bind the current runtime Tool Schema;
static unknown capabilities fail closed. If the proposal budget cannot produce
that ladder, the run stops before Update-Check rather than widening policy.

Selection requires a strict stable-task gain over A0 and no stable-task
regression. Whole-attempt cost and p95 latency may be at most 1.2× A0; retry and
timeout increases must both be zero. Correctness and safety precede operational
ranking. If no candidate passes, `HOLD/ABSTAIN` is a successful terminal result
and no Release call is made.

Release-ID, Release-OOD, and Replay total 450 positions and are outside this
scope. They require a verified `SELECT` plus a second explicit Owner
authorization. `HOLD` permanently blocks that tail.

## Time and cost planning

R10 observations give a sequential wall-clock estimate of 15–25 hours: 2.23 h
for Update-Source, 4.79 h for four Update-Check variants, about 7.4 h for four
Selection variants, plus candidate generation, retry, and variance allowance.

The non-gating budget estimate is approximately USD 4.05: linear scaling of
R10's exact USD 3.0651904832 across 95 formal positions to 125 positions gives
USD 4.0331453726, plus R10-like Updater generation around USD 0.0116856824.
Because task paths and retries vary, the working planning range is USD 3.5–6.5.
This is neither an exact future cost nor an authorization or stopping Gate.
Every actual Agent, User Simulator, and Updater call must retain exact tokens,
price, cost, retry, task/attempt/session lineage, duration, execution path, and
unknown scope. Local compute monetary cost remains `unmetered_unknown`.

## Zero-model readiness

The final-source `R11-NM-008` clean-room passed 183 Python and 13 TypeScript tests,
sdist-to-wheel installation, DeepSeek Harness headless conformance, plugin
build/pack, and a 269-file Secret/PII scan with zero findings. It took 17.11 s
real, 13.14 s user CPU, and 3.69 s system CPU; maximum RSS was 350,109,696
bytes and peak measured footprint was 1,327,440 bytes.

The first post-preregistration clean-room was deliberately interrupted after
260.72 s when inspection proved Flit 3.12 was recursively scanning the ignored,
append-only `runs/bridge/requests` directory while expanding a default exclude
glob. The source distribution never needs those bytes. The build backend now
uses the exact declared package/metadata allowlist; a standalone sdist completed
in 1.12 s with 72 entries and no root runtime-evidence directory. This packaging
correction changed execution source and therefore superseded `R11_A1`; the final
identity was re-frozen as `R11_A2` rather than silently editing a Snapshot.

The isolated `runs/dsh/r11-home` Profile contains the same content-addressed
plugin package and profile files verified for R10. Current preflight passes all
frozen-input checks and deliberately fails on two absent authorities: the API
credential is not present in this process and the Owner authorization artifact
does not exist. Credential presence alone would still be insufficient.

The machine-readable pre-execution preregistration is
`artifacts/research/banking_r11/pre_run_preregistration.json`. No command in this
changed repository visibility, published a Release, or submitted a report.
preparation invoked a model, created paid authorization, promoted a Snapshot,
changed repository visibility, published a Release, or submitted a report.
The subsequent bounded Update-Source execution is recorded above and in the
append-only private experiment evidence; it did not perform any of those other
actions.
changed repository visibility, published a Release, or submitted a report.
