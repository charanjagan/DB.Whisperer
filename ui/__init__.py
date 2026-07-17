"""PySide6 desktop UI for DB.Whisperer.

The pipeline lives in `nl2sql` and knows nothing about Qt; this package is the
window around it. `nl2sql.session.Session` is the seam between the two.
"""

from .main_window import MainWindow

__all__ = ["MainWindow"]
