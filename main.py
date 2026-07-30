"""DB.Whisperer — ask your database questions in English.

    python main.py

Needs a local Ollama running (`ollama serve`) with the model in settings pulled,
and, for Full Assistant mode, a reachable SQL Server. Query Generator mode with a
pasted schema needs neither a server nor a database.
"""

import sys
from pathlib import Path

# Imported before matplotlib's Qt backend so that backend binds to PySide6 rather
# than hunting for whichever Qt binding it finds first.
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from ui import MainWindow
from ui.theme import stylesheet

# Sets the icon Windows shows in the taskbar/Alt-Tab while the app is running.
# The exe's own embedded icon (see db_whisperer.spec's EXE(icon=...)) is what a
# pinned-but-not-running shortcut shows; this is what a *running* window shows,
# and the two are independent -- a frozen exe built before this line existed
# would still show the default icon here regardless of what its file icon is.
ICON_PATH = Path(__file__).resolve().parent / "assets" / "app_icon.ico"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("DB.Whisperer")
    app.setOrganizationName("DB.Whisperer")
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    # Segoe UI is Windows' own system sans-serif; set directly rather than left
    # to the QSS font-family alone, since QFont is what Qt actually falls back
    # from if the name isn't found, and it applies to native bits (menus,
    # dialogs) a stylesheet's font-family rule does not always reach.
    app.setFont(QFont("Segoe UI", 9))
    app.setStyleSheet(stylesheet())

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
