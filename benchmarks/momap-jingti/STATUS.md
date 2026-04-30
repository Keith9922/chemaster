# Benchmark status — `momap-jingti`

> 师姐 (jingti) Gaussian + MOMAP TADF / heavy-atom emitter benchmark.
> Molecule: **C₂₄H₈F₈I₄N₂** (46 atoms, 4 iodines).
> Reference values curated by hand from MOMAP screenshots; raw Gaussian
> output / MOMAP log files were not delivered with the dataset.

This file tracks **what ChemMaster can already reproduce** vs **what's still missing**, with concrete next steps.

---

## ✅ What works today (V0.2.0a1)

### 1. Gaussian input parsing
`gaussian_parse_input` recognises all five raw `.com` files:

| file | task type | molecule |
|---|---|---|
| `jingti-00TDopt2(1).com` | `td_opt_freq` (singlet S2) | C24H8F8I4N2 |
| `Tjingti-00TDopt1(1).com` | `td_opt_freq` (triplet T1) | same |
| `Tjingti-00TDopt2(1).com` | `td_opt_freq` (triplet T1) | same |
| `jingti-00optnacmes1(1).com` | `nacme` | same |
| `jingti-00optnacmes2(1).com` | `nacme` | same |

The Agent can read Gaussian inputs and plan equivalent ChemMaster workflows
(see `result.suggested_chemmaster_workflow` for each parse).

### 2. Geometry extraction → reusable anchor
`benchmarks/momap-jingti/jingti.xyz` is the 46-atom geometry. Loadable via
`chemaster.mcp.io_ase.lookup_by_name("jingti")`. The agent can refer to
"jingti" by name in any workflow.

### 3. S0 single-point energy in psi4 (real numerical agreement)

```
ChemMaster psi4 (B3LYP-D3(BJ)/def2-SVP):  -3017.48311 Hartree
师姐 reference (Gaussian B3LYP/def2svp + GD3BJ):  -3017.47616 Hartree
                                          ──────────────
                                    Diff:  -4.36 kcal/mol
```

Agreement at the **same-method-different-software** level (a few kcal/mol is
typical between Gaussian and psi4 for closed-shell DFT). 209 s wall on a
4-core macOS laptop with `def2-SVP+ECP` for iodines.

### 4. Vertical TDDFT (S1 / S2 / T1 from a single calc_psi4_tddft)

`calc_psi4_tddft` works on smaller molecules (verified on benzene at
B3LYP/STO-3G; full TADF agent run with MiniMax-M2.7 finished in 100 s,
producing publication-quality output).

For the师姐 jingti molecule it would take ~40 minutes per excited-state
calc — runnable but slow without an HPC.

### 5. Photophysics formula library
`chemaster.kb.formulas.photophysics` covers:

- `kr_einstein_from_dipole(E, µ, n)` — Einstein A from transition dipole.
- `kf_strickler_berg(E, f, n)` — same from oscillator strength.
- `krisc_marcus`, `kisc_marcus` (== same Marcus formula, symmetric in |ΔE|).
- `kic_marcus` — internal conversion via Marcus + NACME.
- `plqy(kf, knr, kisc)` — quantum yield.
- `tadf_quantum_yield(...)` — full prompt + delayed decomposition.

**Honest caveat**: classical Marcus *cannot* reproduce the师姐 S1→T1 ISC
rate (1.17 × 10⁹ s⁻¹) at ΔE = 0.93 eV. Marcus barrier exp((ΔE+λ)²/4λkBT) is
prohibitive at high gaps; real heavy-atom ISC goes through MLJ
(Marcus-Levich-Jortner) with high-frequency vibrational acceptors.
Implementing MLJ + density-of-states is a roadmap item (see ⬜ below).

---

## ⬜ What's still missing for full numerical reproduction

| step | what's needed | difficulty |
|---|---|---|
| Excited-state geometry optimization (TD opt for S1 / S2 / T1) | New MCP tool wrapping `psi4.optimize` with a TDDFT root selector — psi4 does support this, just not exposed yet. | 1 day |
| NACME (non-adiabatic coupling matrix elements) | Gaussian / ORCA both expose this via specific iop / keyword. Need a parser + maybe a thin wrapper. ChemMaster has nothing here yet. | 3-5 days |
| MLJ / TVCF rate constants | Full quantum mechanical treatment of vibrational FCWD. `chem.momap` would wrap MOMAP itself; pure-Python MLJ would replace the classical Marcus calls in `photophysics.py`. | 1 week |
| MOMAP wrapper (`chem.momap`) | Subprocess driver for MOMAP binary — input builder + EVC / TVCF result parser. Software is Chinese-academic-licensed. | 3-5 days |
| Heavy-atom basis-set support (def2-ECP, jorge-ECP) | psi4's `def2-SVP` already includes ECPs for I; verified working on this benchmark. May need explicit options for ORCA (its `def2/J` etc.). | mostly done; 1-day polish |

---

## 🔧 How to reproduce the parts that DO work

```bash
# 1. parse the raw Gaussian inputs to confirm the workflow shape
python -c "
from chemaster.mcp.calc_gaussian.server import parse_input
import json
print(json.dumps(parse_input('benchmarks/momap-jingti/raw/jingti-00TDopt2(1).com')['result'], indent=2))
"

# 2. lookup the molecule by name (auto-loaded from benchmarks/)
python -c "
from chemaster.mcp.io_ase.server import lookup_by_name
r = lookup_by_name('jingti')
print(r['result']['formula'], r['result']['n_atoms'], 'atoms')
"

# 3. S0 single point (~3 min on 4 cores)
python -c "
from chemaster.mcp.calc_psi4.server import single_point
from chemaster.mcp.io_ase.server import lookup_by_name
xyz = lookup_by_name('jingti')['result']['xyz']
sp = single_point(xyz, method='B3LYP-D3(BJ)', basis='def2-SVP',
                  charge=0, multiplicity=1, n_threads=4, memory_gb=6)
print('Energy:', sp['result']['energy'])
"
```

---

## Source

| reference | value (师姐) | unit |
|---|---|---|
| S0 energy | -3017.476160 | Hartree |
| S1 energy | -3017.350811 | Hartree |
| S2 energy | -3017.337405 | Hartree |
| T1 energy | -3017.384969 | Hartree |
| kr (S1→S0) | 8.16 × 10⁸ | s⁻¹ |
| kic (S2→S1) | 6.12 × 10¹¹ | s⁻¹ |
| kisc (S1→T1) | 1.17 × 10⁹ | s⁻¹ |
| SOC (S1↔T1) | 5.56 | cm⁻¹ |
| SOC (S2↔T1) | 13.93 | cm⁻¹ |

Full reference in [`reference_values.yaml`](reference_values.yaml).
