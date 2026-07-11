"""Shared test-data fixtures: prompts × molecules × phrasing styles.

Used by:
  - ``scripts/benchmarks/run_execution_and_scalability.py`` (response-rate)
  - ``scripts/benchmarks/run_stress_test.py``                (1(b) stress test)
  - ``tests/integration/test_agent_smoke.py``                 (smoke tests)

Why a shared module?
  The response-rate benchmark (§4.4.2) and the stress test (new) both
  consume prompt data; rather than duplicating two giant lists they share
  one source. The data also feeds future fuzz tests + future eval suites.

Three independent axes:

  1. MOLECULES  — common small molecules with verified XYZ + multiplicity
  2. INTENTS    — what the user wants computed (energy / opt / KB lookup / …)
  3. PHRASINGS  — how the user wrote it (formal EN / casual EN / formal ZH /
                  casual ZH / code-mixed).  The ``{mol}`` slot is filled in
                  at runtime so each phrasing × molecule = one test case.

The cross-product is huge by design (∼10 molecules × 5 intents × 16
phrasings = 800 prompts).  Iterate over the constants directly when you
want all of them, or use :func:`sample_prompts` for a smaller subset.
"""

from __future__ import annotations

import random
from typing import Iterator


# ──────────────────────────────────────────────────────────────────────────────
# 1. Molecules — small set, hand-curated to be psi4-easy with sto-3g / def2-SVP
# ──────────────────────────────────────────────────────────────────────────────

# Each entry: name → (charge, multiplicity, formula_pretty, xyz_block).
# XYZ blocks use Å, two-decimal precision (enough for SCF-energy benchmarks);
# multiplicities are spin-correct (O2 is triplet, all others singlet).
MOLECULES: dict[str, dict] = {
    "H2": {
        "charge": 0, "multiplicity": 1, "formula": "H2",
        "xyz": "2\nH2\nH 0.0 0.0 0.0\nH 0.0 0.0 0.74\n",
        "size": "very_small",
    },
    "H2O": {
        "charge": 0, "multiplicity": 1, "formula": "H2O",
        "xyz": "3\nwater\nO 0.0 0.0 0.0\nH 0.757 -0.587 0.0\nH -0.757 -0.587 0.0\n",
        "size": "small",
    },
    "NH3": {
        "charge": 0, "multiplicity": 1, "formula": "NH3",
        "xyz": ("4\nammonia\nN 0.0 0.0 0.0\nH 0.937 0.0 -0.381\n"
                "H -0.469 0.812 -0.381\nH -0.469 -0.812 -0.381\n"),
        "size": "small",
    },
    "N2": {
        "charge": 0, "multiplicity": 1, "formula": "N2",
        "xyz": "2\nnitrogen\nN 0.0 0.0 0.0\nN 0.0 0.0 1.098\n",
        "size": "very_small",
    },
    "CH4": {
        "charge": 0, "multiplicity": 1, "formula": "CH4",
        "xyz": ("5\nmethane\nC 0.0 0.0 0.0\nH 0.629 0.629 0.629\n"
                "H -0.629 -0.629 0.629\nH -0.629 0.629 -0.629\n"
                "H 0.629 -0.629 -0.629\n"),
        "size": "small",
    },
    "CO2": {
        "charge": 0, "multiplicity": 1, "formula": "CO2",
        "xyz": "3\ncarbon dioxide\nC 0.0 0.0 0.0\nO 0.0 0.0 1.16\nO 0.0 0.0 -1.16\n",
        "size": "small",
    },
    "O2": {
        # Triplet ground state — common test for spin handling.
        "charge": 0, "multiplicity": 3, "formula": "O2",
        "xyz": "2\noxygen\nO 0.0 0.0 0.0\nO 0.0 0.0 1.208\n",
        "size": "very_small",
    },
    "HCl": {
        "charge": 0, "multiplicity": 1, "formula": "HCl",
        "xyz": "2\nhydrogen chloride\nH 0.0 0.0 0.0\nCl 0.0 0.0 1.275\n",
        "size": "very_small",
    },
    "CH3OH": {
        # Methanol — medium-easy single-reference org. molecule.
        "charge": 0, "multiplicity": 1, "formula": "CH3OH",
        "xyz": ("6\nmethanol\nC -0.046 0.663 0.0\nO -0.046 -0.756 0.0\n"
                "H -1.087 0.989 0.0\nH 0.439 1.097 0.890\n"
                "H 0.439 1.097 -0.890\nH 0.851 -1.085 0.0\n"),
        "size": "medium",
    },
    "C2H6": {
        # Ethane — slightly larger but still trivial.
        "charge": 0, "multiplicity": 1, "formula": "C2H6",
        "xyz": ("8\nethane\nC 0.0 0.0 0.764\nC 0.0 0.0 -0.764\n"
                "H 1.018 0.0 1.157\nH -0.509 -0.881 1.157\n"
                "H -0.509 0.881 1.157\nH -1.018 0.0 -1.157\n"
                "H 0.509 0.881 -1.157\nH 0.509 -0.881 -1.157\n"),
        "size": "medium",
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# 2. Intents — categories of chemistry tasks the agent should route correctly
# ──────────────────────────────────────────────────────────────────────────────

# Each intent maps to (expected_tool, [phrasing_templates]).  Each phrasing
# may include ``{mol}`` (substituted with the molecule formula) and
# ``{method}`` / ``{basis}`` (substituted from sensible defaults).
INTENT_GROUPS: list[dict] = [
    {
        "group": "energy",
        "expected_tool": "calc_psi4_single_point",
        "phrasings": [
            # Formal English
            "Compute the SCF energy of {mol}.",
            "What is the single-point energy of {mol} at HF/sto-3g?",
            "Calculate the electronic energy of {mol}.",
            "Compute total energy for {mol}.",
            "Run a single point on {mol} with B3LYP-D3(BJ)/def2-SVP.",
            # Casual English
            "Hey, can you give me the energy of {mol}?",
            "energy of {mol} please",
            "scf {mol}",
            "what's the SCF energy of {mol}",
            "compute {mol} energy",
            # Formal Chinese
            "计算 {mol} 分子的 SCF 能量。",
            "我需要 {mol} 的单点能。",
            "请算一下 {mol} 在 HF/sto-3g 下的总能量。",
            "对 {mol} 做一个单点能计算。",
            # Casual Chinese
            "{mol} 能量",
            "算下 {mol} 单点能",
            "{mol} 的电子能是多少",
        ],
    },
    {
        "group": "optimize",
        "expected_tool": "calc_psi4_single_point",  # routes to SP fallback
        "phrasings": [
            "Optimize the geometry of {mol}.",
            "Find the equilibrium structure of {mol}.",
            "Run geometry optimization on {mol}.",
            "Minimise {mol} energy with respect to coordinates.",
            "optimise {mol}",
            "geometry of {mol} optimize",
            "优化 {mol} 的几何结构",
            "找 {mol} 的平衡构型",
            "{mol} 几何优化",
            "{mol} optimize 一下",
            "对 {mol} 做几何优化",
            "优化 {mol} 极小值",
        ],
    },
    {
        "group": "constant",
        "expected_tool": "const_get",
        "phrasings": [
            "What is Planck's constant?",
            "Look up Avogadro's number.",
            "Tell me the value of hbar.",
            "I need the Boltzmann constant kB.",
            "Get the speed of light.",
            "Get me a physical constant.",
            "constant please",
            "planck constant value",
            "普朗克常数是多少",
            "查一下阿伏伽德罗常数",
            "玻尔兹曼常数 kB 数值",
            "光速的数值是多少",
            "查物理常数",
            "我要 hbar 的值",
            "convert 1 hartree to eV",
            "hartree 到 eV 的换算因子是多少",
        ],
    },
    {
        "group": "kb",
        "expected_tool": "kb_search",
        "phrasings": [
            "Search the knowledge base for TADF.",
            "Find a playbook on opt-freq.",
            "Look up the kRISC skill.",
            "Find documentation on conformer search.",
            "search kb for solvation",
            "search kb tddft",
            "搜索知识库 TADF",
            "查一下 kRISC 的 skill",
            "搜 opt-freq 的 playbook",
            "找 tddft 的 skill",
            "kb 搜 solvation",
            "查相对论方法的 playbook",
        ],
    },
    {
        "group": "skill",
        "expected_tool": "use_skill",
        "phrasings": [
            "Use the opt-freq skill.",
            "Apply the tddft skill.",
            "use_skill on soc",
            "Load the tadf-pipeline skill.",
            "Apply the conformer skill.",
            "use skill ts-search",
            "load the dlpno-ccsdt skill",
            "use the pka skill",
            "use_skill pes-scan",
            "使用 opt-freq skill",
            "应用 tddft skill",
            "调用 use_skill soc",
            "加载 tadf-pipeline skill",
            "应用 conformer skill",
            "调用 ts-search skill",
            "加载 dlpno-ccsdt skill",
        ],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# 3. Cross-product / sampling helpers
# ──────────────────────────────────────────────────────────────────────────────

def iter_all_prompts() -> Iterator[dict]:
    """Yield every (group, intent_text, expected_tool, molecule) combination.

    Phrasings with ``{mol}`` are expanded once per molecule; phrasings
    without it are emitted once with ``molecule=None``.
    """
    for grp in INTENT_GROUPS:
        for phrasing in grp["phrasings"]:
            if "{mol}" in phrasing:
                for mol_name in MOLECULES:
                    yield {
                        "group": grp["group"],
                        "expected_tool": grp["expected_tool"],
                        "intent": phrasing.format(mol=mol_name),
                        "molecule": mol_name,
                    }
            else:
                yield {
                    "group": grp["group"],
                    "expected_tool": grp["expected_tool"],
                    "intent": phrasing,
                    "molecule": None,
                }


def sample_prompts(n: int, *, seed: int = 0) -> list[dict]:
    """Return a deterministic sample of ``n`` prompts from the cross-product.

    Use a seed for reproducibility across stress-test runs.
    """
    all_p = list(iter_all_prompts())
    rng = random.Random(seed)
    if n >= len(all_p):
        return all_p
    return rng.sample(all_p, n)


def count_prompts() -> int:
    """Total number of prompts in the cross-product (for capacity planning)."""
    return sum(1 for _ in iter_all_prompts())
