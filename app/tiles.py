"""The collection as a wall of the game's own cards.

The reference tool shows a collection as a scrollable grid of whole item
cards, and that is the shape asked for: a thing is recognised by its picture
and its name, so a list of text is a list that has to be read, while a card is
a card at a glance.  This is that grid.

Two decisions are the whole of it.

A tile is not a *summary* of an item -- it is the card, the same
:class:`~app.card.ItemCard` the details pane used to draw, with a footer under
it saying how many copies of it the tool holds and what can be done with them.
The pane that drew one card beside the table is gone: with the cards in the
grid there is nothing left for it to draw, and a second drawing of the same
item could only disagree with the first.

And a tile stands for an *item* rather than for one copy of it: the model
gathers the copies before they reach here (see
:func:`app.models.fill_collection`), and a row's ``members`` are every
fingerprint it stands for.  That is what turns a selection of a tile back into
the items it is made of -- the window restores exactly those -- and what the
footer's buttons are drawn from: one copy sends itself back, and several
offer the whole group and the way in to tell them apart
(see :mod:`app.compare`).

The wall and the card frame are shared with that overlay, which is why they
are two classes here rather than one: what the collection draws and what the
comparison draws differ in their footers and in what a click means, and in
nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tl2stash.card import Card, lines

from .card import (
    DIM,
    HEAD,
    LINE,
    PANEL,
    STYLE,
    Hairline,
    IconCache,
    ItemCard,
)
from .theme import CHALK, PALE, WALL

__all__ = ["CardFrame", "CardWall", "ItemTile", "TileGrid", "TileRow"]

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
/* The footer is a control standing on a card, and it is drawn as one: the
   lightest thing on the card, in the window's own ink for a button on a card
   rather than the card palette's -- a card is the site's and does not move, but
   a button on one is the tool's.  Word and outline are the same light, and the
   hover is the one step above it, because the resting state is already light
   and a hover that dimmed would read as the button switching itself off. */
#compare, #transfer, #transferall, #transferstack, #transferone, #recover,
#remove {{
    color: {PALE};
    background: transparent;
    border: 1px solid {PALE};
    border-radius: 3px;
    padding: 2px 8px;
    font-size: 11px;
}}
#compare:hover, #transfer:hover, #transferall:hover, #transferstack:hover,
#transferone:hover, #recover:hover, #remove:hover {{
    color: {CHALK};
    border-color: {CHALK};
}}
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

    One copy of an item is a row too, and that is what the comparison overlay
    is handed: a row whose ``members`` are itself.  A copy differs from its
    fellows in its own bytes, so its fingerprint and its card are its own.

    Nothing here says where the item sat in the game.  The tool holds it, so a
    tab and a slot are a fact about a stash it is no longer in -- and it is
    the game that decides where a restored item lands.

    ``stranded`` is the one item the tool has that has no way back: it was put
    back, and the game's own save erased the write, so no file holds it -- see
    :meth:`tl2stash.service.ItemService.stranded_rows`.  It changes what the
    footer offers, which is why it is a field here and not a flag on the wall.

    ``stacks`` and ``stack_limit`` are the *pile*'s, and they are what makes a
    tile a pile rather than a handful of copies: the game holds five fish in a
    slot and no more, so a card reading ``x4`` stands for four fish the player
    wants to count in fish and send in slot-sized pieces.  ``stacks`` is the
    sizes of the stacks the tool holds, one entry per stack -- a 3-stack and a
    1-stack are ``(3, 1)``, and the card draws the sum -- and ``stack_limit``
    is the game's cap.  Both are defaulted, and both are empty for everything
    the game does not cap, so every other tile in the window is exactly what
    it was.
    """

    fingerprint: str
    name: str
    members: tuple[str, ...]
    card: "Card | str"
    stranded: bool = False
    stacks: tuple[int, ...] = ()
    stack_limit: int | None = None

    @property
    def copies(self) -> int:
        """How many of the tool's items this one tile is."""
        return len(self.members)

    @property
    def units(self) -> int:
        """How many *fish* the tile stands for, when it is a pile.

        The count the card draws and the buttons act on, and a different
        number from :attr:`copies`: the tool's copies of one fish are its
        stacks of it, and the player who has a 3-stack and a 1-stack has four
        fish, not two.
        """
        return sum(self.stacks)

    @property
    def is_a_pile(self) -> bool:
        """Whether the footer is the pile's rather than the copies'.

        More than one fish, and a kind the game caps: one fish is one button's
        worth of decision however the tool came by it, and a kind the game
        does not cap has no slots to divide it into.
        """
        return self.stack_limit is not None and self.units > 1

    @property
    def stack_size(self) -> int:
        """The size of the one stack ``Transfer a Stack`` would send.

        The largest stack the tool holds, or the game's cap off it when that
        is bigger -- a 20-stack from a modded game goes back five at a time.
        """
        assert self.stack_limit is not None
        return min(self.stack_limit, max(self.stacks))


class CardWall(QScrollArea):
    """Cards in a grid, in as many columns as the width has room for.

    The flow is the whole of this class, and it is shared: the collection
    draws a tile per item on it and the comparison overlay a card per copy.
    Neither owns it, because neither decides how many fit.

    How many columns there are is worked out from the width rather than set:
    the window can be any size and a card is a fixed one, so it is a division.
    Reflowing is the whole of the resize handling, and it places only the
    widgets whose cell actually changed -- a wall redrawn on every save cannot
    afford to move what has not moved.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        #: The widgets on the wall, in grid order.
        self._cards: list[QWidget] = []
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

        # The ground behind the cards: the window's own wall, which is darker
        # than a card -- see :data:`app.theme.WALL` for why the tool's half of
        # the window is the one that goes below the cards.
        #
        # A rule in a *sheet* rather than a colour in the widget's palette, and
        # that is not a preference.  Qt re-polishes a widget whenever a sheet
        # reaches it -- the grid sets one, and the window's theme is one -- and
        # a polish resolves a child's palette back to the one it inherits,
        # taking a palette set here off it.  This started out as a palette, and
        # it went unnoticed for as long as it did because the colour it asked
        # for was the colour it fell back to: the wall wanted the cards' ground
        # and the window *was* the cards' ground.  A sheet cannot be undone
        # that way, because a sheet is what a polish applies.
        #
        # ``WA_StyledBackground`` is what makes a plain widget draw a sheet's
        # background at all -- without it Qt draws nothing for a widget with no
        # frame of its own.  The viewport underneath is left to the theme: the
        # wall covers it, because a scroll area with a resizable widget resizes
        # that widget to at least the viewport, so the only thing its colour
        # ever shows through is a repaint one frame wide.
        self._wall.setObjectName("wall")
        self._wall.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._wall.setStyleSheet(f"#wall {{ background-color: {WALL}; }}")

    # -- what it shows ---------------------------------------------------

    def set_cards(self, cards, empty: str = "") -> None:
        """Draw these widgets, in this order, or say why there are none.

        The widgets are not built here and not destroyed here: a wall that
        pooled them would be a wall that had to know what they are, and the
        two walls that use this do not pool alike.
        """
        self._cards = list(cards)
        self._empty.setText(empty)
        self._empty.setVisible(not self._cards)
        self._reflow()

    def cards(self) -> list[QWidget]:
        return list(self._cards)

    def count(self) -> int:
        return len(self._cards)

    def card_at(self, n: int) -> QWidget:
        return self._cards[n]

    def columns(self) -> int:
        return self._columns

    def forget(self, card: QWidget) -> None:
        """Take one widget off the wall for good.

        Hidden *first*, then detached, then deleted.  ``setParent(None)``
        makes a widget parentless -- which is what a top-level window is --
        and Qt hides it on the way out only the way a parent hides a child:
        hidden, but not *explicitly*, which is the one state Qt's own
        deferred re-show (``QWidgetPrivate::_q_showIfNotHidden``) is written
        to undo.  Measured: a bare-detached tile comes back from that call as
        a visible window at its old cell, wearing the application's name --
        the white boxes in ``test/tl2ia_pop_up_error.png``.  Hidden first,
        the state is explicit, and nothing shows it again.
        """
        self._grid.removeWidget(card)
        card.hide()
        card.setParent(None)
        card.deleteLater()

    # -- the flow --------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        """Put every card in the cell its position in the list works out to.

        Unaligned on purpose, in both directions.  A card that filled its cell
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

        for i, card in enumerate(self._cards):
            where = (i // columns, i % columns)
            placed = self._grid.indexOf(card)
            if placed >= 0 and self._grid.getItemPosition(placed)[:2] == where:
                continue
            if placed >= 0:
                self._grid.removeWidget(card)
            self._grid.addWidget(card, where[0], where[1])

    @staticmethod
    def _columns_for(width: int) -> int:
        """How many cards fit: the margin at each end, a gap between each pair."""
        return max(1, (width - 2 * MARGIN + GAP) // (TILE_WIDTH + GAP))


class CardFrame(QFrame):
    """One item drawn as its own card, with a footer under it.

    The card is :class:`~app.card.ItemCard`, or -- for an item that will not
    parse -- the sentence saying so in its place; the footer is the
    subclass's, because what goes in it is the one thing the two walls
    disagree about.

    The stretch between the card and the footer is what lines the footers up
    across a row: cards are as tall as their stats make them, and the grid
    gives every card in a row the height of the tallest, so without it the
    shorter cards would float their footers up into the middle.
    """

    #: A click on the card's set name, with the name that was clicked.
    set_chosen = Signal(str)
    #: Whether that name is a link.  False here and True on :class:`ItemTile`,
    #: which is the difference between the two walls: in the collection a
    #: click takes the player to the rest of the set, and in the comparison
    #: there is nowhere to take them -- the overlay is already showing every
    #: copy of the one item, and the name of its set is a fact about it rather
    #: than a way out.
    LINKS_SETS = False

    def __init__(
        self, row: TileRow, icons: IconCache | None = None, parent=None
    ) -> None:
        super().__init__(parent)
        self.row = row
        self._icons = icons

        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(0)
        self._fill()

    def text(self) -> str:
        """What the card reads back as: the item's lines, or the sentence.

        The same contract the details pane had, and for the same reason --
        what the tests read should be what the item says, not how the widgets
        that draw it happen to be arranged.
        """
        card = self.row.card
        return "\n".join(lines(card)) if isinstance(card, Card) else str(card)

    def _fill(self) -> None:
        self._clear()
        card = self.row.card
        if isinstance(card, Card):
            drawn = ItemCard(card, self._icons, links_sets=self.LINKS_SETS)
            # Connected either way: a card that was not asked to link its set
            # name has nothing to emit, and one that was is this frame's to
            # pass on.
            drawn.set_clicked.connect(self.set_chosen)
            self._column.addWidget(drawn)
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
        raise NotImplementedError

    def _clear(self) -> None:
        while self._column.count():
            item = self._column.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Hidden before the detach, so the state is explicit:
                # see CardWall.forget.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()


class ItemTile(CardFrame):
    """One item, drawn as its card with a footer under it."""

    #: A left click, with the modifiers held while it happened.  The grid
    #: decides what a click *means*; a tile only says that it was clicked.
    clicked = Signal(object)
    #: The ``Compare & Transfer`` button, with the row it stands for.  The
    #: grid passes it on; the window opens the overlay.
    compare = Signal(object)
    #: A transfer button -- either of them -- with the row it stands for.  Both
    #: buttons mean the same thing and differ only in what they say they are
    #: sending: one copy, or every copy the card stands for.
    transfer = Signal(object)
    #: ``Transfer a Stack``, with the row it stands for.  A pile's own button:
    #: one game slot's worth of fish, which is one press and one slot whatever
    #: the pile is made of.
    transfer_stack = Signal(object)
    #: ``Transfer 1``, with the row it stands for.  A pile's answer to the
    #: player who wants one fish out of the pile and not a stack of them.
    transfer_one = Signal(object)
    #: The recover button, with the row it stands for.  Only a stranded card
    #: has one; what recovering means is the window's to decide.
    recover = Signal(object)
    #: The remove button, with the row it stands for.  Only a stranded card
    #: has one, and it is the destructive ending: the window asks before it
    #: does anything with it.
    remove = Signal(object)

    #: This is the collection's wall, so the set name on the card is a link:
    #: the set is a thing the tool holds and the window can show it.
    LINKS_SETS = True

    def __init__(
        self, row: TileRow, icons: IconCache | None = None, parent=None
    ) -> None:
        super().__init__(row, icons, parent)
        self.setObjectName("tile")
        self.setMinimumWidth(TILE_WIDTH)
        self._selected = False

    # -- what it says ----------------------------------------------------

    def set_row(self, row: TileRow) -> None:
        """Draw the same item as the tool now describes it.

        Another copy was absorbed, or this one was moved in the game: the
        fingerprint is the same and the card is the same, but the count is
        not.  Everything else about the tile is kept, including whether it is
        selected.
        """
        if row == self.row:
            return
        self.row = row
        self._fill()

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

    def _footer(self) -> QWidget:
        """The card's own line: what can be done with what it draws.

        One copy of an item is the ordinary case, and the footer's right-hand
        end is the plain way back to the game.  More than one copy is the case
        that needs acting on, and the count takes the left: putting all of them
        back is one decision about the group, and the group is the thing the
        card is.  The way into the copies is across from it.

        The left is empty for a single copy, which is the one thing a footer
        full of buttons would have said twice -- a card with one of something
        has one thing to do with it, and it is the same button in the same
        place either way.

        A stranded item is the exception to all of that, because there is
        nowhere to send it: no file of the game holds it, so instead of a way
        back there are the two answers to the state it is in -- keep the
        tool's copy, or drop it for good.  Keeping it stands on the left,
        where that ending begins; the drop is the card's far end, across the
        stretch from the button a click meant for one is not a click on.

        A *pile* is the other exception, and it is the counts that make it
        one.  The tool's copies of a fish are its stacks of it, and a stack is
        not a thing the player can be handed whole: the game holds five to a
        slot.  So the group's button counts fish rather than copies -- which
        is true however many slots they take up -- and the two buttons across
        from it are the two ways to send less than all of them: one slot's
        worth, or one fish.  ``Compare & Transfer`` is not drawn at all,
        because a pile has no copies to tell apart -- what it is made of is
        sizes, and the buttons say the sizes.
        """
        foot = QWidget()
        row = QHBoxLayout(foot)
        row.setContentsMargins(13, 6, 13, 7)
        row.setSpacing(8)

        if self.row.stranded:
            row.addWidget(self._recover_button())
            row.addStretch(1)
            row.addWidget(self._remove_button())
            return foot

        if self.row.is_a_pile:
            row.addWidget(self._transfer_all_button())
            row.addStretch(1)
            # Nothing between the two answers to the same question: a lone
            # stack's "Transfer a Stack" would send exactly what "Transfer
            # all" sends, and two buttons that do one thing are a worse
            # sentence than one.
            if self.row.stack_size < self.row.units:
                row.addWidget(self._stack_button())
            row.addWidget(self._one_button())
            return foot

        if self.row.copies > 1:
            row.addWidget(self._transfer_all_button())
        row.addStretch(1)

        row.addWidget(
            self._compare_button() if self.row.copies > 1 else self._transfer_button()
        )
        return foot

    def _compare_button(self) -> QPushButton:
        """The way into the copies: one card apiece, side by side.

        Only drawn when there is more than one copy, because that is the only
        time there is anything to compare -- one copy is
        :meth:`_transfer_button` instead.  The count is on the button across
        from it rather than on this one, so the two cannot disagree.

        ``&&`` is Qt's escape for a literal ampersand: one ``&`` in a button's
        text marks the next letter as a keyboard shortcut, and would draw this
        as "Compare Transfer" with a T underlined.
        """
        button = QPushButton("Compare && Transfer")
        button.setObjectName("compare")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(
            "Show every copy of this item side by side, and put one back."
        )
        button.clicked.connect(lambda: self.compare.emit(self.row))
        return button

    def _transfer_button(self) -> QPushButton:
        """One copy, so the card's whole action is to send it back."""
        button = QPushButton("Transfer to Stash")
        button.setObjectName("transfer")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(
            "Return this item to the shared stash, where the game will pick it\n"
            "up on its next load."
        )
        button.clicked.connect(lambda: self.transfer.emit(self.row))
        return button

    def _transfer_all_button(self) -> QPushButton:
        """Every copy at once, which is what a card with several of them is.

        The number is the whole point of the button: the card looks like one
        item and is two or more of them, so putting it back is putting back
        that many things.  It counts fish for a pile -- the copies are stacks
        there, and a stack is not a unit the player has -- and copies
        otherwise.
        """
        count = self.row.units if self.row.is_a_pile else self.row.copies
        noun = "fish" if self.row.is_a_pile else "copies"
        button = QPushButton(f"Transfer all ({count})")
        button.setObjectName("transferall")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(
            f"Return all {count} {noun} to the shared stash, where the game\n"
            "will pick them up on its next load."
        )
        button.clicked.connect(lambda: self.transfer.emit(self.row))
        return button

    def _stack_button(self) -> QPushButton:
        """One game slot's worth: the largest stack, or the game's cap off it.

        A pile is more fish than a slot holds, or it is several stacks of
        them, and this is the button for the player who wants one slot filled
        and not the whole pile: five fish out of a twenty, or the 3-stack out
        of ``{3, 1}`` and not both of them.  The number is what the press
        actually sends, which is why it is worked out from the tool's own
        stacks rather than promised as the game's cap.
        """
        size = self.row.stack_size
        button = QPushButton(f"Transfer a Stack ({size})")
        button.setObjectName("transferstack")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(
            f"Return one stack of {size} -- as much as the game holds in one\n"
            "slot -- to the shared stash, where the game will pick it up on\n"
            "its next load."
        )
        button.clicked.connect(lambda: self.transfer_stack.emit(self.row))
        return button

    def _one_button(self) -> QPushButton:
        """One fish out of the pile, however many stacks it is spread over.

        The smallest thing that can be asked for, and not the same as a card
        with one copy on it: a 4-stack is one copy and four fish, and this
        sends one of them.
        """
        button = QPushButton("Transfer 1")
        button.setObjectName("transferone")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(
            "Return one of them to the shared stash, where the game will pick\n"
            "it up on its next load."
        )
        button.clicked.connect(lambda: self.transfer_one.emit(self.row))
        return button

    def _recover_button(self) -> QPushButton:
        """The ending that keeps the item: stay here.

        There is no transfer to offer, because there is no copy of this item
        in the game to transfer it to -- no file holds it.  What went wrong is
        the *tool's* belief that it did, and this is the button that corrects
        it: the item becomes an ordinary member of the collection.

        Nothing is written to the game either way.  The state this card is in
        -- put back, then gone from the file -- is what the game's save leaves
        behind when it erases a write, and it is also what a character
        carrying the item leaves behind.  The file cannot tell the two apart,
        so a tool that wrote the item back in would be duplicating one the
        player already has.  Which of the two it is decides which button is
        right: this one when the game erased it, and :meth:`_remove_button`
        when the player is carrying it.
        """
        button = QPushButton("Recover Stranded Item")
        button.setObjectName("recover")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(
            "Keep this item in the tool.\n"
            "No stash file has it: the game's own save may have erased it,\n"
            "or a character may be carrying it.  Recovering decides only\n"
            "what the tool believes -- the game is not written to."
        )
        button.clicked.connect(lambda: self.recover.emit(self.row))
        return button

    def _remove_button(self) -> QPushButton:
        """The other ending: the tool's copy goes, and the item with it.

        For the stranded item that turns out to be a duplicate -- the one the
        player can see on a character, which is why no file has it -- keeping
        the tool's copy as well would leave them holding two of something the
        game only ever gave them one of.  So the two endings stand on the
        same line: keep it, or let it go.

        Destructive, and drawn at the far end of the line rather than beside
        the recover button, so a click meant for one is not a click on the
        other.  It deletes nothing by itself -- the window asks first, and
        this button only says which row was asked about.
        """
        button = QPushButton("Remove from Collection")
        button.setObjectName("remove")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(
            "Delete the tool's copy of this item for good.\n"
            "For a stranded duplicate: a character carrying the real one\n"
            "means the collection's copy is not the player's to keep.\n"
            "Nothing in the game is touched, and this cannot be undone."
        )
        button.clicked.connect(lambda: self.remove.emit(self.row))
        return button

    # -- the mouse -------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(event.modifiers())
            return
        super().mousePressEvent(event)


class TileGrid(CardWall):
    """The wall of cards, and which of them are selected.

    Tiles are pooled by fingerprint and only the ones whose row came back
    different are redrawn.  The window rebuilds this list on every save --
    every couple of seconds in play -- and a card is a hundred widgets, so a
    poll that changed nothing has to touch nothing.  That is the property the
    details pane was arranged around, and it is worth keeping: the memo is what
    makes the poll free.

    The selection is the grid's own rather than a view's, because there is no
    view: the thing the player clicks is a card, and a card is not a model
    index.  It is a list of fingerprints, in the order they were added, which
    is what a multiple selection means here -- the window asks only *which
    ones*, and asks the rows for their members when it acts.
    """

    #: A tile's ``Compare & Transfer``, passed on with the tile's row.
    compare = Signal(object)
    #: A tile's transfer button, passed on with the tile's row -- one copy or
    #: all of them, the button says which and the row says what they are.
    transfer = Signal(object)
    #: A tile's ``Transfer a Stack``, passed on with the tile's row.  A pile's
    #: button; the row's ``stacks`` say how much one stack is.
    transfer_stack = Signal(object)
    #: A tile's ``Transfer 1``, passed on with the tile's row.
    transfer_one = Signal(object)
    #: A tile's recover button, passed on with the tile's row.  Only a stranded
    #: card has one; what recovering means is the window's to decide.
    recover = Signal(object)
    #: A tile's remove button, passed on with the tile's row.  Only a stranded
    #: card has one; the window asks before deleting anything.
    remove = Signal(object)
    #: A tile's set name, passed on with the name that was clicked.  The grid
    #: does not know what a set is or what showing one would mean; the window
    #: does, and this is how it hears about it.
    set_chosen = Signal(str)

    def __init__(self, icons: IconCache | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(_STYLE)
        self._icons = icons
        self._rows: list[TileRow] = []
        self._empty_text = ""
        #: Tiles by fingerprint -- the pool.  A tile outlives the row list it
        #: was built for as long as the item it draws is still here.
        self._pool: dict[str, ItemTile] = {}
        self._selected: list[str] = []
        self._anchor: int | None = None

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

        wanted = {row.fingerprint for row in rows}
        for fingerprint in [f for f in self._pool if f not in wanted]:
            tile = self._pool.pop(fingerprint)
            self.forget(tile)

        tiles: list[ItemTile] = []
        for row in rows:
            tile = self._pool.get(row.fingerprint)
            if tile is None:
                tile = ItemTile(row, self._icons)
                tile.clicked.connect(
                    lambda modifiers, t=tile: self._clicked(t, modifiers)
                )
                tile.compare.connect(self.compare)
                tile.transfer.connect(self.transfer)
                tile.transfer_stack.connect(self.transfer_stack)
                tile.transfer_one.connect(self.transfer_one)
                tile.recover.connect(self.recover)
                tile.remove.connect(self.remove)
                tile.set_chosen.connect(self.set_chosen)
                self._pool[row.fingerprint] = tile
            else:
                tile.set_row(row)
            tiles.append(tile)

        # A selection whose items have gone is not a selection.  An item that
        # left the tool -- put back, or filtered out -- takes its tile with it,
        # and the highlight must not outlive the card it was drawn on: the same
        # item coming back would otherwise come back already chosen.
        self._selected = [f for f in self._selected if f in wanted]

        self.set_cards(tiles, empty)
        self._paint_selection()

    def rows(self) -> list[TileRow]:
        return list(self._rows)

    def tile(self, n: int) -> ItemTile:
        """The tile at ``n``, in grid order -- which is the row order, since
        every card on this wall is a tile."""
        return self._cards[n]

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
        fingerprint = self._cards[n].row.fingerprint
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
        index = self._cards.index(tile)
        if modifiers & Qt.KeyboardModifier.ShiftModifier and self._anchor is not None:
            low, high = sorted((self._anchor, index))
            self._selected = [
                other.row.fingerprint for other in self._cards[low : high + 1]
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
        for card in self._cards:
            card.set_selected(card.row.fingerprint in chosen)

