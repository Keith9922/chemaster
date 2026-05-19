#!/usr/bin/env python3
"""MCP 协议合规性探针.

用一个独立的 MCP 客户端（直接走 stdio MCP 协议）连接到 ChemMaster 的几个
MCP server，验证：
  1. server 能在 stdio 模式启动
  2. server 能响应 `tools/list` 请求
  3. server 能响应实际的工具调用并返回 MCP 标准格式

这是论文 §4.4.2 "MCP 跨客户端复用" 的最小可验证版本——证明 MCP server
确实是协议级别的可复用组件，独立客户端（不依赖 Claude Code、Cursor 等）
也能调用。Claude Code / Cursor 走的是同一套 stdio MCP 协议，所以这个探
针通过即等价于跨客户端复用能力的验证。

输出：benchmarks/use_cases/mcp_cross_client/probe_results.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "benchmarks" / "use_cases" / "mcp_cross_client"
OUT_DIR.mkdir(parents=True, exist_ok=True)


async def probe_server(server_module: str, calls: list[dict]) -> dict:
    """Spawn a ChemMaster MCP server and exercise it via the standard
    MCP stdio protocol. Uses the official `mcp` python client to make
    sure we are speaking the actual protocol, not a private API."""
    try:
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
    except ImportError as exc:
        return {"ok": False, "error": f"mcp client lib missing: {exc}"}

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", server_module],
    )
    out: dict = {"server": server_module, "ok": False, "tools": [], "calls": []}
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                out["tools"] = [t.name for t in tools.tools]
                for c in calls:
                    try:
                        result = await session.call_tool(
                            c["name"], arguments=c.get("args", {}))
                        # Result is mcp.types.CallToolResult; pick first text block.
                        text_blocks = [b for b in result.content
                                       if hasattr(b, "text")]
                        snippet = (text_blocks[0].text[:500]
                                   if text_blocks else repr(result)[:500])
                        out["calls"].append({
                            "name": c["name"],
                            "args": c.get("args", {}),
                            "ok": not result.isError,
                            "response_preview": snippet,
                        })
                    except Exception as exc:
                        out["calls"].append({
                            "name": c["name"],
                            "args": c.get("args", {}),
                            "ok": False,
                            "error": f"{type(exc).__name__}: {exc}",
                        })
                out["ok"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


async def amain() -> int:
    print("Probing ChemMaster MCP servers via standard MCP stdio protocol...")
    print()

    targets = [
        {
            "module": "chemaster.mcp.const.server",
            "calls": [
                {"name": "convert_unit",
                 "args": {"value": 1.0, "from_unit": "hartree",
                           "to_unit": "eV"}},
                {"name": "get_constant", "args": {"name": "planck"}},
            ],
        },
        {
            "module": "chemaster.mcp.kb.server",
            "calls": [
                {"name": "kb_search", "args": {"query": "TADF kRISC"}},
                {"name": "list_skills", "args": {}},
            ],
        },
        {
            "module": "chemaster.mcp.calc_psi4.server",
            "calls": [
                # Not invoking psi4 here (would take wall time);
                # only listing tools to confirm the server speaks MCP.
            ],
        },
        {
            # Headline cross-client claim: ChemMaster's **entire agent
            # kernel** is itself MCP-exposed. An external client mounting
            # this server gets `chemaster_run(intent)` as if ChemMaster were
            # a single chemistry tool. Mirrors the Codex-style
            # "agent-as-MCP-server" pattern.
            "module": "chemaster.mcp.agent.server",
            "calls": [
                {"name": "chemaster_list_engines", "args": {}},
                {"name": "chemaster_list_tools", "args": {}},
                # A short mock-LLM run proves the full agent loop is
                # reachable through the protocol. The intent routes to a
                # cheap constant lookup, then `finish`.
                {"name": "chemaster_run",
                 "args": {"intent": "look up the planck constant",
                          "provider": "mock", "max_turns": 5}},
            ],
        },
    ]

    results = []
    for t in targets:
        print(f"  → probing {t['module']}...")
        r = await probe_server(t["module"], t["calls"])
        if r.get("ok"):
            n_calls = len(r.get("calls", []))
            n_call_ok = sum(1 for c in r["calls"] if c.get("ok"))
            print(f"    initialised, {len(r['tools'])} tools listed, "
                  f"{n_call_ok}/{n_calls} call(s) succeeded")
        else:
            print(f"    FAILED: {r.get('error')}")
        results.append(r)
        print()

    summary = {
        "data_source": "real_protocol_probe",
        "method": (
            "Standard MCP stdio client (anthropic mcp python lib) connecting "
            "to ChemMaster MCP servers as separate subprocesses, exactly the "
            "same protocol used by Claude Code, Cursor, and other MCP-aware "
            "LLM clients. A successful probe demonstrates protocol-level "
            "compliance and therefore cross-client reusability."
        ),
        "n_servers_probed": len(results),
        "n_servers_ok": sum(1 for r in results if r.get("ok")),
        "results": results,
        "interpretation": (
            "All servers that initialised and answered list_tools / call_tool "
            "via the standard MCP protocol can in principle be used by any "
            "MCP-compatible client. Claude Code or Cursor users can configure "
            "ChemMaster MCP servers in their respective mcp config files and "
            "obtain the same tool surface."
        ),
    }
    out_path = OUT_DIR / "probe_results.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False,
                                     default=str))
    print(f"Result written to {out_path}")
    print(f"Servers OK: {summary['n_servers_ok']} / {summary['n_servers_probed']}")
    return 0 if summary["n_servers_ok"] == summary["n_servers_probed"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
