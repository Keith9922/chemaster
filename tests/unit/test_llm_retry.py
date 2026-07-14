"""LLM 层瞬时错误重试的单元测试。

此前 llm_client 零重试——一次 429/网络抖动就让整个化学任务失败，与
"错误是常态"（CLAUDE.md §5.7）的自愈哲学自相矛盾，也会污染真 LLM
工程指标（基础设施噪声计入失败）。
"""

from __future__ import annotations

import pytest

from chemaster.agent.llm_client import (
    BaseLLM,
    ContextOverflowError,
    LLMConfig,
    LLMError,
    _is_retryable_llm_error,
)


class _Probe(BaseLLM):
    """暴露 _request_with_retries 的最小实现。"""

    def query(self, dialog):  # pragma: no cover — not used
        raise NotImplementedError


class _StatusError(Exception):
    def __init__(self, status_code, msg="boom"):
        super().__init__(msg)
        self.status_code = status_code


@pytest.fixture
def no_sleep(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("chemaster.agent.llm_client.time.sleep", slept.append)
    return slept


def _probe(max_retries=3):
    return _Probe(LLMConfig(provider="mock", max_retries=max_retries,
                            retry_base_s=1.0))


# ── 判定函数 ─────────────────────────────────────────────────────────────────


def test_retryable_detection_by_status_code():
    assert _is_retryable_llm_error(_StatusError(429))
    assert _is_retryable_llm_error(_StatusError(503))
    assert not _is_retryable_llm_error(_StatusError(401))
    assert not _is_retryable_llm_error(_StatusError(400))


def test_retryable_detection_by_type_and_message():
    class ConnectionFlakyError(Exception):
        pass

    assert _is_retryable_llm_error(ConnectionFlakyError("peer reset"))
    assert _is_retryable_llm_error(Exception("Rate limit exceeded, slow down"))
    assert not _is_retryable_llm_error(ValueError("bad schema"))


# ── 重试行为 ─────────────────────────────────────────────────────────────────


def test_transient_429_retried_then_succeeds(no_sleep):
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise _StatusError(429, "rate limited")
        return "ok"

    assert _probe()._request_with_retries(flaky) == "ok"
    assert attempts["n"] == 3
    assert no_sleep == [1.0, 2.0]  # 指数退避 1s → 2s


def test_retries_exhausted_raises_llm_error(no_sleep):
    def always_503():
        raise _StatusError(503)

    with pytest.raises(LLMError):
        _probe(max_retries=2)._request_with_retries(always_503)
    assert no_sleep == [1.0, 2.0]  # 重试了 2 次后放弃


def test_non_retryable_raises_immediately(no_sleep):
    attempts = {"n": 0}

    def auth_fail():
        attempts["n"] += 1
        raise _StatusError(401, "invalid api key")

    with pytest.raises(LLMError):
        _probe()._request_with_retries(auth_fail)
    assert attempts["n"] == 1
    assert no_sleep == []


def test_context_overflow_never_retried(no_sleep):
    def overflow():
        raise Exception("prompt exceeds the maximum context length")

    with pytest.raises(ContextOverflowError):
        _probe()._request_with_retries(overflow)
    assert no_sleep == []


def test_zero_retries_config(no_sleep):
    def flaky():
        raise _StatusError(429)

    with pytest.raises(LLMError):
        _probe(max_retries=0)._request_with_retries(flaky)
    assert no_sleep == []
