"""chem.const — 物理常数与单位换算 MCP server。

第一个完整示例 MCP，作为其他 server 的参考模板。
详见 docs/MCP_GUIDE.md。
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from chemaster.kb.formulas import constants as C
from chemaster.kb.formulas import units as U

mcp = FastMCP("chem.const")


@mcp.tool()
def get_constant(name: str) -> dict[str, Any]:
    """获取物理常数。

    Args:
        name: 常数名（大小写不敏感，支持别名）。
              常见：planck/h, hbar, kb/boltzmann, c/speed_of_light,
              e/elementary_charge, NA/avogadro, R/gas_constant,
              hartree, bohr, eV_to_J, hartree_to_kcal_per_mol, ...

    Returns:
        ok=True 时:
          {
            "ok": True,
            "value": float, "unit": str, "source": str,
            "warnings": [], "meta": {"name": str}
          }
        ok=False 时:
          {"ok": False, "error_code": "UNKNOWN_CONSTANT", "suggestion": "..."}

    Examples:
        >>> get_constant("hbar")
        {"ok": True, "value": 1.054571817e-34, "unit": "J·s", ...}

        >>> get_constant("hartree_to_kcal_per_mol")
        {"ok": True, "value": 627.509474..., "unit": "kcal/(mol·Hartree)", ...}
    """
    try:
        c = C.get(name)
    except C.UnknownConstantError as e:
        return {
            "ok": False,
            "error_code": "UNKNOWN_CONSTANT",
            "details": str(e),
            "suggestion": f"Available constants: {C.list_names()[:10]}…  Use list_constants() for full list.",
        }
    return {
        "ok": True,
        "value": c.value,
        "unit": c.unit,
        "source": c.source,
        "warnings": [],
        "meta": {"name": c.name, "aliases": list(c.aliases)},
    }


@mcp.tool()
def list_constants() -> dict[str, Any]:
    """列出所有可查的物理常数名。"""
    return {"ok": True, "names": C.list_names(), "warnings": []}


@mcp.tool()
def convert_unit(value: float, from_unit: str, to_unit: str) -> dict[str, Any]:
    """单位换算。

    Args:
        value: 数值
        from_unit: 源单位字符串，例 "hartree" / "kcal/mol" / "angstrom"
        to_unit: 目标单位字符串

    Returns:
        ok=True: {"ok": True, "value": float, "unit": str, "warnings": []}
        ok=False: {"ok": False, "error_code": "UNIT_MISMATCH", "details": "..."}

    Examples:
        >>> convert_unit(1.0, "hartree", "kcal/mol")
        {"ok": True, "value": 627.509…, "unit": "kcal/mol", ...}
    """
    try:
        result = U.convert(value, from_unit, to_unit)
    except U.UnitMismatchError as e:
        return {
            "ok": False,
            "error_code": "UNIT_MISMATCH",
            "details": str(e),
            "suggestion": "Check that source and target units have the same dimensionality.",
        }
    except Exception as e:  # pint 解析错误
        return {
            "ok": False,
            "error_code": "UNIT_PARSE_ERROR",
            "details": f"{type(e).__name__}: {e}",
            "suggestion": "Use standard unit names (hartree, eV, angstrom, ...).",
        }
    return {"ok": True, "value": result, "unit": to_unit, "warnings": []}


def main() -> None:
    """``chemaster-mcp const`` 入口。"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
