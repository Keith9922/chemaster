"""Plan-Confirm-Execute 三段式的 token 强约束实现。

设计目标
--------
- 用户必须经过 ConfirmationLoop 才能拿到合法 token；伪造的字符串不能过 Executor 校验。
- token 一次性：Executor 校验通过即销毁，重放无效（防止同一 plan 被偷跑两次）。
- 进程内白名单 + HMAC 签名双重校验。HMAC key 进程随机生成，**不持久化**。
- 跨进程不能共享 token（这是有意的：CLI 长进程 = 一台机一次会话；HPC 远端工作单元
  应当走专门的 ApprovedPlan 反序列化路径，而不是复用本机 token）。

不在本模块解决的问题
-----------------
- 多用户/多人协同（Phase 5+）。
- 跨机器复现 / replay：那走 ``plan.json`` 反序列化 + 显式 ``--allow-replay`` flag，
  不复用 token 路径。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
from dataclasses import dataclass


_HMAC_KEY: bytes = secrets.token_bytes(32)
"""进程级 HMAC 密钥；进程退出即丢失。"""

_LOCK = threading.Lock()
_LIVE: dict[str, str] = {}
"""task_id -> token 的活跃白名单。一次性。"""


@dataclass(frozen=True)
class IssuedToken:
    """颁发出的 token，用于构造 ApprovedPlan。"""

    task_id: str
    token: str        # base64 url-safe，调用方仅作 opaque 字符串使用
    signature: str    # hex HMAC-SHA256(task_id || token)


class TokenError(PermissionError):
    """token 校验失败。"""


def _sign(task_id: str, token: str) -> str:
    msg = f"{task_id}|{token}".encode("utf-8")
    return hmac.new(_HMAC_KEY, msg, hashlib.sha256).hexdigest()


def issue(task_id: str) -> IssuedToken:
    """颁发 token。同一 task_id 重复 issue 会覆盖之前的 token（上一个作废）。"""
    if not task_id:
        raise ValueError("task_id 不能为空")
    token = secrets.token_urlsafe(16)
    sig = _sign(task_id, token)
    with _LOCK:
        _LIVE[task_id] = token
    return IssuedToken(task_id=task_id, token=token, signature=sig)


def verify(task_id: str, token: str, signature: str | None = None) -> None:
    """校验 ``(task_id, token)`` 在白名单内且 signature 匹配（若提供）。

    校验通过即从白名单 pop（一次性消费）。失败 raise ``TokenError``。
    """
    if not task_id or not token:
        raise TokenError("task_id 或 token 为空")

    with _LOCK:
        live_token = _LIVE.get(task_id)
        if live_token is None:
            raise TokenError(
                f"task_id={task_id!r} 没有活跃 token——必须先经过 ConfirmationLoop"
            )
        if not hmac.compare_digest(live_token, token):
            raise TokenError("token 不匹配（伪造或重放）")
        # signature 可选；若给出则强校验
        if signature is not None:
            expected = _sign(task_id, token)
            if not hmac.compare_digest(expected, signature):
                raise TokenError("signature HMAC 校验失败")
        # 一次性消费
        _LIVE.pop(task_id, None)


def revoke(task_id: str) -> bool:
    """主动作废一个 task_id 的 token（用户取消、测试清理）。返回是否删到。"""
    with _LOCK:
        return _LIVE.pop(task_id, None) is not None


def _reset_for_tests() -> None:
    """仅供单测使用：清空白名单并重置 HMAC key。"""
    global _HMAC_KEY
    with _LOCK:
        _LIVE.clear()
        _HMAC_KEY = secrets.token_bytes(32)
