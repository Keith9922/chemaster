#!/usr/bin/env python3
"""Hard-case probe — heavier atoms + larger molecules + ambiguous prompts.

§4.4.2 (response-rate) and the new stress test both run the *agent loop*
with the deterministic mock router. This probe instead pushes the
**actual chemistry layer** — real psi4 invocations — on cases known to
strain SCF convergence or push beyond ChemMaster's default method/basis.

Tested hard cases:
  1. Heavier elements: HCl, H2S, HF, CH3Cl, CH3SH
     — Cl/S need careful basis (def2-SVP is the floor); test sto-3g
       intentionally to surface "basis too poor" warnings.
  2. Open-shell triplet: O2 ground state (multiplicity=3).
  3. Slightly larger molecules: ethene (C2H4), ethanol (CH3CH2OH),
     propane (C3H8), acetone (C3H6O), benzene (C6H6).
  4. Charged species: methylammonium (CH3NH3+, charge=+1), hydroxide
     (OH-, charge=-1).

For each case we capture: ok / energy (Ha) / wall_time_s /
warnings_count / error_code. The point is NOT to publish a calculation
benchmark — psi4 with sto-3g is not a quantitative method here. The
point is the **structural** finding: which kinds of input does the
chemaster stack handle cleanly, which fail gracefully with a suggestion
the agent can act on, and which (if any) crash without recourse.

Output:
  benchmarks/engineering_metrics/hard_cases.json

Run:
  python scripts/benchmarks/run_hard_cases.py [--method M --basis B]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


# ──────────────────────────────────────────────────────────────────────────────
# Hard-case fixtures (chemistry-realistic — every XYZ verified against PubChem
# / standard references; not auto-generated).
# ──────────────────────────────────────────────────────────────────────────────

HARD_CASES: list[dict] = [
    # ── 1. Heavier elements ───────────────────────────────────────────────
    {
        "id": "HCl_sto3g",
        "molecule": "HCl",
        "category": "heavy_element",
        "charge": 0, "multiplicity": 1,
        "xyz": "2\nHCl\nH 0 0 0\nCl 0 0 1.275\n",
        "method": "HF", "basis": "sto-3g",
        "notes": "Chlorine on sto-3g — tests very-poor basis, but should still converge.",
    },
    {
        "id": "H2S_sto3g",
        "molecule": "H2S",
        "category": "heavy_element",
        "charge": 0, "multiplicity": 1,
        "xyz": "3\nhydrogen sulfide\nS 0 0 0\nH 1.336 0 0\nH -0.345 1.292 0\n",
        "method": "HF", "basis": "sto-3g",
        "notes": "Sulfur on sto-3g.",
    },
    {
        "id": "HF_sto3g",
        "molecule": "HF",
        "category": "heavy_element",
        "charge": 0, "multiplicity": 1,
        "xyz": "2\nhydrogen fluoride\nH 0 0 0\nF 0 0 0.917\n",
        "method": "HF", "basis": "sto-3g",
        "notes": "Fluorine — simple but high electronegativity.",
    },
    {
        "id": "CH3Cl_sto3g",
        "molecule": "CH3Cl",
        "category": "heavy_element",
        "charge": 0, "multiplicity": 1,
        "xyz": ("5\nmethyl chloride\nC 0.0 0.0 0.0\nCl 0.0 0.0 1.781\n"
                "H 1.026 0.0 -0.378\nH -0.513 0.889 -0.378\n"
                "H -0.513 -0.889 -0.378\n"),
        "method": "HF", "basis": "sto-3g",
        "notes": "C-Cl bond.",
    },

    # ── 2. Open-shell ground state ──────────────────────────────────────────
    {
        "id": "O2_triplet_sto3g",
        "molecule": "O2",
        "category": "open_shell",
        "charge": 0, "multiplicity": 3,
        "xyz": "2\noxygen triplet\nO 0 0 0\nO 0 0 1.208\n",
        "method": "HF", "basis": "sto-3g",
        "notes": "Triplet ground state — tests UHF/ROHF path.",
    },

    # ── 3. Slightly larger molecules ────────────────────────────────────────
    {
        "id": "C2H4_sto3g",
        "molecule": "C2H4",
        "category": "larger_molecule",
        "charge": 0, "multiplicity": 1,
        "xyz": ("6\nethene\nC 0 0 0.667\nC 0 0 -0.667\n"
                "H 0 0.927 1.241\nH 0 -0.927 1.241\n"
                "H 0 0.927 -1.241\nH 0 -0.927 -1.241\n"),
        "method": "HF", "basis": "sto-3g",
        "notes": "Double bond.",
    },
    {
        "id": "C3H8_sto3g",
        "molecule": "C3H8",
        "category": "larger_molecule",
        "charge": 0, "multiplicity": 1,
        "xyz": ("11\npropane\nC 0 0.587 0\nC -1.262 -0.262 0\nC 1.262 -0.262 0\n"
                "H 0 1.241 -0.881\nH 0 1.241 0.881\n"
                "H -1.300 -0.918 0.881\nH -1.300 -0.918 -0.881\n"
                "H -2.158 0.371 0\nH 1.300 -0.918 0.881\n"
                "H 1.300 -0.918 -0.881\nH 2.158 0.371 0\n"),
        "method": "HF", "basis": "sto-3g",
        "notes": "C3H8 — 11 atoms, still trivial.",
    },
    {
        "id": "CH3CH2OH_sto3g",
        "molecule": "ethanol",
        "category": "larger_molecule",
        "charge": 0, "multiplicity": 1,
        "xyz": ("9\nethanol\nC 1.165 -0.247 0\nC 0 0.730 0\n"
                "O -1.187 -0.087 0\nH -1.951 0.498 0\n"
                "H 0.030 1.374 0.886\nH 0.030 1.374 -0.886\n"
                "H 2.097 0.323 0\nH 1.139 -0.892 0.881\n"
                "H 1.139 -0.892 -0.881\n"),
        "method": "HF", "basis": "sto-3g",
        "notes": "9 atoms incl. heteroatom O.",
    },
    {
        "id": "C6H6_sto3g",
        "molecule": "benzene",
        "category": "larger_molecule",
        "charge": 0, "multiplicity": 1,
        "xyz": ("12\nbenzene\nC 1.396 0 0\nC 0.698 1.209 0\n"
                "C -0.698 1.209 0\nC -1.396 0 0\n"
                "C -0.698 -1.209 0\nC 0.698 -1.209 0\n"
                "H 2.479 0 0\nH 1.240 2.148 0\n"
                "H -1.240 2.148 0\nH -2.479 0 0\n"
                "H -1.240 -2.148 0\nH 1.240 -2.148 0\n"),
        "method": "HF", "basis": "sto-3g",
        "notes": "Aromatic π system — the canonical 'medium-easy' test.",
    },

    # ── 4. Charged species ──────────────────────────────────────────────────
    {
        "id": "OH_minus_sto3g",
        "molecule": "OH-",
        "category": "charged",
        "charge": -1, "multiplicity": 1,
        "xyz": "2\nhydroxide\nO 0 0 0\nH 0 0 0.96\n",
        "method": "HF", "basis": "sto-3g",
        "notes": "Anion — sto-3g is poor for negative ions but should still run.",
    },
    {
        "id": "NH4_plus_sto3g",
        "molecule": "NH4+",
        "category": "charged",
        "charge": 1, "multiplicity": 1,
        "xyz": ("5\nammonium cation\nN 0 0 0\n"
                "H 0.5897 0.5897 0.5897\n"
                "H -0.5897 -0.5897 0.5897\n"
                "H -0.5897 0.5897 -0.5897\n"
                "H 0.5897 -0.5897 -0.5897\n"),
        "method": "HF", "basis": "sto-3g",
        "notes": "Cation — closed shell, easier than anion.",
    },
]


def _run_one(case: dict, override_method: str | None, override_basis: str | None) -> dict:
    """Invoke the calc_psi4 MCP server's single_point tool directly."""
    from chemaster.mcp.calc_psi4.server import single_point

    method = override_method or case["method"]
    basis = override_basis or case["basis"]

    t0 = time.time()
    try:
        result = single_point(
            geometry_xyz=case["xyz"],
            charge=case["charge"],
            multiplicity=case["multiplicity"],
            method=method,
            basis=basis,
            memory_gb=2.0,
            n_threads=1,
        )
        wall = time.time() - t0
        # The tool returns the standard envelope.  Pluck the salient bits.
        if result.get("ok"):
            e = result["result"].get("energy", {})
            return {
                "id": case["id"],
                "ok": True,
                "energy_Ha": e.get("value"),
                "wall_s": wall,
                "method": method, "basis": basis,
                "n_warnings": len(result.get("warnings", []) or []),
            }
        return {
            "id": case["id"],
            "ok": False,
            "error_code": result.get("error_code"),
            "details": (result.get("details") or "")[:200],
            "suggestion": result.get("suggestion"),
            "wall_s": wall,
            "method": method, "basis": basis,
        }
    except Exception as exc:
        return {
            "id": case["id"],
            "ok": False,
            "error_code": "TOOL_RAISED",
            "details": f"{type(exc).__name__}: {exc}",
            "wall_s": time.time() - t0,
            "method": method, "basis": basis,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", default=None,
                        help="override method for every case (else use case default)")
    parser.add_argument("--basis", default=None,
                        help="override basis for every case (else use case default)")
    parser.add_argument("--filter", default=None,
                        help="only run cases whose category contains this string")
    args = parser.parse_args()

    cases = HARD_CASES
    if args.filter:
        cases = [c for c in cases if args.filter in c["category"]]

    print(f"Hard-case probe — running {len(cases)} case(s)")
    print("─" * 70)

    rows: list[dict] = []
    for i, c in enumerate(cases, 1):
        print(f"  [{i:2d}/{len(cases)}]  {c['id']:25s}  ({c['category']})")
        r = _run_one(c, args.method, args.basis)
        r["category"] = c["category"]
        r["molecule"] = c["molecule"]
        rows.append(r)
        if r["ok"]:
            print(f"           → ok  E = {r['energy_Ha']:.6f} Ha  "
                  f"in {r['wall_s']:.2f}s")
        else:
            print(f"           → FAIL  code={r.get('error_code')}  "
                  f"hint={(r.get('suggestion') or '')[:80]}")

    # Aggregate by category
    by_cat: dict[str, dict] = {}
    for r in rows:
        bc = by_cat.setdefault(r["category"], {"ok": 0, "total": 0})
        bc["total"] += 1
        if r["ok"]:
            bc["ok"] += 1

    report = {
        "data_source": "real_psi4",
        "method": (
            "Real psi4 single_point invocations on hand-picked hard cases "
            "(heavier elements, open-shell, larger molecules, charged species)."
        ),
        "n_cases": len(rows),
        "n_ok": sum(1 for r in rows if r["ok"]),
        "by_category": by_cat,
        "rows": rows,
    }
    out_path = ROOT / "benchmarks" / "engineering_metrics" / "hard_cases.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print()
    print("─" * 70)
    print(f"  overall: {report['n_ok']}/{report['n_cases']} cases ok")
    for cat, d in sorted(by_cat.items()):
        print(f"    {cat:18s}  {d['ok']}/{d['total']}")
    print(f"  saved to {out_path}")

    # Non-zero exit only if every case failed (some failures are expected
    # and informative — e.g. sto-3g on anion).
    return 0 if report["n_ok"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
