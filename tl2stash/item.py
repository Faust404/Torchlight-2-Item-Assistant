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
#:
#: ``|u`` is the second half of the pair and the only other code the game
#: uses: it ends the coloured run.  Both are dropped rather than replaced, so
#: ``|c00ff9933Charge|u rate`` reads ``Charge rate`` -- they sit either side of
#: a word, with the spaces outside them, and taking them out leaves the
#: sentence intact.
_MARKUP = re.compile(r"\|c[0-9A-Fa-f]{8}|\|u")

#: The hole an affix leaves for the item's own name.  Not markup and not
#: colour -- it is a slot, and what fills it is ``Item.name``.
_ITEM_TAG = "[ITEM]"


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
        """Name with affixes, as the game would title it.

        An affix is free to say where the item's own name goes inside it, and
        most of them do: ``'of Invigoration'`` is stored as ``'[ITEM] of
        Invigoration'`` and ``[ITEM]`` is the hole the base name drops into.
        The string itself says where -- 95 of the archive's 205 ``[ITEM]``
        affixes put the tag at the front and the rest at the end, so
        ``'Swift [ITEM]'`` reads ``'Swift Pioneer Belt'`` and ``'[ITEM] of
        Invigoration'`` reads ``'Pioneer Belt of Invigoration'`` -- which is
        why the base name is appended only when no affix has already placed
        it.
        """
        base = strip_markup(self.name)
        prefix = strip_markup(self.prefix).replace(_ITEM_TAG, base)
        suffix = strip_markup(self.suffix).replace(_ITEM_TAG, base)
        placed = _ITEM_TAG in self.prefix or _ITEM_TAG in self.suffix
        parts = (prefix, "" if placed else base, suffix)
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


# -- the tail ------------------------------------------------------------
#
# Which of these encodings an item's damage list uses is not stated anywhere in
# the file, so it has to be worked out from the bytes -- and the candidates are
# byte-incompatible, so a wrong guess corrupts everything after it.  This is
# the single most fragile part of the format.
#
# FNIStash tries its candidates in order and keeps the first that does not
# raise.  That is a guess that can *land* -- a misparse that happens to parse
# is exactly the case that has no error to report -- and it is how a socketed
# item whose tail this code got wrong became an item the tool could not take.
#
# An item in the stash is length-prefixed, so its blob is exactly its own
# bytes: the encoding that reads to the end of the blob is the one that was
# written.  So the candidates are scored by how much of the blob they consume
# rather than by whether they survived, and one that stops short of the end by
# more than the stackable trailer's length is not a reading of this item.
#
# The measurements behind the two candidates (every item in the demo stash and
# every item in the player's vanilla registry, re-read under each):
#
#   * 12-byte records alone read **exactly** to the end of every piece of
#     equipment -- 25 of 25 and 55 of 55 -- and of four Potions of Respec,
#     which end 16 bytes short.
#   * 12-byte records plus one u32 read exactly to the end of every spell and
#     tome -- 13 of the player's own 72 items, 18% of the collection.
#   * A 16-byte record reads nothing those two do not: at zero damage types it
#     consumes the same bytes as the 12-byte one, and above zero it fails on
#     everything.
#   * A lone u32 with no records at all is the second candidate at zero
#     damage types.

#: How far short of the end a candidate may stop and still be believed.  The
#: only shortfall in the measured data is the stackable trailer: four potions
#: end exactly 16 bytes short.  Nothing else is near it, so the bound can be
#: this tight.
TAIL_SLACK = 16


def _damage_records(reader: Reader, n_types: int) -> list[AddedDamage]:
    """The measured layout: ``n_types`` records of three u32s each.

    FNIStash reads a fourth word per record and is wrong about it; the record
    is three words long, and this is what fits the file.
    """
    return [
        AddedDamage(
            from_effect=0,
            from_socket=reader.u32(),
            from_enchant=reader.u32(),
            damage_type=reader.u32(),
        )
        for _ in range(n_types)
    ]


def _records_then_u32(reader: Reader, n_types: int) -> list[AddedDamage]:
    """The same records, then one further u32 -- the stackable trailer.

    Measured on spells, tomes and potions: they carry one trailing word after
    the damage records, present even when there are no records at all.
    """
    added = _damage_records(reader, n_types)
    reader.u32()
    return added


#: The candidates, in the order they win a tie -- which is the order a blob
#: that both of them read is read in.
_TAIL_STRATEGIES = (
    ("12-byte records", _damage_records),
    ("12-byte records + one u32", _records_then_u32),
)


def _read_tail(reader: Reader, n_types: int, strategy) -> tuple:
    """Read a whole tail with one candidate: damages, then the four lists."""
    added = strategy(reader, n_types)
    effects = _read_effect_lists(reader)
    effects2 = _read_effect_lists(reader)
    triggerables = reader.list_of(lambda: Triggerable(reader.torch_text()))
    stats = reader.list_of(lambda: _read_stat(reader))
    return added, effects, effects2, triggerables, stats


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


def _read_item(
    reader: Reader, blob_start: int, blob_end: int, *, nested: bool = False
) -> Item:
    """Read one item, recursing into socketed gems.

    ``blob_start``/``blob_end`` bound the *top level* blob so the raw bytes
    can be reconstructed whole and so the tail can be checked against the
    item's own length.  Gems are nested inline with no length of their own,
    so ``nested`` says which of the two this is -- their extent is wherever
    their own parse finishes.
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

    gems = [
        _read_item(reader, reader.pos, blob_end, nested=True)
        for _ in range(reader.count())
    ]

    reader.take(4)                 # always zero
    max_damage = reader.u32()
    armor = reader.u32()
    reader.take(4)                 # differs between otherwise-equal items
    reader.take(12)                # 12 x 0xFF
    num_damage_types = reader.u16()

    tail_start = reader.pos
    if nested:
        # A gem is the one case this cannot score: it is written inline with no
        # length of its own, so there is no end for a candidate to reach --
        # only the parent's structure after it says where it stopped.  The
        # first candidate that parses is therefore kept, and the parent is what
        # validates it: a gem read wrong ends in the wrong place, and the
        # parent's own tail then cannot consume the parent's blob, so the item
        # is reported unreadable instead of misread.
        last_error: ParseError | None = None
        for _, strategy in _TAIL_STRATEGIES:
            reader.pos = tail_start
            try:
                tail = _read_tail(reader, num_damage_types, strategy)
            except ParseError as exc:
                last_error = exc
                continue
            break
        else:
            raise ParseError(
                f"no tail encoding parsed for the gem in {name!r} at offset "
                f"{start}: {last_error}"
            )
    else:
        # Each candidate is read to its own end, so where the reader stands
        # afterwards belongs to whichever one ran last -- the winner's end is
        # remembered and restored before anything else is read.
        attempts: list[tuple[int, int, tuple]] = []
        problems: list[str] = []
        for label, strategy in _TAIL_STRATEGIES:
            reader.pos = tail_start
            try:
                tail = _read_tail(reader, num_damage_types, strategy)
            except ParseError as exc:
                problems.append(f"{label}: {exc}")
                continue
            attempts.append((blob_end - reader.pos, reader.pos, tail))

        best = min(attempts, key=lambda attempt: attempt[0], default=None)
        if best is None or best[0] > TAIL_SLACK:
            detail = ", ".join(
                [f"{left} bytes unread" for left, _, _ in attempts] + problems
            )
            raise ParseError(
                f"no tail encoding reaches the end of item {name!r} at offset "
                f"{start}: {detail or 'nothing parsed'}"
            )
        reader.pos = best[1]
        tail = best[2]

    added, effects, effects2, triggerables, stats = tail

    # A gem's raw bytes are its own, ending where its parse stopped; a
    # top-level item's are the whole blob, which is what the container
    # length-prefixed.  Both carry their location field absolutely within the
    # buffer, so the offset is measured from wherever they start.
    raw = (
        reader.data[blob_start:blob_end] if not nested
        else reader.data[start : reader.pos]
    )
    rel_offset = location_offset - (blob_start if not nested else start)

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


def parse_item(blob: bytes) -> Item:
    """Parse one item blob (the payload of a stash partition, sans length)."""
    reader = Reader(blob)
    return _read_item(reader, blob_start=0, blob_end=len(blob))
