# ARCHITECTURE — 系统架构详解

> 写代码前读这个。
>
> ⭐ **V2 已落地（2026-04-29）**：六层 → 五层；Skill 不再是架构层，移到 `kb/skills/` 由 `use_skill` 工具读取；旧 Planner/Executor 保留为兼容层，**主路径走 ChemAgent tool-use loop**。
>
> 最新简明视图见 [CLAUDE.md §2](../CLAUDE.md#2-架构总览)。本文档保留 V1 详细描述作为补充参考；其中 §3.4 (Skills 作为 L4) 与 §3.5 (Planner/Confirmation/Executor 三段式) 部分已用 V2 路径替代，新增模块见 `chemaster/agent/` 下的 `agent.py / types.py / llm_client.py / context.py / tool_registry.py / builtins.py / tool_loader.py`。

---

## 1. 设计目标

| 目标 | 反映在哪 |
|---|---|
| 关注点分离 | 六层结构，每层职责单一 |
| 类型安全 | MCP 层强 schema |
| 领域知识可由化学家直接编辑 | Skill 层为 Markdown |
| LLM 可替换 | Agent core 通过 SDK 抽象层 |
| 复现性 | runs/ 全产物 + 版本快照 |
| 错误自愈 | 每个 MCP 返回 warnings，每个 Skill 写恢复策略 |

---

## 2. 六层全景

```
┌──────────────────────────────────────────────────────────┐
│ L6  User Interface                                       │
│   一期 Textual TUI（chemaster CLI）                       │
│   二期 Web/Desktop 客户端（嵌入 3D 分子查看器）             │
├──────────────────────────────────────────────────────────┤
│ L5  Agent Core                                           │
│   Planner / ConfirmationLoop / Executor / Iterator /      │
│   KnowledgeRetriever                                      │
├──────────────────────────────────────────────────────────┤
│ L4  Skills                                               │
│   tadf-pipeline / opt-freq / tddft / soc / ts-search /    │
│   conformer / pes-scan / pka / dlpno-ccsdt / solvation   │
├──────────────────────────────────────────────────────────┤
│ L3  MCP Servers                                          │
│   chem.const / chem.io.ase / chem.calc.* / chem.parse.*  │
│   chem.viz / chem.hpc.slurm / chem.kb / chem.pdf          │
├──────────────────────────────────────────────────────────┤
│ L2  Engines                                              │
│   psi4 / ORCA / BDF / xTB / OpenMM / ASE / cclib /        │
│   RDKit / py3Dmol / Matplotlib / MultiWFN                 │
├──────────────────────────────────────────────────────────┤
│ L1  Knowledge Base                                        │
│   chemaster/kb/formulas/  确定性 Python 模块               │
│   chemaster/kb/rules/     YAML/Markdown，供 RAG            │
│   benchmarks/             测试集                          │
└──────────────────────────────────────────────────────────┘
```

---

## 3. 各层详解

### 3.1 L1 Knowledge Base

**两层分工**：

- `kb/formulas/` —— 确定性 Python 模块。Agent 不"知道"公式，但 *调用*：
  ```python
  from chemaster.kb.formulas.photophysics import krisc_marcus
  k = krisc_marcus(delta_est_eV, soc_meV, reorg_eV, T=298)
  ```
- `kb/rules/` —— 经验性规则，YAML / Markdown。供 RAG 检索：
  - `basis_sets.yaml`：每个基组的适用元素、典型用途、相对成本。
  - `functionals.yaml`：每个泛函的适用场景、已知失败模式、参考文献。
  - `convergence.yaml`：默认阈值与失败时的回退策略。
  - `workflows.yaml`：Skill 引用的工作流元信息。

**关键不变量**：浮点运算只在 formulas/ 内、由 Python 直接执行；rules/ 不含数学，只含建议性文本。

### 3.2 L2 Engines

外部软件，本项目不维护：

- 量子化学：psi4、ORCA、BDF、xTB
- 分子动力学：OpenMM、GROMACS（Phase 5+）
- 工具库：ASE（统一封装）、cclib（解析）、RDKit（化学信息学）、MultiWFN（波函数分析）
- 可视化：py3Dmol、Matplotlib、NGLView

每个 Engine 由对应的 L3 MCP 包装。

### 3.3 L3 MCP Servers

**职责**：把 Engine 暴露为类型化原子操作。

**约定**：

- 每个 MCP 是独立 Python 模块 `chemaster/mcp/<name>/`，含 `server.py` 和 `README.md`。
- 入参：JSON Schema 严格定义。
- 出参：`{ result: ..., warnings: [...], meta: { ... } }` 三段式。
- 物理量带 `unit` 字段；几何用 Å + 元素符号大写。
- 失败：永远不抛 exception 给 LLM；返回 `{ ok: false, error_code: ..., suggestion: ... }`。

**清单**：

| MCP | 主要工具 | Phase |
|---|---|---|
| `chem.const` | get_constant / convert_unit | 1 |
| `chem.io.ase` | smiles_to_xyz / xyz_to_mol / parse_geometry | 1 |
| `chem.calc.psi4` | single_point / optimize / frequency | 1 |
| `chem.calc.xtb` | optimize / vibrations / conformer_search | 1 |
| `chem.parse.cclib` | parse_output / extract_orbitals | 1 |
| `chem.viz` | plot_3d / plot_uv_vis / plot_ir / contact_sheet | 1 |
| `chem.kb` | search / cite | 2 |
| `chem.calc.orca` | single_point / optimize / frequency / tddft / dlpno_ccsdt | 2 |
| `chem.calc.bdf` | tddft / soc / casscf | 2 |
| `chem.analysis.multiwfn` | nto / aim / hirshfeld | 2 |
| `chem.hpc.slurm` | submit / status / fetch / cancel | 3 |
| `chem.pdf` | extract_structures (复用现有) | 5 |

详细 MCP 写法见 [`MCP_GUIDE.md`](MCP_GUIDE.md)。

### 3.4 L4 Skills

**职责**：教 Agent 如何用 MCP 解决一类问题。

**结构**：每个 skill 是 `chemaster/skills/<name>/SKILL.md`，正文 Markdown，含：

```markdown
---
name: opt-freq
description: 几何优化 + 频率确认的标准工作流
when_to_use: 当用户要"算 X 的能量"、"优化 X 的结构"、"找 X 的极小点"时
when_not_to_use: 找过渡态时（用 ts-search 而不是 opt-freq）
---

## 流程

1. 用 chem.calc.psi4.optimize 做几何优化（默认 method=B3LYP-D3(BJ), basis=def2-TZVP）。
2. 优化收敛后，用相同 (method, basis) 调 chem.calc.psi4.frequency。
3. 若有虚频：
   3a. 调 chem.io.ase.displace_along_mode（位移幅度 0.1 Bohr）。
   3b. 重新调 optimize，最多 3 轮。
4. 调 chem.parse.cclib.parse_output 提取 ZPE、热修正、最终能量。
5. 调 chem.viz.plot_3d 出 3D 结构图。
6. 输出 Markdown 报告。

## 常见失败

- SCF 不收敛 → 见 PITFALLS §2.4
- 优化卡死 → 切冗余内坐标，见 PITFALLS §2.5
- 对称性突跳 → 强制 c1，见 PITFALLS §2.6
```

详细 Skill 写法见 [`SKILLS_GUIDE.md`](SKILLS_GUIDE.md)。

### 3.5 L5 Agent Core

**模块**：`chemaster/agent/`

```
agent/
├── planner.py            # 出 Plan 对象
├── confirmation.py       # Plan-Confirm 交互
├── executor.py           # 执行 Plan
├── iterator.py           # benchmark 闭环
├── retriever.py          # RAG over kb/rules/
└── plan.py               # Plan 数据类
```

**核心数据流**：

```python
# 1. 用户输入
user_msg = "算 H2O 的能量"

# 2. Planner: LLM + RAG → Plan
plan = planner.create_plan(
    user_msg,
    skills=load_skills(),
    knowledge=retriever.search(user_msg),
)

# 3. Confirmation: TUI 渲染 Plan, 等用户
approved_plan = confirmation.run(plan, ui=tui)

# 4. Executor: 按 Plan 调 MCP
result = executor.run(approved_plan, mcps=load_mcps())

# 5. 报告
report = result.to_markdown()
```

**Plan 对象**（`agent/plan.py`）：

```python
@dataclass
class PlanStep:
    skill: str | None
    mcp_calls: list[McpCall]
    rationale: str
    alternatives: list[str]
    estimated_cost: Cost
    risks: list[str]

@dataclass
class Plan:
    task_id: str
    user_intent: str
    inferred_workflow: str
    target_system: System
    steps: list[PlanStep]
    total_estimate: Cost
    citations: list[Citation]
```

### 3.6 L6 User Interface

**Textual TUI 布局**：

```
┌──────────────────────────────────────────────────────────┐
│ ChemMaster 0.1.0  •  conn: anthropic/claude-4-6  • [/cmd]│
├──────────────────────────────┬───────────────────────────┤
│                              │ Active Tasks              │
│  > 算 H2O 的能量              │  • opt-freq: optimizing   │
│                              │    SCF iter 12/200        │
│  Agent 我建议这样做...         │                           │
│  [Plan 卡片]                  │ Recent runs               │
│                              │  • h2o-opt-001 ✓ 2 min ago│
│  [A]ccept [E]dit [R]eplan    │                           │
│                              │ Engines                   │
├──────────────────────────────┴───────────────────────────┤
│  /run /show /jobs /kb /skills /quit                      │
└──────────────────────────────────────────────────────────┘
```

**关键交互**：

- 主对话流（左大）。
- 任务面板（右上），实时进度。
- 底部命令行（斜杠命令）。
- Plan-Confirm 卡片以模态弹出，显式按键决策（不许 LLM 自动跳过）。

二期客户端：Tauri 或 Electron + React，原生嵌入 3D 分子查看器、轨道可视化、UV-Vis 图。

---

## 4. 关键流程

### 4.1 一次完整任务的生命周期

```
用户在 TUI 输入 prompt
   │
   ▼
Planner.create_plan(prompt)
   │ ├─ retriever.search(prompt) → 引用 KB
   │ ├─ 查找匹配 skill
   │ ├─ LLM 出 Plan 对象（含 cost / risk）
   │ └─ Planner 校验（成本爆炸警告等）
   ▼
ConfirmationLoop.run(plan)
   │ ├─ TUI 渲染卡片
   │ ├─ 用户 Accept / Edit / Replan
   │ └─ 用户编辑时再次校验"建议+纠偏"
   ▼
Executor.run(approved_plan)
   │ └─ for step in plan.steps:
   │      ├─ 加载 skill (如指定)
   │      ├─ skill 编排 mcp_calls
   │      ├─ for mcp_call in mcp_calls:
   │      │    ├─ mcp.invoke(args)
   │      │    ├─ 收 warnings
   │      │    └─ 出错按 skill 的恢复策略重试
   │      └─ 写入 runs/<task_id>/step_N/
   ▼
Reporter.summarize(runs/<task_id>/)
   │ └─ Markdown 报告 + 图 + 数据表
   ▼
TUI 展示结果链接 + 关键指标
```

### 4.2 复现机制

`runs/<task_id>/` 内必含：

```
runs/<task-id>/
├── meta.json              # 时间、Git commit、包版本、软件版本、随机种子
├── prompt.txt             # 用户原始输入
├── plan.json              # 完整 Plan 对象
├── step_01_optimize/
│   ├── input.psi4         # 输入文件
│   ├── output.log         # 软件原始输出
│   ├── parsed.json        # cclib 解析结果
│   ├── warnings.json
│   └── timing.json
├── step_02_frequency/
│   └── ...
├── figures/
│   ├── geometry.png
│   └── ir.png
└── report.md
```

3 个月后用 `chemaster replay runs/<task-id>` 完整重跑，输出应 bit-perfect。

### 4.3 错误恢复

每个 MCP 错误返回带 `error_code`：

```python
{
  "ok": false,
  "error_code": "SCF_NOT_CONVERGED",
  "details": {"final_residual": 1e-3, "max_iter_reached": true},
  "suggestion": "switch_guess_to_GWH",
  "warnings": [...]
}
```

Skill 内的恢复策略：

```markdown
## SCF 失败时

收到 error_code = SCF_NOT_CONVERGED 时，按顺序尝试：

1. 调 chem.calc.psi4.single_point with guess=GWH
2. 若仍失败：basis 降到 def2-SVP 算 → 用其密度作 guess 升回 def2-TZVP
3. 若仍失败：报告给用户，请手动决策
```

Executor 严格按 skill 写的策略执行，不允许 LLM 自由发挥。

---

## 5. 扩展点

### 5.1 加新 Engine

1. 在 `chemaster/mcp/calc_<name>/` 建目录。
2. 写 `server.py`：定义 tools。
3. 写 `README.md`：文档化。
4. 在 `kb/rules/functionals.yaml` 等加该软件的支持矩阵。
5. 在 `pyproject.toml` 的 `[project.entry-points."chemaster.mcps"]` 注册。

### 5.2 加新 Skill

1. 在 `chemaster/skills/<name>/SKILL.md` 写 Markdown。
2. frontmatter 写清楚 `when_to_use` / `when_not_to_use`。
3. 用 `chemaster skills test <name>` 跑 5+ 触发例 + 5+ 反例。
4. 加到 `kb/rules/workflows.yaml`。

### 5.3 加新 LLM 后端

`chemaster/agent/llm_client.py` 是 thin wrapper，已抽象 Anthropic / OpenAI / 本地 vLLM 三类。新增本地模型只需实现 `LLMClient` 接口。

---

## 6. 性能边界

- 单分子 < 50 原子，DFT/def2-TZVP：本地工作站 OK。
- 50-200 原子：必须 HPC。
- > 200 原子：考虑 xTB 或 ML 势能（Phase 5+）。
- 周期性体系：本毕设不做。

---

## 7. 监控指标

每次运行记录到 `runs/<task-id>/timing.json`：

| 指标 | 单位 | 用途 |
|---|---|---|
| llm_token_in / out | tokens | LLM 成本 |
| llm_calls | count | 请求数 |
| mcp_calls | count | 工具调用数 |
| engine_wall_clock | seconds | 软件耗时 |
| total_wall_clock | seconds | 端到端时间 |
| restart_count | count | 错误自愈次数 |

毕设论文用这些指标证明"真正好用"的硬指标。

---

## 8. 不做的事

- ❌ 不重写计算引擎（永远调外部软件）。
- ❌ 不做 Web 服务（Phase 6 之前不考虑）。
- ❌ 不做云端 SaaS（违背"本地优先"定位）。
- ❌ 不做付费功能（开源项目）。
- ❌ 不做实验自动化（与 Coscientist 划清界限）。
- ❌ 不做反应/合成路线规划（与 ChemCrow 划清界限）。

---

*文档版本：v1.0 (2026-04)。*
