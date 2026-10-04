"""Locating Torchlight 2 save files on disk.

TL2 keeps two parallel save trees under the player's Documents folder:

``save/``      -- vanilla characters and stash
``modsave/``   -- characters and stash for modded games

Each tree holds one folder per Steam ID, and ``sharedstash_v2.bin`` is shared
across all characters.  A player who plays both ways has two *independent*
stashes, which is why every registry row is scoped to the file it came from.

*Which* Documents folder is asked of Windows rather than assumed: the game is
handed the Shell's own answer, and a Documents folder the player has moved --
OneDrive's "back up your Documents folder" being the usual way it moves --
takes the game's saves with it, so the tool has to be given the same answer.
``%USERPROFILE%\\Documents`` is kept as the fallback for a machine where the
Shell will not say (a non-Windows test run, most of all), and ``TL2IA_SAVES``
overrides both, for saves somewhere neither names.
"""

from __future__ import annotations

import ctypes
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ENV_SAVES",
    "SAVE_ROOT",
    "STASH_FILENAME",
    "SaveLocation",
    "find_save_locations",
    "live_location",
]

STASH_FILENAME = "sharedstash_v2.bin"

#: The one environment variable that says where the game's saves are, for a
#: machine the answer below cannot serve: saves copied to a stick, a second
#: install, a profile whose Documents the Shell has lost track of.  It names
#: the folder the game keeps ``save/`` and ``modsave/`` in -- what
#: :data:`SAVE_ROOT` has always been -- and not a Documents folder above it.
#: The tool's own folder follows it (see :func:`app.paths.data_dir`);
#: ``TL2IA_DATA`` is the variable that pins that one.
ENV_SAVES = "TL2IA_SAVES"

#: ``FOLDERID_Documents``, as ``SHGetKnownFolderPath`` documents it.
_DOCUMENTS = uuid.UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")

#: ``…/My Games/Runic Games/Torchlight 2``, under whichever Documents.
_GAME_TREE = Path("My Games") / "Runic Games" / "Torchlight 2"


def _known_folder(folder_id: uuid.UUID) -> Path | None:
    """Where Windows says the folder ``folder_id`` names, or ``None``.

    ``SHGetKnownFolderPath`` is the Shell's own answer.  The id travels in
    the little-endian byte order Windows lays a GUID out in, which is the
    one thing here that is easy to get subtly wrong and invisible while the
    single id in use keeps answering correctly -- so the call is kept general
    and a test asks it about a second folder.

    ``None`` rather than an exception for every way this can fail -- a
    non-Windows interpreter, a Shell that will not answer, a ``ctypes`` call
    that raises: this decides a module constant, and a tool that would not
    start over it is worse than one that looks in the obvious place.  The
    caller falls back to :func:`_assumed_documents`.
    """
    if sys.platform != "win32":
        return None
    try:

        class GUID(ctypes.Structure):
            _fields_ = [("bytes", ctypes.c_ubyte * 16)]

        guid = GUID.from_buffer_copy(folder_id.bytes_le)
        answer = ctypes.c_wchar_p()
        failed = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(answer)
        )
        if failed:
            # The out pointer is not set when the call fails, which is why
            # nothing is freed on this path.
            return None
        try:
            # ``None`` here (a null pointer) raises inside ``Path``, and the
            # handler below turns that into the same quiet answer.
            return Path(answer.value)
        finally:
            # The returned string is the caller's to free.
            ctypes.windll.ole32.CoTaskMemFree(answer)
    except Exception:
        return None


def _known_documents() -> Path | None:
    """Where Windows says the Documents folder is, or ``None`` if it will not.

    The Shell's own answer, and the one the game itself is given -- which is
    what makes a Documents folder the player has moved (OneDrive backing it
    up, most often) something the tool follows instead of a folder it
    quietly stops finding saves in.
    """
    return _known_folder(_DOCUMENTS)


def _assumed_documents() -> Path:
    """``%USERPROFILE%\\Documents``: the guess, for when Windows will not say.

    The folder's physical name is ``Documents`` in every locale, so this is
    right on a machine that has never moved it -- which is most machines, and
    is where the tool looked before it started asking.
    """
    return Path(os.environ.get("USERPROFILE", Path.home())) / "Documents"


def _resolve_root() -> Path:
    """The game's own folder: the variable, Windows' answer, or the guess.

    A function rather than an expression so that both of its sources can be
    replaced in a test, and so that the precedence is readable in one place.
    :data:`SAVE_ROOT` is this, called once at import -- the environment
    variables it reads are set before the process starts or not at all.
    """
    override = os.environ.get(ENV_SAVES)
    if override:
        return Path(override)
    documents = _known_documents()
    if documents is None:
        documents = _assumed_documents()
    return documents / _GAME_TREE


#: ``…/My Games/Runic Games/Torchlight 2``.  The tool's *own* folder is
#: derived from this one rather than from a path of its own -- see
#: :func:`app.paths.data_dir` -- so the two cannot end up on different machines
#: within one Windows profile.
SAVE_ROOT = _resolve_root()


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
