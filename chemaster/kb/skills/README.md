# Skills

> 每个 skill 是教 Agent **如何处理一类问题**的 Markdown 文档。
> 写法见 [`docs/SKILLS_GUIDE.md`](../../docs/SKILLS_GUIDE.md)。

## 已规划的 skill

| Skill | Phase | 状态 | 说明 |
|---|---|---|---|
| [opt-freq](opt-freq/) | 1 | 框架 | ★ 优化+频率，最基础 |
| [conformer](conformer/) | 2 | 框架 | xTB + DFT 漏斗 |
| [tddft](tddft/) | 2 | 框架 | 激发态 |
| [soc](soc/) | 2 | 框架 | 自旋轨道耦合（BDF） |
| [ts-search](ts-search/) | 3 | 框架 | 过渡态 + IRC |
| [pes-scan](pes-scan/) | 3 | 框架 | 势能面扫描 |
| [dlpno-ccsdt](dlpno-ccsdt/) | 3 | 框架 | DLPNO-CCSD(T) |
| [solvation](solvation/) | 3 | 框架 | PCM/SMD/COSMO-RS |
| [pka](pka/) | 4 | 框架 | pKa 预测 |
| **[tadf-pipeline](tadf-pipeline/)** | 4 | 框架 | ★★★ 毕设标杆 |

## 加新 skill 的步骤

1. 建目录：`chemaster/skills/<kebab-case-name>/`
2. 写 `SKILL.md`（参照 [`docs/SKILLS_GUIDE.md`](../../docs/SKILLS_GUIDE.md) §3 模板）
3. 在 `kb/rules/workflows.yaml` 登记
4. 跑触发率测试：`chemaster skills test <name>`
