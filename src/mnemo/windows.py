"""Small Windows adapters; no polling, keyboard hooks, or clipboard monitoring."""

import os
from pathlib import Path
import subprocess
import sys

DEFAULT_HOTKEY = "Ctrl+Alt+M"


def set_taskbar_app_id() -> None:
    if os.name == "nt":
        import ctypes
        set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id("Mnemo.Desktop")


def parse_hotkey(text: str) -> tuple[int, int]:
    parts = [part.strip().upper() for part in text.split('+')]
    modifiers = {"CTRL": 2, "ALT": 1, "SHIFT": 4, "WIN": 8, "META": 8}
    if len(parts) < 2 or len(set(parts)) != len(parts):
        raise ValueError("Выберите сочетание с Ctrl, Alt, Shift или Win и буквой, цифрой либо F1–F24")
    flags = 0
    for part in parts[:-1]:
        if part not in modifiers:
            raise ValueError("Неизвестный модификатор горячей клавиши")
        flags |= modifiers[part]
    key = parts[-1]
    if len(key) == 1 and key in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789':
        vk = ord(key)
    elif key.startswith('F') and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError("Используйте латинскую букву, цифру или F1–F24")
    return flags | 0x4000, vk  # MOD_NOREPEAT


class WindowsHotkey:
    def __init__(self):
        self.current = None
        self.registration_id = None
        self._next_id = 0x4D10

    def register(self, text: str):
        flags, vk = parse_hotkey(text)
        if self.current == text and self.registration_id is not None:
            return
        if os.name != 'nt':
            raise OSError("Глобальные горячие клавиши поддерживаются только в Windows")
        import ctypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        new_id = self._next_id
        if not user32.RegisterHotKey(None, new_id, flags, vk):
            raise OSError("Не удалось зарегистрировать горячую клавишу. Возможно, она занята другой программой.")
        self.close()
        self.registration_id, self.current = new_id, text
        self._next_id = 0x4D10 if new_id == 0x4D11 else 0x4D11

    def close(self):
        if self.registration_id is not None and os.name == 'nt':
            import ctypes
            ctypes.windll.user32.UnregisterHotKey(None, self.registration_id)
        self.registration_id = self.current = None


def startup_command() -> str:
    if getattr(sys, 'frozen', False):
        args = [sys.executable, '--autostart']
    else:
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        executable = str(pythonw) if pythonw.exists() else sys.executable
        args = [executable, str(Path(__file__).with_name('launcher.py').resolve()), '--autostart']
    # Keep explicitly selected data directories when starting outside the project folder.
    from mnemo.paths import data_dir
    args += ['--data-dir', str(data_dir().resolve())]
    return subprocess.list2cmdline(args)


class WindowsAutostart:
    KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
    NAME = 'Mnemo'

    def enabled(self) -> bool:
        if os.name != 'nt':
            return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY) as key:
                value, _ = winreg.QueryValueEx(key, self.NAME)
                return value == startup_command()
        except FileNotFoundError:
            return False

    def set_enabled(self, enabled: bool):
        if os.name != 'nt':
            raise OSError("Автозапуск поддерживается только в Windows")
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, self.NAME, 0, winreg.REG_SZ, startup_command())
            else:
                try:
                    winreg.DeleteValue(key, self.NAME)
                except FileNotFoundError:
                    pass
