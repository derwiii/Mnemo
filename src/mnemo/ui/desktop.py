"""Tray lifetime, modeless capture, global hotkey and desktop preferences."""

import ctypes
import os
import sqlite3
import time
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, QTimer, Qt
from PyQt6.QtGui import QKeySequence, QCursor
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QCheckBox, QKeySequenceEdit

from mnemo.storage import StorageError
from mnemo.windows import DEFAULT_HOTKEY, WindowsHotkey, WindowsAutostart
from mnemo.ui.inbox_screen import QuickAddDialog
from mnemo.ui.widgets import Dialog, RoundedMenu, label, run_dialog, info


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, backend, callback):
        super().__init__()
        self.backend, self.callback = backend, callback

    def nativeEventFilter(self, event_type, message):
        if os.name == 'nt' and self.backend.registration_id is not None:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == self.backend.registration_id:
                QTimer.singleShot(0, self.callback)
                return True, 0
        return False, 0


class DesktopSettingsDialog(Dialog):
    def __init__(self, desktop):
        super().__init__(desktop.window, "Настройки входящих", 520)
        self.desktop = desktop
        self.autostart = QCheckBox("Запускать с Windows в трее")
        self.hotkey = QKeySequenceEdit(QKeySequence(desktop.hotkey_text))
        self.hotkey.setMaximumSequenceLength(1)
        self.hotkey.setAccessibleName("Глобальная горячая клавиша")
        self.body.addWidget(self.autostart)
        self.body.addWidget(label("Быстрое добавление из буфера", "Caption"))
        self.body.addWidget(self.hotkey)
        self.body.addWidget(label("Ctrl, Alt, Shift или Win + латинская буква, цифра либо F1–F24.", "DialogText", wrap=True))
        self.error = label(desktop.hotkey_error, "DialogError", wrap=True)
        self.body.addWidget(self.error)
        self.add_buttons("Сохранить")
        try:
            self.autostart.setChecked(desktop.autostart.enabled())
        except OSError as exc:
            self.error.setText(f"Не удалось прочитать настройку автозапуска: {exc}")
            self.primary.setEnabled(False)

    def _on_primary(self):
        text = self.hotkey.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        error = self.desktop.apply_settings(text, self.autostart.isChecked())
        if error:
            self.error.setText(error)
        else:
            self.accept()


class DesktopController:
    def __init__(self, window, library, *, hotkey=None, autostart=None):
        self.window, self.library = window, library
        self.hotkey = hotkey if hotkey is not None else WindowsHotkey()
        self.autostart = autostart if autostart is not None else WindowsAutostart()
        self.hotkey_text = library.preferences.get('capture_hotkey', DEFAULT_HOTKEY)
        self.hotkey_error = ""
        self.quick = None
        self.quitting = False
        self._ignore_trigger_until = 0.0
        self._click_timer = QTimer(window)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(QApplication.doubleClickInterval())
        self._click_timer.timeout.connect(self._open_from_tray)
        self._capture_screen = None
        app = QApplication.instance()
        self._filter = HotkeyFilter(self.hotkey, lambda: self.open_capture(clipboard=True))
        app.installNativeEventFilter(self._filter)
        self.tray = QSystemTrayIcon(window)
        self.tray.setToolTip("Mnemo · быстрое добавление слов")
        self.tray.setIcon(window.windowIcon())
        self.menu = RoundedMenu()
        self.menu.addAction("Добавить слово", self._open_from_tray)
        self.inbox_action = self.menu.addAction("Входящие", self.show_inbox)
        self.menu.aboutToShow.connect(self._refresh_menu)
        self.menu.addAction("Открыть Mnemo", self.restore)
        self.menu.addSeparator()
        self.menu.addAction("Выйти", self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        window.desktop = self
        app.aboutToQuit.connect(self.shutdown)

    def start(self, *, hidden=False):
        available = QSystemTrayIcon.isSystemTrayAvailable()
        QApplication.instance().setQuitOnLastWindowClosed(not available)
        if available:
            self.tray.show()
        if not hidden or not available:
            self.restore()
        try:
            self.hotkey.register(self.hotkey_text)
        except (OSError, ValueError) as exc:
            self.hotkey_error = str(exc)
            QTimer.singleShot(0, self._report_hotkey_error)

    def _report_hotkey_error(self):
        text = self.hotkey_error + " Измените сочетание в настройках; добавление через трей доступно."
        if self.tray.isVisible() and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.showMessage("Горячая клавиша недоступна", text, QSystemTrayIcon.MessageIcon.Warning)
        else:
            info(self.window, "Горячая клавиша недоступна", text)

    @staticmethod
    def raise_window(window):
        if window.isMinimized():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()
        if os.name == 'nt' and QApplication.platformName() != 'offscreen':
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow(int(window.winId()))

    def restore(self):
        self.raise_window(self.window)

    def _activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._click_timer.stop()
            self._ignore_trigger_until = time.monotonic() + QApplication.doubleClickInterval() / 1000
            self.restore()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            if time.monotonic() >= self._ignore_trigger_until:
                self._click_timer.start()

    def _refresh_menu(self):
        self.inbox_action.setText(f"Входящие · {self.library.inbox.count()}")

    def show_inbox(self):
        self.restore()
        self.window.show_inbox()

    def _open_from_tray(self):
        geometry = self.tray.geometry()
        point = geometry.center() if geometry.isValid() else QCursor.pos()
        self.open_capture(screen=QApplication.screenAt(point))

    def _position_capture(self):
        if self.quick is None:
            return
        screens = QApplication.screens()
        screen = self._capture_screen if self._capture_screen in screens else QApplication.primaryScreen()
        area = screen.availableGeometry()
        margin = 16
        self.quick.move(max(area.left(), area.right() - self.quick.width() - margin + 1),
                        max(area.top(), area.bottom() - self.quick.height() - margin + 1))

    def hide_to_tray(self):
        if self.quitting or not self.tray.isVisible() or not QSystemTrayIcon.isSystemTrayAvailable():
            QApplication.instance().setQuitOnLastWindowClosed(True)
            return False
        if self.window.session is not None:
            self.window.session.finish_animations()
        self.window.hide()
        return True

    def open_capture(self, *, clipboard=False, screen=None):
        self._capture_screen = screen or QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if self.quick is not None:
            self.quick.panel.setFixedWidth(min(440, self._capture_screen.availableGeometry().width() - 32))
            self.quick.adjustSize()
            self._position_capture()
            self.raise_window(self.quick)
            return
        text = ""
        if clipboard:
            try:
                mime = QApplication.clipboard().mimeData()
                if mime is not None and mime.hasText():
                    text = mime.text()
            except RuntimeError:
                pass
        self.quick = QuickAddDialog(self.library, text)
        self.quick.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.quick.saved.connect(self._captured)
        self.quick.finished.connect(self._capture_closed)
        self.quick.inboxRequested.connect(self.show_inbox)
        self.quick.mainRequested.connect(self.restore)
        self.quick.resized.connect(self._position_capture)
        self.quick.panel.setFixedWidth(min(440, self._capture_screen.availableGeometry().width() - 32))
        self.quick.adjustSize()
        self.raise_window(self.quick)
        self._position_capture()

    def _capture_closed(self, _result):
        self.quick = None

    def _captured(self, entry_id, created):
        self.window.decks_screen.refresh()
        inbox = self.window.inbox_screen
        if not created:
            self.restore()
            self.window.show_inbox(entry_id)
        elif self.window.current_page is inbox and inbox.values() == inbox._snapshot:
            inbox.refresh(entry_id)

    def show_settings(self):
        run_dialog(self.window, DesktopSettingsDialog(self))

    def apply_settings(self, text, enabled):
        old_text = self.hotkey_text
        old_registered = self.hotkey.registration_id is not None
        try:
            old_enabled = self.autostart.enabled()
        except OSError as exc:
            return str(exc)
        try:
            self.hotkey.register(text)  # Failure preserves the previous registration.
            if enabled != old_enabled:
                self.autostart.set_enabled(enabled)
            with self.library.db.transaction():
                self.library.preferences.set('capture_hotkey', text)
                self.library.preferences.set('autostart', '1' if enabled else '0')
        except (OSError, ValueError, StorageError, sqlite3.Error) as exc:
            rollback_errors = []
            try:
                if old_registered:
                    self.hotkey.register(old_text)
                else:
                    self.hotkey.close()
            except OSError as error:
                rollback_errors.append(str(error))
            try:
                if self.autostart.enabled() != old_enabled:
                    self.autostart.set_enabled(old_enabled)
            except OSError as error:
                rollback_errors.append(str(error))
            return str(exc) + (" Не удалось восстановить прежние настройки: " + '; '.join(rollback_errors) if rollback_errors else "")
        self.hotkey_text, self.hotkey_error = text, ""
        return None

    def quit(self):
        self.quitting = True
        self.shutdown()
        self.window.close()
        QApplication.instance().quit()

    def shutdown(self):
        self._click_timer.stop()
        if self.quick is not None:
            self.quick.reject()
        self.hotkey.close()
        QApplication.instance().removeNativeEventFilter(self._filter)
        self.tray.hide()
