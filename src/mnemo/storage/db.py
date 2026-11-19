"""Соединение с SQLite, транзакции и миграции схемы (PRAGMA user_version)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from mnemo.storage.schema import MIGRATIONS


class StorageError(Exception):
    """Ошибка хранилища, понятная приложению."""


class DuplicateDeckNameError(StorageError):
    """Колода с таким названием уже есть (без учёта регистра)."""


class NotFoundError(StorageError):
    pass


class Database:
    """Обёртка над соединением. Транзакции вложенные: фиксирует только внешняя."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: транзакциями управляем сами
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._depth = 0
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    @property
    def schema_version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        outer = self._depth == 0
        if outer:
            self.conn.execute("BEGIN")
        self._depth += 1
        try:
            yield self.conn
        except BaseException:
            self._depth -= 1
            if outer:
                self.conn.execute("ROLLBACK")
            raise
        else:
            self._depth -= 1
            if outer:
                self.conn.execute("COMMIT")

    def _migrate(self) -> None:
        current = self.schema_version
        if current > len(MIGRATIONS):
            raise StorageError(
                f"База создана более новой версией Mnemo (схема {current}, поддерживается {len(MIGRATIONS)})"
            )
        for version in range(current, len(MIGRATIONS)):
            self.conn.execute("BEGIN")
            try:
                for statement in MIGRATIONS[version]:
                    self.conn.execute(statement)
                self.conn.execute(f"PRAGMA user_version = {version + 1}")
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
