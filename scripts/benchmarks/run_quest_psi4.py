#!/usr/bin/env python3
"""QUEST 激发态垂直激发能 — psi4 实跑.

每个分子：
  1. SCF 基态
  2. TDDFT 计算 N 个最低单重激发态（CIS-like in psi4 means TDA TDDFT）
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = ROOT / "benchmarks" / "quest"


def run_psi4_tddft(xyz_text: str, label: str, *, n_states: int = 4,
                   method: str = "B3LYP", basis: str = "def2-SVP",
                   scratch=None) -> tuple[list[dict], float]:
    """Run a TDDFT calculation in psi4. Returns list of state dicts + wall.

    psi4's TDDFT-TDA is invoked via the `tdscf` energy (see psi4 manual).
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
    mol_text = "0 1\n" + "\n".join(atoms) + "\nsymmetry c1\nno_reorient\nno_com"
    mol = psi4.geometry(mol_text)

    psi4.set_options({
        "basis": basis,
        "scf_type": "df",
        "reference": "rks",
        "TDSCF_STATES": [n_states],
        "TDSCF_TDA": True,
    })

    t0 = time.time()
    e0, wfn = psi4.energy(method, molecule=mol, return_wfn=True)
    psi4.tdscf(wfn, states=n_states, tda=True)
    wall = time.time() - t0

    states = []
    HARTREE_TO_EV = 27.21138624598853
    # In psi4 1.10 the results land in scalar_variables under names like
    # "TD-DFT ROOT 0 -> ROOT 1 EXCITATION ENERGY".
    for i in range(1, n_states + 1):
        ex_var = f"TD-DFT ROOT 0 -> ROOT {i} EXCITATION ENERGY"
        os_var = f"TD-DFT ROOT 0 -> ROOT {i} OSCILLATOR STRENGTH (LEN)"
        ex_e_au = 0.0
        f_osc = 0.0
        try:
            ex_e_au = psi4.core.variable(ex_var)
        except Exception:
            pass
        try:
            f_osc = psi4.core.variable(os_var)
        except Exception:
            pass
        states.append({
            "state": i,
            "energy_eV": round(float(ex_e_au) * HARTREE_TO_EV, 3),
            "oscillator_strength": round(float(f_osc), 4),
        })

    psi4.core.clean()
    return states, wall


def run_one_molecule(name: str, meta: dict, n_states: int = 4) -> dict:
    xyz_path = BENCHMARK_DIR / "inputs" / f"{name}.xyz"
    if not xyz_path.exists():
        return {"ok": False, "system": name, "error": f"missing {xyz_path}"}

    xyz = xyz_path.read_text()
    print(f"  [{name}] TDDFT (TDA, CAM-B3LYP, def2-SVP, {n_states} states)...", flush=True)
    try:
        states, wall = run_psi4_tddft(xyz, name, n_states=n_states,
                                        method="CAM-B3LYP", basis="def2-SVP")
    except Exception as exc:
        return {"ok": False, "system": name, "error": str(exc)}

    # Compare against singlet states from reference
    ref_singlets = [s for s in meta["excited_states"] if s["spin"] == "singlet"]
    matched = []
    for i, computed in enumerate(states):
        if i < len(ref_singlets):
            ref = ref_singlets[i]
            err = computed["energy_eV"] - ref["vee_cc3"]
            matched.append({
                "state_idx": i + 1,
                "computed_eV": computed["energy_eV"],
                "ref_cc3_eV": ref["vee_cc3"],
                "ref_character": ref["character"],
                "error_eV": round(err, 3),
                "abs_error_eV": round(abs(err), 3),
                "oscillator_strength": computed["oscillator_strength"],
            })

    abs_errors = [m["abs_error_eV"] for m in matched]
    return {
        "ok": True,
        "data_source": "real_psi4",
        "system": name,
        "formula": meta["formula"],
        "method": "TD-CAM-B3LYP/def2-SVP, TDA, via psi4 1.10",
        "states": matched,
        "mae_eV": round(sum(abs_errors) / len(abs_errors), 3) if abs_errors else None,
        "max_abs_error_eV": round(max(abs_errors), 3) if abs_errors else None,
        "wall_time_s": round(wall, 1),
    }


def main() -> int:
    ref = yaml.safe_load((BENCHMARK_DIR / "reference_values.yaml").read_text())

    # We have only formaldehyde xyz file ready; the others need to be added.
    # Run whichever is available.
    targets = [name for name in ref["systems"]
               if (BENCHMARK_DIR / "inputs" / f"{name}.xyz").exists()]
    print(f"Running {len(targets)} QUEST molecule(s) via psi4...")
    print()

    results = []
    for name in targets:
        result = run_one_molecule(name, ref["systems"][name], n_states=3)
        results.append(result)
        archive = BENCHMARK_DIR / "runs_archive" / name
        archive.mkdir(parents=True, exist_ok=True)
        (archive / "result.json").write_text(json.dumps(result, indent=2,
                                                          ensure_ascii=False))
        if result.get("ok"):
            print(f"  → {name}: MAE={result['mae_eV']} eV, max={result['max_abs_error_eV']} eV "
                  f"(wall {result['wall_time_s']}s)")
            for s in result["states"]:
                print(f"    state {s['state_idx']}: {s['computed_eV']} vs CC3 {s['ref_cc3_eV']} "
                      f"({s['ref_character']}), err {s['error_eV']:+.3f}")
        else:
            print(f"  ✗ {name}: {result.get('error', 'unknown')}")
        print()

    valid = [r for r in results if r.get("ok")]
    if valid:
        all_errors = [m["abs_error_eV"] for r in valid for m in r["states"]]
        summary = {
            "data_source": "real_psi4",
            "method_under_test": {
                "functional": "CAM-B3LYP",
                "basis": "def2-SVP",
                "engine": "psi4 1.10",
                "tda": True,
                "note": "Run with psi4 (Gaussian unavailable). def2-SVP used for speed.",
            },
            "acceptance_criteria": ref["acceptance_criteria"],
            "results": results,
            "n_states_total": len(all_errors),
            "mae_eV": round(sum(all_errors) / len(all_errors), 3),
            "max_abs_error_eV": round(max(all_errors), 3),
            "n_passed": sum(1 for e in all_errors
                            if e <= ref["acceptance_criteria"]["per_state_max_error_eV"]),
            "pass_overall": (sum(all_errors) / len(all_errors)
                             <= ref["acceptance_criteria"]["mae_eV_max"]),
        }
    else:
        summary = {"data_source": "real_psi4", "ok": False, "results": results}
    (BENCHMARK_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nSummary written to {BENCHMARK_DIR / 'summary.json'}")
    if "mae_eV" in summary:
        print(f"MAE = {summary['mae_eV']} eV ({summary['n_passed']}/{summary['n_states_total']} states pass)")
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
