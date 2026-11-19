import pytest

pytest.importorskip('PyQt6.QtWidgets')
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtTest import QTest, QSignalSpy
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from mnemo.services import Library
from mnemo.storage import Database, StorageError
from mnemo.ui.main_window import MainWindow
from mnemo.ui.inbox_screen import QuickAddDialog
from mnemo.ui.desktop import DesktopController


class FakeHotkey:
    def __init__(self):
        self.current = None
        self.registration_id = None
        self.fail = None

    def register(self, text):
        if text == self.fail:
            raise OSError('hotkey conflict')
        from mnemo.windows import parse_hotkey
        parse_hotkey(text)
        self.current, self.registration_id = text, 1

    def close(self):
        self.current = self.registration_id = None


class FakeAutostart:
    def __init__(self):
        self.value = False
        self.fail = False

    def enabled(self):
        return self.value

    def set_enabled(self, value):
        if self.fail:
            raise OSError('autostart denied')
        self.value = value


@pytest.fixture
def setup(qapp):
    lib = Library(Database(':memory:'))
    win = MainWindow(lib)
    controller = DesktopController(win, lib, hotkey=FakeHotkey(), autostart=FakeAutostart())
    win.show()
    yield win, lib, controller
    if controller.quick:
        controller.quick.reject()
    controller.shutdown()
    win.desktop = None
    win.close()
    lib.close()
    qapp.setQuitOnLastWindowClosed(True)


def test_quick_capture_and_repeated_hotkey_keeps_input(setup, qapp):
    win, lib, desktop = setup
    QApplication.clipboard().setText('look good')
    desktop.open_capture(clipboard=True)
    form = desktop.quick
    assert form.front.toPlainText() == 'look good'
    form.front.setPlainText('look better')
    QApplication.clipboard().setText('other clipboard')
    desktop.open_capture(clipboard=True)
    assert desktop.quick is form
    assert form.front.toPlainText() == 'look better'
    form.translations.setPlainText('выглядеть лучше')
    form._on_primary()
    assert desktop.quick is None
    assert lib.inbox.list()[0].translations == ['выглядеть лучше']
    assert lib.statistics().total_cards == 0
    assert win.decks_screen.inbox_btn.text() == 'Входящие · 1'
    desktop.open_capture()
    assert desktop.quick.front.toPlainText() == ''
    desktop.quick.reject()
    assert lib.inbox.count() == 1


def test_duplicate_opens_existing_without_overwriting(setup):
    win, lib, desktop = setup
    existing, _ = lib.capture_word('Look good', ['хорошо выглядеть'], 'Original context')
    desktop.open_capture()
    form = desktop.quick
    form.front.setPlainText(' look   GOOD ')
    form.translations.setPlainText('do not overwrite')
    form._on_primary()
    assert win.current_page is win.inbox_screen
    assert win.inbox_screen.entry_id == existing.id
    assert win.inbox_screen.translations.toPlainText() == 'хорошо выглядеть'
    assert win.inbox_screen.context.toPlainText() == 'Original context'
    assert lib.inbox.count() == 1


def test_quick_form_validation_and_write_failure(setup, monkeypatch):
    win, lib, desktop = setup
    desktop.open_capture()
    form = desktop.quick
    for front, translations in [('', ''), ('x'*501, ''), ('word', '\n'.join(['x']*11))]:
        form.front.setPlainText(front)
        form.translations.setPlainText(translations)
        form._on_primary()
        assert form.error.text()
        assert lib.inbox.count() == 0
        assert form.isVisible()
    def fail(*args):
        raise StorageError('write failed')
    monkeypatch.setattr(lib, 'capture_word', fail)
    form.front.setPlainText('word')
    form.translations.clear()
    form._on_primary()
    assert form.error.text() == 'write failed'
    assert form.front.toPlainText() == 'word'
    assert form.isVisible()


def test_inbox_explicit_promotion_and_no_translations(setup):
    win, lib, desktop = setup
    entry, _ = lib.capture_word('word')
    deck = lib.create_deck('English')
    win.show_inbox(entry.id)
    screen = win.inbox_screen
    screen.promote()
    assert screen.error.text()
    assert lib.inbox.get(entry.id)
    screen.translations.setPlainText('слово')
    screen.context.setPlainText('A word.')
    screen.promote()
    assert lib.inbox.count() == 0
    card, = lib.cards.list_by_deck(deck.id)
    assert card.translations == ['слово'] and card.examples[0].text == 'A word.'


def test_tray_close_keeps_session_and_fallback_closes(setup, monkeypatch):
    win, lib, desktop = setup
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    desktop.start(hidden=False)
    deck = lib.create_deck('English')
    lib.save_card(deck.id, 'word', ['слово'])
    win.start_session(deck.id)
    session = win.session
    win.close()
    assert not win.isVisible()
    assert win.session is session and lib.reviews.count() == 0
    desktop.restore()
    assert win.isVisible() and win.session is session
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: False)
    win.close()
    assert QApplication.instance().quitOnLastWindowClosed()


def test_hidden_start_and_no_tray_fallback(setup, monkeypatch):
    win, lib, desktop = setup
    win.hide()
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    desktop.start(hidden=True)
    assert not win.isVisible() and desktop.tray.isVisible()
    desktop.tray.hide()
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: False)
    desktop.start(hidden=True)
    assert win.isVisible()


def test_settings_failures_restore_registration_and_preferences(setup, monkeypatch):
    win, lib, desktop = setup
    desktop.hotkey.register(desktop.hotkey_text)
    desktop.autostart.fail = True
    assert 'denied' in desktop.apply_settings('Ctrl+Alt+N', True)
    assert desktop.hotkey.current == 'Ctrl+Alt+M'
    assert lib.preferences.get('capture_hotkey') == ''
    desktop.autostart.fail = False
    assert desktop.apply_settings('Ctrl+Alt+N', True) is None
    assert desktop.autostart.enabled()
    assert lib.preferences.get('capture_hotkey') == 'Ctrl+Alt+N'
    desktop.hotkey.fail = 'Ctrl+Alt+Q'
    assert 'conflict' in desktop.apply_settings('Ctrl+Alt+Q', False)
    assert desktop.hotkey.current == 'Ctrl+Alt+N'
    assert desktop.autostart.enabled()
    original_set = lib.preferences.set
    def fail(*args):
        raise StorageError('preference write failed')
    monkeypatch.setattr(lib.preferences, 'set', fail)
    assert 'write failed' in desktop.apply_settings('Ctrl+Alt+P', False)
    assert desktop.hotkey.current == 'Ctrl+Alt+N'
    assert desktop.autostart.enabled()
    monkeypatch.setattr(lib.preferences, 'set', original_set)
    assert desktop.apply_settings('Ctrl+Alt+N', False) is None
    assert not desktop.autostart.enabled()


def test_single_click_only_opens_capture_double_click_only_restores_main(setup):
    win, lib, desktop = setup
    desktop._click_timer.setInterval(20)
    win.hide()
    desktop._activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert desktop.quick is None
    timer = QSignalSpy(desktop._click_timer.timeout)
    assert len(timer) or timer.wait(1000)
    assert desktop.quick is not None and desktop.quick.isVisible()
    assert not win.isVisible()
    desktop.quick.reject()
    win.hide()
    desktop._activated(QSystemTrayIcon.ActivationReason.Trigger)
    desktop._activated(QSystemTrayIcon.ActivationReason.DoubleClick)
    desktop._activated(QSystemTrayIcon.ActivationReason.Trigger)  # Windows release signal.
    QTest.qWait(100)
    assert win.isVisible()
    assert desktop.quick is None


def test_capture_position_on_negative_monitor_and_draft_navigation(setup, monkeypatch, qapp):
    win, lib, desktop = setup
    class Screen:
        def availableGeometry(self):
            return QRect(-1920, 0, 1920, 1040)
    screen = Screen()
    monkeypatch.setattr(QApplication, 'screens', lambda: [screen])
    desktop.open_capture(screen=screen)
    form = desktop.quick
    qapp.processEvents()
    area = screen.availableGeometry()
    assert form.geometry().right() == area.right() - 16
    assert form.geometry().bottom() == area.bottom() - 16
    assert area.contains(form.geometry())
    form.front.setPlainText('draft')
    form.main_btn.click()
    assert desktop.quick is form and form.front.toPlainText() == 'draft'
    form.inbox_btn.click()
    assert win.current_page is win.inbox_screen
    assert desktop.quick is form and form.front.toPlainText() == 'draft'
    assert lib.inbox.count() == 0
    desktop.open_capture(clipboard=True, screen=screen)
    assert desktop.quick is form and form.front.toPlainText() == 'draft'


def test_settings_access_is_inside_inbox(setup, monkeypatch):
    win, lib, desktop = setup
    assert not hasattr(win.decks_screen, 'settings_btn')
    seen = []
    monkeypatch.setattr(desktop, 'show_settings', lambda: seen.append(True))
    win.show_inbox()
    win.inbox_screen.settings_btn.click()
    assert seen == [True]


def test_capture_is_independent_during_main_minimize_hide_and_escape(setup, monkeypatch, qapp):
    win, lib, desktop = setup
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    desktop.start()
    desktop.open_capture()
    form = desktop.quick
    form.front.setPlainText('keep this draft')
    assert form.parentWidget() is None
    assert form.windowType() == Qt.WindowType.Tool
    assert not form.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    win.showMinimized()
    qapp.processEvents()
    assert form.isVisible() and not form.isMinimized()
    assert form.front.toPlainText() == 'keep this draft'
    win.showNormal()
    win.close()  # Main window hides in the tray, independent of the capture.
    qapp.processEvents()
    assert not win.isVisible() and form.isVisible()
    desktop.restore()
    QTest.keyClick(form.front, Qt.Key.Key_Escape)
    assert desktop.quick is None
    assert win.isVisible()
    assert lib.inbox.count() == 0


def test_repeated_capture_restores_minimized_draft(setup, qapp):
    win, lib, desktop = setup
    desktop.open_capture()
    form = desktop.quick
    form.front.setPlainText('minimized draft')
    form.showMinimized()
    qapp.processEvents()
    desktop.open_capture()
    assert desktop.quick is form
    assert not form.isMinimized()
    assert form.front.toPlainText() == 'minimized draft'


def test_full_exit_closes_both_windows_and_cancels_pending_capture(setup, monkeypatch):
    win, lib, desktop = setup
    desktop.open_capture()
    desktop.quick.front.setPlainText('unsaved')
    desktop._click_timer.start()
    exits = []
    monkeypatch.setattr(QApplication, 'quit', lambda *args: exits.append(True))
    desktop.quit()
    assert desktop.quick is None
    assert not win.isVisible()
    assert not desktop._click_timer.isActive()
    assert lib.inbox.count() == 0
    assert exits == [True]
