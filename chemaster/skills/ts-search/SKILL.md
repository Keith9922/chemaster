---
name: ts-search
version: 0.1.0
description: 过渡态搜索 + IRC 验证
when_to_use: |
  - 用户要"找过渡态"、"算反应能垒"、"算活化能"。
  - 知道 R / TS 猜测 / P 三个几何（NEB / CI-NEB）或仅 R/P（Growing String）。
when_not_to_use: |
  - 仅找极小点：用 opt-freq。
  - 反应路径复杂、需要构象采样：先用 conformer。
required_mcps:
  - chem.calc.orca   # ORCA 的 NEB-TS 较成熟
  - chem.io.ase
estimated_time: 30 min - 6 hours
---

# Transition State Search + IRC

## 默认参数

- 主方法：CI-NEB-TS（ORCA）
- 备用：dimer / P-RFO
- 收敛：tight
- IRC：双向各 50 步

## 流程

1. 准备 R / P（如果只有这俩） → 跑 NEB-TS
2. TS 优化收敛后跑频率：必须有**且仅有一个**虚频
3. 沿虚频做 IRC（双向）
4. IRC 终点优化 → 验证连接到对的 R / P
5. 报告：能垒 ΔE‡、ΔG‡（用 Eyring 算速率）

## 失败模式

| 问题 | 处理 |
|---|---|
| 频率有 ≥ 2 个虚频 | 沿次要虚频位移后重新优化 |
| IRC 没回到 R 或 P | 回退到 dimer 法重找 TS |
| 能垒离谱（< 0 或 > 100 kcal/mol） | 检查 R/P 是否同自旋态、同电荷 |

## TODO Phase 3

详细展开 + ORCA NEB 输入模板。
