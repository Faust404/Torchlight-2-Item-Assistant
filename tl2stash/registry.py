"""The item registry: a SQLite record of everything the tool has seen.

Two tables, with a deliberate split:

``items``       one row per *distinct item*, keyed by a fingerprint of its raw
                bytes.  Two byte-identical items (a stack of identical potions,
                say) collapse to one row with ``copies`` counted, so nothing is
                silently lost the way a naive "unique fingerprint" would lose it.
``placements``  where that item currently sits, scoped to the save file it was
                seen in.  A player with both a vanilla and a modded stash has
                genuinely separate stashes, so presence has to be per-file.

Items are never deleted.  An item that stops appearing in a stash keeps its row
and its bytes -- "it left the stash" is information, not garbage.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .item import Item
from .stash import Stash

__all__ = ["Registry", "ScanResult"]

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
                self.conn.execute(
                    """
                    INSERT INTO items (fingerprint, guid, name, prefix, suffix,
                                       level, quantity, identified, num_sockets,
                                       num_enchants, num_effects, num_stats,
                                       copies, raw, status, first_seen, last_seen)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'in_stash', ?, ?)
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
                        now,
                        now,
                    ),
                )
            else:
                # Same bytes, maybe a different number of them.
                self.conn.execute(
                    "UPDATE items SET copies = ?, last_seen = ? WHERE fingerprint = ?",
                    (copies, now, print_),
                )

            self.conn.execute(
                """
                INSERT INTO placements (fingerprint, source, container, slot,
                                        present, seen_at)
                VALUES (?,?,?,?,1,?)
                ON CONFLICT(fingerprint, source) DO UPDATE SET
                    container = excluded.container,
                    slot      = excluded.slot,
                    present   = 1,
                    seen_at   = excluded.seen_at
                """,
                (print_, source, item.location.container, item.location.slot_index, now),
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

    def absorbed_fingerprints(self) -> set[str]:
        """Every item the tool has taken, by fingerprint."""
        rows = self.conn.execute(
            "SELECT fingerprint FROM items WHERE status = 'absorbed'"
        ).fetchall()
        return {row["fingerprint"] for row in rows}

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
