"""ChemMaster — 面向 TADF 发光体设计的本地化计算化学 Agent。

主入口：
- 命令行 / TUI: ``chemaster.cli.main``
- MCP servers: ``chemaster.mcp.*.server``
- Agent core: ``chemaster.agent``
- 知识库公式: ``chemaster.kb.formulas``
- Skill 库: ``chemaster.kb.skills`` (Markdown 形式)

详见仓库根目录的 CLAUDE.md。
"""

__version__ = "0.2.0a1"
__all__ = ["__version__"]
