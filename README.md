# AgentLoopGate

AgentLoopGate 是面向知识密集型行动 Agent 的持续改进与发布治理层：它冻结“什么叫用户
价值”，从失败轨迹生成受控的 Harness 修改，再用独立评测、安全、回归和成本硬门决定新
版本应当 `SHIP`、`HOLD` 还是 `ROLLBACK`。

它不是另一套 Agent Runtime、Trace 后端或自我修改框架。Python Core 是治理事实源；运行时
插件只负责把宿主事实安全地接入同一套 Candidate、Snapshot、ID/OOD/Replay 和 Gate 流程。
项目的可执行产品合同是 [SPEC.md](SPEC.md)。

## 当前状态

仓库已经具备无 Key 治理内核、确定性公开 Demo、冻结的 97 任务六池划分、AHE Updater
Adapter、τ³ Adapter、不可变 Snapshot/Batch、可恢复的 A0→Decision 正式编排器、Python Bridge，
以及可打包的 DeepSeek Harness 原生 Bundle。公开 Demo 中的 Outcome 全部是合成 Fixture，只用于
验证软件行为，**不是现实实验结果**。

真实 `EXP_BANKING_P0` 已完成 Pilot、A0 Update-Source、三个 AHE 候选、Update-Check、Selection
以及 A0 Release-ID；A0 Release-ID 因 4/60 Infra Invalid 被诚实封存为 HOLD，尚无最终 Candidate
Decision。该实验同时暴露出 τ³ 默认重试次数与冻结 Spec 不一致，因此保留为不可变 Incident/
工程证据，不作为发布级主结论。修正后的 `EXP_BANKING_R2` 已冻结 v2 执行协议、560 个逻辑
Trial 矩阵、源码身份与非部署评测基线 `R2_A4`；Integrity Gate 和 DeepSeek Harness 插件共存
两项无模型消融已经完成，本地 macOS 与私有 GitHub Linux clean-room 均通过。凭证相关的对称
核心矩阵尚未启动，不能宣称已有 R2 最终结果。冻结身份与文件哈希见
`runs/experiments/EXP_BANKING_R2/freeze_manifest_a4.json`。先前的 `R2_A0` 至 `R2_A3` 分别因
DSH clean-room conformance、Python sdist、本地存在但未进入 Git 的核心源码，以及 Linux 上的
Bridge 异步 `EPIPE` 而在付费核心开始前被取代；原 Snapshot、freeze manifest、失败 CI 和
Incident 均保留，冻结 Objective、Split、Gate、Protocol 与 Study 未改变。
逐项开源/论文验收状态及尚缺证据见
[docs/release-readiness.md](docs/release-readiness.md)。
精确复现步骤、证据/成本记录规范、未来脱敏结果包合同和技术报告骨架见
[docs/research/](docs/research/)。这些材料不会把尚未运行的核心矩阵写成已有结果。

## 无 Key Quickstart

要求 Python `3.12` 与 [uv](https://docs.astral.sh/uv/)。以下命令不访问模型 API：

```sh
uv sync --frozen
uv run agentloopgate doctor --json
uv run agentloopgate contract validate configs/objective_contract.yaml --json
uv run agentloopgate split verify --json
uv run agentloopgate eval reset-check --fixture tests/fixtures/reset --json
uv run agentloopgate demo --fixture tests/fixtures/public_demo --json
```

重新构建完整、确定性的公开证据包：

```sh
uv run agentloopgate demo \
  --fixture tests/fixtures/public_demo \
  --build-output artifacts/public_demo \
  --project . \
  --json
```

输出包括 Host JSONL Trace、`SourceTraceRef`、`EvidenceReceipt`、标准化 `RunRecord`、两个
应被拒绝的候选、一份 JSON/Markdown Decision 和每个 Decision 的四张 SVG 核心图。

## DeepSeek Harness 接入

兼容基线精确冻结为 DeepSeek Harness `0.1.0-rc.8`（commit
`141eb6fef83422698aef7a981029e843e8161534`）、Node `^22.19.0 || >=24.0.0` 和 pnpm
`11.7.0`。P0 不承诺其他宿主版本兼容。

DeepSeek 原生 append-only Session Log 始终是 H0 运行事实源。插件旁路订阅公开 Session
事件，生成可验证的引用与治理证据；它不替换 JSONL/SQLite Persistence，不注册冲突的
`ctx.sessionTelemetry` Backend，也不改变用户已有的 OTel Exporter。插件或 Python Bridge
失效时，原生 Session 仍继续工作，但不完整证据不得进入正式 Gate。

Harness 在构造或恢复 Session 时，部分 seed/收件箱事件不会进入 live firehose。Observer 会在
每次公开 Session flush 时以 `session.events` 权威快照做有界对账，只补录缺失序号；Core 仍按
连续 Cursor 严格验真。可恢复的瞬时 buffer 丢失不会污染证据，补录后仍有缺口才标记
`evidence_incomplete`。

从源码验证并打包插件：

```sh
cd integrations/deepseek-harness
corepack pnpm install --frozen-lockfile
corepack pnpm run generate:protocol
corepack pnpm run typecheck
corepack pnpm test
corepack pnpm run build
corepack pnpm run test:conformance
corepack pnpm pack
```

在已安装精确版本 `dsh` 的开发 Profile 中，使用官方已验证的 add/remove seam：

```sh
dsh plugin --profile headless add ./agentloopgate-dsh-plugin-0.1.0.tgz
dsh --profile headless --dump-config
dsh plugin --profile headless remove @agentloopgate/dsh-plugin
```

完整的 Trace、Bridge、权限和生命周期合同见
[docs/deepseek-harness.md](docs/deepseek-harness.md)。

## 三档 Readiness

运行：

```sh
uv run agentloopgate init --runtime deepseek-harness --project .
uv run agentloopgate doctor --runtime deepseek-harness --project . --json
```

| 等级 | 开发者立刻可用的能力 | 仍需提供 |
|---|---|---|
| `observe_ready` | Trace 回链、工具/成本事实、Evidence Verify | 精确版本 DSH、Bundle、Bridge 与 Redaction 配置 |
| `check_ready` | 加上 Contract Validate、Candidate Check、Decision Explain | 有效 Objective、Asset Manifest、Mutation Policy |
| `govern_ready` | 加上 Diagnose、Update、Evaluate、Gate、Rollback | 冻结合同/六池、确定性 Evaluator、已登记真实 Candidate |

银行场景是第一份纵向 Reference Validation Pack，用于验证从运行时 Trace 到 τ³ Outcome 再到
发布 Gate 的可靠性与可用性；银行 Gold 不会进入通用 Core。其他开发者复用的是接入协议、
证据链、候选隔离、硬门和回滚能力，并必须提供自己领域的目标、数据池与确定性 Evaluator。

### Banking Pilot（需要凭证）

Pilot 使用项目内隔离的 DSH Profile，不修改全局 Profile。先构建并安装当前插件：
τ³ 启动命令会注入精确固定的 `socksio` 运行依赖，并清除父 `uv run` 的解释器标记，因此
使用 SOCKS 代理的开发环境无需修改上游源码；Adapter 同时强制子进程使用 UTC，以规范化
上游 v1.0.1 的无时区时间戳。

```sh
mkdir -p runs/dsh/packages
cd integrations/deepseek-harness
corepack pnpm run build
corepack pnpm pack --pack-destination ../../runs/dsh/packages
DSH_HOME=../../runs/dsh/home ./node_modules/.bin/dsh plugin --profile headless add \
  ../../runs/dsh/packages/agentloopgate-dsh-plugin-0.1.0.tgz
cd ../..
```

在启动 AgentLoopGate 的同一进程环境中导出 `DEEPSEEK_API_KEY`。仓库的
`configs/pilot_pricing.yaml` 保存当前所选模型的官方价格、核对时间与来源；正式运行前必须复核，
价格变化时更新这份证据，不得静默沿用旧数字。下面默认运行冻结 Pilot 池的前三个任务：

```sh
uv run agentloopgate pilot run --json
```

若进程被中断，可在确认输入未变化后用同一 `--run-name` 恢复；已 checkpoint 的 Task 不会
再次调用模型。未完成 Task 的每次重试使用新的 DSH Session，τ³ 结果仅保存 Session Hash
用于 Evidence Join，避免已重置的业务状态读取失败尝试的对话记忆：

```sh
uv run agentloopgate pilot run --run-name <existing-run-name> --resume --json
```

成功输出只表示 DSH Session Trace、τ³ Tool/Outcome 与 `PilotEvidenceJoin` 完整；命令不会把
Pilot 自动包装成 Release 结论，`gate_decision` 在正式诊断和 Gate 前保持 `null`。
DSH Reply 边界允许三种无语义损失的规范化：移除单层 Markdown JSON fence、接纳 JSON
字符串内未转义换行、把非 JSON 的纯自然语言包装为 `content`，以及把“唯一键就是已允许
工具名”的显式 Tool Call 简写展开为 `name/arguments`。它不会从文本推断工具调用；
损坏的 JSON、未知工具名以及同时包含内容和工具调用的响应仍失败关闭。

每个 τ³ Trial 的首轮还会读取当前冻结 Snapshot 下登记的 Harness 资产；候选 Patch 因而会真实
改变模型上下文。读取使用固定路径、UTF-8、128 KiB 上限，完整 Harness Hash 同时进入 DSH
`composition_digest`，避免不同候选被错误地当成同一运行配置。

Pilot 后，人工复核 Objective，再用精确确认语句冻结；这个动作不可由正式编排器代替：

```sh
uv run agentloopgate contract freeze configs/objective_contract.yaml \
  --confirm "FREEZE OBJECTIVE" --json
```

随后运行只读预检：

```sh
uv run agentloopgate experiment protocol-verify \
  --config configs/experiment_protocol_banking_r2_v2.yaml --json
uv run agentloopgate experiment study-verify \
  --config configs/banking_r2_study_v2.yaml --json
uv run agentloopgate experiment preflight \
  --config configs/formal_experiment_r2_a4.yaml --json
```

它逐项核对真实 Pilot Join、冻结 Split、Objective 状态、源码树版本、DSH/τ³/AHE pin、隔离
Profile 与进程凭证。未满足任一项时返回退出码 `4`，不会启动模型或生成候选。源码尚未 commit
时使用完整 public-tree digest 作为 `code_revision`；预检不会替用户执行 commit/push。

凭证不可用时也可先冻结或幂等核验非部署评测基线；该命令不调用模型，也不改变 active
Snapshot：

```sh
uv run agentloopgate experiment baseline-freeze \
  --config configs/formal_experiment_r2_a4.yaml --json
```

全部通过后，一条命令运行或恢复 A0→诊断→AHE 候选→Update-Check→Selection→双 RC→
Release-ID/OOD→Replay→Gate→报告：

```sh
uv run agentloopgate experiment run \
  --config configs/formal_experiment_r2_a4.yaml --json
```

每个付费批次都有输入 Hash、保留的原始 τ³ 结果、双侧 Trace/Receipt/RunRecord/Join 与聚合摘要。
重复执行会先验真并复用，不会静默重复付费调用；证据漂移返回退出码 `5`。排障时可用
`agentloopgate experiment stage --stage <stage> --snapshot <snapshot-id>` 单独恢复一个批次。
每次正式尝试在执行前写 `STARTED`，并以 `COMPLETED` 或 `FAILED` 收尾；记录命令、源码/
协议/Study 身份、墙钟时间、退出码、重试、结果哈希、模型调用、Token 与成本状态。未知成本
只能是 `partial/unavailable`，不能写成 0；纯本地无模型步骤使用 `not_applicable` 并明确
`model_calls=0`。如果两种 Selector 选中同一 Snapshot，560 仍是逻辑矩阵规模，但物理唯一执行
数为 410、复用 150 个角色 Trial；选中不同 Snapshot 时物理执行数为 560。
完整编排只产生 `SHIP_RECOMMENDED/HOLD/REJECT` 建议，绝不会自动 Promote。
只有人类提供与目标、动作匹配的 Approval JSON 后，才可另行运行 `agentloopgate snapshot
promote`；相同授权可安全重试，`snapshot rollback` 也遵循同一边界。

## 凭证与安全

无 Key 工作流不需要凭证。真实实验只从当前进程环境读取 `DEEPSEEK_API_KEY`；不要把密钥
写入命令参数、配置、Trace、Issue 或聊天记录。`.env*`、运行结果、候选和 Snapshot 默认被
Git 忽略，正式公开前仍必须运行仓库级 Secret/PII 检查。

一键执行当前可离线验收项：

```sh
./scripts/verify_p0.sh
```

项目为兼容 macOS 隐藏 `.venv` 使用确定性的非 editable 开发安装；该脚本会显式重装当前
AgentLoopGate 源码，确保 CLI 与刚修改的工作树一致。

该脚本通过只表示实现与 Clean-room Fixture 通过；它不会把未运行的真实 Banking Pilot
标记为 P0 完成。

## License

AgentLoopGate 采用 [Apache License 2.0](LICENSE)。上游兼容基线和许可证见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
