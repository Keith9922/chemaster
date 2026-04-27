# CLAUDE.md — ChemMaster Agent 协作指南

> 这是新会话接手本仓库时**第一个必读文档**。
> 读完本文件后，按 §10 的索引去 `docs/` 找细节，按 §8 的"立即可做的下一步"开始动手。
>
> 不要绕过本文档去推理项目目标 —— 这里写的是已经和用户对齐过的决策，**不要重新讨论**。

---

## 0. TL;DR（30 秒读完）

- **项目**：ChemMaster，一个**面向 TADF 发光体设计**的本地化计算化学 Agent，类 Claude Code 形态的 TUI。
- **核心定位**：自然语言下达计算任务 → Agent 规划 → 用户确认 → 调用 psi4/ORCA/BDF/xTB → 自动出报告 → 必要时迭代。
- **架构**：Agent Core + **Skill 层（方法论）+ MCP 层（类型化原子操作）** + 计算引擎 + 知识库。
- **技术栈**：Python 3.11、Claude Agent SDK（Python）、Textual（TUI）、ASE、cclib、RDKit、psi4、xTB、ORCA、BDF、MultiWFN。
- **毕设标杆**：TADF 流水线（构象→opt→TDDFT→SOC→Marcus 算 kRISC）+ 真人对照实验。
- **开发原则**：**不让 LLM 算数**；所有计算交给专业软件；公式走代码、经验走 RAG；Plan-Confirm-Execute 三段式。

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

完整版本见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。这里只放最关键的两个图。

### 2.1 六层结构

```
┌─────────────────────────────────────────────────────────┐
│ L6  TUI (Textual)        →  二期：Web/Desktop 客户端       │
├─────────────────────────────────────────────────────────┤
│ L5  Agent Core           Planner / Confirmation /        │
│                          Executor / Iterator / Retriever  │
├─────────────────────────────────────────────────────────┤
│ L4  Skills (Markdown)    方法论 / 工作流 / 领域知识         │
│                          tadf-pipeline / opt-freq / ...   │
├─────────────────────────────────────────────────────────┤
│ L3  MCP Servers          类型化原子操作                    │
│                          chem.calc.* / chem.parse.cclib /│
│                          chem.viz / chem.hpc.slurm / ... │
├─────────────────────────────────────────────────────────┤
│ L2  Engines              psi4 / ORCA / BDF / xTB /        │
│                          ASE / cclib / RDKit / MultiWFN   │
├─────────────────────────────────────────────────────────┤
│ L1  Knowledge Base       公式库（确定性 Python）+ 规则库   │
│                          (YAML/Markdown，供 RAG)           │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Skill ↔ MCP 分工（**重点，不要搞错**）

- **MCP** = "Agent 能 *做* 什么"。每个工具是**类型化原子操作**，参数清晰、行为单一。例：`chem.calc.psi4.optimize(geom, method, basis) → {opt_geom, energy, converged}`。
- **Skill** = "Agent 该 *如何* 处理一类问题"。Markdown 文档教 Agent：用哪个工具、参数怎么定、看到什么信号要怎么应对、什么时候停。

**反例（不要这样做）**：
- ❌ 把"opt 失败就沿虚频模式位移重启"塞进 MCP（行为耦合，参数爆炸）。
- ❌ 让 Skill 自己拼 psi4 输入文件字符串（失去类型安全）。

**正例**：
- ✅ MCP `chem.calc.psi4.optimize` 只做一次优化、报告结果与告警。
- ✅ Skill `opt-freq` 教 Agent："先 optimize → 再 frequency → 若有虚频，调用 `chem.io.ase.displace_along_mode` 然后重启 optimize"。

---

## 3. "真正好用"的七项硬指标（**毕设论文要逐项验证**）

| # | 指标 | 目标 | 验证方法 |
|---|---|---|---|
| 1 | 首次安装到第一个结果 | ≤ 30 分钟 | 招新手计时 |
| 2 | 新手不读手册跑通 H2O | ✓ | 招新手观察 |
| 3 | 三个月后同输入复现率 | 100% | 保留 runs/ 全部产物，3 个月后重跑 |
| 4 | 离线核心功能 | ✓ | 拔网线测试（除 LLM API） |
| 5 | 错误自愈率 | ≥ 70% | 注入故障测 SCF/虚频/几何卡死 |
| 6 | 报告可直接进论文 SI | ≥ 90% | 化学专业同学盲评 |
| 7 | 相对手工节省人力 | ≥ 50% | 真人对照实验（见 §6 Phase 4.3） |

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
│   ├── agent/                   # Planner / Confirmation / Executor / Iterator
│   ├── mcp/                     # 自研 MCP servers
│   │   ├── const/               # 物理常数与单位换算（先做，最简单）
│   │   ├── io_ase/              # 结构 IO
│   │   ├── calc_psi4/           # psi4 包装
│   │   ├── calc_orca/
│   │   ├── calc_bdf/
│   │   ├── calc_xtb/
│   │   ├── parse_cclib/         # 输出解析
│   │   ├── analysis_multiwfn/   # 波函数分析
│   │   ├── viz/                 # 出图
│   │   ├── hpc_slurm/           # SLURM 提交与监控
│   │   ├── kb/                  # RAG 检索
│   │   └── pdf/                 # 复用现有 PDF 抽取
│   ├── skills/                  # ★ Skill 库（Markdown 为主）
│   │   ├── opt-freq/SKILL.md
│   │   ├── tddft/SKILL.md
│   │   ├── soc/SKILL.md
│   │   ├── ts-search/SKILL.md
│   │   ├── conformer/SKILL.md
│   │   ├── pes-scan/SKILL.md
│   │   ├── tadf-pipeline/SKILL.md     # ★ 毕设标杆
│   │   ├── pka/SKILL.md
│   │   ├── dlpno-ccsdt/SKILL.md
│   │   └── solvation/SKILL.md
│   ├── kb/
│   │   ├── formulas/                  # 确定性 Python 模块
│   │   │   ├── constants.py
│   │   │   ├── units.py
│   │   │   ├── thermo.py
│   │   │   ├── kinetics.py
│   │   │   └── photophysics.py        # Marcus、kRISC、kF
│   │   └── rules/                     # YAML/Markdown，供 RAG
│   │       ├── basis_sets.yaml
│   │       ├── functionals.yaml
│   │       ├── convergence.yaml
│   │       └── workflows.yaml
│   ├── tui/                     # Textual TUI
│   │   ├── app.py               # 入口
│   │   └── widgets/
│   └── cli.py                   # CLI 入口（python -m chemaster ...）
│
├── tools/                       # 内嵌工具（非 Python 包）
│   └── pdf-structure-extract/   # 现有 PDF 工作（保留并被 chem.pdf MCP 调用）
│
├── benchmarks/                  # 测试集
│   ├── tadf-literature/         # 标杆 TADF 分子集
│   └── gmtkn55-subset/          # 通用精度 benchmark
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

见 §2.2。Skill 不写 psi4 输入文件字符串；MCP 不嵌工作流逻辑。

### 5.4 Plan-Confirm-Execute 三段式

任何会改变文件系统、提交 HPC、或耗时 > 30s 的操作，**必须先出 Plan 让用户确认**。这条对 Agent 自己也适用 —— 在动用户已有代码前先问。

### 5.5 单位带类型

所有物理量在 MCP 边界用 `pint.Quantity` 或带 `unit` 字段的 dict 传递，不裸传 float。Hartree↔kcal/mol 这类换算每犯一次都是论文里的笑话。

### 5.6 复现优先

每个任务的 `runs/<task-id>/` 必须包含：原始用户 prompt、Plan 对象、生成的输入文件、所有命令、stdout/stderr、解析后的结果、版本信息（包+软件+commit）、随机种子。3 个月后重跑必须 bit-perfect。

### 5.7 错误是常态，自愈是默认

SCF 不收敛、虚频、几何卡死、内存爆、磁盘满 —— 这些不是异常分支，是正常工作流的一部分。每个 MCP 都要返回 `warnings` 字段，每个 skill 都要写"看到 X 该怎么办"。详见 [`docs/PITFALLS.md`](docs/PITFALLS.md)。

### 5.8 一切可测试

每个 MCP 配 unit test（mock 计算软件）+ integration test（真跑一个 10 秒能完的小体系）。Skill 用录像式测试（给定输入，校验 Agent 决策路径）。CI 跑 unit；integration 在本地或 release 前跑。

---

## 6. 开发阶段（详见 [`docs/ROADMAP.md`](docs/ROADMAP.md)）

| Phase | 内容 | 周数 | 验收 |
|---|---|---|---|
| 0 | 仓库重构 + 脚手架 + TUI 骨架 | 1 | `chemaster` 命令能进 REPL |
| 1 | MVP 闭环：H2O opt+freq | 4 | 终端输入"算 H2O 的能量"5 分钟出报告 |
| 2 | 知识库 + 智能决策 + 建议+纠偏 | 4 | 用户选 CCSD(T)/aug-cc-pVTZ 算苯环 → Agent 主动警告 |
| 3 | HPC 集成（学校超算） | 3 | 提交 30 原子任务到 SLURM 自动拉回 |
| 4 | TADF 流水线 + benchmark + 真人对照 | 5 | 5-10 个 TADF 分子误差合格；人力节省 ≥50% |
| 5 | 扩展（ORCA/BDF/MultiWFN/PDF→复算 demo） | 2-4 | "读论文-自动复算"端到端 demo |
| 6 | 文档 + 论文 | 1 | 初稿完成 |
| 7 | **打包发布**（PyPI / Homebrew / Docker / Plugin） | 1-2 | 详见 [`docs/PACKAGING.md`](docs/PACKAGING.md) |

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

按依赖顺序：

1. **读** `docs/SETUP.md`，按里面的步骤搭好开发环境（conda + psi4 + xTB + Claude Agent SDK + Textual）。
2. **读** `docs/PITFALLS.md` 一遍 —— 不读这个会反复踩坑。
3. **读** `docs/MCP_GUIDE.md` —— 学怎么写第一个 MCP。
4. **写** `chemaster/mcp/const/server.py` —— 最简单的 MCP，物理常数 + 单位换算。完成后用 `pytest tests/unit/test_const.py` 验证。
5. **写** `chemaster/mcp/io_ase/server.py` —— SMILES → 3D 结构、xyz↔mol 互转。
6. **写** `chemaster/mcp/calc_psi4/server.py` —— `single_point` / `optimize` / `frequency` 三个原子操作。
7. **写** `chemaster/mcp/parse_cclib/server.py` —— 输出解析。
8. **写** `chemaster/agent/` 三段式骨架（先硬编码 H2O 案例，跑通端到端）。
9. **写** `chemaster/tui/app.py` —— Textual 最简对话流。
10. 跑通"用户输入 → Plan → Confirm → Execute → 报告"的 H2O 闭环。

每一步都先写 test 再写实现。每完成一步用 git commit。

**不要**：
- 不要一上来重构现有 PDF 代码 —— 先把它当外挂工具，等 MVP 跑通再考虑迁移到 `tools/`。
- 不要追求一开始就支持 ORCA/BDF —— Phase 1 只用 psi4 + xTB。
- 不要写 Web UI —— 这是二期。
- 不要让 Agent "自由发挥" 选基组/泛函 —— 必须经过 KB 检索 + 规则校验。

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
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | 想知道整体阶段安排 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 写代码前理解六层架构 |
| [`docs/SETUP.md`](docs/SETUP.md) | 第一次搭环境 |
| [`docs/PITFALLS.md`](docs/PITFALLS.md) | **写每个 MCP/Skill 前必读** |
| [`docs/PACKAGING.md`](docs/PACKAGING.md) | Phase 7 发布前 |
| [`docs/MCP_GUIDE.md`](docs/MCP_GUIDE.md) | 写 MCP server 时 |
| [`docs/SKILLS_GUIDE.md`](docs/SKILLS_GUIDE.md) | 写 Skill 时 |
| [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) | 写代码前 |
| [`docs/TADF_PIPELINE.md`](docs/TADF_PIPELINE.md) | 写 TADF skill 时 |
| [`docs/KICKOFF.md`](docs/KICKOFF.md) | **开新会话前给模型抄的 prompt 模板** |

---

## 11. 当前状态快照

- ✅ 仓库目录骨架已建好（截至本文件版本）
- ✅ 设计文档完整（docs/ 下所有 *.md）
- ✅ Python 包骨架（`chemaster/__init__.py` 等占位）
- ⬜ 第一个 MCP server (`chem.const`) ← **下个会话从这里开始**
- ⬜ 第一个 Skill (`opt-freq`)
- ⬜ TUI 入口
- ⬜ MVP 闭环（H2O）

---

*文档版本：v1.0 (2026-04)。每次重大架构调整后更新本文档的 §2、§3、§5、§11。*
