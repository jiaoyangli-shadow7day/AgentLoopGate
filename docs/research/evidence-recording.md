# Experiment evidence and cost recording standard

This is the minimum record required for a Banking formal execution to be usable as
open-source or paper evidence. A score without this record is not a valid
experiment result.

## Evidence layers

| Layer | Unit | Required identity and measurements | Authority |
|---|---|---|---|
| Operator journal | Every manual command, diagnosis, edit, retry, and external run | UTC time or explicit unknown, command purpose, inputs, output/exit, wall time, failure and recovery, model-call count, cost status | Narrative chronology; never replaces machine evidence |
| Attempt ledger | One formal or deterministic operation | Attempt/event IDs, protocol/Study/source/spec identities, stage/batch/Snapshot/Candidate, command, STARTED and terminal times, duration, exit, resume flag, counters, output hashes, error/recovery, cost status | Machine-verifiable workflow lifecycle |
| Model-usage ledger | One provider-facing model call | Call/event IDs, session hash, model, STARTED and terminal times, tokens, provider retries, duration, exit/error, cost value and status | Whole-attempt model usage, including failed or unretained calls |
| Raw benchmark evidence | One immutable τ³ batch output | Batch ID/spec digest, task/trial population, timestamps, termination reason, retained provider usage | Upstream outcome and usage source |
| Trace evidence | One host/benchmark evidence plane | SourceTraceRef, cursor range, event count, source revision, Receipt, normalized record digest, cross-plane Join | Execution lineage and completeness |
| Batch and cost artifacts | One formal batch | Batch/spec digest, all run/receipt/join IDs, summary, disposition/HOLD reasons; valid and Infra Invalid cost partitions | Denominator, integrity, and cost reconciliation |
| Analysis artifacts | Frozen role assignment and six comparisons | Logical/unique/reused counts, batch and summary digests, effective bootstrap seeds, estimates and intervals | Publication statistics and selector contrast |
| Terminal governance evidence | Selection-HOLD, or two selector Decisions plus one governed Release report | Selection/Decision, Lineage, report, outcome and figure hashes; cost refs; skipped-stage proof | Final recommendation or abstention; never automatic deployment |

## Lifecycle invariants

- Write STARTED before invoking a model, benchmark, updater, subprocess, or
  deterministic formal step.
- Write exactly one terminal event: COMPLETED or FAILED. A process crash must
  leave the STARTED event visible; recovery must record and reconcile it rather
  than deleting it.
- Event files and content-addressed artifacts are write-once. Re-running the
  same identity verifies/reuses identical bytes. Different bytes under the same
  identity are corruption, not a new result.
- A logging failure aborts protocol-bound work. “The experiment succeeded but
  the logger failed” is not an acceptable result state.
- Manual/pre-ledger failures remain in the operator journal with unknown fields
  left unknown. Never invent an Attempt ID, timestamp, duration, token count, or
  price after the fact.
- Record skipped stages after a failure. A later success does not imply those
  stages executed in the failed run.

## Cost semantics

Cost has separate scopes and must not be collapsed into one optimistic number.

| Status | Meaning | Permitted value |
|---|---|---|
| `pending` | STARTED event has no terminal evidence yet | No numeric cost |
| `exact` | All calls and billed usage in the stated scope are observed | Exact non-negative USD value |
| `partial` | Some cost is known, but retry/failure/unretained billing is incomplete | Known lower bound plus an explicit missing scope |
| `unavailable` | A model call or billed scope occurred but no defensible numeric amount is available | `null`, never zero |
| `not_applicable` | The operation provably made zero model calls | Known model spend USD 0; infrastructure cost remains separate |

For every paid batch report:

- valid and Infra Invalid run counts;
- retained agent and user-simulator calls/tokens;
- cache-read tokens;
- provider retry count;
- unresolved and unretained calls;
- valid agent/user cost;
- Infra Invalid agent/user cost, including nulls;
- observed whole-attempt cost or a lower bound;
- the cost denominator used by each metric.

Local CPU, filesystem, dependency download, and wall time are not model cost.
If no monetary meter exists, report duration plus `unmetered_unknown`. GitHub
Actions cost is `unavailable_unknown` unless an authoritative billing record is
captured. Neither may be printed as USD 0 merely because the workflow made no
model calls.

## Time and execution-path reporting

Preserve both machine durations and human-visible wall time where available.
For retries, distinguish:

1. provider-internal retries;
2. DSH call/process retries;
3. τ³ simulation retries;
4. an operator resume of an immutable batch;
5. a no-model verification/reuse pass.

Report the path actually taken, including timeouts, partial setup, package
resolution, queue time, skipped stages, and recovery. Do not substitute a
successful rerun's duration for a failed predecessor.

## Infra Invalid and missing evidence

Infrastructure failure is not task failure and not success. It is reported in
a separate denominator. A batch with any Infra Invalid run or incomplete
evidence is HOLD and cannot enter the registered bootstrap analysis. Missing
cost, Trace, Receipt, Join, reset proof, or expected task/trial coverage is an
integrity failure; it cannot be repaired by filling zeros or dropping rows.

If a fresh symmetric rerun is authorized, retain the original failed batch and
give the rerun a new immutable identity according to the frozen protocol. The
publication must disclose both.

## Required publication accounting

The final report must include, even when unfavorable:

- target, valid, Infra Invalid, failed, resumed, reused-role, and missing trial
  counts for every stage and role;
- every Attempt terminal status and every unresolved model call;
- Pass^1, stable-success tasks, critical violations, latency, and exact
  valid-only cost with their denominators;
- all preregistered paired estimates and 95% intervals that are applicable to
  stages actually authorized and run; skipped Release comparisons are explicit
  `not_applicable`, not zero;
- the native choice, the governed choice or null abstention, and every
  HOLD/REJECT reason;
- negative differences and timing outliers from fixture ablations;
- total known model spend, known lower-bound spend, and unknown cost scopes;
- local and remote execution wall time separately;
- deviations: the only acceptable value for frozen scientific choices is
  `none`; operational incidents are listed separately.

## Audit rule

Before accepting `outcome.json`, verify every event digest and group by
Attempt/Call ID. Each group must have one STARTED and one terminal event, unless
it is explicitly reported unresolved and causes HOLD. Recompute every semantic
digest without its own digest field, authenticate every referenced file hash,
and replay the existing-outcome verifier. Search-based “no missing files found”
is insufficient evidence of completeness.
