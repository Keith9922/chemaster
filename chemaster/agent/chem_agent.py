"""ChemAgent —— BaseChemAgent 的具体实现。

Phase 2 LLM 驱动模式：
- 接收用户意图 → 向 LLM 规划 → 调用 MCP 工具 → Plan-Confirm-Execute 三段式 → 报告

Phase 1 仅使用直接 Planner 流水线（chemaster/agent/planner.py），ChemAgent 在 Phase 2 引入。
这个文件是 Phase 2 的骨架，所有核心接口已实现，细节可在后续迭代中完善。

使用方式：
    from chemaster.agent.chem_agent import ChemAgent
    from chemaster.agent.base import AgentConfig
    from chemaster.agent.llm import build_llm

    config = AgentConfig.from_dict(cfg["agent"])
    llm = build_llm(cfg["llm"])
    agent = ChemAgent(llm=llm, config=config, skill_registry=registry)
    trajectory = agent.run(TaskInstance(task_id="t1", description="计算 H2O 的能量"))
"""

from __future__ import annotations

import json
import logging
from typing import Any

from chemaster.agent.base import AgentConfig, BaseChemAgent
from chemaster.agent.types import (
    AssistantMessage,
    Dialog,
    TaskInstance,
    ToolCall,
    ToolSpec,
    ToolFunctionSchema,
)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# 内置工具规格（Phase 2 LLM 可调用的工具）
# -----------------------------------------------------------------------

_USE_SKILL_SPEC = ToolSpec(
    type="function",
    function=ToolFunctionSchema(
        name="use_skill",
        description=(
            "获取指定 skill 的方法论指导。返回完整的 SKILL.md 内容，"
            "包含计算流程、参数选择规则、失败处理策略。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "skill 名称，例如 opt-freq / tddft / tadf-pipeline",
                },
                "level": {
                    "type": "string",
                    "enum": ["level1", "full"],
                    "description": "level1 = 摘要（约 60 token）；full = 完整文档",
                    "default": "full",
                },
            },
            "required": ["skill_name"],
        },
    ),
)

_CALL_MCP_SPEC = ToolSpec(
    type="function",
    function=ToolFunctionSchema(
        name="call_mcp",
        description=(
            "调用计算化学 MCP 工具（原子操作）。"
            "可用 server：chem.const / chem.io.ase / chem.calc.psi4 / "
            "chem.calc.xtb / chem.parse.cclib / chem.viz"
        ),
        parameters={
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "MCP server 名称，例如 chem.calc.psi4",
                },
                "tool": {
                    "type": "string",
                    "description": "工具名称，例如 optimize / frequency / single_point",
                },
                "args": {
                    "type": "object",
                    "description": "工具参数（见 docs/MCP_GUIDE.md）",
                },
            },
            "required": ["server", "tool", "args"],
        },
    ),
)

_PLAN_AND_EXECUTE_SPEC = ToolSpec(
    type="function",
    function=ToolFunctionSchema(
        name="plan_and_execute",
        description=(
            "生成计算计划并请求用户确认后执行。"
            "LLM 确定了计算方案后调用此工具，系统自动走 Plan-Confirm-Execute 流程。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "workflow": {
                    "type": "string",
                    "description": "工作流名称，例如 opt+freq / tddft / tadf-pipeline",
                },
                "target": {
                    "type": "object",
                    "description": "目标体系描述 {formula, smiles, charge, multiplicity}",
                },
                "method": {
                    "type": "string",
                    "description": "计算方法，例如 B3LYP-D3(BJ)",
                },
                "basis": {
                    "type": "string",
                    "description": "基组，例如 def2-TZVP",
                },
                "rationale": {
                    "type": "string",
                    "description": "方案理由（展示给用户看）",
                },
            },
            "required": ["workflow", "target", "rationale"],
        },
    ),
)

_ASK_USER_SPEC = ToolSpec(
    type="function",
    function=ToolFunctionSchema(
        name="ask_user",
        description=(
            "向用户提问，暂停执行等待回复。"
            "当需要用户决策（如方法选择、精度要求）时使用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "问题列表（每条 ≤ 2 句）",
                },
                "context": {
                    "type": "string",
                    "description": "问题背景说明",
                },
            },
            "required": ["questions"],
        },
    ),
)

_FINISH_SPEC = ToolSpec(
    type="function",
    function=ToolFunctionSchema(
        name="finish",
        description="标记任务完成。所有计算结果已汇总，准备出报告时调用。",
        parameters={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "简短结果摘要（1-3 句）",
                },
            },
            "required": ["summary"],
        },
    ),
)


# -----------------------------------------------------------------------
# ChemAgent
# -----------------------------------------------------------------------

class ChemAgent(BaseChemAgent):
    """ChemMaster Phase 2 Agent —— LLM 驱动的计算化学 Agent。

    继承 BaseChemAgent（EvoMaster 架构），添加：
    1. Skill 注入：system prompt 包含所有 Skill Level 1 摘要
    2. MCP 工具调度：call_mcp → 分发到 chemaster.mcp.*
    3. Plan-Confirm 桥接：plan_and_execute → 调用 Planner + ConfirmationLoop
    4. 单位安全：所有数值通过 kb.formulas，不让 LLM 报数
    """

    def __init__(
        self,
        llm,  # BaseLLM 实例
        config: AgentConfig | None = None,
        skill_registry=None,
        mcp_registry: dict[str, Any] | None = None,
        planner=None,
        confirmation_loop=None,
        executor=None,
    ) -> None:
        super().__init__(config=config, skill_registry=skill_registry)
        self.llm = llm
        self.mcp_registry = mcp_registry or {}   # server_name → MCP module
        self.planner = planner
        self.confirmation_loop = confirmation_loop
        self.executor = executor
        self._mcp_state: dict[str, Any] = {}     # 跨 MCP 调用的状态（几何传递）

    # ------------------------------------------------------------------
    # BaseChemAgent 抽象方法实现
    # ------------------------------------------------------------------

    def _get_system_prompt(self) -> str:
        """构建 system prompt。包含：角色定义 + Skill Level 1 摘要 + 约束。"""
        parts = [
            "你是 ChemMaster，一个本地化计算化学 Agent。",
            "你的职责是：理解用户的化学计算需求，规划最合适的计算方案，",
            "调用专业量化软件（psi4/ORCA/BDF/xTB），并生成可进入论文附录的报告。",
            "",
            "# 核心约束",
            "- 你不算数。所有浮点运算、单位换算走 MCP 工具，不要自己报数值。",
            "- 任何会改变文件系统、提交计算的操作，必须先通过 plan_and_execute 让用户确认。",
            "- 参数选择（泛函、基组）必须通过 use_skill 获取知识库规则，不要凭感觉选。",
            "- 遇到计算失败（SCF 不收敛、虚频、几何卡死），参考对应 skill 的失败处理策略。",
            "",
        ]

        # 注入 Skill Level 1 摘要
        if self.skill_registry is not None:
            try:
                skill_summaries = self.skill_registry.list_skills_level1()
                if skill_summaries:
                    parts.append("# 可用 Skills（Level 1 摘要）")
                    for name, summary in skill_summaries.items():
                        parts.append(f"## {name}")
                        parts.append(summary.strip())
                        parts.append("")
            except Exception as exc:
                logger.warning("Skill 摘要注入失败: %s", exc)

        parts += [
            "# 工具使用顺序",
            "1. use_skill：查阅方法论（先查，再行动）",
            "2. call_mcp：执行原子计算操作",
            "3. plan_and_execute：当方案确定后，生成 Plan 请用户确认",
            "4. ask_user：需要用户决策时暂停",
            "5. finish：所有结果已就绪时标记完成",
        ]

        return "\n".join(parts)

    def _get_user_prompt(self, task: TaskInstance) -> str:
        """构建用户初始 prompt。"""
        lines = [f"**任务 ID**: {task.task_id}"]

        if task.task_type:
            lines.append(f"**类型**: {task.task_type}")

        lines += [
            "",
            "**用户需求**:",
            task.description,
        ]

        if task.metadata:
            lines.append("\n**附加信息**:")
            for k, v in task.metadata.items():
                lines.append(f"- {k}: {v}")

        lines += [
            "",
            "请先通过 use_skill 查阅相关方法论，然后制定计算方案。",
        ]

        return "\n".join(lines)

    def _get_tool_specs(self) -> list[ToolSpec]:
        """返回暴露给 LLM 的工具列表。"""
        return [
            _USE_SKILL_SPEC,
            _CALL_MCP_SPEC,
            _PLAN_AND_EXECUTE_SPEC,
            _ASK_USER_SPEC,
            _FINISH_SPEC,
        ]

    def _execute_tool(self, tool_call: ToolCall) -> tuple[str, dict[str, Any]]:
        """分发工具调用到对应处理器。"""
        tool_name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError as exc:
            return f"参数解析失败: {exc}", {"error": str(exc)}

        dispatch = {
            "use_skill": self._tool_use_skill,
            "call_mcp": self._tool_call_mcp,
            "plan_and_execute": self._tool_plan_and_execute,
        }

        handler = dispatch.get(tool_name)
        if handler is None:
            return f"未知工具: {tool_name}", {"error": "unknown_tool"}

        return handler(args)

    def _query_llm(self, dialog: Dialog) -> AssistantMessage:
        """调用 LLM（通过注入的 BaseLLM 实例）。"""
        return self.llm.query(dialog)

    # ------------------------------------------------------------------
    # 工具处理器
    # ------------------------------------------------------------------

    def _tool_use_skill(self, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """use_skill 工具：返回 Skill 文档内容。"""
        skill_name = args.get("skill_name", "")
        level = args.get("level", "full")

        if not self.skill_registry:
            return (
                f"Skill 注册表未初始化，无法获取 {skill_name!r}。",
                {"error": "registry_unavailable"},
            )

        try:
            if level == "level1":
                summaries = self.skill_registry.list_skills_level1()
                content = summaries.get(skill_name, f"未找到 skill: {skill_name}")
            else:
                skill = self.skill_registry.get_skill(skill_name)
                if skill is None:
                    return f"未找到 skill: {skill_name!r}", {"error": "not_found"}
                content = skill.full_content or skill.meta_info or "(无内容)"

            return content, {"skill": skill_name, "level": level}

        except Exception as exc:
            logger.error("use_skill 失败: %s", exc)
            return f"获取 skill 失败: {exc}", {"error": str(exc)}

    def _tool_call_mcp(self, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """call_mcp 工具：分发到对应 MCP 模块。

        Phase 2 实现：通过 mcp_registry 查找并调用对应 server。
        Phase 1 已在 Executor 中直接调用 MCP，此处是 Phase 2 LLM 模式的分发层。
        """
        server = args.get("server", "")
        tool = args.get("tool", "")
        mcp_args = args.get("args", {})

        if not server or not tool:
            return "server 和 tool 参数不能为空", {"error": "missing_params"}

        # 几何状态注入（与 Executor._resolve_geometry 类似逻辑）
        if "geometry_xyz" not in mcp_args and self._mcp_state.get("optimized_geometry_xyz"):
            mcp_args["geometry_xyz"] = self._mcp_state["optimized_geometry_xyz"]
        elif "geometry_xyz" not in mcp_args and self._mcp_state.get("xyz"):
            mcp_args["geometry_xyz"] = self._mcp_state["xyz"]

        # 查找 MCP handler
        handler = self.mcp_registry.get(server)
        if handler is None:
            # Phase 2 占位：列出可用 server
            available = ", ".join(self.mcp_registry.keys()) or "(无)"
            return (
                f"MCP server {server!r} 未注册。可用 server：{available}。\n"
                f"请通过 plan_and_execute 工具让系统自动调度。",
                {"error": "server_not_found", "available": list(self.mcp_registry.keys())},
            )

        try:
            result = handler(tool, mcp_args)
            # 更新几何状态
            if isinstance(result, dict) and result.get("ok"):
                res_data = result.get("result", {})
                for key in ("optimized_geometry_xyz", "xyz", "geometry_xyz", "energy", "frequencies"):
                    if key in res_data:
                        self._mcp_state[key] = res_data[key]

            return json.dumps(result, ensure_ascii=False, indent=2), {"mcp_result": result}

        except Exception as exc:
            logger.error("call_mcp %s.%s 失败: %s", server, tool, exc)
            return f"MCP 调用失败 [{server}.{tool}]: {exc}", {"error": str(exc)}

    def _tool_plan_and_execute(self, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """plan_and_execute 工具：LLM 确认方案后，走 Plan-Confirm-Execute 流程。

        Phase 2 实现：
        1. 调用 Planner 生成 Plan（或 LLM 直接描述的 Plan）
        2. 展示 PlanCard 给用户确认
        3. 用户确认后调用 Executor 执行
        4. 返回执行结果摘要

        当前为占位实现，返回方案摘要供用户确认。
        完整 TUI 交互在 Phase 2 TUI 集成时完善。
        """
        workflow = args.get("workflow", "")
        target = args.get("target", {})
        method = args.get("method", "B3LYP-D3(BJ)")
        basis = args.get("basis", "def2-TZVP")
        rationale = args.get("rationale", "")

        if not self.planner:
            return (
                "Planner 未配置，无法生成计划。请通过 TUI 的直接 Plan-Confirm-Execute 流程执行。",
                {"error": "planner_unavailable"},
            )

        # 构建用户意图描述，转交给 Planner
        formula = target.get("formula", "")
        smiles = target.get("smiles", "")
        intent = f"对 {formula or smiles} 进行 {workflow} 计算，方法 {method}/{basis}。{rationale}"

        try:
            plan = self.planner.create_plan(intent)
            summary = (
                f"已生成计划：{plan.inferred_workflow}\n"
                f"目标：{plan.target_system.formula}\n"
                f"步骤数：{len(plan.steps)}\n"
                f"估算 CPU 时间：{plan.total_estimate.cpu_minutes:.1f} 分钟\n"
                f"需要用户确认：{plan.requires_confirmation}\n"
                f"理由：{rationale}"
            )
            return summary, {"plan_generated": True, "workflow": workflow}

        except NotImplementedError as exc:
            return str(exc), {"error": "not_implemented"}
        except Exception as exc:
            logger.error("plan_and_execute 失败: %s", exc)
            return f"计划生成失败: {exc}", {"error": str(exc)}
