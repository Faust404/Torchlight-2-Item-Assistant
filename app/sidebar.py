"""The rail: the kinds of thing the collection has, and what to show of them.

One facet, down the left edge: the tree of kinds.  The other two -- the
rarities and the level range -- are in the bar across the top (:mod:`app.
filters`), where they cost the wall of cards none of its width.  The kinds stay
here because a kind is a *path*: a sword is a one-handed weapon, a helmet is
armor, and a tree is the only control that says so at a glance.

The tree is the reference database's, which is the game's own kinds gathered
into six groups.  Its **shape** is what the collection actually holds, so a
window with no fish in it says nothing about fish; its **numbers** are what the
filters would leave, so the number beside a row is what ticking it would show.
Keeping the shape still is a deliberate departure from the reference, which
rebuilds its rows on every filter change and drops the ones that reach zero --
boxes that vanish from under the cursor as you tick them.

**The voice.**  The rail is drawn the way the reference draws its own column:
group rows in the card's ``HEAD`` tan, subgroup rows in the deeper ``LABEL``
and upper-cased, leaves in the window's own body ink, counts in the
reference's ``--muted`` at 11px, and a hover band under the row the pointer is
on.  Headings are the *same size* as the kinds they head -- see ``_HEADINGS``
-- so the levels are told apart by ink, weight and case rather than by a size
ramp, which is what the user asked for.  A heading also says what a click on
it would do, which is the reference's tri-state and the only thing that tells
one bulk toggle from another: all of it ticked goes gold, some of it wears a
``·``, an empty row dims.

Nothing here decides anything.  It draws what it is told to draw, says what
has been ticked, and emits :attr:`SidePanel.changed`; :class:`~app.models.
CollectionFilter` is what makes that mean anything.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tl2stash.taxonomy import OTHER, TYPE_GROUPS, Place

from .card import BODY, DIM, GOLD, HEAD, LABEL, MUTED
from .theme import RAIL_PX

__all__ = ["SidePanel", "UNCLASSIFIED", "arranged"]

#: What an item with no kind is called in the rail.  The reference database's
#: word for the same thing, and there is no better one: the game never needed
#: to say what a quest object *is*, so its file says only that it is a quest
#: object.
UNCLASSIFIED = "Unclassified"

#: How a heading row is drawn: ``(ink, size in px, row height in px)``.  The
#: inks are the reference's own -- a group is its ``--head`` tan and a subgroup
#: its deeper ``--label`` -- and the sizes are the rail's, ``RAIL_PX``, which is
#: the size the kinds under them are drawn at.
#:
#: Both were a step *down* from the kinds until the user said so -- 12 and 10
#: against the leaves' 15 -- and the complaint is the whole reason they are now
#: one size: a heading set smaller than the words it heads reads as an
#: afterthought rather than as a heading.  What tells the three levels apart is
#: what tells them apart in the reference's own rail: the ink, the weight, and
#: the upper case on a subgroup.  The sizes still differ from the *counts*'
#: 11px, which is the one thing on a row that is meant to read as a side-note.
#:
#: The heights stay what they were, and they are what keeps the hierarchy
#: legible once the sizes match: a group's 30px row stands a step above its
#: subgroup's 26, which is exactly the leaf's own row.  Measured against the
#: real rail before the sizes moved: at the pane's own 180px the name column is
#: 142px, a subgroup has 130 of it after the 12px indent, and the longest of
#: them -- ``TWO-HANDED`` -- comes to 105px at this size.
_HEADINGS = {
    "group": (HEAD, RAIL_PX, 30),
    "subgroup": (LABEL, RAIL_PX, 26),
}

#: What every count on the rail is drawn in: the reference's ``--muted`` at
#: 11px, which is the same ink a card's kind line wears.  Not the leaves' ink
#: scaled down -- a count is a side-note on the row it belongs to, and the
#: reference sets it a size under the word it counts.
COUNT_PX = 11

#: Where a branch row keeps the words it was built with.  A heading that is
#: partly ticked wears a ``·`` after its name, and the mark has to come and go
#: without the name being respelled from the place every time.
_BASE_ROLE = Qt.ItemDataRole.UserRole

#: And the ink those words wear at rest -- ``HEAD`` for a group, ``LABEL`` for
#: a subgroup.  Kept on the row because it is what the dim and the gold are
#: alternatives *to*, and working it out again would be a second copy of the
#: table above.
_INK_ROLE = Qt.ItemDataRole.UserRole + 1


def _rail_order() -> list[tuple[str, str | None]]:
    """Every group the rail can draw, in the order it draws them.

    Straight out of :data:`tl2stash.taxonomy.TYPE_GROUPS`, whose own order *is*
    the rail's -- and which lists ``Weapons`` three times, once per subgroup,
    which is what makes the three land under one top-level row.
    """
    return [(group, subgroup) for group, subgroup, _ in TYPE_GROUPS] + [(OTHER, None)]


def arranged(
    places: Iterable[Place],
) -> list[tuple[str, list[tuple[str | None, list[Place]]]]]:
    """The places as the rail draws them: group, subgroup, then the leaves.

    A group whose subgroup is ``None`` is not split and gets no subgroup row,
    so ``Armor`` is a heading with six kinds under it and ``Weapons`` is a
    heading with three headings under it.

    Public, and not only for the rail: the advanced search's Type grid draws
    the same kinds in the same groups, in the same order, because the two are
    one state with two views -- see
    :class:`app.advsearch.AdvancedSearchOverlay`.  One arrangement read twice
    is what keeps a kind from being second in one list and fifth in the other.
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
    """The tree of kinds, and a signal when anything in it moves."""

    #: Something was ticked or unticked.  Emitted once per change, and never
    #: while the panel is being rebuilt underneath the user.
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
        #: The rail's own two sizes, made on first use.  A font has to be asked
        #: of the widget rather than of the application, because the family is
        #: the sheet's business -- see :data:`app.theme.SANS`.
        self._fonts: dict[int, QFont] = {}

        column = QVBoxLayout(self)
        column.setContentsMargins(6, 6, 6, 6)
        column.setSpacing(6)

        self.tree = self._build_tree()
        column.addWidget(self.tree, stretch=1)

        self.set_shape(())
        self.set_counts({})

    # -- construction ----------------------------------------------------

    def _build_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        # Named, because the size the rows are set at -- and with it how tall a
        # row is drawn -- is the sheet's one rule about a *rail* rather than
        # about trees: see :data:`app.theme.RAIL_PX`.  Everything else about
        # this tree is set here.
        tree.setObjectName("rail")
        tree.setColumnCount(2)
        tree.header().setVisible(False)
        # Not uniform, which is what a tree of one size would normally ask for:
        # a heading's row is taller than a leaf's -- 30 and 26 against the
        # sheet's 26 -- so every row carries its own height and the view has to
        # read it.  With this on, every row is drawn at the first row's height
        # and the group's 30px row is clipped down to the leaves' size.
        tree.setUniformRowHeights(False)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The last section stretches unless it is told not to, and the last
        # section here is the *count* -- so the numbers were being given the
        # width and the kinds were left with whatever was over, which in a rail
        # this narrow is nothing: the tree drew a column of counts with no
        # words beside them.  The first section stretches instead, and the
        # count takes exactly what its digits need.
        tree.header().setStretchLastSection(False)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        # The platform's 20px a level is a step wide enough that the words in
        # a three-level rail run out of column before they run out of name:
        # at 12 the path still reads as a path and "Socketable" fits under its
        # group rather than eliding to an ellipsis.
        tree.setIndentation(12)
        tree.setToolTip(
            "Tick what to show.  A group ticks everything under it,\n"
            "and only the counts move as you narrow."
        )
        tree.itemChanged.connect(self._item_changed)
        return tree

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

    def set_counts(self, places: Mapping[Place, int] | None = None) -> None:
        """Put the numbers on the rows, and the state the numbers say.

        These are what the filters *would* leave rather than what they do
        leave, so a row reading zero is a row that has nothing behind it under
        the current filters -- see :meth:`app.models.CollectionFilter.counts`.

        A row with nothing behind it also *dims*, which is the reference's own
        reading of the same number: a kind the filters have emptied is not
        somewhere the player can go, and it says so before the pointer is on
        it.  The headings then carry their tri-state, which is
        :meth:`_ink_heading`'s.
        """
        counts = places or {}
        self._updating = True
        try:
            for place, leaf in self._leaves.items():
                count = counts.get(place, 0)
                leaf.setText(1, str(count))
                leaf.setForeground(0, QBrush(QColor(BODY if count else DIM)))
            for subgroup_item in self._subgroups():
                subgroup_item.setText(1, str(self._sum(subgroup_item)))
            for i in range(self.tree.topLevelItemCount()):
                group_item = self.tree.topLevelItem(i)
                group_item.setText(1, str(self._sum(group_item)))
            for heading in self._headings():
                self._ink_heading(heading)
        finally:
            self._updating = False

    def _headings(self):
        """Every heading row in the rail: the groups, then the subgroups."""
        for i in range(self.tree.topLevelItemCount()):
            yield self.tree.topLevelItem(i)
        yield from self._subgroups()

    def _ink_heading(self, item: QTreeWidgetItem) -> None:
        """Say what a click on a heading would do: all of it, some, or none.

        The reference's tri-state, and the thing that keeps a bulk toggle
        legible: a heading with its whole subtree ticked is gold, one with part
        of it wears a ``·`` after its name, and one the filters have emptied --
        a row summing to zero -- dims.  Without it "I own all of this" and "I
        own none of this" are the same row.

        The mark is drawn in the heading's own ink rather than in the gold the
        reference gives it, because a Qt item's text is one colour: the mark
        and the name would have to be painted by hand to differ, and spending
        that on a dot would be the tail wagging the dog.
        """
        ticked, total = self._under(item)
        base, ink = item.data(0, _BASE_ROLE) or "", item.data(0, _INK_ROLE)
        # The row's own number, which ``set_counts`` has just written, is what
        # says whether there is anything under this heading -- the reference
        # reads the same sum off the row it is dimming, and a heading over
        # nothing has the same zero either way.
        if not int(item.text(1) or 0):
            ink, mark = DIM, ""
        elif ticked == total:
            ink, mark = GOLD, ""
        else:
            mark = " ·" if ticked else ""
        item.setText(0, base + mark)
        item.setForeground(0, QBrush(QColor(ink)))

    def _under(self, item: QTreeWidgetItem) -> tuple[int, int]:
        """``(how many leaves below this row are ticked, how many there are)``.

        Walked up from the leaves rather than kept as a second count on every
        heading: a heading is what is under it, and the ticks are the player's
        -- two tables that have to agree are two tables that can disagree.
        """
        ticked = total = 0
        for place, leaf in self._leaves.items():
            above = leaf.parent()
            while above is not None and above is not item:
                above = above.parent()
            if above is item:
                total += 1
                ticked += place in self._ticked
        return ticked, total

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

    def set_places(self, places: Iterable[Place]) -> None:
        """Tick exactly these leaves and nothing else.

        The other half of :meth:`places`, and the one the advanced search's
        Type grid writes through: a kind is ticked in one of two places -- this
        tree and that grid -- and the two are one state rather than two filters
        that intersect, so a search that ticks a sword has to be able to
        *un*tick a boot.

        The group and subgroup rows are left to say what they say by
        themselves, which is what ``ItemIsAutoTristate`` is for: ticking a leaf
        moves its heading, and the heading's own state is read back off its
        children rather than written here.  One :attr:`changed` at the end, and
        none at all if the ticks were already these -- the window redraws the
        wall for every one it hears.
        """
        wanted = {tuple(place) for place in places}
        self._updating = True
        try:
            for place, leaf in self._leaves.items():
                leaf.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if place in wanted
                    else Qt.CheckState.Unchecked,
                )
        finally:
            self._updating = False
        if wanted != self._ticked:
            self._ticked = wanted
            self.changed.emit()

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

    def reset(self) -> None:
        """Untick everything, which is the state the window starts in.

        Silent when nothing was ticked, like every other write here: the window
        redraws the wall for every signal it hears, and the two paths that clear
        the rail -- a click on `Clear filters`, a different save file chosen --
        both clear the bar as well, so a rail with nothing ticked in it has
        nothing to say about either.
        """
        if not self._ticked:
            return
        self._updating = True
        try:
            for leaf in self._leaves.values():
                leaf.setCheckState(0, Qt.CheckState.Unchecked)
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
            for group, subgroups in arranged(self._places):
                group_item = self._branch(group, self.tree.invisibleRootItem(), "group")
                for subgroup, here in subgroups:
                    parent = (
                        self._branch(subgroup.upper(), group_item, "subgroup")
                        if subgroup is not None
                        else group_item
                    )
                    for place in here:
                        self._leaf(place, parent)
        finally:
            self._updating = False

    def _font(self, px: int) -> QFont:
        """One of the rail's own sizes, in the window's family.

        Made from the widget's font rather than from a family named again here,
        so the sheet stays the one place the family is chosen.  The tabular
        figures come with it: the application asks for them once -- see
        :func:`app.theme._base_font` -- and a font copied from it keeps them.
        """
        font = self._fonts.get(px)
        if font is None:
            font = QFont(self.font())
            font.setPixelSize(px)
            self._fonts[px] = font
        return font

    def _branch(self, text: str, parent, heading: str) -> QTreeWidgetItem:
        """A group or subgroup row: a heading over its children, and tickable.

        ``ItemIsAutoTristate`` is what makes ticking it tick everything under
        it and makes its own state say what its children say -- a group row is
        not a fourth filter, it is its children.

        A subgroup is drawn upper-cased, the way the reference draws its own,
        and the *place* keeps its spelling: the row is a heading over kinds,
        and nothing reads it back as a word.
        """
        ink, px, height = _HEADINGS[heading]
        item = QTreeWidgetItem(parent, [text, "0"])
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsAutoTristate
        )
        item.setCheckState(0, Qt.CheckState.Unchecked)
        item.setExpanded(True)
        item.setData(0, _BASE_ROLE, text)
        item.setData(0, _INK_ROLE, ink)
        item.setFont(0, self._font(px))
        item.setForeground(0, QBrush(QColor(ink)))
        # A heading's height is its own rather than the sheet's: the two row
        # sizes are set here and the leaves' 26px comes from the sheet's
        # padding, which is the reference's own arithmetic either way.
        item.setSizeHint(0, QSize(0, height))
        self._count_column(item)
        return item

    def _count_column(self, item: QTreeWidgetItem) -> None:
        """The number beside a row: the reference's ``--muted`` at 11px.

        Set once, when the row is built.  What moves afterwards is the number
        itself, and the state inks a *heading* wears -- never a column's ink.
        """
        item.setFont(1, self._font(COUNT_PX))
        item.setForeground(1, QBrush(QColor(MUTED)))

    def _leaf(self, place: Place, parent: QTreeWidgetItem) -> None:
        item = QTreeWidgetItem(parent, [place[2] or UNCLASSIFIED, "0"])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        # The leaves are the sheet's size -- see app.theme.RAIL_PX -- and the
        # ink starts as the window's own body colour, which :meth:`set_counts`
        # dims on the rows the filters have emptied.
        item.setForeground(0, QBrush(QColor(BODY)))
        self._count_column(item)
        # The rail is narrow on purpose, so the longest kinds are drawn short
        # of their last letter or two -- and what is cut is the end of the
        # name, which is the part that tells one apart from another.  The whole
        # path on hover is what makes that a smaller word rather than a lost
        # one.
        item.setToolTip(
            0, " / ".join(word for word in (place[0], place[1], place[2] or UNCLASSIFIED) if word)
        )
        # A place that was ticked and is still here keeps its tick; the one the
        # collection no longer has is simply gone.
        item.setCheckState(
            0,
            Qt.CheckState.Checked if place in self._ticked else Qt.CheckState.Unchecked,
        )
        self._leaves[place] = item
