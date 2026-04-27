# PITFALLS — 开发坑表

> 写每个 MCP / Skill 前**必读**。这些坑都是真实出现过的，不是假想。
> 如果你在开发中踩到新的坑，**立即补充进本文档**。

---

## 0. 总原则

- **化学计算不是普通工程任务**。错误不光是 crash，更多是"跑完了但结果错"。
- **错误是常态**。SCF 不收敛、虚频、几何卡死、内存爆 —— 都是日常，不是异常分支。
- **沉默地错才致命**。所有 MCP 必须返回 `warnings: [...]`；解析模块必须主动检查未收敛、未达阈值、对称性变化等。
- **复现比正确更重要**。一个能复现的错误结果，比一个复现不了的正确结果价值更高。

---

## 1. LLM 行为类坑

### 1.1 LLM 算数会幻觉
- ❌ "B3LYP 的 HF 交换分数是 0.21"（实际 0.20）。
- ✅ 所有数值参数从 KB / 配置文件读，不让 LLM 报数。

### 1.2 LLM 选基组/泛函会拍脑袋
- ❌ 给一个含 Pt 的体系推荐 6-31G(d)（不支持过渡金属）。
- ✅ Planner 必须先 RAG 检索 `kb/rules/basis_sets.yaml` 里的"适用元素"字段。

### 1.3 LLM 把 Hartree 当 kcal/mol
- ❌ "能量是 -76.4，约 -76 kcal/mol"。
- ✅ MCP 返回值必须带 `unit` 字段；公式库提供换算函数。

### 1.4 LLM 编造文献引用
- ❌ "根据 Goerigk 2017 (J. Chem. Phys. 147, 154103)，ωB97X-D 在……"
- ✅ 引用必须出自 RAG 检索结果，不允许凭空生成。所有引用配 DOI 校验。

### 1.5 LLM 在长 PES/复杂工作流中"失忆"
- ❌ 几何优化 50 步后 LLM 忘了原始用户意图。
- ✅ Plan 对象持久化到 `runs/<task-id>/plan.json`，Executor 每步从 plan 读，不依赖对话历史。

---

## 2. 量子化学软件坑

### 2.1 单位约定不统一
- psi4 默认 Hartree、Bohr；ORCA 默认 Hartree、Å；xTB 输入 Å、输出 Hartree；BDF 部分输入用 a.u.。
- ✅ 统一在 MCP 边界做转换：进 MCP 都用 Å + eV；出 MCP 都用 SI + 单位标签。

### 2.2 几何优化 ≠ 找到极小点
- 优化收敛 ≠ 是真极小点。**必须接频率计算**。出现虚频意味着这是过渡态或鞍点。
- ✅ Skill `opt-freq` 默认行为：优化后自动跑频率；有虚频自动沿模式位移重启。

### 2.3 频率计算必须用与优化一致的方法
- ❌ B3LYP/6-31G* 优化后用 B3LYP/def2-TZVP 算频率 → 得到错误 ZPE。
- ✅ MCP `frequency` 强制校验 `(method, basis)` 与上一步 `optimize` 一致；不一致报错。

### 2.4 SCF 不收敛常见且能修
- 常见原因：初猜差、对称性破缺、阻尼不足。
- 修复策略（**写进 skill**）：
  1. 重新选 guess（SAD → GWH → core hamiltonian）。
  2. 加大 damping，关掉 DIIS 几步后再开。
  3. 降基组先收敛，再用其结果做 guess 升基组。
  4. 关闭/打开对称性。
- MCP 返回 `converged: false` 时必须附带尝试过的策略列表。

### 2.5 几何优化卡死（trust radius 来回震荡）
- 修复策略：
  1. 切到冗余内坐标（redundant internal coords）。
  2. 减小初始 trust radius。
  3. 用 RFO 或 P-RFO 代替 BFGS。
- ORCA 默认比 psi4 鲁棒一些。

### 2.6 对称性意外开关
- psi4 默认开 C_n 对称，几何优化中可能"对称性突跳"。
- ✅ 默认 `symmetry: c1`；只有用户明确要求才打开高对称。

### 2.7 TDDFT 三元纠缠：泛函 / 长程修正 / 振子强度
- ❌ 用 B3LYP 算电荷转移激发态 → 严重低估能量。
- ✅ TDDFT skill 必须根据"是否是 CT 态"来选 ωB97X-D / CAM-B3LYP / LC-ωPBE 等长程修正泛函。判断 CT 态用 NTO 重叠或 Λ 诊断指标。

### 2.8 TDDFT 三重态用 Tamm-Dancoff（TDA）
- 标准 TDDFT 算 T1 经常出现"triplet instability"导致虚根。
- ✅ T1 默认用 TDA-DFT；S1 用全 TDDFT。

### 2.9 SOC 计算软件差异大
- ORCA 用 RI-SOMF 平均场近似，速度快但精度有限。
- BDF 支持完整 Breit-Pauli SOC + state-interaction，**这是为什么 TADF 流水线选 BDF 做 SOC**。
- ✅ TADF skill 写明：SOC 走 BDF，不走 ORCA。

### 2.10 半经验 (xTB) 结构 ≠ DFT 结构
- xTB 优化的几何对芳香共轭体系经常有偏差（键长、二面角）。
- ✅ 漏斗策略：xTB 做构象搜索找到候选 → DFT 重新优化每个候选。不要拿 xTB 几何直接进 TDDFT。

### 2.11 隐式溶剂模型选择
- 极性溶剂可以用 PCM/SMD；H 键体系用 SMD 或加几个显式水。
- COSMO-RS 需要参数化（不是所有软件都有），且对 ΔG_solv 才更准。
- ✅ Skill `solvation` 写明决策树。

### 2.12 文件名/路径含空格或中文
- psi4、ORCA 都对路径敏感。Mac 用户的 iCloud 路径"~/Library/Mobile Documents/..."经常出问题。
- ✅ 工作目录强制用 ASCII 安全的 `runs/<uuid>/`。提交前做 `assert path.is_ascii()`。

### 2.13 临时文件爆磁盘
- ORCA 大体系频率计算可能产生几十 GB 临时文件。
- ✅ 提交前预估磁盘需求，HPC MCP 检查 quota。本地默认设 `--tmp-dir` 到大盘。

### 2.14 内存估算与 `psi4 -m` / ORCA `%maxcore`
- ❌ 8 GB 机器跑 `%maxcore 16000` → OOM。
- ✅ MCP 自动按可用内存的 70% 设置；公式库给一个 `estimate_memory(method, n_basis)` 粗估。

### 2.15 并行核数与超线程
- 写 OMP_NUM_THREADS = 物理核数（不是逻辑核数）。MKL 线程过度认领会让 ORCA 内部并行打架。
- ✅ MCP 默认读 `os.cpu_count() // 2`（保守）；用户配置可覆盖。

### 2.16 ORCA 5 vs 6 输入格式有差异
- 关键字大小写、`%` 块语法略有变化。
- ✅ MCP 探测安装版本，按版本生成输入。

### 2.17 BDF 安装与执行环境
- BDF 需要 `BDFHOME` 环境变量；许可证文件路径要正确。
- ✅ MCP 启动时校验环境变量；缺失给清晰错误信息。

---

## 3. 数据/IO 坑

### 3.1 SMILES → 3D 结构的初始猜测
- RDKit `EmbedMolecule` 偶尔会失败（大环、桥接体系）。
- ✅ 备用：ETKDG 失败时调 `embed_multiple_confs` 多次取最低能；再失败用 `obabel --gen3d`。

### 3.2 立体异构 / 手性丢失
- SMILES 不带 `@` 标记会随机选构型。
- ✅ MCP 输入 SMILES 时校验立体注释；缺失时警告并默认 R 或最低能构型。

### 3.3 元素符号大小写
- `co` (钴) ≠ `CO` (一氧化碳)。SMILES 与 xyz 的解析器差异大。
- ✅ 始终用大写元素符号；解析时校验。

### 3.4 cclib 不支持所有版本/方法
- cclib 对某些 ORCA 6 的 TDDFT 输出解析不全。
- ✅ MCP `parse_cclib` 失败时回退到自写正则（针对 ORCA / BDF / psi4 各自的输出格式写一份兜底）。

### 3.5 输出文件编码
- 中文 Windows 上 ORCA 输出可能 GBK；Linux/Mac 上 UTF-8。
- ✅ 解析统一 `errors='replace'`，并在 manifest 记录编码。

### 3.6 JSON 不能直接放 `numpy` / `Quantity`
- 序列化必须先 `.tolist()` 或 `.magnitude`。
- ✅ 用统一的 `to_json_safe(obj)` 工具函数。

---

## 4. HPC / SLURM 坑

### 4.1 SSH 连接密码 vs key vs 跳板机
- 学校超算常用 LDAP 密码 + 一次性 key。Paramiko 的 key 有时不工作。
- ✅ 配置层支持：纯密码（不推荐）/ ssh-agent / 跳板机 ProxyCommand。

### 4.2 sbatch 队列墙时间预估
- 没人估得准。提交后 squeue 看 START_TIME 也不一定准。
- ✅ 给"乐观/中位/悲观"三个估计，UI 显示中位 + 悲观。

### 4.3 SLURM 脚本里的 `cd "$SLURM_SUBMIT_DIR"`
- 集群默认登录到 home，不是提交目录。
- ✅ 模板里强制 `cd "$SLURM_SUBMIT_DIR"`。

### 4.4 文件传输大小
- 大体系频率有几 GB 输出。`scp` 单文件超 4 GB 在某些老集群有问题。
- ✅ 用 `rsync` + 压缩；只拉关键文件（`.out`, `.molden`, `.hess`），临时文件留集群。

### 4.5 不同集群模块系统差异
- `module load orca/6.0` vs `spack load orca` vs 自编译 PATH。
- ✅ 配置层抽象 `pre_run_hook: "module load orca/6.0"`，用户填写自己集群的命令。

### 4.6 时区与时间戳
- 集群常是 UTC，本机可能是 CST。任务时间戳混乱。
- ✅ 所有时间戳存 ISO8601 + UTC；展示时本地化。

### 4.7 任务状态轮询频率
- 太频繁被超算管理员封；太稀疏用户体验差。
- ✅ 指数退避：开始 30s，逐步退到 5min；任务变化时立刻通知。

---

## 5. Agent / Skill / MCP 集成坑

### 5.1 MCP 工具描述被 LLM 误解
- 描述含糊会让 LLM 选错工具。
- ✅ 工具描述写"何时该用、何时不该用、典型示例"。每个 MCP server 配 `EVALS.md` 列出测试 prompt。

### 5.2 Skill 描述触发不准
- skill 描述太宽 → 误触发；太窄 → 不触发。
- ✅ 用 skill-creator 工具评估触发率。每个 skill 配 ≥ 5 个正例 + 5 个反例。

### 5.3 Skill 调用 MCP 时参数构造错
- LLM 看到 skill 文档后可能"自由发挥"参数。
- ✅ Skill 里给完整 JSON 示例；MCP 入参严格 schema 校验。

### 5.4 三段式被 LLM 跳过 Confirm
- LLM 急着干活，跳过用户确认。
- ✅ Confirm 不是 prompt 引导，是**架构层强制**：Executor 没拿到用户 confirm token 拒绝执行。

### 5.5 MCP 调用 vs Skill 内嵌脚本的优先级
- 遇到能用 MCP 又能写脚本的情况，LLM 偶尔选脚本。
- ✅ Skill 文档明确："xxx 操作必须用 MCP，不允许自己写 shell"。

### 5.6 长任务的进度反馈
- 跑 1 小时的优化没进度提示，用户以为卡了。
- ✅ MCP 支持 `stream=True`，从软件 stdout 抽取进度（SCF 迭代步、几何步）回吐给 TUI。

---

## 6. TUI（Textual）坑

### 6.1 Textual reactive 状态在子线程
- 计算阻塞主线程会冻结 TUI。
- ✅ 计算放 `asyncio.to_thread` 或 `subprocess`；状态更新走 `app.call_from_thread`。

### 6.2 终端图像协议兼容性
- iTerm2、Kitty、WezTerm 各自的协议不互通；tmux 里很多协议失效。
- ✅ 默认写盘 + 链接；探测到支持的终端再启用 inline。提供 `--no-inline-images` 兜底。

### 6.3 中文等宽字体
- Textual 默认按 Unicode East-Asian-Width 算，但某些字体宽度不一致 → 表格错位。
- ✅ 关键面板用 ASCII border；表格用 rich 的 `box=ROUNDED`。

### 6.4 SSH 远程使用 TUI
- 用户可能在 SSH 窗口里跑 chemaster。终端能力检测要可靠。
- ✅ 启动时跑一遍能力探测；不支持的功能 graceful degrade。

---

## 7. 测试与 CI 坑

### 7.1 真跑量化软件测试很慢
- 单元测试不该真跑 psi4。
- ✅ 用 mock：`tests/fixtures/` 放预生成的输出文件，MCP 接受 `--mock-output` 参数走文件回放。

### 7.2 集成测试要锁版本
- psi4 / ORCA 不同版本输出有差异，集成测试跨版本会假阳。
- ✅ Docker 镜像锁版本；CI 矩阵列出支持版本。

### 7.3 浮点比较不能用 ==
- 不同硬件、不同 BLAS 版本，能量末位经常差 1e-6。
- ✅ 用 `pytest.approx(rel=1e-5)` 比能量；几何用 `np.allclose(rtol=1e-3)`。

---

## 8. 安全 / 隐私坑

### 8.1 LLM API key 泄漏
- ❌ 写在配置文件里 commit。
- ✅ 只读环境变量或 `~/.chemaster/config.yaml`（`.gitignore` 含 `*.yaml` 但有 `!*.example.yaml`）。

### 8.2 用户分子结构上传给 LLM
- 用户的 SMILES / 几何可能是保密的。
- ✅ Plan 阶段把分子标识抽象成 `mol_001`；具体几何不进 prompt。提供 "minimize PII" 模式：把用户分子打一个 hash，LLM 只看 hash + 元数据（原子数、电荷、自旋）。

### 8.3 任意命令执行
- HPC SSH MCP 不能给 LLM 发任意 shell 的口子。
- ✅ MCP `chem.hpc.slurm` 只暴露 `submit / status / cancel / fetch`，不暴露 `exec_command`。

---

## 9. 文档 / 项目管理坑

### 9.1 文档过时
- 代码改了，文档没改 → 新会话被误导。
- ✅ 每次 PR 必须含文档变更或 `docs: not affected` 显式声明。CI 加 `docs-staleness` 检查。

### 9.2 多人/多会话冲突
- 不同会话对同一文件并行编辑会冲突。
- ✅ 大改动先创建 issue / PR；小改动直接 commit + push。每次会话开头 `git pull`。

### 9.3 README 与 CLAUDE.md 内容漂移
- 两个文档讲项目，慢慢说不一致。
- ✅ README 是对外、CLAUDE.md 是对 agent；前者讲"是什么、怎么用"，后者讲"怎么开发"。两者各 SoT，不重复。

---

## 10. 化学领域常识陷阱（**不懂化学的开发者必读**）

### 10.1 单点能 vs 几何优化
- "能量"在化学里**几乎从不**指单点能（fixed geometry 的能量）。指优化后极小点的能量 + ZPE + 热修正。

### 10.2 自旋多重度 = 2S+1
- 闭壳: 1（singlet）。开壳: 2（doublet）、3（triplet）...
- 默认值：偶电子单重态、奇电子双重态。MCP 校验。

### 10.3 电荷数与电子数
- N 电子 = 元素总电子数 - 电荷。MCP 自动算并校验。

### 10.4 keV vs eV vs Hartree vs kJ/mol vs kcal/mol
- 1 Hartree ≈ 27.211 eV ≈ 627.5 kcal/mol ≈ 2625.5 kJ/mol
- 全部用公式库换算，绝不手算。

### 10.5 冻芯近似
- 后 HF 方法（MP2、CCSD(T)）默认冻 1s 芯轨道；过渡金属要打开 3d。
- ✅ 默认按周期表自动选；MCP 返回时报告冻结轨道数。

### 10.6 振动频率单位
- 软件输出 cm⁻¹（波数），不是 Hz。换算 ν[Hz] = c × ν̃[cm⁻¹] × 100。

### 10.7 热力学修正
- ZPE / H_corr / G_corr 都依赖温度（默认 298.15 K）和压强（默认 1 atm）。MCP 必须报告温度压强参数。

### 10.8 玻尔兹曼平均
- 多构象的可观测量要按 Boltzmann 权重平均，不是算术平均。

---

## 11. 添加新坑的格式

发现新坑请按这个格式追加：

```markdown
### X.Y 坑名

- ❌ 错误做法 / 实际现象
- ✅ 正确做法 / 修复策略
- 关联：哪些 MCP/Skill 需要处理这个坑
```

---

*最后更新：v1.0 (2026-04)。*
