"""Win32 window geometry and focus only; no process memory or Unity interfaces."""

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

from .geometry import Rect


@dataclass(frozen=True)
class Window:
    hwnd: int
    title: str
    client: Rect
    focused: bool
    dpi: int


class Windows:
    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Live capture requires Windows; replay works without Win32")
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.api.GetForegroundWindow.restype = wintypes.HWND
        self.api.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.api.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.api.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        for name in ("IsWindow", "IsWindowVisible", "IsIconic", "GetDpiForWindow"):
            getattr(self.api, name).argtypes = [wintypes.HWND]
        self.api.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.api.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self.api.WindowFromPoint.argtypes = [wintypes.POINT]
        self.api.WindowFromPoint.restype = wintypes.HWND
        self.api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.api.GetAncestor.restype = wintypes.HWND
        self.api.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.api.GetAsyncKeyState.restype = ctypes.c_short
        self.api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.integrity: dict[int, int | None] = {}
        self.dpi_aware()

    def dpi_aware(self) -> None:
        if not self.api.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4)):
            raise ctypes.WinError(ctypes.get_last_error())

    def get(self, hwnd: int) -> Window:
        self.dpi_aware()
        if not self.api.IsWindow(hwnd) or self.api.IsIconic(hwnd):
            raise RuntimeError("Target window is closed or minimized")
        length = self.api.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        self.api.GetWindowTextW(hwnd, title, length + 1)
        rect = wintypes.RECT()
        point = wintypes.POINT()
        if not self.api.GetClientRect(hwnd, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.api.ClientToScreen(hwnd, ctypes.byref(point)):
            raise ctypes.WinError(ctypes.get_last_error())
        return Window(
            hwnd,
            title.value,
            Rect(point.x, point.y, rect.right, rect.bottom),
            self.api.GetForegroundWindow() == hwnd,
            self.api.GetDpiForWindow(hwnd),
        )

    def list(self) -> list[Window]:
        found: list[Window] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def callback(hwnd: int, _: int) -> bool:
            if self.api.IsWindowVisible(hwnd) and self.api.GetWindowTextLengthW(hwnd):
                try:
                    found.append(self.get(hwnd))
                except (ValueError, OSError, RuntimeError):
                    pass
            return True

        self.api.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        if not self.api.EnumWindows(callback, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return found

    def unobscured(self, hwnd: int, region: Rect) -> bool:
        # Sample the Game-view grid: an occluded screenshot is unsafe for input.
        for fx in (0.05, 0.5, 0.95):
            for fy in (0.05, 0.5, 0.95):
                point = wintypes.POINT(
                    round(region.x + region.width * fx), round(region.y + region.height * fy)
                )
                hit = self.api.WindowFromPoint(point)
                if self.api.GetAncestor(hit, 2) != hwnd:
                    return False
        return True

    def pressed(self, virtual_key: int) -> bool:
        return bool(self.api.GetAsyncKeyState(virtual_key) & 0x8000)

    def outranks_us(self, hwnd: int) -> bool:
        """True when the window's process has a higher integrity level, e.g. runs elevated.

        Windows (UIPI) then silently drops this process's SendInput events while
        SendInput still reports success, so every key would be ignored.
        """
        pid = wintypes.DWORD()
        self.api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        target, own = self._integrity(pid.value), self._integrity(os.getpid())
        return target is not None and own is not None and target > own

    def _integrity(self, pid: int) -> int | None:
        if pid not in self.integrity:
            self.integrity[pid] = process_integrity(pid)
        return self.integrity[pid]


def process_integrity(pid: int) -> int | None:
    """Mandatory integrity RID of a process (0x2000 medium, 0x3000 high), or None."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    advapi.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    advapi.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    advapi.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    process = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        return None
    token = wintypes.HANDLE()
    try:
        if not advapi.OpenProcessToken(process, 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
            return None
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 25, None, 0, ctypes.byref(size))  # TokenIntegrityLevel
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 25, buffer, size, ctypes.byref(size)):
            return None
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        count = advapi.GetSidSubAuthorityCount(sid)[0]
        return int(advapi.GetSidSubAuthority(sid, count - 1)[0])
    finally:
        if token:
            kernel.CloseHandle(token)
        kernel.CloseHandle(process)
