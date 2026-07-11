# ChemMaster — 用户使用手册

> 这是给真实使用者的一页索引。展示当前 V2 (0.2.0a2, 2026-05) 系统**实际能做什么**、
> 怎么调用、以及每个功能背后调的是哪些工具。

---

## 1. 安装 + 第一次配置

### 选项 A — 一行安装（推荐普通用户）

```bash
curl -sSL https://raw.githubusercontent.com/Keith9922/chemaster/main/scripts/install.sh | bash
```

完整三条路径（pipx / uvx / conda）见 [`INSTALL.md`](INSTALL.md)。

### 选项 B — 完整 conda（化学栈 + psi4）

```bash
# 1. 装 chemaster 环境
mamba create -n chemaster python=3.11 -y
mamba activate chemaster
mamba install -c psi4 -c conda-forge psi4 xtb cclib rdkit ase pyyaml -y

# 2. 装 chemaster 自身
pip install chemaster
```

### 一行环境审计

```bash
chemaster doctor
# → Python / pipx / uv 版本
# → psi4 / Gaussian / xtb / ORCA / BDF / MOMAP / pyscf 在 PATH 上的可用性
# → LLM API key 是否配置（masked 显示）
# → user_kb 配置目录状态
# → SLURM 连通性（如有）
```

### LLM API key 配置

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # 推荐
# 或 export MINIMAX_API_KEY=...           # 国内 MiniMax M2.7
# 或 export DASHSCOPE_API_KEY=...         # Qwen
# 或 export DEEPSEEK_API_KEY=...          # DeepSeek
# 或 export OPENAI_API_KEY=...            # OpenAI / openai_compat
# 不配 → MockLLM 仍能跑（适合协议演示）
```

---

## 2. 命令清单

| 命令 | 用途 | 真实做的事 |
|---|---|---|
| `chemaster run "<intent>"` | 一次性任务 | 调 LLM → tool-use loop → 写 trajectory.json + report.md，完成时弹桌面通知 |
| `chemaster tui` | Textual TUI 交互界面 | 全屏对话区 + 引擎状态面板 |
| `chemaster web` | 本地 Web 前端 | FastAPI + 内嵌 SPA，浏览器 http://127.0.0.1:8765 |
| `chemaster mcp-serve` | **作为 MCP server 启动** | 把整个 agent 内核暴露成 MCP server，Claude Code / Cursor / Codex 可挂载 |
| `chemaster doctor` | 一行环境审计 | Python / pipx / 引擎 / API key / user_kb / SLURM 全过一遍 |
| `chemaster show <task_id>` | 看历史任务 | 读 `runs/<task_id>/trajectory.json`，rich 表格渲染 |
| `chemaster replay <task_id>` | 复现历史任务 | 用持久化的 user_intent 重跑 |
| `chemaster init` | 配置向导 | 写 `~/.chemaster/env`（mode 0600） |
| `chemaster --check-engines` | 看引擎可用性 | which psi4 / xtb / orca / multiwfn |
| `chemaster tools list` | 看 Agent 能调的所有工具 | 45 个工具（含 finish/ask_user/think/recommend + 计算 + KB + viz + parse + io） |
| `chemaster skills list` | 看可用工作流 playbook | kb/skills/* |
| `chemaster skills show <name>` | 读完整 skill | 例：`chemaster skills show tadf-pipeline` |
| `chemaster kb search "<query>"` | 搜知识库 | 检索 rules/*.yaml + skills/*/SKILL.md + 用户 KB |
| `chemaster kb list` | 列 yaml 规则 | basis_sets / functionals / convergence / workflows / method_selection |
| `chemaster kb method-rules` | 看方法选择规则集 | 11 条内置 + 用户覆盖（命中规则会显式回显到 L2 recommend 卡片） |
| `chemaster kb add <path>` | 把外部文档加入个人 KB | 复制到 `~/.chemaster/user_kb/{skills,rules,notes}/` |
| `chemaster kb prefs` | 看/改个人偏好 | `~/.chemaster/user_kb/prefs.yaml`（如 `soc: BDF`） |
| `chemaster mcps list` | 列 MCP server entry-points | 15 个：const / io_ase / calc_psi4 / calc_xtb / calc_orca / calc_bdf / calc_pyscf / calc_gaussian / calc_momap / analysis_multiwfn / parse_cclib / viz / kb / hpc_slurm / pdf |

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
