"""Application-wide palette and bundled typography."""

from PyQt6.QtGui import QColor, QFontDatabase, QIcon, QPalette
from PyQt6.QtWidgets import QApplication

from mnemo.paths import resource_path

DEFAULT_THEME = "copper"
THEME_NAMES = {"copper": "Мягкая медь", "blue": "Синий и янтарь", "teal": "Ночной бирюзовый"}

_ROLES = (
    "background", "surface", "text", "text_muted", "accent", "accent_text",
    "art_start", "art_end", "art_bottom",
)
PALETTES = {
    "copper": dict(zip(_ROLES, "#18191B #262426 #F5EEE5 #C2B7AE #EEA77D #231C19 #574F62 #C7693B #1C1A1C".split())),
    "blue": dict(zip(_ROLES, "#10151D #1B232D #F5F2EB #B4BDC8 #ABC9FA #101820 #285A91 #E3AD69 #111821".split())),
    "teal": dict(zip(_ROLES, "#11191C #1E2A2D #F0F3EB #ADC2BF #94D9D0 #102323 #17545C #8AAFC0 #132125".split())),
}


def active_palette():
    app = QApplication.instance()
    return PALETTES[getattr(app, "mnemo_theme", DEFAULT_THEME)]


def build_stylesheet(name: str) -> str:
    p = PALETTES.get(name, PALETTES[DEFAULT_THEME])
    accent = QColor(p["accent"])
    tokens = dict(
        p, text_soft=p["text"], text_faint=p["text_muted"], dialog_bg=p["surface"],
        surface_soft=p["surface"], surface_hover=QColor(p["surface"]).lighter(125).name(),
        surface_active=QColor(p["surface"]).lighter(150).name(),
        accent_hover=accent.lighter(110).name(), accent_pressed=accent.darker(110).name(),
        translation="#F4D9A8", line="rgba(255,255,255,25%)",
        progress_bg="rgba(255,255,255,16%)", ok="#92E8C7", bad="#FF8A9B", warn="#FFC27A",
        grade_again="#FF8A9B", grade_hard="#FFC27A", grade_good="#A9B4FF", grade_easy="#92E8C7",
    )
    sheet = resource_path("theme.qss").read_text(encoding="utf-8")
    for key, value in tokens.items():
        sheet = sheet.replace(f"@{key}@", value)
    return sheet


def setup_app(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(resource_path("mnemo.ico"))))
    if not hasattr(app, "_manrope_font"):
        app._manrope_font = tuple(
            QFontDatabase.addApplicationFont(str(resource_path(f"Manrope-{weight}.ttf")))
            for weight in (400, 500, 600, 700, 800)
        )


def apply_theme(app: QApplication, name: str = DEFAULT_THEME) -> None:
    from mnemo.ui.widgets import TooltipCorners

    if not hasattr(app, "_manrope_font"):
        setup_app(app)
    if not hasattr(app, "_tooltip_corners"):
        app._tooltip_corners = TooltipCorners(app)
        app.installEventFilter(app._tooltip_corners)
    app.mnemo_theme = name if name in PALETTES else DEFAULT_THEME
    p = active_palette()
    palette = QPalette()
    for role, key in (
        ("Window", "background"), ("Base", "surface"), ("AlternateBase", "background"),
        ("Button", "surface"), ("Text", "text"), ("WindowText", "text"), ("ButtonText", "text"),
        ("Highlight", "accent"), ("HighlightedText", "accent_text"),
        ("ToolTipBase", "surface"), ("ToolTipText", "text"), ("PlaceholderText", "text_muted"),
    ):
        palette.setColor(QPalette.ColorRole[role], QColor(p[key]))
    app.setPalette(palette)
    app.setStyleSheet(build_stylesheet(app.mnemo_theme))
    for widget in app.allWidgets():
        widget.update()
