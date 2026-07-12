"""FastAPI Web 前端的端点测试。

web/app.py 此前零测试——正因如此漏过一个"提交任何任务必崩"级 bug
（`TaskInstance(intent=)` 字段不存在 / `result.steps_used` 不存在 /
`_finish_payload` 为 None 时 `.get()` 崩）。这些用例把崩溃路径钉死，
并覆盖 9 个端点的契约与 mock agent 端到端。

依赖 fastapi（web extra）；未安装时整文件跳过。
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("fastapi", reason="web extra not installed (pip install -e '.[web]')")

from fastapi.testclient import TestClient

from chemaster.web.app import create_app

# ──────────────────────────────────────────────────────────────────────────────
# 轻量假 agent：复刻 _run_agent_blocking 依赖的真实接口，避免真跑 psi4
# ──────────────────────────────────────────────────────────────────────────────


class _FakeConfig:
    def __init__(self):
        self.confirm_callback = None
        self.recommend_callback = None


class _FakeAssistant:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeStep:
    def __init__(self, assistant_message, tool_responses=None):
        self.assistant_message = assistant_message
        self.tool_responses = tool_responses or []


class _FakeTraj:
    def __init__(self, status, finish_payload, steps):
        self.status = status
        self.finish_payload = finish_payload
        self.steps = steps


class _FakeTool:
    description = "a fake tool for testing"


class _FakeRegistry:
    def names(self):
        return ["calc_psi4_single_point", "finish"]

    def get(self, name):
        return _FakeTool()


class _FakeAgent:
    """Mimics ChemAgent's surface used by web/app.py."""

    def __init__(self, *, status="completed", finish_payload=None, n_steps=2):
        self.config = _FakeConfig()
        self.tools = _FakeRegistry()
        self._status = status
        self._finish_payload = finish_payload
        self._n_steps = n_steps

    def run(self, task, on_step=None):
        # task must have been built as TaskInstance(description=..., task_id=...)
        # — if web/app.py regresses to intent=, TaskInstance() raises TypeError
        # inside the worker thread and the task ends up 'failed'.
        assert task.description  # description populated
        steps = []
        for i in range(self._n_steps):
            am = _FakeAssistant(content=f"step {i}")
            step = _FakeStep(am, tool_responses=[])
            steps.append(step)
            if on_step:
                on_step(step, i + 1, 30)
        return _FakeTraj(self._status, self._finish_payload, steps)


def _poll_until_done(client, task_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/task/{task_id}").json()
        if r["status"] in ("done", "failed", "waiting_user"):
            return r
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not settle within {timeout}s")


@pytest.fixture
def fake_agent_factory():
    return lambda: _FakeAgent(finish_payload={"summary": "all done",
                                              "key_results": {"E": "-1.17 Ha"}})


@pytest.fixture
def client(fake_agent_factory):
    return TestClient(create_app(agent_factory=fake_agent_factory))


@pytest.fixture
def display_only_client():
    return TestClient(create_app(agent_factory=None))


# ──────────────────────────────────────────────────────────────────────────────
# 静态 / 只读端点
# ──────────────────────────────────────────────────────────────────────────────


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "ChemMaster" in r.text
    assert "text/html" in r.headers["content-type"]


def test_engines_endpoint_shape(client):
    r = client.get("/api/engines")
    assert r.status_code == 200
    engines = r.json()["engines"]
    assert engines and all({"name", "available", "path"} <= set(e) for e in engines)
    # psi4 状态必须与"当前解释器可 import"一致（CI runner 无 psi4 也要过）
    import importlib.util
    expected = importlib.util.find_spec("psi4") is not None
    psi4 = next(e for e in engines if e["name"] == "psi4")
    assert psi4["available"] is expected


def test_skills_endpoint_lists_dirs(client):
    r = client.get("/api/skills")
    assert r.status_code == 200
    skills = r.json()["skills"]
    assert "opt-freq" in skills and "tddft" in skills


def test_tools_endpoint_uses_agent_registry(client):
    r = client.get("/api/tools")
    assert r.status_code == 200
    names = [t["name"] for t in r.json()["tools"]]
    assert "calc_psi4_single_point" in names


def test_tools_endpoint_display_only(display_only_client):
    r = display_only_client.get("/api/tools")
    assert r.status_code == 200
    assert r.json()["tools"] == []


def test_benchmarks_endpoint_aggregates(client):
    r = client.get("/api/benchmarks")
    assert r.status_code == 200
    # engineering_metrics/*.json exist in the repo → key present
    assert "engineering" in r.json()


# ──────────────────────────────────────────────────────────────────────────────
# 任务提交 —— 崩溃回归 + 端到端
# ──────────────────────────────────────────────────────────────────────────────


def test_run_rejects_empty_intent(client):
    r = client.post("/api/run", json={"intent": "   "})
    assert r.status_code == 400


def test_run_completes_without_crashing(client):
    """回归：web 提交任务此前必崩（TaskInstance(intent=) / steps_used /
    None.get()）。这里跑通整条 _run_agent_blocking 并核对结果结构。"""
    r = client.post("/api/run", json={"intent": "compute H2 energy"})
    assert r.status_code == 200
    task_id = r.json()["task_id"]

    final = _poll_until_done(client, task_id)
    assert final["status"] == "done", final
    result = final["result"]
    assert result["agent_status"] == "completed"
    assert result["summary"] == "all done"
    assert result["key_results"] == {"E": "-1.17 Ha"}
    assert result["n_steps"] == 2
    assert result["no_finish_payload"] is False


def test_run_without_finish_payload_falls_back_to_last_text(client):
    """Agent 未调 finish 时（finish_payload=None）不应崩，且回退取
    最后一条 assistant 文本作为 summary。"""
    app = create_app(agent_factory=lambda: _FakeAgent(finish_payload=None, n_steps=3))
    c = TestClient(app)
    r = c.post("/api/run", json={"intent": "do something"})
    task_id = r.json()["task_id"]
    final = _poll_until_done(c, task_id)
    assert final["status"] == "done"
    assert final["result"]["no_finish_payload"] is True
    assert final["result"]["summary"] == "step 2"   # last assistant content


def test_run_events_stream_populated(client):
    r = client.post("/api/run", json={"intent": "compute H2 energy"})
    task_id = r.json()["task_id"]
    _poll_until_done(client, task_id)
    events = client.get(f"/api/task/{task_id}/events").json()["events"]
    assert any(e["type"] == "narration" for e in events)


def test_run_display_only_marks_done(display_only_client):
    r = display_only_client.post("/api/run", json={"intent": "anything"})
    assert r.status_code == 200
    assert r.json()["status"] == "done"


def test_task_not_found_returns_404(client):
    assert client.get("/api/task/nonexistent").status_code == 404
    assert client.get("/api/task/nonexistent/events").status_code == 404
    assert client.post("/api/task/nonexistent/respond", json={}).status_code == 404


def test_agent_exception_marks_failed_not_500(client):
    """agent.run 抛异常时任务标记 failed，HTTP 层不 500。"""
    class _BoomAgent(_FakeAgent):
        def run(self, task, on_step=None):
            raise RuntimeError("engine exploded")

    app = create_app(agent_factory=lambda: _BoomAgent())
    c = TestClient(app)
    task_id = c.post("/api/run", json={"intent": "boom"}).json()["task_id"]
    final = _poll_until_done(c, task_id)
    assert final["status"] == "failed"
    assert "engine exploded" in final["result"]["error"]


# ──────────────────────────────────────────────────────────────────────────────
# confirm / recommend 交互路径
# ──────────────────────────────────────────────────────────────────────────────


def test_confirm_card_flow(client):
    """提交一个会触发 confirm 卡片的任务，respond 后任务继续到 done。"""
    class _ConfirmAgent(_FakeAgent):
        def run(self, task, on_step=None):
            approved = self.config.confirm_callback(
                "calc_psi4_optimize", {"method": "b3lyp"}, "long-running"
            )
            fp = {"summary": "approved" if approved else "declined"}
            return _FakeTraj("completed", fp, [_FakeStep(_FakeAssistant("x"))])

    app = create_app(agent_factory=lambda: _ConfirmAgent())
    c = TestClient(app)
    task_id = c.post("/api/run", json={"intent": "optimize"}).json()["task_id"]

    # wait for the card to appear
    st = _poll_until_done(c, task_id)
    assert st["status"] == "waiting_user"
    assert st["pending_card"]["mode"] == "confirm"

    c.post(f"/api/task/{task_id}/respond", json={"approved": True})
    final = _poll_until_done(c, task_id)
    assert final["status"] == "done"
    assert final["result"]["summary"] == "approved"
