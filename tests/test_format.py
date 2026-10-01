"""Tests for the save-format layer.

Most of these run against a synthetic item blob built field by field, so they
hold on any machine.  The tests that need real save files skip when the files
are absent -- the saves are the player's data, not fixtures to check in.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash import (  # noqa: E402
    descramble,
    parse_item,
    read_save_file,
    read_stash_file,
    scramble,
    write_save_file,
)
from tl2stash.binary import ParseError, Reader  # noqa: E402
from tl2stash.crypto import SaveFile, checksum  # noqa: E402
from tl2stash.item import _read_item, strip_markup  # noqa: E402
from tl2stash.registry import Registry  # noqa: E402
from tl2stash.saves import find_save_locations  # noqa: E402

# --------------------------------------------------------------------------
# Synthetic blob construction
# --------------------------------------------------------------------------


def synthetic_tail(
    *,
    records: int = 0,
    trailer: bytes = b"",
    stats: tuple[int, ...] = (),
    junk: bytes = b"",
) -> bytes:
    """Build an item's tail: the part whose shape has to be worked out.

    ``records`` added-damage records of three u32s each, then an optional
    ``trailer`` word, then the four lists -- all empty but for ``stats`` --
    and ``junk`` past the end, which nothing should read.
    """
    out = bytearray()
    out.extend(records.to_bytes(2, "little"))
    out.extend(b"\x00" * (12 * records))
    out.extend(trailer)
    for _ in range(3):  # effects, effects2, triggerables
        out.extend((0).to_bytes(4, "little"))
    out.extend(len(stats).to_bytes(4, "little"))
    for guid in stats:
        out.extend(guid.to_bytes(8, "little"))
        out.extend(b"\x00" * 4)
    out.extend(junk)
    return bytes(out)


def synthetic_item(
    name: str = "Test Blade",
    prefix: str = "",
    suffix: str = "",
    *,
    slot: int = 10,
    container: int = 24,
    level: int = 5,
    extra_records: bytes = b"",
    tail: bytes | None = None,
) -> tuple[bytes, int]:
    """Build an item blob that parses, and its location offset.

    ``extra_records`` is spliced in *after* the count field, so the count is
    derived from it rather than passed separately -- which is the property
    under test.  ``tail`` replaces the whole variable-length tail; the default
    is the plainest one there is -- no damage types and four empty lists.
    """
    assert len(extra_records) % 8 == 0
    out = bytearray()

    # ``out.extend`` rather than ``out +=``: augmented assignment inside a
    # nested function rebinds the name, making it local to that function.
    def u8(v):
        out.append(v)

    def u16(v):
        out.extend(v.to_bytes(2, "little"))

    def u32(v):
        out.extend(v.to_bytes(4, "little"))

    def u64(v):
        out.extend(v.to_bytes(8, "little"))

    def text(s):
        u16(len(s))
        out.extend(s.encode("utf-16-le"))

    u8(0)
    u64(0x1122334455667788)
    text(name)
    text(prefix)
    text(suffix)
    out.extend(bytes(24))                      # random id
    u32(len(extra_records) // 8)               # extra-record count
    out.extend(extra_records)
    out.extend(bytes(29))
    u32(0)                                     # enchant count
    location_offset = len(out)
    u16(slot)
    u16(container)
    out.extend(bytes(6))
    u8(1)                                      # identified
    out.extend(bytes(8))
    out.extend(bytes(80))
    u32(level)
    u32(1)                                     # quantity
    u32(0)                                     # sockets
    u32(0)                                     # gems
    out.extend(bytes(4))
    u32(0)                                     # max damage
    u32(0)                                     # armor
    out.extend(bytes(4))
    out.extend(b"\xff" * 12)
    out.extend(synthetic_tail() if tail is None else tail)
    return bytes(out), location_offset


# --------------------------------------------------------------------------
# Crypto
# --------------------------------------------------------------------------


def test_checksum_seed_and_roll():
    # seed with no bytes is the seed itself
    assert checksum(b"") == 0x14D3
    # acc = acc * 33 + byte
    assert checksum(b"\x01") == 0x14D3 * 33 + 1
    assert checksum(b"\x00" * 4) == (0x14D3 * 33**4) & 0xFFFFFFFF


def test_scramble_descramble_are_inverses():
    data = bytes(range(256)) * 3
    assert descramble(scramble(data)) == data
    assert scramble(descramble(data)) == data


def test_scramble_preserves_length_and_zero_run():
    data = bytes(64)
    assert scramble(data) == data  # all-zero passes through untouched
    assert len(descramble(data)) == 64


def test_save_file_round_trip(tmp_path):
    body = bytes(range(256)) * 8
    save = SaveFile(
        version=0x44, dummy=1, stored_checksum=checksum(body), body=body,
        stored_size=13 + len(body),
    )
    path = tmp_path / "roundtrip.bin"
    write_save_file(path, save)

    reread = read_save_file(path)
    assert reread.body == body
    assert reread.version == 0x44
    assert reread.checksum_ok
    assert reread.size_ok


# --------------------------------------------------------------------------
# Item parsing
# --------------------------------------------------------------------------


def test_synthetic_item_parses():
    blob, offset = synthetic_item(name="Test Blade", prefix="Keen", level=7)
    item = parse_item(blob)
    assert item.base_name == "Test Blade"
    assert item.display_name == "Keen Test Blade"
    assert item.level == 7
    assert item.location.slot_index == 10
    assert item.location.container == 24
    assert item.location_offset == offset
    assert item.raw == blob


def test_an_affix_says_where_the_item_s_own_name_goes():
    """``[ITEM]`` is the hole the base name drops into, and it moves.

    An affix is free to write the item's name into the middle of itself, and
    the archive's 205 ``[ITEM]`` affixes are about half and half: 95 begin
    with the tag and the rest end with it.  Reading it as anything but a slot
    puts the tag on screen -- ``'[ITEM] of Invigoration Pioneer Belt'`` -- and
    that is the item's title, on every card and in every list.
    """
    blob, _ = synthetic_item(name="Pioneer Belt", prefix="[ITEM] of Invigoration")
    assert parse_item(blob).display_name == "Pioneer Belt of Invigoration"

    blob, _ = synthetic_item(name="War Mallet", prefix="Demolishing [ITEM]")
    assert parse_item(blob).display_name == "Demolishing War Mallet"

    # An affix with no tag leaves the base name where it has always been:
    # between the two, in the order prefix, name, suffix.
    blob, _ = synthetic_item(name="Test Blade", prefix="Keen", suffix="of Flame")
    assert parse_item(blob).display_name == "Keen Test Blade of Flame"


def test_extra_records_shift_the_layout():
    """A non-zero extra-record count must consume exactly 8 bytes per record.

    This is the layout FNIStash cannot read: it skips the count field without
    consuming the records, so every later field is read 8 bytes early.
    """
    records = bytes.fromhex("5dc6720900000000")
    plain_blob, _ = synthetic_item(name="Elixir", slot=4322, container=25)
    variant_blob, _ = synthetic_item(
        name="Elixir", slot=4322, container=25, extra_records=records
    )
    assert len(variant_blob) == len(plain_blob) + 8

    variant = parse_item(variant_blob)
    assert variant.extra_records == records
    # Every field lands where it does in the zero-record form.
    plain = parse_item(plain_blob)
    assert variant.base_name == plain.base_name
    assert variant.location == plain.location
    assert variant.level == plain.level


def test_extra_record_count_is_bounded():
    """An absurd count is a desync, not a licence to skip into the next item."""
    blob, offset = synthetic_item()
    # Walking backwards from the location field: u32 enchant count, 29 opaque
    # bytes, the records themselves, then the u32 count field.
    count_at = offset - 4 - 29 - 0 - 4
    patched = bytearray(blob)
    patched[count_at : count_at + 4] = (10_000).to_bytes(4, "little")
    with pytest.raises(ParseError, match="implausible extra-record count"):
        parse_item(bytes(patched))


def test_truncated_item_raises():
    blob, _ = synthetic_item()
    with pytest.raises(ParseError):
        parse_item(blob[:40])


# --------------------------------------------------------------------------
# The tail, which has to be worked out from the bytes
# --------------------------------------------------------------------------


def test_a_plain_tail_reads_to_the_end_of_the_item():
    blob, _ = synthetic_item(tail=synthetic_tail(records=3, stats=(0xAB,)))
    item = parse_item(blob)

    assert len(item.added_damages) == 3
    assert [stat.guid for stat in item.stats] == [0xAB]


def test_a_trailer_after_the_records_is_read_as_a_trailer():
    """The shape the player's own stored spells and tomes have.

    Read as records alone, the parse stops four bytes short and takes the
    trailer for the first list's count -- so the stat list is read from the
    wrong place.  That parses; it is simply wrong, which is the failure this
    scoring exists to catch.
    """
    tail = synthetic_tail(records=2, trailer=b"\x00" * 4, stats=(0xCD,))
    item = parse_item(synthetic_item(tail=tail)[0])

    assert len(item.added_damages) == 2
    assert [stat.guid for stat in item.stats] == [0xCD]


def test_a_trailer_with_no_records_is_read_the_same_way():
    """Which is the case a lone-stray-u32 rule used to cover badly."""
    tail = synthetic_tail(trailer=b"\x00" * 4, stats=(0xEF,))
    item = parse_item(synthetic_item(tail=tail)[0])

    assert item.added_damages == []
    assert [stat.guid for stat in item.stats] == [0xEF]


def test_the_stackable_trailer_past_the_lists_is_tolerated():
    """Four Potions of Respec in the player's registry end 16 bytes short.

    Nothing here reads those bytes, so an item that ends within the slack is
    still the item -- but the bound is tight, because nothing else in any
    measured stash ends short at all.
    """
    tail = synthetic_tail(records=1, junk=b"\x00" * 16)
    item = parse_item(synthetic_item(tail=tail)[0])

    assert len(item.added_damages) == 1


def test_a_tail_that_is_not_read_to_the_end_is_refused():
    """The safety property: a misparse must fail, not land somewhere.

    FNIStash keeps the first encoding that does not raise, so an item whose
    tail it guesses wrong is returned half-read -- right up to the point where
    something downstream acts on it.  There is no encoding that accounts for
    this blob, so the item is reported unreadable instead, and an item that
    cannot be read is one the archive will not touch.
    """
    tail = synthetic_tail(records=2, stats=(0xAB,), junk=b"\x00" * 64)
    with pytest.raises(ParseError, match="reaches the end"):
        parse_item(synthetic_item(tail=tail)[0])


def _stored_blobs() -> list[bytes]:
    """Every item blob this machine has: the demo stash and the registries.

    Read only, and by URI, so a test can never write to one of them.
    """
    root = Path(__file__).resolve().parent.parent
    blobs: list[bytes] = []
    demo = root / "var" / "demo" / "sharedstash_v2.bin"
    if demo.is_file():
        blobs.extend(entry.blob for entry in read_stash_file(demo).entries)
    for db in sorted((root / "var").glob("items*.db")):
        connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            if connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='items'"
            ).fetchone():
                blobs.extend(row[0] for row in connection.execute("SELECT raw FROM items"))
        finally:
            connection.close()
    return blobs


def test_every_stored_item_consumes_its_own_blob():
    """The measurement this scoring was built from, as a test.

    Every item in the demo stash and in the player's own registries, re-read:
    each parse must reach the end of its blob, or stop at its 16-byte
    stackable trailer.  Anything else means the tail was guessed rather than
    read -- and it is read from 72 of the player's registry rows and 154 of
    the modded ones, so a change here is felt on real items, not on a
    synthetic blob.
    """
    blobs = _stored_blobs()
    if not blobs:
        pytest.skip("nothing stored on this machine to re-read")

    leftovers: dict[int, int] = {}
    for blob in blobs:
        reader = Reader(blob)
        _read_item(reader, blob_start=0, blob_end=len(blob))
        left = len(blob) - reader.pos
        leftovers[left] = leftovers.get(left, 0) + 1

    assert set(leftovers) <= {0, 16}, leftovers
    # The only shortfall there is, is the stackable trailer: ten potions
    # across everything this machine stores, at the last count.  A regression
    # that put ordinary equipment on the slack would sail past that.
    assert leftovers.get(16, 0) <= 16, leftovers


def test_relocation_changes_only_the_location_bytes():
    blob, offset = synthetic_item(slot=10, container=24)
    item = parse_item(blob)
    moved = item.relocated(slot_index=99, container=26)

    assert len(moved) == len(blob)
    assert moved[:offset] == blob[:offset]
    assert moved[offset + 4 :] == blob[offset + 4 :]
    assert int.from_bytes(moved[offset : offset + 2], "little") == 99
    assert int.from_bytes(moved[offset + 2 : offset + 4], "little") == 26
    assert parse_item(moved).location.container == 26


def test_fingerprint_survives_a_move():
    """Identity must not depend on where the item sits.

    Placing an item into the stash is itself a move, so a location-sensitive
    fingerprint would report a brand-new item on every scan.
    """
    item = parse_item(synthetic_item(slot=10, container=24)[0])
    moved = parse_item(item.relocated(slot_index=99, container=26))
    assert item.fingerprint == moved.fingerprint


def test_fingerprint_distinguishes_different_items():
    a = parse_item(synthetic_item(name="Alpha")[0])
    b = parse_item(synthetic_item(name="Beta")[0])
    assert a.fingerprint != b.fingerprint


def test_markup_is_stripped_from_names():
    assert strip_markup("|cFFF2ACB1Spell: Heal Self IV") == "Spell: Heal Self IV"
    assert strip_markup("plain\x00") == "plain"
    item = parse_item(synthetic_item(name="|cFF00FF00Glowing Blade")[0])
    assert item.base_name == "Glowing Blade"


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def test_registry_scan_is_idempotent(tmp_path):
    blob, _ = synthetic_item()
    stash = _stash_of([blob])
    db = tmp_path / "items.db"

    with Registry(db) as reg:
        first = reg.scan(stash, source="test")
        assert len(first.added) == 1
        assert first.vanished == []

        second = reg.scan(stash, source="test")
        assert second.added == []
        assert second.vanished == []
        assert reg.item_count() == 1


def test_registry_notices_an_item_leaving_the_stash(tmp_path):
    a, _ = synthetic_item(name="Alpha")
    b, _ = synthetic_item(name="Beta")
    db = tmp_path / "items.db"

    with Registry(db) as reg:
        reg.scan(_stash_of([a, b]), source="test")
        result = reg.scan(_stash_of([a]), source="test")
        assert len(result.vanished) == 1
        # Gone from the stash, but not from the registry.
        assert reg.item_count() == 2


def test_registry_separates_sources(tmp_path):
    blob, _ = synthetic_item()
    db = tmp_path / "items.db"
    with Registry(db) as reg:
        reg.scan(_stash_of([blob]), source="vanilla")
        result = reg.scan(_stash_of([]), source="modded")
        # An empty modded stash must not mark the vanilla item as gone.
        assert result.vanished == []


class _FakeStash:
    def __init__(self, items):
        self.items = items
        self.failed = []


def _stash_of(blobs):
    return _FakeStash([parse_item(b) for b in blobs])


# --------------------------------------------------------------------------
# Real save files (skipped when absent)
# --------------------------------------------------------------------------

_REAL = [
    pytest.param(loc.path, id=f"{loc.kind}-{loc.steam_id}")
    for loc in find_save_locations()
]


@pytest.mark.skipif(not _REAL, reason="no Torchlight 2 saves on this machine")
@pytest.mark.parametrize("path", _REAL)
def test_real_stash_parses_completely(path):
    """Every partition in a real save must parse -- no silent partial reads.

    An empty stash is skipped, not failed.  It is not a broken save; it is the
    state this tool exists to produce, so asserting that a real save has items
    would make the suite fail exactly when the tool is doing its job.
    """
    stash = read_stash_file(path)
    if not stash.items:
        pytest.skip(f"{path} is empty -- everything in it has been absorbed")
    assert not stash.failed, [
        f"partition {e.index}: {e.error}" for e in stash.failed
    ]
    for item in stash.items:
        assert item.base_name, "item with no name"
        assert item.raw, "item with no raw bytes"


@pytest.mark.skipif(not _REAL, reason="no Torchlight 2 saves on this machine")
@pytest.mark.parametrize("path", _REAL)
def test_real_stash_checksum_and_round_trip(path):
    """Descrambling is correct iff the recomputed checksum matches, and
    re-scrambling reproduces the file byte for byte."""
    original = Path(path).read_bytes()
    save = read_save_file(path)
    assert save.checksum_ok, "descrambled body fails its own checksum"
    assert save.size_ok

    rebuilt = (
        save.version.to_bytes(4, "little")
        + bytes([save.dummy])
        + save.stored_checksum.to_bytes(4, "little")
        + scramble(save.body)
        + save.stored_size.to_bytes(4, "little")
    )
    assert rebuilt == original


@pytest.mark.skipif(not _REAL, reason="no Torchlight 2 saves on this machine")
@pytest.mark.parametrize("path", _REAL)
def test_real_stash_locations_are_sane(path):
    """Slot numbers must be unique and clustered per container.

    Gaps are normal -- a stash tab really does have empty slots between items,
    and one save here has an eight-slot hole in the potions tab.  What is not
    normal is slots from one container landing in different thousands blocks,
    which is what a misread location offset looks like: every slot is then
    drawn from whatever bytes happened to sit at the wrong position.
    """
    stash = read_stash_file(path)
    by_container: dict[int, list[int]] = {}
    for item in stash.items:
        by_container.setdefault(item.location.container, []).append(
            item.location.slot_index
        )
    for container, slots in by_container.items():
        assert len(set(slots)) == len(slots), f"duplicate slot in container {container}"
        blocks = {slot // 1000 for slot in slots}
        assert len(blocks) == 1, (
            f"container {container}: slots span blocks {sorted(blocks)} "
            f"({sorted(slots)})"
        )
