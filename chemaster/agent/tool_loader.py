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

    # calc_bdf — TADF SOC engine (国产化亮点) ────────────────────────────
    _ToolDecl(
        exposed_name="calc_bdf_soc",
        module="chemaster.mcp.calc_bdf.server",
        function="soc",
        description=(
            "Spin-orbit coupling matrix elements via BDF X2C-TDA. THE step "
            "in the TADF pipeline that's hard to get right elsewhere — psi4 "
            "doesn't do SOC natively, ORCA's RI-SOMF is faster but less "
            "accurate. BDF is academic-free (Wenjian Liu group, Peking U). "
            "Returns ENGINE_NOT_FOUND with install hint when BDF isn't set up."
        ),
        is_long_running=True,
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
