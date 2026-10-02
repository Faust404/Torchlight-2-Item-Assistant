"""Every copy of one item, side by side, and the one you send back.

A tile is one *item* however many rolls of it the tool holds -- that is what
makes the collection readable, and it is also the one thing it cannot say.
Two copies of a unique are the same card with two different sets of numbers,
and *which numbers* is the whole reason a player keeps both: this one has the
resistance, that one has the damage.  So the tile's footer carries the way in
(:class:`~app.tiles.ItemTile`) and this is what opens: the reference tool's
own screen, a card per copy, each with the one button that sends that copy
back to the game.

The difference from the collection is exactly that: a tile answers for every
copy at once and this answers for one.  A copy is its own fingerprint, because
a fingerprint is a hash of an item's bytes and two rolls are two items -- so
the cards here are built one per copy, and the button means the copy it is
under rather than the group.

It is a panel over the window rather than a window of its own, and it is not
the whole window either.  A second window can be lost behind the game; a
screen that replaced the collection would be a screen you have to leave to see
what you were comparing against.  So the window stays where it is, dimmed by a
backdrop, and the panel sits inside that backdrop with the window showing
round the edges -- the reference's own shape, and the one that keeps saying
that the collection is under here.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QFrame,
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
    PANEL,
    STYLE,
    Hairline,
    IconCache,
)
from .tiles import MARGIN, TILE_WIDTH, CardFrame, CardWall, TileRow

__all__ = ["CompareOverlay", "ReplicaCard", "inset_for"]

#: The overlay's own rules, over the card's.  A copy is drawn as a tile is --
#: a card in a panel with a footer under it -- but the panel is the same
#: colour as the ground it sits on, which is what tells the two walls apart:
#: the collection's cards are things you pick up, and these are one thing
#: already picked, spread out.
_STYLE = STYLE + f"""
#cpanel {{
    background-color: {PANEL};
    border: 1px solid {LINE};
    border-radius: 4px;
}}
#replica {{
    background-color: {GROUND};
    border: 1px solid {LINE};
    border-radius: 4px;
}}
#replica #card {{ background: transparent; border: 0; border-radius: 0; }}
/* The same button the collection draws, and deliberately: what it does is the
   same thing, and the two are the same word for it -- a copy of an item goes
   back to the stash it came from. */
#transfer {{
    color: {LABEL};
    background: transparent;
    border: 1px solid {DIV};
    border-radius: 3px;
    padding: 2px 8px;
    font-size: 11px;
}}
#transfer:hover {{ color: {HEAD}; border-color: {HEAD}; }}
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

#: What the backdrop is painted in: the darkest colour in the window, at seven
#: tenths.  Dark rather than black, because the cards on the panel are drawn
#: on a near-black ground of their own and a backdrop that matched it would
#: leave the panel with no edge; seven tenths rather than solid, because the
#: collection is still there -- its own ground is nearly this dark, so what
#: shows through is its cards and their words rather than a shape, which is
#: what a dimmed window looks like.
SCRIM = (12, 11, 10, 178)

#: How far the panel's edge sits inside the window's: a share of the window's
#: shorter side, and a floor under it.  The share is what keeps the panel from
#: being the window again on a large screen, and the floor is what keeps it a
#: panel rather than a sliver on a small one -- a share of a small window is a
#: small fraction, and the numbers in a card do not shrink with the window.
INSET = 0.06
MIN_INSET = 24


def inset_for(width: int, height: int) -> int:
    """How far the panel's edge sits inside a window of this size."""
    return max(MIN_INSET, round(min(width, height) * INSET))


class ReplicaCard(CardFrame):
    """One copy of an item, drawn whole, with the one button that returns it.

    A copy is not the item: two copies of a unique have two sets of numbers,
    and the card under the button is the copy's own.  That is the whole of what
    tells one replica from another on this screen, and it is why each is built
    from its own bytes -- the button sends back the copy it is under, and the
    card above it is that copy.
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

        button = QPushButton("Transfer to Stash")
        button.setObjectName("transfer")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(
            "Return this copy to the shared stash, where the game will pick it\n"
            "up on its next load.  The other copies are left where they are."
        )
        button.clicked.connect(lambda: self.put_back.emit(self.row.fingerprint))
        row.addStretch(1)
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


class Panel(QFrame):
    """The panel itself: the title, the way out, and the copies on the wall.

    A ``QFrame`` rather than a plain ``QWidget`` because it is a *styled*
    widget -- the sheet gives it a ground and an edge, and a plain widget has
    nothing to draw either with.
    """

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        """A press on the panel is not a press on the ground behind it.

        The backdrop closes the screen, which is what every pop-up does, and
        the way it knows a click was the backdrop's is that the click reached
        it: a widget that ignores a press passes it up to its parent.  So the
        panel takes its own presses here -- a click on the title, on the strip
        beside it, on the empty half of a card -- and the backdrop keeps only
        the presses that were actually aimed at it.
        """
        event.accept()


class CompareOverlay(QWidget):
    """The copies of one item over the window, each with its own Transfer.

    The overlay is a child of the window rather than a window of its own: it
    covers what it is about, follows its parent's size while it is up, and
    puts the panel inside itself at :func:`inset_for`.  Clicking the backdrop
    or pressing Esc puts it away.  What it emits is one fingerprint -- the
    copy someone decided to send back -- and what the window does with it is
    the window's business, as with every other action here.
    """

    #: A copy to put back, by fingerprint.
    put_back = Signal(str)

    def __init__(self, icons: IconCache | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("compare")
        self._cards: list[ReplicaCard] = []
        self._icons = icons

        # The backdrop, painted rather than styled: a plain QWidget is not a
        # styled widget, so a `background` rule here would draw nothing.
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(*SCRIM))
        self.setPalette(palette)

        self._panel = self._build_panel()
        self._inset = QVBoxLayout(self)
        self._inset.setSpacing(0)
        self._inset.addWidget(self._panel)

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
            self._fit()
        self.raise_()
        self.show()
        self.setFocus()

    def panel(self) -> QWidget:
        """The panel, which is everything the backdrop is not."""
        return self._panel

    def wall(self) -> CardWall:
        """The cards' wall, which scrolls when there are more than fit."""
        return self._wall

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

    def _build_panel(self) -> Panel:
        """The panel, its header and the wall the copies go on."""
        panel = Panel()
        panel.setObjectName("cpanel")
        # On the panel rather than on the wall, so that the sheet reaches the
        # title and the close button too -- they are the panel's, not the
        # wall's, and a sheet set on a widget stops at its children.
        panel.setStyleSheet(_STYLE)

        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._header())
        column.addWidget(Hairline())

        self._wall = CardWall()
        column.addWidget(self._wall, stretch=1)
        return panel

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

    def _fit(self) -> None:
        """Cover the window, and put the panel inside that at its inset.

        Both halves are the same act: the backdrop has to be the window's own
        size or the panel would be measured against a rectangle that is not
        what is on screen, and the inset is a margin *inside* the backdrop
        rather than a geometry worked out from it -- which is what makes the
        panel follow a resize without anything recomputing where it goes.
        """
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        margin = inset_for(parent.width(), parent.height())
        self._inset.setContentsMargins(margin, margin, margin, margin)

    # -- the mouse and the keyboard --------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        """A click on the backdrop, which is everything outside the panel.

        Reaching here at all is the test: the panel and the cards on it take
        their own presses, so what arrives is a click on the part of the
        window the panel is not covering -- which is the part that says the
        player is done looking.
        """
        self.dismiss()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 -- Qt naming
        """Keep covering the window, and keep the panel pinned inside it, when
        the window changes size."""
        if event.type() == QEvent.Type.Resize and watched is self.parentWidget():
            self._fit()
        return super().eventFilter(watched, event)
