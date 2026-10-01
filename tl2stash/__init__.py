"""torchlight2_item_assistant -- external item storage for Torchlight 2.

Read ``sharedstash_v2.bin``, descramble it, parse the items out of it, keep
them in a registry, and take them out of the file so they vanish from the
in-game stash -- then put them back on request.

The format layer here began as a port of FNIStash (Daniel Austin, 2013), which
is the only public implementation of the TL2 save format that survives contact
with real save files.  It is not a faithful port: see ``item.py`` for the
extra-record field FNIStash skips and this does not, which is the difference
between reading all 30 items of a vanilla stash and 6 of a modded one's 77.

The pieces, bottom up::

    binary, crypto    bytes and the save file envelope
    item, stash       the item format and a stash full of items
    saves             where the game keeps its stash files
    registry          what the tool remembers (SQLite)
    archive           taking items out of a file, and putting them back
    watcher, service  the file tells us when to do it
"""

__version__ = "0.0.1"

from .archive import (
    ArchiveReport,
    RestoreReport,
    RestoreRequest,
    archive_stash,
    restore_items,
    serialize_body,
)
from .crypto import SaveFile, descramble, scramble, read_save_file, write_save_file
from .item import Item, parse_item
from .registry import Registry, ScanResult
from .saves import SaveLocation, find_save_locations, live_location
from .service import ItemService
from .stash import Stash, StashEntry, read_stash, read_stash_file
from .watcher import StashWatcher

__all__ = [
    "ArchiveReport",
    "Item",
    "ItemService",
    "Registry",
    "RestoreReport",
    "RestoreRequest",
    "SaveFile",
    "SaveLocation",
    "ScanResult",
    "Stash",
    "StashEntry",
    "StashWatcher",
    "archive_stash",
    "descramble",
    "find_save_locations",
    "live_location",
    "parse_item",
    "read_save_file",
    "read_stash",
    "read_stash_file",
    "restore_items",
    "scramble",
    "serialize_body",
    "write_save_file",
]
