"""ChemMaster agent kernel exposed as an MCP server.

External LLM clients (Claude Code, Cursor, OpenAI Codex CLI, any
MCP-compatible client) can mount this server and call the ChemMaster
agent as if it were a single chemistry tool. This is the "Codex-style"
pattern of `agent-as-mcp-server` — the same architectural move that lets
Codex be invoked from Claude Code and vice versa.

Tools exposed:
  - chemaster_run(intent)         — run a complete chemistry task end-to-end
  - chemaster_list_skills()       — list skills available in the KB
  - chemaster_list_tools()        — list every tool the kernel can dispatch
  - chemaster_list_engines()      — detect psi4 / Gaussian / xtb / ORCA on PATH

Run with:
  python -m chemaster.mcp.agent.server
  # or
  chemaster mcp-serve
"""
