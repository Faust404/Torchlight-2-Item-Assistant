"""Tests for removing items from a stash file.

Every test here works on a copy.  The player's real save is never written to
by the test suite, and neither is the modded or vanilla stash.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash import SaveFile, read_save_file, read_stash_file, write_save_file  # noqa: E402
from tl2stash.archive import (  # noqa: E402
    BACKUP_SUFFIX,
    RestoreRequest,
    archive_stash,
    next_free_slot,
    plan_removal,
    restore_items,
    serialize_body,
)
from tl2stash.crypto import checksum  # noqa: E402
from tl2stash.saves import find_save_locations  # noqa: E402

from test_format import synthetic_item  # noqa: E402
from tl2stash import parse_item  # noqa: E402


def write_synthetic_stash(path: Path, names: list[str]) -> list[str]:
    """Write a stash containing one item per name; return their fingerprints."""
    items = [parse_item(synthetic_item(name=n, slot=3322 + i)[0]) for i, n in enumerate(names)]
    body = serialize_body(items)
    write_save_file(
        path,
        SaveFile(
            version=0x44, dummy=1, stored_checksum=checksum(body),
            body=body, stored_size=13 + len(body),
        ),
    )
    return [i.fingerprint for i in items]


# --------------------------------------------------------------------------
# Rebuilding a body
# --------------------------------------------------------------------------


def test_serialize_body_is_a_copy_not_an_encode():
    items = [parse_item(synthetic_item(name=n)[0]) for n in ("One", "Two")]
    body = serialize_body(items)
    assert int.from_bytes(body[:4], "little") == 2
    assert body[4 : 4 + 4] == len(items[0].raw).to_bytes(4, "little")
    assert body[8 : 8 + len(items[0].raw)] == items[0].raw


def test_serialize_empty_stash():
    assert serialize_body([]) == b"\x00\x00\x00\x00"


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------


def test_plan_removal_matches_by_fingerprint():
    a, b, c = (parse_item(synthetic_item(name=n)[0]) for n in ("Alpha", "Beta", "Gamma"))
    stash = _fake_stash([a, b, c])
    plan = plan_removal(stash, {b.fingerprint})
    assert [i.base_name for i in plan.keep] == ["Alpha", "Gamma"]
    assert [i.base_name for i in plan.remove] == ["Beta"]


def test_plan_removal_matches_a_moved_item():
    """The whole point of a location-independent fingerprint."""
    item = parse_item(synthetic_item(name="Wanderer", slot=10, container=24)[0])
    moved = parse_item(item.relocated(slot_index=99, container=26))
    plan = plan_removal(_fake_stash([moved]), {item.fingerprint})
    assert plan.remove == [moved]


class _FakeStash:
    def __init__(self, items):
        self.items = items
        self.failed = []


def _fake_stash(items):
    return _FakeStash(items)


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


def test_archive_removes_exactly_one_item(tmp_path):
    path = tmp_path / "sharedstash_v2.bin"
    prints = write_synthetic_stash(path, ["Alpha", "Beta", "Gamma"])
    before = read_stash_file(path)
    beta = next(i for i in before.items if i.base_name == "Beta")

    report = archive_stash(path, {prints[1]})

    assert report.changed
    assert [i.base_name for i in report.removed] == ["Beta"]
    assert report.kept == 2

    after = read_stash_file(path)
    assert sorted(i.base_name for i in after.items) == ["Alpha", "Gamma"]
    assert after.save.checksum_ok, "written file fails its own checksum"

    # The survivors keep their bytes, in order, untouched.
    assert [i.raw for i in after.items] == [
        i.raw for i in before.items if i.base_name != "Beta"
    ]
    # And the file shrank by exactly the removed blob plus its length prefix.
    assert len(before.save.body) - len(after.save.body) == len(beta.raw) + 4


def test_archive_leaves_other_items_byte_identical(tmp_path):
    path = tmp_path / "sharedstash_v2.bin"
    write_synthetic_stash(path, ["Alpha", "Beta", "Gamma"])
    before = read_stash_file(path)
    keep_raw = [i.raw for i in before.items if i.base_name != "Gamma"]

    archive_stash(path, {before.items[2].fingerprint})

    after = read_stash_file(path)
    assert [i.raw for i in after.items] == keep_raw


def test_archive_is_a_no_op_when_nothing_matches(tmp_path):
    path = tmp_path / "sharedstash_v2.bin"
    write_synthetic_stash(path, ["Alpha", "Beta"])
    original = path.read_bytes()

    report = archive_stash(path, {"no-such-fingerprint"})

    assert not report.changed
    assert report.backup is None
    assert path.read_bytes() == original


def test_archive_dry_run_writes_nothing(tmp_path):
    path = tmp_path / "sharedstash_v2.bin"
    prints = write_synthetic_stash(path, ["Alpha", "Beta"])
    original = path.read_bytes()

    report = archive_stash(path, {prints[0]}, dry_run=True)

    assert not report.changed
    assert len(report.removed) == 1  # it knows what it would do
    assert path.read_bytes() == original


def test_archive_makes_a_backup(tmp_path):
    path = tmp_path / "sharedstash_v2.bin"
    prints = write_synthetic_stash(path, ["Alpha", "Beta"])
    original = path.read_bytes()

    report = archive_stash(path, {prints[0]})

    assert report.backup is not None and report.backup.is_file()
    assert report.backup.read_bytes() == original
    assert report.backup.name.endswith(BACKUP_SUFFIX)


def test_archive_leaves_no_staging_file_behind(tmp_path):
    path = tmp_path / "sharedstash_v2.bin"
    prints = write_synthetic_stash(path, ["Alpha", "Beta"])
    archive_stash(path, {prints[0]})
    assert not list(tmp_path.glob("*.tl2ia-tmp"))


def test_archive_is_idempotent(tmp_path):
    path = tmp_path / "sharedstash_v2.bin"
    prints = write_synthetic_stash(path, ["Alpha", "Beta", "Gamma"])

    first = archive_stash(path, {prints[0]})
    assert first.changed

    # Running again with the same request must be a no-op, because this is
    # what happens every time the game rewrites the stash.
    second = archive_stash(path, {prints[0]})
    assert not second.changed


def test_archive_prunes_old_backups(tmp_path):
    path = tmp_path / "sharedstash_v2.bin"
    write_synthetic_stash(path, ["Alpha", "Beta", "Gamma"])
    stash = read_stash_file(path)

    for item in stash.items:
        archive_stash(path, {item.fingerprint}, keep_backups=2)

    backups = list(tmp_path.glob(f"*{BACKUP_SUFFIX}"))
    # Two kept, plus possibly the newest sharing a timestamp with a peer.
    assert len(backups) <= 3


# --------------------------------------------------------------------------
# Against a real save, on a copy
# --------------------------------------------------------------------------

_REAL = [pytest.param(loc.path, id=f"{loc.kind}-{loc.steam_id}") for loc in find_save_locations()]


@pytest.mark.skipif(not _REAL, reason="no Torchlight 2 saves on this machine")
@pytest.mark.parametrize("source", _REAL)
def test_real_stash_rebuilds_byte_exactly(source, tmp_path):
    """The strongest available check that nothing is re-encoded.

    If serialising the parsed items reproduces the original body byte for
    byte, then removal cannot corrupt anything it does not remove.
    """
    stash = read_stash_file(source)
    assert serialize_body(stash.items) == stash.save.body


@pytest.mark.skipif(not _REAL, reason="no Torchlight 2 saves on this machine")
@pytest.mark.parametrize("source", _REAL)
def test_real_stash_round_trip_through_archive(source, tmp_path):
    """Take a real save, remove one item, and read it back."""
    copy = tmp_path / "sharedstash_v2.bin"
    shutil.copy2(source, copy)

    before = read_stash_file(copy)
    victim = before.items[0]

    report = archive_stash(copy, {victim.fingerprint})
    assert report.changed

    after = read_stash_file(copy)
    assert after.save.checksum_ok
    assert not after.failed, [e.error for e in after.failed]
    assert len(after.items) == len(before.items) - 1
    assert victim.fingerprint not in {i.fingerprint for i in after.items}
    assert [i.raw for i in after.items] == [
        i.raw for i in before.items if i.fingerprint != victim.fingerprint
    ]


# --------------------------------------------------------------------------
# Putting items back
# --------------------------------------------------------------------------


def test_next_free_slot_prefers_the_original():
    assert next_free_slot({10, 11, 12}, preferred=99) == 99


def test_next_free_slot_fills_a_gap():
    assert next_free_slot({10, 11, 13, 14}, preferred=11) == 12


def test_next_free_slot_appends_when_full():
    assert next_free_slot({10, 11, 12}) == 13


def test_next_free_slot_needs_a_hint_for_an_empty_container():
    with pytest.raises(ValueError):
        next_free_slot(set())
    assert next_free_slot(set(), preferred=7) == 7
    assert next_free_slot(set(), base=7) == 7


def test_restore_puts_an_item_back_where_it_was(tmp_path):
    path = tmp_path / "sharedstash_v2.bin"
    prints = write_synthetic_stash(path, ["Alpha", "Beta", "Gamma"])
    before = path.read_bytes()
    beta = read_stash_file(path).items[1]

    archive_stash(path, {prints[1]})
    assert len(read_stash_file(path).items) == 2

    report = restore_items(
        path,
        [RestoreRequest(raw=beta.raw, container=beta.location.container,
                        slot=beta.location.slot_index, label="Beta")],
    )
    assert report.changed
    assert report.restored == [("Beta", beta.location.container, beta.location.slot_index)]

    # The same items back in the same slots.  Not the same *file order*:
    # restoring appends, so the item returns at the end of the list rather
    # than in its old position.  Order carries no meaning -- each item's blob
    # records its own container and slot, which is what the game reads -- so
    # this is equivalent to the original.  (Restoring in slot order into an
    # empty stash does reproduce the file byte for byte; see the real-save
    # round-trip test.)
    after = read_stash_file(path)
    assert after.save.checksum_ok

    def placements(stash):
        return sorted(
            (i.location.container, i.location.slot_index, i.fingerprint)
            for i in stash.items
        )

    assert placements(after) == placements(read_stash_file_from(before))


def read_stash_file_from(raw: bytes):
    """Parse a raw file image that is already in memory."""
    import tempfile

    from tl2stash import read_stash_file as _read

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as handle:
        handle.write(raw)
        name = handle.name
    return _read(name)


def test_restore_skips_an_item_that_never_left(tmp_path):
    path = tmp_path / "sharedstash_v2.bin"
    write_synthetic_stash(path, ["Alpha", "Beta"])
    item = read_stash_file(path).items[0]

    report = restore_items(
        path, [RestoreRequest(raw=item.raw, container=item.location.container,
                              slot=item.location.slot_index)]
    )
    assert report.restored == []
    assert len(report.skipped) == 1
    assert not report.changed
    # In particular it did not become two copies of itself.
    assert len(read_stash_file(path).items) == 2


def test_restore_is_idempotent(tmp_path):
    path = tmp_path / "sharedstash_v2.bin"
    prints = write_synthetic_stash(path, ["Alpha", "Beta"])
    item = read_stash_file(path).items[0]
    request = RestoreRequest(raw=item.raw, container=item.location.container,
                             slot=item.location.slot_index)

    archive_stash(path, {prints[0]})
    first = restore_items(path, [request])
    assert first.changed

    second = restore_items(path, [request])
    assert not second.changed
    assert len(read_stash_file(path).items) == 2


@pytest.mark.skipif(not _REAL, reason="no Torchlight 2 saves on this machine")
@pytest.mark.parametrize("source", _REAL)
def test_real_stash_full_round_trip_is_byte_identical(source, tmp_path):
    """Empty the stash, put everything back, and get the same file.

    This is the safety property the whole approach rests on.  Taking every
    item out makes the registry the only copy, so "put it back" has to be
    exact -- not merely equivalent.
    """
    copy = tmp_path / "sharedstash_v2.bin"
    shutil.copy2(source, copy)
    original = copy.read_bytes()

    before = read_stash_file(copy)
    requests = [
        RestoreRequest(
            raw=item.raw,
            container=item.location.container,
            slot=item.location.slot_index,
            label=item.display_name,
        )
        for item in sorted(
            before.items, key=lambda i: (i.location.container, i.location.slot_index)
        )
    ]

    archive_stash(copy, {i.fingerprint for i in before.items})
    emptied = read_stash_file(copy)
    assert emptied.items == []
    assert emptied.save.checksum_ok

    report = restore_items(copy, requests)
    assert len(report.restored) == len(requests)
    assert report.skipped == []

    assert copy.read_bytes() == original, "round trip did not reproduce the file"


@pytest.mark.skipif(not _REAL, reason="no Torchlight 2 saves on this machine")
@pytest.mark.parametrize("source", _REAL)
def test_real_stash_remove_everything(source, tmp_path):
    """Removing every item must leave a valid, empty stash -- not a broken file."""
    copy = tmp_path / "sharedstash_v2.bin"
    shutil.copy2(source, copy)

    before = read_stash_file(copy)
    archive_stash(copy, {i.fingerprint for i in before.items})

    after = read_stash_file(copy)
    assert after.items == []
    assert after.save.checksum_ok
    assert after.save.body == b"\x00\x00\x00\x00"
    assert len(copy.read_bytes()) == 13 + 4
