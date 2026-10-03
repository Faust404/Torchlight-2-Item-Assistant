"""Tests for the wall of cards: the tile, its footer and the grid of them.

What a card *says* is ``tests/test_app_card.py``; this is what holds one.  The
two properties worth testing here are the two the design turns on: a tile is
the card itself rather than a summary of it, and a poll that changed nothing
redraws nothing.

Nothing here is shown on a screen.  Qt lays a widget out only once it has been
sized, so the tests that are about the flow show the grid -- under the offscreen
platform, which is a real layout pass with no window behind it.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Before the first PySide6 import, like tests/test_app.py.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 is not installed")

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from app.card import BODY, LABEL, PANEL, ItemCard  # noqa: E402
from app.theme import CHALK, PALE, WALL  # noqa: E402
from app.tiles import (  # noqa: E402
    GAP,
    MARGIN,
    TILE_WIDTH,
    ItemTile,
    TileGrid,
    TileRow,
)
from tl2stash.card import AFFIX, Block, Card, lines  # noqa: E402

from test_app_card import card  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session; Qt allows no more."""
    app = QApplication.instance() or QApplication([])
    yield app


def texts(drawn, name: str) -> list[str]:
    return [
        label.text()
        for label in drawn.findChildren(QLabel)
        if label.objectName() == name
    ]


def row(
    held: "Card | str",
    *,
    fingerprint: str = "fp-1",
    members: tuple[str, ...] | None = None,
    stranded: bool = False,
) -> TileRow:
    """A tile's worth of one item, with the fields a test is not about filled."""
    return TileRow(
        fingerprint=fingerprint,
        name=held.name if isinstance(held, Card) else "Broken",
        members=members if members is not None else (fingerprint,),
        card=held,
        stranded=stranded,
    )


def wall(grid: TileGrid, rows, width: int = 0) -> None:
    """Fill the grid and lay it out, at a width when one matters."""
    grid.set_rows(rows)
    if width:
        grid.resize(width, 600)
    grid.show()
    QApplication.processEvents()


# --------------------------------------------------------------------------
# The tile
# --------------------------------------------------------------------------


def test_a_tile_is_the_card_itself_rather_than_a_summary_of_one(qapp):
    """The decision the whole layout turns on.

    A card is what the player recognises an item by, so a tile draws the card
    the pane used to -- same widget, same lines -- rather than a smaller
    version of it that could disagree with one.
    """
    held = card(
        blocks=(
            Block(AFFIX, ("Silence for 1 sec.",)),
        ),
        flavor="Drill it into their heads.",
    )
    tile = ItemTile(row(held))

    assert tile.findChild(ItemCard) is not None
    assert tile.text() == "\n".join(lines(held))


def test_an_item_that_will_not_parse_is_a_sentence_rather_than_a_card(qapp):
    """There is no tier to ink it with and no picture to draw, so the tile
    says what went wrong in the same place the card would have been."""
    tile = ItemTile(row("Could not read this item: not enough bytes"))

    assert tile.findChild(ItemCard) is None
    assert tile.text() == "Could not read this item: not enough bytes"
    assert texts(tile, "hint") == ["Could not read this item: not enough bytes"]


def test_a_tile_does_not_say_where_the_item_was(qapp):
    """The tab and the slot are the game's fact about a stash this item is no
    longer in.  A card here says what the item *is*; where it goes back to is
    decided when it goes -- see
    :meth:`tl2stash.service.ItemService.first_slot` -- and not read off the
    card that is waiting to be sent."""
    tile = ItemTile(row(card()))
    labels = tile.findChildren(QLabel)

    assert "found" not in {label.objectName() for label in labels}
    assert not any("slot" in label.text().lower() for label in labels)


def button_label(tile, name: str) -> str | None:
    """What one of a tile's buttons says, with Qt's escape for an ampersand
    undone, or ``None`` when the tile has no such button.

    One ``&`` in a button's text marks the letter after it as a keyboard
    shortcut and is not drawn, so a literal one is written twice -- and the
    doubled form is what ``text()`` reports.
    """
    button = tile.findChild(QPushButton, name)
    return None if button is None else button.text().replace("&&", "&")


def test_one_copy_is_one_button_that_sends_it_back(qapp):
    """A comparison of one copy with itself is not worth a screen, so the
    single copy's card does not offer one: its whole action is the way back,
    which is the same act the overlay would have taken two clicks for.

    And that button is the whole of the footer: one of something has one thing
    to do with it, and a corner saying so would be the same word twice.
    """
    one = ItemTile(row(card()))

    assert one.row.copies == 1
    assert button_label(one, "compare") is None, "one copy offered a comparison"
    assert button_label(one, "transfer") == "Transfer to Stash"
    assert button_label(one, "transferall") is None
    assert texts(one, "found") == []


def test_several_copies_count_themselves_and_take_the_corner(qapp):
    """Two is the case the player has to be told about, because the card is
    both of them at once and the overlay is where they come apart.  The count
    goes on the button that acts on all of them, in the corner the single
    copy's footer leaves empty, and the way in sits across from it."""
    two = ItemTile(row(card(), members=("fp-1", "fp-2")))

    assert two.row.copies == 2
    assert button_label(two, "transferall") == "Transfer all (2)"
    assert button_label(two, "compare") == "Compare & Transfer"
    assert button_label(two, "transfer") is None
    assert texts(two, "found") == []


def test_the_footer_button_hands_the_tile_s_row_up(qapp):
    """Which button was pressed is the tile's to say and the window's to act
    on: what goes up is the row, and the row says how many copies it is."""
    one = ItemTile(row(card()))
    asked = []
    one.transfer.connect(asked.append)
    one.findChild(QPushButton, "transfer").click()

    two = ItemTile(row(card(), members=("fp-1", "fp-2")))
    two.transfer.connect(asked.append)
    two.findChild(QPushButton, "transferall").click()

    assert [len(r.members) for r in asked] == [1, 2]


def test_the_same_row_drawn_again_touches_nothing(qapp):
    """Tiles are compared before they are redrawn: a poll that changed nothing
    must not rebuild a hundred widgets per card."""
    held = row(card())
    tile = ItemTile(held)
    built = tile.findChild(ItemCard)

    tile.set_row(held)
    assert tile.findChild(ItemCard) is built


def test_a_row_that_changed_is_redrawn_in_place(qapp):
    """Same item, another copy of it: the card is the same card and the count
    is not -- and the selection must survive the redraw."""
    held = row(card())
    tile = ItemTile(held)
    tile.set_selected(True)

    tile.set_row(replace(held, members=("fp-1", "fp-2")))

    # A second copy is a different *footer*, not just different words in it:
    # the count arrives on its own button.
    assert button_label(tile, "transferall") == "Transfer all (2)"
    assert button_label(tile, "compare") == "Compare & Transfer"
    assert tile.is_selected()


def test_a_stranded_card_offers_only_the_way_to_keep_it(qapp):
    """A card with nowhere to go gets the one button that says so.

    Every other card's footer is a way back to the game.  A stranded item has
    none -- no file holds it -- so what is offered instead is the only true
    thing left to do with it: keep it.  And that is the whole footer: the
    count and the comparison are both about copies the game might have, and
    the game has none of this one.
    """
    gone = ItemTile(row(card(), stranded=True))

    assert button_label(gone, "recover") == "Recover Stranded Item"
    assert button_label(gone, "transfer") is None
    assert button_label(gone, "transferall") is None
    assert button_label(gone, "compare") is None


def test_the_recover_button_hands_the_tile_s_row_up(qapp):
    """Like the transfer buttons, and for the same reason: the tile says
    which row was clicked and the window decides what recovering means."""
    tile = ItemTile(row(card(), stranded=True))
    asked = []
    tile.recover.connect(asked.append)

    tile.findChild(QPushButton, "recover").click()

    assert [r.stranded for r in asked] == [True]


def test_a_card_that_becomes_stranded_exchanges_its_footer(qapp):
    """The same item one save later, when the game's save has erased it.

    Nothing about the card changes -- same fingerprint, same name, same
    picture -- and everything about what can be done with it does.  So the
    flag is a field of the row rather than a second kind of tile: the tile
    that was already drawn for this item is the tile that gets redrawn.
    """
    held = row(card())
    tile = ItemTile(held)
    assert button_label(tile, "transfer") == "Transfer to Stash"

    tile.set_row(replace(held, stranded=True))

    assert button_label(tile, "transfer") is None
    assert button_label(tile, "recover") == "Recover Stranded Item"


# --------------------------------------------------------------------------
# The grid
# --------------------------------------------------------------------------


def test_the_grid_draws_one_tile_per_row_in_order(qapp):
    grid = TileGrid()
    rows = [row(card(name=f"Item {i}"), fingerprint=f"fp{i}") for i in range(3)]
    wall(grid, rows)

    assert grid.count() == 3
    assert grid.rows() == rows
    assert [grid.tile(i).row.fingerprint for i in range(3)] == ["fp0", "fp1", "fp2"]


def test_a_row_list_that_did_not_change_rebuilds_nothing(qapp):
    """The property the whole poll depends on, at the grid's level.

    Rows are frozen records, so an unchanged list is an unchanged value and the
    grid returns without touching a widget -- the tiles, and the cards inside
    them, are the same objects they were.
    """
    grid = TileGrid()
    rows = [row(card(name=f"Item {i}"), fingerprint=f"fp{i}") for i in range(3)]
    wall(grid, rows)
    built = [grid.tile(i) for i in range(3)]

    grid.set_rows(list(rows))

    assert all(grid.tile(i) is built[i] for i in range(3))


def test_only_the_tile_whose_row_changed_is_redrawn(qapp):
    """One item gained a copy; the other two are the same two cards."""
    grid = TileGrid()
    rows = [row(card(name=f"Item {i}"), fingerprint=f"fp{i}") for i in range(3)]
    wall(grid, rows)
    built = [grid.tile(i) for i in range(3)]

    grid.set_rows([rows[0], replace(rows[1], members=("fp1", "fp1b")), rows[2]])

    assert grid.tile(0) is built[0]
    assert grid.tile(2) is built[2]
    assert grid.tile(1) is built[1], "the tile was not pooled by fingerprint"
    assert button_label(grid.tile(1), "transferall") == "Transfer all (2)"


def test_a_tile_whose_item_is_gone_leaves_the_wall(qapp):
    """Filtered out, or put back: the card is not on screen any more, so
    nothing about it may still be selected."""
    grid = TileGrid()
    rows = [row(card(name=f"Item {i}"), fingerprint=f"fp{i}") for i in range(3)]
    wall(grid, rows)
    grid.select_row(1)

    grid.set_rows([rows[0], rows[2]])

    assert grid.count() == 2
    assert [grid.tile(i).row.fingerprint for i in range(2)] == ["fp0", "fp2"]
    assert grid.selected() == [], "a tile that left took its selection with it"


def test_the_wall_says_when_it_has_nothing_to_show(qapp):
    grid = TileGrid()
    grid.set_rows([], empty="Nothing here yet.")
    empty = grid.findChild(QLabel, "empty")

    assert empty.text() == "Nothing here yet."
    assert not empty.isHidden()

    wall(grid, [row(card())], width=600)
    assert empty.isHidden(), "the message stayed up over a card"


def test_the_wall_draws_the_cards_on_a_ground_darker_than_they_are(qapp):
    """The tool's half of the window is the one that goes below the cards.

    A card is the same object in both panes -- the game's stash and the tool --
    so the panes cannot differ in what they put on a card; they differ in what
    a card is put on, and the tool's ground is the darker one, which is what
    makes an item here read as a card in a drawer.

    Read off the drawn pixel rather than off a palette, because a palette is
    where this went wrong: the wall asked for its ground in one and Qt took it
    back off at the next polish, which nothing could see while the colour it
    asked for was the colour the window already was.
    """
    grid = TileGrid()
    wall(grid, [row(card())], width=600)

    # The wall's own margin, which is a strip of its ground with no card on it.
    assert grid.grab().toImage().pixelColor(4, 4).name() == WALL
    assert QColor(WALL).lightness() < QColor(PANEL).lightness(), "not below a card"


def test_the_footer_buttons_are_the_window_s_light_let_down_a_step(qapp):
    """What the tile's one control is drawn in, and what it is drawn *against*.

    The card under the footer is the site's and does not move; the button on it
    is the tool's, and it was drawn in the card's own label tan -- a colour the
    card spends on a *note*, which is what an 11px button beside a cardful of
    lifted numbers read as.  So it takes the window's treatment for a control
    one step down: :data:`app.theme.PALE`, the ink the rail's boxes and the
    filter boxes are outlined in (:data:`app.theme.CHALK`) let down far enough
    not to be glare on every card of a wall.

    Read both ways, because the ink and the outline are one colour here: the
    sheet is what was asked for and the drawn edge is what arrived -- a sheet
    that never reached the button would leave it looking exactly as it did,
    which is how the wall's own ground went wrong once already.
    """
    grid = TileGrid()
    wall(grid, [row(card())], width=600)
    sheet = grid.styleSheet()

    assert f"color: {PALE}" in sheet
    assert f"border: 1px solid {PALE}" in sheet, "the outline is the same light"
    # The claim is the whole of it -- lighter than the tan it replaces, lighter
    # than the body text beside it, and below the window's own control ink.
    assert QColor(PALE).lightness() > QColor(LABEL).lightness()
    assert QColor(PALE).lightness() > QColor(BODY).lightness()
    assert QColor(PALE).lightness() < QColor(CHALK).lightness()

    button = grid.tile(0).findChild(QPushButton, "transfer")
    rect = QRect(button.mapTo(grid, button.rect().topLeft()), button.size())
    image = grid.grab().toImage()

    # The outline's own pixel, on the button's left edge at its middle -- clear
    # of the rounded corners, which are the only place it is drawn over.
    assert image.pixelColor(rect.left(), rect.center().y()).name() == PALE, (
        "the button was not drawn in the ink the sheet asks for"
    )


def test_a_card_fills_its_column_rather_than_floating_in_one(qapp):
    """The reference's own grid, and the reason ``TILE_WIDTH`` is a floor.

    A card of a fixed width centred in its column leaves a gutter twice the
    width of the gap on either side of it, and a wall of four cards on a wide
    window reads as half empty.  Here the columns share the window and the
    cards fill them, so what a wider window buys is wider cards.
    """
    grid = TileGrid()
    rows = [row(card(name=f"Item {i}"), fingerprint=f"fp{i}") for i in range(2)]
    wall(grid, rows, width=2 * (TILE_WIDTH + GAP) + 2 * MARGIN + 100)

    assert grid.columns() == 2
    assert grid.tile(0).width() > TILE_WIDTH, "the card did not grow with its column"
    assert grid.tile(0).width() == grid.tile(1).width(), "the columns are not equal"
    # The second card starts where the first one ends, with only the gap
    # between them -- nothing is standing in a gutter.
    assert grid.tile(1).x() == grid.tile(0).x() + grid.tile(0).width() + GAP


def test_the_columns_come_from_the_width(qapp):
    """The window is any size and a card is a fixed one, so how many fit is a
    division.  Reflowing is the whole of the resize handling."""
    grid = TileGrid()
    rows = [row(card(name=f"Item {i}"), fingerprint=f"fp{i}") for i in range(6)]

    wall(grid, rows, width=3 * (TILE_WIDTH + GAP) + 2 * MARGIN)
    assert grid.columns() == 3
    assert grid.tile(3).y() > grid.tile(0).y(), "the fourth card did not wrap"

    grid.resize(2 * (TILE_WIDTH + GAP) + 2 * MARGIN, 600)
    QApplication.processEvents()
    assert grid.columns() == 2
    assert grid.tile(2).x() == grid.tile(0).x(), "the third card did not rewrap"
    # The stretch comes back off the column the narrower grid gave up: a
    # stretched column with no card in it holds a gap open in the wall.
    assert grid._grid.columnStretch(2) == 0


# --------------------------------------------------------------------------
# The selection
# --------------------------------------------------------------------------


def test_a_click_picks_a_card_and_a_ctrl_click_adds_another(qapp):
    """The selection is the grid's own, because the thing being clicked is a
    card rather than a model index."""
    grid = TileGrid()
    rows = [row(card(name=f"Item {i}"), fingerprint=f"fp{i}") for i in range(3)]
    wall(grid, rows)

    grid.tile(1).clicked.emit(Qt.KeyboardModifier.NoModifier)
    assert [r.fingerprint for r in grid.selected()] == ["fp1"]
    assert grid.tile(1).is_selected()

    grid.tile(2).clicked.emit(Qt.KeyboardModifier.ControlModifier)
    assert [r.fingerprint for r in grid.selected()] == ["fp1", "fp2"]

    # The same card again takes it back out, and the one under it stays.
    grid.tile(1).clicked.emit(Qt.KeyboardModifier.ControlModifier)
    assert [r.fingerprint for r in grid.selected()] == ["fp2"]
    assert not grid.tile(1).is_selected()


def test_a_shift_click_takes_everything_between(qapp):
    grid = TileGrid()
    rows = [row(card(name=f"Item {i}"), fingerprint=f"fp{i}") for i in range(4)]
    wall(grid, rows)

    grid.tile(1).clicked.emit(Qt.KeyboardModifier.NoModifier)
    grid.tile(3).clicked.emit(Qt.KeyboardModifier.ShiftModifier)

    assert [r.fingerprint for r in grid.selected()] == ["fp1", "fp2", "fp3"]


def test_a_plain_click_throws_the_rest_away(qapp):
    grid = TileGrid()
    rows = [row(card(name=f"Item {i}"), fingerprint=f"fp{i}") for i in range(3)]
    wall(grid, rows)

    grid.select_row(0)
    grid.select_row(1, add=True)
    assert len(grid.selected()) == 2

    grid.tile(2).clicked.emit(Qt.KeyboardModifier.NoModifier)
    assert [r.fingerprint for r in grid.selected()] == ["fp2"]

    grid.clear_selection()
    assert grid.selected() == []
    assert not any(grid.tile(i).is_selected() for i in range(3))


def test_a_card_stands_for_every_copy_of_its_item(qapp):
    """What a tile's members are for: the window puts back what the card says
    it is, and the card says it is all of them."""
    grid = TileGrid()
    rows = [row(card(name="Fortress of Fools"), fingerprint="fp0",
                members=("fp0", "fp0b"))]
    wall(grid, rows)

    grid.select_row(0)
    (chosen,) = grid.selected()
    assert chosen.members == ("fp0", "fp0b")
    assert chosen.copies == 2
    assert button_label(grid.tile(0), "transferall") == "Transfer all (2)"


def test_the_tile_s_buttons_hand_the_row_up_through_the_grid(qapp):
    """The tile does not act on anything itself: it says which row was asked
    for, and the grid passes that on the way it passes a click."""
    grid = TileGrid()
    wall(grid, [row(card(), members=("fp0", "fp0b"))])

    compared, transferred = [], []
    grid.compare.connect(compared.append)
    grid.transfer.connect(transferred.append)
    grid.tile(0).compare.emit(grid.tile(0).row)
    grid.tile(0).transfer.emit(grid.tile(0).row)

    assert [r.members for r in compared] == [("fp0", "fp0b")]
    assert [r.members for r in transferred] == [("fp0", "fp0b")]
