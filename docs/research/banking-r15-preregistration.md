# Banking R15 preregistration and authorization hold

`EXP_BANKING_R15` is the first successor identity that binds all repairs exposed
by R14 before any paid candidate evaluation. It is not an extension, rerun, or
repair-in-place of R14. Historical R2–R14 artifacts remain immutable and are
used only as calibration and incident evidence.

Frozen identity:

- Protocol `BANKING_R15_PROTOCOL_1`,
  `sha256:b40198176f9de2b39c9433131455bc0af07eee54650327622677cd9085b84a5f`
- Study `BANKING_R15_STUDY_1`,
  `sha256:bd5988f4f89068fa6347728f6b88ee4b8d8d1f644931ec110944e06b74e25043`
- Execution source
  `tree:sha256:0e3d0794bd21c5f20ff78512144e50da37b16a9784fa948a13055f6c847b4c8e`
- Evaluation Baseline `R15_A0`,
  `sha256:7a5264cfecb9fa19804b8c1aa1e6b1bbc4f380e47d76973351f18bbb46811387`
- Machine preregistration
  `sha256:70a48708b8477d95de42dba8c8e2d13eca87ddd532b89cce9b20a91aefb12155`

The pre-Release matrix remains 25 Update-Source, 40 Update-Check, and 60
Selection positions. Three sibling candidates must be prospective-patch
validated, semantically distinct, and bound to executable runtime capabilities
before paid Update-Check. Selection requires a strict stable-success gain over
the same `R15_A0` tasks with zero stable regression, bounded whole-attempt cost,
latency, retries, and timeouts. No qualifying candidate produces normal
`HOLD`; it never manufactures a winner.

The waste-control path now has two layers. Before paid work, the system applies
each proposed patch in an isolated parent tree and validates the resulting YAML
and exact runtime capability binding. During paid work, a permanent
infrastructure invalidity seals the strict subset, trigger, attempts, trace
availability, and exact cost before the next position. A pre-Agent failure is
recorded as unavailable provenance and may not invent a DeepSeek Harness trace
or evidence join. Resume is verification-only after terminal HOLD.

Local clean-room passed 214 Python and 13 TypeScript tests, Ruff, sdist-to-wheel
installation, DeepSeek Harness headless/native coexistence, plugin build/pack,
and a 332-file Secret/direct-PII scan with zero findings in 19.57 seconds. Every
R15 preparation attempt, including failed test/tool assumptions, made zero
external model calls and incurred known Provider/model cost USD `0`; local
compute monetary cost remains `unmetered_unknown`.

The real formal preflight passed ten checks and stopped only because the exact
R15 pre-Release machine authorization does not exist. This is the intended
safety state. Private Linux CI passed for commit `42990f2`, run `32682027757`,
job `97300237502`; its validation digest is
`sha256:5b3a67042ab2a9e1c7bd3339dfe45d3b59259ec7211695f28b730d2a0967f58b`. No
external Updater, paid position, Release-ID/OOD/Replay, Promote, visibility
change, GitHub Release, publication, or submission is authorized by this
document.

Two registered no-model ablations are already sealed. The integrity fixture
(`4ccbf1…1720`) proves the fail-closed gate converts an unsupported synthetic
`SHIP_RECOMMENDED` into `HOLD`. The DSH coexistence fixture (`7ae1a9…b66c`)
preserves identical SessionEvent hashes, JSONL/SQLite persistence, observer
completion, and OTel across 30 iterations per backend. Its macOS-arm64 local
p95 overhead is 16.423834 ms for JSONL and 0.541667 ms for SQLite; this is noisy
fixture evidence, not a production latency bound. Both made zero model calls.
