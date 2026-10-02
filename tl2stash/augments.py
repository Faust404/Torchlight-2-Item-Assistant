"""What the game's augmented weapons will become.

Seventy-four of the game's unique weapons carry a kill-count task, and
finishing it unlocks one to three extra stats.  The game draws them as locked
-- the task, a rule, and the rewards under it -- and the player sees none of
them until the count is done.

The tool cannot work them out on its own, and this module is why it does not
try: the game holds the unlock in a *triggerable*, resolved at runtime, and
nothing in the archive links an item to the one it carries.  All 70,443 entries
were swept for it -- no item and no affix names an ``ITEM_SLAYER_*`` triggerable,
and the four vanilla items that name an ``OFLEARNING_*`` affix are developers'
test items.  What the game would show is written down in exactly one place
outside it, and this reads that place.

**Where the data comes from.**  ``items.json`` is the published dataset of
`torchlight2-db <https://github.com/majorpain/torchlight2_db>`_, which is
GPL-3.0.  Nothing of its code or its art is used here -- only two fields of its
data file, read at runtime and never copied into this repository:

* ``id``    -- the item's unit name, which is the item file's own ``NAME``
               field lower-cased (``hammer_u02`` is
               ``MEDIA/UNITS/ITEMS/HAMMERS/HAMMER_U02.DAT``);
* ``aug``   -- a list of blocks, each a ``task`` string and the ``fx`` lines
               that finishing it grants.

Its own note on where *that* came from is worth keeping: the block was scraped
out of the game's tooltip, whose boundary is the ``Augmented Weapon:`` header
and the dashed rule under it -- present on exactly these 74 items and no other
in the corpus.  So this is the game's own text, restated.

**Where it is looked for.**  ``TL2_ITEMS_JSON`` first, for a copy somewhere
else; then the sibling ``torchlight2_db/out/items.json`` of this project's
parent, which is where a checkout of the reference keeps it; then
``out/items.json`` beside the game install.  Absent is not an error: the card
simply draws no augment blocks, which is what a machine with no reference
database has always had.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .card import Augment

__all__ = ["find_items_json", "load", "read"]

#: The environment variable that says where the reference's item file is, for
#: a copy that is not where this module would look.  The same bargain
#: ``TL2_INSTALL`` makes for the game itself.
ITEMS_JSON_VAR = "TL2_ITEMS_JSON"

#: The reference database's project directory, and where it publishes.
REFERENCE_DIR = "torchlight2_db"
REFERENCE_OUT = Path("out") / "items.json"


def find_items_json(install: str | Path | None = None) -> Path | None:
    """The reference database's item file, or ``None`` for one that is absent.

    Three places, best first: the environment variable, the checkout beside
    this project, and an ``out/items.json`` next to the game.  ``install`` is
    the game's directory when the caller knows it and ``None`` when it does
    not -- the first two answers do not need it.
    """
    override = os.environ.get(ITEMS_JSON_VAR)
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None

    # Beside this project rather than inside it: the reference is a checkout of
    # its own, and a copy of it inside the tree would be one to keep in step.
    beside = Path(__file__).resolve().parents[1].parent / REFERENCE_DIR
    candidate = beside / REFERENCE_OUT
    if candidate.is_file():
        return candidate

    if install is not None:
        candidate = Path(install) / REFERENCE_OUT
        if candidate.is_file():
            return candidate
    return None


def read(path: str | Path) -> dict[str, tuple[Augment, ...]]:
    """The augment blocks in a reference ``items.json``, by unit name.

    Every item in the file is walked and the ones with nothing to unlock are
    passed over -- 74 of its 6,173 records have anything here.  Keys are
    lower-cased, because the field they are matched against is a unit name and
    the archive's own spelling of one is not fixed.

    Raises :class:`OSError` or :class:`ValueError` for a file that is not
    readable as the reference's -- :func:`load` is the caller that does not
    care, and this is the one that says so.
    """
    path = Path(path)
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"{path}: expected a list of items")

    out: dict[str, tuple[Augment, ...]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        name = str(record.get("id") or "").lower()
        blocks = tuple(
            Augment(str(block.get("task") or ""), tuple(map(str, block.get("fx") or ())))
            for block in record.get("aug") or ()
            if isinstance(block, dict) and (block.get("task") or block.get("fx"))
        )
        if name and blocks:
            out[name] = blocks
    return out


def load(install: str | Path | None = None) -> dict[str, tuple[Augment, ...]]:
    """The table, from wherever the file is; empty if it is nowhere readable.

    The reference database is not the game.  A machine without it is a machine
    this tool has always run on, and an item card that cannot say what a
    weapon will become is a card the player can still read -- so a file that is
    missing, unreadable or no longer the shape this expects is an empty table
    rather than a failure to start.
    """
    path = find_items_json(install)
    if path is None:
        return {}
    try:
        return read(path)
    except (OSError, ValueError):
        return {}
