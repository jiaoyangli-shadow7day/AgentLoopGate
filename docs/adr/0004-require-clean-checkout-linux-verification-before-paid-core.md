# ADR 0004: Require clean-checkout Linux verification before paid core

- Status: Accepted
- Date: 2026-08-21
- Experiment: `EXP_BANKING_R2`

## Context

The local A2 clean-room passed while two imported Python packages existed only
in the developer working tree. Unanchored `candidates/` and `snapshots/`
patterns in the root `.gitignore` matched both generated top-level artifacts
and `agentloopgate/candidates/` plus `agentloopgate/snapshots/`. The files were
therefore absent from the first commit and from the Git-based execution-source
identity. Private Linux CI run `32487980794` exposed the omission.

After root-anchoring those patterns and committing the packages, A3 passed all
Python and release-artifact stages. Linux CI run `32488331642` then exposed a
second platform-sensitive problem: a deliberately crashed Bridge could emit an
asynchronous unhandled `EPIPE` after its lifecycle test had otherwise passed.
That path did not surface in the earlier macOS run.

No credentialed Banking R2 core work had started, so the reproducible baseline
could still be superseded without observing task-quality outcomes or changing
the frozen Objective, Split, Gate, Protocol, or Study.

## Decision

Before any paid core execution, the formal source revision must satisfy all of
the following:

1. It is materialized in a private remote commit; local untracked files cannot
   supply imported execution code.
2. Root-generated artifact ignore patterns are root-anchored, and required
   source packages are explicitly present in the committed inventory.
3. The complete five-stage workflow passes from a clean Linux checkout as well
   as locally: lint/tests, governance fixtures, sdist-to-wheel/fresh install,
   DeepSeek Harness typecheck/tests/build/conformance/pack, and Secret/PII scan.
4. Bridge subprocess error listeners are installed before writes, scoped to the
   owning handle, and stale-handle events cannot affect a replacement Bridge.
5. Any failed remote run, superseded Snapshot, commit, timing, error, Incident,
   and cost status remains part of the append-only evidence chain.
6. A source-changing fix creates a new evaluation-baseline identity and freeze
   manifest. It cannot silently repair the baseline named by a failed run.

R2_A2 and R2_A3 are therefore superseded. R2_A4, source revision
`tree:sha256:38d6fcdac60739fee6ff196afe59be0aa2301256c84a3ba8acd7a46c361e0afe`,
is the first baseline accepted under this rule. It passed local verification
and private Linux GitHub Actions run `32488704733` at commit
`88e3818ee667c627f364f413192612d02b140243`.

## Consequences

- Cross-platform clean-checkout CI is a precondition, not optional release
  polish. A local pass alone cannot authorize paid core execution.
- Execution-source changes require a new baseline/freeze even when the change
  appears to be packaging or lifecycle-only.
- Documentation and generated evidence may be added without changing the
  execution-source digest, but their public-tree audit and remote CI still must
  pass before publication readiness is claimed.
- The two failed jobs used 16 and 47 seconds of job wall time; the successful
  A4 job used 56 seconds. GitHub Actions monetary cost was unavailable and is
  recorded as `unavailable_unknown`, never as zero. All three made zero model
  calls and incurred known model spend USD 0.

## Evidence

- `runs/experiments/EXP_BANKING_R2/incidents/INC_R2_A2_GITIGNORE_SOURCE_OMISSION_SUPERSEDED_001.json`
- `runs/experiments/EXP_BANKING_R2/incidents/INC_R2_A3_BRIDGE_EPIPE_SUPERSEDED_001.json`
- `runs/experiments/EXP_BANKING_R2/freeze_manifest_a4.json`
- `.github/workflows/ci.yml`
- `scripts/verify_p0.sh`
