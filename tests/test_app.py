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
    QCheckBox,
    QHeaderView,
    QLabel,
    QPushButton,
)

import app.window as window_module  # noqa: E402
from app.card import LinkLabel  # noqa: E402
from app.filters import INSET  # noqa: E402
from app.models import LEVEL_MAX, NUMBER_MAX  # noqa: E402
from app.window import GAME_DATA_MISSING, MainWindow  # noqa: E402

#: The real search, kept before any fixture can stand in front of it.
_REAL_FIND_INSTALL = window_module.find_install

from test_archive import write_stash_of, write_synthetic_stash  # noqa: E402
from test_format import synthetic_item  # noqa: E402
from test_gamedata import _bashdrill, install as synthetic_install  # noqa: E402
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


def test_the_row_stands_in_where_the_box_it_is_over_stands_out(window):
    """The user's nudge, which is the row lining up with the cards under it.

    The bar and the collection box are two children of one column, so the row
    is inset from the pane's edge by exactly what a group box puts in front of
    its contents -- :data:`app.filters.INSET`, measured against a real box in
    ``tests/test_app_filters.py`` -- and not by that twice: the box is flush
    with the pane's edge and the inset is the row's own.  Where three widgets
    sit is most of what there is to say about a row like this, and a pane that
    grew a margin or a box that no longer filled it would be the row drifting
    off the cards with nothing else in the suite saying so.
    """
    window.show()
    QApplication.processEvents()

    pane = window.collection_pane
    bar = window.filters.mapTo(pane, window.filters.rect().topLeft())
    box = window.collection_group.mapTo(
        pane, window.collection_group.rect().topLeft()
    )
    search = window.filters.search.mapTo(
        pane, window.filters.search.rect().topLeft()
    )

    assert (bar.x(), box.x()) == (0, 0), (
        "the row and the box no longer start on the pane's own edge"
    )
    assert search.x() == INSET, "the row is not inset from the box's frame"


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


def test_the_stash_row_is_the_item_its_level_and_its_counts(window):
    """Four columns, and where the thing sat is on the name cell's tooltip.

    The "In the game" list is the list the player empties, so it is the item,
    the level it asks for, how many are in the stack and how many sockets it
    has -- the tiling is for the tool's own items.  Which tab and slot it came
    out of is a question about one item, asked by pointing at it.

    A socket count of none is a blank cell rather than a nought, and so is the
    quantity of a stack of one: nearly every row in a stash is both, and the
    point of either column is to be read at a glance.  The fixture's three
    items are plain ones.
    """
    names = [
        window.stash_model.item(row, 0).text()
        for row in range(window.stash_model.rowCount())
    ]
    assert sorted(names) == ["Alpha", "Beta", "Gamma"]
    assert window.stash_model.columnCount() == 4
    assert [
        window.stash_model.headerData(column, Qt.Orientation.Horizontal)
        for column in range(4)
    ] == ["Item", "Lvl", "Qty", "Sockets"]
    assert [
        window.stash_model.item(row, 1).text()
        for row in range(window.stash_model.rowCount())
    ] == ["5", "5", "5"]
    assert [
        window.stash_model.item(row, 2).text()
        for row in range(window.stash_model.rowCount())
    ] == ["", "", ""]
    assert [
        window.stash_model.item(row, 3).text()
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
            win.stash_model.item(row, 0).text(): win.stash_model.item(row, 3)
            for row in range(win.stash_model.rowCount())
        }
        assert set(rows) == {"Plain Helm", "Socketed Helm"}
        assert rows["Socketed Helm"].text() == "3"
        assert rows["Plain Helm"].text() == ""
    finally:
        win.close()


def test_a_stack_in_the_game_says_how_many_it_is(qapp, tmp_path):
    """What the quantity column is for: a fish or a potion is a *pile*, and
    the pile is the item -- twenty potions is one row that has to say twenty,
    because that is what goes back when it goes back.

    A stack of one is a blank cell rather than a 1 -- a column of ones is the
    column nobody reads that a column of noughts would be, and the number only
    means something on the rows where it is not one.
    """
    stash = tmp_path / "sharedstash_v2.bin"
    write_stash_of(
        stash,
        [
            parse_item(synthetic_item(name="Neverending Fish", quantity=20)[0]),
            parse_item(synthetic_item(name="Plain Sword")[0]),
        ],
    )
    win = MainWindow(db_path=tmp_path / "items.db", source=stash)
    try:
        rows = {
            win.stash_model.item(row, 0).text(): win.stash_model.item(row, 2)
            for row in range(win.stash_model.rowCount())
        }
        assert set(rows) == {"Neverending Fish", "Plain Sword"}
        assert rows["Neverending Fish"].text() == "20"
        assert rows["Plain Sword"].text() == ""
    finally:
        win.close()


def test_the_name_column_takes_the_width_the_numbers_do_not(qapp, tmp_path):
    """The name is the column worth reading, so it is the one that stretches.

    A level is two digits and the two counts are one or two, so those three
    columns take what they take and every pixel left over in the pane is name.
    The three modes have to be set *after* ``setModel``, which rebuilds the
    header's sections and puts them all back to Qt's default of a hundred
    pixels each: set before, they were dropped without a word and a pane twice
    that wide showed a hundred-pixel name column with the rest sitting empty
    beside it.
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
            header.sectionResizeMode(column) for column in (1, 2, 3)
        ] == [QHeaderView.ResizeMode.ResizeToContents] * 3
        name, level, quantity, sockets = (
            header.sectionSize(column) for column in range(4)
        )
        assert name > level + quantity + sockets, (
            f"the name got {name}px of a {win.stash_group.width()}px pane, "
            f"against {level + quantity + sockets}px for the three numbers"
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


def test_the_advanced_panel_narrows_the_wall_and_clear_filters_puts_it_back(
    qapp, tmp_path, game_install, monkeypatch
):
    """The wiring, at the window.

    The panel hands over one value; the window is what writes it onto the two
    places a search lives.  Three of the nine facets have controls in the row --
    the name, the rarity, the player level -- and the rest are the panel's: the
    item level range and the sockets behind the button, and the *kinds*, which
    are ticked in the rail.  So this walks one of each: a chip the row also has,
    a facet with no control in the window at all, and the grid that is the
    rail's second view.

    Two swords of the fixture's at two levels and two rarities, so that both the
    item level range and the rarity chip have something to separate, and both
    kinds the collection holds are ticked in the grid -- which is what says the
    rail's ticks came from the panel rather than from a click on the rail.
    """
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    stash = tmp_path / "sharedstash_v2.bin"
    write_stash_of(
        stash,
        [
            parse_item(synthetic_item(name="Longblade", guid=0x7001, level=40)[0]),
            parse_item(synthetic_item(name="Emberblade", guid=0x7002, level=20)[0]),
        ],
    )
    win = MainWindow(db_path=tmp_path / "items.db", source=stash, game=game_install)
    try:
        win.auto_absorb.setChecked(False)
        win._absorb_all()
        assert win.grid.count() == 2, "the fixture did not stock the tool"
        assert win.sidebar.places() == set(), "something was ticked to start with"

        win.filters.advanced.click()
        assert not win.advanced.isHidden(), "the button did not open the panel"

        panel = win.advanced
        panel.name.setText("blade")
        panel.rarity_chips["Unique"].setChecked(True)
        panel.item_low.setValue(10)
        for box in panel.types.findChildren(QCheckBox):
            box.setChecked(True)
        kinds = panel.types.ticks()
        assert kinds, "the grid drew no kind to tick"

        panel.search_button.click()

        assert panel.isHidden(), "Search left the panel up"
        assert win.filters.search_text() == "blade"
        assert win.filters.tiers() == {"Unique"}
        assert win.filters.item_level_range() == (10, LEVEL_MAX)
        assert win.sidebar.places() == kinds, "the kinds did not reach the rail"
        assert [row.name for row in win.grid.rows()] == ["Emberblade"]

        # The second pass, on a facet with no control anywhere in the window:
        # the panel opens on what is in force, and a socket count neither sword
        # has empties the wall.
        win.filters.advanced.click()
        win.advanced.socket_chips[2].setChecked(True)
        win.advanced.search_button.click()

        assert win.filters.sockets() == {2}
        assert win.filters.advanced_active() is True
        assert win.grid.count() == 0, "the socket count did not reach the proxy"
        assert "advanced search is narrowing" in win.status.currentMessage()

        # And `Clear filters` is the whole of it: the bar's controls, the four
        # behind the button, and the kinds, which are the rail's.
        win.filters.clear_button.click()

        assert win.filters.advanced_active() is False
        assert win.filters.search_text() == ""
        assert win.filters.item_level_range() == (0, LEVEL_MAX)
        assert win.sidebar.places() == set(), "the rail kept a kind ticked"
        assert win.grid.count() == 2
    finally:
        win.close()


def test_the_card_reading_facets_reach_the_wall(
    qapp, tmp_path, game_install, monkeypatch
):
    """The three facets that need an item's card, wired end to end.

    A card is not on the row: it is built by walking the game's data files, so
    the window hands the proxy a *way* to ask for one -- its own memo, the same
    one the wall draws from -- and nothing else in the tool would show whether
    the two are connected.  The panel is opened and driven exactly as a player
    drives it, and what is asserted is what ends up on the wall.

    Bashdrill is the item with something on it: 72 physical damage and a list
    of properties, against the fixture's plain sword, which carries neither.
    The three facets are asked in turn, each on its own, because they AND --
    which is the rule the first two halves of this test are also reading.
    """
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    stash = tmp_path / "sharedstash_v2.bin"
    write_stash_of(
        stash,
        [
            _bashdrill(),
            parse_item(synthetic_item(name="Plainblade", guid=0x7001, level=40)[0]),
        ],
    )
    win = MainWindow(db_path=tmp_path / "items.db", source=stash, game=game_install)
    try:
        win.auto_absorb.setChecked(False)
        win._absorb_all()
        assert win.grid.count() == 2, "the fixture did not stock the tool"

        # What the wall is read from is the cards behind it, so the assertion
        # below is a statement about the same reading the filter is given.
        card = win._detail_for(win.grid.rows()[0].fingerprint)
        assert card is not None, "the window cannot answer for its own items"

        # A damage range: the plain sword deals none, and an item that carries
        # no part of an element named in the row is not an item it is looking
        # for, however wide the range is.
        win.filters.advanced.click()
        panel = win.advanced
        panel.damage_spins["physical"][0].setValue(50)
        panel.damage_spins["physical"][1].setValue(100)
        panel.search_button.click()

        assert win.filters.damage_ranges() == (("physical", 50, 100),)
        assert [row.name for row in win.grid.rows()] == ["Bashdrill"]

        # A property row, on the same two items: the words are matched against
        # the lines the card shows, and only one of the two says this one.
        win.filters.clear_button.click()
        win.filters.advanced.click()
        win.advanced.findChild(QPushButton, "aadd").click()
        win.advanced.stat_rows[0].text.setText("lightning damage bonus")
        win.advanced.search_button.click()

        assert win.filters.stat_rows() == (("lightning damage bonus", 0, NUMBER_MAX),)
        assert [row.name for row in win.grid.rows()] == ["Bashdrill"]

        # And the order, which reads the same numbers: most first, with an item
        # that carries none below one that carries seventy-two.
        win.filters.clear_button.click()
        win.filters.sort.setCurrentText("Damage")

        assert [row.name for row in win.grid.rows()] == ["Bashdrill", "Plainblade"]
    finally:
        win.close()


def test_the_wall_says_what_to_do_when_the_tool_is_empty(window):
    """The first thing a new player sees.  An empty panel is a question, and
    this is the answer to it: the stash is the inbox."""
    assert window.collection_model.rowCount() == 0
    assert window.grid.count() == 0
    assert "shared stash" in window.grid.findChild(QLabel, "empty").text()


def test_the_wall_opens_on_the_ladder_and_the_arrow_turns_it(
    qapp, tmp_path, game_install, monkeypatch
):
    """The user's third change at the window: the cards come out ordered.

    The fixture's install has a unique item and rarities of no other kind --
    see ``tests/test_gamedata.py`` -- so what this can show is one rung against
    the untiered tail.  That is enough for the wiring: a rarity before an item
    with none, the levels running up inside both, and neither the names nor the
    order the items went in accounting for what comes out.  The ladder itself,
    every rung from Legendary to Normal, is pinned against a model built by
    hand in ``tests/test_app_filters.py``.

    The reverse is the part worth reading twice: it is *not* the wall upside
    down.  The arrow turns the ladder over and leaves each tier running 1 to
    100, which is what the user asked for and what the reference does not do.
    """
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    stash = tmp_path / "sharedstash_v2.bin"
    write_stash_of(
        stash,
        [
            # Two uniques (0x7002 is the fixture's unique sword), handed over
            # in the order that is neither the names' nor the levels'.
            parse_item(synthetic_item(name="Ash", guid=0x9999, level=99)[0]),
            parse_item(synthetic_item(name="Wisp", guid=0x8888, level=10)[0]),
            parse_item(synthetic_item(name="Stormband", guid=0x7002, level=60)[0]),
            parse_item(synthetic_item(name="Emberband", guid=0x7002, level=20)[0]),
        ],
    )
    win = MainWindow(db_path=tmp_path / "items.db", source=stash, game=game_install)
    try:
        win.auto_absorb.setChecked(False)
        win._absorb_all()
        assert win.grid.count() == 4, "the fixture did not stock the tool"

        wall = [row.name for row in win.grid.rows()]
        assert wall == ["Emberband", "Stormband", "Wisp", "Ash"], (
            "the wall did not open on the rarity ladder"
        )

        # The player's gesture on the arrow.
        win.filters.reverse.click()

        assert [row.name for row in win.grid.rows()] == [
            "Wisp",
            "Ash",
            "Emberband",
            "Stormband",
        ], "the arrow did not turn the ladder over, or turned the tiers with it"

        # And the box's other keys reach the wall the same way.  The arrow
        # stays over, as it does in the reference: one switch for every key.
        win.filters.sort.setCurrentText("Level")

        assert [row.name for row in win.grid.rows()] == [
            "Ash",
            "Stormband",
            "Emberband",
            "Wisp",
        ], "the sort box did not reach the wall"
    finally:
        win.close()


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
        sent_back.findChild(QPushButton, "transfer").click()

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


def test_a_click_on_a_set_name_shows_every_piece_of_that_set(
    qapp, tmp_path, game_install, monkeypatch
):
    """The user's fifth change, end to end: the name on the card is a link.

    The ladder under that name is what the *set* grants rather than what this
    one piece does, so a player reading one piece of a set is the player most
    likely to want the rest -- and the tool is where the rest of it is, because
    the tool is where the items went.

    A switch rather than a narrowing: the player clicked a name, not a control,
    and they are asking to see the set rather than to see the set as well as
    whatever they had ticked a moment ago.  So every other facet goes back to
    where the window starts it -- including the rail, which is the one part of
    that clearing the bar cannot do.  What the click is worth is both pieces
    under one name, where the search for one of them showed one.
    """
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    stash = tmp_path / "sharedstash_v2.bin"
    write_stash_of(
        stash,
        [
            parse_item(synthetic_item(name="Test Set Blade", guid=0x7007, level=20)[0]),
            parse_item(synthetic_item(name="Test Set Edge", guid=0x7008, level=20)[0]),
            parse_item(synthetic_item(name="Test Plain", guid=0x7001, level=10)[0]),
        ],
    )
    win = MainWindow(db_path=tmp_path / "items.db", source=stash, game=game_install)
    try:
        win.auto_absorb.setChecked(False)
        win._absorb_all()
        assert win.grid.count() == 3, "the three were not all absorbed"

        # A player who had narrowed the collection by hand, and is about to
        # click a set name: all of this is what the click switches off.
        win.sidebar.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
        win.filters.chips["Unique"].setChecked(True)
        win.filters.search.setText("Edge")
        assert win.grid.count() == 1, "the narrowing did not narrow"

        # The gesture itself, on the card: the set's name, which is a link
        # there and a bare word in the comparison overlay.
        names = win.grid.findChildren(LinkLabel)
        assert [name.word() for name in names] == ["Test Set"]
        win.show()
        qapp.processEvents()
        QTest.mouseClick(names[0], Qt.MouseButton.LeftButton)

        assert win.filters.shown_set() == "Test Set"
        assert win.filters.search_text() == ""
        assert win.filters.tiers() == set()
        assert win.filters.level_range() == (0, LEVEL_MAX)
        assert win.sidebar.places() == set(), "the rail was left ticked"
        assert win.filters.set_chip.isVisible()
        assert win.filters.set_chip.text() == "Test Set  ✕"
        assert [row.name for row in win.grid.rows()] == [
            "Test Set Blade",
            "Test Set Edge",
        ], "the wall is not the set"
        assert "showing every piece of Test Set" in win.status.currentMessage()

        # And the chip is the way back: the whole collection again, with the
        # item that is in no set back on the wall.
        win.filters.set_chip.click()
        assert win.filters.shown_set() == ""
        assert not win.filters.set_chip.isVisible()
        assert win.grid.count() == 3
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
