"""Splitting the old single registry into one database per stash.

The thing being tested is not that rows move.  It is that rows move *whole* --
in particular that an absorbed item is still absorbed afterwards.  ``absorbed``
is the only record that the tool owns an item; by the time the migration runs,
the tool has already taken it out of the game, so a status lost here is an item
lost outright.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash.migrate import canonical_source, split_registry  # noqa: E402
from tl2stash.registry import Registry  # noqa: E402
from tl2stash.saves import SaveLocation  # noqa: E402
from tl2stash.service import STATUS_ABSORBED  # noqa: E402

from test_archive import write_synthetic_stash  # noqa: E402


STEAM_ID = "76561198328811052"


def _stash(root: Path, kind: str, names: list[str]):
    """A synthetic stash in a realistic tree, plus its location."""
    tree = "save" if kind == "vanilla" else "modsave"
    path = root / tree / STEAM_ID / "sharedstash_v2.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_synthetic_stash(path, names)
    return SaveLocation.at(path)


def _old_registry(path: Path, root: Path):
    """Build the registry as it used to be: one file, two key spellings.

    Mirrors the real thing exactly -- the app wrote the absolute path, the CLI
    wrote ``kind/steam_id``, and both were looking at the same two files.
    """
    from tl2stash import read_stash_file

    vanilla = _stash(root, "vanilla", ["Alpha", "Beta"])
    modded = _stash(root, "modded", ["Gamma"])

    with Registry(path) as reg:
        # The app's spelling: the absolute path.
        reg.scan(read_stash_file(vanilla.path), source=str(vanilla.path))
        # The CLI's spelling: kind/steam_id.
        reg.scan(read_stash_file(vanilla.path), source=vanilla.key)
        reg.scan(read_stash_file(modded.path), source=modded.key)

        absorbed = {
            row["fingerprint"] for row in reg.rows() if row["name"] == "Alpha"
        }
        reg.set_status(absorbed, STATUS_ABSORBED)
    return vanilla, modded


@pytest.fixture
def old_registry(tmp_path):
    db = tmp_path / "var" / "items.db"
    db.parent.mkdir(parents=True)
    vanilla, modded = _old_registry(db, tmp_path / "Documents")
    return db, vanilla, modded


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def test_a_stash_keeps_its_identity_when_the_library_moves(tmp_path):
    """The reason the key is not the path.

    A Steam library moving between drives rewrites every path.  Keyed on the
    path, the registry would find a stash it had never seen -- every item new,
    everything recorded before apparently lost.
    """

    def stash_at(root: Path) -> SaveLocation:
        return SaveLocation.at(
            root / "My Games" / "Torchlight 2" / "save" / STEAM_ID
            / "sharedstash_v2.bin"
        )

    on_c = stash_at(tmp_path / "C")
    on_e = stash_at(tmp_path / "E")

    assert on_c.key == on_e.key == f"vanilla/{STEAM_ID}"
    assert on_c.path != on_e.path, "the paths differ; that is the whole point"


def test_a_modded_stash_is_a_different_stash(tmp_path):
    """Vanilla and modded are separate files, so separate everything."""
    tree = tmp_path / "Torchlight 2"
    vanilla = SaveLocation.at(tree / "save" / STEAM_ID / "sharedstash_v2.bin")
    modded = SaveLocation.at(tree / "modsave" / STEAM_ID / "sharedstash_v2.bin")

    assert vanilla.key != modded.key
    assert vanilla.db_name != modded.db_name


def test_canonical_source_only_rewrites_what_it_recognises():
    path_key = f"C:/Users/someone/Documents/save/{STEAM_ID}/sharedstash_v2.bin"
    assert canonical_source(path_key) == f"vanilla/{STEAM_ID}"
    assert canonical_source(f"vanilla/{STEAM_ID}") == f"vanilla/{STEAM_ID}"
    # A key the tool did not write is not the tool's to reinterpret.
    assert canonical_source("test") == "test"


# --------------------------------------------------------------------------
# Splitting
# --------------------------------------------------------------------------


def test_split_gives_each_stash_its_own_database(old_registry, tmp_path):
    db, vanilla, modded = old_registry
    out = tmp_path / "var"

    report = split_registry(db, out)

    assert report.written[vanilla.key] == out / f"items-vanilla-{STEAM_ID}.db"
    assert report.written[modded.key] == out / f"items-modded-{STEAM_ID}.db"
    assert report.counts[vanilla.key] == 2
    assert report.counts[modded.key] == 1


def test_the_two_spellings_of_one_stash_become_one(old_registry, tmp_path):
    """The bug this migration exists for.

    The same file was recorded under its absolute path and under
    ``kind/steam_id``.  Both are the same stash and must end up in the same
    place, not in two databases that cannot see each other.
    """
    db, vanilla, _ = old_registry
    report = split_registry(db, tmp_path / "var")

    assert str(vanilla.path) in report.renamed
    assert report.renamed[str(vanilla.path)] == vanilla.key

    with Registry(tmp_path / "var" / f"items-vanilla-{STEAM_ID}.db") as reg:
        assert len(reg.rows()) == 2, "the two spellings produced duplicate rows"
        assert len(reg.placements_for(vanilla.key)) == 2


def test_an_absorbed_item_is_still_absorbed_afterwards(old_registry, tmp_path):
    """The one that would hurt.

    ``absorbed`` is the whole record that the tool owns an item, and the tool
    has already removed it from the game.  Losing the mark here loses the item.
    """
    db, vanilla, _ = old_registry
    split_registry(db, tmp_path / "var")

    with Registry(tmp_path / "var" / f"items-vanilla-{STEAM_ID}.db") as reg:
        absorbed = reg.absorbed_fingerprints()
        assert len(absorbed) == 1
        assert reg.get(next(iter(absorbed)))["name"] == "Alpha"


def test_the_original_is_left_alone(old_registry, tmp_path):
    db, _, _ = old_registry
    before = db.read_bytes()
    split_registry(db, tmp_path / "var")
    assert db.read_bytes() == before


def test_a_dry_run_writes_nothing(old_registry, tmp_path):
    db, vanilla, _ = old_registry
    out = tmp_path / "split"

    report = split_registry(db, out, dry_run=True)

    assert report.counts[vanilla.key] == 2, "a dry run still reports what it would do"
    assert not out.exists(), "a dry run created a directory"


def test_running_it_twice_changes_nothing(old_registry, tmp_path):
    db, vanilla, _ = old_registry
    out = tmp_path / "var"
    target = out / f"items-vanilla-{STEAM_ID}.db"

    def snapshot(path):
        with Registry(path) as reg:
            return sorted(
                (row["fingerprint"], row["status"], row["copies"]) for row in reg.rows()
            )

    split_registry(db, out)
    first = snapshot(target)
    split_registry(db, out)

    assert len(first) == 2
    assert snapshot(target) == first, "a second run changed the contents"


def test_an_item_naming_no_stash_is_reported_not_dropped(tmp_path):
    """It cannot be filed, so it is named rather than quietly discarded."""
    db = tmp_path / "var" / "items.db"
    db.parent.mkdir(parents=True)
    _old_registry(db, tmp_path / "Documents")

    # An item with no placement at all: nothing says which stash it came from.
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO items (fingerprint, guid, name, level, quantity, identified,"
        " num_sockets, num_enchants, num_effects, num_stats, copies, raw, status,"
        " first_seen, last_seen)"
        " VALUES ('orphan', '0', 'Stray', 1, 1, 1, 0, 0, 0, 0, 1, X'00', 'absorbed',"
        " '2026-01-01', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    report = split_registry(db, tmp_path / "var")

    assert report.orphans == ["orphan"]
    assert report.total == 3, "the filed items are still filed"


def test_split_refuses_a_registry_that_is_not_there(tmp_path):
    with pytest.raises(FileNotFoundError):
        split_registry(tmp_path / "nothing.db", tmp_path / "var")
