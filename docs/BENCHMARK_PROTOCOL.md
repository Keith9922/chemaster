# BENCHMARK_PROTOCOL.md — ChemMaster 验证实验协议

> 本文档定义 ChemMaster 毕设论文 §4 测试与验证章节使用的所有 benchmark 与工程指标的**测量协议**。
> 协议先行，再做实验，论文里直接引这份文档。
>
> 文档版本：v1.0 (2026-05-05)

---

## 1. 总体设计

ChemMaster 的验证分两部分：

1. **化学层验证**（基础精度）：3 个公开 benchmark 测三类不同任务上的计算正确性
2. **工程层验证**（提交摩擦）：3 个工程指标量化 agent 替研究者省了多少机械劳动 + 化学决策辅助质量

每项验证都给出明确的：**测量对象 / 测量方法 / 接受标准 / 数据存放位置 / 出图方式**。

---

## 2. 化学层验证（基础精度）

### 2.1 Benchmark 1：S22 弱相互作用基准

**目的**：证明 ChemMaster 在 Gaussian 上能正确驱动基态优化与单点能量，结果与 CCSD(T)/CBS 参考值一致。

**测量对象**：S22 数据集中的 5 个体系（按计算成本从低到高）：
1. Water dimer (H₂O dimer, hydrogen-bonded)
2. Methane dimer (CH₄ dimer, dispersion-bound)
3. Ethene-ethyne (C₂H₄...C₂H₂, mixed)
4. Benzene-methane (C₆H₆...CH₄, dispersion)
5. Benzene dimer T-shape (C₆H₆ T-stack)

**计算方法**：
- 单点能量：B3LYP-D3(BJ) / def2-TZVP
- 几何：使用 S22 数据集提供的标准几何（不重新优化）
- 结合能 = E(complex) − E(monomerA) − E(monomerB) + BSSE 校正（counterpoise）

**参考值来源**：
- Jurečka, P.; Šponer, J.; Černý, J.; Hobza, P. *Phys. Chem. Chem. Phys.* **2006**, 8, 1985-1993.
- Řezáč, J.; Riley, K. E.; Hobza, P. *J. Chem. Theory Comput.* **2011**, 7, 2427-2438. (S22A 修订值)

**接受标准**：
- 5 个体系平均绝对误差 (MAE) < 0.5 kcal/mol（B3LYP-D3 在 S22 上的内禀误差范围）
- 单一体系最大误差 < 1.0 kcal/mol
- 注：误差超过此范围不是 bug，可能是 BSSE 处理或基组完备度问题，需在论文中讨论

**数据存放**：
- 输入：`benchmarks/s22/inputs/<system>.xyz` + `benchmarks/s22/protocol.yaml`
- 参考值：`benchmarks/s22/reference_values.yaml`
- 结果：`benchmarks/s22/results/<system>/result.json`
- 汇总：`benchmarks/s22/summary.json`（自动生成）

**出图**：
- 散点图：x=参考值, y=ChemMaster 计算值，含 y=x 参考线
- 误差柱状图：5 个体系的 MAE
- 输出位置：`benchmarks/s22/figures/`

---

### 2.2 Benchmark 2：QUEST 激发态基准

**目的**：证明 ChemMaster 在 Gaussian TDDFT 上能正确算出垂直激发能，结果在 TD-DFT 内禀误差范围内（vs CC3 / CASPT2 高精度参考）。

**测量对象**：QUEST 数据集中的 3-5 个小有机发色团：
1. Formaldehyde (HCHO) - n→π* + π→π*
2. Pyridine - π→π* + n→π*
3. Pyrrole - π→π*
4. (可选) Furan - π→π*
5. (可选) Acetaldehyde (CH₃CHO)

**计算方法**：
- 几何优化：B3LYP-D3(BJ) / def2-TZVP（基态）
- 垂直激发能：TD-CAM-B3LYP / def2-TZVP（前 4 个单重激发态 S1/S2/S3/S4 + 前 2 个三重态 T1/T2）
- TDA = full TDDFT 都跑（用于内部对比）

**参考值来源**：
- Loos, P.-F.; Scemama, A.; Blondel, A.; Garniron, Y.; Caffarel, M.; Jacquemin, D. *J. Chem. Theory Comput.* **2018**, 14, 4360-4379. (QUEST#1)
- Loos, P.-F.; Lipparini, F.; Boggio-Pasqua, M.; Scemama, A.; Jacquemin, D. *J. Chem. Theory Comput.* **2020**, 16, 1711-1741. (QUEST#3)
- 数据库：https://lcpq.github.io/QUESTDB_website/

**接受标准**：
- TD-CAM-B3LYP 与 CC3 参考值的平均绝对误差 < 0.4 eV（TD-DFT 在 QUEST 小分子上的内禀误差）
- 单一激发态最大误差 < 0.6 eV
- 接受标准注：CAM-B3LYP 的系统性蓝移（通常 +0.1～+0.3 eV）是已知特征，论文中说明

**数据存放**：与 S22 同结构，路径替换为 `benchmarks/quest/`

**出图**：
- 散点图：x=CC3 参考激发能, y=TD-CAM-B3LYP 计算值
- 误差分布：按激发态 character (n→π* / π→π* / Rydberg) 分类的误差箱线图
- TDA vs full TDDFT 对比柱状图

---

### 2.3 Benchmark 3：蒽（anthracene）速率与动力学基准

**目的**：证明 ChemMaster 能驱动 Gaussian + BDF + MOMAP 三软件协作流水线，在简单 PAH 上算出与文献一致的荧光与磷光速率。

**测量对象**：蒽分子（C₁₄H₁₀）的：
- S0 → S1 荧光辐射速率 k_r
- T1 → S0 磷光速率 k_p（含 SOC 修正）
- 0-0 跃迁能量 E(0-0) S1 与 T1
- ΔE(S1-T1) 单三重态能隙
- (可选) 振动分辨发射光谱

**计算方法**（流水线）：
1. **基态优化** (Gaussian)：B3LYP-D3(BJ) / 6-31G(d) (S0 minimum)
2. **激发态几何优化** (Gaussian)：TD-B3LYP / 6-31G(d) (S1 minimum, T1 minimum, TDA)
3. **频率计算** (Gaussian)：S0 / S1 / T1 各点的 normal modes
4. **SOC 矩阵元** (BDF)：X2C-TDA / def2-SVP，T1 → S0 SOC matrix elements
5. **TVCF 速率** (MOMAP)：
   - k_r (S1 → S0)：使用 S0 / S1 normal modes + Duschinsky matrix
   - k_p (T1 → S0)：使用 SOC + S0 / T1 normal modes

**参考值来源**：
- 实验：
  - Niwa, A.; Kobayashi, T.; Nagase, T.; Goushi, K.; Adachi, C.; Naito, H. *Appl. Phys. Lett.* **2014**, 104, 213303. (蒽荧光寿命)
  - Marchetti, A. P.; Kearns, D. R. *J. Am. Chem. Soc.* **1967**, 89, 768. (蒽磷光寿命，经典数据)
- 计算 reference：
  - Peng, Q.; Yi, Y.; Shuai, Z.; Shao, J. *J. Am. Chem. Soc.* **2007**, 129, 9333. (蒽 TVCF 速率，Shuai 组经典论文)
  - Niu, Y.; Li, W.; Peng, Q.; Geng, H.; Yi, Y.; Wang, L.; Nan, G.; Wang, D.; Shuai, Z. *Mol. Phys.* **2018**, 116, 1078. (MOMAP 综述)

**接受标准**：
- k_r：与 Shuai 组计算 reference 在数量级内一致（绝对误差 < 1 个数量级）
- k_p：同上
- ΔE(S1-T1)：与文献计算值误差 < 0.2 eV
- 0-0 跃迁能：与实验值误差 < 0.3 eV

**数据存放**：`benchmarks/anthracene/`

**出图**：
- 流水线图（数据流：Gaussian → BDF → MOMAP）
- 速率对比柱状图（实验 vs 计算 vs ChemMaster）
- 振动分辨光谱（如果跑通）

---

## 3. 工程层验证（提交摩擦）

### 3.1 总体说明

工程层验证测量 ChemMaster 替研究者省了多少劳动、agent 化学判断质量如何、trajectory 中自主步占比多大。

**关键设计决策**：

- **被试招募**：≥ 2 名同学，最好是不同实验经验级别（高年级 / 低年级各 1）
- **任务集**：从化学层 benchmark 中选 anchor 任务（避免新分子）
- **计时方法**：被试自报时间 + ChemMaster 自动 trajectory 时间戳
- **统计**：N=2 时只报均值与个体值，不做统计检验；N≥3 时报均值 ± 标准差

### 3.2 指标 5：提交摩擦时间节省率

**定义**：(t_human − t_agent) / t_human × 100%

**任务集**（每被试做以下 3 个）：
1. **任务 A**（简单）：水分子 B3LYP/6-31G(d) opt + freq
2. **任务 B**（中等）：苯分子 TD-B3LYP/def2-SVP，前 3 个单重激发态
3. **任务 C**（复杂）：HCHO Gaussian opt → TDDFT → 选取 S1 几何 → 解析输出

**人工 baseline 测量**（被试做）：
- 计时起点：被试看到任务描述
- 计时终点：被试输出包含目标数值的 markdown 报告
- 被试可以查文献、问任何人，但不可以使用 ChemMaster
- 中途允许吃饭、休息——但纯计算 wall time 之外的时间要扣除（被试自报）

**ChemMaster 测量**：
- 计时起点：用户在 CLI / TUI / Web 输入自然语言指令
- 计时终点：ChemMaster 完成 finish 工具调用
- 计算 wall time 已扣除（不重复计入）

**接受标准**：节省率 ≥ 50%（v3.0 §3 指标 5）

**数据存放**：`runs/engineering_metrics/submission_friction/<subject_id>/<task>/`

**出图**：分组柱状图（每任务 × 每被试 × 人工 vs agent）

### 3.3 指标 3a：技术性故障自动恢复率

**定义**：N(成功自愈) / N(注入) × 100%

**故障注入清单**（在 anchor 任务上执行）：

| 故障类型 | 注入方式 | 期望恢复 |
|---|---|---|
| F1：SCF 不收敛 (initial guess 差) | 修改 initial guess 为 GWH 强制差值 | Agent 检测后改 guess、加 damping、增 maxiter |
| F2：磁盘临时空间不足 | 临时把 `/tmp/chemaster` 设为 50MB | Agent 清理或换路径 |
| F3：输入文件语法错（多余分号）| Mock LLM 偶尔给错语法 | Agent 看错误后修正重提交 |
| F4：网络抖动（HPC SSH 断）| Mock paramiko 偶尔抛 ConnectionError | Agent retry 3 次 |
| F5：超时 | 设故意低的 timeout | Agent 调高 timeout 重试 |

**注入次数**：每类故障 5 次 × 5 类 = 25 次试验

**接受标准**：≥ 80%（v3.0 §3 指标 3a）

**实施**：写故障注入测试套件 `tests/integration/test_fault_recovery.py`，自动跑、自动统计

**数据存放**：`runs/engineering_metrics/fault_recovery/<fault_type>/<trial>/`

**出图**：每类故障的恢复率柱状图

### 3.4 指标 3b：化学决策推荐接受率

**定义**：N(接受 agent 推荐) / N(总推荐) × 100%

**任务集**：从 3 个化学 benchmark 选 5-8 个 anchor，含至少：
- 1 个基态优化推荐
- 2 个 TDDFT 方法推荐
- 1 个 SOC 方法推荐
- 1 个虚频处理推荐

**实施**：被试在 ChemMaster 三前端中跑任务，每次 agent 弹 recommend 卡片时被试做：
- (a) 接受推荐
- (b) 修改后接受
- (c) 取消任务

记录每次的 (decision, reason)。**取消的也要记录**——被试要写一句话原因，论文 §4.3.3 用作"agent 推荐失败模式"分析。

**接受标准**：(a)+(b) 比例 ≥ 70%（v3.0 §3 指标 3b）

**数据存放**：`runs/engineering_metrics/recommendation_acceptance/<subject_id>/<task>/`

**出图**：饼图（接受 / 修改后接受 / 取消）+ 按推荐类型分类的接受率

### 3.5 指标 3c：Trajectory 自主步占比

**定义**：N(decision_authority="agent") / N(总 tool call) × 100%

**实施**：从指标 5 的所有 trajectory 中统计

**接受标准**：≥ 70%（v3.0 §3 指标 3c）

**意义**：自主步占比高 = agent 替研究者承担了大量机械劳动；占比低 = agent 越权太多 *或* 任务本身需要密集决策

**数据存放**：从 `runs/<task_id>/trajectory.jsonl` 中聚合统计

**出图**：堆叠柱状图（每任务 × {agent / user-binary / user-chemistry / system}）

---

## 4. Use Cases 演示

### 4.1 案例 1：本地端到端三前端等价

**目的**：证明同一任务在 CLI / TUI / Web 三前端跑出一致结果。

**任务**："Compute HOMO-LUMO gap of formaldehyde using B3LYP/6-31G(d)"

**实施**：
1. 在 CLI 跑：`chemaster run "Compute HOMO-LUMO gap of formaldehyde using B3LYP/6-31G(d)"`
2. 在 TUI 跑：`chemaster tui` → 输入同样指令
3. 在 Web 跑：`chemaster web` → 浏览器输入同样指令

**接受标准**：三前端输出 HOMO-LUMO gap 数值相同（精确到小数点后 6 位）+ 关键 trajectory 步骤一致

**数据存放**：`benchmarks/use_cases/three_frontends/`

**出图**：三前端截图 + 输出数值对比表

### 4.2 案例 2：MCP 在 Claude Code 中复用

**目的**：证明 ChemMaster 的 MCP server 是真正的可复用组件，不是 monolithic 程序。

**任务**：在 Claude Code 中挂载 `chem.const` 和 `chem.kb` MCP，让 Claude Code 完成：
- 查询 Hartree → eV 换算因子
- 查询 def2-TZVP 基组的覆盖元素
- 列出 ChemMaster 的 skill 库

**实施**：
1. 在 `~/.config/claude-code/mcp.json` 配置 ChemMaster 的两个 MCP server
2. 启动 Claude Code，对话执行上述查询
3. 截图保存

**接受标准**：MCP 在 Claude Code 中能成功调用且返回正确结果

**数据存放**：`benchmarks/use_cases/mcp_cross_client/`

**前置条件**：必须先在 Phase 0 跑通这个 demo，否则相关 claim 不允许进入论文。

---

## 5. 实施时序

```
Week 1
  D1   写完本协议文档（即本文件）→ 已完成
  D2   故障注入测试套件 (tests/integration/test_fault_recovery.py)
  D3   benchmark 输入文件准备（S22 / QUEST / 蒽）
  D4   被试招募 + 时间约定

Week 2
  D5-7 三 benchmark 实际跑通（依赖工具 MCP 完工）
  D8-10 故障注入实验跑完，出指标 3a

Week 3
  D11-12 被试做人工 baseline（指标 5）
  D13-14 被试做 agent 任务（指标 3b + 5）
  D15   数据分析 + 出图

Week 4
  论文 §4 写作，引用本协议
```

---

## 6. 数据透明与复现

所有 benchmark 数据、运行 trajectory、对比脚本、图表生成代码均存放在仓库的：

- `benchmarks/<benchmark_name>/`
- `runs/`（gitignored，但每次实验后选关键 case 归档到 `benchmarks/<name>/runs_archive/`）
- `scripts/benchmarks/`（出图脚本）

毕业论文提交后，仓库可继续公开，**论文 §4 引用的所有数据点都可在仓库中找到对应原始数据 + 处理脚本**。
