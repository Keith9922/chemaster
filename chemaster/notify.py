"""Cross-platform desktop notifications for ChemMaster task completion.

Sends a one-line system notification when a long-running task finishes,
which is the natural use case for computational chemistry: a Gaussian
opt+freq job may run for hours; the researcher should not have to sit and
poll the terminal.

Supported platforms:
- macOS  : osascript (built-in, no extra deps)
- Linux  : notify-send (libnotify, usually pre-installed)
- WSL2   : detects WSL and shells out to powershell.exe (Windows Toast-like
           popup via Wscript.Shell, no BurntToast required)
- Windows: powershell (same Wscript.Shell mechanism)

Opt-out: set environment variable ``CHEMASTER_NO_NOTIFY=1``.

The module is intentionally defensive: notification failure must NEVER
propagate up and crash the agent. The platform-specific helpers each
return ``True`` on success and ``False`` otherwise (and never raise);
the public :func:`notify` wraps everything in a final try/except guard.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Literal, Optional

# Status values emitted by chemaster.agent.types.Trajectory
TaskStatus = Literal["completed", "failed", "waiting_for_input"]


# ──────────────────────────────────────────────────────────────────────────────
# Platform detection
# ──────────────────────────────────────────────────────────────────────────────

def _is_wsl() -> bool:
    """True if running inside Windows Subsystem for Linux 2.

    WSL2 is detected by the presence of "microsoft" in /proc/version, which
    is the well-known fingerprint used by most cross-platform tooling. We
    only check this on Linux to avoid an unnecessary file read on macOS.
    """
    if platform.system() != "Linux":
        return False
    try:
        with open("/proc/version", "r", encoding="utf-8") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Per-platform implementations — each returns True on success, False otherwise.
# ──────────────────────────────────────────────────────────────────────────────

def _notify_macos(title: str, body: str, sound: bool) -> bool:
    """Fire a macOS notification via osascript."""
    if not shutil.which("osascript"):
        return False
    # Escape any double quotes that would otherwise break the AppleScript.
    safe_title = title.replace('"', '\\"')
    safe_body = body.replace('"', '\\"')
    script = f'display notification "{safe_body}" with title "{safe_title}"'
    if sound:
        script += ' sound name "Glass"'
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False, capture_output=True, timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _notify_linux(title: str, body: str, sound: bool) -> bool:
    """Fire a Linux notification via notify-send (from libnotify)."""
    if not shutil.which("notify-send"):
        return False
    try:
        subprocess.run(
            ["notify-send", title, body],
            check=False, capture_output=True, timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _powershell_popup_cmd(title: str, body: str) -> str:
    """Build a powershell one-liner that pops a 5-second Wscript.Shell box.

    Wscript.Shell is universally available on Windows and WSL2-mounted
    Windows; it does not require the BurntToast module to be installed.
    The popup auto-dismisses after 5 seconds (the second arg to .Popup).
    """
    safe_title = title.replace("'", "''")
    safe_body = body.replace("'", "''")
    return (
        "$wshell = New-Object -ComObject Wscript.Shell; "
        f"$wshell.Popup('{safe_body}', 5, '{safe_title}', 64) | Out-Null"
    )


def _notify_wsl(title: str, body: str, sound: bool) -> bool:
    """Fire a Windows popup from WSL2 via powershell.exe."""
    pwsh = shutil.which("powershell.exe")
    if not pwsh:
        candidate = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
        if candidate.exists():
            pwsh = str(candidate)
    if not pwsh:
        return False
    try:
        subprocess.run(
            [pwsh, "-NoProfile", "-Command", _powershell_popup_cmd(title, body)],
            check=False, capture_output=True, timeout=10,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _notify_windows(title: str, body: str, sound: bool) -> bool:
    """Native Windows notification via powershell."""
    if not shutil.which("powershell"):
        return False
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", _powershell_popup_cmd(title, body)],
            check=False, capture_output=True, timeout=10,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def is_enabled() -> bool:
    """Notifications enabled unless explicitly opted out via env var.

    Truthy values for opt-out: ``1``, ``true``, ``yes``, ``on`` (case-insensitive).
    Anything else (including empty/unset) keeps notifications enabled.
    """
    val = os.environ.get("CHEMASTER_NO_NOTIFY", "").strip().lower()
    return val not in ("1", "true", "yes", "on")


def notify(title: str, body: str, *, sound: bool = False) -> bool:
    """Send a desktop notification. Returns True if it actually fired.

    Silently no-ops when:
      - ``CHEMASTER_NO_NOTIFY`` env var is set to a truthy value, or
      - the host platform has no available notification mechanism, or
      - the underlying subprocess call errors (any failure is swallowed).

    This function intentionally never raises — a failed notification must
    not crash the calling agent.
    """
    if not is_enabled():
        return False
    try:
        if _is_wsl():
            return _notify_wsl(title, body, sound)
        sys_name = platform.system()
        if sys_name == "Darwin":
            return _notify_macos(title, body, sound)
        if sys_name == "Linux":
            return _notify_linux(title, body, sound)
        if sys_name == "Windows":
            return _notify_windows(title, body, sound)
    except Exception:
        # Defensive: notification failure must never break the agent.
        pass
    return False


def notify_task_done(
    task_id: str,
    status: TaskStatus,
    *,
    summary: str = "",
    elapsed_s: Optional[float] = None,
) -> bool:
    """Send a task-completion notification with sensible defaults.

    Composes a one-line title/body suitable for a system tray pop-up:

      title  = "ChemMaster ✓ completed"   (✗ for failed, ? for waiting)
      body   = "task abcd1234 — 2.5min — Computed H2O single point ..."

    The body is truncated to roughly 80 chars so it fits in a typical
    notification widget without wrapping awkwardly.
    """
    status_icon = {"completed": "✓", "failed": "✗", "waiting_for_input": "?"}
    icon = status_icon.get(status, "•")
    title = f"ChemMaster {icon} {status}"

    # Drop a conventional "task-" prefix before truncating, otherwise we end
    # up showing "task task-abc" which wastes scarce notification real estate.
    short_id = task_id[5:] if task_id.startswith("task-") else task_id
    short_id = short_id[:8]
    body_parts = [f"task {short_id}"]
    if elapsed_s is not None:
        if elapsed_s < 60:
            body_parts.append(f"{elapsed_s:.1f}s")
        else:
            body_parts.append(f"{elapsed_s / 60:.1f}min")
    if summary:
        # Strip leading/trailing whitespace and truncate to keep notification readable.
        summary = " ".join(summary.split())
        summary_short = summary if len(summary) <= 80 else summary[:77] + "..."
        body_parts.append(summary_short)
    body = " — ".join(body_parts)

    return notify(title, body, sound=(status == "completed"))
