"""Shared stash container -- port of FNIStash's ``File.SharedStash``.

The descrambled body of ``sharedstash_v2.bin`` is::

    u32   item count
    then, per item:
    u32   byte length of the item blob
    ...   the item blob ...

This is the *v2* layout; the older v1 layout has no length prefix, which is
why FNIStash's TODO notes that only shared-stash items are length-prefixed.
"""

from __future__ import annotations

from dataclasses import dataclass

from .binary import ParseError, Reader
from .crypto import SaveFile, read_save_file
from .item import Item, parse_item

__all__ = ["Stash", "StashEntry", "read_stash", "read_stash_file"]


@dataclass
class StashEntry:
    """One slot in the container, which may or may not have parsed."""

    index: int
    blob: bytes
    item: Item | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.item is not None


@dataclass
class Stash:
    save: SaveFile
    entries: list[StashEntry]

    @property
    def items(self) -> list[Item]:
        return [e.item for e in self.entries if e.item is not None]

    @property
    def failed(self) -> list[StashEntry]:
        return [e for e in self.entries if e.item is None]

    def by_container(self) -> dict[int, list[Item]]:
        """Group parsed items by their raw container ID."""
        grouped: dict[int, list[Item]] = {}
        for item in self.items:
            grouped.setdefault(item.location.container, []).append(item)
        return grouped


def read_stash(save: SaveFile) -> Stash:
    """Parse a descrambled save container as a shared stash.

    One unparseable item does not sink the file: FNIStash records the failure
    as ``Left`` and carries on, and so do we -- losing the whole stash because
    one item uses an encoding we don't know would be much worse than showing
    the rest.
    """
    reader = Reader(save.body)
    count = reader.u32()

    entries: list[StashEntry] = []
    for index in range(count):
        try:
            size = reader.u32()
            blob = reader.take(size)
        except ParseError as exc:
            entries.append(StashEntry(index, b"", None, f"truncated container: {exc}"))
            break

        try:
            item = parse_item(blob)
        except ParseError as exc:
            entries.append(StashEntry(index, blob, None, str(exc)))
        else:
            entries.append(StashEntry(index, blob, item))

    return Stash(save=save, entries=entries)


def read_stash_file(path) -> Stash:
    """Read, descramble and parse a shared stash file."""
    return read_stash(read_save_file(path))
