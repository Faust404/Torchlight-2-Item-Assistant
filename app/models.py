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
    "LEVEL_ROLE",
    "PLACE_ROLE",
    "STASH_COLUMNS",
    "TIER_ROLE",
    "CollectionFilter",
    "container_label",
    "fill_collection",
    "fill_stash",
    "new_model",
]

STASH_COLUMNS = ["Item", "Lvl", "Tab", "Slot"]
COLLECTION_COLUMNS = ["Item", "Lvl", "Sockets", "Found in"]

#: The rarity chips' order and their words, which is the game's own order and
#: the reference's vocabulary.  ``Set`` is not among them because it is not a
#: rarity -- a set piece is Rare or Unique and is shown as what it is -- and
#: neither is the unclassified tail, which is shown when nothing is ticked.
TIER_CHIPS = ("Normal", "Magic", "Rare", "Unique", "Legendary")

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
FINGERPRINT_ROLE = Qt.ItemDataRole.UserRole
TIER_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 1)
PLACE_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 2)
LEVEL_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 3)


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


def _cell(text: str = "", *, sort: object | None = None) -> QStandardItem:
    """A read-only cell, optionally sorting by something other than its text.

    Levels and slot numbers sort numerically this way; without it "10" would
    come before "9", which is the kind of detail that makes a tool feel wrong
    without anyone being able to say why.
    """
    item = QStandardItem(text)
    item.setEditable(False)
    if sort is not None:
        item.setData(sort, Qt.ItemDataRole.DisplayRole)
    return item


def _describe(cell: QStandardItem, entry: Entry, level: int) -> None:
    """Put what the row knows onto its name cell, and leave the text alone.

    The picture rides in ``DecorationRole`` and the colour in
    ``ForegroundRole``, and the filters read their own roles -- so
    ``DisplayRole`` stays exactly what it was, and the search box that matches
    on it keeps working unchanged.
    """
    cell.setData(entry.tier_word, TIER_ROLE)
    cell.setData(entry.place, PLACE_ROLE)
    cell.setData(level, LEVEL_ROLE)
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
        if item.num_sockets:
            name.setToolTip(f"{item.num_sockets} socket(s)")

        # No sort override on the tab, unlike level and slot: this column
        # sorts by the label the player can see.  That is the same order as
        # the container ids would give -- the tabs are "Tab 1" to "Tab 3", or
        # "Tab 24" upwards when the game's data is missing -- and sorting by
        # anything else would be sorting by something not on screen.
        container = item.location.container
        tab = _cell(container_label(container, data))
        if data is not None:
            internal = data.container_name(container)
            if internal:
                tab.setToolTip(internal)

        model.appendRow(
            [
                name,
                _cell(str(item.level), sort=item.level),
                tab,
                _cell(str(item.location.slot_index), sort=item.location.slot_index),
            ]
        )


def fill_collection(
    model: QStandardItemModel,
    rows: list,
    placed: dict[str, str],
    catalog: Catalog | None = None,
) -> None:
    """Show what the tool holds.

    ``rows`` are registry rows for items the tool has taken; the caller filters
    them, because this list answers exactly one question -- *what is in here?*
    An item sitting in the game is not in this list, whether it never left or
    the player just put it back.  It is in the panel on the left instead, which
    reads the file and so is the honest place to look for it.

    Listing everything the registry had ever seen, each row tagged with where
    it currently was, meant this list had to be read rather than trusted.  Now
    membership is the answer and the columns are free to describe the item.

    ``placed`` maps a fingerprint to where the item was last seen, so an item
    taken out of the game still says which tab it came from.  ``catalog``
    supplies the tier, the kind and the picture, and reading it is what turns a
    row of text into a row of the game's own items.
    """
    model.removeRows(0, model.rowCount())
    for row in rows:
        name = _cell(row["name"])
        name.setData(row["fingerprint"], FINGERPRINT_ROLE)
        if catalog is not None:
            _describe(name, catalog.entry(row["fingerprint"], row), row["level"])
        model.appendRow(
            [
                name,
                _cell(str(row["level"]), sort=row["level"]),
                _cell(str(row["num_sockets"]), sort=row["num_sockets"]),
                _cell(placed.get(row["fingerprint"], "")),
            ]
        )


class CollectionFilter(QSortFilterProxyModel):
    """The collection list, narrowed by what the sidebar has ticked.

    Four things narrow it and they AND: the search box, the kinds ticked in the
    rail, the rarity chips, and a level range.  A facet with nothing ticked is
    not a filter at all, so a window whose sidebar has just been cleared shows
    the whole collection -- which is what makes the sidebar safe to ignore.

    Ticking a *group* is the same as ticking everything in it, so the sidebar
    flattens its tree to a set of places and hands that over; there is no
    "which groups" anywhere in here.

    :meth:`counts` is the reason this is a class rather than a lambda.  It
    answers *how many rows would there be if this were ticked* -- computed with
    that one facet ignored, so the number beside "Unique" stays the number of
    uniques there *are* rather than dropping to zero the moment something else
    is ticked.  That is the reference database's own ``matches(o, skip)``, and
    it is the whole reason the sidebar's numbers are worth reading.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._places: set[Place] = set()
        self._tiers: set[str] = set()
        self._low: int | None = None
        self._high: int | None = None

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

    def set_level_range(self, low: int | None, high: int | None) -> None:
        """Bounds inclusive; ``None`` at either end means unbounded."""
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

        if ignoring != LEVEL_ROLE:
            level = self._value(parent, row, LEVEL_ROLE) or 0
            if self._low is not None and level < self._low:
                return False
            if self._high is not None and level > self._high:
                return False

        return True

    def _value(self, parent: QModelIndex, row: int, facet: Qt.ItemDataRole):
        """One facet of one row, read off the row's first cell.

        A row is one thing and its first cell is where it says so: the other
        columns are the item's level and where it was found, and neither is
        what a facet is about.
        """
        return self.sourceModel().index(row, 0, parent).data(facet)
