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

from . import paths
from .version import __version__


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] in ("-V", "--version"):
        print(f"Torchlight 2 Item Assistant {__version__}")
        return 0

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

    # Left unset, each stash gets its own database under var/.  Passing --db
    # pools every stash into one file, which is useful for looking at them
    # together and wrong for actually storing items in: an item taken from the
    # modded stash would be restorable into the vanilla one.
    db_path = None
    source = None
    game = None
    for arg in argv:
        if arg.startswith("--db="):
            db_path = Path(arg.split("=", 1)[1])
        elif arg.startswith("--save="):
            source = Path(arg.split("=", 1)[1])
        elif arg.startswith("--game="):
            game = Path(arg.split("=", 1)[1])
        elif arg in ("-h", "--help"):
            print(__doc__)
            print(
                "usage: python -m app [--db=PATH] [--save=PATH] [--game=PATH]\n"
                f"\n"
                f"  --save=PATH  open this stash file instead of the one being played\n"
                f"  --db=PATH    store every stash in one database (default: one\n"
                f"               file per stash under {paths.data_dir()})\n"
                f"  --game=PATH  read the game's data files from this install, for\n"
                f"               item stats; the default is to find them\n"
                f"\n"
                f"  -V, --version  print the version and exit\n"
                f"\n"
                f"  TL2IA_DATA=PATH  move the tool's own folder, default above"
            )
            return 0
        else:
            print(f"unknown argument: {arg}", file=sys.stderr)
            return 2

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Torchlight 2 Item Assistant")

    # The icon on the taskbar and in the title bar, which for a downloaded
    # executable is the same face as its file in Explorer -- the one the spec
    # stamps into the exe.  Missing is not an error: a tool drawn without an
    # icon is the tool as it was before there was one.
    from PySide6.QtGui import QIcon

    icon = Path(__file__).resolve().parent / "icon.ico"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))

    # Dark, before the window exists: a style or a palette set after a widget
    # is built does not reach what is already on screen, and this window is
    # built of hundreds of widgets in its constructor.
    from .theme import apply_theme

    apply_theme(app)

    window = MainWindow(db_path=db_path, source=source, game=game)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
