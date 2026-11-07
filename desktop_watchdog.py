"""Windows UI-thread liveness probe for SkellyMotion.

Run only from a worker thread. A page DOM 'loaded' event is not proof that
WinForms/WebView2 keeps processing Windows messages after initialization.
No OS policy, registry, security exclusions or user files are changed.
"""
from __future__ import annotations

import os


class ConsecutiveFailureDetector:
    """Require several independent failed probes to avoid transient false alarms."""

    def __init__(self, threshold: int = 3):
        if threshold < 1:
            raise ValueError("threshold must be positive")
        self.threshold = threshold
        self.failures = 0
        self.triggered = False

    def observe(self, result: bool | None) -> bool:
        """Return True once when UI thread has repeatedly stopped responding.

        None means the expected window cannot yet be found or reliably probed.
        """
        if result is None or result:
            self.failures = 0
            return False
        self.failures += 1
        if self.failures >= self.threshold and not self.triggered:
            self.triggered = True
            return True
        return False


def windows_ui_responding(title: str, timeout_ms: int = 1000) -> bool | None:
    """Ping the actual WinForms window message pump, not just the web server.

    SendMessageTimeoutW is bounded; if UI thread cannot answer WM_NULL, it is
    unresponsive even if the localhost API and embedded page still exist.
    None means inconclusive; the detector never counts it as a failure.
    """
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
    ]
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM

    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return None
    owner_pid = wintypes.DWORD()
    if not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid)):
        return None
    if owner_pid.value != os.getpid():
        return None

    reply = ctypes.c_size_t()
    # WM_NULL=0; SMTO_BLOCK | SMTO_ABORTIFHUNG=0x3. Never wait forever.
    returned = user32.SendMessageTimeoutW(
        hwnd, 0, 0, 0, 0x0003, max(100, min(int(timeout_ms), 3000)),
        ctypes.byref(reply),
    )
    return bool(returned)
