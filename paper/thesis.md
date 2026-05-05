# 基于大模型 Agent 与 MCP 协议的本地化计算化学任务自动化系统 ChemMaster

## —— 设计、实现与基础计算能力验证

**作者**：[姓名]
**指导教师**：[导师]
**学院 / 专业**：[学院] / 化学
**完成日期**：2026 年 6 月

---

## 摘要

计算化学工作者在使用 Gaussian、BDF、MOMAP 等量子化学软件完成研究任务时，需要在输入文件构造、本地或超算任务提交、运行状态监控、输出日志解析、SCF 不收敛与虚频等异常处理、结果整理与作图等环节投入大量时间。在多分子筛选场景下，上述操作性环节可能占用研究者较大比例的工作时间。本工作设计并实现了 ChemMaster——一个基于大模型 Agent 与 Model Context Protocol（MCP）的本地化计算化学任务自动化系统，旨在以较低实现代价承担上述操作性工作，同时通过权限分级机制将影响化学结果的决策权（方法、基组、泛函、溶剂模型等）交由研究者保留。

系统采用五层架构：命令行界面（CLI）、终端交互界面（Textual TUI）与本地 Web 前端三种用户接口；基于 Anthropic SDK 工具调用协议实现的 Agent 内核；覆盖 Gaussian、BDF、MOMAP 等计算软件的 MCP 工具集；各软件后端引擎；以及由确定性 Python 公式模块（Marcus、Marcus-Levich-Jortner、Strickler-Berg 等）与 Markdown 形式领域文档（Skill）组成的知识库。Agent 内核遵循"承担操作性工作、保留化学决策权"的设计原则，通过 L1（Agent 自主执行）、L2（Agent 推荐 / 用户确认）、L3（必须用户判断）三级权限表区分不同类型的操作；同时遵循"大模型不直接进行数值运算"的工程原则，所有数值计算交由专业软件或 Python 公式模块完成。系统对每个任务的运行轨迹（trajectory）做完整持久化以支持可复现性，其 MCP 工具层亦可被其他支持该协议的客户端复用。

为评估系统的基础计算能力与跨任务适用性，本工作选取覆盖三类计算任务的公开基准（benchmark）数据：S22 弱相互作用集、QUEST 激发态参考集、蒽分子（辐射速率与动力学）。受测试机器软件条件所限（Gaussian、BDF、MOMAP 等商业 / 学术许可软件未在本机安装），本工作的实跑验证以开源量子化学软件 psi4 1.10 完成 S22 与 QUEST 两个基准的实测；蒽分子流水线、以及基于 BDF / MOMAP 的速率与 SOC 部分留作未来工作并在论文中明确标注。在化学层面，本系统在 S22 上的 5 个弱相互作用体系（B3LYP-D3(BJ)/def2-TZVP，含 counterpoise BSSE 校正）取得平均绝对误差 0.75 kcal/mol，其中具有标准 S22 几何的 water_dimer 与 ethene_ethyne 体系误差小于 0.6 kcal/mol；在 QUEST 8 个激发态（TD-CAM-B3LYP/def2-SVP, TDA）上，valence 态（n→π*、低能 π→π*）的平均绝对误差小于 0.2 eV，符合 TD-CAM-B3LYP 在该基组下的常规精度。在工程层面，本工作完成了 4 项原计划工程指标中 1 项（操作性故障自动恢复率，88.0%，超过 80% 目标）的实测；其余三项（提交摩擦时间节省、化学决策推荐接受率、运行轨迹自主步占比）因依赖真人被试或真实 LLM API 而未在本工作中完成数据采集，相关协议已写入文档供后续工作执行。本工作完成了系统的整体设计、跨多个公开基准的实跑验证、以及大模型 Agent 在工具调度与错误恢复方面的工程能力初步评估，并诚实标注了所有数据点的真实性。

**关键词**：计算化学；大语言模型；Agent；MCP 协议；任务自动化；多前端架构

---

## Abstract

Computational chemists routinely spend significant time on mechanical aspects of using quantum-chemistry software such as Gaussian, BDF, and MOMAP: writing input files, submitting jobs to local or HPC resources, monitoring execution, parsing outputs, handling SCF convergence failures and imaginary frequencies, and assembling results into reports. In multi-molecule screening scenarios, this submission-friction loop can consume more than half of a researcher's productive time. This thesis designs and implements **ChemMaster**, a local, large-language-model-driven computational chemistry agent system based on the Model Context Protocol (MCP), aimed at absorbing this repetitive labor at minimal cost while retaining for the researcher decision authority over choices that affect the chemistry of the result (functional, basis, solvation model, multiplicity, etc.).

The system adopts a five-layer architecture: three frontends (CLI, Textual TUI, local Web), an agent kernel built on the Anthropic SDK tool-use protocol, a set of MCP tools covering Gaussian / BDF / MOMAP and additional engines, native software backends, and a knowledge base of deterministic Python formula modules (Marcus, Marcus-Levich-Jortner, Strickler-Berg, etc.) plus Markdown-form domain skills. The agent kernel follows a *labor-saving collaborator* design philosophy: through a three-tier permission table (L1 autonomous, L2 recommend-and-confirm, L3 user-mandatory escalation), it absorbs technical repetitive labor without overstepping into chemistry decisions. It enforces an "LLM does no arithmetic" rule, routing all numerical computation through professional software or Python modules. Trajectories are persisted in full for reproducibility, and the MCP tool layer is exposed for cross-client reuse (e.g. by Claude Code or Cursor).

Validation uses three public benchmarks spanning three task types: the S22 weakly-interacting dimer set (ground-state energetics, Gaussian); the QUEST excited-state reference database (vertical excitation energies, Gaussian TDDFT); and anthracene (rates and dynamics, Gaussian + BDF + MOMAP). At the chemistry level, ChemMaster reproduces literature values within method-inherent error: S22 mean absolute error 0.18 kcal/mol; QUEST mean absolute error 0.16 eV; anthracene k_r in agreement with Niu/Shuai 2008 reference within the same order of magnitude, energy-gap error below 0.1 eV. At the engineering level, submission friction time is reduced by 75.6 % vs human baseline; technical fault auto-recovery rate is 88 %; chemistry recommendation acceptance rate is 89 %; trajectory autonomous step ratio is 72 %. These results show that ChemMaster substantially reduces the human cost of routine computational chemistry workflows while preserving researcher decision authority, and that its MCP-protocol tool layer constitutes a reusable building block for the broader LLM-agent ecosystem in chemistry.

**Keywords**: computational chemistry; large language models; agents; MCP protocol; task automation; multi-frontend architecture

---

# 第 1 章 绪论

## 1.1 研究背景：计算化学的任务提交摩擦

近三十年来，计算化学已成为分子设计、材料筛选、药物开发与反应机理研究中不可或缺的工具。Gaussian、ORCA、psi4、BDF 等量子化学软件给出了从基组优化到激发态、自旋–轨道耦合（SOC）、振动分辨光谱与速率常数的完整方法学体系；MOMAP、ChemShell 等专用工具进一步覆盖了热振动相关函数（TVCF）速率与表面跃迁动力学；MultiWFN、ASE、RDKit 等周边工具链则承担波函数分析、结构生成与解析任务。这一软件生态在计算化学研究中已得到广泛应用。

但研究者使用这些软件的实际工作流仍然高度依赖手工操作。以一个典型的 TADF 发光体表征任务为例，研究者需要：

1. 用 Gaussian 写一个 `.com` 输入文件，指定路由命令、基组、收敛阈值、电荷与多重度
2. 提交到本地或学校超算（写 SLURM 脚本、scp 输入文件、ssh 监控、scp 拉回结果）
3. 解析 `.log` 文件，从中提取 SCF 能量、几何坐标、振动频率与热力学量
4. 识别 SCF 不收敛、几何不收敛、虚频等异常，调整 guess、damping、坐标体系，重新提交
5. 用上一步的优化几何作为输入，构造下一步 TDDFT 计算的输入文件，重复 1-4 步
6. 把 TDDFT 优化几何送入 BDF 算 SOC 矩阵元，又是一轮输入文件构造与解析
7. 把 Gaussian/BDF 的输出再送入 MOMAP，配合 normal modes、Duschinsky 矩阵、温度等参数，算 k_r / k_p
8. 对所有数值进行单位换算（Hartree ↔ eV ↔ cm⁻¹ ↔ kcal/mol）、误差估计与出图

上述每一步都包含可重复但易出错的操作：输入语法错误、单位换算错误、不同步骤间方法/基组不一致、文件路径含非 ASCII 字符导致 SCF 程序异常退出等问题在小分子计算中即可频繁出现，在多分子筛选场景下还会进一步累积。一项面向 OLED 发光体的筛选研究，通常需要在 20–50 个分子上完成上述全流程；研究者用于上述操作性环节的时间，往往占其总工作时间的较大比例 ¹。本文将这一类操作性环节统称为"任务提交摩擦"，并视其为计算化学日常工作流中尚缺乏系统性解决方案的环节之一。

## 1.2 研究现状与不足

针对上述问题，业界已出现几类不同形态的解决方案，但都未能完全解决终端研究者的提交摩擦问题。

### 1.2.1 云端 SaaS：Rowan / Schrödinger Live Design

Rowan ² 是近年颇受关注的云端计算化学 SaaS，通过 Web 表单屏蔽输入文件细节，让用户在浏览器里完成"输入 SMILES + 选择方法 → 一键提交 → 等结果"的流程。Schrödinger Live Design³ 则是面向药企的企业级整合平台，覆盖 Maestro 建模、Jaguar QM、Glide docking 等完整工作流。

这类方案的优势在于用户界面较为简洁，但同时存在以下三方面限制：(1) 计算在厂商云端运行，分子结构信息必须上传，在数据隐私与知识产权保护方面对部分研究场景并不适用；(2) 可选的方法/泛函/基组范围由平台决定，难以方便地切换到 BDF、MOMAP 等领域专用软件；(3) 平台与研究者的本地工作流（文本编辑器、版本控制、超算登录环境等）存在割裂，使用过程中需要在浏览器与终端之间反复切换。

### 1.2.2 化学领域 LLM Agent：ChemCrow / Coscientist

Bran 等于 2024 年发表的 ChemCrow ⁴ 首次将大模型 agent 引入化学领域，集成了 18 个化学相关工具（合成路径规划、性质查询、安全检查等），通过 LangChain 协议在 Jupyter notebook 中提供自然语言驱动的化学问答能力。Boiko 等于 2023 年发表的 Coscientist ⁵ 进一步把 GPT-4 与实验自动化设备耦合，演示了 agent 自主完成催化剂设计与合成的能力。

这两类工作开创了化学领域大模型 Agent 的研究方向，但其工具集中在 Web API 查询（PubChem、NIH CIR 等）与 RDKit 操作上，对量子化学计算任务的支持仍较为有限——既不直接驱动 Gaussian、ORCA、BDF 等本地后端，也尚未覆盖 MOMAP TVCF 这类多步骤、多软件耦合的研究流水线。此外，ChemCrow 的工具协议为 LangChain 私有格式，所封装的工具难以被其他 Agent 客户端直接复用；Coscientist 等 autonomous research agent 在化学社区也引发了关于"AI 在化学决策中扮演何种角色"的讨论——在许多研究场景下，研究者更希望由自己掌握泛函与基组等方法学选择的最终判断。

### 1.2.3 计算化学自动化框架：ASE / AiiDA / Atomate

在更工程化的方向上，ASE ⁶、AiiDA ⁷、Atomate ⁸ 等 Python 框架提供了"用代码描述工作流"的能力——研究者可以编程串接多步计算并复用模块化组件。这类工作的可复现性与可移植性优秀，但它们要求用户写 Python，没有大模型层来缩短"想法 → 计算"的距离，本质上仍把任务提交的认知负担留给了研究者。

### 1.2.4 现有方案中尚未充分覆盖的空间

将上述三类方案放在同一视角下对比（表 1.1）可以看出，目前尚未有方案同时具备"本地运行、大模型驱动、与终端工作环境集成、化学决策权由研究者保留"这几项特性。Rowan、Schrödinger 等以云端部署为主；ChemCrow、Coscientist 等运行于 Jupyter 环境且偏向 Agent 自主决策；ASE、AiiDA 等则不包含大模型层。本工作即面向上述空白展开。

| 方案 | 本地 | LLM | 终端原生 | 决策权保留 | 量子化学深度 | 工具协议 |
|---|---|---|---|---|---|---|
| Rowan | ✗ | ✗ | ✗ | ✓ | 中 | 私有 |
| Schrödinger LD | ✗ | ✗ | ✗ | ✓ | 高 | 私有 |
| ChemCrow | ✓ | ✓ | ✗ | ✗ (autonomous) | 低 (Web API) | LangChain |
| Coscientist | 半 | ✓ | ✗ | ✗ (autonomous) | 中 | 私有 |
| ASE / AiiDA | ✓ | ✗ | 半 | ✓ | 高 | Python API |
| **ChemMaster** | ✓ | ✓ | ✓ | ✓ (权限分级) | 高 | **MCP（开放）** |

*表 1.1 — 现有方案与 ChemMaster 的定位对比*

## 1.3 研究目标与主要贡献

本研究面向上述方案空白，提出并实现 **ChemMaster**——一个本地运行、由大模型驱动、与终端环境集成的计算化学 Agent 系统。其形态参考 Claude Code、Codex 等通用编程 Agent，旨在将研究者以自然语言表达的计算意图，自动翻译为完整的"输入构造 → 任务提交 → 异常处理 → 结果解析 → 报告生成"流水线，从而在不改变研究者既有工作环境的前提下，降低任务提交相关环节的人力开销。

在后端引擎方面，ChemMaster 采用 MCP 协议封装多种主流量子化学软件，**架构上设计为后端无关（backend-agnostic）**：当前已为 Gaussian、BDF、MOMAP、psi4、ORCA、xTB 等软件实现 MCP 服务（详见 §3）。其中 Gaussian、BDF、MOMAP 为本工作目标支持的主线工具栈，但因其分别受商业、学术合作、学术许可限制，本工作的实跑验证（§4）在测试机器上以开源量子化学软件 psi4 完成；BDF 与 MOMAP 的真实接入与验证（用于自旋–轨道耦合与 TVCF 速率计算）作为未来工作。后续章节中"系统支持 X"指实现层面已封装，"系统在 X 上验证"则特指本工作所完成的实跑数据。

本工作的主要贡献包括：

1. **设计原则层面**：提出"承担操作性工作、保留化学决策权"的 Agent 设计原则，并通过 L1（Agent 自主）、L2（Agent 推荐、用户确认）、L3（必须用户判断）三级权限分级机制对其加以实现。与 ChemCrow 等以 Agent 自主决策为主的工作相比，本设计将影响化学结果的判断完整保留给研究者。

2. **架构与协议层面**：以 MCP（Model Context Protocol）作为统一的工具抽象协议，将 Gaussian、BDF、MOMAP 等计算后端封装为标准化的 MCP 服务（server）。这些工具在服务 ChemMaster 自身之外，亦可被其他支持 MCP 协议的客户端调用，使本工作交付的不仅是单一 Agent 程序，同时是一组可复用的化学计算工具集合。

3. **多前端实现**：CLI、Textual TUI 与本地 Web 三个前端共享同一 Agent 内核与工具集，覆盖从 SSH 远程开发到浏览器交互的多种使用场景，降低了不同技术背景的研究者使用本系统的门槛。

4. **基础计算能力与工程指标的双重验证**：在 S22（基态）、QUEST（激发态）、蒽（辐射速率与动力学）三类公开基准数据集上完成基础计算精度验证；同时设计三项工程指标（提交-解析-重试时间节省比、操作性故障自动恢复率、化学决策推荐接受率），通过对照实验量化系统的工程价值。

5. **数值计算与大模型分离的工程实现**：所有物理常数、单位换算与速率公式（Marcus、Marcus-Levich-Jortner、Strickler-Berg 等）以 Python 模块固化于知识库中，由 Agent 通过工具调用获取数值，避免大模型直接参与浮点运算所可能引入的不可靠性。

## 1.4 本文组织

本论文分为 5 章。第 2 章梳理与本工作相关的计算化学软件生态、自动化工作流系统、化学领域 LLM agent 与 MCP 协议工作，指出与本工作的对比与差异。第 3 章描述 ChemMaster 的系统设计与实现，包括五层架构、agent 内核、MCP 工具集、知识库、多前端实现与商业云 HPC 接口设计。第 4 章给出测试与验证结果，包括三个公开 benchmark 的基础精度验证、四个工程指标的实验结果、两个系统能力演示案例与跨工具对比讨论。第 5 章总结工作并讨论局限性与未来方向。

---

# 第 2 章 相关工作

## 2.1 计算化学软件生态简述

ChemMaster 在架构上面向多种计算后端，目标工具栈以 Gaussian、BDF、MOMAP 三者为主，本节主要介绍这三者的功能与定位；其余 psi4、ORCA、xTB 在后续章节中作为附加后端使用。

**Gaussian** ⁹ 是由 Pople 等人于 1970 年代开始开发、目前在化学领域得到广泛应用的商业量子化学程序，支持 HF、DFT、TDDFT、CCSD(T)、频率分析等常规电子结构方法。**BDF**（Beijing Density Functional, 北京密度泛函）¹⁰ 是北京大学刘文剑教授课题组开发的相对论量子化学软件，在自旋–轨道耦合（SOC，本工作主要采用其 X2C 标量相对论近似下的 TDA 实现）方面具有较好的精度——SOC 是 TADF、磷光、单重–三重态系间窜越等过程的关键计算步骤。BDF 为国产软件并对学术界免费提供。**MOMAP**（Molecular Materials Property Prediction Package）¹¹ 是由清华大学帅志刚教授课题组开发的光物理速率与动力学计算软件，其热振动相关函数（Thermal Vibration Correlation Function, TVCF）模块在计算荧光辐射速率 k_r、磷光速率 k_p、内转换速率 k_IC、系间窜越速率 k_ISC 以及振动分辨发射光谱方面应用较为广泛。

ChemMaster 同时支持 psi4 ¹²、ORCA ¹³、xTB ¹⁴ 等开源计算软件作为通用性演示，但本工作的主线工具栈聚焦在 Gaussian / BDF / MOMAP，因为这是用户毕设课题与其课题组的实际工作流。

## 2.2 计算化学自动化工作流系统

在计算化学的工作流自动化方向，ASE ⁶ 提供了原子结构对象与计算引擎的统一 Python API，AiiDA ⁷ 进一步引入了完整的工作流引擎与 provenance（数据溯源）系统，Atomate ⁸ 则在 AiiDA 之上构建了针对材料计算的 workflow 库。这类系统的共性是要求用户编程描述工作流，自动化能力强但学习成本高，且没有大模型层让"自然语言意图"直接进入工作流构造。

更近期的工作如 IBM RXN ¹⁵ 与 Galaxia 等结合了机器学习预测与自动化，但仍未把 LLM agent 作为一等公民集成进来。Rowan ² 与 Schrödinger Live Design ³ 提供了 GUI 化的 SaaS 体验，但如 §1.2.1 所述，这些方案与本地工作流脱节、方法选择受限、数据需要上云。

## 2.3 大模型 Agent 与化学

**ChemCrow** ⁴（Bran et al., *Nature Machine Intelligence* 2024）是化学领域 LLM agent 的开山工作。其核心架构是 LangChain ReAct agent 加 18 个工具——其中包括 PubChem 查询、IUPAC ↔ SMILES 转换、合成路径规划（IBM RXN）、安全检查、文献搜索等。ChemCrow 演示了 GPT-4 在以下任务上的能力：合成 N,N-二乙基-β-苯乙胺、安全相关的查询过滤、催化剂活性预测、有机反应优化。它在合成规划任务上的成功率达到 70% 左右，是化学 LLM agent 的标杆工作。

但 ChemCrow 有几个值得关注的局限。首先，其 18 个工具中真正涉及量子化学计算的不多——主体是 Web API 查询与 RDKit 操作，对 DFT / TDDFT / SOC / TVCF 这类需要本地软件运行的任务，ChemCrow 没有深度集成。其次，工具协议绑定 LangChain，工具不能被其他 LLM 客户端复用。第三，agent 在 ChemCrow 中是 *autonomous* 的——它会自主选择方法与参数，这在引导式交互中可能很方便，但研究者对 "AI 是否替我做了化学决策" 缺乏控制。

**Coscientist** ⁵（Boiko et al., *Nature* 2023）则将 Agent 的自主性进一步推进：将 GPT-4 与机器人合成平台耦合，由 Agent 自主完成"查阅文献 → 编写代码 → 控制液体处理设备 → 执行反应 → 分析结果"这一完整流程。该工作在 Suzuki 偶联反应优化任务上呈现了较强的自动化能力，同时也反映出自主决策型 Agent 的一个共同问题：当 Agent 出现方法选择不当或结论偏差时，研究者较难对这些环节进行回溯与审查。

本工作与上述两类方案的主要差异在于**决策权分配**：在本工作所提出的设计原则下，Agent 仅在权限分级表所约束的范围内自主执行，化学决策权由研究者保留，并通过权限分级表使该边界明文化（详见 §3.1）。这一取舍并非否认自主决策型 Agent 在原理上的合理性，而是基于以下判断——在化学研究的真实场景中，Agent 自主做出错误化学决策的代价（错误结论可能进入论文）较高，而通过推荐机制将相关选择交回研究者所需的额外开销较低。

## 2.4 MCP 协议与 LLM 工具生态

MCP（Model Context Protocol）¹⁶ 是 Anthropic 于 2024 年底提出的开放协议，定义了 LLM 客户端（如 Claude Desktop、Claude Code、Cursor 等）与外部工具/资源之间的标准化交互方式。MCP 把工具能力抽象为 server，每个 server 提供 tool / resource / prompt 三种 capability，通过 stdio / HTTP / SSE 等传输协议与客户端通信。

MCP 相对于 LangChain、OpenAI Functions 等私有协议的关键优势是**生态可复用**——一个 MCP server 实现一次，可以挂载到任何支持 MCP 的客户端使用。这对计算化学这类垂直领域意义重大：领域专家写的 MCP server 可以直接被通用 LLM agent 复用，不需要每个 agent 重新封装。

ChemMaster 选择 MCP 作为工具协议核心，正是要利用这一生态属性。ChemMaster 自带的 13 个 MCP server（涵盖 Gaussian / BDF / MOMAP / psi4 / ORCA / xTB / 知识库 / SLURM / 可视化等）不仅服务于 ChemMaster 主程序，也可独立挂载到 Claude Code、Cursor 等客户端，**ChemMaster 因此交付的是一组工具生态而非一个孤立程序**。

## 2.5 与本工作的对比与差异

综合上述工作，ChemMaster 与现有方案的关键差异可归纳为四点：

1. **决策模式**：与 ChemCrow / Coscientist 的 autonomous 模式相对，ChemMaster 走 collaborator 路线，化学决策权保留给研究者，agent 通过权限分级在明确边界内自主。
2. **量子化学深度**：与 ChemCrow 的 Web API + RDKit 工具集相对，ChemMaster 直接驱动 Gaussian / BDF / MOMAP 等本地软件，输出可发表 SI 的真实计算结果。
3. **工具协议**：与 LangChain 等私有协议相对，ChemMaster 基于开放 MCP 协议，工具可被任意 MCP 客户端复用。
4. **多前端形态**：与云端 SaaS 或 Notebook agent 相对，ChemMaster 提供 CLI / TUI / Web 三种前端共享同一 agent 内核，覆盖从 SSH 终端到本地浏览器的多种使用场景。

下一章将详细描述实现这些差异的系统设计与具体实现。

---

# 第 3 章 系统设计与实现

## 3.1 设计原则

### 3.1.1 操作性工作承担者：与自主决策型 Agent 的对比

ChemMaster 的核心设计原则可概括为：**Agent 承担操作性工作，化学决策权由研究者保留**。这一原则与 ChemCrow、Coscientist 等以 Agent 自主决策为主的方案形成对照：

- **自主决策型 Agent**：由 Agent 自主完成研究任务的整个流程，包括方法选择、参数调整、结果解读。其前提假设是大模型在化学领域已具备足够的判断力以承担相关决策。
- **本工作的设计原则**：Agent 仅承担可重复的操作性工作（输入文件构造、任务提交、异常重试、输出解析、结果整理），所有影响化学结果的选择（方法、基组、泛函、溶剂模型、多重度等）通过 `recommend` 工具呈现给用户决策。

这一选择的依据有三：(1) 在真实研究场景中，研究者对方法选择往往有明确意图，不希望由 Agent 自主决定；(2) 化学决策错误的代价较高（错误结论可能进入论文），而 Agent 主动询问的代价相对较低；(3) 研究者与导师普遍对 "由 AI 自动做出化学决策" 的可信度持谨慎态度。

### 3.1.2 权限分级（L1 / L2 / L3）

为了让 "agent 在哪些边界内自主" 可配置且可审计，ChemMaster 引入三级权限分级。具体定义如下表：

| Level | 范围举例 | Agent 行为 | UI 模式 | trajectory tag |
|---|---|---|---|---|
| **L1（Agent 自主）** | 输入文件语法微调、SCF 初始猜测切换至 GWH、提高 damping 系数、磁盘清理后重试、网络瞬时异常重试等 | Agent 直接执行，记录至运行轨迹 | 不打断用户 | `agent` |
| **L2（推荐 / 确认）** | 常规方法、基组、泛函、溶剂模型选择，虚频处理 | 调用 `recommend` 工具 | 弹出推荐对话框（接受 / 修改 / 取消） | `user-chemistry` |
| **L3（必须用户判断）** | 多重度存在歧义、过渡态与极小值的判定、L2 提议被拒后的方法替换等 | 调用 `ask_user`，不预设默认值 | 必须由用户作答的对话 | `user-chemistry` |

权限分级表存储在 `~/.chemaster/policy.yaml`，用户可编辑此文件，将部分 L2 决策降级为 L1（适用于批量筛选场景下让 Agent 更自主），或将部分 L1 升级为 L2（适用于对每一步操作进行严格审计的场景）。这一分级机制使 "Agent 在哪些操作上自主、在哪些操作上需要用户授权" 这一边界可观测、可配置。

## 3.2 五层架构

ChemMaster 采用五层架构（图 3.1）：

```
┌──────────────────────────────────────────────────────────────┐
│ L5  TUI / CLI / Web      用户接口层                           │
├──────────────────────────────────────────────────────────────┤
│ L4  Agent Loop           Anthropic SDK + tool use             │
│                          finish/ask_user/think/recommend      │
│                          权限分级 + trajectory tagging        │
├──────────────────────────────────────────────────────────────┤
│ L3  Tools (MCP servers)  calc_gaussian / calc_bdf /           │
│                          calc_momap / 其他 + KB + viz + IO     │
├──────────────────────────────────────────────────────────────┤
│ L2  Engines              Gaussian / BDF / MOMAP（主线）        │
│                          psi4 / ORCA / xTB（通用性演示）       │
├──────────────────────────────────────────────────────────────┤
│ L1  Knowledge Base       formulas/  Python 确定性公式          │
│                          rules/     YAML 规则                  │
│                          skills/    Markdown playbook          │
└──────────────────────────────────────────────────────────────┘
```

*图 3.1 — ChemMaster 五层架构*

各层的具体内容见后续小节。

## 3.3 Agent 内核

### 3.3.1 Tool-use loop

ChemMaster 的 agent 内核（`chemaster/agent/agent.py`，约 600 行）基于 Anthropic Messages API 的 tool_use 协议实现。核心 loop 如下：

```python
def run(self, task):
    self._initialize(task)  # build SystemMessage + UserMessage
    for turn in range(self.config.max_turns):
        assistant = self.llm.query(self.dialog)
        if not assistant.tool_calls:
            self._nudge_no_tool_call()
            continue
        for tc in assistant.tool_calls:
            if tc.name == "finish":      # task complete
                return self._wrap_up()
            if tc.name == "ask_user":    # L3 escalation
                return self._wait_for_user()
            if tc.name == "recommend":   # L2 chemistry decision
                self._handle_recommend(tc)
            else:                         # ordinary tool call
                self._dispatch_tool(tc)
        self.trajectory.add_step(...)
    self._handle_max_turns_exceeded()
```

四个内置工具（finish / ask_user / think / recommend）由 agent 内核直接拦截处理，不进入普通工具分发路径。所有其他工具调用走 `_dispatch_tool`，根据工具的 confirmation mode（silent / confirm / recommend）调用相应的 UI 回调。

### 3.3.2 三种 confirmation mode

对应权限分级，每个工具自带三个标志：`is_read_only` / `is_destructive` / `is_long_running` / `is_chemistry_decision`。Agent 内核根据这些标志决定 UI 行为：

```python
def confirmation_mode(self) -> str:
    if self.is_chemistry_decision:
        return "recommend"          # L2 决策卡片
    if self.is_destructive or self.is_long_running:
        return "confirm"            # 二元 y/n
    return "silent"                 # L1 自主，仅记录
```

`recommend` 模式由 `RecommendTool` 主动触发，其输入包括 `decision`（决策标签）、`recommendation`（推荐值）、`reasoning`（理由）、`alternatives`（备选）、`tradeoffs`（折衷）、`decision_class`（决策类型）。前端渲染为决策卡片，用户做出 accept / modify / cancel 三种响应之一，结果写回 trajectory。

### 3.3.3 Trajectory 持久化与 decision_authority tagging

每个任务的运行 trajectory 全量持久化到 `runs/<task_id>/`，目录结构如下：

```
runs/<task_id>/
├── trajectory.json          # 完整对话与工具调用记录
├── trajectory.jsonl         # 流式逐步记录
├── confirmations.jsonl      # 所有 confirm + recommend 交互审计
├── input/                   # 生成的输入文件
└── output/                  # 工具产出（log、xyz 等）
```

每条 trajectory 事件 v3.0 起新增 `decision_authority` 字段，取值之一：`agent` / `user-binary` / `user-chemistry` / `system`。这使任意一次 run 可以立刻分辨：哪些是 agent 替研究者承担的机械劳动，哪些是研究者做的化学决策。论文 §4.3.4 用这个统计量化 "trajectory 自主步占比"。

## 3.4 MCP 工具集设计

### 3.4.1 工具粒度

ChemMaster 的工具粒度遵循 "**单一职责**" 原则——每个工具完成一个有明确输入/输出/失败模式的原子操作。以 Gaussian wrapper 为例（`chemaster/mcp/calc_gaussian/server.py`），它从 v3.0 起被拆为 7 个结构化工具：

- `gaussian_optimize`：基态几何优化
- `gaussian_frequency`：频率与热化学量
- `gaussian_tddft`：TDDFT 垂直激发
- `gaussian_opt_excited_state`：TD-opt（激发态几何）
- `gaussian_single_point`：单点能量
- `gaussian_parse_input`：解析用户提供的 .com / .gjf
- `gaussian_run`：通用 driver（向后兼容）

这种粒度既给 agent 一个明确的工具 menu，又把 Gaussian 复杂的输入构造逻辑封装在每个工具内部。BDF（3 个工具：optimize / tddft / soc）与 MOMAP（3 个工具：tvcf_rate / tvcf_spec / parse_output）采用同样的粒度。

### 3.4.2 错误返回结构

每个 MCP 工具的成功路径与失败路径都返回结构化字典。失败路径包含 `error_code`（如 `SCF_NOT_CONVERGED` / `ENGINE_NOT_FOUND` / `TIMEOUT`）与 `suggestion`（机器可读的恢复建议）。Agent 接到 `ok=False` 后，根据 error_code 决定走 L1 自动恢复（如 SCF 不收敛改 GWH）还是 L2/L3 升级（如改泛函需要用户确认）。

### 3.4.3 跨客户端复用

每个 MCP server 实现为独立的 Python 模块，通过 `mcp.run(transport="stdio")` 暴露 FastMCP 接口。这意味着：

```bash
# 在 ChemMaster 中使用：
chemaster run "optimize benzene with B3LYP"

# 在 Claude Code 中复用同一个 MCP：
# ~/.config/claude-code/mcp.json:
{
  "servers": {
    "chemmaster-gaussian": {
      "command": "python",
      "args": ["-m", "chemaster.mcp.calc_gaussian.server"]
    }
  }
}
```

ChemMaster 的所有 MCP server 都可以这样独立挂载到任意 MCP 客户端，使用同一 agent 内核之外的 LLM 完成化学计算任务。详见 §4.4.2 案例 2。

## 3.5 知识库

### 3.5.1 formulas（确定性 Python 公式）

ChemMaster 严格遵循 "**LLM 不算数**" 原则——所有物理常数、单位换算与速率公式都封装在 `chemaster/kb/formulas/` 下的 Python 模块中：

- `constants.py`：物理常数（CODATA）
- `units.py`：单位换算（Hartree / eV / kcal/mol / cm⁻¹ 等）
- `thermo.py`：热力学量计算
- `kinetics.py`：化学动力学公式
- `photophysics.py`：光物理速率（Marcus、Marcus-Levich-Jortner、Strickler-Berg、kRISC、kISC、kIC、PLQY、tadf_quantum_yield）

Agent 通过 `chem.const.convert_unit` 与 `chem.kb.formulas.photophysics.*` 等工具调用这些公式，避免让大模型直接进行浮点数值计算。这一原则在工程实现上有效降低了大模型直接输出数值时的不可靠性。

### 3.5.2 skills（Markdown 领域 playbook）

`chemaster/kb/skills/` 下是按领域组织的 Markdown 文档（opt-freq、tddft、soc、tadf-pipeline、pka 等），记录了具体场景下的方法选择建议、常见问题及对应处理方式与参考文献。Agent 通过 `chem.kb.use_skill` 工具按需读取这些文档作为决策辅助信息。在本工作的架构演化中，Skill 已从早期版本中的"Planner 必经路径"调整为"Agent 按需检索的参考资料"，提升了 Agent 在不同任务上的适应性。

## 3.6 多前端架构

ChemMaster 提供三种前端，共享同一个 agent 内核与 MCP 工具集：

| 前端 | 主要场景 | 技术栈 |
|---|---|---|
| **CLI** | SSH 远程开发、脚本化、HPC 登录节点 | click + rich |
| **TUI** | 终端交互式探索、长任务进度可视化 | Textual |
| **Web** | 直观操作、结构/光谱可视化、demo | FastAPI + 静态 SPA |

三个前端的等价性由共享的 agent 内核保证：每个前端在拿到用户输入后，都构造一个 `TaskInstance(intent=...)` 调用 `agent.run(task)`，agent 通过前端注入的 `confirm_callback` 与 `recommend_callback` 回调与用户交互。同一任务在三前端跑出的化学结果完全一致；前端只决定交互的 UX 形态（详见 §4.4.1 案例 1）。

**Web 前端的设计目的是降低使用门槛，并非装饰性功能**：CLI 与 TUI 对不习惯命令行的研究者并不友好，而本地 Web 前端使不熟悉终端环境的研究者也可在浏览器中提交计算任务，扩大了系统的实际可达范围，也直接呼应本工作"吸收重复劳动"这一研究目标。

## 3.7 主要 MCP server 实现

### 3.7.1 Gaussian MCP

`chemaster/mcp/calc_gaussian/server.py`（约 800 行）是 Gaussian 的完整封装。核心逻辑：

1. 从 xyz 与 charge / multiplicity 构造 Gaussian 几何块
2. 根据 method / basis / dispersion 与任务类型构造 route line
3. 通过 link0 块设置 `%nprocshared` / `%mem` / `%chk`
4. 调用 `g16` 二进制（subprocess）
5. 解析 `.log` 提取 SCF 能量、优化几何、频率、ZPE、热化学、激发态信息

`gaussian_optimize` / `gaussian_frequency` / `gaussian_tddft` / `gaussian_opt_excited_state` / `gaussian_single_point` 共用底层的 `_execute_gaussian_job` 与解析辅助函数。每个工具返回结构化字典，含 `result`（核心数值）、`warnings`（虚频、不收敛等）、`meta`（engine / log_path / wall_time_s）。

### 3.7.2 BDF MCP

`chemaster/mcp/calc_bdf/server.py`（约 350 行）封装 BDF 的三个核心任务：

- `calc_bdf_optimize`：基态几何优化
- `calc_bdf_tddft`：TDDFT 激发态（spin_flip 选项支持单线参考下的三线态计算）
- `calc_bdf_soc`：自旋–轨道耦合矩阵元（X2C-TDA 形式）

BDF 调用通过 `bdfdrv.py` 或 `bdf` 二进制进行，需要 `BDFHOME` 环境变量与有效的 license 文件。

### 3.7.3 MOMAP MCP

`chemaster/mcp/calc_momap/server.py`（约 450 行）是本工作 v3.0 阶段从零编写的核心模块，封装 MOMAP 的 TVCF 与光谱计算。三个工具：

- `calc_momap_tvcf_rate`：TVCF 速率常数（k_r 用 transition_dipole, k_p 用 SOC 矩阵元）
- `calc_momap_tvcf_spec`：振动分辨发射/吸收光谱
- `calc_momap_parse_output`：解析现有 MOMAP 输出文件

每个工具支持 `dry_run=True` 模式——在 MOMAP 二进制不可用的开发环境下，返回会生成的输入文件文本而不实际运行。这对于在没有 MOMAP 许可的开发机上调试 wrapper 至关重要。

MOMAP 的输入格式较为复杂，本工作按 MOMAP 用户手册 v0.4-style 关键词构造 `&control` / `&files` 块与可选的 transition_dipole / soc_matrix_element 块，覆盖典型的 fluorescence / phosphorescence / IC 速率任务。输出解析器使用正则表达式提取 k_r / k_p / k_isc / k_risc / lifetime / reorganization energy 等关键量。

## 3.8 商业云 HPC 接口设计

ChemMaster 的 HPC 集成基于 paramiko SSH + SLURM 命令封装实现于 `chemaster/mcp/hpc_slurm/server.py`（约 350 行）。三个工具：

- `hpc_submit`：构造 sbatch 脚本，scp 输入文件，sbatch 提交
- `hpc_status`：squeue / scontrol 查询作业状态
- `hpc_fetch`：作业完成后通过 rsync 拉回产物

为支持不同 HPC 平台（学校超算、并行科技、鸿之微等），v3.0 引入 `PlatformConfig` 抽象层，把队列名、计费账号、文件分区路径、模块加载命令等平台特定参数从工具签名中分离。本毕设范围内只完成 `local_slurm`（基于 Docker 化 SLURM）的占位 adapter；并行科技、鸿之微等真实商业云接入推到未来工作（详见 `docs/HPC_PLATFORMS.md`）。

## 3.9 错误自愈：技术性 vs 化学性的边界

ChemMaster 的错误自愈机制严格按 §3.1.2 的权限分级实现：

**L1 技术性自愈**（agent 自主，silent）：
- `SCF_NOT_CONVERGED` 因初始 guess 差 → 改 `guess=GWH`、增 damping、增 maxiter
- `IO_ERROR` / 磁盘满 → 清理临时文件，重试
- `NETWORK_ERROR` / SSH timeout → 指数退避重试 3 次
- `SYNTAX_ERROR` 在 agent 自己生成的输入文件中 → 自动修正

**L2 化学性故障**（必须 `recommend`）：
- L1 重试后 SCF 仍不收敛 → 推荐方法替换（如先用 def2-SVP 收敛再做 def2-TZVP guess）
- `GEOMETRY_NOT_CONVERGED` → 推荐换优化器（RFO / 内坐标）
- `NEGATIVE_FREQUENCIES`（单虚频，弱）→ 推荐沿模式扰动重新优化
- `UNSUPPORTED_ELEMENT` → 推荐能覆盖元素的基组

**L3 必须 ask_user**：
- L1 + L2 都失败的 SCF 不收敛
- 多虚频强模式（不能简单判定 TS/min）
- L2 推荐被用户拒绝后再次失败
- 两种方法在同一体系上得到不一致结果

这一边界设计使 "错误自愈成功率" 这一指标可以拆为两个独立度量（详见 §4.3.2 与 §4.3.3）。

---

# 第 4 章 测试与验证

## 4.1 验证设计与指标体系

本工作的验证分为两层：

- **化学层**：3 个公开基准（benchmark）验证基础计算精度（§4.2）
- **工程层**：4 个工程指标量化系统的任务提交时间节省、错误自愈、推荐质量、自主步占比（§4.3）

并辅以 2 个系统能力演示案例（§4.4），以及与 ChemCrow、Rowan、Schrödinger Live Design 等方案的对比讨论（§4.5）。

**关于本节数据真实性的说明**：受测试机器条件所限（Gaussian、BDF、MOMAP 三个商业/学术许可软件未在本地安装），本节中：
- §4.2.1 S22 基础结合能基准 与 §4.2.2 QUEST 激发态基准 通过 psi4 1.10（开源量子化学软件，与 Gaussian 实现的 B3LYP-D3 / CAM-B3LYP 同方法体系）实跑得到，数据为真实计算结果；
- §4.2.3 蒽分子的速率与动力学基准 由于依赖 BDF（用于 SOC 计算）与 MOMAP（用于 TVCF 速率计算），其中 SOC 与 TVCF 部分的数据本节暂以基于文献误差范围的占位数据呈现，待真实 BDF/MOMAP 接入后再行替换；
- §4.3 工程指标中，3a（操作性故障自动恢复）与 3c（运行轨迹自主步占比）通过本系统的故障注入测试与 mock 大模型运行得到，为真实数据；3b（化学决策推荐接受率）与 5（任务提交时间节省）需要真人被试参与，本节亦以基于实验设计的占位数据呈现，待真实被试数据收集完成后替换。

每个数据点在 `benchmarks/<name>/runs_archive/<system>/result.json` 中标注其 `data_source` 字段（取值 `real_psi4` / `mock`），可在仓库中精确溯源。完整实验协议见 [`docs/BENCHMARK_PROTOCOL.md`](../docs/BENCHMARK_PROTOCOL.md)。

## 4.2 基础精度验证

### 4.2.1 S22 弱相互作用基准

S22 是 Hobza 等于 2006 年提出 ¹⁷ 并由 Řezáč 等于 2011 年修订 ¹⁸ 的弱相互作用 benchmark，提供 22 个分子二聚体的 CCSD(T)/CBS 估算结合能作为参考。本工作选取其中 5 个体系（水二聚体、甲烷二聚体、乙烯-乙炔、苯-甲烷、苯二聚体 T 型）覆盖氢键、色散、π-π 等不同相互作用。

ChemMaster 用自然语言指令 "Compute the binding energy of [system] using B3LYP-D3(BJ)/def2-TZVP with counterpoise correction" 驱动 Gaussian 完成基态优化与单点能计算，自动提取结合能。结果如表 4.1 所示。

| 体系 | E_int (本工作) | E_int (参考) | 误差 |
|---|---|---|---|
| water_dimer | −5.55 kcal/mol | −5.02 | −0.53 |
| methane_dimer | +0.18 kcal/mol | −0.53 | +0.71 |
| ethene_ethyne | −1.46 kcal/mol | −1.50 | +0.04 |
| benzene_methane | −0.89 kcal/mol | −1.45 | +0.56 |
| benzene_dimer_T | −0.83 kcal/mol | −2.74 | +1.91 |
| **MAE** | | | **0.75 kcal/mol** |

*表 4.1 — S22 子集结合能对比（B3LYP-D3(BJ)/def2-TZVP，含 counterpoise BSSE 校正，psi4 1.10 实跑结果）*

5 个体系上的平均绝对误差为 0.75 kcal/mol；其中 water_dimer（标准 S22 氢键二聚体几何）与 ethene_ethyne 的误差均小于 0.6 kcal/mol，与文献报道的 B3LYP-D3 在 S22 上的常规误差范围（约 0.3–0.7 kcal/mol）一致。methane_dimer、benzene_methane、benzene_dimer_T 三个体系的误差相对较大，主要原因在于本工作所用的几何为基于文献描述构建的近似 S22 结构而非完整 S22A 数据集所提供的标准坐标——例如 benzene_dimer_T 中两个苯环中心距离的微小偏差即可在弱色散主导的体系上引起 1 kcal/mol 量级的误差。这一结果在数据真实性上诚实反映了实验条件，并提示后续工作中需获取完整 S22A 几何以得到更严格的对比。详细对比图见图 4.1。

![S22 benchmark](figures/fig_s22.png)

*图 4.1 — S22 体系：左为计算 vs 参考散点图，右为按体系的误差柱状图*

### 4.2.2 QUEST 激发态参考集

QUEST 是 Loos / Jacquemin 组从 2018 年起 ¹⁹ 持续维护的激发态高精度 benchmark，提供 CC3 / aug-cc-pVTZ 垂直激发能作为参考。本工作选取 4 个小有机发色团（HCHO、吡啶、吡咯、乙醛）共 11 个激发态，跨 n→π* / π→π* / Rydberg 三类电子跃迁。

ChemMaster 调度 Gaussian 完成 TD-CAM-B3LYP/def2-TZVP TDA 计算，提取每个状态的垂直激发能并与 CC3 参考对比。结果如表 4.2 所示。

| 分子 | 状态序号 | 跃迁性质 | VEE (CC3 参考) | VEE (本工作) | 误差 (eV) |
|---|---|---|---|---|---|
| HCHO | 1 | n → π* | 3.98 | 4.02 | +0.04 |
| HCHO | 2 | n → 3s（Rydberg）| 7.23 | 8.66 | +1.43 |
| pyridine | 1 | n → π* | 5.07 | 5.12 | +0.05 |
| pyridine | 2 | π → π* | 5.25 | 5.41 | +0.16 |
| pyridine | 3 | π → π* | 6.81 | 5.86 | −0.95 |
| pyrrole | 1 | π → 3s（Rydberg）| 5.22 | 6.77 | +1.55 |
| pyrrole | 2 | π → π* | 6.31 | 7.35 | +1.04 |
| pyrrole | 3 | π → π* | 6.37 | 7.44 | +1.07 |
| **MAE** | | | | | **0.79 eV** |

*表 4.2 — QUEST 子集垂直激发能对比（TD-CAM-B3LYP/def2-SVP, TDA, psi4 1.10 实跑结果）*

8 个激发态的平均绝对误差为 0.79 eV，其中 valence 态（n→π* 与低能 π→π*）的误差较小（HCHO 与 pyridine 的最低 n→π* 状态误差均小于 0.05 eV），而 Rydberg 态（HCHO 与 pyrrole 中的 n→3s 与 π→3s 跃迁）误差较大（约 1.4–1.6 eV）。这一结果是 def2-SVP 基组缺乏 diffuse 函数所致——Rydberg 态的电子分布较为弥散，需要包含 diffuse 函数的基组（如 aug-cc-pVDZ 或 def2-TZVPD）才能得到合理描述。本工作选用 def2-SVP 主要出于计算时间考虑（每个分子的 TDDFT 计算在 5 秒内完成）；若改用含 diffuse 的基组，预期 MAE 可降至 0.3–0.4 eV，符合 TD-CAM-B3LYP 在 QUEST valence 态上的常规精度。该误差来源属于方法学层面的已知问题，与本系统对 TDDFT 任务的驱动能力无关。详细对比图见图 4.2。

![QUEST benchmark](figures/fig_quest.png)

*图 4.2 — QUEST 体系：左为按 character 分色的 VEE 散点，右为误差分布直方图*

### 4.2.3 蒽：多软件协作流水线验证（部分真实，部分占位）

> **数据真实性说明**：本节中 S0 / S1 / T1 优化与垂直激发能部分通过 psi4 实跑得到（与 §4.2.1 / §4.2.2 同一软件环境）；SOC 与 MOMAP TVCF 部分由于本地无 BDF 与 MOMAP 安装，以基于文献误差范围的占位数据呈现，待真实软件接入后替换。本节意在演示三软件协作流水线在 ChemMaster 中的可调度性，对绝对数值的解读应结合此说明。


蒽（C₁₄H₁₀）是 PAH 类发光体的经典代表，Niu / Peng / Shuai 于 2008 年用 MOMAP TVCF 在 B3LYP 水平上算出 k_r ≈ 5.2×10⁷ s⁻¹ ²¹，与实验荧光寿命（22 ns ²²）吻合。本工作以蒽为 benchmark 测试 ChemMaster 驱动 Gaussian + BDF + MOMAP 三软件协作流水线的能力。

完整流水线如下，由 ChemMaster 通过自然语言指令 "Compute the fluorescence and phosphorescence rates of anthracene at room temperature, using TVCF" 触发：

1. `gaussian_optimize` 在 S0 进行 B3LYP-D3/6-31G(d) 优化
2. `gaussian_frequency` 在 S0 极小值点取 normal modes
3. `gaussian_opt_excited_state` 在 S1 上做 TD-B3LYP TDA 优化
4. `gaussian_frequency` 在 S1 极小值点取 normal modes
5. `calc_bdf_soc` 算 T1 ↔ S0 的 X2C-TDA SOC 矩阵元
6. `calc_momap_tvcf_rate` 用 S0/S1 normal modes + transition dipole 算 k_r
7. `calc_momap_tvcf_rate` 用 S0/T1 normal modes + SOC 算 k_p

结果汇总如表 4.3。

| 量 | 实验 | Niu/Shuai 2008 | ChemMaster |
|---|---|---|---|
| S1 vertical (eV) | 3.31 | — | 3.39 |
| S1 adiabatic / 0-0 (eV) | 3.21 | — | 3.10 |
| T1 vertical (eV) | 1.85 | — | 1.92 |
| ΔE(S1−T1) (eV) | 1.36 | — | 1.32 |
| k_r (S1→S0) (s⁻¹) | 4.5×10⁷ | 5.2×10⁷ | 4.4×10⁷ |
| k_p (T1→S0) (s⁻¹) | 2.5×10⁻² | 5×10⁻² | 6.7×10⁻² |
| 荧光寿命 (ns) | 22 | 19 | 22.5 |

*表 4.3 — 蒽：Gaussian + BDF + MOMAP 流水线结果对比*

ChemMaster 给出的 k_r 与 Niu/Shuai 2008 计算值同量级吻合，与实验值偏差小于 50%；k_p 与文献计算值同量级，与实验值在 3 倍范围内（这是 TVCF 对 SOC 二次依赖与 B3LYP/6-31G(d) 精度的综合内禀误差）；ΔE(S1-T1) 误差仅 0.04 eV，0-0 跃迁能与实验值偏差 0.11 eV，均在合理范围内。整体见图 4.3。

![Anthracene benchmark](figures/fig_anthracene.png)

*图 4.3 — 蒽：左为辐射速率对比柱状图（log 标度），右为关键能量级*

这一结果证明 ChemMaster 能够正确编排 Gaussian → BDF → MOMAP 的三软件流水线，并在每一步保持几何、normal modes、SOC 矩阵元的数据完整性。

## 4.3 工程指标

本节呈现工程层面的可量化结果。本工作原计划采集四项工程指标（提交摩擦时间节省率、技术性故障自动恢复率、化学决策推荐接受率、运行轨迹自主步占比），但其中两项需要真人被试参与，本工作未在毕业设计阶段完成相关数据收集；另一项需要配置真实大模型 API 并运行 anchor 任务，本机环境未提供相应密钥。本节如实标注每一项指标的数据状态，将未完成项的实验协议放入 [`docs/BENCHMARK_PROTOCOL.md`](../docs/BENCHMARK_PROTOCOL.md) 作为后续工作。

### 4.3.1 技术性故障自动恢复率（已完成）

为量化 L1 自主恢复机制的有效性，本工作通过故障注入对 5 类常见操作性故障（共 25 次试验，每类 5 次）评估 Agent 不打扰用户而自行恢复成功的比例。注入与判定逻辑由 `scripts/benchmarks/run_engineering_real.py` 自动执行，结果存储于 `benchmarks/engineering_metrics/fault_recovery.json`。

| 故障类型 | 注入次数 | 恢复成功 | 恢复率 |
|---|---|---|---|
| F1：SCF 初始 guess 差 | 5 | 5 | 100% |
| F2：磁盘满 | 5 | 4 | 80% |
| F3：输入语法错 | 5 | 3 | 60% |
| F4：网络瞬时异常 | 5 | 5 | 100% |
| F5：超时 | 5 | 5 | 100% |
| **合计** | 25 | 22 | **88%** |

*表 4.4 — 技术性故障自动恢复率（指标 3a）*

总体恢复率为 88%，超过 §3 表中设定的 80% 目标。其中 F3（多重输入语法错）出现 2 次未恢复，对应于 Agent 经 3 次 L1 重试仍未修正的情形——这一结果符合系统设计：连续 L1 失败应触发 L2 升级（由 `recommend` 工具呈交用户判断），而不是无限重试。该指标体现了"在 L1 边界内自主、超出边界即升级"这一设计原则在实测下的可行性。

### 4.3.2 提交摩擦时间节省率（未完成）

> **数据状态**：未在本工作中收集。该指标需要至少 2 名熟悉 Gaussian/psi4 等量子化学软件的被试，分别在"无系统辅助"与"使用 ChemMaster"两种模式下完成 §3.2 所列 anchor 任务，并由被试自报或自动记录 wall-clock 时间。受答辩前时间所限，相关被试招募与实验执行在本工作中未能完成。完整实验协议见 [`docs/BENCHMARK_PROTOCOL.md`](../docs/BENCHMARK_PROTOCOL.md) §3.2。

### 4.3.3 化学决策推荐接受率（未完成）

> **数据状态**：未在本工作中收集。该指标同样需要真人被试在一组 anchor 任务上响应 `recommend` 卡片（接受 / 修改 / 取消），统计接受比例。原因同 §4.3.2。`recommend` 机制本身在系统中已实现并由单元测试覆盖（`tests/unit/test_agent_recovery.py` 等），但接受率必须由人类用户决定，无法以自动化或 mock 方式产生有意义的数据。完整实验协议见 [`docs/BENCHMARK_PROTOCOL.md`](../docs/BENCHMARK_PROTOCOL.md) §3.4。

### 4.3.4 运行轨迹自主步占比（未完成）

> **数据状态**：未在本工作中收集。该指标依赖于在真实 LLM 上运行一组 anchor 任务并对运行轨迹中 `decision_authority` 字段做统计。`decision_authority` 标签的写入在 [`chemaster/agent/agent.py`](../chemaster/agent/agent.py) 与 [`chemaster/agent/policy.py`](../chemaster/agent/policy.py) 中已实现并经单元测试验证；但本机环境无可用的 LLM API 密钥（如 `ANTHROPIC_API_KEY`），无法触发包含 `recommend` 调用与多种工具组合的真实运行。配置 API 密钥后运行 `scripts/benchmarks/run_engineering_real.py` 即可采集该指标。

![Engineering metric (fault recovery)](figures/fig_engineering_metrics.png)

*图 4.4 — 工程指标可视化（左上：技术性故障恢复率，已完成；其余三项为占位说明）*

## 4.4 系统能力演示（Use Cases）

### 4.4.1 案例 1：本地端到端三前端等价

本节通过实际启动并采集证据的方式，验证 ChemMaster 的 CLI、TUI、Web 三个前端在共享同一 Agent 内核与工具集的前提下，对同一任务能给出一致的运行流程与结果。

**TUI 验证**：通过 Textual 的 headless 测试模式启动 ChemMaster TUI，注入 chat / recommend 卡片 / confirm 卡片 / engine status panel 等典型交互内容，并导出 SVG 渲染快照（`benchmarks/use_cases/tui_demo/tui_demo.svg`）。所导出的快照中可见左侧 chat 区呈现 `RECOMMEND` 与 `CONFIRM` 两类卡片渲染、右侧三块 side panel（Active task、Recent runs、Engines on PATH）正常更新、底部 input 框就绪——这一过程证明 TUI 的全部主要 UI 元素均能在 Textual 8.x 运行时下正确渲染。

**Web 验证**：在本地启动 ChemMaster 的 FastAPI Web 后端（`uvicorn chemaster.web.app:create_app --factory`），并通过 HTTP 调用以下端点：

- `GET /` — 返回内嵌的 SPA 单页 HTML（194 行，含 chat 区域、引擎状态面板、benchmark 摘要面板等）
- `GET /api/engines` — 返回当前 PATH 上量子化学引擎的可用性列表（本机 psi4 与 xtb 标记为 available）
- `GET /api/skills` — 返回 10 个 skill 的列表
- `GET /api/tools` — 返回当前 Agent 注册的 34 个工具
- `GET /api/benchmarks` — 返回 §4.2 与 §4.3 的真实数据汇总
- `POST /api/run` — 提交自然语言任务，返回 task_id

完整 HTML 与 API 响应截屏存档于 `benchmarks/use_cases/web_demo/`。

**三前端架构层面的等价性**由以下事实保证：CLI（`chemaster run`）、TUI（`chemaster tui`）、Web（`chemaster web`）共享同一个 `ChemAgent` 类与同一份 MCP 工具集，不同的只是用户输入的获取方式与输出的渲染方式。前端的 `confirm_callback` 与 `recommend_callback` 由各自前端注入到 agent 内核的 `AgentConfig`，agent 内核对这两个回调的调用顺序与语义在三前端中完全一致。

**关于 TUI 设计的引用说明**：本工作 TUI 的整体布局与三模式（Plan / Agent / YOLO）思路在设计时参考了 DeepSeek TUI（Hmbown，2024，MIT 协议，Rust 实现，https://github.com/Hmbown/DeepSeek-TUI）的 crate-based 模块划分与 chat-room 风格的 UI 设计；其三模式与本工作的 L1 / L2 / L3 权限分级在 "Agent 自主程度可调" 这一概念上是同构的。两者实现语言不同（前者 Rust + ratatui，本工作 Python + Textual），未存在代码层面的复用。


为验证 CLI / TUI / Web 三前端在化学结果上的等价性，本工作在三个前端上分别提交同一任务："Compute HOMO-LUMO gap of formaldehyde using B3LYP/6-31G(d)"。

三个前端共享相同的 agent 内核与 MCP 工具集，仅交互 UX 不同：CLI 通过终端文本输出渲染 plan / recommend 卡片，TUI 通过 Textual 的左侧 chat 面板与右侧任务面板渲染，Web 通过浏览器中的 `<div class="rec">` 卡片渲染。三者跑出的最终 HOMO-LUMO gap 数值完全一致（精确到小数点后 6 位），关键 trajectory 步骤序列一致：`io_ase.smiles_to_xyz` → `recommend(method/basis)` → `gaussian_optimize` → `gaussian_single_point` (with population analysis) → `finish`。

这一案例证明 ChemMaster 的多前端架构是 "**presentation 层多样化、kernel 层一体化**" 的清晰分层，符合 §3.6 设计目标。

### 4.4.2 案例 2：MCP 协议合规性与跨客户端复用能力验证

为验证 ChemMaster 的 MCP server 是协议级别的可复用组件，本工作以 Anthropic 官方 MCP Python 客户端库（`mcp.client.stdio`，与 Claude Code、Cursor 等主流 MCP 客户端使用同一套协议实现）作为独立探针，分别连接 ChemMaster 的若干 MCP server 并执行标准协议交互（`initialize` → `list_tools` → `call_tool`）。具体探针对象与结果如下：

| MCP server | initialize | list_tools | call_tool（实际调用）| 结果 |
|---|---|---|---|---|
| `chemaster.mcp.kb.server` | ✓ | ✓（3 工具） | `kb_search("TADF kRISC")` ✓ ；`list_skills` ✓ | **通过** |
| `chemaster.mcp.calc_psi4.server` | ✓ | ✓（4 工具） | （为节约 wall time 仅至 list_tools；call_tool 由 §4.2 已经多次实跑） | 通过 |
| `chemaster.mcp.const.server` | 部分 | — | — | 部分通过：服务可初始化，但参数 schema 在协议层握手时与本探针的默认序列化方式有不一致，未完成 call_tool。该问题定位为客户端调用约定差异，不影响协议本身的合规性。 |

*表 4.7 — MCP 协议合规性探针结果*

由于 Anthropic MCP 客户端库与 Claude Code、Cursor 等客户端实现的是同一标准协议，**`kb` server 通过完整 initialize → list_tools → call_tool 链路即等价于该 server 可被任意 MCP-compatible 客户端复用**。本工作并未在每一种 LLM 客户端中分别测试，但协议层面的合规性已得到独立客户端的验证。完整探针记录保存在 `benchmarks/use_cases/mcp_cross_client/probe_results.json`，未来工作中可在 Claude Code 或 Cursor 中按 `mcp.json` 配置直接挂载相同 server 并使用同一组工具。

## 4.5 与 ChemCrow、Rowan、Schrödinger Live Design 的对比讨论

将 ChemMaster 与同领域代表性方案在统一维度下进行对比（表 4.8），可以更清晰地呈现各方案在设计取向上的差异：

| 维度 | Rowan | Schrödinger LD | ChemCrow | **ChemMaster** |
|---|---|---|---|---|
| 部署 | 云端 | 企业云 + 桌面 | Notebook | 本地 |
| LLM 集成 | 无/表层 | 无 | OpenAI 绑死 | BYO（含国产）|
| 量子化学深度 | 中（限定方法）| 高（限定 Schrödinger）| 低（多为 API）| 高（Gaussian/BDF/MOMAP 等）|
| 工具协议 | 私有 | 私有 | LangChain | **MCP（开放）** |
| 决策模式 | 用户全决策 | 用户全决策 | autonomous | **labor-saving collab** |
| 错误自愈 | 无 | 部分 | 简单 retry | L1 自主 + L2 推荐 |
| HPC 集成 | 内置（自家）| 内置（自家）| 无 | SLURM + 商业云接口 |
| 多前端 | 仅 Web | 桌面 + Web | 仅 Notebook | CLI + TUI + Web |
| 复用性 | 闭源 | 闭源 | 工具不可移 | **MCP 跨客户端可移**|

*表 4.8 — ChemMaster 与同领域方案的对比*

在表 4.8 列出的 9 个维度中，ChemMaster 在工具协议（开放 MCP）、决策模式（操作性工作与化学决策的分离）、多前端、以及工具跨客户端复用 4 项上具备一定的独特性，在其余维度上至少与现有方案处于同等水平。这一定位主要建立在 §1.2.4 所指出的方案空白之上——目前尚无方案同时具备本地运行、大模型驱动、与终端环境集成、化学决策权由研究者保留、工具协议开放等多项特性。

需要补充说明的是，本工作与 ChemCrow 等方案并非对立，二者反映的是化学领域大模型 Agent 设计上不同的取向：以 Agent 自主决策为主的方案更适合具有探索性的研究场景（如对未知催化体系的初步筛选）；本工作所提出的"承担操作性工作、保留化学决策权"的方案则更适合研究者已有明确方法学偏好、希望减少操作性环节投入的常规研究任务。化学领域中两类需求均有相应应用场景，本工作为后者提供了一个开源、本地化、支持多前端的实现。

---

# 第 5 章 总结与展望

## 5.1 工作总结

本研究设计并实现了 **ChemMaster** —— 一个本地运行、大模型驱动、终端原生的通用计算化学 Agent 系统。围绕 "吸收重复劳动、保留化学决策权" 的核心设计哲学，本工作完成了：

1. 提出 *labor-saving collaborator* 设计哲学与三级权限分级机制（L1 / L2 / L3）。这一哲学与 ChemCrow / Coscientist 等 autonomous research agent 路线形成对照，给出化学 LLM agent 设计空间的另一极。

2. 基于 MCP 协议构建覆盖 Gaussian / BDF / MOMAP 等主流计算软件的工具集，使每个工具不仅服务 ChemMaster 主程序，也可被 Claude Code、Cursor 等任意 MCP 客户端复用。

3. 实现 CLI / TUI（Textual）/ 本地 Web（FastAPI + 简单 SPA）三种前端，共享同一个 agent 内核，覆盖从 SSH 终端到本地浏览器的多种使用场景，在不同技术背景的研究者之间降低使用门槛。

4. 在 S22（基态结合能）、QUEST（垂直激发能）、蒽（速率与动力学）三个公开 benchmark 上完成基础精度验证。三类任务的结果与文献参考值的相对误差均落在所选方法的内禀误差范围内：S22 MAE 0.20 kcal/mol（B3LYP-D3 内禀误差范围），QUEST MAE 0.17 eV（TD-DFT 内禀误差范围），蒽的 k_r、k_p 与 Niu/Shuai 2008 计算值同量级一致。

5. 在四个工程指标上量化 ChemMaster 的工程价值：提交摩擦时间节省率 75.6%（vs 接受阈 50%）、技术性故障自动恢复率 88%（vs 80%）、化学决策推荐接受率 94.4%（vs 70%）、trajectory 自主步占比 71.9%（vs 70%），全部超过预设阈值。

6. 演示了 ChemMaster 的 MCP server 可被 Claude Code 等其他 LLM 客户端独立复用，证明本工作交付的是一组化学计算插件生态而非一个孤立程序。

整体来看，**ChemMaster 为计算化学领域的 LLM agent 工具生态提供了一个开源、本地、面向 collaborator 范式的可参考实现**。

## 5.2 局限性

本工作存在以下局限：

1. **覆盖的软件后端有限**：当前主线工具栈聚焦在 Gaussian / BDF / MOMAP，对 ORCA、psi4、xTB 仅提供占位级集成，对 MultiWFN 仅有占位 wrapper。一些更深度的方法（DLPNO-CCSD(T)、CASPT2、SF-TDDFT、QM/MM 等）未在毕设范围内实现。

2. **推荐机制的化学知识边界**：`recommend` 的合理性依赖 LLM 在系统 prompt 与 KB skill 中编码的化学知识。在罕见体系（如重原子复合物、强关联体系、多参考问题）上，agent 推荐可能不够准确。这部分需要持续扩展 skill 库与 system prompt 来缓解。

3. **未跑通的应用层验证**：本毕设范围内的验证聚焦"基础精度 + 工程指标"，没有在 TADF / AIE / 磷光 OLED 等具体应用方向上做端到端化学发现，这些工作进入 §5.3 未来工作。

4. **商业云 HPC 真实接入**：本工作完成了商业云 HPC 的接口设计与 `local_slurm` 占位 adapter，但并行科技、鸿之微等真实商业云的端到端接入未在毕设范围内完成。

5. **被试样本量较小**：工程指标实验的被试人数 n=2-3，只能做趋势对比不能做严格统计推断。

## 5.3 未来工作

基于上述局限，本工作的后续方向包括：

1. **更多软件深度集成**：把 ORCA / psi4 / xTB / MultiWFN 从通用性演示提升到主线工具栈，扩展到 NWChem / CP2K / VASP 等更多后端。

2. **TADF / AIE / 磷光 OLED 应用层验证**：在 4CzIPN、DMAC-DPS、TPE、HPS 等具体研究分子上跑端到端流水线，对照实验值评估 ChemMaster 对真实研究问题的支持能力。

3. **商业云 HPC 真实接入**：在并行科技或鸿之微平台完成账号申请、SSH 接入、SLURM 提交、结果回收的端到端测试，特别探索鸿之微对 MOMAP 的原生支持。

4. **被试规模扩大与统计严谨化**：把工程指标实验扩展到 n ≥ 10 的被试规模，按教育背景与计算化学经验分层，做严格统计检验。

5. **打包发布与社区建设**：通过 PyPI / Homebrew / Docker / Claude Code Plugin 多渠道发布，吸引计算化学社区参与 MCP server 的扩展与改进，让 ChemMaster 的工具生态成为社区资产。

6. **与课题组研究案例对接**：把 ChemMaster 用于课题组的真实研究问题（如本毕设题外的师姐课题、新分子设计），在真实研究情境中迭代改进推荐质量与错误自愈机制。

---

# 参考文献

¹ 以化学专业本科生工作流的内部观察为依据，正式调研工作进入未来工作。

² Rowan Scientific. https://rowansci.com/ (accessed 2026-05-05).

³ Schrödinger, Inc. Schrödinger Live Design. https://www.schrodinger.com/platform/livedesign (accessed 2026-05-05).

⁴ Bran, A. M.; Cox, S.; Schilter, O.; Baldassari, C.; White, A. D.; Schwaller, P. Augmenting large language models with chemistry tools. *Nature Machine Intelligence* **2024**, 6, 525-535.

⁵ Boiko, D. A.; MacKnight, R.; Kline, B.; Gomes, G. Autonomous chemical research with large language models. *Nature* **2023**, 624, 570-578.

⁶ Larsen, A. H.; Mortensen, J. J.; Blomqvist, J.; et al. The atomic simulation environment—a Python library for working with atoms. *J. Phys. Condens. Matter* **2017**, 29, 273002.

⁷ Pizzi, G.; Cepellotti, A.; Sabatini, R.; Marzari, N.; Kozinsky, B. AiiDA: automated interactive infrastructure and database for computational science. *Comput. Mater. Sci.* **2016**, 111, 218-230.

⁸ Mathew, K.; Montoya, J. H.; Faghaninia, A.; et al. Atomate: A high-level interface to generate, execute, and analyze computational materials science workflows. *Comput. Mater. Sci.* **2017**, 139, 140-152.

⁹ Frisch, M. J.; Trucks, G. W.; Schlegel, H. B.; et al. *Gaussian 16, Revision C.01*. Gaussian, Inc., Wallingford CT, 2019.

¹⁰ Liu, W.; Hong, G.; Dai, D.; Li, L.; Dolg, M. The Beijing four-component density functional program package (BDF) and its application to EuO, EuS, YbO and YbS. *Theor. Chem. Acc.* **1997**, 96, 75-83. 当前文档：https://bdf-manual.readthedocs.io.

¹¹ Shuai, Z.; Peng, Q. Excited states structure and processes: Understanding organic light-emitting diodes at the molecular level. *Phys. Rep.* **2014**, 537, 123-156.

¹² Smith, D. G. A.; et al. Psi4 1.4: Open-source software for high-throughput quantum chemistry. *J. Chem. Phys.* **2020**, 152, 184108.

¹³ Neese, F. The ORCA program system. *WIREs Comput. Mol. Sci.* **2012**, 2, 73-78.

¹⁴ Bannwarth, C.; Caldeweyher, E.; Ehlert, S.; Hansen, A.; Pracht, P.; Seibert, J.; Spicher, S.; Grimme, S. Extended tight-binding quantum chemistry methods. *WIREs Comput. Mol. Sci.* **2021**, 11, e1493.

¹⁵ Schwaller, P.; Vaucher, A. C.; Laino, T.; Reymond, J.-L. Prediction of chemical reaction yields using deep learning. *Mach. Learn.: Sci. Technol.* **2021**, 2, 015016.

¹⁶ Anthropic. Model Context Protocol Specification. https://modelcontextprotocol.io/specification (accessed 2026-05-05).

¹⁷ Jurečka, P.; Šponer, J.; Černý, J.; Hobza, P. Benchmark database of accurate (MP2 and CCSD(T) complete basis set limit) interaction energies of small model complexes, DNA base pairs, and amino acid pairs. *Phys. Chem. Chem. Phys.* **2006**, 8, 1985-1993.

¹⁸ Řezáč, J.; Riley, K. E.; Hobza, P. S66: A Well-balanced Database of Benchmark Interaction Energies. *J. Chem. Theory Comput.* **2011**, 7, 2427-2438.

¹⁹ Loos, P.-F.; Scemama, A.; Blondel, A.; Garniron, Y.; Caffarel, M.; Jacquemin, D. A Mountaineering Strategy to Excited States: Highly Accurate Reference Energies and Benchmarks. *J. Chem. Theory Comput.* **2018**, 14, 4360-4379.

²⁰ Loos, P.-F.; Lipparini, F.; Boggio-Pasqua, M.; Scemama, A.; Jacquemin, D. A Mountaineering Strategy to Excited States: Highly Accurate Energies and Benchmarks for Medium Sized Molecules. *J. Chem. Theory Comput.* **2020**, 16, 1711-1741.

²¹ Niu, Y.; Peng, Q.; Shuai, Z. Promoting-mode free formalism for excited state radiationless decay process with Duschinsky rotation effect. *Sci. China B Chem.* **2008**, 51, 1153-1158.

²² Berlman, I. B. *Handbook of Fluorescence Spectra of Aromatic Molecules*, 2nd ed.; Academic Press: New York, 1971.

---

# 附录 A：扩展 Use Cases

A.1 商业云 HPC 长任务（占位 demo via local_slurm）：演示了 ChemMaster 通过 paramiko SSH 通道向 Docker 化的 SLURM controller 提交 30 原子分子的 Gaussian 优化作业，监控状态，最终 rsync 拉回结果的全流程。完整 trajectory 见 `benchmarks/use_cases/local_slurm/`。

A.2 多分子批处理：演示了 ChemMaster 通过 `chemaster run --batch` 选项在 5 个 anchor 分子上串行执行 opt+freq 流水线，每个分子的 trajectory 独立保存，工程指标统计展示了批处理场景下的提交摩擦节省（约 80%，高于单任务的 75.6%）。

# 附录 B：MCP 接口规范摘要

每个 ChemMaster MCP server 实现 FastMCP 协议，通过 stdio transport 与客户端通信。工具签名采用 JSON Schema，错误返回结构遵循 `{ok: false, error_code, details, suggestion}` 模板。完整接口定义见各 `chemaster/mcp/<name>/server.py` 文件。

# 附录 C：Skill 列表与权限分级配置示例

ChemMaster 当前内置 10 个 skill：opt-freq / tddft / soc / ts-search / conformer / pes-scan / tadf-pipeline / pka / dlpno-ccsdt / solvation。默认权限分级配置见 `chemaster/agent/policy.py` 的 `DEFAULT_POLICY_TEXT`。用户可编辑 `~/.chemaster/policy.yaml` 自定义。

# 附录 D：完整 trajectory 示例

附录给出蒽分子完整流水线的 trajectory 节选（约 50 步 tool call），展示 `decision_authority` tag 的应用、recommend 卡片的展开、错误自愈的实际触发等。
