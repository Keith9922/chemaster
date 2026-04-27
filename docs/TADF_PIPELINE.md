# TADF_PIPELINE — 标杆问题详解

> 毕设的核心 demo。Phase 4 重点。

---

## 1. 背景：什么是 TADF

**TADF** (Thermally Activated Delayed Fluorescence，热激活延迟荧光) 是 OLED 第三代发光材料的核心机制。理想 TADF 分子需要：

1. **小 ΔEST**（S1 与 T1 能隙小，通常 < 0.3 eV）→ 反向系间窜越（RISC: T1 → S1）容易。
2. **足够的 SOC**（自旋轨道耦合 > 0.1 cm⁻¹）→ RISC 速率不至于太慢。
3. **适中的振子强度** f(S1)（不能太小，否则发光弱）。
4. **kRISC ≥ 10⁵ s⁻¹** 是工业可用的门槛。

设计 TADF 分子的核心是用计算预测以上指标，在合成前筛选候选。

---

## 2. 计算流水线

```
SMILES / 论文 PDF
   │
   ├─→ chem.pdf.extract_structures (如果输入是 PDF)
   ▼
┌─────────────────────────────────────┐
│ Step 1: 构象搜索 (skill.conformer)   │
│   xTB + CREST iMTD-GC               │
│   保留 Boltzmann 权重 > 1% 的构象     │
└─────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────┐
│ Step 2: 基态优化 (skill.opt-freq)    │
│   ωB97X-D / def2-SVP                │
│   每个构象单独优化 + 频率确认          │
│   选最稳定 + 无虚频                  │
└─────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────┐
│ Step 3: TDDFT (skill.tddft)         │
│   ωB97X-D / def2-TZVP, TDA          │
│   计算 S1 与 T1 (前 5-10 态)         │
│   提取: E(S1), E(T1), f(S1)          │
│   ΔEST = E(S1) - E(T1)              │
└─────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────┐
│ Step 4: SOC (skill.soc, BDF)         │
│   BDF X2C-TDA 或 RKS-TDDFT-SOC      │
│   <S1|HSO|T1> 矩阵元 (cm⁻¹)         │
└─────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────┐
│ Step 5: 重组能 λ                    │
│   ΔE_4-point method (Nelsen)         │
│   或用 Marcus 模型简化               │
└─────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────┐
│ Step 6: kRISC 计算                  │
│   Marcus-Levich-Jortner 或 Marcus    │
│   (chemaster.kb.formulas.photophysics)│
└─────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────┐
│ Step 7: 轨道分析 (chem.analysis.    │
│         multiwfn)                   │
│   NTO 分析 S1 / T1 性质 (LE / CT)   │
│   HOMO-LUMO gap, dihedral 与共轭性   │
└─────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────┐
│ Step 8: 报告                        │
│   ΔEST, f(S1), <SOC>, kRISC,        │
│   构象图, 轨道图, 与文献对比          │
└─────────────────────────────────────┘
```

---

## 3. 默认参数（**chem.kb.rules 里写死，不让 LLM 改**）

| 量 | 默认 | 备注 |
|---|---|---|
| 构象搜索方法 | xTB GFN2 + CREST iMTD-GC | 半经验快速 |
| 基态泛函 | ωB97X-D | 长程修正，对 D-A 体系准 |
| 基态基组 | def2-SVP（优化）→ def2-TZVP（单点/激发态） | 漏斗 |
| TDDFT 方法 | TDA（三重态）/ 全 TDDFT（单重态） | 见 PITFALLS §2.8 |
| 隐式溶剂 | 默认 toluene (PCM)，可选 dichloromethane / film | OLED 真实环境 |
| SOC 软件 | BDF | ORCA 的 RI-SOMF 备用 |
| 温度 | 298.15 K | |
| 重组能方法 | 4-point | |

---

## 4. 标杆 anchor 分子（Phase 4 验证集）

| 分子 | 来源 | ΔEST 文献值 (eV) | kRISC 文献值 (s⁻¹) |
|---|---|---|---|
| 4CzIPN | Adachi 2014 (Nature) | ~0.10 | 5×10⁶ |
| DMAC-DPS | Adachi 2014 | ~0.10 | 1×10⁶ |
| 2CzPN | Adachi 2012 | ~0.21 | 7×10³ |
| ACRSA | 多篇 | ~0.05 | 1×10⁵ |
| 4CzTPN-Ph | Adachi 2014 | ~0.16 | — |
| (你 PDF 抽出的 P=O / N-MR) | 2025 JPCL | 待提取 | 待提取 |

每个分子的参考几何与文献值放在 `benchmarks/tadf-literature/<molecule>.yaml`。

---

## 5. 验收指标

毕设 Phase 4 验收：

| 指标 | 目标 | 测量 |
|---|---|---|
| ΔEST 平均绝对误差 | < 0.05 eV | 与文献对比 |
| 振子强度数量级一致 | ≥ 80% 分子 | 与文献对比 |
| <SOC> 数量级一致 | ≥ 80% | 与文献对比 |
| kRISC 数量级一致 | ≥ 70% | log10(k) 误差 < 1 |
| 端到端耗时（< 50 atom 分子） | < 4 小时 (本地) / < 1 小时 (HPC) | 真测 |
| 人力对照实验：节省时间 | ≥ 50% | 见下 |

### 5.1 真人对照实验设计

招 3-5 个化学专业本科或研究生，分两组：

- A 组（手动）：用 Gaussian/ORCA 手动跑一个标杆分子的 TADF 流水线。
- B 组（ChemMaster）：用 chemaster 跑同一个分子。

记录：

- 总耗时（不含计算时间，只算用户操作时间）。
- 错误次数（输入文件错、忘写参数、文件没保存等）。
- 主观评分（1-5 分量表）。

预期：B 组人力节省 ≥ 50%（毕设论文非功能需求章节的核心实验）。

---

## 6. tadf-pipeline skill 编排

`chemaster/skills/tadf-pipeline/SKILL.md`：

```yaml
---
name: tadf-pipeline
description: 完整 TADF 发光体计算流水线（构象→DFT→TDDFT→SOC→kRISC）
when_to_use: |
  - 用户要"算 X 的 TADF 性质"、"评估 X 的 OLED 适用性"。
  - 给定 SMILES 或 xyz，要 ΔEST、振子强度、kRISC。
required_skills:
  - conformer
  - opt-freq
  - tddft
  - soc
required_mcps:
  - chem.calc.xtb
  - chem.calc.orca   # 或 psi4
  - chem.calc.bdf
  - chem.analysis.multiwfn
  - chem.viz
  - chem.kb
estimated_time: 2-8 hours (本地) / 30-90 min (HPC)
---
```

---

## 7. 与现有 PDF 抽取的衔接

本仓库已有 `tools/pdf-structure-extract/`（来自现 README）。流程：

```
用户：分析这篇论文的 TADF 分子
   │
   ▼
chem.pdf.extract_structures(pdf_path)
   ├─→ output/chemical_structure_candidates/<paper>/
   ├─→ SMILES 列表（已规范化）
   └─→ 候选裁剪图
   │
   ▼
人工 / 半自动 review SMILES（保证抽取准确）
   │
   ▼
对每个 SMILES 调 tadf-pipeline skill
   │
   ▼
聚合报告：每个分子的 ΔEST / kRISC + 与论文报告值对比
```

这是毕设的明星 demo —— **"读论文-自动复算-生成对比报告"**。

---

## 8. 论文写作要点（毕设论文章节建议）

- **§1 引言**：TADF 在 OLED 的地位 + 当前计算流水线的人力瓶颈。
- **§2 相关工作**：ChemCrow、Coscientist、商业 TADF 计算工具（如 Schrödinger 的 Excited States workflow）。
- **§3 系统设计**：六层架构 + Skill+MCP 双层。
- **§4 TADF 流水线**：本文档内容。
- **§5 实验**：anchor 分子精度验证 + 真人对照实验 + GMTKN55 通用 benchmark。
- **§6 案例研究**：从 P=O / N-MR-TADF 论文 PDF 自动抽取并复算。
- **§7 讨论**：差异化、局限、未来工作。
- **§8 结论**。

---

*文档版本：v1.0 (2026-04)。*
