---
name: solvation
version: 0.2.0
description: 隐式溶剂模型选型（PCM / SMD / COSMO-RS）+ 计算 ΔG_solv
when_to_use: |
  - 用户问"在水中能量是多少"、"溶剂效应"
  - TADF / 光化学：要算给定溶剂中的吸收/发射波长
  - pKa / 反应焓需要溶剂自由能修正
when_not_to_use: |
  - 极强氢键 / 显式溶剂壳必需：用 QM/MM 或 explicit microsolvation（未实装）
  - 离子液体 / 高浓盐：隐式模型不够
required_mcps:
  - chem.calc.psi4
  - chem.calc.orca
  - chem.io.ase
estimated_time: opt 比气相多 1.5×；frequency 多 2×
references:
  - "Marenich, Cramer, Truhlar, J. Phys. Chem. B 113, 6378 (2009) — SMD"
  - "Klamt, Jonas, Bürger, Lohrenz, J. Phys. Chem. A 102, 5074 (1998) — COSMO-RS"
---

# Solvation: Implicit Solvent Selection

## 决策树

```
need ΔG_solv only? ───────── yes ─→ SMD (psi4 / ORCA, water 默认)
                                    返回值精度 ±1-2 kcal/mol
       │ no
       ▼
need geometry / freq in solvent? ─ yes ─→ PCM (psi4) 或 CPCM (ORCA)
                                          快、稳定，精度略低
       │ no
       ▼
need parameterized real solvent (e.g. THF, dichloromethane)? ─ yes ─→ COSMO-RS
                                                                       (ORCA + 商业 COSMOtherm 后端)
                                                                       本 V2 不实装
```

## 默认选择（按场景）

| 场景 | 推荐 | 备注 |
|---|---|---|
| 通用 ΔG_solv（水）| SMD | 最准确、被引最多 |
| 光化学吸收谱（甲苯） | PCM | 与 TDDFT 兼容 |
| 反应能垒 | SMD on optimized geometry | 用气相几何即可 |
| 离子化合物 | SMD + 显式 first solvation shell | ChemMaster 不自动加显式水 |

## 详细步骤

### 用 PCM（psi4）

```
chem.calc.psi4.optimize(
    geometry_xyz=...,
    method="B3LYP-D3(BJ)", basis="def2-SVP",
    extra_options={"PCM": True, "PCM_SOLVENT": "water"},
)
```

注：psi4 V2 当前 `optimize` 没有 PCM 直通参数。生产用法需要扩展该 MCP；目前
此 skill 文档是 *为 Agent 在做 plan 时提供决策依据*，不是 self-contained 脚本。

### 用 SMD（ORCA）

```
chem.calc.orca.single_point(
    geometry_xyz=...,
    method="B3LYP D3BJ",
    basis="def2-TZVP",
    extra_keywords="CPCM(water)",
)
```

ORCA 关键字 `CPCM(water)` 等价于 SMD（ORCA 5+ 默认）。

## 常见失败

- SMD 收敛慢：先气相 SCF 收敛 → 把波函数当 guess 喂给 SMD 的 SCF。
- 强极性溶剂（DMSO / 水）下，CT 态能量被显著稳定 ≥ 0.5 eV：TDDFT 时记得加。

## 与其他 skill 的边界

- pka skill 已经在用 SMD。
- tadf-pipeline 默认用 toluene-PCM（D-A 体系常用 host 材料）。
