---
name: tadf-pipeline
version: 0.1.0
description: 完整 TADF 发光体计算流水线（构象→DFT→TDDFT→SOC→kRISC）
when_to_use: |
  - 用户要"算 X 的 TADF 性质"、"评估 X 的 OLED 适用性"、
    "算 ΔE_ST"、"算 kRISC"。
  - 给定 SMILES 或 xyz，要 ΔEST、振子强度、kRISC、轨道分析。
  - 从论文 PDF 抽出分子后想自动复算。
when_not_to_use: |
  - 仅要单点能 / 优化：用 opt-freq。
  - 仅要激发态（不要 SOC）：用 tddft。
  - 用户明确说"只做某一步"：路由到对应 skill。
required_skills:
  - conformer
  - opt-freq
  - tddft
  - soc
required_mcps:
  - chem.calc.xtb
  - chem.calc.orca
  - chem.calc.bdf
  - chem.analysis.multiwfn
  - chem.viz
  - chem.kb
estimated_time: 2-8 hours (本地) / 30-90 min (HPC)
references:
  - "Endo et al., Adv. Mater. 2009, 21, 4802 (TADF mechanism)"
  - "Uoyama et al., Nature 2012, 492, 234 (4CzIPN)"
  - "BDF SOC 计算手册"
---

# TADF Emitter Screening Pipeline

> **毕设标杆 skill**。所有 anchor case（4CzIPN、DMAC-DPS、P=O / N-MR 系列等）都跑这个流水线。

## 总览

详见 [`docs/TADF_PIPELINE.md`](../../../docs/TADF_PIPELINE.md)。

```
SMILES / xyz → 构象搜索 → 基态 opt+freq → TDDFT (S1, T1)
                                          ↓
       MultiWFN (NTO) ← SOC (BDF) ← 重组能 ← Marcus (kRISC)
                                          ↓
                                         报告
```

## 默认参数（**KB 写死，不让 LLM 改**）

| 量 | 默认 |
|---|---|
| 构象搜索 | xTB GFN2 + CREST iMTD-GC |
| 基态泛函 | ωB97X-D |
| 基态基组 | def2-SVP（opt）→ def2-TZVP（单点 + TDDFT）|
| TDDFT 方法 | TDA（T1）/ 全 TDDFT（S1） |
| 隐式溶剂 | toluene (PCM) |
| SOC 软件 | BDF (X2C-TDA) |
| 温度 | 298.15 K |
| 重组能方法 | 4-point |

## 详细步骤

### Step 1 — 构象搜索

调用 [`conformer`](../conformer/SKILL.md) skill：

```yaml
delegate_to: conformer
args:
  smiles: <SMILES>
  method: xtb-gfn2
  energy_window_kcal: 6.0   # 保留 ΔE < 6 kcal/mol
  rmsd_threshold: 0.5
```

输出：保留 Boltzmann 权重 > 1% 的构象列表。

### Step 2 — 基态优化（每个构象）

对每个构象调用 [`opt-freq`](../opt-freq/SKILL.md) skill：

```yaml
delegate_to: opt-freq
args:
  geometry: <conformer xyz>
  method: ωB97X-D
  basis: def2-SVP
  solvent: toluene
```

排除有虚频或能量过高的构象，选最稳定那个进入 Step 3。

### Step 3 — TDDFT 激发态

调用 [`tddft`](../tddft/SKILL.md) skill：

```yaml
delegate_to: tddft
args:
  geometry: <opt geometry from step 2>
  method: ωB97X-D
  basis: def2-TZVP
  n_singlets: 5
  n_triplets: 5
  use_tda_for_triplets: true
  solvent: toluene
```

提取：E(S1)、E(T1)、f(S1)、ΔEST = E(S1) - E(T1)。

**质量门**：
- 若 ΔEST > 0.5 eV → 警告"可能不是好的 TADF 候选"，但流程继续。
- 若 f(S1) < 0.001 → 警告"振子强度太小，发光弱"。

### Step 4 — SOC（用 BDF）

调用 [`soc`](../soc/SKILL.md) skill：

```yaml
delegate_to: soc
args:
  geometry: <opt geometry from step 2>
  method: ωB97X-D-X2C-TDA
  basis: def2-TZVP-J     # BDF 兼容的基组
  states: ['S1', 'T1']
  engine: bdf
```

提取：<S1|H_SO|T1> 矩阵元（cm⁻¹）。

### Step 5 — 重组能 λ

4-point 法：

```yaml
chem.calc.orca.single_point: { geometry: <S0 opt>, state: T1, ... }
chem.calc.orca.optimize:     { geometry: <S0 opt>, state: T1, ... }
chem.calc.orca.single_point: { geometry: <T1 opt>, state: S0, ... }
# λ = E(T1@S0_geo) - E(T1@T1_geo) + E(S0@T1_geo) - E(S0@S0_geo)
```

或简化用 chemaster.kb.formulas 内的 `reorg_energy_4point()`（待 Phase 4 加）。

### Step 6 — kRISC

```yaml
chem.const.call:
  module: chemaster.kb.formulas.photophysics
  function: krisc_marcus
  args:
    delta_E_ST_eV: <step 3>
    soc_cm_inv: <step 4>
    reorganization_energy_eV: <step 5>
    temperature_K: 298.15
```

> **注意**：这是 LLM 不算数原则的体现。kRISC 不让 LLM 算，调 Python 函数。

### Step 7 — 轨道分析

```yaml
chem.analysis.multiwfn.nto:
  state: S1
  geometry: <opt geometry>
  density_file: <step 3 .molden>

chem.analysis.multiwfn.nto:
  state: T1
  ...
```

判断 S1 / T1 性质（LE / CT / hybrid）。

### Step 8 — 报告

`report.md` 包含：

- 分子结构图（2D + 3D）
- 构象列表与权重
- 基态几何指标（关键二面角、HOMO-LUMO gap）
- 表：S1, T1 能量、振子强度、ΔEST、SOC、λ、kRISC
- NTO 图（S1 / T1）
- **与文献对比表**（如果给了 reference values）
- 计算耗时与方法引用

## 失败模式

| 问题 | 处理 |
|---|---|
| Step 2 频率有虚频 | 自动位移重启（opt-freq 内置）；2 轮失败则丢弃该构象 |
| Step 3 三重态不稳（虚根） | 强制 TDA |
| Step 3 ΔEST < 0 | 警告"反 TADF"，可能是计算偏差或真有奇异能级排序 |
| Step 4 BDF 不可用 | 回退到 ORCA 的 RI-SOMF（精度差，报告里注明） |
| Step 5 重组能负 | 几何优化没收敛到极小点；回 Step 2 |

## anchor 分子

`benchmarks/tadf-literature/` 下含：
- `4CzIPN.yaml`
- `DMAC-DPS.yaml`
- `2CzPN.yaml`
- `ACRSA.yaml`
- 用户的 P=O / N-MR-TADF 系列

每个文件含：SMILES、几何、文献报告的 ΔEST / kRISC / f(S1)、来源 DOI。

## 验证

```
chemaster eval benchmarks/tadf-literature/4CzIPN.yaml
```

期望：
- ΔEST 误差 < 0.05 eV
- kRISC 数量级一致（log10 误差 < 1）
- 总耗时 < 4 hours (本地, 8 cores)
