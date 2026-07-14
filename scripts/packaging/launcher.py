"""PyInstaller entry point for the chemaster CLI.

Wraps `chemaster.cli.main` so PyInstaller has a clean script-style entry.
"""
from __future__ import annotations

from chemaster.cli import main

if __name__ == "__main__":
    main()
