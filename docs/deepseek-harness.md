# DeepSeek Harness 接入合同

AgentLoopGate 通过原生 Cordis Bundle 接入 DeepSeek Harness，并把其 append-only Session Log
作为运行事实源。插件只旁路采集、回链和查询治理结果；它不替换 Session Persistence、
`ctx.sessionTelemetry`、模型 Provider，也不获得 Promote、Rollback、Final 或 Gate 修改权限。

## 冻结兼容基线

- DeepSeek Harness npm：`0.1.0-rc.8`
- 官方源码 commit：`141eb6fef83422698aef7a981029e843e8161534`
- Node：`^22.19.0 || >=24.0.0`
- pnpm：`11.7.0`
- Profile：官方 `headless`

P0 只保证该精确基线。宿主仍处于 Developer Preview；任何升级都必须重跑本文末尾的全部
Conformance，不能把 peer dependency 的 semver 放宽当作兼容性证明。

## 已核对的官方 seam

以下路径均来自上述 commit：

| 能力 | 官方源码/文档 | AgentLoopGate 用法 |
|---|---|---|
| Bundle/Profile | `docs/architecture.md`、`packages/bundle/README.md`、`apps/cli/reference/README.md` | manifest 声明 `dsh.bundle.patch`；通过 `dsh plugin --profile headless add/remove` 安装卸载 |
| Headless | `packages/bundle/headless/cordis.patch.yml`、`src/startup.ts`、`src/index.ts` | 通用 Bundle 不改 runner；Banking Example 用末层 Patch 禁用普通 runner，挂载可恢复的单 Turn runner，不 Patch Harness Core |
| Service/生命周期 | `vendor/cordis/src/service.ts`、`vendor/cordis/src/context.ts` | `AgentLoopGateService` + Provider；所有副作用绑定 Fiber |
| Session Trace | `packages/core/session/src/index.ts` | 订阅 `session/created`、`session/event`、`session/flush`、`session/disposed`，从公开 `Session.events` 回填 |
| Tool | `packages/core/tools/src/index.ts`、`docs/cookbook/adding-a-tool.md` | `ctx.tools.register(defineTool(...))` 注册四个受限工具 |
| 子进程 | `packages/subprocess/subprocess/src/index.ts`、`packages/subprocess/subprocess-local/src/index.ts` | `ctx.subprocess.spawn(...)` 管理唯一、惰性 Python JSONL Bridge |
| Persistence | `packages/session/session-persistence-*` | 不注册、不配置、不读取私有存储格式；同时验证 JSONL 与 SQLite |
| Telemetry | `packages/session/session-telemetry/src/index.ts`、`packages/session/session-telemetry-otel/src/index.ts` | 不注册或替换 `ctx.sessionTelemetry`，不修改 mode/exporter |

官方 Command seam 已核对，但 P0 没有增加模型可见或人类宿主命令：人类的冻结、评测、
Promote 与 Rollback 仍只走 Python CLI。这是权限边界，不是缺失的插件功能。

## Trace 到治理证据的关系

DeepSeek Harness 的 Session Log 继续回答“实际发生了什么”，JSONL/SQLite 决定如何持久化，
OTel 决定是否向开发者自己的 Collector 导出。AgentLoopGate Observer 独立消费同一公开事件流：

```text
Session Log ──> 原生 JSONL / SQLite
           ├──> 原生 OTel（可选，配置不变）
           └──> AgentLoopGate Observer ──> SourceTraceRef / Evidence Receipt
```

默认 `reference` 模式只保存事件身份、摘要和 Hash；`mirror` 模式保存经过 AgentLoopGate
Redaction 的必要副本。两者都用 `(session.id, event.seq)` 去重。序号缺口、丢弃或 Bridge
失败会把证据标为 `evidence_incomplete`，相关 Run 不能进入正式 Gate，但不会中断普通 Agent Turn。

## 插件提供什么

安装 Bundle 后，Profile 获得：

- `ctx.agentLoopGate` 版本化 Service；
- Session live + backfill Observer；
- 四个模型可见的非特权工具：status、contract validate、candidate check、decision explain；
- 本地持久 Python Bridge；
- SourceTraceRef 与后续 Outcome/Decision 的回链入口。

插件不提供第二套 Trace、评分器或治理内核。社区项目可以保留自己的 DSH Agent、工具、
Persistence、Telemetry 和确定性 Evaluator，再把 Outcome 导入同一套 Candidate、Snapshot、
ID/OOD/Replay、成本、安全和发布 Gate。

## Banking Reference Validation 的双 Trace

`examples/tau3-banking` 不让 DSH 和 τ³ 各跑一次互不相关的 Agent。τ³ 注册的
`agentloopgate_dsh` Agent 会在每个 User/Tool Result Turn 恢复同一个 DSH Session：DSH 调模型并
保存输入、严格 JSON 回复和 Usage；τ³ 解释回复中的 Tool Call，在其银行环境中真实执行，再由
τ³ Evaluator 判最终状态和政策结果。

首轮模型上下文还包含当前 Snapshot 的固定白名单 Harness 资产。读取拒绝符号链接和越界路径，
总量限制为 128 KiB；资产树 Hash 写入 DSH composition digest。这样 A0 与候选仍共享相同的 τ³
政策、工具和 Evaluator，但候选 Patch 确实改变被评 Harness，而不是只改变登记表。

因此两份 Trace 的权威不同：DSH Session Log 是模型会话事实，τ³ Raw Result 是工具执行、环境
状态和 Outcome 事实。AgentLoopGate 为两侧分别生成 SourceTraceRef、EvidenceReceipt 和
RunRecord，再用 `PilotEvidenceJoin` 关联 Task、Trial、Session Hash 与两侧 Artifact。Join 不保存
明文 Session ID，也不允许 DSH 或插件给自己评分。任一侧缺失或不完整，Pilot 证据即失败关闭。

## 开发与验证

在仓库根目录同步 Python 环境，在插件目录同步精确 pnpm lock：

```sh
uv sync
cd integrations/deepseek-harness
corepack pnpm install --frozen-lockfile
corepack pnpm run generate:protocol
corepack pnpm run typecheck
corepack pnpm test
corepack pnpm run build
corepack pnpm run test:conformance
```

`generate:protocol` 从 Python Pydantic Bridge 模型生成 JSON Schema 和 TypeScript envelope 类型，
插件不得手写另一份 envelope。`test:conformance` 会打包当前 Bundle，在全新的临时
`DSH_HOME` 中执行官方 add/load/remove 流程，并以本地模拟 DeepSeek SSE 端点真实完成一个
Agent Turn、一次模型请求和一个已验证 DSH SourceTraceRef；它不读取真实 `DEEPSEEK_API_KEY`。

当前 Conformance 还覆盖：四工具权限、Bridge 失败降级、live/backfill 去重、有限缓冲、
序号缺口、Provider/Observer/Tool 卸载、Bridge 子进程回收，以及启用原生 JSONL、SQLite、
OTel FULL 时插件安装前后的逻辑 SessionEvent 与 Telemetry Provider 共存。
