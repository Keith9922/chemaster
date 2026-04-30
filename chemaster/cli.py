"""``chemaster`` command-line entry point.

Sub-commands:

- ``chemaster``                 → REPL (placeholder Textual TUI)
- ``chemaster run "<intent>"``  → one-shot agent run; prints summary + report path
- ``chemaster --version``       → version
- ``chemaster --check-engines`` → engine availability
- ``chemaster init``            → user config setup (placeholder)
- ``chemaster eval <yaml>``     → benchmark / smoke test
- ``chemaster skills list``     → list available skills (kb/skills/)
- ``chemaster skills show <name>`` → print a skill's SKILL.md
- ``chemaster kb search "<q>"`` → search the knowledge base
- ``chemaster mcps list``       → list registered MCP servers
- ``chemaster tools list``      → list agent-visible tool names
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from chemaster import __version__

console = Console()


# ══════════════════════════════════════════════════════════════════════════════
# Top-level group
# ══════════════════════════════════════════════════════════════════════════════


@click.group(invoke_without_command=True)
@click.option("--version", is_flag=True, help="Print version and exit.")
@click.option("--check-engines", is_flag=True, help="Check installed compute engines.")
@click.option("--tui", is_flag=True,
              help="Launch the experimental Textual TUI (beta).")
@click.pass_context
def main(ctx: click.Context, version: bool, check_engines: bool, tui: bool) -> None:
    """ChemMaster — AI agent for computational chemistry."""
    if version:
        click.echo(f"chemaster {__version__}")
        return
    if check_engines:
        _check_engines()
        return
    if tui:
        try:
            from chemaster.tui.app import run_tui
            run_tui()
        except Exception as exc:
            click.secho(f"TUI failed to launch: {exc}", fg="red", err=True)
            sys.exit(1)
        return
    if ctx.invoked_subcommand is None:
        _interactive_repl()


# ══════════════════════════════════════════════════════════════════════════════
# `run` — the headline V2 command
# ══════════════════════════════════════════════════════════════════════════════


@main.command()
@click.argument("intent")
@click.option("--runs-dir", default="./runs", show_default=True,
              help="Where to write per-task artefacts.")
@click.option("--max-turns", type=int, default=30, show_default=True,
              help="Maximum agent loop iterations.")
@click.option("--llm-provider",
              type=click.Choice(["mock", "anthropic", "minimax", "qwen",
                                 "deepseek", "openai_compat"]),
              default=None,
              help="LLM provider. Defaults to 'anthropic' (if ANTHROPIC_API_KEY) "
                   "→ 'minimax' (if MINIMAX_API_KEY) → 'qwen' (if "
                   "DASHSCOPE_API_KEY) → 'deepseek' (if DEEPSEEK_API_KEY) "
                   "→ 'mock' (no real LLM).")
@click.option("--llm-model", default=None,
              help="Override LLM model id (e.g. claude-sonnet-4-6, MiniMax-M2.7).")
@click.option("--no-confirm", is_flag=True,
              help="Auto-approve all destructive / long-running tool calls.")
@click.option("--enabled-tool", multiple=True,
              help="Whitelist a single tool by name; pass multiple times. "
                   "If unset, all registered tools are exposed.")
def run(
    intent: str,
    runs_dir: str,
    max_turns: int,
    llm_provider: str | None,
    llm_model: str | None,
    no_confirm: bool,
    enabled_tool: tuple[str, ...],
) -> None:
    """Run the agent on a single natural-language task.

    Examples:
        chemaster run "Compute the energy of benzene"
        chemaster run "Optimize ethanol" --no-confirm
    """
    import os

    from chemaster.agent.agent import AgentConfig, ChemAgent
    from chemaster.agent.llm_client import LLMConfig, create_llm
    from chemaster.agent.tool_loader import build_default_registry
    from chemaster.agent.types import TaskInstance

    # Pick provider (auto-detect from env vars unless explicitly overridden).
    provider = llm_provider
    if provider is None:
        if os.environ.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.environ.get("MINIMAX_API_KEY"):
            provider = "minimax"
        elif os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY"):
            provider = "qwen"
        elif os.environ.get("DEEPSEEK_API_KEY"):
            provider = "deepseek"
        else:
            provider = "mock"

    if provider == "mock":
        click.secho(
            "⚠ No LLM API key set — using MockLLM. "
            "The agent cannot reason; this run will exit immediately.",
            fg="yellow", err=True,
        )
        click.secho(
            "  Set ANTHROPIC_API_KEY or MINIMAX_API_KEY to enable a real model.",
            fg="yellow", err=True,
        )

    # Sensible default model per provider.
    default_model = {
        "anthropic": "claude-sonnet-4-6",
        "minimax": "MiniMax-M2.7",
        "qwen": "qwen-max",
        "deepseek": "deepseek-chat",
        "mock": "mock",
    }.get(provider, "")
    cfg = LLMConfig(provider=provider, model=llm_model or default_model)
    try:
        llm = create_llm(cfg)
    except Exception as exc:
        click.secho(f"Failed to initialize LLM: {exc}", fg="red", err=True)
        sys.exit(2)

    registry = build_default_registry()
    confirm_cb = (lambda *_: True) if no_confirm else _interactive_confirm

    agent_cfg = AgentConfig(
        max_turns=max_turns,
        runs_dir=Path(runs_dir),
        confirm_callback=confirm_cb,
        enabled_tools=list(enabled_tool) or None,
    )
    agent = ChemAgent(llm=llm, tools=registry, config=agent_cfg)

    console.print(Panel(
        f"[bold]{intent}[/bold]\n"
        f"provider={provider}  model={cfg.model}  tools={len(registry)}",
        title="ChemMaster Agent",
        border_style="cyan",
    ))

    def _on_step(step, n, total):
        ass = step.assistant_message
        if not ass or not ass.tool_calls:
            return
        for tc in ass.tool_calls:
            obs_first = ""
            for tr in step.tool_responses:
                if tr.tool_call_id == tc.id:
                    obs_first = (tr.content or "").splitlines()[0][:90]
                    break
            mark = "·" if not obs_first else ("✗" if any(
                tr.is_error for tr in step.tool_responses
                if tr.tool_call_id == tc.id) else "✓")
            console.print(
                f"  [dim]step {n:>2}/{total}[/dim]  "
                f"[cyan]{tc.name}[/cyan]  {mark}  "
                f"[dim]{obs_first}[/dim]"
            )

    try:
        traj = agent.run(TaskInstance(description=intent), on_step=_on_step)
    except Exception as exc:
        _render_agent_error(exc, agent_cfg.runs_dir, getattr(agent, "trajectory", None))
        sys.exit(3)

    _print_summary(traj, agent_cfg.runs_dir)
    _write_markdown_report(traj, agent_cfg.runs_dir)


# ══════════════════════════════════════════════════════════════════════════════
# Skills / KB / MCPs / tools commands
# ══════════════════════════════════════════════════════════════════════════════


@main.group()
def skills() -> None:
    """Manage skill playbooks (kb/skills/)."""


@skills.command(name="list")
def skills_list() -> None:
    """List every skill with a one-line summary."""
    from chemaster.mcp.kb.server import list_skills as _list_skills

    result = _list_skills()
    if not result["ok"]:
        click.secho("KB error: " + result.get("details", ""), fg="red")
        sys.exit(1)
    table = Table(title="Skills (kb/skills/)", show_lines=False)
    table.add_column("name", style="cyan")
    table.add_column("summary")
    for sk in result["result"]["skills"]:
        table.add_row(sk["name"], sk["summary"][:80])
    console.print(table)


@skills.command(name="show")
@click.argument("name")
def skills_show(name: str) -> None:
    """Print a skill's SKILL.md content."""
    from chemaster.mcp.kb.server import use_skill

    result = use_skill(skill_name=name, action="get_info")
    if not result["ok"]:
        click.secho(result.get("details", "skill not found"), fg="red")
        click.echo(result.get("suggestion", ""))
        sys.exit(1)
    console.print(Panel(
        result["result"]["content"],
        title=f"skill: {name}",
        border_style="green",
    ))


@main.group()
def kb() -> None:
    """Knowledge-base operations."""


@kb.command(name="search")
@click.argument("query")
@click.option("--top-k", type=int, default=5, show_default=True)
def kb_search_cmd(query: str, top_k: int) -> None:
    """Search the chemistry knowledge base."""
    from chemaster.mcp.kb.server import kb_search

    result = kb_search(query=query, top_k=top_k)
    if not result["ok"]:
        click.secho(result.get("details", "search failed"), fg="red")
        sys.exit(1)
    hits = result["result"]["hits"]
    if not hits:
        click.echo(f"No hits for {query!r}.")
        return
    table = Table(title=f"kb_search: {query!r}", show_lines=True)
    table.add_column("kind", style="dim", width=6)
    table.add_column("title", style="cyan", width=30)
    table.add_column("score", justify="right", width=6)
    table.add_column("snippet")
    for h in hits:
        table.add_row(h["kind"], h["title"], f"{h['score']:.2f}", h["snippet"][:120])
    console.print(table)


@kb.command(name="list")
def kb_list() -> None:
    """List the YAML rule files in kb/rules/."""
    base = Path(__file__).parent / "kb" / "rules"
    for child in sorted(base.iterdir()):
        if child.is_file():
            click.echo(child.name)


@main.group()
def mcps() -> None:
    """MCP server management."""


@mcps.command(name="list")
def mcps_list() -> None:
    """List every registered MCP server entry-point."""
    try:
        from chemaster.mcp import list_servers
        for name in list_servers():
            click.echo(name)
    except Exception as exc:
        click.secho(f"Failed to enumerate MCPs: {exc}", fg="red", err=True)
        sys.exit(1)


@main.group()
def tools() -> None:
    """Agent tool registry."""


@tools.command(name="list")
def tools_list() -> None:
    """List every tool the Agent has access to (built-ins + adapted MCPs)."""
    from chemaster.agent.tool_loader import build_default_registry

    reg = build_default_registry()
    table = Table(title=f"Agent tool registry ({len(reg)} tools)", show_lines=False)
    table.add_column("name", style="cyan")
    table.add_column("flags", style="dim")
    table.add_column("description")
    for name in sorted(reg.names()):
        t = reg.get(name)
        flags: list[str] = []
        if t.is_read_only:
            flags.append("read")
        if t.is_destructive:
            flags.append("destructive")
        if t.is_long_running:
            flags.append("long")
        table.add_row(
            name,
            "/".join(flags) or "—",
            (t.description or "").split("\n")[0][:90],
        )
    console.print(table)


# ══════════════════════════════════════════════════════════════════════════════
# show / replay / init / eval
# ══════════════════════════════════════════════════════════════════════════════


@main.command()
@click.argument("task_id")
@click.option("--runs-dir", default="./runs", show_default=True)
def show(task_id: str, runs_dir: str) -> None:
    """Pretty-print a previous task's trajectory (without re-running)."""
    task_dir = Path(runs_dir) / task_id
    traj_path = task_dir / "trajectory.json"
    if not traj_path.exists():
        click.secho(f"No trajectory at {traj_path}", fg="red", err=True)
        click.echo("Available task ids:")
        for d in sorted(Path(runs_dir).glob("*/")):
            click.echo(f"  {d.name}")
        sys.exit(1)
    traj = json.loads(traj_path.read_text())

    style = {"completed": "green", "failed": "red",
             "waiting_for_input": "yellow"}.get(traj["status"], "white")
    console.print(Panel(
        f"[bold]Status:[/bold] [{style}]{traj['status']}[/{style}]\n"
        f"[bold]Started:[/bold] {traj.get('started_at')}\n"
        f"[bold]Finished:[/bold] {traj.get('finished_at')}\n"
        f"[bold]Steps:[/bold] {len(traj.get('steps', []))}\n"
        f"[bold]Path:[/bold] {traj_path}",
        title=f"Task {task_id}",
        border_style=style,
    ))

    table = Table(title="Steps", show_lines=False)
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("tool", style="cyan", width=28)
    table.add_column("ok", width=4)
    table.add_column("snippet")
    for i, step in enumerate(traj.get("steps", []), 1):
        ass = step.get("assistant_message") or {}
        tcs = ass.get("tool_calls") or []
        for tc in tcs:
            name = tc.get("name", "?")
        if not tcs:
            table.add_row(str(i), "(no tool call)", "—", "—")
            continue
        for tc in tcs:
            for tr in step.get("tool_responses", []):
                ok = "✓" if not tr.get("is_error") else "✗"
                snippet = (tr.get("content") or "")[:80].replace("\n", " ")
                table.add_row(str(i), tc["name"], ok, snippet)
                break
            else:
                table.add_row(str(i), tc["name"], "·", "(no response yet)")
    console.print(table)

    payload = traj.get("finish_payload") or {}
    if payload.get("summary"):
        console.print(Panel(payload["summary"], title="Summary",
                            border_style="cyan"))
    if payload.get("key_results"):
        kr = Table(title="Key results")
        kr.add_column("name"); kr.add_column("value")
        for k, v in payload["key_results"].items():
            kr.add_row(str(k), str(v))
        console.print(kr)


@main.command()
@click.argument("task_id")
@click.option("--runs-dir", default="./runs", show_default=True)
def replay(task_id: str, runs_dir: str) -> None:
    """Re-run a previous task using its persisted user intent.

    Useful for: regression testing after a tool/MCP change, sharing a run
    with a collaborator (point them at the same task_id), or recomputing
    after a system upgrade.
    """
    task_dir = Path(runs_dir) / task_id
    traj_path = task_dir / "trajectory.json"
    if not traj_path.exists():
        click.secho(f"No trajectory at {traj_path}", fg="red", err=True)
        sys.exit(1)
    traj = json.loads(traj_path.read_text())
    # Reconstruct the original user prompt: it's in the first user message.
    intent = None
    # The trajectory schema doesn't include the dialog directly; for V2 we
    # store it in step assistant messages, so the easiest source of truth
    # is the task description. Fall back to the meta key.
    intent = (traj.get("meta") or {}).get("user_intent")
    if not intent:
        click.secho(
            f"Task {task_id} has no recoverable user_intent on the "
            f"trajectory. Re-run manually with `chemaster run \"…\"`.",
            fg="yellow", err=True,
        )
        sys.exit(2)
    click.echo(f"Replaying task {task_id}: {intent}")
    ctx = click.get_current_context()
    ctx.invoke(run, intent=intent, runs_dir=runs_dir, max_turns=30,
               llm_provider=None, llm_model=None,
               no_confirm=True, enabled_tool=())


@main.command()
def init() -> None:
    """Interactive first-time configuration wizard.

    Walks you through setting up:
      - LLM API key (Anthropic / MiniMax)
      - Default runs directory
      - Default LLM provider

    Writes to ~/.chemaster/config.toml (created if missing). The agent will
    pick up the values via env-var fallback OR by sourcing ~/.chemaster/env.
    """
    config_dir = Path.home() / ".chemaster"
    config_dir.mkdir(parents=True, exist_ok=True)
    env_path = config_dir / "env"

    console.print(Panel(
        "[bold]ChemMaster setup wizard[/bold]\n"
        "We'll configure your LLM provider and default settings. Skip any "
        "prompt by pressing Enter.",
        title="Welcome",
        border_style="cyan",
    ))

    provider = click.prompt(
        "LLM provider [anthropic / minimax / mock]",
        default="minimax", type=click.Choice(["anthropic", "minimax", "mock"]),
    )
    api_key = ""
    if provider == "anthropic":
        api_key = click.prompt("ANTHROPIC_API_KEY", hide_input=True, default="")
    elif provider == "minimax":
        api_key = click.prompt("MINIMAX_API_KEY", hide_input=True, default="")

    runs_dir = click.prompt("Default runs directory",
                           default=str(Path.cwd() / "runs"))

    lines = [
        f"# Generated by `chemaster init` on {time.strftime('%Y-%m-%d %H:%M')}",
        f"export CHEMASTER_LLM_PROVIDER={provider}",
        f"export CHEMASTER_RUNS_DIR={runs_dir}",
    ]
    if provider == "anthropic" and api_key:
        lines.append(f"export ANTHROPIC_API_KEY={api_key}")
    if provider == "minimax" and api_key:
        lines.append(f"export MINIMAX_API_KEY={api_key}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_path.chmod(0o600)

    console.print(Panel(
        f"Wrote [bold]{env_path}[/bold] (mode 0600).\n\n"
        "Add this to your shell rc:\n\n"
        f"    [cyan]source {env_path}[/cyan]\n\n"
        "Then run [bold]chemaster --check-engines[/bold] to verify the "
        "calculation backends, and [bold]chemaster run \"<intent>\"[/bold] "
        "to fire your first agent task.",
        title="Done", border_style="green",
    ))


@main.command(name="eval")
@click.argument("yaml_path")
def eval_cmd(yaml_path: str) -> None:
    """Run a benchmark spec (legacy placeholder)."""
    click.echo(f"chemaster eval {yaml_path}: benchmark runner not yet wired into V2.")


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _render_agent_error(exc: Exception, runs_dir: Path, traj=None) -> None:
    """Pretty-print an agent crash with hints + trajectory pointer.

    Tells the user what likely went wrong and where to look. Tries to map
    common exception types to actionable suggestions.
    """
    name = type(exc).__name__
    msg = str(exc)

    hints: list[str] = []
    msg_lower = msg.lower()
    if "anthropic" in msg_lower or "api_key" in msg_lower or "401" in msg:
        hints.append("Check ANTHROPIC_API_KEY / MINIMAX_API_KEY is set "
                     "and not expired.")
    if "context" in msg_lower and "length" in msg_lower:
        hints.append("Context overflow — try fewer enabled tools, "
                     "or break the task into smaller steps.")
    if "timeout" in msg_lower or "timed out" in msg_lower:
        hints.append("LLM API timeout — try a smaller model, fewer tokens, "
                     "or check your network.")
    if "connection" in msg_lower or "ssl" in msg_lower:
        hints.append("Network/TLS error — verify connectivity and that "
                     "no proxy is interfering.")
    if not hints:
        hints.append("Unexpected error. Re-run with --max-turns lower "
                     "to isolate the failing step.")

    body_lines = [f"[bold red]{name}[/bold red]: {msg}", ""]
    body_lines.append("[bold]Hints[/bold]:")
    for h in hints:
        body_lines.append(f"  • {h}")
    if traj is not None and traj.task_id:
        body_lines.append("")
        body_lines.append(
            f"[bold]Inspect:[/bold] {runs_dir / traj.task_id / 'trajectory.json'}"
        )
    console.print(Panel("\n".join(body_lines),
                        title="Agent error", border_style="red"))


def _interactive_repl() -> None:
    """No-args ``chemaster`` drops into a text-mode REPL.

    Lightweight conversational interface backed by ChemAgent. Picks the
    LLM provider from env vars; if no key set, prints a banner with quick
    setup hints instead of an error.
    """
    import os

    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_minimax = bool(os.environ.get("MINIMAX_API_KEY"))

    console.print(Panel(
        "[bold cyan]ChemMaster[/bold cyan] — natural-language computational "
        "chemistry agent\n\n"
        f"version  [dim]{__version__}[/dim]\n"
        f"provider [dim]{'anthropic' if has_anthropic else ('minimax' if has_minimax else 'NONE — set ANTHROPIC_API_KEY or MINIMAX_API_KEY')}[/dim]\n\n"
        "Type a chemistry task in plain language. Examples:\n"
        "  [cyan]Compute the energy of methane[/cyan]\n"
        "  [cyan]Optimize benzene at B3LYP/def2-SVP and run TDDFT[/cyan]\n"
        "  [cyan]ΔE_ST of DMAC-BP at TDA-B3LYP[/cyan]\n\n"
        "Type [yellow]/help[/yellow] for commands, [yellow]/exit[/yellow] "
        "to leave.",
        title="ChemMaster REPL",
        border_style="cyan",
    ))

    if not (has_anthropic or has_minimax):
        console.print("[red]No LLM API key found.[/red] Run "
                      "[cyan]chemaster init[/cyan] to set one up, then re-run.")
        return

    from chemaster.agent.agent import AgentConfig, ChemAgent
    from chemaster.agent.llm_client import LLMConfig, create_llm
    from chemaster.agent.tool_loader import build_default_registry
    from chemaster.agent.types import TaskInstance

    provider = "anthropic" if has_anthropic else "minimax"
    default_model = {"anthropic": "claude-sonnet-4-6",
                    "minimax": "MiniMax-M2.7"}[provider]
    llm = create_llm(LLMConfig(provider=provider, model=default_model))
    registry = build_default_registry()
    cfg = AgentConfig(
        max_turns=30,
        runs_dir=Path(os.environ.get("CHEMASTER_RUNS_DIR", "./runs")),
        confirm_callback=_interactive_confirm,
    )
    agent = ChemAgent(llm=llm, tools=registry, config=cfg)

    while True:
        try:
            line = console.input("[bold cyan]chemaster>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not line:
            continue
        if line in ("/exit", "/quit", "/q"):
            break
        if line == "/help":
            console.print(
                "[cyan]/help[/cyan]    show this message\n"
                "[cyan]/tools[/cyan]   list available tools\n"
                "[cyan]/exit[/cyan]    leave the REPL\n"
                "Anything else is sent to the agent as a task."
            )
            continue
        if line == "/tools":
            for name in sorted(registry.names()):
                console.print(f"  [dim]{name}[/dim]")
            continue

        try:
            traj = agent.run(TaskInstance(description=line))
            _print_summary(traj, cfg.runs_dir)
            _write_markdown_report(traj, cfg.runs_dir)
        except Exception as exc:
            console.print(f"[red]Agent crashed:[/red] {type(exc).__name__}: {exc}")


def _check_engines() -> None:
    import shutil

    checks = [
        ("psi4", "psi4"),
        ("xtb", "xtb"),
        ("crest", "crest"),
        ("orca", "orca"),
        ("multiwfn", "Multiwfn"),
    ]
    click.echo(f"ChemMaster {__version__} environment check")
    click.echo(f"  ✓ Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    for label, exe in checks:
        path = shutil.which(exe)
        mark = "✓" if path else "⚠"
        line = f"  {mark} {label}: {'OK' if path else 'not found'}"
        if path:
            line += f"  ({path})"
        click.echo(line)


def _interactive_confirm(tool_name: str, args: dict, reason: str) -> bool:
    """Prompt the user to approve a tool call. Returns True if approved."""
    panel = Panel(
        f"[yellow]Tool:[/yellow]    [bold]{tool_name}[/bold]\n"
        f"[yellow]Reason:[/yellow]  {reason}\n"
        f"[yellow]Args:[/yellow]    {json.dumps(args, indent=2, default=str)[:600]}",
        title="Approve agent action?",
        border_style="yellow",
    )
    console.print(panel)
    answer = click.prompt(
        "[A]ccept / [D]ecline (default: Accept)",
        default="A",
        show_default=False,
    ).strip().lower()
    return not answer.startswith("d")


def _write_markdown_report(traj, runs_dir: Path) -> None:
    """Write runs/<task_id>/report.md — a paper-ready summary of the run.

    The report has three sections: header (status / steps / wall time),
    agent summary (the finish payload narrative), and per-step trace
    (tool name + first 200 chars of the observation).
    """
    if traj is None or not traj.task_id:
        return
    task_dir = runs_dir / traj.task_id
    if not task_dir.exists():
        return
    report_path = task_dir / "report.md"

    lines: list[str] = []
    lines.append(f"# ChemMaster run report — `{traj.task_id}`")
    lines.append("")
    lines.append(f"- **Status**: {traj.status}")
    lines.append(f"- **Started**: {traj.started_at}")
    if traj.finished_at:
        lines.append(f"- **Finished**: {traj.finished_at}")
    lines.append(f"- **Steps**: {len(traj.steps)}")
    lines.append("")

    # Pull finish summary if present.
    summary = ""
    key_results: dict | None = None
    if traj.steps:
        last = traj.steps[-1]
        if last.assistant_message and last.assistant_message.tool_calls:
            tc = last.assistant_message.tool_calls[0]
            if tc.name == "finish":
                summary = tc.arguments.get("summary", "")
                key_results = tc.arguments.get("key_results")
    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(summary)
        lines.append("")
    if key_results:
        lines.append("## Key results")
        lines.append("")
        lines.append("| name | value |")
        lines.append("|---|---|")
        for k, v in key_results.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # Per-step trace
    lines.append("## Step trace")
    lines.append("")
    for i, step in enumerate(traj.steps, 1):
        ass = step.assistant_message
        if not ass or not ass.tool_calls:
            lines.append(f"### Step {i}: (no tool call)")
            continue
        for tc in ass.tool_calls:
            lines.append(f"### Step {i}: `{tc.name}`")
            lines.append("")
            args_str = json.dumps(tc.arguments, ensure_ascii=False, default=str)
            if len(args_str) > 400:
                args_str = args_str[:400] + " …(truncated)"
            lines.append(f"**Args**: `{args_str}`")
            lines.append("")
            for tr in step.tool_responses:
                obs = (tr.content or "")[:600]
                ok_mark = "✗" if tr.is_error else "✓"
                lines.append(f"**Result** ({ok_mark}):")
                lines.append("")
                lines.append("```")
                lines.append(obs)
                lines.append("```")
                lines.append("")
            break  # one tool call per step in this report style

    lines.append("---")
    lines.append("")
    lines.append(f"*Generated by ChemMaster {__version__} at "
                 f"{time.strftime('%Y-%m-%d %H:%M:%S')}*")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def _print_summary(traj, runs_dir: Path) -> None:
    """Pretty-print the trajectory result + key numbers + report path."""
    from chemaster.agent.types import ToolMessage

    task_dir = runs_dir / traj.task_id
    style = {
        "completed": "green",
        "failed": "red",
        "waiting_for_input": "yellow",
    }.get(traj.status, "white")
    console.print(Panel(
        f"[bold]Status:[/bold] [{style}]{traj.status}[/{style}]\n"
        f"[bold]Steps:[/bold]  {len(traj.steps)}\n"
        f"[bold]Task ID:[/bold] {traj.task_id}\n"
        f"[bold]Trajectory:[/bold] {task_dir / 'trajectory.json'}",
        title="ChemMaster — Run Summary",
        border_style=style,
    ))

    # Pull finish payload if present.
    if traj.steps:
        last = traj.steps[-1]
        if last.assistant_message and last.assistant_message.tool_calls:
            tc = last.assistant_message.tool_calls[0]
            if tc.name == "finish":
                summary = tc.arguments.get("summary", "")
                key_results = tc.arguments.get("key_results", {})
                if summary:
                    console.print(Panel(summary, title="Agent summary", border_style="cyan"))
                if key_results:
                    table = Table(title="Key results", show_header=True)
                    table.add_column("name")
                    table.add_column("value")
                    for k, v in key_results.items():
                        table.add_row(str(k), str(v))
                    console.print(table)

    if traj.status == "waiting_for_input" and traj.finish_payload:
        qs = traj.finish_payload.get("questions", [])
        for q in qs:
            console.print(f"  [yellow]?[/yellow] {q}")


if __name__ == "__main__":
    main()
