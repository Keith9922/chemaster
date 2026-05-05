"""ChemMaster local Web frontend.

Architecture:
- FastAPI backend exposing the agent + tool registry as REST + Server-Sent
  Events streams.
- Static SPA (single-file HTML + vanilla JS) for the browser UI.

The Web frontend is the third surface (alongside CLI + TUI) of ChemMaster.
Same agent kernel, same MCP tool set, different presentation layer suited
to chemistry researchers who prefer visual interaction (structure rendering,
spectrum plots, results tables) over command line.

Launch via: `chemaster web` (defined in cli.py).
"""

from chemaster.web.app import create_app, main

__all__ = ["create_app", "main"]
