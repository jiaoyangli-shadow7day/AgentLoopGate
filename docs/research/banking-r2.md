# Banking R2 study protocol

Banking R2 is the release-grade experiment for the AgentLoopGate open-source
technical report or systems/workshop paper. Its claim is deliberately narrow:
an evidence-governed selection layer can change an external updater's candidate
choice, preserve trace lineage, and prevent unsupported promotion. It does not
claim to invent a universally better self-evolution algorithm.

## Frozen inputs

- Experiment: `EXP_BANKING_R2`
- Execution protocol: `configs/experiment_protocol_banking_r2_v2.yaml`
- Study plan: `configs/banking_r2_study_v2.yaml`
- Objective: `configs/objective_contract.yaml`
- Split: `configs/splits.yaml`
- Formal configuration: `configs/formal_experiment_r2_a4.yaml`
- Evaluation baseline: `snapshots/R2_A4/manifest.json`
- Combined freeze manifest:
  `runs/experiments/EXP_BANKING_R2/freeze_manifest_a4.json`

The protocol and study-plan digests are verified before paid execution. Every
R2 batch identity includes the protocol digest. Any change creates a new
protocol, study, experiment, and baseline identity; it never edits R2 in place.
The current source revision is
`tree:sha256:38d6fcdac60739fee6ff196afe59be0aa2301256c84a3ba8acd7a46c361e0afe`.
`R2_A4` is an evaluation-only snapshot; deployment activation remains on `A0`.
`R2_A0` was superseded before paid execution when clean-room conformance exposed
a stale v1 test contract. `R2_A1` was then superseded when release-artifact
clean-room exposed that its source distribution omitted the configured local
build backend. `R2_A2` was superseded when the first clean Git checkout exposed
that unanchored artifact ignore rules had omitted two imported core packages
from both the commit and source identity. `R2_A3` was superseded after Linux CI
exposed an unhandled asynchronous Bridge `EPIPE`. Their bytes, failed remote
runs, and failure incidents remain immutable. A4 passed both the complete local
clean-room and the private Linux GitHub Actions workflow before this freeze.

## Core matrix

| Stage | Tasks | Trials | Variants | Target task-trials |
|---|---:|---:|---:|---:|
| Update-Source | 25 | 1 | 1 | 25 |
| Update-Check | 10 | 1 | A0 + 3 candidates | 40 |
| Selection | 15 | 1 | 3 candidates | 45 |
| Release-ID | 20 | 3 | A0 + two selector RCs | 180 |
| Release-OOD | 20 | 3 | A0 + two selector RCs | 180 |
| Replay | 10 | 3 | A0 + two selector RCs | 90 |
| Total |  |  |  | 560 |

If both selectors choose the same candidate, the orchestrator may reuse the
same content-addressed batch; it must not manufacture a third distinct version.
The role-assignment artifact therefore reports both counts: 560 logical trials
and either 560 unique executions (distinct choices) or 410 unique executions
plus 150 reused role-trials (identical choices). Reused evidence produces an
explicit selector null contrast, not a second independent sample.

## Minimal ablations

1. **Selector:** compare Updater-native and AgentLoopGate choices on the same
   frozen release evidence.
2. **Integrity Gate:** replay a fixed otherwise-passing assessment with and
   without complete evidence; only the production Gate result is authoritative.
3. **Diagnosis direction:** compare candidate asset families across
   Update-Check and independent Selection.
4. **Plugin coexistence/overhead:** compare native JSONL/SQLite persistence and
   enabled OTel with the observer off/on, including event equality and p50/p95
   fixture overhead.

These ablations reuse core evidence or deterministic headless fixtures and add
no model calls.

## Analysis and reporting

The task is the statistical unit. The primary endpoint is stable-success task
count. Report paired task differences and a frozen 95% paired-task bootstrap
interval with 10,000 resamples and seed `20260821`. Also report Pass^1,
infrastructure-invalid rate, critical violations, valid-only exact cost,
retained-run latency, retry-path wall time, and all HOLD reasons. Missing or
invalid evidence is reported separately and holds the affected formal batch.

The implementation records the exact per-comparison effective seed and uses a
two-sided nearest-rank 95% interval over paired task-level stable-success
differences. Each interval is bound to baseline/candidate batch and summary
digests. It refuses incomplete or Infra Invalid evidence. Diagnosis-direction
results are descriptive because only three non-randomized candidates exist and
Selection has no A0 arm; no causal asset-family claim is permitted.

## Attempt and cost evidence

Every paid formal batch and AHE model call writes durable STARTED and terminal
events. Deterministic workflow steps (baseline, diagnosis, materialization,
selection, role mapping, statistics/ablations, lineage, decisions, report,
outcome, and resume verification) use the same append-only experiment ledger.
Events bind source/protocol/study, command, timestamps, duration, exit status,
result hashes, counters, failure type, and recovery action.

Cost uses explicit `exact`, `partial`, `unavailable`, or `not_applicable`
status. Known fragments remain lower bounds; missing usage or retry billing is
never converted to zero. Infra Invalid runs are reported separately and hold an
incomplete batch. Pure local steps record zero model calls and
`not_applicable`, rather than presenting them as measured model spend.

## Current execution state

Protocol v2, Study v2, the A4 plugin profile, `R2_A4`, the superseding freeze
manifest, successful local and Linux source/release-artifact clean-room
verification, and the two A4 fixture/artifact-replay ablations are complete.
The combined freeze has semantic digest
`sha256:587cd2f1373273a40e9725b7eaeb50fafadec9650bbb8ccc295b147d685eea58`
and was verified by `ATT_D3BC2948CA9D4E2F8D66C64AD54D77B9` against 29
file bindings. Credentialed R2 core work has not started. The no-credential
preflight exits 4 only for the three current-process credential boundaries. No
final R2 selector result, bootstrap interval, Gate decision, or
diagnosis-direction result exists until that core matrix runs.

The two failed private CI runs consumed 16 and 47 seconds of job wall time;
the successful A4 job consumed 56 seconds. GitHub Actions monetary cost was not
available to the experiment process and is therefore `unavailable_unknown`,
not zero. All A4 preparation and ablation steps made zero model calls and have
known model spend USD 0; local CPU/filesystem/dependency monetary cost was not
metered and remains `unmetered_unknown`.

Results may be positive, negative, or HOLD. Thresholds, pools, and analysis
choices cannot be changed after observing R2 outcomes.
