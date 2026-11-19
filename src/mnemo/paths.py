"""Пути к ресурсам: одинаково работают из исходников и из собранной папки (NFR-9).

В сборке PyInstaller ресурсы кладутся в `mnemo/resources` внутри папки приложения
(`--add-data "src\\mnemo\\resources;mnemo\\resources"`).
"""

import sys
from pathlib import Path


def resource_path(*parts: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "mnemo" / "resources" / Path(*parts)
    return Path(__file__).parent / "resources" / Path(*parts)


def data_dir() -> Path:
    """Каталог пользовательских данных: `%APPDATA%\\Mnemo` на Windows (docs/specs/product.md, раздел 3).

    Переменная окружения MNEMO_DATA_DIR переопределяет путь (тесты, отладка).
    """
    import os

    override = os.environ.get("MNEMO_DATA_DIR")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Mnemo"
    return Path.home() / ".local" / "share" / "Mnemo"


def db_path() -> Path:
    return data_dir() / "mnemo.db"
