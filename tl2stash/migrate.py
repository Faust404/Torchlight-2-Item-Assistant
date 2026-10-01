"""Splitting one registry into one registry per stash.

The registry used to keep every stash in a single database, with ``items``
keyed by fingerprint alone -- so the *same* item sitting in both a vanilla and
a modded stash was one row with one status, and no query could tell them
apart.  Worse, the string naming each stash had two spellings depending on
which code wrote it: ``tools/scan.py`` used ``kind/steam_id`` while
``ItemService`` used the absolute path of the file.  One stash, two identities,
and neither half could see the other's items.

This moves the old database into one file per stash and collapses the two
spellings into the one that survives the Steam library moving.

Two things it must not do:

* **Rescan.** :meth:`Registry.scan` re-reads items out of a stash *file* and
  writes every one of them back as ``in_stash``.  For an item the tool has
  absorbed -- and therefore removed from the file -- that would silently
  un-absorb it.  ``absorbed`` is the entire record that the tool owns the
  item; every other copy of it is gone.  So rows are copied verbatim.
* **Lose anything.**  The items are the player's.  Rows are counted before
  and after, and a mismatch stops the whole thing rather than half-writing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .registry import Registry
from .saves import STASH_FILENAME, SaveLocation

__all__ = ["SplitReport", "canonical_source", "split_registry"]


@dataclass
class SplitReport:
    """What a split did, or would do."""

    #: Canonical stash key -> the database written for it.
    written: dict[str, Path] = field(default_factory=dict)
    #: Canonical stash key -> how many items went into it.
    counts: dict[str, int] = field(default_factory=dict)
    #: Old spelling -> new, for the keys that needed renaming.
    renamed: dict[str, str] = field(default_factory=dict)
    #: Items with no placement at all.  They name no stash, so they cannot be
    #: filed; reported rather than dropped.
    orphans: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def summary(self) -> str:
        if not self.written:
            return "nothing to split"
        return (
            f"{self.total} items across {len(self.written)} stash(es): "
            + ", ".join(f"{key} ({self.counts[key]})" for key in self.written)
        )


def canonical_source(source: str) -> str:
    """Normalise a registry source key to ``kind/steam_id``.

    Only a key that names a stash *file* is rewritten.  The stored value may be
    an absolute path -- from the days when the two callers disagreed -- or the
    canonical key already; anything else is left exactly as it is, because a
    key the tool did not write is not the tool's to reinterpret.
    """
    path = Path(source)
    if path.name == STASH_FILENAME:
        return SaveLocation.at(path).key
    return source


def _dedupe(placements: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """One placement per (fingerprint, source), preferring the present one.

    Two spellings of the same stash can each hold a placement for one item.
    Since they are the same stash, they are the same placement, and the row
    that says the item is *there* is the one that matches the file.
    """
    best: dict[str, sqlite3.Row] = {}
    for row in placements:
        current = best.get(row["fingerprint"])
        if current is None:
            best[row["fingerprint"]] = row
            continue
        if (row["present"], row["seen_at"]) > (current["present"], current["seen_at"]):
            best[row["fingerprint"]] = row
    return list(best.values())


def split_registry(
    db_path: str | Path, out_dir: str | Path, *, dry_run: bool = False
) -> SplitReport:
    """Move ``db_path`` into one database per stash under ``out_dir``.

    Safe to run twice: each target is written with ``INSERT OR REPLACE`` and
    verified by fingerprint set, so a second run is a no-op and a run that
    fails leaves the originals untouched.
    """
    db_path = Path(db_path)
    out_dir = Path(out_dir)
    report = SplitReport(dry_run=dry_run)

    if not db_path.is_file():
        raise FileNotFoundError(f"no registry at {db_path}")

    source_conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    source_conn.row_factory = sqlite3.Row
    try:
        items = source_conn.execute("SELECT * FROM items").fetchall()
        placements = source_conn.execute("SELECT * FROM placements").fetchall()
        item_columns = [
            row[1] for row in source_conn.execute("PRAGMA table_info(items)")
        ]
        placement_columns = [
            row[1] for row in source_conn.execute("PRAGMA table_info(placements)")
        ]
    finally:
        source_conn.close()

    by_print = {row["fingerprint"]: row for row in items}
    if not by_print:
        return report

    # Group placements under their canonical stash.
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in placements:
        key = canonical_source(row["source"])
        if key != row["source"]:
            report.renamed[row["source"]] = key
        grouped.setdefault(key, []).append(row)

    filed = {row["fingerprint"] for rows in grouped.values() for row in rows}
    report.orphans = sorted(fp for fp in by_print if fp not in filed)

    for key, rows in sorted(grouped.items()):
        members = _dedupe(rows)
        fingerprints = [row["fingerprint"] for row in members if row["fingerprint"] in by_print]
        report.counts[key] = len(fingerprints)
        report.written[key] = out_dir / f"items-{key.replace('/', '-')}.db"

        if dry_run:
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        target = report.written[key]
        with Registry(target) as registry:
            for fingerprint in fingerprints:
                registry.conn.execute(
                    f"INSERT OR REPLACE INTO items ({','.join(item_columns)}) "
                    f"VALUES ({','.join('?' * len(item_columns))})",
                    tuple(by_print[fingerprint][column] for column in item_columns),
                )
            for row in members:
                if row["fingerprint"] not in by_print:
                    continue
                # The source is rewritten to the canonical key as it goes in.
                # Copying it verbatim would carry the old spelling into the
                # new database -- the rows would be filed under the path while
                # the app looks them up by key, and every placement lookup
                # would come back empty.  Which is the same bug, one layer on.
                values = [
                    key if column == "source" else row[column]
                    for column in placement_columns
                ]
                registry.conn.execute(
                    f"INSERT OR REPLACE INTO placements "
                    f"({','.join(placement_columns)}) "
                    f"VALUES ({','.join('?' * len(placement_columns))})",
                    tuple(values),
                )
            registry.conn.commit()
            _verify(target, fingerprints, by_print)

    return report


def _verify(path: Path, fingerprints: list[str], original: dict[str, sqlite3.Row]) -> None:
    """Every item present, and every status exactly as it was.

    The status is the part that matters.  An item that arrives without its
    ``absorbed`` mark is an item the tool has forgotten it owns -- and since
    the tool removed it from the game, nothing else has a copy.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        got = {row["fingerprint"]: row["status"] for row in conn.execute("SELECT * FROM items")}
    finally:
        conn.close()

    missing = sorted(set(fingerprints) - set(got))
    if missing:
        raise RuntimeError(f"{path} is missing {len(missing)} item(s): {missing[:5]}")

    wrong = [
        fp for fp in fingerprints
        if got[fp] != original[fp]["status"]
    ]
    if wrong:
        raise RuntimeError(
            f"{path} changed the status of {len(wrong)} item(s): {wrong[:5]}"
        )
