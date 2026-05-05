# ChemMaster 修改计划（Refactor Plan）

> 记录与用户对齐过的修改方向。等代码动起来时按本文执行。
>
> **设计哲学锚点**：ChemMaster 是 **labor-saving collaborator，不是 autonomous decision-maker**。
> Agent 吸收重复劳动，化学决策权完整保留给研究者。决策权可通过权限分级表向下委托给 agent，但用户始终掌握权限调整权。

---

## 0. 对齐决策清单（v2）

本节是与用户对齐过的关键决策。后面的章节都按这里的口径执行。

### 0.1 项目定位

**ChemMaster 是一个本地运行、大模型驱动、终端原生的通用计算化学 Agent 系统。**核心目标是吸收"输入构造 → 任务提交 → 错误重试 → 结果解析"这条提交链路上的重复劳动；化学决策权（方法、基组、泛函、溶剂模型、多重度等）保留给研究者，但通过权限分级表向 agent 委托一部分常规决策。

形态参照 Claude Code / Codex：终端原生、自然语言驱动、插件化（MCP）、多前端（CLI / TUI / 本地 Web）。

### 0.2 论文题目

> **基于大模型 Agent 与 MCP 协议的本地化计算化学任务自动化系统 ChemMaster**
> **—— 设计、实现与基础计算能力验证**

副标题口径："设计 + 实现 + 基础验证"，**不限定 TADF / AIE / 光物理等具体领域**。验证目的是证明系统在标准 benchmark 上可靠，不是证明某个化学发现。

### 0.3 验证范围

3 个公开 benchmark 同时支撑两条 claim：(a) 基础计算能力，(b) 跨任务类型的泛化能力。**不做 TADF 应用层验证**，相关方向放进 §6 未来工作。

| Benchmark | 测什么 | 工具链 | 支撑 claim |
|---|---|---|---|
| **S22 子集**（5 体系）| 基态弱相互作用结合能精度 | Gaussian | 基础 |
| **QUEST 子集**（3-5 分子）| 垂直激发能精度 | Gaussian TDDFT | 基础 + 跨任务 |
| **蒽 (anthracene)** | MOMAP TVCF 在简单 PAH 上的速率精度（荧光 + 磷光）| Gaussian + BDF + MOMAP | 基础 + 多软件协作泛化 |

三类任务（基态结构 / 激发态能级 / 速率与动力学）覆盖了 ChemMaster 工具链的三个不同断面。师姐 case 作为可选 supplementary，写进 §5.4 案例章节而非主 benchmark。

### 0.3.1 商业云 HPC 接入的 scope 调整

**当前阶段**：只做接口设计与代码占位，**不做端到端真实接入**。

具体范围：
- 调研并行科技 / 鸿之微等商业云的 SLURM 接入文档，记录认证、提交、文件分区等关键信息到 `docs/HPC_PLATFORMS.md`
- 在 `chemaster/mcp/hpc_slurm/` 设计可扩展的 platform adapter 接口（基于现有 paramiko SSH 层）
- 写一个 `local_slurm` 占位 adapter（可在本地 Docker 跑通最小 SLURM 演示，证明接口设计成立）
- **真实商业云接入推到论文 §6 未来工作**

理由：商业云接入涉及账号、配额、单独调研，时间不可控。本毕设把"接口预留 + 本地 SLURM demo"作为成立证据即可。

### 0.4 权限分级（recommend 机制的优化）

`recommend` 不是"所有化学决策都问用户"，而是按预设权限分级。配置文件位于 `~/.chemaster/policy.yaml`（用户可调）。

| Level | 范围 | Agent 行为 |
|---|---|---|
| L1（自主）| 输入文件语法微调、guess=GWH、damping、网络/磁盘类 retry | Silent，记录到 trajectory |
| L2（推荐+确认）| 常规方法/基组/泛函选择、虚频处理、溶剂模型 | 用 `recommend` 提交，用户接受/改/取消 |
| L3（必须用户决断）| L2 重试仍失败、多重度模糊、TS vs 极小值判定、改换软件后端 | 用 `ask_user` 强制升级，不接受默认值 |

默认权限：所有用户先体验 L2-默认；老手可以把若干 L2 项调成 L1（自主），让 agent 更省事。

### 0.5 第二梯队工作必做

- **Textual TUI 必做**：演示属性优先
- **本地 Web 前端必做**：评委直观感受 + 论文配图加分

第三梯队（ORCA/psi4/xTB 深度真接入、MultiWFN）保留代码作通用性演示，不做实际验证，写进 §6 未来工作。

### 0.6 相关工作章节侧重

§2 相关工作的笔墨分布（**Agent 类为主，系统类带过**）：

| 子章节 | 内容 | 估计笔墨 |
|---|---|---|
| §2.1 计算化学软件生态 | Gaussian/BDF/MOMAP 简介 | 1 页 |
| §2.2 计算化学自动化工作流系统 | ASE / AiiDA / Atomate / Rowan / Schrödinger Live Design | 2 页 |
| **§2.3 大模型 Agent 与化学**（重点）| ChemCrow / Coscientist / 其他 | 4-5 页 |
| §2.4 MCP 协议与 LLM 工具生态 | MCP 简介 + 现有化学相关 MCP | 1-2 页 |
| §2.5 与本工作的对比与差异 | 表格对比 + 差异化分析 | 2-3 页 |

### 0.7 §5 必含 "Use Cases" 章节

不只列误差表，要写**叙述性的 2 个案例**（从原 4 个案例减到 2 个，减少臃肿）：
1. 本地端到端：从自然语言指令到完整结果（CLI / TUI / Web 三前端等价演示）
2. MCP 在 Claude Code 中复用（**必须实际跑通后才能写**，未验证不允许写进论文）

其余 2 个案例（商业云长任务、多分子批处理）写进附录 A，不占主章节。

### 0.8 章节合并：§3 §4 → "系统设计与实现"

应化学评审"结构臃肿"的反馈，把原 §3 系统总体设计 + §4 关键技术与实现合并为：

> **第 3 章 系统设计与实现**

下设 8-9 个二级节，把"设计意图 + 实现细节"放在同一节内讲。一级章节减为 5 章。新章节结构详见本文 §最末「最终章节大纲」。

### 0.9 多前端的论证定位（Web 不是自嗨）

CLI / TUI / Web 三前端是 ChemMaster 的**有意架构选择**，对应不同使用场景与受众，**不是 vanity feature**：

| 前端 | 主要场景 | 受众 |
|---|---|---|
| **CLI** | SSH 远程开发、脚本化、HPC 登录节点 | 熟悉命令行的研究者、HPC workflow |
| **TUI** | 终端内交互式探索、长任务实时进度可视化 | 重度 terminal 用户但需要可视反馈 |
| **Web** | 直观操作、结构/能级/光谱可视化、demo 与对外展示 | **不熟悉 CLI 的化学研究者、学生、合作者** |

**Web 前端直接服务 ChemMaster 的核心 claim**："吸收 repetitive labor" 必须能被广泛的研究者使用，CLI/TUI 把不少化学家挡在门外，Web 是 accessibility 维度的解。论文 §3.x 多前端章节要明确写出这个论证。

但**Web 实施仍需控制 scope**——只做最小可用版（chat box + task list + 结构/光谱可视化 + 提交按钮），不追求完整产品级 UI。

### 0.10 必须在动笔前完成的代码工作

应化学评审"未爆雷"的反馈，以下两项**必须在论文写作前跑通**，否则相关 claim 不允许进入论文：

**(a) MCP 跨客户端复用 demo（半天）**
- 把 `chem.const` 或 `chem.kb` 等简单 MCP 挂到 Claude Code（或其他 MCP 客户端）
- 截图证明可调用、能返回正确结果
- 跑通后才允许在 §1.3 贡献章节和 §3.4.3 写入相关 claim

**(b) 工程指标测量协议（[BENCHMARK_PROTOCOL.md](docs/BENCHMARK_PROTOCOL.md)，1 天）**
- 提交摩擦时间节省率：被试人数 ≥ 3、计时起止点定义、每被试 anchor 数 ≥ 3、统计处理方式
- 技术性故障自动恢复率：故障注入清单、注入次数、判定标准
- 化学决策推荐接受率：被试人数 ≥ 2、anchor 数 ≥ 5、接受/override 判定标准
- 协议先写，再做实验，论文里引这份协议

---

---

## 1. Prompt 修正

### 1.1 原则性修改：System Prompt 重写

**目标文件**：`chemaster/agent/system_prompt.md`

**(a) 新增第 0 条原则**（放在所有原则之前）：

> **0. You are a labor-saving collaborator, not an autonomous decision-maker.**
> Your job is to absorb the *repetitive labor* of computational chemistry — writing input files, submitting jobs, parsing outputs, retrying transient failures, formatting reports. Your job is **not** to make scientific decisions on the user's behalf.
>
> For any choice that affects the chemistry of the result (functional, basis, solvation model, multiplicity, treating a structure as a TS vs a minimum, switching method after failure), you **recommend with reasoning** via `recommend` (or `ask_user` if no `recommend` tool is available) and let the user decide before proceeding.
>
> Default behaviors marked below ("recommend B3LYP-D3..." etc.) are **suggestions to surface to the user, not values to silently apply**.

**(b) §3 Method selection 重写**：

去掉 "Default for organic small molecules: B3LYP-D3(BJ) / def2-TZVP" 的 autonomous 语气，改成：

> Before calling any QM optimization or excited-state tool, propose method/basis/options to the user via `recommend`/`ask_user`, with reasoning grounded in system size, target property, and KB skill recommendations. Only proceed after the user confirms or overrides.
>
> Common defaults you may **recommend** (not silently apply):
> - Organic ground state opt: B3LYP-D3(BJ) / def2-TZVP
> - Charge-transfer excited states: ωB97X-D / def2-TZVP
> - T1 via TDDFT: TDA (Tamm-Dancoff)
> - SOC for TADF: BDF (X2C-TDA)
> - Conformer search funnel: xTB GFN2 → DFT re-opt
> - DLPNO-CCSD(T): ORCA (psi4 lacks the algorithm)

**(c) §6 Failure handling 拆分** —— 区分技术性 vs 化学性：

```
当前 prompt：
  SCF_NOT_CONVERGED → try GWH, then larger damping, then drop to def2-SVP

改为：
  Technical recovery (proceed silently, log to trajectory):
    - guess=GWH
    - increase damping
    - increase maxiter
    - retry on transient I/O / network errors
    - syntax-level input file fixes

  Chemistry decisions (must use `recommend` / `ask_user` first):
    - changing functional / basis / solvation model
    - changing TDA ↔ RPA
    - adding/removing dispersion correction or ECP
    - declaring an imaginary-frequency geometry to be a TS vs re-optimizing as a minimum
    - changing multiplicity assumption
```

**(d) §"When to ask the user" 翻转**：

```
当前：
  Use ask_user only when:
    ...
  Don't ask routine questions ('which basis should I use?').

改为：
  Always recommend-then-confirm before any chemistry decision.
  Routine input-file syntax tweaks may proceed silently and be logged.

  Use `recommend` for: method/basis/functional/solvent/multiplicity choices.
  Use `ask_user` for: ambiguous molecule identity, or when no reasonable
                     default exists to recommend.
```

### 1.2 之前对齐过但 Prompt 里仍未体现的方向

**(a) 软件栈重定向：psi4/xTB/ORCA → Gaussian/BDF/MOMAP**

System Prompt 当前的 "Tool routing cheat-sheet" 全是 psi4 命令。需要：

```
当前：
  | "Compute energy of X"  | io_ase.smiles_to_xyz → calc_psi4.optimize → calc_psi4.frequency |

改为（主路径走 Gaussian/BDF/MOMAP，psi4/ORCA/xTB 作为可选）：
  | "Compute energy of X" | io_ase.smiles_to_xyz → calc_gaussian.optimize → calc_gaussian.frequency |
  | "TADF / kRISC of X"   | (Gaussian opt) → (Gaussian TDDFT) → (BDF SOC) → (MOMAP rate) |
  | "AIE molecule rate"   | Gaussian opt+freq (S0, S1) → MOMAP TVCF |
  | "Phosphorescence"     | Gaussian opt → BDF SOC → MOMAP kp |
```

**注意**：psi4/ORCA/xTB 的 wrapper **不删**——保留作为"通用框架支持任意 QM 后端"的演示。但 cheat-sheet 主路径走用户实际用的栈。

**(b) HPC 目标更新：学校 SLURM → 商业云（并行/鸿之微）**

```
当前 §"Submit to HPC" → chem.hpc.slurm.submit

补充：
  HPC 目标平台为商业云超算（并行科技、鸿之微等），其 SLURM 接入方式
  与学校超算略有差异（认证 token、文件分区、提交命令）。具体参数
  通过 `chem.kb.kb_search("hpc-platform/<name>")` 查询。
```

**(c) "推荐而非决策" 在 cheat-sheet 中的体现**

每条 routing 之前都隐含一个 `recommend` 步骤。Prompt 里应明示：

```
  All routing entries below assume method/basis are confirmed with the user
  via `recommend`/`ask_user` before the calc tools are called.
```

---

## 2. 机制扩展

### 2.1 Confirmation 第三 mode：Recommend & decide

**目标文件**：
- `chemaster/agent/builtins.py` — 新增 `RecommendTool`
- `chemaster/agent/confirmation.py` — 增加 `RECOMMEND` mode 处理
- `chemaster/cli.py` — 终端 UI 渲染推荐卡片
- 未来 TUI / Web 一并支持

**RecommendTool 设计**：

```python
class RecommendTool(BaseTool):
    name = "recommend"
    description = (
        "Surface a chemistry decision to the user with your recommendation "
        "and reasoning. Use this before applying any choice that affects "
        "the chemistry of the result (functional, basis, solvent, multiplicity, "
        "method substitution after failure). The user may accept your "
        "recommendation, override it, or cancel the task."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "description": "Short label of the decision being made (e.g. 'functional for S1 optimization')."
            },
            "recommendation": {
                "type": "string",
                "description": "Your recommended choice (e.g. 'ωB97X-D / def2-TZVP')."
            },
            "reasoning": {
                "type": "string",
                "description": "Why this recommendation, given the system and target property."
            },
            "alternatives": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Other reasonable choices the user might prefer.",
            },
            "tradeoffs": {
                "type": "string",
                "description": "Cost / accuracy tradeoffs.",
            },
        },
        "required": ["decision", "recommendation", "reasoning"],
    }
```

**返回值**：用户决策结果，含 `{"decided": "<final choice>", "reason": "<user's note>"}`，回灌进 trajectory。

**三种 confirmation mode 总表**：

| Mode | 触发场景 | UI 形态 | trajectory 标签 |
|---|---|---|---|
| **Silent** | 读 KB、画图、技术性 retry、解析输出 | 无 prompt | `decision_authority: agent` |
| **Confirm** | 提交 HPC、写大文件、长任务、destructive | "执行 X，y/n？" | `decision_authority: user (binary)` |
| **Recommend** | 方法 / 基组 / 泛函 / 溶剂模型 / 多重度等化学决策 | "推荐 X，理由...；接受 / 改 / 取消" | `decision_authority: user (chemistry)` |

### 2.2 错误自愈率指标拆分（详细解释见 §4）

把 "错误自愈成功率 70%" 拆为两个独立指标：
- **指标 A：技术性故障自动恢复率** ≥ 80%
- **指标 B：化学决策推荐接受率** ≥ 70%

详细定义见本文 §4 给用户的解释。

---

## 3. 结构调整

### 3.1 Trajectory tagging

**目标文件**：`chemaster/agent/agent.py`、`chemaster/agent/types.py`

每条 trajectory 事件加 `decision_authority` 字段：
- `agent` — agent 自主行动（读 KB、解析、画图、技术性 retry）
- `user-binary` — 用户做了 yes/no 确认
- `user-chemistry` — 用户做了化学决策（含 override agent 推荐）
- `system` — 框架级事件（task start / end）

论文 §结果章节可统计：

> 在 N 个 anchor 任务中，总 tool call 步数 X，其中 agent 自主步占比 Y%，
> 用户决策点占比 Z%（其中化学决策 P 个、二元确认 Q 个）。

这是 "agent 吸收重复劳动" 的直接量化证据。

### 3.2 Benchmark 指标设计

写一份独立的 `docs/BENCHMARK_PROTOCOL.md`，定义：

- **化学指标**：3 个公开 benchmark + 师姐 case 的对比方式
  - S22 子集：相对结合能误差 (kcal/mol)
  - QUEST 子集：垂直激发能误差 (eV)
  - AIE (TPE/HPS)：kr/knr 数量级 + AIE 趋势是否复现
  - 师姐 case：与师姐参考值的相对误差
- **工程指标**：
  - 提交摩擦时间节省率（人工 baseline vs ChemMaster 计时）
  - 技术性故障自动恢复率（指标 A）
  - 化学决策推荐接受率（指标 B）
  - Trajectory 自主步占比（指标 C）
  - MCP 在 Claude Code 等客户端的复用 demo

---

## 4. 给用户解释："错误自愈率" 拆分的含义

### 4.1 旧版本（混在一起的问题）

之前我说"错误自愈成功率 ≥ 70%" —— 这是指 agent 遇到错误（SCF 不收敛、虚频、等等）时，**不打扰用户、自己解决** 的比例。

但用户的新原则是 "AI 推荐，人决策"。这就出现矛盾：

- 如果 agent **改方法（B3LYP → ωB97X-D）**自己解决了错误，算"自愈成功"——但这违反了"人决策"
- 如果 agent **遇错就问用户**，"自愈率" 就接近 0%——但这违反了"吸收重复劳动"

混在一起的指标无法回答："agent 到底是越权了，还是省了人力？"

### 4.2 新版本（拆成两个独立指标）

**指标 A：技术性故障自动恢复率**

- 衡量：agent 在不需要做化学决策的故障上，自己恢复的比例
- 例子：
  - SCF 不收敛 → 改 guess=GWH → 成功 ✓
  - SCF 不收敛 → 加 damping → 成功 ✓
  - 磁盘满 → 清理临时文件 → 重试 ✓
  - 输入文件语法错 → 自动修正 ✓
  - 网络抖动 → 重试 ✓
- 测量方法：注入 N 个技术性故障，记录 agent 自动恢复成功 / 总次数
- 目标：≥ 80%
- 解释什么：**agent 替你处理了多少机械性重复劳动**

**指标 B：化学决策推荐接受率**

- 衡量：当 agent 提出方法选择推荐时，用户接受的比例
- 例子：
  - Agent 推荐"用 B3LYP-D3/def2-TZVP 算 4CzIPN 基态" → 用户接受 ✓
  - Agent 推荐"S1 用 ωB97X-D 因为有 CT 特征" → 用户改成 CAM-B3LYP ✗（推荐被 override）
  - Agent 推荐"虚频 -15 cm⁻¹ 视为伪极小值，沿模式扰动重新优化" → 用户同意 ✓
- 测量方法：N 个 anchor 任务，统计 agent 推荐被用户接受 vs override 的比例
- 目标：≥ 70%
- 解释什么：**agent 的化学判断质量如何**

### 4.3 为什么拆开很重要

| 拆开后 | 答辩席评委的反应 |
|---|---|
| "技术性故障自动恢复率 85%" | "Agent 帮你省了不少机械活，OK" |
| "化学决策推荐接受率 75%" | "Agent 给的方法建议靠谱，但最终是用户拍板，没越权" |

合在一起说"自愈率 70%"，评委要么觉得太低（如果理解成"省 grunt work"），要么觉得越权（如果理解成"自动改方法"）。**拆开后两个指标各自意义明确，且都对应你的设计哲学**。

### 4.4 论文里怎么写

在 §结果 / §讨论章节：

> 我们用两个独立指标度量 agent 行为：（A）技术性故障自动恢复率衡量 ChemMaster 替研究者处理了多少机械性重复劳动；（B）化学决策推荐接受率衡量 agent 在化学判断上的辅助质量。前者达到 X%，证明 ChemMaster 显著降低了提交摩擦中的人力消耗；后者达到 Y%，且所有用户 override 操作均完整记录在 trajectory 中——这是 ChemMaster 与 ChemCrow 等 autonomous research agent 的关键区别：决策权完整保留给研究者，agent 只在边界明确的范围内自主行动。

---

## 5. 实施顺序

| 优先级 | 项目 | 工作量 | 依赖 |
|---|---|---|---|
| 1 | System Prompt 重写（§1.1 + §1.2）| 半天 | 无 |
| 2 | RecommendTool + confirmation 第三 mode（§2.1）| 2-3 天 | §1 |
| 3 | Trajectory tagging（§3.1）| 半天 | §2 |
| 4 | BENCHMARK_PROTOCOL.md（§3.2）| 半天 | §1-3 |
| 5 | 现有 22 个工具的 `is_chemistry_decision` 标志补全 | 半天 | §2 |
| 6 | CLI 渲染推荐卡片 | 半天 | §2 |
| 7 | 单元测试覆盖新 RecommendTool 和 confirmation 路径 | 半天 | §2 |

合计：~1 周专项工作。

---

## 6. 不在本计划内但相关的工作

以下工作不属于本次"哲学修正"范围，但与上述修改有依赖关系，记录在此：

- MOMAP MCP 从零写起（独立工作，约 1-2 周）
- Gaussian MCP 工具拆细（opt / freq / tddft / opt_es 各成结构化工具，约 1 周）
- BDF MCP 扩充（opt / tddft / 多种 SOC 变体，约 3-5 天）
- 商业云 HPC 接口设计（接口预留 + 本地 SLURM demo，约 3-5 天，**真实接入推到未来工作**）
- TUI 实现（Textual，约 1-2 周）
- 本地 Web 前端最小可用版（FastAPI + 简单 SPA，含结构/光谱可视化，约 1-2 周）
- Worktree `objective-meitner-befa64` 8 commit 合回主线
- 3 个公开 benchmark（S22 / QUEST / 蒽）端到端跑通

详见 `docs/ROADMAP.md`（待更新）和论文章节计划（待写）。

---

## 7. 最终章节大纲（合并 §3 §4 后）

```
摘要 / Abstract
关键词

第 1 章 绪论
  1.1 研究背景
  1.2 研究现状与不足
  1.3 研究目标与主要贡献
  1.4 本文组织

第 2 章 相关工作
  2.1 计算化学软件生态简述
  2.2 计算化学自动化工作流系统
  2.3 大模型 Agent 与化学（重点）
  2.4 MCP 协议与 LLM 工具生态
  2.5 与本工作的对比与差异

第 3 章 系统设计与实现       ← 原 §3 + §4 合并
  3.1 设计哲学
       3.1.1 labor-saving collaborator vs autonomous agent
       3.1.2 权限分级（L1 / L2 / L3）
  3.2 五层架构
  3.3 Agent 内核：tool-use loop + 三种 confirmation mode + trajectory
  3.4 MCP 工具集：设计原则与跨客户端复用
  3.5 知识库：formulas + skills + "LLM 不算数"
  3.6 多前端架构：CLI / TUI / Web 等价性与 accessibility 论证
  3.7 主要 MCP server 实现要点（Gaussian / BDF / MOMAP）
  3.8 商业云 HPC 接口设计（接口预留，真实接入为未来工作）
  3.9 错误自愈：技术性 vs 化学性的边界

第 4 章 测试与验证          ← 原 §5 升为 §4
  4.1 验证设计与指标体系
  4.2 基础精度验证
       4.2.1 S22 弱相互作用集
       4.2.2 QUEST 激发态参考集
       4.2.3 蒽：MOMAP TVCF 速率
  4.3 工程指标
       4.3.1 提交摩擦时间节省率
       4.3.2 技术性故障自动恢复率
       4.3.3 化学决策推荐接受率
       4.3.4 Trajectory 自主步占比
  4.4 系统能力演示（Use Cases）
       4.4.1 案例 1：本地端到端（CLI/TUI/Web 三前端等价）
       4.4.2 案例 2：MCP 在 Claude Code 中复用
  4.5 与 ChemCrow / Rowan / Schrödinger 的对比讨论

第 5 章 总结与展望
  5.1 工作总结
  5.2 局限性
  5.3 未来工作

参考文献
附录 A：扩展 use cases（商业云长任务、多分子批处理）
附录 B：MCP 接口规范摘要
附录 C：Skill 列表与权限分级配置示例
附录 D：完整 trajectory 示例
```

总章数：5 章 + 4 个附录。中文本科毕设预期页数 60-80 页。

---

*文档版本：v2.1  最后更新：2026-05-05*
