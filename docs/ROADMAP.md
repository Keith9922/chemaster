# ChemMaster 落地实现路线

> 计算化学领域的本地 Agent 工具 —— 类 Claude Code 形态。
> 用户用自然语言下达计算任务，Agent 规划方案、与用户确认、调用专业软件执行（本地或 HPC）、解析结果并出图、必要时迭代直到误差收敛。

本仓库（chemaster）目前已有 **PDF 化学结构抽取 + SMILES 识别**能力（见根目录 `README.md`），将作为 ChemMaster Agent 的一个子工具继续保留并被 Agent 调用。本文档描述把仓库升级成 ChemMaster Agent 的整体路线。

---

## 1. 项目定位与边界

### 1.1 产品形态

- 形态：**本地 TUI 工具**，命令名 `chemaster`，参考 Claude Code / Codex / Gemini CLI 形态。
- TUI 框架：**Textual**（Python 生态最成熟的 TUI 库）。布局：左对话流 + 右任务面板 + 底部 Plan-Confirm 卡片 + 斜杠命令（`/run`、`/edit-plan`、`/show`、`/jobs`）。
- 底层：基于 **Claude Agent SDK Python**。LLM 后端可插拔，默认 Anthropic / OpenAI 兼容 API；可替换为本地部署的 Qwen / DeepSeek / Llama，支持完全离线/国产化部署。
- 输出：TUI 展示对话与进度；产物（图表、log、输入文件、Markdown 报告）写到本地 `./runs/<task-id>/`。
- 图像处理（一期）：写盘 + 链接显示。在 iTerm2 / Kitty / WezTerm 等支持的终端里启用 inline image protocol（Sixel / Kitty / iTerm2 image）。
- 图像处理（二期）：Web/Desktop 客户端，原生嵌入 3D 分子查看器（py3Dmol / NGLView / Mol\*）。
- 配置：`~/.chemaster/config.yaml` 管理计算软件路径、HPC 凭据、LLM API、默认偏好。
- 协议：所有计算软件统一封装为 **MCP server**，工作流封装为 **Skills**，Agent 通过 Skill+MCP 双层调度。

### 1.1bis 差异化与"真正好用"的硬指标

我们对标的是 Rowan、Quantum Mobile、Schrödinger Live Design 这类商业云产品。差异化定位：

- **本地优先**：用户的分子结构不上传，对药企、材料企业、保密课题组关键。
- **BYO LLM**：API key 用户自带，可换便宜的国产模型，可本地部署，成本可控。
- **HPC 原生**：直连用户实际工作的超算，不强求迁移到供应商云。
- **完全开源**：可审计、可二次开发。

但"差异化定位"不等于"真正好用"。后者必须用可量化的硬指标承诺：

| 指标 | 目标 |
|---|---|
| 首次安装到第一个结果 | ≤ 30 分钟（含装 psi4 + xTB） |
| 新手不读手册跑通 H2O | ✓ |
| 三个月后同输入复现率 | 100%（保留所有输入、版本、随机种子、commit） |
| 离线核心功能 | ✓（除 LLM API；可换本地模型） |
| 错误自愈率 | ≥ 70%（SCF 不收敛、虚频、几何卡死等常见 case 自动恢复） |
| 报告可直接进论文 SI | ≥ 90%（自动出表、出图、写 Method 段落） |
| 相对手工流程节省人力 | ≥ 50%（在 TADF 标杆问题上测得） |

这七条进入毕设论文的"非功能需求验证"章节，逐项设计实验测量。

不做的事（毕设阶段明确不做）：
- 不做 Web 前端（最后阶段如果时间有余裕，套一个 Streamlit/Gradio 的 demo UI 给答辩用）。
- 不做实验机器人 / 合成自动化（Coscientist 的方向，与本课题无关）。
- 不做检索/合成路线规划（ChemCrow 的方向）。
- 不做新的计算引擎，所有浮点运算交给专业软件。

### 1.2 范围收敛与标杆问题

完整覆盖 Gaussian + VASP + GROMACS + 多层级方法在博士课题组也要做几年。本毕设的实际目标范围：

> **面向 TADF 发光体设计的本地化计算化学 Agent** —— 以 psi4 / ORCA / BDF / xTB 为后端，通过 Skill+MCP 双层架构封装方法论与软件接口，覆盖从 PDF 文献提取分子 → 构象搜索 → 几何优化 → TDDFT 激发态 → 自旋轨道耦合（SOC）→ Marcus 公式算 kRISC 的端到端流水线。Agent 自动完成方法分级选择、HPC 任务编排、错误自愈、可重复报告生成。在已发表 TADF 分子集上验证：精度匹配文献、相对手工流程节省 ≥ 50% 人力时间。

**为什么选 TADF（标杆问题）**：

- 当前 OLED/光物理领域热点，2024-2026 年顶刊持续输出（你 `output/` 目录里就有 P=O / N-MR-TADF 的相关论文）。
- 计算流水线天然多软件协作，正好展示 Agent 价值：xTB 构象搜索 → ORCA/BDF TDDFT → BDF SOC（BDF 在 SOC 上强）→ Marcus 算 kRISC → MultiWFN 轨道分析。
- 复用本仓库已有 PDF 结构抽取：论文 PDF → 自动抽分子 → 自动复算 → 与文献数值对比。叙事完整、demo 出彩。
- 验证标准清晰：S1/T1 能隙、振子强度、kRISC 都有可对比的实验/理论值。
- 商业产品做 TADF 全自动化的极少，差异化明显。

**Anchor cases 安排**：

- **Smoke test**（Phase 1）：H2O / NH3 / 苯环 的 opt+freq，跑通技术链路。
- **核心 anchor**（Phase 2-4）：5-10 个已发表 TADF 分子（如 4CzIPN、DMAC-DPS、P=O / N-MR 系列），跑完整 TADF 流水线。
- **扩展 anchor**（Phase 5）：从论文 PDF 自动抽 → 自动复算 → 出对比报告。

- 主要场景：TADF 流水线 + 通用小分子（< 100 原子）DFT 工作流（opt / freq / TDDFT / SOC / IRC / PES 扫描）。
- 主要后端：psi4（开源）+ ORCA（学术免费）+ **BDF（北大刘文剑组，学术免费，国产；SOC/相对论强，是 TADF 流水线的关键）** + xTB（半经验、秒级，构象搜索）。
- 次要后端（v1.0 后视情况加）：NWChem（开源）、PySCF（开源）、OpenMM（MD）、Gaussian（如果实验室有 license）。
- 目标体系：闭壳层有机分子优先；开壳层、过渡金属、周期性体系作为后期扩展。

#### 后端选型备忘（免费/开源生态盘点）

| 软件 | 开源/免费 | 主要场景 | Phase | 备注 |
|---|---|---|---|---|
| **psi4** | 开源 (BSD) | 通用 DFT/MP2/CCSD(T)，Python API 干净 | Phase 1 | 主力，conda 一键装 |
| **xTB** | 开源 (LGPL) | GFN1/GFN2 半经验，秒级 | Phase 1 | 分级方法的最底层 |
| **ORCA** | 学术免费（非开源） | DFT、TDDFT、DLPNO-CCSD(T)、激发态强 | Phase 2 | 需注册下载，社区活跃 |
| **BDF** | 学术免费（国产） | 相对论方法、激发态、PT2/CASPT2 | Phase 2 | 国产化亮点，刘文剑组北大开发；国内毕设答辩有加分 |
| **PySCF** | 开源 (Apache 2.0) | Python 原生量化，嵌入计算友好 | Phase 5 | 与 ASE/RDKit 集成最丝滑 |
| **NWChem** | 开源 (ECL 2.0) | DFT/CC，DOE 支持，可扩展到大规模 HPC | Phase 5 | HPC 友好 |
| **OpenMolcas** | 开源 (LGPL) | 多参考方法（CASPT2/CASSCF） | 视需要 | 处理强关联 |
| **GAMESS-US** | 学术免费 | 经典通用包 | 视需要 | 老牌但仍维护 |
| **MOPAC** | 开源 (LGPL, 2022 起) | PM6/PM7 半经验 | 视需要 | 教学/快速估算 |
| **OpenMM** | 开源 (MIT) | MD，Python API 优秀 | Phase 5 | 走 MD 路线时的首选 |
| **GROMACS / LAMMPS** | 开源 (LGPL/GPL) | MD | 视需要 | 经典 MD |
| **Quantum ESPRESSO / CP2K / ABINIT** | 开源 (GPL) | 周期性体系 DFT | 不在毕设范围 | 留作扩展 |
| **MultiWFN** | 免费（国产） | 波函数分析（NBO/AIM/ELF/电荷） | Phase 2 | 田鹏开发，国内毕设亮点；命令行友好可包 MCP |
| **Gaussian** | 商业 | — | 视实验室 license | 不优先支持，但 ASE 已有接口 |
| **VASP** | 商业 | — | 不在毕设范围 | — |

**结论**：Phase 1 用 psi4 + xTB 跑通闭环；Phase 2 加 ORCA 和 BDF（前者扩功能、后者扩国产化叙事）；MultiWFN 作为分析工具在 Phase 2 引入。这套组合零商业 license，毕设全程可在普通工作站和学校超算上跑。

---

## 2. 技术架构

### 2.1 六层结构（Skill + MCP 双层封装）

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 6: User Interface (Textual TUI；二期：Web/Desktop)    │
├─────────────────────────────────────────────────────────────┤
│  Layer 5: Agent Core                                         │
│   - Planner (任务规划，输出 Plan 对象)                        │
│   - Confirmation Loop (与用户三段式交互)                      │
│   - Executor (调度 Skill / 直接 MCP 调用)                     │
│   - Iterator (benchmark 驱动的自动迭代)                       │
│   - Knowledge Retriever (RAG over KB)                        │
├─────────────────────────────────────────────────────────────┤
│  Layer 4: Skills (方法论 / 工作流 / 领域知识，Markdown)       │
│   核心工作流类:                                                │
│     - skill.opt-freq        (opt + 频率确认)                  │
│     - skill.tddft           (激发态)                          │
│     - skill.soc             (自旋轨道耦合)                    │
│     - skill.ts-search       (过渡态 + IRC)                    │
│     - skill.conformer       (构象搜索 xTB→DFT 漏斗)            │
│     - skill.pes-scan        (势能面扫描)                      │
│   领域应用类:                                                  │
│     - skill.tadf-pipeline   (★ 毕设标杆：完整 TADF 流水线)    │
│     - skill.pka             (pKa 预测)                        │
│   方法专题类:                                                  │
│     - skill.dlpno-ccsdt     (DLPNO-CCSD(T) 配置陷阱)          │
│     - skill.solvation       (PCM/SMD/COSMO-RS 选择)           │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: MCP Tools (类型化的原子操作)                        │
│   - chem.calc.psi4 / orca / bdf / xtb (atomic ops)           │
│   - chem.parse.cclib                                          │
│   - chem.analysis.multiwfn                                    │
│   - chem.viz                                                  │
│   - chem.hpc.slurm                                            │
│   - chem.io.ase                                               │
│   - chem.const                                                │
│   - chem.kb (RAG)                                             │
│   - chem.pdf (复用现有 PDF 抽取)                              │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: Engines                                             │
│   - ASE (统一封装多个 QC 软件)                                │
│   - psi4 / ORCA / BDF / xTB / OpenMM                         │
│   - cclib / RDKit / py3Dmol / Matplotlib / MultiWFN          │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: Knowledge Base                                      │
│   - 公式库（确定性 Python 模块，不交给 LLM 计算）              │
│   - 方法选择规则（YAML / Markdown，供 RAG 检索）               │
│   - Benchmark 数据（GMTKN55 / TADF 文献集）                   │
└─────────────────────────────────────────────────────────────┘
```

**Skill vs MCP 分工原则**：

- **MCP** = "Agent 能 *做* 什么"。每个工具是类型化原子操作，参数清晰，行为单一。例：`chem.calc.psi4.optimize(geom, method, basis)` 返回优化后的结构和能量。
- **Skill** = "Agent 该 *如何* 处理一类问题"。Markdown 文档教 Agent：什么时候用哪个工具、参数怎么定、看到什么信号要怎么应对、什么时候该停。
- 反例（不要这样做）：把"opt 失败就重启 freq 模式位移"塞进 MCP；把"自己拼 psi4 输入文件"塞进 Skill。
- 这样分层的工程收益：Skill 文件人类可读、可由化学领域同学直接编辑；MCP 是开发者维护的稳定接口。两层独立演进。

### 2.2 知识库设计（双层）

**Layer A — 确定性公式库**（`chemaster/kb/formulas/`）
- 物理常数：直接用 `scipy.constants`，不让 LLM 报数。
- 单位换算：`pint` 包装，提供 `to_kcal_mol()`、`to_eV()`、`bohr_to_angstrom()` 等。
- 热力学公式：自由能、焓、熵、ZPE 修正、partition function 等。
- 动力学：Eyring、Arrhenius、Marcus（用于 TADF/RISC 这类应用）。
- 这一层是 **被 Agent 调用的 Python 函数**，不是给 LLM 看的文本。

**Layer B — 方法选择经验库**（`chemaster/kb/rules/`）
- 基组推荐表（按精度/成本/适用元素分类）。
- 泛函推荐表（按体系类型：有机闭壳、激发态、过渡金属、长程、色散等）。
- 收敛阈值与默认值（SCF、几何优化、频率虚频判据）。
- 失败模式与常见警告（虚频、SCF 不收敛、symmetry 跳变等）。
- 这一层是 Markdown / YAML，由 Agent **RAG 检索**后用作决策依据。
- 来源：Cramer《Essentials of Computational Chemistry》、Jensen《Introduction to Computational Chemistry》、Goerigk-Grimme 系列 benchmark 文章、ORCA / psi4 官方手册。

### 2.3 MCP 工具清单

| MCP 名称 | 形态 | 主要能力 |
|---|---|---|
| `chem.calc.psi4` | 自研 | 单点 / 优化 / 频率 / TDDFT |
| `chem.calc.orca` | 自研 | 单点 / 优化 / 频率 / TDDFT / DLPNO-CCSD(T) |
| `chem.calc.bdf` | 自研 | 相对论 / 激发态 / 多参考（国产化亮点） |
| `chem.calc.xtb` | 自研 | GFN1/GFN2 快速预筛选 |
| `chem.analysis.multiwfn` | 自研 | 波函数分析（NBO/AIM/ELF/电荷分布） |
| `chem.parse.cclib` | 自研 | 输出文件→结构化 JSON |
| `chem.io.ase` | 自研 | xyz/mol/sdf 互转、坐标变换、对称性检测 |
| `chem.viz` | 自研 | 3D 结构、轨道、UV-Vis、IR、PES 出图 |
| `chem.hpc.slurm` | 自研 | sbatch 提交 / squeue 查询 / 拉回结果 |
| `chem.const` | 自研 | 物理常数与单位换算 |
| `chem.kb` | 自研 | 知识库 RAG 检索 |
| `chem.pdf` | 自研 | 复用本仓库已有的 PDF 结构抽取（输入论文 → SMILES） |

每个 MCP 单独成包，可独立测试。Agent 编排层通过 MCP 协议调用。

---

## 3. 人机协作（Plan-Confirm-Execute）

这是产品最核心的交互范式，对应你提出的 "2(b) 人工 Check" 和 "2(c) 建议+纠偏"：

### 3.1 三段式流程

```
用户自然语言输入
      │
      ▼
┌──────────────┐
│  Plan 阶段    │  Agent 出方案：
│              │   - 推荐方法（基组/泛函/任务类型）
│              │   - 列出每个选择的"理由"和"替代选项"
│              │   - 估算计算成本（CPU·hour / 内存 / 磁盘）
│              │   - 估算预计耗时
│              │   - 列出潜在风险（收敛、虚频、对称性等）
└──────┬───────┘
       │ 输出 Plan 对象 → 渲染为终端 markdown 表格
       ▼
┌──────────────┐
│ Confirm 阶段  │  用户三种选择：
│              │   1. 接受 → 进入 Execute
│              │   2. 修改 → 用户改某项参数
│              │   3. 让 Agent 重新规划
│              │
│              │  Agent 在用户修改时执行"建议+纠偏"：
│              │   - 校验改动的合理性（KB 规则匹配）
│              │   - 若不合理（如 200 原子点 CCSD(T)/aug-cc-pVTZ）
│              │     → 反向提醒（"这会跑 ~6 个月"）
│              │   - 若合理但有更优替代 → 给出建议但不强制
└──────┬───────┘
       ▼
┌──────────────┐
│ Execute 阶段  │  Agent 自动执行：
│              │   - 生成输入文件
│              │   - 提交（本地或 SLURM）
│              │   - 实时监控（进度条 + 队列状态 + 心跳）
│              │   - 自动错误恢复（SCF 不收敛→换 guess、加阻尼）
│              │   - 输出解析与可视化
│              │   - 写最终 Markdown 报告
└──────────────┘
```

### 3.2 Plan 对象示例

```yaml
task_id: opt-freq-water-001
intent: "计算水分子的能量"
inferred_workflow: opt+freq         # Agent 推断需要做几何优化+频率确认
target_system:
  formula: H2O
  charge: 0
  multiplicity: 1
  n_atoms: 3
  initial_geometry: built-in
plan:
  - step: geometry_optimization
    method: B3LYP-D3(BJ)
    basis: def2-TZVP
    backend: psi4
    rationale: "小分子有机/无机体系，B3LYP-D3(BJ)/def2-TZVP 是社区默认的精度-成本平衡点。"
    alternatives:
      - {method: ωB97X-D, basis: def2-TZVP, why: "长程更准但贵 ~30%"}
      - {method: PBE0, basis: def2-SVP, why: "粗算用，~3 倍快"}
    estimated_cost: {cpu_minutes: 0.5, memory_gb: 1, disk_mb: 50}
  - step: frequency
    method: B3LYP-D3(BJ)
    basis: def2-TZVP
    rationale: "确认极小点（无虚频）并得到 ZPE/热修正。频率必须用与优化一致的方法。"
total_estimate:
  wall_clock: "~1 min on 4 cores"
risks: []
required_user_confirmation: true
```

### 3.3 终端 UI 示意

```
┌─ ChemMaster Plan ─────────────────────────────────────────┐
│ Task: 计算水分子的能量                                       │
│ Workflow: 几何优化 → 频率确认 (推断)                          │
│                                                            │
│  Step 1  Geometry Opt   B3LYP-D3(BJ)/def2-TZVP   psi4     │
│          理由: 小分子默认精度-成本平衡点                        │
│          替代: ωB97X-D (更准, +30%) | PBE0/def2-SVP (粗算)  │
│                                                            │
│  Step 2  Frequency      B3LYP-D3(BJ)/def2-TZVP   psi4     │
│          理由: 确认极小点，必须与优化方法一致                    │
│                                                            │
│  Estimated: ~1 min on 4 cores  •  Risks: none             │
└────────────────────────────────────────────────────────────┘

[A]ccept   [E]dit step   [R]eplan   [Q]uit  >
```

---

## 4. 分阶段开发计划

### Phase 0：仓库重构与脚手架（1 周）

- [ ] 把现有 PDF 抽取代码移到 `tools/pdf-structure-extract/` 子模块。
- [ ] 建立新的包结构：
  ```
  chemaster/
    docs/                  # 设计文档（本文档所在处）
    chemaster/             # Python 包根
      agent/               # Agent core
      mcp/                 # 自研 MCP servers (类型化原子操作)
      skills/              # ★ Skill 库 (方法论 / 工作流)
        opt-freq/
        tddft/
        soc/
        tadf-pipeline/     # ★ 毕设标杆 skill
        ...
      kb/                  # 知识库
        formulas/          # 确定性公式库
        rules/             # YAML/Markdown 规则（供 RAG）
      tui/                 # Textual TUI (替代原计划的 cli/)
    tools/                 # 已有 PDF 抽取移到这里
    tests/
    benchmarks/            # GMTKN55 / TADF 文献集
    runs/                  # 运行产物（.gitignore）
    pyproject.toml
  ```
- [ ] 安装依赖矩阵：psi4、xTB、ASE、cclib、RDKit、`mcp` Python SDK、Claude Agent SDK、**Textual**、**rich**。
- [ ] CI（pytest + ruff）。
- [ ] 起一个最简 Textual TUI 骨架（空白对话流 + 状态面板），证明 TUI 链路通。

### Phase 1：MVP 闭环 —— "算水分子"（4 周）

目标：用户输入"算水分子的能量" → Agent 出 Plan → 用户确认 → psi4 跑完 → 出报告 + 3D 图。

- [ ] `chem.const` MCP（物理常数 + 单位换算）。
- [ ] `chem.io.ase` MCP（xyz/SMILES 转结构、初始几何）。
- [ ] `chem.calc.psi4` MCP（单点 / 优化 / 频率）。
- [ ] `chem.parse.cclib` MCP。
- [ ] `chem.viz` MCP（py3Dmol 3D 图、matplotlib 简单出图）。
- [ ] Agent core：Planner + Confirmation Loop + Executor 三段式。
- [ ] CLI 入口 + REPL。
- [ ] 跑通 `H2O / H2 / CH4 / NH3 / CO2` 五个案例的 opt+freq。
- [ ] 输出 Markdown 报告（含 3D 图、能量、ZPE、热修正、频率列表）。

**验收标准**：终端里输入"算 H2O 的能量"，5 分钟内产出包含 3D 图和能量数据的 Markdown 报告。

### Phase 2：知识库 + 智能决策（4 周）

- [ ] 整理 `kb/rules/` 内容：
  - `basis_sets.yaml`（适用元素、典型用途、成本系数）
  - `functionals.yaml`（按体系类型分类、推荐场景、已知失败模式）
  - `convergence.yaml`（默认阈值、失败时的回退策略）
  - `workflows.yaml`（预定义工作流：opt+freq / TDDFT / IRC / PES scan / 溶剂化）
- [ ] `chem.kb` MCP：基于 BM25 + 向量检索的混合 RAG。
- [ ] Planner 升级：先检索 KB → 再让 LLM 推理 → 输出带引用的 Plan。
- [ ] 实现"建议+纠偏"逻辑：
  - 用户改方法时，校验 (体系大小, 方法成本) 是否合理。
  - 用 `chem.const` 内的成本模型（基于 N_basis^4 等粗略估算）给警告。
- [ ] Skill 化：把 opt+freq、TDDFT、IRC 等做成可复用的 skill 文件。

**验收标准**：用户故意输入"用 CCSD(T)/aug-cc-pVTZ 算苯环的优化"，Agent 能识别成本爆炸并主动建议替代方案。

### Phase 3：HPC 集成与监控（3 周，**学校超算账号已确认可用，先预留位置**）

- [ ] `chem.hpc.slurm` MCP：
  - SSH + sbatch 提交（paramiko 或 fabric）。
  - 状态查询（squeue）+ 队列时长估算（基于历史运行）。
  - 完成后自动 `rsync` 拉回结果。
- [ ] 任务持久化：`runs/<task-id>/state.json` 记录提交时间、jobid、状态。
- [ ] 实时监控：终端进度条（rich）+ 心跳。
- [ ] 错误恢复策略：
  - SCF 不收敛 → 自动切换 guess、调阻尼、降低基组重启。
  - 几何优化未收敛 → 调整 trust radius / 用 redundant internal coords 重启。
  - 虚频 → 沿虚频方向位移后重启 opt。

**验收标准**：可以从本地配置一个超算账号，提交一个中等体系（~30 原子）的计算任务到 SLURM 队列，Agent 自动监控并拉回结果。

### Phase 4：TADF 标杆 + 闭环迭代 —— **毕设核心创新点**（5 周）

**4.1 TADF 流水线（端到端 demo）**

- [ ] 完成 `skill.tadf-pipeline`：
  - 输入：分子 SMILES 或 xyz
  - 流程：xTB 构象搜索 → DFT 几何优化（GS）→ TDDFT（S1/T1）→ BDF SOC 计算 → Marcus 公式算 kRISC → MultiWFN 做 NTO/HOMO-LUMO 分析 → 生成 SI 风格报告
- [ ] 在 5-10 个已发表 TADF 分子（4CzIPN、DMAC-DPS、P=O / N-MR 系列）跑全流程。
- [ ] 与文献报告值对比 ΔEST、振子强度、kRISC，给出误差表。

**4.2 通用 benchmark 闭环**

- [ ] 接入 GMTKN55 子集（先选 W4-11、BH9 之类几十到一百多条数据的小子集）。
- [ ] Iterator 模块：
  - 给定测试集 + 容差 → Agent 在 (xTB, B3LYP/6-31G*, ωB97X-D/def2-TZVP, DLPNO-CCSD(T)/cc-pVTZ) 之间分级。
  - 每个体系先用便宜方法算 → 与参考值对比 → 误差超阈值的体系自动升级方法。
  - 终止条件：所有体系误差 < 阈值，或所有方法都用尽。
- [ ] 出"误差 vs 计算成本"的曲线（对比固定方法）。

**4.3 人力节省对比实验（验证"真正好用"）**

- [ ] 招 3-5 个化学专业同学手动跑 TADF 流水线，记录耗时与错误数。
- [ ] 用 ChemMaster 跑同样的分子，记录耗时与错误数。
- [ ] 计算节省比例，进入论文非功能需求验证章节。

**验收标准**：
1. TADF 流水线在 ≥ 80% 的标杆分子上，关键指标（ΔEST、kRISC）与文献误差在领域可接受范围内。
2. 分级方法策略相对"全部用 ωB97X-D"节省 ≥ 30% 计算成本。
3. 相对手工流程节省 ≥ 50% 人力时间。

### Phase 5：扩展能力（视时间，2-4 周）

- [ ] `chem.calc.orca` MCP（接入 ORCA，开放更高级方法）。
- [ ] `chem.calc.bdf` MCP（接入 BDF，国产化叙事 + 相对论/激发态能力）。
- [ ] `chem.analysis.multiwfn` MCP（波函数分析）。
- [ ] `chem.calc.openmm` MCP（接入 MD，做溶剂化的 QM/MM 简单工作流）。
- [ ] 复用本仓库已有 `chem.pdf` 工具：用户给一篇论文 PDF → Agent 抽取分子结构 → 自动复算 → 与论文报告值对比。这是一个非常出彩的 demo 场景。
- [ ] Streamlit / Gradio 的 demo UI（仅用于答辩展示）。
- [ ] Plugin manifest 导出：让别人可以在 Claude Code 里直接装用。

### Phase 6：文档与发布（1 周）

- [ ] README、安装指南、tutorial（5 个跑通的案例）。
- [ ] 录屏 demo。
- [ ] 毕设论文初稿。

---

## 5. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| LLM 在方法选择上幻觉 | 给出不合理的基组/泛函组合 | 强制经过 KB 检索 + 规则校验，关键决策不让 LLM 自由发挥 |
| 计算软件 license / 平台兼容 | psi4 / ORCA 在 Windows 上易出问题 | 优先支持 macOS + Linux；Windows 用 WSL2 |
| HPC 队列等待时间不可控 | 影响交互体验 | 提供"本地小算+HPC 大算"双轨；Agent 能在等待时干别的 |
| 化学单位/对称性常见 bug | 结果偏离量级 | MCP wrapper 层做强校验；所有数值带单位用 pint |
| Benchmark 范围太大跑不完 | Phase 4 卡住 | 选 W4-11 (~140 数据点) 这种小子集，确保能在合理时间跑完 |
| 论文 demo 不够亮眼 | 答辩拿不到高分 | Phase 5 的"读论文-自动复算-对比"是非常吸引人的 demo |

---

## 6. 与已有工作的差异化

| 项目 | 主要场景 | 与 ChemMaster 的差异 |
|---|---|---|
| ChemCrow (2023) | 合成化学、检索、反应预测 | 不做计算化学，工具集合完全不同 |
| Coscientist (Nature 2023) | 实验机器人、自主合成 | 不做仿真计算 |
| El Agente / MD-Agent 等 | 部分覆盖 MD 或 QC | 多为概念性 demo，未做 benchmark 闭环验证 |
| **ChemMaster** | **小分子量化全流程 + 自动方法分级 + benchmark 闭环验证** | **本毕设核心** |

---

## 7. 立即可以开始的下一步

按依赖顺序：

1. **完成 Phase 0 的仓库重构**（移现有 PDF 代码到 `tools/`，建立新包结构）。
2. **写 `chem.const` MCP**（最简单，用来跑通 MCP 协议链路）。
3. **写 `chem.io.ase` MCP**（输入处理）。
4. **写 `chem.calc.psi4` MCP**（核心计算）。
5. **拼出最简 Agent**（先不做 KB，硬编码方法选择，跑通 H2O 闭环）。
6. **再回头做 KB + Planner 智能化**。

每个 MCP 都先写最小可用版本（一两个方法/参数），跑通后再扩展。先做"端到端能跑"，再做"每个环节都精"。

---

---

## 8. Phase 6 — 文档与论文（1 周）

- [ ] README、安装指南、tutorial（5 个跑通的案例）
- [ ] 录屏 demo（H2O / 4CzIPN / PDF→复算 三个场景）
- [ ] mkdocs 站点部署到 GitHub Pages
- [ ] CITATION.cff
- [ ] 毕设论文初稿

---

## 9. Phase 7 — 打包与发布（1-2 周）

完整指南见 [`PACKAGING.md`](PACKAGING.md)。优先级与里程碑：

### 9.1 P0 — PyPI + conda-forge

- [ ] `pyproject.toml` metadata 完善（已就位，进 release 前 review）
- [ ] 把 version bump 到 `1.0.0a1`
- [ ] `python -m build` + `twine check` 本地通过
- [ ] 测试 release 到 [TestPyPI](https://test.pypi.org)
- [ ] 正式 release 到 PyPI（`twine upload dist/*`，或用 OIDC trusted publisher）
- [ ] 提交 conda-forge staged-recipes（`grayskull pypi chemaster` 自动生成 recipe）
- [ ] 等待 conda-forge bot 合并 + 创建 feedstock

### 9.2 P0 — GitHub Release + 一键安装脚本

- [ ] 打 git tag `v1.0.0a1`
- [ ] CI 自动构建 wheel + sdist 上传到 GitHub Release Assets
- [ ] `install.sh` 写好（详见 [`PACKAGING.md`](PACKAGING.md) §9）
- [ ] README 顶部加 badges（PyPI、CI、coverage）

### 9.3 P1 — Docker

- [ ] `Dockerfile.slim`（仅 chemaster 包）
- [ ] `Dockerfile.full`（含 psi4 + xTB + cclib + RDKit）
- [ ] CI 推到 GHCR：`ghcr.io/<user>/chemaster:slim` 与 `:full`
- [ ] 文档示范："`docker run -v $PWD:/data ghcr.io/<user>/chemaster eval data/h2o.yaml`"

### 9.4 P1 — Homebrew tap

- [ ] 建仓库 `homebrew-tap`
- [ ] `Formula/chemaster.rb`
- [ ] 测试 `brew install <user>/tap/chemaster`

### 9.5 P2 — Claude Code Plugin

- [ ] 仓库根加 `plugin.json`（已含示例，详见 [`PACKAGING.md`](PACKAGING.md) §6）
- [ ] 提交到 Claude Code plugin marketplace
- [ ] 文档示范 `/plugin install <user>/chemaster`

### 9.6 P2 — 学术发布

- [ ] `CITATION.cff` 写完
- [ ] 投 [JOSS](https://joss.theoj.org/)（Journal of Open Source Software）拿正式引用 DOI
- [ ] 配 Zenodo 自动 archive

### 9.7 验收标准

- 一个**完全没接触过项目**的化学专业研究生：
  1. 5 行命令内装上能用
  2. 能跑通 H2O smoke test
  3. 看完 README + tutorial 能跑通自己的分子
- PyPI / conda-forge 都能搜到 `chemaster`
- CI 全绿、文档站可访问、Release notes 写清亮点+破坏性变更+修复

---

## 10. 整体 Phase 时间表（毕设视角）

| Phase | 内容 | 周数（estimated） | 验收 |
|---|---|---|---|
| 0 | 仓库重构 + 脚手架 + TUI 骨架 | 1 | `chemaster` 能进 REPL |
| 1 | MVP 闭环：H2O opt+freq | 4 | 输入"算 H2O 的能量" 5 分钟内出报告 |
| 2 | 知识库 + Skill 智能化 | 4 | 用户选 CCSD(T)/aug-cc-pVTZ 算苯环 → Agent 主动警告 |
| 3 | HPC（学校超算）集成 | 3 | 提交 30 原子任务到 SLURM 自动拉回 |
| 4 | TADF 流水线 + benchmark + 真人对照 | 5 | 5-10 个 TADF 分子误差合格；人力节省 ≥ 50% |
| 5 | 扩展（ORCA/BDF/MultiWFN/PDF→复算 demo） | 2-4 | "读论文-自动复算" 端到端 demo |
| 6 | 文档 + 论文 | 1 | 初稿完成 |
| 7 | **打包发布**（PyPI / Homebrew / Docker / Plugin） | 1-2 | 1.0.0a1 发布；docker 镜像可用；至少 PyPI 可装 |

总计约 **21-24 周**（5-6 个月），符合一个本科毕设的实际工作量上限。

---

## 11. 文档索引

写代码前读：

| 文档 | 用途 |
|---|---|
| [`../CLAUDE.md`](../CLAUDE.md) | Agent 协作主入口（**新会话第一个读**） |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 六层架构详解 |
| [`SETUP.md`](SETUP.md) | 开发环境搭建 |
| [`PITFALLS.md`](PITFALLS.md) | **写每个 MCP/Skill 前必读** |
| [`MCP_GUIDE.md`](MCP_GUIDE.md) | 写 MCP server 时 |
| [`SKILLS_GUIDE.md`](SKILLS_GUIDE.md) | 写 Skill 时 |
| [`CONVENTIONS.md`](CONVENTIONS.md) | 代码规范 |
| [`TADF_PIPELINE.md`](TADF_PIPELINE.md) | 写 tadf-pipeline skill 时 |
| [`PACKAGING.md`](PACKAGING.md) | Phase 7 发布前 |

---

*文档状态：v0.4。三轮反馈调整：(1) 加 Phase 6 文档/论文 + Phase 7 完整打包发布章节；(2) 加整体时间表；(3) 加文档索引；(4) 与 PACKAGING.md / PITFALLS.md / MCP_GUIDE.md / SKILLS_GUIDE.md 全面交叉引用。下一轮：实质开发开始前的最后一次 review。*
