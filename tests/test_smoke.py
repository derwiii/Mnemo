from mnemo import __version__
from mnemo.paths import resource_path


def test_version_is_set():
    assert __version__


def test_theme_resource_exists():
    assert resource_path("theme.qss").is_file()
