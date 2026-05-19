# Competitive Feature Scan — for ChemMaster

**Scope window**: 2026-03-20 → 2026-05-20 (last ~60 days).
**Sources**: `openai/codex` releases 0.128–0.131 + `developers.openai.com/codex`; `Hmbown/DeepSeek-TUI` v0.8.34–v0.8.39 changelog; `code.claude.com` docs for hooks, plugins, skills, subagents (Claude Code is closed-source so changelogs aren't published as releases; features are dated via doc presence and recent CLI versions referenced inline).
**Lens**: ChemMaster is Python 3.11 + Anthropic SDK + MCP, CLI + Textual TUI + FastAPI Web, 15 MCP tools, L1/L2/L3 permission gating, skills/user_kb already in place. Hooks and OS sandboxing are NOT yet implemented. Just-landed: AGENTS.md compat, agent-as-MCP-server, desktop notifications.

---

## 1. openai/codex (Rust terminal coding agent)

Recent: 0.131 (2026-05-18), 0.130 (2026-05-12), 0.129 (~2026-05-06), 0.128 (~2026-04-30). The releases ship `bwrap`, an `app-server`, a `responses-api-proxy`, a `codex-windows-sandbox-setup`, a Python SDK, an install.sh/install.ps1, and a config-schema.json — a full distribution stack worth studying.

### 1.1 OS-level sandboxing (Seatbelt + Bubblewrap + Windows WFP)
Codex sandboxes every shell command on macOS via `sandbox-exec` + Seatbelt policies, Linux via vendored `bwrap` (Bubblewrap 0.11.2) with seccomp namespacing, Windows via WFP filters and an `AppContainer`-style setup binary. 0.131 hardened deny-read rules, scoped write roots, and PowerShell wrapper unwrapping; 0.129 shipped a standalone `bwrap` fallback for npm/DotSlash installs.
- **Borrow? Yes.** ChemMaster runs untrusted Gaussian input files and shells out heavily; a per-task chroot/Seatbelt jail dramatically tightens our threat model and matches §5 ("复现优先") and the unfinished OS-sandbox checkbox in CLAUDE.md §0.
- **Cost: L.** Real platform-specific work; minimum viable cut is Linux-only `bwrap` wrapper (~1 week) before macOS/Windows parity.

### 1.2 Permission profiles (Auto / Untrusted / Never / Full-access)
Codex now has four built-in profiles plus per-cwd `--sandbox-profile` selection, with active-profile metadata exposed to clients. Untrusted auto-runs read-only ops, Auto allows workspace writes, Never disables prompts while keeping sandbox bounds, `--dangerously-bypass-approvals-and-sandbox` opts out.
- **Borrow? Yes (concept).** Maps cleanly onto our L1/L2/L3 in `~/.chemaster/policy.yaml` — Codex's profile name + per-cwd override is a UX template we should imitate.
- **Cost: S.** We already have the gating; this is renaming/exposing it as a top-level CLI flag and showing it in the status line.

### 1.3 `codex doctor` diagnostics
New in 0.131 — a one-shot command that audits runtime, auth, terminal, network, config, and local state and emits a support-ready report.
- **Borrow? Yes.** We already half-have this with `chemaster --check-engines`; extending it into a full `chemaster doctor` (psi4 / ORCA / xTB / Gaussian / BDF / MOMAP / cclib / RDKit / API key / SLURM reachability) directly serves hard indicator #1 (≤30 min to first result).
- **Cost: S.** ~1 day.

### 1.4 Plugin marketplace + bundled hooks + version-aware sharing
0.128–0.131 turned plugins into a real distribution channel: marketplace CLI, share metadata, remote bundle sync, discoverability controls, plugin-bundled hooks, role-aware share contexts. Plugins now ship hooks by default.
- **Borrow? Partially.** A community marketplace for ChemMaster *skills* (TADF protocol, xTB-conf-search, NEB workflow) is appealing long-term but premature for a thesis. Worth designing the manifest now so we don't repaint later.
- **Cost: M** (design-only now); L if implemented.

### 1.5 `@` unified picker (files/dirs/plugins/skills)
The TUI picker searches files, directories, plugins, and skills in one keystroke, backed by app-server plugin metadata.
- **Borrow? Yes.** Our Textual TUI should let `@water.xyz`, `@calc_gaussian.optimize`, `@skill:tadf-screen` resolve in one picker. Strong UX win for chemists who don't memorize tool names.
- **Cost: M.** Maybe ~1 week of Textual work.

### 1.6 Python SDK (`openai-codex`) with concurrent turn routing
0.131 published a real Python SDK as wheels, with pinned generated types and approval-mode passthrough.
- **Borrow? Skip-for-now.** We already expose ChemMaster as an MCP server (just landed), which is the better cross-client primitive. Don't duplicate.
- **Cost: N/A.**

### 1.7 Remote-control / app-server daemon
A long-running daemon-managed `codex remote-control` for headless app-server with runtime enable/disable, registry-backed remote environments.
- **Borrow? Skip.** This serves Codex's web/IDE clients. Our equivalent is the existing FastAPI Web layer; revisiting it now would slip the thesis.
- **Cost: N/A.**

---

## 2. Hmbown/DeepSeek-TUI (Rust TUI for DeepSeek API)

Six minor releases in 8 days (v0.8.34 → v0.8.39). Mostly polish, but the TUI plumbing is interesting because we share the same problem space (a streaming chat TUI talking to a non-OpenAI provider) and they've been Hardening features we haven't built yet.

### 2.1 Prefix-cache chip + cache-aware footer
v0.8.35–v0.8.36 added a footer chip showing prefix-cache stability (`cache prefix 100%`), and stopped red-flagging low last-request hit rates when the system/tool prefix itself was stable.
- **Borrow? Yes.** Anthropic's prompt-cache pricing matters for ChemMaster (system prompt + skills are huge); showing live cache hit rate in our Textual status bar would let us see when cache breaks (a CLAUDE.md open-question line item).
- **Cost: S.** Anthropic SDK already returns `cache_creation_input_tokens` / `cache_read_input_tokens`.

### 2.2 Per-call approval fingerprinting (arity-aware + lossy)
v0.8.39 fixed approval scoping: approving `cargo build` now covers `cargo build --release` (lossy family fingerprint), but *denials* are pinned to the exact call so denying one bash invocation doesn't over-block later calls.
- **Borrow? Yes.** Directly relevant to our L2 approval cards: when a chemist accepts "run Gaussian with `opt freq B3LYP/6-31G(d)`," they shouldn't be re-prompted for the same with `=tight`. Asymmetric approve-broad / deny-narrow is the right policy.
- **Cost: S.** A normalization helper plus session approval store extension.

### 2.3 Loop-guard against repeated identical tool calls
v0.8.38: identical tool-call blocks now return a *failed* result rather than success, so checklist/tool loops trip a halt path instead of spinning. Pairs with a checklist-style guidance system in their base prompt.
- **Borrow? Yes.** Chemistry tasks frequently retry the same SCF / opt; an explicit "you've called calc_gaussian.optimize with these exact args 3× — escalate" guard is cheap insurance against Anthropic billing surprises.
- **Cost: S.** Add a content-hash dedupe inside the agent loop.

### 2.4 Sub-agent done-handoff token economy
v0.8.36 changed `<deepseek:subagent.done>` sentinels to point at preceding summary lines rather than re-emitting JSON, citing prefix-cache economics. This is a tiny but smart pattern for keeping multi-agent context cache-friendly.
- **Borrow? Yes.** ChemMaster doesn't have sub-agents yet but our `recommend` cards and tool results show similar duplication. Worth borrowing the "point, don't duplicate" pattern when we add agent handoffs.
- **Cost: S.** Style/format change only.

### 2.5 Compaction pins user query in tool-heavy histories
v0.8.39: automatic compaction now pins the latest user text message when the retained tail only contains tool calls/results — avoids Jinja template failures and keeps "what did the user ask?" alive.
- **Borrow? Yes (eventually).** When ChemMaster context fills (Gaussian outputs are huge), we'll want compaction that preserves the original `chemaster run "..."` intent. Not blocking for thesis demo but a known sharp edge.
- **Cost: M.** Requires a compaction strategy we don't have yet.

### 2.6 Tencent Lighthouse + China-mirror update path
v0.8.37 set up `DEEPSEEK_TUI_RELEASE_BASE_URL` for users behind GitHub-blocking networks plus a CNB cargo-install fallback.
- **Borrow? Yes.** ChemMaster has Chinese-domestic users (BDF/MOMAP are PRC-origin). A `CHEMASTER_RELEASE_BASE_URL` env var + a mirror in CNB/Gitee is a 1-line change with disproportionate value.
- **Cost: S.**

### 2.7 ACP (Agent Communication Protocol) JSON-RPC id stringification
v0.8.39 supports Zed's stricter ACP client (string ids).
- **Borrow? Skip.** ACP is editor-integration plumbing; MCP is our protocol of choice.
- **Cost: N/A.**

---

## 3. Claude Code (Anthropic CLI)

No public changelog, but the docs site (`code.claude.com`) is the canonical reference and several features described below were added or substantially revamped in the v2.1.x line referenced inline.

### 3.1 Hooks system (lifecycle events, JSON schema, async, deduplication)
A first-class hooks system fires at session/turn/tool boundaries (`SessionStart`, `PreToolUse`, `PostToolUseFailure`, `PermissionRequest`, etc.) plus async events (`FileChanged`, `CwdChanged`, `Notification`). Handlers can be shell commands, HTTP endpoints, MCP tools, single-turn Claude prompts, or subagents. They return JSON to allow/deny/defer/inject context. Configurable in user, project, plugin scopes.
- **Borrow? Yes — high priority.** CLAUDE.md §11 has hooks listed as NOT yet implemented but valuable. For chemistry: `PreToolUse` hook validates input geometry sanity; `PostToolUse` hook auto-runs cclib parse after Gaussian; `SessionEnd` archives `runs/<task>`. Their JSON-stdin / exit-code contract is well-thought-out — borrow the schema verbatim.
- **Cost: M.** ~1.5 weeks for v1 (PreToolUse, PostToolUse, SessionStart/End, command type only).

### 3.2 Plugins as a package format (skills + agents + hooks + MCPs + LSPs + monitors)
A plugin is a directory with `.claude-plugin/plugin.json` plus optional `skills/`, `agents/`, `hooks/hooks.json`, `.mcp.json`, `.lsp.json`, `monitors/`, `bin/`, `settings.json`. Installable via marketplace, local dir, or URL/zip. Namespaced (e.g. `/my-plugin:hello`). Validation built in.
- **Borrow? Partially / design-only.** A "ChemMaster pack" format that bundles a skill (e.g., TADF) + the MCPs it depends on (`calc_gaussian.tddft`) + L2/L3 policy rules + a prompt-cache profile is genuinely powerful, but premature. *Design* the manifest now (cheap), defer the marketplace.
- **Cost: S** (manifest design); L (marketplace).

### 3.3 Skills: progressive disclosure + `!\`command\`` injection + `context: fork`
Claude Code skills are SKILL.md + supporting files; the `description` is always in context, full body only loads when invoked; ``!`cmd` `` placeholders execute *before* the model sees the prompt (preprocessing); `context: fork` runs the skill in an isolated subagent with its own system prompt.
- **Borrow? Yes — partial.** Our skills system already exists but is lighter. The two patterns worth importing: (a) `!\`cmd\`` dynamic context injection — for chem this is huge ("give me current geometry" via `!\`obabel input.xyz -O - --gen3d\``); (b) progressive disclosure so we don't bloat the system prompt with every skill body. *Skip* fork-into-subagent for now.
- **Cost: S** for `!\`cmd\`` injection; **S** for description-first loading.

### 3.4 Subagents with preloaded skills + isolated contexts
Subagents are specialized AI workers (`Explore`, `Plan`, `general-purpose`, custom). They get their own context window, their own system prompt, their own tool allowlist. Skills can be preloaded into a subagent (`skills:` frontmatter), and `context: fork` lets a parent skill delegate to one.
- **Borrow? Yes — eventually.** Chemistry maps well: a `geometry-builder` subagent (read-only, RDKit + obabel only), a `convergence-debugger` subagent (Gaussian output + L1-tier retries only), a `report-writer` subagent (cclib + viz only). Reduces both context and risk surface.
- **Cost: L.** Major architectural addition; defer past thesis unless we trim scope.

### 3.5 One-line install (`curl -fsSL https://claude.ai/install.sh | bash`) with background auto-update
Native installer + auto-update + Homebrew cask (stable & latest channels) + WinGet + apt/dnf/apk. Truly turnkey.
- **Borrow? Yes — high priority.** This is the lowest-friction path to indicator #1 (≤30 min first result). Our `pyproject.toml` exists but `pip install chemaster` doesn't ship engines. A one-liner that detects conda, installs a slim env, and primes psi4/xTB via conda-forge is a *thesis user study* enabler.
- **Cost: M.** ~1 week for a Bash + PowerShell installer that runs conda/mamba behind the scenes.

### 3.6 `routines` + `/loop` + scheduled tasks
Routines run on Anthropic-managed infra on a cron; `/loop` repeats a prompt within a session for polling; desktop scheduled tasks run on user's machine.
- **Borrow? Skip mostly.** Chemistry researchers don't typically need cron'd LLM calls. *Optional borrow*: `/loop` for SLURM job polling — "every 5 min, check job 12345 and report" — but that's better expressed as a single tool that blocks-with-timeout.
- **Cost: S** for `/loop`-like primitive; **L** for routines.

### 3.7 `additionalContext` injection from hooks + auto-memory
Hooks on `SessionStart` and `PreToolUse` can inject system reminders (branch name, environment) that don't appear as chat messages. Claude Code also builds "auto memory" by saving build commands and debug insights cross-session.
- **Borrow? Yes — small piece.** `additionalContext` for ChemMaster: every turn, inject "current geometry: H2O, multiplicity: 1, charge: 0, last successful method: B3LYP/6-31G(d)" silently. Synergizes with our user_kb. Auto-memory is more ambitious — skip for thesis.
- **Cost: S** for additionalContext (once hooks land); M for auto-memory.

### 3.8 `--add-dir` skills auto-discovery + live change detection
Claude Code watches skill directories and picks up edits without restart. `--add-dir` extends file access *and* auto-loads `.claude/skills/` from added directories.
- **Borrow? Yes.** Live reload of our `kb/skills/` is a small DX win during demos and thesis writing. Already partly there via Python's watchdog ecosystem.
- **Cost: S.**

---

## Top 5 to consider (prioritized for ChemMaster's thesis window)

| # | Feature | Source | Why it wins | Cost |
|---|---|---|---|---|
| 1 | **Hooks system (PreToolUse / PostToolUse / SessionStart / SessionEnd, command + http types)** | Claude Code (§3.1) | Closes the explicit open question in CLAUDE.md §0; unlocks auto-cclib-after-Gaussian, geometry sanity gates, archive-on-session-end, L1/L2/L3 enforcement-by-policy without code changes. Highest leverage per dev-week. | M |
| 2 | **`chemaster doctor`** | codex (§1.3) | Cheap (~1 day) and directly drives hard indicator #1 (≤30 min to first result). Auditing 6 engines + API keys + SLURM in one command is a thesis-demo gold star. | S |
| 3 | **Prefix-cache chip + arity-aware approval fingerprints** | DeepSeek-TUI (§2.1, §2.2) | Two small changes that compound into a tight L2 confirmation UX *and* visible Anthropic-cache savings. Resolves the "prompt caching?" open question concretely. | S+S |
| 4 | **One-line installer + background auto-update + Homebrew cask** | Claude Code (§3.5) | Required for the 2–3 被试 user study in indicator 3b/5 ("submission friction ↓50%"). Conda complexity is currently the #1 risk to that study. | M |
| 5 | **OS-level sandbox (Linux `bwrap` first, macOS Seatbelt second)** | codex (§1.1) | The other unchecked CLAUDE.md item. Even a minimal Linux-only `bwrap` jail around `calc_*` tools is a defensible thesis chapter §3 (security) and prevents the next `rm -rf $HOME` headline. | L (S for MVP) |

**Honorable mentions**: dynamic `!\`cmd\`` context injection in skills (§3.3, very cheap, very Pythonic), unified `@` picker in the TUI (§1.5), `additionalContext` once hooks land (§3.7), and the China mirror env var (§2.6 — 1-line, near-zero cost).

**Explicit defers**: plugins/marketplace (§1.4, §3.2 — design manifest only), subagents (§3.4), routines (§3.6), remote-control daemon (§1.7), ACP (§2.7).
