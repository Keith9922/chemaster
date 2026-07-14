"""kb.formulas — 确定性公式库。LLM 不算数，从这里调。

模块:
- ``constants``: 物理常数表（CODATA-2018）
- ``units``: 单位换算（基于 pint + 化学专用快捷换算）
- ``thermo``: 热力学（ZPE、Boltzmann 权重）
- ``kinetics``: 化学动力学（Arrhenius、Eyring）
- ``photophysics``: 光物理（Marcus kRISC、Strickler-Berg、TADF 量子产率）
"""

from chemaster.kb.formulas import constants, kinetics, photophysics, thermo, units

__all__ = ["constants", "kinetics", "photophysics", "thermo", "units"]
