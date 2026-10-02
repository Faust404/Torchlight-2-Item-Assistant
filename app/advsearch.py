"""The advanced search: the facets the bar has no room for, over the window.

The bar over the collection carries four controls, and four more are here:
a range of *item* levels, the socket counts, an item's four stat requirements,
and the classes it may be restricted to.  They are the reference database's own
advanced search, section for section and rule for rule -- see
:meth:`app.models.CollectionFilter.set_requirements` for the two rules that are
easy to get wrong -- and they are on a panel rather than in the row because a
row of nine controls is a row nobody reads.

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

from collections.abc import Sequence

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
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
from tl2stash.taxonomy import Place

from .card import BODY, DIM, GOLD, HEAD, LABEL, LINE, PANEL, Hairline
from .compare import SCRIM, inset_for
from .filters import SpinBox, chip_style
from .models import (
    CLASSES,
    LEVEL_MAX,
    REQ_MAX,
    REQ_WORDS,
    SOCKET_COUNTS,
    TIER_CHIPS,
    Advanced,
)
from .sidebar import UNCLASSIFIED, arranged
from .theme import CHALK, PALE

__all__ = ["AdvancedSearchOverlay"]

#: The group button that shows every kind rather than one group's.  Spelled
#: once, because three places here compare against it and a second spelling
#: would be a tab that matches nothing.
ALL_TYPES = "All"

#: How wide the panel is allowed to get, however wide the window is.  A form is
#: read down a column, and a search box spanning a 1400px screen puts its words
#: at one edge and its end at the other; the reference caps its own panel for
#: the same reason, and this is a little wider than its 640 for the two-column
#: grid of kinds.
PANEL_MAX = 720

#: The air inside the panel, on every side and between two sections.  Wide,
#: because the sections are the structure here: what tells the four groups of
#: controls apart is the space between them, since a rule under each would be
#: four more lines on a screen that is already a form.
PAD = 16

#: The column a row's label is written in.  Fixed, so that the four sections'
#: controls line up down the panel even though the longest word in them --
#: "Vitality" -- is nothing like the longest in the Type grid.
LABEL_PX = 92

#: What the Class section says when there is nothing to restrict by.  The
#: restrictions are the reference database's and are in no file of the game's,
#: so on a machine without it this section could only ever match nothing --
#: which is a control that lies, and the one honest thing to do with it is to
#: say so and leave it dark.
NO_CLASSES = (
    "The reference database's items.json was not found, and the game's own "
    "files do not say which class an item is for — so there is nothing here "
    "to narrow by."
)

#: The Class section's other half, when there *is* something to narrow by: the
#: one rule of the five that reads backwards -- an item that names no class is
#: one every class may use, so it passes whatever is ticked.
CLASSES_HINT = (
    "No box ticked means every class.  An item that names no class is one any "
    "class may use, so it is shown whatever is ticked here."
)


def _row_label(text: str) -> QLabel:
    """The name a row's controls are read against, right up against them."""
    label = QLabel(text)
    label.setStyleSheet(f"color: {LABEL}; font-size: 11px;")
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
    label.setStyleSheet(f"color: {DIM}; font-size: 11px;")
    label.setWordWrap(True)
    return label


def _spin(value: int, top: int, tip: str) -> SpinBox:
    """One end of a range: a number box with its whole span on it."""
    spin = SpinBox()
    spin.setRange(0, top)
    spin.setValue(value)
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


def _empty(layout) -> None:
    """Take every widget out of a layout, and take the widgets away with it.

    ``setParent(None)`` rather than ``deleteLater``: a widget out of a layout
    but still parented keeps its last geometry and stays *visible* until the
    event loop gets round to the deferred delete, which is a grid drawing the
    boxes it has just replaced underneath the ones that replaced them.
    """
    while layout.count():
        widget = layout.takeAt(0).widget()
        if widget is not None:
            widget.setParent(None)


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


class TypeGrid(QWidget):
    """Every kind the collection holds, under a row of group buttons.

    A second view of the rail and not a second filter: the shape and the order
    are :func:`app.sidebar.arranged`'s, which is what the rail draws from, and
    the ticks are the same ticks -- the window writes them onto the rail when
    the draft is committed rather than ANDing two sets here.  So a player who
    ticks Boots on this panel and a player who ticks Boots on the rail have
    asked for the same collection.

    What is *not* here is any count.  The rail's numbers are what the filters
    would leave, and there is nothing to count against a draft: a number beside
    a box nobody has searched for yet would be the numbers of a list the player
    is not looking at, which is the one thing a count must never be.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._places: frozenset[Place] = frozenset()
        self._ticked: set[Place] = set()
        self._boxes: dict[Place, QCheckBox] = {}
        self._tabs: dict[str, QPushButton] = {}
        self._tab = ALL_TYPES
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
        self._grid.setVerticalSpacing(5)
        column.addLayout(self._grid)

    # -- what it is told --------------------------------------------------

    def set_kinds(self, places) -> None:
        """Draw this shape of the collection, keeping the ticks it had.

        Called after every poll with what the collection holds, and does
        nothing at all when the shape has not moved -- the same bargain the
        rail makes, and for the same reason: a grid rebuilt under the pointer
        is a grid that loses the click.  The panel is usually hidden, where
        this costs one comparison of two small sets.
        """
        wanted = frozenset(tuple(place) for place in places)
        if wanted == self._places:
            return
        self._places = wanted
        self._ticked &= wanted
        if self._tab != ALL_TYPES and not self._under(self._tab):
            # The group the player was looking at is gone from the collection.
            self._tab = ALL_TYPES
        self._rebuild()

    def ticks(self) -> set[Place]:
        """The kinds ticked, flattened -- a kind is itself and no subtree."""
        return set(self._ticked)

    def tick(self, places) -> None:
        """Tick exactly these kinds and nothing else, without saying so."""
        self._ticked = {tuple(place) for place in places} & self._places
        self._fill()

    # -- the user ---------------------------------------------------------

    def _chosen(self, group: str) -> None:
        self._tab = group
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
            for name, subgroups in arranged(self._places)
            if group == ALL_TYPES or name == group
            for _, here in subgroups
            for place in here
        ]

    def _rebuild(self) -> None:
        """Redraw the group buttons, then refill the grid from the new shape."""
        groups = [ALL_TYPES] + [name for name, _ in arranged(self._places)]
        _empty(self._tab_row)
        self._tabs = {}
        for name in groups:
            button = QPushButton(name)
            button.setObjectName("atab")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setChecked(name == self._tab)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, group=name: self._chosen(group))
            self._tabs[name] = button
            self._tab_row.addWidget(button)
        self._tab_row.addStretch(1)
        self._fill()

    def _fill(self) -> None:
        """Put the chosen tab's kinds in the grid, two to a row."""
        _empty(self._grid)
        self._boxes = {}
        self._updating = True
        try:
            for i, place in enumerate(self._under(self._tab)):
                box = QCheckBox(place[2] or UNCLASSIFIED)
                box.setChecked(place in self._ticked)
                box.setToolTip(" / ".join(word for word in place if word))
                box.toggled.connect(self._moved)
                self._boxes[place] = box
                self._grid.addWidget(box, i // 2, i % 2)
        finally:
            self._updating = False
        self._ink_tabs()

    def _ink_tabs(self) -> None:
        """Say on a group button what the rail says on a heading: all, or not all.

        The reference's own tri-state, as far as a button can carry it: gold
        for a group with every kind under it ticked, the control ink for one
        with some or none of it.  The mark a *partly* ticked heading wears on
        the rail is not here -- a button reading ``Weapons ·`` looks like a
        name with a smudge on it rather than like a state -- and what that
        group has instead is the grid under it, which is one click away.
        """
        for name, button in self._tabs.items():
            here = self._under(name)
            whole = bool(here) and all(place in self._ticked for place in here)
            ink = GOLD if whole else CHALK
            button.setStyleSheet(
                "QPushButton {"
                f" color: {ink}; border: 1px solid {ink};"
                " border-radius: 3px; padding: 3px 9px;"
                "}"
            )


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
        rebuilds only when the shape has moved.
        """
        wanted = list(places)
        if wanted == self._shape:
            return
        self._shape = wanted
        self.types.set_kinds(wanted)

    def open_for(self, state: Advanced, classes: Sequence[str] = CLASSES) -> None:
        """Open on this search, with the class boxes only if there are classes.

        ``classes`` is the four words when the reference database was found and
        nothing at all when it was not.
        """
        self._write(state)
        self._offer_classes(classes)

        parent = self.parentWidget()
        if parent is not None:
            parent.installEventFilter(self)
            self._fit()
        self.raise_()
        self.show()
        self.setFocus()

    def draft(self) -> Advanced:
        """What the controls say right now, as one search."""
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

    def _body(self) -> QScrollArea:
        """The sections, in the reference's own order, in a column that scrolls.

        The reference folds its sections; this scrolls them instead, because a
        fold is a state the panel would have to remember and the panel is
        thrown away on every Esc -- and four sections of a form is a short
        scroll.
        """
        scroll = QScrollArea()
        scroll.setObjectName("abody")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(PAD, PAD - 4, PAD, PAD)
        column.setSpacing(PAD + 4)
        for section in (
            self._general(),
            self._type_section(),
            self._requirements(),
            self._classes(),
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
        section = Section("Stat Requirements")
        self.req_spins: dict[str, tuple[SpinBox, SpinBox]] = {}
        for word in REQ_WORDS:
            low = _spin(
                0,
                REQ_MAX,
                f"The {word.lower()} an item asks for, from 0.\n"
                "An item that asks for none of it asks for 0, so a floor\n"
                "leaves it out and a ceiling does not.",
            )
            high = _spin(REQ_MAX, REQ_MAX, f"The {word.lower()} an item asks for, to.")
            self.req_spins[word] = (low, high)
            section.row(word, _pair(low, high))
        section.note(
            "An item is worn either by the player level or by these attributes, "
            "so these four rows narrow the stat half of that."
        )
        return section

    def _classes(self) -> Section:
        section = Section("Class")
        self.class_boxes: dict[str, QCheckBox] = {}
        for word in CLASSES:
            box = QCheckBox(word)
            box.setToolTip(f"Show the items only an {word} may use.")
            self.class_boxes[word] = box
        section.row("For", _chips(list(self.class_boxes.values())))
        self.class_note = _note(CLASSES_HINT)
        section.row("", self.class_note)
        return section

    def _offer_classes(self, classes: Sequence[str]) -> None:
        """Offer the class boxes, or say why there are none to offer."""
        known = bool(classes)
        for box in self.class_boxes.values():
            box.setEnabled(known)
            if not known:
                box.setChecked(False)
        self.class_note.setVisible(not known)
        if not known:
            self.class_note.setText(NO_CLASSES)

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
