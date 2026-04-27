# MCP_GUIDE — 怎么写 MCP server

> 写每个 `chemaster/mcp/<name>/server.py` 之前读这个。

---

## 1. MCP 是什么

[Model Context Protocol](https://modelcontextprotocol.io/) 是 Anthropic 推的协议，让 LLM 能调用外部"工具"。每个 MCP server 暴露一组 typed function，LLM 通过 JSON Schema 知道怎么调。

ChemMaster 用 Python 的 `mcp` SDK 写 server，用 stdio transport（最简单），由 Claude Agent SDK 启动。

---

## 2. 项目里的 MCP 约定

每个 MCP server 是 `chemaster/mcp/<snake_name>/`：

```
chemaster/mcp/calc_psi4/
├── __init__.py
├── server.py            # MCP 入口
├── _tools.py            # 各 tool 的实现
├── _parsing.py          # 输出解析（如果复杂）
├── README.md            # 文档（必须）
├── EVALS.md             # 触发 prompt 测试集（必须）
└── tests/               # 单元 / 集成测试
    ├── test_tools.py
    └── fixtures/
```

启动方式（CLI 注册在 `pyproject.toml`）：

```bash
chemaster-mcp calc_psi4    # 启动 calc_psi4 server
```

---

## 3. 最简 MCP 模板

```python
# chemaster/mcp/const/server.py
"""chem.const — 物理常数与单位换算。"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from chemaster.kb.formulas import constants, units

mcp = FastMCP("chem.const")


@mcp.tool()
def get_constant(name: str) -> dict:
    """获取物理常数。

    Args:
        name: 常数名。支持: planck, hbar, kb, c, e, NA, R, eV_to_J, ...

    Returns:
        {
          "value": float,
          "unit": str,
          "uncertainty": float | None,
          "source": str
        }

    Examples:
        >>> get_constant("hbar")
        {"value": 1.054571817e-34, "unit": "J·s", "source": "CODATA-2018"}
    """
    try:
        c = constants.get(name)
    except KeyError:
        return {"ok": False, "error_code": "UNKNOWN_CONSTANT",
                "suggestion": f"Try one of: {list(constants.list_names())}"}
    return {"ok": True, "value": c.value, "unit": c.unit, "source": c.source}


@mcp.tool()
def convert_unit(value: float, from_unit: str, to_unit: str) -> dict:
    """单位换算。

    Args:
        value: 数值
        from_unit: 源单位，例 "Hartree"
        to_unit: 目标单位，例 "kcal/mol"

    Returns:
        {
          "ok": True,
          "value": float,
          "unit": str,
          "warnings": [...]
        }
    """
    try:
        result = units.convert(value, from_unit, to_unit)
    except units.UnitMismatchError as e:
        return {"ok": False, "error_code": "UNIT_MISMATCH", "details": str(e)}
    return {"ok": True, "value": result, "unit": to_unit, "warnings": []}


if __name__ == "__main__":
    mcp.run(transport="stdio")
```

---

## 4. 设计原则（**违反这些会被打回**）

### 4.1 原子性

每个 tool 做**一件事**。

- ✅ `optimize(geom, method, basis)` → 返回优化后几何与能量
- ❌ `optimize_and_freq_and_report(...)` ← 这是 Skill 的事

### 4.2 类型化输入

```python
@mcp.tool()
def optimize(
    geometry: str,            # xyz 格式字符串
    charge: int = 0,
    multiplicity: int = 1,
    method: str = "B3LYP-D3(BJ)",
    basis: str = "def2-TZVP",
    max_iter: int = 200,
    convergence: str = "tight",   # loose | normal | tight | very_tight
    memory_gb: float = 4.0,
    n_threads: int = 4,
) -> dict:
    ...
```

不要接受 `**kwargs` —— LLM 会瞎填。

### 4.3 三段式返回

```python
{
  "ok": bool,
  "result": {...},          # ok=True 时的核心结果
  "error_code": "...",      # ok=False 时
  "details": {...},
  "suggestion": "...",
  "warnings": [             # 总是有
    {"code": "...", "message": "...", "severity": "info|warn|error"}
  ],
  "meta": {
    "engine": "psi4",
    "engine_version": "1.9.1",
    "wall_time_s": 12.5,
    "n_basis_functions": 84,
    "input_file": "/path/to/runs/.../input.psi4",
    "output_file": "/path/to/runs/.../output.log",
  }
}
```

### 4.4 物理量带 unit

```python
{
  "result": {
    "final_energy": {"value": -76.42, "unit": "Hartree"},
    "zpe":          {"value":   0.021, "unit": "Hartree"},
    "wall_time":    {"value":  12.5,  "unit": "s"},
    "geometry":     {"value": "...xyz...", "unit": "angstrom"}
  }
}
```

### 4.5 不抛异常给 LLM

```python
# ❌ 错误
def optimize(...):
    psi4.optimize(...)          # 失败时抛异常给 LLM

# ✅ 正确
def optimize(...):
    try:
        e = psi4.optimize(...)
    except psi4.SCFConvergenceError as exc:
        return {
            "ok": False,
            "error_code": "SCF_NOT_CONVERGED",
            "details": {"max_iter": ..., "final_residual": ...},
            "suggestion": "Try guess=GWH or basis=def2-SVP first",
        }
```

### 4.6 主动校验已知坑

写每个 tool 前先翻 [`PITFALLS.md`](PITFALLS.md)。例：

- 频率计算入参与 optimize 的 method/basis 不一致 → 拒绝（PITFALLS §2.3）
- 路径含中文 → 拒绝（PITFALLS §2.12）
- memory_gb 超过物理内存 → 警告并下调（§2.14）

### 4.7 输出归档

每次 tool 调用产生的输入文件、原始输出 log，写到 `runs/<task-id>/<step>/`，文件路径回填到 `meta.input_file` / `meta.output_file`。

### 4.8 Mock 模式

测试时用 `--mock-output <fixture-dir>` 启动，跳过真跑软件，从 fixture 读输出。这样单元测试 < 1 秒。

---

## 5. 工具描述写法

LLM 看到的是 docstring。

**好的 docstring**：

```python
@mcp.tool()
def optimize(...) -> dict:
    """对分子做几何优化（找最近的极小点）。

    使用 psi4 的 optking 优化器。默认方法 B3LYP-D3(BJ)/def2-TZVP 是有机
    小分子（< 50 原子）的精度-成本平衡点。

    何时用：
      - 用户要"算 X 的能量"、"优化 X 的结构"、"找 X 的最稳定构象"。

    何时不用：
      - 找过渡态：用 ts_search，不用 optimize。
      - 仅算单点能：用 single_point。

    重要：optimize 收敛 ≠ 是真极小点。必须接 frequency 确认无虚频。
    建议用 opt-freq skill 而不是直接调本 tool。

    Args:
        geometry: 初始几何，xyz 格式字符串。
        charge: 体系电荷，默认 0（中性）。
        multiplicity: 自旋多重度（2S+1）。闭壳偶电子默认 1，开壳奇电子默认 2。
        method: DFT 泛函或 HF/MP2 等方法。建议从 chem.kb.search 拿推荐。
        basis: 基组。
        ...

    Returns:
        ok=True 时:
          {ok, result: {final_energy, optimized_geometry, n_iterations,
                        converged}, warnings, meta}
        ok=False 时:
          {ok=False, error_code, details, suggestion}

        常见 error_code:
          - SCF_NOT_CONVERGED: SCF 未收敛
          - GEOMETRY_NOT_CONVERGED: 几何优化未在 max_iter 内收敛
          - UNSUPPORTED_ELEMENT: 基组不支持某元素
          - INVALID_MULTIPLICITY: 自旋多重度与电子数不匹配

    Examples:
        H2O 优化:
        >>> optimize("3\n\nO 0 0 0.119\nH 0 0.756 -0.477\nH 0 -0.756 -0.477",
        ...          method="B3LYP-D3(BJ)", basis="def2-TZVP")
        {"ok": True, "result": {"final_energy": {...}, ...}, ...}
    """
```

注意：

- 第一句写"做什么"。
- 接段写"何时用 / 不用" —— LLM 路由的关键。
- 重要约束直接写在 docstring（如"必须接 frequency"）。
- 列出常见 error_code。
- 给至少一个 example。

---

## 6. EVALS.md（触发与正确性测试）

每个 MCP 配 `EVALS.md`，列出 5+ 触发 prompt 与期望调用：

```markdown
# chem.calc.psi4 evals

## 应该触发的

| Prompt | 期望 tool | 期望参数 |
|---|---|---|
| 算 H2O 的 B3LYP 能量 | single_point 或 optimize | method=B3LYP* |
| 优化乙醇的几何 | optimize | method=默认 |

## 不应该触发的

| Prompt | 不应触发的 tool | 原因 |
|---|---|---|
| 找苯环的过渡态 | optimize | 应路由到 ts-search skill |
| 用 CCSD(T) 算 | (任意 psi4 tool) | psi4 慢，应用 chem.calc.orca.dlpno_ccsdt |
```

跑 evals：

```bash
chemaster evals run --mcp calc_psi4
```

---

## 7. README.md（每个 MCP 目录的）

模板：

```markdown
# chem.calc.psi4

psi4 量子化学软件包装。提供单点能、几何优化、频率计算等原子操作。

## 工具列表

| 工具 | 说明 |
|---|---|
| single_point | 单点能 |
| optimize | 几何优化 |
| frequency | 频率计算 |

## Error codes

- `SCF_NOT_CONVERGED`: SCF 未收敛
- `GEOMETRY_NOT_CONVERGED`: 几何优化未收敛
- ...

## 依赖

- psi4 ≥ 1.9
- conda install -c conda-forge psi4

## 性能

- H2O / def2-TZVP: ~5 s on 4 cores
- 苯环 / def2-TZVP: ~30 s
- 50 原子 / def2-TZVP: ~10 min

## 已知坑

参见 [PITFALLS.md](../../../docs/PITFALLS.md) §2.3-2.12。
```

---

## 8. 测试

```python
# tests/unit/test_calc_psi4.py
import pytest
from chemaster.mcp.calc_psi4 import server


def test_optimize_h2o_mock(tmp_path):
    """优化 H2O — mock 输出。"""
    result = server.optimize.fn(
        geometry="...xyz...",
        method="B3LYP-D3(BJ)",
        basis="def2-TZVP",
        _mock_output_path="tests/fixtures/psi4_h2o_opt.log",
    )
    assert result["ok"]
    assert result["result"]["final_energy"]["value"] == pytest.approx(-76.42, rel=1e-3)
    assert result["result"]["converged"]


def test_optimize_unsupported_element():
    result = server.optimize.fn(
        geometry="1\n\nUu 0 0 0",      # 假元素
        ...
    )
    assert not result["ok"]
    assert result["error_code"] == "UNSUPPORTED_ELEMENT"
```

集成测试（真跑）：

```python
# tests/integration/test_calc_psi4_real.py
@pytest.mark.integration
def test_h2_optimize_real():
    result = server.optimize.fn(
        geometry="2\n\nH 0 0 0\nH 0 0 0.74",
        method="HF",
        basis="STO-3G",
    )
    assert result["ok"]
    assert result["result"]["final_energy"]["value"] == pytest.approx(-1.117, rel=1e-2)
```

---

## 9. CLI 注册

`pyproject.toml`：

```toml
[project.scripts]
chemaster        = "chemaster.cli:main"
chemaster-mcp    = "chemaster.mcp:dispatcher_main"

[project.entry-points."chemaster.mcps"]
const               = "chemaster.mcp.const.server:mcp"
io_ase              = "chemaster.mcp.io_ase.server:mcp"
calc_psi4           = "chemaster.mcp.calc_psi4.server:mcp"
calc_orca           = "chemaster.mcp.calc_orca.server:mcp"
calc_bdf            = "chemaster.mcp.calc_bdf.server:mcp"
calc_xtb            = "chemaster.mcp.calc_xtb.server:mcp"
parse_cclib         = "chemaster.mcp.parse_cclib.server:mcp"
analysis_multiwfn   = "chemaster.mcp.analysis_multiwfn.server:mcp"
viz                 = "chemaster.mcp.viz.server:mcp"
hpc_slurm           = "chemaster.mcp.hpc_slurm.server:mcp"
kb                  = "chemaster.mcp.kb.server:mcp"
pdf                 = "chemaster.mcp.pdf.server:mcp"
```

---

## 10. Checklist（每个 MCP 完成前过）

- [ ] `server.py` 写完，每个 tool 有完整 docstring
- [ ] 入参 schema 严格（无 `**kwargs`）
- [ ] 返回值带 `ok` / `warnings` / `meta` / 物理量带 `unit`
- [ ] 错误转结构化 error_code
- [ ] 已查 PITFALLS 相关条目
- [ ] `README.md` 写完
- [ ] `EVALS.md` ≥ 5 正例 + 5 反例
- [ ] 单元测试覆盖关键路径
- [ ] 集成测试至少 1 个真跑案例
- [ ] 在 `pyproject.toml` 的 entry-points 注册
- [ ] `chemaster --check-engines` 能检测出该 MCP

---

*文档版本：v1.0 (2026-04)。*
