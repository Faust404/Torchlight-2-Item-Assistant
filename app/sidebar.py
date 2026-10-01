"""The rail: what the collection holds, and what to show of it.

Three facets, laid over each other down the left edge: the kinds of thing the
collection has, the rarities, and a level range.  A window with a hundred items
in it is not a list anyone reads -- it is a list you narrow -- and these are the
three ways a player narrows one.

The tree is the reference database's, which is the game's own kinds gathered
into six groups.  Its **shape** is what the collection actually holds, so a
window with no fish in it says nothing about fish; its **numbers** are what the
filters would leave, so the number beside a row is what ticking it would show.
Keeping the shape still is a deliberate departure from the reference, which
rebuilds its rows on every filter change and drops the ones that reach zero --
boxes that vanish from under the cursor as you tick them.

Nothing here decides anything.  It draws what it is told to draw, says what has
been ticked, and emits :attr:`SidePanel.changed`; :class:`~app.models.
CollectionFilter` is what makes that mean anything.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tl2stash.card import TIER_INK
from tl2stash.taxonomy import OTHER, TYPE_GROUPS, Place

from .models import TIER_CHIPS

__all__ = ["SidePanel"]

#: What an item with no kind is called in the rail.  The reference database's
#: word for the same thing, and there is no better one: the game never needed
#: to say what a quest object *is*, so its file says only that it is a quest
#: object.
UNCLASSIFIED = "Unclassified"

#: The highest level the game has an item at, so the range cannot be set past
#: what the collection could hold.  Level 100 is the character cap; an item's
#: own requirement runs a little above it.
LEVEL_MAX = 100

#: How dim a chip is drawn when it is not ticked.
OFF_INK = "#6f6963"
OFF_BORDER = "#33302c"


def _chip_style(ink: str) -> str:
    """A rarity chip: the tier's own colour, in the reference's pill shape.

    Tinted while ticked and grey while not, so that a glance at the column says
    which rarities are in play without reading a single word.  The indicator is
    collapsed to nothing and the pill itself is the control -- a checkbox's box
    beside a coloured pill is two things saying one thing.
    """
    return (
        "QCheckBox {"
        f" color: {ink};"
        f" border: 1px solid {ink};"
        " border-radius: 9px; padding: 3px 8px;"
        " background: rgba(255, 255, 255, 0.05);"
        "}"
        "QCheckBox::indicator { width: 0px; height: 0px; }"
        "QCheckBox:!checked {"
        f" color: {OFF_INK}; border-color: {OFF_BORDER}; background: transparent;"
        "}"
    )


def _rail_order() -> list[tuple[str, str | None]]:
    """Every group the rail can draw, in the order it draws them.

    Straight out of :data:`tl2stash.taxonomy.TYPE_GROUPS`, whose own order *is*
    the rail's -- and which lists ``Weapons`` three times, once per subgroup,
    which is what makes the three land under one top-level row.
    """
    return [(group, subgroup) for group, subgroup, _ in TYPE_GROUPS] + [(OTHER, None)]


def _arranged(
    places: Iterable[Place],
) -> list[tuple[str, list[tuple[str | None, list[Place]]]]]:
    """The places as the rail draws them: group, subgroup, then the leaves.

    A group whose subgroup is ``None`` is not split and gets no subgroup row,
    so ``Armor`` is a heading with six kinds under it and ``Weapons`` is a
    heading with three headings under it.
    """
    present = set(places)
    drawn: list[tuple[str, list[tuple[str | None, list[Place]]]]] = []
    for group, subgroup in _rail_order():
        here = sorted(
            (place for place in present if place[0] == group and place[1] == subgroup),
            key=lambda place: (place[2].lower(), place[2]),
        )
        if not here:
            continue
        if drawn and drawn[-1][0] == group:
            drawn[-1][1].append((subgroup, here))
        else:
            drawn.append((group, [(subgroup, here)]))
    return drawn


class SidePanel(QWidget):
    """The three facets, and a signal when any of them moves."""

    #: Something was ticked, unticked or retyped.  Emitted once per change, and
    #: never while the panel is being rebuilt underneath the user.
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        #: True while this widget is writing to itself, so that the writes do
        #: not come back round as changes the user made.
        self._updating = False
        #: What the collection holds -- the shape the tree is drawn to.  Kept
        #: so that a poll that changes nothing does not rebuild the tree, which
        #: would take the ticks with it.
        self._places: set[Place] = set()
        self._leaves: dict[Place, QTreeWidgetItem] = {}
        self._ticked: set[Place] = set()

        column = QVBoxLayout(self)
        column.setContentsMargins(6, 6, 6, 6)
        column.setSpacing(6)

        self.tree = self._build_tree()
        column.addWidget(self.tree, stretch=1)

        column.addWidget(self._rule("Rarity"))
        column.addLayout(self._build_chips())

        column.addWidget(self._rule("Level"))
        column.addLayout(self._build_levels())

        column.addStretch(0)
        self.clear_button = QPushButton("Clear filters")
        self.clear_button.clicked.connect(self.reset)
        column.addWidget(self.clear_button)

        self.set_shape(())
        self.set_counts({}, {})

    # -- construction ----------------------------------------------------

    def _build_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.header().setVisible(False)
        tree.setUniformRowHeights(True)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        tree.setToolTip(
            "Tick what to show.  A group ticks everything under it,\n"
            "and only the counts move as you narrow."
        )
        tree.itemChanged.connect(self._item_changed)
        return tree

    def _rule(self, text: str) -> QLabel:
        """A small heading over one of the facets."""
        label = QLabel(text)
        label.setObjectName("facet")
        label.setStyleSheet(
            "QLabel#facet { color: #8b837b; padding-top: 6px; }"
        )
        return label

    def _build_chips(self) -> QGridLayout:
        """The rarity chips, two to a row in the game's own order."""
        grid = QGridLayout()
        grid.setSpacing(4)
        self.chips: dict[str, QCheckBox] = {}
        for i, word in enumerate(TIER_CHIPS):
            chip = QCheckBox(word)
            chip.setStyleSheet(_chip_style(TIER_INK[word.lower()]))
            chip.setToolTip(f"Show only the {word.lower()} items.")
            chip.toggled.connect(self._facet_changed)
            grid.addWidget(chip, i // 2, i % 2)
            self.chips[word] = chip
        return grid

    def _build_levels(self) -> QHBoxLayout:
        """A min and a max, where zero means "no bound" rather than "level 0"."""
        row = QHBoxLayout()
        row.setSpacing(4)
        self.low = self._spin()
        self.high = self._spin()
        row.addWidget(self.low)
        row.addWidget(QLabel("to"))
        row.addWidget(self.high)
        row.addStretch(1)
        return row

    def _spin(self) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, LEVEL_MAX)
        # Zero is not a level the game has an item at, so it is free to mean
        # "any" -- and meaning it in the widget is what keeps the empty string
        # out of the range arithmetic.
        spin.setSpecialValueText("Any")
        spin.setValue(0)
        spin.valueChanged.connect(self._facet_changed)
        return spin

    # -- what the panel is told ------------------------------------------

    def set_shape(self, places: Iterable[Place]) -> None:
        """Draw the rail for these places, keeping whatever is already ticked.

        Called after every poll, and does nothing at all on the polls where the
        collection has not changed shape -- which is nearly all of them, and
        which is what keeps a tick from being undone every two seconds.
        """
        wanted = set(places)
        if wanted == self._places:
            return
        self._places = wanted
        # A tick on a kind the collection no longer has would hide everything
        # and show nothing ticked to explain it, so it goes with the kind.
        self._ticked &= wanted
        self._rebuild()

    def set_counts(
        self,
        places: Mapping[Place, int] | None = None,
        tiers: Mapping[str, int] | None = None,
    ) -> None:
        """Put the numbers on the rows and the chips.

        These are what the filters *would* leave rather than what they do
        leave, so a row reading zero is a row that has nothing behind it under
        the current filters -- see :meth:`app.models.CollectionFilter.counts`.
        """
        counts = places or {}
        self._updating = True
        try:
            for place, leaf in self._leaves.items():
                leaf.setText(1, str(counts.get(place, 0)))
            for subgroup_item in self._subgroups():
                subgroup_item.setText(1, str(self._sum(subgroup_item)))
            for i in range(self.tree.topLevelItemCount()):
                group_item = self.tree.topLevelItem(i)
                group_item.setText(1, str(self._sum(group_item)))
            for word, chip in self.chips.items():
                chip.setText(f"{word}  {(tiers or {}).get(word, 0)}")
        finally:
            self._updating = False

    def _sum(self, item: QTreeWidgetItem) -> int:
        """A row's count, which is its children's -- a group is what is in it."""
        return sum(
            int(item.child(i).text(1) or 0) for i in range(item.childCount())
        )

    def _subgroups(self):
        for i in range(self.tree.topLevelItemCount()):
            group_item = self.tree.topLevelItem(i)
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                if child.childCount():
                    yield child

    # -- what the panel says ---------------------------------------------

    def places(self) -> set[Place]:
        """The leaves that are ticked, flattened -- a group is its children."""
        return set(self._ticked)

    def tiers(self) -> set[str]:
        """The rarity words that are ticked."""
        return {word for word, chip in self.chips.items() if chip.isChecked()}

    def level_range(self) -> tuple[int | None, int | None]:
        """The bounds, either of which is ``None`` when the box says "Any"."""
        return (self.low.value() or None, self.high.value() or None)

    # -- the user --------------------------------------------------------

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 0:
            return
        ticked = {
            place
            for place, leaf in self._leaves.items()
            if leaf.checkState(0) == Qt.CheckState.Checked
        }
        # Ticking one leaf moves its group too, and a group that has moved is a
        # second ``itemChanged`` for the same change.  The window does one
        # thing per signal, so it should hear about it once.
        if ticked == self._ticked:
            return
        self._ticked = ticked
        self.changed.emit()

    def _facet_changed(self, *_) -> None:
        if not self._updating:
            self.changed.emit()

    def reset(self) -> None:
        """Untick everything, which is the state the window starts in."""
        self._updating = True
        try:
            for leaf in self._leaves.values():
                leaf.setCheckState(0, Qt.CheckState.Unchecked)
            for chip in self.chips.values():
                chip.setChecked(False)
            self.low.setValue(0)
            self.high.setValue(0)
        finally:
            self._updating = False
        self._ticked = set()
        self.changed.emit()

    # -- drawing ---------------------------------------------------------

    def _rebuild(self) -> None:
        """Draw the tree, and put back the ticks it had before."""
        self._updating = True
        try:
            self.tree.clear()
            self._leaves = {}
            for group, subgroups in _arranged(self._places):
                group_item = self._branch(group, self.tree.invisibleRootItem())
                for subgroup, here in subgroups:
                    parent = (
                        self._branch(subgroup, group_item)
                        if subgroup is not None
                        else group_item
                    )
                    for place in here:
                        self._leaf(place, parent)
        finally:
            self._updating = False

    def _branch(self, text: str, parent) -> QTreeWidgetItem:
        """A group or subgroup row: a heading over its children, and tickable.

        ``ItemIsAutoTristate`` is what makes ticking it tick everything under
        it and makes its own state say what its children say -- a group row is
        not a fourth filter, it is its children.
        """
        item = QTreeWidgetItem(parent, [text, "0"])
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsAutoTristate
        )
        item.setCheckState(0, Qt.CheckState.Unchecked)
        item.setExpanded(True)
        return item

    def _leaf(self, place: Place, parent: QTreeWidgetItem) -> None:
        item = QTreeWidgetItem(parent, [place[2] or UNCLASSIFIED, "0"])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        # A place that was ticked and is still here keeps its tick; the one the
        # collection no longer has is simply gone.
        item.setCheckState(
            0,
            Qt.CheckState.Checked if place in self._ticked else Qt.CheckState.Unchecked,
        )
        self._leaves[place] = item
