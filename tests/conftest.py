import os

import pytest

# Тесты интерфейса идут без реального экрана.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    # Qt подключается только здесь, чтобы тесты логики (domain, storage) шли без него.
    qt_widgets = pytest.importorskip("PyQt6.QtWidgets")
    app = qt_widgets.QApplication.instance() or qt_widgets.QApplication([])
    # Как при штатном запуске: Fusion вместо нестабильного native-стиля в offscreen.
    from mnemo.ui.theme import setup_app
    setup_app(app)
    yield app
