"""Keep the native Windows frame styles while drawing the whole client area in Qt."""

import ctypes
import os
from ctypes import wintypes


WM_NCCALCSIZE = 0x0083
WM_SYSCOMMAND = 0x0112
SC_MINIMIZE = 0xF020
SC_MAXIMIZE = 0xF030
SC_RESTORE = 0xF120
MONITOR_DEFAULTTONEAREST = 2
GWL_STYLE = -16
WS_POPUP = 0x80000000
WS_OVERLAPPEDWINDOW = 0x00CF0000
SWP_FRAME_CHANGED = 0x0020
SWP_NO_MOVE_SIZE_OR_ACTIVATE = 0x0017
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("monitor", wintypes.RECT),
        ("work", wintypes.RECT),
        ("flags", wintypes.DWORD),
    ]


if os.name == "nt":
    _user32 = ctypes.windll.user32
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    _user32.SetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.SendMessageW.restype = wintypes.LPARAM
    _user32.IsZoomed.argtypes = [wintypes.HWND]
    _user32.IsZoomed.restype = wintypes.BOOL
    _user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
    _user32.MonitorFromRect.restype = wintypes.HMONITOR
    _user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL
    _dwmapi = ctypes.windll.dwmapi
    _dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    _dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long


def enable_system_frame(hwnd: int) -> None:
    style = _user32.GetWindowLongW(hwnd, GWL_STYLE)
    _user32.SetWindowLongW(hwnd, GWL_STYLE, (style & ~WS_POPUP) | WS_OVERLAPPEDWINDOW)
    _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_FRAME_CHANGED | SWP_NO_MOVE_SIZE_OR_ACTIVATE)
    # A custom frame needs an explicit preference. Older Windows versions ignore the attribute.
    corners = ctypes.c_int(DWMWCP_ROUND)
    _dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(corners), ctypes.sizeof(corners))


def send_system_command(hwnd: int, command: int) -> None:
    _user32.SendMessageW(hwnd, WM_SYSCOMMAND, command, 0)


def uses_custom_client_area(message) -> bool:
    msg = wintypes.MSG.from_address(int(message))
    if msg.message != WM_NCCALCSIZE:
        return False
    if _user32.IsZoomed(msg.hWnd):
        # The first RECT is the proposed window bounds in both message forms.
        # At maximize, Windows puts the resize frame outside the work area.
        bounds = wintypes.RECT.from_address(msg.lParam)
        monitor = _user32.MonitorFromRect(ctypes.byref(bounds), MONITOR_DEFAULTTONEAREST)
        info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
        if _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            bounds.left = max(bounds.left, info.work.left)
            bounds.top = max(bounds.top, info.work.top)
            bounds.right = min(bounds.right, info.work.right)
            bounds.bottom = min(bounds.bottom, info.work.bottom)
    return True
