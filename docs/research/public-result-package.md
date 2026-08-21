# Sanitized Banking R2 public result package contract

The public result package is a derived, privacy-reviewed view of authoritative
private evidence. It must not be assembled until the credentialed R2 Outcome is
terminal and verified. A template, partial directory, or synthetic demo must
never be labeled as the Banking result package.

## Intended layout

```text
artifacts/research/banking_r2/release/
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

The directory does not exist yet by design. Its creation is an outcome-dependent
step and must fail if the private evidence is incomplete or inconsistent.

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
- Secret/PII audit result, clean-room run URL/commit, and package verification
  status;
- `scientific_protocol_deviations: []` and a separate list of operational
  incidents; an empty incident list is not permitted when retained failures
  exist.

The manifest must hash every package file except itself, then carry a canonical
digest over its own payload excluding its digest field. The release README must
print the same root digest.

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
   the private remote CI run and its compute-cost status.
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
