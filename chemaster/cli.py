"""``chemaster`` 命令行入口。

子命令：
- ``chemaster``                 进入 TUI（无参数）
- ``chemaster --version``       打印版本
- ``chemaster --check-engines`` 检测计算软件可用性
- ``chemaster init``            首次配置（写 ~/.chemaster/config.yaml）
- ``chemaster eval <yaml>``     跑标杆 / smoke test
- ``chemaster skills list``     列出 skill
- ``chemaster mcps list``       列出 MCP server
- ``chemaster kb list``         列出知识库条目
- ``chemaster clean``           清理旧 runs
"""

from __future__ import annotations

import sys

import click

from chemaster import __version__


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
        # 默认行为：进 TUI
        from chemaster.tui.app import run_tui
        run_tui()


@main.command()
def init() -> None:
    """首次配置（生成 ~/.chemaster/config.yaml）。Phase 1 实现。"""
    click.echo("Phase 1 TODO: implement chemaster init")


@main.command(name="eval")
@click.argument("yaml_path")
def eval_cmd(yaml_path: str) -> None:
    """跑 benchmark / smoke test。Phase 1+ 实现。"""
    click.echo(f"Phase 1 TODO: run eval for {yaml_path}")


@main.group()
def skills() -> None:
    """Skill 管理。"""


@skills.command(name="list")
def skills_list() -> None:
    """列出已注册 skill。"""
    from pathlib import Path

    base = Path(__file__).parent / "skills"
    for child in sorted(base.iterdir()):
        if child.is_dir() and (child / "SKILL.md").exists():
            click.echo(child.name)


@main.group()
def mcps() -> None:
    """MCP server 管理。"""


@mcps.command(name="list")
def mcps_list() -> None:
    """列出已注册 MCP server。"""
    from chemaster.mcp import list_servers

    for name in list_servers():
        click.echo(name)


@main.group()
def kb() -> None:
    """知识库管理。"""


@kb.command(name="list")
def kb_list() -> None:
    """列出 kb/rules 下的规则文件。"""
    from pathlib import Path

    base = Path(__file__).parent / "kb" / "rules"
    for child in sorted(base.iterdir()):
        if child.is_file():
            click.echo(child.name)


def _check_engines() -> None:
    """检测可用计算引擎。"""
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


if __name__ == "__main__":
    main()
