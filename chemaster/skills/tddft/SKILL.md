---
name: tddft
version: 0.1.0
description: 含时密度泛函（TDDFT）激发态计算
when_to_use: |
  - 算 UV-Vis 谱、激发能、振子强度。
  - tadf-pipeline 内部调用。
  - 用户问"S1"、"激发态"、"垂直激发能"、"振子强度"。
when_not_to_use: |
  - 仅基态：用 opt-freq。
  - 多参考体系（强关联）：用 CASSCF / NEVPT2，不在本 skill 范围。
required_mcps:
  - chem.calc.orca   # 或 psi4 / bdf
  - chem.parse.cclib
  - chem.viz
estimated_time: 5 min - 2 hours
---

# TDDFT Excited States

## 默认参数

- 泛函：ωB97X-D（长程修正，对 CT 态友好）
- 基组：def2-TZVP
- 三重态：TDA（避免 triplet instability，PITFALLS §2.8）
- 单重态：full TDDFT
- 求 5 个 singlet + 5 个 triplet

## 关键决策点

- **是否 CT 态**：用 NTO 重叠 < 0.3 或 Λ 诊断 < 0.4 判定
  - 若是 CT 且用了 B3LYP → 警告并建议切 ωB97X-D / CAM-B3LYP / LC-ωPBE
- **是否需要溶剂**：默认 PCM；H 键体系建议 SMD

## 流程

1. 读取已优化 S0 几何
2. 调 chem.calc.orca.tddft（n_singlets=5, n_triplets=5, tda_for_triplets=true）
3. 解析输出：状态能量、振子强度、轨道贡献
4. NTO 分析（chem.analysis.multiwfn.nto）
5. UV-Vis 模拟图（chem.viz.plot_uv_vis，含高斯展宽）
6. 报告

## TODO Phase 2

详细展开 + 失败模式表。
