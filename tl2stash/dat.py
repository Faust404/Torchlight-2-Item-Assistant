"""Reading the game's DAT files: what an item *is*, as opposed to what it says.

The stash file holds an item's numbers and the names of its effects.  It does
not hold the words those effects are written in -- ``OFTHEMAGE PERCENT CAST
SPEED`` is a key, and the sentence the player reads lives in the game's data
files.  Those are DAT files, and this reads them.

A DAT file is a dictionary of strings plus a tree of nodes::

    u32 version
    u32 dictionary size, then that many (u32 id, torchText) pairs
    node

    node:
        u32 node id
        u32 variable count, then that many (u32 id, u32 type, value)
        u32 child count, then that many nodes

Text variables hold an index into the dictionary rather than the string, so
the dictionary is read first and the strings are resolved as the tree is
built -- nothing downstream has to carry the dictionary around to make sense
of a value.

Variable ids are opaque 32-bit constants -- they are *not* the names written
out.  The same id means the same thing in every file: ``0x00660DE5`` holds
``'Djinn Fire Sword'`` on an item, ``'MELEEDAMAGEBONUS'`` on an effect and
``'ARMOR'`` on an inventory slot.  The constants in this module were read off
the files themselves and are each pinned by a test against the real archive;
the meaning of each is stated where it is defined.

Format derived by reading the files directly and cross-checked against the
public DAT2TXT notes.  Not transcribed from another implementation.
"""

from __future__ import annotations

import struct
from typing import Iterator

from .binary import ParseError, Reader

__all__ = [
    "VAR_AFFIX",
    "VAR_AFFIX_EFFECT",
    "VAR_ARMOR_ELECTRIC",
    "VAR_ARMOR_FIRE",
    "VAR_ARMOR_ICE",
    "VAR_ARMOR_MIN_WEIGHT",
    "VAR_ARMOR_MULT",
    "VAR_ARMOR_PHYSICAL",
    "VAR_ARMOR_POISON",
    "VAR_ARMOR_WEIGHT",
    "VAR_AFFIX_LEVEL",
    "VAR_BADDES",
    "VAR_BADDESOT",
    "VAR_BASEFILE",
    "VAR_COUNT",
    "VAR_DAMAGE_ELECTRIC",
    "VAR_DAMAGE_FIRE",
    "VAR_DAMAGE_ICE",
    "VAR_DAMAGE_PHYSICAL",
    "VAR_DAMAGE_POISON",
    "VAR_DAMAGE_TYPE",
    "VAR_DISPLAYPRECISION",
    "VAR_DISPLAY_NAME",
    "VAR_DURATION",
    "VAR_EFFECT_GRAPH",
    "VAR_EFFECT_TYPE",
    "VAR_FLAVOR",
    "VAR_GOODDES",
    "VAR_GOODDESOT",
    "VAR_ICON",
    "VAR_LEVEL",
    "VAR_MAXDAMAGE",
    "VAR_MINDAMAGE",
    "VAR_NAME",
    "VAR_RARITY_DMG_MOD",
    "VAR_SET",
    "VAR_SLOT_BASE",
    "VAR_SPEED_DMG_MOD",
    "VAR_UNIDENTIFIED_NAME",
    "VAR_UNITTYPE",
    "VAR_UNIT_GUID",
    "DatFile",
    "DatNode",
    "field_hash",
]

#: How deep a tree may nest before the file is called corrupt.  Real files
#: nest a handful of levels; this exists so a garbled file raises ParseError
#: rather than blowing the interpreter's stack, which is a different kind of
#: failure and a much worse one to debug.
MAX_DEPTH = 64

# Variable types, as stored.
_TYPE_INT = 1
_TYPE_FLOAT = 2
_TYPE_DOUBLE = 3
_TYPE_WORD = 4
_TYPE_TEXT = 5
_TYPE_BOOL = 6
_TYPE_INT64 = 7
_TYPE_TRANSLATE = 8

#: The types whose value is an index into the dictionary.
_TEXT_TYPES = (_TYPE_TEXT, _TYPE_TRANSLATE)

def field_hash(name: str) -> int:
    """The id a DAT variable is filed under, from its name.

    A variable's id is not an arbitrary constant: it is Knuth's DEK hash of
    the field's own name, upper-cased --

        h = len(name)
        for c in name: h = ((h << 5) ^ (h >> 27) ^ c) & 0xFFFFFFFF

    which means the ids in the files can be *checked* rather than merely
    collected.  Twelve of the constants below were originally read off the
    files without knowing this, and all twelve reproduce exactly, which is
    what makes this more than a plausible-looking guess.  It also means a
    field nobody has catalogued yet can be looked up by name instead of
    guessed at.

    Four of the constants below are named for what the field *means* rather
    than what it is called, so they hash under the game's spelling and not
    under their own: ``VAR_FLAVOR`` is the field ``DESCRIPTION``,
    ``VAR_EFFECT_TYPE`` is the field ``EFFECT``.  Four more -- ``VAR_SLOT_BASE``
    and the three unnamed armour fields -- have no name yet, and no name tried
    has produced them.
    """
    data = name.encode("ascii")
    value = len(data)
    for byte in data:
        value = ((value << 5) ^ (value >> 27) ^ byte) & 0xFFFFFFFF
    return value


# -- the variables this tool reads -------------------------------------------
#
# Each of these was found by dumping the files that carry it and reading what
# came back, then confirmed against a second, unrelated file: the name
# variable alone turns up on items, affixes, skills, sets, inventory slots and
# effects, holding the right string every time.  Where a name is known it is
# now written as :func:`field_hash` of that name, so the claim is checkable
# rather than a number to be taken on trust.

#: What the thing is called.  Present on every named node in the archive.
VAR_NAME = field_hash("NAME")

#: The file this one inherits from -- a magic sword says it is based on
#: ``media/units/items/swords/base_sword.dat`` and need only give the
#: differences.
VAR_BASEFILE = field_hash("BASEFILE")

#: The name shown before the item is identified.
VAR_UNIDENTIFIED_NAME = field_hash("UNIDENTIFIED_NAME")

#: The icon's name, as a stem under ``MEDIA/UI/ICONS``.
VAR_ICON = field_hash("ICON")

#: What an item *is*, in one string: the tier and the kind together, as
#: ``'UNIQUE 1HSWORD'`` or ``'MAGIC BOOTS'``.  Most items inherit it rather
#: than state it -- ``BERSERKER_01_BOOTS.DAT`` carries none of its own and
#: takes ``'UNIQUE BOOTS'`` from three files up.
#:
#: The first word is a tier only when it is one of the six the archive
#: actually uses -- MAGIC, UNIQUE, NORMAL, QUESTITEM, LEGENDARY, LEVEL -- so
#: ``'SWORD'`` and ``'POTION'`` are types with no tier in front of them.  The
#: archive has no ``RARE``: the blue tier is the game's ``MAGIC``.
VAR_UNITTYPE = field_hash("UNITTYPE")

#: The set an item belongs to, as ``'U_TRUE_NORTH'`` -- the *internal* name,
#: which is what ``MEDIA/SETS/U_TRUE_NORTH.DAT`` is filed under and what its
#: ``DISPLAYNAME`` turns into ``'True North'`` for the player.
VAR_SET = field_hash("SET")

#: ``KEFFECT_TYPE_MELEEDAMAGEBONUS`` and friends: an effect node's own type,
#: spelled out.  Equal to the node's id, which is what makes an effect's
#: position in EFFECTSLIST.DAT meaningful.
#:
#: The game's own name for the field is ``EFFECT``, which is what the hash is
#: taken over; the constant is named for what it *means* instead.
VAR_EFFECT_TYPE = field_hash("EFFECT")

# The four description templates an effect can carry.  Which one the game
# uses is decided by the ``description_type`` on the effect record inside the
# item -- the data file only supplies the words.  Not every effect has all
# four: 208 of the 239 carry GOODDES, 198 carry BADDESOT.
VAR_GOODDES = field_hash("GOODDES")  # '+[VALUE] Melee weapon damage bonus'
VAR_GOODDESOT = field_hash("GOODDESOT")  # the same, for [DURATION] seconds
VAR_BADDES = field_hash("BADDES")  # '-[VALUE] Melee weapon damage penalty'
VAR_BADDESOT = field_hash("BADDESOT")

#: How many decimal places to show an effect's value to.  1 on fourteen of the
#: effects, 2 on three, 0 on the rest.
VAR_DISPLAYPRECISION = field_hash("DISPLAYPRECISION")

#: The block an inventory container numbers its slots from.  ``BAG_ARMS_SLOT``
#: declares 3322, and the save file's container 24 holds items in slots 3322
#: upwards; the two were matched on exactly that.
VAR_SLOT_BASE = 0x173B97DF

#: The name of the *effect* an affix grants.  The game's own name for this
#: field is ``TYPE``.
#:
#: An item's effect record names an affix, not an effect -- ``OFTHEELEPHANT MAX
#: HP`` is the affix, and it is not unique: 107 different affixes are called
#: ``OFFLAME DAMAGE BONUS``, granting everything from fire damage to dodge
#: chance.  Each of them carries an effect node, and *that* node's VAR_AFFIX_
#: EFFECT is the effect proper (``MAX HP``, ``DAMAGE BONUS``) -- a name that is
#: unique and that EFFECTSLIST holds description wording for.
VAR_AFFIX_EFFECT = field_hash("TYPE")

#: The set ladder: a set's own file is a root with one child per rung, each
#: carrying how many of the set's pieces it takes and the name of the affix it
#: grants.  A rung names an affix *file* rather than stating its bonus, so
#: reading a ladder is two lookups -- the rung, and then the affix it names.
#:
#: ``VAR_AFFIX`` is both the child's node id and the field the name is under,
#: which is one field in two places rather than two that must agree.
VAR_COUNT = field_hash("COUNT")
VAR_AFFIX = field_hash("AFFIX")

#: The level a set rung's bonus is granted at -- which is also the level its
#: numbers are *scaled to*.  A rung states its numbers as a nominal and names
#: a by-level graph beside them, and the two are combined at this level.  It
#: is a field of the rung rather than of the item: two pieces of a set can sit
#: at different levels and the same rung still grants the same number.
VAR_AFFIX_LEVEL = field_hash("AFFIXLEVEL")

#: The by-level graph an effect's numbers scale with, as a bare stem under
#: ``MEDIA/GRAPHS/STATS`` -- ``'STEAL_HEALTH_AND_MANA'`` for LIFE STEAL, and
#: ``'MANA_PLAYER_GENERIC'`` for DRAW MANA.  36 of the 239 effects name one;
#: the rest state numbers that need no curve.
#:
#: Filed under two ids, ``0x0B01C930`` and ``0x0B01C933``, which always hold
#: the same string -- measured over all 239 effects, no disagreement.  Both
#: were read off the files; neither is a hashed name, and no candidate name
#: tried has produced them.
VAR_EFFECT_GRAPH = 0x0B01C930

#: What a *data file's* effect node states its numbers in.  The save file's
#: effect record has a value list instead, and the two are the same numbers:
#: the ends of a range the game rolls between are ``MIN`` and ``MAX``, and the
#: roll is what lands in a record's value list.
VAR_DURATION = field_hash("DURATION")
VAR_DAMAGE_TYPE = field_hash("DAMAGE_TYPE")

#: The name to show for a skill or a monster.  Distinct from VAR_NAME, which
#: on a skill is its internal id: a spell node called ``Fireball III`` reads
#: ``spell_fireball`` under VAR_NAME and ``Fireball III`` under this.
VAR_DISPLAY_NAME = field_hash("DISPLAYNAME")

#: Flavour text: the italic line under a unique item's name.
VAR_FLAVOR = field_hash("DESCRIPTION")

# -- the numbers a weapon's damage is built from -----------------------------
#
# A save file records a weapon's *physical maximum* and nothing else -- no
# minimum, and no elemental part at all -- so the rest has to be worked out
# from the item's own data file.  These are the fields that do it; the
# arithmetic is in :mod:`tl2stash.gamedata`.

#: The item's own unit id, as a decimal string.  This is the same number the
#: save file carries on the item, and it is what ties a stored item back to
#: the data file it was made from.
VAR_UNIT_GUID = field_hash("UNIT_GUID")

VAR_LEVEL = field_hash("LEVEL")
VAR_MINDAMAGE = field_hash("MINDAMAGE")
VAR_MAXDAMAGE = field_hash("MAXDAMAGE")

#: A percentage modifier on the item's nominal damage: one for the weapon
#: class's own speed, one for its rarity.  Both default to 100.
VAR_SPEED_DMG_MOD = field_hash("SPEED_DMG_MOD")
VAR_RARITY_DMG_MOD = field_hash("RARITY_DMG_MOD")

#: How much of the damage is of each element.  They are shares of the whole,
#: not absolute numbers, which is why they are read as a group.
VAR_DAMAGE_PHYSICAL = field_hash("DAMAGE_PHYSICAL")
VAR_DAMAGE_FIRE = field_hash("DAMAGE_FIRE")
VAR_DAMAGE_ICE = field_hash("DAMAGE_ICE")
VAR_DAMAGE_ELECTRIC = field_hash("DAMAGE_ELECTRIC")
VAR_DAMAGE_POISON = field_hash("DAMAGE_POISON")

#: The same, for armour.
VAR_ARMOR_PHYSICAL = field_hash("ARMOR_PHYSICAL")
VAR_ARMOR_FIRE = field_hash("ARMOR_FIRE")
VAR_ARMOR_ICE = field_hash("ARMOR_ICE")
VAR_ARMOR_ELECTRIC = field_hash("ARMOR_ELECTRIC")
VAR_ARMOR_POISON = field_hash("ARMOR_POISON")

#: Two fields on the base armour file that the item inherits rather than
#: states: how heavy the piece is, and how much armour that weight is worth.
#: Neither is a hashed name -- both are among the field ids nobody has a name
#: for, so they are recorded as they were read.
VAR_ARMOR_WEIGHT = 0x1ED83664
VAR_ARMOR_MIN_WEIGHT = 0x1ED83772
VAR_ARMOR_MULT = 0xE720656C


class DatNode:
    """One node of a DAT tree.

    Variables are flattened into a plain mapping of id to value, because that
    is how they are used: a caller knows the variable it wants and asks for
    it.  Keeping the type alongside would only invite callers to branch on it
    when they already know what they are reading.
    """

    __slots__ = ("node_id", "variables", "children")

    def __init__(
        self,
        node_id: int,
        variables: dict[int, int | float | str],
        children: list["DatNode"],
    ) -> None:
        self.node_id = node_id
        self.variables = variables
        self.children = children

    def __repr__(self) -> str:
        name = self.variables.get(VAR_NAME)
        label = f" {name!r}" if isinstance(name, str) else ""
        return f"<DatNode {self.node_id:#010x}{label} {len(self.children)} children>"

    # -- variables --------------------------------------------------------

    def variable(self, var_id: int) -> int | float | str | None:
        return self.variables.get(var_id)

    def number(self, var_id: int) -> float | None:
        """A numeric variable as a float, or ``None`` if it is absent or text.

        Everything numeric comes back as a float -- ints, words, booleans
        included.  The distinction between an integer variable and a float one
        is a storage detail; where these values are used they are formatted
        the same way.
        """
        value = self.variables.get(var_id)
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def text(self, var_id: int) -> str | None:
        value = self.variables.get(var_id)
        return value if isinstance(value, str) else None

    # -- the tree ---------------------------------------------------------

    def walk(self) -> Iterator["DatNode"]:
        """This node and every node beneath it, parents first."""
        yield self
        for child in self.children:
            yield from child.walk()

    @property
    def name(self) -> str | None:
        return self.text(VAR_NAME)


class DatFile:
    """A parsed DAT file: its strings, and the tree that refers to them."""

    __slots__ = ("version", "dictionary", "root")

    def __init__(
        self, version: int, dictionary: dict[int, str], root: DatNode
    ) -> None:
        self.version = version
        self.dictionary = dictionary
        self.root = root

    def __repr__(self) -> str:
        return f"<DatFile v{self.version} {len(self.dictionary)} strings>"

    @classmethod
    def parse(cls, data: bytes) -> "DatFile":
        reader = Reader(data)
        version = reader.u32()

        dictionary: dict[int, str] = {}
        for _ in range(reader.count()):
            index = reader.u32()
            dictionary[index] = reader.torch_text()

        root = _read_node(reader, dictionary, 0)
        return cls(version, dictionary, root)


def _read_node(
    reader: Reader, dictionary: dict[int, str], depth: int
) -> DatNode:
    if depth > MAX_DEPTH:
        raise ParseError(f"nodes nested deeper than {MAX_DEPTH}")

    node_id = reader.u32()

    variables: dict[int, int | float | str] = {}
    for _ in range(reader.count()):
        var_id_ = reader.u32()
        var_type = reader.u32()
        variables[var_id_] = _read_value(reader, var_type, dictionary)

    children = [
        _read_node(reader, dictionary, depth + 1)
        for _ in range(reader.count())
    ]
    return DatNode(node_id, variables, children)


def _read_value(
    reader: Reader, var_type: int, dictionary: dict[int, str]
) -> int | float | str:
    # Int is signed and Word is not, and the difference is observable: the
    # entry for a melee damage bonus carries -100 as its lower bound, and read
    # as a Word that arrives as 4294967196.
    if var_type == _TYPE_INT:
        return struct.unpack("<i", reader.take(4))[0]
    if var_type == _TYPE_WORD:
        return reader.u32()
    if var_type == _TYPE_BOOL:
        return bool(reader.u32())
    if var_type == _TYPE_FLOAT:
        return struct.unpack("<f", reader.take(4))[0]
    if var_type == _TYPE_DOUBLE:
        return struct.unpack("<d", reader.take(8))[0]
    if var_type == _TYPE_INT64:
        return struct.unpack("<q", reader.take(8))[0]
    if var_type in _TEXT_TYPES:
        index = reader.u32()
        # A text variable naming a string the dictionary does not have is a
        # broken file, but not one worth refusing to read: the rest of the
        # tree is still good, and the empty string renders as nothing rather
        # than as a wrong answer.
        return dictionary.get(index, "")

    # The value's width is unknown, so there is no way to step over it and
    # keep reading.  Stopping here is the only honest option; the caller
    # decides whether one unreadable file matters.
    raise ParseError(f"unknown variable type {var_type}")
