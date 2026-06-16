"""Load Inter font into Qt's font database at startup."""
from pathlib import Path
from PyQt5 import QtGui, QtWidgets


FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"

_INTER_FILES = [
    "Inter-Regular.ttf",
    "Inter-Medium.ttf",
    "Inter-SemiBold.ttf",
    "Inter-Bold.ttf",
]


def load_inter() -> str:
    """
    Load all Inter weights into Qt font database.
    Returns 'Inter' if successful, 'Segoe UI' as fallback.
    """
    db = QtGui.QFontDatabase()
    loaded = 0

    for fname in _INTER_FILES:
        path = FONTS_DIR / fname
        if path.exists():
            fid = db.addApplicationFont(str(path))
            if fid != -1:
                loaded += 1

    return "Inter" if loaded > 0 else "Segoe UI"


def apply_font(app: QtWidgets.QApplication) -> str:
    """Load Inter and set it as the application-wide default font."""
    family = load_inter()
    font = QtGui.QFont(family, 13)
    font.setHintingPreference(QtGui.QFont.PreferFullHinting)
    app.setFont(font)
    return family
