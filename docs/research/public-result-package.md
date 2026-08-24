# Sanitized Banking formal-result public package contract

> R2 is historical evidence only and must never be presented as the current
> AgentLoopGate result. The current public candidate is the verified R15 v1.1
> Selection-HOLD package at `artifacts/research/banking_r15/release_v2`, Manifest
> `79e9a8…364c8`. The contract remains configuration-driven and fail closed for
> both a full formal Outcome and a pre-Release Selection-HOLD terminal.

The public result package is a derived, privacy-reviewed view of authoritative
private evidence. It must not be assembled until the credentialed formal Outcome is
terminal and verified. A template, partial directory, or synthetic demo must
never be labeled as the Banking result package.

## Full-Outcome layout

```text
artifacts/research/<formal-experiment>/release/
  README.md
  manifest.json
  reproduction.json
  outcome.json
  lineage_summary.json
  role_assignment.json
  statistics.json
  failure_accounting.json
  cost_summary.json
  decisions/
    native.json
    agentloopgate.json
  ablations/
    selector.json
    diagnosis_direction.json
    integrity_gate.json
    plugin_coexistence_overhead.json
  reports/
    decision.json
    decision.md
    01_candidate_curve.svg
    02_failure_funnel.svg
    03_pool_comparison.svg
    04_gate_waterfall.svg
```

This layout is conditional on a future experiment reaching `SELECT` and then
completing an independently authorized Release tail. R15 correctly did not
create it.

## Selection-HOLD v1.1 layout

R15 uses the smaller terminal contract because no candidate passed Selection:

```text
artifacts/research/banking_r15/release_v2/
  README.md
  manifest.json
  selection_hold_outcome.json
  selection.json
  statistics.json
  lineage_summary.json
  failure_accounting.json
  cost_summary.json
  reproduction.json
  ablations/
    integrity_gate.json
    plugin_coexistence_overhead.json
  reports/
    selection_hold.json
    selection_hold.md
    technical_report.md
    01_candidate_curve.svg
    02_failure_funnel.svg
    03_pool_comparison.svg
    04_gate_waterfall.svg
```

The v1.1 verifier additionally binds three paired Selection bootstrap
comparisons, complete whole-experiment model cost, all four Selection-only
figures, and the technical report to the private Outcome and Selection digests.
It never treats the absent Release tail as zero-valued Release evidence.

## Manifest contract

`manifest.json` must contain:

- schema/package version, creation time, and explicit `sanitized_derived_view`;
- experiment, protocol, Study, source, Objective, Split, Pricing, Asset
  Manifest, baseline Snapshot, and private Outcome digests;
- the immutable P0 raw and batch hashes, without including P0 raw bytes;
- logical, unique-executed, reused, valid, Infra Invalid, failed, and unresolved
  counts;
- final and native Decision values plus Decision/Lineage/statistics/report
  digests;
- known model spend, lower-bound spend if applicable, every unknown cost scope,
  and local/remote wall-time summaries;
- a path, SHA-256, media type, privacy classification, and derivation statement
  for every public file;
- Secret/PII audit result, the frozen execution-source clean-room run and
  commit, and package content-verification status;
- `scientific_protocol_deviations: []` and a separate list of operational
  incidents; an empty incident list is not permitted when retained failures
  exist.

The manifest must hash every package file except itself, then carry a canonical
digest over its own payload excluding its digest field. To avoid a hash cycle,
the release README prints the private Outcome digest and points readers to the
Manifest; it does not embed the Manifest digest.

## Allowed derived content

- Aggregate batch summaries and registered paired statistics.
- Content-addressed IDs and hashes that cannot reveal direct user/session
  identity.
- Both final selector Decisions and their Gate evidence references after those
  references are rewritten to public package paths.
- Candidate/Snapshot aliases needed to reproduce comparisons, provided no
  prompt, customer, account, or session content is embedded.
- Failure, retry, timing, token, and cost aggregates, including unknown-status
  disclosures.
- The four deterministic SVG figures and their source Decision digest.
- The two no-model fixture/replay ablations and two core-evidence ablations.

## Excluded private content

- Credentials, environment dumps, proxy URLs containing authentication, shell
  history, and provider request headers.
- Raw DSH Session JSONL/SQLite, raw τ³ transcripts, model prompts/responses,
  tool arguments/results, and updater free-form reasoning.
- Direct session IDs, user/customer/account/card/contact identifiers, personal
  paths, emails, phone numbers, or other direct identifiers.
- Hidden/OOD task content whose license or benchmark policy does not authorize
  redistribution.
- Machine-local absolute paths and private repository tokens/URLs with
  embedded credentials.
- Fabricated zero values for missing cost, token, time, or retry evidence.

Hashes alone are not automatically safe: low-entropy identifiers must be
replaced by package-local aliases rather than published as guessable hashes.

## Derivation and verification

After a terminal private Outcome exists, create its final publication freeze
(which is distinct from the running pre-run preregistration) and run:

```sh
uv run python scripts/build_public_result_package.py \
  --config <formal-config.yaml> \
  --freeze <terminal-publication-freeze.json> \
  --output artifacts/research/<formal-experiment>/release
```

The command writes a STARTED and terminal package Attempt. Before the core
finishes it must exit 4 with `PublicPackageBlocked` and create no release
directory. After completion it deep-verifies private evidence, derives only the
allow list, scans every payload, and either creates an immutable package or
verifies byte-identical existing output. It never overwrites conflicting bytes.

Anyone with the sanitized directory—but without private Trace—can independently
verify its complete file set, Manifest and artifact digests, cross-artifact
Decision/statistics bindings, cost-status invariants, and Secret/PII scan:

```sh
uv run python scripts/verify_public_result_package.py \
  --package artifacts/research/<formal-experiment>/release
```

1. Verify the existing private Outcome through the formal orchestrator without
   executing new model calls.
2. Verify complete Attempt and model-call lifecycles, batch/cost reconciliation,
   Lineage, Decisions, statistics, ablations, and report hashes.
3. Generate only the allow-listed derived fields. Do not copy a private file
   wholesale merely because its top-level schema looks safe.
4. Assign stable public aliases, strip disallowed text, and preserve aggregate
   denominators and unknown-status values.
5. Build the content manifest and independently recompute every file hash and
   canonical digest.
6. Run the Secret/direct-PII audit over the exact intended Git-public tree.
7. Build/install/test from a clean checkout containing the package, then record
   the private remote CI run and its compute-cost status as an external GitHub
   attestation and in the release-readiness record. The run ID cannot be written
   back into the content-addressed package commit without creating a commit/CI
   cycle.
8. Have the Owner review the package and report. This authorizes neither public
   visibility nor a Release; those require a separate explicit instruction.

## Fail-closed publication rules

Do not produce or publish the package when any of the following is true:

- no verified terminal `outcome.json` exists;
- an Attempt or model call is unresolved without a disclosed HOLD;
- a formal batch is incomplete, corrupt, or missing exact registered coverage;
- a Decision, statistics, Lineage, ablation, report, or file hash conflicts;
- valid-run cost accounting is not exact, or unknown attempt cost is hidden;
- Secret/PII scanning reports a finding;
- the package changes a result, denominator, interval, or frozen method;
- the repository has not passed clean-checkout CI at the package commit;
- the Owner has not separately authorized publication.
