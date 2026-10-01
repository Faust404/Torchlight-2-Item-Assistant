"""Table models for the two lists the window shows.

Two views, deliberately: what the game has and what the tool has.  Keeping
them side by side is what makes the intake model legible -- the player can
watch a thing leave the left column and appear in the right one, which is a
better explanation of what this tool does than any amount of prose.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel

from tl2stash.item import Item

__all__ = [
    "COLLECTION_COLUMNS",
    "STASH_COLUMNS",
    "container_label",
    "fill_collection",
    "fill_stash",
    "new_model",
]

STASH_COLUMNS = ["Item", "Lvl", "Tab", "Slot"]
COLLECTION_COLUMNS = ["Item", "Lvl", "Sockets", "Where", "Found in"]


def container_label(container: int) -> str:
    """A display name for one of the shared stash's tabs.

    These are the game's own container ids.  Their *names* live in the
    INVENTORY data inside DATA.PAK, which this tool does not read yet, so the
    id is the honest label -- better than inventing names that would be wrong
    the moment a mod added a tab.
    """
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


def fill_stash(model: QStandardItemModel, items: list[Item]) -> None:
    """Show what is in the save file right now."""
    model.removeRows(0, model.rowCount())
    for item in sorted(items, key=lambda i: (i.location.container, i.location.slot_index)):
        name = _cell(item.display_name)
        name.setData(item.fingerprint, Qt.ItemDataRole.UserRole)
        if item.num_sockets:
            name.setToolTip(f"{item.num_sockets} socket(s)")

        model.appendRow(
            [
                name,
                _cell(str(item.level), sort=item.level),
                _cell(container_label(item.location.container), sort=item.location.container),
                _cell(str(item.location.slot_index), sort=item.location.slot_index),
            ]
        )


def fill_collection(
    model: QStandardItemModel,
    rows: list,
    placed: dict[str, str],
) -> None:
    """Show what the tool has.

    ``rows`` are registry rows and ``placed`` maps a fingerprint to where the
    item was last seen, so an item taken from the game still says which tab it
    came out of.
    """
    model.removeRows(0, model.rowCount())
    for row in rows:
        absorbed = row["status"] == "absorbed"
        returned = row["status"] == "returned"
        name = _cell(row["name"])
        name.setData(row["fingerprint"], Qt.ItemDataRole.UserRole)
        if absorbed:
            # The one distinction that matters in this list.
            name.setForeground(Qt.GlobalColor.darkGreen)

        # "Returned" is worth its own word: the item is in the game because
        # the player put it there, so it will not be swept up automatically
        # the way everything else in the stash is.
        status = "In tool" if absorbed else ("Returned" if returned else "In game")
        where = placed.get(row["fingerprint"], "")
        model.appendRow(
            [
                name,
                _cell(str(row["level"]), sort=row["level"]),
                _cell(str(row["num_sockets"]), sort=row["num_sockets"]),
                _cell(status, sort=(0 if absorbed else 1 if returned else 2)),
                _cell(where),
            ]
        )
