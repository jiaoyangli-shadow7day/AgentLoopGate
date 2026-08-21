# AgentLoopGate open-source and paper readiness

Status date: 2026-08-21

Current formal baseline: `R2_A4`

Current source revision:
`tree:sha256:38d6fcdac60739fee6ff196afe59be0aa2301256c84a3ba8acd7a46c361e0afe`

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
| Reproducible non-deployment evaluation baseline | PASS | `R2_A4`, semantic digest `sha256:77cbb049...fa7d5`; two completed Attempt IDs; deployment remains `A0` | Use A4 for all paid R2 work |
| Combined pre-core freeze | PASS | `freeze_manifest_a4.json`, semantic digest `sha256:587cd2f1...ea58`, file SHA256 `9448328e...9543`; 29 file bindings verified by `ATT_D3BC2948CA9D4E2F8D66C64AD54D77B9` | Recheck before credentialed start |
| Source-tree no-key clean-room | PASS local + remote | Local five-stage run: exit 0, 113 Python tests, 13 TypeScript tests, artifact install, DSH conformance/pack, Secret scan; Linux GitHub Actions run `32488704733` passed | Preserve the green run and rerun after any execution-source change |
| Python sdist/wheel clean install | PASS locally | sdist-to-wheel build, fresh Python 3.12 venv install, installed `0.1.0` CLI/init/readiness; ADR 0003 | Preserve build artifacts/checksums in final release candidate |
| DeepSeek Harness native Trace coexistence and overhead | PASS for frozen fixture ablation | `plugin_coexistence_overhead_a4.json`; 30 paired JSONL and 30 paired SQLite iterations; native persistence, OTel coexistence, hash, and persistence checks true | Report as fixture/system evidence, not Banking task-quality evidence |
| Evidence Integrity Gate ablation | PASS for artifact replay | `integrity_gate_a4.json`; production path HOLD versus explicitly synthetic gate-disabled counterfactual | Preserve the distinction from a formal release Decision |
| A0 / Updater-native / AgentLoopGate symmetric Release-ID, OOD, Replay | NOT RUN | No R2 core batch artifacts exist | Securely inject the current-process credential and run/resume the A2 formal workflow |
| Independent selector ablation | PENDING CORE | Deterministic implementation/tests exist | Derive from the completed frozen core evidence; no extra model calls |
| Diagnosis-direction ablation | PENDING CORE | Deterministic implementation/tests exist and causal limitations are encoded | Derive from Update-Check/Selection evidence; no causal overclaim |
| Bootstrap uncertainty | PENDING CORE | 10,000-resample task-paired implementation and tests exist | Generate the six registered comparisons from valid complete R2 batches |
| Unique Decision, Lineage, report, and four core figures | MISSING RESULTS | Orchestrator/report implementation and unit tests exist | Produce and verify real artifacts after the matrix completes |
| Complete attempt, timing, token, retry, and cost evidence | PASS for work performed; PENDING CORE | Append-only Attempt Ledger, model-usage ledger implementation, incidents, and `operator_journal.md` | Audit every paid call/batch; unknown billing must remain partial/unavailable, never zero |
| Sanitized public Banking result package | BUILDER PASS; MISSING RESULTS | Fail-closed content-addressed builder, Secret/PII gate, idempotence/conflict tests, and blocked Attempt `ATT_E332E57709E74D73A9E7A2A87F7B2C36`; no release directory exists | Run builder only after final R2 seal; then verify exact package and private CI attestation |
| Reproduction and technical-report material | PASS pre-result; PENDING RESULTS | Exact A4 reproduction protocol, evidence/cost dictionary, sanitized-package contract, technical-report outline, README, SPEC, ADRs, and plugin guide | Populate only sealed results, final digests, captions, and limitations after core |
| License and third-party declarations | PASS locally | Apache-2.0 `LICENSE`; `THIRD_PARTY_NOTICES.md`; pinned upstream revisions | Recheck package archives and final repository tree |
| Secret and direct-PII audit | PASS for current intended public tree | `scripts/audit_public_tree.py`: 194 text files, 3 secret + 3 PII rules, zero findings | Rerun after the sanitized real-results package is added |
| Private GitHub repository | PASS | `jiaoyangli-shadow7day/AgentLoopGate`, visibility `PRIVATE` | Keep private until explicit Owner authorization |
| Version-controlled remote and GitHub CI | PASS | Private branch `codex/r2-a2-pre-core`; failed runs `32487980794` and `32488331642` retained; fixed source commit `88e3818...` passed run `32488704733` | Require a new green run after any execution-source change |
| Public visibility, Release, or submission | NOT AUTHORIZED | Owner restriction in the active objective | Requires a separate explicit Owner authorization after every row above passes |

## Cost interpretation

All R2 work completed so far is no-model validation or deterministic ablation:
known model spend is USD 0 and model-cost status is `not_applicable`. Local CPU,
filesystem, and dependency-resolution cost is `unmetered_unknown`; GitHub
Actions monetary cost for the 16-second and 47-second failed jobs and 56-second
successful job is `unavailable_unknown`. Total infrastructure cost is therefore
unknown rather than zero. The future
credentialed matrix must report exact valid-run cost where usage is complete and
lower-bound `partial`/`unavailable` status wherever retries, failures, or missing
billing prevent exact reconciliation.

## Required completion order

1. Recheck A4 freeze, Pilot joins, plugin profile, protocol/study digests, and
   current source revision in the credential-bearing process.
2. Run or resume the single formal A4 orchestrator. Never manually skip or
   overwrite an immutable Attempt after failure.
3. Audit all core role assignments, unique-versus-aliased trial counts, evidence
   completeness, Infra Invalid denominators, token usage, wall time, retries,
   and costs before accepting statistics.
4. Generate selector and diagnosis-direction ablations, six paired bootstrap
   comparisons, Decision/Lineage/report, and four figures from those sealed
   artifacts only.
5. Build the sanitized public result package and technical-report material;
   rerun Secret/PII, package clean-room, and reproducibility checks.
6. Create and push a reviewed private results commit/branch, then require green
   GitHub CI. Do not publish or create a Release.
7. Ask the Owner for separate authorization before changing visibility,
   publishing a Release, or submitting a paper/report externally.
