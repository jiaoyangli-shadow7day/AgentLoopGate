# AgentLoopGate v1.0：Vibe Coding 执行规格

> 文档类型：产品目标 + 工程合同 + 实验协议 + 开发任务单  
> 版本：v1.0 Execution Core r37
> 日期：2026-08-23
> 周期：8 周，单人项目  
> 默认实验载体：τ³-bench `banking_knowledge`  
> 首个社区宿主：DeepSeek Harness 原生 Cordis 插件  
> 状态：本文件是 v1 P0 的唯一范围与验收事实源

---

## 0. Coding Agent 必须先读

### 0.1 本文件怎么用

本文件不是愿景文档，而是可以直接拆给 Coding Agent 的执行合同。

- `必须`：P0 验收项，不得自行删除或降级。
- `应当`：默认实现；只有真实兼容性或成本证据成立时才能调整。
- `可以`：实现选择，不影响 P0 验收。
- `禁止`：违反信任边界或实验有效性的行为。

每次开发只领取第 12 节的一张任务卡。Coding Agent 必须：

1. 先读本节、任务卡及其引用章节；
2. 检查当前仓库和被 pin 的上游源码，不得凭空假设 API、CLI 参数或字段；
3. 先写或更新测试，再完成最小实现；
4. 只修改任务卡允许的目录；
5. 运行任务卡列出的验收命令；
6. 报告改动文件、测试结果、未解决风险，不得把未运行写成已完成；
7. 未经产品 Owner 明确批准，不得修改本 SPEC 的目标、Gate、数据池或信任边界。

每张任务卡的“修改范围”隐含允许新增或修改直接覆盖该任务的 `tests/unit/`、
`tests/integration/`、`tests/e2e/` 与 `tests/fixtures/`；测试不得改写信任核、冻结数据或
掩盖真实上游失败。

### 0.2 一次任务的完成格式

Coding Agent 完成任务后必须输出：

```text
Task: Txx
Status: done | blocked
Changed: [files]
Acceptance: [command -> result]
Artifacts: [paths]
Risks: [remaining risks]
Next: [next unblocked task]
```

### 0.3 开发总原则

- 先跑通无 Key Fixture，再接真实模型和真实 Benchmark。
- Python Core 是治理事实源；DeepSeek Harness 插件是接入层，不复制治理逻辑。
- 宿主原生 Trace 是“实际发生了什么”的运行事实源：τ³ 使用其 Raw Result，DeepSeek Harness 使用其 append-only Session Log。
- AgentLoopGate Evidence Receipt 与 Normalized Records 是治理事实源；它们必须回链宿主 Trace，外部 Telemetry/Observability 不直接参与判分。
- 候选生成器只能提出修改，不能修改目标、评测、数据划分或发布门。
- 任何正式结论都必须能回链到任务、Run、Trace、Snapshot、Candidate 和 Decision。
- 结果不理想不是 Bug；隐藏失败、移动任务、放宽 Gate 才是 Bug。

---

## 1. 产品目标与核心理念

### 1.1 一句话定义

AgentLoopGate 是面向知识密集型行动 Agent 的持续改进与发布治理层：它冻结“什么叫用户价值”，从失败轨迹生成受控的 Harness 修改，再用独立评测、安全、回归和成本门决定该版本应当 Ship、Hold 还是 Rollback。

### 1.2 目标用户

- 负责知识密集型行动 Agent 的 AI PM；
- Agent/Harness 工程师；
- 评测、质量与发布负责人；
- 希望在 DeepSeek Harness 中使用可审计优化与发布治理能力的社区开发者。

### 1.3 项目要证明的唯一主张

> 只按开发集分数选择 Harness 修改，可能带来过拟合、遗忘、违规或成本失控；由产品目标函数驱动、具备独立验证与发布门的闭环，能够拒绝“看似提升、实际不应发布”的修改，并选择更接近稳定用户价值的版本。

项目成功不要求必须产生一个可发布的新版本。若全部候选都不满足 Gate，真实的 `HOLD` 结论也是有效结果。

“选择”不是强制从候选中挑出一个相对最好者。AgentLoopGate 必须把同池、同任务、同 Trial 的 A0
作为 Selection 基线；只有候选在不丢失 A0 稳定成功任务的前提下产生新的稳定成功，并通过完整性、
关键违规、全 Attempt 成本、重试、超时和尾延迟约束，才可以成为 `RC_agentloopgate`。否则选择器
必须 `HOLD/ABSTAIN`，并在任何 Release 付费批次开始前停止。

### 1.4 五个不可删的核心支柱

1. **目标函数先于优化**：先冻结 Objective Contract，再看候选结果。
2. **失败证据驱动改进**：先定位检索、推理、工具、顺序、验证或恢复问题，再让外部 Updater 修改对应 Harness 资产。
3. **广义但受控的 Harness 进化**：修改面不限于 Prompt，但所有资产、路径、风险和权限必须登记。
4. **独立验证决定发布**：Update、Selection、ID、OOD、Replay 角色分离；开发分数不能直接决定发布。
5. **社区可用的 DeepSeek Harness 插件**：通过官方 Cordis/Bundle 扩展点把 AgentLoopGate 接入 DeepSeek Harness，保留原生 Session/Persistence/Telemetry，并保留不可被插件替换的 Python 治理内核。

### 1.5 北极星指标

`Reliable Policy-Compliant Resolution（RPCR）`：Agent 在独立任务上经过重复运行，持续把外部系统推进到正确目标状态，且没有关键政策违规。

用户价值代理由以下部分共同构成：

- 任务是否严格完成；
- 是否稳定完成；
- 是否遵守政策与权限；
- 是否保留旧能力并能迁移；
- 成本和延迟是否可接受。

### 1.6 证据边界

本项目证明的是公开受控环境中的目标函数、优化选择和发布治理能力，不证明真实用户采用、留存、分发或商业收益。Benchmark 提升禁止包装成线上银行业务价值。

---

## 2. v1 P0 范围

### 2.1 P0-A：治理内核

| ID | 能力 | P0 验收结果 |
|---|---|---|
| P0-01 | Objective Contract | YAML 可校验、可冻结、带 Hash；缺字段阻止运行 |
| P0-02 | Trace 证据链 | 宿主 Trace 保持原生；AgentLoopGate 保存 SourceTraceRef、Evidence Receipt 和可重建 Normalized Record |
| P0-03 | 数据池 ACL | 越池读取直接拒绝并记录；Updater 看不到 Selection/Release |
| P0-04 | Snapshot | Harness、模型、合同、数据 Hash 和代码版本组成可复现 Snapshot |
| P0-05 | Promotion Gate | 输出逐门证据与 `SHIP_RECOMMENDED/HOLD/REJECT` |
| P0-06 | 回滚 | 可恢复父 Snapshot；发布动作必须由人类 CLI 触发 |
| P0-07 | 决策报告 | 自动生成 Markdown/JSON 决策卡和四张核心图 |

### 2.2 P0-B：失败诊断与持续优化

| ID | 能力 | P0 验收结果 |
|---|---|---|
| P0-08 | 失败漏斗 | 至少区分检索、政策推理、工具发现、参数、顺序、验证、恢复 |
| P0-09 | FailureBundle | 将失败证据、价值损失、目标资产和约束结构化交给 Updater |
| P0-10 | Harness Asset Manifest | 可变资产、路径、风险、操作与回滚单元机器可读 |
| P0-11 | Mutation Policy | 未登记路径、越权、泄漏、超预算或修改信任核时直接拒绝 |
| P0-12 | 外部 Updater Adapter | AHE 为默认；命中冻结 Tripwire 时允许 ACE 降级；至少一个真实外部 Updater 跑通 |
| P0-13 | Candidate Ladder | 至少 3 个真实候选；每个有单一假设、Diff、来源、预测、风险和结果 |
| P0-14 | 双选择器对照 | 在同一 Snapshot 梯子上比较 Updater-native 与 AgentLoopGate Selector |

### 2.3 P0-C：评测完整性与独立发布验证

| ID | 能力 | P0 验收结果 |
|---|---|---|
| P0-15 | Benchmark Adapter | 统一 Adapter 接口；τ³ 是参考实现；JSONL Outcome Adapter 支持社区自有确定性评测 |
| P0-16 | Trial Reset | 每次 Trial 从相同初始状态开始并生成 `initial_state_digest` |
| P0-17 | Infra Invalid | Provider/Runner、Host Turn 预算、协议兼容或证据链失败不计 Agent 成败；Benchmark 已形成完整结果的任务级 `timeout` 依 Adapter 合同判为有效失败；两者均保留原记录、费用/时间边界，Infra Invalid 有限重试，修复后以版本化协议对称重跑 |
| P0-18 | Outcome-first / Eval Incident | 合法替代路径只要结果正确且不违规，不因非必要路径差异判失败；Outcome/路径冲突自动建 Incident，未解决前同时阻断 Candidate 与 Ship |
| P0-19 | 多池评测 | Pilot、Update-Source、Update-Check、Selection、Release-ID、Release-OOD 物理互斥 |
| P0-20 | 可靠性与回归 | Release 使用 `Pass^k`；Replay 检测遗忘；灾难性回退触发 HOLD |

### 2.4 P0-D：DeepSeek Harness 社区插件

| ID | 能力 | P0 验收结果 |
|---|---|---|
| P0-21 | 原生 Bundle | `@agentloopgate/dsh-plugin` 通过官方 Bundle/Profile 机制加载，不 Patch Harness Core |
| P0-22 | AgentLoopGate Service | 在 Cordis Context 中提供版本化 AgentLoopGate 服务定义与 Provider |
| P0-23 | Python Bridge | 插件通过本地 `stdio JSONL` 调用 Python Core；Schema 和错误码稳定 |
| P0-24 | Trace Adapter/Observer | 旁路订阅 DeepSeek Session 事件并规范化；不替换 JSONL/SQLite Persistence 或 OTel Telemetry |
| P0-25 | 社区工具面 | 默认暴露状态、合同校验、候选校验、决策解释；Propose 需显式启用 |
| P0-26 | 权限边界 | 模型永远不能打开 Final、改 Gate、改 Split、Promote 或扩大插件权限 |
| P0-27 | 生命周期 | 在 pin 的 `headless` Profile 中可加载、调用、卸载；卸载无残留 Effect |
| P0-28 | Core Independence | 未安装或关闭插件时，Python CLI、Gate、报告和 Fixture Demo 仍完整可用 |
| P0-29 | 社区 Bootstrap | `agentloopgate init --runtime deepseek-harness` 生成最小配置并报告 observe/check/govern 三档 Readiness |

### 2.5 P0-E：可复现开源交付

| ID | 能力 | P0 验收结果 |
|---|---|---|
| P0-30 | No-key Demo | 一条命令运行 Fixture 的基线、候选、Gate、报告和插件 Conformance |
| P0-31 | Public Release | 公开仓库、明确许可证、锁文件、第三方声明、Quickstart 和 Release Artifact；源码打包只遍历显式发布 Allowlist，不扫描或收录被忽略的运行证据目录 |
| P0-32 | 真实实验包 | 保存脱敏配置、聚合结果、候选 Diff、决策卡和失败案例 |
| P0-33 | Banking 纵向验证 | 3—7 个 Pilot 由 DeepSeek Harness 承载模型会话、τ³ 执行工具并判 Outcome，AgentLoopGate 关联双侧证据并完成诊断与 Gate |

### 2.6 P0 最终交付物

v1 只要求以下八类交付，不再为同一证据生成多份文档：

1. 可复现的公开仓库与 README；
2. 可独立运行的 `agentloopgate` Python CLI；
3. `Objective Contract`、数据池 Manifest、Asset Manifest 与冻结 Hash；
4. A0 基线、至少 3 个候选、同一 Snapshot 梯子与双选择器对照；
5. 安全/成本结果、至少一个真实拒绝案例，以及 DeepSeek 插件 × Banking Pilot 纵向验证；若
   Selection 选出候选，还必须有真实 ID/OOD/Replay 结果；若 Selection 弃权，则必须改为提供
   正常终态的 Selection-HOLD 报告、逐候选原因、完整成本/时间/重试证据和 Release 零启动证明；
6. 最终 Decision Record 与可回滚 Snapshot；
7. 可安装、可卸载、兼容原生 Trace 的 DeepSeek Harness 插件包及一份集成说明；
8. No-key Demo、四张核心图和 2—3 分钟演示。

### 2.7 明确退出 P0 的内容

以下内容不是被否定，而是移入 `LATER.md`，不得阻塞 v1：

- 97 个任务的完整 Agent Capability Map；
- Evaluation-to-Data 训练数据配方和样例包；
- 2 模型 × 2 Harness 联合实验；
- Langfuse 或第二套外部 Trace UI；
- Web 控制台；
- 多 Runtime Host；
- AHE/ACE 之外的优化器排行榜；
- 自动执行 Risk-H 代码修改；
- 全量人工 Task Audit、双人盲标 κ、LLM Grader 校准平台；
- 16 张图表、英文论文、原创证明包和多份重复设计文档。

### 2.8 非目标

- 不训练或修改基础模型权重；
- 不自建 Benchmark、银行系统或通用 Observability 平台；
- 不允许 Updater 修改任务、Gold、评测器、Objective、Gate 或数据划分；
- 不做真实生产流量、自动灰度或无人审批发布；
- 不把 DeepSeek Harness 插件写成第二份 Python Core；
- 不以“首次提出”或工件数量作为项目价值。

---

## 3. 系统架构与信任边界

### 3.1 组件关系

```text
τ³ Runner ----------> τ³ Raw Result ----------------------+
                                                           |
DeepSeek Agent -----> append-only Session Log ------------+---> SourceTraceRef
                       |                                   |          |
                       +--> JSONL / SQLite Persistence     |          v
                       +--> OTel（可选，继续工作）          |   Evidence Receipt
                       +--> AgentLoopGate Observer ------------+          |
                                                                      v
                                                               Normalized Records
                                                                      |
                               +----------------------+---------------+-----------+
                               |                      |                           |
                               v                      v                           v
                          Diagnosis              Evaluation                 Cost Ledger
                               |                      |                           |
                               v                      +------------+--------------+
                        FailureBundle                            |
                               |                                 v
                               v                          Promotion Gate
                        AHE / ACE Adapter                        |
                               |                                 v
                               v                     Decision + Snapshot + Report
                          Candidate Patch
```

DeepSeek Harness 插件和 τ³ Adapter 是两个输入 Surface。通用接入时二者可以独立使用；Banking
Reference Validation 中，DSH 承载同一个 Target Agent 的模型会话，τ³ 承载真实工具执行、环境
状态与独立 Outcome。它们共享 SourceTraceRef、RunRecord、Candidate、Gate 和 Report，不各自
实现一套规则，也不能把两次互不相干的运行伪装成一次纵向验证。

### 3.2 Trace 证据层级

AgentLoopGate 对所有 Runtime 使用同一套三层证据模型：

| 层 | 作用 | τ³ 来源 | DeepSeek Harness 来源 |
|---|---|---|---|
| H0 Host Trace | 宿主运行事实，“实际发生了什么” | τ³ Raw Result/Trace | append-only Session Log |
| L0 Evidence Receipt/Mirror | 保存来源指针、序号范围、Hash、采集状态和必要脱敏副本 | τ³ Artifact Ref | `session.id + event.seq`、Digest、可选镜像 |
| L1 Normalized Record | 统一诊断、评测和 Gate 字段 | RunRecord | RunRecord |

规则：

- H0 不被 AgentLoopGate 修改；
- L1 必须回链 L0，L0 必须回链 H0；
- Gate 读取 L1，但正式决策前必须通过 Evidence Verify；
- 若 H0 可能被宿主清理，`trace_ingest_mode=mirror` 必须保存经过脱敏的必要事件副本；
- 正式 Run 只有在 H0 保留期覆盖复现期且 Revision 可验证时才可使用 `reference`；否则必须使用 `mirror`；
- DeepSeek OTel 是可选的外部观测出口，不是 Gate 事实源，因为它可以关闭、采用 best-effort 交付或应用不同的 Redaction；
- AgentLoopGate 插件不得注册一个与现有 `ctx.sessionTelemetry` 冲突的 Backend。

### 3.3 Governance Trust Kernel

以下内容属于不可变信任核：

- Objective Contract 及其 Hash；
- 数据池 Manifest、ACL 和 Final 访问规则；
- τ³ 任务、初始状态、Gold、Evaluator 与 Grader；
- Leakage Scanner、Mutation Policy 和 Promotion Gate；
- SourceTraceRef、Evidence Receipt/Hash、Snapshot Manifest、Decision Record；
- Promote/Rollback 的人类授权边界。

Updater、DeepSeek Harness 插件、模型工具和外部 Trace 平台都不能替换、覆盖或绕过信任核。

### 3.4 可变 Harness

`configs/harness_assets.yaml` 必须登记以下资产族：

| 资产族 | 示例 | P0 自动能力 | 默认风险 |
|---|---|---|---|
| Prompt/Instruction | system prompt、完成检查表 | 允许生成、检查、评测 | L |
| Context/Memory/Skill | playbook、经验库、恢复指南 | 允许生成、检查、评测 | L/M |
| Retrieval/Search Policy | query 拆解、top-k、rerank、停止条件 | 允许生成、检查、评测 | M |
| Tool Contract/Routing | 描述、Schema、参数校验、路由 | 允许生成、检查、评测 | M |
| Orchestration/State | 顺序、重试、验证、恢复配置 | 仅登记配置型资产并评测 | M |
| Middleware/Runtime Code | Hook、权限、依赖、可执行代码 | 可登记和生成提案；P0 禁止自动执行 | H |

“广义 Harness”是长期资产模型；P0 的安全执行面聚焦 L/M。Risk-H 候选可以被记录，但必须自动 `HOLD_RISK_H`，不能进入正式 RC。

### 3.5 依赖方向

```text
schemas <- core services <- CLI
schemas <- bridge protocol <- DeepSeek Harness plugin
adapters -> core services
updaters -> candidate registry -> evaluation -> gate
reporting -> normalized records + decisions
```

禁止 Python Core 依赖 DeepSeek Harness。插件可以依赖生成的 JSON Schema/TypeScript 类型，但不得手写另一套不一致的业务规则。

### 3.6 RuntimeTraceAdapter 接口

Core 只依赖宿主无关的 Trace 接口，τ³ 与 DeepSeek Harness 分别实现 Adapter：

```python
class RuntimeTraceAdapter(Protocol):
    def attach(self, source: RuntimeSource) -> SourceTraceRef: ...
    def sync(self, ref: SourceTraceRef) -> EvidenceReceipt: ...
    def verify(self, ref: SourceTraceRef) -> EvidenceStatus: ...
    def normalize(self, receipt: EvidenceReceipt) -> list[RunRecord]: ...
```

新 Runtime 只需提供这四个动作和确定性 Outcome Adapter，无需修改诊断、Updater、Gate、Snapshot 或报告模块。Adapter 必须使用宿主公开 API；若宿主只提供导出文件，则该文件必须有稳定身份、Digest 和可校验的事件顺序。

---

## 4. Objective Contract 与 Promotion Gate

### 4.1 合同最小 Schema

`configs/objective_contract.yaml`：

```yaml
contract_version: "1.0"
project: "AgentLoopGate"
primary_metric: "reliable_policy_compliant_resolution"
benchmark:
  name: "tau3-bench"
  suite: "banking_knowledge"
  commit: "PIN_BEFORE_PILOT"
reliability:
  trials: 3
  stable_success_required: 3
gates:
  leakage_hits_max: 0
  critical_violations_max: 0
  id_stable_task_net_min: 0
  ood_stable_task_net_min: -1
  replay_stable_task_net_min: -1
  catastrophic_regressions_max: 0
  mean_cost_ratio_max: 1.20
  p50_latency_ratio_max: 1.25
decision_order:
  - evaluation_integrity
  - leakage
  - critical_violation
  - id_effect
  - ood_noninferiority
  - replay
  - reliability
  - cost
  - latency
frozen_at: null
contract_digest: null
```

Pilot 后、任何正式候选结果产生前，填入真实 commit、阈值、冻结时间和规范化 SHA256。冻结后变更必须创建新合同版本，不得覆盖旧文件。

### 4.2 指标

**结果：**

- `Pass^1`：单次严格成功；
- `Pass^k`：同一任务 k 次全部成功；
- `stable_success_task_count`：满足 Pass^k 的任务数；
- `terminal_state_correct`：最终状态正确。

**诊断：**

- Gold Document Recall/Full Coverage；
- 正确工具发现、选择、参数和顺序；
- Search-to-Action Conversion；
- 恢复成功率。

Gold 只用于离线诊断，禁止进入 FailureBundle 的可见文本或 Candidate Patch。

**安全：**

- Critical Violation Count；
- Policy Violation Rate；
- Unsupported Action Rate；
- User-claim Overtrust。

**效率：**

- Token、模型调用、检索调用、工具调用；
- 延迟、单任务成本；
- 每新增一个稳定成功任务的边际成本。

### 4.3 不使用单一加权总分

Gate 使用字典序：先评估完整性和安全硬门，再看 ID/OOD/Replay，再看可靠性、成本和延迟。任何综合分只可用于画 Pareto 图，不能覆盖硬门失败。

### 4.4 Gate 决策算法

```python
def decide(candidate, baseline, contract):
    if not evaluation_integrity_complete(candidate, baseline):
        return HOLD("evaluation_integrity")
    if candidate.mutates_trust_kernel or candidate.leakage_hits > 0:
        return REJECT("trust_boundary_or_leakage")
    if candidate.risk_tier == "H":
        return HOLD("risk_h_not_executable_in_v1")
    if candidate.release_critical_violations > 0:
        return HOLD("critical_violation")
    if candidate.id_stable_tasks - baseline.id_stable_tasks < contract.id_min:
        return HOLD("id_effect")
    if candidate.ood_stable_tasks - baseline.ood_stable_tasks < contract.ood_min:
        return HOLD("ood_noninferiority")
    if candidate.replay_stable_tasks - baseline.replay_stable_tasks < contract.replay_min:
        return HOLD("replay_regression")
    if candidate.catastrophic_regressions > 0:
        return HOLD("catastrophic_regression")
    if candidate.mean_cost / baseline.mean_cost > contract.cost_ratio_max:
        return HOLD("cost")
    if candidate.p50_latency / baseline.p50_latency > contract.latency_ratio_max:
        return HOLD("latency")
    return SHIP_RECOMMENDED
```

`SHIP_RECOMMENDED` 不是自动发布。只有人类执行 `agentloopgate snapshot promote` 后，Snapshot 才进入 `SHIPPED`。

### 4.5 灾难性回退

若 A0 在某任务为 `k/k`，候选为 `0/k`，记为灾难性回退。高风险状态修改任务发生一次即 HOLD。

---

## 5. 数据划分、实验与评估完整性

### 5.1 97 个任务的冻结划分

| Pool | 数量 | 用途 | Updater 可见性 |
|---|---:|---|---|
| Pilot | 7 | 接入、成本、字段和规则校验 | 可见；永久排除正式结果 |
| Update-Source | 25 | 产生失败证据和候选 | 可见 |
| Update-Check | 10 | 迭代快速筛选 | 仅聚合结果，Trace 不回传 |
| Selection | 15 | 在冻结候选中选择 RC | 不可见 |
| Release-ID | 20 | 独立同分布确认 | 终点前不可见 |
| Release-OOD | 20 | 按完整工作流族预留的迁移确认 | 终点前不可见 |

Replay 从 Update-Source 预注册 10 个代表性任务，不新增数据池。

每个池保存独立 JSON Manifest 和 SHA256。正式候选生成前运行 `split freeze`；冻结后禁止移动任务。

### 5.2 OOD 构造

在看候选结果前，按业务工作流、产品类别、高风险状态修改、文档数和工具调用复杂度聚类，预留 2—3 个完整工作流族作为 Release-OOD。禁止从随机切分中事后挑选“不利任务”包装成 OOD。

### 5.3 Outcome-first

- 主判据是最终状态与必要政策，不是是否复现唯一 Expected Action 路径；
- Action 顺序只有在改变业务语义或安全性时才是硬门；
- Outcome 与路径 Grader 冲突时创建 Eval Incident，不得默认归因于 Agent；
- v1 不使用软性 LLM Grader 参与 Ship/Hold。

正式诊断必须把“有效 Run、官方 Outcome 失败、DB 不匹配、且全部 Expected Action Check 均匹配”
至少识别为保守的 `evaluator_conflict`。这只是触发调查，不得直接把失败改判为成功；调查必须在
冻结的初始状态上执行脱敏状态差分，并区分顺序/额外副作用、Agent 行为、Evaluator 算法与 Task
Fixture 缺陷。任何一个未解决 Eval Incident 都必须在把 FailureBundle 交给 AHE/ACE 之前阻断整个
候选生成阶段，不能只过滤冲突 Bundle 后继续用同一批次的其他失败生成候选。

若确定是 Task/Gold/Evaluator 缺陷，原始 Raw、官方 Outcome、成本与重试记录保持不可变；修复必须
以独立、内容寻址的 Evaluator/Task Overlay 表示，校验上游 commit、原 Task Hash、Overlay Hash 和
适用 Task 集，并进入新的 ExecutionProtocol、Experiment、Baseline 与 Batch 身份。禁止就地修改
被 pin 的上游 checkout，也禁止使用候选轨迹反推或补写 Gold。零模型因果隔离只用于 Incident
裁决，不能在旧实验中覆盖官方分数；决策级证据必须按第 5.5 节对受影响 A0 与全部候选对称重跑。

τ³ 参考实现固定使用 `tau2-bench v1.0.1`、commit
`fc0055dc4e0a316c3f83133267fbd6faaa770992`。运行时通过
`uv run --with socksio==1.0.0` 注入精确依赖，使宿主使用 SOCKS 代理时仍保持可复现；不得
修改上游源码来隐式修补运行环境。Adapter 必须清除父 `uv run` 的解释器标记、强制 τ³
子进程使用 UTC，并将该固定版本产生的无时区时间解释为 UTC。Adapter 以官方
`reward_info.reward` 在官方容差内等于 `1` 作为严格成功；`action_checks` 默认只进入离线诊断，
只有 `reward_basis` 明确包含 `ACTION` 时才参与上游 Outcome。仅官方
`termination_reason=infrastructure_error` 直接映射为 τ³ Infra Invalid；AgentLoopGate 自身发现的
Reset、Evidence 或 Evaluator 完整性错误仍按第 5.5 节映射。τ³ Raw Result 的 `agent_cost/user_cost`
是宿主展示与交叉核对证据，不再作为协议 1.6+ 的成本权威；有效运行的 Agent 与 User 成本必须从
最终保留 Simulation 所绑定的直接 Task Attempt 模型调用账本，按冻结 Token 单价重算。Token 从
已验证调用事件的 `usage` 汇总，延迟取 `duration`。有效运行缺少正式 Gate 所需的成本或评测证据时
必须标记评测不完整，不得静默补零。对于没有形成可计费 τ³ 结果的 Infra Invalid，Raw `agent_cost`
可以保持未知（`null`），不得推断为零；它不进入业务成功率或有效运行成本 Gate，但必须保留
Infra Invalid 状态、执行时间、失败类型、重试拓扑以及可验证的 DeepSeek Harness Trace/Token
事实。失败尝试的 Trace 推导成本只能作为恢复成本旁证，不得回填为 τ³ `agent_cost`。

Protocol `1.7+` 的 `EvaluationSummary.mean_cost` 必须等于该批次所有有效 Run 的直接 Agent 与 User
精确费用之和除以有效 Run 数，并绑定对应 Cost Artifact Digest 与 `cost_status=exact`。候选曲线、
选择器与最终 Cost Gate 只能消费这个绑定值；不得重新读取 RunRecord 或 τ³ Raw Result 的成本字段。
跨多个批次计算平均成本时必须按各批次 `valid_run_count` 加权，不得对“批次均值”再做无权平均。

社区 JSONL Outcome 必须声明独立 Evaluator 身份、被评系统身份、Pool、Snapshot，并引用可校验
Digest 的 Evaluator Evidence Artifact。Evaluator 与被评系统相同、Evidence 缺失或上下文不匹配时
拒绝导入；JSONL 中的自报分数不是治理证据。

### 5.4 Trial Reset

每个 Trial 必须：

1. 恢复数据库、Fixture、Harness Snapshot 和缓存到冻结初始状态；
2. 以 `run_id/attempt_id` 隔离工作目录和 Session；
3. 禁止读取其他 Trial 的 Trace、候选结果和残留会话；
4. 记录 `initial_state_digest`、`terminal_state_digest` 和环境健康状态；
5. A0 与候选使用相同模型、资源、超时和工具面。

### 5.5 Infra Invalid

以下情况标记 `infra_invalid`，不进入成功/失败分母：Reset Hash 不符、依赖服务不可用、Evaluator
崩溃、Trace 缺失、共享资源故障、Provider/Runner 系统错误、模型以 `max-tokens` 终止、Turn 超时，
或模型已返回可解析内容但冻结的 Reply/Trace 协议无法无损消费。不得把这些错误记为 Task Failure，
也不得用无效运行的零分指导候选方向。

- 每个 `(Experiment, Batch, task_id, trial, seed)` 最多自动重试 1 次，即初次执行加 1 次重试；
- 该预算是跨进程、跨 `--auto-resume` 的全局预算，Resume 只能消费剩余额度，不能重新领取；
- 每次真实 Task Attempt 必须在调用模型前写入独立的 append-only Task Attempt Ledger；已写
  `STARTED` 而无终态的 Attempt 也保守计入预算，防止进程中断后重复付费或无限重跑；
- Task Attempt Ledger 必须在首次 Agent 调用前追加实际 DSH Session Hash 绑定；Agent 与 User
  Model Usage Ledger 的每个调用事件必须直接带 `task_id/trial/seed/attempt_index`，失败尝试不得依赖
  时间窗或会话命名规则才能归属到任务位置；
- 原失败记录必须保留；
- 超过上限则该批次 HOLD；
- 修复 Grader 或环境 Bug 后，必须对 A0 与全部受影响候选对称重跑。

“受影响”按内容寻址的 Task/Evaluator 依赖闭包计算，不等于无条件重跑全部 97 个任务：未改变
Task、Gold、Evaluator、初始状态、Harness Snapshot、模型、预算和 Gate 的既有 Run 可以保留为
历史证据，但不得被拼接进一个伪装成原生完整 Batch 的新结果。若正式统计需要合并未受影响证据，
必须使用预先实现并通过 Fixture 验证的 Composite Evidence Artifact，逐 Run 绑定来源 Experiment、
原始字节 Hash 与适用性证明；P0 若没有该能力，就在新实验中重跑完整受影响 Pool，不得手工拼表。

即使批次因 Infra Invalid 或缺失有效 Trial 而 HOLD，也必须封存原始结果、Trace、RunRecord、
Evidence Join、完整性问题和 HOLD 原因，不能让“封存失败”遮蔽“评测失败”。纯证据表示层修复
（不改变原始 Outcome、任务执行、成功判据或有效运行成本）可以在 Eval Incident/ADR 授权后，
对同一份不可变原始字节重新摄取并生成 HOLD Artifact，无需再次调用模型；该快速裁决不能把
HOLD 改写为通过，也不能替代后续获得决策级证据所需的对称重跑。

每次正式调用无论成功或失败，都必须先把宿主原生 Session Trace 与 Runner Envelope 刷盘，再
写终态。Adapter 应从已验证的原生 Trace/Envelope 恢复输入、缓存命中、输出 Token、模型费用、
finish reason 和耗时；可验证值进入 Attempt 的已知费用，无法验证的范围保留为 `unknown`，不得
记为零。τ³ Raw Result 的 `agent_cost/user_cost` 与直接模型调用账本是不同口径：Raw 值只作为
宿主展示与差异审计证据；协议 1.6+ 的有效运行成本 Gate 必须沿
`retained Simulation → completed Task Attempt → Agent/User model calls` 直接归因，并由冻结价格
重算。全部直接账本与可验证 Raw 值共同支持整次 Attempt 的费用核对。报告必须分别列出直接有效
运行成本、Raw 对照值与不一致计数、全 Attempt 已知下界、未知费用范围和本地计算时间。
User Simulator 必须另写进程级 append-only 调用账本，使被 τ³ 重试、替换或中断的运行仍保留
`STARTED/COMPLETED/FAILED`、Token、费用、耗时与错误终态；不得只依赖最终 Raw Result。
若 User Simulator Provider 调用返回的整条回复既没有非空最终文本也没有 Tool Call，协议可以冻结
一次 `bounded_same_call_context_final_only_v1` 修复：只在原对话后追加“补交缺失用户回复”的指令，
不得读取 Formal Gold、引入新事实、改变用户目标、推断工具或补全参数。原调用与修复调用必须分别
写入账本，保留各自 Token、费用和终态；修复成功时，τ³ 保留结果必须聚合两次 Usage，直接冻结价格
逐调用账本仍为成本权威。第二次仍为空、坏结构或不合法 Tool Call 必须按原 Attempt fail closed，
不得发起第三次调用。该能力只恢复 User Simulator 消息完整性，不能把业务失败改写为成功。

协议冻结的输入、缓存命中与输出单价必须在任何付费 User Simulator 调用之前可读且为非负有限
Decimal；缺失或非法必须在调用前失败。每个 `exact` 调用必须同时具有三个可验证 Token 计数，其
费用只允许按冻结单价计算，动态远程价格表、Provider/LiteLLM 返回的 `result.cost` 和 Raw Result
均不得覆盖该值。只要任一正 Token 对应正冻结单价，精确费用就必须大于零；否则 reconciliation
必须失败并使批次 HOLD。缺 Token 或无法验证费用必须记为 `unavailable/partial`，不得降为零。

成本有两个不得混淆的判定面：`valid_cost_status` 只判断进入分母的有效 Run 是否具备精确 Agent
与 User 成本，直接服务业务成本 Gate；`whole_attempt accounting_status` 判断包括无效、重试、
中断和未保留调用在内的运营总成本是否完全可观测。前者非 `exact` 必须 HOLD；后者允许以
`partial` 的明确下界进入报告，前提是所有未知范围逐项披露、没有把未知记零，且 Evidence
Integrity 与有效 Run 成本均通过。`partial` 运营下界本身不得冒充精确总成本，也不得参与候选
优劣排序；当 `whole_attempt accounting_status=exact`、Agent/User 未结算调用均为 0 时，精确的
全 Attempt 总成本必须作为 Selection 的次级运营证据，同时仍不能覆盖正确性和安全硬门。

任何新的付费正式实验还必须引用冻结、可验 Digest 的 `ExecutionProtocol`，至少固定并校验
模型精确 ID、每 Turn 最大输出 Token、Turn/Simulation 超时、重试次数/间隔、并发、Resume、
时区、跨 Resume 的全局 Task Attempt 上限、网络路由、Reply/Trace 协议版本、User 调用账本、
成本 Gate 范围、冻结价格权威、直接 Task Attempt 成本归属、Raw 对照策略、正 Token 零成本拒绝
策略、成本缺失策略和延迟证据口径；其 Digest 必须进入
`FormalBatchSpec` 和 Batch ID。正式冻结前，必须在不泄露 Formal Task/Gold 的 Pilot 或确定性
复杂度 Fixture 上覆盖短回复、长推理、多 Tool 与状态修改四档，验证模型不会系统性触顶且完整
调用可在超时内落盘。校准只决定执行预算，不参与候选选择或结果打分。正式 preflight 必须使用
无模型 Fixture 强制覆盖：上游返回零但存在正 Token 时按冻结价格重算、缺单价时调用前失败、Raw
与直接账本不一致时直接账本保持权威，以及伪造的“正 Token + exact 0”账本被拒绝。

旧实验或旧 Selection 设计只允许 existing-only 验真，不能继续产生新的正式运行。新的付费工作
必须同时使用 Formal Config schema `1.2`、Protocol `1.8+`、Study `1.2+` 和新的 Baseline。
Formal Config 必须绑定一个位于运行证据命名空间、不会改变执行源码身份的私有 Authorization Root。

付费授权分为两个不可合并的内容寻址 Scope：`pre_release_checkpoint` 只允许
Update-Source/Update-Check/Selection，并精确绑定 125 个位置；`release_tail` 只允许
Release-ID/Release-OOD/Replay，并精确绑定 450 个位置、已验证的 `SELECT` Selection Digest 与
governed Candidate ID。后者不得在 `HOLD/ABSTAIN` 或已有 `selection_hold_outcome.json` 时创建。
CLI preflight 与 `FormalExperimentService` 必须在每个新付费 Stage 前分别验真适用授权；直接调用
Service 不能绕过。`existing-only` 不要求付费授权且绝不能调用模型。

`agentloopgate experiment authorize-paid` 必须要求逐字确认语句，输出
`paid_execution_started=false`、`model_calls=0` 与 `cost_status=not_applicable`；它只封存精确
Scope 的机器能力凭据，不能启动 Batch。2026-08-23 起，Owner 已对实现冻结研究目标所需的私有实验
授予持续委托：受托研究 Operator 在冻结并审计精确 Scope 后可代为创建该凭据，无需逐批再次请求
聊天确认；这项委托包括满足 `SELECT` 前置条件后的 Release-ID/OOD/Replay 评测，但不包括 Promote、
部署、改变仓库可见性、发布 GitHub Release、公开证据或投稿。仅存在 API Key、通过 preflight、过去
授权或 Coding Agent 自行推断仍不构成许可；持续委托及每个精确机器凭据必须同时可审计。历史实验的
原授权边界保持不可变。治理记录见 `docs/research/standing-experiment-mandate.md`。

### 5.6 最小评估审计

P0 不建设大型评估审计平台，但必须完成：

- 97 个任务的 Manifest、Task、Grader 与初始状态 Hash 自动审计；
- 7 个 Pilot 的 Reference/Reset/合法替代路径 Fixture；
- 正式运行中所有 Critical Violation、灾难性回退、Outcome 冲突和 Infra Invalid 的人工复核；
- 所有未解决 Eval Incident 同时阻止 Candidate 生成与最终 Ship；
- Fixture 覆盖“全部 Action 匹配但 DB 不匹配”自动建 Incident、冲突 Bundle 不外发、以及任一
  未解决 Incident 阻断其他 FailureBundle 进入 Updater。

### 5.7 候选实验流程

1. 在 Update-Source 运行 A0；
2. 输出失败漏斗和 Top FailureBundle；
3. AHE 生成 Candidate；若满足第 7.6 节 Tripwire，冻结 ADR 后改用 ACE；
4. Candidate Check 检查路径、信任核、泄漏、风险和 Diff 预算；
5. 在 Update-Check 筛查，最多保留 6 个候选；
6. 同一轮候选必须从同一个冻结 A0 形成兄弟 Snapshot，避免把前序候选的影响混入后序候选；
   本轮 Gate 选出的版本才可成为下一轮父 Snapshot，跨轮形成 `A0 → A1 → ... → An`；
7. 冻结后在 Selection 对 A0 与全部候选执行同池、同任务、同 Trial 的对称评测；
8. 在同一候选梯子上生成 `RC_native`；AgentLoopGate 以 A0 为下界生成
   `RC_agentloopgate` 或显式 `HOLD/ABSTAIN`；
9. 若 AgentLoopGate 弃权，在启动任何 Release 付费批次前停止并封存理由；只有新的、预注册的
   科学比较计划和 Owner 授权才可继续运行 Updater-native Release 分支；
10. 若选出候选，对 `RC_native`、`RC_agentloopgate` 和 A0 运行 Release-ID/OOD，不能隐藏任一
   选择器的失败；
11. 运行 Replay、Gate，输出最终决策；
12. 若 Ship，执行回滚演练；若 Hold，保留失败证据。

### 5.8 最小候选要求

- 最少 3 个、最多 6 个真实候选；
- 每个候选只有一个可证伪主假设；
- 同一 Parent、FailureBundle 与行为语义指纹下的同义改写只算一个候选；不能用文案近义改写
  填满 3—6 个候选名额；
- 至少覆盖 2 个 Harness 资产族；
- 至少 1 个候选被真实 Gate 拒绝；
- 不强制必须有通过 Gate 的候选。

---

## 6. 失败诊断与候选修改

### 6.1 失败分类

```text
retrieval_miss
document_selection_error
cross_document_reasoning_error
policy_application_error
tool_discovery_error
tool_selection_error
tool_parameter_error
action_order_error
state_verification_error
recovery_error
user_claim_overtrust
spec_or_evaluator_issue
infra_failure
unknown
```

失败优先级：

```text
priority = affected_task_count × user_value_loss × risk_weight × fixability
```

该值用于排序 FailureBundle，不进入发布 Gate。

### 6.2 FailureBundle 最小字段

```json
{
  "failure_bundle_id": "FB_001",
  "snapshot_id": "A0",
  "source_pool": "update_source",
  "failure_type": "policy_application_error",
  "affected_run_ids": ["R_001"],
  "evidence_refs": ["runs/normalized/R_001.json"],
  "redacted_summary": "Agent 找到主规则但遗漏例外条件",
  "target_asset_families": ["context_memory_skill", "retrieval_search_policy"],
  "expected_behavior_change": "执行前核对例外与必要前置条件",
  "must_not_change": ["objective", "grader", "split", "final_access"],
  "budget": {"max_files": 4, "max_changed_lines": 160}
}
```

FailureBundle 禁止包含 Release 任务、Gold 文档清单、Expected Action 或目标状态答案。

### 6.3 Candidate 最小要求

Candidate 必须保存：

- `candidate_id`、`parent_snapshot_id`；
- `updater` 和精确版本/commit；
- 单一主假设；
- 目标资产族、Risk Tier；
- Patch/Diff 路径和 Hash；
- 来源 FailureBundle Hash；
- 修改前预测；
- Candidate Check 结果；
- Update-Check/Selection/Release 结果；
- 最终状态与拒绝理由。

### 6.4 修改预算

默认单候选：

- 最多 4 个文件；
- 最多 160 行净变更；
- 必须有明确回滚单元；
- 多资产修改必须说明为何属于同一原子变化；
- 超预算自动 `REJECT_CHANGE_BUDGET`，不得静默拆分后沿用同一 ID。

---

## 7. Updater Adapter

### 7.1 统一接口

```python
class UpdaterAdapter(Protocol):
    name: str
    version: str

    def doctor(self) -> UpdaterHealth: ...

    def propose(
        self,
        parent_snapshot: SnapshotManifest,
        failure_bundle: FailureBundle,
        asset_manifest: HarnessAssetManifest,
        mutation_policy: MutationPolicy,
        count: int,
    ) -> list[CandidateRecord]: ...
```

Adapter 只负责把项目证据交给外部方法并接回 Patch。Candidate Check、评测和发布决策必须由 AgentLoopGate Core 完成。

### 7.2 P0 Updater 决策

- 默认：AHE；
- 降级：ACE；
- 禁止：同时跑多种方法后选择结果最好者；
- P0 完成条件：AHE 或 ACE 至少一个真实外部方法生成可登记 Candidate；纯手写 Candidate 只能用于 Fixture，不能满足真实实验验收。

P0 的 AHE pin 为 `agentic-harness-engineering 0.1.0`、commit
`8b2a55d97590363fe50c3cc6b5e833b020a4bb4c`，其 NexAU 依赖由上游锁定到 `v0.3.9`。
AHE 必须在与 Core 隔离的 Python 3.13+ 环境运行；只把 FailureBundle 命中的父 Snapshot 白名单资产
复制进临时 Workspace，并通过 OS Sandbox 将写权限限制在该 Workspace。AHE 原始 Trace、版本、
输入 Hash、Token/成本与文件 Diff 回收后仍须经过 Core Candidate Check。API Key 只从进程环境继承，
不得写入 AHE 配置快照。未触发第 7.6 节 Tripwire 时，ACE 保持禁用。

AHE 及其 NexAU 依赖产生的 bash stdout/stderr、长工具输出、缓存、`TMPDIR` 与其他中间文件必须全部
路由到当前内容寻址 Attempt 的 `.runtime` 子目录，禁止依赖进程全局 `/tmp` 默认路径。`doctor` 必须
在与正式 Updater 相同的 OS Sandbox Profile 中真实执行一次零模型 NexAU bash 命令，验证命令、输出
与错误证据均落在该 Attempt 根内；此预检失败时必须在首次 Updater 模型调用前停止。只检查 Python
import、只改 `TMPDIR` 或允许整个 `/tmp` 写入均不能满足本项。

### 7.3 AHE 可见范围

AHE 进程只能读取：

- 父 Snapshot 的可变 Harness 资产；
- Update-Source 的脱敏 FailureBundle；
- Harness Asset Manifest；
- Mutation Policy；
- 候选工作目录。

AHE 禁止读取 Selection、Release、Gold、Evaluator 源码、Objective/Gate 写权限和历史私有决策。

### 7.4 AHE 输出适配

Adapter 必须将外部输出规范化成 CandidateRecord，并保存：

- 原方法输出的不可变副本；
- 方法版本、输入 Hash、Token/成本；
- 实际文件 Diff；
- 无法映射字段的明确 `unsupported_fields`；
- 失败时的退出码和 stderr 摘要。

### 7.5 Updater-native 与 AgentLoopGate Selector

两种选择器读取完全相同的 Candidate Ladder：

- `RC_native`：按外部 Updater 原生更新/选择信号得到；
- `RC_agentloopgate`：按冻结 Objective、A0 Selection 基线、安全与运营非劣约束得到；允许为空。

AgentLoopGate Selector 必须满足：

1. A0 和候选的 `stable_task_outcomes` 任务集合完全一致，且 Evaluation Integrity 完整；
2. 候选不能把 A0 的任一稳定成功任务变为失败；`stable_success_task_count` 必须严格高于 A0；
3. 关键违规必须为 0；
4. 成本同时保存有效 Run 的直接 Agent+User 均值和精确 whole-Attempt 总额；排序/约束还必须读取
   Task Attempt 重试数、Timeout 数、p95 与最大延迟，不能只看 retained mean cost 与 p50；
5. 先按正确性，再按 Timeout、重试、p95、最大延迟、whole-Attempt 成本排序；成本不是第一 Gate；
6. 没有候选全部满足时输出 `HOLD/ABSTAIN`，`agentloopgate_candidate_id=null`，并保存逐候选原因；
7. Selection 基线、策略、候选输入、Cost/Task-Attempt/Batch 引用和最终选择共同进入不可变 Digest。

`HOLD/ABSTAIN` 是治理层成功拒绝提名候选的正常终态，不是基础设施异常，也不使用错误退出码。
编排器必须写出可幂等验真的 `selection_hold_outcome.json` 与 JSON/Markdown 报告，至少绑定
Protocol、Study、Source Revision、A0、全部候选、Selection、Lineage、所有已完成 Batch、候选
终态、每个成本 Artifact，以及 Updater 与正式批次的已知模型成本。未知费用必须逐项披露为
`partial/unavailable`，不得记零。该终态必须声明并验证 `release_batch_count=0` 与
`model_calls_after_selection=0`；重复 Resume 只验真已有 Artifact，不能触发 Release 或新模型调用。

若被 pin 的 Updater 不暴露结构化 score/selector（AHE `0.1.0` 的单次
`run_evolve_agent` 即如此），Adapter 必须把这一字段记为 `unsupported`，并以该方法明确的
continuation/emission 顺序作为 `RC_native`，同时保存信号来源。禁止从 AgentLoopGate 的
Update-Check 分数反向伪造“Updater-native score”。

比较目标是证明“治理选择层是否改变发布判断”，不是宣称 AgentLoopGate 发明了更好的自进化算法。

任何 `harness/tools/**` 候选必须绑定宿主当前 Turn 的真实 Tool Schema。Manifest 必须为工具路由
声明 `runtime_capability_routing` 语义校验；运行时逐项验证 `capability_ref`，未知目标 fail closed。
为了保持跨 DeepSeek Harness、τ³ 和其他宿主的可移植性，Candidate Check 不允许候选硬编码未绑定的
`capability:` 清单。工具路由资产仍可作为模型上下文，但其“目标存在”必须由运行时 Registry 校验，
不能仅凭 YAML 文案声称已经执行了路由治理。

### 7.6 AHE → ACE Tripwire

只有以下任一条件在最多 3 个工作日的真实 Spike 中成立，才允许提交 ADR 并降级 ACE：

1. AHE 无法在被 pin 环境启动或产生文件级候选；
2. AHE 不能限制写入 Asset Manifest 白名单；
3. AHE 必须读取 Final、Gold 或修改信任核才能工作；
4. AHE 输出无法回链输入证据、版本与 Diff；
5. AHE 的依赖/许可证阻止项目公开发布。

“AHE 结果不好看”不是降级理由。ACE 最多再投入 2 个工作日；仍失败则 P0 标记为阻塞，不用自研优化器冒充外部方法。

---

## 8. DeepSeek Harness P0 插件

### 8.1 产品定位

插件是 AgentLoopGate 面向 DeepSeek Harness 社区的原生接入与分发入口。社区开发者安装后，可以：

1. 继续使用 DeepSeek Harness 原生 Session Log、JSONL/SQLite Persistence 和 OTel Telemetry；
2. 将 DeepSeek Harness 的 Agent/Session/Tool 事实旁路映射为 AgentLoopGate Evidence Receipt 与 Normalized Record；
3. 查询当前合同、Core 健康和 Snapshot；
4. 校验候选是否越权、泄漏或超预算；
5. 查看某个候选为什么被 Ship/Hold/Reject；
6. 在显式授权后，从 Update-Source FailureBundle 请求外部 Updater 提案；
7. 通过 JSONL Outcome Adapter 导入自己的确定性评测结果；
8. 继续通过人类 CLI 运行正式评测和 Promote/Rollback。

插件不是新的 Trace UI，也不是新的 Persistence Backend。它在 DeepSeek 原生 Trace 之上增加治理语义。

### 8.2 官方宿主约束

DeepSeek Harness 当前是 Developer Preview。P0 兼容基线冻结为：

- npm 版本：`@deepseek-ai/dsh` 及相关宿主包 `0.1.0-rc.8`；
- 官方源码 commit：`141eb6fef83422698aef7a981029e843e8161534`；
- Node：`^22.19.0 || >=24.0.0`；pnpm：`11.7.0`；
- Runtime Profile：官方 `headless`；
- Bundle：manifest 的 `dsh.bundle.patch` + `dsh plugin --profile <name> add/remove`；
- Cordis：`Service`、`ctx.on(...)`、`ctx.effect(...)`；
- Trace：公开的 `session/created`、`session/event`、`session/flush`、`session/disposed`；
- Tool：`ctx.tools.register(defineTool(...))`；子进程：`ctx.subprocess.spawn(...)`。

P0 只声明对上述精确基线兼容。升级宿主版本前必须重新运行 build、类型检查、Bundle、
JSONL/SQLite/OTel 共存和生命周期 Conformance，不得仅放宽 semver 范围。

禁止根据本 SPEC 猜测未确认的官方函数签名。`docs/deepseek-harness.md` 必须记录被验证的源码路径、命令和兼容性结论。

### 8.3 插件包结构

目标结构；实际入口名以 pin 后官方规范为准：

```text
integrations/deepseek-harness/
├── package.json
├── pnpm-lock.yaml
├── tsconfig.json
├── cordis.patch.yml
├── src/
│   ├── service.ts       # ctx.agentLoopGate 契约
│   ├── provider.ts      # Python Bridge Provider
│   ├── observer.ts      # Session/Agent/Tool -> Evidence Receipt
│   ├── tools.ts         # 模型可见的受限工具
│   ├── commands.ts      # 人类直接命令；如官方 seam 可用
│   ├── policy.ts        # 工具权限与数据池限制
│   ├── bridge.ts        # stdio JSONL client
│   └── index.ts
└── test/
    ├── conformance.test.ts
    ├── permissions.test.ts
    ├── lifecycle.test.ts
    └── observer.test.ts
```

`package.json` 必须使用官方 `dsh.bundle`/Bundle 声明方式，把插件作为 out-of-tree Bundle 装入 Profile；禁止修改 DeepSeek Harness Core 或写入 `node_modules`。

### 8.4 Cordis Service

插件应声明一个版本化 `ctx.agentLoopGate` Service，最小方法：

```ts
interface AgentLoopGateService {
  health(): Promise<HealthResponse>
  validateContract(request: ContractValidateRequest): Promise<ContractValidateResponse>
  checkCandidate(request: CandidateCheckRequest): Promise<CandidateCheckResponse>
  explainDecision(request: DecisionExplainRequest): Promise<DecisionExplainResponse>
  ingestEvents(request: EventBatchRequest): Promise<EventBatchResponse>
  syncTrace(request: TraceSyncRequest): Promise<TraceSyncResponse>
  propose?(request: ProposeRequest): Promise<ProposeResponse>
}
```

Service Definition、Provider 和模型 Tool Consumer 必须可独立测试。卸载 Provider 后，所有注册的 Effect、事件监听和工具必须解除。

### 8.5 Python Bridge

默认 Bridge 是本地持久子进程：

```text
uv run agentloopgate bridge serve --project <project-root>
```

传输使用一行一个 JSON Envelope 的 stdin/stdout：

```json
{
  "protocol_version": "1.0",
  "request_id": "REQ_001",
  "method": "candidate.check",
  "payload": {},
  "actor": {"type": "dsh_plugin", "session_id_hash": "sha256:..."}
}
```

响应：

```json
{
  "protocol_version": "1.0",
  "request_id": "REQ_001",
  "ok": true,
  "result": {},
  "error": null
}
```

规则：

- JSON Schema 由 Python Pydantic 模型生成；TypeScript 类型从同一 Schema 生成；
- stdout 只输出协议 JSON；日志写 stderr；
- 最大请求体默认 1 MiB，事件批次默认 100 条；
- 重复 `request_id` 必须幂等返回，不重复执行修改；
- Bridge 不接受模型提供的任意 Shell 命令；
- Provider/Bridge 不可用时，读取返回明确 unavailable，修改请求 fail closed；
- 插件不得把 Secret、完整环境变量或 Final 内容发给 Bridge 日志。

### 8.6 原生 Trace 共存与 Observer

#### 8.6.1 共存合同

DeepSeek Harness 的 append-only Session Log 是 DSH Runtime 的 H0 事实源。AgentLoopGate Observer 必须是旁路消费者：

- 通过公开的 `ctx.sessions`、`session/event`、`session/flush` 和生命周期事件接入；
- 不注册或替换 `ctx.sessionTelemetry` Backend；
- 不关闭、不改写、不改变用户现有 JSONL/SQLite Persistence；
- 不关闭、不改写用户现有 OTel 的 `FULL/FEEDBACK_ONLY/DISABLED` 配置；
- 不直接解析某个持久化文件格式作为唯一实现路径，以兼容 JSONL 和 SQLite Provider；
- 不向 DeepSeek Session 反写 AgentLoopGate 判分、Gold、Gate 或 Final；
- 插件卸载后，原生 Session、Persistence 和 Telemetry 行为必须与安装前一致。

#### 8.6.2 采集模式

```yaml
trace:
  source: deepseek_session
  ingest_mode: reference   # reference | mirror
  live: true
  backfill_on_start: true
  max_batch_events: 100
  max_buffer_events: 1000
  redact_policy: configs/trace_redaction.yaml
```

- `reference`：默认。保存 SourceTraceRef、事件身份、Hash 和治理所需字段，不复制完整内容；
- `mirror`：当宿主 Trace 保留期不能覆盖实验复现期时启用，保存必要且脱敏的事件副本；
- 两种模式都不得依赖 OTel 是否启用；
- 使用 `(runtime_host, session.id, event.seq)` 去重，保存连续 Cursor；
- Live firehose 只承担低延迟采集；每次 Session flush 必须以公开 `session.events` 权威快照做有界对账，补录构造、Resume 或瞬时缓冲压力下未被 live 观察到的事件；
- Hot Reload/Resume 允许幂等重放，Core 按 Session Hash、Event Seq 与 Batch Hash 去重；flush 对账后仍有序号缺口才标记 `evidence_incomplete`，阻止相关 Run 进入最终 Gate；
- Backfill 从公开 Session API 读取规范化事件，不读取私有数据库表或压缩帧。

#### 8.6.3 事件映射

Observer 根据 pin 后官方事件图映射：

- Turn/Step 开始结束；
- user/assistant message 的允许字段；
- tool call/result；
- usage、latency、status；
- Session/Snapshot/Plugin Composition 标识；
- `session.id`、事件 `seq`、事件时间和父子/来源关系。

DSH→τ³ 运行协议版本必须由一个共享常量/Schema 定义，生产端写入每个实际模型生成消息，消费端
显式列出兼容版本，测试逐版本覆盖。缺少来源标记与存在但版本不受支持是两个不同错误：前者为
`provenance_missing`，后者为 `protocol_version_unsupported`；禁止消费者用散落的硬编码版本把已
存在的 provenance 误报为缺失。协议版本改变执行或证据语义时必须按第 16 节新建实验身份。

Observer 只负责事实采集，不推断任务是否成功。Outcome 由 Benchmark/Evaluator Adapter 或人类批准的确定性结果导入。

社区自有任务通过 `agentloopgate run ingest --file <results.jsonl>` 导入 Outcome。该入口只接受第 9 节 Schema，不执行用户提供的代码或 Shell；任务 ID、Pool、Snapshot 和 Evidence Ref 必须能校验。这样插件可以服务 τ³ 之外的 DeepSeek Harness 项目，同时不让宿主或模型自行给自己打分。

Observer 故障必须 fail open：不得中断 Agent Turn。Live 失败进入有限缓冲并记录 dropped/error count；不得无限占用内存。Flush 对账以不超过 `max_batch_events` 的批次顺序补录，不把完整 Trace 复制进第二个无界队列。Run 若存在未修复丢失，不得用于正式 Decision。

#### 8.6.4 原生 Telemetry 的角色

开发者可以继续使用 DeepSeek OTel 把 Trace 发往自己的 Collector。AgentLoopGate 不读取或修改其 Exporter 配置，也不把 OTel Delivery 当作 Gate 证据完整性的依据。AgentLoopGate 自己的 Redaction 只作用于 Evidence Receipt/Mirror，不改写原生 Session Log 或原生 Telemetry 的策略。

### 8.7 模型可见工具

默认启用：

| Tool | 作用 | 是否写状态 |
|---|---|---:|
| `agentloopgate_status` | 查看 Core、合同、Snapshot 和 Observer 状态 | 否 |
| `agentloopgate_contract_validate` | 校验合同或配置 | 否 |
| `agentloopgate_candidate_check` | 检查已登记候选 | 只写审计记录 |
| `agentloopgate_decision_explain` | 读取脱敏 Decision 摘要 | 否 |

默认禁用、需插件配置与项目 Policy 同时允许：

| Tool | 约束 |
|---|---|
| `agentloopgate_propose` | 只读 Update-Source FailureBundle；只写候选目录；有候选数、成本和路径预算 |

永不向模型注册：

- Selection/Release/Final 读取；
- Objective、Gate、Split、Evaluator 修改；
- `snapshot_promote`、`snapshot_rollback`；
- 插件权限修改；
- 任意 Shell、任意文件路径或任意 Bridge 方法。

### 8.8 社区安装与使用路径

P0 README 必须给出经过 Clean-room 验证的流程：

1. 安装 AgentLoopGate Python Core；
2. 获取或构建 `@agentloopgate/dsh-plugin` Bundle；
3. 在一个全新的 DeepSeek Harness `headless` Profile 中按官方方式安装/挂载；
4. 运行 `agentloopgate init --runtime deepseek-harness --project .` 生成最小配置；
5. 设置项目根目录，不复制 API Key 到插件配置；
6. 运行 `agentloopgate doctor --runtime deepseek-harness` 查看 Readiness；
7. 运行 No-key Conformance Fixture；
8. 运行一个 Headless Agent Fixture，确认原生 Session 仍持久化且 AgentLoopGate 生成 SourceTraceRef；
9. 调用四个默认工具；
10. 卸载插件并确认没有残留工具、监听器或子进程，原生 Trace 仍工作。

No-key Conformance 必须使用 DeepSeek Harness 的测试支持或 Fixture Provider，不得发起真实模型请求，也不得要求 `DEEPSEEK_API_KEY`。

具体安装命令必须来自被 pin 版本的官方实现验证，未验证前不得在 README 伪造 `dsh plugin install` 等命令。

### 8.9 插件 P0 验收

必须全部通过：

- package build、typecheck、unit test；
- Bundle 可被 pin 的 `headless` Profile 加载；
- `ctx.agentLoopGate` Service 可用；
- 四个默认 Tool 可调用且 Schema 正确；
- `agentloopgate_propose` 默认不存在或返回 disabled；
- 读取 Final、Promote、改 Gate 的请求被拒绝并有审计记录；
- Session/Tool Fixture 能生成 SourceTraceRef、Evidence Receipt 和 Normalized Record；
- 已启用的 JSONL/SQLite Persistence 在安装前后保存同一逻辑 SessionEvent；
- 已启用的 OTel Backend 不被替换，Telemetry Mode 与 Exporter 配置不被修改；
- 插件没有注册竞争性的 `ctx.sessionTelemetry` Backend；
- Live + Backfill 去重通过，重复 `(session.id, event.seq)` 不产生重复 Evidence；
- Session 构造/Resume 时未发布到 live firehose 的事件会在 flush 通过公开 `session.events` 补齐；
- Trace 序号缺口会标记 `evidence_incomplete` 并阻止正式 Gate；
- Bridge 崩溃不影响普通 Headless Agent 完成；
- 插件卸载后无工具、事件监听和子进程残留；
- 插件卸载后原生 Session Persistence/Telemetry 继续工作；
- 不安装插件时 Python No-key Demo 仍通过。

P0 不要求 Web UI，也不要求把 AgentLoopGate 页面嵌入 DeepSeek Harness Web。

### 8.10 Banking Pilot 纵向验证

插件不能只在人工 Fixture 中展示四个只读工具。P0 必须完成一个真实纵向切片：

1. 选择 3—7 个 τ³ `banking_knowledge` Pilot 任务；
2. τ³ 自定义 `HalfDuplexAgent` 把每个 User/Tool Result Turn 送入同一个 pin 后的 DeepSeek
   Harness `headless` Session；DSH 负责模型调用、会话恢复和原生 Persistence；
   首轮同时加载当前 Snapshot 中登记的 Harness 资产；资产必须按固定白名单和顺序读取、限制总
   字节数，其内容 Hash 必须进入 DSH `composition_digest`，否则候选评测无效；
3. DSH Session Log 记录模型输入、模型 JSON 回复、finish reason、Usage 与生成耗时；即使 Runner
   或 Reply Adapter 失败，已完成调用的原生记录和可验证 Usage 也必须先刷盘；τ³ Raw Result 记录
   由 τ³ 实际执行的 Tool Call、环境状态与成本。禁止声称 τ³ 工具是 DSH 原生 Tool Event；
4. AgentLoopGate Observer 为 DSH Session 生成 SourceTraceRef；τ³ Adapter 为 Raw Result 生成
   独立 SourceTraceRef；两侧分别生成 Evidence Receipt 与 RunRecord；
5. τ³ Evaluator 是最终状态、必要 Action 和政策结果的唯一 Outcome 权威，DSH 或插件不得自评；
6. `PilotEvidenceJoin` 以 Task、Trial、DSH Session Hash、两侧 Run/Trace/Receipt 将同一次运行关联；
7. AgentLoopGate 输出失败分类和 Candidate Check 所需输入，并证明双侧证据可被正式 Gate 消费；
   Pilot 本身不产生 Release 结论，`gate_decision` 必须为 `null`，Gate Decision 只来自随后冻结的
   Selection/Release-ID/OOD/Replay；
8. 关闭插件后，用相同 Profile 验证 DeepSeek 原生 Trace 仍可记录。

该纵向切片证明插件与治理链真实可用，不进入正式 Release-ID/OOD 主结论，也不要求在 3—7 个任务上宣称统计提升。

银行场景是 Reference Validation Pack，不是 Core 中的业务硬编码。所有银行任务、政策、Gold 和 τ³ 专用映射必须位于 Adapter/Example 层；删除该 Example 后，Core Schema、DeepSeek 插件、JSONL Outcome Adapter、Updater、Gate 和 Snapshot 仍应正常工作。

### 8.11 即插即用的三档 Readiness

`agentloopgate doctor --runtime deepseek-harness --json` 必须输出：

| Readiness | 安装后能力 | 必要条件 |
|---|---|---|
| `observe_ready` | Trace 关联、状态、成本/工具事实、Evidence Verify | Bundle、Bridge、Session Event 接入正常 |
| `check_ready` | Contract Validate、Candidate Check、Decision Explain | Objective 模板和 Asset Manifest 有效 |
| `govern_ready` | Diagnose、Updater、ID/OOD/Replay、Gate、Rollback | 确定性 Evaluator、数据池、冻结合同和至少一个候选 |

产品承诺是“即插即观察、即插即体检、配置后治理”，禁止宣传成不提供业务目标和 Evaluator 也能自动发布。

### 8.12 社区开发者可复用能力合同

银行验证通过后，DeepSeek Harness 开发者可以直接复用：

- Session Trace Adapter、SourceTraceRef、Evidence Verify 和成本/工具事实；
- Objective Contract 模板与 Readiness Doctor；
- JSONL Outcome 导入与自定义 BenchmarkAdapter 接口；
- 失败漏斗、FailureBundle 和修改路由；
- AHE/ACE Updater Adapter、Candidate Registry、Diff/Leakage/Risk Check；
- 自定义 ID/OOD/Replay、Pass^k、安全/成本 Gate；
- Decision Explain、Snapshot、人工 Promote 与 Rollback。

开发者必须提供自己的领域目标、确定性 Evaluator、数据池划分和可修改资产；AgentLoopGate 不复用银行 Gold 或政策替其他领域判分。

---

## 9. 数据合同

### 9.1 通用规则

- Python 使用 Pydantic v2；所有正式模型 `extra="forbid"`；
- 时间为 UTC ISO-8601；
- 金额使用 decimal string，不使用二进制浮点保存账单；
- Hash 使用 `sha256:<hex>`；
- 枚举禁止自由文本；
- Evidence Receipt 只追加，Normalized Record 可重建；
- Schema 变更必须提升 `schema_version` 并提供迁移测试。

### 9.1.1 SourceTraceRef 与 EvidenceReceipt

```json
{
  "schema_version": "1.0",
  "source_trace_id": "STR_001",
  "runtime_host": "deepseek_harness",
  "source_locator": "binding:TB_001",
  "session_id_hash": "sha256:...",
  "event_seq_start": 0,
  "event_seq_end": 42,
  "event_count": 43,
  "source_revision": "provider_revision_or_digest",
  "persistence_kind": "jsonl",
  "ingest_mode": "reference",
  "mirror_path": null,
  "mirror_digest": null,
  "cursor_complete": true,
  "evidence_status": "verified",
  "created_at": "2026-08-20T00:00:00Z"
}
```

`source_locator` 是项目相对的 Artifact URI 或本地 Trace Binding ID，不得包含明文 Session ID、Credential、URL Secret 或越出项目根目录的文件路径。DeepSeek Session 使用本地 Binding 将 Hash 身份解析为公开 Session API 句柄；τ³/Fixture 可以指向项目内 Artifact。`persistence_kind` 允许 `tau_raw/jsonl/sqlite/memory/unknown`；AgentLoopGate 通过公开 Session API 采集，不能因值为 SQLite 就直接查询其私有表。`evidence_status` 允许 `pending/verified/incomplete/unavailable`。正式 Gate 只接受 `verified`。

EvidenceReceipt 至少记录：`receipt_id`、`source_trace_id`、`run_id`、已映射事件范围、Redaction Policy Digest、Normalized Record Digest、采集时间和错误计数。

### 9.2 RunRecord

```json
{
  "schema_version": "1.0",
  "run_id": "R_001",
  "attempt_id": "A_001",
  "task_id": "banking_xxx",
  "pool": "update_source",
  "snapshot_id": "S_A0",
  "candidate_id": null,
  "source": "tau3",
  "runtime_host": "python_cli",
  "runtime_version": "git:...",
  "model_id": "exact_model_id",
  "benchmark_commit": "sha",
  "objective_digest": "sha256:...",
  "split_digest": "sha256:...",
  "initial_state_digest": "sha256:...",
  "terminal_state_digest": "sha256:...",
  "trial_index": 1,
  "run_validity": "valid",
  "success": false,
  "critical_violations": [],
  "input_tokens": 0,
  "output_tokens": 0,
  "latency_ms": 0,
  "cost": "0.000000",
  "source_trace_ref": "STR_001",
  "evidence_receipt_ref": "ER_001",
  "created_at": "2026-08-20T00:00:00Z"
}
```

`source=dsh` 时必须记录 `runtime_profile` 和 `composition_digest`，Session 身份只通过 SourceTraceRef 保存 Hash；不得保存明文 Credential。`source=tau3` 时 SourceTraceRef 指向 τ³ Raw Result/Trace Artifact。
DSH `latency_ms` 只累计带受支持 `agentloopgate_protocol` 来源标记的实际模型生成耗时；P0 明确兼容
`dsh-tau3/1.0` 与 `dsh-tau3/1.1` 的现有证据，新的生产端默认写 `dsh-tau3/1.1`。τ³ 在自定义
Agent 首轮前注入的零成本静态 greeting 不属于 DSH 模型调用，必须排除。除这一个 `turn_idx=0`
静态 greeting 外，缺少来源标记、版本不受支持或生成耗时缺失的 assistant 消息一律使证据导入
失败，并分别报告 `provenance_missing`、`protocol_version_unsupported` 或 `latency_missing`。

DSH→τ³ Reply Adapter 只能做无可执行语义的有界规范化：移除单层 JSON fence、接纳 JSON
字符串内的未转义控制字符、把非空且非 JSON-like 的纯文本包装为 `content`，或把唯一键
为当前 allow-list Tool 名且值为参数对象的显式简写展开成 `name/arguments`。此外，允许把
`tool_calls` 元素中键集合严格等于 `{function, arguments}`、`function` 为当前 allow-list 中非空
字符串且 `arguments` 为对象的 DeepSeek 显式别名规范化为 `{name, arguments}`；也允许把键集合
为 `{name, <一个或多个参数键>}`、`name` 为 allow-list Tool 且不含 `arguments`、`function`、
`content`、`tool_calls` 的扁平显式调用收拢为 `{name, arguments:{<参数键>...}}`。生产 Prompt 应让客户回复
直接使用非 JSON 纯文本，只让 Tool Call 使用 JSON，避免把长客户文本塞入易损的 JSON 字符串。
不得从自然语言猜测 Tool Call；未知 Tool、空扁平参数、保留键混入、损坏的 Tool JSON、非对象
参数或混合 `content/tool_calls` 默认失败关闭并保留原生 Trace。Reply Policy v5 额外只允许以下两条
由 R6 原生 Trace 校准、整条回复锚定且唯一可逆的规则：

1. 整条回复严格形如 `{"tool_calls":[{"<allow-listed-tool>","arguments":<object>}]}` 时，只补入
   缺失的固定字段标签 `"name":`，随后必须通过标准 JSON、严格 Reply Schema 与当前 Turn
   allow-list 校验；不得修复其他语法错误、补括号、补引号或改参数；
2. 整条回复严格形如
   `{"tool_calls":[{"call_discoverable_agent_tool":"<explicit-subtool>","arguments":<object>}]}`，
   且通用 wrapper 在当前 Turn allow-list、subtool 是非空安全标识符时，允许确定性展开为
   `{name:"call_discoverable_agent_tool", arguments:{agent_tool_name:<explicit-subtool>,
   arguments:<该 object 的 canonical JSON string>}}`。subtool 必须由回复明示，实际执行仍由 τ³
   的 unlock 状态和工具 Schema 授权；不得从 reasoning、Knowledge Base 或 Formal Gold 推断。

除这两个完整形状外，未知 Tool、多个或混合调用、值或参数缺失、额外键、数组参数、损坏的
`content` JSON 或其他损坏 Tool JSON 一律失败关闭。错误必须区分 JSON 语法失败、Schema 不兼容、
未知 Tool 与混合回复，不得把已成功解析但形状不兼容的回复笼统报告为“无效 JSON”。损坏的
`content` JSON 也不得猜测补全；模型应在下一预注册重试中改用纯文本。

### 9.2.1 PilotEvidenceJoin

Banking Reference Validation 的一次 Task/Trial 必须产生一个严格 Join：

```json
{
  "schema_version": "1.0",
  "join_id": "PEJ_001",
  "task_id": "banking_xxx",
  "trial_index": 1,
  "dsh_run_id": "DSH_001",
  "tau_run_id": "TAU_001",
  "dsh_source_trace_ref": "DSH_TRACE_001",
  "dsh_evidence_receipt_ref": "ER_DSH_001",
  "tau_source_trace_ref": "TAU_TRACE_001",
  "tau_evidence_receipt_ref": "ER_TAU_001",
  "session_id_hash": "sha256:...",
  "outcome_success": true,
  "evidence_digest": "sha256:...",
  "created_at": "2026-08-20T00:00:00Z"
}
```

Join 只引用两侧已验证、不可变 Artifact，不复制明文 Session ID。`outcome_success` 必须来自
τ³ Outcome；DSH RunRecord 可以复用该 Outcome，但不得生成第二个评分。缺任一侧 Trace、Receipt、
Task/Trial/Seed 对不上或 DSH Cursor 不完整时，不得建立 Join，也不得进入 Banking Pilot Gate。

### 9.2.2 FormalBatchArtifact

每个付费评测批次必须保存完整 `FormalBatchSpec`、`spec_digest`、保留的 τ³ Raw Result 路径、
τ³/DSH Run ID、Evidence Join ID、`EvaluationSummary` 和 `batch_digest`。批次 ID 由 Spec Hash
确定；重复命令只能验真并恢复。Raw Result、Trace、Receipt、RunRecord、Join 或 Summary 任一漂移
必须退出码 `5`，禁止静默重跑付费批次。`code_revision` 不包含可变 `harness/`；Harness 由
Snapshot 的逐文件 Hash 与 DSH `composition_digest` 单独锁定，避免重复计数和 Promote 后误报源码漂移。

### 9.3 SnapshotManifest

```yaml
schema_version: "1.0"
snapshot_id: "S_A1"
parent_snapshot_id: "S_A0"
candidate_id: "C_001"
model_id: "exact_model_id"
objective_digest: "sha256:..."
split_digest: "sha256:..."
asset_manifest_digest: "sha256:..."
code_revision: "git_or_source_digest"
harness_files:
  harness/system_prompt.md: "sha256:..."
runtime:
  host: "python_cli"
  version: "exact"
created_at: "2026-08-20T00:00:00Z"
```

### 9.4 CandidateRecord

```json
{
  "schema_version": "1.0",
  "candidate_id": "C_001",
  "parent_snapshot_id": "S_A0",
  "failure_bundle_digest": "sha256:...",
  "updater": {"name": "ahe", "version": "commit_sha"},
  "hypothesis": "加入例外核对步骤可减少政策遗漏且不增加成本超过20%",
  "asset_families": ["context_memory_skill"],
  "risk_tier": "L",
  "patch_path": "candidates/C_001.patch",
  "patch_digest": "sha256:...",
  "changed_files": ["harness/skills/policy_check.md"],
  "predicted_effect": {"metric": "stable_success_task_count", "direction": "increase"},
  "status": "registered",
  "created_at": "2026-08-20T00:00:00Z"
}
```

### 9.5 DecisionRecord

```json
{
  "schema_version": "1.0",
  "decision_id": "D_001",
  "candidate_id": "C_001",
  "baseline_snapshot_id": "S_A0",
  "decision": "HOLD",
  "gates": [
    {"name": "leakage", "status": "pass", "evidence_ref": "artifacts/..."},
    {"name": "ood_noninferiority", "status": "fail", "evidence_ref": "artifacts/..."}
  ],
  "summary": "ID 改善但 OOD 稳定成功任务净损失 2 个，超过允许值 1",
  "human_approval": null,
  "created_at": "2026-08-20T00:00:00Z"
}
```

### 9.6 Candidate 状态机

```text
DRAFT
  -> REGISTERED
  -> CHECKED
  -> UPDATE_EVALUATED
  -> SELECTION_EVALUATED
  -> RELEASE_EVALUATED
  -> SHIP_RECOMMENDED | HELD | REJECTED
  -> SHIPPED
  -> ROLLED_BACK
```

任何状态跳转必须保存时间、操作者和证据引用。

### 9.7 Lineage 与人类 Approval

正式 `lineage.json` 必须列出 3—7 个 Pilot Task 对应的 `PilotEvidenceJoin`、所有 Formal Batch、
Candidate 和 Snapshot；Gate 的 Evaluation Integrity Evidence 必须指向该 Lineage，使最终 Decision
可回链 DSH Session Event 与 τ³ Outcome。

Promote/Rollback 的 Approval JSON 最小合同：

```json
{
  "schema_version": "1.0",
  "approval_id": "APPROVAL_001",
  "action": "promote",
  "target_snapshot_id": "S_A1",
  "actor": "human-owner",
  "confirmation": "I understand this changes the active harness snapshot.",
  "approved_at": "2026-08-20T00:00:00Z"
}
```

`action` 只能是 `promote/rollback`，目标与 CLI 动作必须精确一致。相同 Approval 的重试幂等；
不同证据不得覆盖既有 Activation。

---

## 10. CLI 合同

### 10.1 必须实现的命令

```bash
# 环境、合同、数据
agentloopgate doctor
agentloopgate init --runtime deepseek-harness --project .
agentloopgate doctor --runtime deepseek-harness
agentloopgate contract validate configs/objective_contract.yaml
agentloopgate contract freeze configs/objective_contract.yaml --confirm "FREEZE OBJECTIVE"
agentloopgate split freeze --config configs/splits.yaml
agentloopgate split verify
agentloopgate eval reset-check --fixture tests/fixtures/reset
agentloopgate pilot run --pricing-config configs/pilot_pricing.yaml

# 正式实验：先验真冻结输入；授权命令只在 Owner 明确批准后人工运行
agentloopgate experiment protocol-verify --config FROZEN_PROTOCOL_1_8.yaml --json
agentloopgate experiment study-verify --config FROZEN_STUDY_1_2.yaml --json
agentloopgate experiment authorize-paid --config FORMAL_CONFIG_1_2.yaml \
  --scope pre_release_checkpoint \
  --confirm OWNER_AUTHORIZED_PRE_RELEASE_CHECKPOINT --json
agentloopgate experiment preflight --config FORMAL_CONFIG_1_2.yaml --json
agentloopgate experiment run --config FORMAL_CONFIG_1_2.yaml --json
# Release 只有 SELECT + 第二次 Owner 授权后才可运行；HOLD 时禁止创建此授权
agentloopgate experiment authorize-paid --config FORMAL_CONFIG_1_2.yaml \
  --scope release_tail --confirm OWNER_AUTHORIZED_RELEASE_TAIL --json
agentloopgate snapshot promote SNAPSHOT_ID --decision DECISION.json --approval APPROVAL.json
agentloopgate snapshot rollback PARENT_SNAPSHOT_ID --approval APPROVAL.json

# 报告与集成
agentloopgate bridge serve --project .
agentloopgate demo --fixture tests/fixtures/public_demo
```

Baseline、Diagnose、Propose、Candidate Check、Evaluate、Select、Replay、Decide 与 Report Build
是 `experiment run` 内部的可恢复阶段和 Python API，不再为每个内部动作强制一条独立 CLI。
这样缩小 P0 表面积，同时保留 §5—§7 的完整证据与信任边界。Promote/Rollback 是必须携带
人类 Approval Artifact 的独立运维命令，不包含在自动实验命令中，也不能由 DeepSeek 插件或
模型触发。

### 10.2 通用 CLI 行为

- 成功退出码 `0`；输入/Schema 错误 `2`；Policy 拒绝 `3`；外部依赖不可用 `4`；评测不完整 `5`；
- stdout 输出人类摘要；`--json` 输出单个稳定 JSON 对象；
- 错误必须含 `code`、`message`、`remediation`；
- 命令重复执行必须幂等，或明确拒绝并指出已有 Artifact；
- 默认不联网安装依赖，不打印 Secret，不自动 Promote。

`agentloopgate init` 只能创建不存在的模板或使用 `--force` 覆盖未冻结模板；不得改写已冻结 Objective、Split、Asset Manifest 或用户的 DeepSeek Profile。`doctor --runtime deepseek-harness` 必须输出第 8.11 节三档 Readiness 和具体补救步骤。

### 10.3 No-key Demo 期望输出

Fixture 必须构造：

- A0；
- 一个开发集提升但 OOD 回退的候选；
- 一个成本超限候选；
- Gate 分别输出 HOLD 原因；
- 一份 Decision JSON/Markdown；
- 四张核心图；
- 一次 Bridge 和 DeepSeek 插件 Conformance；
- 一个原生 Session Persistence 仍工作的 Host Trace；
- 一个可验证的 SourceTraceRef/Evidence Receipt；
- `doctor` 至少报告 `observe_ready`。

Fixture 只验证软件行为，不能冒充真实实验结果。

---

## 11. 仓库结构

```text
AgentLoopGate/
├── README.md
├── SPEC.md
├── LATER.md
├── LICENSE
├── THIRD_PARTY_NOTICES.md
├── pyproject.toml
├── uv.lock
├── configs/
│   ├── objective_contract.yaml
│   ├── splits.yaml
│   ├── harness_assets.yaml
│   ├── mutation_policy.yaml
│   ├── evaluator.yaml
│   ├── formal_experiment.yaml
│   ├── pilot_pricing.yaml
│   ├── runtime_dsh.yaml
│   └── trace_redaction.yaml
├── data/
│   ├── splits/
│   └── manifests/
├── examples/
│   └── tau3-banking/     # Reference Validation Pack，不进入 Core 业务规则
├── harness/
│   ├── system_prompt.md
│   ├── context/
│   ├── skills/
│   ├── retrieval/
│   ├── tools/
│   └── orchestration/
├── agentloopgate/
│   ├── cli.py
│   ├── schemas/
│   ├── contracts/
│   ├── adapters/
│   │   ├── base.py
│   │   ├── dsh_tau3.py
│   │   ├── fixture.py
│   │   ├── jsonl.py
│   │   └── tau3.py
│   ├── traces/
│   ├── splits/
│   ├── diagnosis/
│   ├── updaters/
│   │   ├── base.py
│   │   ├── ahe.py
│   │   └── ace.py
│   ├── mutation/
│   ├── candidates/
│   ├── evaluation/
│   ├── experiment/
│   │   ├── batch.py
│   │   ├── diagnostics.py
│   │   ├── orchestrator.py
│   │   └── service.py
│   ├── gates/
│   ├── snapshots/
│   ├── runtime/
│   ├── bridge/
│   └── reporting/
├── integrations/
│   └── deepseek-harness/
├── candidates/
├── snapshots/
├── runs/                 # Evidence Receipt/Mirror/Normalized，默认 gitignore
├── artifacts/
│   └── public_demo/      # 可提交的脱敏 Fixture 结果
├── reports/
├── docs/
│   └── deepseek-harness.md
├── scripts/
│   └── verify_p0.sh
└── tests/
    ├── fixtures/
    ├── unit/
    ├── integration/
    └── e2e/
```

除 README、SPEC、LATER、第三方声明和一份 DeepSeek 集成说明外，不新增独立叙事文档。设计事实优先进入 Schema、测试和代码注释。

---

## 12. Vibe Coding 任务卡

### T00：仓库骨架与无 Key 入口

**依赖：** 无。  
**修改范围：** 根目录、`agentloopgate/__init__.py`、`agentloopgate/cli.py`、`tests/fixtures/`、`tests/unit/test_cli.py`。  
**实现：** 建立 Python 3.12 + uv + Typer + Pydantic + pytest + Ruff；实现 `doctor` 和空 Fixture `demo`。  
**验收：**

```bash
uv sync
uv run ruff check .
uv run pytest -q
uv run agentloopgate doctor --json
```

### T01：核心 Schema 与 Hash

**依赖：** T00。  
**修改范围：** `agentloopgate/schemas/`、`agentloopgate/contracts/`、`configs/`。  
**实现：** ObjectiveContract、SourceTraceRef、EvidenceReceipt、RunRecord、FailureBundle、CandidateRecord、SnapshotManifest、DecisionRecord；规范化 JSON/YAML 与 SHA256。  
**验收：** 合法 Fixture 全通过；缺字段、额外字段、错误枚举、Hash 漂移均失败。

### T02：Trace 证据链与 Fixture Adapter

**依赖：** T01。  
**修改范围：** `agentloopgate/traces/`、`agentloopgate/adapters/fixture.py`。  
**实现：** 定义第 3.6 节 RuntimeTraceAdapter；实现 H0 SourceTraceRef、L0 Evidence Receipt/Mirror、L1 Normalized rebuild、成本字段和 Fixture Run。  
**验收：** 删除 Normalized 后可从可用 H0 或 Evidence Mirror 重建；篡改来源或 Mirror 后 Hash 校验失败；缺口状态阻止正式 Gate。

### T03：数据池 ACL、Freeze 与 Trial Reset

**依赖：** T01。  
**修改范围：** `agentloopgate/splits/`、`agentloopgate/evaluation/reset.py`、`data/splits/`。  
**实现：** 六池 Manifest、访问角色、Freeze Hash、Reset Digest、Infra Invalid。  
**验收：** Updater 读取 Selection/Release 必须退出码 3；Reset Fixture 连续两次 Digest 一致。

### T04：Benchmark Adapter、τ³ 与 A0

**依赖：** T02、T03。  
**修改范围：** `agentloopgate/adapters/tau3.py`、相关测试。  
**实现：** 定义统一 BenchmarkAdapter；先检查实际 pin 的 τ³ API；实现 τ³ 运行与 JSONL Outcome 导入；映射 Outcome、Action、Token、延迟、成本、Host Trace 和 Evidence Receipt。  
**验收：** 3—7 个 Pilot 可运行；至少一个 Reference Fixture 通过；合法社区 JSONL 可导入；自评分、错 Pool、错 Snapshot 和无 Evidence 的结果被拒绝；Infra Invalid 不进入分母。

### T05：失败漏斗与 FailureBundle

**依赖：** T04。  
**修改范围：** `agentloopgate/diagnosis/`。  
**实现：** 第 6.1 节分类、证据引用、优先级、脱敏 FailureBundle。  
**验收：** Fixture 中已知检索/政策/工具错误分类正确；Bundle 不含受保护字段。

### T06：Asset Manifest、Mutation Policy 与 Candidate Registry

**依赖：** T01、T05。  
**修改范围：** `agentloopgate/mutation/`、`agentloopgate/candidates/`、`harness/`。  
**实现：** 路径白名单、Risk、Diff 预算、信任核 Hash、Leakage Scanner、候选状态机。  
**验收：** 合法 L/M Patch 通过；改 Gate、Split、Evaluator、未登记路径、Gold 特征或 Risk-H 自动执行均失败。

### T07：AHE Adapter 与 ACE Tripwire

**依赖：** T06。  
**修改范围：** `agentloopgate/updaters/`。  
**实现：** 先做真实 AHE Spike；pin 版本；规范化输入输出；保存原始 Artifact。只有满足第 7.6 节才实现 ACE。  
**验收：** 至少一个外部方法从 Fixture FailureBundle 生成可登记 Candidate；越权写入被 Candidate Check 拒绝。

### T08：Evaluation、双选择器与 Gate

**依赖：** T03、T04、T06。  
**修改范围：** `agentloopgate/evaluation/`、`agentloopgate/gates/`。  
**实现：** Pass^1/Pass^k、ID/OOD/Replay、Critical、成本、带 A0 基线与弃权的双选择器，以及
第 4.4 节 Gate。
**验收：** 固定 Fixture 覆盖每一个 Gate pass/fail；无提升、稳定任务回退、重试/超时增加、
whole-Attempt 成本或 p95 超限均能产生逐项原因；无合格候选时必须在 Release 前 `HOLD`；综合分
不能覆盖硬门。

### T09：Snapshot、Rollback 与报告

**依赖：** T08。  
**修改范围：** `agentloopgate/snapshots/`、`agentloopgate/reporting/`。  
**实现：** Promote 授权、父版本回滚、Decision Markdown/JSON、四张图。  
**验收：** 未授权 Promote 失败；Rollback 后 Harness Hash 与父 Snapshot 一致。

### T10：Bridge Protocol

**依赖：** T01、T06、T08。  
**修改范围：** `agentloopgate/bridge/`、Schema 导出。  
**实现：** stdio JSONL、方法路由、幂等、防任意方法、错误码、TypeScript 类型生成；加入 trace sync/verify 方法。  
**验收：** health/validate/check/explain/ingest/sync 全通过；重复请求不重复写；未知方法、超大请求、Final/Promote 请求拒绝。

### T11：DeepSeek Harness Spike 与原生 Bundle

**依赖：** T10。  
**修改范围：** `integrations/deepseek-harness/`、`agentloopgate/runtime/`、`agentloopgate/cli.py`、`docs/deepseek-harness.md`。  
**实现：** pin 官方版本/commit；确认实际 Bundle、Service、Session Event、Persistence、Telemetry、Tool、Command、Headless seam；实现 Service、Provider、四个只读 Tool和 `agentloopgate init/doctor` Bootstrap；集中定义 DSH→τ³ 协议版本与有界 Reply 规范化。
**验收：** build/typecheck/test；Bundle 在全新 Headless Profile 加载；工具通过 Bridge 返回正确结构；Doctor 正确报告三档 Readiness；插件不注册竞争性的 `ctx.sessionTelemetry` Backend；`dsh-tau3/1.0`/`1.1` 消费、纯文本客户回复、`function/arguments` 与 allow-list 扁平参数安全别名、未知 Tool/保留键拒绝和非成功 Runner Envelope 的 Usage 恢复均有测试。

### T12：Observer、权限与生命周期 Conformance

**依赖：** T11。  
**修改范围：** DeepSeek 插件和 E2E Fixture。  
**实现：** Session/Event live + backfill、SourceTraceRef、Cursor/去重、reference/mirror 模式、Propose 默认禁用、权限拒绝、Bridge 故障隔离、卸载清理。  
**验收：** 满足第 8.9 节全部条件；分别验证 JSONL Persistence、SQLite Persistence 和一个启用 OTel 的 Fixture 不被替换；不安装插件时 Python Core 测试仍通过。

### T13：真实 Candidate Ladder 与正式实验

**依赖：** T04—T12。  
**修改范围：** 配置、候选、运行 Artifact；冻结后禁止改核心代码。  
**实现：** 先完成第 8.10 节 DeepSeek 插件 × 3—7 个 Banking Pilot 纵向验证，并为每个
Task/Trial 生成 `PilotEvidenceJoin`；再用未泄露 Formal Task/Gold 的复杂度 Fixture/Pilot 校准并
冻结模型输出预算、Turn/Simulation 超时、Reply/Trace 协议与费用恢复口径；随后冻结合同/数据，
运行 A0，生成 3—6 候选并完成 Selection；若 AgentLoopGate 选出 RC，再完成双 RC、
Release-ID/OOD、Replay 与 Decision；若弃权，则封存正常 Selection-HOLD 终态并结束付费路径。
**验收：** Banking Pilot 能从正式 Decision 经 Join 同时回链 DeepSeek Session Event 与 τ³ Outcome，
且可证明 τ³ 执行了真实工具；关闭插件后原生 Trace 仍工作；至少一个真实提案被 Candidate
Check 拒绝，或一个已登记候选被正式 Gate `HOLD/REJECT`；
所有结论可追溯；正式批次不系统性触发 `max-tokens`/Turn 超时，失败调用的已知 Token、费用、
finish reason、执行路径和墙钟时间可审计；若无 Ship 候选则诚实 HOLD。

### T14：公开发布与 Clean-room

**依赖：** T13。  
**修改范围：** README、LICENSE、第三方声明、公开 Artifact、Release 配置。  
**实现：** No-key Quickstart、三档 Readiness、原生 Trace 共存说明、插件安装/卸载步骤、脱敏结果、2—3 分钟 Demo，并提供 `scripts/verify_p0.sh` 统一执行 Python Fixture 与插件 Conformance；Python sdist 只从明确的源码/元数据 Allowlist 构建，运行目录体量不得影响打包。
**验收：** 在干净目录运行 `./scripts/verify_p0.sh` 完成 Python Demo 和插件 Conformance；在本地存在大量 ignored `runs/` 证据时 sdist 仍不得遍历或收录该目录；公开内容无 Secret/PII/Final 泄漏。

### 12.1 标准任务 Prompt

复制给 Coding Agent：

```text
实现 SPEC 第 12 节 Task Txx，只做该任务。
先读取 SPEC 0、相关接口章节和当前仓库；再检查被 pin 上游源码，禁止猜测 API。
先补测试，再实现最小代码。不得修改 Objective、Gate、Split、Trust Kernel 或其他任务范围。
完成后运行任务卡验收命令，并按 SPEC 0.2 格式报告。
```

---

## 13. 测试与 P0 Definition of Done

### 13.1 测试层级

**Unit：** Schema、Hash、SourceTraceRef、Cursor/去重、ACL、Mutation Policy、Leakage、Gate、Bridge 路由。  
**Integration：** Fixture/τ³/JSONL Adapter、AHE/ACE Adapter、Evidence Verify、Snapshot/Rollback、Plugin Bridge、DSH Persistence/Telemetry 共存。  
**E2E：** No-key Demo、Banking Pilot 纵向验证、Candidate Ladder、DeepSeek Headless Conformance、Core Independence。

### 13.2 必须长期通过的命令

```bash
uv run ruff check .
uv run pytest -q
uv run agentloopgate demo --fixture tests/fixtures/public_demo

cd integrations/deepseek-harness
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm test
pnpm run build
pnpm run test:conformance
pnpm pack

cd ../..
./scripts/verify_p0.sh
```

Headless Conformance 的真实命令在 T11 根据 pin 后官方 CLI 写入 package script `test:conformance`，CI 只调用该 script，不在多处复制宿主命令。

### 13.3 四张核心图

1. A0—An 的 Pass^1、Pass^k 与成本曲线；
2. 检索 → 政策 → 工具 → 正确状态失败漏斗；
3. Update/Selection 候选对照；仅在 Selection 选出候选时追加 ID/OOD/Replay，对弃权路径明确画出
   “Selection HOLD → Release 未启动”；
4. Gate 瀑布与最终 Ship/Hold 理由。

### 13.4 P0 完成条件

只有同时满足以下条件才算 v1 完成：

- Objective Contract、Split、Asset Manifest 已冻结并可校验；
- Python Core 从 Run 到 Decision 一条命令可重放；
- 至少一个真实外部 Updater 接入；
- 至少 3 个真实候选、至少 2 个资产族、至少 1 个真实拒绝；
- ID/OOD/Replay、Pass^k、安全、成本和 Eval Integrity 的软件能力与确定性 Fixture 可审计；真实
  Selection 若选出候选，真实 ID/OOD/Replay 也必须可审计；若弃权，则 Selection-HOLD 终态、逐候选
  原因、总已知模型成本、未知费用范围、时间/重试和 Release 零启动证明必须可审计；
- Ship/Hold 结论唯一，且可回滚；
- DeepSeek Harness 原生 Bundle 可安装/加载/调用/卸载；
- 开发者现有 DeepSeek Session Persistence 和 OTel Telemetry 在安装前后继续工作；
- SourceTraceRef 能把 AgentLoopGate Decision 回链到 DeepSeek `session.id + event.seq`；
- `agentloopgate init/doctor` 能达到 `observe_ready` 并明确列出 `check/govern` 缺口；
- 插件不能打开 Final、改 Gate 或 Promote；
- 插件关闭后 Core 完整可用；
- 3—7 个 Banking Pilot 完成 τ³ Turn → DeepSeek 模型 Session/原生 Trace → τ³ Tool/Outcome → 双侧 Evidence Join → Gate 的纵向链路；
- 新正式实验绑定经复杂度校准的输出/超时预算和单一 DSH→τ³ 协议版本事实源；所有成功、Task Failure、Infra Invalid、重试、Token、费用下界、未知费用范围、执行路径和墙钟时间完整保存；
- No-key Demo、README、许可证、第三方声明和公开结果包可用。

以下均不能替代上述条件：漂亮架构图、大量文档、Fixture 的假提升、未运行的测试、只读插件壳、手写 Candidate 冒充外部 Updater。

---

## 14. 八周执行顺序

### 第 1 周：事实源与两项 Spike

- T00—T03；
- τ³ 最小 Pilot；
- DeepSeek Harness Bundle/Service/Session/Persistence/Telemetry/Headless seam Spike；
- Pilot 后冻结 Objective 候选阈值和版本。

### 第 2 周：基线与诊断

- T04—T05；
- 运行 A0 Update-Source；
- 得到真实失败漏斗和 2—3 个 FailureBundle。

### 第 3 周：受控修改与 Updater

- T06—T07；
- 生成第一批 Candidate；
- 验证路径、泄漏、Risk 和 Diff 预算。

### 第 4 周：评测与 Gate

- T08—T09；
- 完成 Update-Check、Replay、Fixture 全 Gate 覆盖；
- 形成 Candidate Ladder。

### 第 5 周：DeepSeek Harness 插件

- T10—T12；
- 打包 Bundle；
- Headless、权限、Observer、原生 Trace 共存、故障隔离与卸载测试；
- 完成 3—7 个 Banking Pilot 纵向验证。

### 第 6 周：Selection 与 Release

- 冻结候选；
- 运行双选择器；只有 Selection 选出候选才运行 Release-ID/OOD、Pass^k 和 Replay，否则封存
  Selection-HOLD 并停止新增付费批次；
- 生成真实 Decision；
- 若 Ship，回滚演练。

### 第 7 周：产品化

- 报告、四张图、README；
- 插件 Clean-room 安装；
- No-key Demo 和脱敏结果包。

### 第 8 周：发布

- T14；
- 公开仓库和 Release Artifact；
- Demo 视频；
- 发布后从干净环境复查一次。

---

## 15. 风险与停止规则

| 风险 | Tripwire | 行动 |
|---|---|---|
| τ³ 接入失败 | 2 天不能稳定跑 1 个 Pilot | 使用最简 BM25；仍失败则阻塞，不换题包装 |
| AHE 不兼容 | 满足第 7.6 节且 3 天无合法候选 | ADR 后降级 ACE |
| ACE 仍失败 | 再投入 2 天仍无合法候选 | P0 阻塞；不自研冒充 |
| DeepSeek Harness API 漂移 | pin 版本与文档不一致 | 以实际源码为准更新 Adapter/文档，保留精确 pin |
| 插件原生安装路径不稳定 | 官方 CLI 无稳定 install verb | 使用官方 Bundle + Profile patch 的 out-of-tree 加载；仍必须是 Cordis 原生插件 |
| Telemetry Backend 冲突 | 插件加载后原 OTel 消失或 duplicate provider | AgentLoopGate 不注册 `ctx.sessionTelemetry` Backend，改用 Session Event 旁路订阅 |
| 原生 Trace 被重复或改写 | 安装插件前后逻辑 SessionEvent 不一致 | 对比事件类型/序号/Hash；不一致即阻止发布插件 |
| Trace 补录不完整 | Cursor 出现序号缺口或 SourceTraceRef 不可验证 | 标记 `evidence_incomplete`，阻止对应 Run 进入 Gate |
| 执行预算与任务复杂度不匹配 | Pilot/正式运行系统性触发 `max-tokens` 或 Turn 超时 | 停止新付费批次；封存原证据；在未泄露 Fixture/Pilot 校准后新建 Protocol/Experiment/Baseline 并对称重跑 |
| Reply/Trace 协议漂移 | 生产端版本、消费端版本或结构化回复 Schema 不一致 | 区分缺失、版本不支持与 Schema 错误；仅做 allow-list 内无语义规范化；语义变化新建实验身份 |
| 失败费用不可审计 | 已完成模型调用在异常路径丢失 Usage/费用，或未知值被记零 | 先刷原生 Trace/Envelope 与双模型调用账本；有效 Run 成本不精确则 HOLD；全 Attempt 只能形成下界时逐项披露未知范围，不冒充精确值 |
| “即插即用”承诺过度 | 无 Evaluator 仍声称可治理 | Doctor 三档 Readiness；只承诺即插即观察/体检、配置后治理 |
| Observer 字段不足 | 无法得到 Outcome | 继续记录 Session/Tool 事实，由 Evaluator Adapter 导入 Outcome；不让 Observer 猜分 |
| 插件影响 Agent | Observer/Bridge 异常阻塞 Turn | 异步批量、有限缓冲、fail open；修复前不发布插件 |
| 候选越权 | 修改信任核、Final 或未登记路径 | 直接 REJECT，新建 Candidate ID |
| 成本超限 | Pilot 外推超预算 | 候选 6→3；不删 Release-ID/OOD、安全或插件 P0 |
| 全部候选无提升 | Selection 无合格候选 | 输出 HOLD；项目仍可完成 |

不允许优先删除：Objective Contract、真实外部 Updater、独立数据池、ID/OOD/Replay、安全/成本 Gate、Trial Reset、Decision、DeepSeek 原生插件、原生 Trace 共存、Banking 纵向验证、Core Independence。

---

## 16. 变更控制

### 16.1 Pilot 前可调整

- 代码目录细节；
- 上游 Adapter 的实际字段映射；
- DeepSeek Harness 官方 API 对应的入口文件名；
- Fixture 数据；
- Pilot 测得的成本/延迟阈值候选。

### 16.2 正式候选前必须冻结

- τ³、AHE/ACE、DeepSeek Harness 精确版本与 commit；
- 模型、检索配置、每 Turn 最大输出 Token、Turn/Simulation 超时和并发预算；
- Objective Contract 与 Gate 阈值；
- 六池任务与 Hash；
- Replay 任务；
- OOD 工作流族；
- Asset Manifest、Mutation Policy、Risk 与 Diff Budget；
- AHE/ACE 选择状态；
- 外部 Updater 的临时文件、工具输出、缓存与子进程结果目录策略，以及在正式 OS Sandbox 内执行的
  零模型写入预检；
- Trial 数、Infra Invalid 与重试规则；
- 跨进程 Resume 的全局 Task Attempt 上限与网络路由策略；
- Task Attempt、Agent/User Model Usage Ledger 的 Schema 版本、逐调用任务身份与 DSH Session
  绑定策略；
- 双选择器规则；
- DeepSeek 插件权限策略、Bridge Protocol 与 DSH→τ³ Reply/Trace 协议版本；
- Runner 非成功终态、Usage/费用恢复和未知费用报告口径；
- Trace `reference/mirror` 模式、Redaction Policy、Cursor/去重、Evidence Verify 与原生 Telemetry 共存规则；
- Banking Pilot 的 3—7 个任务、DSH Profile 和 Trace/Outcome Join Key。

### 16.3 冻结后允许的变更

只允许：

1. 明确 Bug 修复，并对 A0 与全部受影响候选对称重跑；
2. 命中预注册 Tripwire 的降级；
3. 不改变数值结论的报告、脱敏和安装文档修复。

每次变更必须保留旧结果并写入机器可读 Experiment Log。

### 16.4 R2 A4 之后的修复边界

Banking R2 A4 使用冻结的 4096 输出 Token、180 秒 Turn 超时和 `dsh-tau3/1.1` 生产标记完成了
一次失败协议诊断；它的原始 Result、DSH Session Trace、模型用量账本、Attempt 终态和 Incident
必须永久保持不可变。修复消费端协议版本判断属于表示层修复，可以在同一原始字节上生成不高于
`HOLD` 的恢复 Artifact；提高 Token/超时、改变 Reply 兼容或失败费用恢复会影响执行行为，必须在
新 Protocol、Experiment 与 Baseline 身份下进行。新实验保持原 Objective、Split、Gate、任务和
Trial 对称性；不得挑选性复用 A4 成功项、删除 Infra Invalid 或把未知费用改写为零。
所有派生证据路径也必须随新 Experiment 隔离；旧 Experiment 的 write-once 目录只能读、不能写。

### 16.5 R3 之后的恢复与成本边界

Banking R3 以协议 `1.2` 和 8192 输出 Token 完成 Update-Source：25 个任务位置中 22 个有效、
3 个 Infra Invalid，结论为不可推进的 `HOLD`。该结果同时证明了两个协议缺口：τ³ 的
`max_retries=1` 只约束单个进程，外层 `--auto-resume` 会对 Infra Invalid 重新应用预算；最终
Raw Result 不能保存被丢弃 Attempt 内的 User Simulator 调用成本。R3 的 Batch、Attempt、模型
账本、Raw Result、成本下界和 HOLD 不得重写。

后续正式实验必须使用新 Protocol/Experiment/Baseline 身份，并同时满足：

1. 通过 append-only Task Attempt Ledger 在 `(Batch, task, trial, seed)` 维度执行全局两次上限；
2. 通过独立 User Model Usage Ledger 记录最终 Raw Result 之外的 Simulator 调用；
3. 把有效 Run 精确成本作为 Gate，把全 Attempt 已知下界与未知范围作为独立运营披露；
4. 依据 R3 的五个触顶任务和 pinned DeepSeek provider 的 256k 默认上限，将 Agent 每 Turn 输出
   预算校准为 32768，并保持 300 秒 Turn、1800 秒 Simulation 超时；
5. R3 已确认本机代理 `127.0.0.1:10823` 曾瞬时失联，而同机直连健康；因此该实验冻结
   `direct_no_proxy`，只清除子进程代理变量，不修改系统或用户网络设置；
6. Objective、Split、Gate、任务、Trial、模型、温度、Provider 重试和四项消融保持不变。

以上修订只解决可观测性、执行预算与恢复拓扑，不得用 R3 的 Formal Gold、成功/失败结果选择
候选或调整成功判据。若新基线仍有 Infra Invalid，继续封存为 HOLD，不得通过追加 Resume 绕过
全局预算。

### 16.6 R4 之后的 Reply 兼容边界

Banking R4 以协议 `1.3`、全局两次 Task Attempt 上限、独立 Agent/User 调用账本、
`direct_no_proxy` 和 32768 输出 Token 完成 Update-Source。25 个任务位置中 24 个有效、1 个
Infra Invalid，结论为 `HOLD`。全 Attempt 的 796 次 Agent 调用和 233 次 User Simulator 调用均有
精确 Usage/费用，整次模型成本为 USD `0.69178802080000000240`；R3 的代理、输出预算、跨 Resume
重试和失败费用可观测性缺口均已被修复。R4 Batch、Raw Result、双模型账本、Task Attempt Ledger、
成本报告和 HOLD 不得重写。

唯一 Infra Invalid 位置在第一次 Attempt 生成了语法不完整的 JSON，第二次 Attempt 生成了
`{<tool-name>: <same-tool-name>, arguments: {...}}`。前者没有唯一可恢复语义，必须继续 fail closed；
后者只有在以下条件全部成立时才允许规范化为 `{name: <tool-name>, arguments: {...}}`：

1. 对象键必须且只能是动态工具名与 `arguments`；
2. 动态工具名必须在当前 Turn 的精确 allow-list 内；
3. 动态键的值必须是与键逐字相等的字符串；
4. `arguments` 必须是对象且内容原样保留；
5. 未知工具、值不相等、额外键、非对象参数或无效 JSON 一律拒绝。

这是一条可证明唯一映射、无参数补全、无工具猜测的表示层兼容规则，但它会改变正式执行能否继续，
因此必须命名为新的 Reply Normalization Policy，并使用新 Protocol/Experiment/Baseline 身份完成
25 个 Update-Source 位置的对称重跑。新实验保持 R4 的 Objective、Split、Gate、任务、Trial、模型、
温度、输出/超时、网络、全局重试和成本口径不变；不得只重跑失败位置，不得把 R4 的 HOLD 改写为
成功，不得对语法损坏的 Attempt 做推测性修复。R4 的脱敏根因 Artifact 必须作为新协议校准依据，
但 R4 的 Formal Gold、成功/失败结果仍不得用于候选选择或成功判据调整。

### 16.7 R5 之后的 Empty-Final 与嵌套超时边界

Banking R5 使用 Reply Policy v4 完成了新的 25 位置 Update-Source：23 个有效、2 个 Infra Invalid，
7 个成功、16 个有效 Task Failure，结论为 `HOLD`。R4 唯一阻断位置 `task_078` 在 R5 第一次
Attempt 即走完 832.19 秒的完整路径并被 evaluator 判为有效 Task Failure，证明 v4 消除了特定的
冗余工具名表示阻断，而没有改变真实业务成败。R5 Batch、Raw Result、双模型账本、Task Attempt
Ledger、成本下界和 HOLD 不得重写。

R5 的 23 个有效 Run 成本精确：Agent USD `0.512214029600000021`，User Simulator USD
`0.0943866400000000017`。全 Attempt 已知模型成本下界为 USD `0.65718674880000000402`；两次
外层 300 秒超时在 Envelope/Usage 返回前终止 DSH，费用未知且不得填零。R5 同时证明两个新的协议
缺口：

1. 四次被旧分类称为 invalid JSON 的终态均为 56 个 reasoning token、0 个最终文本字符；这是
   `empty_final_response_after_reasoning`，不是可修复的 JSON 语法。不得从 reasoning 推断工具或回复；
2. pinned `@deepseek-ai/dsh-llm-deepseek@0.1.0-rc.8` 的宿主
   `streamIdleTimeoutMs` 默认为 300000，而 R5 外层 subprocess timeout 也恰为 300 秒。两个超时
   同时竞争，外层可能先杀死 DSH，使宿主无法完成自己负责的 abort、Trace 持久化和终态返回。

后续正式实验必须使用新 Protocol/Experiment/Study/Baseline 身份，并满足：

1. 把 DSH provider 的 `streamIdleTimeoutMs` 显式冻结为 300000；外层 subprocess timeout 冻结为
   360 秒，使宿主先拥有取消权，并预留有界的 Trace 持久化与进程退出余量；这不等于允许模型在
   300 秒无数据后继续生成；
2. 空最终文本必须使用独立错误类型，不得再记为 invalid JSON；如果存在非零 reasoning Usage，仍
   逐调用保留 Token、费用、时长和原生 Session 引用；
3. 每个 tau3 Agent Turn 最多允许一次同 Session 的 final-only 修复调用。修复 Prompt 只能要求
   “补交缺失的最终 reply”，不得复制 reasoning、猜测工具、补全参数或查看 Formal Gold；原调用与
   修复调用必须分别写入 append-only Agent Model Usage Ledger；
4. 修复成功时，tau3 Raw Result 中该 Turn 的 Agent token、费用和时长必须聚合两次调用，避免有效
   Run 成本漏记；修复失败仍按原 Task Attempt 失败并受全局两次位置上限约束；
5. 无效 JSON、未知工具、歧义结构、修复后仍为空、Host Idle Timeout 或证据不完整继续 fail closed；
6. Objective、Split、Gate、25 个任务、Trial、模型、温度、32768 输出 Token、1800 秒 Simulation、
   `direct_no_proxy`、Provider 内部重试为 0、全局 Task Attempt 两次上限、成本 Gate 与四项消融均
   保持不变。

新的无模型校准必须覆盖：一次 empty-final 后修复成功的聚合 Usage/费用；连续两次 empty-final 的
有界失败；修复回复为坏 JSON/未知工具时拒绝；显式 v4 仍保持旧语义；DSH 内层 idle timeout 小于
外层 timeout 并被 child environment 与 Composition Digest 绑定。完成 clean-room 后，对全部 25 个
Update-Source 位置对称重跑；不得只重跑 `task_067`、`task_074`，不得追加第三次 Task Attempt。

### 16.8 R6 之后的显式 Reply 表示与失败尝试 Lineage 边界

Banking R6 使用协议 `1.4`、显式 300,000 ms DSH idle timeout、360 秒外层 Turn timeout 和一次
同 Session final-only 修复完成 25 个 Update-Source 位置：24 个有效、1 个 Infra Invalid、4 个成功、
20 个有效 Task Failure，结论为 `HOLD`。全 Attempt 的 828 次 Agent 调用与 237 次 User Simulator
调用均有终态和精确费用；整次观察模型成本为 USD `0.76983436480000000316`，Provider 重试和未结算
调用均为 0。R6 Batch、Raw Result、双模型账本、Task Attempt Ledger、原生 DSH Session、Evidence
Join、成本报告、根因 Artifact 和 HOLD 不得重写。

R6 证明 R5 的两项控制真实生效：3 次 empty-final 全部被一次同 Session 修复，原调用和修复调用的
Usage/费用既独立落账又聚合进入有效 Run；没有调用触及 32,768 输出上限、300 秒 Host idle timeout
或未知费用。R5 永久无效的 `task_067`、`task_074` 在 R6 首次 Attempt 即形成有效 Task Failure，说明
该修复只恢复执行完整性，没有伪造业务成功。`task_019` 的完整 `termination_reason=timeout` 按 §5.3
是有效 Task Failure；它不是 Infra Invalid，也不构成 Simulation 预算 Spec 缺口。

R6 唯一永久 Infra Invalid 为 `task_069`。`task_053` Attempt 1 与 `task_069` Attempt 1 均明确输出了
allow-listed wrapper 和完整参数，但在单一 Tool Call 对象里遗漏固定的 `name` 字段标签；
`task_069` Attempt 2 则明确输出了 `call_discoverable_agent_tool`、被调用 subtool 和完整底层参数，
但使用了 wrapper alias 形状。v4 依据冻结规则正确 fail closed；重复出现的显式、唯一可判定表示说明
P0 的“即插即用”仍缺一个更窄的 v5 规范化规则，而不是需要放宽成功判据或推断 reasoning。

R6 还证明现有失败证据的归属不够直接：失败 Attempt 的费用、模型调用和原生 Session 均存在，
但 Task Attempt 终态没有直接绑定 DSH Session Hash，Agent/User 调用事件也没有直接绑定任务位置；
当前只能依靠不可变时间窗与确定性 Session 命名复核。公开论文级证据禁止依赖这种旁路推导。

后续正式实验必须使用新 Protocol/Experiment/Study/Baseline 身份，并同时满足：

1. Reply Policy 冻结为
   `bounded_allow_list_v5_missing_name_and_discoverable_wrapper_alias`，且只实现 §9.2 两个精确形状；
2. Task Attempt Ledger 升级后，每次 Attempt 必须记录 `STARTED → SESSION_BOUND → terminal`；
   `SESSION_BOUND` 在首次 Agent 调用前写入实际 Session Hash；无模型调用的早期失败可无 Session，
   但必须显式标注；
3. Agent 与 User Model Usage Ledger 新版本对每个调用的 STARTED/terminal 事件强制绑定相同的
   `task_id/trial/seed/attempt_index`；任务归属、失败费用和修复费用不得再靠时间窗推断；
4. 新的无模型校准必须覆盖两个 R6 形状的正例，以及未知 wrapper/subtool、混合回复、多调用、
   额外键、数组或损坏参数、非唯一语法和未 unlock subtool 的反例；必须证明 raw reply 不被覆盖、
   执行权限仍由 τ³ 掌握；
5. Objective、Split、Gate、25 个任务、Trial、模型、温度、32768 输出 Token、300000/360/1800
   超时顺序、`direct_no_proxy`、Provider 内部重试 0、全局 Task Attempt 两次上限、empty-final 修复、
   成本 Gate 与四项消融保持不变；
6. 完成 clean-room 后对全部 25 个 Update-Source 位置对称重跑；不得只重跑 `task_053/task_069`，
   不得追加第三次 Attempt。新基线 Evidence Integrity Gate 通过前，不得生成候选或运行 Core 560。

### 16.9 R7 之后的冻结价格与直接成本归属边界

Banking R7 使用协议 `1.5` 完成 25 个 Update-Source 位置并通过 Evidence Integrity Gate，随后由固定
诊断生成 3 个 AHE 候选，A0 Update-Check 也形成 10/10 有效结果。R7 的这些 Batch、Raw Result、
Agent/User/Task Attempt 账本、原生 DSH Session、候选、费用、时间和诊断均为不可变历史证据。

首个候选 Update-Check 期间，LiteLLM 远程价格表超时且本地表没有 `deepseek-v4-flash`，导致上游
User Simulator 在 42,394 input 与 2,068 output Token 非零时返回 13 个 `cost=0`。旧 User hook
错误地把动态返回值写成 `exact 0`；按已冻结单价重算应为 USD `0.00651420`。操作员在任何候选
Simulation checkpoint 前停止批次；该批次是 FAILED/partial，保留一个未终结 Agent 调用，不得
Resume 成有效证据，也不得进入 Selection/Core 560。这个事件是实现与 preflight 缺口，不改变
Objective、Split、业务成功判据、Reply v5 或 Gate。

后续新的付费正式实验必须使用 Protocol `1.6+`、新的 Experiment/Study/Baseline 身份，并同时满足：

1. User Simulator hook 在任何付费调用前读取冻结单价，只用已验证 Token 重算费用；动态价格表与
   上游 `result.cost` 不具权威；
2. 成本 Artifact 使用 schema `1.3+`，从最终保留 Simulation 绑定的 completed Task Attempt 选择
   Agent/User ledger `1.2` 调用；失败、重试、未保留和未终结调用仍完整进入 whole-Attempt 口径；
3. 每个 direct `exact` 调用必须和冻结价格重算值一致；正 Token 对应正单价时 `exact 0` 必须拒绝；
   Raw `agent_cost/user_cost` 只列为对照，并报告 raw/direct mismatch；
4. 无模型校准和 clean-room 必须覆盖 §5.5 的四个成本 Fixture，并绑定成本实现、账本、Batch、协议、
   Service 与 AHE doctor 的文件 Digest；
5. AHE doctor 必须从隔离工作目录真实导入 pinned checkout 的 `evolve`；正式 child environment 必须
   注入该 checkout 的 `PYTHONPATH`，且 `direct_no_proxy` 同时清除大小写代理变量；
6. R7 已完成且语义不受影响的历史证据不得删除或伪装成 R8。新的决策级比较从受成本实现影响的
   最早阶段重跑；若新 Protocol/Source 身份使基线不可直接比较，则补齐同身份 A0 对称证据。禁止
   因文案、排版或可从不可变原始字节重建的表示层修改机械地把全部研究从零重跑；也禁止选择性
   复用能改变结论的旧结果。每次重跑范围及其依赖理由必须写入 append-only Operator Journal。

### 16.10 R8 之后的 Cost Gate 输入绑定

R8 在任何付费 Batch 开始前的源代码审计发现：Cost Artifact 已能按 §5.5 从直接 Task Attempt
Agent/User 调用重算有效费用，但 Batch `EvaluationSummary.mean_cost`、候选曲线和最终 Cost Gate
仍读取 τ³ Raw `RunRecord.cost`。因此 R8 只保留为无模型校准、预检与 fail-closed 证据，不产生正式
比较结论；不得在当前实现上继续 R8 付费执行，也不得把 R7 Raw cost 重新包装为新 Gate 结果。

后续新的付费正式实验必须使用 Protocol `1.7+`、新的 Experiment/Study/Baseline 身份，并满足：

1. Cost Artifact 使用 schema `1.4+`，同时给出有效 Agent、有效 User、二者总和与按有效 Run 数
   计算的精确均值；非 `exact` 时不得构造可用于排序的精确均值；
2. Evaluation Summary 使用 schema `1.1+`，绑定 `direct_task_attempt_model_calls`、Cost Digest、
   Cost Status 与直接 Agent+User 均值；
3. Selection、候选曲线和最终 Gate 必须只读取上述 Summary 值；最终跨 Batch 均值按有效 Run 数
   加权。任何 Summary 缺少直接来源、Digest 或 `exact` 状态时必须 fail closed；
4. 无模型回归必须故意令 Raw cost 与直接 Agent+User cost 不相等，并证明 Batch Summary 与最终
   Gate 输入采用后者；校准必须绑定 Evaluation、Ledger、Batch、Orchestrator 与 Service 实现；
5. 修复不改变 Objective、Split、Outcome、Reply v5、Trace 共存、任务集合、模型、Gate 阈值、
   Core 560 或四项消融，只收紧成本证据到决策的端到端归属；
6. R7/R8 的全部成功、失败、部分、费用、时间与命令纠正记录继续保持不可变。只有受该语义依赖的
   新正式比较使用新身份重跑，纯文案与不影响证据的表示层修改仍不触发模型调用。

### 16.11 R10 C2 之后的 Selection 设计修正与付费暂停

R10 已完成 Update-Source 25 个位置、A0/C1/C2/C3 Update-Check 各 10 个位置，以及 C1/C2
Selection 各 15 个位置，共 95 个正式任务位置；C3 Selection、Release-ID、Release-OOD 与 Replay
均未启动。到 C2 封存为止，可验证模型总成本为 USD `3.0651904832`，本地计算费用仍为未计量；
所有批次的 Raw、Batch、Cost、Task Attempt、Agent/User Usage、DSH Session、Evidence Join、
外层墙钟时间、错误与重试必须保持不可变。

C1 与 C2 在 Selection 都是 7/15，但成功任务发生互换，不能解释为稳定方向性提升。零模型设计审计
进一步确认：

1. 冻结的 R10 Study 在 Selection 只安排了 3 个候选，没有 A0 同池基线；
2. 当时的 Selector 必须从合格候选中选一个，没有 `HOLD/ABSTAIN`；
3. 当时排序只读取稳定成功数、有效 Run 平均成本与 p50，未读取 whole-Attempt 成本、失败尝试、
   重试、Timeout、p95 与最大延迟；
4. C1 `C_AHE_AED3D43F759E` 与尚未运行 Selection 的 C3 `C_AHE_23F1F9DC6BD4` 在修订后的
   行为语义指纹下相同，都是 read-after-write 成功声明门，不能作为两个独立修改方向；
5. C2 `C_AHE_A3C057997F5B` 在工具路由 YAML 中硬编码通用开发工具名，而 Banking Runtime 的
   实际工具集合由每个 Task 的动态 Tool Schema 提供；它在修订后的 Candidate Check 下为
   `REJECT_UNBOUND_CAPABILITY`。因此 C2 的 7/15 只能保留为历史执行证据，不能支持“工具路由修改
   指导出正确自进化方向”的因果主张。

这属于 SPEC/Selection 设计缺口，不是通过继续跑 C3 或 Release 就能补救的随机波动。自 C2 完成起，
所有新增付费实验进入 `PAID_HOLD`；禁止用旧 R10 Selector 生成 RC，禁止启动 C3/Release/OOD/Replay，
也禁止修改 R10 Protocol、Study、Batch 或已有候选来事后满足新规则。

该暂停必须由代码执行而非只靠文档提醒：schema 1.0/1.1 Formal Config 一律不能启动新的付费 Stage；
schema 1.2 若缺少与当前 Experiment、Protocol、Study、Source Revision 和 125 个位置完全一致的
`pre_release_checkpoint` Owner Authorization，preflight 与 Service 都必须失败。仓库当前不生成
下一实验的 Authorization Artifact；因此即使凭证仍在当前进程中，也不能开始下一批付费调用。

下一次付费实验必须使用新的 Experiment/Study/Baseline 身份，Study schema `1.2+` 的 Selection
矩阵为 A0 + 3 个语义不同且通过 capability 绑定的候选，即 15 × 1 × 4 = 60 个 Selection 位置；
在其余旧矩阵逻辑不变时 Core 目标由 560 变为 575。Selection Policy 至少冻结：严格稳定成功增益、
零稳定任务回退、whole-Attempt 成本比、p95 比、重试增量与 Timeout 增量。若没有候选通过，必须在
Release 前结束为 `HOLD/ABSTAIN`。该结果按 §7.5 作为成功退出的正常治理终态封存，不能伪装成
基础设施失败，也不能为了获得“完整 Release 曲线”而绕过弃权继续调用模型。

R10 的 Evidence Governance、Trace/Persistence/Telemetry 共存、直接 Token/成本归属、失败恢复、
批次完整性和运行时间证据仍可用于工程可靠性与历史审计；候选效果结果可用于提出新假设和估算执行
预算，但在完成跨身份等价性证明前，不得作为新 Selector 的决策级复用。是否复用任一模型结果必须
先生成逐 Artifact 的 Evidence Reuse Audit；不能证明相同 Objective、Split、任务、Trial、模型、
执行语义、Harness Composition 与 Evaluator 身份的证据，只能标记为 `historical_context`。任何最小
补充付费计划仍需 Owner 明确授权。

### 16.12 R11 修正检查点的冻结与授权边界

R10 C2 后的零模型修正已经冻结为 `EXP_BANKING_R11`，但冻结不等于获准执行。其唯一可执行输入为：

- Protocol `BANKING_R11_PROTOCOL_1`：
  `sha256:68b03d74f7195b80928c61fdd79f713fe3bcbba0c0df3b054763c4d88bb663ea`；
- Study `BANKING_R11_STUDY_1`：
  `sha256:97de7e47fd2328f568b74b70f23cc6347adae477d9bc1db81984ec641ca05ebb`；
- Execution Source：
  `tree:sha256:c392a3af0afadd566bd21169d11e63684312921c1e1fbab24f13cefb88bebee0`；
- Evaluation Baseline `R11_A2`：
  `sha256:c65cec1e852e1840d04a556f595b99e788bc7099b3afd084e6401209ccf5a2bb`。

`R11_A0` 是在外部 Updater 授权边界加入前生成的准备期 Baseline；`R11_A1` 是在 sdist 有界打包
修正前生成的准备期 Baseline。二者只能保留为不可变历史，不能执行。活动部署仍为 `A0`，R11 的
全部 Baseline Freeze 都没有部署或 Promote 任何 Snapshot。

Formal Config schema `1.2+` 允许经过复核的新 Evaluation Baseline 与当前活动 Snapshot 的 Harness
资产不同，但必须把新资产和 Source Revision 完整内容寻址，并在运行前按该 Evaluation Baseline
重新验真 Live Bytes；该例外只用于尚未激活的正式评测输入。它不得绕过单独的人类 Promotion
Approval，也不得改变活动 Snapshot Registry。旧 schema 继续要求与活动 Snapshot 相同。

R11 的原计划第一段 Owner Scope 为 25 个 Update-Source、40 个 Update-Check、60 个 Selection，
共 125 个正式任务位置，以及同一 Scope 内单独计量的外部 AHE Updater 生成调用。实际授权后来被
限定为既有 25 个 Update-Source 的执行和封存；它不授权 Updater、Update-Check 或 Selection。外部
Updater 不计入 125，但后继实验若授权该能力，必须记录每次 Token、价格、成本、重试、耗时、执行
路径和 Lineage，并在首次 AHE 调用前再次验证
`external_updater_generation_authorized=true`。凭证存在、输入已冻结或 preflight 通过都不能替代
Owner 授权。

R11 曾通过 `R11-NM-008` 零模型 Clean-room（183 个 Python、13 个 TypeScript 测试，
269 文件 Secret/PII 扫描零发现）。随后在 Owner 的限定授权下，仅执行了其 25 个
Update-Source 位置：24 个有效、`task_020` 一个 Infra Invalid。原始结果、Agent/User Usage、
Task-Attempt 和成本账本均已不可变封存；直接有效 Agent/User 成本分别为 USD `0.5385791880` 和
USD `0.08244740`，整次观察到的 provider 成本下界为 USD `0.7266205472000000021`，本地计算货币
成本为 `unmetered_unknown`。因 `infra_invalid:1` 与 `missing_valid_trials`，该 Batch 必须是 `HOLD`，
不得进入 Update-Check、Selection 或 Release。

封存过程中发现“Infra Invalid 没有 completed task-attempt lineage”会使恢复路径错误失败；修复仅允许
`existing_only` 在验真既有 Evidence 时跳过修复后运行时代码的字节绑定，仍严格校验 Protocol、Study、
Pricing、Snapshot、Raw 和 Artifact Digest，且绝不允许新的付费执行使用该例外。此实现修复不会改变
R11 的输入、原始事实或 `HOLD` 含义。R11 不能重跑、不能被原地补齐；后继完整实验必须建立新的冻结
身份与新的 Owner 付费授权。顺序执行时间 15–25 小时、中心成本约 USD 4.05、工作范围 USD 3.5–6.5
仍只适用于后继完整 checkpoint 的计划，不是 Gate、授权或停止条件。机器可验预注册、R11 封存记录与
完整边界见 `artifacts/research/banking_r11/pre_run_preregistration.json`、
`docs/research/banking-r11-preregistration.md` 和
`runs/experiments/EXP_BANKING_R11/`。

### 16.13 R12 后继身份与 Infra Invalid 恢复校准

R11 的部分 `HOLD` 之后，完整验证必须使用新的 `EXP_BANKING_R12`，不得把 R11 的 24 个有效结果或
`task_020` 作为 R12 决策级复用。R12 的冻结身份为 Protocol
`sha256:6c86b494bad7766a8b25477c7e0a73217bc5a7f552e995824ed0ee538dcbd3f2`、Study
`sha256:423ca8b74d38998c038e2824f9d9582275cae9630a6f85c201afa628301732a4`、Execution Source
`tree:sha256:d7f8e3a0b8a9004fcb1778d90bb773360dda6a5fa1eb7ad68ca9a64eece265bd` 与
Evaluation Baseline `R12_A0`
`sha256:f4af003bf938583b134e6a1eab42bcb0abcf9f10b730e8f1411c61b443922c36`。

Cost-Lineage Calibration schema 1.2 新增强制 fixture
`infra_invalid_failed_attempt_lineage_sealed`：只有明确为 `infrastructure_error`、不存在 completed
Attempt 且同一 task/trial/seed 的最终冻结 Attempt 为 failed 时，封存才可绑定该 failed Attempt；所有
非 Infra Invalid 结果仍必须绑定 completed Attempt。`existing_only` 的运行时字节例外只可验真并封存
已经存在的原始证据，新付费 Stage 必须保持全部运行时绑定严格一致。

R12 最终冻结源码的 `R12-NM-003` no-key clean-room 通过 190 个 Python、13 个 TypeScript 测试、
sdist→wheel、DSH conformance/build/pack 和 281 文件 Secret/PII 零发现；耗时 16.11 s real、
12.42 s user CPU、2.81 s system CPU，最大 RSS 358,694,912 bytes，已知模型调用与费用均为 0，
本地计算货币成本仍为 `unmetered_unknown`。随后 R12 在精确机器授权下执行 25 个 Update-Source
位置、三个外部 AHE 候选和 10 个 A0 Update-Check Anchor 位置；Anchor 的 `task_073` 在两次冻结
Attempt 中均因空 `UserMessage` 结构错误成为 Infra Invalid，批次因 9/10 有效分母而不可变
`HOLD`。候选 Update-Check、Selection、Release 与 Promote 均未启动，不能声称候选有效或已经找到
正确自进化方向。所有已观测 Provider 调用成本下界为 USD `1.1970712488`，已知调用均为精确账本，
本地计算仍为 `unmetered_unknown`。终态封存 Digest 为
`sha256:73457f10b7a7f8e2347b7d06cf24680ff46805546290b3ba89432bbca5ad383e`；同一 R12 身份禁止
重跑、补齐或扩展，修复后必须冻结后继身份。

### 16.14 R12 后的 User Simulator 与 AHE 沙箱完整性边界

R12 `task_073` 的两次终态来自 pinned τ³ User Simulator 将“无最终文本且无 Tool Call”的 Provider
回复直接构造成非法 `UserMessage`；这不是 Agent Reply v5 能处理的路径，也不得从 reasoning 推断
用户内容。R12 三个 AHE Attempt 的 stderr 同时记录了对 `/tmp/nexau_bash_tool_results` 的
`Operation not permitted`：AgentLoopGate 正确地只允许 Attempt 根写入，但 NexAU LocalSandbox 与
AHE LongToolOutputMiddleware 仍使用进程全局 `/tmp` 默认目录。三个进程虽退出 0 并产生候选，候选
从未进入 Update-Check，故既不能认定候选无效，也不能把该警告忽略为不影响正式执行。

这两项同时属于实现与 Protocol/SPEC 完整性缺口。R12 原始证据、成本下界 USD `1.1970712488`、
`HOLD` 和未评测候选保持不可变；修复、诊断与 clean-room 均为零外部模型调用，已知 Provider 成本
为 USD `0`，本地计算货币成本为 `unmetered_unknown`。后继正式实验必须使用 Protocol `1.9+` 和
全新的 Experiment/Study/Source/Evaluation Baseline 身份，并冻结：

1. User Simulator `bounded_same_call_context_final_only_v1`，每 Turn 最多一次，双调用独立账本且
   retained Usage 聚合，第二次为空继续 fail closed；
2. Updater `attempt_local_runtime_only_v1`，NexAU bash、长输出、cache 与 TMPDIR 全部位于 Attempt 根；
3. 在正式 macOS Sandbox 中实际执行 NexAU bash 的无模型 doctor，而不是只做 import 检查；
4. 内容寻址的 R12 根因 Artifact、后继完整性 Calibration、所有相关运行时代码 Hash、反例测试和
   完整 clean-room；
5. 原 Objective、97 任务 Split、Evaluator Overlay、Pricing、Reply v5、Trace 共存、A0-bound
   Selection、成本/延迟/重试 Gate 与人工 Promotion 边界不变。

机器根因与校准证据分别为
`artifacts/research/banking_r13/r12_successor_integrity_incident.json`（Digest
`sha256:552d0cd210f96ee23de5cb2516eff3e90337fdb716d78988677df7e8a0a4ab65`）和
`artifacts/research/banking_r13/successor_integrity_calibration.json`。只有后者的 Runtime Binding、
Protocol Digest 与后继冻结源码逐字匹配后，才可创建新的付费机器授权；任何不匹配都必须在首次
模型调用前失败。后继实验仍须从 25 个 Update-Source 全池开始，禁止只补跑 `task_073`、复用 R12
候选或把 R12 的 34 个有效位置拼入新决策分母。

---

## 17. 旧 SPEC 核心保留映射

| 旧 SPEC 核心 | 新 P0 位置 | 状态 |
|---|---|---|
| Objective Contract 与 RPCR | §1、§4 | 完整保留并简化 Schema |
| 失败漏斗与修改路由 | §6 | 完整保留 |
| 广义 Harness 资产 | §3.4 | 保留全资产模型；P0 自动执行收敛到 L/M |
| AHE 默认、ACE 降级 | §7 | 完整保留，并明确真实接入验收 |
| Candidate Snapshot Ladder | §5.7、§6.3 | 完整保留 |
| AHE-native vs AgentLoopGate Selector | §5.7、§7.5 | 完整保留 |
| 六池隔离与防泄漏 | §5.1、§3.3 | 完整保留 |
| ID/OOD/Replay/Pass^k | §4、§5 | 完整保留 |
| 安全、成本、可靠性硬门 | §4 | 完整保留 |
| Outcome-first、Reset、Infra Invalid | §5.3—§5.6 | 保留核心，删去过度审计平台 |
| Ship/Hold/Rollback | §4.4、§9.6 | 完整保留 |
| Governance Trust Kernel | §3.3 | 完整保留 |
| DeepSeek Harness Cordis 插件 | §8、T10—T12 | 提升为明确 P0 社区交付 |
| DeepSeek 原生 Session/Persistence/Telemetry | §3.2、§8.6 | 明确为共存而非替代；新增 P0 兼容合同 |
| Banking 作为可靠性/可用性验证场 | §8.10、T13 | 新增插件 × 真实场景纵向验证 |
| 本地事实源、插件失效降级 | §3、§8.6、§13 | 完整保留 |
| 可复现开源版本 | §2.5、T14 | 保留，删除原创证明繁文 |
| Capability Map | §2.7 | 移出 P0 |
| Evaluation-to-Data | §2.7 | 移出 P0 |
| Model × Harness 2×2 | §2.7 | 移出 P0 |
| Langfuse UI | §2.7 | 移出 P0；不影响本地事实源 |

精简原则是“删除不直接证明主张的旁支”，不是删除原项目的持续优化、治理和社区接入能力。

---

## 18. 实施依据

实现前必须重新核对被 pin 版本，官方源码优先于本 SPEC 中的描述：

1. τ³-bench：<https://github.com/sierra-research/tau2-bench>
2. SEAGym：<https://github.com/antropy-research/SEAGym>
3. AHE：<https://github.com/china-qijizhifeng/agentic-harness-engineering>
4. ACE：<https://github.com/kayba-ai/agentic-context-engine>
5. DeepSeek Harness：<https://github.com/deepseek-ai/deepseek-harness>
6. DeepSeek Harness Architecture：<https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md>
7. DeepSeek Harness Development：<https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/development.md>
8. DeepSeek Session Event Log：<https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/core/session>
9. DeepSeek Session Telemetry Seam：<https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/session/session-telemetry>
10. DeepSeek OTel Backend：<https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/session/session-telemetry-otel>
11. DeepSeek JSONL/SQLite Persistence：<https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/session>

DeepSeek Harness 官方文档确认：它使用 Cordis 插件架构；Profile 由有序 Bundle 和 Patch 组成；`headless` 是官方模板；Service、事件、Tool Registry 和可逆 Effect 是扩展点。Session 是 append-only 运行事实源，可由 JSONL/SQLite 持久化；Telemetry 是独立可选出口。它同时明确处于 Developer Preview，因此 T11 必须精确 pin 并以真实源码完成 Conformance。

---

## 19. 开工顺序

下一步不是继续扩写规格，而是按顺序执行：

```text
T00 -> T01 -> (T02 + T03) -> T04 -> T05 -> T06 -> T07
                                      |                |
                                      +-------> T08 -> T09
T01 + T06 + T08 -> T10 -> T11 -> T12
T04...T12 -> T13 -> T14
```

第一张任务卡是 T00。第一阶段入场券是：`doctor`、Schema 测试、Host Trace→Normalized 重建、六池 ACL 和两个真实上游 Spike，而不是新的方向性文档。
