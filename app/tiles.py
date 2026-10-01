"""The collection as a wall of the game's own cards.

The reference tool shows a collection as a scrollable grid of whole item
cards, and that is the shape asked for: a thing is recognised by its picture
and its name, so a list of text is a list that has to be read, while a card is
a card at a glance.  This is that grid.

Two decisions are the whole of it.

A tile is not a *summary* of an item -- it is the card, the same
:class:`~app.card.ItemCard` the details pane used to draw, with a footer under
it saying where the thing was found and, when there is more than one, how many
copies of it the tool holds.  The pane that drew one card beside the table is
gone: with the cards in the grid there is nothing left for it to draw, and a
second drawing of the same item could only disagree with the first.

And a tile stands for an *item* rather than for one copy of it: the model
gathers the copies before they reach here (see
:func:`app.models.fill_collection`), and a row's ``members`` are every
fingerprint it stands for.  That is what turns a selection of a tile back into
the items it is made of -- the window restores exactly those -- and what makes
the copy count on the footer worth printing at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tl2stash.card import Card, lines

from .card import (
    DIM,
    GROUND,
    HEAD,
    LABEL,
    LINE,
    PANEL,
    STYLE,
    Hairline,
    IconCache,
    ItemCard,
)

__all__ = ["ItemTile", "TileGrid", "TileRow"]

#: The narrowest a card is drawn: the width its longest stat line needs before
#: it wraps.  It is a floor rather than a size -- the reference's cards fill
#: their columns and the columns share the window, so a wider window is wider
#: cards rather than wider gutters.
TILE_WIDTH = 340
#: Between two cards, and between two rows of them.
GAP = 8
#: Around the whole wall.
MARGIN = 10

#: The tile's rules, over the card's.  The card keeps its colours and its type;
#: the frame moves out one level, because what the frame marks is now the
#: *tile* -- which includes the footer, and the footer is not part of the card.
#: So the card inside a tile gives up its own edge, and the two rules are
#: written so that cannot depend on the order they are read in: ``#tile #card``
#: outranks ``#card`` by specificity, which is the one thing Qt's stylesheet
#: language shares with the web's.
_STYLE = STYLE + f"""
#tile {{
    background-color: {PANEL};
    border: 1px solid {LINE};
    border-radius: 4px;
}}
#tile[selected="true"] {{ border-color: {HEAD}; }}
#tile #card {{ background: transparent; border: 0; border-radius: 0; }}
#found {{ color: {DIM}; font-size: 11px; }}
#copies {{ color: {LABEL}; font-size: 11px; }}
#empty {{ color: {DIM}; font-size: 13px; padding: 6px; }}
"""


@dataclass(frozen=True)
class TileRow:
    """What one tile draws, and what it stands for.

    Frozen and therefore comparable: the grid tells a poll that changed
    something from a poll that changed nothing by comparing these, and rebuilds
    only the tiles whose row came back different.  So the fields are exactly
    what a tile puts on screen, and nothing that is not.

    ``members`` is every fingerprint the tile stands for -- the copies of one
    item, gathered by the model -- and ``copies`` is that count.  ``card`` is
    the built card, or the sentence that stands in for one when the item will
    not parse; both are shown, and only one of them is a card.
    """

    fingerprint: str
    name: str
    members: tuple[str, ...]
    found: str
    card: "Card | str"

    @property
    def copies(self) -> int:
        """How many of the tool's items this one tile is."""
        return len(self.members)


class ItemTile(QFrame):
    """One item, drawn as its card with a footer under it.

    The stretch between the card and the footer is what lines the footers up
    across a row: cards are as tall as their stats make them, and the grid
    gives every tile in a row the height of the tallest, so without it the
    shorter cards would float their footers up into the middle.
    """

    #: A left click, with the modifiers held while it happened.  The grid
    #: decides what a click *means*; a tile only says that it was clicked.
    clicked = Signal(object)

    def __init__(
        self, row: TileRow, icons: IconCache | None = None, parent=None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("tile")
        self.setMinimumWidth(TILE_WIDTH)
        self.row = row
        self._icons = icons
        self._selected = False

        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(0)
        self._fill()

    # -- what it says ----------------------------------------------------

    def set_row(self, row: TileRow) -> None:
        """Draw the same item as the tool now describes it.

        Another copy was absorbed, or this one was moved in the game: the
        fingerprint is the same and the card is the same, but the count and
        the place are not.  Everything else about the tile is kept, including
        whether it is selected.
        """
        if row == self.row:
            return
        self.row = row
        self._fill()

    def text(self) -> str:
        """What the tile reads back as: the card's lines, or the sentence.

        The same contract the details pane had, and for the same reason --
        what the tests read should be what the item says, not how the widgets
        that draw it happen to be arranged.
        """
        card = self.row.card
        return "\n".join(lines(card)) if isinstance(card, Card) else str(card)

    def set_selected(self, on: bool) -> None:
        if on == self._selected:
            return
        self._selected = on
        self.setProperty("selected", on)
        # Qt resolves a widget's stylesheet rules once and keeps them, so a
        # property that changes has to be re-resolved by hand.  This is the
        # documented dance, and skipping it is a border that never moves.
        self.style().unpolish(self)
        self.style().polish(self)

    def is_selected(self) -> bool:
        return self._selected

    # -- the pieces ------------------------------------------------------

    def _fill(self) -> None:
        self._clear()
        card = self.row.card
        if isinstance(card, Card):
            self._column.addWidget(ItemCard(card, self._icons))
        else:
            # An item that would not parse is a sentence rather than a card:
            # there is no tier to ink it with and no picture to draw.
            hint = QLabel(str(card))
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            hint.setContentsMargins(13, 12, 13, 12)
            self._column.addWidget(hint)

        self._column.addStretch(1)
        # Ruled off from the card above it, the way every other section is.
        self._column.addWidget(Hairline())
        self._column.addWidget(self._footer())

    def _footer(self) -> QWidget:
        foot = QWidget()
        row = QHBoxLayout(foot)
        row.setContentsMargins(13, 6, 13, 7)
        row.setSpacing(8)

        found = QLabel(self.row.found)
        found.setObjectName("found")
        row.addWidget(found)
        row.addStretch(1)

        if self.row.copies > 1:
            copies = QLabel(f"{self.row.copies} copies")
            copies.setObjectName("copies")
            row.addWidget(copies)
        return foot

    def _clear(self) -> None:
        while self._column.count():
            item = self._column.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    # -- the mouse -------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(event.modifiers())
            return
        super().mousePressEvent(event)


class TileGrid(QScrollArea):
    """The wall of cards, and which of them are selected.

    Tiles are pooled by fingerprint and only the ones whose row came back
    different are redrawn.  The window rebuilds this list on every save --
    every couple of seconds in play -- and a card is a hundred widgets, so a
    poll that changed nothing has to touch nothing.  That is the property the
    details pane was arranged around, and it is worth keeping: the memo is what
    makes the poll free.

    How many columns there are is worked out from the width rather than set:
    the window can be any size and a card is a fixed one, so it is a division.
    Reflowing is the whole of the resize handling, and it places only the tiles
    whose cell actually changed.

    The selection is the grid's own rather than a view's, because there is no
    view: the thing the player clicks is a card, and a card is not a model
    index.  It is a list of fingerprints, in the order they were added, which
    is what a multiple selection means here -- the window asks only *which
    ones*, and asks the rows for their members when it acts.
    """

    def __init__(self, icons: IconCache | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(_STYLE)

        self._icons = icons
        self._rows: list[TileRow] = []
        self._empty_text = ""
        #: Tiles by fingerprint -- the pool.  A tile outlives the row list it
        #: was built for as long as the item it draws is still here.
        self._pool: dict[str, ItemTile] = {}
        #: The tiles in grid order, which is the row order.
        self._order: list[ItemTile] = []
        self._selected: list[str] = []
        self._anchor: int | None = None
        self._columns = 0

        self._wall = QWidget()
        outer = QVBoxLayout(self._wall)
        outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        outer.setSpacing(GAP)

        self._empty = QLabel()
        self._empty.setObjectName("empty")
        self._empty.setWordWrap(True)
        outer.addWidget(self._empty)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(GAP)
        outer.addLayout(self._grid)
        outer.addStretch(1)
        self.setWidget(self._wall)

        # The ground behind the cards, which is darker than the cards -- the
        # site's own reason for the two being different colours.  A palette
        # rather than a stylesheet, because a `background` rule on a scroll
        # area does not reach its viewport, which is the widget that shows.
        for widget in (self.viewport(), self._wall):
            widget.setAutoFillBackground(True)
            palette = widget.palette()
            palette.setColor(QPalette.ColorRole.Window, QColor(GROUND))
            widget.setPalette(palette)

    # -- what it shows ---------------------------------------------------

    def set_rows(self, rows, empty: str = "") -> None:
        """Draw these tiles, in this order, or say why there are none.

        Called after every poll and every filter change.  The whole of the
        cheapness is the first comparison: rows are frozen records, so a poll
        that changed nothing returns here without touching a widget.
        """
        rows = list(rows)
        if rows == self._rows and empty == self._empty_text:
            return
        self._rows = rows
        self._empty_text = empty
        self._empty.setText(empty)
        self._empty.setVisible(not rows)

        wanted = {row.fingerprint for row in rows}
        for fingerprint in [f for f in self._pool if f not in wanted]:
            tile = self._pool.pop(fingerprint)
            self._grid.removeWidget(tile)
            tile.setParent(None)
            tile.deleteLater()

        self._order = []
        for row in rows:
            tile = self._pool.get(row.fingerprint)
            if tile is None:
                tile = ItemTile(row, self._icons)
                tile.clicked.connect(
                    lambda modifiers, t=tile: self._clicked(t, modifiers)
                )
                self._pool[row.fingerprint] = tile
            else:
                tile.set_row(row)
            self._order.append(tile)

        # A selection whose items have gone is not a selection.  An item that
        # left the tool -- put back, or filtered out -- takes its tile with it,
        # and "Put back selected" must not be armed by a card that is no
        # longer on screen.
        self._selected = [f for f in self._selected if f in wanted]

        self._reflow()
        self._paint_selection()

    def rows(self) -> list[TileRow]:
        return list(self._rows)

    def count(self) -> int:
        return len(self._order)

    def columns(self) -> int:
        return self._columns

    def tile(self, n: int) -> ItemTile:
        return self._order[n]

    # -- the selection ---------------------------------------------------

    def selected(self) -> list[TileRow]:
        """The selected tiles' rows, in grid order rather than click order.

        Grid order because that is the order the player sees them in, and the
        window's status line reads out of it.
        """
        chosen = set(self._selected)
        return [row for row in self._rows if row.fingerprint in chosen]

    def select_row(self, n: int, add: bool = False) -> None:
        """Select the tile at ``n``.  ``add`` keeps what was selected."""
        fingerprint = self._order[n].row.fingerprint
        if add:
            if fingerprint not in self._selected:
                self._selected.append(fingerprint)
        else:
            self._selected = [fingerprint]
        self._anchor = n
        self._paint_selection()

    def clear_selection(self) -> None:
        self._selected = []
        self._anchor = None
        self._paint_selection()

    def _clicked(self, tile: ItemTile, modifiers) -> None:
        """A card was clicked: plain picks it, ctrl adds it, shift spans."""
        index = self._order.index(tile)
        if modifiers & Qt.KeyboardModifier.ShiftModifier and self._anchor is not None:
            low, high = sorted((self._anchor, index))
            self._selected = [
                other.row.fingerprint for other in self._order[low : high + 1]
            ]
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            # A second click takes it back out, and the ones already selected
            # keep their places rather than being reordered under the player.
            fingerprint = tile.row.fingerprint
            chosen = [f for f in self._selected if f != fingerprint]
            if len(chosen) == len(self._selected):
                chosen.append(fingerprint)
            self._selected = chosen
            self._anchor = index
        else:
            self._selected = [tile.row.fingerprint]
            self._anchor = index
        self._paint_selection()

    def _paint_selection(self) -> None:
        chosen = set(self._selected)
        for tile in self._order:
            tile.set_selected(tile.row.fingerprint in chosen)

    # -- the flow --------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        """Put every tile in the cell its position in the list works out to.

        Unaligned on purpose, in both directions.  A tile that filled its cell
        horizontally is what makes the wall meet the window's edges rather than
        standing in the middle of a gutter, and one that filled it vertically
        is what lines the footers up along the bottom of a row -- the cards'
        own stats decide how tall each one is, and the row takes the tallest.
        """
        columns = self._columns_for(self.viewport().width())
        if columns != self._columns:
            # Every used column takes an equal share of what is left over, and
            # the stretch comes back off the ones a narrower grid abandoned --
            # a column left stretched would hold a gap where a card used to be.
            for column in range(max(columns, self._columns)):
                self._grid.setColumnStretch(column, 1 if column < columns else 0)
            self._columns = columns

        for i, tile in enumerate(self._order):
            where = (i // columns, i % columns)
            placed = self._grid.indexOf(tile)
            if placed >= 0 and self._grid.getItemPosition(placed)[:2] == where:
                continue
            if placed >= 0:
                self._grid.removeWidget(tile)
            self._grid.addWidget(tile, where[0], where[1])

    @staticmethod
    def _columns_for(width: int) -> int:
        """How many cards fit: the margin at each end, a gap between each pair."""
        return max(1, (width - 2 * MARGIN + GAP) // (TILE_WIDTH + GAP))
