"""The item registry: a SQLite record of everything the tool has seen.

Two tables, with a deliberate split:

``items``       one row per *distinct item*, keyed by a fingerprint of its raw
                bytes.  Two byte-identical items (a stack of identical potions,
                say) collapse to one row with ``copies`` counted, so nothing is
                silently lost the way a naive "unique fingerprint" would lose it.
                The exception is a re-counted fish stack whose leftover lands on
                bytes the file also holds: the tool's copy takes a key of its own
                so the bare fingerprint keeps meaning *the file's* -- see
                :func:`held_key`.
``placements``  where that item currently sits, scoped to the save file it was
                seen in.  A player with both a vanilla and a modded stash has
                genuinely separate stashes, so presence has to be per-file.

Items are almost never deleted.  An item that stops appearing in a stash keeps
its row and its bytes -- "it left the stash" is information, not garbage.  The
one exception is :meth:`Registry.forget`, which is never called on its own: it
is the player deciding, by hand, that a stranded item the tool is holding was
never theirs to keep -- see :meth:`~tl2stash.service.ItemService.remove` -- or
the last of a stack's fish having gone back to the game, where the row
describes nothing any more; see :meth:`Registry.recount` and the restore path
in :mod:`tl2stash.service`.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .item import Item
from .stash import Stash

__all__ = ["Arrival", "HELD_SUFFIX", "Registry", "ScanResult", "held_key", "is_held"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    fingerprint   TEXT PRIMARY KEY,
    -- Hex text, not INTEGER: item GUIDs are unsigned 64-bit and SQLite's
    -- INTEGER is signed, so anything above 2^63 would fail to bind.
    guid          TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    prefix        TEXT    NOT NULL DEFAULT '',
    suffix        TEXT    NOT NULL DEFAULT '',
    level         INTEGER NOT NULL DEFAULT 0,
    quantity      INTEGER NOT NULL DEFAULT 1,
    identified    INTEGER NOT NULL DEFAULT 1,
    num_sockets   INTEGER NOT NULL DEFAULT 0,
    num_enchants  INTEGER NOT NULL DEFAULT 0,
    num_effects   INTEGER NOT NULL DEFAULT 0,
    num_stats     INTEGER NOT NULL DEFAULT 0,
    copies        INTEGER NOT NULL DEFAULT 1,
    raw           BLOB    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'in_stash',
    first_seen    TEXT    NOT NULL,
    last_seen     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS placements (
    fingerprint TEXT    NOT NULL REFERENCES items(fingerprint),
    source      TEXT    NOT NULL,
    container   INTEGER NOT NULL,
    slot        INTEGER NOT NULL,
    present     INTEGER NOT NULL DEFAULT 1,
    seen_at     TEXT    NOT NULL,
    PRIMARY KEY (fingerprint, source)
);

CREATE INDEX IF NOT EXISTS idx_items_name ON items(name);
CREATE INDEX IF NOT EXISTS idx_placements_source ON placements(source, present);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ScanResult:
    source: str
    total: int
    added: list[Item]
    unchanged: int
    vanished: list[str]
    failed: int

    @property
    def summary(self) -> str:
        bits = [f"{self.total} in stash"]
        if self.added:
            bits.append(f"{len(self.added)} new")
        if self.vanished:
            bits.append(f"{len(self.vanished)} gone")
        if self.failed:
            bits.append(f"{self.failed} unparseable")
        return ", ".join(bits)


@dataclass(frozen=True)
class Arrival:
    """One item the tool is taking in from outside a stash file.

    A :meth:`Registry.scan` needs none of this: it reads a stash, so every
    value below is either already in the item's own bytes or is the moment it
    is being read.  An *imported* collection has to be told, because the rest
    are facts about the tool the file came from rather than about the item --
    how many byte-identical copies it held, when it first and last saw it, and
    where the item sat.

    A ``container``/``slot`` is filled in only when the file's stash is this
    one's own; a foreign item has no place here.  That is a state the rest of
    the tool already handles -- see
    :meth:`~tl2stash.service.ItemService.restore`, which falls back to the
    item's kind and the tab's first cell.
    """

    item: Item
    copies: int = 1
    first_seen: str | None = None
    last_seen: str | None = None
    container: int | None = None
    slot: int | None = None


#: Marks a registry row as standing for fish the tool holds which are
#: byte-identical to fish the file also holds -- see :func:`held_key`.
HELD_SUFFIX = ":held"


def held_key(fingerprint: str) -> str:
    """The registry key for a copy the tool holds of bytes the file also has.

    A row keyed by an item's own fingerprint answers one question -- *where are
    these bytes* -- and its ``copies`` count says how many of them the answer
    covers.  Both answers are the same answer, which holds for everything
    except the one thing the tool re-counts.  A fish stack's count is *inside*
    its fingerprint, so a split stack is a new row, and the leftover of a split
    can land on bytes the file already holds: five fish sent out of ten leave
    five, and the five the game was just handed are those exact bytes.  One row
    cannot say both -- ``copies = 2`` would have the tool claiming the game's
    stack, and ``copies = 1`` would have it forget its own.

    So the tool's copy gets a key of its own, this one, and the bare
    fingerprint keeps meaning *the file's*.  Nothing else has to know: every
    other reading of a fingerprint -- the vacuum, :meth:`enforce
    <tl2stash.service.ItemService.enforce>`, the stranded list, the archive's
    own skip -- compares whole fingerprints against ones read out of a file, so
    a held key can never be mistaken for one of them.  A held row is never in
    the file and is never expected to be; the scan finds it under no placement
    and leaves it exactly as it is.

    Downstream the key stays opaque.  A card gathers its members by guid and
    name rather than by fingerprint (``app.models._gathered``), so a held row
    sits on the same card as the rest of its pile, and a fingerprint is only
    ever a lookup key -- which is what lets this be a suffix rather than a new
    column.
    """
    return fingerprint + HELD_SUFFIX


def is_held(key: str) -> bool:
    """Whether ``key`` is a :func:`held_key` rather than an item's own print."""
    return key.endswith(HELD_SUFFIX)


class Registry:
    """SQLite-backed item store.  Use as a context manager."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def __enter__(self) -> "Registry":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    # -- scanning --------------------------------------------------------

    def scan(self, stash: Stash, source: str) -> ScanResult:
        """Record everything in ``stash`` as present in ``source``.

        Items previously seen in this source but absent now are marked
        ``present = 0`` rather than deleted -- that is how items leaving the
        in-game stash becomes visible to the tool.
        """
        now = _now()
        items = stash.items

        # Byte-identical items are one registry row with a copy count.
        counts = Counter(item.fingerprint for item in items)
        by_print: dict[str, Item] = {}
        for item in items:
            by_print.setdefault(item.fingerprint, item)

        added: list[Item] = []
        for print_, item in by_print.items():
            copies = counts[print_]
            existing = self.conn.execute(
                "SELECT 1 FROM items WHERE fingerprint = ?", (print_,)
            ).fetchone()
            if existing is None:
                added.append(item)
                # The literal rather than service.STATUS_IN_STASH: the status
                # constants live in service.py, which imports this module, so
                # reaching back for them would be a cycle.
                self._insert(print_, item, copies, "in_stash", now, now)
            else:
                # Same bytes, maybe a different number of them.
                self.conn.execute(
                    "UPDATE items SET copies = ?, last_seen = ? WHERE fingerprint = ?",
                    (copies, now, print_),
                )

            self._remember(
                print_,
                source,
                item.location.container,
                item.location.slot_index,
                now,
                True,
            )

        # Anything filed under this source that we did not just see is gone.
        seen = set(by_print)
        rows = self.conn.execute(
            "SELECT fingerprint FROM placements WHERE source = ? AND present = 1",
            (source,),
        ).fetchall()
        vanished = [row["fingerprint"] for row in rows if row["fingerprint"] not in seen]
        for print_ in vanished:
            self.conn.execute(
                "UPDATE placements SET present = 0 WHERE fingerprint = ? AND source = ?",
                (print_, source),
            )

        self.conn.commit()
        return ScanResult(
            source=source,
            total=len(items),
            added=added,
            unchanged=len(items) - len(added),
            vanished=vanished,
            failed=len(stash.failed),
        )

    # -- writing ---------------------------------------------------------
    #
    # Two ways in, and exactly one way a row gets written.  ``scan`` reads a
    # file, so everything about an item is either in its bytes or is the
    # moment it was read; ``add`` is handed the rest.

    def _insert(
        self,
        print_: str,
        item: Item,
        copies: int,
        status: str,
        first_seen: str,
        last_seen: str,
    ) -> None:
        """Write one item row.  The only INSERT into ``items`` there is.

        The display fields are re-derived from the item's own bytes here, at
        the one point every item passes through, rather than being passed in
        by each caller -- so there is nowhere for a caller to get them wrong.
        """
        self.conn.execute(
            """
            INSERT INTO items (fingerprint, guid, name, prefix, suffix,
                               level, quantity, identified, num_sockets,
                               num_enchants, num_effects, num_stats,
                               copies, raw, status, first_seen, last_seen)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                print_,
                f"{item.guid:016X}",
                item.base_name,
                item.prefix.rstrip("\x00"),
                item.suffix.rstrip("\x00"),
                item.level,
                item.quantity,
                item.identified,
                item.num_sockets,
                item.num_enchants,
                len(item.effects) + len(item.effects2),
                len(item.stats),
                copies,
                item.raw,
                status,
                first_seen,
                last_seen,
            ),
        )

    def _remember(
        self,
        print_: str,
        source: str,
        container: int,
        slot: int,
        seen: str,
        present: bool,
    ) -> None:
        """Say where an item is in ``source``, present or not."""
        self.conn.execute(
            """
            INSERT INTO placements (fingerprint, source, container, slot,
                                    present, seen_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(fingerprint, source) DO UPDATE SET
                container = excluded.container,
                slot      = excluded.slot,
                present   = excluded.present,
                seen_at   = excluded.seen_at
            """,
            (print_, source, container, slot, 1 if present else 0, seen),
        )

    def add(self, arrivals: list[Arrival], *, source: str, status: str) -> int:
        """Take in items that did not come from a stash file.

        Returns how many were new.  An item the registry already holds is left
        *completely* alone -- its status, its timestamps, its copy count, and
        its placement -- which is what makes reading the same collection in
        twice change nothing the second time, the property a restore needs.
        An item that is already here is here; the file is not news about it.

        One transaction, committed at the end.  The checking happens before
        this is called, so a collection that is refused is refused whole.

        A placement is written only for an arrival that carries one, and then
        with ``present = 0``: these items are precisely the ones the file does
        *not* hold.  ``present`` is read by :meth:`scan`'s vanish check and
        nowhere else, and an import is not a scan -- nothing should look to
        the file for an item it never had.
        """
        added = 0
        for arrival in arrivals:
            print_ = arrival.item.fingerprint
            if self.get(print_) is not None:
                continue
            seen = arrival.last_seen or _now()
            self._insert(
                print_,
                arrival.item,
                arrival.copies,
                status,
                arrival.first_seen or seen,
                seen,
            )
            if arrival.container is not None and arrival.slot is not None:
                self._remember(
                    print_, source, arrival.container, arrival.slot, seen, False
                )
            added += 1
        self.conn.commit()
        return added

    def recount(
        self,
        old: str,
        item: Item,
        *,
        copies: int,
        status: str,
        source: str,
        key: str | None = None,
        first_seen: str | None = None,
        container: int | None = None,
        slot: int | None = None,
    ) -> None:
        """Move a stack's row onto the bytes it has now that its count changed.

        A stack count is inside the fingerprint, so a stack that goes back to
        the game a few fish at a time is a *new* row for what the player sees
        as the same pile -- and the old row is not stale information, it is a
        row describing fish that are no longer there.  So this is a move and
        not an edit: the old row goes, placements and all, and the new bytes
        take its place.

        They may not be *new*, though.  The registry holds byte-identical
        items as one row with a copy count, and a re-counted stack can land
        exactly on bytes already held -- the leftover of a split that happens
        to equal a *tool-side* stack from somewhere else, say.  The row that
        already exists is then the right row and this one joins it: copy
        counts add up, and ``returned`` wins the status.

        Returned rather than absorbed, because one row cannot say "two of
        these bytes are in the file and one is in the tool", and of the two
        answers only that one is safe.  ``returned`` means *the file has these
        and keeps them*, so the tool merely under-counts the copies it still
        holds -- visible, and recovered the moment the player absorbs, since
        the row's copy count is still the whole truth and no write is ever
        made off it.  ``absorbed`` would have the vacuum take the game's
        copies back out of a stash the player had just put them in, and the
        row would then be counting fish the tool no longer holds.

        ``key`` is the row to write when it must *not* be the item's own
        fingerprint -- see :func:`held_key`, which is the one caller and the
        whole reason the parameter exists.  Everything else about the row is
        the item's: its name, its kind, its quantity, and the placement.

        ``first_seen`` is carried over by the caller when the new row is the
        old stack continuing, and left out when it is not; ``container`` and
        ``slot`` -- the placement -- are written with ``present = 0`` for the
        same reason :meth:`add` does it: the bytes are not in the file, and
        the position is only a memory of where they were.

        The deletion is unconditional, so a row already gone is not an error;
        a caller that has several shares of one stack to settle can call this
        more than once without minding.
        """
        now = _now()
        self.conn.execute("DELETE FROM placements WHERE fingerprint = ?", (old,))
        self.conn.execute("DELETE FROM items WHERE fingerprint = ?", (old,))

        print_ = key or item.fingerprint
        existing = self.get(print_)
        if existing is None:
            self._insert(print_, item, copies, status, first_seen or now, now)
        else:
            merged = (
                "returned"
                if "returned" in (existing["status"], status)
                else status
            )
            self.conn.execute(
                "UPDATE items SET copies = ?, status = ?, last_seen = ? "
                "WHERE fingerprint = ?",
                (existing["copies"] + copies, merged, now, print_),
            )
        if container is not None and slot is not None:
            self._remember(print_, source, container, slot, now, False)
        self.conn.commit()

    def forget(self, fingerprints: set[str]) -> int:
        """Delete items outright: their rows, their bytes, and where they were.

        The one destructive method here, and the one thing the registry's
        "items are never deleted" rule has an exception for: a *stranded*
        item -- handed to the game, absent from the file -- is sometimes one
        the player can see is a duplicate a character is already carrying,
        and keeping the tool's copy would leave them holding two.  The row is
        not information then; it is a mistake being put down.

        Placements go first, in the same transaction.  They reference
        ``items`` and carry no ``ON DELETE`` clause, so with ``PRAGMA
        foreign_keys`` on -- as it is here -- an item deleted while a
        placement still points at it is not a lingering row but a failed
        delete.

        Nothing here guards *which* items may go.  A stranded duplicate is
        :meth:`~tl2stash.service.ItemService.remove`'s to offer; a stack
        whose last fish went back to the game is
        :meth:`~tl2stash.service.ItemService.restore_pile`'s and its
        siblings' to settle -- there is no remainder for it to describe, and
        the bytes it had are gone.  Returns how many item rows went.
        """
        if not fingerprints:
            return 0
        marks = ",".join("?" * len(fingerprints))
        params = tuple(fingerprints)
        self.conn.execute(
            f"DELETE FROM placements WHERE fingerprint IN ({marks})", params
        )
        cursor = self.conn.execute(
            f"DELETE FROM items WHERE fingerprint IN ({marks})", params
        )
        self.conn.commit()
        return cursor.rowcount

    # -- queries ---------------------------------------------------------

    def set_status(self, fingerprints: set[str], status: str) -> int:
        """Mark items as absorbed (ours) or in_stash (the game's).

        This is what stops the game resurrecting an item.  Torchlight holds
        the stash in memory and rewrites it wholesale at save points, so an
        absorbed item comes back on the next save unless the tool knows to
        take it out again -- and "absorbed" is exactly that memory.
        """
        if not fingerprints:
            return 0
        marks = ",".join("?" * len(fingerprints))
        cursor = self.conn.execute(
            f"UPDATE items SET status = ? WHERE fingerprint IN ({marks})",
            (status, *fingerprints),
        )
        self.conn.commit()
        return cursor.rowcount

    def fingerprints_with_status(self, status: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT fingerprint FROM items WHERE status = ?", (status,)
        ).fetchall()
        return {row["fingerprint"] for row in rows}

    def absorbed_fingerprints(self) -> set[str]:
        """Every item the tool has taken, by fingerprint."""
        return self.fingerprints_with_status("absorbed")

    def get(self, fingerprint: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM items WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()

    def search(self, query: str, limit: int = 500) -> list[sqlite3.Row]:
        """Find items whose name contains every whitespace-separated term."""
        terms = [t for t in query.split() if t]
        if not terms:
            return self.rows()[:limit]
        sql = "SELECT * FROM items WHERE 1=1"
        params: list = []
        for term in terms:
            sql += " AND (name LIKE ? OR prefix LIKE ? OR suffix LIKE ?)"
            params.extend([f"%{term}%"] * 3)
        sql += " ORDER BY name COLLATE NOCASE, level LIMIT ?"
        params.append(limit)
        return self.conn.execute(sql, params).fetchall()

    def item_count(self) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(copies), 0) AS n FROM items"
        ).fetchone()
        return row["n"]

    def rows(self, status: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM items"
        params: tuple = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY name COLLATE NOCASE, level"
        return self.conn.execute(sql, params).fetchall()

    def where_is(self, print_: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM placements WHERE fingerprint = ? AND present = 1",
            (print_,),
        ).fetchall()

    def placements_for(self, source: str) -> dict[str, sqlite3.Row]:
        """Every placement in ``source``, keyed by fingerprint.

        One query rather than one per item, because the window wants this for
        the whole collection on every refresh.
        """
        rows = self.conn.execute(
            "SELECT * FROM placements WHERE source = ?", (source,)
        ).fetchall()
        return {row["fingerprint"]: row for row in rows}

    def last_placement(self, print_: str, source: str) -> sqlite3.Row | None:
        """Where this item last sat in ``source``, present or not.

        Restoring needs this rather than :meth:`where_is`: an absorbed item is
        precisely one that is *not* present, and its last position is exactly
        the one worth putting it back in.
        """
        return self.conn.execute(
            "SELECT * FROM placements WHERE fingerprint = ? AND source = ?",
            (print_, source),
        ).fetchone()

    def first_slot(self, container: int, source: str) -> int | None:
        """The lowest slot this save has ever held in this container.

        Every item the tool has seen leaves a placement behind, present or
        not, so this is the tab's own first cell even after everything in it
        has been taken -- and a tab the player has swept out is exactly the
        one they are putting something back into.  It is the long way round to
        what the game's own files state outright; see
        :meth:`tl2stash.gamedata.GameData.slot_base`.

        ``None`` when this save has never held anything in that container,
        which is the one case where the tool has nothing to go on.
        """
        row = self.conn.execute(
            "SELECT MIN(slot) AS first FROM placements WHERE source = ? AND container = ?",
            (source, container),
        ).fetchone()
        return row["first"]
