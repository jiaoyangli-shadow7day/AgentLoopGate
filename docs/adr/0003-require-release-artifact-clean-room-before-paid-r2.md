# ADR 0003: Require release-artifact clean-room before paid Banking R2

- Status: superseded for baseline identity by ADR 0004; clean-room rule retained
- Date: 2026-08-21
- Supersedes for paid R2 execution: `R2_A1`
- Does not replace: R2_A0/R2_A1 snapshots, freeze manifests, incidents, or
  `EXP_BANKING_P0`

## Context

The source-tree clean-room passed, but a later publication acceptance check ran
the standard `uv build` path. Flit created an sdist and then failed to build a
wheel from it because the configured local PEP 517 backend, `build_backend.py`,
was absent from the sdist. A developer checkout could install and test while a
released source archive remained unusable. No credentialed R2 core batch had
started, so no outcome was available to influence this correction.

The failed command, generated sdist hash, skipped downstream steps, timing, and
cost boundary are retained in
`runs/experiments/EXP_BANKING_R2/incidents/INC_R2_A1_SDIST_BUILD_SUPERSEDED_001.json`.

## Decision

1. Preserve R2_A1 and its freeze manifest byte-for-byte as superseded evidence.
2. Include `build_backend.py` explicitly through `[tool.flit.sdist]`.
3. Make clean-room acceptance build the sdist, build a wheel from that sdist,
   install the wheel into a fresh virtual environment outside the checkout, and
   run the installed CLI's version, DeepSeek Harness initialization, and
   three-level readiness report.
4. Treat a fresh project's `doctor` exit code 4 and `not_ready` payload as the
   expected truthful state while asserting that `observe_ready`, `check_ready`,
   and `govern_ready` are all present.
5. Re-run the entire no-key suite after the new A2 config exists, then bind the
   resulting source tree, clean-room script, CI workflow, incident, and package
   files into `freeze_manifest_a2.json`.
6. Keep Objective, Split, Gate, Protocol v2, Study v2, task pools, model pins,
   retry/timeout/concurrency rules, and statistical analysis unchanged.

## Consequences

This decision originally selected `configs/formal_experiment_r2_a2.yaml` and
evaluation-only baseline `R2_A2`. ADR 0004 preserves that history and
supersedes only the current baseline identity with `R2_A4`; the release-artifact
clean-room requirement remains active. Deployment remains on `A0`. A
source-tree test pass alone is not sufficient for open-source readiness; both
Python release artifacts and the DeepSeek Harness package must pass their
isolated installation/conformance paths. Known model spend for these no-model
checks is USD 0, while unmetered local compute cost remains unknown and is not
represented as zero.
