"""torchlight2_item_assistant -- external item storage for Torchlight 2.

Level A: read ``sharedstash_v2.bin``, descramble it, parse the items out and
register them.  Level B: intercept the game's own write so archived items
vanish from the in-game stash.

The format layer here is a port of FNIStash (Daniel Austin, 2013), which is
the only public implementation of the TL2 save format that survives contact
with real save files.
"""

__version__ = "0.0.1"

from .crypto import SaveFile, descramble, scramble, read_save_file, write_save_file
from .item import Item, parse_item
from .stash import Stash, StashEntry, read_stash, read_stash_file

__all__ = [
    "Item",
    "SaveFile",
    "Stash",
    "StashEntry",
    "descramble",
    "parse_item",
    "read_save_file",
    "read_stash",
    "read_stash_file",
    "scramble",
    "write_save_file",
]
