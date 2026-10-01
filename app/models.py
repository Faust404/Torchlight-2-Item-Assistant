"""Table models for the two lists the window shows.

Two views, deliberately: what the game has and what the tool has.  Keeping
them side by side is what makes the intake model legible -- the player can
watch a thing leave the left column and appear in the right one, which is a
better explanation of what this tool does than any amount of prose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QStandardItem, QStandardItemModel

from tl2stash.card import TIER_INK
from tl2stash.item import Item

from .catalog import Catalog, Entry

if TYPE_CHECKING:  # pragma: no cover
    from tl2stash.gamedata import GameData

__all__ = [
    "COLLECTION_COLUMNS",
    "FINGERPRINT_ROLE",
    "KIND_ROLE",
    "LEVEL_ROLE",
    "STASH_COLUMNS",
    "TIER_ROLE",
    "container_label",
    "fill_collection",
    "fill_stash",
    "new_model",
]

STASH_COLUMNS = ["Item", "Lvl", "Tab", "Slot"]
COLLECTION_COLUMNS = ["Item", "Lvl", "Sockets", "Found in"]

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
FINGERPRINT_ROLE = Qt.ItemDataRole.UserRole
TIER_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 1)
KIND_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 2)
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
    cell.setData(entry.kind, KIND_ROLE)
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
