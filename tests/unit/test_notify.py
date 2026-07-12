"""Unit tests for ``chemaster.notify`` — cross-platform task-completion alerts.

We can't actually fire system notifications in CI, so every subprocess call
is mocked.  The tests verify:

  1. opt-out via ``CHEMASTER_NO_NOTIFY`` works
  2. platform dispatch picks the right helper for macOS / Linux / WSL / Windows
  3. graceful no-op when the platform tool is missing
  4. ``notify_task_done`` composes a sensible title/body for each status
  5. all exception paths are swallowed (notification never crashes the agent)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from chemaster import notify as nf

# ──────────────────────────────────────────────────────────────────────────────
# is_enabled / opt-out via env var
# ──────────────────────────────────────────────────────────────────────────────

class TestIsEnabled:
    def test_default_enabled(self, monkeypatch):
        monkeypatch.delenv("CHEMASTER_NO_NOTIFY", raising=False)
        assert nf.is_enabled() is True

    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on", "On"])
    def test_truthy_env_disables(self, monkeypatch, val):
        monkeypatch.setenv("CHEMASTER_NO_NOTIFY", val)
        assert nf.is_enabled() is False

    @pytest.mark.parametrize("val", ["", "0", "false", "no", "off", "anything-else"])
    def test_falsy_env_keeps_enabled(self, monkeypatch, val):
        monkeypatch.setenv("CHEMASTER_NO_NOTIFY", val)
        assert nf.is_enabled() is True


# ──────────────────────────────────────────────────────────────────────────────
# Platform dispatch
# ──────────────────────────────────────────────────────────────────────────────

class TestPlatformDispatch:
    def test_macos_dispatches_to_osascript(self, monkeypatch):
        monkeypatch.delenv("CHEMASTER_NO_NOTIFY", raising=False)
        monkeypatch.setattr(nf.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(nf, "_is_wsl", lambda: False)

        with patch.object(nf, "_notify_macos", return_value=True) as m:
            ok = nf.notify("title", "body")
        assert ok is True
        m.assert_called_once_with("title", "body", False)

    def test_linux_dispatches_to_notify_send(self, monkeypatch):
        monkeypatch.delenv("CHEMASTER_NO_NOTIFY", raising=False)
        monkeypatch.setattr(nf.platform, "system", lambda: "Linux")
        monkeypatch.setattr(nf, "_is_wsl", lambda: False)

        with patch.object(nf, "_notify_linux", return_value=True) as m:
            ok = nf.notify("title", "body")
        assert ok is True
        m.assert_called_once()

    def test_wsl_overrides_linux_dispatch(self, monkeypatch):
        """Inside WSL2 we must call the powershell.exe path, not notify-send."""
        monkeypatch.delenv("CHEMASTER_NO_NOTIFY", raising=False)
        monkeypatch.setattr(nf.platform, "system", lambda: "Linux")
        monkeypatch.setattr(nf, "_is_wsl", lambda: True)

        with patch.object(nf, "_notify_wsl", return_value=True) as wsl, \
             patch.object(nf, "_notify_linux", return_value=True) as lx:
            ok = nf.notify("title", "body")
        assert ok is True
        wsl.assert_called_once()
        lx.assert_not_called()

    def test_windows_dispatches_to_powershell(self, monkeypatch):
        monkeypatch.delenv("CHEMASTER_NO_NOTIFY", raising=False)
        monkeypatch.setattr(nf.platform, "system", lambda: "Windows")
        monkeypatch.setattr(nf, "_is_wsl", lambda: False)

        with patch.object(nf, "_notify_windows", return_value=True) as m:
            ok = nf.notify("title", "body")
        assert ok is True
        m.assert_called_once()

    def test_unknown_platform_is_noop(self, monkeypatch):
        monkeypatch.delenv("CHEMASTER_NO_NOTIFY", raising=False)
        monkeypatch.setattr(nf.platform, "system", lambda: "Plan9")
        monkeypatch.setattr(nf, "_is_wsl", lambda: False)
        assert nf.notify("title", "body") is False


# ──────────────────────────────────────────────────────────────────────────────
# Per-platform helpers — verify they degrade gracefully when the CLI is missing
# ──────────────────────────────────────────────────────────────────────────────

class TestPlatformHelpers:
    def test_macos_no_osascript_returns_false(self, monkeypatch):
        monkeypatch.setattr(nf.shutil, "which", lambda _: None)
        assert nf._notify_macos("t", "b", False) is False

    def test_linux_no_notify_send_returns_false(self, monkeypatch):
        monkeypatch.setattr(nf.shutil, "which", lambda _: None)
        assert nf._notify_linux("t", "b", False) is False

    def test_macos_swallows_subprocess_error(self, monkeypatch):
        monkeypatch.setattr(nf.shutil, "which", lambda _: "/usr/bin/osascript")
        def boom(*_a, **_kw):
            raise OSError("subprocess broken")
        monkeypatch.setattr(nf.subprocess, "run", boom)
        # Helper must return False, not raise.
        assert nf._notify_macos("t", "b", False) is False

    def test_macos_special_chars_get_escaped(self, monkeypatch):
        monkeypatch.setattr(nf.shutil, "which", lambda _: "/usr/bin/osascript")
        captured = {}
        def fake_run(args, **kw):
            captured["args"] = args
            class R:
                returncode = 0
            return R()
        monkeypatch.setattr(nf.subprocess, "run", fake_run)
        ok = nf._notify_macos('he said "hi"', 'with "quotes"', False)
        assert ok is True
        # Title and body must have escaped quotes so the AppleScript stays well-formed.
        assert '\\"hi\\"' in captured["args"][2]
        assert '\\"quotes\\"' in captured["args"][2]


# ──────────────────────────────────────────────────────────────────────────────
# notify() — disabled / exception swallowing
# ──────────────────────────────────────────────────────────────────────────────

class TestNotifyPublicAPI:
    def test_opt_out_short_circuits(self, monkeypatch):
        monkeypatch.setenv("CHEMASTER_NO_NOTIFY", "1")
        # Should never touch the platform layer.
        with patch.object(nf, "_notify_macos") as m, \
             patch.object(nf, "_notify_linux") as lin, \
             patch.object(nf, "_notify_wsl") as w, \
             patch.object(nf, "_notify_windows") as win:
            assert nf.notify("t", "b") is False
        for mock in (m, lin, w, win):
            mock.assert_not_called()

    def test_swallows_inner_exception(self, monkeypatch):
        """A broken platform helper must not crash the caller."""
        monkeypatch.delenv("CHEMASTER_NO_NOTIFY", raising=False)
        monkeypatch.setattr(nf.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(nf, "_is_wsl", lambda: False)
        with patch.object(nf, "_notify_macos", side_effect=RuntimeError("broken")):
            # Must not raise.
            assert nf.notify("t", "b") is False


# ──────────────────────────────────────────────────────────────────────────────
# notify_task_done — composes title/body from trajectory metadata
# ──────────────────────────────────────────────────────────────────────────────

class TestNotifyTaskDone:
    def test_completed_uses_check_icon_and_sound(self, monkeypatch):
        captured = {}
        def fake_notify(title, body, *, sound=False):
            captured.update(title=title, body=body, sound=sound)
            return True
        monkeypatch.setattr(nf, "notify", fake_notify)

        nf.notify_task_done("task-abcd1234", "completed", summary="H2O energy ok")
        assert "✓" in captured["title"]
        assert "completed" in captured["title"]
        assert "task abcd1234" in captured["body"]
        assert "H2O energy ok" in captured["body"]
        assert captured["sound"] is True  # success sound

    def test_failed_uses_cross_icon_no_sound(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(nf, "notify", lambda *a, **kw: captured.setdefault("kw", kw) or True)
        nf.notify_task_done("task-xyz", "failed")
        assert captured["kw"]["sound"] is False

    def test_elapsed_formatted_seconds_under_minute(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(nf, "notify", lambda title, body, **kw: captured.setdefault("body", body) or True)
        nf.notify_task_done("task-1", "completed", elapsed_s=12.5)
        assert "12.5s" in captured["body"]

    def test_elapsed_formatted_minutes_over_minute(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(nf, "notify", lambda title, body, **kw: captured.setdefault("body", body) or True)
        nf.notify_task_done("task-1", "completed", elapsed_s=240.0)  # 4 min
        assert "4.0min" in captured["body"]

    def test_long_summary_is_truncated(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(nf, "notify", lambda title, body, **kw: captured.setdefault("body", body) or True)
        long = "a" * 200
        nf.notify_task_done("task-1", "completed", summary=long)
        # The body uses " — " separator; the last segment must end with "..."
        last_seg = captured["body"].rsplit(" — ", 1)[-1]
        assert last_seg.endswith("...")
        assert len(last_seg) <= 80

    def test_summary_whitespace_collapsed(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(nf, "notify", lambda title, body, **kw: captured.setdefault("body", body) or True)
        nf.notify_task_done("task-1", "completed", summary="line1\n\n\n  line2  ")
        assert "line1 line2" in captured["body"]
