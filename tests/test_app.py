"""Smoke tests for the window, run against Qt's offscreen platform.

These are not tests of the format or the file writes -- those live in
tl2stash and are tested there.  What they cover is the wiring: that the
window builds, that the tables are fed, and above all that the automatic
pass acts on the right events.  A GUI that vacuums a stash when it opens is a
bug no unit test below it would catch.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Qt needs a platform plugin even to build widgets.  Must be set before the
# first PySide6 import, hence the importorskip below rather than at the top.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 is not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.window import MainWindow  # noqa: E402

from test_archive import write_synthetic_stash  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session; Qt allows no more."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def no_real_saves(monkeypatch):
    """Stop window tests discovering the player's own stashes.

    Constructing a window runs a sync, and a sync can take items out of the
    file it is pointed at.  If discovery can find the real saves, a test that
    goes wrong takes something real with it -- so discovery finds nothing,
    and every test passes its file in explicitly.
    """
    import app.window as window_module

    monkeypatch.setattr(window_module, "find_save_locations", lambda: [])


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """Make dialogs non-blocking.

    A real QMessageBox waits for a click that never comes under the offscreen
    platform, so a test that trips one hangs forever instead of failing.  An
    earlier run of this file did exactly that, and produced no output at all.
    Tests that care what the user answered override these.
    """
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)


@pytest.fixture
def window(qapp, tmp_path):
    stash = tmp_path / "sharedstash_v2.bin"
    write_synthetic_stash(stash, ["Alpha", "Beta", "Gamma"])
    win = MainWindow(db_path=tmp_path / "items.db", source=stash)

    # The window must be looking at the file the test handed it.  This exact
    # assumption is what failed before, and it failed silently.
    assert win.service is not None
    assert win.service.source.resolve() == stash.resolve(), (
        f"the window opened {win.service.source}, not the file the test asked for"
    )

    yield win
    win.close()


# --------------------------------------------------------------------------
# Building
# --------------------------------------------------------------------------


def test_window_opens_without_a_save_file(qapp, tmp_path):
    """The game may never have run.  That is not a crash."""
    win = MainWindow(db_path=tmp_path / "items.db", source=tmp_path / "absent.bin")
    assert win.stash_model.rowCount() == 0
    win.close()


def test_window_uses_the_file_it_was_given(qapp, tmp_path):
    """Regression: an explicit save file that discovery does not know about.

    The window used to ignore it and fall back to the first discovered save,
    which pointed it at the player's real stash.  Silently operating on a
    different file than the one asked for is the worst possible failure for a
    tool whose job is deciding which items leave which file.
    """
    stash = tmp_path / "elsewhere" / "sharedstash_v2.bin"
    stash.parent.mkdir()
    write_synthetic_stash(stash, ["Solo"])

    win = MainWindow(db_path=tmp_path / "items.db", source=stash)
    try:
        assert win.service.source.resolve() == stash.resolve()
        assert win.stash_model.rowCount() == 1
        assert win.stash_model.item(0, 0).text() == "Solo"
    finally:
        win.close()


def test_stash_and_collection_are_both_listed(window):
    assert window.stash_model.rowCount() == 3
    assert window.collection_model.rowCount() == 3
    assert "3" in window.stash_group.title()


def test_the_stash_column_shows_where_things_are(window):
    names = [
        window.stash_model.item(row, 0).text()
        for row in range(window.stash_model.rowCount())
    ]
    assert sorted(names) == ["Alpha", "Beta", "Gamma"]


def test_search_filters_the_collection(window):
    window.search.setText("Beta")
    assert window.collection_proxy.rowCount() == 1
    assert window.collection_proxy.index(0, 0).data() == "Beta"

    window.search.setText("")
    assert window.collection_proxy.rowCount() == 3


# --------------------------------------------------------------------------
# The automatic pass -- what it acts on, and what it must not
# --------------------------------------------------------------------------


def test_opening_the_window_does_not_absorb(window, tmp_path):
    """Looking is not deciding.

    The stash may hold a session's worth of things the player has not thought
    about yet, so startup shows them and touches nothing.
    """
    assert window.stash_model.rowCount() == 3
    assert window.service.registry.absorbed_fingerprints() == set()
    assert len(window.service.stash_items()) == 3


def test_pressing_refresh_does_not_absorb(window):
    window._sync(write=False)
    assert window.stash_model.rowCount() == 3
    assert window.service.registry.absorbed_fingerprints() == set()


def test_a_save_is_absorbed_automatically(window, tmp_path):
    """The flow the tool exists for: the player puts things in the stash, the
    game saves, the items end up here and out of the game."""
    stash = window.service.source
    assert not window.watcher.changed(), "startup already accepted the file"

    # The player adds something and the game writes the stash.
    write_synthetic_stash(stash, ["Alpha", "Beta", "Gamma", "Delta"])
    assert window.watcher.changed(), "a rewritten save must register as a change"

    window._sync()

    assert window.stash_model.rowCount() == 0
    assert window.collection_model.rowCount() == 4
    names = {
        window.collection_model.item(r, 0).text()
        for r in range(window.collection_model.rowCount())
    }
    assert "Delta" in names


def test_automatic_off_leaves_the_stash_alone(window):
    window.auto_absorb.setChecked(False)
    window._sync()
    assert window.stash_model.rowCount() == 3
    assert window.service.registry.absorbed_fingerprints() == set()


def test_the_game_putting_an_item_back_is_undone(window):
    """Torchlight saves from memory, so it re-adds what we took."""
    stash = window.service.source
    game_saved = stash.read_bytes()

    window._sync()
    assert window.stash_model.rowCount() == 0

    stash.write_bytes(game_saved)  # the game saves its in-memory copy
    window._sync()

    assert window.stash_model.rowCount() == 0
    assert window.collection_model.rowCount() == 3


# --------------------------------------------------------------------------
# The explicit gesture
# --------------------------------------------------------------------------


def test_absorb_everything_takes_the_lot(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    window.auto_absorb.setChecked(False)

    window._absorb_all()

    assert window.stash_model.rowCount() == 0
    assert len(window.service.registry.absorbed_fingerprints()) == 3


def test_absorb_everything_can_be_cancelled(window, monkeypatch):
    """The confirmation is the only thing between a stray click and the
    player's whole stash changing places."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel
    )
    window.auto_absorb.setChecked(False)

    window._absorb_all()

    assert window.stash_model.rowCount() == 3
    assert window.service.registry.absorbed_fingerprints() == set()


def test_restore_puts_the_selection_back(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    window.auto_absorb.setChecked(False)
    window._absorb_all()
    assert window.stash_model.rowCount() == 0

    # Select the first row of the collection and put it back.
    window.collection_view.selectRow(0)
    window._restore_selected()

    assert window.stash_model.rowCount() == 1
    assert window.collection_model.rowCount() == 3


def test_restoring_does_not_get_undone_by_the_automatic_pass(window, monkeypatch):
    """The whole point of the in_stash status, at the window level."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    window._absorb_all()
    window.collection_view.selectRow(0)
    window._restore_selected()

    window.auto_absorb.setChecked(True)
    window._sync()

    assert window.stash_model.rowCount() == 1, "the restored item vanished again"
