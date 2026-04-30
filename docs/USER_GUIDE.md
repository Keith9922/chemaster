# ChemMaster — 用户使用手册

> 这是给真实使用者的一页索引。展示当前 V2 (0.2.0a1) 系统**实际能做什么**、
> 怎么调用、以及每个功能背后调的是哪些工具。

---

## 1. 安装 + 第一次配置

```bash
# 1. 装 chemaster 环境
conda create -n chemaster python=3.11 -y
conda activate chemaster
conda install -c conda-forge psi4 xtb cclib rdkit ase pyyaml -y

# 2. 装 chemaster 自身
git clone https://github.com/<your>/chemaster
cd chemaster
pip install -e ".[dev]"

# 3. 一键配置（写到 ~/.chemaster/env）
chemaster init
# → 选 LLM provider (anthropic / minimax / qwen / deepseek / mock)
# → 输入 API key
# → 选默认 runs 目录

# 4. 把生成的 env 加到 shell rc
echo 'source ~/.chemaster/env' >> ~/.zshrc

# 5. 检查计算引擎
chemaster --check-engines
```

---

## 2. 命令清单

| 命令 | 用途 | 真实做的事 |
|---|---|---|
| `chemaster` | 进入交互式 REPL | 启动 ChemAgent，等用户输入；/help、/tools、/exit 命令 |
| `chemaster run "<intent>"` | 一次性任务 | 调 LLM → tool-use loop → 写 trajectory.json + report.md |
| `chemaster show <task_id>` | 看历史任务 | 读 `runs/<task_id>/trajectory.json`，rich 表格渲染 |
| `chemaster replay <task_id>` | 复现历史任务 | 用持久化的 user_intent 重跑 |
| `chemaster init` | 配置向导 | 写 `~/.chemaster/env`（mode 0600） |
| `chemaster --check-engines` | 看引擎可用性 | which psi4 / xtb / orca / multiwfn |
| `chemaster tools list` | 看 Agent 能调的所有工具 | 22 + 8 = 30 个，含 read-only / destructive / long-running 标志 |
| `chemaster skills list` | 看可用工作流 playbook | kb/skills/* (10 份完整文档) |
| `chemaster skills show <name>` | 读完整 skill | 例：`chemaster skills show tadf-pipeline` |
| `chemaster kb search "<query>"` | 搜知识库 | 检索 rules/*.yaml + skills/*/SKILL.md |
| `chemaster kb list` | 列 yaml 规则 | basis_sets / functionals / convergence / workflows |
| `chemaster mcps list` | 列 MCP server entry-points | const / io_ase / calc_psi4 / calc_xtb / calc_orca / calc_bdf / analysis_multiwfn / parse_cclib / viz / kb / hpc_slurm / pdf |
| `chemaster --tui` | 实验 Textual TUI | beta 版，CLI 是主要入口 |

---

## 3. 实战例子

### 例 1：水分子能量（最快 demo）

```bash
$ chemaster run "Compute the energy of water"

[Agent 流程]
step 1  io_lookup_by_name(name="water")
step 2  calc_psi4_optimize(method="B3LYP-D3(BJ)", basis="def2-SVP")
step 3  calc_psi4_frequency(...)
step 4  finish(summary, key_results)

[输出]
runs/<task_id>/
  ├── trajectory.json       # 完整对话历史
  ├── report.md             # 论文级总结
  ├── confirmations.jsonl   # 安全审计日志
  └── step_NN/              # 每步的输入文件 + 输出 log
```

### 例 2：TADF 激发态（项目核心场景）

```bash
$ chemaster run "Run TADF analysis on benzene at B3LYP/STO-3G"

[Agent 流程]
step 1  io_lookup_by_name(name="benzene")
step 2  calc_psi4_optimize(...)
step 3  calc_psi4_frequency(...)
step 4  calc_psi4_tddft(n_states=3, triplets=True, tda=True)
        → S1, S2, T1 + ΔE_ST + 振子强度
step 5  finish(...)
```

实际产出（benzene 端到端测试已验证）：
- E(GS) = -228.9 H
- S1 (π→π*), S2, T1 — 能量、波长、振子强度
- ΔE_ST = E(T1) - E(S1)，TADF 设计的核心指标
- thermal_corrections 完整（H/G/T·S，P0-2 实装）

### 例 3：4CzIPN（真 TADF anchor 分子）

```bash
# 4CzIPN 已经预先 MMFF 优化好，直接调用
$ chemaster run "Run a TDDFT analysis on 4CzIPN at omega-B97X-D / def2-SVP"

# 这会调 io_lookup_by_name("4CzIPN") → 拿到预存的 94 原子 xyz
# 然后 LLM 自主走 opt → tddft 流程
# 注意：4CzIPN 的 DFT 优化在本地 1-2 小时；建议用 chemaster --no-confirm + screen
```

### 例 4：通过 HPC 跑大计算

```bash
# 1. 配置（一次性）
$ vi ~/.chemaster/hpc.yaml
host: hpc.school.edu
user: alice
ssh_key: ~/.ssh/id_ed25519
remote_workdir: /work/alice/chemaster_runs
partition: cpu
time_limit: "12:00:00"
modules: [psi4/1.9, openmpi/4.1]

# 2. 让 Agent 自己提交
$ chemaster run "Optimize 4CzIPN at omega-B97X-D / def2-TZVP via HPC"
# Agent 调 hpc_submit → 拿到 job_id 立即返回；hpc_status / hpc_fetch 异步轮询
```

### 例 5：从论文 PDF 自动复算（roadmap，未完整接入）

```bash
$ chemaster run "Read paper.pdf, extract the TADF molecules, recompute their delta E_ST"
# 当前版本：chem.pdf MCP 是占位；tools/pdf-structure-extract/ 里的脚本可独立用
# Phase 5 完整接入：DECIMER → SMILES → 自动复算 → 对比文献
```

---

## 4. Agent 能调的 30 个工具一览

### 内建（3）
- `finish` / `ask_user` / `think`

### 知识库（3）
- `kb_search` / `list_skills` / `use_skill`

### 物理常数（3）
- `const_get` / `const_list` / `const_convert`

### 结构 IO（4）
- `io_smiles_to_xyz` / `io_xyz_to_smiles` / `io_parse_geometry` / `io_lookup_by_name`

### psi4 计算（4）
- `calc_psi4_single_point` / `calc_psi4_optimize` / `calc_psi4_frequency` / `calc_psi4_tddft` ★ 新

### xTB（2）
- `calc_xtb_single_point` / `calc_xtb_optimize`

### ORCA（2，需用户装 ORCA）
- `calc_orca_single_point` / `calc_orca_optimize`

### BDF（1，需用户装 BDF；TADF SOC）
- `calc_bdf_soc`

### 解析（2）
- `parse_output` / `parse_orbitals`

### 可视化（2）
- `viz_plot_3d` / `viz_plot_ir`

### MultiWFN（1，需用户装 MultiWFN）
- `analysis_nto`

### HPC（3，需 ~/.chemaster/hpc.yaml）
- `hpc_submit` / `hpc_status` / `hpc_fetch`

---

## 5. LLM 后端切换

| 提供商 | env var | 默认模型 | 备注 |
|---|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` | 工具调用最稳，推荐 |
| MiniMax | `MINIMAX_API_KEY` | `MiniMax-M2.7` | 国产，Anthropic-compatible |
| Qwen | `DASHSCOPE_API_KEY` | `qwen-max` | 阿里 DashScope 兼容 |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat` | 国产，便宜 |
| OpenAI-compat | `OPENAI_API_KEY` + `--llm-provider openai_compat --base-url ...` | 任意 | 本地 vLLM / llama.cpp |
| Mock | （无）| 测试用 | 不联网 |

CLI 自动按 env-var 优先级选第一个有值的。

---

## 6. 已知限制（坦率说）

- **TUI**：Textual UI 是 beta，体验不如 CLI。CLI + rich panels 是当前主路径。
- **TADF anchor 分子真跑**：4CzIPN 76 原子，在本地工作站做完整 opt+freq+TDDFT 需要 4-8 小时。**短期 demo 用 benzene 或 DMAC-BP**。
- **ORCA / BDF / MultiWFN**：MCP wrapper 已实装，但默认环境不带这三个二进制 —— 需要用户自己装（academic-free）。`chemaster --check-engines` 会告诉你哪些可用。
- **HPC**：需要用户写 `~/.chemaster/hpc.yaml` + 一次手工 ssh 验证。MCP 不会自动帮你解决跳板机、密码 + key 这类组合。

---

## 7. 故障排查

| 症状 | 原因 | 解法 |
|---|---|---|
| `chemaster run` 直接说 "MockLLM... no API key" | 没 export key | `chemaster init` 或手动 export |
| psi4 报 SCF_NOT_CONVERGED | 难收敛 | Agent 会自己重试 GWH / damping；若失败看 trajectory.json |
| TDDFT 出虚根 | full TDDFT 三重态不稳 | tda=True（默认已设），见 PITFALLS §2.8 |
| ORCA 报 ENGINE_NOT_FOUND | 没装 | https://orcaforum.kofo.mpg.de/ ，academic-free |
| BDF 报 NO_BDFHOME | 没设环境 | export BDFHOME=/path/to/bdf |
| 路径中文 / 空格 → SCF crash | psi4/ORCA 路径敏感 | runs_dir 用 ASCII 路径，PITFALLS §2.12 |

---

*文档版本：v0.2.0a1（2026-04-30）。*
