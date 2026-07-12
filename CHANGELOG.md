# Changelog

所有面向用户可见的变更记录在此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [0.2.0a3] — 答辩后大整合：四路合流 + 内核重构 + 权限分级真接线 (2026-07-11)

> 毕设于 2026-05-21 完成答辩、05-30 论文修订定稿。本版本把答辩前后散落在
> 4 处的代码统一为一条主线，并完成第一轮答辩后重构。

### Added
- **权限分级真接线**：`~/.chemaster/policy.yaml` 的 L1/L2/L3 此前只是
  system prompt 里的文字约定（`policy.py` 是死代码），现在 `_handle_recommend`
  真按 policy 分流——L1 静默接受（authority=agent，全程留痕）、L2 推荐卡片、
  **L3 无交互通道时拒绝自动接受，强制升级 ask_user 并挂起任务**。
  新增 8 个专项测试（此前 recommend 循环路径零测试覆盖）。
- **`chemaster/agent/factory.py`**：统一的 agent 组装工厂（provider 探测 /
  默认 model / wiring）。替换 5 处互相漂移的复制粘贴——REPL 此前不认
  qwen/deepseek 的 key，agent-as-MCP server 用的还是一批旧 model id。
- **`chemaster/engines.py`**：统一引擎探测（4 处互不一致的引擎清单合一；
  psi4/pyscf 按"当前解释器可 import"判定，doctor 此前漏检纯模块安装）。
- **psi4 TD-opt 移植**（来自 objective-meitner worktree 的 8 个 commit）：
  `calc_psi4_optimize_excited_state`（TDA 激发态几何优化）、
  `io_compute_descriptors`（键长/键角/二面角确定性计算）、MLJ 速率公式
  `k_mlj`、HCHO 全流水线 benchmark 证据。开源路径首次具备激发态优化能力。
- 恢复主仓库工作区滞留 2 个月的未提交修复：TUI `TaskInstance(intent=)`
  字段错误（提交任务必崩）、TUI 硬编码 mock LLM（改为按环境变量自动探测
  + `--llm-provider/--llm-model` 选项）、TUI 逐步流式显示。

### Changed
- **agent 内核重构**：run/continue_run 收敛为 `_run_loop`；sync 与 streaming
  两条路径的三对镜像方法（~350 行语义重复）收敛到共享 helper——消掉复制后
  各自演化出的 5 个 bug（streaming 的 recommend 直通 no-op、authority 标签
  缺失、`continue_run` 异常时 trajectory 不落盘等）。streaming 的工具执行
  改为 `asyncio.to_thread`，不再阻塞事件循环。
- **llm_client 表驱动**：MiniMax/Qwen/DeepSeek 三份复制样板收敛为
  `_normalized_config`；context-overflow 探测合一；anthropic `model=None`
  兜底默认模型（web/tui 传 None 曾直接把 None 发给 API）；`timeout_s`
  真正传给 SDK（此前形同虚设）。
- **psi4 会话隔离**：五个工具的重复 setup 收敛为 `_psi4_session`，每次调用
  `clean_options()`——修掉 TD-opt 的 optking/tdscf 选项泄漏毒化后续 tddft
  的顺序依赖 bug；输出日志写独立临时目录（不再把 `*_output.log`、
  `psi.*.clean` 拉到仓库根，且并发调用不再互相覆盖）。

### Fixed
- `calc_pyscf` 返回契约：SCF 不收敛此前返回 `ok=True` + `error_code` 并存
  ——agent 按 `ok` 判读会把不收敛当成功，`x2c_soc` 还会拿不收敛的能量继续
  算修正值。现在统一 `ok=False` + `suggestion`。
- `kb/rules/functionals.yaml` 非法 YAML（B2PLYP 条目）导致整个文件从不进
  检索语料；修复后给用户自带文档加 1.3× 检索加权（实验室自定义规则不再被
  通用条目挤出 top-k）。
- `list_skills` 不再把 user_kb 的 notes 当 skill 返回；单测与真实
  `~/.chemaster`（user_kb 与 policy.yaml）完全隔离。
- **scalability N=10000 数据找回**：bd1ec99 重新生成时把 be787c2 的
  N=10000 结果误覆盖为 N=100，已从 git 历史恢复。
- executor：时间戳/Python 版本不再 shell 出去取；`_write_json_sync` 真正
  fsync 写入的 fd（此前 fsync 的是一个新打开且未写入的句柄）。
- 版本号统一为 0.2.0a3（pyproject 此前停在 0.2.0a1，CHANGELOG 已是 0.2.0a2）。

### Added（第二波，同日）
- **web/tui 测试盲区补齐**：两个前端从零测试 → 26 个（FastAPI TestClient
  钉死"提交必崩"回归路径全链路；Textual pilot 驱动真事件循环测卡片交互）；
  `web` / `tui` extras 首次在 pyproject 声明。
- **LLM 瞬时错误重试**：429/5xx/网络抖动指数退避（max_retries=3）——
  此前零重试，一次限流就让整个化学任务失败。
- **GitHub Actions 复活**：CI（ubuntu/macos × py3.11/3.12，ruff + unit）
  与 PyPI Release workflow 真正入库并首跑全绿——根因是 `.gitignore` 一直
  把 `.github/workflows/` 忽略，workflow 从未进过任何提交；push 前用无
  psi4 的干净 venv 模拟 runner，提前修掉 36 个环境依赖失败。
- **真 LLM 工程指标**（`run_engineering_real_llm.py` + 实测数据）：与
  mock 版同题库/同故障注入规格/同 anchor，LLM 换成 MiniMax-M2.7 真实 API
  面对全部 54 个工具。结果（2026-07-12 实采，`*_real_llm.json`，不覆盖
  mock 数据）：**路由 98.0%（98/100，语义判据；mock 单一判据口径 67%，
  差值主要是判据 artifact）、故障自愈 96%（17 L1 + 7 干净升级 + 1 失败
  如实记录）、自主步占比 72.7%（≥70% 达标）**。至此三项旗舰工程指标
  都有了"真实大模型"版本，不再只有 mock 路由数据。
- **真的任务取消**：`AgentConfig.should_abort` 协作式中止（sync/streaming
  双路径，trajectory 记 `cancelled` 并落盘）；Web 取消按钮现在真的停后端
  （此前只是前端停止轮询），卡在 confirm/recommend 卡片上的线程也会被解放。
- **引擎日志归档**：psi4 输出日志按 `CHEMASTER_ENGINE_LOG_DIR` 落到
  `runs/<task>/engine_logs/`（时间戳防覆盖）——恢复 §5.6 复现承诺。
- **MCP 决策透传**：`chemaster_run` 结果新增 `chemistry_decisions` 块——
  MCP 模式没有交互通道，L2 决策被自动接受，此前完全隐形；现在显式回传
  并提示调用方 LLM 转述给它的用户。

### Fixed（第二波，同日）
- `hpc_slurm.fetch` 功能性坏死：submit 建 `jobname-timestamp` 目录而 fetch
  按 `*job_id*` 猜文件名，永远匹配不上。现在 submit 把 job_id →
  remote_workdir 登记进 `~/.chemaster/hpc_jobs.json`，fetch 按索引拉取
  （`remote_dir=` 参数留作逃生口），rsync 也真正带上配置的 ssh_key。
- MCP 层 22 处缺失 `suggestion` 的错误返回补齐（gaussian 结构化五工具 /
  bdf / momap / pyscf / kb）；新增 `chemaster/mcp/_common.py`（`err()` 把
  suggestion 做成必填、`probe_binary` 消掉 7 份 `_check_engine` 拷贝、
  `xyz_atom_lines`）。
- `calc_psi4` 拆出 `parsers.py`（server 1580 → 1391 行）；解析器群在无
  psi4 环境可测（7 个新测试不再随 psi4 缺席而跳过）。

### Docs
- CLAUDE.md → v4.0（答辩后状态；§8 换成新阶段清单）；README 数字与
  benchmark JSON 对齐（路由 100%、故障处置 25/25 双口径注明、N=10000、
  3c=80%、17 server / 54 工具）；thesis.md 英文摘要与中文正文同步。

## [0.2.0a2] — Round-2 robustness + Codex-inspired upgrades + thesis sync (2026-05-20)

### Added — ChemMaster-as-MCP-server (`chemaster.mcp.agent.server`)

整个 Agent 内核现在以 MCP server 形态对外开放。任何兼容 MCP 的客户端
（Claude Code、Cursor、OpenAI Codex CLI）都可以挂载 ChemMaster 并通过
`chemaster_run("…")` 调用整套化学工作流，**而不只是单个工具**。这是
§1.3 "MCP-as-open-protocol" 主张的最强证据：协议合规性从"3 个工具
server"升级到"整个 agent 内核"。

四个工具：
- `chemaster_run(intent)`         —— 完整 agent 循环端到端
- `chemaster_list_skills()`       —— KB 中可用的 skill 目录
- `chemaster_list_tools()`        —— 内核能调度的全部 45 个工具
- `chemaster_list_engines()`      —— 检测 PATH 上的化学引擎

新 CLI：`chemaster mcp-serve`。

### Added — `chemaster doctor`（来自 Codex 借鉴 §1.3）
一行环境审计：Python / pipx / uv 版本，所有化学引擎在 PATH 上的存在，
所有 LLM API key（值会被遮蔽），用户配置目录，SLURM 连通性。退出码非
零只在影响实际计算时才发生。

### Added — `chemaster.notify` 跨平台桌面通知
任务完成时弹一条系统通知（macOS osascript / Linux notify-send / WSL2
和 Windows PowerShell）。化学场景下 Gaussian 单点动辄数小时，让研究
者不必盯着终端。可通过 `CHEMASTER_NO_NOTIFY=1` 关闭。

### Added — 方法选择规则引擎（`chemaster.kb.method_selection`）
"什么任务用什么方法"从隐式 if 分支变成声明式 YAML：

- `chemaster/kb/rules/method_selection.yaml` 11 条内置规则
- `~/.chemaster/user_kb/rules/method_selection.yaml` 用户可覆盖
- 按 id 合并，按 priority 排序；用户规则永远赢
- L2 recommend 卡片显式回显命中规则的 id + rationale + source

新 CLI：`chemaster kb method-rules [--task-type tddft] [--full]`。

### Added — 一行安装路径
- `scripts/install.sh` —— pipx/uvx-aware 引导，自动检测引擎，含
  `CHEMASTER_RELEASE_BASE_URL` 国内镜像支持
- `docs/INSTALL.md` —— pipx / uvx / conda 三条安装路径的完整矩阵
- `pyproject.toml` 清理：移除幽灵依赖 `claude-agent-sdk`，URL 修正

### Added — 系统层指标扩展
- **压力测试**（`scripts/benchmarks/run_stress_test.py`）—— 10 分子 ×
  ~33 phrasing = **334 测试，路由 100% / agent_ok 100%**，mean 99 ms，
  p99 = 140 ms（输出：`benchmarks/engineering_metrics/stress_test.json`
  + `paper/figures/fig_stress_test.png`）
- **硬例子真跑**（`scripts/benchmarks/run_hard_cases.py`）—— 重元素
  / 开壳层 / 较大分子 / 带电species 共 11 case，HF/sto-3g 和
  B3LYP-D3(BJ)/def2-SVP 各 **11/11 全过**

### Added — `AGENTS.md` 软链
指向 `CLAUDE.md` 的 git-tracked symlink，让 OpenAI Codex / Cursor /
Claude Code 等客户端读到同一份项目级指令而无需重复维护。

### Added — `docs/COMPETITIVE_SCAN.md`
Codex 0.128-0.131、DeepSeek-TUI v0.8.34-v0.8.39、Claude Code 文档的
1.4k 字借鉴分析，含 Top-5 优先级排序。

### Changed — 共享的确定性路由模块
`chemaster.agent.mock_routing` 把双语关键词路由器从
`scripts/benchmarks/run_execution_and_scalability.py` 中抽出，benchmark
脚本和 MCP server 共用一份。新增 4 个 phrasing 类别支持
`平衡构型 / 结构优化 / 构型优化 / 平衡几何`（修复 §4.4.2 之前 10/120
optimize 误路由到 kb_search 的真实 bug）。

### Changed — 文档结构整理
历史文档移到 `docs/archive/`（KICKOFF、V2_RELEASE_NOTES、MINIMAX_PROMPTS、
REFACTOR_PLAN、PACKAGING、GITHUB_SETUP、ROADMAP）。`docs/` 只留
authoritative reference docs。

### Fixed — 代码 lint
ruff `--fix` 清理 20 个 unused-import / unused-var 问题；手动处理 7 个
F841 stragglers（保留 psi4 风格的 side-effect 调用）。最终 **0 ruff
F-finding**。

### Fixed — 论文真值审计（9 轮自主审计）
- §4.4.3 N=1000/N=5000 → 真实 N=2000 / mean 131 ms / std 4.9 ms
- §4.4.4 user_kb LOC 200 / 19 tests → 真实 348 / 25
- §4.4.2 失败 phrasing 例子从虚构的 "kb 检索一下" → 真实失败的
  "Look up basis set rules" / "查基组规则"
- §5.1 conclusion 14 servers / 6000 行 → 真实 15 / 6549
- 英文 abstract "valence MAE < 0.2 eV" → 真实 0.45 eV（分 valence /
  Rydberg 拆开报告）
- §4.5.3 端到端 demo 引用的 `benchmarks/use_cases/end_to_end_demo/`
  目录之前不在 feat 分支上，从 main 的 f9cd856 恢复（12 个文件，含
  trajectory.json / 5 张截图 / report.md）

### Tests
- **336 passed, 2 skipped** （增 +25 method-selection, +4 doctor,
  +30 notify, +15 mcp-agent-server）
- 4/4 MCP cross-client probe（含 agent server 真跑 `chemaster_run`）
- 334/334 stress test 全过
- 11/11 hard cases 全过（两种方法×基组）

## [Unreleased-prior] — Streaming agent loop (foundation for `chemaster web`)

### Added — `chemaster.agent.types` AgentEvent protocol
- 8 dataclasses describing every state transition of the Agent loop:
  `StepStartedEvent`, `AssistantMessageEvent`, `ConfirmationRequiredEvent`,
  `ToolStartedEvent`, `ToolCompletedEvent`, `StepCompletedEvent`,
  `RunCompletedEvent`, `ErrorEvent`. All carry `type` (discriminator) +
  `timestamp`; all are JSON-serialisable via `to_dict()` for the WebSocket
  wire format. `AgentEvent` union type aliased for callers.

### Added — `ChemAgent.run_streaming` async generator
- `async def run_streaming(task) -> AsyncIterator[AgentEvent]` mirrors the
  sync `run()` loop and yields events at every transition. Designed for the
  upcoming FastAPI WebSocket server (`chemaster web`) and a future live-
  rendering CLI.
- Internals: `_step_streaming` and `_dispatch_tool_streaming` are async
  generators that delegate to the existing tool registry — no behavioural
  drift from sync path.
- Confirmation flow is properly awaitable: `ConfirmationRequiredEvent` is
  yielded *before* the tool runs; `_await_confirmation` resolves
  `AgentConfig.async_confirm_callback` (preferred) or falls back to the
  legacy sync `confirm_callback` (run via `asyncio.to_thread` so a slow
  prompt cannot stall the event loop).
- Three terminal payload semantics on `RunCompletedEvent`:
  `completed` → finish-tool args; `waiting_for_input` → ask_user payload;
  `failed` → `reason` (e.g. `"max_turns_exceeded"`).

### Added — `AgentConfig.async_confirm_callback`
- New optional field; takes precedence over `confirm_callback` when running
  via `run_streaming`. Sync callback continues to work for the legacy CLI.

### Tests
- `tests/unit/test_agent_streaming.py` — 13 tests covering: event order;
  approval / decline / no-callback paths; long-running flag; sync-fallback;
  ask_user → waiting_for_input; max_turns_exceeded → failed; unknown tool →
  is_error; trajectory persistence; per-step started/completed pairing; full
  JSON round-trip of every event payload.
- All 13 pass; the existing 27 agent_loop + 16 plan/planner/confirmation +
  10 executor/confirmation_log tests still pass (zero regression).

### Tooling
- Repo hygiene: residual logs in repo root (`frequency_output.log`,
  `optimize_output.log`, `test_opt.log`, `psi.91710.clean`) are already
  covered by `.gitignore` but should be removed manually from working trees.

## [0.2.0a1] — Architecture V2 + production polish (2026-04-30)

### Added — P0: TADF pipeline blockers cleared
- `chemaster.mcp.calc_psi4.tddft` — full TDDFT excited-state tool with TDA
  default, singlets + triplets, ΔE_ST, oscillator strengths, parser robust to
  psi4's "Excited State N (M A): X.YYY au   AA.BB nm f = Z.ZZ" format.
- `chemaster.mcp.calc_psi4.frequency` thermal_corrections — h_corr / g_corr /
  T·S / total_h / total_g / e_corr now parsed from psi4's thermo block (was
  hard-coded null, breaking the entire free-energy chain).
- `benchmarks/tadf-literature/{4CzIPN,DMAC-BP,DMAC-DPS}.{xyz,yaml}` — MMFF-
  optimized geometries + literature ΔE_ST / oscillator strength.
- `chemaster.mcp.io_ase` lazy-loads the TADF anchor xyzs into the lookup
  table at import time, so `io_lookup_by_name("4CzIPN")` just works.
- `tests/integration/test_tadf_pipeline.py` — drives the full
  io_lookup → opt → freq → tddft → finish chain on benzene (routine) and
  DMAC-BP (CHEMASTER_E2E_FULL=1 opt-in).

### Added — P1: real multi-software wrappers
- `chem.calc_orca` — single_point / optimize via subprocess. Full DLPNO-
  CCSD(T) / RIJCOSX / hybrid-DFT keyword passthrough; ENGINE_NOT_FOUND
  with concrete download hint.
- `chem.calc_bdf` — SOC (X2C-TDA) skeleton; ENGINE_NOT_FOUND + NO_BDFHOME
  errors. Spin field correctly converts multiplicity → 2S.
- `chem.analysis_multiwfn` — NTO analysis via menu-driven CLI piped to
  Multiwfn; FILE_NOT_FOUND for missing wavefunction inputs.

### Added — P2: hygiene
- PDF helper scripts moved scripts/ → tools/pdf-structure-extract/.
- 4 TODO skill stubs (dlpno-ccsdt / pes-scan / pka / solvation) replaced
  with real, runnable workflow documents.
- `chemaster` (no args) drops into a text REPL backed by ChemAgent
  instead of trying to launch a half-built TUI; --tui flag opt-in.

### Added — P3: UX polish
- `chemaster show <task_id>` — pretty-prints a previous trajectory.
- `chemaster replay <task_id>` — re-runs a task from its recorded intent.
- `chemaster init` — interactive config wizard, writes ~/.chemaster/env
  (mode 0600).
- Live progress streaming during `chemaster run` — each tool call is
  printed with ✓/✗ and observation snippet as it happens.
- Auto-generated `runs/<task_id>/report.md` after every task: header,
  summary, key_results table, per-step trace.
- `_render_agent_error` — typed hint mapping (auth / context / timeout /
  network) with trajectory-pointer panel on agent crash.

### Added — P4: BYO-LLM expansion + HPC + release prep
- `chemaster.agent.llm_client` gets `OpenAICompatLLM` (generic OpenAI
  /v1/chat/completions with function calling), `QwenLLM` (DashScope),
  `DeepSeekLLM`. CLI auto-detects DASHSCOPE_API_KEY / QWEN_API_KEY /
  DEEPSEEK_API_KEY.
- `chem.hpc_slurm` — submit / status / fetch over paramiko SSH; reads
  ~/.chemaster/hpc.yaml for host / user / partition / time_limit /
  modules. Async-style: submit returns job_id immediately so the agent
  doesn't block on the cluster.
- `pyproject.toml` version 0.1.0 → **0.2.0a1**; openai>=1.30 added.
- `python -m build` produces a clean wheel + sdist; `twine check`
  passes both.
- `CITATION.cff` for "Cite this repository" / Zenodo / JOSS.

### Tests
- 217 unit tests (was 86 before V2). New batches:
  * test_calc_orca.py — 13 tests
  * test_calc_bdf_multiwfn.py — 9 tests
  * test_hpc_slurm.py — 6 tests
  * test_agent_loop.py extensions — Qwen/DeepSeek/OpenAI-compat (5 new)
- Integration: H2O e2e + agent_real_psi4 (CH4/NH3/trajectory/finish) +
  tadf_pipeline (benzene smoke; DMAC-BP opt-in) + e2e_sweep (5 small
  molecules).

### Tool registry
22 → **30** tools.

---

## [Unreleased] — Architecture V2 (2026-04-29)

### Added — V2 Agent core (Claude-Code-style tool-use loop)
- `chemaster.agent.types` — Dialog / Message / ToolCall / Trajectory / TaskInstance.
- `chemaster.agent.llm_client` — `BaseLLM` + `MockLLM` (scriptable) + `AnthropicLLM`
  (real Claude via Anthropic SDK, lazy-imported). `OpenAICompatLLM` stub for
  future Qwen / DeepSeek / vLLM support.
- `chemaster.agent.context.ContextManager` — token budget + truncation
  strategies (`latest_half`, `sliding_window`).
- `chemaster.agent.tool_registry.{BaseTool, ToolRegistry, MCPToolAdapter}` —
  unified tool surface; per-tool flags
  `is_read_only` / `is_destructive` / `is_long_running`.
- `chemaster.agent.builtins.{FinishTool, AskUserTool, ThinkTool}` —
  always-available built-in tools.
- `chemaster.agent.agent.{BaseAgent, ChemAgent}` — the actual loop.
  `chemaster.agent.agent.build_default_chem_agent()` factory wires built-ins
  + every available MCP tool.
- `chemaster.agent.system_prompt.md` — chemistry-expert system prompt
  (English; Marcus formula reminder, method-selection cheat sheet, error
  recovery patterns).
- `chemaster.agent.tool_loader.build_default_registry()` — adapts every
  available MCP server function as a `BaseTool`. 22 tools register cleanly.

### Added — chem.kb MCP
- `kb_search(query, top_k)` — term-frequency search over `kb/rules/*.yaml`
  + `kb/skills/*/SKILL.md`. Returns hits with citations.
- `list_skills()` — enumerate playbooks with one-line summaries.
- `use_skill(name, action="get_info" | "get_metadata" | "get_reference")` —
  read a skill's content. Mirrors EvoMaster's SkillTool actions.

### Added — CLI overhaul
- `chemaster run "<intent>"` — one-shot agent run; auto-picks Anthropic if
  `ANTHROPIC_API_KEY` set, else MockLLM. `--no-confirm`, `--max-turns`,
  `--llm-provider`, `--enabled-tool` flags.
- `chemaster skills list / show <name>`
- `chemaster kb search "<query>" / list`
- `chemaster tools list` (with read-only / destructive / long flags)
- `chemaster mcps list`
- Rich-formatted Panel + Table output throughout.
- Interactive confirmation prompt for destructive / long-running tools.
- `chemaster/__main__.py` — `python -m chemaster …` works.

### Added — Confirmation audit trail
- Per-tool confirmation gate: only destructive / long-running tools call the
  user-supplied `confirm_callback`; read-only tools (kb_search, think,
  finish) bypass entirely.
- Each prompt is recorded on `trajectory.meta['confirmations']` and
  appended as JSONL to `runs/<task_id>/confirmations.jsonl`.

### Changed — Skills migrated from architectural layer to KB documents
- `chemaster/skills/*` → `chemaster/kb/skills/*`. Skills are no longer a
  control-flow construct (no more `when_to_use` triggering). They are
  searchable Markdown docs the Agent loads via `use_skill` when needed.

### Changed — Legacy modules become V2 compatibility shims
- `agent/planner.py` `Planner` keeps working for the H2O e2e test, but its
  docstring marks it deprecated.
- `agent/executor.py` `Executor` likewise — used only by the legacy H2O e2e.
- `agent/confirmation.py` `ConfirmationLoop` now offers `auto_approve` /
  `reject` programmatic helpers and a CLI prompt fallback (was
  NotImplementedError).
- `agent/iterator.py`, `agent/retriever.py` documented as out-of-scope for
  V2 MVP.

### Fixed
- `chemaster/mcp/calc_psi4/server.py::_parse_frequencies_from_output` was
  returning after the first `Freq [cm^-1]` line; high-symmetry molecules
  (CH4 / Td) only got 3 of their 9 frequencies. Now reads all blocks.
- `chemaster/mcp/calc_psi4/server.py::frequency` defensively unpacks
  `psi4.frequencies(...)` whether it returns a scalar (production) or a
  `(energy, wfn)` tuple (mock tests).
- `chemaster/kb/rules/functionals.yaml` line 66 had unquoted `**...**`
  markdown that YAML parsed as an alias marker. Now a quoted string.
- `chemaster/mcp/calc_xtb/server.py` `ENGINE_NOT_FOUND` now carries a
  concrete `suggestion` (conda install hint + GitHub releases link).
- `tests/unit/test_calc_psi4.py` — H2O / CH3 fixtures are now standard xyz
  (atom count + comment header). 16 pre-existing failing tests fixed.
- `tests/conftest.py` — pre-attaches `psi4.core.get_active_wavefunction`
  noop so unittest.mock.patch works across psi4 versions.

### Tests
- 166 unit + 6 integration tests pass (172 total) — see also
  [test_agent_loop.py](tests/unit/test_agent_loop.py),
  [test_kb_mcp.py](tests/unit/test_kb_mcp.py),
  [test_agent_recovery.py](tests/unit/test_agent_recovery.py),
  [test_confirmation_log.py](tests/unit/test_confirmation_log.py),
  [test_cli.py](tests/unit/test_cli.py),
  [test_agent_real_psi4.py](tests/integration/test_agent_real_psi4.py).
- New integration tests run real psi4 driven by mocked LLM (deterministic
  tool-call sequence) on H2O, CH4, NH3.

## [0.1.0] - committed 2026-04-29 (commit 9bbe51e)

First Phase-1 MVP: hard-coded H2O Plan→Confirm→Execute end-to-end via
psi4 (B3LYP-D3(BJ)/def2-TZVP). Trajectory + step artefacts persisted to
`runs/<task_id>/`. Established the MCP server pattern and the
formulas/rules KB structure.
