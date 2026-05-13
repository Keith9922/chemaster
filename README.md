# ChemMaster

> **A local, large-language-model-driven, terminal-native agent that absorbs the
> repetitive labor in computational chemistry workflows — while keeping every
> chemistry decision in the researcher's hands.**
>
> 本地运行、由大模型驱动、与终端环境集成的计算化学 Agent 系统。
> 设计原则：**Agent 承担操作性工作（输入构造、提交、解析、错误重试），化学决策权（方法/基组/泛函/溶剂模型）通过推荐机制保留给研究者。**

[![Tests](https://img.shields.io/badge/tests-228%20passed-brightgreen)]()
[![License](https://img.shields.io/badge/license-MIT-blue)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)]()

---

## 核心特点

- **Labor-saving collaborator，不是 autonomous agent**：通过 L1（自主）/ L2（推荐确认）/ L3（必须用户判断）三级权限分级机制，明确划分"机械操作"与"化学决策"边界。
- **基于 MCP（Model Context Protocol）协议**：每个量子化学软件封装为标准化 MCP server，可被 ChemMaster 主程序调用，**也可被 Claude Code、Cursor 等任意 MCP 客户端独立挂载使用**。
- **多前端形态**：CLI、Textual TUI、本地 Web 三种用户接口共享同一个 Agent 内核与工具集。
- **本地运行**：分子结构不上传云端；除 LLM API 调用外全部在本地进行。
- **"LLM 不算数"原则**：所有数值计算（物理常数、单位换算、Marcus 速率公式等）固化在 Python 模块中由 Agent 调用，避免大模型直接进行浮点运算。

## 截图

| 命令行单测 | TUI 终端界面 | 本地 Web 前端 |
|---|---|---|
| ![pytest](paper/figures/v3_real/fig_real_pytest.png) | ![tui](paper/figures/v3/fig_tui_textual_render.png) | ![web](paper/figures/v3/fig_web_default.png) |

## 五层架构

![架构](paper/figures/v4/fig_architecture.png)

完整说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 快速开始

### 安装

```bash
git clone https://github.com/Keith9922/chemaster.git
cd chemaster

# 推荐使用 Conda 安装（psi4 仅在 Conda 上提供）
conda install -c conda-forge psi4 dftd3-python
pip install -e ".[dev]"
pip install textual fastapi uvicorn playwright pint rdkit ase

# 配置 LLM API key（任选其一）
export ANTHROPIC_API_KEY=sk-ant-...
# 或 export OPENAI_API_KEY=...
# 或 export DASHSCOPE_API_KEY=...   (Qwen)
# 或 export MINIMAX_API_KEY=...
# 或 export DEEPSEEK_API_KEY=...
```

### 三种使用方式

```bash
# 命令行
chemaster run "Compute the energy of water using B3LYP/def2-SVP"

# Textual TUI（终端交互界面）
chemaster tui

# 本地 Web 前端（FastAPI + 内嵌 SPA，浏览器打开 http://127.0.0.1:8765）
chemaster web
```

### 运行单元测试

```bash
/opt/miniconda3/bin/python -m pytest tests/unit/ -q
# 228 passed, 1 skipped
```

## 已支持的计算后端

| 软件 | 协议 | 状态 | 用途 |
|---|---|---|---|
| **Gaussian** | MCP | 接口已实现 | 主线工具栈 — 基态优化、TDDFT、频率分析 |
| **BDF** | MCP | 接口已实现 | 主线工具栈 — 自旋–轨道耦合（X2C-TDA） |
| **MOMAP** | MCP | 接口已实现 | 主线工具栈 — TVCF 速率与振动分辨光谱 |
| **PySCF** | MCP | **实测可用** | **BDF SOC 的开源 reference — 蒽 X2C-1e 三阶段相对论真跑通** |
| psi4 | MCP | 实测可用 | 替代后端 — 在没有 Gaussian 许可时可完整跑 S22 / QUEST 验证 |
| ORCA | MCP | 接口已实现 | 替代后端 |
| xTB | MCP | 实测可用 | 半经验快速预筛 |
| ASE | MCP | 实测可用 | 结构 IO + 几何描述符 |

## 已完成验证

### 化学计算精度

| Benchmark | 方法 | 结果 |
|---|---|---|
| **S22 弱相互作用集**（5 体系） | B3LYP-D3(BJ)/def2-TZVP + counterpoise，psi4 实跑 | MAE = **0.75 kcal/mol**；water_dimer 与 ethene_ethyne 误差 < 0.6 kcal/mol |
| **QUEST 激发态参考集**（3 分子 8 状态） | TD-CAM-B3LYP/def2-SVP, TDA，psi4 实跑 | Valence 态 MAE < **0.2 eV**；Rydberg 态因 def2-SVP 缺 diffuse 函数偏大 |
| **蒽 X2C-1e SOC**（开源 reference） | RKS / RKS+X2C / GKS+X2C-1e B3LYP/def2-svp，**PySCF 实跑** | 标量相对论修正 **−5.28 eV**；SOC 修正 **−0.10 meV**（C/H 体系 SOC 极小，化学正确）|
| 蒽完整 BDF + MOMAP TVCF 流水线 | — | **未在本工作中完成**（依赖 BDF 与 MOMAP 软件许可，留作未来工作）|

详细数据：[`benchmarks/s22/summary.json`](benchmarks/s22/summary.json)、[`benchmarks/quest/summary.json`](benchmarks/quest/summary.json)、[`benchmarks/anthracene/runs_archive/x2c_pyscf/result.json`](benchmarks/anthracene/runs_archive/x2c_pyscf/result.json)。

### 工程指标

| 指标 | 结果 |
|---|---|
| 单元测试 | **253 passed, 1 skipped**（用 conda Python 加载完整依赖时；含 calc_pyscf 12 项新测试） |
| MCP 协议合规性独立探针 | 3/3 servers initialised；kb 与 const 通过完整 initialize → list_tools → call_tool 链路 |
| 操作性故障自动恢复率 | **84%（21/25）**，达到设定的 80% 目标 |
| 提交摩擦时间节省率（指标 5）| **未在本工作中完成**（需真人被试参与）|
| 化学决策推荐接受率（指标 3b）| **未在本工作中完成**（同上）|
| Trajectory 自主步占比（指标 3c）| **未在本工作中完成**（需真实 LLM API 触发完整工具调用链） |

详细数据：[`benchmarks/engineering_metrics/`](benchmarks/engineering_metrics/)。

## 仓库目录结构

```
chemaster/
├── chemaster/                 # 主包源代码
│   ├── agent/                 # Agent 内核（tool-use loop, 权限分级, trajectory）
│   ├── mcp/                   # 13 个 MCP server（calc_gaussian, calc_bdf, calc_momap, ...）
│   ├── kb/                    # 知识库
│   │   ├── formulas/          # 确定性 Python 公式模块（Marcus, MLJ, Strickler-Berg, ...）
│   │   ├── rules/             # YAML 规则
│   │   └── skills/            # Markdown 领域文档（opt-freq, tddft, soc, ...）
│   ├── tui/                   # Textual TUI 实现
│   ├── web/                   # 本地 Web 前端（FastAPI + 内嵌 SPA）
│   └── cli.py                 # 命令行入口
├── benchmarks/                # 基准数据
│   ├── s22/                   # S22 实测结果
│   ├── quest/                 # QUEST 实测结果
│   ├── engineering_metrics/   # 工程指标
│   └── use_cases/             # TUI / Web / MCP 跨客户端 demo 证据
├── docs/                      # 设计文档
│   ├── ARCHITECTURE.md
│   ├── BENCHMARK_PROTOCOL.md
│   ├── REFACTOR_PLAN.md       # v3.0 设计决策清单
│   └── ...
├── paper/                     # 毕设论文
│   ├── thesis_draft.docx      # Word 论文初稿
│   └── figures/               # 论文配图
├── scripts/
│   ├── benchmarks/            # benchmark 运行脚本
│   ├── generate_thesis_docx.py
│   └── ...
└── tests/                     # 单元测试 + 集成测试
```

## 设计原则

详见 [docs/REFACTOR_PLAN.md](docs/REFACTOR_PLAN.md)。简版要点：

1. **承担操作性工作，保留化学决策权**：Agent 仅在权限分级表（`~/.chemaster/policy.yaml`）允许的范围内自主行动，所有影响化学结果的选择都通过 `recommend` 工具或 `ask_user` 工具交回研究者。
2. **LLM 不直接做浮点运算**：物理常数、单位换算、速率公式等固化在 Python 模块中由 Agent 通过工具调用获取，避免大模型直接产出数值带来的不可靠性。
3. **MCP 协议为核心**：所有计算工具都封装为标准 MCP server，确保协议级别的可复用性。

## 与同类工作的对比

![对比](paper/figures/v4/fig_comparison.png)

完整对比与讨论见毕业论文 §1.2 与 §4.6（[paper/thesis_draft.docx](paper/thesis_draft.docx)）。

## 开发状态

本项目目前处于**工程原型阶段**——架构设计完整、核心代码可运行、有限范围内的实测数据已发布。不建议用于生产研究。

| 部分 | 状态 |
|---|---|
| Agent 内核（tool-use, 权限分级, trajectory）| ✅ |
| 13 个 MCP server | ✅ |
| psi4、xTB 实测可用 | ✅ |
| Gaussian、BDF、MOMAP 真实接入测试 | ⏸ 软件许可受限，留作后续工作 |
| CLI / TUI / Web 三前端 | ✅ |
| 基础精度验证（S22, QUEST）| ✅ |
| 工程指标实验（被试参与的提交摩擦时间、推荐接受率）| ⏸ 待补 |
| 商业云 HPC 真实接入 | ⏸ 仅接口预留 + 本地 SLURM 占位 |

## 引用本项目

如果本项目对你的研究有帮助，请引用：

```bibtex
@software{chemmaster2026,
  title  = {ChemMaster: A Local Computational-Chemistry Agent Built on Large-Language-Model and MCP Protocol},
  author = {Zhang, Ronggang},
  year   = {2026},
  url    = {https://github.com/Keith9922/chemaster}
}
```

## 致谢

本项目站在多个优秀开源工作的肩膀之上。在协议与运行时层面，使用了 Anthropic 提出的 [MCP](https://modelcontextprotocol.io/) 协议规范及其 [Python SDK](https://github.com/modelcontextprotocol/python-sdk)。在 Agent 形态的设计上，本项目从 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 与 [DeepSeek TUI](https://github.com/Hmbown/DeepSeek-TUI) 的交互范式中受到启发；化学 Agent 的研究方向受 [ChemCrow](https://github.com/ur-whitelab/chemcrow-public) 与 [Coscientist](https://github.com/gomesgroup/coscientist) 等工作的启发；科学计算工作流的设计参考了 [ASE](https://wiki.fysik.dtu.dk/ase/)、[AiiDA](https://www.aiida.net/)、[Atomate](https://atomate.org/) 等系统。

代码运行时直接依赖以下开源项目：
量子化学与化学信息工具 [psi4](https://psicode.org)、[PySCF](https://pyscf.org)（用作 BDF X2C SOC 路径的开源 reference）、[xTB](https://github.com/grimme-lab/xtb)、[ASE](https://wiki.fysik.dtu.dk/ase/)、[RDKit](https://www.rdkit.org)、[cclib](https://cclib.github.io)、[pint](https://pint.readthedocs.io)；
LLM Agent 与协议 [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python)、[MCP](https://modelcontextprotocol.io/)；
用户界面与命令行 [click](https://click.palletsprojects.com)、[rich](https://rich.readthedocs.io)、[Textual](https://textual.textualize.io)；
Web 后端与浏览器自动化 [FastAPI](https://fastapi.tiangolo.com)、[uvicorn](https://www.uvicorn.org)、[Playwright](https://playwright.dev)；
数据处理与可视化 [NumPy](https://numpy.org)、[matplotlib](https://matplotlib.org)、[PyYAML](https://pyyaml.org)；
SSH 与 HPC 集成 [paramiko](https://www.paramiko.org)；
文档与图表 [python-docx](https://python-docx.readthedocs.io)、[drawio](https://www.drawio.com)；
开发工具 [pytest](https://pytest.org)、[git-filter-repo](https://github.com/newren/git-filter-repo)。

## License

[MIT License](LICENSE) — see file for details.

---

*This is the `main` README. For project-internal notes, see [CLAUDE.md](CLAUDE.md). For the thesis, see [paper/thesis_draft.docx](paper/thesis_draft.docx).*
