#!/usr/bin/env python3
"""S22 子集结合能 — 用 psi4 实跑（替代 Gaussian wrapper）.

由于本机没有 Gaussian 许可，本脚本用 psi4（同样实现 B3LYP-D3/def2-TZVP）
替代 Gaussian 跑 S22 子集的结合能。在论文 §4.2.1 中需明确说明。

每个体系：
  1. dimer single-point B3LYP-D3(BJ)/def2-TZVP
  2. monomer A single-point at dimer geometry
  3. monomer B single-point at dimer geometry
  4. binding energy = E(dimer) - E(A) - E(B)（无 BSSE 校正以求快）

运行需要：/opt/miniconda3/bin/python（已装 psi4 1.10）
预计耗时：5 个体系合计约 5-15 分钟。

用法：
    /opt/miniconda3/bin/python scripts/benchmarks/run_s22_psi4.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = ROOT / "benchmarks" / "s22"


def run_psi4_single_point(xyz_text: str, label: str, *, method="B3LYP-D3BJ",
                          basis="def2-TZVP", scratch=None) -> tuple[float, float]:
    """Drive psi4 from Python API. Returns (energy_hartree, wall_time_s)."""
    import psi4
    psi4.core.clean()
    if scratch is None:
        import tempfile
        scratch = tempfile.gettempdir()
    psi4.core.set_output_file(f"{scratch}/{label}.out", False)
    psi4.set_memory("4 GB")
    psi4.set_num_threads(4)

    # Construct molecule from xyz text. psi4 expects:
    #   charge multiplicity
    #   ATOM x y z
    lines = [l for l in xyz_text.strip().splitlines() if l.strip()]
    n_atoms = int(lines[0])
    atoms = lines[2:2 + n_atoms]
    mol_text = "0 1\n" + "\n".join(atoms) + "\nsymmetry c1\nno_reorient\nno_com"
    mol = psi4.geometry(mol_text)

    psi4.set_options({
        "basis": basis,
        "scf_type": "df",
        "reference": "rks",
        "guess": "sad",
    })

    t0 = time.time()
    energy = psi4.energy(method, molecule=mol)
    wall = time.time() - t0
    psi4.core.clean()
    return float(energy), wall


def run_psi4_dimer_cp(xyz_text: str, system_name: str, label: str, *,
                     method="B3LYP-D3BJ", basis="def2-TZVP",
                     scratch=None) -> tuple[float, float]:
    """Run a counterpoise-corrected dimer interaction energy in psi4.

    Returns (interaction_energy_hartree, wall_time_s). The CP procedure
    computes the dimer and each monomer in the full dimer basis,
    yielding a BSSE-corrected interaction energy directly.
    """
    import psi4
    psi4.core.clean()
    if scratch is None:
        import tempfile
        scratch = tempfile.gettempdir()
    psi4.core.set_output_file(f"{scratch}/{label}.out", False)
    psi4.set_memory("4 GB")
    psi4.set_num_threads(4)

    lines = [l for l in xyz_text.strip().splitlines() if l.strip()]
    n_atoms = int(lines[0])
    atoms = lines[2:2 + n_atoms]
    split_at = SPLIT_BY_SYSTEM.get(system_name, n_atoms // 2)
    a_atoms = atoms[:split_at]
    b_atoms = atoms[split_at:]

    # psi4 fragmented molecule: --- separator splits monomers
    frag_block = "0 1\n" + "\n".join(a_atoms) + "\n--\n0 1\n" + "\n".join(b_atoms)
    mol_text = frag_block + "\nsymmetry c1\nno_reorient\nno_com"
    mol = psi4.geometry(mol_text)

    psi4.set_options({
        "basis": basis,
        "scf_type": "df",
        "reference": "rks",
        "guess": "sad",
    })

    t0 = time.time()
    e_int = psi4.energy(method, molecule=mol, bsse_type="cp")
    wall = time.time() - t0
    psi4.core.clean()
    return float(e_int), wall


SPLIT_BY_SYSTEM = {
    "water_dimer":     3,    # 3 + 3
    "methane_dimer":   5,    # 5 + 5
    "ethene_ethyne":   6,    # ethene 6 + ethyne 4
    "benzene_methane": 12,   # benzene 12 + methane 5
    "benzene_dimer_T": 12,   # 12 + 12
}


def split_dimer(xyz_text: str, system_name: str) -> tuple[str, str]:
    """Split dimer xyz into two monomers using SPLIT_BY_SYSTEM table."""
    lines = [l for l in xyz_text.strip().splitlines() if l.strip()]
    n = int(lines[0])
    atoms = lines[2:2 + n]
    split_at = SPLIT_BY_SYSTEM.get(system_name, n // 2)
    a_atoms = atoms[:split_at]
    b_atoms = atoms[split_at:]
    a_xyz = f"{len(a_atoms)}\nmonomer A\n" + "\n".join(a_atoms)
    b_xyz = f"{len(b_atoms)}\nmonomer B\n" + "\n".join(b_atoms)
    return a_xyz, b_xyz


def run_one_system(name: str, meta: dict) -> dict:
    """Run counterpoise-corrected interaction energy for an S22 system."""
    xyz_path = BENCHMARK_DIR / "inputs" / f"{name}.xyz"
    if not xyz_path.exists():
        return {"ok": False, "system": name, "error": f"missing {xyz_path}"}

    xyz = xyz_path.read_text()
    print(f"  [{name}] running CP-corrected interaction energy...", flush=True)
    try:
        e_int_hartree, t_total = run_psi4_dimer_cp(xyz, name, name)
    except Exception as exc:
        return {"ok": False, "system": name, "phase": "cp_calc", "error": str(exc)}

    HARTREE_TO_KCAL = 627.5094740631
    e_int_kcal = e_int_hartree * HARTREE_TO_KCAL

    ref = meta["reference_binding_energy"]
    err = e_int_kcal - ref
    return {
        "ok": True,
        "data_source": "real_psi4",
        "system": name,
        "method": "B3LYP-D3(BJ)/def2-TZVP, counterpoise-corrected, via psi4 1.10",
        "computed_binding_energy_kcal": round(e_int_kcal, 3),
        "reference_binding_energy_kcal": ref,
        "error_kcal": round(err, 3),
        "abs_error_kcal": round(abs(err), 3),
        "within_acceptance":
            abs(err) <= meta.get("expected_b3lyp_d3bj_def2tzvp_error_max", 0.5),
        "interaction_hartree": round(e_int_hartree, 6),
        "wall_time_s": round(t_total, 2),
        "geometry_note": (
            "water_dimer uses the standard S22 hydrogen-bonded geometry; "
            "other dimers use approximate near-equilibrium geometries due to "
            "lack of canonical S22A coordinates in our local copy. Direct "
            "comparison to S22A reference values is therefore strongest "
            "for water_dimer; other systems reflect both method and "
            "geometry approximation errors."
            if name != "water_dimer" else
            "Standard S22 hydrogen-bonded geometry (Hobza 2006)."
        ),
    }


def main() -> int:
    ref = yaml.safe_load((BENCHMARK_DIR / "reference_values.yaml").read_text())

    targets = list(ref["systems"].keys())
    if len(sys.argv) > 1:
        targets = [s for s in sys.argv[1:] if s in ref["systems"]]

    print(f"Running {len(targets)} S22 system(s) via psi4...")
    print()
    results = []
    for name in targets:
        result = run_one_system(name, ref["systems"][name])
        results.append(result)
        archive = BENCHMARK_DIR / "runs_archive" / name
        archive.mkdir(parents=True, exist_ok=True)
        (archive / "result.json").write_text(json.dumps(result, indent=2,
                                                          ensure_ascii=False))
        if result.get("ok"):
            wt = result['wall_time_s']
            wall = wt['total'] if isinstance(wt, dict) else wt
            print(f"  → {name}: E_int = {result['computed_binding_energy_kcal']} "
                  f"kcal/mol (ref {result['reference_binding_energy_kcal']}, "
                  f"err {result['error_kcal']:+.3f}, wall {wall:.1f}s)")
        else:
            print(f"  ✗ {name}: {result.get('error', 'unknown')}")
        print()

    # Aggregate
    valid = [r for r in results if r.get("ok")]
    if valid:
        abs_errors = [r["abs_error_kcal"] for r in valid]
        summary = {
            "data_source": "real_psi4",
            "method_under_test": {
                "functional": "B3LYP-D3(BJ)",
                "basis": "def2-TZVP",
                "engine": "psi4 1.10",
                "note": ("Run with psi4 instead of Gaussian (commercial license "
                         "unavailable). Same B3LYP-D3(BJ)/def2-TZVP method."),
            },
            "acceptance_criteria": ref["acceptance_criteria"],
            "results": results,
            "n_passed": sum(1 for r in valid if r["within_acceptance"]),
            "n_total": len(valid),
            "mae_kcal": round(sum(abs_errors) / len(abs_errors), 3),
            "max_abs_error_kcal": round(max(abs_errors), 3),
            "pass_overall": (sum(abs_errors) / len(abs_errors)
                             <= ref["acceptance_criteria"]["mae_kcal_per_mol_max"]),
        }
    else:
        summary = {"data_source": "real_psi4", "ok": False, "results": results}

    (BENCHMARK_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nSummary written to {BENCHMARK_DIR / 'summary.json'}")
    if "mae_kcal" in summary:
        print(f"MAE = {summary['mae_kcal']} kcal/mol  ({summary['n_passed']}/{summary['n_total']} pass)")
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
