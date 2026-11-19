"""Verify Windows ownership and taskbar styles, which offscreen Qt cannot exercise."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip('PyQt6.QtWidgets')


@pytest.mark.skipif(os.name != 'nt', reason='Windows window ownership')
def test_native_capture_has_no_owner_and_survives_main_minimize():
    script = r'''
import ctypes
from ctypes import wintypes
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtTest import QTest
from mnemo.storage import Database
from mnemo.services import Library
from mnemo.ui.main_window import MainWindow
from mnemo.ui.desktop import DesktopController

class Hotkey:
    registration_id = None
    def register(self, text): pass
    def close(self): pass

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
lib = Library(Database(':memory:'))
window = MainWindow(lib)
desktop = DesktopController(window, lib, hotkey=Hotkey())
try:
    window.show()
    desktop.open_capture()
    form = desktop.quick
    form.front.setPlainText('native independence test')
    QTest.qWait(100)
    user32 = ctypes.WinDLL('user32')
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    get_style = user32.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.GetWindowLongW
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    user32.IsIconic.argtypes = [wintypes.HWND]
    hwnd = int(form.winId())
    assert not user32.GetWindow(hwnd, 4), 'Capture unexpectedly has a Windows owner'
    style = get_style(hwnd, -20)
    assert style & 0x80, 'Capture must have WS_EX_TOOLWINDOW'
    assert not style & 0x40000, 'Capture must not have WS_EX_APPWINDOW'
    window.showMinimized()
    QTest.qWait(100)
    assert form.isVisible() and not user32.IsIconic(hwnd)
    window.hide()
    QTest.qWait(100)
    assert form.isVisible() and form.front.toPlainText() == 'native independence test'
    desktop.restore()
    QTest.keyClick(form.front, Qt.Key.Key_Escape)
    assert desktop.quick is None and window.isVisible()
    assert lib.inbox.count() == 0
    print('Native ownership, taskbar style, minimize, hide and Escape verified')
finally:
    desktop.shutdown()
    window.desktop = None
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    lib.close()
'''
    env = {**os.environ, 'QT_QPA_PLATFORM': 'windows',
           'PYTHONPATH': str(Path(__file__).resolve().parents[2] / 'src')}
    result = subprocess.run([sys.executable, '-c', script], env=env,
                            capture_output=True, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert b'verified' in result.stdout
