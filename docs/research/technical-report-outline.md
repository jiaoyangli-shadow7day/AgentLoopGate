# AgentLoopGate technical report outline

> Result-free R11 report plan. Bracketed fields may be populated only from a
> verified `EXP_BANKING_R11` terminal outcome and its sanitized manifest. R10
> remains historical engineering evidence, not the current evaluation or a
> source of R11 result values.

This outline is ready for a workshop paper, systems paper draft, or open-source
technical report. Until terminal evidence exists, every bracketed result field
means “not available,” not zero.

## Working title and claim

**AgentLoopGate: Evidence-Governed Selection and Release Control for Agent
Harness Evolution**

Narrow claim: an external governance layer can preserve runtime Trace lineage,
compare updater-native and independently selected Harness candidates on frozen
ID/OOD/Replay evidence, and prevent unsupported promotion through fail-closed
release gates.

Non-claims: AgentLoopGate is not a new Agent Runtime, Trace store, universal
self-improvement algorithm, proof of safety, or evidence that Banking gains
automatically transfer to other domains.

## Abstract template

1. Problem: updater-generated Harness changes can be selected and shipped from
   incomplete, coupled, or weakly traceable evidence.
2. System: AgentLoopGate freezes user value, derives bounded candidates from
   failure evidence, separates updater-native and governance selection, and
   gates release on authenticated ID/OOD/Replay evidence, safety, cost, and
   integrity.
3. Integration: a DeepSeek Harness plugin coexists with native JSONL/SQLite and
   OTel Trace while the Python core remains the governance fact source.
4. Evaluation: frozen Banking R11 first evaluates A0 plus three bounded
   candidates over 125 pre-Release positions. A `HOLD` is a valid terminal;
   the 450-position Release-ID/OOD/Replay tail is conditional on `SELECT` and
   a second Owner authorization.
5. Result: `[populate from outcome/statistics/decisions only]`.
6. Limitation: one domain, one updater, one primary agent/runtime family, small
   candidate set, and system-fixture—not production-load—plugin overhead.

## Paper structure

### 1. Introduction

- Why “generate a patch” is not the same as “know what to ship.”
- Failure modes: training/evaluation coupling, missing Trace lineage,
  incomplete retry/cost accounting, OOD regressions, and auto-promotion.
- Contributions:
  1. runtime-independent evidence and Snapshot contracts;
  2. independent selection plus lexicographic release gating;
  3. append-only attempt/model/cost accounting with Infra Invalid separation;
  4. DeepSeek Harness native-Trace coexistence;
  5. a frozen, reproducible Banking reference validation.

### 2. Goals and threat model

- Knowledge-intensive action Agents and Harness-level changes.
- Trusted kernel, mutable assets, host-runtime boundary, human promotion.
- Evidence corruption, missing events, stale source, retries, and cost blindness.
- Out of scope: model-weight training, autonomous deployment, universal domain
  claims, adversarial host compromise.

### 3. System design

- Objective Contract and six disjoint pools.
- Host Trace → SourceTraceRef → Receipt → normalized RunRecord → Join.
- Diagnosis, bounded candidate generation, immutable Snapshot lineage.
- Update-Check, independent Selection, Release-ID/OOD/Replay.
- Gate ordering and `SHIP_RECOMMENDED/HOLD/REJECT` semantics.
- Append-only lifecycle, resumption, cost reconciliation, and human promotion.

### 4. DeepSeek Harness integration

- Why native Session persistence remains H0 fact source.
- Observer snapshot reconciliation and cursor integrity.
- Bridge crash isolation and fail-closed governance behavior.
- What plugin coexistence proves and what it does not prove.

### 5. Experimental method

- Frozen R11 identities, `R11_A2`, and the R10/R11 supersession chronology.
- The 25-position Update-Source, 40-position Update-Check, and 60-position
  A0-bound Selection checkpoint.
- A0 and three semantically distinct, runtime-capability-bound candidates;
  updater-native versus AgentLoopGate roles are reported only when independent
  selection evidence exists.
- Task-level stable success, Pass^1, critical violations, latency, and cost.
- Paired task bootstrap: 10,000 resamples, frozen seed, and only the
  comparisons whose registered pools actually completed.
- Infra Invalid, retries, evidence gaps, semantic de-duplication, capability
  binding, role aliasing, and HOLD policy.
- Four pre-registered minimal ablations.

### 6. Results

#### RQ1: Does independent selection change the chosen candidate?

Report candidate aliases, semantic fingerprints, runtime-capability bindings,
A0 comparison inputs, and the exact selector disposition. If no candidate
meets the strict gain/non-regression/cost/retry/latency gates, report the sealed
`HOLD` and that no Release model calls occurred. If roles alias, report a null
contrast and evidence reuse—not two independent variants.

#### RQ2: Does a selected change improve reliable task outcomes?

Populate this table only if R11 reaches `SELECT`, receives the separately
authorized Release tail, and seals the required pools. On a terminal `HOLD`,
the table is intentionally absent and the report must not substitute R10 data.

| Role | Pool | Stable tasks / tasks | Pass^1 | Infra Invalid | Critical violations | p50 latency | Exact valid cost |
|---|---|---:|---:|---:|---:|---:|---:|
| A0 | Release-ID | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` |
| Updater-native | Release-ID | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` |
| AgentLoopGate | Release-ID | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` |
| A0 | Release-OOD | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` |
| Updater-native | Release-OOD | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` |
| AgentLoopGate | Release-OOD | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` |
| A0 | Replay | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` |
| Updater-native | Replay | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` |
| AgentLoopGate | Replay | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` | `[artifact]` |

For each baseline-versus-role/pool comparison, report observed stable-task net,
rate difference, 95% interval, task count, effective seed, and both batch
digests. Do not report trial-level pseudo-replication.

#### RQ3: Does fail-closed evidence governance matter?

- Production integrity-gate Decision and the synthetic disabled-gate
  counterfactual.
- False-promotion prevention interpretation.
- Every real core HOLD/REJECT reason and incomplete denominator.

#### RQ4: Are diagnosis and selection separable?

- Candidate asset families, Update-Check changes, independent Selection ranks,
  and failure-type transitions.
- Descriptive only: three updater-produced candidates do not identify a causal
  effect of asset family.

#### RQ5: Can the plugin coexist with native Trace at acceptable fixture cost?

- JSONL and SQLite paired p50/p95 deltas with all signed samples/outliers.
- Native persistence, event-hash, observer completeness, and OTel coexistence.
- Clearly label this as headless fixture evidence, not production latency.

#### RQ6: What did the experiment cost and how long did it take?

Report model calls, tokens, provider retries, valid/Infra/failed spend,
lower-bound or unavailable scopes, local wall time, remote CI wall time, and
recovery paths. Unknown infrastructure cost remains unknown.

### 7. Discussion and limitations

- Distinguish a correct governance direction from a positive task-quality gain.
- Discuss negative, null, HOLD, or REJECT outcomes without changing the claim.
- Single Banking environment and upstream-version pins.
- Candidate dependence and small non-randomized candidate population.
- Benchmark/user-simulator and provider variance.
- Bootstrap scope and lack of multi-domain external validity.
- Fixture overhead versus production-scale performance.
- Human approval remains outside the measured automatic workflow.

### 8. Reproducibility and ethics

- Exact frozen identities and commands, including the separate paid-scope
  authorizations.
- Failure/supersession chronology and no outcome-driven protocol edits.
- Secret, direct-PII, raw Trace, and benchmark-content handling.
- Artifact availability tiers: public aggregates versus controlled raw evidence.
- Licensing and upstream notices.

## Required figures

1. `01_candidate_curve.svg`: A0 through candidates, Pass^1, stable success, and
   normalized cost. Caption must name the exact pool/denominator.
2. `02_failure_funnel.svg`: retrieval → policy → tool → state counts. Caption
   must state whether counts are runs, tasks, or diagnosis labels.
3. `03_pool_comparison.svg`: stable tasks by role and Release-ID/OOD/Replay.
   Caption must disclose role aliasing and reused evidence.
4. `04_gate_waterfall.svg`: ordered integrity, regression, reliability, safety,
   OOD, and cost gates ending in the governed Decision. Caption must state that
   SHIP_RECOMMENDED is not deployment.

## Result-population rule

Every number and conclusion in the final report must cite a package path and
digest from the sanitized manifest. A value may not be copied from console
output when a sealed artifact exists. Missing, failed, or unknown evidence is
reported as such; it is never converted to zero, omitted from a denominator, or
replaced with a successful rerun without disclosing the predecessor.
