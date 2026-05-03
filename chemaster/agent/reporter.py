"""Markdown 报告生成器 —— 把 ``runs/<task-id>/`` 转成 ``report.md``。

设计目标
-------
- 读 ``plan.json`` + ``meta.json`` + ``step_NN_*/result.json``，输出
  一份**可直接进论文 SI** 的 Markdown 报告。
- 通用，不绑定 TADF；任何 opt+freq / single_point / TDDFT / 多 step
  pipeline 都能用。
- LLM 不算数：能量换算调 ``kb.formulas.units``。

报告结构
-------
1. 标题 + 任务元信息（task_id、timestamp、用户 prompt）
2. 输入分子（formula、SMILES、charge、multiplicity、xyz）
3. 计划摘要（每 step 一行）
4. 每 step 详情（方法、基组、能量、频率、ZPE、热力学、收敛、耗时、warnings）
5. 关键结果汇总表（最终能量、ZPE、G(298 K)、虚频数）
6. 引用（来自 plan.citations）
7. 复现块（软件版本、git commit、随机种子）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chemaster.kb.formulas import units as U


def generate_report(task_dir: str | Path) -> Path:
    """生成 ``<task_dir>/report.md``。

    Args:
        task_dir: ``runs/<task-id>/`` 目录路径。必须包含 ``plan.json``
            与至少一个 ``step_*/result.json``。

    Returns:
        生成的 ``report.md`` 绝对路径。

    Raises:
        FileNotFoundError: ``plan.json`` 不存在。
    """
    td = Path(task_dir)
    plan_path = td / "plan.json"
    if not plan_path.exists():
        raise FileNotFoundError(f"plan.json not found in {td}")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    meta = _load_or_empty(td / "meta.json")
    steps = _collect_step_results(td)

    md_parts: list[str] = []
    md_parts.append(_render_header(plan, meta))
    md_parts.append(_render_target_system(plan))
    md_parts.append(_render_plan_summary(plan))
    md_parts.append(_render_step_details(plan, steps))
    md_parts.append(_render_key_results(steps))
    md_parts.append(_render_citations(plan))
    md_parts.append(_render_reproducibility(meta, plan))

    out = td / "report.md"
    out.write_text("\n\n".join(p for p in md_parts if p) + "\n", encoding="utf-8")
    return out


# ──────────────────────────────────────────────────────────────────────
# Section 渲染器
# ──────────────────────────────────────────────────────────────────────

def _render_header(plan: dict, meta: dict) -> str:
    return (
        f"# ChemMaster Run Report — `{plan['task_id']}`\n\n"
        f"**User intent:** {plan.get('user_intent', '(empty)')}  \n"
        f"**Workflow:** `{plan.get('inferred_workflow', '?')}`  \n"
        f"**Created at:** {plan.get('created_at', '?')}  \n"
        f"**Generated at:** {meta.get('timestamp', '?')}\n"
    )


def _render_target_system(plan: dict) -> str:
    sys_ = plan.get("target_system") or {}
    lines = ["## 1. Target system\n"]
    rows = [
        ("Formula", sys_.get("formula")),
        ("SMILES", sys_.get("smiles")),
        ("Charge", sys_.get("charge")),
        ("Multiplicity", sys_.get("multiplicity")),
        ("# atoms", sys_.get("n_atoms")),
        ("Notes", sys_.get("notes")),
    ]
    lines.append("| field | value |")
    lines.append("|---|---|")
    for k, v in rows:
        if v is None or v == "":
            continue
        lines.append(f"| {k} | `{v}` |")
    if sys_.get("geometry_xyz"):
        lines.append("\n```xyz")
        lines.append(sys_["geometry_xyz"].rstrip())
        lines.append("```")
    return "\n".join(lines)


def _render_plan_summary(plan: dict) -> str:
    steps = plan.get("steps") or []
    if not steps:
        return ""
    lines = ["## 2. Plan summary\n"]
    lines.append("| # | name | skill | est. wall-time | rationale |")
    lines.append("|---|---|---|---|---|")
    pipe = "|"
    escaped_pipe = "\\|"
    for i, s in enumerate(steps, 1):
        cost = s.get("estimated_cost") or {}
        wt = cost.get("wall_clock_s")
        wt_str = f"{wt:.0f}s" if isinstance(wt, (int, float)) else "?"
        rationale = (s.get("rationale") or "").replace(pipe, escaped_pipe)
        skill_name = s.get("skill") or "-"
        lines.append(
            f"| {i} | {s.get('name', '?')} | `{skill_name}` | {wt_str} | {rationale} |"
        )
    return "\n".join(lines)


def _render_step_details(plan: dict, steps: list[dict]) -> str:
    if not steps:
        return ""
    parts = ["## 3. Step-by-step results\n"]
    for s in steps:
        parts.append(_render_one_step(s))
    return "\n\n".join(parts)


def _render_one_step(step: dict) -> str:
    name = step["name"]
    idx = step["idx"]
    result = step.get("result") or {}
    warnings = step.get("warnings") or []

    lines = [f"### Step {idx:02d} — {name}\n"]
    if not result.get("ok", False):
        lines.append(f"**Status:** ❌ FAILED — `{result.get('error_code', '?')}`")
        if result.get("details"):
            lines.append(f"  \n_Details_: {result['details']}")
        if result.get("suggestion"):
            lines.append(f"  \n_Suggestion_: {result['suggestion']}")
        return "\n".join(lines)

    lines.append("**Status:** ✓ OK")

    inner = result.get("result") or {}
    # 能量
    energy = (
        inner.get("final_energy")
        or inner.get("energy")
    )
    if energy and "value" in energy:
        e_Eh = energy["value"]
        lines.append("")
        lines.append("| quantity | value | unit |")
        lines.append("|---|---|---|")
        lines.append(f"| Final energy | `{e_Eh:.6f}` | Hartree |")
        try:
            lines.append(f"| Final energy | `{U.hartree_to_kcal_per_mol(e_Eh):.3f}` | kcal/mol |")
            lines.append(f"| Final energy | `{U.hartree_to_eV(e_Eh):.4f}` | eV |")
        except Exception:
            pass

    # 收敛 / 步数
    if "converged" in inner:
        lines.append(f"- Converged: **{inner['converged']}**")
    if "n_iterations" in inner and inner["n_iterations"]:
        lines.append(f"- Iterations: {inner['n_iterations']}")

    # 频率块
    if "frequencies_cm_inv" in inner and inner["frequencies_cm_inv"]:
        freqs = inner["frequencies_cm_inv"]
        ints = inner.get("ir_intensities_km_per_mol") or []
        n_imag = inner.get("n_imaginary", 0)
        lines.append(f"- # imaginary frequencies: **{n_imag}**")
        zpe = inner.get("zpe")
        if zpe and "value" in zpe:
            lines.append(f"- ZPE: `{zpe['value']:.6f}` Hartree")
        tc = inner.get("thermal_corrections") or {}
        for label, key in (("H_corr (RRHO)", "h_corr"),
                           ("G_corr (RRHO)", "g_corr"),
                           ("TS (RRHO)", "ts")):
            v = tc.get(key)
            if v and "value" in v:
                lines.append(f"- {label}: `{v['value']:.6f}` Hartree")
        if tc.get("method"):
            lines.append(f"- RRHO method: `{tc['method']}`")
        # frequency table（top 10）
        lines.append("\n| # | freq (cm⁻¹) | IR (km/mol) |")
        lines.append("|---|---|---|")
        top = list(zip(freqs[:10], (ints + [None] * 10)[:10]))
        for j, (f, ii) in enumerate(top, 1):
            ii_s = f"{ii:.2f}" if isinstance(ii, (int, float)) else "—"
            lines.append(f"| {j} | {f:.2f} | {ii_s} |")

    # HOMO-LUMO + dipole
    gap = inner.get("homo_lumo_gap")
    if gap and "value" in gap:
        lines.append(f"- HOMO–LUMO gap: `{gap['value']:.4f}` {gap.get('unit', '')}")
    dip = inner.get("dipole")
    if dip and "value" in dip:
        lines.append(f"- Dipole moment: `{dip['value']:.4f}` {dip.get('unit', '')}")

    # warnings
    if warnings:
        lines.append("\n**Warnings:**")
        for w in warnings:
            lines.append(f"- {w}")

    # 软件版本 / 耗时
    meta = result.get("meta") or {}
    if meta:
        info = []
        for k in ("psi4_version", "xtb_version", "wall_time_s"):
            if k in meta:
                info.append(f"{k}=`{meta[k]}`")
        if info:
            lines.append("")
            lines.append("_Engine meta:_ " + " · ".join(info))
    return "\n".join(lines)


def _render_key_results(steps: list[dict]) -> str:
    """汇总：最终能量、ZPE、G(298 K)、虚频数、最终几何。"""
    if not steps:
        return ""
    last_energy = None
    last_zpe = None
    last_g = None
    last_h = None
    last_n_imag = None
    last_geom = None
    for s in steps:
        inner = ((s.get("result") or {}).get("result")) or {}
        e = inner.get("final_energy") or inner.get("energy")
        if e and "value" in e:
            last_energy = e
        if inner.get("optimized_geometry_xyz"):
            last_geom = inner["optimized_geometry_xyz"]
        zpe = inner.get("zpe")
        if zpe:
            last_zpe = zpe
        tc = inner.get("thermal_corrections") or {}
        if tc.get("g_corr"):
            last_g = tc["g_corr"]
        if tc.get("h_corr"):
            last_h = tc["h_corr"]
        if "n_imaginary" in inner:
            last_n_imag = inner["n_imaginary"]

    lines = ["## 4. Key results\n", "| metric | value | unit |", "|---|---|---|"]
    if last_energy:
        e_Eh = last_energy["value"]
        lines.append(f"| Electronic energy | `{e_Eh:.6f}` | Hartree |")
        try:
            lines.append(f"| Electronic energy | `{U.hartree_to_kcal_per_mol(e_Eh):.2f}` | kcal/mol |")
        except Exception:
            pass
    if last_zpe:
        lines.append(f"| ZPE | `{last_zpe['value']:.6f}` | Hartree |")
    if last_h:
        lines.append(f"| H_corr (298 K) | `{last_h['value']:.6f}` | Hartree |")
    if last_g:
        lines.append(f"| G_corr (298 K) | `{last_g['value']:.6f}` | Hartree |")
    if last_energy and last_g:
        g_total = last_energy["value"] + last_g["value"]
        lines.append(f"| **G (298 K, total)** | `{g_total:.6f}` | **Hartree** |")
    if last_n_imag is not None:
        marker = "✓" if last_n_imag == 0 else "⚠"
        lines.append(f"| # imaginary frequencies | {last_n_imag} {marker} | — |")
    if last_geom:
        lines.append("\n**Optimized geometry (XYZ):**\n")
        lines.append("```xyz")
        lines.append(last_geom.rstrip())
        lines.append("```")
    return "\n".join(lines)


def _render_citations(plan: dict) -> str:
    cites = plan.get("citations") or []
    if not cites:
        return ""
    lines = ["## 5. Citations\n"]
    for c in cites:
        score = f" (RAG score {c['score']:.2f})" if c.get("score") is not None else ""
        lines.append(f"- {c['text']} — `{c['source']}`{score}")
    return "\n".join(lines)


def _render_reproducibility(meta: dict, plan: dict) -> str:
    lines = ["## 6. Reproducibility\n"]
    lines.append("| field | value |")
    lines.append("|---|---|")
    for k in ("chemaster_version", "python_version", "git_commit", "timestamp"):
        v = meta.get(k)
        if v:
            lines.append(f"| {k} | `{v}` |")
    lines.append(f"| task_id | `{plan['task_id']}` |")
    lines.append(
        "\n_To replay this run bit-perfectly:_  "
        f"`chemaster replay {plan['task_id']}`  "
        "(Phase 5)"
    )
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _load_or_empty(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _collect_step_results(task_dir: Path) -> list[dict]:
    """扫 task_dir 下所有 step_NN_*/ 子目录，按 NN 排序。"""
    out: list[dict] = []
    for sub in sorted(task_dir.iterdir()):
        if not sub.is_dir():
            continue
        if not sub.name.startswith("step_"):
            continue
        # step_NN_<slug>
        try:
            idx = int(sub.name.split("_")[1])
        except (IndexError, ValueError):
            continue
        name = "_".join(sub.name.split("_")[2:]) or sub.name
        result = _load_or_empty(sub / "result.json")
        warnings_blob = _load_or_empty(sub / "warnings.json")
        out.append({
            "idx": idx,
            "name": name,
            "result": result,
            "warnings": warnings_blob.get("warnings") or [],
            "step_dir": sub,
        })
    return out


# ──────────────────────────────────────────────────────────────────────
# CLI hook
# ──────────────────────────────────────────────────────────────────────

def _cli_main(argv: list[str] | None = None) -> int:
    """``python -m chemaster.agent.reporter <task_dir>`` 入口。"""
    import sys

    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: python -m chemaster.agent.reporter <task_dir>", file=sys.stderr)
        return 1
    out = generate_report(args[0])
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_main())
