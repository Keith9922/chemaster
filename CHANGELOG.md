# Changelog

所有面向用户可见的变更记录在此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- 项目骨架与设计文档完整版（CLAUDE.md、ROADMAP.md、ARCHITECTURE.md、PITFALLS.md、PACKAGING.md、SETUP.md、SKILLS_GUIDE.md、MCP_GUIDE.md、TADF_PIPELINE.md、CONVENTIONS.md）
- 仓库目录结构（chemaster/agent、chemaster/mcp/*、chemaster/skills/*、chemaster/kb、chemaster/tui）
- pyproject.toml + .gitignore + LICENSE

### Planned (Phase 1)
- 第一个 MCP server: `chem.const`
- 第一个 MCP server: `chem.io.ase`
- 第一个 MCP server: `chem.calc.psi4`
- 第一个 MCP server: `chem.parse.cclib`
- Agent core 三段式骨架
- Textual TUI 入口
- H2O 端到端闭环 demo

## [0.1.0] - 待发布

首个 alpha 版本：跑通 H2O / 苯环 的 opt+freq 闭环。
