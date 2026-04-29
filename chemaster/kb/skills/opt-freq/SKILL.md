---
name: opt-freq
version: 0.1.0
description: 几何优化 + 频率确认的标准量化工作流
when_to_use: |
  - 用户要"算 X 的能量"、"优化 X 的结构"、"找 X 的极小点"。
  - 需要 ZPE、热修正、自由能。
  - 后续工作流（如 TDDFT、SOC）需要先有优化好的几何。
when_not_to_use: |
  - 找过渡态：用 ts-search。
  - 仅快速估算单点：直接调 chem.calc.*.single_point。
  - 多构象搜索：先用 conformer skill。
required_mcps:
  - chem.calc.psi4
  - chem.io.ase
  - chem.parse.cclib
  - chem.viz
estimated_time: 1-30 minutes (单分子 < 50 atoms)
references:
  - "Cramer, Essentials of Computational Chemistry, Ch. 7-8"
  - "Jensen, Introduction to Computational Chemistry, Ch. 13"
---

# Geometry Optimization + Frequency Confirmation

## 流程概述

1. 准备初始几何（SMILES → 3D 或用户给的 xyz）
2. 几何优化
3. 频率计算（与优化用相同 method/basis）
4. 检查虚频；若有，沿模式位移后重启优化
5. 提取热力学量（ZPE、H_corr、G_corr）
6. 出 3D 图与报告

## 默认参数

- method: `B3LYP-D3(BJ)`
- basis: `def2-TZVP`
- engine: `psi4`（首选；ORCA 备用）
- temperature: 298.15 K
- pressure: 1 atm
- charge / multiplicity: 用户提供，否则按"中性 + 偶电子单重 / 奇电子双重"自动推断

## 详细步骤

### Step 1 — 初始几何

```yaml
# 如果用户给 SMILES：
chem.io.ase.smiles_to_xyz:
  smiles: <SMILES>
  embed_n_conformers: 10
  optimize_force_field: UFF
```

如果连 SMILES 都没有（"算水分子"这种）：

```yaml
chem.io.ase.lookup_by_name:
  name: water
```

### Step 2 — 几何优化

```yaml
chem.calc.psi4.optimize:
  geometry: <xyz from step 1>
  charge: <charge>
  multiplicity: <mult>
  method: B3LYP-D3(BJ)
  basis: def2-TZVP
  convergence: tight
```

**若 ok=False**：

| error_code | 处理 |
|---|---|
| SCF_NOT_CONVERGED | 见 §"SCF 失败恢复" |
| GEOMETRY_NOT_CONVERGED | 见 §"几何优化失败恢复" |
| UNSUPPORTED_ELEMENT | 切换 basis（chem.kb.search 查 basis_for_element） |

### Step 3 — 频率计算

**重要**：必须用与 optimize 相同的 (method, basis)。

```yaml
chem.calc.psi4.frequency:
  geometry: <optimized xyz from step 2>
  charge: <charge>
  multiplicity: <mult>
  method: B3LYP-D3(BJ)      # 与 step 2 完全一致
  basis: def2-TZVP          # 与 step 2 完全一致
  temperature: 298.15
  pressure: 1.0
```

返回值含 `frequencies`（cm⁻¹），`zpe`，`thermal_corrections`。

### Step 4 — 虚频检查

```python
imaginary = [f for f in result.frequencies if f < -10]   # < -10 cm⁻¹ 才算
```

如果有虚频：
1. 找绝对值最大的虚频 mode i
2. 调 `chem.io.ase.displace_along_mode(geom, mode_i, amplitude=0.1)` 得到位移后几何
3. 回到 Step 2 重新优化
4. 最多 3 轮；3 轮仍有虚频 → 报告"疑似过渡态"，请用户决策（可能要切到 ts-search）

### Step 5 — 解析与可视化

```yaml
chem.parse.cclib.parse_output:
  output_file: <step 3 output>
chem.viz.plot_3d:
  geometry: <final xyz>
  output: figures/geometry.png
chem.viz.plot_ir:
  frequencies: <freqs>
  intensities: <ir_int>
  output: figures/ir.png
```

### Step 6 — 报告

输出 Markdown 含：
- 分子结构图
- 最终能量（Hartree + kcal/mol）
- ZPE
- 热力学修正（H, G at 298.15 K）
- 振动频率列表（top 10）
- 优化迭代步数
- 计算耗时

## SCF 失败恢复策略

按顺序尝试：

1. **换初猜**：guess=GWH（默认 SAD 失败常见）
2. **加阻尼**：damping=0.5，关掉 DIIS 前 5 步
3. **降基组先收敛**：def2-SVP 收敛后用其密度作 def2-TZVP guess
4. **关对称性**：symmetry=c1
5. **报告失败**：含已尝试策略与各自 final_residual

## 几何优化失败恢复策略

1. 切冗余内坐标：coordinate_system=redundant_internal
2. 减小初始 trust radius 到 0.1
3. 改用 RFO 优化器
4. max_iter 增加到 500
5. 报告失败

## 与其他 skill 的衔接

- 后续 TDDFT：把 step 5 的 optimized_geometry 直接传给 tddft skill
- 后续 SOC（TADF）：用 tadf-pipeline 整体调度，不要单独触发本 skill
- 后续 IRC（鞍点）：本 skill 不适用，路由到 ts-search

## 验证 / 测试

参见 [`examples/h2o.md`](examples/h2o.md)（待写）。

测试输入：`算 H2O 的能量`

期望产出：
- `runs/<id>/` 含 step_01_optimize / step_02_frequency
- `report.md` 含 3D 图、能量 ≈ -76.4 Hartree、无虚频
- 总耗时 < 5 minutes
