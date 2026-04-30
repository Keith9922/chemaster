---
name: pes-scan
version: 0.2.0
description: 一维 / 二维势能面扫描（找出反应坐标、构象旋转能垒、CT 路径）
when_to_use: |
  - 探查"沿键长 / 角度 / 二面角变化时能量怎么走"
  - 找过渡态前的扫描定位（TS 搜索的输入）
  - 验证某个构象是否处于鞍点附近
  - TADF: 给体-受体二面角扫描以确定 CT 态稳定区间
when_not_to_use: |
  - 已知反应坐标且只需 TS：直接 ts-search
  - 完整反应路径：用 IRC（不在本 V2 范围）
required_mcps:
  - chem.calc.psi4
  - chem.io.ase
  - chem.viz
estimated_time: 0.5-4 hours (一维 12 点 / 30 原子体系)
---

# Potential Energy Surface Scan

## 流程概述

1. 先 opt+freq 拿到极小点（前置）。
2. 选 reaction coordinate（键长 / 角度 / 二面角）。
3. 在指定 grid（12-24 点）逐点固定 RC 并 SCF。
4. 出能量曲线；峰值用 ts-search 精化。

## 详细步骤

### Step 1 — 选 RC

例如：
- 给体-受体扭转：每 15° 一个点，共 24 点（对称时减半）。
- 键长扫描：从平衡 ±0.5 Å，步长 0.05 Å。

### Step 2 — 逐点 SCF

```python
energies = []
for rc_value in scan_grid:
    geom = build_geometry_with_rc_locked(opt_xyz, rc_value)
    e = chem.calc.psi4.single_point(geom, method="B3LYP-D3(BJ)", basis="def2-SVP")
    energies.append((rc_value, e["result"]["energy"]["value"]))
```

V2 当前实装是简化版（只单点，不松弛剩余自由度）。完整 relaxed scan 需要在
psi4 的 `optking` 加 `frozen_dihedral` 列表 —— 后续工作。

### Step 3 — 出图

调 `chem.viz.plot_xy(x=..., y=..., xlabel=..., ylabel=...)`。

## 常见失败

- SCF 不收敛：扫描中部分几何非物理；用小 step。
- 能量曲线跳跃：SCF 多解（broken symmetry）；强制 `symmetry c1`，或用前点
  波函数作 guess（PITFALLS §2.4）。

## 与其他 skill 的边界

- 峰值 → ts-search 精化。
- Marcus 重组能见 tadf-pipeline 的 4-point method（不需要扫描）。
