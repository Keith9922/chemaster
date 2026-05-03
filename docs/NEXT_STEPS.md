# NEXT_STEPS — Phase 1 收尾后的开发路线

> P0（缺陷修复）+ P1（Phase 1 收尾）已完成，详见本文 §0。
> 本文档描述 P2-P6 的工作清单，可直接开 prompt 让 MiniMax / Claude 按 ID 顺序拆任务。
>
> **核心原则：先做通用化，再做 TADF 等具体领域。** TADF 只是一个 anchor case。

---

## 0. 已完成（P0 + P1，2026-04 收尾）

### P0 缺陷修复

| ID | 内容 | 落地 |
|---|---|---|
| P0-1 | benzene XYZ 修正（11C+11H 幻原子 → 标准 12 原子）| `chemaster/mcp/io_ase/server.py` + 测试断言 |
| P0-2 | Executor `_write_json_sync` fd 泄漏 | `chemaster/agent/executor.py` |
| P0-3 | `_electron_count` 重复 Mg key + 改用 ase.data.atomic_numbers | `chemaster/mcp/calc_psi4/server.py` |
| P0-4 | psi4 三个工具 docstring `n_threads 默认 1`（与代码对齐）| 同上 |
| P0-5 | `kf_strickler_berg` docstring 公式与代码常数对齐 | `chemaster/kb/formulas/photophysics.py` |
| P0-6 | `.gitignore` 加 `timer.dat / *output*.log / fort.*` | `.gitignore`（仓库根残留 log 用户本地 `rm` 一次） |
| P0-7 | psi4 输出路径参数化（`output_dir`），Executor 自动注入 `step_dir` | `chemaster/mcp/calc_psi4/server.py` + `chemaster/agent/executor.py` |

### P1 Phase 1 收尾

| ID | 内容 | 落地 |
|---|---|---|
| P1-A | ConfirmationLoop 真实现 + 一次性 HMAC token；伪造/重放都被 `PermissionError` 拒绝 | `chemaster/agent/confirmation.py`、`chemaster/agent/_token_registry.py`、`tests/unit/test_confirmation.py`（13 个测试） |
| P1-B | TUI 接 Planner / ConfirmationLoop / Executor，按 A/E/R/Q 走完一遍 | `chemaster/tui/app.py`、`chemaster/tui/widgets/plan_card.py` |
| P1-C | Markdown 报告生成器（6 段：元信息/分子/Plan 摘要/Step 详情/Key results/复现）| `chemaster/agent/reporter.py`、`tests/unit/test_reporter.py`（8 个测试） |
| P1-D | 完整 RRHO 热力学（ASE `IdealGasThermo`），`frequency` 工具填 H_corr / G_corr / TS | `chemaster/kb/formulas/thermo.py`、`chemaster/mcp/calc_psi4/server.py`、`tests/unit/test_thermo.py`（7 个测试） |
| P1-E | `chemaster init / eval / clean / report` 真实现 | `chemaster/cli.py`、`chemaster/config.py`、`tests/unit/test_cli.py`（10 个测试） |

**测试现状**（沙盒可跑的 82 个全绿，需要 rdkit/psi4 环境的 4 个文件本地跑）：

```
tests/unit/test_cli.py            10 passed
tests/unit/test_confirmation.py   13 passed   ← 强约束
tests/unit/test_constants.py       4 passed
tests/unit/test_executor.py        6 passed
tests/unit/test_parse_cclib.py    11 passed
tests/unit/test_photophysics.py    5 passed
tests/unit/test_plan.py            3 passed
tests/unit/test_planner.py         8 passed
tests/unit/test_reporter.py        8 passed   ← 新
tests/unit/test_thermo.py          7 passed   ← 新
tests/unit/test_units.py           7 passed
                                  82 passed
tests/unit/test_io_ase.py          需 rdkit
tests/unit/test_viz.py             需 matplotlib + ase
tests/unit/test_calc_psi4.py       mock 路径，需 psi4 import 占位
tests/unit/test_calc_xtb.py        mock 路径，需 mcp.server.fastmcp
tests/integration/test_h2o_e2e.py  需真装 psi4，约 30s
```

---

## 1. P2 · Planner 通用化（不再只支持 H2O）

> 这一步做完，Planner 能处理任意有机小分子的 opt+freq / single_point / TDDFT 三大基础工作流。

### P2-A · LLM Planner

**新增 / 改动**

```
chemaster/agent/planner.py            # 重写为 LLMPlanner（保留 HardcodedPlanner 兜底）
chemaster/agent/prompts/system.md     # Planner system prompt
chemaster/agent/prompts/few_shot.yaml # 4-6 个 few-shot 例子
chemaster/llm/__init__.py             # 抽象 LLMClient
chemaster/llm/anthropic_client.py
chemaster/llm/openai_client.py
chemaster/llm/local_client.py         # vLLM / Ollama / DeepSeek
tests/unit/test_llm_planner.py        # record/replay fixtures，不真调 API
```

**关键约束**
- LLM 输出**强制 JSON schema**（pydantic 校验 Plan）；不允许自由文本入 Plan。
- 校验失败让 LLM 重试 ≤ 3 次。
- 生成的 Plan 字段 `target_system.geometry_xyz` 必须非空（自动调 `chem.io.ase.smiles_to_xyz` 补）。

**验收**：`Planner().create_plan("算苯酚的 IR 谱")` 出可执行 Plan。

### P2-B · KnowledgeRetriever + chem.kb MCP

**新增 / 改动**

```
chemaster/agent/retriever.py          # 真实现，BM25 优先
chemaster/mcp/kb/server.py            # search / get_rule
chemaster/kb/rules/elements.yaml      # 每个元素的常用基组、相对论需求
chemaster/kb/index/                   # 索引产物（gitignore）
tests/unit/test_retriever.py
```

- Phase 2 用 `rank_bm25` 纯本地实现，不引向量数据库。
- 切片：`kb/rules/*.yaml` 按 entry 切；`chemaster/skills/*/SKILL.md` 也进。

### P2-C · 通用 io_ase 接口扩展

```
chemaster/mcp/io_ase/server.py
  + smiles_to_xyz_multiconf(smiles, n_confs=10)   # ETKDG + UFF rank
  + displace_along_mode(xyz, mode_vec, amplitude) # 虚频自愈
  + count_rotatable_bonds(smiles)
  + element_set(xyz)
```

`displace_along_mode` 是 `opt-freq` 自愈路径必需品。

### P2-D · 通用化 Executor 的 state passing

把 `_resolve_geometry`/`_maybe_inject_output_dir` 升级成基于 Plan 模板字符串的统一注入：

```yaml
- server: chem.calc.psi4
  tool: optimize
  args:
    geometry_xyz: "${step_01.result.xyz}"
    method: "${kb.functional.recommended}"
```

**新增**

```
chemaster/agent/state.py              # 跨 step 状态字典 + 模板渲染
tests/unit/test_state_passing.py
```

---

## 2. P3 · 错误自愈 + Skill 代码化

> CLAUDE.md §3 #5 承诺"错误自愈率 ≥ 70%"。当前 SKILL.md 写了恢复策略但没人执行。

### P3-A · Skill Runner

```
chemaster/agent/skill_runner.py       # 解析 SKILL.md 为可执行步骤图
chemaster/skills/_schema.py           # frontmatter pydantic 模型
tests/unit/test_skill_runner.py
```

让 Plan 的 `step.skill: "opt-freq"` 字段有意义：Executor 看到 `skill` 非空就把控制权交给 SkillRunner。

### P3-B · opt-freq 自愈代码化

`chemaster/skills/opt-freq/runner.py`：
- `SCF_NOT_CONVERGED` → guess=GWH 重试 → 降基组 def2-SVP 重试 → 报失败
- `GEOMETRY_NOT_CONVERGED` → 切 `redundant_internal` → 减小 trust radius
- `IMAGINARY_FREQUENCY` → 沿模式位移 0.1 Å 重启优化（最多 3 轮）

这是论文里"自愈率"实测数据来源。

### P3-C · 把其他 Skill 补完

| Skill | 当前 | P3 要做 |
|---|---|---|
| opt-freq | MD 写好 | + `runner.py` |
| tddft | MD 写好 | 补 Λ 诊断段 + `runner.py` |
| soc | MD 写好 | `runner.py`（等 BDF MCP） |
| conformer | MD 写好 | `runner.py`（xtb + crest） |
| ts-search | MD 写好 | `runner.py`（ORCA NEB-TS） |
| tadf-pipeline | MD 写好 | `runner.py`（编排上面四个） |
| pka | TODO 桩 | 写完整 SKILL.md |
| solvation | TODO 桩 | 同上 |
| pes-scan | TODO 桩 | 同上 |
| dlpno-ccsdt | TODO 桩 | 同上 |

---

## 3. P4 · 第二批 MCP 引擎

| MCP | 优先级 | 用途 | 第一批工具 |
|---|---|---|---|
| `chem.calc.orca` | 高 | TDDFT、SOC、NEB-TS | `single_point` / `optimize` / `frequency` / `tddft` |
| `chem.parse.cclib` | 已实现，加测试 | 覆盖 ORCA / Gaussian 真输出 | fixture 覆盖 |
| `chem.hpc.slurm` | 中 | 学校超算闭环 | `submit_job` / `poll_status` / `fetch_results` / `cancel` |
| `chem.calc.bdf` | 中 | TADF X2C-TDA SOC | `tddft_soc` |
| `chem.analysis.multiwfn` | 低 | NTO、Hirshfeld | `nto` / `hirshfeld` |
| `chem.pdf` | 低 | wrap 现有 `tools/pdf-structure-extract` | `extract_structures` |

新增框架（chem.calc.orca 为例）：

```
chemaster/mcp/calc_orca/server.py
chemaster/mcp/calc_orca/_input_builder.py
chemaster/mcp/calc_orca/_output_parser.py
tests/unit/test_calc_orca.py
tests/fixtures/orca_h2o.out
```

---

## 4. P5 · 复现 / Benchmark / Iterator

> CLAUDE.md §3 #3 "3 个月后同输入复现率 100%" 是论文亮点。

### P5-A · `chemaster replay <task-id>`

```
chemaster/agent/replay.py             # 重建 Plan，强制走原 commit，对比 result.json
tests/integration/test_replay_h2o.py
```

CLI 加 `replay` 子命令，diff 关键字段（能量、频率、HOMO-LUMO）：误差超阈值即 FAIL。

### P5-B · BenchmarkIterator

```
chemaster/agent/iterator.py           # 真实现
benchmarks/gmtkn55-subset/            # 5-10 个分子
benchmarks/tadf-literature/           # 加 DMAC-DPS / PXZ-TRZ / CzBN / 4CzPN
chemaster/cli.py                      # eval --iterate
```

算法：xTB → B3LYP/6-31G* → ωB97X-D/def2-TZVP → DLPNO-CCSD(T)/def2-TZVP，
按容差自动升级；输出 (error vs cost) 曲线。

---

## 5. P6 · 打包 / 文档 / 答辩

| ID | 产物 | 路径 |
|---|---|---|
| P6-1 | PyPI 包 | `pyproject.toml` 已配，`python -m build && twine upload` |
| P6-2 | conda-forge recipe | `recipe/meta.yaml` |
| P6-3 | Homebrew tap | `Formula/chemaster.rb` |
| P6-4 | Docker（含 psi4 + xTB） | `Dockerfile` |
| P6-5 | 终端录屏 | `docs/demo.cast` |
| P6-6 | 答辩 demo 脚本 | `docs/DEMO_SCRIPT.md`（H2O → 苯 → 4CzIPN 三层） |
| P6-7 | 引用 | `CITATION.cff` + `docs/PAPER_OUTLINE.md` |

---

## 6. 推荐执行顺序与时间盒

| 周 | 工作 | 产出 |
|---|---|---|
| W1 | P2-A + P2-B | 任意小分子 Planner |
| W2 | P2-C + P2-D + P3-A | 通用化 + skill runner |
| W3 | P3-B（opt-freq 自愈代码化） | 错误自愈率有数据 |
| W4 | P4 ORCA + P4 cclib 测试加固 | TDDFT 链路 |
| W5 | P5-A（replay） | 复现率 100% 证据 |
| W6 | P4 BDF + P3-C tadf-pipeline runner | TADF 端到端 |
| W7 | P4 MultiWFN + 跑 1-2 个 TADF anchor | NTO 报告 |
| W8 | P5-B + benchmark 跑 | benchmark 曲线 |
| W9 | 论文实验复盘 + 截图 | 答辩素材 |
| W10 | P6 打包 + DEMO_SCRIPT | 可交付 |

---

## 7. 框架不变量（CI 应静态守护）

防止 Skill 与 Planner 边界腐化，建议 `.github/workflows/lint.yml` 加：

```bash
# Skill 不能直接 import 引擎
! grep -rn -E "import (psi4|xtb|orca)" chemaster/skills/*/runner.py 2>/dev/null

# Agent core 不能写引擎名（除 SERVER_TO_MODULE 映射表）
grep -rn -E "(psi4|orca|bdf|xtb)" chemaster/agent/ \
  | grep -v "_SERVER_TO_MODULE\|# allow-engine-mention\|test_" \
  && exit 1 || true

# Planner 不能 hard-code 化学领域名（如 'tadf'）
! grep -E "\"(tadf|krisc|isc|risc)\"" chemaster/agent/planner.py
```

---

## 8. 当前可运行的 demo 路径（截至 P0/P1 收尾）

```bash
# 1. 装环境
conda create -n chemaster python=3.11 -y && conda activate chemaster
pip install -e ".[dev]"
conda install -c conda-forge psi4 xtb cclib rdkit ase -y

# 2. 单测全绿
pytest tests/unit -v

# 3. 端到端 H2O（真跑 psi4，~30s）
pytest tests/integration -v -m integration

# 4. 看产物
ls runs/<task-id>/        # plan.json meta.json step_*/result.json report.md
cat runs/<task-id>/report.md

# 5. CLI 路径
chemaster --version
chemaster --check-engines
chemaster init                # 写 ~/.chemaster/config.yaml
chemaster skills list
chemaster mcps list
chemaster kb list
chemaster eval benchmarks/tadf-literature/4CzIPN.yaml   # P4 之后才跑得通

# 6. TUI
chemaster                     # 输入"算 H2O 的能量" → A → 看 report
```

---

*文档版本：v1.0 (2026-04)。每完成一个 P 阶段更新 §0 与时间盒表。*
