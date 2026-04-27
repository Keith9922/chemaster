# chem.const

物理常数与单位换算 MCP server。

## 工具

| 工具 | 说明 |
|---|---|
| `get_constant(name)` | 查物理常数 |
| `list_constants()` | 列所有常数名 |
| `convert_unit(value, from_unit, to_unit)` | 单位换算 |

## Error codes

- `UNKNOWN_CONSTANT`: 常数名不在表内
- `UNIT_MISMATCH`: 源/目标单位维度不匹配（如 hartree → angstrom）
- `UNIT_PARSE_ERROR`: pint 解析失败（拼写错误等）

## 依赖

- `scipy>=1.11`
- `pint>=0.23`

## 启动

```bash
chemaster-mcp const
```

或 import：

```python
from chemaster.mcp.const.server import mcp
```

## 实现笔记

- 所有常数从 `chemaster.kb.formulas.constants`（包装 scipy.constants）取，避免硬编码。
- 单位换算同时提供 pint 通用版（`convert`）与化学常用快捷函数（`hartree_to_eV` 等），后者更快可读。
