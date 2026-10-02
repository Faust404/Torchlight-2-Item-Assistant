"""Every copy of one item, side by side, and the one you put back.

A tile is one *item* however many rolls of it the tool holds -- that is what
makes the collection readable, and it is also the one thing it cannot say.
Two copies of a unique are the same card with two different sets of numbers,
and *which numbers* is the whole reason a player keeps both: this one has the
resistance, that one has the damage.  So the tile's footer carries the way in
(:class:`~app.tiles.ItemTile`) and this is what opens: the reference tool's
own screen, a card per copy over the window, each with the one button that
sends that copy back to the game.

The difference from the collection is exactly that: a tile answers for every
copy at once and this answers for one.  A copy is its own fingerprint, because
a fingerprint is a hash of an item's bytes and two rolls are two items -- so
the cards here are built one per copy, and "Put back" means the one under the
pointer rather than the group.

It is an overlay rather than a window because it is about the collection it
covers: a second window can be lost behind the game, and what is being
compared is the thing that was just clicked.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .card import (
    BODY,
    DIM,
    DIV,
    GROUND,
    HEAD,
    LABEL,
    LINE,
    STYLE,
    IconCache,
)
from .tiles import MARGIN, TILE_WIDTH, CardFrame, CardWall, TileRow

__all__ = ["CompareOverlay", "ReplicaCard"]

#: The overlay's own rules, over the card's.  A copy is drawn as a tile is --
#: a card in a panel with a footer under it -- but the panel is the same
#: colour as the ground it sits on, which is what tells the two walls apart:
#: the collection's cards are things you pick up, and these are one thing
#: already picked, spread out.
_STYLE = STYLE + f"""
#replica {{
    background-color: {GROUND};
    border: 1px solid {LINE};
    border-radius: 4px;
}}
#replica #card {{ background: transparent; border: 0; border-radius: 0; }}
#found {{ color: {DIM}; font-size: 11px; }}
#putback {{
    color: {LABEL};
    background: transparent;
    border: 1px solid {DIV};
    border-radius: 3px;
    padding: 2px 8px;
    font-size: 11px;
}}
#putback:hover {{ color: {HEAD}; border-color: {HEAD}; }}
#ctitle {{
    color: {BODY};
    font-size: 15px;
    font-weight: 600;
    padding-left: 2px;
}}
#cclose {{
    color: {DIM};
    background: transparent;
    border: 0;
    font-size: 15px;
    padding: 2px 8px;
}}
#cclose:hover {{ color: {HEAD}; }}
"""

#: How far the overlay's own ground is lifted off the window behind it.  It
#: covers the whole window, so it *is* the ground while it is up; the lift is
#: what keeps it from reading as the same surface with different cards on it.
SCRIM = "#0c0b0a"


class ReplicaCard(CardFrame):
    """One copy of an item, drawn whole, with the one button that returns it.

    A copy is not the item: two copies of a unique have two sets of numbers,
    and the card under the button is the copy's own.  The place it was last
    seen in the game is in the footer because that is what the collection
    cannot say either -- its tile says the first copy's place, and this says
    each one's.
    """

    #: The copy to put back, by fingerprint.
    put_back = Signal(str)

    def __init__(
        self, row: TileRow, icons: IconCache | None = None, parent=None
    ) -> None:
        super().__init__(row, icons, parent)
        self.setObjectName("replica")
        self.setMinimumWidth(TILE_WIDTH)

    def _footer(self) -> QWidget:
        foot = QWidget()
        row = QHBoxLayout(foot)
        row.setContentsMargins(13, 6, 13, 7)
        row.setSpacing(8)

        found = QLabel(self.row.found)
        found.setObjectName("found")
        row.addWidget(found)
        row.addStretch(1)

        button = QPushButton("Put back")
        button.setObjectName("putback")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(
            "Return this copy to the shared stash, where the game will pick it\n"
            "up on its next load.  The other copies are left where they are."
        )
        button.clicked.connect(lambda: self.put_back.emit(self.row.fingerprint))
        row.addWidget(button)
        return foot

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        """A card is not the ground, so a click on one must not close the screen.

        Nothing inside the frame handles a press -- the card, its labels, its
        rules all ignore it -- so Qt walks up to the nearest widget that takes
        it, which without this is the overlay, and a click on a card someone
        was reading would put the screen away.  Taking it here stops the walk,
        and does nothing else: the values on the card are text, and text does
        not act.
        """
        event.accept()


class CompareOverlay(QWidget):
    """The copies of one item over the window, each with its own Put back.

    The overlay is a child of the window rather than a window of its own, and
    it covers what it is about: it follows its parent's size while it is up,
    and clicking the ground or pressing Esc puts it away.  What it emits is
    one fingerprint -- the copy someone decided to send back -- and what the
    window does with it is the window's business, as with every other action
    here.
    """

    #: A copy to put back, by fingerprint.
    put_back = Signal(str)

    def __init__(self, icons: IconCache | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("compare")
        self._cards: list[ReplicaCard] = []
        self._icons = icons

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._header())

        self._wall = CardWall()
        self._wall.setStyleSheet(_STYLE)
        column.addWidget(self._wall, stretch=1)

        # The ground, painted rather than styled: a plain QWidget is not a
        # styled widget, so a `background` rule here would draw nothing.
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(SCRIM))
        self.setPalette(palette)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setVisible(False)

    # -- opening and closing ---------------------------------------------

    def open_for(self, rows) -> None:
        """Show one card per copy, over the window."""
        self._clear()
        self._cards = [ReplicaCard(row, self._icons) for row in rows]
        for card in self._cards:
            card.put_back.connect(self.put_back)
        self._wall.set_cards(self._cards)

        parent = self.parentWidget()
        if parent is not None:
            parent.installEventFilter(self)
            self.setGeometry(parent.rect())
        self.raise_()
        self.show()
        self.setFocus()

    def dismiss(self) -> None:
        """Put the window back the way it was."""
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        self.hide()

    def drop(self, print_: str) -> None:
        """Take one copy's card down; the overlay closes when the last goes.

        Called after the copy has gone back to the game: the card is a thing
        the tool no longer holds, and leaving it up would leave a button that
        puts back what is already there.
        """
        for card in list(self._cards):
            if card.row.fingerprint == print_:
                self._cards.remove(card)
                self._wall.forget(card)
        self._wall.set_cards(self._cards)
        if not self._cards:
            self.dismiss()

    def cards(self) -> list[ReplicaCard]:
        """The copies on show, in the order they were given."""
        return list(self._cards)

    # -- the pieces ------------------------------------------------------

    def _header(self) -> QWidget:
        head = QWidget()
        row = QHBoxLayout(head)
        row.setContentsMargins(MARGIN + 4, 9, MARGIN + 4, 9)
        row.setSpacing(8)

        title = QLabel("Item Comparison")
        title.setObjectName("ctitle")
        row.addWidget(title)
        row.addStretch(1)

        # The multiplication sign, which is what a close button is drawn as in
        # every window there is.  Qt has no such character in its standard
        # icons, so it is the character itself.
        close = QPushButton("✕")
        close.setObjectName("cclose")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("Close (Esc)")
        close.clicked.connect(self.dismiss)
        row.addWidget(close)
        return head

    def _clear(self) -> None:
        for card in self._cards:
            self._wall.forget(card)
        self._cards = []

    # -- the mouse and the keyboard --------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        """A click on the ground, which is everything the cards do not cover.

        The header and the wall are children, and a widget that does not
        handle a press passes it to its parent -- so a click on the title, or
        beside it, arrives here and puts the overlay away, which is what every
        tool with an overlay does.
        """
        self.dismiss()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 -- Qt naming
        """Keep covering the window when the window changes size."""
        if event.type() == QEvent.Type.Resize and watched is self.parentWidget():
            self.setGeometry(watched.rect())
        return super().eventFilter(watched, event)
