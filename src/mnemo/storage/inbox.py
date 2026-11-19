"""SQLite repositories for captures and persistent application preferences."""

import json
from dataclasses import replace

from mnemo.domain.inbox import InboxEntry
from mnemo.domain.models import utcnow
from mnemo.domain.validation import front_key, ValidationError
from mnemo.storage.db import Database, NotFoundError
from mnemo.storage.repositories import _dt, _parse_dt


class InboxRepository:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _entry(row):
        if row is None:
            return None
        return InboxEntry(row['front'], json.loads(row['translations']), row['context'],
                          row['id'], _parse_dt(row['created_at']), _parse_dt(row['updated_at']))

    def get(self, entry_id: str) -> InboxEntry | None:
        return self._entry(self.db.conn.execute(
            'SELECT * FROM inbox_entries WHERE id=?', (entry_id,)).fetchone())

    def find(self, front: str) -> InboxEntry | None:
        return self._entry(self.db.conn.execute(
            'SELECT * FROM inbox_entries WHERE front_key=?', (front_key(front),)).fetchone())

    def list(self) -> list[InboxEntry]:
        return [self._entry(row) for row in self.db.conn.execute(
            'SELECT * FROM inbox_entries ORDER BY created_at DESC, id')]

    def count(self) -> int:
        return self.db.conn.execute('SELECT COUNT(*) FROM inbox_entries').fetchone()[0]

    def capture(self, entry: InboxEntry) -> tuple[InboxEntry, bool]:
        with self.db.transaction() as conn:
            existing = self.find(entry.front)
            if existing is not None:
                return existing, False
            conn.execute('INSERT INTO inbox_entries VALUES (?,?,?,?,?,?,?)',
                         (entry.id, entry.front, front_key(entry.front),
                          json.dumps(entry.translations, ensure_ascii=False), entry.context,
                          _dt(entry.created_at), _dt(entry.updated_at)))
        return entry, True

    def update(self, entry: InboxEntry) -> InboxEntry:
        entry = replace(entry, updated_at=utcnow())
        with self.db.transaction() as conn:
            other = self.find(entry.front)
            if other is not None and other.id != entry.id:
                raise ValidationError(["Такое слово уже есть во входящих"])
            result = conn.execute(
                'UPDATE inbox_entries SET front=?, front_key=?, translations=?, context=?, updated_at=? WHERE id=?',
                (entry.front, front_key(entry.front), json.dumps(entry.translations, ensure_ascii=False),
                 entry.context, _dt(entry.updated_at), entry.id))
            if result.rowcount != 1:
                raise NotFoundError("Заготовка больше не существует")
        return entry

    def delete(self, entry_id: str) -> None:
        with self.db.transaction() as conn:
            if conn.execute('DELETE FROM inbox_entries WHERE id=?', (entry_id,)).rowcount != 1:
                raise NotFoundError("Заготовка больше не существует")


class Preferences:
    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str, default: str = "") -> str:
        row = self.db.conn.execute('SELECT value FROM app_settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default

    def set(self, key: str, value: str) -> None:
        with self.db.transaction() as conn:
            conn.execute('INSERT INTO app_settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                         (key, value))
