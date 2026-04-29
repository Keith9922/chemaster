# ChemMaster

> **Claude Code for computational chemistry — local, open, scriptable.**
>
> 用自然语言下达计算任务，真 LLM 驱动的 Agent 自主推理 → 调用 psi4 / xTB / ORCA / BDF → 自动出报告。
>
> 标杆场景：**TADF 发光体设计**（OLED 第三代发光材料的全流程计算筛选）。

---

## 特性

- **真 LLM tool-use loop** — 基于 Anthropic SDK 的 ChemAgent，22 个工具自动加载（MCP 适配 + 内建 finish/ask_user/think），错误自愈、Trajectory 全持久化便于复现。
- **本地优先** — 分子结构不上传；除 LLM API 全部离线运行。
- **多模型支持（BYO LLM）** — Anthropic 直连，**MiniMax M2.7（已实测跑通）**，OpenAI-compatible（Qwen / DeepSeek / vLLM）接口预留。
- **多软件统一接口** — psi4 / xTB（已实装）、ORCA / BDF / MultiWFN（接口占位）通过同一套自然语言命令调用。
- **Per-tool 安全确认** — 每个工具自带 `is_destructive` / `is_long_running` 标志；UI 弹确认对话框；审计日志写到 `runs/<task_id>/confirmations.jsonl`。
- **可检索的领域知识库** — `kb/rules/*.yaml` 基组/泛函规则、`kb/skills/*/SKILL.md` 工作流文档，由 Agent 通过 `kb_search` / `use_skill` 工具按需读取。
- **可重复** — 每个任务的完整对话、工具结果、版本快照写到 `runs/<task_id>/`，3 个月后可 replay。

---

## 快速开始

### 安装（手动）

```bash
# 1. conda 环境（psi4 + xtb + RDKit + ASE + cclib 全部一键装）
conda create -n chemaster python=3.11 -y
conda activate chemaster
conda install -c conda-forge psi4 xtb cclib rdkit ase pyyaml -y
pip install anthropic mcp click rich pint pydantic platformdirs

# 2. 装 chemaster 自身（开发模式）
git clone https://github.com/<user>/chemaster
cd chemaster
pip install -e ".[dev]"

# 3. 配 LLM API key（任选其一）
export ANTHROPIC_API_KEY=sk-ant-...        # 用 Claude
export MINIMAX_API_KEY=sk-cp-...           # 用 MiniMax M2.7（国产，已实测跑通）

# 4. 检查环境
chemaster --check-engines
```

> 一键安装脚本 / PyPI / Homebrew / Docker 镜像列在路线图（Phase 7），尚未发布。

---

## 用法

### 一行命令跑一个真任务

```bash
$ chemaster run "Compute the energy of water"

╭───────────── ChemMaster Agent ─────────────╮
│ Compute the energy of water                 │
│ provider=minimax  model=MiniMax-M2.7  tools=22 │
╰─────────────────────────────────────────────╯

[step 1] io_lookup_by_name(name="water")
  → xyz: 3 atoms, formula H2O
[step 2] calc_psi4_optimize(method="B3LYP-D3(BJ)", basis="def2-SVP", ...)
  → optimized; final_energy = -76.3589 Hartree
[step 3] calc_psi4_frequency(...)
  → 3 modes, n_imaginary = 0, ZPE = 0.0212 Hartree
[step 4] finish

╭──────── ChemMaster — Run Summary ─────────╮
│ Status:    completed                       │
│ Steps:     4                               │
│ Task ID:   task-7c2b                       │
│ Trajectory: runs/task-7c2b/trajectory.json │
╰────────────────────────────────────────────╯

╭─────────────── Agent summary ──────────────────╮
│ Computed water (H₂O) at B3LYP-D3(BJ)/def2-SVP. │
│ Electronic energy: -76.3589 Hartree.            │
│ ZPE: 0.0212 Hartree.                            │
│ Frequencies: 1639, 3792, 3887 cm⁻¹.            │
│ No imaginary frequencies → confirmed minimum.   │
╰─────────────────────────────────────────────────╯
```

### 其他命令

```bash
chemaster run "Optimize methane" --no-confirm     # 跳过交互式确认（脚本模式）
chemaster --check-engines                          # 看哪些计算软件可用
chemaster tools list                               # Agent 能调的 22 个工具
chemaster skills list                              # 可用的 playbook（opt-freq / tadf-pipeline / …）
chemaster skills show tadf-pipeline                # 看某个 skill 的完整内容
chemaster kb search "basis for transition metals"  # 检索知识库
```

---

## 架构（V2）

5 层 + Skill 是工具不是架构层（参考 EvoMaster / Claude Code 设计）：

```
┌─────────────────────────────────────────────────────────────┐
│ L5  CLI / TUI       chemaster run "<intent>"                 │
├─────────────────────────────────────────────────────────────┤
│ L4  Agent Loop      ChemAgent (Anthropic SDK + tool use)     │
│                     finish / ask_user / think 内建工具       │
│                     Trajectory 持久化 + per-tool confirm     │
├─────────────────────────────────────────────────────────────┤
│ L3  Tools (22)      MCP servers via MCPToolAdapter           │
│                     calc_psi4 / calc_xtb / io / parse / viz  │
│                     kb_search / use_skill / list_skills      │
├─────────────────────────────────────────────────────────────┤
│ L2  Engines         psi4 / xTB / ORCA / BDF / cclib / RDKit  │
├─────────────────────────────────────────────────────────────┤
│ L1  Knowledge Base                                           │
│     kb/formulas/    Python 确定性公式（Marcus、Strickler-Berg）│
│     kb/rules/       YAML 规则（基组 / 泛函 / 收敛）           │
│     kb/skills/      Markdown playbook（opt-freq / tadf-…）   │
└─────────────────────────────────────────────────────────────┘
```

详见 [docs/V2_RELEASE_NOTES.md](docs/V2_RELEASE_NOTES.md) §2。

---

## 当前状态

| Phase | 内容 | 状态 |
|---|---|---|
| 0 | 仓库脚手架 + 设计文档 | ✅ |
| 1 | 工具链路打通（硬编码 H2O e2e）| ✅ |
| **1.5** | **真 Claude tool-use Agent loop** | ✅ |
| 2 | LLM 接入（Anthropic + MiniMax M2.7 实测）| ✅ |
| 3 | TADF 流水线 anchor 分子（4CzIPN 等 5 个）| ⬜ |
| 4 | ORCA / BDF / MultiWFN 真实接入 | ⬜ |
| 5 | HPC 异步集成 | ⬜ |
| 6 | 文档 + 论文 | ⬜ |
| 7 | PyPI 发布 | ⬜ |

**测试**：183 / 183 全绿（177 单元 + 6 集成；含 MiniMax 接入测试 6 项 + 类型强制转换测试 5 项）。

**E2E 实测**（见 `runs/<sweep>/_e2e_sweep_report.md`）：

| molecule | status    | E (Hartree) | n_modes | n_imag | wall (s) |
|----------|-----------|-------------|---------|--------|----------|
| water    | completed | -76.3589    | 3       | 0      | 8.7      |
| methane  | completed | -40.4897    | 9       | 0      | 22.6     |
| ammonia  | completed | -56.5107    | 6       | 0      | 17.4     |
| co2      | completed | -188.4447   | 4       | 0      | 11.3     |
| ethanol  | completed | -154.9247   | 21      | 0      | 174.6    |

---

## 文档

| 文档 | 内容 |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | **新会话第一个读** —— V2 架构 + 当前状态 |
| [`docs/V2_RELEASE_NOTES.md`](docs/V2_RELEASE_NOTES.md) | V1 → V2 完整变更说明 |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | 8 阶段开发路线（V2 已落地 Phase 0-2） |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 五层架构详解 |
| [`docs/SETUP.md`](docs/SETUP.md) | 开发环境搭建 |
| [`docs/PITFALLS.md`](docs/PITFALLS.md) | 化学计算 / Agent 开发坑表 |
| [`docs/MCP_GUIDE.md`](docs/MCP_GUIDE.md) | 怎么写 MCP server |
| [`docs/SKILLS_GUIDE.md`](docs/SKILLS_GUIDE.md) | 怎么写 Skill (V2: markdown playbook) |
| [`docs/TADF_PIPELINE.md`](docs/TADF_PIPELINE.md) | 标杆问题：TADF 发光体设计 |
| [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) | 代码与协作规范 |
| [`docs/KICKOFF.md`](docs/KICKOFF.md) | 新开发会话启动包（含可复制 prompt 模板） |

---

## 与现有工具的关系

| 工具 | 主要场景 | ChemMaster 的差异 |
|---|---|---|
| [ChemCrow](https://github.com/ur-whitelab/chemcrow-public) | 合成化学、检索、反应预测 | 不做计算化学 |
| [Coscientist](https://github.com/gomes-lab/coscientist) | 实验机器人、自主合成 | 不做仿真计算 |
| [EvoMaster](https://github.com/EMResearch/EvoMaster) | 软件测试 / API fuzzing | 完全不同领域，**架构借鉴**（agent loop + skill-as-tool） |
| Rowan / Schrödinger Live Design | 商业云端计算化学 SaaS | ChemMaster 本地优先、开源、BYO LLM |

---

## 内嵌工具

### `tools/pdf-structure-extract/` — 论文 PDF → 化学结构图 + SMILES

ChemMaster 启动前已有的独立工具，将通过 `chem.pdf` MCP 集成到 Agent。把科研 PDF 中的化学结构图裁剪出来，识别 SMILES，并标注回 PDF。底层 PyMuPDF + DECIMER。

详细用法见 [`tools/pdf-structure-extract/README.md`](tools/pdf-structure-extract/README.md)。

---

## 贡献

1. 读 [`CLAUDE.md`](CLAUDE.md) 了解 V2 架构
2. 读 [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) 了解规范
3. 读 [`docs/PITFALLS.md`](docs/PITFALLS.md) 避坑
4. 加新 MCP / Skill 见对应 GUIDE
5. 提 PR 前跑 `pytest tests/unit && pytest -m integration`

---

## License

MIT — 详见 [`LICENSE`](LICENSE)。

---

## 引用

待 1.0 release 后补 `CITATION.cff` + JOSS 论文 DOI。
