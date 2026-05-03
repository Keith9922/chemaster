"""ConfirmationLoop —— Plan-Confirm-Execute 三段式中间态。

强制约束（架构层，不靠 prompt 引导）：Executor 没拿到本模块 ``approve()``
返回的 ``ApprovedPlan``，token 校验会失败。这样 LLM / 误用者**无法**跳过
用户确认。

UI 层（TUI ModalScreen / CLI prompt）只需要：
1. ``loop = ConfirmationLoop()``
2. ``approved = loop.approve(plan)`` —— 在 UI 渲染 plan 卡片，按 A 后调本方法
3. 把 ``approved`` 喂给 ``Executor.run()``

UI 自己处理 E（Edit Plan）、R（Replan）、Q（Quit）。E/R 改完 plan 再调
``approve(new_plan)``；Q 直接不调本模块即可（token 不会颁出）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chemaster.agent import _token_registry as _tr
from chemaster.agent.plan import Plan


@dataclass
class ApprovedPlan:
    """已确认的 Plan + 一次性 token。Executor 用 token 校验合法性。

    *不* 在 ``__post_init__`` 里校验 token 非空，因为：
    - Executor.run() 会校验。
    - 测试代码构造空 token 来验证拒绝路径。
    - 反序列化场景（replay）需要先构造再赋值。
    """

    plan: Plan
    confirm_token: str
    user_edits: list[str] = field(default_factory=list)
    signature: str = ""


class ConfirmationLoop:
    """渲染 Plan、收集用户决策、出 ApprovedPlan。

    本类不直接做 UI；它给 UI 提供 ``approve()``、``reject()``、``edit()``
    三个钩子。UI 决定何时调哪个。
    """

    def __init__(self, ui=None) -> None:  # noqa: ANN001
        self.ui = ui

    # ------------------------------------------------------------------
    # 公共 API（UI 调用）
    # ------------------------------------------------------------------

    def approve(
        self,
        plan: Plan,
        user_edits: list[str] | None = None,
    ) -> ApprovedPlan:
        """用户在 UI 上按 A（Accept），UI 调本方法颁发 token。"""
        issued = _tr.issue(plan.task_id)
        return ApprovedPlan(
            plan=plan,
            confirm_token=issued.token,
            user_edits=list(user_edits or []),
            signature=issued.signature,
        )

    def reject(self, plan: Plan) -> None:
        """用户拒绝。撤销可能存在的 token（理论上没颁过，幂等）。"""
        _tr.revoke(plan.task_id)

    def edit(self, plan: Plan) -> Plan:  # noqa: ARG002
        """Phase 2：让 UI 弹编辑器修改 plan。Phase 1 直接抛出。"""
        raise NotImplementedError(
            "Phase 2: ConfirmationLoop.edit() 让用户改方法/基组/收敛阈值"
        )

    # ------------------------------------------------------------------
    # 兼容旧接口：run() —— 已弃用
    # ------------------------------------------------------------------

    def run(self, plan: Plan) -> ApprovedPlan:  # noqa: ARG002
        """旧测试代码路径。强烈建议改用 ``approve()``。"""
        raise NotImplementedError(
            "ConfirmationLoop.run() 已弃用；UI 请直接调 approve()/reject()。"
        )
