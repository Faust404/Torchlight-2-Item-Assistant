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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QHeaderView,
    QLabel,
    QPushButton,
)

import app.window as window_module  # noqa: E402
from app.window import GAME_DATA_MISSING, MainWindow  # noqa: E402

#: The real search, kept before any fixture can stand in front of it.
_REAL_FIND_INSTALL = window_module.find_install

from test_archive import write_stash_of, write_synthetic_stash  # noqa: E402
from test_format import synthetic_item  # noqa: E402
from test_gamedata import install as synthetic_install  # noqa: E402
from tl2stash import parse_item  # noqa: E402


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


def test_the_filters_stand_over_the_pane_they_narrow(window):
    """The search box, the rarities and the level range, on the collection.

    They narrow one pane of the three and nothing else, so they belong over
    it: a row across the whole window both reads as if it narrowed the game's
    stash and the kinds too, and puts the controls a window's width away from
    the cards they act on.  The pane's column is the filters with the
    collection under them, which is the whole of the arrangement.
    """
    pane = window.collection_pane
    assert window.filters.parent() is pane
    assert window.collection_group.parent() is pane

    column = pane.layout()
    assert column.indexOf(window.filters) < column.indexOf(window.collection_group)
    assert column.count() == 2, "the pane holds the filters and the collection"

    # And nothing of them is left in the window's own column, which is the
    # toolbar and the splitter.
    assert window.centralWidget().layout().indexOf(window.filters) == -1


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
    The item leaves the tool's cards on the same refresh and turns up in the
    game's panel, so the two lists keep answering their own questions.
    """
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    window.auto_absorb.setChecked(False)
    window._absorb_all()
    assert window.collection_model.rowCount() == 3
    assert window.grid.count() == 3

    window.grid.tile(0).findChild(QPushButton, "transfer").click()

    assert window.collection_model.rowCount() == 2, "the restored item stayed in the tool"
    assert window.grid.count() == 2, "its card stayed on the wall"
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


def test_the_stash_row_is_the_item_its_level_and_its_sockets(window):
    """Three columns, and where the thing sat is on the name cell's tooltip.

    The "In the game" list is the list the player empties, so it is the item,
    the level it asks for and how many sockets it has -- the tiling is for the
    tool's own items.  Which tab and slot it came out of is a question about
    one item, asked by pointing at it.

    A socket count of none is a blank cell rather than a nought: nearly every
    row in a stash has no sockets, and the point of the column is to be read at
    a glance.  The fixture's three items are plain ones.
    """
    names = [
        window.stash_model.item(row, 0).text()
        for row in range(window.stash_model.rowCount())
    ]
    assert sorted(names) == ["Alpha", "Beta", "Gamma"]
    assert window.stash_model.columnCount() == 3
    assert [
        window.stash_model.headerData(column, Qt.Orientation.Horizontal)
        for column in range(3)
    ] == ["Item", "Lvl", "Sockets"]
    assert [
        window.stash_model.item(row, 1).text()
        for row in range(window.stash_model.rowCount())
    ] == ["5", "5", "5"]
    assert [
        window.stash_model.item(row, 2).text()
        for row in range(window.stash_model.rowCount())
    ] == ["", "", ""]


def test_a_socketed_item_in_the_game_says_so_in_its_own_column(qapp, tmp_path):
    """What the column is for: a socketed item has to come out of the game
    before the gems in it can, so it is the one thing about a row still in the
    stash that decides what to do next.

    An item with no sockets has an empty cell rather than a nought: over a
    stash where nearly nothing is socketed, a column of zeroes is one nobody
    can read at a glance.
    """
    stash = tmp_path / "sharedstash_v2.bin"
    write_stash_of(
        stash,
        [
            parse_item(synthetic_item(name="Plain Helm", level=12)[0]),
            parse_item(synthetic_item(name="Socketed Helm", level=12, sockets=3)[0]),
        ],
    )
    win = MainWindow(db_path=tmp_path / "items.db", source=stash)
    try:
        rows = {
            win.stash_model.item(row, 0).text(): win.stash_model.item(row, 2)
            for row in range(win.stash_model.rowCount())
        }
        assert set(rows) == {"Plain Helm", "Socketed Helm"}
        assert rows["Socketed Helm"].text() == "3"
        assert rows["Plain Helm"].text() == ""
    finally:
        win.close()


def test_the_name_column_takes_the_width_the_two_numbers_do_not(qapp, tmp_path):
    """The name is the column worth reading, so it is the one that stretches.

    A level is two digits and a socket count is one, so those two columns take
    what they take and every pixel left over in the pane is name.  The three
    modes have to be set *after* ``setModel``, which rebuilds the header's
    sections and puts them all back to Qt's default of a hundred pixels each:
    set before, they were dropped without a word and a pane twice that wide
    showed a hundred-pixel name column with the rest sitting empty beside it.
    """
    stash = tmp_path / "sharedstash_v2.bin"
    write_synthetic_stash(stash, ["Alpha"])
    win = MainWindow(db_path=tmp_path / "items.db", source=stash)
    try:
        win.show()
        qapp.processEvents()
        header = win.stash_view.horizontalHeader()
        assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
        assert [
            header.sectionResizeMode(column) for column in (1, 2)
        ] == [QHeaderView.ResizeMode.ResizeToContents] * 2
        name, level, sockets = (header.sectionSize(column) for column in range(3))
        assert name > level + sockets, (
            f"the name got {name}px of a {win.stash_group.width()}px pane, "
            f"against {level + sockets}px for the two numbers"
        )
    finally:
        win.close()


def test_the_game_list_does_not_offer_to_sort(window):
    """No sort arrow, because there is no sort behind it.

    The list is thrown away and rebuilt on every poll, so a column the player
    sorted by comes back in stash order at the next save -- and the arrow Qt
    draws would sit over a list that is in tab-and-slot order, claiming an
    order the rows do not have.
    """
    assert not window.stash_view.isSortingEnabled()


def test_search_filters_the_collection(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    window.auto_absorb.setChecked(False)
    window._absorb_all()

    window.filters.search.setText("Beta")
    assert window.collection_proxy.rowCount() == 1
    assert window.collection_proxy.index(0, 0).data() == "Beta"
    assert [row.name for row in window.grid.rows()] == ["Beta"], (
        "the wall did not follow the search"
    )

    window.filters.search.setText("")
    assert window.collection_proxy.rowCount() == 3
    assert window.grid.count() == 3


def test_a_search_that_matches_nothing_says_so(window, monkeypatch):
    """An empty wall with a search in the box is a different nothing from an
    empty collection, and the one thing a player will wonder is which."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    window.auto_absorb.setChecked(False)
    window._absorb_all()

    window.filters.search.setText("nothing like this")
    assert window.grid.count() == 0
    empty = window.grid.findChild(QLabel, "empty")
    assert not empty.isHidden()
    assert "matches these filters" in empty.text()


def test_the_wall_says_what_to_do_when_the_tool_is_empty(window):
    """The first thing a new player sees.  An empty panel is a question, and
    this is the answer to it: the stash is the inbox."""
    assert window.collection_model.rowCount() == 0
    assert window.grid.count() == 0
    assert "shared stash" in window.grid.findChild(QLabel, "empty").text()


def test_one_card_stands_for_every_copy_of_its_item(qapp, tmp_path, monkeypatch):
    """Two rolls of one unique: two items, one card, and the card says so.

    This is the shape the copy count exists for, and the reason putting a card
    back can put back more than one thing.  The status line says which of them
    were copies, because the player clicked one card.
    """
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    stash = tmp_path / "sharedstash_v2.bin"
    twins = [
        parse_item(synthetic_item(name="Fortress of Fools", level=level)[0])
        for level in (48, 50)
    ]
    write_stash_of(stash, twins)

    win = MainWindow(db_path=tmp_path / "items.db", source=stash)
    try:
        win.auto_absorb.setChecked(False)
        win._absorb_all()

        assert len(win.service.registry.absorbed_fingerprints()) == 2, (
            "the two rolls were not both kept"
        )
        # The model's rows are the *tiles*: two items, one card between them.
        assert win.collection_model.rowCount() == 1
        assert win.grid.count() == 1
        assert win.grid.rows()[0].copies == 2

        win.grid.tile(0).findChild(QPushButton, "transferall").click()

        assert win.stash_model.rowCount() == 2, "the card put back only one copy"
        assert "2 of Fortress of Fools" in win.status.currentMessage()
    finally:
        win.close()


def test_the_compare_button_shows_each_copy_and_puts_one_back(
    qapp, tmp_path, monkeypatch
):
    """The copies, told apart, and one of them sent back on its own.

    The tile draws both rolls of the unique as one card -- that is what makes
    the collection readable -- so the overlay is the one place they come
    apart, and putting back exactly one of them is the only reason the screen
    exists.  The other copy stays in the tool and stays on the screen.
    """
    from PySide6.QtWidgets import QMessageBox, QPushButton

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    stash = tmp_path / "sharedstash_v2.bin"
    twins = [
        parse_item(synthetic_item(name="Fortress of Fools", level=level)[0])
        for level in (48, 50)
    ]
    write_stash_of(stash, twins)

    win = MainWindow(db_path=tmp_path / "items.db", source=stash)
    try:
        win.auto_absorb.setChecked(False)
        win._absorb_all()
        assert win.grid.count() == 1, "the two rolls were not one card"
        assert win.grid.rows()[0].copies == 2

        # The player's gesture: the button on the card.
        win.grid.tile(0).findChild(QPushButton, "compare").click()

        assert not win.compare.isHidden(), "the button did not open the overlay"
        shown = win.compare.cards()
        assert [copy.row.copies for copy in shown] == [1, 1], (
            "a copy's card is the copy, not the group"
        )
        assert len({copy.row.fingerprint for copy in shown}) == 2
        # Each is drawn from its own bytes: the two rolls have two levels.
        assert len({copy.text() for copy in shown}) == 2, (
            "both copies were drawn with the same card"
        )

        sent_back, kept = shown
        sent_back.findChild(QPushButton, "putback").click()

        assert win.stash_model.rowCount() == 1, "no copy went back to the game"
        assert win.service.registry.absorbed_fingerprints() == {
            kept.row.fingerprint
        }, "the wrong copy left the tool"
        assert win.grid.rows()[0].copies == 1, "the tile still counts the copy"
        assert [copy.row.fingerprint for copy in win.compare.cards()] == [
            kept.row.fingerprint
        ]
        assert not win.compare.isHidden(), "the overlay closed with a copy left"
        assert "put back 1" in win.status.currentMessage()
    finally:
        win.close()


def test_the_one_copy_card_sends_its_item_back_without_the_overlay(
    qapp, tmp_path, monkeypatch
):
    """One copy has nothing to be compared with, so its card offers the act
    the overlay would have taken two clicks for: the button is the transfer.
    """
    from PySide6.QtWidgets import QMessageBox, QPushButton

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    stash = tmp_path / "sharedstash_v2.bin"
    write_stash_of(stash, [parse_item(synthetic_item(name="Bashdrill")[0])])

    win = MainWindow(db_path=tmp_path / "items.db", source=stash)
    try:
        win.auto_absorb.setChecked(False)
        win._absorb_all()
        assert win.grid.rows()[0].copies == 1
        assert win.grid.tile(0).findChild(QPushButton, "compare") is None
        assert win.grid.tile(0).findChild(QPushButton, "transferall") is None

        win.grid.tile(0).findChild(QPushButton, "transfer").click()

        assert win.compare.isHidden(), "one copy opened the comparison"
        assert win.stash_model.rowCount() == 1, "the item did not go back"
        assert win.service.registry.absorbed_fingerprints() == set()
        assert win.grid.count() == 0
        assert "put back 1" in win.status.currentMessage()
    finally:
        win.close()


def test_the_transfer_all_button_sends_every_copy_at_once(
    qapp, tmp_path, monkeypatch
):
    """The card is the group, so the button that names the group puts back
    what the card says it is -- both rolls, in one click, leaving nothing
    behind on the wall."""
    from PySide6.QtWidgets import QMessageBox, QPushButton

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    stash = tmp_path / "sharedstash_v2.bin"
    write_stash_of(
        stash,
        [
            parse_item(synthetic_item(name="Fortress of Fools", level=level)[0])
            for level in (48, 50)
        ],
    )

    win = MainWindow(db_path=tmp_path / "items.db", source=stash)
    try:
        win.auto_absorb.setChecked(False)
        win._absorb_all()
        assert win.grid.rows()[0].copies == 2

        win.grid.tile(0).findChild(QPushButton, "transferall").click()

        assert win.stash_model.rowCount() == 2, "not every copy went back"
        assert win.service.registry.absorbed_fingerprints() == set()
        assert win.grid.count() == 0
        assert "put back 2" in win.status.currentMessage()
        assert "2 of Fortress of Fools" in win.status.currentMessage()
    finally:
        win.close()


# --------------------------------------------------------------------------
# The stats
# --------------------------------------------------------------------------


def test_the_stash_tooltip_names_the_tab_the_player_counts(game_window):
    """The file numbers containers; the player counts tabs from one.

    The internal name is on the tooltip under it: it says what the bag was
    built for, which is not what the player is looking at but is what a bug
    report would quote.
    """
    assert game_window.stash_model.rowCount() == 3
    for row in range(game_window.stash_model.rowCount()):
        cell = game_window.stash_model.item(row, 0)
        assert cell.toolTip() == f"Tab 1 · slot {3322 + row}\nSHARED_STASH_BAG_ARMS"


def test_the_collection_draws_the_item_rather_than_summarising_it(stocked):
    """What the wall is for: the item's own card, not a row of columns.

    Rendered from the bytes the registry kept, so it is the same parse the
    game does rather than a re-reading of the columns beside it.
    """
    assert stocked.grid.count() == 3  # the collection is in name order
    assert stocked.grid.tile(0).text() == "Alpha\nRequirements\nPlayer Level 5"
    assert stocked.grid.tile(2).text() == "Gamma\nRequirements\nPlayer Level 5"


def test_the_selection_survives_a_refresh(stocked):
    """The wall is rebuilt whenever the game saves -- every few seconds in
    play.  A highlight that went out on every save would blink on and off
    under a player reading the cards they had picked out."""
    stocked.grid.select_row(1)
    assert [row.name for row in stocked.grid.selected()] == ["Beta"]

    stocked._sync(write=False)

    assert stocked.grid.count() == 3
    assert [row.name for row in stocked.grid.selected()] == ["Beta"], (
        "the selection was dropped by a refresh"
    )
    assert stocked.grid.tile(1).is_selected()


def test_the_poll_draws_no_card_again(stocked, monkeypatch):
    """The property the whole wall is arranged around.

    Drawing a card means walking the game's data files and cutting a picture
    out of a sheet, and the wall is rebuilt on every save.  So a card is built
    once per item and looked up by fingerprint after that: a poll that changed
    nothing must not draw anything, and neither must clicking on a card that is
    already drawn.
    """
    calls: list[str] = []
    original = stocked._render_stats
    monkeypatch.setattr(
        stocked,
        "_render_stats",
        lambda print_: calls.append(print_) or original(print_),
    )

    assert stocked.grid.count() == 3, "the fixture's cards were not built"
    assert len(calls) == 0, "the cards were drawn again to build the wall"

    stocked.grid.select_row(0)
    assert stocked.grid.tile(0).text() == "Alpha\nRequirements\nPlayer Level 5"
    assert len(calls) == 0, "selecting a card drew it again"

    for _ in range(3):
        stocked._sync(write=False)

    assert len(calls) == 0, "a refresh drew a card again"
    assert stocked.grid.tile(0).text() == "Alpha\nRequirements\nPlayer Level 5"


def test_without_the_game_the_window_says_so_in_one_line(qapp, tmp_path):
    """A machine without Torchlight II installed is degraded, not broken.

    The items are stored and put back exactly the same; all that is missing is
    the wording.  The game's panel still works, and the one line over the wall
    says what is missing -- with the whole of it, including how to point the
    tool at the game, on the tooltip rather than in the window.
    """
    stash = tmp_path / "sharedstash_v2.bin"
    write_synthetic_stash(stash, ["Alpha"])
    win = MainWindow(
        db_path=tmp_path / "items.db", source=stash, game=tmp_path / "nowhere"
    )
    try:
        assert win._game_data() is None
        assert not win.banner.isHidden()
        assert "not found" in win.banner.text()
        assert win.banner.toolTip() == GAME_DATA_MISSING
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
        assert win.grid.count() == 2, "the cards were not drawn without the game"
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


def test_restore_puts_the_item_back(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    window.auto_absorb.setChecked(False)
    window._absorb_all()
    assert window.stash_model.rowCount() == 0

    # The first card's own button, which is where putting one back lives now.
    window.grid.tile(0).findChild(QPushButton, "transfer").click()

    assert window.stash_model.rowCount() == 1
    assert window.collection_model.rowCount() == 2
    assert window.grid.count() == 2


def test_restoring_does_not_get_undone_by_the_automatic_pass(window, monkeypatch):
    """The whole point of the in_stash status, at the window level."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    window._absorb_all()
    window.grid.tile(0).findChild(QPushButton, "transfer").click()

    window.auto_absorb.setChecked(True)
    window._sync()

    assert window.stash_model.rowCount() == 1, "the restored item vanished again"
