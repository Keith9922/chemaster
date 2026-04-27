# CONVENTIONS — 代码与协作规范

---

## 1. Python 风格

- **Python 3.11**（不要用 3.12+ 特性以兼容 conda-forge）
- 格式化与 lint：`ruff format` + `ruff check`，配置在 `pyproject.toml`。
- 行宽 100。
- 类型注解：所有公开函数必须有 type hint。私有可省。
- 字符串：双引号优先（与 Black/ruff 默认一致）。
- f-string 优先于 `.format()`。

---

## 2. 命名

| 对象 | 风格 | 示例 |
|---|---|---|
| 模块 | `snake_case` | `chem.calc.psi4` |
| 类 | `PascalCase` | `PlanStep`, `LLMClient` |
| 函数/变量 | `snake_case` | `optimize_geometry` |
| 常量 | `UPPER_SNAKE` | `DEFAULT_BASIS = "def2-TZVP"` |
| MCP server 名 | `chem.<域>.<工具>` | `chem.calc.psi4` |
| MCP 工具名 | `snake_case` | `optimize`, `single_point` |
| Skill 目录 | `kebab-case` | `tadf-pipeline` |
| 测试 | `test_<被测>` | `test_const.py::test_convert_unit` |

---

## 3. 物理量与单位

- 进 MCP 边界：长度 Å、能量 eV、时间 s、温度 K。
- 出 MCP 边界：返回值带 `unit` 字段，例 `{"energy": -76.4, "unit": "Hartree"}`。
- 内部转换：`chemaster.kb.formulas.units` 模块；用 `pint.Quantity`。
- 几何：xyz 字符串或 `[(elem, x, y, z), ...]` list。元素符号大写。

---

## 4. 错误处理

- MCP 永远不抛异常给 LLM。返回 `{ok: bool, ...}`。
- 内部 Python 代码可以正常 raise；MCP wrapper 层 catch 后转结构化错误。
- 错误码命名：`UPPER_SNAKE`，例 `SCF_NOT_CONVERGED`、`IMAGINARY_FREQUENCY_FOUND`。
- 每个错误码必须文档化在对应 MCP 的 `README.md` 的 "Error codes" 节。

---

## 5. 日志

- 用 `logging`（不用 `print`）。
- 日志写到 `runs/<task-id>/logs/<module>.log`。
- 级别：DEBUG 详细 / INFO 关键路径 / WARNING 可恢复 / ERROR 任务失败。
- 计算软件原始 stdout/stderr 写 `runs/<task-id>/step_N/output.log`。

---

## 6. 测试

- 单元测试：`tests/unit/test_<module>.py`，mock 外部软件。
- 集成测试：`tests/integration/test_<workflow>.py`，真跑小体系（H2、H2O 等）。
- fixtures：`tests/fixtures/` 放预生成的输出文件（用于 mock）。
- 浮点比较：`pytest.approx(rel=1e-5)` 比能量；`np.allclose(rtol=1e-3)` 比几何。
- 必须测的项：参数边界、错误码触发路径、单位换算。

---

## 7. 文档

- 公开函数：docstring 用 Google 风格（`Args:` / `Returns:` / `Raises:`）。
- MCP 工具：每个 tool 必须有 description、参数描述、示例输入/输出。
- Skill：frontmatter + Markdown 正文。
- 每个 PR 必须更新或显式声明"docs not affected"。

---

## 8. Git / 提交

- 主分支 `main`。
- 工作分支 `feat/<topic>`、`fix/<issue>`、`docs/<topic>`。
- 提交信息：[Conventional Commits](https://www.conventionalcommits.org/)
  - `feat(scope): subject`
  - `fix(scope): subject`
  - `docs(scope): subject`
  - `test(scope): subject`
  - `refactor(scope): subject`
  - `chore: subject`
  - `perf(scope): subject`
- scope 可以是 `mcp/psi4`、`skill/tadf`、`agent/planner`、`tui`、`kb`。
- 中文 subject 可，且推荐（团队中文为主）。
- PR 标题同样用 Conventional Commits 格式。

---

## 9. 依赖管理

- 主依赖在 `pyproject.toml` 的 `[project.dependencies]`。
- 开发依赖在 `[project.optional-dependencies.dev]`。
- 不锁版本（让 conda solver 决定），但写最小兼容版本：`numpy>=1.24`。
- 计算软件（psi4 等）**不写进 dependencies** —— 用户用 conda 单独装。MCP 层做存在性检测。

---

## 10. 代码审查（自审 + 互审）

合并前每个 PR 检查：

- [ ] 没有硬编码路径、API key
- [ ] 没有打印调试信息（`print` / `breakpoint()`）
- [ ] 测试都过
- [ ] ruff check 无报错
- [ ] 文档已更新
- [ ] CHANGELOG 已更新（如有用户可见变更）
- [ ] PITFALLS 中相关坑已检查

---

## 11. 数据保留与隐私

- `runs/` 进 `.gitignore`，不提交。
- 任何分子结构、客户数据、API key 都不提交到仓库。
- `tests/fixtures/` 只放公共示例（H2O、苯环等）。
- LLM prompt 中默认隐去具体几何坐标，使用 hash + 元数据（见 PITFALLS §8.2）。

---

## 12. 中英文混用

- 用户面文本（TUI 输出、报告）：中文。
- 代码标识符、错误码：英文。
- 注释与文档：中文为主，专有术语英文。
- 提交信息：中文。

---

*文档版本：v1.0 (2026-04)。*
