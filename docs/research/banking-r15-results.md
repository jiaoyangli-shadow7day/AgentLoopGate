# Banking R15 terminal results

## Result in one paragraph

Banking R15 is a valid, fully sealed pre-Release `HOLD`. The external AHE
Updater generated three semantically distinct Harness candidates, but none
produced a strict stable-success gain over `R15_A0` without regression on the
same frozen 15-task Selection population. Two candidates tied A0 at 6/15 and
one scored 5/15, yet all three lost the same two A0 successes (`task_062` and
`task_095`); candidate 2 additionally lost `task_056`. AgentLoopGate therefore
identified ability exchange hidden by aggregate scores and correctly declined
to nominate a Release candidate. No Release-ID, Release-OOD, Replay, promotion,
deployment, publication, or post-Selection model call occurred.

This result supports the project's governance claim: AgentLoopGate can accept
external updater proposals, preserve DeepSeek Harness execution evidence,
compare candidates against a frozen baseline at task level, account for
retries, latency and exact model cost, and fail closed when apparent gains
trade away protected capabilities. It does **not** show that AHE produced a
safe positive self-evolution in this study, that Banking results generalize to
other domains, or that AgentLoopGate is itself a better updater.

## Frozen identity and terminal evidence

- Experiment: `EXP_BANKING_R15`
- Protocol digest:
  `sha256:b40198176f9de2b39c9433131455bc0af07eee54650327622677cd9085b84a5f`
- Study digest:
  `sha256:bd5988f4f89068fa6347728f6b88ee4b8d8d1f644931ec110944e06b74e25043`
- Execution-source revision:
  `tree:sha256:0e3d0794bd21c5f20ff78512144e50da37b16a9784fa948a13055f6c847b4c8e`
- Baseline: `R15_A0`
- Outcome digest:
  `sha256:827ed2a5b3337832c49cd255f17568fad3a58fe201860311d66decb83ba0bdc3`
- Selection digest:
  `sha256:b5e800793f700e1d096a325961b3f40bac8cd93d12dddbdcbc111d48fa600466`
- Sanitized package manifest digest:
  `sha256:ce8ab4fe8b5bfde251da7e55d3448a900e290d33a3cd491961224a3fc6f6c2df`

The public-facing evidence is the independently verifiable package at
`artifacts/research/banking_r15/release`. Its manifest records
`publication_authorized: false`; the directory is a local publication
candidate, not evidence that publication occurred.

## Selection comparison

All values below are derived from the package's `selection.json` and
`cost_summary.json`. Success counts use the identical frozen 15-task population.
Cost is the whole-observed-attempt lower bound, including non-retained calls.

| Variant | Success | Gains vs A0 | Regressions vs A0 | p50 / p95 latency (ms) | Retries / timeouts | Whole-attempt cost (USD) | Decision |
|---|---:|---|---|---:|---:|---:|---|
| `R15_A0` | 6/15 | — | — | 265,903 / 977,157 | 1 / 0 | 0.4520428360 | baseline |
| `C_AHE_758BDB468FB4` | 6/15 | 017, 096 | 062, 095 | 264,917 / 1,838,752 | 1 / 1 | 0.5066522160 | held |
| `C_AHE_B55294C01B2A` | 5/15 | 017, 090 | 056, 062, 095 | 273,388 / 1,631,601 | 0 / 0 | 0.5009778704 | held |
| `C_AHE_217A9DDE7972` | 6/15 | 017, 090 | 062, 095 | 314,154 / 1,614,647 | 0 / 0 | 0.5095613824 | held |

The paired task surface is the central finding:

- `task_017` was a repeatable gain across all three AHE candidates.
- `task_062` and `task_095` were repeatable regressions across all three.
- aggregate ties for candidates 1 and 3 therefore conceal two-for-two ability
  exchanges;
- candidate 2 was one stable success worse than A0;
- every candidate exceeded A0's p95 latency by more than the frozen 1.2 ratio;
- candidate 1 also added a timeout;
- every candidate's whole-attempt cost was higher than A0, although still
  inside the frozen 1.2 cost-ratio ceiling.

The selector's reason is
`no_candidate_passed_baseline_bound_selection_policy`. The policy requires a
strict correctness gain, zero stable-task regression, and acceptable retry,
timeout, tail-latency and cost evidence. A total-score tie is not a gain.

## Execution completeness and cost

R15 completed all 125 authorized paid pre-Release positions:

- 25 Update-Source positions;
- 40 Update-Check positions (A0 plus three candidates, 10 each);
- 60 Selection positions (A0 plus three candidates, 15 each).

All nine formal batches have exact accounting and zero Infra Invalid runs. The
formal process took 52,591.59 seconds of local wall time. Exact known model
cost was USD `3.9086647880000000116`: formal batches cost
`3.8830976464000000116` and external Updater calls cost `0.0255671416`.
There is no unknown model-cost scope and no unresolved Updater model call.
Local compute monetary cost and GitHub Actions compute monetary cost remain
explicitly unknown/unmetered; they are not reported as zero.

## What the experiment establishes

1. **External-updater compatibility.** AgentLoopGate accepted three AHE
   proposals while keeping governance identity, candidate lineage and Harness
   execution evidence separate from updater-native ranking.
2. **Task-level regression detection.** The gate exposed common losses that a
   scalar success total would hide.
3. **Correct abstention.** The system reached a normal terminal `HOLD`, held all
   candidates, and made zero post-Selection model calls.
4. **Evidence and cost integrity.** Paid attempts, retries, unretained calls,
   latency and native-price cost were retained and reconciled exactly.
5. **Trace coexistence.** The registered no-model ablation verifies JSONL and
   SQLite persistence, event-hash equivalence, observer completeness and OTel
   coexistence for the DeepSeek Harness plugin fixture. This is fixture-level
   integration evidence, not a production-load latency claim.

## What it does not establish

- No candidate passed Selection, so there is no Release-ID/OOD/Replay evidence
  and no basis for a positive deployment or generalization claim.
- One Banking environment, one updater backend, one model/runtime family and
  three dependent candidates do not identify a universal AHE effect.
- The shared regressions motivate a better updater objective, but R15 cannot be
  reused to validate a newly designed updater. A future study must freeze a new
  identity and use untouched evaluation tasks.
- AgentLoopGate governs self-evolution; R15 does not claim that its current AHE
  adapter is itself an optimal evolution algorithm.

## Next research direction

The evidence supports designing an AgentLoopGate-guided updater that treats the
baseline's stable-success set as protected constraints, proposes sparse
failure-cluster-specific changes, and repairs counterexamples before full
Selection. The objective should optimize paired task gains subject to zero
protected-task regression, rather than aggregate score alone. This is a new
hypothesis generated by R15 and must be evaluated under a separately frozen
successor study; the R15 Selection tasks may inform design but cannot serve as
untouched confirmation data.

## Reproduction and verification

From the repository root, verify the sanitized package without private traces:

```sh
uv run python -m scripts.verify_public_result_package \
  --package artifacts/research/banking_r15/release
```

The expected manifest digest is
`sha256:ce8ab4fe8b5bfde251da7e55d3448a900e290d33a3cd491961224a3fc6f6c2df`,
with 12 files, zero Secret/direct-PII findings, and
`publication_authorized: false`.
