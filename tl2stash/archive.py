"""Removing items from a stash file.

This is what makes an item disappear from the game.  Two properties make it
safe, and both come from keeping every item's raw bytes rather than
re-serialising from parsed fields:

* **Nothing is rewritten.**  Removing an item means dropping its blob and
  decrementing the count.  The surviving items are copied through byte for
  byte, so the two thirds of the format nobody understands is carried along
  untouched.  FNIStash re-serialises from its parsed structures and can drift;
  we cannot drift, because we never re-encode.

* **Slots do not shift.**  An item's container and slot live *inside* its
  blob, not in its file position, so removing one leaves every other item
  where it was.  The player just sees an empty slot -- which is exactly what a
  removed item should look like.

* **Nothing unread is dropped.**  The plan is made over the stash's *entries*
  rather than over its parsed items, so an item whose bytes defeated the
  parser is carried through untouched instead of being written out of
  existence.  The tool deletes only what it understood, which -- since it can
  only store what it understood -- means it never deletes something the
  registry is not holding a copy of.

Timing is the part that is not ours to control.  Torchlight holds the stash in
memory and rewrites the file at save points (exit to title, map transition,
death), so a rewrite made while the game is running survives only until its
next save.  That is why :func:`archive_stash` is written to be run
*repeatedly* and cheaply: applying it after each of the game's saves converges
on the same result, and the item is gone the next time the game reads the file
rather than the instant we write it.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .crypto import checksum, read_save_file, scramble
from .item import Item, parse_item
from .stash import Stash, StashEntry, read_stash

__all__ = [
    "ArchiveReport",
    "RemovalPlan",
    "RestoreReport",
    "RestoreRequest",
    "archive_stash",
    "backup_path",
    "next_free_slot",
    "plan_removal",
    "restore_items",
    "serialize_body",
]

#: Suffix for files we archive, to match the game's own ``.restore`` habit
#: without colliding with it.
BACKUP_SUFFIX = ".tl2ia-bak"


def serialize_body(blobs: Sequence[bytes]) -> bytes:
    """Rebuild a stash body from item blobs.

    The container is a u32 count followed by length-prefixed blobs.  Because
    each item still holds its original bytes, this is a copy, not an encode --
    and it takes blobs rather than items so that a blob which never parsed can
    be carried through just the same.
    """
    out = bytearray()
    out += len(blobs).to_bytes(4, "little")
    for blob in blobs:
        out += len(blob).to_bytes(4, "little")
        out += blob
    return bytes(out)


@dataclass
class RemovalPlan:
    """A stash split in two: what stays, and what goes.

    Asymmetric on purpose.  What is kept is a list of *entries*, because an
    entry the parser could not read is still an item in the file and still has
    to be written back.  What is removed is a list of *items*, because only
    something we understood has a fingerprint to match on -- so an unreadable
    blob cannot be in this list even by mistake.
    """

    keep: list[StashEntry]
    remove: list[Item]

    @property
    def is_empty(self) -> bool:
        return not self.remove


@dataclass
class ArchiveReport:
    path: Path
    backup: Path | None
    removed: list[Item] = field(default_factory=list)
    kept: int = 0
    #: How many of the kept entries the parser could not read.  They stay in
    #: the file untouched -- but the player should hear about them, because an
    #: item the tool cannot read is an item it cannot store either.
    unreadable: int = 0
    changed: bool = False


def plan_removal(stash: Stash, fingerprints: set[str]) -> RemovalPlan:
    """Split a stash into entries to keep and items to take out.

    Matching is by fingerprint, which is stable across the item being moved
    between slots -- the common case, since the player moves an item *into*
    the stash before it is taken.

    Nothing without a fingerprint is ever removed.  An entry the parser could
    not read has no fingerprint to match, so it is kept -- which is the whole
    safety property here: the tool only deletes what it understood, and it can
    only *have* what it understood, so nothing is dropped that the registry
    does not hold a copy of.
    """
    keep: list[StashEntry] = []
    remove: list[Item] = []
    for entry in stash.entries:
        if entry.item is not None and entry.item.fingerprint in fingerprints:
            remove.append(entry.item)
        else:
            keep.append(entry)

    # Every entry is accounted for exactly once.  If this ever fails to hold,
    # the write below would drop an item nobody holds a copy of, so it is
    # checked rather than assumed -- the failure mode is the player's stash.
    assert len(keep) + len(remove) == len(stash.entries)

    return RemovalPlan(keep=keep, remove=remove)


def _require_whole(path: Path, stash: Stash) -> None:
    """Refuse to rewrite a file whose entries did not all read.

    A container that ends mid-entry -- a save caught half-written, or a
    damaged file -- leaves an entry holding no bytes at all.  There is nothing
    to carry through for it, so writing the entries that *did* read would
    produce a file with an item missing.  Refusing is the only safe answer;
    the caller shows the reason and the next poll tries again.
    """
    for entry in stash.entries:
        if not entry.blob:
            raise ValueError(
                f"{path.name} could not be read whole ({entry.error}); "
                "not rewriting it"
            )


def backup_path(path: Path, when: datetime | None = None) -> Path:
    """A timestamped sibling path for the pre-write copy."""
    stamp = (when or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return path.with_name(f"{path.name}.{stamp}{BACKUP_SUFFIX}")


def _encode(save_version: int, dummy: int, body: bytes) -> bytes:
    """Build the full scrambled file image for a body."""
    return (
        save_version.to_bytes(4, "little")
        + bytes([dummy])
        + checksum(body).to_bytes(4, "little")
        + scramble(body)
        + (13 + len(body)).to_bytes(4, "little")
    )


def archive_stash(
    path: str | Path,
    fingerprints: set[str],
    *,
    dry_run: bool = False,
    keep_backups: int = 10,
) -> ArchiveReport:
    """Remove the given items from a stash file, writing it back in place.

    The file is rewritten only if something actually changed, and the original
    is copied aside first.  A dry run does everything except the write.
    """
    path = Path(path)
    report = ArchiveReport(path=path, backup=None)

    save = read_save_file(path)
    stash = read_stash(save)
    _require_whole(path, stash)
    plan = plan_removal(stash, fingerprints)
    report.removed = plan.remove
    report.kept = len(plan.keep)
    report.unreadable = sum(1 for entry in plan.keep if not entry.ok)

    if plan.is_empty:
        return report

    body = serialize_body([entry.blob for entry in plan.keep])
    if dry_run:
        return report

    backup = backup_path(path)
    shutil.copy2(path, backup)
    report.backup = backup

    # Write to a sibling and replace, so an interrupted write cannot leave a
    # half-written stash where the real one was.
    staged = path.with_name(path.name + ".tl2ia-tmp")
    staged.write_bytes(_encode(save.version, save.dummy, body))
    staged.replace(path)

    report.changed = True
    _prune_backups(path, keep_backups)
    return report


def _prune_backups(path: Path, keep: int) -> None:
    """Keep only the most recent ``keep`` backups."""
    pattern = f"{path.name}.*{BACKUP_SUFFIX}"
    backups = sorted(
        path.parent.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for stale in backups[keep:]:
        try:
            stale.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------
# Putting items back
# --------------------------------------------------------------------------
#
# Taking everything out of a stash makes the registry the only copy of those
# items, so the way back is not a nicety -- it is the safety property that
# makes the whole approach reasonable.  It works for the same reason removal
# does: the blob was kept, so putting an item back is a copy plus a patch to
# its location field, not a re-creation.


@dataclass
class RestoreRequest:
    raw: bytes
    container: int
    slot: int | None = None
    label: str = ""


@dataclass
class RestoreReport:
    path: Path
    backup: Path | None = None
    restored: list[tuple[str, int, int]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    changed: bool = False


def next_free_slot(
    occupied: set[int], preferred: int | None = None, base: int | None = None
) -> int:
    """Lowest free slot, preferring the item's original one.

    Slots are not compacted when items leave -- removal leaves a hole -- so
    filling gaps keeps a restored item near where it was and keeps the tab
    from drifting upward over time.
    """
    if preferred is not None and preferred not in occupied:
        return preferred
    if occupied:
        slot = min(occupied)
        while slot in occupied:
            slot += 1
        return slot
    if base is None:
        raise ValueError("cannot place into an empty container without a slot")
    return base


def restore_items(
    path: str | Path,
    requests: list[RestoreRequest],
    *,
    dry_run: bool = False,
    keep_backups: int = 10,
) -> RestoreReport:
    """Put items from the registry back into a stash file.

    An item already present in the stash is skipped rather than duplicated --
    restoring something that never left would otherwise silently clone it.
    """
    path = Path(path)
    report = RestoreReport(path=path)

    save = read_save_file(path)
    stash = read_stash(save)
    _require_whole(path, stash)
    present = {item.fingerprint for item in stash.items}
    occupied: dict[int, set[int]] = {}
    for item in stash.items:
        occupied.setdefault(item.location.container, set()).add(item.location.slot_index)

    # The blobs already in the file, unreadable ones included: putting an item
    # back must not be the moment some other item quietly leaves.
    blobs = [entry.blob for entry in stash.entries]
    for request in requests:
        item = parse_item(request.raw)
        if item.fingerprint in present:
            report.skipped.append(request.label or item.display_name)
            continue

        slots = occupied.setdefault(request.container, set())
        slot = next_free_slot(slots, request.slot)
        slots.add(slot)

        # ``relocated`` returns the item's bytes with only its container and
        # slot fields patched, so there is nothing to re-parse on the way in.
        blobs.append(item.relocated(slot, request.container))
        present.add(item.fingerprint)
        report.restored.append((request.label or item.display_name, request.container, slot))

    if not report.restored or dry_run:
        return report

    body = serialize_body(blobs)
    backup = backup_path(path)
    shutil.copy2(path, backup)
    report.backup = backup

    staged = path.with_name(path.name + ".tl2ia-tmp")
    staged.write_bytes(_encode(save.version, save.dummy, body))
    staged.replace(path)

    report.changed = True
    _prune_backups(path, keep_backups)
    return report
