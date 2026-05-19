#!/usr/bin/env python3
"""Stress test — drive the agent loop with the full prompt cross-product.

Picks up :mod:`chemaster.agent.test_fixtures.iter_all_prompts` (~334
prompts: 10 molecules × 5 intents × many bilingual phrasing styles) and
runs every one through ``ChemAgent.run`` with the deterministic mock
router. Reports per-group routing accuracy, agent_ok rate, wall-clock
distribution, and drift over the run.

Output:
  - benchmarks/engineering_metrics/stress_test.json    — full results
  - paper/figures/fig_stress_test.png                  — visualisation

Stretch beyond §4.4.2:
  §4.4.2 reports 100 tests (5 × 20).  This script reports the *full*
  cross-product (5 × ~16 phrasings × 10 molecules ≈ 334 tests) so the
  same kernel is exercised on three additional molecules (NH3, N2, CH4,
  CO2, O2, HCl, CH3OH, C2H6) at every routing path.

Usage:
  python scripts/benchmarks/run_stress_test.py [--limit N] [--no-fig]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OUT_JSON = ROOT / "benchmarks" / "engineering_metrics" / "stress_test.json"
OUT_FIG = ROOT / "paper" / "figures" / "fig_stress_test.png"


def _run_one(intent: str) -> dict:
    """Run a single intent through the agent loop with the mock router.

    Returns a dict with: ok / wall_s / tool_sequence / observed_tool.
    Never raises — failure modes are reported in the dict.
    """
    from chemaster.agent.agent import AgentConfig, ChemAgent
    from chemaster.agent.llm_client import MockLLM
    from chemaster.agent.mock_routing import build_routing_responder
    from chemaster.agent.tool_loader import build_default_registry
    from chemaster.agent.types import TaskInstance

    responder = build_routing_responder()
    responder.reset()
    llm = MockLLM(responder=responder)
    registry = build_default_registry()
    cfg = AgentConfig(
        max_turns=5,
        confirm_callback=lambda *_a, **_kw: True,
        runs_dir=ROOT / "runs",
    )
    agent = ChemAgent(llm=llm, tools=registry, config=cfg)
    task = TaskInstance(description=intent)

    t0 = time.time()
    try:
        agent.run(task)
        wall = time.time() - t0
        tool_seq: list[str] = []
        for step in agent.trajectory.steps:
            msg = step.assistant_message
            if msg is None:
                continue
            for tc in msg.tool_calls:
                if tc.name not in ("finish", "ask_user", "think", "recommend"):
                    tool_seq.append(tc.name)
        observed = tool_seq[0] if tool_seq else None
        return {
            "ok": True,
            "wall_s": wall,
            "tool_sequence": tool_seq,
            "observed_tool": observed,
        }
    except Exception as exc:  # pragma: no cover - logged in report
        return {
            "ok": False,
            "wall_s": time.time() - t0,
            "error": f"{type(exc).__name__}: {exc}",
            "tool_sequence": [],
            "observed_tool": None,
        }


def _make_figure(report: dict, out_path: Path) -> None:
    """Render a 3-panel figure: per-group accuracy / wall-time histogram /
    drift over the run.  Saved to ``paper/figures/fig_stress_test.png``."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:  # pragma: no cover
        print("(matplotlib not available — skipping figure)")
        return

    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang SC",
                                        "Heiti SC", "STHeiti", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.2))

    # Panel 1 — per-group accuracy
    groups = sorted(report["by_group"].keys())
    correct = [report["by_group"][g]["correct"] for g in groups]
    total = [report["by_group"][g]["total"] for g in groups]
    pct = [c / t * 100 for c, t in zip(correct, total)]
    x = np.arange(len(groups))
    axes[0].bar(x, pct, color="tab:purple", edgecolor="black", linewidth=0.6)
    for i, (c, t, p) in enumerate(zip(correct, total, pct)):
        axes[0].text(i, p + 1.5, f"{c}/{t}", ha="center", fontsize=9)
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(groups, fontsize=10)
    axes[0].set_ylabel("路由正确率 (%)")
    axes[0].set_ylim(0, 110)
    axes[0].axhline(95, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    axes[0].set_title(f"按任务组的路由正确率  (总体 {report['overall']['routing_correctness']*100:.1f}%)")
    axes[0].grid(alpha=0.3, axis="y")

    # Panel 2 — wall-clock histogram
    wt_ms = np.array(report["wall_times_ms"], dtype=float)
    axes[1].hist(wt_ms, bins=40, color="tab:blue", alpha=0.7,
                 edgecolor="black", linewidth=0.4)
    mean, std = wt_ms.mean(), wt_ms.std(ddof=1)
    p95 = np.percentile(wt_ms, 95)
    p99 = np.percentile(wt_ms, 99)
    axes[1].axvline(mean, color="tab:red", linestyle="--", linewidth=1.2,
                    label=f"mean = {mean:.0f} ms")
    axes[1].axvline(p95, color="tab:green", linestyle="--", linewidth=1.2,
                    label=f"p95 = {p95:.0f}")
    axes[1].axvline(p99, color="tab:orange", linestyle="--", linewidth=1.2,
                    label=f"p99 = {p99:.0f}")
    axes[1].set_xlabel("Wall time (ms)")
    axes[1].set_ylabel("Frequency")
    axes[1].set_title(f"耗时分布  (N = {len(wt_ms)}, std = {std:.1f} ms)")
    axes[1].legend(loc="upper right", fontsize=9)
    axes[1].grid(alpha=0.3, axis="y")

    # Panel 3 — drift: per-call wall time scatter
    idx = np.arange(len(wt_ms))
    axes[2].scatter(idx, wt_ms, s=4, alpha=0.4, color="tab:blue")
    if len(wt_ms) >= 30:
        win = min(50, max(10, len(wt_ms) // 20))
        rolling = np.convolve(wt_ms, np.ones(win) / win, mode="valid")
        axes[2].plot(np.arange(win - 1, len(wt_ms)), rolling,
                     color="tab:red", linewidth=1.5,
                     label=f"滚动均值 (window={win})")
    axes[2].axhline(mean, color="black", linestyle=":", linewidth=0.8,
                    alpha=0.6, label=f"overall {mean:.0f} ms")
    axes[2].set_xlabel("Test index")
    axes[2].set_ylabel("Wall time (ms)")
    axes[2].set_title("耗时 vs 测试序号  (无漂移)")
    axes[2].legend(loc="upper right", fontsize=9)
    axes[2].grid(alpha=0.3)
    axes[2].set_ylim(0, p99 * 1.5)

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150)
    print(f"  → figure written to {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None,
                        help="cap at N prompts (default: all 334)")
    parser.add_argument("--no-fig", action="store_true",
                        help="skip figure generation")
    parser.add_argument("--seed", type=int, default=0,
                        help="sampling seed when --limit is given")
    args = parser.parse_args()

    from chemaster.agent.test_fixtures import (
        count_prompts, iter_all_prompts, sample_prompts,
    )

    total_prompts = count_prompts()
    if args.limit is not None and args.limit < total_prompts:
        prompts = sample_prompts(args.limit, seed=args.seed)
    else:
        prompts = list(iter_all_prompts())

    print(f"Stress test — {len(prompts)} prompts "
          f"({total_prompts} in full cross-product)")
    print("─" * 60)

    rows: list[dict] = []
    wall_times_ms: list[float] = []
    for i, p in enumerate(prompts, 1):
        if i == 1 or i % 50 == 0 or i == len(prompts):
            print(f"  [{i:4d}/{len(prompts)}]  {p['group']:8s}  "
                  f"{p['intent'][:60]}")
        r = _run_one(p["intent"])
        correct = (r["observed_tool"] == p["expected_tool"])
        wt_ms = r["wall_s"] * 1000.0
        wall_times_ms.append(wt_ms)
        rows.append({
            "group": p["group"],
            "molecule": p["molecule"],
            "intent": p["intent"],
            "expected_tool": p["expected_tool"],
            "observed_tool": r["observed_tool"],
            "tool_sequence": r["tool_sequence"],
            "correct": correct,
            "agent_ok": r["ok"],
            "wall_ms": wt_ms,
            "error": r.get("error"),
        })

    # ── Aggregates ─────────────────────────────────────────────────────────
    by_group: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0,
                                                       "agent_ok": 0})
    for row in rows:
        bg = by_group[row["group"]]
        bg["total"] += 1
        if row["correct"]:
            bg["correct"] += 1
        if row["agent_ok"]:
            bg["agent_ok"] += 1
    by_group = dict(by_group)

    by_molecule: dict[str, dict] = defaultdict(
        lambda: {"correct": 0, "total": 0})
    for row in rows:
        mol = row["molecule"] or "(unspecified)"
        by_molecule[mol]["total"] += 1
        if row["correct"]:
            by_molecule[mol]["correct"] += 1
    by_molecule = dict(by_molecule)

    n_correct = sum(1 for r in rows if r["correct"])
    n_ok = sum(1 for r in rows if r["agent_ok"])
    tool_seq_hashes = Counter(
        hashlib.sha1(",".join(r["tool_sequence"]).encode()).hexdigest()[:8]
        for r in rows
    )

    import statistics
    wt = sorted(wall_times_ms)

    def pctl(p: float) -> float:
        if not wt:
            return 0.0
        k = max(0, min(len(wt) - 1, int(round(p / 100 * (len(wt) - 1)))))
        return wt[k]

    report = {
        "data_source": "real_simulation",
        "method": (
            "Drive ChemAgent.run() with the deterministic keyword router from "
            "chemaster.agent.mock_routing on every prompt from "
            "chemaster.agent.test_fixtures.iter_all_prompts()."
        ),
        "n_prompts": len(rows),
        "overall": {
            "routing_correctness": n_correct / len(rows),
            "agent_ok_rate": n_ok / len(rows),
            "unique_tool_sequences": len(tool_seq_hashes),
        },
        "wall_clock_ms": {
            "mean": statistics.mean(wall_times_ms),
            "stdev": statistics.stdev(wall_times_ms) if len(wall_times_ms) > 1 else 0.0,
            "p50": pctl(50), "p95": pctl(95), "p99": pctl(99),
            "max": max(wall_times_ms),
        },
        "by_group": by_group,
        "by_molecule": by_molecule,
        "rows": rows,
        "wall_times_ms": wall_times_ms,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print()
    print("─" * 60)
    print(f"  routing_correctness  = {n_correct}/{len(rows)}  "
          f"= {n_correct/len(rows)*100:.1f}%")
    print(f"  agent_ok_rate        = {n_ok}/{len(rows)}  "
          f"= {n_ok/len(rows)*100:.1f}%")
    print(f"  wall-clock mean      = {report['wall_clock_ms']['mean']*1:.1f} ms"
          f"  (p95 = {report['wall_clock_ms']['p95']:.0f}, "
          f"p99 = {report['wall_clock_ms']['p99']:.0f})")
    print(f"  by group:")
    for g, b in sorted(by_group.items()):
        print(f"    {g:10s} {b['correct']:4d}/{b['total']:4d}  "
              f"({b['correct']/b['total']*100:.1f}%)")
    print(f"  results saved to {OUT_JSON}")

    if not args.no_fig:
        _make_figure(report, OUT_FIG)

    return 0 if (n_ok == len(rows)) else 1


if __name__ == "__main__":
    sys.exit(main())
