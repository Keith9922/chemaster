# AGENTS.md — ChemMaster Agent 协作指南

> 这是新会话接手本仓库时**第一个必读文档**。
> 读完本文件后，按 §10 的索引去 `docs/` 找细节，按 §8 的"立即可做的下一步"开始动手。
>
> 不要绕过本文档去推理项目目标 —— 这里写的是已经和用户对齐过的决策，**不要重新讨论**。
>
> **本版本（v3.0）反映 2026-05-05 的方案修正：定位调整为"通用工具 + 基础验证"，
> 砍掉 TADF 应用层验证，引入 labor-saving collaborator 哲学与权限分级机制。
> 详见 `docs/REFACTOR_PLAN.md`。**

---

## 0. TL;DR（30 秒读完）

- **项目**：ChemMaster，**本地运行、大模型驱动、终端原生**的**通用计算化学 Agent 系统**，类 Codex 形态。
- **核心定位**：吸收"输入构造 → 任务提交 → 错误重试 → 结果解析"链路上的重复劳动，让研究者只下达自然语言意图；化学决策权（方法/基组/泛函/溶剂模型）通过权限分级机制保留给研究者。**类比**：coding vs vibe coding 之于程序员，对应 ChemMaster 之于计算化学家。
- **架构 V2（已落地）**：5 层 — TUI/CLI/Web · Agent Loop（基于 Anthropic SDK + tool use）· Tools (MCP servers + 内建 finish/ask_user/think/recommend) · Engines · Knowledge Base（formulas/ Python + rules/ YAML + skills/ Markdown）。
- **关键设计哲学（v3.0 新增）**：**labor-saving collaborator，非 autonomous decision-maker**。Agent 通过 **L1（自主）/ L2（推荐+确认）/ L3（必须用户决断）** 三级权限分级，吸收技术性重复劳动而不越权做化学决策。
- **技术栈**：Python 3.11、Anthropic SDK + MCP、ASE、cclib、RDKit、psi4/ORCA/xTB（通用性演示）、**Gaussian/BDF/MOMAP（主线工具栈）**、MultiWFN（未来工作）。
- **验证范围（v3.0 调整）**：3 个公开 benchmark — **S22**（基态结合能精度，Gaussian）+ **QUEST**（垂直激发能精度，Gaussian TDDFT）+ **蒽**（速率与动力学精度，Gaussian + BDF + MOMAP）。**TADF / AIE 应用层验证推到未来工作。**
- **开发原则**：**LLM 不算数**（公式走 `chemaster.kb.formulas` Python 模块）；所有计算交给专业软件；MCP 错误带 `suggestion` 让 Agent 在 L1 范围内自主恢复；化学决策性故障必须经 `recommend` / `ask_user` 升级；Trajectory 全持久化便于复现，且每条事件 tag `decision_authority` 区分自主步与决策点。

---

## 1. 项目愿景（why）

化学/材料/药物领域的研究者每天耗费大量时间在：写计算软件输入文件、提交 SLURM 任务、等待、解析输出、重启失败任务、整理图表。**ChemMaster 把这些重复劳动交给 Agent**，研究者只用自然语言下达意图。

我们对标的是 Rowan、Schrödinger Live Design 这类商业云产品和 ChemCrow 这类化学领域 LLM agent。**差异化**：

| 维度 | Rowan / Schrödinger | ChemCrow | ChemMaster |
|---|---|---|---|
| 部署 | 云端 SaaS | Notebook | 本地优先，分子结构不上传 |
| 形态 | Web GUI / 桌面 GUI | Jupyter | **终端原生 + 多前端（CLI/TUI/Web）** |
| LLM | 无或表层 | OpenAI 绑死 | BYO API（Anthropic / OpenAI / Qwen / DeepSeek 任选；可本地部署） |
| 计算 | 厂商云 | 主要走 Web API | 用户本机或商业云超算（并行/鸿之微，接口预留） |
| 工具协议 | 私有 | LangChain | **MCP（行业标准，可被 Codex/Cursor 复用）** |
| 决策模式 | 用户全决策 | autonomous research agent | **labor-saving collaborator（权限分级）** |
| 源码 | 闭源 | 开源 | 完全开源 |
| 国产化 | 弱 | 无 | 支持 BDF（北大刘文剑组）+ MultiWFN（田鹏） |

但"差异化"不等于"好用"。"好用"必须用硬指标承诺（见 §3）。

---

## 2. 架构总览

完整版本见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。这里放最关键的两个图。

### 2.1 五层结构 (V2 + v3.0 哲学修正)

```
┌──────────────────────────────────────────────────────────────┐
│ L5  TUI / CLI / Web      chemaster run "<intent>"             │
│                          rich Panel for confirmations,        │
│                          Textual TUI / FastAPI Web,           │
│                          summary, key_results table.          │
├──────────────────────────────────────────────────────────────┤
│ L4  Agent Loop           BaseAgent + ChemAgent                │
│                          Anthropic SDK + tool use             │
│                          Built-in: finish/ask_user/think/     │
│                                    recommend ← v3.0           │
│                          Trajectory persisted to runs/        │
│                          每条事件 tag decision_authority      │
│                          Confirmation 三 mode：               │
│                            silent / confirm / recommend       │
├──────────────────────────────────────────────────────────────┤
│ L3  Tools (MCP servers)  calc_gaussian / calc_bdf / calc_momap│
│                          calc_psi4 / calc_orca / calc_xtb     │
│                          io_ase / parse_cclib / viz /         │
│                          hpc_slurm / chem.kb / pdf            │
│                          每个 tool 自带                       │
│                            is_read_only / is_destructive /    │
│                            is_long_running /                  │
│                            is_chemistry_decision ← v3.0       │
├──────────────────────────────────────────────────────────────┤
│ L2  Engines              Gaussian / BDF / MOMAP（主线）        │
│                          psi4 / ORCA / xTB（通用性演示）       │
│                          ASE / cclib / RDKit / MultiWFN       │
├──────────────────────────────────────────────────────────────┤
│ L1  Knowledge Base       formulas/  Python 确定性公式          │
│                          rules/     YAML 规则                  │
│                          skills/    Markdown playbook（被     │
│                                      use_skill 工具读取）      │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 设计哲学：labor-saving collaborator + 权限分级（v3.0 核心）

**核心原则**：Agent 吸收重复劳动，**不替研究者做化学决策**。决策权可通过权限分级表向下委托给 agent，但用户始终掌握权限调整权。

**三级权限**（详见 `~/.chemaster/policy.yaml`）：

| Level | 范围 | Agent 行为 |
|---|---|---|
| **L1（自主）** | 输入文件语法微调、guess=GWH、damping、网络/磁盘类 retry | Silent 执行，记录到 trajectory |
| **L2（推荐+确认）** | 常规方法/基组/泛函选择、虚频处理、溶剂模型 | 用 `recommend` 提交，用户接受/改/取消 |
| **L3（必须用户决断）** | L2 重试仍失败、多重度模糊、TS vs 极小值判定、改换软件后端 | 用 `ask_user` 强制升级 |

### 2.3 Skill 是工具，不是架构层

- **MCP / Tools** = "Agent 能 *做* 什么"。每个工具是**类型化原子操作**：`calc_gaussian.optimize(geometry_xyz, method, basis, ...) → {ok, result, warnings, meta}`。
- **Skills (kb/skills/)** = 给 Agent 阅读的**领域参考文档**。Agent 通过 `use_skill(name, action="get_info")` 工具按需读取。**不再做触发匹配 / 不再是 Planner 的必经路径**。

---

## 3. "真正好用"的硬指标（毕设论文要验证）

| # | 指标 | 目标 | 验证方法 |
|---|---|---|---|
| 1 | 首次安装到第一个结果 | ≤ 30 分钟 | conda 装 chemaster env + `chemaster run` 跑 H2O |
| 2 | 端到端时间（H2O opt+freq）| < 5 min | `pytest tests/integration/test_h2o_e2e.py` |
| 3a | **技术性故障自动恢复率** | ≥ 80% | 注入 N 个技术性故障（SCF guess/磁盘/网络），跑 anchor 任务 |
| 3b | **化学决策推荐接受率** | ≥ 70% | 2-3 个被试 × ≥5 个 anchor 分子，agent 推荐被接受 vs override 比例 |
| 3c | **Trajectory 自主步占比** | ≥ 70% | 3 个公开 benchmark 全程统计 |
| 4 | 报告可直接进论文 SI（基础精度）| ≥ 80% | 3 个公开 benchmark（S22 / QUEST / 蒽）误差落在方法内禀范围 |
| 5 | **提交摩擦时间节省率** | ≥ 50% | 2-3 被试人工 baseline vs ChemMaster |

V1 文档曾列七项硬指标。V2 砍掉前两项（要等长周期验证）。**v3.0 把指标 3 拆为 3a/3b/3c，对应 labor-saving collaborator 哲学**——3a 衡量 agent 替你省了多少机械活，3b 衡量 agent 化学判断质量，3c 衡量 trajectory 中自主步与决策点的比重。

---

## 4. 项目布局

```
chemaster/
├── AGENTS.md                    # ★ 本文件，新会话第一个读
├── README.md                    # 项目对外介绍
├── pyproject.toml               # 包配置
├── .gitignore
├── .python-version              # 3.11
│
├── docs/                        # 设计文档
│   ├── REFACTOR_PLAN.md         # ★ v3.0 修正方案与决策清单
│   ├── BENCHMARK_PROTOCOL.md    # ★ 工程指标实验协议
│   ├── HPC_PLATFORMS.md         # 商业云 HPC 调研记录
│   ├── ROADMAP.md               # 阶段开发路线
│   ├── ARCHITECTURE.md          # 架构详解
│   ├── CONVENTIONS.md           # 代码、命名、提交规范
│   ├── PITFALLS.md              # ★ 开发坑表（必读）
│   ├── PACKAGING.md             # 打包发布流程
│   ├── SETUP.md                 # 开发环境搭建
│   ├── SKILLS_GUIDE.md          # 怎么写 skill
│   ├── MCP_GUIDE.md             # 怎么写 MCP server
│   └── TADF_PIPELINE.md         # 标杆问题（已降级为未来工作参考）
│
├── chemaster/                   # Python 包根
│   ├── agent/                   # Agent kernel（含 RecommendTool, 权限分级）
│   ├── mcp/                     # 自研 MCP servers
│   │   ├── const/               # 物理常数与单位换算
│   │   ├── io_ase/              # 结构 IO
│   │   ├── calc_gaussian/       # ★ Gaussian（主线，待拆细工具）
│   │   ├── calc_bdf/            # ★ BDF（主线，待扩充工具）
│   │   ├── calc_momap/          # ★ MOMAP（主线，待从零写）
│   │   ├── calc_psi4/           # 通用性演示
│   │   ├── calc_orca/           # 通用性演示
│   │   ├── calc_xtb/            # 通用性演示
│   │   ├── parse_cclib/         # 输出解析
│   │   ├── analysis_multiwfn/   # 波函数分析（占位）
│   │   ├── viz/                 # 出图
│   │   ├── hpc_slurm/           # SLURM 提交（含 platform adapter）
│   │   ├── kb/                  # RAG 检索
│   │   └── pdf/                 # PDF 抽取（占位）
│   ├── kb/
│   │   ├── formulas/            # 确定性 Python 公式模块
│   │   ├── rules/               # YAML 规则
│   │   └── skills/              # Markdown skill 库
│   ├── tui/                     # Textual TUI
│   ├── web/                     # ★ FastAPI 本地 Web 前端
│   └── cli.py                   # CLI 入口
│
├── tools/                       # 内嵌工具（非 Python 包）
│   └── pdf-structure-extract/   # 现有 PDF 工作
│
├── benchmarks/                  # 测试集
│   ├── s22/                     # ★ 弱相互作用基准
│   ├── quest/                   # ★ 激发态基准
│   ├── anthracene/              # ★ MOMAP 速率基准
│   ├── tadf-literature/         # 历史遗留（未来工作）
│   └── momap-jingti/            # 历史遗留（鲸钛初步数据）
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── runs/                        # 运行产物（.gitignore）
└── scripts/                     # 现有 PDF 脚本（暂保留）
```

---

## 5. 开发原则（**违反这些会反复返工**）

### 5.1 LLM 不算数

任何浮点运算、单位换算、物理常数 —— **走 `chemaster.kb.formulas` 模块**，不让 LLM 报数。LLM 只做：意图理解、方案规划、工具调用、结果解释。

### 5.2 计算外置

所有量化/分子模拟交给专业软件。MCP wrapper 只做参数构造、输入文件生成、结果解析、错误识别。**绝不重新发明计算引擎**。

### 5.3 Skill + MCP 双层不许混

见 §2.3。Skill 不写 Gaussian 输入文件字符串；MCP 不嵌工作流逻辑。

### 5.4 Plan-Confirm-Execute 三段式（v3.0 修订）

任何会改变文件系统、提交 HPC、或耗时 > 30s 的操作，**必须先出 Plan 让用户确认**（confirm mode）。

**v3.0 新增**：任何**化学决策性操作**（方法/基组/泛函/溶剂/多重度/TS 判定/改换后端）**必须用 recommend 机制呈现给用户**（recommend mode）。L1 范围内的纯技术性微调（语法修正、guess 改 GWH、磁盘清理重试）可以 silent 执行但全部记录到 trajectory。

### 5.5 单位带类型

所有物理量在 MCP 边界用 `pint.Quantity` 或带 `unit` 字段的 dict 传递，不裸传 float。Hartree↔kcal/mol 这类换算每犯一次都是论文里的笑话。

### 5.6 复现优先

每个任务的 `runs/<task-id>/` 必须包含：原始用户 prompt、Plan 对象、生成的输入文件、所有命令、stdout/stderr、解析后的结果、版本信息（包+软件+commit）、随机种子、`confirmations.jsonl`、**`decision_authority` tag**。3 个月后重跑必须 bit-perfect。

### 5.7 错误是常态，技术性自愈是默认（v3.0 修订）

SCF 不收敛、虚频、几何卡死、内存爆、磁盘满 —— 这些不是异常分支，是正常工作流的一部分。

**v3.0 修订**：

- **技术性故障**（输入语法、SCF guess、damping、磁盘/网络）→ **L1 自主恢复**，重试上限 3 次。
- **化学性故障**（改泛函/基组、TS 判定、多重度变更、PCM 改 SS-PCM）→ **必须升级到 L2/L3**，用 `recommend` 或 `ask_user` 让用户决策。

每个 MCP 都要返回 `warnings` 字段；每个 skill 都要写"看到 X 该怎么办，且区分 L1/L2/L3"。详见 [`docs/PITFALLS.md`](docs/PITFALLS.md)。

### 5.8 一切可测试

每个 MCP 配 unit test（mock 计算软件）+ integration test（真跑一个 10 秒能完的小体系）。Skill 用录像式测试（给定输入，校验 Agent 决策路径）。CI 跑 unit；integration 在本地或 release 前跑。**v3.0 新增**：recommend 机制路径必须有专门的测试覆盖（mock 用户接受 / override / 取消三种）。

---

## 6. 开发阶段（v3.0 修订）

详见 [`docs/REFACTOR_PLAN.md`](docs/REFACTOR_PLAN.md)。本节给一个粗概览：

| Phase | 内容 | 周数 | 验收 |
|---|---|---|---|
| 0 | 地基对齐：AGENTS.md / 协议文档 / MCP cross-client demo | 1-2 天 | 文档同步 |
| 1 | 设计哲学对齐：system_prompt + RecommendTool + 权限分级 + tagging | 4-5 天 | 跑通 demo 任务，验证 recommend 卡片 |
| 2 | 工具栈补完：Gaussian 拆细 + BDF 扩充 + MOMAP 从零写 | 2.5-3.5 周 | 蒽端到端跑通 |
| 3 | HPC 接口预留 + Agent 异步化 + TUI + Web | 3-4 周 | 三前端等价跑同一任务 |
| 4 | 三 benchmark 跑通 + 工程实验 | 4 周 | result.json 出齐 |
| 5 | 论文写作（Markdown）+ 答辩准备 | 4-5 周 | 初稿完成 |

**毕设范围外**（推到未来工作）：
- TADF / AIE 应用层验证
- ORCA / psi4 / xTB 深度真接入
- MultiWFN 真接入
- 商业云 HPC 真实接入（接口预留 + 本地 SLURM demo 已足够）
- PyPI / Homebrew / Docker / Plugin 打包发布

---

## 7. 关于 TADF（v3.0 降级为未来工作）

**v3.0 重要变更**：TADF 不再是毕设主线验证案例。

历史背景：v1.0 / v2.0 都把 TADF 流水线（4CzIPN / DMAC-DPS 等）作为标杆问题。v3.0 将这条线降级为**未来工作**，原因：

1. TADF kRISC 的实验值 vs 计算值常差 1-2 个数量级（计算化学领域公开难题），不适合作为本科毕设主验证
2. 验证 scope 缩小到"基础计算能力"后，3 个公开 benchmark（S22 / QUEST / 蒽）已足够
3. TADF 应用层论证如果做不深会被质疑，做深则超过本科毕设工作量

`docs/TADF_PIPELINE.md` 仍保留作为未来工作的参考。`benchmarks/tadf-literature/` 历史 anchor 数据保留但不进入毕设主验证。

---

## 8. 立即可做的下一步（v3.0 入口）

新会话从这里开始（按依赖排序）：

1. **MCP 跨客户端 demo 验证**（30 min）：把 `chem.const` 或 `chem.kb` 挂到 Codex 等 MCP 客户端，截图。**未跑通前不允许在论文 §1.3 贡献章节写相关 claim**。
2. **合并 worktree `objective-meitner-befa64` 的 8 个 commit** 回主线（含 TD-opt + MLJ + 鲸钛起步数据）。
3. **system_prompt.md 重写**：按 `docs/REFACTOR_PLAN.md` §1.1 重写，新增 Principle 0（labor-saving collaborator），改 §3 / §6 / §When to ask user，改 cheat-sheet 主路径走 Gaussian/BDF/MOMAP。
4. **`RecommendTool` 实现**（builtins.py 新增类）+ `confirmation.py` 第三 mode 扩展 + `~/.chemaster/policy.yaml` 加载 + Trajectory `decision_authority` tagging。
5. **Gaussian MCP 拆细**：当前只有 `parse_input` + 通用 `run`，需要拆出 `optimize / frequency / tddft / opt_excited_state / single_point`。
6. **BDF MCP 扩充**：当前只有 `soc`，需要加 `optimize / tddft`。
7. **MOMAP MCP 从零写**：speed / dynamics / TVCF 解析 + 与 Gaussian/BDF 数据流对接。
8. **HPC 平台 adapter 接口**：基于现有 paramiko SSH 层，加平台抽象 + `local_slurm` 占位 adapter。
9. **Textual TUI 完整版** + **本地 Web 前端最小版**（FastAPI + 简单 SPA）。
10. **3 公开 benchmark**（S22 / QUEST / 蒽）输入文件 + 跑通脚本 + 文献参考值对比。
11. **工程指标实验**：`docs/BENCHMARK_PROTOCOL.md` 协议先行，2-3 被试，注入故障，统计三指标。
12. **论文 §1-§5 + 附录撰写**（Markdown）。

每一步都先写 test 再写实现。每完成一步用 git commit。

**不要**：
- 不要重构现有 PDF 代码 —— 它在 `tools/pdf-structure-extract/`，是外挂工具。
- 不要让 Agent "自由发挥" 选基组/泛函 —— 必须经 `recommend` 让用户决策。
- 不要在 system prompt 里写公式 —— 公式只在 `chemaster.kb.formulas` Python 模块里。
- **不要把"MCP 跨客户端复用"等未验证的 claim 写进论文** —— 必须先跑通 demo。
- **不要把 TADF / AIE 应用层结果写进论文 §4 主验证** —— 这一类已降级为未来工作。

---

## 9. 用户偏好与约定（**记住，少返工**）

- 用户是**化学专业本科生**，这是毕业设计。**导师方向：基础化学，懂 Gaussian/BDF/MOMAP 等软件**——属于 REFACTOR_PLAN 里的"情形 A"，方案合适度风险消除。
- 用户**没有当前可用的 HPC 账号**（v3.0 修订）。商业云（并行/鸿之微）接入降级为"接口预留 + 本地 SLURM demo"，真实接入推到未来工作。
- 用户**没说要支持 Windows**，但 macOS + Linux 是必须。Windows 走 WSL2。
- 用户已经有 `chemaster/output/` 目录的 PDF 抽取产物 —— 不要清理。
- 用户的 PDF 抽取代码在根 `README.md` 里有说明 —— 不要覆盖那个 README，把项目对外介绍写在新的 `README.md`（如已有就保留改为附录或归档）。
- LLM API key 用户自带，**不要在仓库里硬编码任何 key**。
- 默认语言：中文为主（注释、文档、提交信息）；代码标识符英文。
- 提交信息格式：`<type>(<scope>): <subject>`，例：`feat(mcp/momap): add tvcf rate tool`。
- **核心比喻**：ChemMaster 之于计算化学家 = vibe coding 之于程序员。这条进论文 §1.1。

---

## 10. 文档索引

| 文档 | 何时读 |
|---|---|
| **本文件** (`AGENTS.md`) | 新会话第一个读 |
| [`README.md`](README.md) | 项目对外介绍 |
| [`docs/REFACTOR_PLAN.md`](docs/REFACTOR_PLAN.md) | **v3.0 决策清单，理解项目当前状态前必读** |
| [`docs/BENCHMARK_PROTOCOL.md`](docs/BENCHMARK_PROTOCOL.md) | 工程指标实验协议 |
| [`docs/HPC_PLATFORMS.md`](docs/HPC_PLATFORMS.md) | 商业云 HPC 调研记录 |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | 想知道整体阶段安排 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 写代码前理解架构 |
| [`docs/SETUP.md`](docs/SETUP.md) | 第一次搭环境 |
| [`docs/PITFALLS.md`](docs/PITFALLS.md) | 写每个 MCP/Skill 前必读 |
| [`docs/MCP_GUIDE.md`](docs/MCP_GUIDE.md) | 写 MCP server 时 |
| [`docs/SKILLS_GUIDE.md`](docs/SKILLS_GUIDE.md) | 写 Skill 时 |
| [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) | 写代码前 |
| [`docs/TADF_PIPELINE.md`](docs/TADF_PIPELINE.md) | 未来工作参考（v3.0 已不再是毕设主线） |
| [`docs/PACKAGING.md`](docs/PACKAGING.md) | 未来工作（毕设范围外） |

---

## 11. 当前状态快照（v3.0）

V2 架构已落地，v3.0 哲学修正进行中：

- ✅ Phase 0 仓库脚手架 + 设计文档
- ✅ Phase 1 工具链路打通：硬编码 H2O e2e
- ✅ **Phase 1.5 真 Codex tool-use Agent loop**（V2 核心里程碑）
  - `chemaster.agent.{types,llm_client,context,tool_registry,builtins,agent}`
  - `system_prompt.md` 化学专家 prompt（v3.0 待重写）
  - 22 工具（含 finish/ask_user/think + 7 计算 + KB 三件套 + viz + parse + io）
  - `chem.kb` MCP（`kb_search` / `list_skills` / `use_skill`）
  - Per-tool confirmation + audit log（`runs/<task_id>/confirmations.jsonl`）
  - CLI: `chemaster run / skills / kb / tools / mcps / --check-engines`
  - 测试：166 单元 + 6 集成 = 172 全绿
- 🚧 **v3.0 进行中**（本批次提交）：
  - AGENTS.md 同步至 v3.0（本次）
  - system_prompt.md 重写（按 REFACTOR_PLAN §1.1 §1.2）
  - RecommendTool + confirmation 第三 mode + 权限分级 + tagging
  - Gaussian MCP 拆细 / BDF 扩充 / MOMAP 从零写
  - HPC platform adapter + 异步化
  - Textual TUI / 本地 Web 前端
  - 3 公开 benchmark（S22 / QUEST / 蒽）+ 工程实验
  - 论文 §1-§5 撰写（Markdown）
- ⬜ Phase 2 接入 ANTHROPIC_API_KEY 跑真 Codex（用户保留）
- ⬜ 未来工作：TADF / AIE / ORCA / psi4 / xTB / MultiWFN 深度集成、商业云真实接入、打包发布

---

*文档版本：v3.0 (2026-05-05)。每次重大架构调整后更新本文档的 §0、§2、§3、§5、§7、§8、§9、§11。*
