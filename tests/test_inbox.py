import pytest

from mnemo.domain.validation import ValidationError
from mnemo.services import Library
from mnemo.storage import Database, NotFoundError, StorageError
from mnemo.storage.schema import MIGRATIONS


@pytest.fixture
def lib():
    library = Library(Database(':memory:'))
    yield library
    library.close()


def test_captures_do_not_enter_any_learning_pool(lib):
    deck = lib.create_deck('English')
    before = lib.statistics()
    entry, created = lib.capture_word('  Come   across ', ['наткнуться'], 'I came across it.')
    assert created
    existing, created = lib.capture_word('come across', ['DO NOT OVERWRITE'], 'new context')
    assert not created and existing.id == entry.id
    assert existing.translations == ['наткнуться'] and existing.context == 'I came across it.'
    assert lib.inbox.count() == 1
    assert lib.statistics() == before
    assert lib.session_queue(deck.id) == []
    assert lib.free_session_queue() == []
    assert lib.db.conn.execute('select count(*) from card_states').fetchone()[0] == 0


@pytest.mark.parametrize('front,translations', [('', []), ('x'*501, []), ('word', ['x']*11)])
def test_invalid_capture(lib, front, translations):
    with pytest.raises(ValidationError):
        lib.capture_word(front, translations)
    assert lib.inbox.count() == 0


def test_edit_and_unique_word(lib):
    entry, _ = lib.capture_word('first')
    lib.capture_word('second')
    with pytest.raises(ValidationError):
        lib.save_inbox(entry.id, ' SECOND ', [], '')
    assert lib.inbox.get(entry.id).front == 'first'
    updated = lib.save_inbox(entry.id, 'First', [' ', ' первый '], ' context ')
    assert updated.translations == ['первый'] and updated.context == 'context'


def test_promote_is_explicit_and_only_once(lib):
    deck = lib.create_deck('English')
    entry, _ = lib.capture_word('word')
    with pytest.raises(ValidationError):
        lib.promote_inbox(entry.id, deck.id, 'word', [])
    assert lib.inbox.count() == 1
    card = lib.promote_inbox(entry.id, deck.id, 'word', ['слово'], 'A word.')
    assert lib.inbox.count() == 0
    assert lib.cards.get(card.id).examples[0].text == 'A word.'
    assert lib.cards.get(card.id).examples[0].translation is None
    assert lib.states.get(card.id).reps == 0
    assert lib.reviews.count() == 0
    with pytest.raises(NotFoundError):
        lib.promote_inbox(entry.id, deck.id, 'word', ['слово'])
    assert len(lib.cards.list_by_deck(deck.id)) == 1


def test_failed_conversion_rolls_back_card_and_state(lib, monkeypatch):
    deck = lib.create_deck('English')
    entry, _ = lib.capture_word('word')
    def fail(entry_id):
        raise StorageError('write failed')
    monkeypatch.setattr(lib.inbox, 'delete', fail)
    with pytest.raises(StorageError):
        lib.promote_inbox(entry.id, deck.id, 'word', ['слово'])
    assert lib.inbox.get(entry.id) is not None
    assert lib.cards.list_by_deck(deck.id) == []
    assert lib.db.conn.execute('select count(*) from card_states').fetchone()[0] == 0


def test_duplicate_card_needs_explicit_confirmation(lib):
    deck = lib.create_deck('English')
    lib.save_card(deck.id, 'word', ['слово'])
    entry, _ = lib.capture_word('WORD')
    with pytest.raises(ValidationError):
        lib.promote_inbox(entry.id, deck.id, 'WORD', ['слово'])
    assert lib.inbox.get(entry.id)
    lib.promote_inbox(entry.id, deck.id, 'WORD', ['слово'], allow_duplicate=True)
    assert len(lib.cards.list_by_deck(deck.id)) == 2


def test_migration_preserves_existing_learning_and_persists_inbox(tmp_path, monkeypatch):
    path = tmp_path / 'migration.db'
    from mnemo.domain.models import Grade, AnswerMode
    # Populate cards and review history using only the previously shipped schema.
    with monkeypatch.context() as patch:
        patch.setattr('mnemo.storage.db.MIGRATIONS', MIGRATIONS[:2])
        old = Database(path)
        from mnemo.storage import DeckRepository, CardRepository
        from mnemo.domain.models import Deck, Card
        deck = DeckRepository(old).add(Deck('Old deck'))
        card = CardRepository(old).add(Card(deck.id, 'old', ['старый']))
        old_library = Library(old)
        old_library.record_review(card.id, Grade.GOOD, AnswerMode.SELF)
        previous_state = old_library.states.get(card.id)
        old_library.close()
    lib = Library(Database(path))
    assert lib.states.get(card.id) == previous_state
    assert lib.reviews.count() == 1
    lib.record_review(card.id, Grade.GOOD, AnswerMode.SELF)
    state = lib.states.get(card.id)
    entry, _ = lib.capture_word('new')
    lib.preferences.set('capture_hotkey', 'Ctrl+Alt+N')
    lib.close()
    lib = Library(Database(path))
    assert lib.db.schema_version == len(MIGRATIONS)
    assert lib.cards.get(card.id).front == 'old'
    assert lib.states.get(card.id) == state
    assert lib.reviews.count() == 2
    assert lib.inbox.get(entry.id).translations == []
    assert lib.preferences.get('capture_hotkey') == 'Ctrl+Alt+N'
    lib.close()
