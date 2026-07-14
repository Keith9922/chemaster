"""权限分级（policy.yaml → recommend 流程）的接线测试。

覆盖 v3.0 的三级语义在 agent loop 里的真实行为：
- L1：policy 把 decision_class 降级为自主 → 静默接受，不调 callback，
      authority 记为 agent，审计照记。
- L2：默认 → callback 呈卡片（accept / modify / cancel）。
- L3：无 recommend 通道时不允许自动接受 → 升级 ask_user，任务挂起。
"""

from __future__ import annotations

from pathlib import Path

from chemaster.agent.agent import AgentConfig, BaseAgent
from chemaster.agent.llm_client import MockLLM, stub_assistant_message, stub_tool_call
from chemaster.agent.policy import Policy, load_policy
from chemaster.agent.tool_registry import ToolRegistry
from chemaster.agent.types import TaskInstance


def _recommend_call(decision_class: str):
    return stub_tool_call("recommend", {
        "decision": "选择泛函",
        "recommendation": "B3LYP-D3(BJ)",
        "reasoning": "常规有机小分子基态",
        "decision_class": decision_class,
    })


def _agent(policy: Policy, responses, tmp_path: Path, recommend_callback=None):
    llm = MockLLM(responses=responses)
    return BaseAgent(
        llm=llm,
        tools=ToolRegistry(),
        config=AgentConfig(
            max_turns=4,
            runs_dir=tmp_path / "runs",
            policy=policy,
            recommend_callback=recommend_callback,
        ),
    )


def _finish():
    return stub_assistant_message("", [stub_tool_call("finish", {"summary": "done"})])


# ── policy 解析 ───────────────────────────────────────────────────────────────


def test_load_policy_writes_and_parses_default(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEMASTER_POLICY", str(tmp_path / "policy.yaml"))
    policy = load_policy()
    assert (tmp_path / "policy.yaml").exists()
    assert policy.level_for_decision("method") == "L2"
    assert policy.level_for_decision("multiplicity") == "L3"
    assert policy.level_for_decision("unheard_of_class") == "L2"  # default
    assert policy.is_silent_recovery("network_retry")


def test_load_policy_respects_user_overrides(tmp_path, monkeypatch):
    p = tmp_path / "policy.yaml"
    p.write_text("default: L2\ndecisions:\n  functional: L1\n", encoding="utf-8")
    monkeypatch.setenv("CHEMASTER_POLICY", str(p))
    policy = load_policy()
    assert policy.level_for_decision("functional") == "L1"


# ── L1：降级为自主 → 静默接受 ────────────────────────────────────────────────


def test_l1_demotion_auto_accepts_without_callback_prompt(tmp_path):
    policy = Policy(default_level="L2", decisions={"functional": "L1"})
    calls: list[dict] = []

    def cb(payload):
        calls.append(payload)
        return {"status": "cancel"}  # 如被调用会取消 → 用于证明未被调用

    agent = _agent(
        policy,
        responses=[
            stub_assistant_message("", [_recommend_call("functional")]),
            _finish(),
        ],
        tmp_path=tmp_path,
        recommend_callback=cb,
    )
    traj = agent.run(TaskInstance(description="test L1"))

    assert calls == [], "L1 决策不应打扰用户（callback 不应被调用）"
    assert traj.status == "completed"
    rec = traj.meta["recommendations"]
    assert rec["accepted"] == 1
    assert rec["log"][0]["level"] == "L1"
    # authority 记为 agent（自主步）
    tool_msgs = [m for s in traj.steps for m in s.tool_responses
                 if m.name == "recommend"]
    assert tool_msgs[0].meta["decision_authority"] == "agent"


# ── L2：默认 → callback 决定 ─────────────────────────────────────────────────


def test_l2_callback_receives_level_and_decides(tmp_path):
    policy = Policy(default_level="L2", decisions={"functional": "L2"})
    seen: list[dict] = []

    def cb(payload):
        seen.append(payload)
        return {"status": "modify", "modified_value": "ωB97X-D",
                "user_note": "CT 态"}

    agent = _agent(
        policy,
        responses=[
            stub_assistant_message("", [_recommend_call("functional")]),
            _finish(),
        ],
        tmp_path=tmp_path,
        recommend_callback=cb,
    )
    traj = agent.run(TaskInstance(description="test L2"))

    assert seen and seen[0]["level"] == "L2"
    assert traj.status == "completed"
    assert traj.meta["recommendations"]["modified"] == 1
    obs = [m for s in traj.steps for m in s.tool_responses
           if m.name == "recommend"][0]
    assert "ωB97X-D" in obs.content
    assert obs.meta["decision_authority"] == "user-chemistry"


def test_l2_without_callback_auto_accepts(tmp_path):
    policy = Policy(default_level="L2")
    agent = _agent(
        policy,
        responses=[
            stub_assistant_message("", [_recommend_call("basis")]),
            _finish(),
        ],
        tmp_path=tmp_path,
    )
    traj = agent.run(TaskInstance(description="test L2 script mode"))
    assert traj.status == "completed"
    assert traj.meta["recommendations"]["accepted"] == 1


def test_l2_cancel_finishes_as_cancelled_not_completed(tmp_path):
    """回归：用户在化学决策卡上点"取消"，任务终态必须是 cancelled，
    而不是 completed（否则 web 会显示"任务完成"，与审计的 cancel 矛盾）。"""
    policy = Policy(default_level="L2", decisions={"functional": "L2"})

    def cb(payload):
        return {"status": "cancel", "user_note": "算了"}

    agent = _agent(
        policy,
        responses=[
            stub_assistant_message("", [_recommend_call("functional")]),
            _finish(),  # 不应被消费
        ],
        tmp_path=tmp_path,
        recommend_callback=cb,
    )
    traj = agent.run(TaskInstance(description="cancel at decision"))
    assert traj.status == "cancelled"
    assert traj.meta["recommendations"]["cancelled"] == 1


# ── L3：无通道 → 升级 ask_user 挂起 ──────────────────────────────────────────


def test_l3_without_callback_escalates_to_ask_user(tmp_path):
    policy = Policy(default_level="L2", decisions={"multiplicity": "L3"})
    agent = _agent(
        policy,
        responses=[
            stub_assistant_message("", [_recommend_call("multiplicity")]),
            _finish(),  # 不应被消费：任务应在升级点挂起
        ],
        tmp_path=tmp_path,
    )
    traj = agent.run(TaskInstance(description="test L3 escalation"))

    assert traj.status == "waiting_for_input"
    assert traj.finish_payload and "questions" in traj.finish_payload
    assert "multiplicity" in traj.finish_payload["questions"][0]
    rec = traj.meta["recommendations"]
    assert rec["escalated"] == 1
    obs = [m for s in traj.steps for m in s.tool_responses
           if m.name == "recommend"][0]
    assert obs.meta["recommend_status"] == "escalated"
    assert obs.meta["escalation"] is True


def test_l3_with_callback_lets_user_decide(tmp_path):
    policy = Policy(default_level="L2", decisions={"multiplicity": "L3"})

    def cb(payload):
        assert payload["level"] == "L3"
        return {"status": "accept"}

    agent = _agent(
        policy,
        responses=[
            stub_assistant_message("", [_recommend_call("multiplicity")]),
            _finish(),
        ],
        tmp_path=tmp_path,
        recommend_callback=cb,
    )
    traj = agent.run(TaskInstance(description="test L3 with channel"))
    assert traj.status == "completed"
    assert traj.meta["recommendations"]["accepted"] == 1


# ── 审计落盘 ─────────────────────────────────────────────────────────────────


def test_recommend_audit_line_written_with_level(tmp_path):
    policy = Policy(default_level="L2", decisions={"functional": "L1"})
    agent = _agent(
        policy,
        responses=[
            stub_assistant_message("", [_recommend_call("functional")]),
            _finish(),
        ],
        tmp_path=tmp_path,
    )
    traj = agent.run(TaskInstance(description="audit"))
    log = tmp_path / "runs" / traj.task_id / "confirmations.jsonl"
    assert log.exists()
    import json
    lines = [json.loads(ln) for ln in log.read_text().splitlines()]
    rec = [entry for entry in lines if entry.get("type") == "recommend"]
    assert rec and rec[0]["level"] == "L1" and rec[0]["status"] == "accept"
