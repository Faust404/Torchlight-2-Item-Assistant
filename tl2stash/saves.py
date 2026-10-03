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

#: ``…/My Games/Runic Games/Torchlight 2``.  The tool's *own* folder is
#: derived from this one rather than from a path of its own -- see
#: :func:`app.paths.data_dir` -- so the two cannot end up on different machines
#: within one Windows profile.
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
    def key(self) -> str:
        """The registry's name for this stash -- its identity.

        Deliberately not the path.  The absolute path changes when a Steam
        library moves between drives, or when the game is reinstalled, and a
        registry keyed on it would then be looking at a stash it had never
        seen: every item in it would be new, and every item recorded under the
        old path would look lost.  Which tree it is and whose it is survives
        all of that.
        """
        return f"{self.kind}/{self.steam_id}"

    @property
    def db_name(self) -> str:
        """This stash's own database file name.

        One file per stash rather than one file with a source column, so that
        a modded item cannot be restored into a vanilla save -- not because
        the code checks, but because the vanilla stash's database has never
        held it.
        """
        return f"items-{self.kind}-{self.steam_id}.db"

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def mtime(self) -> float:
        return self.path.stat().st_mtime if self.exists else 0.0

    @property
    def size(self) -> int:
        return self.path.stat().st_size if self.exists else 0

    @classmethod
    def at(cls, path: str | Path) -> "SaveLocation":
        """Identity for a stash file given by path alone.

        Discovery knows which tree it walked in; a file named on the command
        line does not come with that answer.  Both routes have to arrive at
        the same identity, or the same stash ends up in the registry twice
        under two names -- which is exactly what happened here, and is why
        this derivation lives in one place instead of at each call site.
        """
        path = Path(path)
        return cls(
            path=path,
            kind="modded" if "modsave" in path.parts else "vanilla",
            steam_id=path.parent.name,
        )

    def __str__(self) -> str:
        return self.key


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
