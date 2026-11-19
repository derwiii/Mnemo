import pytest

pytest.importorskip("PyQt6.QtWidgets")

from mnemo.domain.models import AnswerMode, Grade  # noqa: E402
from mnemo.services import Library  # noqa: E402
from mnemo.storage import Database  # noqa: E402
from mnemo.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture
def library():
    lib = Library(Database(":memory:"))
    yield lib
    lib.close()


@pytest.fixture
def win(qapp, library):
    w = MainWindow(library)
    w.resize(1000, 720)
    w.show()
    qapp.processEvents()
    yield w
    w.close()


def test_empty_stats_screen(win):
    assert win.decks_screen.stats_btn.isEnabled()
    win.show_stats()
    s = win.stats_screen
    assert win.current_page is s
    assert s.number_text("total") == "0" and s.number_text("correct") == "—"
    assert s.hardest_row_count == 0 and s._empty.isVisibleTo(s)


def test_stats_numbers_and_edit_link(win, library):
    deck = library.create_deck("A")
    c = library.save_card(deck.id, "hard word", ["т"])
    for _ in range(3):
        library.record_review(c.id, Grade.AGAIN, AnswerMode.SELF)
    library.record_review(c.id, Grade.GOOD, AnswerMode.SELF)
    win.show_stats()
    s = win.stats_screen
    assert s.number_text("total") == "1" and s.number_text("today") == "4"
    assert s.number_text("correct") == "25%"
    assert s.hardest_row_count == 1
    s.editCard.emit(c.id)
    assert win.current_page is win.editor_screen and win.editor_screen.front.text() == "hard word"


def test_back_returns_to_decks(win):
    win.show_stats()
    win.stats_screen.back_btn.click()
    assert win.current_page is win.decks_screen
