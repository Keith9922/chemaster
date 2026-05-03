"""Tool loader — adapt every available MCP server function into the registry.

Each entry in `TOOL_MANIFEST` declares:
- where the function lives (`module:function`)
- what name to expose to the LLM
- permission flags (read-only / destructive / long-running)

The loader is defensive: if an MCP server can't be imported (e.g. ORCA not
installed), the affected tool is silently skipped with a debug log.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass

from chemaster.agent.builtins import register_builtins
from chemaster.agent.tool_registry import MCPToolAdapter, ToolRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ToolDecl:
    exposed_name: str
    module: str
    function: str
    description: str
    is_read_only: bool = False
    is_destructive: bool = False
    is_long_running: bool = False
    is_chemistry_decision: bool = False


# Tool exposure naming convention for the LLM:
#   <category>_<verb>   e.g. const_get, io_smiles_to_xyz, calc_psi4_optimize
# We avoid dots in tool names because some LLM tool-use schemas reject them.

TOOL_MANIFEST: list[_ToolDecl] = [
    # const ────────────────────────────────────────────────────────────────
    _ToolDecl(
        exposed_name="const_get",
        module="chemaster.mcp.const.server",
        function="get_constant",
        description=(
            "Look up a physical constant by name. Use for any value the user mentions "
            "(Planck h, Boltzmann kB, speed of light c, electron mass, Avogadro NA, "
            "Hartree↔eV factor, Bohr radius, etc.). Returns {value, unit, source}. "
            "ALWAYS use this — never recall constants from memory."
        ),
        is_read_only=True,
    ),
    _ToolDecl(
        exposed_name="const_list",
        module="chemaster.mcp.const.server",
        function="list_constants",
        description="List every supported constant name. Use when const_get reports UNKNOWN_CONSTANT.",
        is_read_only=True,
    ),
    _ToolDecl(
        exposed_name="const_convert",
        module="chemaster.mcp.const.server",
        function="convert_unit",
        description=(
            "Convert a numerical value between physical units. Use for ALL unit "
            "conversions (Hartree → kcal/mol, eV → cm⁻¹, Bohr → Å, K → kJ/mol via kT, "
            "etc.). Never hand-calculate."
        ),
        is_read_only=True,
    ),

    # formulas ─────────────────────────────────────────────────────────────
    # Deterministic chemistry formulas. CLAUDE.md §5.1: LLM does not do
    # floating-point math. These tools wrap chemaster.kb.formulas.* so the
    # agent gets exact numerical results instead of LLM arithmetic.
    _ToolDecl(
        exposed_name="formula_krisc_marcus",
        module="chemaster.mcp.formulas.server",
        function="compute_krisc_marcus",
        description=(
            "RISC (reverse intersystem crossing) rate constant k_RISC via Marcus "
            "high-T limit. Inputs: ΔE_ST (eV), SOC (cm⁻¹), reorganization energy "
            "λ (eV), T (K). Use whenever you have these four quantities — never "
            "hand-compute the exponential/sqrt."
        ),
        is_read_only=True,
    ),
    _ToolDecl(
        exposed_name="formula_kf_strickler_berg",
        module="chemaster.mcp.formulas.server",
        function="compute_kf_strickler_berg",
        description=(
            "Radiative rate constant k_F via Strickler-Berg. Inputs: emission "
            "energy E (eV), oscillator strength f. Returns k_F (s⁻¹) and "
            "radiative lifetime (ns)."
        ),
        is_read_only=True,
    ),
    _ToolDecl(
        exposed_name="formula_kisc_marcus",
        module="chemaster.mcp.formulas.server",
        function="compute_kisc_marcus",
        description="ISC (S→T) rate via Marcus high-T limit. Same input shape as k_RISC.",
        is_read_only=True,
    ),
    _ToolDecl(
        exposed_name="formula_plqy",
        module="chemaster.mcp.formulas.server",
        function="compute_plqy",
        description="Photoluminescence quantum yield Φ_F = k_F / (k_F + k_NR + k_ISC).",
        is_read_only=True,
    ),
    _ToolDecl(
        exposed_name="formula_boltzmann",
        module="chemaster.mcp.formulas.server",
        function="compute_boltzmann_weights",
        description=(
            "Boltzmann conformer populations from relative energies (kcal/mol). "
            "Always use for multi-conformer averaging — DO NOT take arithmetic mean."
        ),
        is_read_only=True,
    ),
    _ToolDecl(
        exposed_name="formula_eyring",
        module="chemaster.mcp.formulas.server",
        function="compute_eyring",
        description=(
            "Eyring rate constant k = κ·(kBT/h)·exp(-ΔG‡/RT). Inputs: ΔG‡ in "
            "kJ/mol, T in K. Use for any TST rate from activation free energy."
        ),
        is_read_only=True,
    ),
    _ToolDecl(
        exposed_name="formula_arrhenius",
        module="chemaster.mcp.formulas.server",
        function="compute_arrhenius",
        description="Arrhenius rate k = A·exp(-Ea/RT). Use when you have A and Ea.",
        is_read_only=True,
    ),

    # io_ase ────────────────────────────────────────────────────────────────
    _ToolDecl(
        exposed_name="io_smiles_to_xyz",
        module="chemaster.mcp.io_ase.server",
        function="smiles_to_xyz",
        description=(
            "Convert a SMILES string to a 3D xyz geometry via RDKit ETKDG embedding "
            "and force-field minimization. First step for almost any user input that "
            "names or draws a molecule."
        ),
        is_read_only=True,
    ),
    _ToolDecl(
        exposed_name="io_xyz_to_smiles",
        module="chemaster.mcp.io_ase.server",
        function="xyz_to_smiles",
        description="Recover a canonical SMILES from xyz coordinates (best-effort).",
        is_read_only=True,
    ),
    _ToolDecl(
        exposed_name="io_parse_geometry",
        module="chemaster.mcp.io_ase.server",
        function="parse_geometry",
        description="Parse a structure file/string (xyz / mol / sdf / pdb). Returns atoms + xyz.",
        is_read_only=True,
    ),
    _ToolDecl(
        exposed_name="io_lookup_by_name",
        module="chemaster.mcp.io_ase.server",
        function="lookup_by_name",
        description=(
            "Resolve a common-name molecule (water, methane, benzene, ethanol, NH3, …) "
            "to a canonical xyz. Uses a built-in name → xyz table."
        ),
        is_read_only=True,
    ),

    # calc_psi4 (long-running, will request user confirmation by default) ──
    _ToolDecl(
        exposed_name="calc_psi4_single_point",
        module="chemaster.mcp.calc_psi4.server",
        function="single_point",
        description=(
            "Single-point energy with psi4 (no geometry change). Inputs: xyz, method, "
            "basis, charge, multiplicity. Default B3LYP-D3(BJ)/def2-TZVP. "
            "Long-running for large systems."
        ),
        is_long_running=True,
    ),
    _ToolDecl(
        exposed_name="calc_psi4_optimize",
        module="chemaster.mcp.calc_psi4.server",
        function="optimize",
        description=(
            "Geometry optimization with psi4. Inputs: xyz, method, basis, charge, "
            "multiplicity, max_iter. Returns optimized_geometry_xyz, final_energy, "
            "n_iterations, converged. ALWAYS follow with calc_psi4_frequency to verify "
            "the minimum (no imaginary frequencies)."
        ),
        is_long_running=True,
    ),
    _ToolDecl(
        exposed_name="calc_psi4_frequency",
        module="chemaster.mcp.calc_psi4.server",
        function="frequency",
        description=(
            "Harmonic frequency analysis with psi4. MUST use the same method/basis as "
            "the optimize that produced the geometry. Returns frequencies (cm⁻¹), "
            "n_imaginary, ZPE, thermal corrections (H, G at temperature)."
        ),
        is_long_running=True,
    ),
    _ToolDecl(
        exposed_name="calc_psi4_tddft",
        module="chemaster.mcp.calc_psi4.server",
        function="tddft",
        description=(
            "TDDFT excited-state calculation with psi4. Use AFTER optimize to get "
            "S1/T1 energies, oscillator strengths, and ΔE_ST for TADF analysis. "
            "Default tda=True (Tamm-Dancoff) avoids triplet-instability issues "
            "(PITFALLS §2.8). For charge-transfer states, prefer ωB97X-D over B3LYP."
        ),
        is_long_running=True,
    ),
    _ToolDecl(
        exposed_name="calc_psi4_optimize_excited_state",
        module="chemaster.mcp.calc_psi4.server",
        function="optimize_excited_state",
        description=(
            "Excited-state geometry optimization (TDA only) via psi4. Use this "
            "AFTER calc_psi4_optimize (ground state) to get the *adiabatic* "
            "S1/T1/Sn/Tn geometry — the input to adiabatic ΔE_ST and Stokes "
            "shift. Args: target_state (1=S1/T1, 2=S2/T2, ...), "
            "target_spin ('singlet' / 'triplet'), n_states (≥ target_state). "
            "WARNING: psi4 1.10 has FD-only TDDFT gradients, so cost scales as "
            "3·N_atom per opt step. ≤20 atoms is realistic on a laptop; bigger "
            "needs HPC. Tip: for molecules that break symmetry on excitation "
            "(HCHO pyramidalization etc.), pre-perturb the input geometry by "
            "~0.2 Å along the expected distortion mode, otherwise the optimizer "
            "may converge in 1 step at the GS stationary point."
        ),
        is_long_running=True,
    ),

    # calc_gaussian — read user-supplied Gaussian inputs (.com / .gjf) ───
    _ToolDecl(
        exposed_name="gaussian_parse_input",
        module="chemaster.mcp.calc_gaussian.server",
        function="parse_input",
        description=(
            "Parse a Gaussian .com / .gjf input file. Use when the user "
            "hands you a Gaussian input (e.g. legacy benchmark data) and "
            "you need to understand what task it represents (sp / opt / "
            "td_opt / nacme / etc.) plus the molecule. Returns a "
            "structured dict + a suggested ChemMaster workflow mapping."
        ),
        is_read_only=True,
    ),
    _ToolDecl(
        exposed_name="gaussian_run",
        module="chemaster.mcp.calc_gaussian.server",
        function="run",
        description=(
            "Drive the g16 / g09 binary on an existing Gaussian input file. "
            "Prefer the structured tools (gaussian_optimize / _frequency / "
            "_tddft / _opt_excited_state / _single_point) which build the "
            "input for you."
        ),
        is_long_running=True,
    ),
    # v3.0: structured Gaussian tools (the v3.0 main path)
    _ToolDecl(
        exposed_name="gaussian_optimize",
        module="chemaster.mcp.calc_gaussian.server",
        function="optimize",
        description=(
            "Ground-state geometry optimization in Gaussian (g16). Builds the "
            ".com from xyz + method + basis, runs g16, parses the optimized "
            "geometry and final SCF energy. Default B3LYP/6-31G(d) with D3BJ "
            "dispersion. Returns ENGINE_NOT_FOUND if Gaussian is unavailable."
        ),
        is_long_running=True,
    ),
    _ToolDecl(
        exposed_name="gaussian_frequency",
        module="chemaster.mcp.calc_gaussian.server",
        function="frequency",
        description=(
            "Harmonic frequency analysis in Gaussian. Returns frequencies, "
            "ZPE, thermal corrections, imaginary-mode count. Method/basis "
            "MUST match the prior optimization."
        ),
        is_long_running=True,
    ),
    _ToolDecl(
        exposed_name="gaussian_tddft",
        module="chemaster.mcp.calc_gaussian.server",
        function="tddft",
        description=(
            "TDDFT vertical excitation in Gaussian (TDA by default). "
            "Returns excited-state energies, oscillator strengths, "
            "wavelengths. Use n_triplets > 0 to include triplet states."
        ),
        is_long_running=True,
    ),
    _ToolDecl(
        exposed_name="gaussian_opt_excited_state",
        module="chemaster.mcp.calc_gaussian.server",
        function="opt_excited_state",
        description=(
            "TD-opt: optimize geometry of a specific excited state in "
            "Gaussian. Critical for fluorescence/phosphorescence rates."
        ),
        is_long_running=True,
    ),
    _ToolDecl(
        exposed_name="gaussian_single_point",
        module="chemaster.mcp.calc_gaussian.server",
        function="single_point",
        description=(
            "Single-point energy at a fixed geometry in Gaussian."
        ),
        is_long_running=True,
    ),

    # calc_orca (academic-free; faster than psi4 for large systems) ──────
    _ToolDecl(
        exposed_name="calc_orca_single_point",
        module="chemaster.mcp.calc_orca.server",
        function="single_point",
        description=(
            "Single-point energy with ORCA. Use for: DLPNO-CCSD(T) "
            "energetics, range-separated DFT (ωB97X-D3BJ) on >50-atom "
            "systems, RIJCOSX-accelerated hybrid DFT. Returns "
            "ENGINE_NOT_FOUND if ORCA isn't on PATH."
        ),
        is_long_running=True,
    ),
    _ToolDecl(
        exposed_name="calc_orca_optimize",
        module="chemaster.mcp.calc_orca.server",
        function="optimize",
        description=(
            "Geometry optimization with ORCA. More robust than psi4's "
            "optking on awkward geometries (large rings, TM complexes). "
            "Always follow with calc_psi4_frequency to verify the minimum."
        ),
        is_long_running=True,
    ),

    # calc_bdf — SOC + opt + TDDFT (国产化亮点) ────────────────────────────
    _ToolDecl(
        exposed_name="calc_bdf_soc",
        module="chemaster.mcp.calc_bdf.server",
        function="soc",
        description=(
            "Spin-orbit coupling matrix elements via BDF X2C-TDA. THE step "
            "in the TADF / phosphorescence pipeline that's hard to get right "
            "elsewhere. BDF is academic-free (Wenjian Liu group, Peking U)."
        ),
        is_long_running=True,
    ),
    _ToolDecl(
        exposed_name="calc_bdf_optimize",
        module="chemaster.mcp.calc_bdf.server",
        function="optimize",
        description="Ground-state geometry optimization in BDF.",
        is_long_running=True,
    ),
    _ToolDecl(
        exposed_name="calc_bdf_tddft",
        module="chemaster.mcp.calc_bdf.server",
        function="tddft",
        description=(
            "TDDFT vertical excitation in BDF. Use spin_flip=True for triplet "
            "states from a singlet reference."
        ),
        is_long_running=True,
    ),

    # calc_momap — TVCF rate / spectrum (Shuai 组招牌) ──────────────────
    _ToolDecl(
        exposed_name="calc_momap_tvcf_rate",
        module="chemaster.mcp.calc_momap.server",
        function="tvcf_rate",
        description=(
            "TVCF rate constant via MOMAP. Computes k_r (fluorescence) when "
            "transition_dipole is provided, k_p (phosphorescence) when "
            "soc_matrix_element_cm_inv > 0. Requires Gaussian/BDF freq "
            "outputs for both electronic states. dry_run=True returns the "
            "would-be input file without invoking momap."
        ),
        is_long_running=True,
    ),
    _ToolDecl(
        exposed_name="calc_momap_tvcf_spec",
        module="chemaster.mcp.calc_momap.server",
        function="tvcf_spec",
        description=(
            "Vibrationally-resolved emission or absorption spectrum via MOMAP "
            "TVCF. Returns peak positions and (path to) full spectrum data."
        ),
        is_long_running=True,
    ),
    _ToolDecl(
        exposed_name="calc_momap_parse_output",
        module="chemaster.mcp.calc_momap.server",
        function="parse_output",
        description=(
            "Parse an existing MOMAP output file (run elsewhere) for rates "
            "and spectrum data. Use to harvest results from HPC runs."
        ),
        is_read_only=True,
    ),

    # analysis_multiwfn — wavefunction analysis (NTO etc.) ──────────────
    _ToolDecl(
        exposed_name="analysis_nto",
        module="chemaster.mcp.analysis_multiwfn.server",
        function="nto_analysis",
        description=(
            "Natural Transition Orbital analysis via Multiwfn. Use after "
            "TDDFT to characterize each excited state's hole/particle "
            "distribution — critical for distinguishing CT from LE excited "
            "states in TADF design (PITFALLS §2.7). Needs a .molden / "
            ".gbw / .fch wavefunction file from the prior QM step."
        ),
        is_long_running=True,
    ),

    # hpc_slurm — async submit / status / fetch on a university cluster ──
    _ToolDecl(
        exposed_name="hpc_submit",
        module="chemaster.mcp.hpc_slurm.server",
        function="submit",
        description=(
            "Submit a SLURM job over SSH; returns the job_id immediately so "
            "the agent can continue with other work and poll status. "
            "Requires ~/.chemaster/hpc.yaml with host/user/ssh_key/etc."
        ),
        is_destructive=True,            # external side-effect on the cluster
    ),
    _ToolDecl(
        exposed_name="hpc_status",
        module="chemaster.mcp.hpc_slurm.server",
        function="status",
        description=(
            "Query a SLURM job_id's current state (squeue / sacct fallback). "
            "Use periodically while waiting for hpc_submit jobs to finish."
        ),
        is_read_only=True,
    ),
    _ToolDecl(
        exposed_name="hpc_fetch",
        module="chemaster.mcp.hpc_slurm.server",
        function="fetch",
        description=(
            "Pull a finished SLURM job's output directory back over rsync. "
            "Call after hpc_status reports COMPLETED."
        ),
        is_destructive=True,
        is_long_running=True,
    ),

    # calc_xtb (fast, but mark long-running for safety on big molecules) ──
    _ToolDecl(
        exposed_name="calc_xtb_single_point",
        module="chemaster.mcp.calc_xtb.server",
        function="single_point",
        description="Single-point energy with xTB (GFN2 default). Seconds-fast.",
        is_read_only=False,
    ),
    _ToolDecl(
        exposed_name="calc_xtb_optimize",
        module="chemaster.mcp.calc_xtb.server",
        function="optimize",
        description=(
            "Geometry optimization with xTB. Cheap (seconds). Use for: pre-screening "
            "before DFT, conformer search inputs, very large systems."
        ),
    ),

    # calc_pyscf (open-source X2C SOC reference for the BDF wrapper) ──────
    _ToolDecl(
        exposed_name="calc_pyscf_single_point",
        module="chemaster.mcp.calc_pyscf.server",
        function="single_point",
        description=(
            "Single-point energy with PySCF. Supports HF/DFT and three "
            "relativistic levels: 'none' / 'scalar' (X2C-1e via decorator) / "
            "'soc' (two-component GKS+X2C-1e, includes spin-orbit coupling). "
            "Open-source pip-installable, runs natively on macOS arm64. Use "
            "as the open-source reference path for SOC tasks when BDF is "
            "unavailable."
        ),
        is_read_only=False,
        is_long_running=True,
    ),
    _ToolDecl(
        exposed_name="calc_pyscf_x2c_soc",
        module="chemaster.mcp.calc_pyscf.server",
        function="x2c_soc",
        description=(
            "Three-stage relativistic analysis (non-rel / scalar X2C / "
            "two-component X2C+SOC) on the same geometry, reporting scalar "
            "and SOC corrections in meV. Open-source reference for the BDF "
            "X2C-TDA SOC pathway."
        ),
        is_read_only=False,
        is_long_running=True,
        is_chemistry_decision=True,
    ),

    # parse_cclib ──────────────────────────────────────────────────────────
    _ToolDecl(
        exposed_name="parse_output",
        module="chemaster.mcp.parse_cclib.server",
        function="parse_output",
        description=(
            "Parse a quantum-chemistry output file (psi4/ORCA/Gaussian/etc.) via cclib. "
            "Returns engine, energy, geometry, scf_iterations, frequencies if present. "
            "Use after a calculation to extract structured data when the tool didn't "
            "already give you everything you need."
        ),
        is_read_only=True,
    ),
    _ToolDecl(
        exposed_name="parse_orbitals",
        module="chemaster.mcp.parse_cclib.server",
        function="extract_orbitals",
        description="Extract MO energies and occupations around HOMO/LUMO from an output file.",
        is_read_only=True,
    ),

    # viz ───────────────────────────────────────────────────────────────────
    _ToolDecl(
        exposed_name="viz_plot_3d",
        module="chemaster.mcp.viz.server",
        function="plot_3d",
        description="Render a 3D structure of an xyz to PNG (writes to disk).",
        is_destructive=True,        # writes a file; mild side-effect
    ),
    _ToolDecl(
        exposed_name="viz_plot_ir",
        module="chemaster.mcp.viz.server",
        function="plot_ir",
        description="Plot an IR spectrum from frequencies + intensities to PNG.",
        is_destructive=True,
    ),
]


def build_default_registry(extras: list[_ToolDecl] | None = None) -> ToolRegistry:
    """Build a ToolRegistry with built-ins + every MCP tool we can import."""
    registry = ToolRegistry()
    register_builtins(registry)
    decls = list(TOOL_MANIFEST) + list(extras or [])

    for decl in decls:
        try:
            module = importlib.import_module(decl.module)
        except ImportError as exc:
            logger.debug("Skipping %s (module %s not importable: %s)",
                         decl.exposed_name, decl.module, exc)
            continue
        fn = getattr(module, decl.function, None)
        if fn is None:
            logger.debug("Skipping %s: %s has no attribute %s",
                         decl.exposed_name, decl.module, decl.function)
            continue
        # Unwrap FastMCP decorator if present.
        actual_fn = getattr(fn, "fn", fn)

        adapter = MCPToolAdapter(
            fn=actual_fn,
            name=decl.exposed_name,
            description=decl.description,
            is_read_only=decl.is_read_only,
            is_destructive=decl.is_destructive,
            is_long_running=decl.is_long_running,
            is_chemistry_decision=decl.is_chemistry_decision,
        )
        registry.register(adapter)

    # Try to attach the chem.kb tools as well (they live in chem.mcp.kb).
    _try_register_kb(registry)

    logger.info("Tool registry loaded: %d tools (%s)", len(registry), ", ".join(registry.names()))
    return registry


def _try_register_kb(registry: ToolRegistry) -> None:
    """The chem.kb MCP exposes kb_search / use_skill — attach if available."""
    try:
        kb_module = importlib.import_module("chemaster.mcp.kb.server")
    except ImportError:
        return

    for fn_name, exposed, description, ro in [
        (
            "kb_search",
            "kb_search",
            (
                "Search the chemistry knowledge base for relevant rules / playbook "
                "sections (basis sets, functionals, convergence, workflows). Returns "
                "the top-k snippets with citations."
            ),
            True,
        ),
        (
            "use_skill",
            "use_skill",
            (
                "Read or query a built-in chemistry skill / playbook by name "
                "(e.g. 'opt-freq', 'tadf-pipeline', 'tddft'). Use this when planning "
                "a multi-step workflow you have not done before."
            ),
            True,
        ),
        (
            "list_skills",
            "list_skills",
            "List the available chemistry skills / playbooks with one-line summaries.",
            True,
        ),
    ]:
        fn = getattr(kb_module, fn_name, None)
        if fn is None:
            continue
        actual_fn = getattr(fn, "fn", fn)
        registry.register(MCPToolAdapter(
            fn=actual_fn,
            name=exposed,
            description=description,
            is_read_only=ro,
        ))


__all__ = ["build_default_registry", "TOOL_MANIFEST"]
