"""Locating Torchlight 2 save files on disk.

TL2 keeps two parallel save trees under the player's Documents folder:

``save/``      -- vanilla characters and stash
``modsave/``   -- characters and stash for modded games

Each tree holds one folder per Steam ID, and ``sharedstash_v2.bin`` is shared
across all characters.  A player who plays both ways has two *independent*
stashes, which is why every registry row is scoped to the file it came from.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = ["STASH_FILENAME", "SaveLocation", "find_save_locations", "live_location"]

STASH_FILENAME = "sharedstash_v2.bin"

#: ``…/My Games/Runic Games/Torchlight 2``
SAVE_ROOT = (
    Path(os.environ.get("USERPROFILE", Path.home()))
    / "Documents"
    / "My Games"
    / "Runic Games"
    / "Torchlight 2"
)


@dataclass(frozen=True)
class SaveLocation:
    path: Path
    kind: str  # "vanilla" | "modded"
    steam_id: str

    @property
    def label(self) -> str:
        """Short name for a picker: which tree, and whose."""
        return f"{self.kind} · {self.steam_id}"

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def mtime(self) -> float:
        return self.path.stat().st_mtime if self.exists else 0.0

    @property
    def size(self) -> int:
        return self.path.stat().st_size if self.exists else 0

    def __str__(self) -> str:
        return f"{self.kind}/{self.steam_id}"


def find_save_locations(root: Path | None = None) -> list[SaveLocation]:
    """Every shared stash file present, vanilla and modded."""
    root = root or SAVE_ROOT
    found: list[SaveLocation] = []
    for kind, folder in (("vanilla", "save"), ("modded", "modsave")):
        tree = root / folder
        if not tree.is_dir():
            continue
        for profile in sorted(tree.iterdir()):
            stash = profile / STASH_FILENAME
            if stash.is_file():
                found.append(SaveLocation(stash, kind, profile.name))
    return found


def live_location(root: Path | None = None) -> SaveLocation | None:
    """The most recently written stash -- i.e. the one being played."""
    locations = find_save_locations(root)
    return max(locations, key=lambda loc: loc.mtime) if locations else None
