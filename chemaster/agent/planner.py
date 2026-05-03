"""Planner —— 把用户意图转成 Plan 对象。

实现见 docs/ARCHITECTURE.md §3.5、docs/CLAUDE.md §5.4。

Phase 1 占位实现：硬编码识别 H2O / NH3 / CH4 / CO2 / 苯环 的 opt+freq 案例。
Phase 2 接入 LLM + RAG。
"""

from __future__ import annotations

from dataclasses import dataclass

from chemaster.agent.plan import (
    Citation,
    Cost,
    McpCall,
    Plan,
    PlanStep,
    System,
)


@dataclass
class _BuiltinMol:
    """内置分子描述符，供 Phase 1 Planner 匹配用。"""

    lookup_name: str       # 传给 chem.io.ase.lookup_by_name 的名字
    formula: str
    smiles: str
    n_atoms: int
    charge: int = 0
    multiplicity: int = 1
    notes: str = ""
    # 关键词列表（小写），用于匹配用户输入
    keywords: tuple[str, ...] = ()
    # 成本估算（cpu_min, mem_gb, wall_s）
    cpu_min: float = 1.0
    mem_gb: float = 1.0
    wall_s: float = 60.0


# ---------------------------------------------------------------
# Phase 1 内置分子库（ROADMAP 要求的 5 个烟雾测试分子）
# ---------------------------------------------------------------
_BUILTIN_MOLECULES: list[_BuiltinMol] = [
    _BuiltinMol(
        lookup_name="water",
        formula="H2O",
        smiles="O",
        n_atoms=3,
        notes="neutral singlet water",
        keywords=("h2o", "水分子", "water", "水"),
        cpu_min=1.0,
        mem_gb=1.0,
        wall_s=60.0,
    ),
    _BuiltinMol(
        lookup_name="ammonia",
        formula="NH3",
        smiles="N",
        n_atoms=4,
        notes="neutral singlet ammonia",
        keywords=("nh3", "氨气", "ammonia", "氨"),
        cpu_min=1.5,
        mem_gb=1.0,
        wall_s=90.0,
    ),
    _BuiltinMol(
        lookup_name="methane",
        formula="CH4",
        smiles="C",
        n_atoms=5,
        notes="neutral singlet methane",
        keywords=("ch4", "甲烷", "methane"),
        cpu_min=1.5,
        mem_gb=1.0,
        wall_s=90.0,
    ),
    _BuiltinMol(
        lookup_name="co2",
        formula="CO2",
        smiles="O=C=O",
        n_atoms=3,
        notes="neutral singlet carbon dioxide",
        keywords=("co2", "二氧化碳", "carbon dioxide"),
        cpu_min=1.5,
        mem_gb=1.0,
        wall_s=90.0,
    ),
    _BuiltinMol(
        lookup_name="benzene",
        formula="C6H6",
        smiles="c1ccccc1",
        n_atoms=12,
        notes="neutral singlet benzene",
        keywords=("benzene", "苯", "苯环", "c6h6"),
        cpu_min=5.0,
        mem_gb=2.0,
        wall_s=300.0,
    ),
]


class Planner:
    """Phase 1 硬编码 Planner —— 支持 H2O / NH3 / CH4 / CO2 / 苯 的 opt+freq。

    Phase 2 实现：
    1. retriever.search(user_intent) → 找匹配 skill + KB 规则
    2. LLM 出 Plan 草案
    3. 校验：成本爆炸、不支持元素、单位异常
    4. 输出最终 Plan
    """

    _DEFAULT_METHOD = "B3LYP-D3(BJ)"
    _DEFAULT_BASIS = "def2-TZVP"

    def __init__(self, llm_client=None, retriever=None) -> None:
        self.llm = llm_client
        self.retriever = retriever

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def create_plan(self, user_intent: str) -> Plan:
        """把用户意图转成可执行 Plan。

        Phase 1：关键词匹配内置分子库。
        Phase 2：先 RAG 后 LLM 推理。
        """
        text = user_intent.lower().strip()

        # Phase 1 关键词匹配
        for mol in _BUILTIN_MOLECULES:
            if any(kw in text for kw in mol.keywords):
                return self._builtin_opt_freq_plan(user_intent, mol)

        # Phase 1 不支持的体系
        supported = ", ".join(
            "/".join(m.keywords[:2]) for m in _BUILTIN_MOLECULES
        )
        raise NotImplementedError(
            f"Phase 1 Planner 仅支持：{supported}。\n"
            f"收到：{user_intent!r}\n"
            f"Phase 2 将接入 LLM + RAG 实现任意体系规划。"
        )

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _builtin_opt_freq_plan(self, user_intent: str, mol: _BuiltinMol) -> Plan:
        """通用工厂：为内置分子生成 opt+freq 两步计划。"""

        target_system = System(
            formula=mol.formula,
            smiles=mol.smiles,
            charge=mol.charge,
            multiplicity=mol.multiplicity,
            n_atoms=mol.n_atoms,
            notes=mol.notes,
        )

        step1 = PlanStep(
            name="geometry_optimization",
            skill="opt-freq",
            mcp_calls=[
                McpCall(
                    server="chem.io.ase",
                    tool="lookup_by_name",
                    args={"name": mol.lookup_name},
                ),
                McpCall(
                    server="chem.calc.psi4",
                    tool="optimize",
                    args={
                        "method": self._DEFAULT_METHOD,
                        "basis": self._DEFAULT_BASIS,
                        "charge": mol.charge,
                        "multiplicity": mol.multiplicity,
                    },
                ),
            ],
            rationale=f"获取 {mol.formula} 优化几何，作为频率计算起点",
            estimated_cost=Cost(
                cpu_minutes=mol.cpu_min,
                memory_gb=mol.mem_gb,
                wall_clock_s=mol.wall_s,
                confidence="high",
            ),
            risks=["SCF_NOT_CONVERGED", "GEOMETRY_NOT_CONVERGED"],
        )

        step2 = PlanStep(
            name="frequency",
            skill="opt-freq",
            mcp_calls=[
                McpCall(
                    server="chem.calc.psi4",
                    tool="frequency",
                    args={
                        "method": self._DEFAULT_METHOD,
                        "basis": self._DEFAULT_BASIS,
                        "charge": mol.charge,
                        "multiplicity": mol.multiplicity,
                    },
                ),
            ],
            rationale="验证极小点，获取 ZPE 和热力学修正（ΔH, ΔG, S）",
            estimated_cost=Cost(
                cpu_minutes=mol.cpu_min,
                memory_gb=mol.mem_gb,
                wall_clock_s=mol.wall_s,
                confidence="high",
            ),
            risks=["NEGATIVE_FREQUENCIES"],
        )

        return Plan(
            user_intent=user_intent,
            inferred_workflow="opt+freq",
            target_system=target_system,
            steps=[step1, step2],
            total_estimate=Cost(
                cpu_minutes=mol.cpu_min * 2,
                memory_gb=mol.mem_gb * 2,
                wall_clock_s=mol.wall_s * 2,
                confidence="high",
            ),
            citations=[
                Citation(
                    text="B3LYP-D3(BJ)/def2-TZVP recommended for small organic/inorganic molecules",
                    source="kb/rules/functionals.yaml#B3LYP-D3(BJ)",
                    score=0.95,
                )
            ],
            requires_confirmation=True,
        )
