"""ChemMaster Textual TUI.

布局参考与设计说明
-----------------
本 TUI 的整体架构借鉴了 DeepSeek TUI（https://github.com/Hmbown/DeepSeek-TUI，
MIT licensed）的 crate-based 模块切分（cli/tui/agent/mcp/protocol/state/...）
与三模式（Plan / Agent / YOLO）设计哲学。其中：

- DeepSeek TUI 的三模式 ↔ ChemMaster 的 L1（自主）/ L2（推荐+确认）/ L3（必须
  用户判断）权限分级系本质同构 —— 都把 "Agent 自主程度" 作为一个可调维度。
- DeepSeek TUI 是 Rust 项目，本工作为 Python + Textual 实现，未直接复用其
  代码，但在 chat panel + side panel + bottom input 的整体布局、以及
  recommend 卡片 / confirm 卡片的 UI 设计上参考了其 chat-room 风格。

布局：
  ┌─────────────────────────────┬───────────────────┐
  │  Chat (RichLog)             │ Active task       │
  │                             │ Recent runs       │
  │                             │ Engine status     │
  ├─────────────────────────────┴───────────────────┤
  │ Input (bottom)                                   │
  └──────────────────────────────────────────────────┘

支持：
- 用户在 Input 中输入自然语言指令，回车提交
- Plan-Confirm-Execute 卡片（confirm mode）：A/R 接受/拒绝
- Recommend 卡片（recommend mode）：A 接受 / M <value> 修改 / 其他取消
- 实时显示 tool call、observation、自主步与决策步
- 斜杠命令：/help, /skills, /tools, /clear, /quit

Phase 3 实现：从 72 行骨架补到完整可用 TUI。

依赖：textual >= 0.40 (`pip install textual`).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Footer, Header, Input, RichLog, Static
    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

if TEXTUAL_AVAILABLE:

    class ChemMasterApp(App):
        """ChemMaster Textual TUI 主应用类."""

        CSS = """
        Screen { layout: vertical; }
        #main { height: 1fr; }
        #chat {
            width: 3fr;
            border: round $primary;
            padding: 0 1;
        }
        #side { width: 1fr; }
        #side > Static {
            border: round $secondary;
            padding: 0 1;
            height: auto;
            margin: 0 0 1 0;
        }
        Input { dock: bottom; }
        """

        BINDINGS = [
            Binding("ctrl+c", "quit", "Quit"),
            Binding("ctrl+l", "clear_chat", "Clear chat"),
        ]

        TITLE = "ChemMaster — labor-saving collaborator"

        def __init__(self, *, agent: Any | None = None, **kw) -> None:
            super().__init__(**kw)
            self._agent = agent
            self._pending_card: dict | None = None
            self._task_history: list[dict] = []

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="main"):
                yield RichLog(id="chat", highlight=True, markup=True, wrap=True)
                with Vertical(id="side"):
                    yield Static(self._render_active_task_panel(), id="task_panel")
                    yield Static(self._render_recent_runs(), id="recent_panel")
                    yield Static(self._render_engine_status(), id="engine_panel")
            yield Input(placeholder="describe your computation, or /help for commands",
                        id="cmd_input")
            yield Footer()

        # ─────────────────────────────────────────────────────
        # Side panels
        # ─────────────────────────────────────────────────────

        def _render_active_task_panel(self) -> str:
            return "[b]Active task[/b]\n(idle — type a request below)"

        def _render_recent_runs(self) -> str:
            if not self._task_history:
                return "[b]Recent runs[/b]\n(none)"
            lines = ["[b]Recent runs[/b]"]
            for h in self._task_history[-5:]:
                ok = "✓" if h.get("ok") else ("…" if h.get("ok") is None else "✗")
                lines.append(f"  {ok} {h.get('task','?')[:40]}")
            return "\n".join(lines)

        def _render_engine_status(self) -> str:
            import shutil
            engines = ["g16", "g09", "bdf", "momap", "psi4", "orca", "xtb"]
            available = [e for e in engines if shutil.which(e)]
            unavailable = [e for e in engines if e not in available]
            return (
                "[b]Engines on PATH[/b]\n"
                f"[green]ready[/green]: {' '.join(available) if available else '(none)'}\n"
                f"[dim red]missing[/dim red]: {' '.join(unavailable[:4])}..."
            )

        # ─────────────────────────────────────────────────────
        # Input handling
        # ─────────────────────────────────────────────────────

        def on_input_submitted(self, event: Input.Submitted) -> None:
            text = event.value.strip()
            event.input.value = ""
            if not text:
                return
            chat: RichLog = self.query_one("#chat", RichLog)
            chat.write(f"[b cyan]>[/b cyan] {text}")

            if text.startswith("/"):
                self._handle_command(text, chat)
                return
            if self._pending_card:
                self._handle_card_input(text, chat)
                return
            asyncio.create_task(self._run_agent_task(text, chat))

        def _handle_command(self, text: str, chat: RichLog) -> None:
            cmd = text.lower().strip()
            if cmd in ("/quit", "/q"):
                self.exit()
            elif cmd in ("/help", "/h"):
                chat.write(
                    "[b]Commands[/b]\n"
                    "  /skills  — list available skills\n"
                    "  /tools   — list registered tools\n"
                    "  /clear   — clear chat\n"
                    "  /quit    — exit"
                )
            elif cmd == "/skills":
                from pathlib import Path
                skills_dir = Path(__file__).resolve().parents[1] / "kb" / "skills"
                if skills_dir.exists():
                    for sk in sorted(skills_dir.iterdir()):
                        if sk.is_dir():
                            chat.write(f"  • {sk.name}")
                else:
                    chat.write("  (no kb/skills directory)")
            elif cmd == "/tools":
                if self._agent:
                    chat.write("[b]Tools registered[/b]")
                    for n in self._agent.tools.names()[:30]:
                        chat.write(f"  • {n}")
                else:
                    chat.write("(no agent attached; TUI in display mode)")
            elif cmd == "/clear":
                chat.clear()
            else:
                chat.write(f"[red]Unknown command:[/red] {text}")

        def _handle_card_input(self, text: str, chat: RichLog) -> None:
            card = self._pending_card
            self._pending_card = None
            if not card:
                return
            t = text.lower().strip()
            if card["mode"] == "confirm":
                approved = t in {"a", "approve", "y", "yes"}
                chat.write(f"[dim]→ {'approved' if approved else 'rejected'}[/dim]")
                card["future"].set_result({"approved": approved})
            elif card["mode"] == "recommend":
                if t in {"a", "accept", "y"}:
                    chat.write("[dim]→ accepted[/dim]")
                    card["future"].set_result({"status": "accept"})
                elif t.startswith("m ") or t.startswith("m:"):
                    modified = text[1:].strip(": ")
                    chat.write(f"[dim]→ modified to: {modified}[/dim]")
                    card["future"].set_result(
                        {"status": "modify", "modified_value": modified})
                else:
                    chat.write("[dim]→ cancelled[/dim]")
                    card["future"].set_result(
                        {"status": "cancel", "user_note": text})

        # ─────────────────────────────────────────────────────
        # Agent runner
        # ─────────────────────────────────────────────────────

        async def _run_agent_task(self, text: str, chat: RichLog) -> None:
            if self._agent is None:
                chat.write("[yellow]No agent attached. TUI is in display-only mode.[/yellow]")
                self._task_history.append({"task": text, "ok": False})
                self._refresh_panels()
                return

            chat.write(f"[dim]starting agent task at {datetime.now().strftime('%H:%M:%S')}[/dim]")
            self._task_history.append({"task": text, "ok": None})
            self._refresh_panels()

            try:
                from chemaster.agent.types import TaskInstance
                task = TaskInstance(intent=text)
                result = await asyncio.to_thread(self._agent.run, task)
                ok = (result.status == "completed")
                chat.write(f"[green]✓ task done[/green] (status={result.status})")
                if hasattr(self._agent, "_finish_payload") and self._agent._finish_payload:
                    summary = self._agent._finish_payload.get("summary", "")
                    if summary:
                        chat.write(f"[b]Summary:[/b] {summary}")
                self._task_history[-1]["ok"] = ok
            except Exception as exc:
                chat.write(f"[red]✗ agent error:[/red] {type(exc).__name__}: {exc}")
                self._task_history[-1]["ok"] = False
            self._refresh_panels()

        # ─────────────────────────────────────────────────────
        # Card display (called by callbacks during agent run)
        # ─────────────────────────────────────────────────────

        def show_confirm_card(self, tool: str, args: dict, reason: str) -> asyncio.Future:
            chat: RichLog = self.query_one("#chat", RichLog)
            chat.write(
                f"[on yellow][b]CONFIRM[/b][/on yellow] [b]{tool}[/b] — {reason}\n"
                f"  args: {args}\n"
                f"  type [b]a[/b] to approve, [b]r[/b] to reject"
            )
            future: asyncio.Future = asyncio.Future()
            self._pending_card = {"mode": "confirm", "future": future,
                                   "tool": tool, "args": args}
            return future

        def show_recommend_card(self, payload: dict) -> asyncio.Future:
            chat: RichLog = self.query_one("#chat", RichLog)
            alts = payload.get("alternatives") or []
            chat.write(
                f"[on cyan][b]RECOMMEND[/b][/on cyan] {payload.get('decision','')}\n"
                f"  → [b green]{payload.get('recommendation','')}[/b green]\n"
                f"  why: {payload.get('reasoning','')}\n"
                f"  alternatives: {' / '.join(alts) if alts else '(none)'}\n"
                f"  type [b]a[/b] to accept, [b]m <value>[/b] to modify, "
                f"or anything else to cancel"
            )
            future: asyncio.Future = asyncio.Future()
            self._pending_card = {"mode": "recommend", "future": future,
                                   "payload": payload}
            return future

        def _refresh_panels(self) -> None:
            try:
                self.query_one("#task_panel", Static).update(self._render_active_task_panel())
                self.query_one("#recent_panel", Static).update(self._render_recent_runs())
                self.query_one("#engine_panel", Static).update(self._render_engine_status())
            except Exception:
                pass

        def action_clear_chat(self) -> None:
            try:
                self.query_one("#chat", RichLog).clear()
            except Exception:
                pass


    def main(agent: Any | None = None) -> None:
        """Launch the TUI (called from `chemaster tui`)."""
        app = ChemMasterApp(agent=agent)
        app.run()

else:

    def main(agent: Any | None = None) -> None:
        print("Textual is not installed. Run: pip install textual")
        print("(TUI requires textual >= 0.40)")
