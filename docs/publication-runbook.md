# AgentLoopGate publication authorization runbook

This runbook prepares a safe repository-visibility change. It does not grant
authorization, publish the repository, create a GitHub Release, promote a
candidate, deploy software, or submit a report.

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
- Repository: `jiaoyangli-shadow7day/AgentLoopGate`; current required state is
  `PRIVATE`.

The scientific claim is governance utility: AgentLoopGate detected paired
capability regressions hidden by aggregate ties and failed closed. The result
does not establish positive AHE evolution, a deployable candidate, or
cross-domain generalization.

## Preauthorization verification

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

Acceptance requires:

1. clean-room, package verification, DeepSeek Harness conformance, build, and
   Secret/direct-PII audit all pass;
2. the publication-candidate verifier reports
   `ready_for_owner_publication_review`, `publication_authorized:false`, and
   only `owner_publication_authorization` as a remaining blocker;
3. the working tree is clean, the remote default branch points at the intended
   commit, and its latest private CI run succeeded;
4. GitHub still reports `PRIVATE` before the authorized visibility action.

## Authority boundary

Changing visibility requires a new, explicit Owner instruction that names the
repository and authorizes `PRIVATE` → `PUBLIC`. Authorization to make the
repository public does not implicitly authorize any of the following:

- a GitHub Release, package-registry publication, DOI, announcement, or paper
  submission;
- Release-ID/OOD/Replay experiments or other paid model calls;
- Promote, deployment, or changing the R15 `HOLD` conclusion;
- publishing ignored raw Trace, Attempt, model response, candidate, Snapshot,
  environment, or credential material.

## Authorized visibility procedure

Only after the exact visibility authorization is present in the active task:

1. repeat the preauthorization verification without modifying the tree;
2. record the authorized repository, intended visibility, commit, CI run, and
   the fact that GitHub Release/Promote/submission remain outside scope;
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

A GitHub Release or report submission requires its own Owner instruction and a
new review of version/tag metadata and publication venue. R15 remains a
Selection-HOLD systems result; no Release evaluation should be fabricated to
fill figures or tables.
