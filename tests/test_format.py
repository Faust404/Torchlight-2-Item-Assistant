"""Tests for the save-format layer.

Most of these run against a synthetic item blob built field by field, so they
hold on any machine.  The tests that need real save files skip when the files
are absent -- the saves are the player's data, not fixtures to check in.
"""

from __future__ import annotations

import sqlite3
import struct
import sys
from dataclasses import replace
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
from tl2stash.item import (  # noqa: E402
    _read_item,
    as_float,
    is_enchant,
    strip_markup,
)
from tl2stash.registry import Registry  # noqa: E402
from tl2stash.saves import find_save_locations  # noqa: E402

# --------------------------------------------------------------------------
# Synthetic blob construction
# --------------------------------------------------------------------------


def synthetic_tail(
    *,
    records: int = 0,
    trailer: bytes = b"",
    effects: tuple[bytes, ...] = (),
    stats: tuple[int, ...] = (),
    junk: bytes = b"",
) -> bytes:
    """Build an item's tail: the part whose shape has to be worked out.

    ``records`` added-damage records of three u32s each, then an optional
    ``trailer`` word, then the four lists -- the first holding ``effects``
    (see ``synthetic_effect``), all empty but for ``stats`` -- and ``junk``
    past the end, which nothing should read.  A list's count is derived from
    what is put in it, as with the extra records above.
    """
    out = bytearray()
    out.extend(records.to_bytes(2, "little"))
    out.extend(b"\x00" * (12 * records))
    out.extend(trailer)
    out.extend(len(effects).to_bytes(4, "little"))
    for effect in effects:
        out.extend(effect)
    for _ in range(2):  # effects2, triggerables
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
    guid: int = 0x1122334455667788,
    slot: int = 10,
    container: int = 24,
    level: int = 5,
    quantity: int = 1,
    sockets: int = 0,
    extra_records: bytes = b"",
    tail: bytes | None = None,
) -> tuple[bytes, int]:
    """Build an item blob that parses, and its location offset.

    ``extra_records`` is spliced in *after* the count field, so the count is
    derived from it rather than passed separately -- which is the property
    under test.  ``tail`` replaces the whole variable-length tail; the default
    is the plainest one there is -- no damage types and four empty lists.
    ``sockets`` is the count the item says it has, which is a field of its own
    and not the list of gems in them: a socketed item with nothing socketed in
    it is the ordinary case.

    ``quantity`` is how many of the item the stack holds, the field right
    before the socket count; one is what everything that does not stack
    carries, which is why it is the default here.

    ``guid`` is the item's own id, and it is the one field here that is not
    about the item's *shape*: the game's data files are indexed by it, so a
    test that wants an item the game knows passes the guid of a file it built
    (see ``tests/test_gamedata.install``).  The default is a number no game
    file has, which is an item the tool can parse and the files cannot
    describe -- the ordinary case on a machine with no game installed.
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
    u64(guid)
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
    u32(quantity)
    u32(sockets)
    u32(0)                                     # gems
    out.extend(bytes(4))
    u32(0)                                     # max damage
    u32(0)                                     # armor
    out.extend(bytes(4))
    out.extend(b"\xff" * 12)
    out.extend(synthetic_tail() if tail is None else tail)
    return bytes(out), location_offset


def synthetic_effect(
    *,
    kind: int = 0x8041,
    name: str = "",
    file: str | None = None,
    guid: int | None = None,
    extra: int | None = None,
    values: tuple[float, ...] = (),
    index: int = 0,
    damage_type: int = 0,
    description_type: int = 0,
    item_level: int = 0,
    duration: float = 0.0,
    value: float = 0.0,
    link: int = 0,
) -> bytes:
    """Build one effect record, written the way the game writes it.

    Mirrors ``tl2stash.item._read_effect`` field for field, and like it needs
    to be told nothing about the type: ``file``, ``guid`` and ``extra`` are
    written only when given, because which effect types carry them is the
    data's business.  ``values`` is a tuple of the floats the fields really
    are -- the packing is here so no caller has to do it -- and the count is
    derived from it rather than passed, so the two cannot disagree.
    """
    out = bytearray()

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

    def f32(v):
        out.extend(struct.pack("<f", v))

    u16(kind)
    u16(0)                                     # extra-string flag
    text(name)
    if file is not None:
        text(file)
    if guid is not None:
        u64(guid)
    if extra is not None:
        u16(extra)
    u8(len(values))
    for v in values:
        f32(v)
    text("")                                   # always empty in practice
    u32(index)
    u32(damage_type)
    u32(description_type)
    u32(item_level)
    f32(duration)
    u32(0)                                     # unknown
    f32(value)
    u32(link)
    return bytes(out)


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


def test_a_stack_says_how_many_of_it_there_are():
    """The quantity is the save file's own field, between the level and the
    socket count.

    It is the number a fish or a potion is carried in, and 1 for everything
    that does not stack.  One field out -- reading the sockets' word as the
    stack's -- turns twenty potions into one with twenty holes in it, so the
    two numbers are asserted apart on the one blob.
    """
    item = parse_item(synthetic_item(name="Neverending Fish", quantity=20)[0])
    assert item.quantity == 20
    assert item.num_sockets == 0

    assert parse_item(synthetic_item(name="Test Blade")[0]).quantity == 1


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


# --------------------------------------------------------------------------
# Effects
# --------------------------------------------------------------------------


def test_the_two_extra_bytes_are_read_before_the_value_list():
    """The record that made Tasty Fish Meat unreadable, rebuilt from its bytes.

    ``0x9141`` is the one effect type carrying two unexplained bytes, and the
    only question about them is which side of the value list they sit on.  The
    game's own record answers it: after the file path come ``00 00``, then the
    value count ``02``, then two copies of 9374.0 -- the health a Tasty Fish
    Meat recharges, exactly as the game's item file states it.  Read the pair
    on the other side of the list, as FNIStash does, and the first of those
    zeroes is taken for the count while the real count becomes the length of a
    512-character string, which runs off the end of the item.  Both readings
    parse an effect whose extra pair is zero *and* whose value count is zero,
    which is every giant fish FNIStash was tested on.
    """
    effect = synthetic_effect(
        kind=0x9141,
        name="FISHHPRECHARGE",
        file="MEDIA/PARTICLES/EVENTS/HEALTHPOTION.LAYOUT",
        extra=0,
        values=(9374.0, 9374.0),
        index=124,
        description_type=1,
        duration=2.0,
        value=18748.0,
    )
    # The tail of the real record, transcribed from the item's own bytes and
    # grouped by field: the extra pair, the count, the two values, the empty
    # text, then index, damage type, description type, item level, duration,
    # the unknown word, the value and the link.  This is what keeps the test
    # honest -- a builder that drifted along with a reverted parser would
    # still fail here.
    assert effect[-45:] == bytes.fromhex(
        "0000" "02" "00781246" "00781246" "0000"
        "7c000000" "00000000" "01000000" "00000000"
        "00000040" "00000000" "00789246" "00000000"
    )

    blob, _ = synthetic_item(
        name="Tasty Fish Meat", tail=synthetic_tail(effects=(effect,))
    )
    [parsed] = parse_item(blob).effects

    assert parsed.name == "FISHHPRECHARGE"
    assert parsed.num_values == 2
    assert [as_float(v) for v in parsed.values] == [9374.0, 9374.0]
    assert parsed.index == 124
    assert parsed.description_type == 1
    assert as_float(parsed.duration) == 2.0
    assert as_float(parsed.value) == 18748.0


def test_which_records_an_enchanter_wrote_is_read_off_the_type():
    """The rule, on the type values: ``0x84__`` and ``0x85__``, an enchanter's.

    The save file marks no record as an enchantment and says only how many an
    item has, so the count is the ground the rule was measured on -- the test
    below re-runs that measurement on everything this machine stores.  The
    record's *shape* is a real one, parsed out of a blob, and only its type is
    varied here: ``0x8541`` is also a type that carries a file path, which is
    why the low byte cannot be read as part of the question, and ``0x8002`` is
    a type the file holds and the card never draws.
    """
    blob, _ = synthetic_item(
        tail=synthetic_tail(effects=(synthetic_effect(kind=0x8041),))
    )
    [record] = parse_item(blob).effects

    kinds = (0x8400, 0x8441, 0x8500, 0x8541, 0x8041, 0x8141, 0xA041, 0x8058, 0x8002)
    assert [is_enchant(replace(record, type=kind)) for kind in kinds] == [
        True, True, True, True, False, False, False, False, False,
    ]


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


def _vanilla_blobs() -> list[bytes]:
    """Every item blob the vanilla save holds, the modded registries left out.

    The mask is the game's, so the measurement is taken on the game's own
    files: a mod is the one place a record could carry one of its two patterns
    with no enchanter behind it.  Read only, and by URI, so a test can never
    write to one of them.
    """
    root = Path(__file__).resolve().parent.parent
    blobs: list[bytes] = []
    demo = root / "var" / "demo" / "sharedstash_v2.bin"
    if demo.is_file():
        blobs.extend(entry.blob for entry in read_stash_file(demo).entries)
    for db in sorted((root / "var").glob("items*.db")):
        if "-modded-" in db.name:
            continue
        connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            if connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='items'"
            ).fetchone():
                blobs.extend(row[0] for row in connection.execute("SELECT raw FROM items"))
        finally:
            connection.close()
    return blobs


def test_every_stored_enchantment_is_one_the_mask_finds():
    """The measurement the rule was built from, as a test.

    ``num_enchants`` says how many enchantments an item has and never says
    which records they are, so the count is the only ground there is: on every
    item this machine stores, the effects the mask catches plus the damage
    records carrying ``from_enchant`` add up to it.  Zero mismatches is what
    makes the rule a reading of the format rather than a guess -- FNIStash's
    ``isEnchant`` is a weaker one, and it is precedent here, not the rule.
    """
    blobs = _vanilla_blobs()
    if not blobs:
        pytest.skip("nothing stored on this machine to re-read")

    enchanted = 0
    for blob in blobs:
        try:
            item = parse_item(blob)
        except Exception:  # noqa: BLE001 -- an unreadable blob is not this test's business
            continue
        found = sum(is_enchant(effect) for effect in item.effects + item.effects2)
        found += sum(1 for added in item.added_damages if added.from_enchant)
        assert found == item.num_enchants, (item.name, found, item.num_enchants)
        enchanted += bool(item.num_enchants)

    if not enchanted:
        pytest.skip("no enchanted item is stored on this machine")


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


def test_requantifying_changes_only_the_count_bytes():
    """Re-counting a stack, which is the one edit a pile ever needs.

    The count is a field of the record like any other, at a fixed offset past
    the location -- the same arithmetic the parse already relies on -- so the
    edit is four bytes in place and nothing else moves: not the location, not
    the sockets, not the effects.
    """
    blob, offset = synthetic_item(quantity=20, sockets=2)
    item = parse_item(blob)
    fewer = item.requantified(5)

    count = item.quantity_offset
    assert count == offset + 103, "the count moved relative to the location"
    assert len(fewer) == len(blob)
    assert fewer[:count] == blob[:count]
    assert fewer[count + 4 :] == blob[count + 4 :]

    reread = parse_item(fewer)
    assert reread.quantity == 5
    assert reread.name == item.name
    assert reread.location.slot_index == item.location.slot_index
    assert reread.num_sockets == item.num_sockets


def test_the_count_is_inside_the_fingerprint():
    """Which is what makes a split a re-key and not an edit.

    Identity is the bytes with only the *location* zeroed, so two counts of
    one pile are two items to the registry and one pile to the player.  Every
    caller that splits a stack therefore has to re-key the row -- see
    :meth:`tl2stash.registry.Registry.recount`.
    """
    item = parse_item(synthetic_item(quantity=20)[0])
    assert item.fingerprint != parse_item(item.requantified(5)).fingerprint
    assert item.fingerprint == parse_item(item.requantified(20)).fingerprint


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
