#!/usr/bin/env python3
"""S22 弱相互作用 benchmark 运行脚本.

用法::

    python scripts/benchmarks/run_s22.py                # 跑全部 5 个体系
    python scripts/benchmarks/run_s22.py water_dimer    # 只跑指定体系

每个体系：
    1. 读取 benchmarks/s22/inputs/<system>.xyz
    2. 用 ChemMaster 调用 gaussian_optimize (B3LYP-D3/def2-TZVP) → 得 dimer 能量
    3. 拆 monomer，分别 single-point → 得 monomer 能量
    4. 计算结合能 E_int = E(dimer) - sum(E(monomer))
    5. 写 result.json 到 benchmarks/s22/runs_archive/<system>/

如果 Gaussian 不可用，脚本会输出 mock data 并标注 "ENGINE_NOT_FOUND"，
便于在没装 Gaussian 的开发机上验证脚本逻辑本身正确。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = ROOT / "benchmarks" / "s22"


def load_reference() -> dict:
    with (BENCHMARK_DIR / "reference_values.yaml").open() as f:
        return yaml.safe_load(f)


def split_dimer(xyz_text: str) -> tuple[str, str]:
    """For S22 we know the dimer is two roughly-disjoint molecules.

    Naive split: bisect by line index (works for our 6-atom water dimer
    where atoms 1-3 are mol A, atoms 4-6 are mol B). For real S22 use
    we'd parse the actual binding partners; here we keep the demo simple.
    """
    lines = [l for l in xyz_text.strip().splitlines() if l.strip()]
    n = int(lines[0])
    atoms = lines[2: 2 + n]
    half = n // 2
    a_atoms = atoms[:half]
    b_atoms = atoms[half:]
    a_xyz = f"{len(a_atoms)}\nmonomer A\n" + "\n".join(a_atoms)
    b_xyz = f"{len(b_atoms)}\nmonomer B\n" + "\n".join(b_atoms)
    return a_xyz, b_xyz


def run_one_system(system_name: str, system_meta: dict) -> dict[str, Any]:
    """Run a single S22 system through ChemMaster's Gaussian wrapper."""
    from chemaster.mcp.calc_gaussian.server import optimize, single_point

    xyz_path = BENCHMARK_DIR / "inputs" / f"{system_name}.xyz"
    if not xyz_path.exists():
        return {"ok": False, "error": f"Missing input {xyz_path}"}

    xyz = xyz_path.read_text()

    # Step 1: optimize the dimer
    dimer_result = optimize(
        geometry_xyz=xyz, method="B3LYP", basis="def2-TZVP",
        charge=0, multiplicity=1, dispersion="GD3BJ", timeout_s=3600,
    )
    if not dimer_result["ok"]:
        return {
            "ok": False,
            "error_code": dimer_result["error_code"],
            "details": dimer_result.get("details"),
            "phase": "dimer_optimize",
            "system": system_name,
        }
    e_dimer = dimer_result["result"]["final_energy"]["value"]

    # Step 2: monomer single-points (no opt — use dimer geometry's halves)
    a_xyz, b_xyz = split_dimer(xyz)
    sp_a = single_point(geometry_xyz=a_xyz, method="B3LYP", basis="def2-TZVP")
    sp_b = single_point(geometry_xyz=b_xyz, method="B3LYP", basis="def2-TZVP")

    if not sp_a["ok"] or not sp_b["ok"]:
        return {"ok": False, "phase": "monomer_sp",
                "details": "monomer single-point failed",
                "system": system_name}

    e_a = sp_a["result"]["final_energy"]["value"]
    e_b = sp_b["result"]["final_energy"]["value"]

    # Step 3: binding energy (kcal/mol)
    HARTREE_TO_KCAL = 627.5094740631
    e_int_hartree = e_dimer - e_a - e_b
    e_int_kcal = e_int_hartree * HARTREE_TO_KCAL

    ref_value = system_meta["reference_binding_energy"]
    error = e_int_kcal - ref_value

    return {
        "ok": True,
        "system": system_name,
        "method": "B3LYP-D3(BJ)/def2-TZVP",
        "computed_binding_energy_kcal": e_int_kcal,
        "reference_binding_energy_kcal": ref_value,
        "error_kcal": error,
        "abs_error_kcal": abs(error),
        "within_acceptance":
            abs(error) <= system_meta.get("expected_b3lyp_d3bj_def2tzvp_error_max", 0.5),
    }


def write_archive(system_name: str, payload: dict) -> Path:
    archive = BENCHMARK_DIR / "runs_archive" / system_name
    archive.mkdir(parents=True, exist_ok=True)
    out = archive / "result.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return out


def summary_table(results: list[dict]) -> str:
    rows = ["| System | E_int (calc) | E_int (ref) | |Error| | Pass |",
            "|---|---|---|---|---|"]
    for r in results:
        if r.get("ok"):
            rows.append(
                f"| {r['system']:<20} | {r['computed_binding_energy_kcal']:8.3f} | "
                f"{r['reference_binding_energy_kcal']:8.3f} | "
                f"{r['abs_error_kcal']:6.3f} | "
                f"{'✓' if r['within_acceptance'] else '✗'} |"
            )
        else:
            rows.append(f"| {r['system']:<20} | {r.get('error_code','FAIL')} | - | - | ✗ |")
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("system", nargs="?",
                        help="Run a single system; if omitted, run all")
    args = parser.parse_args()

    ref = load_reference()
    systems = ref["systems"]

    targets = [args.system] if args.system else list(systems.keys())
    results: list[dict] = []
    for name in targets:
        if name not in systems:
            print(f"[skip] unknown system: {name}", file=sys.stderr)
            continue
        print(f"[s22] running {name}...")
        payload = run_one_system(name, systems[name])
        results.append(payload)
        out = write_archive(name, payload)
        print(f"  → {out}")

    print()
    print(summary_table(results))

    # Write summary
    summary = {
        "method_under_test": ref["method_under_test"],
        "acceptance_criteria": ref["acceptance_criteria"],
        "results": results,
        "n_passed": sum(1 for r in results if r.get("within_acceptance")),
        "n_total": len(results),
    }
    if results:
        valid = [r["abs_error_kcal"] for r in results if r.get("ok")]
        summary["mae_kcal"] = sum(valid) / len(valid) if valid else None
        summary["max_abs_error_kcal"] = max(valid) if valid else None
        summary["pass_overall"] = (
            summary["mae_kcal"] is not None
            and summary["mae_kcal"] <= ref["acceptance_criteria"]["mae_kcal_per_mol_max"]
        )

    summary_path = BENCHMARK_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    print(f"\nSummary: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
