"""MCP servers —— 类型化原子操作。详见 docs/MCP_GUIDE.md。

所有 server 通过 ``chemaster-mcp <name>`` 启动（pyproject.toml 注册）。
"""

from __future__ import annotations

import importlib.metadata
import sys


def list_servers() -> list[str]:
    """列出已注册的 MCP server 名。"""
    eps = importlib.metadata.entry_points(group="chemaster.mcps")
    return sorted(ep.name for ep in eps)


def dispatcher_main() -> None:
    """``chemaster-mcp <name>`` 入口：按名启动指定 server。"""
    if len(sys.argv) < 2:
        print("Usage: chemaster-mcp <server-name>")
        print("Available servers:")
        for name in list_servers():
            print(f"  - {name}")
        sys.exit(1)

    name = sys.argv[1]
    eps = importlib.metadata.entry_points(group="chemaster.mcps")
    matches = [ep for ep in eps if ep.name == name]
    if not matches:
        print(f"Unknown server: {name!r}. Available: {list_servers()}", file=sys.stderr)
        sys.exit(2)

    server = matches[0].load()
    server.run(transport="stdio")
