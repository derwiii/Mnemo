import pytest

pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtCore import QAbstractAnimation, QEvent, QPoint, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtTest import QTest
from mnemo.services import Library
from mnemo.storage import Database
from mnemo.ui.main_window import MainWindow
from mnemo.ui.session_screen import State
from mnemo.ui.theme import active_palette


def test_rail_single_click_selects_and_double_click_preserves_focus(qapp):
    lib = Library(Database(":memory:"))
    lib.create_deck("Первая")
    lib.create_deck("Вторая")
    win = MainWindow(lib)
    win.show()
    qapp.processEvents()
    home = win.decks_screen
    first, second = home.rows()
    left = Qt.MouseButton.LeftButton
    wait = QGuiApplication.styleHints().mouseDoubleClickInterval() + 30
    try:
        assert first.isChecked()
        saved = lib.preferences.get("focused_deck")
        QTest.mouseClick(second, left)
        assert win.current_page is home
        assert second.isChecked() and home.selected_id == second.deck_id
        assert home.open_btn.text() == second.title.text().upper()
        assert lib.preferences.get("focused_deck") == saved
        QTest.qWait(wait)
        assert lib.preferences.get("focused_deck") == second.deck_id

        QTest.mouseClick(first, left)
        assert first.isChecked()
        QTest.mouseDClick(first, left)
        assert win.deck_screen.deck_id == first.deck_id
        assert win.current_page is win.deck_screen
        win.deck_screen.add_btn.click()
        win.close_editor()
        assert win.current_page is win.deck_screen
        win.deck_screen.back_btn.click()
        QTest.qWait(wait)
        assert win.current_page is home
        assert second.isChecked() and home.selected_id == second.deck_id
        assert lib.preferences.get("focused_deck") == second.deck_id

        first.setFocus(Qt.FocusReason.TabFocusReason)
        QTest.keyClick(first, Qt.Key.Key_Space)
        assert first.isChecked() and home.selected_id == first.deck_id
    finally:
        win.close()
        win.deleteLater()
        qapp.sendPostedEvents(win, QEvent.Type.DeferredDelete)
        lib.close()


def test_home_rail_expands_and_scrolls_with_motion_setting(qapp, monkeypatch):
    lib = Library(Database(":memory:"))
    for index in range(10):
        deck = lib.create_deck(f"Колода {index} · длинное название для адаптивной компоновки", "", "en", "ru")
        lib.save_card(deck.id, f"word {index}", ["слово"])
    win = MainWindow(lib)
    win.show()
    home = win.decks_screen
    try:
        win.resize(760, 600)
        qapp.processEvents()
        close = win._chrome.bar.close_btn
        assert win.rect().contains(close.mapTo(win, close.rect().bottomRight()))
        drag = win._chrome.drag_strip
        assert win.childAt(QPoint(win.width() // 2, 0)) is drag
        for widget in (
            home.open_btn, home._meta, home.study_btn, home.repeat_btn, home.more_btn,
            home._big, home._big_caption, home._decks_due, home.study_all_btn,
            home.pool_btn, home._selected_due, home._rail, home.next,
        ):
            assert widget.visibleRegion().boundingRect() == widget.rect()
        assert home._rail.horizontalScrollBar().maximum() > 0
        QTest.mouseClick(home.study_all_btn, Qt.MouseButton.LeftButton)
        assert win.session is not None
        win.session.exitRequested.emit()
        assert win.current_page is home
        QTest.mouseClick(home.open_btn, Qt.MouseButton.LeftButton)
        assert win.current_page is win.deck_screen
        search = win.deck_screen.search
        assert search.width() >= search.fontMetrics().horizontalAdvance(search.placeholderText()) + 24
        win.show_decks()

        win.resize(1000, 720)
        qapp.processEvents()
        rail = home._rail.size()
        hero = home.hero.height()
        fonts = [item.font().pixelSize() for item in (home._big, home.study_all_btn)]

        win.resize(1440, 960)
        qapp.processEvents()
        assert home._rail.width() > rail.width()
        assert home._rail.height() > rail.height()
        assert home.hero.height() == hero
        assert home._big.font().pixelSize() > fonts[0]
        assert home.study_all_btn.font().pixelSize() > fonts[1]

        bar = home._rail.horizontalScrollBar()
        before = bar.value()
        monkeypatch.delenv("MNEMO_REDUCED_MOTION", raising=False)
        home.next.click()
        assert home._rail_scroll.state() == QAbstractAnimation.State.Running
        home._rail_scroll.setCurrentTime(home._rail_scroll.duration() // 2)
        assert before < bar.value() < home._rail_scroll.endValue()
        home._rail_scroll.setCurrentTime(home._rail_scroll.duration())
        assert bar.value() == home._rail_scroll.endValue()
        monkeypatch.setenv("MNEMO_REDUCED_MOTION", "1")
        home.previous.click()
        assert home._rail_scroll.state() == QAbstractAnimation.State.Stopped
        assert bar.value() == before

        win.resize(1920, 1080)
        qapp.processEvents()
        assert home._content.width() == 1380
        assert abs(home._content.mapTo(win, home._content.rect().center()).x() - win.width() // 2) <= 1
        assert home.hero.x() == home._strip_title.x()
        assert home.hero.width() <= 760
    finally:
        win.close()
        win.deleteLater()
        qapp.sendPostedEvents(win, QEvent.Type.DeferredDelete)
        lib.close()


def test_home_selection_and_palette_survive_reopening(qapp, tmp_path):
    database = tmp_path / "profile.db"
    lib = Library(Database(database))
    first = lib.create_deck("Первая")
    second = lib.create_deck("Вторая")
    lib.save_card(second.id, "two", ["два"])
    lib.set_deck_cover(second.id, "route")
    win = MainWindow(lib)
    home = win.decks_screen
    assert active_palette()["accent"] == "#EEA77D"
    tile = next(row for row in home.rows() if row.deck_id == second.id)
    tile.click()
    assert win.current_page is home
    assert home.selected_id == second.id and tile.isChecked()
    assert tile.count.text() == "1 карточка"
    assert home._selected_due.text() == "1 к повторению"
    win._set_theme("teal")
    assert active_palette()["accent"] == "#94D9D0"
    assert home.selected_id == second.id
    home.open_btn.click()
    assert win.deck_screen.deck_id == second.id
    win.close()
    lib.close()

    lib = Library(Database(database))
    win = MainWindow(lib)
    assert active_palette()["accent"] == "#94D9D0"
    assert win.decks_screen.selected_id == second.id
    lib.delete_deck(second.id)
    win.show_decks()
    assert win.decks_screen.selected_id == first.id
    win.close()
    lib.close()


def test_cover_dialog_save_cancel_and_reload(qapp, monkeypatch):
    lib = Library(Database(":memory:"))
    deck = lib.create_deck("Английский", "", "en", "ru")
    win = MainWindow(lib)
    def choose(parent, dialog):
        dialog._choices["book"].click()
        return True
    monkeypatch.setattr("mnemo.ui.main_window.run_dialog", choose)
    win.choose_cover(deck.id)
    assert lib.deck_cover(deck.id) == "book"
    win.show_deck(deck.id)
    assert win.deck_screen.cover.cover_id == "book"
    monkeypatch.setattr("mnemo.ui.main_window.run_dialog", lambda *args: False)
    win.choose_cover(deck.id)
    assert lib.deck_cover(deck.id) == "book"
    win.close(); lib.close()


def test_keyboard_during_entrance_and_completion(qapp):
    lib = Library(Database(":memory:"))
    deck = lib.create_deck("Тест")
    lib.save_card(deck.id, "one", ["один"])
    win = MainWindow(lib)
    win.show(); qapp.processEvents()
    win.start_session(deck.id)
    session = win.session
    assert session.entrance.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    QTest.keyClick(session._input, Qt.Key.Key_Return)
    assert session.state is State.REVEALED
    QTest.keyClick(session, Qt.Key.Key_3)
    assert session.is_finished
    assert len(session.results) == 1
    session.finish_animations()
    assert not session.entrance.isVisible()
    assert session._end_art.complete
    win.show_decks()
    assert win.decks_screen._big_caption.text() == "Сегодня повторять нечего"
    win.close(); lib.close()


def test_home_repeat_ignores_due_and_returns_home(qapp):
    from mnemo.domain.models import AnswerMode, Grade
    lib = Library(Database(":memory:"))
    deck = lib.create_deck("Повторение")
    card = lib.save_card(deck.id, "one", ["один"])
    lib.record_review(card.id, Grade.GOOD, AnswerMode.SELF)
    win = MainWindow(lib)
    home = win.decks_screen
    assert not home.study_btn.isEnabled()
    assert home.repeat_btn.isEnabled()
    home.repeat_btn.click()
    assert win.session.current_card.card_id == card.id
    win.session.exitRequested.emit()
    assert win.current_page is win.decks_screen
    win.close(); lib.close()


def test_deck_settings_refresh_name_and_delete_navigation(qapp, monkeypatch):
    lib = Library(Database(":memory:"))
    deck = lib.create_deck("До")
    win = MainWindow(lib)
    win.show_deck(deck.id)
    def rename(parent, dialog):
        lib.update_deck(deck.id, "После", "")
        return True
    monkeypatch.setattr("mnemo.ui.main_window.run_dialog", rename)
    win.deck_screen.rename_action.trigger()
    assert win.deck_screen._title.text() == "После"
    monkeypatch.setattr("mnemo.ui.main_window.confirm", lambda *a, **k: True)
    win.deck_screen.delete_action.trigger()
    assert win.current_page is win.decks_screen
    assert lib.decks.get(deck.id) is None
    win.close(); lib.close()


def test_window_controls_survive_navigation_and_maximize(qapp):
    lib = Library(Database(":memory:"))
    deck = lib.create_deck("Колода")
    win = MainWindow(lib)
    drag = win._chrome.drag_strip
    try:
        win.show()
        for show in (win.show_decks, lambda: win.show_deck(deck.id), win.show_stats):
            show()
            qapp.processEvents()
            close = win._chrome.bar.close_btn
            center = close.mapTo(win, close.rect().center())
            assert win.childAt(center) is close
            if win.current_page is not win.decks_screen:
                back = win.current_page.back_btn
                assert abs(back.geometry().center().y() - win._chrome.bar.geometry().center().y()) <= 1
            assert win.childAt(QPoint(win.width() // 2, 0)) is drag
            assert win.childAt(QPoint(8, 8)) is win._chrome.edges["top_left"]
            start = win.pos()
            center = QPoint(drag.width() // 2, 0)
            QTest.mousePress(drag, Qt.MouseButton.LeftButton, pos=center)
            QTest.mouseMove(drag, center + QPoint(32, 24))
            QTest.mouseRelease(drag, Qt.MouseButton.LeftButton, pos=center)
            assert win.pos() == start + QPoint(32, 24)
        QTest.mouseDClick(drag, Qt.MouseButton.LeftButton, pos=center)
        qapp.processEvents()
        assert win._stack.property("expanded") is True
        assert not win._chrome.edges["left"].isVisible()
        center = QPoint(drag.width() // 2, 0)
        QTest.mousePress(drag, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseMove(drag, center + QPoint(32, 24))
        QTest.mouseRelease(drag, Qt.MouseButton.LeftButton, pos=center)
        qapp.processEvents()
        assert win._stack.property("expanded") is False
        assert win._chrome.edges["left"].isVisible()
    finally:
        win.close()
        win.deleteLater()
        qapp.sendPostedEvents(win, QEvent.Type.DeferredDelete)
        lib.close()


@pytest.mark.parametrize("maximized", [False, True])
def test_window_minimize_and_restore_with_application_icon(qapp, maximized):
    lib = Library(Database(":memory:"))
    win = MainWindow(lib)
    try:
        win.show()
        qapp.processEvents()
        if maximized:
            win._chrome.bar.maximize_btn.click()
            qapp.processEvents()
        geometry = win.geometry()
        assert win.windowIcon().cacheKey() == qapp.windowIcon().cacheKey()
        assert win.windowIcon().availableSizes()
        native = qapp.platformName() == "windows"
        if native:
            from ctypes import windll

            hwnd = int(win.winId())
            user32 = windll.user32
            caption_and_minimize = 0x00C20000  # WS_CAPTION | WS_MINIMIZEBOX
            assert user32.GetWindowLongW(hwnd, -16) & caption_and_minimize == caption_and_minimize
            assert not user32.GetWindowLongW(hwnd, -20) & 0x00080000  # WS_EX_LAYERED
            assert user32.SendMessageW(hwnd, 0x007F, 1, 0)  # WM_GETICON / ICON_BIG

        QTest.mouseClick(win._chrome.bar.minimize_btn, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert win.isMinimized()
        assert win.windowOpacity() == 1.0
        if native:
            from mnemo.ui.windows_frame import SC_RESTORE, send_system_command

            assert user32.IsIconic(hwnd)
            send_system_command(hwnd, SC_RESTORE)
        elif maximized:
            win.showMaximized()
        else:
            win.showNormal()
        qapp.processEvents()
        assert not win.isMinimized() and win.isMaximized() == maximized
        assert win.geometry() == geometry
    finally:
        win.close()
        win.deleteLater()
        qapp.sendPostedEvents(win, QEvent.Type.DeferredDelete)
        lib.close()


def test_windows_corner_preference_survives_restore(qapp):
    import sys

    if qapp.platformName() != "windows" or sys.getwindowsversion().build < 22000:
        pytest.skip("Windows 11 native corner preference")

    from ctypes import byref, c_int, c_long, c_void_p, sizeof, windll, wintypes
    from mnemo.ui.windows_frame import DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND

    get_attribute = windll.dwmapi.DwmGetWindowAttribute
    get_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, c_void_p, wintypes.DWORD]
    get_attribute.restype = c_long
    lib = Library(Database(":memory:"))
    win = MainWindow(lib)

    def check_corners(expanded):
        qapp.processEvents()
        corners = c_int()
        result = get_attribute(int(win.winId()), DWMWA_WINDOW_CORNER_PREFERENCE, byref(corners), sizeof(corners))
        assert result == 0
        assert corners.value == DWMWCP_ROUND
        assert win._stack.property("expanded") is expanded

    try:
        win.show()
        check_corners(False)
        win.showMaximized()
        check_corners(True)
        win.showNormal()
        check_corners(False)
        win.showMinimized()
        qapp.processEvents()
        win.showNormal()
        check_corners(False)
        win.hide()
        win.show()
        check_corners(False)
    finally:
        win.close()
        win.deleteLater()
        qapp.sendPostedEvents(win, QEvent.Type.DeferredDelete)
        lib.close()
