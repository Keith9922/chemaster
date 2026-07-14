"""MCP server 公共骨架 — envelope 构造 / 引擎探测 / XYZ 工具。

此前每个 calc server 各复制一份引擎探测、错误 dict 手拼、XYZ 头剥离，
已漂移出 7 份 `_check_engine`、5 份 XYZ 解析、大面积缺失 `suggestion`
的错误返回。新代码一律用本模块；旧 server 逐步收敛（`_check_engine`
保持各自返回签名、内部改用 :func:`probe_binary`）。

设计约定（docs/MCP_GUIDE.md / CLAUDE.md §5.7）：
- 所有工具返回 ``{"ok": bool, ...}`` envelope；
- **错误必须带 suggestion** —— agent 的 L1 自愈靠它决定下一步，缺失
  suggestion 的错误等于把恢复责任甩回给 LLM 瞎猜。:func:`err` 把
  suggestion 做成必填位置参数，从类型上杜绝再漏。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

__all__ = [
    "err",
    "ok",
    "probe_binary",
    "xyz_atom_lines",
]


# ══════════════════════════════════════════════════════════════════════════════
# Envelope 构造
# ══════════════════════════════════════════════════════════════════════════════


def ok(result: Any, warnings: list | None = None,
       meta: dict | None = None, **extra: Any) -> dict[str, Any]:
    """成功 envelope。``extra`` 允许 server 附加顶层字段（如 data_source）。"""
    return {
        "ok": True,
        "result": result,
        "warnings": warnings or [],
        "meta": meta or {},
        **extra,
    }


def err(error_code: str, details: str, suggestion: str,
        meta: dict | None = None, **extra: Any) -> dict[str, Any]:
    """错误 envelope；``suggestion`` 必填（L1 自愈的输入）。"""
    if not suggestion:
        raise ValueError(
            f"err({error_code!r}): suggestion 不能为空 — agent 的自主恢复"
            "依赖它（CLAUDE.md §5.7）"
        )
    out: dict[str, Any] = {
        "ok": False,
        "error_code": error_code,
        "details": details,
        "suggestion": suggestion,
        **extra,
    }
    if meta is not None:
        out["meta"] = meta
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 引擎二进制探测
# ══════════════════════════════════════════════════════════════════════════════


def probe_binary(
    candidates: tuple[str, ...] | list[str],
    version_args: list[str] | None = None,
    version_regex: str | None = None,
    timeout: float = 10.0,
) -> tuple[str | None, str]:
    """在 PATH 上找候选可执行文件并（可选）取版本。

    Returns:
        (path, version)；找不到时 (None, "")。version 取不到时为
        "unknown"（二进制在但 --version 失败不算引擎缺失）。

    各 server 的 ``_check_engine`` 应收敛为本函数的薄包装（保留各自
    的返回签名与 HOME 环境变量检查），不要再复制 subprocess 流程。
    """
    path = None
    for cand in candidates:
        path = shutil.which(cand)
        if path:
            break
    if not path:
        return None, ""

    if version_args is None:
        return path, "unknown"

    try:
        proc = subprocess.run(
            [path, *version_args],
            capture_output=True, text=True, timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if version_regex:
            m = re.search(version_regex, out)
            return path, (m.group(1) if m else "unknown")
        first = out.strip().splitlines()
        return path, (first[0].strip() if first else "unknown")
    except Exception:
        return path, "unknown"


# ══════════════════════════════════════════════════════════════════════════════
# XYZ 工具
# ══════════════════════════════════════════════════════════════════════════════


def _is_atom_line(s: str) -> bool:
    """一行是否长得像原子坐标：``<元素> <x> <y> <z>`` （末 3 个可转 float）。"""
    parts = s.split()
    if len(parts) < 4:
        return False
    try:
        float(parts[-1])
        float(parts[-2])
        float(parts[-3])
    except ValueError:
        return False
    # 首 token 不能是纯数字（那是原子数/电荷行，不是元素符号）
    return not parts[0].lstrip("+-").isdigit()


def xyz_atom_lines(xyz: str) -> list[str]:
    """从"标准 XYZ / 裸原子行"两种输入中取出原子行。

    兼容三种形态（用**内容**而非纯行数判据区分注释行——真 LLM 常给裸
    原子行，而标准 XYZ 的第 2 行是注释）：
      - ``N\\ncomment\\nEl x y z...``（标准，带注释行）
      - ``N\\nEl x y z...``（无注释行）
      - ``El x y z...``（裸原子行）

    Raises:
        ValueError: 空输入、或带原子数 header 时声明数与实际原子行数不符
        （能抓出"少写一行原子"这类真错误，而不是把注释吞成原子）。
    """
    lines = [ln.strip() for ln in xyz.strip().splitlines() if ln.strip()]
    if not lines:
        raise ValueError("empty XYZ input")

    first = lines[0].split()
    has_header = len(first) == 1 and first[0].isdigit()
    if not has_header:
        # 裸原子行（可能整体就是坐标）。
        atoms = [ln for ln in lines if _is_atom_line(ln)]
        if not atoms:
            raise ValueError("no atom lines found in XYZ")
        return atoms

    n_atoms = int(first[0])
    rest = lines[1:]
    # 内容判据：紧跟 header 的若不是原子行，就是注释行，丢掉。
    if rest and not _is_atom_line(rest[0]):
        rest = rest[1:]
    atoms = [ln for ln in rest if _is_atom_line(ln)]
    if len(atoms) != n_atoms:
        raise ValueError(
            f"XYZ header declares {n_atoms} atoms but {len(atoms)} atom "
            f"lines were found"
        )
    return atoms
