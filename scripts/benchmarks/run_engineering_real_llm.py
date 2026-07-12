#!/usr/bin/env python3
"""真实 LLM 工程指标采集 — mock 路由版指标的真 LLM 对照。

mock 版（run_execution_and_scalability.py / run_engineering_real.py）测的是
"系统"的稳定性：真 agent loop + 确定性路由。本脚本把 LLM 换成真实 API，
测的是"系统 + 真实大模型"的端到端表现——同一套题库、同一套判据：

  A. execution_correctness_real_llm — 5 组意图 × 20 phrasing = 100 条
     成功 = 不崩 + 期望工具出现在调用序列 + 干净 finish。
  B. fault_recovery_real_llm — 5 类故障 × 5 trial = 25 次注入
     成功 = L1 依 suggestion 恢复，或重试耗尽后干净升级 ask_user。
     与 mock 版的差别：mock responder "知道"修复魔法值；真 LLM 只能从
     suggestion 文本推断，所以修复判定放宽为语义谓词（换了 scratch 路径
     即算修、timeout 调大即算修、瞬时错误重试即算修）——与人类操作员的
     判断口径一致，谓词随数据一起记录。
  C. trajectory_breakdown_real_llm — 5 个 anchor 任务的自主步占比。

输出 benchmarks/engineering_metrics/*_real_llm.json —— **绝不覆盖 mock 版
文件**（N=10000 数据曾被重跑覆盖丢失，教训记入 CLAUDE.md §8）。

用法:
  python scripts/benchmarks/run_engineering_real_llm.py \
      --provider minimax [--smoke] [--only A,B,C] [--limit-phrasings N]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "benchmarks" / "engineering_metrics"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tool_sequence(traj) -> list[str]:
    seq: list[str] = []
    for step in traj.steps:
        am = step.assistant_message
        if am:
            seq.extend(tc.name for tc in am.tool_calls)
    return seq


def _usage_totals(traj) -> dict:
    tin = tout = 0
    for step in traj.steps:
        am = step.assistant_message
        usage = (am.meta or {}).get("usage") if am else None
        if usage:
            tin += int(usage.get("input_tokens", 0) or 0)
            tout += int(usage.get("output_tokens", 0) or 0)
    return {"input_tokens": tin, "output_tokens": tout}


def _fresh_agent(provider: str, model: str | None, registry=None,
                 max_turns: int = 8):
    """每个 trial 一个全新 agent（干净 dialog / trajectory）。"""
    from chemaster.agent.agent import AgentConfig, ChemAgent
    from chemaster.agent.factory import build_chem_agent
    from chemaster.agent.llm_client import LLMConfig, create_llm

    runs_dir = Path(tempfile.mkdtemp(prefix="chemaster_realllm_"))
    if registry is None:
        return build_chem_agent(
            provider=provider, model=model, runs_dir=runs_dir,
            max_turns=max_turns,
            confirm_callback=lambda *_a, **_kw: True,   # 无人值守
        )
    llm = create_llm(LLMConfig(provider=provider, model=model))
    return ChemAgent(llm=llm, tools=registry, config=AgentConfig(
        max_turns=max_turns, runs_dir=runs_dir,
        confirm_callback=lambda *_a, **_kw: True,
    ))


# ══════════════════════════════════════════════════════════════════════════════
# 指标 A — execution correctness（真 LLM 路由 100 条双语意图）
# ══════════════════════════════════════════════════════════════════════════════

# 每组"语义正确"的合法工具集合。mock 版的 expected_tool 是为确定性路由器
# 定制的单一目标（其中 optimize 组甚至写的是 mock 路由器的 SP fallback）；
# 真 LLM 用 const_convert 回答单位换算、用 use_skill 直接读 skill 都属于
# 正确路由，按单一 expected_tool 判会把评测 artifact 算成模型错误。
# JSON 里同时记录两种口径（semantic / mock_criterion）。
ACCEPTABLE_TOOLS: dict[str, set[str]] = {
    "energy": {"calc_psi4_single_point"},
    "constant": {"const_get", "const_convert"},
    "kb": {"kb_search", "use_skill", "list_skills"},
    "optimize": {"calc_psi4_optimize"},
    "skill": {"use_skill", "list_skills"},
}


def indicator_a(provider: str, model: str | None,
                limit_phrasings: int | None) -> dict:
    exec_mod = _load_module(
        ROOT / "scripts" / "benchmarks" / "run_execution_and_scalability.py",
        "exec_scal",
    )
    groups = exec_mod.TEST_INTENTS

    results = []
    t0 = time.time()
    usage_total = {"input_tokens": 0, "output_tokens": 0}
    n_recommends = 0

    for group in groups:
        acceptable = ACCEPTABLE_TOOLS.get(
            group["group"], {group["expected_tool"]})
        phrasings = group["phrasings"]
        if limit_phrasings:
            phrasings = phrasings[:limit_phrasings]
        for phrasing in phrasings:
            from chemaster.agent.types import TaskInstance
            trial = {"group": group["group"], "intent": phrasing,
                     "acceptable_tools": sorted(acceptable),
                     "mock_expected_tool": group["expected_tool"]}
            t1 = time.time()
            try:
                agent = _fresh_agent(provider, model, max_turns=10)
                traj = agent.run(TaskInstance(description=phrasing))
                seq = _tool_sequence(traj)
                usage = _usage_totals(traj)
                usage_total["input_tokens"] += usage["input_tokens"]
                usage_total["output_tokens"] += usage["output_tokens"]
                n_recommends += len(
                    (traj.meta.get("recommendations") or {}).get("log", []))
                trial.update({
                    "agent_ok": traj.status == "completed",
                    "routed_ok": any(t in seq for t in acceptable),
                    "mock_criterion_ok": group["expected_tool"] in seq,
                    "status": traj.status,
                    "tool_sequence": seq,
                    "n_steps": len(traj.steps),
                })
            except Exception as exc:  # noqa: BLE001 — 记录为失败，不中断批次
                trial.update({
                    "agent_ok": False, "routed_ok": False,
                    "mock_criterion_ok": False,
                    "status": "exception",
                    "error": f"{type(exc).__name__}: {exc}",
                })
            trial["wall_s"] = round(time.time() - t1, 2)
            results.append(trial)
            mark = "✓" if trial.get("routed_ok") else "✗"
            print(f"  [{group['group']:<10}] {mark} {phrasing[:50]!r} "
                  f"({trial['wall_s']}s)", flush=True)

    n = len(results)
    n_agent_ok = sum(r["agent_ok"] for r in results)
    n_routed = sum(r["routed_ok"] for r in results)
    n_mock_crit = sum(r["mock_criterion_ok"] for r in results)
    per_group = {}
    for g in groups:
        rs = [r for r in results if r["group"] == g["group"]]
        per_group[g["group"]] = {
            "n": len(rs),
            "agent_ok": sum(r["agent_ok"] for r in rs),
            "routed_ok": sum(r["routed_ok"] for r in rs),
        }

    return {
        "data_source": "real_llm",
        "provider": provider,
        "model": model or "(provider default)",
        "method": (
            "Same 5 intent groups × bilingual phrasings as the mock-routing "
            "execution_correctness.json, driven by a real LLM over the full "
            "default tool registry (54 tools). routed_ok: any semantically "
            "acceptable tool for the group appears in the call sequence "
            "(see acceptable_tools per trial); mock_criterion_ok kept for "
            "comparison with the mock harness's single expected_tool."
        ),
        "generated_at": _now(),
        "n_total": n,
        "agent_ok": n_agent_ok,
        "agent_ok_rate_pct": round(100 * n_agent_ok / n, 1) if n else 0,
        "routed_ok": n_routed,
        "routing_rate_pct": round(100 * n_routed / n, 1) if n else 0,
        "mock_criterion_ok": n_mock_crit,
        "mock_criterion_rate_pct": round(100 * n_mock_crit / n, 1) if n else 0,
        "per_group": per_group,
        "n_recommend_cards_auto_accepted": n_recommends,
        "usage_totals": usage_total,
        "wall_s_total": round(time.time() - t0, 1),
        "trials": results,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 指标 B — 故障自愈（真 LLM 读 suggestion 恢复）
# ══════════════════════════════════════════════════════════════════════════════

# 与 run_engineering_real.py 的 5 类故障同源；修复判定改为语义谓词。
REAL_FAULT_SPECS = {
    "F1_scf_bad_guess": dict(
        tool_name="calc_psi4_optimize",
        arg_hint="method='B3LYP', basis='sto-3g', guess='SAD'",
        error_code="SCF_NOT_CONVERGED",
        details="Residual 1e-3 at iter 200 with SAD initial guess.",
        suggestion="Try guess=GWH or drop to def2-SVP first.",
        is_fixed=lambda kw: str(kw.get("guess", "")).upper() == "GWH"
        or "svp" in str(kw.get("basis", "")).lower(),
        ok_msg="final_energy=-76.42 Hartree",
    ),
    "F2_disk_full": dict(
        tool_name="calc_gaussian_optimize",
        arg_hint="scratch_dir='/tmp/scratch'",
        error_code="IO_ERROR_NOSPACE",
        details="No space left on device under /tmp/scratch (98% full).",
        suggestion="Set scratch_dir to a different path with >=10 GB free.",
        is_fixed=lambda kw: bool(kw.get("scratch_dir"))
        and str(kw.get("scratch_dir")) not in ("/tmp/scratch", "wrong_value"),
        ok_msg="job ok; scf_energy=-40.5 Hartree",
    ),
    "F3_input_syntax": dict(
        tool_name="calc_psi4_single_point",
        arg_hint="method='b3lpy'",
        error_code="INPUT_SYNTAX",
        details="Unknown method 'b3lpy'; allowed are HF/B3LYP/M06-2X/wB97X.",
        suggestion="Set method to one of the allowed values "
                   "(suspected typo: 'b3lpy' -> 'B3LYP').",
        is_fixed=lambda kw: str(kw.get("method", "")).upper() in
        ("HF", "B3LYP", "M06-2X", "WB97X"),
        ok_msg="ok; method run at sto-3g",
    ),
    "F4_network_glitch": dict(
        tool_name="hpc_slurm_submit",
        arg_hint="script_path='job.sh'",
        error_code="NETWORK_TRANSIENT",
        details="Connection reset by peer on ssh control channel.",
        suggestion="Transient network error; simply retry the submit "
                   "(it is idempotent).",
        is_fixed=lambda kw: True,   # 瞬时故障：重试本身就是修复
        ok_msg="job_id=12345 queued",
    ),
    "F5_timeout": dict(
        tool_name="calc_orca_optimize",
        arg_hint="timeout_s=120",
        error_code="TIMEOUT",
        details="Job exceeded timeout_s=120; partial output preserved.",
        suggestion="Increase timeout_s (e.g. 600) and resubmit.",
        is_fixed=lambda kw: float(kw.get("timeout_s") or 0) > 120,
        ok_msg="ok; converged after 480 s",
    ),
}


def _build_real_faulty_tool(fault_type: str, fail_first_n: int):
    from chemaster.agent.tool_registry import BaseTool, ToolResult

    spec = REAL_FAULT_SPECS[fault_type]

    class FaultyTool(BaseTool):
        name = spec["tool_name"]
        description = (
            f"Run a {spec['tool_name'].replace('_', ' ')} job. "
            f"Typical args: {spec['arg_hint']}."
        )
        input_schema = {"type": "object"}
        is_long_running = False

        def __init__(self) -> None:
            self.calls: list[dict] = []
            self.fails_remaining = fail_first_n

        def run(self, **kwargs) -> ToolResult:
            self.calls.append(dict(kwargs))
            try:
                fixed = bool(spec["is_fixed"](kwargs))
            except Exception:
                fixed = False
            if self.fails_remaining > 0 and not fixed:
                self.fails_remaining -= 1
                return ToolResult(
                    ok=False,
                    observation=(
                        f"[{spec['error_code']}]\n"
                        f"Details: {spec['details']}\n"
                        f"Suggestion: {spec['suggestion']}"
                    ),
                    data={"ok": False, "error_code": spec["error_code"],
                          "suggestion": spec["suggestion"]},
                    is_error=False,
                )
            return ToolResult(
                ok=True,
                observation=f"[OK] {spec['tool_name']}\n{spec['ok_msg']}",
                data={"ok": True, "result": {"msg": spec["ok_msg"]}},
            )

    return FaultyTool(), spec


def indicator_b(provider: str, model: str | None, trials_per_fault: int) -> dict:
    from chemaster.agent.builtins import register_builtins
    from chemaster.agent.tool_registry import ToolRegistry
    from chemaster.agent.types import TaskInstance

    fail_schedule = (1, 1, 2, 2, 3)[:trials_per_fault]
    trials = []
    t0 = time.time()
    usage_total = {"input_tokens": 0, "output_tokens": 0}

    for fault_type in REAL_FAULT_SPECS:
        for idx, fail_first_n in enumerate(fail_schedule):
            flaky, spec = _build_real_faulty_tool(fault_type, fail_first_n)
            registry = ToolRegistry()
            register_builtins(registry)
            registry.register(flaky)

            intent = (
                f"Use the `{spec['tool_name']}` tool to run this job. "
                f"Start with exactly these arguments: {spec['arg_hint']}. "
                "Get the job to complete."
            )
            trial = {"fault": fault_type, "trial": idx,
                     "fail_first_n": fail_first_n}
            t1 = time.time()
            try:
                agent = _fresh_agent(provider, model, registry=registry,
                                     max_turns=10)
                traj = agent.run(TaskInstance(description=intent))
                usage = _usage_totals(traj)
                usage_total["input_tokens"] += usage["input_tokens"]
                usage_total["output_tokens"] += usage["output_tokens"]
                tool_succeeded = any(
                    "[OK]" in (tr.content or "")
                    for step in traj.steps for tr in step.tool_responses
                    if tr.name == spec["tool_name"]
                )
                escalated = traj.status == "waiting_for_input"
                recovered = traj.status == "completed" and tool_succeeded
                trial.update({
                    "status": traj.status,
                    "n_tool_calls": len(flaky.calls),
                    "recovered_l1": recovered,
                    "escalated_clean": escalated,
                    "handled": recovered or escalated,
                })
            except Exception as exc:  # noqa: BLE001
                trial.update({
                    "status": "exception", "handled": False,
                    "recovered_l1": False, "escalated_clean": False,
                    "error": f"{type(exc).__name__}: {exc}",
                })
            trial["wall_s"] = round(time.time() - t1, 2)
            trials.append(trial)
            mark = ("✓L1" if trial.get("recovered_l1")
                    else "↑L3" if trial.get("escalated_clean") else "✗")
            print(f"  [{fault_type:<18}] trial {idx} fail_n={fail_first_n} "
                  f"{mark} ({trial['wall_s']}s)", flush=True)

    n = len(trials)
    n_handled = sum(t["handled"] for t in trials)
    n_l1 = sum(t["recovered_l1"] for t in trials)
    n_l3 = sum(t["escalated_clean"] for t in trials)
    return {
        "data_source": "real_llm",
        "provider": provider,
        "model": model or "(provider default)",
        "method": (
            "Same 5 fault classes / fail_first_n schedule as the mock "
            "fault_recovery.json, driven by a real LLM reading the error "
            "suggestion. Fix detection is semantic (any changed scratch dir, "
            "timeout>120, allowed method, retry for transients) because the "
            "mock responder knew magic values a real operator cannot. "
            "handled = autonomous L1 recovery OR clean ask_user escalation."
        ),
        "generated_at": _now(),
        "n_trials_total": n,
        "n_recovered_l1": n_l1,
        "n_escalated_clean": n_l3,
        "n_handled": n_handled,
        "handled_rate_pct": round(100 * n_handled / n, 1) if n else 0,
        "l1_recovery_rate_pct": round(100 * n_l1 / n, 1) if n else 0,
        "acceptance_target_pct": 80.0,
        "pass_overall": (100 * n_handled / n) >= 80.0 if n else False,
        "usage_totals": usage_total,
        "wall_s_total": round(time.time() - t0, 1),
        "trials": trials,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 指标 C — trajectory 自主步占比（真 LLM）
# ══════════════════════════════════════════════════════════════════════════════

ANCHOR_TASKS = [
    "Compute the energy of H2",
    "Optimize H2",
    "Look up the value of Planck constant",
    "Search KB for B3LYP-D3 basis set rules",
    "Use skill opt-freq",
]


def indicator_c(provider: str, model: str | None,
                anchors: list[str]) -> dict:
    from chemaster.agent.types import TaskInstance

    total = {"agent": 0, "user-binary": 0, "user-chemistry": 0, "system": 0}
    per_task = []
    t0 = time.time()

    for intent in anchors:
        entry = {"intent": intent}
        try:
            agent = _fresh_agent(provider, model, max_turns=8)
            traj = agent.run(TaskInstance(description=intent))
            counts = {"agent": 0, "user-binary": 0,
                      "user-chemistry": 0, "system": 0}
            for step in traj.steps:
                for tr in step.tool_responses:
                    auth = (tr.meta or {}).get("decision_authority")
                    if auth in counts:
                        counts[auth] += 1
            for k, v in counts.items():
                total[k] += v
            entry.update({"status": traj.status, "authority_counts": counts,
                          "tool_sequence": _tool_sequence(traj)})
        except Exception as exc:  # noqa: BLE001
            entry.update({"status": "exception",
                          "error": f"{type(exc).__name__}: {exc}"})
        per_task.append(entry)
        print(f"  [3c] {intent[:40]!r} → {entry.get('status')}", flush=True)

    n_tagged = sum(total.values())
    return {
        "data_source": "real_llm",
        "provider": provider,
        "model": model or "(provider default)",
        "method": (
            "Same 5 anchor tasks as the mock trajectory_breakdown.json, "
            "driven by a real LLM over the full registry; counts "
            "decision_authority tags on tool responses."
        ),
        "generated_at": _now(),
        "authority_totals": total,
        "n_tagged_steps": n_tagged,
        "autonomous_fraction_pct": (
            round(100 * total["agent"] / n_tagged, 1) if n_tagged else 0
        ),
        "acceptance_target_pct": 70.0,
        "per_task": per_task,
        "wall_s_total": round(time.time() - t0, 1),
    }


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provider", default="minimax")
    ap.add_argument("--model", default=None)
    ap.add_argument("--only", default="A,B,C",
                    help="comma list of indicators to run (A,B,C)")
    ap.add_argument("--limit-phrasings", type=int, default=None,
                    help="cap phrasings per intent group (A)")
    ap.add_argument("--trials-per-fault", type=int, default=5)
    ap.add_argument("--smoke", action="store_true",
                    help="tiny run: 2 phrasings/group, 1 trial/fault, 2 anchors")
    args = ap.parse_args()

    only = {s.strip().upper() for s in args.only.split(",")}
    limit = 2 if args.smoke else args.limit_phrasings
    trials_per_fault = 1 if args.smoke else args.trials_per_fault
    anchors = ANCHOR_TASKS[:2] if args.smoke else ANCHOR_TASKS
    suffix = "_smoke" if args.smoke else ""

    print(f"provider={args.provider} model={args.model or '(default)'} "
          f"only={sorted(only)} smoke={args.smoke}", flush=True)

    if "A" in only:
        print("\n== A. execution correctness (real LLM) ==", flush=True)
        blob = indicator_a(args.provider, args.model, limit)
        out = OUT_DIR / f"execution_correctness_real_llm{suffix}.json"
        out.write_text(json.dumps(blob, indent=2, ensure_ascii=False))
        print(f"→ {out}  agent_ok={blob['agent_ok_rate_pct']}%  "
              f"routing={blob['routing_rate_pct']}%", flush=True)

    if "B" in only:
        print("\n== B. fault recovery (real LLM) ==", flush=True)
        blob = indicator_b(args.provider, args.model, trials_per_fault)
        out = OUT_DIR / f"fault_recovery_real_llm{suffix}.json"
        out.write_text(json.dumps(blob, indent=2, ensure_ascii=False))
        print(f"→ {out}  handled={blob['handled_rate_pct']}%  "
              f"(L1 {blob['n_recovered_l1']} / L3 {blob['n_escalated_clean']})",
              flush=True)

    if "C" in only:
        print("\n== C. trajectory autonomy (real LLM) ==", flush=True)
        blob = indicator_c(args.provider, args.model, anchors)
        out = OUT_DIR / f"trajectory_breakdown_real_llm{suffix}.json"
        out.write_text(json.dumps(blob, indent=2, ensure_ascii=False))
        print(f"→ {out}  autonomous={blob['autonomous_fraction_pct']}%",
              flush=True)

    print("\nDONE_REAL_LLM_METRICS", flush=True)


if __name__ == "__main__":
    main()
