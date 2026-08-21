# AgentLoopGate open-source and paper readiness

Status date: 2026-08-21  
Current formal baseline: `R2_A2`  
Current source revision:
`tree:sha256:3919fd01a5ca66941fd688f72c88d30f82d1a082cdb7c4f373bb8d92dd03c5bf`

This is the requirement-to-evidence checklist for the v1 release. A local test
pass is not sufficient: every required row must have direct evidence. Rows that
depend on the credentialed Banking R2 matrix remain incomplete regardless of
whether the implementation is present.

## Acceptance matrix

| Requirement | State | Authoritative evidence | Remaining work |
|---|---|---|---|
| Preserve `EXP_BANKING_P0` HOLD and Incident evidence | PASS | Raw SHA256 `476567bf...bb0ad`; batch SHA256 `b90c2e44...69ac`; R2 freeze manifests bind both | Recheck in final publication seal |
| Version retry, timeout, concurrency, cost, and Infra Invalid protocol | PASS | `experiment_protocol_banking_r2_v2.yaml`, digest `sha256:e3d1a258...35172`; Protocol v2 tests | None before outcomes; protocol is frozen |
| Freeze the 560-logical-trial Banking R2 study | PASS | `banking_r2_study_v2.yaml`, digest `sha256:197f4f61...608c0`; study verifier and tests | None before outcomes; study is frozen |
| Reproducible non-deployment evaluation baseline | PASS | `R2_A2`, semantic digest `sha256:940748e4...78a6`; two completed Attempt IDs; deployment remains `A0` | Use A2 for all paid R2 work |
| Combined pre-core freeze | PASS | `freeze_manifest_a2.json`, semantic digest `sha256:ea009b77...0dc3`, file SHA256 `3e838875...2c56`; 20 file bindings verified by `ATT_5FDE7ABD12304311A34F657D2C6EBC4A` | Recheck before credentialed start |
| Source-tree no-key clean-room | PASS locally | Final five-stage run: exit 0, 113 Python tests, 13 TypeScript tests, fixture rebuild, DSH conformance/pack, Secret scan | Obtain remote CI evidence after a commit is pushed |
| Python sdist/wheel clean install | PASS locally | sdist-to-wheel build, fresh Python 3.12 venv install, installed `0.1.0` CLI/init/readiness; ADR 0003 | Preserve build artifacts/checksums in final release candidate |
| DeepSeek Harness native Trace coexistence and overhead | PASS for frozen fixture ablation | `plugin_coexistence_overhead_v2.json`; 30 paired JSONL and 30 paired SQLite iterations; native persistence and OTel checks true | Report as fixture/system evidence, not Banking task-quality evidence |
| Evidence Integrity Gate ablation | PASS for artifact replay | `integrity_gate_v2.json`; production path HOLD versus explicitly synthetic gate-disabled counterfactual | Preserve the distinction from a formal release Decision |
| A0 / Updater-native / AgentLoopGate symmetric Release-ID, OOD, Replay | NOT RUN | No R2 core batch artifacts exist | Securely inject the current-process credential and run/resume the A2 formal workflow |
| Independent selector ablation | PENDING CORE | Deterministic implementation/tests exist | Derive from the completed frozen core evidence; no extra model calls |
| Diagnosis-direction ablation | PENDING CORE | Deterministic implementation/tests exist and causal limitations are encoded | Derive from Update-Check/Selection evidence; no causal overclaim |
| Bootstrap uncertainty | PENDING CORE | 10,000-resample task-paired implementation and tests exist | Generate the six registered comparisons from valid complete R2 batches |
| Unique Decision, Lineage, report, and four core figures | MISSING RESULTS | Orchestrator/report implementation and unit tests exist | Produce and verify real artifacts after the matrix completes |
| Complete attempt, timing, token, retry, and cost evidence | PASS for work performed; PENDING CORE | Append-only Attempt Ledger, model-usage ledger implementation, incidents, and `operator_journal.md` | Audit every paid call/batch; unknown billing must remain partial/unavailable, never zero |
| Sanitized public Banking result package | MISSING RESULTS | Public synthetic demo exists; real R2 package does not | Build only after final R2 seal; exclude credentials, raw sensitive traces, and direct identifiers |
| Reproduction and technical-report material | PARTIAL | README, SPEC, Banking R2 protocol, ADRs, plugin guide | Add final methods/results/limitations, artifact manifest, figure captions, and exact reproduction commands |
| License and third-party declarations | PASS locally | Apache-2.0 `LICENSE`; `THIRD_PARTY_NOTICES.md`; pinned upstream revisions | Recheck package archives and final repository tree |
| Secret and direct-PII audit | PASS for current intended public tree | `scripts/audit_public_tree.py`: 165 text files, 3 secret + 3 PII rules, zero findings | Rerun after the sanitized real-results package is added |
| Private GitHub repository | PASS | `jiaoyangli-shadow7day/AgentLoopGate`, visibility `PRIVATE` | Keep private until explicit Owner authorization |
| Version-controlled remote and GitHub CI | NOT YET PROVEN | Local workflow exists and local equivalent passes; repository has no commit/default branch | Create a reviewed commit/branch, push privately, and require a green remote run |
| Public visibility, Release, or submission | NOT AUTHORIZED | Owner restriction in the active objective | Requires a separate explicit Owner authorization after every row above passes |

## Cost interpretation

All R2 work completed so far is no-model validation or deterministic ablation:
known model spend is USD 0 and model-cost status is `not_applicable`. Local CPU,
filesystem, dependency download, and CI-equivalent execution were not monetarily
metered, so total infrastructure cost is unknown rather than zero. The future
credentialed matrix must report exact valid-run cost where usage is complete and
lower-bound `partial`/`unavailable` status wherever retries, failures, or missing
billing prevent exact reconciliation.

## Required completion order

1. Recheck A2 freeze, Pilot joins, plugin profile, protocol/study digests, and
   current source revision in the credential-bearing process.
2. Run or resume the single formal A2 orchestrator. Never manually skip or
   overwrite an immutable Attempt after failure.
3. Audit all core role assignments, unique-versus-aliased trial counts, evidence
   completeness, Infra Invalid denominators, token usage, wall time, retries,
   and costs before accepting statistics.
4. Generate selector and diagnosis-direction ablations, six paired bootstrap
   comparisons, Decision/Lineage/report, and four figures from those sealed
   artifacts only.
5. Build the sanitized public result package and technical-report material;
   rerun Secret/PII, package clean-room, and reproducibility checks.
6. Create and push a reviewed private commit/branch, then require green GitHub
   CI. Do not publish or create a Release.
7. Ask the Owner for separate authorization before changing visibility,
   publishing a Release, or submitting a paper/report externally.
