"""Точка входа: python -m mnemo."""

import sys
import argparse
import os
import sqlite3

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication, QMessageBox

from mnemo.paths import db_path, data_dir
from mnemo.services import Library
from mnemo.settings import APP_NAME
from mnemo.storage import Database, StorageError
from mnemo.windows import set_taskbar_app_id
from mnemo.ui.main_window import MainWindow
from mnemo.ui.theme import setup_app
from mnemo.ui.desktop import DesktopController
from mnemo.ui.single_instance import SingleInstance


def main() -> int:
    parser = argparse.ArgumentParser(description="Mnemo")
    parser.add_argument('--autostart', action='store_true')
    parser.add_argument('--data-dir')
    args = parser.parse_args()
    if args.data_dir:
        os.environ['MNEMO_DATA_DIR'] = args.data_dir
    set_taskbar_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    setup_app(app)
    instance = SingleInstance(data_dir())
    try:
        if not instance.start():
            return 0
    except OSError as exc:
        QMessageBox.warning(None, "Не удалось открыть Mnemo", str(exc))
        return 1
    library = None
    window = None
    desktop = None
    try:
        library = Library(Database(db_path()))
        window = MainWindow(library)
        desktop = DesktopController(window, library)
        instance.activated.connect(desktop.restore)
        desktop.start(hidden=args.autostart)
        return app.exec()
    except (OSError, sqlite3.Error, StorageError) as exc:
        QMessageBox.critical(None, "Не удалось запустить Mnemo", str(exc))
        return 1
    finally:
        if desktop is not None:
            desktop.shutdown()
        if window is not None:
            # Delete the native window before QApplication and its event handlers are torn down.
            window.deleteLater()
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        instance.close()
        if library is not None:
            library.close()


if __name__ == "__main__":
    raise SystemExit(main())
