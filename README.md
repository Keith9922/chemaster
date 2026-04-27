# ChemMaster

> **AI agent for computational chemistry — local, open, scriptable.**
>
> 用自然语言下达计算任务，Agent 规划方案 → 用户确认 → 调用 psi4 / ORCA / BDF / xTB → 自动出图、出报告 → 必要时迭代。
>
> 标杆场景：**TADF 发光体设计**（OLED 第三代发光材料的全流程计算筛选）。

---

## 核心特性

- **本地优先** — 分子结构不上传；可离线（除 LLM API）。
- **BYO LLM** — Anthropic / OpenAI / Qwen / DeepSeek，或本地 Qwen / DeepSeek / Llama。
- **多软件统一接口** — psi4、ORCA、BDF（北大刘文剑组）、xTB、MultiWFN，同一套自然语言 API。
- **Plan-Confirm-Execute 三段式** — Agent 出方案，用户确认/编辑，再执行。所有关键决策可见可改。
- **HPC 原生集成** — SLURM 自动提交、监控、拉回结果（Phase 3）。
- **Skill + MCP 双层** — 方法论（Skill, Markdown）与工具（MCP, 类型化）解耦，易扩展。
- **可重复** — 每个任务的输入文件、版本、随机种子全保留，3 个月后 bit-perfect 重跑。

---

## 快速开始

### 一行装

```bash
curl -sSL https://raw.githubusercontent.com/<user>/chemaster/main/install.sh | bash
```

### 手动装

```bash
conda create -n chemaster python=3.11 -y
conda activate chemaster
conda install -c conda-forge chemaster psi4 xtb cclib rdkit ase -y

# 配置 LLM API
export ANTHROPIC_API_KEY=sk-ant-...

# 检查环境
chemaster --check-engines

# 启动 TUI
chemaster
```

详见 [`docs/SETUP.md`](docs/SETUP.md)。

---

## 用法示例

### 算个水分子的能量

```
$ chemaster
> 算 H2O 的能量

[Plan]
  Step 1  几何优化  B3LYP-D3(BJ)/def2-TZVP   psi4
          理由: 小分子默认精度-成本平衡点
  Step 2  频率确认  B3LYP-D3(BJ)/def2-TZVP   psi4
          理由: 确认极小点 + ZPE 修正
  估时: ~1 min on 4 cores

[A]ccept  [E]dit  [R]eplan  [Q]uit  > A

[Executing] step_01_optimize ... ✓ (12.3s)
[Executing] step_02_frequency ... ✓ (8.1s)

[Report] runs/task-a3f2/report.md
  最终能量: -76.418 Hartree (-47930 kcal/mol)
  ZPE:    +0.021 Hartree
  G(298K): -76.397 Hartree
  无虚频 ✓
```

### 算一个 TADF 分子的全套指标

```
> 算 4CzIPN 的 TADF 性质

[Plan]  → tadf-pipeline skill
  Step 1  构象搜索   xTB GFN2 + CREST
  Step 2  基态优化   ωB97X-D / def2-SVP
  Step 3  TDDFT     ωB97X-D / def2-TZVP, S1+T1
  Step 4  SOC       BDF X2C-TDA
  Step 5  重组能 λ  4-point method
  Step 6  kRISC     Marcus
  Step 7  NTO 分析  MultiWFN
  估时: ~3 hours on 8 cores
...
```

### 从论文 PDF 自动复算

```
> 把这篇论文的所有 TADF 分子算一遍并和文献对比
  paper.pdf

[Plan]
  Step 1  PDF → 化学结构抽取  chem.pdf (DECIMER + RDKit)
  Step 2  对每个分子调 tadf-pipeline
  Step 3  生成对比表
...
```

---

## 文档

| 文档 | 内容 |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Agent 协作主入口（开发者第一个读） |
| [`docs/KICKOFF.md`](docs/KICKOFF.md) | **新开发会话启动包**（含可复制 prompt 模板） |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | 7 阶段开发路线 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 六层架构详解 |
| [`docs/SETUP.md`](docs/SETUP.md) | 开发环境搭建 |
| [`docs/PITFALLS.md`](docs/PITFALLS.md) | 化学计算 / Agent 开发坑表 |
| [`docs/MCP_GUIDE.md`](docs/MCP_GUIDE.md) | 怎么写 MCP server |
| [`docs/SKILLS_GUIDE.md`](docs/SKILLS_GUIDE.md) | 怎么写 Skill |
| [`docs/PACKAGING.md`](docs/PACKAGING.md) | 打包发布到 PyPI / conda-forge / Docker |
| [`docs/TADF_PIPELINE.md`](docs/TADF_PIPELINE.md) | 标杆问题：TADF 发光体设计 |
| [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) | 代码与协作规范 |

---

## 与现有工具的关系

| 工具 | 主要场景 | ChemMaster 的差异 |
|---|---|---|
| [ChemCrow](https://github.com/ur-whitelab/chemcrow-public) | 合成化学、检索、反应预测 | 不做计算化学 |
| [Coscientist](https://github.com/gomes-lab/coscientist) | 实验机器人、自主合成 | 不做仿真计算 |
| Rowan / Schrödinger Live Design | 商业云端计算化学 SaaS | ChemMaster 本地优先、开源、BYO LLM |
| **ChemMaster** | **TADF + 通用 DFT 流水线 + benchmark 闭环** | **本项目** |

---

## 当前状态

仓库处于 **Phase 0 / 1 之间**：架构与文档完整，第一个 MCP server (`chem.const`) 已实现，其余 MCP / Skill 待 Phase 1+ 填充。详见 [`CLAUDE.md`](CLAUDE.md) §11。

---

## 内嵌工具（Tools）

### `tools/pdf-structure-extract/` — 论文 PDF → 化学结构图 + SMILES

> 这是 ChemMaster 启动前的独立工具，已迁移到 `tools/`，并被 `chem.pdf` MCP 调用。

把科研 PDF 中的化学结构图裁剪出来，识别 SMILES，并标注回 PDF。底层用 PyMuPDF + DECIMER。

详细用法见 [`tools/pdf-structure-extract/README.md`](tools/pdf-structure-extract/README.md)（待迁移自原 README）。

---

## 贡献

1. 读 [`CLAUDE.md`](CLAUDE.md) 了解架构
2. 读 [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) 了解规范
3. 读 [`docs/PITFALLS.md`](docs/PITFALLS.md) 避坑
4. 加新 MCP / Skill 见对应 GUIDE
5. 提 PR 时跑 `pytest tests/unit && ruff check chemaster tests`

---

## License

MIT — 详见 [`LICENSE`](LICENSE)。

---

## 引用

待 1.0 release 后补 `CITATION.cff` + JOSS 论文 DOI。
