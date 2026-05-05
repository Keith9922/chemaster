#!/usr/bin/env python3
"""Generate paper figures from benchmark/runs_archive data."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIG_DIR = ROOT / "benchmarks" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def _try_matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except ImportError:
        return None


def fig_s22(plt) -> None:
    summary = json.loads((ROOT / "benchmarks" / "s22" / "summary.json").read_text())
    valid = [r for r in summary["results"] if r.get("ok")]
    systems = [r["system"] for r in valid]
    refs = [r["reference_binding_energy_kcal"] for r in valid]
    calcs = [r["computed_binding_energy_kcal"] for r in valid]
    errors = [r["error_kcal"] for r in valid]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))

    # Scatter plot
    ax1.plot(refs, refs, "k--", lw=1, alpha=0.5, label="y = x")
    ax1.scatter(refs, calcs, s=80, c="tab:blue", edgecolors="black", zorder=5)
    for x, y, lbl in zip(refs, calcs, systems):
        ax1.annotate(lbl.replace("_", " "), (x, y), fontsize=8,
                     xytext=(5, 5), textcoords="offset points")
    ax1.set_xlabel("Reference E_int (kcal/mol)")
    ax1.set_ylabel("Computed E_int (kcal/mol)")
    ax1.set_title(f"S22 binding energies\nMAE = {summary['mae_kcal']:.2f} kcal/mol")
    ax1.legend()
    ax1.grid(alpha=0.3)

    # Error bars
    ax2.bar(range(len(systems)), errors,
            color=["tab:green" if abs(e) <= 0.5 else "tab:red" for e in errors],
            edgecolor="black")
    ax2.axhline(0.5, color="gray", lw=0.5, ls="--")
    ax2.axhline(-0.5, color="gray", lw=0.5, ls="--")
    ax2.set_xticks(range(len(systems)))
    ax2.set_xticklabels([s.replace("_", "\n") for s in systems], fontsize=9)
    ax2.set_ylabel("Error (kcal/mol)")
    ax2.set_title("Per-system errors (B3LYP-D3/def2-TZVP)")
    ax2.grid(alpha=0.3, axis="y")

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig_s22.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  → {FIG_DIR / 'fig_s22.png'}")


def fig_quest(plt) -> None:
    summary = json.loads((ROOT / "benchmarks" / "quest" / "summary.json").read_text())
    states_flat = []
    for sys_result in summary["results"]:
        if not sys_result.get("ok"):
            continue
        for s in sys_result["states"]:
            # Real psi4 outputs use computed_eV / ref_cc3_eV / ref_character;
            # mock outputs used vee_cc3_eV / vee_computed_eV / character.
            entry = {
                "vee_cc3_eV": s.get("ref_cc3_eV", s.get("vee_cc3_eV")),
                "vee_computed_eV": s.get("computed_eV", s.get("vee_computed_eV")),
                "error_eV": s["error_eV"],
                "character": s.get("ref_character", s.get("character", "")),
                "system": sys_result["system"],
            }
            states_flat.append(entry)
    refs = [s["vee_cc3_eV"] for s in states_flat]
    calcs = [s["vee_computed_eV"] for s in states_flat]
    errors = [s["error_eV"] for s in states_flat]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))

    ax1.plot([min(refs), max(refs)], [min(refs), max(refs)],
             "k--", lw=1, alpha=0.5, label="y = x")
    by_char = {}
    for s in states_flat:
        ch = "n→π*" if "n -> π*" in s["character"] else (
             "Rydberg" if "3s" in s["character"] or "Rydberg" in s["character"] else "π→π*")
        by_char.setdefault(ch, []).append(s)
    colors = {"n→π*": "tab:orange", "π→π*": "tab:blue", "Rydberg": "tab:green"}
    for ch, items in by_char.items():
        ax1.scatter([s["vee_cc3_eV"] for s in items],
                    [s["vee_computed_eV"] for s in items],
                    s=70, c=colors[ch], label=ch, edgecolors="black", zorder=5)
    ax1.set_xlabel("CC3 reference VEE (eV)")
    ax1.set_ylabel("TD-CAM-B3LYP VEE (eV)")
    ax1.set_title(f"QUEST excited-state energies\nMAE = {summary['mae_eV']:.2f} eV")
    ax1.legend()
    ax1.grid(alpha=0.3)

    # Error histogram
    ax2.hist(errors, bins=12, color="tab:purple", edgecolor="black", alpha=0.7)
    ax2.axvline(0, color="black", lw=1)
    ax2.set_xlabel("Error (CAM-B3LYP − CC3) [eV]")
    ax2.set_ylabel("Count")
    ax2.set_title("QUEST error distribution")
    ax2.grid(alpha=0.3, axis="y")

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig_quest.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  → {FIG_DIR / 'fig_quest.png'}")


def fig_anthracene(plt) -> None:
    summary = json.loads((ROOT / "benchmarks" / "anthracene" / "summary.json").read_text())
    p = summary["result"]["results"]
    cmp = summary["result"]["comparison_to_reference"]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))

    # Rate constants on log scale
    cats = ["k_r (S1→S0)", "k_p (T1→S0)"]
    k_exp = [4.5e7, 2.5e-2]
    k_ref = [cmp["k_r_ref_s_inv"], cmp["k_p_ref_s_inv"]]
    k_calc = [p["k_r_s_inv"], p["k_p_s_inv"]]
    x = range(len(cats))
    w = 0.27
    axes[0].bar([i - w for i in x], k_exp, width=w, label="Experiment",
                 color="tab:gray", edgecolor="black")
    axes[0].bar(x, k_ref, width=w, label="Niu/Shuai 2008",
                 color="tab:blue", edgecolor="black")
    axes[0].bar([i + w for i in x], k_calc, width=w, label="ChemMaster",
                 color="tab:green", edgecolor="black")
    axes[0].set_yscale("log")
    axes[0].set_xticks(list(x))
    axes[0].set_xticklabels(cats)
    axes[0].set_ylabel("Rate (s$^{-1}$)")
    axes[0].set_title("Anthracene radiative rates")
    axes[0].legend()
    axes[0].grid(alpha=0.3, which="both", axis="y")

    # Energy levels
    en = ["S1 vert", "S1 adia", "T1 vert"]
    e_calc = [p["S1_vertical_eV"], p["S1_adiabatic_eV"], p["T1_vertical_eV"]]
    axes[1].bar(en, e_calc, color="tab:green", edgecolor="black")
    axes[1].axhline(3.43, color="red", ls="--", lw=0.7, label="exp S1 vert ~3.43")
    axes[1].axhline(1.85, color="orange", ls="--", lw=0.7, label="exp T1 vert ~1.85")
    axes[1].set_ylabel("Energy (eV)")
    axes[1].set_title("Anthracene excited-state energies")
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.3, axis="y")

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig_anthracene.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  → {FIG_DIR / 'fig_anthracene.png'}")


def fig_engineering(plt) -> None:
    em = ROOT / "benchmarks" / "engineering_metrics"
    sf = json.loads((em / "submission_friction.json").read_text())
    fr = json.loads((em / "fault_recovery.json").read_text())
    ra = json.loads((em / "recommendation_acceptance.json").read_text())
    tb = json.loads((em / "trajectory_breakdown.json").read_text())

    fig, axes = plt.subplots(2, 2, figsize=(11, 8))

    # Submission friction
    tasks = [t["task"].split("_")[1] for t in sf["tasks"]]
    h = [t["human_minutes_avg"] for t in sf["tasks"]]
    a = [t["agent_minutes_avg"] for t in sf["tasks"]]
    x = range(len(tasks))
    w = 0.35
    axes[0, 0].bar([i - w/2 for i in x], h, w, label="Human", color="tab:gray", edgecolor="black")
    axes[0, 0].bar([i + w/2 for i in x], a, w, label="ChemMaster", color="tab:green", edgecolor="black")
    axes[0, 0].set_xticks(list(x))
    axes[0, 0].set_xticklabels(tasks)
    axes[0, 0].set_ylabel("Wall-clock time (min)")
    axes[0, 0].set_title(f"Submission friction\noverall savings: {sf['overall_savings_pct']:.1f}%")
    axes[0, 0].legend()
    axes[0, 0].grid(alpha=0.3, axis="y")

    # Fault recovery
    types = list(fr["by_fault_type"].keys())
    rates = [fr["by_fault_type"][t]["rate"] * 100 for t in types]
    axes[0, 1].bar([t.replace("_", "\n", 1) for t in types],
                    rates, color="tab:blue", edgecolor="black")
    axes[0, 1].axhline(80, color="red", ls="--", lw=0.7, label="target 80%")
    axes[0, 1].set_ylabel("Recovery rate (%)")
    axes[0, 1].set_title(f"Technical fault auto-recovery\noverall: {fr['recovery_rate_pct']:.1f}%")
    axes[0, 1].set_ylim(0, 110)
    axes[0, 1].legend()
    axes[0, 1].grid(alpha=0.3, axis="y")

    # Recommendation acceptance
    classes = list(ra["by_decision_class"].keys())
    accepted = [ra["by_decision_class"][c]["accepted"] for c in classes]
    modified = [ra["by_decision_class"][c]["modified"] for c in classes]
    cancelled = [ra["by_decision_class"][c]["cancelled"] for c in classes]
    axes[1, 0].bar(classes, accepted, label="accepted", color="tab:green", edgecolor="black")
    axes[1, 0].bar(classes, modified, bottom=accepted, label="modified",
                    color="tab:orange", edgecolor="black")
    axes[1, 0].bar(classes, cancelled,
                    bottom=[a + m for a, m in zip(accepted, modified)],
                    label="cancelled", color="tab:red", edgecolor="black")
    axes[1, 0].set_ylabel("Count")
    axes[1, 0].set_title(f"Chemistry recommendation outcomes\nacceptance: {ra['acceptance_pct']:.1f}%")
    axes[1, 0].legend()
    axes[1, 0].tick_params(axis="x", rotation=30)
    axes[1, 0].grid(alpha=0.3, axis="y")

    # Trajectory breakdown (pie)
    bd = tb["across_all_tasks"]
    labels = ["Agent silent", "User binary", "User chemistry", "System"]
    sizes = [bd["agent_silent"], bd["user_binary_confirm"],
             bd["user_chemistry_decision"], bd["system_events"]]
    colors_pie = ["tab:green", "tab:orange", "tab:purple", "tab:gray"]
    axes[1, 1].pie(sizes, labels=labels, colors=colors_pie, autopct="%.1f%%",
                    wedgeprops={"edgecolor": "black"})
    axes[1, 1].set_title(f"Trajectory step composition\nautonomous ratio: {tb['agent_step_ratio_pct']:.1f}%")

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig_engineering_metrics.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  → {FIG_DIR / 'fig_engineering_metrics.png'}")


def main() -> None:
    plt = _try_matplotlib()
    if plt is None:
        print("matplotlib not available; skipping figure generation")
        return
    print(f"Writing figures to {FIG_DIR}")
    fig_s22(plt)
    fig_quest(plt)
    fig_anthracene(plt)
    fig_engineering(plt)
    print("done.")


if __name__ == "__main__":
    main()
