"""Noticing that the game has rewritten the stash file.

There is no hook to install and nothing to intercept: Torchlight 2 is not
aware the tool exists.  What it does give us is a file that changes whenever
the game saves, and that change is the whole of what there is to notice -- the
game writes the stash with the player's new items in it, and does not read the
file again until the next load.  Watching the file is therefore not a poor
substitute for hooking the game; it is the whole interface.

Noticing is *all* this does, and all it is for.  What the tool does about a
save -- whether anything is taken, and when -- is the player's decision, made
at a button; the watcher's job is only that the list of what the game is
holding is never stale.

Polling a stat is enough.  The file is small, saves are seconds apart at the
fastest, and the alternative -- a filesystem notification API -- has enough
platform quirks around replace-by-rename (which is how both the game and this
tool write) that it would be less reliable, not more.

The contract that makes this robust is **accept on success**: :meth:`changed`
reports that the file differs from the last state the caller managed to
process, and the caller calls :meth:`accept` only once it has.  A save caught
half-written therefore stays "changed" and is retried on the next poll, rather
than being consumed and forgotten.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["FileState", "StashWatcher"]


@dataclass(frozen=True)
class FileState:
    """Enough of a stat to tell one version of a file from another.

    Modification time and size together: mtime alone can repeat within a
    filesystem's timestamp resolution, and size alone misses a rewrite that
    happens to be the same length -- which is the *likely* case here, since
    items of similar size trade places.
    """

    mtime_ns: int
    size: int


class StashWatcher:
    """Reports when a file no longer matches the last state accepted."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._accepted: FileState | None = None

    def state(self) -> FileState | None:
        """The file's current state, or ``None`` if it is not there."""
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return FileState(mtime_ns=stat.st_mtime_ns, size=stat.st_size)

    def changed(self) -> bool:
        """Has the file moved on since the last accepted state?

        True on the very first call, so a caller that polls and then accepts
        gets one initial pass over whatever is already on disk.
        """
        return self.state() != self._accepted

    def accept(self) -> None:
        """Record the current state as processed."""
        self._accepted = self.state()

    def reset(self) -> None:
        """Forget the accepted state, so the next poll reports a change."""
        self._accepted = None

    def retarget(self, path: str | Path) -> None:
        """Point at a different file, as if newly created."""
        self.path = Path(path)
        self.reset()
