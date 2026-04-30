---
name: dlpno-ccsdt
version: 0.2.0
description: DLPNO-CCSD(T) gold-standard single-point energetics via ORCA
when_to_use: |
  - 关键能量评价（反应焓、键能、互变异构能差）需要 chemical accuracy (~1 kcal/mol)
  - Benchmark：DFT 方法的参考值
  - 50-300 原子的有机/有机金属体系，CCSD(T) 太慢、DLPNO 显著加速
when_not_to_use: |
  - 周期性体系（DLPNO 不支持周期边界）
  - 多参考态体系（双键断裂、过渡金属 d 电子开壳）：用 CASPT2 / NEVPT2
  - 仅做几何优化或频率：用 DFT，CCSD(T) 太贵
required_mcps:
  - chem.calc.orca       # DLPNO-CCSD(T) 在 ORCA 里实现
  - chem.io.ase
  - chem.parse.cclib
estimated_time: 1-12 hours (50-100 atoms, def2-TZVP)
references:
  - "Riplinger, Neese, J. Chem. Phys. 138, 034106 (2013) — original DLPNO-CCSD(T)"
  - "Liakos, Neese, J. Chem. Theory Comput. 11, 4054 (2015) — convergence to canonical CCSD(T)"
---

# DLPNO-CCSD(T) Single-Point Energy

> Use after a DFT geometry optimization. Treats the **single-reference**
> wave function and recovers > 99.9 % of the canonical CCSD(T) correlation
> energy at a fraction of the cost.

## 流程概述

1. Optimize geometry first (DFT, e.g. B3LYP-D3(BJ)/def2-TZVP via psi4 or ORCA).
2. Pass the optimized xyz to `chem.calc.orca.single_point` with method
   `"DLPNO-CCSD(T) TightSCF"` and a triple-ζ basis (e.g. `cc-pVTZ` or
   `def2-TZVP`).
3. (Recommended) extrapolate to the CBS limit by repeating with `cc-pVQZ`
   and applying a 2-point Helgaker formula.

## 默认参数

| 参数 | 推荐值 | 备注 |
|---|---|---|
| method | `DLPNO-CCSD(T)` | TightPNO 默认；NormalPNO 速度优先时可用 |
| basis | `cc-pVTZ` (或 `def2-TZVP`) | 对相关能至少 TZ；DZ 收敛不够 |
| extra_keywords | `TightSCF RIJCOSX def2/J def2-TZVP/C` | 引入 RI 加速 |
| memory | ≥ 8 GB | 比 DFT 高一档 |

## 详细步骤

### Step 1 — DFT 几何优化（前置）

调 `chem.calc.psi4.optimize` 或 `chem.calc.orca.optimize`，方法 B3LYP-D3(BJ)
/ def2-TZVP。**DLPNO-CCSD(T) 不会自己跑几何优化** —— 它只算单点。

### Step 2 — DLPNO-CCSD(T) 单点

```
chem.calc.orca.single_point(
    geometry_xyz=<optimized_xyz>,
    method="DLPNO-CCSD(T) TightSCF",
    basis="cc-pVTZ",
    extra_keywords="RIJCOSX def2/J def2-TZVP/C",
)
```

返回 final electronic energy。注意 ORCA 的 `FINAL SINGLE POINT ENERGY` 行
是包含相关能的总能。

### Step 3 — CBS 外推（可选）

重复 Step 2 用 `cc-pVQZ` 基组，然后用 Helgaker 2 点 1/X^3 外推到 CBS。
公式库：`chemaster.kb.formulas.thermo`（待补 `cbs_extrapolate_helgaker`）。

## 常见失败

| 错误码 | 处理 |
|---|---|
| `ENGINE_NOT_FOUND` | 装 ORCA（学术免费）|
| `SCF_NOT_CONVERGED` | extra_keywords 加 `SlowConv` |
| `TIMEOUT` | `cc-pVDZ` 先粗跑或减少 fragment 数；DLPNO 100 原子以上易超时 |

## 与其他 skill 的边界

- **后续 IRC / 反应能垒**：用本 skill 算反应物 / 产物 / TS 的单点。
- **多参考态体系**：路由到 CASPT2（不在本 V2 实装范围）。
- **激发态**：用 `tddft` skill；EOM-DLPNO-CCSD(T) 在 ChemMaster 中尚未接入。
