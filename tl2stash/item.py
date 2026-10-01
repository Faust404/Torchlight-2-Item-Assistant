"""Item blob parsing -- port of FNIStash's ``FNIStash.File.Item``.

An item is stored as one self-delimiting blob.  The blob is *not* fully
understood: a good third of it is opaque bytes whose meaning nobody has
reverse-engineered, and the tail has three different encodings that can only
be told apart by trying each in turn until one parses to the end.

Rather than pretend otherwise, every item keeps its ``raw`` blob verbatim and
records ``location_offset`` -- the byte position of the 4-byte location field
inside that blob.  That is FNIStash's "Partition" trick: an item can be
rewritten with a new container/slot and be byte-identical everywhere else,
including in the parts we cannot interpret.  Level B depends on this.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .binary import ParseError, Reader

__all__ = [
    "AddedDamage",
    "Effect",
    "Item",
    "Location",
    "Stat",
    "Triggerable",
    "parse_item",
]

#: Effect types whose serialised form carries a file path string.
EFFECT_HAS_FILE = frozenset(
    {
        0x8141, 0x8140, 0x9041, 0x8541, 0x8149, 0x8148, 0x0140, 0x2141,
        0xA541, 0x9141, 0x8150, 0x8151, 0xA141, 0x8158, 0x8159, 0x0141,
        0x814C, 0x8145,
    }
)

#: Effect types whose serialised form carries a u64 GUID.
EFFECT_HAS_GUID = frozenset({0xA141, 0xA041, 0x2141, 0x2041, 0xA541})

#: Effect type that carries two extra bytes, seen on the giant fish/shark/
#: warsnout boss items.
EFFECT_TYPE_2EXTRA = 0x9141

#: An effect of this type is followed by a throwaway u32.
EFFECT_TYPE_EAT_U32 = 0x804A

#: ``eBytesLink`` value meaning "another effect list follows".
EFFECT_LINK_CONTINUES = 0x03

#: Effects of this type are present in the file but never displayed.
EFFECT_TYPE_SKIP = 0x8002

#: Location value marking a gem sitting in a socket rather than a slot.
IN_SOCKET = 0xFFFF

#: Upper bound on the extra-record count.  No real item carries more than a
#: handful; a larger value means we are reading a field that is not this one,
#: and failing is much better than skipping megabytes into the next item.
MAX_EXTRA_RECORDS = 64

#: Torchlight embeds ``|cAARRGGBB`` colour codes directly in display strings,
#: e.g. ``|cFFF2ACB1Spell: Heal Self IV``.  They are markup, not name.
_MARKUP = re.compile(r"\|c[0-9A-Fa-f]{8}")


def strip_markup(text: str) -> str:
    """Remove colour markup and the trailing NUL from a Torchlight string."""
    return _MARKUP.sub("", text).rstrip("\x00")


@dataclass
class Location:
    """Where the item sits.  ``container``/``slot`` are raw game IDs."""

    slot_index: int
    container: int

    @property
    def in_socket(self) -> bool:
        return self.slot_index == IN_SOCKET and self.container == IN_SOCKET


@dataclass
class AddedDamage:
    from_effect: int
    from_socket: int
    from_enchant: int
    damage_type: int


@dataclass
class Effect:
    type: int
    name: str
    file: str | None
    guid: int | None
    num_values: int
    values: list[int]
    index: int
    damage_type: int
    description_type: int
    item_level: int
    duration: int
    value: int
    link: int
    extra_string: str | None


@dataclass
class Triggerable:
    name: str


@dataclass
class Stat:
    guid: int
    data: bytes


@dataclass
class Item:
    # -- provenance, needed for byte-exact rewrite -----------------------
    raw: bytes
    location_offset: int

    # -- parsed fields ---------------------------------------------------
    guid: int
    name: str
    prefix: str
    suffix: str
    random_id: bytes
    extra_records: bytes
    num_enchants: int
    location: Location
    identified: int
    level: int
    quantity: int
    num_sockets: int
    gems: list["Item"] = field(default_factory=list)
    max_damage: int = 0
    armor: int = 0
    added_damages: list[AddedDamage] = field(default_factory=list)
    effects: list[Effect] = field(default_factory=list)
    effects2: list[Effect] = field(default_factory=list)
    triggerables: list[Triggerable] = field(default_factory=list)
    stats: list[Stat] = field(default_factory=list)

    # -- derived ---------------------------------------------------------

    @property
    def display_name(self) -> str:
        """Name with affixes, as the game would title it."""
        parts = [strip_markup(p) for p in (self.prefix, self.name, self.suffix)]
        return " ".join(p for p in parts if p)

    @property
    def base_name(self) -> str:
        return strip_markup(self.name)

    @property
    def fingerprint(self) -> str:
        """Stable identity, independent of where the item currently sits.

        The blob embeds the container and slot, so hashing it whole would give
        a moved item a new identity -- and *placing* an item into the stash is
        itself a move, so that would break the core flow.  Zeroing the four
        location bytes leaves everything else, including the per-instance
        bytes that distinguish two otherwise-identical items.
        """
        off = self.location_offset
        identity = self.raw[:off] + b"\x00\x00\x00\x00" + self.raw[off + 4 :]
        return hashlib.sha1(identity).hexdigest()

    def relocated(self, slot_index: int, container: int) -> bytes:
        """Return ``raw`` with only the location field changed.

        Everything else -- including bytes we cannot interpret -- is carried
        through untouched.
        """
        off = self.location_offset
        return (
            self.raw[:off]
            + slot_index.to_bytes(2, "little")
            + container.to_bytes(2, "little")
            + self.raw[off + 4 :]
        )


# -- tail strategies -----------------------------------------------------
#
# FNIStash tries three encodings for the variable-length damage list at the
# end of an item and keeps the first that parses through to the stats list.
# The three are byte-incompatible, so a wrong guess corrupts everything after
# it -- this is the single most fragile part of the format.


def _damage_innate(reader: Reader, n_types: int) -> list[AddedDamage]:
    return [
        AddedDamage(
            from_effect=reader.u32(),
            from_socket=reader.u32(),
            from_enchant=reader.u32(),
            damage_type=reader.u32(),
        )
        for _ in range(n_types)
    ]


def _damage_nothing(reader: Reader, n_types: int) -> list[AddedDamage]:
    return [
        AddedDamage(
            from_effect=0,
            from_socket=reader.u32(),
            from_enchant=reader.u32(),
            damage_type=reader.u32(),
        )
        for _ in range(n_types)
    ]


def _damage_4bytes_zero(reader: Reader, n_types: int) -> list[AddedDamage]:
    """No damage list at all; a single stray u32 instead."""
    reader.u32()
    return []


_TAIL_STRATEGIES = (_damage_innate, _damage_nothing, _damage_4bytes_zero)


def _read_effect(reader: Reader) -> Effect:
    eff_type = reader.u16()
    extra_string_flag = reader.u16()
    name = reader.torch_text()

    file = reader.torch_text() if eff_type in EFFECT_HAS_FILE else None
    guid = reader.u64() if eff_type in EFFECT_HAS_GUID else None

    num_values = reader.u8()
    values = [reader.u32() for _ in range(num_values)]
    reader.torch_text()  # always empty in practice

    if eff_type == EFFECT_TYPE_2EXTRA:
        reader.u16()

    index = reader.u32()
    damage_type = reader.u32()
    description_type = reader.u32()
    item_level = reader.u32()
    duration = reader.u32()
    reader.u32()  # unknown
    value = reader.u32()
    link = reader.u32()

    extra_string = (
        reader.torch_text_1byte() if extra_string_flag == 0x02 else None
    )

    return Effect(
        type=eff_type,
        name=name,
        file=file,
        guid=guid,
        num_values=num_values,
        values=values,
        index=index,
        damage_type=damage_type,
        description_type=description_type,
        item_level=item_level,
        duration=duration,
        value=value,
        link=link,
        extra_string=extra_string,
    )


def _read_effect_lists(reader: Reader) -> list[Effect]:
    """Read effect lists, following the chain while the link says to.

    An empty list terminates; otherwise the last effect's ``link`` field
    decides whether another list follows.
    """
    collected: list[Effect] = []
    while True:
        effects = reader.list_of(lambda: _read_effect(reader))
        if not effects:
            return collected
        last = effects[-1]
        if last.type == EFFECT_TYPE_EAT_U32:
            reader.u32()
        collected.extend(e for e in effects if e.type != EFFECT_TYPE_SKIP)
        if last.link != EFFECT_LINK_CONTINUES:
            return collected


def _read_stat(reader: Reader) -> Stat:
    return Stat(guid=reader.u64(), data=reader.take(4))


def _read_item(reader: Reader, blob_start: int, blob_end: int) -> Item:
    """Read one item, recursing into socketed gems.

    ``blob_start``/``blob_end`` bound the *top level* blob so the raw bytes
    can be reconstructed whole.  Gems are nested inline, so their extent is
    wherever their own parse finishes.
    """
    start = reader.pos

    reader.u8()                    # lead byte, always 0x00 as far as anyone knows
    guid = reader.u64()
    name = reader.torch_text()
    prefix = reader.torch_text()
    suffix = reader.torch_text()
    random_id = reader.take(24)

    # A count of fixed 8-byte records that follow.  FNIStash calls this field
    # "added for the new stash format" and skips straight past it, which is
    # correct only while the count is zero -- true of every vanilla item, but
    # not of stackable items in the potion and spell tabs, which carry one
    # record and which FNIStash therefore cannot read at all.  Skipping
    # ``8 * count`` bytes reduces to FNIStash's behaviour when count is 0.
    extra_count = reader.u32()
    if extra_count > MAX_EXTRA_RECORDS:
        raise ParseError(
            f"implausible extra-record count {extra_count} at offset "
            f"{reader.pos - 4}"
        )
    extra_records = reader.take(8 * extra_count)

    reader.take(29)                # almost entirely 0xFF
    num_enchants = reader.u32()

    location_offset = reader.pos
    slot_index = reader.u16()
    container = reader.u16()

    reader.take(6)                 # 00 01 01 01 01 00
    identified = reader.u8()
    reader.take(8)                 # varies between otherwise-equal items
    for _ in range(4):
        reader.take(20)            # varies between otherwise-equal items

    level = reader.u32()
    quantity = reader.u32()
    num_sockets = reader.u32()

    gems = [_read_item(reader, reader.pos, blob_end) for _ in range(reader.count())]

    reader.take(4)                 # always zero
    max_damage = reader.u32()
    armor = reader.u32()
    reader.take(4)                 # differs between otherwise-equal items
    reader.take(12)                # 12 x 0xFF
    num_damage_types = reader.u16()

    tail_start = reader.pos
    last_error: ParseError | None = None
    for strategy in _TAIL_STRATEGIES:
        reader.pos = tail_start
        try:
            added = strategy(reader, num_damage_types)
            effects = _read_effect_lists(reader)
            effects2 = _read_effect_lists(reader)
            triggerables = reader.list_of(lambda: Triggerable(reader.torch_text()))
            stats = reader.list_of(lambda: _read_stat(reader))
        except ParseError as exc:
            last_error = exc
            continue

        is_top_level = start == blob_start
        raw = (
            reader.data[blob_start:blob_end] if is_top_level
            else reader.data[start : reader.pos]
        )
        rel_offset = location_offset - (blob_start if is_top_level else start)
        if not is_top_level:
            # A gem's location field is still absolute within the buffer.
            rel_offset = location_offset - start

        return Item(
            raw=raw,
            location_offset=rel_offset,
            guid=guid,
            name=name,
            prefix=prefix,
            suffix=suffix,
            random_id=random_id,
            extra_records=extra_records,
            num_enchants=num_enchants,
            location=Location(slot_index=slot_index, container=container),
            identified=identified,
            level=level,
            quantity=quantity,
            num_sockets=num_sockets,
            gems=gems,
            max_damage=max_damage,
            armor=armor,
            added_damages=added,
            effects=effects,
            effects2=effects2,
            triggerables=triggerables,
            stats=stats,
        )

    raise ParseError(
        f"no tail encoding parsed for item {name!r} at offset {start}: {last_error}"
    )


def parse_item(blob: bytes) -> Item:
    """Parse one item blob (the payload of a stash partition, sans length)."""
    reader = Reader(blob)
    return _read_item(reader, blob_start=0, blob_end=len(blob))
