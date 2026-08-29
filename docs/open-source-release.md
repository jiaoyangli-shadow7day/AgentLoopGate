# AgentLoopGate public source release record

Status date: 2026-08-29

## Authorization and scope

The Owner explicitly authorized publishing
`jiaoyangli-shadow7day/AgentLoopGate` and every audited tracked project
material that can be safely open-sourced. The authorized public tree contains:

- the Python governance core, CLI, schemas, configurations, and tests;
- the DeepSeek Harness plugin source, lockfile, conformance fixtures, and guide;
- the English and Chinese papers plus the English reader-review record;
- the sanitized, independently verifiable Banking R15 result package;
- the project specification, research history, reproducibility guidance,
  license, third-party notices, contribution policy, and security policy.

Ignored runtime roots, credentials, raw model conversations, private traces,
unredacted benchmark content, local environments, caches, and machine
authorization artifacts remain outside the public tree.

## Evidence semantics

The R15 package field `publication_authorized:false` records that the package
did not grant its own publication authority when it was created. It is part of
the immutable package manifest and remains false after the later Owner
authorization. Publishing the package does not change its `HOLD` outcome,
create Release-ID/OOD/Replay evidence, promote a candidate, or establish a
positive self-evolution result.

## Publication checks

The public source release is complete only when all of the following are true:

1. the complete clean-room suite, paper fact verifier, package verifier, and
   Secret/direct-PII audit pass on the intended commit;
2. CI passes on the same default-branch commit;
3. GitHub reports the repository as `PUBLIC`;
4. an unauthenticated client can read the repository and clone it;
5. a fresh anonymous clone can install the locked dependencies and run the
   no-key doctor path;
6. the papers, DeepSeek Harness integration, sanitized R15 package, license,
   and community files are present in that clone.

The exact post-publication commit and verification result are recorded in the
final section after the visibility action. Package-registry publication,
deployment, Promote, paid experiments, and paper submission remain separate
actions.

## Final public verification

The intended-tree local clean-room completed on 2026-08-29: 221 Python tests,
13 TypeScript tests, Ruff, paper fact binding, both R15 package verifiers,
Python sdist-to-wheel installation, DeepSeek Harness build/conformance/pack,
and the public-tree Secret/direct-PII audit passed. The audit scanned 377 text
files with zero findings; binary files were not interpreted as text.

The audited publication tree was committed as
`99773d44b1a618eb1a6087cf0575cf61e0223e4f`. GitHub clean-room run
[`33252845445`](https://github.com/jiaoyangli-shadow7day/AgentLoopGate/actions/runs/33252845445)
completed successfully on that exact commit before publication.

The repository was then changed from `PRIVATE` to `PUBLIC` under the Owner's
authorization. Post-publication checks confirmed:

- GitHub reports `PUBLIC` at
  <https://github.com/jiaoyangli-shadow7day/AgentLoopGate>;
- unauthenticated HTTP reads of the repository, README, and license succeeded;
- a credential-free shallow clone resolved to the publication commit;
- `uv sync --frozen` succeeded in that clone;
- `agentloopgate doctor --json` returned `no_key_mode:true`,
  `status:ready`, and version `0.1.0`;
- the clone contained both papers, the DeepSeek Harness plugin, license and
  community files, and the sanitized R15 result package;
- independent package verification reproduced manifest
  `sha256:79e9a8dd31009f969cdd79021bbcc857c827dc1d5a6808a28fd05937e4f364c8`
  with 18 files and zero Secret/direct-PII findings.

The publication-record update changes documentation only. It does not alter
the verified source, paper PDF, plugin, or content-addressed R15 package from
the publication commit.
