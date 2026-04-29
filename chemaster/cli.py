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
@click.pass_context
def main(ctx: click.Context, version: bool, check_engines: bool) -> None:
    """ChemMaster — AI agent for computational chemistry."""
    if version:
        click.echo(f"chemaster {__version__}")
        return
    if check_engines:
        _check_engines()
        return
    if ctx.invoked_subcommand is None:
        # Default: TUI (when implemented). Until then, show help.
        try:
            from chemaster.tui.app import run_tui
            run_tui()
        except (ImportError, NotImplementedError):
            click.echo(ctx.get_help())


# ══════════════════════════════════════════════════════════════════════════════
# `run` — the headline V2 command
# ══════════════════════════════════════════════════════════════════════════════


@main.command()
@click.argument("intent")
@click.option("--runs-dir", default="./runs", show_default=True,
              help="Where to write per-task artefacts.")
@click.option("--max-turns", type=int, default=30, show_default=True,
              help="Maximum agent loop iterations.")
@click.option("--llm-provider", type=click.Choice(["mock", "anthropic", "minimax"]),
              default=None,
              help="LLM provider. Defaults to 'anthropic' (if ANTHROPIC_API_KEY) "
                   "→ 'minimax' (if MINIMAX_API_KEY) → 'mock' (no real LLM).")
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

    try:
        traj = agent.run(TaskInstance(description=intent))
    except Exception as exc:
        click.secho(f"Agent crashed: {type(exc).__name__}: {exc}", fg="red", err=True)
        sys.exit(3)

    _print_summary(traj, agent_cfg.runs_dir)


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
# init / eval (legacy placeholders)
# ══════════════════════════════════════════════════════════════════════════════


@main.command()
def init() -> None:
    """First-time configuration scaffold (placeholder)."""
    click.echo("chemaster init: scaffold not yet implemented in V2.")
    click.echo("For now, just `export ANTHROPIC_API_KEY=…` and run `chemaster run …`.")


@main.command(name="eval")
@click.argument("yaml_path")
def eval_cmd(yaml_path: str) -> None:
    """Run a benchmark spec (legacy placeholder)."""
    click.echo(f"chemaster eval {yaml_path}: benchmark runner not yet wired into V2.")


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


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
