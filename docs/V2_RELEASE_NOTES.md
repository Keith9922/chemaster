# ChemMaster Architecture V2 — Release Notes

> Date: 2026-04-29
> Branch: `claude/keen-beaver-625252`
> Goal: Convert ChemMaster from a hard-coded H2O Plan→Confirm→Execute
> pipeline into a real **Claude-Code-style tool-use agent for
> computational chemistry**.

---

## 1. What changed (one paragraph)

Previously the agent was a regex router (`if "h2o" in text: ...`) that
emitted a fixed Plan, asked for confirmation via a token gate, and ran
through a linear Executor. V2 replaces all three with a single
**LLM-driven tool-use loop** (`BaseAgent` / `ChemAgent`) that wraps the
Anthropic SDK, drives every existing MCP server as a tool, surfaces
each tool's `suggestion` field so the agent can self-recover, gates
destructive / long-running tools by **per-tool flags + a user
callback**, and persists every step as a replayable Trajectory. The
old "Skill as architectural layer" idea is gone — Skills are now
markdown documents in `kb/skills/` that the Agent reads via the
`use_skill` tool when planning.

---

## 2. Architecture: V1 vs V2

```
                          V1                                       V2
                ┌──────────────────────┐                ┌──────────────────────┐
   L6/L5  TUI   │ Textual              │      L5  CLI   │ chemaster run "<…>"   │
                ├──────────────────────┤                ├──────────────────────┤
   L5  Agent    │ Planner ─┐           │      L4  Loop  │  BaseAgent /          │
                │ Confirm ─┤  3-stage  │                │  ChemAgent            │
                │ Executor ┘           │                │  (Anthropic + tool    │
                │ Iterator             │                │   use loop)           │
                ├──────────────────────┤                │  finish/ask/think     │
   L4  Skills   │ Markdown w/ when_to_use ├──────────┐  │  Trajectory persist   │
                │ trigger matching      │           │  ├──────────────────────┤
                ├──────────────────────┤            │  │ L3  Tools (MCP        │
   L3  MCP      │ chem.calc.* / kb     │            ├─→│      servers, adapted │
                │  / io / viz / hpc    │            │  │      via MCPToolAdapter)│
                ├──────────────────────┤            │  ├──────────────────────┤
   L2  Engines  │ psi4/xtb/orca/bdf    │            │  │ L2  Engines (same)    │
                ├──────────────────────┤            │  ├──────────────────────┤
   L1  KB       │ formulas + rules     │            │  │ L1  KB                │
                │                      │            │  │  formulas (Python)    │
                │                      │            │  │  rules (YAML)         │
                │                      │            │  │  skills (Markdown,    │
                │                      │            └──┘  read by use_skill)   │
                └──────────────────────┘                └──────────────────────┘
                  6 layers, Skill required               5 layers, Skill optional
```

**Key shifts:**

| Concern             | V1                                     | V2                                                                          |
|---------------------|----------------------------------------|-----------------------------------------------------------------------------|
| Agent reasoning     | Hard-coded `if/elif`                   | Real Claude via `AnthropicLLM`; tool-use loop                                |
| Skill role          | Architectural layer + trigger router   | Markdown docs in `kb/skills/`, read by the `use_skill` tool                  |
| Confirmation        | `confirm_token` central gate           | `is_destructive` / `is_long_running` per tool + user callback                |
| Error recovery      | Skill-internal `if error_code == ...`  | Tool returns `{error_code, suggestion}`, Agent picks next call               |
| Persistence         | `runs/<id>/step_NN/result.json`        | Same plus `trajectory.json` (full dialog) + `confirmations.jsonl` (audit)    |
| LLM provider        | Anthropic-only (in plan)               | `BaseLLM` interface; `MockLLM` for tests, `AnthropicLLM` real, OpenAI stub  |
| Test coverage       | 86 unit + 2 integration                | **166 unit + 6 integration** (ChemAgent driving real psi4 across 4-5 molecules) |

---

## 3. New modules

```
chemaster/agent/
├── types.py              Message / Dialog / ToolCall / Trajectory / TaskInstance
├── llm_client.py         BaseLLM, MockLLM, AnthropicLLM, OpenAICompatLLM (stub)
├── context.py            ContextManager (latest-half / sliding-window truncation)
├── tool_registry.py      BaseTool / ToolRegistry / MCPToolAdapter / ToolResult
├── builtins.py           FinishTool / AskUserTool / ThinkTool
├── agent.py              BaseAgent + ChemAgent + build_default_chem_agent
├── tool_loader.py        TOOL_MANIFEST + build_default_registry (22 tools)
├── system_prompt.md      English chemistry-expert system prompt
├── plan.py               (legacy) Plan / PlanStep / Citation — V1 compat
├── planner.py            (legacy) hard-coded H2O Planner — V1 compat
├── confirmation.py       (legacy → simplified) ConfirmationLoop with auto_approve
├── executor.py           (legacy) linear Executor for V1 H2O e2e
├── iterator.py           (deferred) Phase-4+ benchmark loop
└── retriever.py          (deprecated) superseded by chem.kb MCP

chemaster/mcp/kb/server.py
   kb_search(query, top_k)        — term-frequency search over rules + skills
   list_skills()                  — enumerate playbooks
   use_skill(name, action, ref)   — read SKILL.md (get_info / get_metadata / get_reference)

chemaster/cli.py
   chemaster run "<intent>"       (plus --no-confirm / --max-turns / --enabled-tool)
   chemaster skills list / show <name>
   chemaster kb search / list
   chemaster tools list           — agent-visible registry with permission flags
   chemaster mcps list
   chemaster --check-engines

chemaster/__main__.py             — `python -m chemaster …` entry point
```

**Migrated:** `chemaster/skills/` → `chemaster/kb/skills/` (10 SKILL.md files).

---

## 4. Test coverage (172 / 172 passing)

### Unit tests (166)

| Suite                       | Tests | Coverage |
|-----------------------------|-------|----------|
| test_agent_loop.py          | 18    | finish / ask_user / think round-trip; nudging; max_turns; per-tool confirm; tool exception trapping; ChemAgent system prompt loading |
| test_kb_mcp.py              | 14    | kb_search hits / misses; list_skills; use_skill get_info / get_metadata / get_reference; error paths; registry integration |
| test_agent_recovery.py      | 4     | error suggestion surfaces in observation; agent recovers from SCF failure using suggestion; gives up at max_turns |
| test_confirmation_log.py    | 4     | trajectory meta accumulates approved/declined counts; jsonl audit trail; read-only bypass |
| test_cli.py                 | 10    | --version, --check-engines; skills/kb/tools/mcps list; chemaster run with no API key |
| test_confirmation.py        | 5     | ConfirmationLoop.auto_approve / reject / token uniqueness |
| (pre-existing)              | 111   | const, formulas, plan, planner, executor, calc_psi4 (mock), calc_xtb, io_ase, parse_cclib, viz, photophysics, planner, plan |

### Integration tests (6 + 1 opt-in)

| Test                                         | What it proves                                                  | Wall time |
|----------------------------------------------|-----------------------------------------------------------------|-----------|
| test_h2o_e2e.py::test_h2o_end_to_end         | V1 Plan→Execute path still passes (backward-compat)             | ~22 s     |
| test_h2o_e2e.py::test_h2o_smoke_under_5min   | V1 e2e fits under the 5-min hard metric                         | ~4 s      |
| test_agent_real_psi4.py::methane             | ChemAgent drives real psi4 to compute CH4 opt+freq end-to-end   | ~26 s     |
| test_agent_real_psi4.py::ammonia             | Same for NH3                                                    | ~25 s     |
| test_agent_real_psi4.py::trajectory_persist  | runs/<id>/trajectory.json contains all 4 steps in order         | ~25 s     |
| test_agent_real_psi4.py::finish_payload      | Agent's finish summary key_results round-trips                  | ~25 s     |
| test_e2e_sweep.py::sweep[water]              | Comprehensive sweep across H2O / CH4 / NH3 / CO2                | ~14 s     |
| test_e2e_sweep.py::sweep[methane]            | …                                                               | ~16 s     |
| test_e2e_sweep.py::sweep[ammonia]            | …                                                               | ~14 s     |
| test_e2e_sweep.py::sweep[co2]                | Linear molecule (3N-5 modes)                                    | ~17 s     |
| test_e2e_sweep.py::sweep_summary_report      | Aggregated Markdown report at runs/<sweep>/_e2e_sweep_report.md | <1 s      |
| test_e2e_sweep.py::sweep[ethanol] (opt-in)   | 9-atom organic; 21 modes                                        | ~175 s    |

Run-once command:

```bash
# Routine (≤ 2 min):
pytest -m integration

# Full sweep (~5 min):
CHEMASTER_E2E_FULL=1 pytest -m integration
```

---

## 5. How to use the V2 system

```bash
# 1. Check engines
chemaster --check-engines

# 2. List the tools the Agent has
chemaster tools list

# 3. Search the knowledge base
chemaster kb search "basis for transition metals"
chemaster skills list
chemaster skills show tadf-pipeline

# 4. Run the agent (needs ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=sk-ant-...
chemaster run "Compute the energy of benzene"

# 5. Run the agent with auto-approval (CI / scripted use)
chemaster run "Optimize methanol" --no-confirm

# 6. Inspect a previous run
ls runs/<task_id>/
cat runs/<task_id>/trajectory.json
cat runs/<task_id>/confirmations.jsonl
```

---

## 6. What's intentionally still missing (deferred)

- **Real LLM integration smoke** — needs ANTHROPIC_API_KEY (user-supplied,
  per agreed plan).
- **OpenAI-compatible / Qwen / DeepSeek backend** — `OpenAICompatLLM`
  is a stub; wire-up is straightforward (chat-completions with
  function-calling).
- **Textual TUI** — CLI is the V2 baseline. TUI is an experience
  upgrade for a later iteration.
- **HPC async submission** — `chem.hpc.slurm` MCP exists; integrating
  Trajectory-aware async polling is Phase 5.
- **TADF anchor molecules** — system prompt + skill exists; running
  the full pipeline on 4CzIPN / DMAC-DPS / etc. is Phase 3.
- **ORCA / BDF / MultiWFN** — server.py modules are placeholders;
  real wiring is Phase 4.
- **Multi-channel release** — only PyPI is on the V2 path; conda-forge,
  Homebrew, Docker, plugin marketplace, JOSS are pushed to "future
  work" in the thesis.

---

## 7. Commit log (V2 batch)

```
bb9151a test(integration): comprehensive E2E sweep across 4-5 molecules
b14afe8 docs: sync architecture V2 across CLAUDE.md / ROADMAP / guides
66994fc feat(agent): per-tool confirmation log + audit trail in trajectory
2adf9ad test(integration): ChemAgent + real psi4 end-to-end (CH4, NH3)
71e5497 feat(agent): error-recovery loop hardening + 4 new unit tests
3518f83 refactor(agent): legacy modules become V2 compatibility shims
ed084f7 chore: untrack timer.dat (psi4 leftover, ignored going forward)
f311c57 test(agent): add 18 agent-loop unit tests + harden tool-exception handling
   (and earlier: feat(agent): introduce BaseAgent + ToolRegistry skeleton)
```

```
9bbe51e feat(agent): H2O end-to-end smoke test passing — Phase 1 MVP complete   ← V1 baseline
```

---

*Generated 2026-04-29 by Claude Sonnet 4.6 in autonomous execution mode,
following the iterate-and-test plan from `2026-04-29 architecture-V2 PR`.*
