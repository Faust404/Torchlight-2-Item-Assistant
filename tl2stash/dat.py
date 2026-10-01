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
    "VAR_BADDES",
    "VAR_BADDESOT",
    "VAR_BASEFILE",
    "VAR_DISPLAYPRECISION",
    "VAR_EFFECT_TYPE",
    "VAR_GOODDES",
    "VAR_GOODDESOT",
    "VAR_ICON",
    "VAR_NAME",
    "VAR_SLOT_BASE",
    "VAR_UNIDENTIFIED_NAME",
    "DatFile",
    "DatNode",
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

# -- the variables this tool reads -------------------------------------------
#
# Each of these was found by dumping the files that carry it and reading what
# came back, then confirmed against a second, unrelated file: the name
# variable alone turns up on items, affixes, skills, sets, inventory slots and
# effects, holding the right string every time.

#: What the thing is called.  Present on every named node in the archive.
VAR_NAME = 0x00660DE5

#: The file this one inherits from -- a magic sword says it is based on
#: ``media/units/items/swords/base_sword.dat`` and need only give the
#: differences.
VAR_BASEFILE = 0xE27227C5

#: The name shown before the item is identified.
VAR_UNIDENTIFIED_NAME = 0xB9F80B70

#: The icon's name, as a stem under ``MEDIA/UI/ICONS``.
VAR_ICON = 0x006585AE

#: ``KEFFECT_TYPE_MELEEDAMAGEBONUS`` and friends: an effect node's own type,
#: spelled out.  Equal to the node's id, which is what makes an effect's
#: position in EFFECTSLIST.DAT meaningful.
VAR_EFFECT_TYPE = 0x0E421C35

# The four description templates an effect can carry.  Which one the game
# uses is decided by the ``description_type`` on the effect record inside the
# item -- the data file only supplies the words.  Not every effect has all
# four: 208 of the 239 carry GOODDES, 198 carry BADDESOT.
VAR_GOODDES = 0x5AD318DA  # '+[VALUE] Melee weapon damage bonus'
VAR_GOODDESOT = 0x4C62A0DF  # the same, for [DURATION] seconds
VAR_BADDES = 0x003318F2  # '-[VALUE] Melee weapon damage penalty'
VAR_BADDESOT = 0xCC63CFB4

#: How many decimal places to show an effect's value to.  1 on fourteen of the
#: effects, 2 on three, 0 on the rest.
VAR_DISPLAYPRECISION = 0xE5A5EDCC

#: The block an inventory container numbers its slots from.  ``BAG_ARMS_SLOT``
#: declares 3322, and the save file's container 24 holds items in slots 3322
#: upwards; the two were matched on exactly that.
VAR_SLOT_BASE = 0x173B97DF


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
