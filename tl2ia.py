"""Entry script: what the executable is built from.

``python -m app`` runs ``app/__main__.py`` as a module *inside* its package,
which is why its relative imports work.  A frozen executable has no package
around its entry script -- PyInstaller runs it as ``__main__`` at the top
level of the bundle -- so a build pointed at ``app/__main__.py`` would get as
far as ``from .window import MainWindow`` and fail there, on a machine that is
not yours to debug.  The executable is built from this file instead, which
does nothing but hand over to the same ``main()``.

Two ways in, one way through: ``python tl2ia.py`` and ``python -m app`` are
the same program, and so is ``Torchlight2ItemAssistant.exe``.
"""

from __future__ import annotations

from app import main

if __name__ == "__main__":
    raise SystemExit(main())
