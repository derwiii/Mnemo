"""Диалог импорта и экспорт колоды через интерфейс."""

import json

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QDialog  # noqa: E402

from mnemo.services import Library  # noqa: E402
from mnemo.storage import Database  # noqa: E402
from mnemo.ui import main_window as mw  # noqa: E402
from mnemo.ui.import_dialog import ImportDialog  # noqa: E402
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


def doc(n, bad=()):
    cards = [{"front": f"w{i}", "translations": [] if i in bad else [f"т{i}"]} for i in range(n)]
    return json.dumps(
        {"schema_version": 1, "deck": {"name": "Из файла", "source_language": "en"}, "cards": cards},
        ensure_ascii=False,
    )


def test_preview_shows_counts_and_errors(qapp, library):
    dlg = ImportDialog(None, library)
    dlg.set_source_text(doc(50, bad=(2, 9, 20)))
    assert "47" in dlg.stats.text() and "3" in dlg.stats.text()
    assert dlg.problems.text().count("Запись") == 3
    assert dlg.sample.text().count("\n") == 4  # первые 5 карточек
    assert dlg.new_btn.isChecked() and dlg.new_name.text() == "Из файла"
    assert dlg.primary.isEnabled()


def test_bad_json_shows_error_and_disables_import(qapp, library):
    dlg = ImportDialog(None, library)
    dlg.set_source_text("{не json")
    assert "JSON" in dlg.problems.text()
    assert not dlg.primary.isEnabled()


def test_import_into_new_deck(qapp, library):
    dlg = ImportDialog(None, library)
    dlg.set_source_text(doc(10))
    dlg._on_primary()
    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.report.added == 10
    (s,) = library.deck_summaries()
    assert s.deck.name == "Из файла" and s.card_count == 10 and s.deck.source_language == "en"


def test_existing_deck_duplicates_skip_by_default(qapp, library):
    deck = library.create_deck("Есть")
    dlg = ImportDialog(None, library, deck.id)
    assert dlg.existing_btn.isChecked()
    dlg.set_source_text(doc(5))
    dlg._on_primary()
    assert library.cards.count_by_deck(deck.id) == 5
    again = ImportDialog(None, library, deck.id)
    again.set_source_text(doc(5))
    assert "Дубликатов: 5" in again.stats.text()
    assert not again.primary.isEnabled()  # нечего добавлять
    again.add_btn.setChecked(True)
    assert again.primary.isEnabled()
    again._on_primary()
    assert library.cards.count_by_deck(deck.id) == 10


def test_new_deck_name_conflict_keeps_dialog_open(qapp, library):
    library.create_deck("Из файла")
    dlg = ImportDialog(None, library)
    dlg.new_btn.setChecked(True)  # без выбранной колоды диалог по умолчанию берёт существующую
    dlg.set_source_text(doc(3))
    dlg._on_primary()
    assert dlg.error.text() and dlg.report is None
    assert library.cards.counts_by_deck() == {}


def test_load_file_and_prompt(qapp, library, tmp_path):
    copied = []
    path = tmp_path / "words.json"
    path.write_text(doc(4), encoding="utf-8")
    dlg = ImportDialog(None, library, copy_text=copied.append, pick_file=lambda _p: str(path))
    dlg.file_btn.click()
    assert "words.json" in dlg.source_status.text() and "4" in dlg.stats.text()
    dlg.prompt_btn.click()
    assert copied and "schema_version" in copied[0]
    dlg.load_file(str(tmp_path / "нет.json"))
    assert not dlg.primary.isEnabled()


def test_window_import_flow_opens_deck(win, library, monkeypatch):
    shown = []

    def fake_run(window, dialog):
        dialog.set_source_text(doc(3))
        dialog._on_primary()
        return dialog.result() == QDialog.DialogCode.Accepted

    monkeypatch.setattr(mw, "run_dialog", fake_run)
    monkeypatch.setattr(mw, "info", lambda w, title, text: shown.append(text))
    win.open_import(None)
    assert win.current_page is win.deck_screen
    assert shown and "Добавлено: 3" in shown[0]
    assert library.deck_summaries()[0].card_count == 3


def test_export_writes_file(win, library, tmp_path, monkeypatch):
    deck = library.create_deck("Эксп/орт")
    library.save_card(deck.id, "a", ["б"])
    target = tmp_path / "out.json"
    names = []
    monkeypatch.setattr(win, "_choose_save_path", lambda name: names.append(name) or str(target))
    monkeypatch.setattr(mw, "info", lambda *a: None)
    win.export_deck(deck.id)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["cards"][0]["front"] == "a" and data["deck"]["name"] == "Эксп/орт"
    assert "/" not in names[0]


def test_import_buttons_are_enabled(win, library):
    deck = library.create_deck("Д")
    assert win.decks_screen.import_btn.isEnabled()
    win.show_deck(deck.id)
    assert win.deck_screen.import_action.isEnabled() and win.deck_screen.export_action.isEnabled()
