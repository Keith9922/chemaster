---
name: conformer
version: 0.1.0
description: 多构象搜索 — xTB/CREST 粗筛 + DFT 精筛漏斗
when_to_use: |
  - 用户给的分子有可旋转键 ≥ 2 个，单一构象不可信。
  - tadf-pipeline / pka 等 skill 内部调用。
  - 用户明确要"找最稳构象"、"采样构象"。
when_not_to_use: |
  - 已给优化好的几何且确认是全局最稳。
  - 刚性小分子（如 H2O）。
required_mcps:
  - chem.calc.xtb
  - chem.io.ase
  - chem.calc.psi4   # 或 orca，做 DFT 精筛
estimated_time: 5 min - 2 hours (取决于体系大小与可旋转键数)
---

# Conformer Search

## 默认参数

- 粗筛：CREST iMTD-GC (xTB GFN2)
- 能量窗：6 kcal/mol
- RMSD 去重：0.5 Å
- 精筛：B3LYP-D3(BJ)/def2-SVP 单点

## 流程

1. xTB GFN2 优化初始结构
2. CREST iMTD-GC 搜索（默认 -T <n_cores>，--ewin 6.0）
3. xTB 输出去重 → 候选列表
4. 对每个候选用 DFT (def2-SVP) 单点排序
5. 保留 Boltzmann 权重 > 1% 的构象
6. 输出 list[xyz] + weights

## 失败模式

| 问题 | 处理 |
|---|---|
| CREST 找不到任何构象 | 检查初始结构合理性；尝试 --noreftopo |
| 候选过多 (>200) | 缩小 ewin |
| 精筛阶段 SCF 不收敛 | 用 opt-freq 的 SCF 恢复策略 |

## TODO Phase 2

完整步骤展开。
