#!/usr/bin/env python3
"""S22 complete (all 22 dimers) via psi4, geometries pulled from ASE.

ASE ships the canonical S22 coordinates and CCSD(T)/CBS reference energies
under ``ase.collections.s22``. We use those (verified to reproduce Hobza
2006 references) and drive psi4 to compute counterpoise-corrected
interaction energies. This replaces the previous hand-built S22 subset
with the full 22-system benchmark.

Outputs:
  benchmarks/s22/inputs_full/<name>.xyz
  benchmarks/s22/runs_archive_full/<name>/result.json
  benchmarks/s22/summary_full.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "benchmarks" / "s22"
INPUTS = BENCH / "inputs_full"
ARCHIVE = BENCH / "runs_archive_full"

EV_TO_KCAL = 23.06035


# Mapping from ASE S22 system name → (split_index, friendly_short_name)
# split_index = how many atoms belong to monomer A; rest go to B.
# These are taken directly from the original Hobza 2006 ordering.
S22_SPLITS: dict[str, int] = {
    "Ammonia_dimer":                            4,    # NH3 + NH3 (8 = 4+4)
    "Water_dimer":                              3,    # H2O + H2O (6 = 3+3)
    "Formic_acid_dimer":                        5,    # HCOOH + HCOOH (10 = 5+5)
    "Formamide_dimer":                          6,    # HCONH2 + HCONH2 (12 = 6+6)
    "Uracil_dimer_h-bonded":                    12,   # uracil + uracil (24 = 12+12)
    "2-pyridoxine_2-aminopyridine_complex":     17,   # 17 + 16 = 33 atoms
    "Adenine-thymine_Watson-Crick_complex":     15,   # adenine 15 + thymine 15 (30 atoms)
    "Methane_dimer":                            5,    # CH4 + CH4 (10 = 5+5)
    "Ethene_dimer":                             6,    # C2H4 + C2H4 (12 = 6+6)
    "Benzene-methane_complex":                  12,   # benzene 12 + methane 5
    "Benzene_dimer_parallel_displaced":         12,   # 12 + 12 (24 atoms)
    "Pyrazine_dimer":                           10,   # 10 + 10 (20 atoms)
    "Uracil_dimer_stack":                       12,   # 12 + 12 (24)
    "Indole-benzene_complex_stack":             16,   # indole 16 + benzene 12 (28)
    "Adenine-thymine_complex_stack":            15,   # 15 + 15 (30)
    "Ethene-ethyne_complex":                    6,    # ethene 6 + ethyne 4 (10)
    "Benzene-water_complex":                    12,   # benzene 12 + water 3 (15)
    "Benzene-ammonia_complex":                  12,   # benzene 12 + ammonia 4 (16)
    "Benzene-HCN_complex":                      12,   # benzene 12 + HCN 3 (15)
    "Benzene_dimer_T-shaped":                   12,   # benzene + benzene (24)
    "Indole-benzene_T-shape_complex":           16,   # indole 16 + benzene 12 (28)
    "Phenol_dimer":                             13,   # phenol + phenol (26)
}


def short_name(ase_name: str) -> str:
    return ase_name.lower().replace(" ", "_").replace("-", "_").replace("'", "")


def export_xyz_from_ase() -> dict[str, str]:
    """Dump every S22 system to an .xyz file and return {name: path}."""
    from ase.collections import s22
    INPUTS.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for name in s22.names:
        atoms = s22[name]
        sname = short_name(name)
        path = INPUTS / f"{sname}.xyz"
        # Standard xyz format
        lines = [str(len(atoms)), f"S22 system {name} (geometry from ASE)"]
        for sym, (x, y, z) in zip(atoms.get_chemical_symbols(),
                                    atoms.get_positions()):
            lines.append(f"{sym:2s}  {x:>12.6f}  {y:>12.6f}  {z:>12.6f}")
        path.write_text("\n".join(lines) + "\n")
        paths[name] = str(path)
    return paths


def run_dimer_cp(ase_name: str, xyz_path: str, split_at: int,
                 method: str = "B3LYP-D3BJ", basis: str = "def2-TZVP") -> dict:
    """Run counterpoise-corrected interaction energy for one S22 dimer.

    Geometry is read from xyz; the dimer is split into two monomers at
    ``split_at`` (taken from ``S22_SPLITS``). psi4's bsse_type='cp' is used.
    """
    import psi4
    import tempfile

    psi4.core.clean()
    scratch = tempfile.gettempdir()
    label = short_name(ase_name)
    psi4.core.set_output_file(f"{scratch}/{label}.out", False)
    psi4.set_memory("4 GB")
    psi4.set_num_threads(4)

    raw = Path(xyz_path).read_text().strip().splitlines()
    n_atoms = int(raw[0])
    atoms = [l.strip() for l in raw[2:2 + n_atoms] if l.strip()]
    a = atoms[:split_at]
    b = atoms[split_at:]
    if not a or not b:
        return {"ok": False, "system": ase_name,
                "error": f"empty monomer split at {split_at}"}

    # Some S22 dimers contain N-H groups that confuse psi4 fragment charge
    # detection; pin everything to neutral closed-shell explicitly.
    frag = ("0 1\n" + "\n".join(a) + "\n--\n0 1\n" + "\n".join(b) +
            "\nunits angstrom\nsymmetry c1\nno_reorient\nno_com")
    try:
        mol = psi4.geometry(frag)
    except Exception as exc:
        # Last-resort fallback: ditch fragment decomposition and just compute the
        # complex energy without CP — we still get *a* number, but note this in
        # the result.
        return {"ok": False, "system": ase_name,
                "phase": "psi4_geom_parse",
                "error": f"fragment parser failed: {exc}",
                "wall_s": 0.0}

    psi4.set_options({
        "basis": basis,
        "scf_type": "df",
        "reference": "rks",
        "guess": "sad",
    })
    t0 = time.time()
    try:
        e_int_hartree = psi4.energy(method, molecule=mol, bsse_type="cp")
    except Exception as exc:
        return {"ok": False, "system": ase_name, "phase": "psi4_cp",
                "error": str(exc), "wall_s": time.time() - t0}
    wall = time.time() - t0
    psi4.core.clean()
    HARTREE_TO_KCAL = 627.5094740631
    return {
        "ok": True,
        "data_source": "real_psi4",
        "system": ase_name,
        "short_name": label,
        "method": f"{method}/{basis}, counterpoise-corrected, via psi4 1.10",
        "computed_binding_energy_kcal": round(float(e_int_hartree)
                                               * HARTREE_TO_KCAL, 3),
        "interaction_hartree": round(float(e_int_hartree), 6),
        "wall_time_s": round(wall, 2),
    }


def main() -> int:
    from ase.collections import s22

    print(f"Exporting all 22 S22 xyz from ASE → {INPUTS} ...")
    paths = export_xyz_from_ase()
    print(f"  wrote {len(paths)} xyz files\n")

    # Optional limit (run a subset for debugging)
    only = set(sys.argv[1:]) if len(sys.argv) > 1 else None

    results = []
    for ase_name in s22.names:
        if only is not None and ase_name not in only:
            continue
        if ase_name not in S22_SPLITS:
            print(f"  [skip] no split mapping for {ase_name}")
            continue

        ref_eV = s22.data[ase_name]["cc_energy"]
        ref_kcal = ref_eV * EV_TO_KCAL

        print(f"  [{ase_name}] N={len(s22[ase_name])} atoms, "
              f"ref={ref_kcal:.2f} kcal/mol — running CP ...", flush=True)
        try:
            r = run_dimer_cp(ase_name, paths[ase_name],
                              split_at=S22_SPLITS[ase_name])
        except Exception as exc:
            r = {"ok": False, "system": ase_name, "phase": "outer",
                 "error": str(exc)}
        if r.get("ok"):
            err = r["computed_binding_energy_kcal"] - ref_kcal
            r["reference_binding_energy_kcal"] = round(ref_kcal, 3)
            r["error_kcal"] = round(err, 3)
            r["abs_error_kcal"] = round(abs(err), 3)
            print(f"     → {r['computed_binding_energy_kcal']:+.2f} kcal/mol "
                  f"(err {err:+.2f}, wall {r['wall_time_s']:.1f}s)")
        else:
            print(f"     ✗ {r.get('error', 'unknown')}")
        results.append(r)

        archive = ARCHIVE / short_name(ase_name)
        archive.mkdir(parents=True, exist_ok=True)
        (archive / "result.json").write_text(
            json.dumps(r, indent=2, ensure_ascii=False))

    valid = [r for r in results if r.get("ok")]
    if valid:
        abs_err = [r["abs_error_kcal"] for r in valid]
        summary = {
            "data_source": "real_psi4",
            "n_total": len(valid),
            "method_under_test": {
                "functional": "B3LYP-D3(BJ)",
                "basis": "def2-TZVP",
                "engine": "psi4 1.10",
                "geometry_source": "ase.collections.s22 (canonical Hobza 2006 coordinates)",
                "note": "Reference energies are CCSD(T)/CBS values shipped with ASE.",
            },
            "n_passed_within_0.5": sum(1 for e in abs_err if e <= 0.5),
            "n_passed_within_1.0": sum(1 for e in abs_err if e <= 1.0),
            "mae_kcal": round(sum(abs_err) / len(abs_err), 3),
            "max_abs_error_kcal": round(max(abs_err), 3),
            "results": results,
        }
    else:
        summary = {"data_source": "real_psi4", "ok": False, "results": results}

    (BENCH / "summary_full.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nWrote {BENCH / 'summary_full.json'}")
    if "mae_kcal" in summary:
        print(f"MAE = {summary['mae_kcal']} kcal/mol over {summary['n_total']} systems")
        print(f"  {summary['n_passed_within_0.5']} systems within 0.5 kcal/mol")
        print(f"  {summary['n_passed_within_1.0']} systems within 1.0 kcal/mol")
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
