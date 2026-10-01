"""Entry point: ``python -m app``.

Kept separate from the window so the import of PySide6 is the *first* thing
that can fail, with a message that says what to do about it.  A traceback
ending in ``ModuleNotFoundError: No module named 'PySide6'`` is a fine message
for someone who wrote the code and a useless one for someone who downloaded an
executable.
"""

from __future__ import annotations

import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "var" / "items.db"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(
            "PySide6 is not installed.\n"
            "  pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    from .window import MainWindow

    db_path = DEFAULT_DB
    source = None
    for arg in argv:
        if arg.startswith("--db="):
            db_path = Path(arg.split("=", 1)[1])
        elif arg.startswith("--save="):
            source = Path(arg.split("=", 1)[1])
        elif arg in ("-h", "--help"):
            print(__doc__)
            print("usage: python -m app [--db=PATH] [--save=PATH]")
            return 0
        else:
            print(f"unknown argument: {arg}", file=sys.stderr)
            return 2

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Torchlight 2 Item Assistant")

    window = MainWindow(db_path=db_path, source=source)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
