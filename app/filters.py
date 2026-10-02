"""The row over the collection: the search box, the rarities, the level range.

Three of the four things that narrow a collection, in one row above the cards
rather than in a column beside them -- which is where the reference tool puts
them, and where they cost the wall none of its width.  The row sits over the
collection and not across the whole window, so that the controls are next to
the only pane they narrow.  The fourth, the kinds, stays in the rail: a kind
has a path (a sword is a one-handed weapon) and a tree is the only control
that says so, while a tree drawn across the top of a window is a tree nobody
reads.

The rarities and the levels are each in a box of their own, in the window's own
control ink like every other control the player operates
(:data:`app.theme.CHALK` says why).  Five pills reading ``Unique 4`` in a row
are legible; a pair of number boxes saying ``0`` and ``100`` beside them are
not, and two outlined rectangles are what tells a reader where the rarity chips
stop and the level range starts.

The counts on the chips are what a tick *would* leave rather than what it does
leave -- see :meth:`app.models.CollectionFilter.counts` -- so the number beside
a chip stays worth reading while another one is ticked.

Nothing here decides anything.  It draws what it is told to draw, says what is
ticked, and emits :attr:`FilterBar.changed`; :class:`~app.models.
CollectionFilter` is what makes that mean anything.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
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

from .models import LEVEL_MAX, TIER_CHIPS
from .theme import CHALK

__all__ = ["FilterBar", "SpinBox"]

#: How much of a tier's colour a ticked pill is filled with, of 255.  A wash
#: rather than the colour itself, so that the word on it stays the brightest
#: thing in the chip.
WASH = 77

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
    """The four controls that narrow a collection by something other than kind."""

    #: Something was typed, ticked or spun.  One signal for all of them, because
    #: the window does one thing with it: re-apply every facet and re-count.
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        #: True while this widget is writing to itself -- a reset, most of all
        #: -- so that its own writes do not come back round as the player
        #: having changed something.
        self._updating = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
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
        # beside it is what pays for that; 180 still leaves the box readable.
        self.search.setMinimumWidth(180)
        self.search.setToolTip(
            "Show only the items whose name contains this.\n"
            "It narrows what the ticks beside it leave."
        )
        self.search.textChanged.connect(self._moved)
        row.addWidget(self.search)

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

        row.addStretch(1)
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

    # -- the user --------------------------------------------------------

    def _moved(self, *_) -> None:
        if not self._updating:
            self.changed.emit()

    def reset(self) -> None:
        """Put every control back, which is the state the window starts in."""
        self._updating = True
        try:
            self.search.clear()
            for chip in self.chips.values():
                chip.setChecked(False)
            self.low.setValue(0)
            self.high.setValue(LEVEL_MAX)
        finally:
            self._updating = False
        self.changed.emit()
