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

import app.window as window_module  # noqa: E402
from app.window import GAME_DATA_MISSING, MainWindow  # noqa: E402

#: The real search, kept before any fixture can stand in front of it.
_REAL_FIND_INSTALL = window_module.find_install

from test_archive import write_synthetic_stash  # noqa: E402
from test_gamedata import install as synthetic_install  # noqa: E402


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
def no_real_game(monkeypatch):
    """Stop window tests *searching* for the game's data files.

    The search is a walk of the registry and every Steam library, and reading
    ten thousand files takes a second; either would make these tests depend on
    what happens to be installed on the machine running them.  Only the search
    is turned off -- an install the test names with ``game=`` is still used,
    which is how the tests that care about stats get one.
    """
    import app.window as window_module

    monkeypatch.setattr(
        window_module,
        "find_install",
        lambda explicit=None: _REAL_FIND_INSTALL(explicit) if explicit else None,
    )


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


@pytest.fixture
def game_install(tmp_path):
    """A stand-in for the game's own data files.

    The synthetic install the game-data tests already use, so the two agree on
    what a name means.
    """
    return synthetic_install(tmp_path / "game")


@pytest.fixture
def game_window(qapp, tmp_path, game_install):
    """A window with the game's data, and three items it has not taken."""
    stash = tmp_path / "sharedstash_v2.bin"
    write_synthetic_stash(stash, ["Alpha", "Beta", "Gamma"])
    win = MainWindow(db_path=tmp_path / "items.db", source=stash, game=game_install)
    try:
        assert win._game_data() is not None, "the fixture's install did not load"
        yield win
    finally:
        win.close()


@pytest.fixture
def stocked(game_window, monkeypatch):
    """The same window, with all three absorbed."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    game_window.auto_absorb.setChecked(False)
    game_window._absorb_all()
    assert game_window.collection_model.rowCount() == 3, (
        "the fixture did not stock the tool"
    )
    return game_window


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


def test_the_two_panels_describe_different_places(window):
    """At startup: three items in the game, none of them ours.

    The panels are not two views of one list.  The left one is the file; the
    right one is the tool.  Until something is absorbed they share no rows, so
    an empty collection is the correct answer to "what does the tool hold?"
    """
    assert window.stash_model.rowCount() == 3
    assert window.collection_model.rowCount() == 0
    assert "3" in window.stash_group.title()
    assert "0" in window.collection_group.title()


def test_the_collection_lists_only_what_the_tool_holds(window, monkeypatch):
    """The contract for the right-hand panel.

    An item in the stash is the game's until it is absorbed.  It must not sit
    in the tool's list looking like something the tool is responsible for --
    which is what happened while the panel showed every item ever seen, each
    tagged with where it currently was.
    """
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    window.auto_absorb.setChecked(False)
    window._sync()
    assert window.stash_model.rowCount() == 3
    assert window.collection_model.rowCount() == 0, (
        "the collection listed items the tool had not taken"
    )

    window._absorb_all()
    assert window.stash_model.rowCount() == 0
    assert window.collection_model.rowCount() == 3


def test_an_item_put_back_drops_off_the_collection(window, monkeypatch):
    """The user's third point, at the window level.

    Putting an item back has to be visible in the place the player is looking.
    The item leaves the tool's list on the same refresh and turns up in the
    game's panel, so the two lists keep answering their own questions.
    """
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    window.auto_absorb.setChecked(False)
    window._absorb_all()
    assert window.collection_model.rowCount() == 3

    window.collection_view.selectRow(0)
    window._restore_selected()

    assert window.collection_model.rowCount() == 2, "the restored item stayed in the tool"
    assert window.stash_model.rowCount() == 1, "the restored item is not in the game's panel"


def test_modded_and_vanilla_do_not_share_a_pile(qapp, tmp_path, monkeypatch):
    """The user's fourth point, stated as a property.

    Two stashes, two databases.  An item absorbed out of one is not in the
    other -- and could not be put back into it, because that database has
    never held its bytes.  That is the point of a file each rather than a
    column: the separation cannot be forgotten in a query.
    """
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )

    vanilla = tmp_path / "save" / "76561198328811052" / "sharedstash_v2.bin"
    modded = tmp_path / "modsave" / "76561198328811052" / "sharedstash_v2.bin"
    for path in (vanilla, modded):
        path.parent.mkdir(parents=True)
    write_synthetic_stash(vanilla, ["Alpha"])
    write_synthetic_stash(modded, ["Beta"])

    var = tmp_path / "var"
    one = MainWindow(db_dir=var, source=vanilla)
    two = MainWindow(db_dir=var, source=modded)
    try:
        assert one.service.source_key == "vanilla/76561198328811052"
        assert two.service.source_key == "modded/76561198328811052"

        one._absorb_all()
        two._absorb_all()

        assert one.service.registry.path != two.service.registry.path
        assert one.service.registry.path.name == "items-vanilla-76561198328811052.db"
        assert two.service.registry.path.name == "items-modded-76561198328811052.db"
        assert {r["name"] for r in one.service.registry.rows()} == {"Alpha"}
        assert {r["name"] for r in two.service.registry.rows()} == {"Beta"}
    finally:
        one.close()
        two.close()


def test_the_stash_column_shows_where_things_are(window):
    names = [
        window.stash_model.item(row, 0).text()
        for row in range(window.stash_model.rowCount())
    ]
    assert sorted(names) == ["Alpha", "Beta", "Gamma"]


def test_search_filters_the_collection(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    window.auto_absorb.setChecked(False)
    window._absorb_all()

    window.search.setText("Beta")
    assert window.collection_proxy.rowCount() == 1
    assert window.collection_proxy.index(0, 0).data() == "Beta"

    window.search.setText("")
    assert window.collection_proxy.rowCount() == 3


# --------------------------------------------------------------------------
# The stats
# --------------------------------------------------------------------------


def test_the_tab_column_names_the_tab_the_player_counts(game_window):
    """The file numbers containers; the player counts tabs from one.

    The internal name is the cell's tooltip: it says what the bag was built
    for, which is not what the player is looking at.
    """
    assert game_window.stash_model.rowCount() == 3
    for row in range(game_window.stash_model.rowCount()):
        assert game_window.stash_model.item(row, 2).text() == "Tab 1"
        assert (
            game_window.stash_model.item(row, 2).toolTip() == "SHARED_STASH_BAG_ARMS"
        )


def test_the_details_pane_describes_the_selected_item(stocked):
    """What the pane is for: the item's own stats, not the table's summary.

    Rendered from the bytes the registry kept, so it is the same parse the
    game does rather than a re-reading of the columns beside it.
    """
    assert stocked.details.toPlainText() == "Select an item to see its stats."

    stocked.collection_view.selectRow(0)  # the collection is sorted by name
    assert stocked.details.toPlainText() == "Alpha\nRequires Level 5"


def test_the_selection_and_the_pane_survive_a_refresh(stocked):
    """Both tables are rebuilt whenever the game saves -- every few seconds in
    play.  Losing the selection there would empty the pane while it was being
    read, and would quietly disarm "Put back selected"."""
    stocked.collection_view.selectRow(1)
    assert stocked.details.toPlainText() == "Beta\nRequires Level 5"

    stocked._sync(write=False)

    assert stocked.collection_model.rowCount() == 3
    assert stocked._current_fingerprint() is not None, "the selection was dropped"
    assert stocked.details.toPlainText() == "Beta\nRequires Level 5"


def test_the_poll_never_renders_anything(stocked, monkeypatch):
    """The property the whole pane is arranged around.

    Drawing stats means walking the game's data files, and the table beneath
    is redrawn on every save.  So the lines are kept by fingerprint: an item
    is drawn when it is selected and never again, however many refreshes go by
    while it stays selected.
    """
    calls: list[str] = []
    original = stocked._render_stats
    monkeypatch.setattr(
        stocked,
        "_render_stats",
        lambda print_: calls.append(print_) or original(print_),
    )

    stocked.collection_view.selectRow(0)
    assert stocked.details.toPlainText() == "Alpha\nRequires Level 5"
    assert len(calls) == 1, "selecting an item did not draw it"

    for _ in range(3):
        stocked._sync(write=False)

    assert len(calls) == 1, "a refresh drew the stats again"
    assert stocked.details.toPlainText() == "Alpha\nRequires Level 5"


def test_selecting_another_item_draws_that_one(stocked):
    stocked.collection_view.selectRow(0)
    stocked.collection_view.selectRow(2)
    assert stocked.details.toPlainText() == "Gamma\nRequires Level 5"


def test_without_the_game_the_pane_says_so(qapp, tmp_path):
    """A machine without Torchlight II installed is degraded, not broken.

    The items are stored and put back exactly the same; all that is missing is
    the wording, so the pane says which and how to fix it rather than showing
    nothing or, worse, guessing.
    """
    stash = tmp_path / "sharedstash_v2.bin"
    write_synthetic_stash(stash, ["Alpha"])
    win = MainWindow(
        db_path=tmp_path / "items.db", source=stash, game=tmp_path / "nowhere"
    )
    try:
        assert win._game_data() is None
        assert win.details.toPlainText() == GAME_DATA_MISSING
        assert "no game data" in win._describe()
        assert win.stash_model.rowCount() == 1, "the game's panel still works"
    finally:
        win.close()


def test_a_window_that_cannot_read_the_game_still_absorbs(qapp, tmp_path, monkeypatch):
    """The one thing that must not depend on the game being installed."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    stash = tmp_path / "sharedstash_v2.bin"
    write_synthetic_stash(stash, ["Alpha", "Beta"])
    win = MainWindow(
        db_path=tmp_path / "items.db", source=stash, game=tmp_path / "nowhere"
    )
    try:
        win.auto_absorb.setChecked(False)
        win._absorb_all()
        assert win.collection_model.rowCount() == 2
        assert win.stash_model.rowCount() == 0
    finally:
        win.close()


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
    assert window.collection_model.rowCount() == 2


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
