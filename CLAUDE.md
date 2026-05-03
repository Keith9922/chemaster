# CLAUDE.md — ChemMaster Agent 协作指南

> 这是新会话接手本仓库时**第一个必读文档**。
> 读完本文件后，按 §10 的索引去 `docs/` 找细节，按 §8 的"立即可做的下一步"开始动手。
>
> 不要绕过本文档去推理项目目标 —— 这里写的是已经和用户对齐过的决策，**不要重新讨论**。

---

## 0. TL;DR（30 秒读完）

- **项目**：ChemMaster，**面向 TADF 发光体设计**的本地化计算化学 Agent，类 Claude Code 形态。
- **核心定位**：用户自然语言下达计算任务 → 真 LLM 驱动的 Agent 自主推理 → 影响外部状态时按工具弹确认 → 调用 psi4/ORCA/BDF/xTB → 自动出报告。
- **架构 V2（已落地）**：5 层 — TUI/CLI · Agent Loop（BaseAgent + ChemAgent，基于 Anthropic SDK + tool use）· Tools (MCP servers + 内建 finish/ask_user/think) · Engines · Knowledge Base（formulas/ Python + rules/ YAML + skills/ Markdown）。
- **关键变化**：**Skill 不再是架构层**，移到 `kb/skills/` 下，被 `use_skill` 工具按需读取（参考 EvoMaster）；**Confirmation 是 per-tool**（每个工具自带 `is_destructive` / `is_long_running` 标志），不再是中央 token 校验。
- **技术栈**：Python 3.11、Anthropic SDK + MCP、ASE、cclib、RDKit、psi4、xTB、ORCA、BDF、MultiWFN。
- **毕设标杆**：TADF 流水线（构象→opt→TDDFT→SOC→Marcus 算 kRISC）。
- **开发原则**：**不让 LLM 算数**（公式走 `chemaster.kb.formulas` Python 模块）；所有计算交给专业软件；MCP 错误带 `suggestion` 让 Agent 自主恢复；Trajectory 全持久化便于复现。

---

## 1. 项目愿景（why）

化学/材料/药物领域的研究者每天耗费大量时间在：写计算软件输入文件、提交 SLURM 任务、等待、解析输出、重启失败任务、整理图表。**ChemMaster 把这些重复劳动交给 Agent**，研究者只用自然语言下达意图。

我们对标的是 Rowan、Quantum Mobile、Schrödinger Live Design 这类商业云产品。**差异化**：

| 维度 | 商业云产品 | ChemMaster |
|---|---|---|
| 部署 | 云端 SaaS | 本地优先，分子结构不上传 |
| LLM | 厂商绑定 | BYO API（Anthropic / OpenAI / Qwen / DeepSeek 任选；可本地部署） |
| 计算 | 厂商云 | 用户本机或学校超算 |
| 源码 | 闭源 | 完全开源 |
| 国产化 | 弱 | 支持 BDF（北大刘文剑组）+ MultiWFN（田鹏） |

但"差异化"不等于"好用"。"好用"必须用硬指标承诺（见 §3）。

---

## 2. 架构总览

完整版本见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。这里放最关键的两个图。

### 2.1 五层结构 (V2)

```
┌──────────────────────────────────────────────────────────────┐
│ L5  TUI / CLI            chemaster run "<intent>"             │
│                          rich Panel for confirmations,        │
│                          summary, key_results table.          │
├──────────────────────────────────────────────────────────────┤
│ L4  Agent Loop           BaseAgent + ChemAgent                │
│                          Anthropic SDK + tool use             │
│                          Built-in: finish / ask_user / think  │
│                          Trajectory persisted to runs/        │
│                          Confirmation per-tool (callback)     │
├──────────────────────────────────────────────────────────────┤
│ L3  Tools (MCP servers)  calc_psi4 / calc_xtb / calc_orca /   │
│                          calc_bdf / io_ase / parse_cclib /    │
│                          viz / hpc_slurm / chem.kb / pdf      │
│                          每个 tool 自带 is_read_only /         │
│                          is_destructive / is_long_running     │
├──────────────────────────────────────────────────────────────┤
│ L2  Engines              psi4 / ORCA / BDF / xTB /            │
│                          ASE / cclib / RDKit / MultiWFN       │
├──────────────────────────────────────────────────────────────┤
│ L1  Knowledge Base       formulas/  Python 确定性公式          │
│                          rules/     YAML 规则                  │
│                          skills/    Markdown playbook（被     │
│                                      use_skill 工具读取）      │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 Skill 是工具，不是架构层（**V2 关键变化**）

- **MCP / Tools** = "Agent 能 *做* 什么"。每个工具是**类型化原子操作**：`calc_psi4_optimize(geometry_xyz, method, basis, ...) → {ok, result, warnings, meta}`。
- **Skills (kb/skills/)** = 给 Agent 阅读的**领域参考文档**。Agent 通过 `use_skill(name, action="get_info")` 工具按需读取。**不再做触发匹配 / 不再是 Planner 的必经路径**。

**正例**：
- ✅ `calc_psi4_optimize` 做一次优化、返回结果与 `suggestion`（如 SCF 失败建议 GWH 重试）。
- ✅ Agent 看到 `SCF_NOT_CONVERGED` + suggestion → 决定调 `kb_search("SCF convergence")` 或直接重试，无需固定 Skill 路由。
- ✅ `kb/skills/tadf-pipeline/SKILL.md` 是 Markdown，Agent 用 `use_skill("tadf-pipeline")` 加载。

**反例（V1 错位，已纠正）**：
- ❌ 旧：Planner 必须先选 Skill → Skill 编排 MCP → Executor 死板执行。
- ❌ 旧：Confirmation 是中央 token gate（`confirm_token` 拒执行）。V2 改为 per-tool 标志 + 用户回调。

---

## 3. "真正好用"的硬指标（毕设论文要验证）

| # | 指标 | 目标 | 验证方法 |
|---|---|---|---|
| 1 | 首次安装到第一个结果 | ≤ 30 分钟 | conda 装 chemaster env + `chemaster run` 跑 H2O |
| 2 | 端到端时间（H2O opt+freq）| < 5 min | `pytest tests/integration/test_h2o_e2e.py` |
| 3 | 错误自愈成功率 | ≥ 70% | 注入故障测 SCF/虚频；mock-LLM recovery 测试已覆盖 |
| 4 | 报告可直接进论文 SI | ≥ 80% | 5 个 anchor 分子产出对比文献值 |

V1 文档曾列七项硬指标（含 3 个月复现率、50% 人力对照实验）。V2 砍掉前者
（要等 3 个月才能验）和后者（要做对照实验，工作量与本课题创新点无关），
进入 ROADMAP 的"未来工作"。

---

## 4. 项目布局

```
chemaster/
├── CLAUDE.md                    # ★ 本文件，新会话第一个读
├── README.md                    # 项目对外介绍
├── pyproject.toml               # 包配置
├── .gitignore
├── .python-version              # 3.11
│
├── docs/                        # 设计文档
│   ├── ROADMAP.md               # 6 个阶段开发路线 + 打包发布
│   ├── ARCHITECTURE.md          # 架构详解
│   ├── CONVENTIONS.md           # 代码、命名、提交规范
│   ├── PITFALLS.md              # ★ 开发坑表（必读）
│   ├── PACKAGING.md             # 打包发布流程（PyPI / Homebrew / Docker / Claude Code Plugin）
│   ├── SETUP.md                 # 开发环境搭建
│   ├── SKILLS_GUIDE.md          # 怎么写 skill
│   ├── MCP_GUIDE.md             # 怎么写 MCP server
│   └── TADF_PIPELINE.md         # 标杆问题详解
│
├── chemaster/                   # Python 包根
│   ├── agent/                   # V2 真 tool-use Agent loop
│   │   ├── agent.py             # ChemAgent (BaseAgent + Anthropic SDK loop)
│   │   ├── llm_client.py        # AnthropicLLM / OpenAICompatLLM / Qwen / DeepSeek / MiniMax / Mock
│   │   ├── tool_registry.py     # ToolSpec, build_default_registry()
│   │   ├── builtins.py          # finish / ask_user / think
│   │   ├── context.py           # session state, runs/<task_id>/ persistence
│   │   ├── confirmation.py      # per-tool confirm callback (NOT central token)
│   │   ├── trajectory.py        # full audit log (msgs + tool calls + confirms)
│   │   ├── reporter.py          # auto runs/<task_id>/report.md
│   │   ├── system_prompt.md     # chemistry-expert system prompt
│   │   └── (legacy: planner.py / executor.py kept as compat shims)
│   ├── mcp/                     # 自研 MCP servers
│   │   ├── const/               # 物理常数与单位换算
│   │   ├── io_ase/              # 结构 IO + lookup_by_name
│   │   ├── calc_psi4/           # single_point / optimize / frequency / tddft
│   │   │                        # / optimize_excited_state (TD-opt, NEW)
│   │   ├── calc_orca/           # subprocess wrapper, full keyword passthrough
│   │   ├── calc_bdf/            # SOC (X2C-TDA) skeleton; needs $BDFHOME
│   │   ├── calc_xtb/            # xtb subprocess
│   │   ├── calc_gaussian/       # parse .com/.gjf, run g16/g09
│   │   ├── parse_cclib/         # 输出解析
│   │   ├── analysis_multiwfn/   # NTO 分析（菜单式 CLI piped）
│   │   ├── viz/                 # 出图
│   │   ├── hpc_slurm/           # paramiko SSH submit/status/fetch
│   │   ├── kb/                  # use_skill / list_skills / kb_search
│   │   └── pdf/                 # wrap tools/pdf-structure-extract/
│   ├── kb/
│   │   ├── formulas/            # 确定性 Python 模块（LLM 不算数）
│   │   │   ├── constants.py / units.py / thermo.py / kinetics.py
│   │   │   └── photophysics.py  # Marcus / MLJ / Strickler-Berg / Einstein-A
│   │   ├── rules/               # YAML（basis_sets, functionals, convergence, workflows）
│   │   └── skills/              # ★ Markdown playbook（被 use_skill 工具读取）
│   │       ├── opt-freq/ tddft/ soc/ ts-search/ conformer/ pes-scan/
│   │       ├── tadf-pipeline/   # ★ 毕设标杆
│   │       └── pka/ dlpno-ccsdt/ solvation/
│   ├── tui/                     # Textual TUI（opt-in via --tui flag）
│   └── cli.py                   # chemaster init / run / show / replay / skills / mcps
│
├── tools/                       # 内嵌工具（非 Python 包）
│   └── pdf-structure-extract/
│
├── benchmarks/                  # ★ 论文证据基地（不在 .gitignore）
│   ├── REPORT_v0.2.0a2.md       # 当前批次综合报告
│   ├── tadf-literature/         # 4CzIPN / DMAC-BP / DMAC-DPS anchors
│   ├── momap-jingti/            # 师姐 jingti C24H8F8I4N2 + STATUS.md
│   └── hcho-pipeline-2026-05-03/  # HCHO 端到端结果存档
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

### 5.3 Skill + MCP 边界不许混

见 §2.2。Skill 是 Markdown 文档（`kb/skills/*.md`），被 `use_skill` 工具按需读取，不写 psi4 输入文件字符串；MCP 是类型化原子操作，不嵌工作流逻辑。

### 5.4 Per-tool confirmation（V2）

每个 MCP tool 有 `is_destructive` / `is_long_running` 标志位（在 `ToolSpec` 里声明）；Agent 在调用前触发用户回调（`chemaster.agent.confirmation.ConfirmationCallback`），用户 A/E/R/Q 决策。**不再有中央 token 校验**（V1 的 HMAC `confirm_token` 已废）。所有确认事件写入 `runs/<task_id>/confirmations.jsonl` 留痕。

### 5.5 单位带类型

所有物理量在 MCP 边界用 `pint.Quantity` 或带 `unit` 字段的 dict 传递，不裸传 float。Hartree↔kcal/mol 这类换算每犯一次都是论文里的笑话。

### 5.6 复现优先

每个任务的 `runs/<task-id>/` 必须包含：原始用户 prompt、Plan 对象、生成的输入文件、所有命令、stdout/stderr、解析后的结果、版本信息（包+软件+commit）、随机种子。3 个月后重跑必须 bit-perfect。

### 5.7 错误是常态，自愈是默认

SCF 不收敛、虚频、几何卡死、内存爆、磁盘满 —— 这些不是异常分支，是正常工作流的一部分。每个 MCP 都要返回 `warnings` 字段，每个 skill 都要写"看到 X 该怎么办"。详见 [`docs/PITFALLS.md`](docs/PITFALLS.md)。

### 5.8 一切可测试

每个 MCP 配 unit test（mock 计算软件）+ integration test（真跑一个 10 秒能完的小体系）。Skill 用录像式测试（给定输入，校验 Agent 决策路径）。CI 跑 unit；integration 在本地或 release 前跑。

---

## 6. 开发阶段（V2 修订版，详见 [`docs/ROADMAP.md`](docs/ROADMAP.md) 顶部 V2 状态段）

| Phase | 状态 | 内容 |
|---|---|---|
| 0 | ✅ | 仓库脚手架 + 设计文档 |
| 1 | ✅ | 工具链路打通（硬编码 H2O e2e） |
| **1.5** | ✅ | **真 Claude tool-use Agent loop** (V2 核心，0.2.0a1) |
| 2 | ✅ | 多 LLM provider（Anthropic + OpenAI-compat + Qwen + DeepSeek + MiniMax） |
| 3 | 🔧 | TADF 流水线 anchor 分子（HCHO ✅、jingti S0 SP ✅、jingti TDDFT 进行中、4CzIPN/DMAC-* 待跑） |
| 4 | 🔧 | 真实引擎接入：psi4 全 ✅、Gaussian parser ✅、ORCA/BDF/MultiWFN 骨架 ⬜ |
| 5 | 🔧 | HPC 异步集成（`chem.hpc_slurm` 已 paramiko ✅，需真集群联调） |
| 6 | ⬜ | 文档 + 论文 |
| 7 | ⬜ | PyPI 发布（多渠道发布推到未来工作） |

**已砍掉**（推到论文"未来工作"章节）：3 个月复现率验证、50% 人力对照实验、conda-forge / Homebrew / Docker / Claude Code Plugin 多渠道发布、benchmark Iterator 闭环作为毕设核心。

---

## 7. 标杆问题：TADF 发光体设计

详见 [`docs/TADF_PIPELINE.md`](docs/TADF_PIPELINE.md)。

**为什么选 TADF**：

- OLED 领域热点（你已有 P=O / N-MR-TADF 论文素材）。
- 流水线天然多软件协作：xTB（构象）→ ORCA/BDF（TDDFT）→ BDF（SOC）→ Marcus（kRISC）→ MultiWFN（NTO 分析）。
- 复用现有 PDF 抽取：论文 → 分子 → 复算 → 对比，叙事完整。
- 验证标准清晰：S1/T1 能隙、振子强度、kRISC 都有可对比的实验/理论值。

**核心 anchor cases**（Phase 4）：4CzIPN、DMAC-DPS、P=O / N-MR 系列共 5-10 个分子。

---

## 8. 立即可做的下一步（新会话从这里开始）

V2 架构 + Phase 2 LLM 矩阵 + Phase 3 起步（HCHO 完成、jingti S0/TDDFT 进行中）已落地。当前最关键的开放工作，按性价比排：

1. **跑完 jingti 端到端 + 论文 Section 数据**（性价比最高）：jingti vertical TDDFT 已经在跑；接着做 S1/T1 TD-opt（用 `optimize_excited_state`）→ 算 ΔE_ST 的 vert / adiab 两套数→ 用 `k_mlj` 算 k_ISC，对比师姐 MOMAP 1.17e9。预计本地 6-12 小时；产出 `benchmarks/REPORT_v0.2.0a3.md`。
2. **真 SOC 接入（k_ISC 算硬数）**：当前 MLJ 用文献典型 SOC=5.56 cm⁻¹ 当 input。让 ChemMaster 自己算 SOC：(a) ORCA `RI-SOMF` 包装到 `calc_orca` MCP，对小体系跑通；(b) 等用户拿到 BDF 后接 `calc_bdf.tddft_soc`。
3. **MOMAP-grade k_F (Franck-Condon FCWD)**：当前 `kr_einstein_from_dipole` / `kf_strickler_berg` 是垂直近似；想要全振动结构的 FCWD，需 normal-mode displacement → Huang-Rhys 全集 → FC 积分。1-2 周工作。
4. **NACME 解析 / k_IC**：师姐 k_IC = 6.12e11 s⁻¹ 没法不读 NACME 重现。Gaussian / ORCA NACME parser → `kic_marcus(nacme)` 已经有公式。3-5 天。
5. **更多 anchor 分子**：4CzIPN (76 atoms)、DMAC-DPS / DMAC-BP (82-83 atoms) — 需要 HPC 才现实，等 #1 把 jingti 跑漂亮再说。

每一步都先写 test 再写实现。每完成一步用 git commit。

**不要**：
- 不要重构现有 PDF 代码 —— 它在 `tools/pdf-structure-extract/`，是外挂工具，未来通过 `chem.pdf` MCP 集成。
- 不要让 Agent "自由发挥" 选基组/泛函 —— 必须先调 `kb_search` 或 `use_skill` 拿建议。
- 不要在 system prompt 里写公式 —— 公式只在 `chemaster.kb.formulas` Python 模块里。
- 不要把 benchmark 结果写进 `runs/`（gitignored），要写进 `benchmarks/<task>-<date>/`，论文 Section 才能引。

---

## 9. 用户偏好与约定（**记住，少返工**）

- 用户是**化学专业本科生**，这是毕业设计。
- 用户**有学校超算账号**（已确认），但 Phase 3 才用，前期本地为主。
- 用户**没说要支持 Windows**，但 macOS + Linux 是必须。Windows 走 WSL2。
- 用户已经有 `chemaster/output/` 目录的 PDF 抽取产物 —— 不要清理。
- 用户的 PDF 抽取代码在根 `README.md` 里有说明 —— 不要覆盖那个 README，把项目对外介绍写在新的 `README.md`（如已有就保留改为附录或归档）。
- LLM API key 用户自带，**不要在仓库里硬编码任何 key**。
- 默认语言：中文为主（注释、文档、提交信息）；代码标识符英文。
- 提交信息格式：`<type>(<scope>): <subject>`，例：`feat(mcp/psi4): add optimize tool`。

---

## 10. 文档索引

| 文档 | 何时读 |
|---|---|
| **本文件** (`CLAUDE.md`) | 新会话第一个读 |
| [`README.md`](README.md) | 项目对外介绍（用户、贡献者读） |
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | 一页用户操作手册（新用户跑通 H2O / 苯 / TADF anchor） |
| [`docs/V2_RELEASE_NOTES.md`](docs/V2_RELEASE_NOTES.md) | V2 架构详解（5 层、tool-use loop、per-tool confirm） |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | 想知道整体阶段安排（顶部有 V2 状态段） |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 写代码前理解 5 层架构 |
| [`docs/SETUP.md`](docs/SETUP.md) | 第一次搭环境 |
| [`docs/PITFALLS.md`](docs/PITFALLS.md) | **写每个 MCP/Skill 前必读** |
| [`docs/PACKAGING.md`](docs/PACKAGING.md) | 发布前 |
| [`docs/MCP_GUIDE.md`](docs/MCP_GUIDE.md) | 写 MCP server 时 |
| [`docs/SKILLS_GUIDE.md`](docs/SKILLS_GUIDE.md) | 写 Skill markdown 时 |
| [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) | 写代码前 |
| [`docs/TADF_PIPELINE.md`](docs/TADF_PIPELINE.md) | 写 TADF skill 时 |
| [`benchmarks/REPORT_v0.2.0a2.md`](benchmarks/REPORT_v0.2.0a2.md) | **本批次（HCHO + jingti + MLJ）综合证据报告，论文 Section 直接引** |
| [`benchmarks/momap-jingti/STATUS.md`](benchmarks/momap-jingti/STATUS.md) | 师姐 jingti 复现进度（已合 → 待办对照） |
| [`docs/KICKOFF.md`](docs/KICKOFF.md) | **开新会话前给模型抄的 prompt 模板** |

---

## 11. 当前状态快照（2026-05-03）

V2 架构 + Phase 2 LLM 矩阵已落地，Phase 3 TADF 流水线进行中（参见 [CHANGELOG.md](CHANGELOG.md) 0.2.0a1/a2 + [`benchmarks/REPORT_v0.2.0a2.md`](benchmarks/REPORT_v0.2.0a2.md)）：

- ✅ Phase 0 仓库脚手架 + 设计文档
- ✅ Phase 1 工具链路打通（硬编码 H2O e2e，commit 9bbe51e）
- ✅ **Phase 1.5 真 Claude tool-use Agent loop**（V2 核心，commit f6de8f9 / 0.2.0a1）
- ✅ Phase 2 LLM provider 矩阵：Anthropic + OpenAI-compat + Qwen + DeepSeek + MiniMax
- ✅ Phase 3 起步：HCHO 端到端 (GS opt + freq + vertical TDDFT + S1/T1 TD-opt) ✓ 2.5 min
- 🔧 Phase 3 进行中：jingti vertical TDDFT 后台跑（46 atoms, 4×I）
- ✅ **Phase 4 (psi4)**：S0 SP / opt / freq / TDDFT / **TD-opt（commit 2b19e6a, NEW）** 全跑通真实分子
- ✅ **Phase 4 (rate constants)**：MLJ k_mlj 公式（commit cd0e5d3, NEW）—— 师姐 jingti k_ISC 1.17e9 复现到 1 量级内
- ⬜ Phase 4 (其他引擎)：ORCA / BDF / MultiWFN MCP 骨架在，缺真集群跑
- ⬜ Phase 5 HPC: `chem.hpc_slurm` paramiko 已实现，缺真集群联调
- 🔧 工具数：32 → **33 MCPs**；测试：229 → **245 unit + 3 integration**（全绿）

下一步重点见 §8。

---

*文档版本：v2.1 (2026-05-03)。每次重大架构调整或 Phase 状态变化后更新本文档的 §2、§3、§5、§6、§11。*
