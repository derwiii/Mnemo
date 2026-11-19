"""Covers survive restart and upgrading an existing library never loses cards."""
import pytest

from mnemo.services import Library
from mnemo.storage import Database
from mnemo.storage.schema import MIGRATIONS


def test_upgrade_and_persist_cover(tmp_path, monkeypatch):
    path = tmp_path / "existing.db"
    with monkeypatch.context() as patch:
        patch.setattr("mnemo.storage.db.MIGRATIONS", MIGRATIONS[:3])
        old = Library(Database(path))
        deck = old.create_deck("Слова")
        card = old.save_card(deck.id, "word", ["слово"])
        old.db.conn.execute(
            "INSERT INTO deck_appearance(deck_id, icon, color) VALUES (?, 'travel', 'sand')",
            (deck.id,),
        )
        old.close()
    lib = Library(Database(path))
    assert lib.cards.get(card.id).translations == ["слово"]
    assert lib.deck_cover(deck.id) == "route"
    lib.set_deck_cover(deck.id, "spark")
    lib.close()
    lib = Library(Database(path))
    assert lib.deck_cover(deck.id) == "spark"
    assert lib.cards.get(card.id).translations == ["слово"]
    with pytest.raises(ValueError):
        lib.set_deck_cover(deck.id, "unknown")
    assert lib.deck_cover(deck.id) == "spark"
    lib.delete_deck(deck.id)
    assert lib.db.conn.execute("SELECT COUNT(*) FROM deck_appearance").fetchone()[0] == 0
    lib.close()
