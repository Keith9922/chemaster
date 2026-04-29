# SKILLS_GUIDE — 怎么写 Skill

> 写每个 `chemaster/kb/skills/<name>/SKILL.md` 之前读这个。
>
> ⭐ **V2 架构变更（2026-04-29）**：
> - 路径：`chemaster/skills/` → `chemaster/kb/skills/`
> - 定位：Skill **不再是架构层 / 不再做触发匹配**，是 Agent 通过 `use_skill` 工具按需读取的 markdown 文档（参考 EvoMaster 的 SkillTool 模式）
> - frontmatter 简化：`when_to_use` / `when_not_to_use` 仍可保留作描述，但不再作为路由触发器
> - 不需要再"在 workflows.yaml 注册触发规则"
> - 不需要再做"5+ 正例 / 5+ 反例"触发率测试
>
> 见 [CLAUDE.md §2.2](../CLAUDE.md#22-skill-是工具不是架构层v2-关键变化)。

---

## 1. Skill 是什么

Skill 是教 Agent **如何处理一类问题**的 Markdown 文档。Agent 看到匹配的用户意图就加载对应 skill，按 skill 的指引调 MCP 工具。

**Skill ≠ MCP**：

- MCP 是"动词"（能做什么）。
- Skill 是"剧本"（怎么处理这类问题）。

---

## 2. Skill 文件结构

每个 skill 是 `chemaster/skills/<kebab-case-name>/`：

```
chemaster/skills/opt-freq/
├── SKILL.md            # 必须，主入口
├── examples/           # 可选，正例 prompt
│   └── h2o.md
└── references/         # 可选，给 Agent 检索的参考材料
    └── convergence.md
```

`SKILL.md` 是核心。

---

## 3. SKILL.md 模板

```markdown
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
  - 仅快速估算单点：用 single-point（如有此 skill），或直接调 chem.calc.*.single_point。
  - 多构象搜索：先用 conformer skill。
required_mcps:
  - chem.calc.psi4    # 或 chem.calc.orca / chem.calc.xtb
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

1. 准备初始几何（SMILES → 3D 或用户给的 xyz）。
2. 几何优化。
3. 频率计算（与优化用相同 method/basis）。
4. 检查虚频；若有，沿模式位移后重启优化。
5. 提取热力学量（ZPE、H_corr、G_corr）。
6. 出 3D 图与报告。

## 默认参数

- method: `B3LYP-D3(BJ)`
- basis: `def2-TZVP`
- engine: `psi4`（首选；ORCA 备用）
- temperature: 298.15 K
- pressure: 1 atm
- charge / multiplicity: 用户提供，否则按"中性 + 偶电子单重 / 奇电子双重"自动推断

## 详细步骤

### Step 1 — 初始几何

如果用户给了 xyz，直接用。
如果给了 SMILES：

```
chem.io.ase.smiles_to_xyz(smiles=<smiles>, embed_n_conformers=10, optimize_force_field="UFF")
```

如果连 SMILES 都没有（"算水分子"这种）：

```
chem.io.ase.lookup_by_name(name="water")
```

### Step 2 — 几何优化

```
chem.calc.psi4.optimize(
  geometry=<xyz>,
  charge=<charge>,
  multiplicity=<mult>,
  method="B3LYP-D3(BJ)",
  basis="def2-TZVP",
  convergence="tight",
)
```

**若 ok=False**：

| error_code | 处理 |
|---|---|
| SCF_NOT_CONVERGED | 见 §"SCF 失败恢复" |
| GEOMETRY_NOT_CONVERGED | 见 §"几何优化失败恢复" |
| UNSUPPORTED_ELEMENT | 切换 basis（见 chem.kb.search basis_for_element） |

### Step 3 — 频率计算

**重要**：必须用与 optimize 相同的 (method, basis)。

```
chem.calc.psi4.frequency(
  geometry=<optimized_xyz from step 2>,
  charge=<charge>,
  multiplicity=<mult>,
  method="B3LYP-D3(BJ)",      # 与 step 2 完全一致
  basis="def2-TZVP",          # 与 step 2 完全一致
  temperature=298.15,
  pressure=1.0,
)
```

返回值含 `frequencies`（cm⁻¹），`zpe`，`thermal_corrections`。

### Step 4 — 虚频检查

```
imaginary = [f for f in result.frequencies if f < -10]   # < -10 cm⁻¹ 才算
```

如果有虚频：

1. 找绝对值最大的虚频 mode i。
2. 调 `chem.io.ase.displace_along_mode(geom, mode_i, amplitude=0.1)` 得到位移后几何。
3. 回到 Step 2 重新优化。
4. 最多 3 轮；3 轮仍有虚频 → 报告"疑似过渡态"，请用户决策（可能要切到 ts-search）。

### Step 5 — 解析与可视化

```
chem.parse.cclib.parse_output(output_file=<step 3 output>)
chem.viz.plot_3d(geometry=<final xyz>, output="figures/geometry.png")
chem.viz.plot_ir(frequencies=<freqs>, intensities=<ir_int>, output="figures/ir.png")
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

---

## SCF 失败恢复策略

按顺序尝试，直到收敛或所有策略用尽：

1. **换初猜**：guess=GWH（默认 SAD 失败常见）
2. **加阻尼**：damping=0.5，DIIS 关掉前 5 步
3. **降基组先收敛**：用 def2-SVP 算到收敛 → 用其密度作 def2-TZVP 的 guess
4. **关对称性**：symmetry=c1
5. **报告失败给用户**：含已尝试策略与各自 final_residual

---

## 几何优化失败恢复策略

1. 切冗余内坐标：coordinate_system=redundant_internal
2. 减小初始 trust radius 到 0.1
3. 改用 RFO 优化器
4. max_iter 增加到 500
5. 报告失败

---

## 与其他 skill 的衔接

- 后续 TDDFT：把 step 5 的 optimized_geometry 直接传给 tddft skill。
- 后续 SOC（TADF）：用 tadf-pipeline 整体调度，不要单独触发本 skill。
- 后续 IRC（鞍点）：本 skill 不适用，路由到 ts-search。

---

## 验证 / 测试

参见 `examples/h2o.md`。

测试输入：
```
算 H2O 的能量
```

期望产出：
- `runs/<id>/` 含完整 step_01_optimize / step_02_frequency 目录
- `report.md` 含 3D 图、能量 ≈ -76.4 Hartree、无虚频
- 总耗时 < 5 minutes
```

---

## 4. 编写要点

### 4.1 Frontmatter 必填

- `name`: 与目录名一致（kebab-case）。
- `description`: 一句话。
- `when_to_use` / `when_not_to_use`: **决定触发率的关键**。写具体场景，不写抽象描述。
- `required_mcps`: 列出依赖。

### 4.2 步骤要可执行

每一步给出**确切的 MCP 调用与参数**，不要写"调用 psi4 优化它"这种抽象描述。

### 4.3 错误恢复必须写

每个可能失败的步骤后跟"若 X 错误码该怎么办"。这是 Skill 比单 MCP 强的核心价值。

### 4.4 与其他 skill 的边界

明确"什么时候应该路由到别的 skill" —— 防止 skill 误触发。

### 4.5 引用要给来源

`references` 段列出文献或文档。出现在报告里时带 DOI/页码。

### 4.6 不要让 Agent 自由发挥关键参数

method、basis、收敛阈值这些必须在 skill 里写死或写明决策树，不能让 LLM 自己拍脑袋。

---

## 5. Skill 测试

```bash
# 列出所有 skill
chemaster skills list

# 测试 skill 触发
chemaster skills test opt-freq --prompts examples/h2o.md

# 看 skill 是否会被指定 prompt 触发
chemaster skills route --prompt "算水分子的能量"
# 输出: matched skill: opt-freq (confidence 0.95)
```

---

## 6. 命名规则

- skill 目录：kebab-case，例 `opt-freq`、`tadf-pipeline`、`ts-search`。
- skill `name` frontmatter 与目录名一致。
- 同领域 skill 用相同前缀：`pka` / `pka-with-explicit-water`、`tddft` / `tddft-cosmo`。

---

## 7. 已规划 skill 清单

| Skill | Phase | 说明 |
|---|---|---|
| opt-freq | 1 | ★ 优化+频率，最基础 |
| conformer | 2 | xTB + DFT 漏斗，构象搜索 |
| tddft | 2 | 激发态计算 |
| soc | 2 | 自旋轨道耦合（BDF） |
| ts-search | 3 | 过渡态搜索 + IRC |
| pes-scan | 3 | 势能面扫描 |
| dlpno-ccsdt | 3 | DLPNO-CCSD(T) 单点 |
| solvation | 3 | PCM/SMD/COSMO-RS 决策 |
| pka | 4 | pKa 预测 |
| **tadf-pipeline** | 4 | ★★★ 毕设标杆 skill，调度上面所有 skill |

---

## 8. Checklist（每个 skill 完成前过）

- [ ] frontmatter 完整（name、description、when_to_use、required_mcps）
- [ ] 流程步骤可执行（具体 MCP 调用 + 参数）
- [ ] 错误恢复策略写完
- [ ] 与其他 skill 的边界明确
- [ ] `examples/` 至少 1 个完整正例
- [ ] `chemaster skills test <name>` 通过
- [ ] 触发率：5+ 正例 prompt 全触发，5+ 反例 prompt 不触发
- [ ] 在 `kb/rules/workflows.yaml` 登记

---

*文档版本：v1.0 (2026-04)。*
