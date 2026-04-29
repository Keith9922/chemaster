# Changelog

所有面向用户可见的变更记录在此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

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
