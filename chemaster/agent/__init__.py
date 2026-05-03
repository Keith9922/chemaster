"""Agent core: Planner / Confirmation / Executor / Iterator / Retriever / LLM / Context.

Phase 1（直接流水线）：
    Planner → ConfirmationLoop → Executor → Reporter

Phase 2（LLM 驱动循环，EvoMaster 架构）：
    ChemAgent(BaseChemAgent) → _step() 循环 → use_skill / call_mcp / plan_and_execute
    ContextManager 防溢出；Trajectory 逐步记录；ask_user 暂停机制。
"""

# --- Phase 1 直接流水线 ---
from chemaster.agent.confirmation import ApprovedPlan, ConfirmationLoop
from chemaster.agent.executor import Executor
from chemaster.agent.iterator import BenchmarkIterator
from chemaster.agent.plan import (
    Alternative,
    Citation,
    Cost,
    McpCall,
    Plan,
    PlanStep,
    System,
)
from chemaster.agent.planner import Planner
from chemaster.agent.retriever import KnowledgeRetriever

# --- Phase 2 EvoMaster 架构层 ---
from chemaster.agent.base import AgentConfig, BaseChemAgent
from chemaster.agent.chem_agent import ChemAgent
from chemaster.agent.context import ContextConfig, ContextManager
from chemaster.agent.llm import AnthropicLLM, OpenAICompatLLM, build_llm
from chemaster.agent.types import (
    AssistantMessage,
    Dialog,
    MessageRole,
    StepRecord,
    SystemMessage,
    TaskInstance,
    ToolCall,
    ToolCallFunction,
    ToolMessage,
    ToolSpec,
    ToolFunctionSchema,
    Trajectory,
    UserMessage,
)

__all__ = [
    # Phase 1 — 直接流水线
    "Plan",
    "PlanStep",
    "System",
    "Cost",
    "McpCall",
    "Alternative",
    "Citation",
    "Planner",
    "ConfirmationLoop",
    "ApprovedPlan",
    "Executor",
    "BenchmarkIterator",
    "KnowledgeRetriever",
    # Phase 2 — EvoMaster Agent 核心
    "AgentConfig",
    "BaseChemAgent",
    "ChemAgent",
    "ContextConfig",
    "ContextManager",
    "AnthropicLLM",
    "OpenAICompatLLM",
    "build_llm",
    # 类型系统
    "AssistantMessage",
    "Dialog",
    "MessageRole",
    "StepRecord",
    "SystemMessage",
    "TaskInstance",
    "ToolCall",
    "ToolCallFunction",
    "ToolMessage",
    "ToolSpec",
    "ToolFunctionSchema",
    "Trajectory",
    "UserMessage",
]
