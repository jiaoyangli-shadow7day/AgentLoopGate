# Banking R2 reproducibility protocol

> Historical existing-evidence verification only. Do not execute the
> credentialed commands below as a new or resumed paid study. R2 was superseded;
> current `PAID_HOLD` policy and the corrected experiment requirements are in
> [release-readiness.md](../release-readiness.md) and SPEC §16.11.

This document describes how to reproduce and audit `EXP_BANKING_R2` without
changing its frozen scientific choices. It is an execution protocol, not a
results document. No final Banking R2 result exists until the credentialed core
finishes and the sealed `outcome.json` verifies.

## Immutable identities

| Item | Frozen value |
|---|---|
| Experiment | `EXP_BANKING_R2` |
| Evaluation baseline | `R2_A4` |
| Execution source | `tree:sha256:38d6fcdac60739fee6ff196afe59be0aa2301256c84a3ba8acd7a46c361e0afe` |
| Objective | `sha256:9065911cc14f620fb4f840cb35c0fbeac86fe8a59145d4d182c5a5f1a637544f` |
| Split | `sha256:f63532b9953a488e0bfddbd09b0ca62eb9ed6d229db35f69835e1666751973c1` |
| Protocol | `sha256:e3d1a2586ce6c13772a0b8dddfbe5ccc90f62d7811645ce2b401802aaa535172` |
| Study | `sha256:197f4f618c66b1c48bea2fe979b2b0727e1d3d7424c544737bb998494d9608c0` |
| Pricing evidence | `sha256:0dcc3e377789e4ef449ba539021fd0d448a78520bedbddc1156abd3733c26271` |
| Asset manifest | `sha256:af37a45929cb14ed22e0ab13284d1effe57cd829804bc153ddccdbd964a888e0` |
| Combined pre-core freeze | `sha256:587cd2f1373273a40e9725b7eaeb50fafadec9650bbb8ccc295b147d685eea58` |

`R2_A4` is evaluation-only. Deployment activation remains on `A0`. Reproducing
the study must not promote a Snapshot or change repository visibility.

## Environment

Run from the repository root. The reference environment uses Python 3.12,
DeepSeek Harness `0.1.0-rc.8` at commit
`141eb6fef83422698aef7a981029e843e8161534`, τ³ `1.0.1` at commit
`fc0055dc4e0a316c3f83133267fbd6faaa770992`, Node
`^22.19.0 || >=24.0.0`, and the pinned package locks. The execution protocol
also fixes UTC, concurrency, retry limits, timeouts, temperatures, seeds, step
limits, and output-token limits.

Before a credentialed run, record the following in the append-only operator
journal: Git commit and source digest, OS/architecture, Python/uv/Node/pnpm
versions, upstream checkout commits, DSH package/profile/lock hashes, start
time, and whether a proxy is active. Do not record proxy credentials or secret
values.

## No-model acceptance

Install exactly from the locks and run the complete clean-room workflow:

```sh
uv sync --frozen
./scripts/verify_p0.sh
```

Then verify the frozen scientific inputs:

```sh
uv run agentloopgate experiment protocol-verify \
  --config configs/experiment_protocol_banking_r2_v2.yaml --json
uv run agentloopgate experiment study-verify \
  --config configs/banking_r2_study_v2.yaml --json
uv run agentloopgate experiment baseline-freeze \
  --config configs/formal_experiment_r2_a4.yaml --json
uv run agentloopgate experiment preflight \
  --config configs/formal_experiment_r2_a4.yaml --json
```

Without a credential in the current process, preflight must exit 4 and identify
only credential boundaries. With a correctly isolated current-process
credential, it must exit 0. Any source, protocol, Study, Pilot join, plugin, or
runtime mismatch is a real blocker and must not be relabeled as a credential
failure.

The two no-model A4 ablations can be reproduced explicitly:

```sh
uv run agentloopgate experiment ablation-integrity \
  --study configs/banking_r2_study_v2.yaml \
  --protocol configs/experiment_protocol_banking_r2_v2.yaml \
  --output artifacts/research/banking_r2/ablations/integrity_gate_a4.json \
  --json
uv run agentloopgate experiment ablation-plugin \
  --study configs/banking_r2_study_v2.yaml \
  --protocol configs/experiment_protocol_banking_r2_v2.yaml \
  --output artifacts/research/banking_r2/ablations/plugin_coexistence_overhead_a4.json \
  --json
```

Existing content-addressed outputs must be verified and reused. A byte conflict
must fail; it must never overwrite an earlier result.

## Credentialed core

The credential must already be present in the process environment that starts
the command. Never put it in a command argument, config file, shell history,
Trace, log, Issue, or chat message.

Run or resume the single frozen workflow:

```sh
uv run agentloopgate experiment run \
  --config configs/formal_experiment_r2_a4.yaml --json
```

The same command is the supported recovery path. Completed content-addressed
batches are verified and reused; an interrupted or failed Attempt remains in
the ledger. Do not delete a failed batch, rename a run, change the Split, or
increase retry limits to obtain a favorable result. A digest conflict exits
fail-closed rather than silently repeating paid work.

The registered matrix contains 560 logical task-trials. If both selectors
choose the same Snapshot, 150 role-trials reuse identical physical evidence,
so the physical count is 410 and the selector contrast is explicitly null.
Otherwise all 560 are unique executions.

## Authoritative private evidence

The completed workflow must contain and mutually authenticate at least:

```text
runs/experiments/EXP_BANKING_R2/
  attempt_ledger/ATT_*/*.json
  model_usage/*.jsonl
  raw/B_*.json
  batches/B_*.json
  costs/B_*.json
  diagnosis.json
  proposal_plan.json
  selection.json
  role_assignment.json
  statistics.json
  lineage.json
  decisions/native.json
  decisions/agentloopgate.json
  outcome.json
  lifecycle/<candidate-id>/*.json

runs/
  trace_refs/*.json
  receipts/*.json
  normalized/*.json
  diagnostics/*.json
  evidence_joins/*.json

reports/EXP_BANKING_R2/
  decision.json
  decision.md
  01_candidate_curve.svg
  02_failure_funnel.svg
  03_pool_comparison.svg
  04_gate_waterfall.svg

artifacts/research/banking_r2/ablations/
  selector_v2.json
  diagnosis_direction_v2.json
  integrity_gate_a4.json
  plugin_coexistence_overhead_a4.json
```

Raw τ³ output and host Trace are private evidence. They are not automatically
part of the public result package.

## Completion verification

After the first terminal run, invoke the same command again. It must verify the
existing Outcome, every Lineage batch, Snapshot, Decision, statistics artifact,
ablation digest, and report-file hash without performing new paid work.

Then check all of the following before interpreting results:

1. Every Attempt has exactly one STARTED event and one COMPLETED or FAILED
   terminal event; no terminal cost status is `pending`.
2. Every model call has STARTED and terminal usage evidence, or is explicitly
   counted as unresolved with `unavailable` cost.
3. Logical, unique-executed, and reused role-trial counts reconcile.
4. Every formal batch covers its exact registered task/trial population.
5. Infra Invalid runs are reported separately; any affected batch is HOLD and
   excluded from publication bootstrap comparisons.
6. Valid-run model cost is exact. Failed/unretained/retried calls remain in
   whole-attempt accounting; unknown billing is `partial` or `unavailable`.
7. Both native and AgentLoopGate Decisions exist, while only the governed
   Decision feeds the main report. `SHIP_RECOMMENDED` is never called a deploy.
8. All six paired comparisons use 10,000 resamples, seed `20260821`, and the
   task—not the trial—as the statistical unit.
9. The four SVGs and their Decision JSON/Markdown match the hashes sealed in
   `outcome.json`.
10. P0 raw and batch hashes remain unchanged.

Finally rerun `./scripts/verify_p0.sh` and
`uv run python scripts/audit_public_tree.py` after building the sanitized
package. Record every failed check and skipped stage as well as the eventual
successful rerun.

The sanctioned package command is:

```sh
uv run python scripts/build_public_r2_package.py \
  --config configs/formal_experiment_r2_a4.yaml \
  --freeze runs/experiments/EXP_BANKING_R2/freeze_manifest_a4.json \
  --output artifacts/research/banking_r2/release
```

Before `outcome.json` exists, exit code 4 plus no output directory is the
expected fail-closed result—not a partial public package.
