# AgentLoopGate publication authorization runbook

This runbook records the safety boundary and verification procedure for the
public source release. On 2026-08-29, the Owner explicitly instructed the
operator to open-source the project and every repository material that can be
safely published. That instruction authorizes the scoped repository visibility
change and publication of the audited tracked tree. It does not authorize a
package-registry upload, candidate promotion, deployment, paid experiment,
paper submission, or disclosure of ignored/private evidence.

## Frozen publication candidate

- Formal result: `EXP_BANKING_R15`, terminal Selection `HOLD`.
- Private Outcome digest:
  `sha256:827ed2a5b3337832c49cd255f17568fad3a58fe201860311d66decb83ba0bdc3`.
- Sanitized v1.1 package Manifest:
  `sha256:79e9a8dd31009f969cdd79021bbcc857c827dc1d5a6808a28fd05937e4f364c8`.
- Exact known model cost: USD `3.9086647880000000116`; unknown model-cost
  scope: none. Local and GitHub Actions compute monetary cost remain unknown.
- Release-ID, Release-OOD, Replay, Promote, deployment, GitHub Release, and
  submission were not run.
- Repository: `jiaoyangli-shadow7day/AgentLoopGate`; intended public state is
  `PUBLIC` after all pre-publication checks pass.

The scientific claim is governance utility: AgentLoopGate detected paired
capability regressions hidden by aggregate ties and failed closed. The result
does not establish positive AHE evolution, a deployable candidate, or
cross-domain generalization.

The package field `publication_authorized:false` is immutable creation-time
provenance: the package cannot authorize its own publication. It is deliberately
preserved after the later Owner authorization and must not be rewritten.

## Pre-publication verification

Run from a clean checkout of the intended default-branch commit:

```sh
./scripts/verify_p0.sh
uv run python -m scripts.verify_publication_candidate --project .
git status --short
gh repo view jiaoyangli-shadow7day/AgentLoopGate \
  --json defaultBranchRef,visibility,url
gh run list --repo jiaoyangli-shadow7day/AgentLoopGate \
  --branch "$(git branch --show-current)" --limit 1
```

Acceptance before the visibility change requires:

1. clean-room, package verification, DeepSeek Harness conformance, build, and
   Secret/direct-PII audit all pass;
2. the publication-candidate verifier reports the immutable package state
   `ready_for_owner_publication_review`, `publication_authorized:false`, and
   only `owner_publication_authorization` as its historical workflow blocker;
   the active 2026-08-29 Owner instruction satisfies that external blocker;
3. the working tree is clean, the remote default branch points at the intended
   commit, and its latest private CI run succeeded;
4. GitHub still reports `PRIVATE` before the authorized visibility action.

## Current authority boundary

The active Owner instruction authorizes `jiaoyangli-shadow7day/AgentLoopGate`
to change from `PRIVATE` to `PUBLIC` and makes every audited tracked file
publicly readable. It does not authorize any of the following:

- a package-registry publication, DOI, external announcement, or paper
  submission;
- Release-ID/OOD/Replay experiments or other paid model calls;
- Promote, deployment, or changing the R15 `HOLD` conclusion;
- publishing ignored raw Trace, Attempt, model response, candidate, Snapshot,
  environment, or credential material.

## Authorized visibility procedure

Only after the exact visibility authorization is present in the active task:

1. repeat the pre-publication verification without modifying the tree;
2. record the authorized repository, intended visibility, commit, CI run, and
   the fact that registry publication/Promote/submission remain outside scope;
3. execute the single scoped GitHub visibility change;
4. query GitHub immediately and require `visibility: PUBLIC` on the same
   repository and default-branch commit;
5. verify the README, LICENSE, security policy, and v1.1 package are anonymously
   readable, then rerun the independent package verifier from a fresh checkout;
6. record the post-publication repository URL and verification result without
   rewriting the content-addressed R15 package.

Making a repository private again cannot retract clones or cached public
content. A failed preauthorization check therefore blocks publication instead
of relying on rollback.

## Separate future actions

A package-registry upload, report submission, DOI, announcement, or deployment
requires its own Owner instruction and a new review of the target. R15 remains
a Selection-HOLD systems result; no Release evaluation should be fabricated to
fill figures or tables.
