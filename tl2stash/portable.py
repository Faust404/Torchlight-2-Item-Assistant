"""Moving a collection between machines, as one file.

The registry is a database in the game's own folder, which makes it easy to
back up and impossible to hand to anyone: a player moving to a new machine, or
keeping a copy of what the tool holds before reinstalling, has nothing they can
carry.  This module is that half -- one JSON file out, the same file back in.

The file is a *transport* for item bytes, not a second database.  The bytes
are the item, as they are everywhere else in this tool; every field beside
them is either something bytes cannot say (how many identical copies there
were, where the item sat, when it was first seen) or a legibility aid for a
person opening the file in an editor.  On the way back in the bytes are what
is believed: each blob is parsed again, its fingerprint recomputed, and the
metadata around it ignored -- it is what a person reads, not what the tool
knows.

Nothing here touches a save file, and nothing reaches the registry until the
whole collection has been read and checked.  A collection half-imported
because item nine was corrupt would be worse than one refused whole.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .binary import ParseError
from .item import parse_item
from .registry import Arrival, Registry
from .service import STATUS_ABSORBED

__all__ = [
    "FORMAT",
    "SUFFIX",
    "TOOL",
    "CollectionError",
    "ImportReport",
    "collection_text",
    "import_collection",
    "read_collection",
    "write_collection",
]

#: Names the tool in the file, so that some other JSON -- a settings export, a
#: game file -- cannot be read as a collection and half-land in the registry.
TOOL = "Torchlight2ItemAssistant"

#: The *file* format's version, which is not the tool's.  A file from a later
#: version is refused rather than read optimistically: whatever a future
#: format adds, this one does not know to preserve it, and silently dropping
#: a field is how a backup stops being one.
FORMAT = 1

#: What an exported collection is called.
SUFFIX = ".tl2ia"


class CollectionError(ValueError):
    """A file that cannot be imported at all, with the reason a person needs.

    Whole-file refusals only.  One bad item among fifty is not this: it is
    counted in the report and the other forty-nine still arrive.
    """


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ImportReport:
    """What one import did, in the terms the window has to say it."""

    #: The stash the file says it came from.
    source: str
    #: How many items the file listed.
    total: int = 0
    #: How many were new to this registry and are now held.
    added: int = 0
    #: How many this registry already had, and left exactly as they were.
    already: int = 0
    #: How many blobs would not parse.
    unreadable: int = 0
    #: How many parsed but were not the item the file claimed.
    refused: int = 0
    #: One line per item that did not make it, named, for the report box.
    problems: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        bits = [f"{self.total} in file", f"{self.added} new"]
        if self.already:
            bits.append(f"{self.already} already here")
        if self.unreadable:
            bits.append(f"{self.unreadable} unreadable")
        if self.refused:
            bits.append(f"{self.refused} altered")
        return ", ".join(bits)


# -- out -----------------------------------------------------------------


def collection_text(registry: Registry, source_key: str, *, version: str) -> str:
    """The whole collection as one JSON document, ready to write.

    Everything the tool *holds* -- the absorbed rows, which is the same query
    the wall itself draws from -- so that what the player sees is what they
    get.  An item the game still has is not the tool's to give away, and
    ``copies`` has to be carried here because bytes cannot say how many
    byte-identical copies there were: they are one row in the registry and one
    entry in this file, and one blob either way.
    """
    items = []
    for row in registry.rows(status=STATUS_ABSORBED):
        place = registry.last_placement(row["fingerprint"], source_key)
        items.append(
            {
                "fingerprint": row["fingerprint"],
                "name": row["name"],
                "prefix": row["prefix"],
                "suffix": row["suffix"],
                "level": row["level"],
                "quantity": row["quantity"],
                "copies": row["copies"],
                "container": place["container"] if place else None,
                "slot": place["slot"] if place else None,
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "blob": base64.b64encode(row["raw"]).decode("ascii"),
            }
        )
    return json.dumps(
        {
            "tool": TOOL,
            "format": FORMAT,
            "version": version,
            "exported": _now(),
            "stash": source_key,
            "items": items,
        },
        indent=2,
    )


def write_collection(path: str | Path, text: str) -> Path:
    """Write a collection out, giving it :data:`SUFFIX` if it has none.

    A name the player chose is otherwise kept exactly, and returned, because
    the window says where the file went -- and a save dialog that quietly
    renames things is how people lose track of what they saved.
    """
    path = Path(path)
    if not path.suffix:
        path = path.with_suffix(SUFFIX)
    path.write_text(text, encoding="utf-8")
    return path


def read_collection(path: str | Path) -> str:
    """A collection file's text, with a failure a person can act on."""
    path = Path(path)
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CollectionError(f"Could not read {path.name}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise CollectionError(f"{path.name} is not a text file.") from exc


# -- in ------------------------------------------------------------------


def import_collection(
    registry: Registry, source_key: str, text: str
) -> ImportReport:
    """Read a collection back in.  Returns what it did.

    ``registry`` is the one for the stash currently open, and ``source_key``
    is that stash's identity.  The file is checked whole before anything is
    written; then every item that survived checking is offered to the registry
    in one transaction.
    """
    data = _load(text)
    file_key = data["stash"]
    if _kind(file_key) != _kind(source_key):
        raise CollectionError(
            f"That collection came from a {_kind(file_key)} stash, and the "
            f"open stash is {_kind(source_key)}. A modded item in a vanilla "
            f"save is the one thing the separate databases exist to prevent."
        )

    # The file is only allowed to say where an item sat when it is talking
    # about this very stash; from anywhere else the item is a stranger here,
    # and a stranger has no place -- which the tool already handles, falling
    # back to the item's kind and the tab's first cell.
    ours = file_key == source_key
    report = ImportReport(source=file_key, total=len(data["items"]))
    arrivals: list[Arrival] = []
    for entry in data["items"]:
        arrival = _arrival(entry, report, ours)
        if arrival is not None:
            arrivals.append(arrival)

    report.added = registry.add(arrivals, source=source_key, status=STATUS_ABSORBED)
    report.already = len(arrivals) - report.added
    return report


def _load(text: str) -> dict:
    """The file's own claim to be a collection of a format we read."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CollectionError("That is not a collection file: it is not JSON.") from exc
    if not isinstance(data, dict):
        raise CollectionError(
            "That is not a collection file: it is not a JSON object."
        )
    if data.get("tool") != TOOL:
        raise CollectionError(
            "That is not a collection file: it was not written by this tool."
        )
    version = data.get("format")
    # ``isinstance(version, int)`` alone would pass ``true``, which is 1 here.
    if not isinstance(version, int) or isinstance(version, bool) or version != FORMAT:
        raise CollectionError(
            f"That file says it is collection format {version!r}; this tool "
            f"reads format {FORMAT}."
        )
    if not isinstance(data.get("stash"), str) or not data["stash"]:
        raise CollectionError(
            "That collection file does not say which stash it came from."
        )
    if not isinstance(data.get("items"), list):
        raise CollectionError("That collection file lists no items.")
    return data


def _kind(key: str) -> str:
    """``"vanilla/7656…"`` -> ``"vanilla"``."""
    return key.split("/", 1)[0]


def _arrival(entry, report: ImportReport, ours: bool) -> Arrival | None:
    """One item from the file, or ``None`` and a note in ``report`` why not."""
    if not isinstance(entry, dict):
        report.unreadable += 1
        report.problems.append("An entry that is not an item.")
        return None
    name = entry.get("name")
    name = name if isinstance(name, str) and name else "An item"

    blob = _blob(entry.get("blob"))
    if blob is None:
        report.unreadable += 1
        report.problems.append(f"{name}: its bytes are not readable.")
        return None
    try:
        item = parse_item(blob)
    except ParseError:
        report.unreadable += 1
        report.problems.append(f"{name}: its bytes are not a readable item.")
        return None
    if item.fingerprint != entry.get("fingerprint"):
        report.refused += 1
        report.problems.append(
            f"{name}: its bytes are not the item the file names. Skipped."
        )
        return None

    copies = entry.get("copies")
    if not isinstance(copies, int) or isinstance(copies, bool) or copies < 1:
        copies = 1
    return Arrival(
        item=item,
        copies=copies,
        first_seen=_when(entry.get("first_seen")),
        last_seen=_when(entry.get("last_seen")),
        # From the *bytes*, not from the entry's own container/slot fields:
        # those are the file's account of where the item sat, and the item's
        # bytes are the item.
        container=item.location.container if ours else None,
        slot=item.location.slot_index if ours else None,
    )


def _blob(value) -> bytes | None:
    if not isinstance(value, str):
        return None
    try:
        return base64.b64decode(value, validate=True)
    except ValueError:  # binascii.Error, which is one
        return None


def _when(value) -> str | None:
    """A timestamp from the file, or ``None`` -- which means "now", later."""
    return value if isinstance(value, str) and value else None
