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

:guilabel:`Advanced search` stands between the search box and the sort, and
opens :class:`app.advsearch.AdvancedSearchOverlay` -- eight more facets that
have no room in this row: an item level range, socket counts, four attribute
requirements, the classes an item may be restricted to, the damage and armour
elements asked about, and the property rows.  It belongs with the search box
rather than after the sort because what is behind it is the rest of what
*narrows* a collection, and the sort is where the narrowing ends and the
ordering begins.  Those eight facets are kept *here* rather than in the panel,
because this is where every facet lives until the window asks for it, and the
panel is a thing that opens and closes: a search that unset eight facets by
being closed would be a filter with a lifetime of its own.  The button wears
the rail's gold while one of those eight is narrowing the collection, which is
the only sign a control this row has not got is doing anything -- see
:meth:`FilterBar.advanced_active`.

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

from .card import GOLD
from .models import (
    LEVEL_MAX,
    REQ_REST,
    REQ_WORDS,
    SORT_KEYS,
    TIER_CHIPS,
    Advanced,
)
from .theme import CHALK

__all__ = ["FilterBar", "SpinBox", "chip_style"]

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


def chip_style(ink: str) -> str:
    """A rarity chip: the window's light ink over the tier's own colour, in a
    pill.

    Public, because the advanced search's panel draws the same five chips in
    its Rarity row and the two rows are the same control in two places: a
    player who has learned what a green pill means over the collection must
    not be told a different story by a green pill inside the panel.

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


def _advanced_style(active: bool) -> str:
    """The advanced search's button: a box the row's language, gold when it is on.

    The same outlined rectangle as the number boxes, because it is a control in
    the same row and one more of the same kind.  What it says that they cannot
    is when it is *doing* something: the four facets behind it have no control
    in this row, so without the ink a collection narrowed by a panel nobody can
    see would look exactly like one narrowed by nothing.

    The rail's gold rather than a colour of its own -- it is the ink the
    reference uses for "this one is on", and the rail already uses it for a
    group with everything ticked, which is the same statement about a different
    control.
    """
    ink = GOLD if active else CHALK
    return (
        "QPushButton {"
        f" color: {ink};"
        f" border: 1px solid {ink};"
        # Three pixels of vertical padding rather than two, which is the
        # user's other ask about this button: the chips beside it are drawn
        # at three and the reset at the style's own, so two left this the
        # shortest control in the row by a pixel and it read as a thing
        # sitting slightly below the line the others are on.
        " border-radius: 3px; padding: 3px 8px;"
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

    #: `Clear filters` was pressed: every facet back to rest, and the whole
    #: collection shown again.  A signal of its own because the bar is not the
    #: only place a facet is ticked -- the kinds are in the rail, which is not
    #: this widget's to untick -- and :attr:`changed` cannot say whether one
    #: control moved or all of them were put back at once.
    cleared = Signal()

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
        #: The advanced search's eight facets, which have no control here: an
        #: item level range (kept as the pair of numbers it is), the socket
        #: counts, the four attribute ranges in :data:`~app.models.REQ_WORDS`
        #: order, the class words, and the three that read the item's own card
        #: -- the damage and armour elements asked about, and the property
        #: rows.  Plain attributes rather than widgets, because there is
        #: nothing to draw -- the panel draws them, and :meth:`current` and
        #: :meth:`adopt` are how the two sides pass them.  All of them stay at
        #: rest until a panel writes one, and "at rest" is a range or a set
        #: that lets everything through: the same bargain the facets above
        #: make.
        self._item_low = 0
        self._item_high = LEVEL_MAX
        self._sockets: set[int] = set()
        self._reqs: tuple[tuple[int, int], ...] = REQ_REST
        self._classes: set[str] = set()
        self._damage: tuple[tuple[str, int, int], ...] = ()
        self._armor: tuple[tuple[str, int, int], ...] = ()
        self._stats: tuple[tuple[str, int, int], ...] = ()
        self._bonuses = False

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
        # width.  The button's own width came from the sheet rather than from
        # here for the same reason -- see :mod:`app.theme` -- and moving it in
        # front of the sort changed none of this arithmetic: it takes no
        # stretch wherever it stands.
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

        # The way into the eight facets that have no room here, and the only
        # thing in the row that opens something rather than being something.
        # It stands between the search box and the sort, which is where the
        # user asked for it: what is behind it is the rest of what *narrows* a
        # collection, so it belongs with the controls that narrow, and the
        # sort -- which only orders what the others leave -- is where the
        # narrowing ends.
        #
        # After the set chip rather than before it, because that chip is the
        # other half of the search box's own question and the two belong
        # together; the chip takes no room in the layout at all until a set is
        # being shown, so this is the control immediately after the search box
        # on every ordinary day.
        self.advanced = QPushButton("Advanced search")
        self.advanced.setObjectName("advanced")
        self.advanced.setCursor(Qt.CursorShape.PointingHandCursor)
        self.advanced.setToolTip(
            "More ways to narrow the collection: item level, sockets,\n"
            "an item's stat requirements, the class it is for, its damage\n"
            "and armour, and the stats it shows."
        )
        self._ink_advanced()
        row.addSpacing(10)
        row.addWidget(self.advanced)

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
        #
        # Its width is the sheet's rather than this file's -- a rule on
        # ``QPushButton#reverse``, which is also what takes the style's own
        # 80-pixel floor off it; see :mod:`app.theme`.
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
            chip.setStyleSheet(chip_style(TIER_INK[word.lower()]))
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

    # -- what the bar says about the advanced search ----------------------

    def item_level_range(self) -> tuple[int, int]:
        """The item levels to show, both ends included.

        The *other* level range, and the two are asked of different numbers:
        what the item is against what it asks of the character.  This one has
        no boxes in the row and comes from the panel, which is where it is set.
        """
        return (self._item_low, self._item_high)

    def sockets(self) -> set[int]:
        """The socket counts ticked; empty for any number of them."""
        return set(self._sockets)

    def requirement_ranges(self) -> tuple[tuple[int, int], ...]:
        """The four attribute ranges, in :data:`~app.models.REQ_WORDS` order."""
        return tuple(self._reqs)

    def classes(self) -> set[str]:
        """The class words ticked; empty for every class."""
        return set(self._classes)

    def damage_ranges(self) -> tuple[tuple[str, int, int], ...]:
        """The damage elements asked about, one ``(element, low, high)`` each.

        Only the elements the search names, which is what the model reads the
        presence test from: a row left covering everything is not passed and
        does not have to be filtered out again downstream -- see
        :meth:`app.models.CollectionFilter.set_damage`.
        """
        return tuple(self._damage)

    def armor_ranges(self) -> tuple[tuple[str, int, int], ...]:
        """The armour elements asked about, the same shape exactly."""
        return tuple(self._armor)

    def stat_rows(self) -> tuple[tuple[str, int, int], ...]:
        """The property rows: what to look for, and the range to find it in."""
        return tuple(self._stats)

    def bonuses(self) -> bool:
        """Whether a property row may be answered by a set's bonus as well."""
        return self._bonuses

    def advanced_active(self) -> bool:
        """Whether one of the eight panel-only facets is narrowing anything.

        What the button's ink says, and the reason it is worked out from the
        facets rather than remembered as a flag: a flag is a second answer to a
        question the facets have already answered, and the two would come apart
        the first time a panel was dismissed without being applied.
        """
        return bool(
            self._item_low
            or self._item_high != LEVEL_MAX
            or self._sockets
            or self._classes
            or self._reqs != REQ_REST
            or self._damage
            or self._armor
            or self._stats
        )

    def current(self) -> Advanced:
        """Everything the advanced search opens on, as one value.

        The bar's own three facets are read off their controls and the eight
        behind the button off the attributes above, so there is one copy of
        each and nothing to keep in step.  ``places`` is left resting: the
        kinds are ticked in the rail, which is not part of the bar, and whoever
        assembles a draft fills that field from it -- see
        :meth:`app.window.MainWindow._open_advanced`.
        """
        return Advanced(
            text=self.search_text(),
            tiers=frozenset(self.tiers()),
            low=self.low.value(),
            high=self.high.value(),
            item_low=self._item_low,
            item_high=self._item_high,
            sockets=frozenset(self._sockets),
            reqs=tuple(self._reqs),
            classes=frozenset(self._classes),
            damage=tuple(self._damage),
            armor=tuple(self._armor),
            stats=tuple(self._stats),
            bonuses=self._bonuses,
        )

    def adopt(self, state: Advanced) -> None:
        """Write a search back onto the controls, and onto the eight behind them.

        What pressing `Search` does with the draft the panel hands over.  The
        three controls are written *silently*: this is one move, the window
        makes it, and a bar that emitted for each of the writes would have the
        window re-apply half a search several times over.  The caller emits
        once when it is done -- see :meth:`app.window.MainWindow._advanced_search`.

        The rail is not touched.  ``state.places`` is the window's to apply,
        because the rail is not part of the bar and this method has no way to
        reach it.
        """
        self._updating = True
        try:
            self.search.setText(state.text)
            for word, chip in self.chips.items():
                chip.setChecked(word in state.tiers)
            self.low.setValue(state.low)
            self.high.setValue(state.high)
        finally:
            self._updating = False

        self._item_low, self._item_high = state.item_low, state.item_high
        self._sockets = set(state.sockets)
        self._reqs = tuple(state.reqs)
        self._classes = set(state.classes)
        self._damage = tuple(state.damage)
        self._armor = tuple(state.armor)
        self._stats = tuple(state.stats)
        self._bonuses = state.bonuses
        self._ink_advanced()

    def _ink_advanced(self) -> None:
        """Say whether the eight facets behind the button are doing anything."""
        self.advanced.setStyleSheet(_advanced_style(self.advanced_active()))

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

        The eight behind the advanced button *are* put back, and they are the
        ones that make this the whole of "show everything": they are facets of
        the same collection, they are what the gold button has been saying is
        on, and a `Clear filters` that left a class ticked somewhere the player
        cannot see would be the one control here that does not do what it says.
        """
        self.search.clear()
        for chip in self.chips.values():
            chip.setChecked(False)
        self.low.setValue(0)
        self.high.setValue(LEVEL_MAX)
        self._item_low, self._item_high = 0, LEVEL_MAX
        self._sockets = set()
        self._reqs = REQ_REST
        self._classes = set()
        self._damage = ()
        self._armor = ()
        self._stats = ()
        self._bonuses = False
        self._ink_advanced()

    def reset(self) -> None:
        """Put every control back, which is the state the window starts in.

        What `Clear filters` does, and it is the whole of that: the bar's own
        controls and the eight facets behind the button, said once through
        :attr:`changed` so that the window applies the whole of it in one go.
        The kinds are the rail's and are cleared by whoever hears
        :attr:`cleared` -- the bar cannot reach them, and a bar that cleared
        everything except the one control the player is looking at would be a
        button that does not do what it says.
        """
        self._updating = True
        try:
            self._clear_controls()
            self._show("")
        finally:
            self._updating = False
        self.changed.emit()
        self.cleared.emit()
