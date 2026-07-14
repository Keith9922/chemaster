"""calc_psi4 的纯文本输出解析器群。

从 server.py 拆出（答辩后重构 §8.4）：这些函数只做正则解析、与"驱动
psi4"零耦合，拆出后**无 psi4 环境也可测试**（server.py 的单测因为要
mock psi4 模块，在无 psi4 的 CI runner 上整体跳过；本模块不受影响）。

server.py 仍以同名下划线函数 re-export，旧调用点/测试不需要改。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

__all__ = [
    "get_ir_intensities",
    "parse_frequencies_from_output",
    "parse_opt_iterations_from_output",
    "parse_tdscf_from_output",
    "parse_thermal_from_output",
]

_EV_PER_HARTREE: float | None = None


def _ev_per_hartree() -> float:
    """CODATA 值优先走 kb.formulas；导入失败时用内置字面量兜底。"""
    global _EV_PER_HARTREE
    if _EV_PER_HARTREE is None:
        try:
            from chemaster.kb.formulas import constants as C
            _EV_PER_HARTREE = float(C.get("hartree_to_eV").value)
        except Exception:
            _EV_PER_HARTREE = 27.211386245988
    return _EV_PER_HARTREE


def parse_frequencies_from_output(log_path: str) -> list[float]:
    """从 psi4 输出文件解析频率（cm^-1）。

    psi4 频率输出格式（psi4 1.9+）：
        Freq [cm^-1]                1618.2540           3834.8812           3931.8836
    也兼容旧格式（每行一个 Frequency 关键字）。
    若解析失败返回空 list。
    """
    try:
        text = Path(log_path).read_text()
    except Exception:
        return []

    freqs: list[float] = []

    # 新格式：提取所有含 'Freq [cm^-1]' 行中的数字。
    # 注意：高对称分子（如 CH4 / Td）会按 irrep 分块输出多组 'Freq [cm^-1]'，
    # 不能只取第一行（早期 bug：methane 9 个模式只解析出 3 个）。
    for line in text.splitlines():
        if "Freq [cm^-1]" in line:
            nums = re.findall(r"([-+]?\d+\.\d+)", line)
            for s in nums:
                v = float(s)
                if v != 0.0:
                    freqs.append(v)
    if freqs:
        return freqs

    # 旧格式：逐行匹配 'Frequency' 关键字
    pattern = re.compile(r"^\s*Frequency\s+([-+]?\d+\.\d+)", re.MULTILINE)
    for m in pattern.finditer(text):
        val = float(m.group(1))
        if val != 0.0:
            freqs.append(val)

    return freqs


def get_ir_intensities(wfn, n_freqs: int) -> list[float]:
    """从 wavefunction 获取 IR 强度，处理 psi4 版本差异。

    psi4 不同版本访问 IR_intensity 的方式不同，做 fallback。
    """
    try:
        fa = wfn.frequency_analysis
        if fa is not None and "IR_intensity" in fa:
            data = fa["IR_intensity"].data
            if hasattr(data, "tolist"):
                return [float(x) for x in data.tolist()]
            return [float(x) for x in data]
    except Exception:
        pass
    # fallback：返回零强度列表
    return [0.0] * n_freqs


def parse_thermal_from_output(log_path: str) -> dict[str, Any]:
    """Parse psi4's thermochemistry summary block.

    Extracts the corrections (H, G, internal-E thermal) and the absolute
    enthalpy / Gibbs at temperature. Returns a dict with each value tagged
    by unit; missing fields stay None.

    psi4 prints, e.g.:
        Correction H    15.928 [kcal/mol] ... 0.02538285 [Eh]
        Total H, Enthalpy at  298.15 [K]  ... -76.33282512 [Eh]
        Correction G     2.488 [kcal/mol] ... 0.00396527 [Eh]
        Total G, Gibbs energy at  298.15 [K] ... -76.35424270 [Eh]
        Correction E    15.335 [kcal/mol] ... 0.02443866 [Eh]
        Total E, Thermal (internal) energy at  298.15 [K] ... -76.33376930 [Eh]
    """
    out = {
        "h_corr": None,            # H_corr (Hartree, includes ZPE + thermal H)
        "g_corr": None,            # G_corr
        "e_corr": None,            # internal energy correction
        "ts": None,                # T·S = H_corr - G_corr (derived)
        "total_h": None,           # absolute enthalpy at T (Hartree)
        "total_g": None,           # absolute Gibbs at T (Hartree)
        "total_e": None,           # absolute internal E at T (Hartree)
    }
    try:
        text = Path(log_path).read_text(errors="replace")
    except Exception:
        return out

    # Correction X    XX.XXX [kcal/mol]    XX.XXX [kJ/mol]    0.0XXXXXXX [Eh]
    corr = re.compile(
        r"Correction\s+([HGES])\b[^\n]*?([-+]?\d+\.\d+)\s*\[Eh\]",
        re.MULTILINE,
    )
    for m in corr.finditer(text):
        kind = m.group(1)
        val = float(m.group(2))
        if kind == "H":
            out["h_corr"] = {"value": val, "unit": "Hartree"}
        elif kind == "G":
            out["g_corr"] = {"value": val, "unit": "Hartree"}
        elif kind == "E":
            out["e_corr"] = {"value": val, "unit": "Hartree"}

    total = re.compile(
        r"Total\s+(\w+)[^\n]*?at\s+\d+\.\d+\s*\[K\][^\n]*?"
        r"([-+]?\d+\.\d+)\s*\[Eh\]",
        re.MULTILINE,
    )
    for m in total.finditer(text):
        kind = m.group(1)
        val = float(m.group(2))
        if kind == "H":
            out["total_h"] = {"value": val, "unit": "Hartree"}
        elif kind == "G":
            out["total_g"] = {"value": val, "unit": "Hartree"}
        elif kind == "E":
            out["total_e"] = {"value": val, "unit": "Hartree"}

    # T·S derived from H_corr - G_corr (since G = H - T·S → T·S = H - G).
    if out["h_corr"] is not None and out["g_corr"] is not None:
        ts_Eh = out["h_corr"]["value"] - out["g_corr"]["value"]
        out["ts"] = {"value": round(ts_Eh, 8), "unit": "Hartree"}

    return out


def parse_opt_iterations_from_output(log_path: str) -> int:
    """Count optimizer macro steps from psi4's geometry-optimization printout.

    psi4 1.10's optking prints the banner
        "OPTKING 3.0: for geometry optimizations"
    once per macro step (i.e. once per outer geometry update). We count those.
    Falls back to "Optimization Iteration N" for older psi4 formats.
    """
    try:
        text = Path(log_path).read_text(errors="replace")
    except Exception:
        return 0
    n = len(re.findall(r"OPTKING\s+\d+\.\d+:\s*for\s+geometry\s+optimizations", text))
    if n:
        return n
    return len(re.findall(r"Optimization\s+Iteration\s+\d+", text))


def parse_tdscf_from_output(
    output_path: str,
    want_triplets: bool,
) -> tuple[list[dict], list[dict]]:
    """Regex-parse psi4's TDDFT printout. Tolerant to formatting drift.

    psi4 prints (≥1.9):
        Excited State    1 (3 A):   0.25504 au   178.65 nm f = 0.0000
                                ^^^      ^^^      ^^^         ^^^
                              spin#  excitation  wavelength  oscillator
    where spin# == 1 → singlet, 3 → triplet.
    """
    try:
        text = Path(output_path).read_text(errors="replace")
    except Exception:
        return [], []

    eV_per_au = _ev_per_hartree()

    pattern = re.compile(
        r"Excited\s+State\s+(\d+)\s*\(\s*(\d+)\s*[A-Za-z']*\s*\)\s*:\s*"
        r"([-+]?\d+\.\d+)\s*au\s+([-+]?\d+\.\d+)\s*nm\s+f\s*=\s*([-+]?\d+\.\d+)",
        re.MULTILINE,
    )
    singlets: list[dict] = []
    triplets: list[dict] = []
    seen_keys: set[tuple[int, int]] = set()   # (spin, state) — psi4 prints twice

    for m in pattern.finditer(text):
        idx = int(m.group(1))
        spin = int(m.group(2))
        e_au = float(m.group(3))
        wl_nm = float(m.group(4))
        f_osc = float(m.group(5))
        e_eV = e_au * eV_per_au

        key = (spin, idx)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        entry = {
            "state": idx,
            "excitation_energy": {"value": round(e_eV, 4), "unit": "eV"},
            "wavelength_nm": round(wl_nm, 2),
            "oscillator_strength": round(f_osc, 6),
        }
        if spin == 1:
            singlets.append(entry)
        elif spin == 3 and want_triplets:
            triplets.append(entry)

    # Re-number per spin (psi4 numbers across all states; we want S1, S2, ...
    # and T1, T2, ... independently).
    for i, e in enumerate(singlets, 1):
        e["state"] = i
    for i, e in enumerate(triplets, 1):
        e["state"] = i

    return singlets, triplets
