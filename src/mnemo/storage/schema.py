"""Схема БД. Каждая миграция — список SQL-команд; номер версии = индекс + 1.

Менять уже выпущенную миграцию нельзя: изменения добавляются новой.
"""

MIGRATIONS: list[list[str]] = [
    # --- версия 1 ---
    [
        """CREATE TABLE decks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            name_key TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            source_language TEXT NOT NULL DEFAULT '',
            target_language TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE cards (
            id TEXT PRIMARY KEY,
            deck_id TEXT NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
            front TEXT NOT NULL,
            front_key TEXT NOT NULL,
            search_text TEXT NOT NULL,
            translations TEXT NOT NULL,
            examples TEXT NOT NULL,
            hints TEXT NOT NULL,
            tags TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        "CREATE INDEX idx_cards_deck ON cards(deck_id)",
        "CREATE INDEX idx_cards_deck_front ON cards(deck_id, front_key)",
        """CREATE TABLE card_states (
            card_id TEXT PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            due_at TEXT NOT NULL,
            interval_days REAL NOT NULL,
            ease REAL NOT NULL,
            lapses INTEGER NOT NULL,
            reps INTEGER NOT NULL
        )""",
        "CREATE INDEX idx_states_due ON card_states(due_at)",
        """CREATE TABLE review_logs (
            id TEXT PRIMARY KEY,
            card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
            reviewed_at TEXT NOT NULL,
            grade TEXT NOT NULL,
            hints_used INTEGER NOT NULL,
            response_time_ms INTEGER NOT NULL,
            answer_mode TEXT NOT NULL,
            typed_answer TEXT,
            overridden INTEGER NOT NULL,
            interval_before REAL NOT NULL,
            interval_after REAL NOT NULL
        )""",
        "CREATE INDEX idx_logs_card ON review_logs(card_id)",
    ],
    [
        """CREATE TABLE deck_appearance (
            deck_id TEXT PRIMARY KEY REFERENCES decks(id) ON DELETE CASCADE,
            icon TEXT NOT NULL DEFAULT 'auto',
            color TEXT NOT NULL DEFAULT 'mint'
        )""",
    ],
    [
        """CREATE TABLE inbox_entries (
            id TEXT PRIMARY KEY,
            front TEXT NOT NULL,
            front_key TEXT NOT NULL UNIQUE,
            translations TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""",
    ],
    [
        "ALTER TABLE deck_appearance ADD COLUMN cover_id TEXT NOT NULL DEFAULT 'cards'",
        """UPDATE deck_appearance SET cover_id = CASE icon
            WHEN 'book' THEN 'book'
            WHEN 'travel' THEN 'route'
            WHEN 'work' THEN 'links'
            ELSE 'cards' END""",
    ],
]
