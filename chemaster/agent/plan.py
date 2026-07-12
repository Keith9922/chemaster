"""Plan 数据类 —— Agent 与用户交互的中心对象。

每次任务必须先生成 Plan、用户确认、Executor 才能执行。
持久化到 ``runs/<task_id>/plan.json``，支持 3 个月后 replay。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal


@dataclass
class System:
    """要计算的化学体系。"""

    formula: str | None = None         # H2O / SMILES / 自定义标签
    smiles: str | None = None
    geometry_xyz: str | None = None     # xyz 块字符串
    charge: int = 0
    multiplicity: int = 1
    n_atoms: int | None = None
    notes: str | None = None


@dataclass
class Cost:
    """一个 Plan 步骤或整体的成本估算。"""

    cpu_minutes: float = 0.0
    memory_gb: float = 0.0
    disk_mb: float = 0.0
    wall_clock_s: float = 0.0
    confidence: Literal["high", "medium", "low"] = "medium"


@dataclass
class McpCall:
    """单次 MCP 调用计划。Executor 实际调用时按此拼参数。"""

    server: str                         # 例 "chem.calc.psi4"
    tool: str                           # 例 "optimize"
    args: dict = field(default_factory=dict)


@dataclass
class Alternative:
    """方法替代选项（给用户编辑 Plan 时看的）。"""

    label: str                          # "ωB97X-D / def2-TZVP"
    rationale: str                      # "更准但贵 30%"
    cost_factor: float = 1.0


@dataclass
class PlanStep:
    """一个原子的执行步骤。"""

    name: str                           # "geometry_optimization"
    skill: str | None = None            # 触发的 skill；可空（直接调 MCP）
    mcp_calls: list[McpCall] = field(default_factory=list)
    rationale: str = ""                 # 为什么这样做
    alternatives: list[Alternative] = field(default_factory=list)
    estimated_cost: Cost = field(default_factory=Cost)
    risks: list[str] = field(default_factory=list)


@dataclass
class Citation:
    """引用（Planner 必须给出依据）。"""

    text: str
    source: str                          # 文档名 / DOI / KB rule 路径
    score: float | None = None           # RAG 召回分


@dataclass
class Plan:
    """完整 Plan 对象。Confirmation 阶段渲染、Executor 阶段执行。"""

    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    user_intent: str = ""
    inferred_workflow: str = ""          # "opt+freq" / "tddft" / "tadf-pipeline"
    target_system: System = field(default_factory=System)
    steps: list[PlanStep] = field(default_factory=list)
    total_estimate: Cost = field(default_factory=Cost)
    citations: list[Citation] = field(default_factory=list)
    requires_confirmation: bool = True

    # ---------- 序列化 ----------

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> Plan:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> Plan:
        # 简化反序列化；生产环境用 pydantic 更稳。
        steps = [
            PlanStep(
                name=s["name"],
                skill=s.get("skill"),
                mcp_calls=[McpCall(**c) for c in s.get("mcp_calls", [])],
                rationale=s.get("rationale", ""),
                alternatives=[Alternative(**a) for a in s.get("alternatives", [])],
                estimated_cost=Cost(**s.get("estimated_cost", {})),
                risks=s.get("risks", []),
            )
            for s in data.get("steps", [])
        ]
        return cls(
            task_id=data["task_id"],
            created_at=data["created_at"],
            user_intent=data["user_intent"],
            inferred_workflow=data["inferred_workflow"],
            target_system=System(**data.get("target_system", {})),
            steps=steps,
            total_estimate=Cost(**data.get("total_estimate", {})),
            citations=[Citation(**c) for c in data.get("citations", [])],
            requires_confirmation=data.get("requires_confirmation", True),
        )
