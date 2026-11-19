"""Константы и лимиты приложения (в одном месте, см. план, принцип 5)."""

APP_NAME = "Mnemo"

WINDOW_WIDTH = 1000
WINDOW_HEIGHT = 720
WINDOW_MIN_WIDTH = 760
WINDOW_MIN_HEIGHT = 600

# Через сколько карточек возвращается карточка с оценкой «Не помню» (FR-S6).
AGAIN_REINSERT_OFFSET = 3

# Слово длиннее этого числа символов показывается мельче (docs/specs/design.md, раздел 7.6).
LONG_FRONT_CHARS = 18

# Размеры экрана сессии (docs/specs/design.md, разделы 2 и 7.5).
SESSION_MARGIN_X = 48
HINT_COLUMN_WIDTH = 220
HINT_COLUMN_GAP = 24
HINT_SHIFT_MS = 200
# Если основной блок после сдвига уже этого значения, подсказки идут под кнопкой.
MIN_MAIN_BLOCK_WIDTH = 520

# Границы данных (docs/specs/cards.md, разделы 1 и 2).
DECK_NAME_MAX = 100
FRONT_MAX = 500
TRANSLATIONS_MAX = 10
# Technical bound on the Cartesian product of alternatives in one text field.
MARKUP_MAX_COMBINATIONS = 256
# Length of the shorter normalized answer, excluding spaces (FR-S14).
ANSWER_ONE_EDIT_LENGTH = 5
ANSWER_TWO_EDITS_LENGTH = 10
EXAMPLES_MAX = 10
HINTS_MAX = 5

# Статус «выучена»: интервал не меньше этого числа дней (docs/specs/repetition.md, раздел 5.5).
LEARNED_INTERVAL_DAYS = 21

# Сколько карточек колоды рисуется за раз (список прокручивается, дальше «Показать ещё»).
CARDS_PAGE_SIZE = 200

# Импорт JSON (docs/specs/import-export.md, FR-I8).
IMPORT_MAX_BYTES = 5 * 1024 * 1024
IMPORT_MAX_CARDS = 5000
IMPORT_PREVIEW_CARDS = 5
IMPORT_SCHEMA_VERSION = 1

# Планировщик (docs/specs/repetition.md, раздел 3). Все параметры в одном месте.
EASE_START = 2.5
EASE_MIN = 1.3
EASE_MAX = 3.0
EASE_AGAIN_DELTA = -0.20
EASE_HARD_DELTA = -0.15
EASE_EASY_DELTA = 0.15
HARD_INTERVAL_FACTOR = 1.2
EASY_INTERVAL_BONUS = 1.3
LAPSE_INTERVAL_FACTOR = 0.5
MIN_REVIEW_INTERVAL_DAYS = 1.0
MAX_INTERVAL_DAYS = 365.0
AGAIN_DELAY_MINUTES = 10
FIRST_HARD_DAYS = 0.5
FIRST_GOOD_DAYS = 1.0
FIRST_EASY_DAYS = 3.0

# Очередь сессии (docs/specs/repetition.md, FR-S2, FR-A3, FR-A4).
# Дневные лимиты отключены по решению пользователя (None = без ограничений).
# Механизм сохранён: значение можно вернуть числом, например 20 и 200.
DAILY_NEW_LIMIT: int | None = None
DAILY_REVIEW_LIMIT: int | None = None
DIFFICULTY_LAPSE_WEIGHT = 1.0
DIFFICULTY_EASE_WEIGHT = 2.0
QUEUE_DIFFICULTY_WEIGHT = 2.0
QUEUE_OVERDUE_CAP_DAYS = 30.0

# Статистика (docs/specs/repetition.md, раздел 4).
STATS_HARDEST_LIMIT = 10
STATS_PERIOD_DAYS = 30
