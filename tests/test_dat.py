"""Tests for the DAT reader.

The synthetic tests build a file field by field, so they hold on any machine.
The tests against the real files skip when the game is not installed -- and
those are the ones that matter, because they are what pins the variable
constants.  A constant read off the data and written down wrong would still
look fine in a fixture built from the same misunderstanding.
"""

from __future__ import annotations

import re
import struct
from collections import Counter
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash import dat  # noqa: E402
from tl2stash.dat import (  # noqa: E402
    VAR_AFFIX_EFFECT,
    VAR_AFFIX_LEVEL,
    VAR_BADDES,
    VAR_BADDESOT,
    VAR_BASEFILE,
    VAR_DISPLAYPRECISION,
    VAR_DISPLAY_NAME,
    VAR_EFFECT_TYPE,
    VAR_FLAVOR,
    VAR_GOODDES,
    VAR_GOODDESOT,
    VAR_ICON,
    VAR_NAME,
    VAR_SLOT_BASE,
    VAR_SLOT_NAME,
    VAR_UNIDENTIFIED_NAME,
    VAR_UNITTYPE,
    VAR_UNITTYPES,
    DatFile,
    DatNode,
    field_hash,
)
from tl2stash.binary import ParseError  # noqa: E402
from tl2stash.gamedata import GameData, find_install  # noqa: E402

# The var types as the format numbers them.
INT, FLOAT, DOUBLE, WORD, TEXT, BOOL, INT64, TRANSLATE = range(1, 9)


# --------------------------------------------------------------------------
# Synthetic DAT construction
# --------------------------------------------------------------------------


def _torch_text(text: str) -> bytes:
    encoded = text.encode("utf-16-le")
    return struct.pack("<H", len(encoded) // 2) + encoded


def write_dat(dictionary: dict[int, str], nodes: list[dict], *, version: int = 2) -> bytes:
    """Build a DAT file.

    ``nodes`` is a list of ``{"id": int, "vars": {id: (type, value)}, "kids":
    [...]}``; a value for a TEXT or TRANSLATE variable is the dictionary index.
    ``vars`` may also be a *list* of ``(id, (type, value))`` pairs, which is
    what a DAT list needs: its entries all carry the one field id, and a
    mapping cannot hold two of those.
    """
    out = bytearray()
    out += struct.pack("<I", version)
    out += struct.pack("<I", len(dictionary))
    for index, text in sorted(dictionary.items()):
        out += struct.pack("<I", index)
        out += _torch_text(text)

    def emit(node: dict):
        out.extend(struct.pack("<I", node.get("id", 0)))
        variables = node.get("vars", {})
        listed = variables if isinstance(variables, list) else list(variables.items())
        out.extend(struct.pack("<I", len(listed)))
        for var_id, (var_type, value) in listed:
            out.extend(struct.pack("<II", var_id, var_type))
            if var_type in (INT, WORD):
                # Masked because it is the same four bytes either way -- that
                # is the whole point of the signedness test below.
                out.extend(struct.pack("<I", value & 0xFFFFFFFF))
            elif var_type is BOOL:
                out.extend(struct.pack("<I", 1 if value else 0))
            elif var_type is FLOAT:
                out.extend(struct.pack("<f", value))
            elif var_type is DOUBLE:
                out.extend(struct.pack("<d", value))
            elif var_type is INT64:
                out.extend(struct.pack("<q", value))
            elif var_type in (TEXT, TRANSLATE):
                out.extend(struct.pack("<I", value))
            else:
                raise ValueError(f"unhandled type {var_type}")
        kids = node.get("kids", [])
        out.extend(struct.pack("<I", len(kids)))
        for kid in kids:
            emit(kid)

    for node in nodes:
        emit(node)
    return bytes(out)


@pytest.fixture
def sample():
    """A tree with one of every variable type on it."""
    dictionary = {0: "a name", 1: "some text", 2: "translated"}
    data = write_dat(
        dictionary,
        [
            {
                "id": 0x12345678,
                "vars": {
                    0x00000001: (INT, 7),
                    0x00000002: (FLOAT, 0.5),
                    0x00000003: (DOUBLE, 1.25),
                    0x00000004: (WORD, 4000000000),
                    0x00000005: (TEXT, 0),
                    0x00000006: (BOOL, True),
                    0x00000007: (INT64, -5000000000),
                    0x00000008: (TRANSLATE, 1),
                },
                "kids": [
                    {"id": 0x99, "vars": {0x00000005: (TEXT, 2)}},
                ],
            }
        ],
    )
    return DatFile.parse(data)


# --------------------------------------------------------------------------
# The tree
# --------------------------------------------------------------------------


def test_a_file_keeps_its_version_and_its_strings(sample):
    assert sample.version == 2
    assert sample.dictionary == {0: "a name", 1: "some text", 2: "translated"}


def test_text_variables_are_resolved_as_the_tree_is_built(sample):
    """Nothing downstream should have to carry the dictionary around."""
    assert sample.root.text(0x00000005) == "a name"
    assert sample.root.text(0x00000008) == "some text"


def test_a_text_variable_naming_a_missing_string_is_empty_not_an_error():
    """A broken string is not worth refusing to read the rest of the file for."""
    data = write_dat({0: "here"}, [{"vars": {0x00000005: (TEXT, 999)}}])
    assert DatFile.parse(data).root.text(0x00000005) == ""


def test_every_number_comes_back_as_a_float(sample):
    """Int, Word, Bool and Double are all numbers where they are used."""
    for var_id in (0x00000001, 0x00000002, 0x00000003, 0x00000004):
        value = sample.root.number(var_id)
        assert isinstance(value, float), var_id

    assert sample.root.number(0x00000001) == 7.0
    assert sample.root.number(0x00000002) == 0.5
    assert sample.root.number(0x00000003) == 1.25
    assert sample.root.number(0x00000006) == 1.0


def test_a_text_variable_is_not_a_number(sample):
    assert sample.root.number(0x00000005) is None
    assert sample.root.text(0x00000001) is None


def test_a_variable_that_is_not_there_is_none(sample):
    assert sample.root.variable(0xDEADBEEF) is None
    assert sample.root.number(0xDEADBEEF) is None
    assert sample.root.text(0xDEADBEEF) is None


def test_walk_visits_every_node_parents_first(sample):
    visited = list(sample.root.walk())
    assert len(visited) == 2
    assert visited[0] is sample.root
    assert visited[1].text(0x00000005) == "translated"


# --------------------------------------------------------------------------
# A list, which is a node whose variables repeat
# --------------------------------------------------------------------------


def test_a_list_keeps_every_entry_not_only_the_last():
    """An affix's applicability list is a node with one entry per unit type.

    The bytes are a node's: a count, then that many field-id-and-value pairs,
    then a child count of zero.  Nothing distinguishes it from a node that
    happens to state the same field three times, and the game's files carry
    1,136 of them -- ``UNIQUE_DEFENSE_BONUS`` may be applied to armor, to
    trinkets and to unique socketables, and a mapping of ids to values keeps
    only the third of those.  So the entries are kept beside it, in file order.
    """
    dictionary = {0: "ARMOR", 1: "TRINKET", 2: "UNIQUE SOCKETABLE"}
    data = write_dat(
        dictionary,
        [
            {
                "kids": [
                    {
                        "id": VAR_UNITTYPES,
                        "vars": [
                            (VAR_UNITTYPE, (TEXT, 0)),
                            (VAR_UNITTYPE, (TEXT, 1)),
                            (VAR_UNITTYPE, (TEXT, 2)),
                        ],
                    }
                ]
            }
        ],
    )

    node = DatFile.parse(data).root.children[0]

    assert node.node_id == VAR_UNITTYPES
    assert node.texts(VAR_UNITTYPE) == ("ARMOR", "TRINKET", "UNIQUE SOCKETABLE")
    assert node.values(VAR_UNITTYPE) == ("ARMOR", "TRINKET", "UNIQUE SOCKETABLE")
    # The mapping is still there and still holds the last one -- it is what an
    # affix file's *name* is read through, and it is not wrong, only partial.
    assert node.text(VAR_UNITTYPE) == "UNIQUE SOCKETABLE"


def test_a_node_that_does_not_repeat_answers_the_same_way():
    """One entry is a list of one, so every caller has one shape to read.

    ``GEM_TEST_ARMOR``'s children state a host once each, and the four older
    gems' state theirs under the other spelling; both come back through this.
    """
    data = write_dat(
        {0: "WEAPON"},
        [
            {
                "kids": [
                    {"vars": {VAR_UNITTYPE: (TEXT, 0)}},
                    {"vars": [(VAR_UNITTYPES, (TEXT, 0))]},
                    {"vars": {0x01: (INT, 7)}},
                ]
            }
        ],
    )
    first, second, third = DatFile.parse(data).root.children

    assert first.texts(VAR_UNITTYPE) == ("WEAPON",)
    assert second.texts(VAR_UNITTYPES) == ("WEAPON",)
    # Nothing stated under it is an empty answer rather than an error, and not
    # the one value every node would otherwise have.
    assert third.values(VAR_UNITTYPE) == ()
    assert third.texts(VAR_UNITTYPE) == ()


# --------------------------------------------------------------------------
# Signedness -- the one place the format is easy to get quietly wrong
# --------------------------------------------------------------------------


def test_int_is_signed_and_word_is_not():
    """Both are four bytes and both are "a number"; only one goes negative.

    The game's own data shows it: the entry for a melee damage bonus carries
    -100 as its lower bound.  Read as a Word that same word arrives as
    4294967196, which is a value no item has ever had.
    """
    data = write_dat(
        {},
        [{"vars": {0x01: (INT, -100), 0x02: (WORD, 4000000000)}}],
    )
    root = DatFile.parse(data).root

    assert root.number(0x01) == -100.0
    assert root.number(0x02) == 4000000000.0


def test_the_raw_unsigned_reading_is_what_the_signed_one_avoids():
    """Stated as the arithmetic, so the test above cannot pass by accident."""
    data = write_dat({}, [{"vars": {0x01: (INT, -100)}}])
    raw = data[-8:-4]  # the value word, just before the child count
    assert struct.unpack("<I", raw)[0] == 4294967196
    assert DatFile.parse(data).root.number(0x01) == -100.0


def test_an_int64_is_signed_too():
    data = write_dat({}, [{"vars": {0x01: (INT64, -5000000000)}}])
    assert DatFile.parse(data).root.number(0x01) == -5000000000.0


# --------------------------------------------------------------------------
# Refusing what it cannot read
# --------------------------------------------------------------------------


def test_an_unknown_variable_type_stops_the_parse():
    """Its width is unknown, so there is no way to step over it and go on.

    Guessing would not fail here -- it would return a tree with the rest of
    the node read from the wrong offset, which is worse than an error.
    """
    data = write_dat({}, [{"vars": {0x01: (WORD, 1)}}])
    broken = bytearray(data)
    # version | empty dictionary | node id | var count | var id | type | value
    #    0-4         4-8            8-12      12-16     16-20   20-24
    broken[20:24] = struct.pack("<I", 99)

    with pytest.raises(ParseError, match="unknown variable type 99"):
        DatFile.parse(bytes(broken))


def test_a_truncated_file_stops_the_parse():
    data = write_dat({}, [{"vars": {0x01: (TEXT, 0)}}])
    with pytest.raises(ParseError):
        DatFile.parse(data[:-6])


# --------------------------------------------------------------------------
# Real files (skipped when the game is not installed)
# --------------------------------------------------------------------------


_INSTALL = find_install()

needs_game = pytest.mark.skipif(
    _INSTALL is None, reason="Torchlight II is not installed on this machine"
)


@pytest.fixture(scope="module")
def game():
    # The game's own files and nothing else.  The augment table is the
    # reference database's, which may or may not be on the machine running
    # this -- and a test whose expected lines depend on that is a test that
    # passes here and fails somewhere else.
    return GameData.load(_INSTALL, augments={})


#: The same fixture under the name the other test modules import it by.
real_game = game


# --------------------------------------------------------------------------
# A variable's id is the DEK hash of its name
# --------------------------------------------------------------------------


def test_the_id_of_a_variable_is_the_dek_hash_of_its_name():
    """Checkable arithmetic rather than a constant to be taken on trust.

    ``h`` starts at the name's length; each byte then does
    ``h = ((h << 5) ^ (h >> 27) ^ byte)``.  The literal below is the id the
    files hold for ``NAME``, read off them before the rule was known.
    """
    assert field_hash("NAME") == 0x00660DE5


def test_every_constant_this_module_measured_reproduces_from_its_name():
    """The twelve that were measured before the rule was found, and the ones
    found since by using it.  All of them at once, so a wrong one cannot hide
    behind a right one."""
    assert field_hash("NAME") == VAR_NAME
    assert field_hash("BASEFILE") == VAR_BASEFILE
    assert field_hash("UNIDENTIFIED_NAME") == VAR_UNIDENTIFIED_NAME
    assert field_hash("ICON") == VAR_ICON
    assert field_hash("GOODDES") == VAR_GOODDES
    assert field_hash("GOODDESOT") == VAR_GOODDESOT
    assert field_hash("BADDES") == VAR_BADDES
    assert field_hash("BADDESOT") == VAR_BADDESOT
    assert field_hash("DISPLAYPRECISION") == VAR_DISPLAYPRECISION
    # The game's own name for the field an affix names its effect under.
    assert field_hash("TYPE") == VAR_AFFIX_EFFECT
    assert field_hash("DISPLAYNAME") == VAR_DISPLAY_NAME
    assert field_hash("DESCRIPTION") == VAR_FLAVOR


def test_the_ids_no_name_has_reproduced_are_these_five():
    """Every constant either falls out of the rule or is listed here.

    Two different things stop a constant reproducing from *its own* name.
    Four of them the module names for what the field means rather than what
    it is called -- ``VAR_FLAVOR`` is the field ``DESCRIPTION``,
    ``VAR_EFFECT_TYPE`` is the field ``EFFECT`` -- and those hash correctly
    under the game's spelling.  ``VAR_AFFIX_LEVEL`` and ``VAR_SLOT_NAME`` are
    the same arrangement for a smaller reason: the fields are the one words
    ``AFFIXLEVEL`` and ``SLOTNAME``, and the constants are spaced for reading.
    The rest are simply their own names.

    What is left over is five ids with no name at all, and that is the point
    of writing the list down: none of them is a hash of a name nobody has
    guessed yet by accident, and a sixth cannot join them without someone
    deciding it belongs.  ``VAR_EFFECT_GRAPH`` is the one that arrived last:
    the graph an effect's numbers scale with, on 36 of the 239 effects, filed
    under two ids that always hold the same string.
    """
    renamed = {
        VAR_AFFIX_EFFECT: "TYPE",
        VAR_AFFIX_LEVEL: "AFFIXLEVEL",
        VAR_DISPLAY_NAME: "DISPLAYNAME",
        VAR_FLAVOR: "DESCRIPTION",
        VAR_EFFECT_TYPE: "EFFECT",
        VAR_SLOT_NAME: "SLOTNAME",
    }

    unexplained = []
    for name in dir(dat):
        if not name.startswith("VAR_"):
            continue
        value = getattr(dat, name)
        if not isinstance(value, int):
            continue
        if field_hash(renamed.get(value, name[4:])) != value:
            unexplained.append(name)

    assert sorted(unexplained) == [
        "VAR_ARMOR_MIN_WEIGHT",
        "VAR_ARMOR_MULT",
        "VAR_ARMOR_WEIGHT",
        "VAR_EFFECT_GRAPH",
        "VAR_SLOT_BASE",
    ]


@pytest.fixture(scope="module")
def effects(game):
    """``MEDIA/EFFECTSLIST.DAT``, the file the constants below are read from."""
    from tl2stash.pak import PakFile, PakIndex

    from tl2stash.gamedata import archive_path

    man_path = archive_path(_INSTALL)
    index = PakIndex.read(man_path)
    with PakFile(man_path.with_name("DATA.PAK"), index) as archive:
        return DatFile.parse(archive.read("MEDIA/EFFECTSLIST.DAT"))


@needs_game
def test_the_effect_list_is_a_flat_list_of_239(effects):
    assert effects.version == 2
    assert len(effects.root.children) == 239
    assert not effects.root.variables


@needs_game
def test_every_effect_names_itself(effects):
    """This is what pins VAR_NAME: 239 nodes, and not one is anonymous."""
    for node in effects.root.children:
        assert node.text(VAR_NAME), node


@needs_game
def test_an_effect_carries_its_own_type_name(effects):
    """Under VAR_EFFECT_TYPE, an effect spells out what it is.

    Which makes the file a *list* whose order means something rather than a
    bag of nodes -- and makes it possible to check a name against the node it
    came from.

    The spelling is the name with everything that is not a letter or a digit
    turned into an underscore: the effect called ``MAX MANA`` declares itself
    ``KEFFECT_TYPE_MAX_MANA``.  Assuming the two matched literally is the
    mistake this test was written with.
    """
    def spelled_out(name: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in name.upper())

    for node in effects.root.children:
        expected = f"KEFFECT_TYPE_{spelled_out(node.text(VAR_NAME))}"
        assert node.text(VAR_EFFECT_TYPE) == expected, node.text(VAR_NAME)


@needs_game
def test_the_four_description_templates_read_as_sentences(effects):
    """Pinning the four constants, on the effect they were read from."""
    by_name = {node.text(VAR_NAME).upper(): node for node in effects.root.children}
    bonus = by_name["MELEEDAMAGEBONUS"]

    assert bonus.text(VAR_GOODDES) == "+[VALUE] Melee weapon damage bonus"
    assert bonus.text(VAR_GOODDESOT) == (
        "+[VALUE] Melee weapon damage bonus for [DURATION]"
    )
    assert bonus.text(VAR_BADDES) == "-[VALUE] Melee weapon damage penalty"
    assert bonus.text(VAR_BADDESOT) == (
        "-[VALUE] Melee weapon damage penalty for [DURATION]"
    )


@needs_game
def test_the_description_tags_are_a_bounded_vocabulary(effects):
    """The whole set of holes a description can leave, read off the data.

    This is what the renderer has to fill in, and it is worth having in one
    place: a tag that turns up later and is not in this set fails here rather
    than reaching a player as a literal ``[VALUE3AND4]`` on their tooltip.

    ``[VALUE5]`` is the one that is easy to miss -- it appears on four
    descriptions out of eight hundred.
    """
    known = {
        "VALUE",
        "VALUE1",
        "VALUE2",
        "VALUE3",
        "VALUE4",
        "VALUE5",
        "VALUE3AND4",
        "VALUE_OT",
        "VALUE1ASDURATION",
        "DURATION",
        "DMGTYPE",
        "NAME",
    }
    found = Counter()
    for node in effects.root.children:
        for var in (VAR_GOODDES, VAR_GOODDESOT, VAR_BADDES, VAR_BADDESOT):
            text = node.text(var)
            if text:
                found.update(re.findall(r"\[([^\]]+)\]", text))

    assert set(found) <= known, f"unknown tags: {sorted(set(found) - known)}"
    assert found["VALUE"] > 500, "the common case has stopped being common"
    assert found["DURATION"] > 100, "the duration tag has gone missing"


@needs_game
def test_not_every_description_has_a_number_to_fill_in(effects):
    """Seventy-nine of them are fixed sentences.

    ``Identify Item``, ``Create Waypoint Portal``, ``NA``, ``Learn [NAME]`` --
    and ``% Attack Rating Bonus``, which names a percentage and then leaves no
    hole to put it in.  So the renderer cannot assume it always has a value to
    substitute, and a description with no hole is not a broken one.
    """
    templates = [
        text
        for node in effects.root.children
        for var in (VAR_GOODDES, VAR_GOODDESOT, VAR_BADDES, VAR_BADDESOT)
        if (text := node.text(var))
    ]
    with_value = [text for text in templates if "[VALUE" in text]

    assert len(templates) > 700
    assert len(with_value) / len(templates) > 0.85, "the ratio has changed"
    assert len(templates) - len(with_value) > 20, "the fixed ones have vanished"


@needs_game
def test_display_precision_is_a_small_count(effects):
    """Zero, one or two decimals -- never anything that would round to noise."""
    values = {
        node.number(VAR_DISPLAYPRECISION) for node in effects.root.children
    }
    assert values <= {0.0, 1.0, 2.0}, values


@needs_game
def test_a_container_names_itself_and_its_id():
    """The file for the first shared stash bag says it is bag 24.

    Which is the number the save file records, so no arithmetic is needed to
    tie the two together.
    """
    from tl2stash.gamedata import archive_path
    from tl2stash.pak import PakFile, PakIndex

    man_path = archive_path(_INSTALL)
    index = PakIndex.read(man_path)
    with PakFile(man_path.with_name("DATA.PAK"), index) as archive:
        data = DatFile.parse(
            archive.read("MEDIA/INVENTORY/CONTAINERS/SHARED_STASH_BAG_ARMS.DAT")
        )

    assert data.root.text(VAR_NAME) == "SHARED_STASH_BAG_ARMS"
    assert data.root.number(VAR_SLOT_BASE) == 24


@needs_game
def test_an_item_names_itself(game):
    """VAR_NAME on something that is not an effect at all."""
    node = game.by_name("Djinn Fire Sword")
    assert node is not None, "the sword in MEDIA/UNITS/ITEMS/SWORDS is not indexed"
    assert node.text(VAR_NAME).lower() == "djinn fire sword"
