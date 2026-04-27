"""chem.calc_orca MCP server.

TODO: implement per docs/MCP_GUIDE.md. See chem.const for reference.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chem.calc_orca")


# TODO Phase 1+: add @mcp.tool() functions.
# Each tool must:
#   - Have full docstring (when_to_use / when_not_to_use)
#   - Strict typed params (no **kwargs)
#   - Return {"ok": bool, "result": ..., "warnings": [...], "meta": {...}}
#   - On error return {"ok": False, "error_code": "...", "suggestion": "..."}
#   - Physical quantities carry "unit" field
#   - Check known PITFALLS before processing


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
