---
name: pka
version: 0.2.0
description: 直接 / 热力学循环法预测有机分子 pKa
when_to_use: |
  - 给一个 R-H / R-OH / R-COOH 分子，估算 pKa
  - 比较多个位点哪个最酸
  - 给分子设计提供初步酸碱性指导
when_not_to_use: |
  - 多质子位点共耦合（用 multi-protonation skill — 未实装）
  - 真实溶剂效应非常重要时（用显式溶剂 + MD，不在本 skill 范围）
required_mcps:
  - chem.calc.psi4         # opt + freq + 单点
  - chem.io.ase
  - chem.const             # 公式库做 -RT ln10 转换
estimated_time: 30 min - 2 hours / 分子
references:
  - "Liptak & Shields, J. Am. Chem. Soc. 123, 7314 (2001) — 热力学循环法"
  - "Klamt et al., J. Phys. Chem. A 107, 9380 (2003) — COSMO-RS pKa"
---

# pKa Prediction (Direct DFT + Thermodynamic Cycle)

## 流程概述

1. Optimize HA 中性体 + A⁻ 阴离子（M06-2X / def2-TZVPD + 隐式溶剂 SMD）。
2. Frequency 拿 G(298K)。
3. 计算溶剂相 ΔG_dep = G(A⁻) + G(H⁺) - G(HA)。
4. pKa = ΔG_dep / (RT ln 10)。

H⁺ 在水中的标准自由能取经验值 -270.3 kcal/mol（Camaioni & Schwerdtfeger 2005）。

## 默认参数

| 参数 | 推荐值 |
|---|---|
| method | M06-2X-D3 |
| basis | def2-TZVPD（D 表示加 diffuse 函数；阴离子必需）|
| solvent | water (SMD)|
| H⁺ G_solv | -270.3 kcal/mol |

## 详细步骤

### Step 1 — Optimize HA + A⁻

两次调 `chem.calc.psi4.optimize`：分别 charge=0 和 charge=-1（H 拿走）。
multiplicity = 1（闭壳）。

### Step 2 — Frequency 拿 G

两次调 `chem.calc.psi4.frequency`，提取 `total_g`（V2 P0-2 实装的 thermal_corrections 字段）。

### Step 3 — 算 ΔG_dep 和 pKa

公式库（待补 `chemaster.kb.formulas.kinetics.pka_from_dg`）：

```python
G_HA = freq_HA["result"]["thermal_corrections"]["total_g"]["value"]
G_A  = freq_A_minus["result"]["thermal_corrections"]["total_g"]["value"]
G_H_plus = -270.3 / 627.5   # kcal/mol → Hartree
delta_G_au = G_A + G_H_plus - G_HA

# pKa = ΔG / (RT ln 10)
RT = chem.const.get_constant("kb").value * 298.15  # J
delta_G_J = chem.const.convert_unit(delta_G_au, "Hartree", "J")["value"]
pKa = delta_G_J / (RT * 2.30259)
```

## 精度预期

直接 DFT 法对脂肪族 / 酸 / 醇通常 ±1-2 pKa 单位。芳香酸（苯酚类）需要专门的
溶剂模型（COSMO-RS）才能 ±0.5。

## 与其他 skill 的边界

- 多步去质子化（多个酸性位点）：本 skill 一次只算一个；多次调用并比较 ΔG。
- 完整 microkinetic：不在本 skill 范围。
