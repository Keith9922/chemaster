"""Textual TUI 的 pilot 测试。

tui/app.py 此前零测试——曾漏过 `TaskInstance(intent=)` 字段 bug（每次
提交任务必崩，界面不崩但任务全失败）。这里用 Textual 的 run_test() 驱动
真实事件循环，覆盖：启动渲染、任务提交走 mock agent、斜杠命令、
confirm/recommend 卡片交互、引擎面板。

依赖 textual（tui extra）；未安装时整文件跳过。
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual", reason="tui extra not installed (pip install -e '.[tui]')")

from chemaster.tui.app import ChemMasterApp

# ──────────────────────────────────────────────────────────────────────────────
# 轻量假 agent —— 复刻 _run_agent_task 依赖的接口
# ──────────────────────────────────────────────────────────────────────────────


class _FakeRegistry:
    def names(self):
        return ["calc_psi4_single_point", "finish", "kb_search"]


class _FakeConfig:
    confirm_callback = None
    recommend_callback = None


class _FakeAssistant:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeStep:
    def __init__(self, content="working"):
        self.assistant_message = _FakeAssistant(content)
        self.tool_responses = []


class _FakeTraj:
    def __init__(self, status="completed"):
        self.status = status


class _FakeAgent:
    def __init__(self, status="completed", summary="done"):
        self.tools = _FakeRegistry()
        self.config = _FakeConfig()
        self._status = status
        self._finish_payload = {"summary": summary} if summary else None

    def run(self, task, on_step=None):
        # regression guard: TUI must build TaskInstance(description=...)
        assert task.description
        if on_step:
            on_step(_FakeStep("thinking"), 1, 30)
        return _FakeTraj(self._status)


async def _submit(pilot, app, text):
    """把文本填进输入框并回车，触发 on_input_submitted。"""
    from textual.widgets import Input
    inp = app.query_one("#cmd_input", Input)
    inp.value = text
    inp.focus()
    await pilot.press("enter")
    await pilot.pause()


# ──────────────────────────────────────────────────────────────────────────────
# 启动 / 渲染
# ──────────────────────────────────────────────────────────────────────────────


async def test_app_starts_and_renders_panels():
    app = ChemMasterApp(agent=_FakeAgent())
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import Input, RichLog, Static
        # all three side panels + chat + input composed successfully
        assert app.query_one("#task_panel", Static) is not None
        assert app.query_one("#recent_panel", Static) is not None
        assert app.query_one("#engine_panel", Static) is not None
        assert app.query_one("#chat", RichLog) is not None
        assert app.query_one("#cmd_input", Input) is not None
        # psi4 importable in test env → shows up in the ready list
        assert "psi4" in app._render_engine_status()


async def test_engine_panel_uses_shared_probe():
    app = ChemMasterApp(agent=None)
    async with app.run_test():
        assert "ready" in app._render_engine_status()


# ──────────────────────────────────────────────────────────────────────────────
# 任务提交（回归：不再崩）
# ──────────────────────────────────────────────────────────────────────────────


async def test_submit_task_runs_agent_and_records_history():
    app = ChemMasterApp(agent=_FakeAgent(summary="H2 = -1.17 Ha"))
    async with app.run_test() as pilot:
        await _submit(pilot, app, "compute H2 energy")
        # the agent runs in a worker task stored on the app
        await app._agent_task
        await pilot.pause()
        assert app._task_history
        assert app._task_history[-1]["ok"] is True
        assert app._task_history[-1]["task"] == "compute H2 energy"


async def test_submit_failing_task_marks_history_not_ok():
    class _BoomAgent(_FakeAgent):
        def run(self, task, on_step=None):
            raise RuntimeError("SCF diverged")

    app = ChemMasterApp(agent=_BoomAgent())
    async with app.run_test() as pilot:
        await _submit(pilot, app, "break it")
        await app._agent_task
        await pilot.pause()
        assert app._task_history[-1]["ok"] is False


async def test_display_only_mode_no_agent():
    app = ChemMasterApp(agent=None)
    async with app.run_test() as pilot:
        await _submit(pilot, app, "hello")
        await app._agent_task
        await pilot.pause()
        assert app._task_history[-1]["ok"] is False


async def test_empty_input_is_ignored():
    app = ChemMasterApp(agent=_FakeAgent())
    async with app.run_test() as pilot:
        await _submit(pilot, app, "   ")
        await pilot.pause()
        assert app._task_history == []
        assert not hasattr(app, "_agent_task")


# ──────────────────────────────────────────────────────────────────────────────
# 斜杠命令
# ──────────────────────────────────────────────────────────────────────────────


async def test_slash_clear_resets_chat():
    app = ChemMasterApp(agent=_FakeAgent())
    async with app.run_test() as pilot:
        from textual.widgets import RichLog
        await _submit(pilot, app, "/help")
        chat = app.query_one("#chat", RichLog)
        assert chat.lines  # help wrote something
        await _submit(pilot, app, "/clear")
        assert not chat.lines


async def test_slash_quit_exits_app():
    app = ChemMasterApp(agent=_FakeAgent())
    async with app.run_test() as pilot:
        await _submit(pilot, app, "/quit")
        await pilot.pause()
    # run_test context exits cleanly → app.exit() was honoured
    assert app._return_value is None


async def test_unknown_command_does_not_run_agent():
    app = ChemMasterApp(agent=_FakeAgent())
    async with app.run_test() as pilot:
        await _submit(pilot, app, "/bogus")
        await pilot.pause()
        assert app._task_history == []


# ──────────────────────────────────────────────────────────────────────────────
# confirm / recommend 卡片交互
# ──────────────────────────────────────────────────────────────────────────────


async def test_confirm_card_approve():
    app = ChemMasterApp(agent=_FakeAgent())
    async with app.run_test() as pilot:
        fut = app.show_confirm_card("calc_psi4_optimize", {"m": "b3lyp"}, "long-running")
        assert app._pending_card and app._pending_card["mode"] == "confirm"
        await _submit(pilot, app, "a")
        result = await asyncio.wait_for(fut, timeout=2)
        assert result == {"approved": True}
        assert app._pending_card is None


async def test_recommend_card_modify():
    app = ChemMasterApp(agent=_FakeAgent())
    async with app.run_test() as pilot:
        fut = app.show_recommend_card({
            "decision": "选泛函", "recommendation": "B3LYP", "reasoning": "常规",
        })
        await _submit(pilot, app, "m ωB97X-D")
        result = await asyncio.wait_for(fut, timeout=2)
        assert result["status"] == "modify"
        assert "ωB97X-D" in result["modified_value"]


async def test_recommend_card_cancel():
    app = ChemMasterApp(agent=_FakeAgent())
    async with app.run_test() as pilot:
        fut = app.show_recommend_card({"decision": "d", "recommendation": "r"})
        await _submit(pilot, app, "no thanks")
        result = await asyncio.wait_for(fut, timeout=2)
        assert result["status"] == "cancel"
