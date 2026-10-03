"""The advanced search: the facets the bar has no room for, over the window.

The bar over the collection carries four controls, and seven more are here: a
range of *item* levels, the socket counts, an item's four stat requirements,
the classes it may be restricted to, and the three that read the item's own
card -- a damage and an armour range per element, and the property rows.  They
are the reference database's own advanced search, section for section and rule
for rule -- see :meth:`app.models.CollectionFilter.set_requirements` for the two
rules that are easy to get wrong, and
:meth:`app.models.CollectionFilter.set_damage` for the two the element rows
have -- and they are on a panel rather than in the row because a row of a dozen
controls is a row nobody reads.

It opens over the window the way the comparison screen does: a scrim, a panel
inside it, Esc or the `✕` or a press on the backdrop to put it away.  What is
different is that this one edits a *draft*.  Nothing here narrows anything
until `Search` is pressed, and a draft thrown away -- by Esc, by the cross, by
a click on the ground -- has narrowed nothing at all: a panel that applied as
it was filled would be a panel whose Cancel is a lie, and one that applied on
a timer would be a panel that cannot be left half-set while the player thinks.

`Reset` puts the controls back to the resting state without applying anything,
which is what the reference's own does and the only reading that keeps `Reset`
and `Search` two different words.

Nothing here decides anything either.  It draws what it is told to draw and
hands back an :class:`~app.models.Advanced`; the window writes that onto the
bar and the rail, and :class:`~app.models.CollectionFilter` is what makes it
mean something.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QCompleter,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tl2stash.card import TIER_INK
from tl2stash.taxonomy import KIND_PLACES, Place

from .card import BODY, DIM, GOLD, HEAD, LABEL, LINE, PANEL, Hairline
from .compare import SCRIM, inset_for
from .filters import SpinBox, chip_style
from .models import (
    CLASSES,
    ELEMENTS,
    ELEMENT_REST,
    LEVEL_MAX,
    NUMBER_MAX,
    REQ_MAX,
    REQ_WORDS,
    SOCKET_COUNTS,
    TIER_CHIPS,
    Advanced,
)
from .sidebar import UNCLASSIFIED, arranged
from .theme import BODY_PX, CHALK, PALE

__all__ = ["AdvancedSearchOverlay", "vocabulary"]

#: The group button that takes every kind rather than one group's.  Spelled
#: once, because three places here compare against it and a second spelling
#: would be a button that toggles nothing.
ALL_TYPES = "All"

#: How wide the panel is allowed to get, however wide the window is.  A form is
#: read down a column, and a search box spanning a 1400px screen puts its words
#: at one edge and its end at the other; the reference caps its own panel for
#: the same reason, and this is wider than its 620 -- for the Type grid, which
#: draws four kinds to a row and now draws the whole of the game's taxonomy in
#: them.
#:
#: It is a cap and not a width.  What the panel opens at is the width of the
#: form inside it -- see :class:`Body` -- and this is only what stops a wide
#: *window* from handing it more than a form should have.  Which means it has
#: to stand clear of the form rather than inside it: the widest thing here is
#: the grid, and how wide that is depends on the machine's face, which is not a
#: number this file can pin.  A cap below the form would not make the panel
#: narrower than the form -- it would make it narrower *than its own form*, and
#: the ends of the rows would be cut off, because the body scrolls down and not
#: across.  So it is set well clear, and in practice the form is what decides.
PANEL_MAX = 960

#: How many kind boxes stand in one row of the Type grid.  The user's own
#: number.  The reference draws two, which is what its narrower panel fits; at
#: this width four leaves the longest kind word in the game room to spare and
#: still reads as a column -- see :class:`TypeGrid`.
COLUMNS = 4

#: How far a subgroup's heading is set in from its group's, in the Type grid.
#: The rail's arithmetic, near enough: what tells the two headings apart is
#: their ink, their case and this indent, and none of the three is a size.
SUBGROUP_INDENT = 12

#: The air inside the panel, on every side and between two sections.  Wide,
#: because the sections are the structure here: what tells the four groups of
#: controls apart is the space between them, since a rule under each would be
#: four more lines on a screen that is already a form.
PAD = 16

#: The size a row's name is written at, and its note under it.  One spelling,
#: because the Class section's indent is measured through it -- see
#: :func:`_class_indent` -- and a size written twice is a measurement taken off
#: the wrong one.
NAME_PX = 11

#: The column a row's label is written in.  Fixed, so that the sections'
#: controls line up down the panel even though the longest word in them --
#: "Vitality" -- is nothing like the longest in the Type grid.
LABEL_PX = 92

#: How far one press of a stepper moves a *number* box -- the damage, armour
#: and property ranges, whose top is :data:`~app.models.NUMBER_MAX`.  The level
#: and requirement boxes step by one, because that is the scale they are on: a
#: range of 0 to 110 or 0 to 500 is walked.  A damage figure is in the
#: thousands, and a box that took four thousand presses to cross is a box
#: nobody uses the arrows on; ten is a step a thumb can hold down.
STEP_BY = 10

#: The roll at the front of a property line: its sign, its number and its per
#: cent sign if it has one.  It is the part that differs from item to item --
#: ``+15% to Fire Damage`` and ``+38% to Fire Damage`` are one stat -- so it is
#: the part the suggestions leave off.
_ROLL = re.compile(r"^[-+]?\d+(?:\.\d+)?\s*%?\s*")


def vocabulary(cards) -> list[str]:
    """The stats to offer in the property rows, off the collection's own cards.

    The reference offers its own curated vocabulary, which is a list of every
    stat the *game* has; this offers the stats the player's items actually
    *show*, which is a shorter list and the one that answers the question they
    are asking.  Both are a list of names to type, and the names are the same
    names -- the game's own wording, because that is what the lines say.

    Sorted and deduplicated, so a collection of two hundred items with the same
    six stats offers six suggestions and not two hundred.
    """
    said = set()
    for card in cards:
        for line in card.properties:
            words = _ROLL.sub("", line).strip()
            if words:
                said.add(words.casefold())
    return sorted(said)


def _row_label(text: str) -> QLabel:
    """The name a row's controls are read against, right up against them."""
    label = QLabel(text)
    label.setStyleSheet(f"color: {LABEL}; font-size: {NAME_PX}px;")
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    label.setMinimumWidth(LABEL_PX)
    return label


def _note(text: str) -> QLabel:
    """A line under a row, in the ink of a side-note.

    The reference's own hints are written this way -- under the chips they are
    about, against the field rather than the label -- and they earn their line:
    a row of chips starts dark and means something *by* being dark, which is
    not a thing a row of boxes can say on its own.
    """
    label = QLabel(text)
    label.setStyleSheet(f"color: {DIM}; font-size: {NAME_PX}px;")
    label.setWordWrap(True)
    return label


def _class_indent() -> int:
    """How far the Class section's row is set in from the section's own edge.

    The row has nothing naming it.  Flush with the caption above it the boxes
    read as a row that had fallen out of the form -- the user's own reading of
    them there, and their own measure for where the row belongs: *"align with
    the other sections like maybe the strength text of the previous stat
    requirements section"*.  So the row begins where a name in the label column
    begins, and ``Strength`` is the anchor because it is the longest of the
    four requirement names written directly above this row.

    Measured in the panel's own face rather than pinned as a number, so that
    the row lines up with the names on any face the application is drawn in: a
    name is right-aligned in :data:`LABEL_PX`, so it begins that column's width
    back from its end.  The face is the one :func:`_row_label` writes in -- the
    application's own family, taken from the application because that is where
    the labels inherit it from, at :data:`NAME_PX`.

    A column with no room left in it (a name as wide as :data:`LABEL_PX`) gives
    up and starts at the edge: there is no name to line up under, and a
    negative inset is a row drawn out of its own section.
    """
    face = QFont(QApplication.font())
    face.setPixelSize(NAME_PX)
    return max(0, LABEL_PX - QFontMetrics(face).horizontalAdvance("Strength"))


def _spin(value: int, top: int, tip: str, step: int = 1) -> SpinBox:
    """One end of a range: a number box with its whole span on it."""
    spin = SpinBox()
    spin.setRange(0, top)
    spin.setValue(value)
    spin.setSingleStep(step)
    spin.setToolTip(tip)
    spin.setMaximumWidth(84)
    return spin


def _pair(low: SpinBox, high: SpinBox) -> QWidget:
    """Two number boxes and the word between them, as one control."""
    row = QWidget()
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    line.setSpacing(6)
    between = QLabel("to")
    between.setStyleSheet(f"color: {DIM};")
    line.addWidget(low)
    line.addWidget(between)
    line.addWidget(high)
    line.addStretch(1)
    return row


def _completer(words: Sequence[str], editor: QLineEdit) -> QCompleter:
    """The suggestions under one of the property rows' text boxes.

    Matched by containment rather than from the start, because the vocabulary
    is a list of the *sentences* items say rather than a list of names: a
    player who remembers ``fire damage`` should not have to remember which
    words come before it.
    """
    completer = QCompleter(list(words), editor)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    return completer


def _element_pair(spins: dict, element: str) -> tuple[int, int]:
    """Where one of the Damage or Armor rows stands, as a pair."""
    low, high = spins[element]
    return low.value(), high.value()


def _elements_chosen(spins: dict) -> tuple[tuple[str, int, int], ...]:
    """The element rows that have moved off the range that covers everything.

    Only the moved ones, in the game's own order of elements: a row nobody
    touched is not asking anything, and the model reads the absence of an
    element from the *tuple* rather than comparing every pair against the rest
    range a second time -- see :meth:`app.models.CollectionFilter.set_damage`.
    """
    return tuple(
        (element, *_element_pair(spins, element))
        for element in ELEMENTS
        if _element_pair(spins, element) != ELEMENT_REST
    )


def _write_elements(spins: dict, chosen) -> None:
    """Put a search's element rows back on the boxes, the rest at rest."""
    by_name = {element: (low, high) for element, low, high in chosen}
    for element, (low, high) in spins.items():
        wanted = by_name.get(element, ELEMENT_REST)
        low.setValue(wanted[0])
        high.setValue(wanted[1])


def _chips(widgets: Sequence[QWidget]) -> QWidget:
    """A row of tick boxes, left-aligned and no wider than it needs."""
    row = QWidget()
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    line.setSpacing(6)
    for widget in widgets:
        line.addWidget(widget)
    line.addStretch(1)
    return row


def _set_in(widget: QWidget, left: int) -> QWidget:
    """A widget set in from the left edge it would otherwise be drawn at.

    A holder and not a margin on the widget itself, so that it works the same
    for a row of boxes and for a sentence that wraps: both are laid out at the
    width the holder has left for them, and neither has to know it was moved.
    """
    holder = QWidget()
    line = QHBoxLayout(holder)
    line.setContentsMargins(left, 0, 0, 0)
    line.setSpacing(0)
    line.addWidget(widget)
    return holder


def _empty(layout) -> None:
    """Take every widget out of a layout, and take the widgets away with it.

    Hidden, then detached, then deleted.  Hidden because a widget out of a
    layout but still visible keeps its last geometry and stays on screen
    until the event loop gets round to the deferred delete, which is a grid
    drawing the boxes it has just replaced underneath the ones that replaced
    them.  Hidden *before* the detach because Qt hides a widget handed to
    ``setParent(None)`` only implicitly -- hidden, but not explicitly -- and
    that is the state Qt's own deferred re-show undoes, as a window
    (CardWall.forget, and the picture it names).  Deleted because what comes
    here is replaced, not pooled: detaching one used to be the last anyone
    heard of it.
    """
    while layout.count():
        widget = layout.takeAt(0).widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()


class Panel(QFrame):
    """The panel itself: the title, the form, and the two buttons under it.

    A ``QFrame`` rather than a plain ``QWidget`` because it is a *styled*
    widget -- the sheet gives it a ground and an edge, and a plain widget has
    nothing to draw either with.  The comparison screen's panel is the same
    class of thing, spelled where it is used rather than shared, because the
    two share a shape and no behaviour.

    It takes its own presses, which is what makes the backdrop's click mean
    "the panel is not what I aimed at": a widget that ignores a press passes it
    up to its parent, so a click on the title, on the gap under the last
    section, on any label in the form, reaches here and stops -- and the
    backdrop keeps only the presses actually aimed at it.
    """

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        event.accept()


class Section(QWidget):
    """One titled group of rows: a caption over a two-column form."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(9)

        caption = QLabel(title)
        caption.setStyleSheet(f"color: {HEAD}; font-size: 12px;")
        column.addWidget(caption)

        self.rows = QFormLayout()
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setHorizontalSpacing(10)
        self.rows.setVerticalSpacing(7)
        self.rows.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.rows.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        column.addLayout(self.rows)

    def row(self, label: str, editor: QWidget) -> None:
        self.rows.addRow(_row_label(label), editor)

    def note(self, text: str) -> None:
        """A hint under the row above, against the field and not the label."""
        self.rows.addRow(_row_label(""), _note(text))

    def wide(self, editor: QWidget, left: int = 0) -> None:
        """A row with no name of its own, running the width of the section.

        Two of the sections are not a name and a control: the stat requirements
        are read as two pairs, each pair naming itself, and the class boxes are
        a row of boxes with nothing to name them -- the reference draws both
        flush with the section's own edge.  A row of the form would have set
        them a label's width in from that edge, which is what ``For`` was doing
        and what the user asked to have taken away.

        ``left`` sets such a row back in from that edge by hand, for the one
        row that has no name and still does not read as part of the caption
        above it -- see :func:`_class_indent`.  It is a margin on a holder
        rather than a label of its own, so that the row stays nameless: nothing
        is written where a name would be.
        """
        if left:
            editor = _set_in(editor, left)
        self.rows.addRow(editor)


class Body(QScrollArea):
    """The column of sections, as wide as the form that stands in it.

    A scroll area's own width hint is a guess rather than a measurement -- Qt
    hands it a few dozen ems whatever is inside -- and the guess is narrower
    than this form.  The wide rows were squeezed into it and the difference was
    handed to a sideways scroll bar, which is what the user saw and asked never
    to see again: the panel is this column's width and nothing else, so the
    hint is taken from the content instead.  The panel opens at the width the
    form asks to be drawn at, up to :data:`PANEL_MAX` and the room the window
    has, and every row is drawn at the size its own contents asked for.

    The sideways bar is *off* rather than merely unwanted, because those are
    two different statements: nothing here is meant to be reached by scrolling
    across, and a bar that came back the moment a row was a pixel too wide
    would be the same complaint again.  Up and down still scrolls -- the form
    is longer than any window -- and that is the one direction the panel reads
    in.

    A window narrower than the form is the one case left over, and it is the
    window's answer that is the smaller one: the panel is given the room there
    is and the last few pixels of a wide row are cut off, rather than the panel
    offering to slide across.  A window that narrow is one the collection
    behind it is already unreadable in.
    """

    def sizeHint(self) -> QSize:  # noqa: N802 -- Qt naming
        inside = self.widget()
        if inside is None:
            return super().sizeHint()
        # The form's own width, plus the strip the scroll bar takes when it
        # stands beside it: a hint that forgot the bar would be a hint whose
        # last few pixels were the ones clipped.
        bare = super().sizeHint()
        return QSize(
            inside.sizeHint().width() + self.verticalScrollBar().sizeHint().width(),
            bare.height(),
        )


class TypeGrid(QWidget):
    """Every kind the *game* has, in one grid, under a strip of buttons.

    A second view of the rail and not a second filter: the shape and the order
    are :func:`app.sidebar.arranged`'s, which is what the rail draws from, and
    the ticks are the same ticks -- the window writes them onto the rail when
    the draft is committed rather than ANDing two sets here.  So a player who
    ticks Boots on this panel and a player who ticks Boots on the rail have
    asked for the same collection.

    What it draws is the game's own vocabulary rather than the collection's:
    :data:`tl2stash.taxonomy.KIND_PLACES`, with whatever the collection holds
    that the taxonomy does not know added to it -- a mod's kinds, and the empty
    kind an item with no ``UNITTYPE`` word carries.  The rail is a description
    of what is *here* and can only offer what the player has; this is a form,
    and a form that could only name what is already on hand could only ever
    narrow.  The reference keeps its own type list for the same reason, and
    spells it out: ``Fist``, ``Rifle``, ``2H Mace`` and ``2H Sword`` stand in
    it although no item in its corpus carries one, *"kept because UNITTYPE can
    still emit them"*.

    Two things follow, and both are the point rather than a side effect.  A
    group stays on the strip whether or not the collection has a kind under it,
    because the group has kinds in it either way.  And a kind ticked here stays
    ticked when the collection loses its last one: the kind is still a kind, so
    the tick is no longer the collection's business -- which is what the rail
    cannot say and this can.

    The strip is a *bulk toggle* and not a set of tabs, which is the
    reference's own reading of this control and the one the user asked to have
    mimicked: every group is on screen at once, under its own heading, and a
    group button ticks every kind below it -- or unticks them all when they are
    already ticked.  Nothing is hidden and nothing moves, so there is no state
    a player can lose by pressing one, and ``All`` is the same toggle over
    every kind there is.

    **Every box is ticked when the panel opens**, because an empty set of
    places is the model's word for *any kind* -- see
    :meth:`app.models.CollectionFilter.set_places` -- so the grid's resting
    state is everything on, and :meth:`ticks` reads it back as the empty set
    again.  It is the reference's ``coverAll``, and the reason a Search pressed
    without touching this grid leaves the rail exactly where it was rather than
    painting forty ticks on it.

    What is *not* here is any count.  The rail's numbers are what the filters
    would leave, and there is nothing to count against a draft: a number beside
    a box nobody has searched for yet would be the numbers of a list the player
    is not looking at, which is the one thing a count must never be.

    The boxes are the game's kinds rather than the current answer's, also like
    the reference: a box that vanished because of a filter the same panel set
    is a box the player cannot tick, so a search could never be widened from
    here -- and a box that vanished because the collection has none of that
    kind is the same fault with a longer memory.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        #: Everything the grid draws: the game's kinds, and the collection's
        #: strangers.  A kind's *box* is a thing the player can ask for, and
        #: what the player can ask for is the game's list -- see the class
        #: docstring -- so this is a wider set than the rail's and the ticks
        #: are read against it rather than against what the collection holds.
        self._drawn: frozenset[Place] = frozenset()
        self._ticked: set[Place] = set()
        self._boxes: dict[Place, QCheckBox] = {}
        self._tabs: dict[str, QPushButton] = {}
        self._updating = False

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(9)

        self._tab_row = QHBoxLayout()
        self._tab_row.setContentsMargins(0, 0, 0, 0)
        self._tab_row.setSpacing(4)
        column.addLayout(self._tab_row)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(4)
        # Four even columns, so the boxes stand in columns down the grid rather
        # than wherever the longest word in each row puts them.  Without this
        # the columns take their own widths and a row of four kinds comes out
        # as ragged as the words in it.
        for column_index in range(COLUMNS):
            self._grid.setColumnStretch(column_index, 1)
        column.addLayout(self._grid)

    # -- what it is told --------------------------------------------------

    def set_kinds(self, places) -> None:
        """Draw the game's kinds with the collection's strangers among them.

        ``places`` is what the collection holds, and the one thing it changes
        about the grid: a kind the taxonomy does not know -- a mod's, or one
        whose data file is gone -- has no box otherwise, and a box is the only
        way to ask for it.  Called after every poll, and it does nothing at all
        when the *drawn* set has not moved, which is the same bargain the rail
        makes: a kind of the game's arriving in the collection changes nothing
        on screen, and a grid rebuilt under the pointer is a grid that loses
        the click.

        A grid that was wholly ticked stays wholly ticked across the change,
        which is the resting state being carried over rather than a new kind
        arriving unticked: the collection gains and loses a kind every time the
        player moves an item, and a panel left open on a poll must not come
        back narrowed by the item that happened to arrive.  A grid the player
        *has* narrowed keeps only the ticks it still has -- which for the
        game's own kinds is all of them, however the collection moves.
        """
        drawn = KIND_PLACES | {tuple(place) for place in places}
        if drawn == self._drawn:
            return
        whole = self._ticked == set(self._drawn)
        self._drawn = frozenset(drawn)
        self._ticked = set(drawn) if whole else self._ticked & drawn
        self._rebuild()

    def ticks(self) -> set[Place]:
        """The kinds ticked, flattened -- a kind is itself and no subtree.

        Empty when every kind is ticked, because that is what the ticked grid
        *means*: the panel is an allow-list whose empty state is not "nothing"
        but "anything", so the resting state of the control and the resting
        state of the search are the same state written twice -- see
        :meth:`tick` for the other direction of the same round trip.

        What is handed back is the rail's own value, and it can name kinds the
        rail is not drawing because the collection has none of them: a kind
        that is not *there* is not an item that fails to match, so the two sets
        narrow to the same collection -- see
        :meth:`app.models.CollectionFilter.set_places`, whose empty set means
        every kind and whose named set means only those.
        """
        if self._ticked == set(self._drawn):
            return set()
        return set(self._ticked)

    def tick(self, places) -> None:
        """Tick these kinds and nothing else -- and every kind, given none.

        The other half of :meth:`ticks`, and the reason a panel opened on a
        search that names no kinds comes up with the whole grid ticked: no
        kinds ticked is not a grid the player would recognise as *their*
        search, and an empty grid and a full one mean the same thing to the
        model.  A search that does name kinds ticks exactly those of them the
        grid draws -- and a name it does not draw is a kind from neither the
        game's list nor the collection's, which is no kind at all.
        """
        named = {tuple(place) for place in places}
        self._ticked = set(self._drawn) if not named else named & self._drawn
        self._fill()

    # -- the user ---------------------------------------------------------

    def _toggle(self, group: str) -> None:
        """A group button: tick everything under it, or untick it if it is whole.

        The reference's own rule, and the one the user asked for -- *"hitting
        the respective buttons should select all items under that subsection"*
        -- with the second press being how a player clears one group out of a
        grid that opened fully ticked.  ``All`` is the same press over every
        kind there is.
        """
        here = self._under(group)
        whole = bool(here) and all(place in self._ticked for place in here)
        for place in here:
            if whole:
                self._ticked.discard(place)
            else:
                self._ticked.add(place)
        self._fill()

    def _moved(self, *_) -> None:
        """A box was ticked.  Guarded, because :meth:`_fill` writes them all."""
        if self._updating:
            return
        for place, box in self._boxes.items():
            if box.isChecked():
                self._ticked.add(place)
            else:
                self._ticked.discard(place)
        self._ink_tabs()

    # -- drawing ----------------------------------------------------------

    def _under(self, group: str) -> list[Place]:
        """The kinds under one group button, in the rail's own order.

        :func:`arranged`'s shape, walked rather than sorted again: the rail's
        order is the order of the taxonomy's own table, and the one thing this
        grid must not do is invent a second one.
        """
        return [
            place
            for name, subgroups in arranged(self._drawn)
            if group == ALL_TYPES or name == group
            for _, here in subgroups
            for place in here
        ]

    def _heading(self, text: str, ink: str, indent: int = 0) -> QLabel:
        """One of the grid's two headings, in the rail's own voice.

        The same rule the rail is drawn by, since these head the same kinds:
        a group is the reference's tan and its own capitalisation, and a
        subgroup is the deeper tan, upper case, and set in a little from the
        left.  The *sizes* are one size, the body's -- what separates the three
        levels is the ink and the indent, which is what the user's first
        request settled on the rail and what is worth keeping the same here.
        """
        label = QLabel(text.upper() if indent else text)
        # One rule, so the air above a heading and the step in from the left
        # are the same kind of number in the same place -- a group opens a
        # little space over itself and a subgroup is set in under it.
        label.setStyleSheet(
            f"color: {ink}; font-size: {BODY_PX}px;"
            f" padding: {2 if indent else 6}px 0 1px {indent}px;"
        )
        return label

    def _rebuild(self) -> None:
        """Redraw the group buttons, then refill the grid from the new shape."""
        groups = [ALL_TYPES] + [name for name, _ in arranged(self._drawn)]
        _empty(self._tab_row)
        self._tabs = {}
        for name in groups:
            button = QPushButton(name)
            button.setObjectName("atab")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(
                "Tick every kind there is.\nPress again to untick them all."
                if name == ALL_TYPES
                else f"Tick every kind under {name}.\n"
                "Press again to untick them all."
            )
            button.clicked.connect(lambda _=False, group=name: self._toggle(group))
            self._tabs[name] = button
            self._tab_row.addWidget(button)
        self._tab_row.addStretch(1)
        self._fill()

    def _fill(self) -> None:
        """Put every group in the grid at once, four kinds to a row.

        Each group gets a heading spanning the whole width, each subgroup an
        indented one under it, and its kinds follow -- so a group never breaks
        across the gutter with a heading stranded at the bottom of a column,
        which is what the spanning cell is for.

        The list is :attr:`_drawn`'s, so it is the whole of the game's taxonomy
        with the collection's strangers folded in where their group puts them
        -- fifty-odd boxes on a panel that a collection of four kinds used to
        give a dozen.  That it is long is the point of it: this is a form to ask
        questions of, not a description of the answer.
        """
        _empty(self._grid)
        self._boxes = {}
        self._updating = True
        try:
            row = 0
            for group, subgroups in arranged(self._drawn):
                self._grid.addWidget(self._heading(group, HEAD), row, 0, 1, COLUMNS)
                row += 1
                for subgroup, here in subgroups:
                    if subgroup is not None:
                        label = self._heading(subgroup, LABEL, SUBGROUP_INDENT)
                        self._grid.addWidget(label, row, 0, 1, COLUMNS)
                        row += 1
                    for i, place in enumerate(here):
                        box = QCheckBox(place[2] or UNCLASSIFIED)
                        box.setChecked(place in self._ticked)
                        box.setToolTip(" / ".join(word for word in place if word))
                        box.toggled.connect(self._moved)
                        self._boxes[place] = box
                        self._grid.addWidget(box, row + i // COLUMNS, i % COLUMNS)
                    row += (len(here) + COLUMNS - 1) // COLUMNS
        finally:
            self._updating = False
        self._ink_tabs()

    def _ink_tabs(self) -> None:
        """Say on a group button what the rail says on a heading: all, some, none.

        The reference's own three states, and its own argument for the middle
        one: with every kind ticked at rest, a player who unticks one armour
        type would otherwise see ``Armor`` go dark, which reads as *no armour*
        when it means *nearly all armour*.  Two channels carry the three, so
        they cannot be confused for one another -- the border goes from the
        control ink to gold, and the fill and the word stay where they are
        until the group is wholly ticked.

        All three are drawn on the button itself rather than left to the sheet,
        because the state is the button's and the sheet has one rule for a
        button: a group's ink is not a variant of the panel's buttons, it is a
        reading of the boxes under it.
        """
        for name, button in self._tabs.items():
            here = self._under(name)
            on = sum(1 for place in here if place in self._ticked)
            if not here or on == 0:
                ink, border = CHALK, CHALK
            elif on == len(here):
                ink, border = GOLD, GOLD
            else:
                ink, border = LABEL, GOLD
            button.setStyleSheet(
                "QPushButton {"
                f" color: {ink}; border: 1px solid {border};"
                " border-radius: 3px; padding: 3px 9px;"
                "}"
            )


class StatRow(QWidget):
    """One property row: what to look for, its range, and the way out.

    Three controls because the reference's own row has three, and they are the
    three parts of the question: which stat, how much of it, and -- when the
    row was a mistake -- a cross to take it away.  ``value`` and ``set_value``
    are the whole of what the panel asks of it; the row knows nothing about
    searching, and nothing about the other rows.

    The text box suggests the collection's own property lines, by containment
    rather than by prefix: the vocabulary is a list of sentences the items
    happen to say, and a player who remembers ``fire damage`` should not have
    to remember which words come before it.
    """

    def __init__(self, vocabulary: Sequence[str], on_remove, parent=None) -> None:
        super().__init__(parent)
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)

        self.text = QLineEdit()
        self.text.setObjectName("advstat")
        self.text.setPlaceholderText("a stat, as the item says it")
        self.text.setClearButtonEnabled(True)
        self.text.setMinimumWidth(150)
        self.text.setCompleter(_completer(vocabulary, self.text))
        self.text.setToolTip(
            "The words to look for among the item's own lines.\n"
            "Start typing and the stats your collection actually shows\n"
            "are suggested, which is a shorter list than the game has."
        )

        self.low = _spin(
            0,
            NUMBER_MAX,
            "The lowest the number on such a line may be.  The number\n"
            "read is the first one the line states.\n"
            f"Left at 0 and {NUMBER_MAX} the row asks only whether\n"
            "the item says it at all.",
            step=STEP_BY,
        )
        self.high = _spin(
            NUMBER_MAX, NUMBER_MAX, "The highest it may be.", step=STEP_BY
        )
        self.remove = QPushButton("✕")
        self.remove.setObjectName("arem")
        self.remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove.setToolTip("Take this row away.")
        self.remove.clicked.connect(lambda: on_remove(self))

        line.addWidget(self.text, stretch=1)
        line.addWidget(self.low)
        between = QLabel("to")
        between.setStyleSheet(f"color: {DIM};")
        line.addWidget(between)
        line.addWidget(self.high)
        line.addWidget(self.remove)

    def value(self) -> tuple[str, int, int]:
        """This row as the search spells it: the words, and the two ends."""
        return self.text.text().strip(), self.low.value(), self.high.value()

    def set_value(self, text: str, low: int, high: int) -> None:
        """Put one of a search's rows on the controls."""
        self.text.setText(text)
        self.low.setValue(low)
        self.high.setValue(high)


#: The panel's own rules, over the window's.  The ground and the edge are the
#: card's -- the panel is the same kind of thing as a card, a surface the
#: window's own colour does not reach -- and everything else is the window's
#: control language: outlined boxes, the light ink, the labels in the tans the
#: rail's rows wear.
_STYLE = f"""
#apanel {{
    background-color: {PANEL};
    border: 1px solid {LINE};
    border-radius: 4px;
}}
#atitle {{
    color: {BODY};
    font-size: 15px;
    font-weight: 600;
    padding-left: 2px;
}}
#aclose {{
    color: {DIM};
    background: transparent;
    border: 0;
    font-size: 15px;
    padding: 2px 8px;
}}
#aclose:hover {{ color: {HEAD}; }}
/* The body scrolls, and both it and the widget inside it have to be told not to
   paint: a scroll area's viewport comes with the palette's own ground, which
   would put a rectangle of the *window's* colour in the middle of a panel that
   is the card's. */
#abody, #abody > QWidget > QWidget {{
    background: transparent;
    border: 0;
}}
#areset, #asearch {{
    color: {PALE};
    background: transparent;
    border: 1px solid {PALE};
    border-radius: 3px;
    padding: 3px 12px;
    font-size: 12px;
}}
#areset:hover, #asearch:hover {{ color: {CHALK}; border-color: {CHALK}; }}
/* The two that are not part of the form's own grammar: the way to add a
   property row, and the way to take one away.  Both are the footer's outline
   in the dimmer ink -- they are means rather than ends, and the one control
   here that ends anything is `Search`. */
#aadd {{
    color: {PALE};
    background: transparent;
    border: 1px solid {PALE};
    border-radius: 3px;
    padding: 2px 10px;
    font-size: 11px;
}}
#aadd:hover {{ color: {CHALK}; border-color: {CHALK}; }}
#arem {{
    color: {DIM};
    background: transparent;
    border: 0;
    font-size: 13px;
    padding: 0 4px;
}}
#arem:hover {{ color: {HEAD}; }}
/* The commit, in the ink the reference gives the button that ends a form: the
   one control here that is not an alternative to anything. */
#asearch {{ color: {GOLD}; border-color: {GOLD}; }}
"""


class AdvancedSearchOverlay(QWidget):
    """The panel, over the window, editing one search at a time.

    A child of the window rather than a window of its own, like the comparison
    screen and for the same reason: what it narrows is behind it, and a second
    window can be lost behind the game.  It does not touch the collection --
    what it emits is an :class:`~app.models.Advanced`, and the window is what
    writes that onto the bar and the rail.
    """

    #: A search to apply.  Emitted only by `Search`: everything else here puts
    #: the panel away with the collection exactly as it was.
    searched = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("advanced")
        self._shape: list[Place] = []

        # The backdrop, painted rather than styled: a plain QWidget is not a
        # styled widget, so a `background` rule here would draw nothing.  The
        # same scrim the comparison screen draws, and deliberately: both are
        # the window dimmed rather than a colour of their own.
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(*SCRIM))
        self.setPalette(palette)

        self._panel = self._build_panel()
        self._inset = QHBoxLayout(self)
        self._inset.setSpacing(0)
        self._inset.addStretch(1)
        self._inset.addWidget(self._panel)
        self._inset.addStretch(1)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setVisible(False)

    # -- opening and closing ---------------------------------------------

    def set_kinds(self, places) -> None:
        """Tell the panel which kinds the collection holds.

        Called after every poll, and passed straight to the Type grid, which
        draws the game's own kinds around them and rebuilds only when what it
        draws has moved.
        """
        wanted = list(places)
        if wanted == self._shape:
            return
        self._shape = wanted
        self.types.set_kinds(wanted)
        self._remeasure()

    def _remeasure(self) -> None:
        """Let the panel widen if the form inside it has.

        The panel is as wide as the form it holds, and Qt works that width out
        once -- while the Type grid is still empty, because the panel is built
        before it is given anything to draw.  A grid filled with the game's
        kinds afterwards is a form half again as wide as the panel that was
        measured around it, and the extra is not a sideways scroll: the body
        scrolls down and not across, so it is the ends of the rows.  Asking the
        body to say how wide it is asks the form again -- see
        :meth:`Body.sizeHint` -- and the panel is laid out around the answer.
        """
        self._scroll.updateGeometry()

    def open_for(
        self,
        state: Advanced,
        classes: Sequence[str] = CLASSES,
        vocabulary: Sequence[str] = (),
    ) -> None:
        """Open on this search, with the class boxes only if there are classes.

        ``classes`` is the four words when the game's data answers the question
        and nothing at all when it does not -- see
        :meth:`~tl2stash.gamedata.GameData.has_classes`, which is what the
        caller asks.  ``vocabulary`` is the collection's own
        property lines, with their rolls taken off, for the Stats section's
        suggestions -- see :meth:`app.window.MainWindow._stat_vocabulary`.
        """
        self._offer_vocabulary(vocabulary)
        self._write(state)
        self._offer_classes(classes)

        parent = self.parentWidget()
        if parent is not None:
            parent.installEventFilter(self)
            self._fit()
        self.raise_()
        self.show()
        self.setFocus()
        # And once the panel is up, because a hidden widget is not laid out: the
        # form has been given the grid's kinds on the way in, and this is the
        # moment the panel can be measured around what they came to.
        self._remeasure()

    def draft(self) -> Advanced:
        """What the controls say right now, as one search.

        Two of the fields are *reduced* rather than read off a control one for
        one: an element row left covering everything is not part of the search,
        and neither is a property row nobody has written a word into -- a row
        added and abandoned is a row the player did not mean.
        """
        rows = [row.value() for row in self.stat_rows]
        return Advanced(
            text=self.name.text(),
            tiers=frozenset(
                word for word, chip in self.rarity_chips.items() if chip.isChecked()
            ),
            low=self.player_low.value(),
            high=self.player_high.value(),
            item_low=self.item_low.value(),
            item_high=self.item_high.value(),
            sockets=frozenset(
                count for count, chip in self.socket_chips.items() if chip.isChecked()
            ),
            reqs=tuple(
                (self.req_spins[word][0].value(), self.req_spins[word][1].value())
                for word in REQ_WORDS
            ),
            classes=frozenset(
                word
                for word, box in self.class_boxes.items()
                if box.isChecked() and box.isEnabled()
            ),
            damage=_elements_chosen(self.damage_spins),
            armor=_elements_chosen(self.armor_spins),
            stats=tuple(row for row in rows if row[0]),
            bonuses=self.bonuses_box.isChecked(),
            places=frozenset(self.types.ticks()),
        )

    def panel(self) -> QWidget:
        """The panel, which is everything the backdrop is not."""
        return self._panel

    def dismiss(self) -> None:
        """Put the window back the way it was, applying nothing."""
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        self.hide()

    def reset(self) -> None:
        """Put every control back to the resting state, applying nothing.

        A draft thrown away rather than a search run: `Reset` and `Search` are
        two words and this is the difference between them.  The kinds go back
        to none ticked with everything else, which is where the rail starts.
        """
        self._write(Advanced())

    # -- the pieces ------------------------------------------------------

    def _build_panel(self) -> Panel:
        panel = Panel()
        panel.setObjectName("apanel")
        # On the panel rather than on each piece, so that the sheet reaches the
        # title and the two buttons as well as the form: they are the panel's,
        # and a sheet set on a widget stops at its children.
        panel.setStyleSheet(_STYLE)
        panel.setMaximumWidth(PANEL_MAX)

        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._header())
        column.addWidget(Hairline())
        column.addWidget(self._body(), stretch=1)
        column.addWidget(Hairline())
        column.addWidget(self._footer())
        return panel

    def _header(self) -> QWidget:
        head = QWidget()
        row = QHBoxLayout(head)
        row.setContentsMargins(PAD + 2, 9, PAD + 2, 9)
        row.setSpacing(8)

        title = QLabel("Advanced Search")
        title.setObjectName("atitle")
        row.addWidget(title)
        row.addStretch(1)

        # The multiplication sign, which is what a close button is drawn as in
        # every window there is -- the comparison screen's own, in this panel.
        close = QPushButton("✕")
        close.setObjectName("aclose")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("Close without searching (Esc)")
        close.clicked.connect(self.dismiss)
        row.addWidget(close)
        return head

    def _body(self) -> Body:
        """The sections, in the reference's own order, in a column that scrolls.

        The reference folds its sections; this scrolls them instead, because a
        fold is a state the panel would have to remember and the panel is
        thrown away on every Esc -- and seven sections of a form is a longer
        scroll than four, but a scroll either way.  Down only, and the column
        is what gives the panel its width rather than the other way round --
        see :class:`Body`.
        """
        scroll = Body()
        #: Kept, because it is the one piece that knows how wide the form is
        #: -- see :meth:`AdvancedSearchOverlay._remeasure`.
        self._scroll = scroll
        scroll.setObjectName("abody")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(PAD, PAD - 4, PAD, PAD)
        column.setSpacing(PAD + 4)
        damage, self.damage_spins = self._elements("Damage")
        armor, self.armor_spins = self._elements("Armor")
        for section in (
            self._general(),
            self._type_section(),
            self._requirements(),
            self._classes(),
            damage,
            armor,
            self._stats_section(),
        ):
            column.addWidget(section)
        column.addStretch(1)

        scroll.setWidget(content)
        return scroll

    def _footer(self) -> QWidget:
        foot = QWidget()
        row = QHBoxLayout(foot)
        row.setContentsMargins(PAD, 9, PAD, 9)
        row.setSpacing(8)

        self.reset_button = QPushButton("Reset")
        self.reset_button.setObjectName("areset")
        self.reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_button.setToolTip("Put every control here back to the resting state.")
        self.reset_button.clicked.connect(self.reset)
        row.addWidget(self.reset_button)
        row.addStretch(1)

        self.search_button = QPushButton("Search")
        self.search_button.setObjectName("asearch")
        self.search_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_button.setToolTip(
            "Narrow the collection to what these say, and close this panel."
        )
        self.search_button.clicked.connect(self._searched)
        row.addWidget(self.search_button)
        return foot

    # -- the sections ----------------------------------------------------

    def _general(self) -> Section:
        section = Section("General")

        # The bar's own search box, in the panel: the sheet outlines the two by
        # name, and this one is *named* rather than bare for the reason the
        # other is -- a number box holds a line edit of its own, so a rule on
        # ``QLineEdit`` alone would reach inside every spin box here and draw a
        # second border a few pixels inside the first.
        self.name = QLineEdit()
        self.name.setObjectName("advname")
        self.name.setPlaceholderText("name")
        self.name.setClearButtonEnabled(True)
        self.name.setToolTip(
            "Show only the items whose name contains this, as the search box\n"
            "over the collection does."
        )
        section.row("Name", self.name)

        self.item_low = _spin(
            0,
            LEVEL_MAX,
            "The item levels to show, both ends included.\n"
            "An item of level 0 -- a socketable, or a potion -- is in a range\n"
            f"that starts at 0, and 0 to {LEVEL_MAX} is every level there is.",
        )
        self.item_high = _spin(
            LEVEL_MAX, LEVEL_MAX, "The item levels to show, both ends included."
        )
        # The *other* level range.  This one is what the item is; the one below
        # is what it asks of the character, and the two are different numbers.
        section.row("Item Level", _pair(self.item_low, self.item_high))

        self.player_low = _spin(
            0,
            LEVEL_MAX,
            "The player levels to show, both ends included: an item is shown\n"
            "when the level it requires falls in this range.\n"
            "Anything the game gates on nothing is always shown.",
        )
        self.player_high = _spin(
            LEVEL_MAX, LEVEL_MAX, "The player levels to show, both ends included."
        )
        section.row("Player Level", _pair(self.player_low, self.player_high))

        self.socket_chips: dict[int, QCheckBox] = {}
        for count in SOCKET_COUNTS:
            chip = QCheckBox(str(count))
            chip.setToolTip(f"Show only the items with exactly {count} sockets.")
            self.socket_chips[count] = chip
        section.row("Sockets", _chips(list(self.socket_chips.values())))
        section.note("No chip ticked means any number of sockets.")

        self.rarity_chips: dict[str, QCheckBox] = {}
        for word in TIER_CHIPS:
            chip = QCheckBox(word)
            chip.setStyleSheet(chip_style(TIER_INK[word.lower()]))
            chip.setToolTip(
                f"Show only the {word.lower()} items.  No chip ticked shows\n"
                "every rarity, including the items that have none."
            )
            self.rarity_chips[word] = chip
        section.row("Rarity", _chips(list(self.rarity_chips.values())))
        return section

    def _type_section(self) -> Section:
        section = Section("Type")
        self.types = TypeGrid()
        section.row("Kinds", self.types)
        return section

    def _requirements(self) -> Section:
        """The four attributes, two of them to a line, and nothing under them.

        Two to a line is the reference's own reading of these four: they are
        four short rows -- a name and two small numbers -- and a row each makes
        the section twice as tall as it needs to be, on a panel that is already
        the longest thing here.  So they stand in a two-column grid, each pair
        naming itself in the label ink the rest of the form's rows name
        themselves in, which is what makes the pairing readable: the second
        column's pair is *Dexterity's* because ``Dexterity`` stands beside it,
        not because of where it is in a line of four.

        The section used to carry a line saying that an item is worn either by
        the player level or by these attributes, so these rows narrow the stat
        half of that.  The user asked for the panel's sections to be rows and
        nothing else, so the sentence is on the low box of each row instead --
        which is where the rest of that reading already is, and where a reader
        who wonders what the number means will hover anyway.  Worth writing
        down because the sentence is not lost and a later reader should not put
        it back on the face of the panel.
        """
        section = Section("Stat Requirements")
        self.req_spins: dict[str, tuple[SpinBox, SpinBox]] = {}

        cells = QWidget()
        grid = QGridLayout(cells)
        grid.setContentsMargins(0, 0, 0, 0)
        # The form's own gaps, so that a pair reads the way every other row
        # here does, and the two cells stand the same distance apart as a label
        # does from its own controls.
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)
        for index, word in enumerate(REQ_WORDS):
            low = _spin(
                0,
                REQ_MAX,
                f"The {word.lower()} an item asks for, from 0.\n"
                "An item that asks for none of it asks for 0, so a floor\n"
                "leaves it out and a ceiling does not.  An item is worn\n"
                "by the player level or by these attributes, so these\n"
                "rows narrow the stat half of that.",
            )
            high = _spin(REQ_MAX, REQ_MAX, f"The {word.lower()} an item asks for, to.")
            self.req_spins[word] = (low, high)
            line, column = divmod(index, 2)
            grid.addWidget(_row_label(word), line, column * 2)
            grid.addWidget(_pair(low, high), line, column * 2 + 1)
        # The two pairs split what is left of the line and the names stay at
        # their own width, which is what keeps the second cell's name against
        # the first cell's controls rather than halfway across the section.
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        section.wide(cells)
        return section

    def _classes(self) -> Section:
        """The class boxes lined up with the sections above.

        Nothing names this row.  ``For`` was a word standing in the label
        column so that the boxes would start where every other row's controls
        start, and the user asked for the boxes themselves instead -- but with
        the word gone the boxes were flush with the caption's own edge, which
        reads as a row that has fallen out of the form rather than as the
        answer to it.  So they are set back in to where the sections above
        begin their rows, the x a name in the label column starts at: the
        reference's own reading of the same four boxes, at the user's own
        measure -- see :func:`_class_indent`.

        Nothing is said under them.  There was a note here once, holding the
        one rule of the five that reads backwards -- an item naming no class is
        shown whatever is ticked -- and a line for the case where there was
        nothing to narrow by at all; the user asked for the text gone, and the
        rule went where the section's other removed notes went, onto the boxes
        themselves.  The line for the empty case is simply gone: the classes
        now come from the game's own files, so the state it described is one no
        real install can reach.
        """
        section = Section("Class")
        self.class_boxes: dict[str, QCheckBox] = {}
        for word in CLASSES:
            box = QCheckBox(word)
            article = "an" if word[:1] in "AEIO" else "a"
            box.setToolTip(
                f"Show the items only {article} {word} may use.  No box ticked "
                "means every class, and an item that names no class is one any "
                "class may use, so it is shown whatever is ticked here."
            )
            self.class_boxes[word] = box
        section.wide(_chips(list(self.class_boxes.values())), left=_class_indent())
        return section

    def _elements(self, title: str) -> tuple[Section, dict]:
        """One of the two number sections: a range per element, and its boxes.

        Two of these are built, and they are built by the same code on purpose:
        the Damage section and the Armor section ask the same question of the
        same five types with the same rule, and two hand-written copies of five
        rows is two places for the fifth element to be missing from.

        The five rows are the whole vocabulary, so a row has no way to be
        *named* without a bound -- which is what the reference's own form does
        with an empty pair of boxes.  Here a row that has been moved at all is
        the naming, and the range it was moved to is the rest of the question.

        What used to stand under these rows -- that a named type has to be one
        the item carries, that the two ranges have to overlap, and that a row
        left covering everything asks nothing -- is on the boxes now, split
        across the pair the way the rest of each box's reading already is: the
        low box carries the type and the overlap, the high box the row at rest.
        The user asked for these sections to be rows and nothing else.
        """
        section = Section(title)
        spins: dict[str, tuple[SpinBox, SpinBox]] = {}
        for element in ELEMENTS:
            name = element.title()
            low = _spin(
                0,
                NUMBER_MAX,
                f"The lowest {element} {title.lower()} to show.\n"
                "A type named here has to be one the item carries, and the\n"
                "two ranges have to overlap: a sword rolling 14-28 passes a\n"
                "request for 20-30.  An item with none of it is left out as\n"
                "soon as either box of this row moves.",
                step=STEP_BY,
            )
            high = _spin(
                NUMBER_MAX,
                NUMBER_MAX,
                f"The highest {element} {title.lower()} to show.\n"
                "A row left at 0 and the top asks nothing.",
                step=STEP_BY,
            )
            spins[element] = (low, high)
            section.row(name, _pair(low, high))
        return section, spins

    def _stats_section(self) -> Section:
        """The property rows, the button that adds one, and the widening box.

        The rows are built and thrown away with the panel rather than made
        once: what a row holds is a *draft*, and a draft is thrown away on
        every Esc, so a row that outlived the panel would be a piece of a
        search nobody can see.

        What stood under it -- that a row is answered by one of the item's own
        lines, that the number read is the first one on that line, and that the
        suggestions are the stats the collection shows -- is on the rows
        themselves now, which is where those three facts are each about
        something: see :class:`StatRow`, whose two ends carry the reading, and
        the text box, whose tip says where the suggestions come from.
        """
        section = Section("Stats")
        self.stat_rows: list[StatRow] = []
        self._vocabulary: list[str] = []

        holder = QWidget()
        self._stat_list = QVBoxLayout(holder)
        self._stat_list.setContentsMargins(0, 0, 0, 0)
        self._stat_list.setSpacing(6)

        add = QPushButton("+ Add stat")
        add.setObjectName("aadd")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.setToolTip("Look for one more property.")
        add.clicked.connect(lambda: self._add_stat())
        self._stat_list.addWidget(add, alignment=Qt.AlignmentFlag.AlignLeft)
        section.row("", holder)

        self.bonuses_box = QCheckBox("Include set bonuses")
        self.bonuses_box.setToolTip(
            "Answer a row from the item's set bonuses as well as from its own\n"
            "lines.  A stat that exists only on a set's ladder is found by a\n"
            "row only while this is ticked."
        )
        section.row("", self.bonuses_box)
        return section

    def _add_stat(
        self, text: str = "", low: int = 0, high: int = NUMBER_MAX
    ) -> StatRow:
        """Put one more row above the add button, and hand it back."""
        row = StatRow(self._vocabulary, self._drop_stat)
        row.set_value(text, low, high)
        self.stat_rows.append(row)
        # Under the button rather than over it: the button is the section's
        # floor, and a row arriving above it keeps the pointer where it was.
        self._stat_list.insertWidget(self._stat_list.count() - 1, row)
        return row

    def _drop_stat(self, row: StatRow) -> None:
        """Take one row away -- the cross, and nothing else."""
        if row in self.stat_rows:
            self.stat_rows.remove(row)
        # Hidden before the detach, so the state is explicit and nothing
        # re-shows the row (CardWall.forget); the deferred delete lets the
        # click that got here -- the row's own -- finish first.
        row.hide()
        row.setParent(None)
        row.deleteLater()

    def _offer_stats(self, rows) -> None:
        """Fill the Stats section from a search: one row each, and no more."""
        for row in list(self.stat_rows):
            self._drop_stat(row)
        for text, low, high in rows:
            self._add_stat(text, low, high)

    def _offer_vocabulary(self, words: Sequence[str]) -> None:
        """Offer the collection's own property lines to the rows' text boxes."""
        self._vocabulary = sorted(words)
        for row in self.stat_rows:
            row.text.setCompleter(_completer(self._vocabulary, row.text))

    def _offer_classes(self, classes: Sequence[str]) -> None:
        """Offer the class boxes, or leave them dark when there is nothing."""
        known = bool(classes)
        for box in self.class_boxes.values():
            box.setEnabled(known)
            if not known:
                box.setChecked(False)

    # -- the user --------------------------------------------------------

    def _searched(self) -> None:
        self.searched.emit(self.draft())
        self.dismiss()

    def _write(self, state: Advanced) -> None:
        """Put a search on the controls.  One way in, for opening and resetting.

        One move either way -- the window is opening the panel on what the
        collection is already narrowed by, or the player has pressed Reset --
        so nothing here emits: the panel has one signal and it is the one
        `Search` sends.
        """
        self.name.setText(state.text)
        for word, chip in self.rarity_chips.items():
            chip.setChecked(word in state.tiers)
        self.player_low.setValue(state.low)
        self.player_high.setValue(state.high)
        self.item_low.setValue(state.item_low)
        self.item_high.setValue(state.item_high)
        for count, chip in self.socket_chips.items():
            chip.setChecked(count in state.sockets)
        for word, (low, high) in zip(REQ_WORDS, state.reqs):
            self.req_spins[word][0].setValue(low)
            self.req_spins[word][1].setValue(high)
        for word, box in self.class_boxes.items():
            box.setChecked(word in state.classes)
        _write_elements(self.damage_spins, state.damage)
        _write_elements(self.armor_spins, state.armor)
        self._offer_stats(state.stats)
        self.bonuses_box.setChecked(state.bonuses)
        self.types.set_kinds(self._shape)
        self.types.tick(state.places)

    # -- the geometry, the mouse and the keyboard ------------------------

    def _fit(self) -> None:
        """Cover the window, and put the panel inside that at its inset.

        Both halves are the same act, as on the comparison screen: the backdrop
        has to be the window's own size, and the inset is a margin *inside* it
        rather than a geometry worked out from it -- which is what makes the
        panel follow a resize without anything recomputing where it goes.  The
        two stretches either side of the panel are what keep it centred once
        the window is wider than :data:`PANEL_MAX`.
        """
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        margin = inset_for(parent.width(), parent.height())
        self._inset.setContentsMargins(margin, margin, margin, margin)

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        """A click on the backdrop, which is everything outside the panel.

        Reaching here at all is the test: the panel takes its own presses, so
        what arrives is a click on the part of the window the panel is not
        covering -- which is the part that says the player is done here.
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
