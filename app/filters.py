"""The row over the collection: the search box, the sort, the facets.

Three of the things that narrow a collection -- a word, the rarities, a range
of levels -- in one row above the cards rather than in a column beside them,
which is where the reference tool puts them, and where they cost the wall none
of its width.  The row sits over the collection and not across the whole
window, so that the controls are next to the only pane they narrow.  The kinds
stay in the rail: a kind has a path (a sword is a one-handed weapon) and a tree
is the only control that says so, while a tree drawn across the top of a window
is a tree nobody reads.  The sets are not here either, and have no control at
all: a set is arrived at by clicking its name on a card, and what this row does
with one is stand in for it until the player clicks the cross -- see
:meth:`FilterBar.show_set`.

The fourth control is the odd one out in exactly one way: it orders the list
rather than narrowing it, and the list it orders is the one the other three
have already left.  It is the reference's own -- a box of keys over a little
button carrying an arrow -- and it stands where the reference keeps its own,
just before the rarities, which are the one facet a sort is a reading *of*.

The rarities and the levels are each in a box of their own, in the window's own
control ink like every other control the player operates
(:data:`app.theme.CHALK` says why), and the sort's two controls are in one of
the same boxes.  Five pills reading ``Unique 4`` in a row are legible; a pair
of number boxes saying ``0`` and ``100`` beside them are not, and two outlined
rectangles are what tells a reader where the rarity chips stop and the level
range starts.

The counts on the chips are what a tick *would* leave rather than what it does
leave -- see :meth:`app.models.CollectionFilter.counts` -- so the number beside
a chip stays worth reading while another one is ticked.

Nothing here decides anything.  It draws what it is told to draw, says what is
ticked, shown or sorted, and emits :attr:`FilterBar.changed` or
:attr:`FilterBar.resorted`; :class:`~app.models.CollectionFilter` is what makes
either of them mean anything.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
    QWidget,
)

from tl2stash.card import TIER_INK

from .models import LEVEL_MAX, SORT_KEYS, TIER_CHIPS
from .theme import CHALK

__all__ = ["FilterBar", "SpinBox"]

#: How much of a tier's colour a ticked pill is filled with, of 255.  A wash
#: rather than the colour itself, so that the word on it stays the brightest
#: thing in the chip.
WASH = 77

#: How far the row stands in from the left edge of the pane it is over.  The
#: bar is the collection box's *sibling* rather than its content -- the pane
#: stacks the two -- so with no inset the search box, which is the first
#: control in the row, would stand over the box's frame while everything the
#: box holds begins a little further in.  The inset is that little further:
#: the nine pixels a layout leaves inside a group box -- a child box, as the
#: three panes are; a box that is a window of its own is given a window's own
#: margins, two pixels more -- and the one-pixel border the sheet draws round
#: it.  The user's nudge, in other words, is the row lining up with what it is
#: over, and ``tests/test_app_filters.py`` measures it against a real box
#: rather than against the 10 written down twice.
#:
#: The left only.  What stands at the right end of the row is the reset, and a
#: reset belongs under the pane's corner rather than over its contents.
INSET = 10

#: The two white steppers: six pixels across at the base and three rows deep,
#: with each edge placed half a pixel off the grid.  That last is the whole of
#: the geometry's care: a triangle of a dozen pixels whose edges land on whole
#: coordinates comes out a grey haze, because every one of those pixels is then
#: half covered.  Off the grid by half a pixel, each is wholly in or wholly out
#: -- which is why the painter below is left un-smoothed, as a stepper arrow is
#: drawn everywhere.
STEP = 3.0
STEP_ROWS = 3


class SpinBox(QSpinBox):
    """A number box whose two steppers are drawn here rather than by the style.

    Qt will give a spin box an outlined frame or keep the style's own stepper
    arrows, and not both.  The moment a rule touches the box's frame, the
    stylesheet style takes the whole control over and draws the two buttons as
    flat blocks -- with no arrows at all, because an arrow in Qt's stylesheet
    language is an *image file* and this application ships none.  A number box
    whose steppers are two blank squares reads as broken, so the frame is the
    sheet's (:mod:`app.theme`) and the triangles are painted here: a dozen
    lines, and the corners come out cleaner than the style's own.

    Everything else about the widget is ``QSpinBox``'s, including the frame
    the sheet draws for it -- a type selector matches subclasses, which is why
    the rule in :mod:`app.theme` reaches this class without naming it.
    """

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(CHALK))
        painter.drawPolygon(self._triangle(QStyle.SubControl.SC_SpinBoxUp))
        painter.drawPolygon(self._triangle(QStyle.SubControl.SC_SpinBoxDown))
        painter.end()

    def _triangle(self, which) -> list[QPointF]:
        """One arrow: six pixels across, three rows deep, in the style's button."""
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        button = self.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox, option, which, self
        )
        middle = button.center()
        top = button.top() + (button.height() - STEP_ROWS) // 2
        if which == QStyle.SubControl.SC_SpinBoxUp:
            base, tip = top + STEP_ROWS, top - 0.5
        else:
            base, tip = top, top + STEP_ROWS + 0.5
        return [
            QPointF(middle.x() - STEP, base),
            QPointF(middle.x() + STEP, base),
            QPointF(middle.x(), tip),
        ]


def _wash(ink: str) -> str:
    """A tier's colour as a fill the chip's own word can be written on."""
    colour = QColor(ink)
    return f"rgba({colour.red()}, {colour.green()}, {colour.blue()}, {WASH})"


def _chip_style(ink: str) -> str:
    """A rarity chip: the window's light ink over the tier's own colour, in a
    pill.

    The word is the light in *both* states and the tier is what the pill is
    *filled* with, which is the other way round from how this started: the word
    used to be inked in the tier and dimmed to a grey while unticked, and that
    grey was the thing the user could not read -- five words a shade off the
    ground they were drawn on, blending into the bar they sit on.  A word the
    player has to read is in the window's control ink here, as every other word
    on a control is.

    So what a tick changes is the fill: a washed pill for a rarity that is in
    play, the bare ground for one that is not, and the outline either way.  The
    wash is what says *on* at a glance down the bar, and the colour it is a
    wash of says which rarity the chip is.

    The indicator is collapsed to nothing and the pill itself is the control --
    a checkbox's box beside a coloured pill is two things saying one thing.
    """
    return (
        "QCheckBox {"
        f" color: {CHALK};"
        f" border: 1px solid {CHALK};"
        " border-radius: 9px; padding: 3px 8px;"
        f" background: {_wash(ink)};"
        "}"
        "QCheckBox::indicator { width: 0px; height: 0px; }"
        "QCheckBox:!checked { background: transparent; }"
    )


def _set_style() -> str:
    """The chip a shown set stands in: the rarity pills' treatment, in purple.

    A button rather than a tick box, because it is not a thing the player
    chooses between: it is *on* for as long as a card's set name has been
    clicked, and clicking it is the way back to the whole collection.  So it
    takes the same pill as the rarity chips -- the window's own ink for the
    word and the outline, a wash of one colour for the fill -- and the one
    difference is what is written on it: the name, and the cross that says the
    chip comes off.  A chip with nothing to say how it comes off is a filter
    the player is stuck behind.
    """
    return (
        "QPushButton {"
        f" color: {CHALK};"
        f" border: 1px solid {CHALK};"
        " border-radius: 9px; padding: 3px 8px;"
        f" background: {_wash(TIER_INK['set'])};"
        "}"
    )


def _box(title: str, controls: Iterable[QWidget]) -> QGroupBox:
    """A group of controls in its own outlined box.

    A ``QGroupBox`` rather than a frame with a label over it, because its title
    is drawn in the window's own label colour and in the same place as the
    three panes' titles -- so a box here and a pane there are the same kind of
    thing at two sizes, which is what they are.  What tells them apart is the
    outline: the control ink for a box the player operates, a hairline for a
    region.
    """
    box = QGroupBox(title)
    box.setObjectName("filterbox")
    row = QHBoxLayout(box)
    row.setContentsMargins(8, 2, 8, 4)
    row.setSpacing(6)
    for control in controls:
        row.addWidget(control)
    return box


class FilterBar(QWidget):
    """The controls over a collection: the ones that narrow it, and the sort."""

    #: Something was typed, ticked or spun.  One signal for all of them, because
    #: the window does one thing with it: re-apply every facet and re-count.
    changed = Signal()

    #: The order moved -- the key or the arrow.  A signal of its own because it
    #: is not a facet: nothing about *which* rows are on the wall has changed,
    #: so there is nothing to count, and the numbers beside the rail and the
    #: chips would be the same numbers they already are.
    resorted = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        #: True while this widget is writing to itself -- a reset, most of all
        #: -- so that its own writes do not come back round as the player
        #: having changed something.
        self._updating = False
        #: The set being shown, if one is.  Unlike every other facet this is
        #: not read off a control: the chip below is written *from* it, so
        #: that the two cannot disagree about what is being shown.
        self._set = ""
        #: Whether the sort is being read the other way about.  Not read off
        #: the button either, for the same reason: the arrow is written *from*
        #: this, so the glyph and what the window is told cannot come apart.
        self._backwards = False

        row = QHBoxLayout(self)
        row.setContentsMargins(INSET, 0, 0, 0)
        row.setSpacing(6)

        self.search = QLineEdit()
        # Named, because the window's stylesheet outlines the search box in
        # white and a rule on ``QLineEdit`` would also reach the line edit
        # inside each of the two number boxes below.
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search the collection…")
        self.search.setClearButtonEnabled(True)
        # A floor, because a text box's own minimum is nothing: squeezed, it
        # would collapse to a sliver while the pills beside it kept their
        # width.  It matters beyond this row, too -- whatever the bar asks for,
        # the pane under it asks for as well, and the three panes together are
        # what set the window's own minimum width.  Every pixel of floor here
        # is a pixel the window cannot open narrower, and the game's list
        # beside it is what pays for that; 120 still leaves the box readable.
        #
        # It was 180 and came down with the sort box, which is the first
        # control this row has had to find room for; the advanced search's
        # button is the next, and the box that takes every spare pixel is the
        # one place that room can come from without costing a control its
        # width.
        #
        # It is a floor and not the width: the box takes every pixel the row
        # is not already spending (below), so it is as wide as the pane has
        # room for and this is only what it cannot be squeezed under.
        self.search.setMinimumWidth(120)
        self.search.setToolTip(
            "Show only the items whose name contains this.\n"
            "It narrows what the ticks beside it leave."
        )
        self.search.textChanged.connect(self._moved)
        # The one control here that is worth widening, so it is the one that
        # takes what the row has over.  The two boxes beside it are as wide as
        # the words in them and no wider -- that is their own test -- and the
        # reset at the far end is a button, so what is left of a wide pane
        # lands here rather than as a gap in the middle of the bar, which is
        # what the user was looking at when they asked for this.
        row.addWidget(self.search, 1)

        # The set, when one is being shown.  It sits with the search box
        # because it is the other half of what the box is for -- both answer
        # "which items", one by a word the player types and one by a name they
        # clicked -- and it is drawn only while there is a set: an empty chip
        # in the row every other day would be furniture.  A hidden widget takes
        # no room in a layout, so the row is the row it always was until the
        # click that puts one here.
        #
        # While it is here the row is as wide as the chip, and the collection
        # pane's own floor with it -- a button's layout minimum is its own
        # width, and this row is what sets the window's minimum.  That is the
        # trade taken deliberately: the alternative is a chip that can be
        # squeezed to a sliver exactly when the window is small, and the status
        # line sends the player to this chip to get back.  It is bounded in any
        # case by the longest set name the game has, which is seventeen
        # characters.
        self.set_chip = QPushButton()
        self.set_chip.setObjectName("setchip")
        self.set_chip.setStyleSheet(_set_style())
        self.set_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_chip.setToolTip("Show the whole collection again.")
        self.set_chip.clicked.connect(self.clear_set)
        self.set_chip.setVisible(False)
        row.addWidget(self.set_chip)

        # The sort, which is the one control here that does not narrow: it
        # orders what the others leave.  It stands where the reference keeps
        # its own -- just before the rarities, which are the one facet a sort
        # is a reading of -- and it is in a box of the row's own language
        # rather than a bare pair of controls, because the alternative is the
        # word "Sort" floating in the middle of the bar with nothing to say
        # which two of the widgets it belongs to.
        #
        # Neither of them takes stretch: what the row has over belongs to the
        # search box, and a box that grew with the pane would be a select the
        # width of the window.
        row.addSpacing(10)
        self.sort = QComboBox()
        self.sort.setObjectName("sort")
        for key in SORT_KEYS:
            self.sort.addItem(key)
        self.sort.setToolTip(
            "What the cards are ordered by.  The rarity order is the wall's\n"
            "own -- best first, the untiered last -- and the arrow reads it\n"
            "the other way about."
        )
        self.sort.currentIndexChanged.connect(self._resorted)
        # The arrow, which is the reference's: it points the way the key is
        # read, and clicking it turns the key over.  One switch rather than one
        # per key, also like the reference -- so a player who has turned the
        # ladder over and then asks for the names gets them backwards, which is
        # the one reading of *"reverse the order"* that cannot surprise anyone
        # halfway down a list.
        self.reverse = QPushButton()
        self.reverse.setObjectName("reverse")
        self.reverse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reverse.clicked.connect(self._turn)
        self._point_arrow()
        self.sort_box = _box("Sort", [self.sort, self.reverse])

        row.addWidget(self.sort_box)
        row.addSpacing(10)
        self.chips: dict[str, QCheckBox] = {}
        for word in TIER_CHIPS:
            chip = QCheckBox(word)
            chip.setStyleSheet(_chip_style(TIER_INK[word.lower()]))
            chip.setToolTip(f"Show only the {word.lower()} items.")
            chip.toggled.connect(self._moved)
            self.chips[word] = chip
        self.rarity_box = _box("Rarity", self.chips.values())
        row.addWidget(self.rarity_box)

        row.addSpacing(10)
        self.low = self._spin(0)
        self.high = self._spin(LEVEL_MAX)
        self.level_box = _box(
            "Player level", [self.low, QLabel("to"), self.high]
        )
        row.addWidget(self.level_box)

        self.clear_button = QPushButton("Clear filters")
        self.clear_button.setToolTip("Untick everything, in the bar and in the rail.")
        self.clear_button.clicked.connect(self.reset)
        row.addWidget(self.clear_button)

    def _spin(self, value: int) -> SpinBox:
        """A min or a max: two player levels, both ends included.

        The boxes used to read ``Any`` at zero, which was one word for "do not
        ask" -- two things a level box can mean, and only one of them is a
        level.  Zero is one: a socketable is level 0 and the collection holds
        them, so a box the player sets to 0 has to mean the thing it says.

        What they range over is the level an item *asks for*, which is the
        number on its tooltip and not the level it is -- so the range answers
        "what can this character use", which is what a player narrowing a
        collection is asking.
        """
        spin = SpinBox()
        spin.setRange(0, LEVEL_MAX)
        spin.setValue(value)
        spin.setToolTip(
            "The player levels to show, both ends included: an item is shown\n"
            "when the level it requires falls in this range.\n"
            f"0 to {LEVEL_MAX} is the whole range, and is where these start.\n"
            "Anything the game gates on nothing at all is always shown."
        )
        spin.valueChanged.connect(self._moved)
        return spin

    # -- what the bar is told --------------------------------------------

    def set_counts(self, tiers: Mapping[str, int] | None = None) -> None:
        """Put the numbers on the chips.

        These are what the filters *would* leave rather than what they do
        leave, so a chip reading zero is a rarity that has nothing behind it
        under the current filters -- see :meth:`app.models.CollectionFilter.
        counts`.
        """
        self._updating = True
        try:
            for word, chip in self.chips.items():
                chip.setText(f"{word}  {(tiers or {}).get(word, 0)}")
        finally:
            self._updating = False

    # -- what the bar says -----------------------------------------------

    def search_text(self) -> str:
        """What is in the box, which the proxy matches as a fixed string."""
        return self.search.text()

    def tiers(self) -> set[str]:
        """The rarity words that are ticked."""
        return {word for word, chip in self.chips.items() if chip.isChecked()}

    def level_range(self) -> tuple[int, int]:
        """The bounds, both of them player levels and both ends included.

        What comes out is the whole range until the player narrows it, so the
        two boxes say what they are letting through rather than standing in for
        a question nobody asked.
        """
        return (self.low.value(), self.high.value())

    def shown_set(self) -> str:
        """The set being shown, or the empty string for all of them."""
        return self._set

    # -- what the bar says about the order --------------------------------

    def sort_key(self) -> str:
        """What the cards are ordered by, in the words the proxy is given.

        The words on the box *are* the keys -- ``app.models.SORT_KEYS`` is
        what filled it -- so what comes out is what the player read, and there
        is no table between the two to get out of step.
        """
        return self.sort.currentText()

    def sort_backwards(self) -> bool:
        """Whether the key is being read the other way about, which is the
        arrow.

        The key's own order is the one written down in the model -- for the
        ladder, best first, which is the user's rule rather than the
        reference's -- and this says only whether the player has turned it
        over.  At rest it is ``False``, and the arrow points down.
        """
        return self._backwards

    # -- the set ---------------------------------------------------------

    def show_set(self, name: str) -> None:
        """Show one set and nothing else, whatever the bar was showing before.

        A set is arrived at by clicking a *name on a card*, and a player who
        does that is asking to see the set -- not asking to see the set as well
        as the uniques they happened to have ticked a moment ago.  A narrowing
        inside a narrowing is the way to a wall with two cards on it and no
        explanation, so this one switch clears the rest: the search box, the
        chips and the level range go back to where the window starts, and the
        set is the only thing left saying anything.  The rail is cleared by the
        window, which is where the rail lives.

        All of it behind :attr:`_updating` and one :attr:`changed` at the end,
        because to the window this is one move and not five.
        """
        self._updating = True
        try:
            self._clear_controls()
            self._show(name)
        finally:
            self._updating = False
        self.changed.emit()

    def clear_set(self) -> None:
        """Show the whole collection again, keeping the rest of the bar.

        What the chip's cross does.  It is the one facet with a control of its
        own that is *off* a tick -- the chip is not a box the player ticks but
        a statement of what is being shown -- so taking it off leaves whatever
        else the player had set exactly where it was.
        """
        if not self._set:
            return
        self._updating = True
        try:
            self._show("")
        finally:
            self._updating = False
        self.changed.emit()

    def _show(self, name: str) -> None:
        """Put a set on the chip, or take the chip off.  Silent, and internal."""
        self._set = name or ""
        self.set_chip.setText(f"{self._set}  ✕" if self._set else "")
        self.set_chip.setVisible(bool(self._set))

    # -- the user --------------------------------------------------------

    def _moved(self, *_) -> None:
        if not self._updating:
            self.changed.emit()

    def _resorted(self, *_) -> None:
        """The order moved.  Guarded like every other signal here, and for the
        same reason: writing the box is the window's doing and not the
        player's."""
        if not self._updating:
            self.resorted.emit()

    def _turn(self) -> None:
        """The arrow: read the key the other way about."""
        self._backwards = not self._backwards
        self._point_arrow()
        self._resorted()

    def _point_arrow(self) -> None:
        """Say which way the key is read, in the reference's own two glyphs.

        Down is the key's own order and up is the other one, so the button
        says what a click would *do* as well as what is being done -- which is
        the whole of what a two-glyph button can carry.
        """
        self.reverse.setText("↑" if self._backwards else "↓")

    def _clear_controls(self) -> None:
        """Every control in the row back to the value the window starts it at.

        Silent, and the caller's to guard: two of the three callers below want
        the clearing *and* something else, and only the last of them wants the
        signal.

        The sort is not one of these controls and is not put back.  It is not a
        facet -- clearing the filters asks to see *everything* again, which it
        does, and says nothing about the order any of it is in.  A player who
        has asked for the newest first and then clears the search box is still
        asking for the newest first.
        """
        self.search.clear()
        for chip in self.chips.values():
            chip.setChecked(False)
        self.low.setValue(0)
        self.high.setValue(LEVEL_MAX)

    def reset(self) -> None:
        """Put every control back, which is the state the window starts in."""
        self._updating = True
        try:
            self._clear_controls()
            self._show("")
        finally:
            self._updating = False
        self.changed.emit()
