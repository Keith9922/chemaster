"""``chemaster`` 命令行入口。

子命令：
- ``chemaster``                 进入 TUI（无参数）
- ``chemaster --version``       打印版本
- ``chemaster --check-engines`` 检测计算软件可用性
- ``chemaster init``            首次配置（写 ~/.chemaster/config.yaml）
- ``chemaster eval <yaml>``     跑 benchmark / smoke test
- ``chemaster skills list``     列出 skill
- ``chemaster mcps list``       列出 MCP server
- ``chemaster kb list``         列出知识库条目
- ``chemaster clean``           清理旧 runs
- ``chemaster report <task>``   重新生成 runs/<task>/report.md
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

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


# ────────────────────────────────────────────────────────────────────────
# init
# ────────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--force", is_flag=True, help="Overwrite existing config.")
@click.option("--config-dir", type=click.Path(),
              help="Override config directory (default: ~/.chemaster).")
def init(force: bool, config_dir: str | None) -> None:
    """生成 ~/.chemaster/config.yaml。"""
    from chemaster import config as _cfg

    dst = Path(config_dir) / "config.yaml" if config_dir else None
    try:
        out = _cfg.init_config(force=force, dst=dst)
    except FileExistsError as e:
        click.echo(f"⚠ {e}", err=True)
        click.echo("Use --force to overwrite.", err=True)
        sys.exit(2)
    except FileNotFoundError as e:
        click.echo(f"✗ {e}", err=True)
        sys.exit(1)

    click.echo(f"✓ wrote {out}")
    click.echo("\n下一步：编辑 config.yaml 填入 LLM API key（或用 ANTHROPIC_API_KEY 环境变量）。")


# ────────────────────────────────────────────────────────────────────────
# eval
# ────────────────────────────────────────────────────────────────────────

@main.command(name="eval")
@click.argument("yaml_path", type=click.Path(exists=True))
@click.option("--runs-dir", type=click.Path(), default="./runs", show_default=True)
def eval_cmd(yaml_path: str, runs_dir: str) -> None:
    """跑一份 benchmark YAML（如 benchmarks/tadf-literature/4CzIPN.yaml）。

    Phase 1 极简语义：YAML 里有 ``user_intent`` 字段就把它送给 Planner
    跑一遍 opt+freq；其它字段（literature_values 等）写进 report.md。
    """
    import yaml

    from chemaster.agent.confirmation import ConfirmationLoop
    from chemaster.agent.executor import Executor
    from chemaster.agent.planner import Planner

    spec = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8")) or {}
    intent = spec.get("user_intent") or f"算 {spec.get('name', 'molecule')} 的能量"

    click.echo(f"▶ Eval: {yaml_path}")
    click.echo(f"  intent: {intent}")

    plan = Planner().create_plan(intent)
    approved = ConfirmationLoop().approve(plan, user_edits=["auto-eval"])
    executor = Executor(runs_dir=runs_dir)
    t0 = time.time()
    result = executor.run(approved)
    elapsed = time.time() - t0

    click.echo(f"  task_dir: {result['task_dir']}")
    click.echo(f"  ok: {result['ok']}  steps={result['n_steps_completed']}/{len(plan.steps)}  "
               f"elapsed={elapsed:.1f}s")
    if result.get("report_path"):
        click.echo(f"  report: {result['report_path']}")
    sys.exit(0 if result["ok"] else 1)


# ────────────────────────────────────────────────────────────────────────
# skills / mcps / kb
# ────────────────────────────────────────────────────────────────────────

@main.group()
def skills() -> None:
    """Skill 管理。"""


@skills.command(name="list")
def skills_list() -> None:
    """列出已注册 skill。"""
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
    base = Path(__file__).parent / "kb" / "rules"
    for child in sorted(base.iterdir()):
        if child.is_file() and child.suffix in (".yaml", ".yml", ".md"):
            click.echo(child.name)


# ────────────────────────────────────────────────────────────────────────
# clean
# ────────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--runs-dir", type=click.Path(), default="./runs", show_default=True)
@click.option("--older-than", default="30d", show_default=True,
              help="Delete runs older than this. Format: '7d', '24h', '30d'.")
@click.option("--dry-run", is_flag=True, help="Print what would be removed without deleting.")
def clean(runs_dir: str, older_than: str, dry_run: bool) -> None:
    """清理旧 runs/ 任务产物。"""
    import shutil

    seconds = _parse_duration(older_than)
    cutoff = time.time() - seconds

    rd = Path(runs_dir)
    if not rd.exists():
        click.echo(f"runs dir {rd} does not exist; nothing to clean.")
        return

    targets = [
        p for p in rd.iterdir()
        if p.is_dir() and p.stat().st_mtime < cutoff
    ]
    if not targets:
        click.echo(f"No runs older than {older_than} in {rd}.")
        return

    for p in targets:
        age_days = (time.time() - p.stat().st_mtime) / 86400
        if dry_run:
            click.echo(f"[dry-run] would remove {p}  (age={age_days:.1f}d)")
        else:
            shutil.rmtree(p)
            click.echo(f"removed {p}  (age={age_days:.1f}d)")


def _parse_duration(s: str) -> float:
    """'7d' → 7*86400；'24h' → 24*3600；'90m' → 90*60；纯数字按秒。"""
    s = s.strip()
    if not s:
        raise click.BadParameter("--older-than 不能为空")
    unit = s[-1].lower()
    if unit.isdigit():
        return float(s)
    try:
        n = float(s[:-1])
    except ValueError as e:
        raise click.BadParameter(f"无法解析 {s!r}") from e
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit, 86400)


# ────────────────────────────────────────────────────────────────────────
# report
# ────────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("task_dir", type=click.Path(exists=True))
def report(task_dir: str) -> None:
    """重新生成指定 task_dir 的 report.md。"""
    from chemaster.agent.reporter import generate_report

    out = generate_report(task_dir)
    click.echo(f"✓ {out}")


# ────────────────────────────────────────────────────────────────────────
# engines check
# ────────────────────────────────────────────────────────────────────────

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
    click.echo(
        f"  ✓ Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    for label, exe in checks:
        path = shutil.which(exe)
        mark = "✓" if path else "⚠"
        line = f"  {mark} {label}: {'OK' if path else 'not found'}"
        if path:
            line += f"  ({path})"
        click.echo(line)


if __name__ == "__main__":
    main()
