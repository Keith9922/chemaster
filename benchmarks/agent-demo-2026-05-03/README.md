# Agent demo — 一句话调用 H2O 计算（2026-05-03）

第一次完整端到端的 **真 LLM Agent → 真 QC 工具 → 出报告** 闭环。

## 命令

```bash
chemaster run --llm-provider minimax --no-confirm \
  "Optimize water at B3LYP-D3(BJ)/def2-TZVP, then compute its harmonic
   frequencies, and report the O-H bond length, H-O-H angle, and the three
   vibrational frequencies."
```

## 配置

| 项目 | 值 |
|---|---|
| LLM | MiniMax-M2.7（通过 `https://api.minimaxi.com/anthropic` Anthropic 兼容端点）|
| QC engine | psi4 1.10 |
| 方法 / 基组 | B3LYP-D3(BJ) / def2-TZVP |
| 总时长 | 64 秒（5 次 LLM round-trip + 4 个真 psi4 工具调用） |
| 总步数 | 7 |
| 自动确认 | `--no-confirm`（all is_long_running 工具自动放行） |

## Agent 自主决策路径（7 步，无人工干预）

| 步 | 工具 | 输入 | 输出/事件 |
|---:|---|---|---|
| 1 | `io_lookup_by_name` | `name="water"` | 取出标准 H2O 起始几何 |
| 2 | `calc_psi4_optimize` | `method=B3LYP-D3(BJ)`, `basis=def2-TZVP` | E = −76.4636 Ha, 几何收敛 |
| 3 | `calc_psi4_frequency` | 优化后几何, 同方法基组 | 3 实频, n_imag=0, ZPE=0.02117 Ha |
| 4 | `io_compute_descriptors` | 错误的输入格式 | ✗ INVALID_GEOMETRY |
| 5 | `io_compute_descriptors` | 修正后, `bonds=[[0,1],[0,2]], angles=[[1,0,2]]` | ✓ O-H=0.9627Å, H-O-H=105.25° |
| 6 | `finish` | 整合 + 文献对比 | 出 [report.md](report.md) |

第 4-5 步的**自我错误恢复**是个真实功能，不是脚本：第 4 步 LLM 给的 XYZ 格式不对，MCP 返回 `INVALID_GEOMETRY` + `suggestion`，第 5 步 LLM 读了 suggestion 修正后重试成功。

## 数值结果 vs 实验

| 量 | ChemMaster (B3LYP-D3(BJ)/def2-TZVP) | 实验 (gas phase) | Δ |
|---|---:|---:|---:|
| O-H bond length | **0.9627 Å** | 0.958 Å | +0.5% |
| H-O-H angle | **105.25°** | 104.5° | +0.7% |
| ν₂ bend | **1617.1 cm⁻¹** | 1595 cm⁻¹ | +1.4% |
| ν₁ symmetric stretch | **3785.6 cm⁻¹** | 3657 cm⁻¹ | +3.5% |
| ν₃ asymmetric stretch | **3890.8 cm⁻¹** | 3756 cm⁻¹ | +3.6% |
| ZPE | 13.3 kcal/mol | — | — |

频率偏高 3-4% 是 B3LYP/def2-TZVP 在水分子上的**已知系统性误差**（IR scale factor ≈ 0.965），不是 ChemMaster 的 bug。键长/键角 < 1% 误差。

## 一个 LLM 类原则的实际验证

第一版 demo（commit 之前）Agent 自己从坐标算 H-O-H 角，给出 **102.0°**（错了 ~2.5°）。
本版本加了 [`io_compute_descriptors`](../../chemaster/mcp/io_ase/server.py) 工具 + 描述里写了 "**use this for any geometry numbers, do NOT compute yourself**"，Agent 立刻改用工具，给出 **105.25°**（正确）。

这就是 [CLAUDE.md §5.1 "LLM 不算数"](../../CLAUDE.md) 原则的具体实证：**约束 LLM 不要自己做算术，把所有数值算给确定性 Python，是这个 Agent 设计的核心安全保障。**

## 复现

需要：
- conda env `chemaster`（Python 3.11 + psi4 + ase + cclib + rdkit + anthropic SDK）
- `MINIMAX_API_KEY` 环境变量（任何 token-plan 用户都行）

```bash
conda activate chemaster
pip install -e .[dev]
export MINIMAX_API_KEY=sk-cp-...
chemaster run --llm-provider minimax --no-confirm \
  "Optimize water at B3LYP-D3(BJ)/def2-TZVP, then compute its harmonic
   frequencies, and report the O-H bond length, H-O-H angle, and the
   three vibrational frequencies."
```

完整 trajectory.json + 自动生成的 report.md 都在本目录下。
