"""chemaster.agent MCP server — exposes the ChemMaster agent kernel itself.

This is the *agent-as-MCP-server* pattern: rather than only publishing the
individual chemistry tools (chem.const, chem.kb, calc_psi4, ...), we wrap
the **entire agent loop** as a single MCP tool. An external LLM client
(Claude Code, Cursor, OpenAI Codex CLI) can mount this server and call
``chemaster_run("Compute H2O HF/sto-3g energy")`` — the request is routed
through ChemMaster's L1/L2/L3 permission gates, MCP tool dispatch,
trajectory recording and finish-payload synthesis, then the structured
result is returned to the calling agent.

Why this matters for the thesis:
  §4.5.2 already shows three *tool* MCP servers being driven by an
  independent client. This server demonstrates that the **chemistry
  kernel itself** is MCP-protocol compliant and cross-client reusable —
  the strongest possible evidence that §1.3's "MCP-as-open-protocol"
  claim holds at the system level, not just the tool level.

Tools exposed:
  - chemaster_run        — run a complete chemistry task end-to-end
  - chemaster_list_skills — list skills available in the KB
  - chemaster_list_tools — list every tool the kernel can dispatch
  - chemaster_list_engines — detect psi4 / Gaussian / xtb / ORCA on PATH

Safety defaults:
  - Default LLM provider is ``mock`` (deterministic, no API key required).
    Pass ``provider="anthropic"`` (or any supported provider name) to use
    a real LLM. The caller must have the corresponding API key in env.
  - Confirms auto-approve (the calling LLM already has its own approval
    flow — double-confirming would block the protocol).
  - Each request gets its own temp ``runs/`` directory so concurrent
    requests don't trample each other.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)
mcp = FastMCP("chemaster.agent")


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers — lazy-imported so the MCP server starts fast and so that
# this module remains importable even if optional deps (psi4 etc.) are missing.
# ──────────────────────────────────────────────────────────────────────────────

def _build_agent(provider: str, max_turns: int, runs_dir: Path):
    """Construct a fresh ChemAgent per request.

    A new agent is built every call so:
      - concurrent MCP requests don't share state,
      - the LLM provider can vary per call,
      - the temp ``runs_dir`` stays isolated.

    For ``provider="mock"`` we attach the keyword-routing responder from
    :mod:`chemaster.agent.mock_routing` — the same one used by the
    response-rate benchmark (§4.4.2). That keeps the MCP server usable
    out-of-the-box without an API key, suitable for cross-client
    protocol-compliance demos.
    """
    from chemaster.agent.factory import build_chem_agent

    responder = None
    if provider == "mock":
        from chemaster.agent.mock_routing import build_routing_responder
        responder = build_routing_responder()
        responder.reset()

    agent = build_chem_agent(
        provider=provider,
        runs_dir=runs_dir,
        max_turns=max_turns,
        confirm_callback=lambda *_a, **_kw: True,  # auto-approve (caller is an LLM)
        mock_responder=responder,
    )
    return agent, agent.tools


def _summarize_trajectory(traj, agent=None) -> dict[str, Any]:
    """Compress a full Trajectory into a result blob safe to send over MCP.

    Includes the bits external clients usually care about:
      - status / task_id / finish_payload (the structured answer)
      - n_steps + tool-call sequence (so the caller can audit what happened)
      - elapsed_s
      - trajectory_path (where to find the full JSONL on disk)

    The finish payload is sourced from (in priority order):
      1. ``agent._finish_payload`` — set by the finish tool dispatcher
      2. ``traj.finish_payload`` — set when status="waiting_for_input"
      3. the most recent ``finish`` ToolCall arguments found in the steps
    """
    from datetime import datetime

    tool_calls: list[dict[str, Any]] = []
    finish_from_steps: dict[str, Any] | None = None
    for step in traj.steps:
        ass = step.assistant_message
        if not ass or not ass.tool_calls:
            continue
        for tc in ass.tool_calls:
            tool_calls.append({"step": step.step_id, "name": tc.name})
            if tc.name == "finish":
                finish_from_steps = dict(tc.arguments or {})

    finish_payload = (
        getattr(agent, "_finish_payload", None)
        or traj.finish_payload
        or finish_from_steps
    )

    elapsed_s = None
    if traj.started_at and traj.finished_at:
        try:
            t0 = datetime.fromisoformat(traj.started_at)
            t1 = datetime.fromisoformat(traj.finished_at)
            elapsed_s = (t1 - t0).total_seconds()
        except (ValueError, TypeError):
            pass

    out: dict[str, Any] = {
        "task_id": traj.task_id,
        "status": traj.status,
        "n_steps": len(traj.steps),
        "tool_calls": tool_calls,
        "finish_payload": finish_payload,
        "elapsed_s": elapsed_s,
        "started_at": traj.started_at,
        "finished_at": traj.finished_at,
    }

    # 权限分级透传：MCP 模式下没有交互通道，L2 化学决策会被自动接受。
    # 把这些决策显式回传给调用方 LLM —— 它有义务转述给它的用户，
    # 否则"labor-saving collaborator"的决策留痕在 MCP 形态下是隐形的。
    recs = (traj.meta or {}).get("recommendations")
    if recs and recs.get("log"):
        out["chemistry_decisions"] = {
            "accepted": recs.get("accepted", 0),
            "modified": recs.get("modified", 0),
            "cancelled": recs.get("cancelled", 0),
            "escalated": recs.get("escalated", 0),
            "log": [
                {k: r.get(k) for k in
                 ("decision", "recommendation", "decision_class",
                  "level", "status", "user_note")}
                for r in recs["log"]
            ],
            "note": (
                "These chemistry decisions were resolved without an "
                "interactive user (auto-accepted unless policy demoted them "
                "to L1 or escalated to L3). Relay them to your user."
            ),
        }
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Tool 1 — run a full chemistry task end-to-end
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def chemaster_run(
    intent: str,
    *,
    provider: str = "mock",
    max_turns: int = 20,
    input_data: str = "",
) -> dict[str, Any]:
    """Run a complete ChemMaster agent task and return the structured result.

    The natural-language ``intent`` is fed to the agent loop, which plans,
    calls the relevant MCP tools (psi4 / Gaussian / KB / unit conversion /
    visualisation / etc.), and finishes with a structured payload.

    Use this tool from any MCP-compatible client (Claude Code, Cursor, Codex)
    to delegate chemistry work to ChemMaster without re-implementing its
    permission gates, KB lookup or trajectory recording.

    When to use:
      - Driving an end-to-end chemistry workflow from another LLM agent.
      - Embedding ChemMaster into a larger multi-agent pipeline.
      - Verifying cross-client protocol compatibility.

    When NOT to use:
      - For pure unit conversion or constant lookup — call
        ``chemaster.mcp.const.server`` directly (lower overhead).
      - For KB search alone — call ``chemaster.mcp.kb.server`` directly.

    Args:
        intent: free-form task description, e.g.
                ``"Compute the HF/sto-3g energy of water"``.
        provider: LLM provider name. Default ``"mock"`` runs a deterministic
                  router suitable for protocol-compliance testing without an
                  API key. Real providers: ``"anthropic"``, ``"openai_compat"``,
                  ``"minimax"``, ``"qwen"``, ``"deepseek"``. The caller must
                  have the corresponding API key in env.
        max_turns: hard cap on the agent loop (default 20, max 60).
        input_data: optional extra context (XYZ, SMILES, …) appended to the
                    intent before agent planning.

    Returns:
        ``{
            "ok": True,
            "result": {
                "task_id": "...",
                "status": "completed" | "failed" | "waiting_for_input",
                "n_steps": 5,
                "tool_calls": [{"step": 1, "name": "io_lookup_by_name"}, ...],
                "finish_payload": {...},
                "elapsed_s": 0.3,
                "trajectory_path": "/tmp/.../trajectory.json"
            },
            "warnings": [],
            "meta": {"engine": "chemaster.agent v...", "provider": "..."}
        }``
    """
    if not intent or not intent.strip():
        return {
            "ok": False,
            "error_code": "EMPTY_INTENT",
            "details": "chemaster_run needs a non-empty intent string.",
            "suggestion": "Pass a natural-language task, e.g. 'Compute H2O HF/sto-3g energy'.",
        }
    max_turns = max(1, min(int(max_turns or 20), 60))

    # Isolated per-request runs dir so concurrent calls never collide.
    runs_dir = Path(tempfile.mkdtemp(prefix="chemaster_mcp_runs_"))

    try:
        from chemaster.agent.agent import BaseAgent
        from chemaster.agent.types import TaskInstance

        try:
            agent, registry = _build_agent(provider, max_turns, runs_dir)
        except Exception as exc:
            return {
                "ok": False,
                "error_code": "AGENT_INIT_FAILED",
                "details": f"Failed to construct ChemAgent (provider={provider!r}): {exc}",
                "suggestion": (
                    f"Verify the API key for provider {provider!r} is set, or "
                    "pass provider='mock' for a deterministic offline run."
                ),
            }

        task = TaskInstance(description=intent, input_data=input_data)
        try:
            traj = agent.run(task)
        except Exception as exc:
            return {
                "ok": False,
                "error_code": "AGENT_RUN_FAILED",
                "details": f"Agent loop raised: {type(exc).__name__}: {exc}",
                "suggestion": "Inspect runs_dir for partial trajectory.",
                "meta": {"runs_dir": str(runs_dir)},
            }

        summary = _summarize_trajectory(traj, agent=agent)
        traj_path = runs_dir / traj.task_id / "trajectory.json"
        summary["trajectory_path"] = str(traj_path) if traj_path.exists() else None

        return {
            "ok": True,
            "result": summary,
            "warnings": (
                [] if traj.status == "completed"
                else [{"code": "NON_COMPLETED_STATUS",
                       "message": f"Agent finished with status={traj.status!r}."}]
            ),
            "meta": {
                "engine": f"chemaster.agent {BaseAgent.VERSION}",
                "provider": provider,
                "n_tools_registered": len(registry),
                "max_turns": max_turns,
            },
        }
    finally:
        # Best-effort cleanup: keep runs dir if the user asked for it
        # explicitly via env, otherwise discard.
        if os.environ.get("CHEMASTER_KEEP_MCP_RUNS", "").strip().lower() not in ("1", "true", "yes"):
            shutil.rmtree(runs_dir, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────────────
# Tool 2 — list skills (delegates to chem.kb for consistency)
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def chemaster_list_skills() -> dict[str, Any]:
    """List every skill ChemMaster's knowledge base exposes.

    Equivalent to calling ``chem.kb.list_skills`` directly, but offered here
    so a client that mounts ``chemaster.agent`` doesn't have to mount two
    servers to discover capabilities.

    Returns:
        ``{
            "ok": True,
            "result": {"skills": [
                {"name": "opt-freq", "summary": "...", "version": "0.1.0"},
                ...
            ]},
            "warnings": [],
            "meta": {"engine": "chemaster.agent"}
        }``
    """
    try:
        from chemaster.mcp.kb.server import list_skills as _kb_list_skills
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "KB_IMPORT_FAILED",
            "details": str(exc),
            "suggestion": "Verify chemaster.mcp.kb is installed correctly.",
        }
    return _kb_list_skills()


# ──────────────────────────────────────────────────────────────────────────────
# Tool 3 — enumerate every tool the agent kernel can dispatch
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def chemaster_list_tools() -> dict[str, Any]:
    """List every tool registered with the ChemMaster agent kernel.

    Returns each tool's name plus a one-line description so an external
    LLM can decide whether ``chemaster_run`` is likely to dispatch what it
    needs, or whether it should call a more specific MCP server directly.

    Returns:
        ``{
            "ok": True,
            "result": {
                "n_tools": 43,
                "tools": [
                    {"name": "calc_psi4_single_point", "summary": "..."},
                    ...
                ]
            },
            "warnings": [],
            "meta": {"engine": "chemaster.agent"}
        }``
    """
    try:
        from chemaster.agent.tool_loader import build_default_registry
        registry = build_default_registry()
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "REGISTRY_BUILD_FAILED",
            "details": f"Could not build tool registry: {exc}",
            "suggestion": "Run `pytest tests/unit/test_tool_loader.py` to diagnose.",
        }

    tools: list[dict[str, str]] = []
    for spec in registry.specs():
        desc = (spec.description or "").strip().splitlines()
        summary = desc[0][:200] if desc else ""
        tools.append({"name": spec.name, "summary": summary})

    return {
        "ok": True,
        "result": {"n_tools": len(tools), "tools": tools},
        "warnings": [],
        "meta": {"engine": "chemaster.agent"},
    }


# ──────────────────────────────────────────────────────────────────────────────
# Tool 4 — detect computational chemistry engines on PATH
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def chemaster_list_engines() -> dict[str, Any]:
    """Report which quantum-chemistry engines are detected on the local PATH.

    Useful for a remote client to know whether ``chemaster_run`` can
    dispatch to Gaussian / psi4 / xtb / ORCA / BDF / MOMAP on the host
    machine, *before* spending tokens on a task that needs them.

    Returns:
        ``{
            "ok": True,
            "result": {
                "psi4":     {"available": True,  "path": "/opt/.../psi4"},
                "xtb":      {"available": False, "path": null},
                "gaussian": {"available": False, "path": null},
                "orca":     {"available": False, "path": null},
                "bdf":      {"available": False, "path": null},
                "momap":    {"available": False, "path": null}
            },
            "warnings": [],
            "meta": {"engine": "chemaster.agent"}
        }``
    """
    from chemaster.engines import probe_engines

    out: dict[str, Any] = {
        s.name: {"available": s.available, "path": s.path}
        for s in probe_engines()
    }
    return {
        "ok": True,
        "result": out,
        "warnings": [],
        "meta": {"engine": "chemaster.agent"},
    }


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Run the chemaster.agent MCP server on stdio.

    Intended for invocation from an MCP client config:

        {
          "mcpServers": {
            "chemmaster": {
              "command": "python",
              "args": ["-m", "chemaster.mcp.agent.server"]
            }
          }
        }
    """
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
