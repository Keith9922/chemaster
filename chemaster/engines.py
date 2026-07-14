"""统一的计算引擎探测 — ``--check-engines`` / doctor / TUI / Web 共用。

此前 4 处各自维护一份引擎清单和探测逻辑，并且互相不一致：
``--check-engines`` 漏掉 g16/bdf/momap，doctor 对 psi4 只查 PATH（漏掉
纯 Python-module 安装），TUI/Web 又各写了一份 psi4 的 import 检查。

探测语义：
- 纯二进制引擎（xtb / orca / g16 / bdf / momap / Multiwfn）：PATH 上有
  候选可执行文件即可用。
- Python 模块引擎（psi4 / pyscf）：**当前解释器可 import 才算可用** ——
  wrapper 是 ``import psi4`` 驱动的，二进制在 PATH 但模块缺失照样跑不了。
"""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class EngineSpec:
    name: str                                # 展示名
    binaries: tuple[str, ...] = ()           # PATH 上的候选可执行名
    python_module: str | None = None         # 需要可 import 的模块
    install_hint: str = ""


ENGINE_SPECS: tuple[EngineSpec, ...] = (
    EngineSpec("psi4", ("psi4",), python_module="psi4",
               install_hint="mamba install -c conda-forge psi4"),
    EngineSpec("pyscf", (), python_module="pyscf",
               install_hint="pip install pyscf"),
    EngineSpec("xtb", ("xtb",),
               install_hint="mamba install -c conda-forge xtb"),
    EngineSpec("crest", ("crest",),
               install_hint="mamba install -c conda-forge crest"),
    EngineSpec("orca", ("orca",),
               install_hint="vendor binary; ensure on $PATH (free for academic)"),
    EngineSpec("gaussian", ("g16", "g09"),
               install_hint="Gaussian commercial; ensure g16 on $PATH"),
    EngineSpec("bdf", ("bdf",),
               install_hint="free for academic; ensure bdf on $PATH"),
    EngineSpec("momap", ("momap",),
               install_hint="commercial; ensure momap on $PATH"),
    EngineSpec("multiwfn", ("Multiwfn", "multiwfn"),
               install_hint="http://sobereva.com/multiwfn/"),
)


@dataclass
class EngineStatus:
    spec: EngineSpec
    available: bool
    path: str | None = None       # 命中的可执行路径（或模块占位说明）
    detail: str = ""              # 供 doctor / TUI 展示的补充说明

    @property
    def name(self) -> str:
        return self.spec.name


def probe_engine(spec: EngineSpec) -> EngineStatus:
    path = None
    for exe in spec.binaries:
        path = shutil.which(exe)
        if path:
            break

    if spec.python_module is not None:
        importable = importlib.util.find_spec(spec.python_module) is not None
        if importable:
            return EngineStatus(spec, True, path or "(python module)", "importable")
        if path:
            return EngineStatus(
                spec, False, path,
                "binary on PATH but module not importable in this env",
            )
        return EngineStatus(spec, False, None, "")

    return EngineStatus(spec, path is not None, path)


def probe_engines(
    specs: tuple[EngineSpec, ...] = ENGINE_SPECS,
) -> list[EngineStatus]:
    return [probe_engine(s) for s in specs]


__all__ = [
    "ENGINE_SPECS",
    "EngineSpec",
    "EngineStatus",
    "probe_engine",
    "probe_engines",
]
