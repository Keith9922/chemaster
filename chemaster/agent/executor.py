"""Executor —— 按 ApprovedPlan 顺序调 MCP 工具，写产物到 runs/<task-id>/。

约束：
- 只接受 ApprovedPlan（必须经过 ConfirmationLoop）
- 任务产物全写到 runs/<task-id>/
- MCP 返回 ok=False 时本步记 warning 并终止后续 step
"""

from __future__ import annotations

import importlib
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from chemaster.agent.confirmation import ApprovedPlan

logger = logging.getLogger(__name__)

# 已注册的 MCP server 名称（与 pyproject.toml entry-points 对齐）
# 全名 → _mcp_funcs key 的映射（从 MCP server 字符串到模块注册名）
_SERVER_TO_MODULE: dict[str, str] = {
    "chem.const": "const",
    "chem.io.ase": "io_ase",
    "chem.calc.psi4": "calc_psi4",
    "chem.calc.xtb": "calc_xtb",
    "chem.calc.orca": "calc_orca",
    "chem.calc.bdf": "calc_bdf",
    "chem.parse.cclib": "parse_cclib",
    "chem.analysis.multiwfn": "analysis_multiwfn",
    "chem.viz": "viz",
    "chem.hpc.slurm": "hpc_slurm",
    "chem.kb": "kb",
    "chem.pdf": "pdf",
}

_MCP_SERVER_NAMES = list(_SERVER_TO_MODULE.values())


class Executor:
    """执行 Plan，写产物到 runs/<task-id>/。"""

    def __init__(self, runs_dir: str | Path = "./runs") -> None:
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._mcp_funcs: dict[str, dict[str, Any]] = {}
        self._wire_mcps()

    # ------------------------------------------------------------------
    # 私有工具
    # ------------------------------------------------------------------

    def _wire_mcps(self) -> None:
        """通过 importlib 动态加载所有 MCP server 的 tool 函数。

        找不到的 server 跳过并记录 warning；运行时不存在的 MCP 不影响
        其他 MCP 的调用。

        note: psi4 对 OpenMP 初始化顺序敏感。rdkit 先导入会导致 psi4
        在 SCF 迭代时 segfault。因此在加载任何 MCP 之前先初始化 psi4
        的线程配置（确保 OMP_NUM_THREADS=1 写入环境）。
        """
        # 预先初始化 psi4 全局状态（rdkit 兼容性 hack，PITFALLS §8）
        try:
            import psi4
            import os
            os.environ.setdefault("OMP_NUM_THREADS", "1")
            psi4.set_num_threads(1)
            logger.debug("psi4 全局线程数已预设为 1")
        except Exception as exc:
            logger.warning("psi4 预初始化失败（可能未安装）: %s", exc)

        for server_name in _MCP_SERVER_NAMES:
            full_module = f"chemaster.mcp.{server_name}.server"
            try:
                mod = importlib.import_module(full_module)
            except ImportError as exc:
                logger.warning("MCP server '%s' 无法导入，跳过: %s", server_name, exc)
                continue

            # 收集该 module 中公开的 tool 函数（返回 annotation 为 dict 的 callable）
            # 注意：FastMCP 的 @mcp.tool() 装饰器不设 _mcp_tool 属性，
            # 故改用 inspect 校验返回类型 annotation。
            import inspect
            tool_funcs: dict[str, Any] = {}
            for attr_name in dir(mod):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(mod, attr_name)
                if not callable(attr):
                    continue
                try:
                    sig = inspect.signature(attr)
                    ann = sig.return_annotation
                    if ann is inspect.Parameter.empty:
                        continue
                    # 兼容 'dict' 和 'dict[str, Any]' 两种写法
                    if ann not in (dict, "dict", "Dict[str, Any]"):
                        # 也接受 from __future__ annotations 下的小写 dict
                        if str(ann).replace(" ", "").lower() not in ("dict", "dict[str,any]"):
                            continue
                except (ValueError, TypeError):
                    continue
                tool_funcs[attr_name] = attr

            if tool_funcs:
                self._mcp_funcs[server_name] = tool_funcs
                logger.debug("已加载 MCP server '%s'，工具: %s", server_name, list(tool_funcs.keys()))

    def _resolve_geometry(self, args: dict, state: dict) -> dict:
        """若 args 中缺 geometry_xyz 字段，从 state 自动注入。

        Phase 1 简化规则：
        - 优先用 state['optimized_geometry_xyz']
        - 其次用 state['xyz']
        - 若仍缺，不注入（由 MCP 自己报错）
        """
        if "geometry_xyz" not in args:
            for key in ("optimized_geometry_xyz", "xyz"):
                if key in state and state[key]:
                    args = {**args, "geometry_xyz": state[key]}
                    break
        return args

    def _collect_meta(self) -> dict:
        """收集版本快照，写入 meta.json。"""
        meta: dict[str, Any] = {
            "timestamp": subprocess.run(
                ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
                capture_output=True, text=True,
            ).stdout.strip(),
            "python_version": subprocess.run(
                ["python", "--version"],
                capture_output=True, text=True,
            ).stdout.strip(),
        }

        # Git commit（若有）
        git_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True,
            cwd=self.runs_dir.parent,
        )
        if git_result.returncode == 0:
            meta["git_commit"] = git_result.stdout.strip()

        # 包版本
        try:
            import chemaster
            meta["chemaster_version"] = chemaster.__version__
        except Exception:
            meta["chemaster_version"] = "unknown"

        return meta

    def _write_json_sync(self, path: Path, data: dict) -> None:
        """写 JSON 并 fsync 确保持久化。"""
        path.write_text(
            __import__("json").dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.fsync(path.open())

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def run(self, approved: ApprovedPlan) -> dict:
        """执行已批准的 Plan。

        Returns:
            {
              "ok": bool,
              "task_dir": Path,
              "last_result": dict | None,
              "n_steps_completed": int,
              "warnings": list[str],
            }
        """
        # 0. 校验 confirm_token
        if not approved.confirm_token:
            raise ValueError("confirm_token 为空，拒绝执行。必须经过 ConfirmationLoop 确认。")

        plan = approved.plan
        task_dir = self.runs_dir / plan.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Executor 开始，task_id=%s，steps=%d", plan.task_id, len(plan.steps))

        # 2. 写 meta.json
        meta = self._collect_meta()
        self._write_json_sync(task_dir / "meta.json", meta)

        # 3. 写 plan.json
        self._write_json_sync(task_dir / "plan.json", plan.to_dict())

        # 4. 状态传递 dict（step 输出 → 下步输入）
        state: dict[str, Any] = {}

        # 5. 逐 step 执行
        n_steps_completed = 0
        all_warnings: list[str] = []
        last_result: dict | None = None

        for i, step in enumerate(plan.steps, start=1):
            step_slug = step.name.replace(" ", "_").lower()
            step_dir = task_dir / f"step_{i:02d}_{step_slug}"
            step_dir.mkdir(parents=True, exist_ok=True)
            logger.info("执行 step %02d: %s", i, step.name)

            step_ok = True
            step_warnings: list[str] = []

            for mcp_call in step.mcp_calls:
                server_name = mcp_call.server          # e.g. "chem.const"
                tool_name = mcp_call.tool              # e.g. "get_constant"

                # server 名转模块名：通过映射表
                module_name = _SERVER_TO_MODULE.get(server_name)
                if module_name is None:
                    logger.error("MCP server '%s' 不在映射表中，跳过 step", server_name)
                    step_ok = False
                    break

                if module_name not in self._mcp_funcs:
                    logger.error("MCP server '%s' 未加载，跳过 step", module_name)
                    step_ok = False
                    break

                if tool_name not in self._mcp_funcs[module_name]:
                    logger.error("MCP tool '%s' 在 server '%s' 中不存在", tool_name, server_name)
                    step_ok = False
                    break

                fn = self._mcp_funcs[module_name][tool_name]

                # 注入 geometry_xyz（state passing）
                args = self._resolve_geometry(dict(mcp_call.args), state)

                try:
                    result = fn(**args)
                except Exception as exc:  # MCP 不应抛异常，但防御性 catch
                    result = {
                        "ok": False,
                        "error_code": "EXECUTOR_EXCEPTION",
                        "details": f"{type(exc).__name__}: {exc}",
                        "suggestion": "检查 MCP 函数签名是否匹配",
                    }

                # 写 result.json
                self._write_json_sync(step_dir / "result.json", result)

                # 收集 warnings
                if result.get("warnings"):
                    step_warnings.extend(result["warnings"])

                if not result.get("ok", False):
                    logger.warning(
                        "step %02d mcp_call %s.%s 返回 ok=False，error_code=%s",
                        i, server_name, tool_name, result.get("error_code"),
                    )
                    step_ok = False
                    break

                # 将 MCP 返回的 result 更新到 state
                # 兼容两种返回结构：直接返回 {ok, xyz, ...} 或包装在 result 字段下
                if isinstance(result, dict):
                    inner = result.get("result", result)
                    for key in ("optimized_geometry_xyz", "xyz", "geometry_xyz",
                                "energy", "frequencies"):
                        if key in inner:
                            state[key] = inner[key]

                last_result = result

            # 写 step warnings.json（即使是空 list 也写，保持一致性）
            self._write_json_sync(step_dir / "warnings.json", {"warnings": step_warnings})
            all_warnings.extend(step_warnings)

            if not step_ok:
                logger.warning("step %02d 失败，终止后续 step", i)
                break

            n_steps_completed = i

        logger.info(
            "Executor 完成。n_steps_completed=%d/%d，task_dir=%s",
            n_steps_completed, len(plan.steps), task_dir,
        )
        return {
            "ok": n_steps_completed == len(plan.steps),
            "task_dir": task_dir,
            "last_result": last_result,
            "n_steps_completed": n_steps_completed,
            "warnings": all_warnings,
        }
