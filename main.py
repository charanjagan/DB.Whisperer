"""DB.Whisperer — ask your database questions in English.

    python main.py

Needs a local Ollama running (`ollama serve`) with the model in settings pulled,
and, for Full Assistant mode, a reachable SQL Server. Query Generator mode with a
pasted schema needs neither a server nor a database.
"""

import sys

# Imported before matplotlib's Qt backend so that backend binds to PySide6 rather
# than hunting for whichever Qt binding it finds first.
from PySide6.QtWidgets import QApplication

from ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("DB.Whisperer")
    app.setOrganizationName("DB.Whisperer")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
