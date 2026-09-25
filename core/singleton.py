"""
core/singleton.py
Cross-process single-instance guard for the SignalPilot bot and dashboard.

A Windows named mutex is the authoritative guard: acquisition is atomic across
processes (no PID-file race window), and the OS releases the mutex automatically
when the owning process exits or crashes, so "already running" can never get
stuck from a stale lock.

A small lock file (data/<app>.pid) is written too, purely as a human-readable
record of the owning PID; it is NOT used to decide whether another instance is
running. On non-Windows platforms (or if the mutex API is unavailable) the guard
falls back to an atomic O_EXCL lock file.
"""

import os
import sys
from pathlib import Path

LOCK_DIR = Path("data")

# name -> open mutex handle for every guard this process currently holds. Kept
# referenced for the whole process lifetime so the mutex is never released early.
_HELD: dict[str, object] = {}


def _win32_try_mutex(name: str):
    """Return True when owned, False when another process owns it, None when the
    mutex API is not available (caller falls back to a lock file)."""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None
    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.restype = wintypes.HANDLE
    create_mutex.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    try:
        handle = create_mutex(None, False, name)
    except Exception:
        return None
    if not handle:
        return None
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass
        return False
    _HELD[name] = handle
    return True


def acquire(app: str) -> bool:
    """Try to become the one and only running instance of `app` ("bot",
    "dashboard"). Returns True when this process is now the sole instance,
    False when another instance is already active."""
    if app in _HELD:
        return True
    LOCK_DIR.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        result = _win32_try_mutex(f"SignalPilotV1.{app}")
        if result is False:
            return False
        if result is True:
            _write_pid(app)
            return True

    try:
        fd = os.open(str(LOCK_DIR / f"{app}.pid"), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    except OSError:
        return False
    else:
        with os.fdopen(fd, "w") as fh:
            fh.write(str(os.getpid()))
        return True


def release(app: str) -> None:
    """Drop the single-instance guard for `app`. Safe to call more than once."""
    handle = _HELD.pop(app, None)
    if handle is not None and sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle(handle)
        except Exception:
            pass
    try:
        (LOCK_DIR / f"{app}.pid").unlink()
    except Exception:
        pass


def _write_pid(app: str) -> None:
    try:
        (LOCK_DIR / f"{app}.pid").write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass