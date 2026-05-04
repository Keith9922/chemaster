# Changelog

所有面向用户可见的变更记录在此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased] — Streaming agent loop (foundation for `chemaster web`)

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
