"""Table models for the two lists the window shows.

Two views, deliberately: what the game has and what the tool has.  Keeping
them side by side is what makes the intake model legible -- the player can
watch a thing leave the left column and appear in the right one, which is a
better explanation of what this tool does than any amount of prose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor, QStandardItem, QStandardItemModel

from tl2stash.card import TIER_INK
from tl2stash.item import Item
from tl2stash.taxonomy import Place

from .catalog import Catalog, Entry

if TYPE_CHECKING:  # pragma: no cover
    from tl2stash.gamedata import GameData

__all__ = [
    "COLLECTION_COLUMNS",
    "FINGERPRINT_ROLE",
    "GATE_ROLE",
    "LEVEL_ROLE",
    "MEMBERS_ROLE",
    "PLACE_ROLE",
    "STASH_COLUMNS",
    "TIER_ROLE",
    "CollectionFilter",
    "container_label",
    "fill_collection",
    "fill_stash",
    "new_model",
]

#: What each model's columns are.  The collection is not a table at all any
#: more -- it is a grid of cards drawn from the model's rows -- so its one
#: column is where a row keeps what it knows, and the model is what the filters
#: read.
#:
#: The stash keeps the item, the level it asks for, how many are in the stack
#: and how many sockets it has, which is what a row of that list is for.  The
#: socket count is a column rather than a line on the tooltip because it is the
#: one thing about an item still in the game that decides what happens *next*:
#: a socketed item has to be taken out of the game before its gems can be.  The
#: quantity is a column because a stack is what a fish or a potion *is*: one
#: row saying ``20`` says how much of the stash is that thing, where a line on
#: a tooltip would have to be hovered over twenty times to add up.  Where it sat
#: -- the tab and the slot -- stays on the name cell's tooltip, which costs
#: nothing and explains itself on hover, rather than in two columns nobody
#: reads.
#:
#: Two of the four columns are counts that are mostly nothing, and both are
#: blank rather than a number on every row: the sockets of an item with none,
#: and the quantity of everything that does not stack.  A column of noughts and
#: ones is a column nobody can read at a glance, which is the only reason to
#: have one at all.
STASH_COLUMNS = ["Item", "Lvl", "Qty", "Sockets"]
COLLECTION_COLUMNS = ["Item"]

#: The rarity chips' order and their words, which is the game's own order and
#: the reference's vocabulary.  ``Set`` is not among them because it is not a
#: rarity -- a set piece is Rare or Unique and is shown as what it is -- and
#: neither is the unclassified tail, which is shown when nothing is ticked.
TIER_CHIPS = ("Normal", "Magic", "Rare", "Unique", "Legendary")

#: The top of the level range, and so the level of the box that ends it.
#: Measured over the archive: 5,974 item files state a level and the highest of
#: them is 105 -- the Wanderer's X07 set and a legendary wand -- so this is the
#: round number above the game's own top.  The character cap is 100, and the
#: game's items run past it, which is why the ceiling is not the cap.  A mod's
#: item above 110 would fall outside the default range, which is the one thing
#: this ceiling costs.
LEVEL_MAX = 110

#: What a row carries besides what it shows.
#:
#: The fingerprint is what a row *is* -- it is how a selection is turned back
#: into an item, and it has always been ``UserRole``.  The rest are what the
#: filters read, and they ride on the row's first cell because a row is one
#: thing: a proxy asked about row 12 is asking about the item in it.
#:
#: ``TIER_ROLE`` holds the tier *word* (``Magic``, ``Unique``) rather than the
#: colour key, so that a rarity chip and the card's kind line name the same
#: thing by the same name, and there is no translation between them to get
#: wrong.  An item with no rarity has the empty string, which no chip carries
#: -- such an item is shown when no chip is ticked, and is simply not one of
#: the rarities when one is.
#:
#: ``PLACE_ROLE`` holds where the item sits in the rail -- ``('Weapons',
#: 'One-Handed', 'Sword')``.  The kind filter matches on that whole triple
#: rather than on the kind word alone, because the *empty* kind is a real kind
#: in two different groups: a quest item and an item whose data file the game
#: has not got are both kinds of nothing, and they are filed under Misc and
#: Other respectively.  A filter keyed on the word alone would tick both.
#:
#: ``MEMBERS_ROLE`` holds every fingerprint the row stands for.  A row is a
#: *tile*: the tool's copies of one item are gathered into one row however many
#: rolls of it there are, and this is what turns a selection of that row back
#: into the items it is made of.
#:
#: ``LEVEL_ROLE`` is the item's own level -- the number the list shows and has
#: always shown.  ``GATE_ROLE`` is a different number and the one the level
#: range filters on: the *player* level the item asks for, which is the level
#: the game withholds the item until.  The two differ -- a level 45 unique can
#: ask for 51 -- and where the gate is unknown, which is every item on a
#: machine with no game installed, the role carries the item's level so that
#: the range still means something rather than letting everything through.
#: Zero is a real gate value and the reason the two roles are not merged: an
#: item the game gates on nothing at all, a potion, is usable at any level and
#: is shown whatever range is asked for.
FINGERPRINT_ROLE = Qt.ItemDataRole.UserRole
TIER_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 1)
PLACE_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 2)
LEVEL_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 3)
MEMBERS_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 4)
GATE_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 6)


def container_label(container: int, data: "GameData | None" = None) -> str:
    """A display name for one of the shared stash's tabs.

    With the game's data to hand this is the tab's *position*: the player
    counts tabs from one, and the internal names -- ``SHARED_STASH_BAG_ARMS``
    and so on -- describe what each bag was originally built for while any
    item goes in any tab.  The name is still worth having, which is why it is
    the cell's tooltip rather than its text.

    Without the data, the container id is the honest label -- better than
    inventing names that would be wrong the moment a mod added a tab.
    """
    if data is not None:
        tab = data.stash_tab(container)
        if tab is not None:
            return f"Tab {tab}"
        name = data.container_name(container)
        if name:
            return name
    return f"Tab {container}"


def new_model(columns: list[str]) -> QStandardItemModel:
    model = QStandardItemModel()
    model.setHorizontalHeaderLabels(columns)
    return model


def _cell(text: str = "") -> QStandardItem:
    """A cell the player cannot type into."""
    item = QStandardItem(text)
    item.setEditable(False)
    return item


def _describe(cell: QStandardItem, entry: Entry, level: int) -> None:
    """Put what the row knows onto its name cell, and leave the text alone.

    The picture rides in ``DecorationRole`` and the colour in
    ``ForegroundRole``, and the filters read their own roles -- so
    ``DisplayRole`` stays exactly what it was, and the search box that matches
    on it keeps working unchanged.

    ``level`` is the item's own, and the gate falls back to it when the game's
    data could not answer -- so a range over a collection the tool cannot trace
    behaves as it did before there was a gate at all.
    """
    cell.setData(entry.tier_word, TIER_ROLE)
    cell.setData(entry.place, PLACE_ROLE)
    cell.setData(level, LEVEL_ROLE)
    cell.setData(level if entry.gate is None else entry.gate, GATE_ROLE)
    cell.setForeground(QBrush(QColor(TIER_INK[entry.tier])))
    if entry.icon is not None:
        cell.setIcon(entry.icon)


def fill_stash(
    model: QStandardItemModel,
    items: list[Item],
    data: "GameData | None" = None,
    catalog: Catalog | None = None,
) -> None:
    """Show what is in the save file right now.

    Four columns and no more: the item, the level it asks for, how many are in
    the stack and how many sockets it has.  Which tab and which slot it came
    out of is on the name cell's tooltip -- it is worth having when it is asked
    for and worth nothing in a column, since the row a player is looking at is
    the row they just put something in.

    The quantity is the stack the item *is*, which is one for nearly everything
    and twenty for a pile of potions, and the socket count is how many the item
    has.  Both are blank when there is nothing to say -- no sockets, or the one
    every unstackable item carries -- rather than a zero or a one on every row:
    a column of noughts and ones is a column nobody can read at a glance, which
    is the only reason to have one.

    ``data`` names the tabs; without it they fall back to the container id.
    ``catalog`` supplies the tier, the kind and the picture, and without it the
    rows are the plain names they were before there was one.
    """
    model.removeRows(0, model.rowCount())
    for item in sorted(items, key=lambda i: (i.location.container, i.location.slot_index)):
        name = _cell(item.display_name)
        name.setData(item.fingerprint, FINGERPRINT_ROLE)
        if catalog is not None:
            _describe(name, catalog.entry(item.fingerprint, item), item.level)
        name.setToolTip(_where_it_sat(item, data))

        # A stack of one is not a stack, and the numbers are the save file's
        # own: the quantity is how many the item *is*, not how many of them the
        # tool has seen.
        quantity = _cell(str(item.quantity if item.quantity > 1 else ""))
        sockets = _cell(str(item.num_sockets or ""))
        model.appendRow([name, _cell(str(item.level)), quantity, sockets])


def _where_it_sat(item: Item, data: "GameData | None") -> str:
    """The name cell's tooltip: the tab, the slot, and the bag's own name.

    The internal name is the second line because it is the second question --
    ``SHARED_STASH_BAG_ARMS`` says what the bag was built for, which is not
    what the player is looking at but is what a save file or a bug report
    talks about.  How many sockets the item has is not here: it is a column of
    the same row.
    """
    lines = [
        f"{container_label(item.location.container, data)} · slot {item.location.slot_index}"
    ]
    if data is not None:
        internal = data.container_name(item.location.container)
        if internal:
            lines.append(internal)
    return "\n".join(lines)


def _gathered(rows: list) -> list[list]:
    """The registry rows, gathered into the tiles they draw as.

    Two rows are one tile when they are the same *item* rather than the same
    bytes: the same base item wearing the same two affixes, under the same
    name.  That is the reference tool's own rule, and it is why two
    differently-rolled copies of one unique are one card with a count rather
    than two cards that look alike.

    The name is part of the key and the level is not, which is the one thing
    here worth arguing about.  Two drops of one unique at two levels are one
    item -- its stats follow its level, and comparing the two rolls is exactly
    what the card's button is for.  Two rows with one guid and two names are
    two *things*, and no rule that merged them could be right: the name is
    what the card draws, so two names are two cards.  Over the player's own
    registry the two rules come to the same 37 tiles, which is the measurement
    that says the name costs nothing -- it is there for the item a mod writes
    its own guid for.

    Byte-identical copies never get here as two rows: the registry has already
    collapsed them into one with a copy count.
    """
    groups: dict[tuple, list] = {}
    for row in rows:
        key = (row["guid"], row["prefix"], row["suffix"], row["name"])
        groups.setdefault(key, []).append(row)
    return list(groups.values())


def fill_collection(
    model: QStandardItemModel,
    rows: list,
    catalog: Catalog | None = None,
) -> None:
    """Show what the tool holds, one row per *item* rather than per copy.

    ``rows`` are registry rows for items the tool has taken; the caller filters
    them, because this list answers exactly one question -- *what is in here?*
    An item sitting in the game is not in this list, whether it never left or
    the player just put it back.  It is in the panel on the left instead, which
    reads the file and so is the honest place to look for it.

    Listing everything the registry had ever seen, each row tagged with where
    it currently was, meant this list had to be read rather than trusted.  Now
    membership is the answer and the row is free to be the tile: the copies of
    one item are gathered by :func:`_gathered`, the first of them is what the
    tile draws, and ``MEMBERS_ROLE`` carries the rest so that selecting the
    tile is selecting every copy of it.

    What the row does *not* carry is where the game had the item.  The tool
    holds it now, so the tab and the slot it once sat in say nothing about
    where it is; the collection is a place of its own, and the panel beside it
    is where anything about the game's stash belongs.  Where a restored item
    lands is decided on the way back (see
    :meth:`tl2stash.service.ItemService.first_slot`), not by what it used to
    be.

    ``catalog`` supplies the tier, the kind and the picture, and reading it is
    what turns a row of text into a row of the game's own items.
    """
    model.removeRows(0, model.rowCount())
    for group in _gathered(rows):
        first = group[0]
        name = _cell(first["name"])
        name.setData(first["fingerprint"], FINGERPRINT_ROLE)
        name.setData(tuple(row["fingerprint"] for row in group), MEMBERS_ROLE)
        if catalog is not None:
            _describe(name, catalog.entry(first["fingerprint"], first), first["level"])
        model.appendRow([name])


class CollectionFilter(QSortFilterProxyModel):
    """The collection, narrowed by what the controls above it have ticked.

    Four things narrow it and they AND: the search box, the kinds ticked in
    the rail, the rarity chips, and a range of player levels.  A facet with
    nothing ticked is not a filter at all, so a window whose controls have just
    been cleared shows the whole collection -- which is what makes them safe to
    ignore.

    Ticking a *group* is the same as ticking everything in it, so the rail
    flattens its tree to a set of places and hands that over; there is no
    "which groups" anywhere in here.

    :meth:`counts` is the reason this is a class rather than a lambda.  It
    answers *how many rows would there be if this were ticked* -- computed with
    that one facet ignored, so the number beside "Unique" stays the number of
    uniques there *are* rather than dropping to zero the moment something else
    is ticked.  That is the reference database's own ``matches(o, skip)``, and
    it is the whole reason the numbers beside a control are worth reading.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._places: set[Place] = set()
        self._tiers: set[str] = set()
        #: The level range, as the two boxes hand it over.  It starts as the
        #: whole of it, so the default is a range and not a special case.
        self._low: int = 0
        self._high: int = LEVEL_MAX

    # -- what is ticked --------------------------------------------------

    def set_places(self, places) -> None:
        """Keep only these leaves of the rail, or all of them when given none."""
        wanted = {tuple(place) for place in places}
        if wanted != self._places:
            self._places = wanted
            self._refilter()

    def set_tiers(self, tiers) -> None:
        wanted = set(tiers)
        if wanted != self._tiers:
            self._tiers = wanted
            self._refilter()

    def set_level_range(self, low: int, high: int) -> None:
        """Both bounds included, and both of them *player* levels.

        What the range is over is what the item asks of the character, not what
        the item is: the two are different numbers, and the one a player
        narrowing a collection has in mind is their own level.  Anything the
        game gates on nothing passes whatever the range, so the default range
        is the whole of it and not a special case.
        """
        if (low, high) != (self._low, self._high):
            self._low, self._high = low, high
            self._refilter()

    def _refilter(self) -> None:
        """Tell the view the predicate changed.

        ``invalidateFilter`` would be the obvious call and Qt deprecated it in
        6.9; the pair below is what replaced it, and the direction says only
        rows are filtered, which is the cheaper of the two.

        Only called when a facet has actually moved.  The window re-applies
        every facet after every poll, and a poll that changed nothing has no
        business remapping the rows under the player's selection.
        """
        self.beginFilterChange()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    # -- what the sidebar shows ------------------------------------------

    def counts(self, facet: Qt.ItemDataRole) -> dict:
        """How many rows each value of one facet has, with that facet ignored.

        The search box is *not* ignored: it is a text filter rather than a
        facet, and a count that ignored what the player had typed would be a
        number for a list they are not looking at.
        """
        tally: dict = {}
        for row in range(self.sourceModel().rowCount()):
            if self._accepts(row, QModelIndex(), ignoring=facet):
                value = self._value(QModelIndex(), row, facet)
                tally[value] = tally.get(value, 0) + 1
        return tally

    # -- the predicate ---------------------------------------------------

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:  # noqa: N802
        return self._accepts(row, parent)

    def _accepts(
        self,
        row: int,
        parent: QModelIndex,
        ignoring: Qt.ItemDataRole | None = None,
    ) -> bool:
        """Whether this row survives the search and every facet but ``ignoring``.

        The search comes first and is never skipped -- it is what
        ``setFilterFixedString`` drives, and deferring to the base class is
        what keeps the search box behaving exactly as it did before there were
        facets at all.
        """
        if not super().filterAcceptsRow(row, parent):
            return False

        if ignoring != PLACE_ROLE and self._places:
            if self._value(parent, row, PLACE_ROLE) not in self._places:
                return False

        if ignoring != TIER_ROLE and self._tiers:
            if self._value(parent, row, TIER_ROLE) not in self._tiers:
                return False

        if ignoring != GATE_ROLE:
            # Not ``or 0``: zero is an item the game gates on nothing, and an
            # item nobody has to grow into is one every range includes.
            gate = self._value(parent, row, GATE_ROLE)
            if gate and (gate < self._low or gate > self._high):
                return False

        return True

    def _value(self, parent: QModelIndex, row: int, facet: Qt.ItemDataRole):
        """One facet of one row, read off the row's first cell.

        A row is one thing and its first cell is where it says so.  The
        collection is a single column -- what the player sees is the card the
        tile draws from the row, not the cells -- so the first cell is the
        whole of what there is to read.
        """
        return self.sourceModel().index(row, 0, parent).data(facet)
