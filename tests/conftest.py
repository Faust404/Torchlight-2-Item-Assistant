"""Safety net for a test suite that is capable of writing to save files.

This tool's job is to modify a file the player cares about, which means a
mistake in a test is not a failed assertion -- it is the player's stash.  That
is not hypothetical: an earlier version of these tests constructed the window
with a path it did not honour, the window fell back to the first save it could
find, and a test that meant to absorb four synthetic items emptied a real
stash instead.

So writes are fenced.  Every function that can write a stash file is wrapped
for the duration of a test and refuses a path outside that test's temporary
directory.  The fence is the point: it turns "a test wandered into the
player's Documents folder" from silent data loss into a loud failure.

The settings file is the tool's other write, and it is the same kind of thing
-- a file the player owns, in the player's folder -- so it is fenced the same
way.  Nothing in the suite writes one today; the fence is what keeps that true
once something does.  An exported collection goes wherever a save dialog was
pointed, which is the player's own folders as often as not, so it is fenced
with the rest.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tl2stash.archive as _archive  # noqa: E402
import tl2stash.portable as _portable  # noqa: E402
import tl2stash.service as _service  # noqa: E402
from app.settings import Settings as _Settings  # noqa: E402

_WRITERS = ("archive_stash", "restore_items", "write_collection")


@pytest.fixture(autouse=True)
def no_writes_outside_tmp(tmp_path, monkeypatch):
    """Refuse to write any stash file that is not inside this test's tmp dir."""

    allowed = tmp_path.resolve()

    def guard(name: str, original):
        def wrapper(path, *args, **kwargs):
            target = Path(path).resolve()
            if target != allowed and allowed not in target.parents:
                raise AssertionError(
                    f"{name}() was asked to write {target}, which is outside "
                    f"the test's temporary directory. A test must never "
                    f"write to the player's own files."
                )
            return original(path, *args, **kwargs)

        wrapper.__name__ = name
        return wrapper

    # Patch where each is *used*, not only where it is defined: these modules
    # did ``from .archive import ...``, so rebinding the name in archive.py
    # would leave the already-imported references pointing at the original.
    # The window holds its own reference to the collection writer, which is
    # the one a click reaches.
    modules = [_archive, _portable, _service]
    try:
        from app import window as _window
    except ImportError:
        pass
    else:
        modules.append(_window)
    for module in modules:
        for name in _WRITERS:
            if hasattr(module, name):
                monkeypatch.setattr(module, name, guard(name, getattr(module, name)))

    # The settings file, whose writer is a method rather than a function: same
    # check, on the path the instance was built with.
    def guarded_set(self, name, value):
        target = Path(self.path).resolve()
        if target != allowed and allowed not in target.parents:
            raise AssertionError(
                f"Settings.set() was asked to write {target}, which is outside "
                f"the test's temporary directory. A test must never modify a "
                f"file in the player's own folders."
            )
        return original_set(self, name, value)

    original_set = _Settings.set
    monkeypatch.setattr(_Settings, "set", guarded_set)


@pytest.fixture(autouse=True)
def no_widgets_left_behind():
    """Delete the widgets a test built, because nothing else can.

    A Qt widget tree built from Python cannot die on its own.  Giving a widget
    a parent hands ownership to C++, and PySide keeps the parent's reference to
    the child wrapper out of sight of the garbage collector -- which also
    cannot see the connections a child's signals hold to the window's own
    bound methods.  So a ``MainWindow`` that is closed and dropped stays in
    memory with its ~300 widgets, and every later ``setStyleSheet`` in the
    process re-polishes all of them: the suite ran for hours, ~17 s of
    restyling per test, once ``test_app.py`` had run in the same process.

    Deleting the top-level widgets is what releases the tree -- the C++
    objects go, the hidden references go with them -- so this runs after every
    test, whether or not the test closed what it built.  ``close`` goes first
    so that a window's own closeEvent still runs (the poll timer stops, the
    service closes); ``deleteLater`` is queued rather than immediate, and no
    event loop runs between tests, so the queue is flushed by hand.
    """

    yield

    # Qt is optional for this suite: most modules never import it, and a test
    # module that does may skip.  Import nothing that is not already loaded.
    if "PySide6.QtWidgets" not in sys.modules:
        return
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            # A widget parented to another top-level goes with its parent's
            # deletion, and the wrapper is a stub by the time it is reached
            # here.  Nothing left to delete is not a problem.
            pass
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
