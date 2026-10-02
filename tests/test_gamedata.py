"""Tests for the game-data facade.

Most of these run against a synthetic install -- a manifest, an archive and a
handful of DAT files built in the test -- so they hold on a machine that has
never seen Torchlight II.  What they cannot check is whether the *constants*
are right, since a fixture built from a wrong constant would agree with
itself; ``tests/test_dat.py`` pins those against the real files instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash.dat import (  # noqa: E402
    VAR_AFFIX,
    VAR_AFFIX_EFFECT,
    VAR_AFFIX_LEVEL,
    VAR_BADDES,
    VAR_BADDESOT,
    VAR_COUNT,
    VAR_DAMAGE_TYPE,
    VAR_DISPLAYPRECISION,
    VAR_DISPLAY_NAME,
    VAR_DURATION,
    VAR_EFFECT_GRAPH,
    VAR_EFFECT_TYPE,
    VAR_GOODDES,
    VAR_GOODDESOT,
    VAR_LEVEL,
    VAR_MAXDAMAGE,
    VAR_MINDAMAGE,
    VAR_NAME,
    VAR_SET,
    VAR_SLOT_BASE,
    VAR_SLOT_NAME,
    VAR_UNITTYPE,
    VAR_UNITTYPES,
    VAR_UNIT_GUID,
    DatFile,
)
from tl2stash.gamedata import (  # noqa: E402
    DEFAULT_PRECISION,
    GRAPH_LEVEL_VAR,
    GRAPH_VALUE_VAR,
    GameData,
    archive_path,
    find_install,
    read_unit_type,
)

from test_dat import (  # noqa: E402
    FLOAT,
    INT,
    TEXT,
    TRANSLATE,
    needs_game,
    real_game,
    write_dat,
)
from test_pak import write_synthetic_pak  # noqa: E402
from test_tooltip import item, word  # noqa: E402


# --------------------------------------------------------------------------
# A synthetic install
# --------------------------------------------------------------------------


def install(tmp_path: Path) -> Path:
    """An install directory with just enough in it to load."""
    files: dict[str, bytes] = {}
    strings: dict[int, str] = {}

    def string(text: str) -> int:
        """The index of ``text`` in this file's dictionary, adding it if new."""
        index = len(strings)
        strings[index] = text
        return index

    def effect(name: str, templates: dict[int, str], graph: str | None = None) -> dict:
        """One effect node.  ``templates`` maps a description variable to its
        wording; written as a dict because the keys are the game's constants.

        ``graph`` is the by-level curve the effect's numbers scale with, as a
        bare stem, which is how 36 of the game's 239 effects state it.
        """
        variables = {
            VAR_NAME: (TEXT, string(name)),
            VAR_EFFECT_TYPE: (TEXT, string(f"KEFFECT_TYPE_{name}")),
            VAR_DISPLAYPRECISION: (2, 2),
        }
        if graph:
            variables[VAR_EFFECT_GRAPH] = (TEXT, string(graph))
        for var, text in templates.items():
            variables[var] = (TRANSLATE, string(text))
        return {"vars": variables}

    # The effects are the root's children -- EFFECTSLIST is a list, not a
    # single node -- and every string they mention shares one dictionary.
    effects = {
        "kids": [
            effect(
                "MELEEDAMAGEBONUS",
                {
                    VAR_GOODDES: "+[VALUE] Melee weapon damage bonus",
                    VAR_GOODDESOT: "+[VALUE] Melee weapon damage bonus for [DURATION]",
                    VAR_BADDES: "-[VALUE] Melee weapon damage penalty",
                    VAR_BADDESOT: "-[VALUE] Melee weapon damage penalty for [DURATION]",
                },
            ),
            effect("MAX MANA", {VAR_GOODDES: "+[VALUE] Max Mana"}),
            # Three effects for the set ladders below: one whose numbers scale
            # with a curve, one that names a skill, and one that lasts.
            effect(
                "SET DAMAGE BONUS",
                {VAR_GOODDES: "+[VALUE] Set damage"},
                graph="TEST_CURVE",
            ),
            effect(
                "SET PROC",
                {VAR_GOODDES: "[VALUE]% chance to cast [NAME] on kill"},
            ),
            effect(
                "SET BURN",
                {
                    VAR_GOODDES: "+[VALUE] Set burn",
                    VAR_GOODDESOT: "[VALUE_OT] Set burn damage over [DURATION]",
                },
            ),
        ]
    }
    files["MEDIA/EFFECTSLIST.DAT"] = write_dat(strings, [effects])

    # A by-level curve, and the skill one of the effects above names.  200% at
    # level 1 and 145.5% at level 10 -- the second is what the real archive's
    # MANA_PLAYER_GENERIC states at level 99 -- so the rungs below land on
    # different numbers from one nominal, one of them exactly and one of them
    # only after rounding.  The rows are the root's children, as a graph file
    # has them: a top-level list of two nodes would parse as one node and lose
    # the second.
    files["MEDIA/GRAPHS/STATS/TEST_CURVE.DAT"] = write_dat(
        {},
        [
            {
                "kids": [
                    {"vars": {GRAPH_LEVEL_VAR: (INT, 1), GRAPH_VALUE_VAR: (FLOAT, 200.0)}},
                    {"vars": {GRAPH_LEVEL_VAR: (INT, 10), GRAPH_VALUE_VAR: (FLOAT, 145.5)}},
                ]
            }
        ],
    )
    files["MEDIA/SKILLS/TESTPROC.DAT"] = write_dat(
        {0: "TEST_PROC", 1: "Test Proc"},
        [
            {
                "vars": {
                    VAR_NAME: (TEXT, 0),
                    VAR_DISPLAY_NAME: (TEXT, 1),
                }
            }
        ],
    )

    # The seven by-level curves an item's requirements come off, under the
    # names the game files them by.  The numbers are small and unlike each
    # other on purpose: a curve read for the wrong field, or a requirement
    # scaled by the wrong one, lands on a value the tests can name.
    def curve(stem: str, points: dict[int, float]) -> None:
        files[f"MEDIA/GRAPHS/STATS/{stem}.DAT"] = write_dat(
            {},
            [
                {
                    "kids": [
                        {
                            "vars": {
                                GRAPH_LEVEL_VAR: (INT, level),
                                GRAPH_VALUE_VAR: (FLOAT, value),
                            }
                        }
                        for level, value in points.items()
                    ]
                }
            ],
        )

    curve("ITEM_LEVEL_REQUIREMENTS", {1: 3.0, 10: 13.0, 20: 24.0, 50: 57.0})
    # The Normal curve stops at 20 here, as the game's stops at 50, so that a
    # level past its end falling through to the general one can be tested.
    curve("ITEM_LEVEL_REQUIREMENTS_NORMAL", {1: 1.0, 10: 8.0, 20: 15.0})
    curve("ITEM_LEVEL_REQUIREMENTS_SOCKETABLE", {1: 1.0, 10: 2.0, 20: 12.0})
    curve("ITEM_STRENGTH_REQUIREMENTS", {10: 50.0, 20: 100.0})
    curve("ITEM_DEXTERITY_REQUIREMENTS", {10: 25.0, 20: 75.0})
    curve("ITEM_MAGIC_REQUIREMENTS", {10: 150.0, 20: 200.0, 50: 400.0})
    curve("ITEM_DEFENSE_REQUIREMENTS", {10: 90.0, 20: 60.0})

    # Items to ask those curves about.  Each is one of the shapes a
    # requirement is read for, and each states its own level because the
    # curves are indexed by it.
    def item_file(
        path: str,
        name: str,
        unit_type: str,
        level: int,
        guid: int,
        stated: dict | None = None,
    ) -> None:
        variables = {
            VAR_NAME: (TEXT, string(name)),
            VAR_UNITTYPE: (TEXT, string(unit_type)),
            VAR_LEVEL: (INT, level),
            # Written as the decimal *string* the game writes it as, which is
            # the one place the file's shape can be got wrong quietly.
            VAR_UNIT_GUID: (TEXT, string(str(guid))),
        }
        variables.update(stated or {})
        files[f"MEDIA/UNITS/ITEMS/{path}"] = write_dat(strings, [{"vars": variables}])

    from tl2stash.dat import (  # noqa: PLC0415 -- the fixture's own names
        VAR_DEFENSE_REQUIRED,
        VAR_DEXTERITY_REQUIRED,
        VAR_LEVEL_REQUIRED,
        VAR_MAGIC_REQUIRED,
        VAR_STRENGTH_REQUIRED,
    )

    # A plain sword: no rarity of its own, so its gate is the Normal curve.
    item_file("SWORDS/TEST_PLAIN.DAT", "Test Plain", "SWORD", 10, 0x7001)
    # A unique: the general curve.
    item_file("SWORDS/TEST_UNIQUE.DAT", "Test Unique", "UNIQUESWORD", 20, 0x7002)
    # A socketable: the socketing curve, which is about the item it goes into.
    item_file("GEMS/TEST_GEM.DAT", "Test Gem", "SOCKETABLE", 20, 0x7003)
    # One that states its own level, which is the answer and is not scaled.
    item_file(
        "SWORDS/TEST_STATED.DAT",
        "Test Stated",
        "UNIQUESWORD",
        20,
        0x7004,
        {VAR_LEVEL_REQUIRED: (INT, 99)},
    )
    # One that states attributes, which are percentages of their curves.
    item_file(
        "SWORDS/TEST_STATS.DAT",
        "Test Stats",
        "UNIQUESWORD",
        10,
        0x7005,
        {
            VAR_STRENGTH_REQUIRED: (INT, 100),
            VAR_MAGIC_REQUIRED: (INT, 100),
            VAR_DEFENSE_REQUIRED: (INT, 0),
        },
    )
    # A Normal item past the end of the Normal curve, which falls through to
    # the general one rather than being extrapolated.
    item_file("SWORDS/TEST_OFF_CURVE.DAT", "Test Off Curve", "SWORD", 50, 0x7006)

    # Two pieces of the set above.  Membership is one field on the item's own
    # file and it holds the set's *internal* name -- the display one is the set
    # file's business, and turning one into the other is what
    # ``appearance_for`` does.  Two of them, because a set of one is a set
    # nothing can be shown *apart* from: ``tests/test_app.py`` clicks one of
    # these names and has to see the other.
    item_file(
        "SWORDS/TEST_SET_BLADE.DAT",
        "Test Set Blade",
        "UNIQUESWORD",
        20,
        0x7007,
        {VAR_SET: (TEXT, string("TEST_SET"))},
    )
    item_file(
        "SWORDS/TEST_SET_EDGE.DAT",
        "Test Set Edge",
        "UNIQUESWORD",
        20,
        0x7008,
        {VAR_SET: (TEXT, string("TEST_SET"))},
    )

    # Containers: each names itself and declares the id the save file records.
    # The ARMS tab also names the slot file its cells come from, which is how
    # the game ties a container to the numbers its slots carry: the container
    # says *which* file, and the file says *which number* the first cell has.
    files["MEDIA/INVENTORY/CONTAINERS/SHARED_STASH_BAG_ARMS.DAT"] = write_dat(
        {0: "SHARED_STASH_BAG_ARMS", 1: "BAG_ARMS_SLOT"},
        [
            {
                "vars": {VAR_NAME: (TEXT, 0), VAR_SLOT_BASE: (2, 24)},
                "kids": [{"vars": {VAR_SLOT_NAME: (TEXT, 1)}}],
            }
        ],
    )
    files["MEDIA/INVENTORY/CONTAINERS/SHARED_STASH_BAG_SPELLS.DAT"] = write_dat(
        {0: "SHARED_STASH_BAG_SPELLS"},
        [{"vars": {VAR_NAME: (TEXT, 0), VAR_SLOT_BASE: (2, 26)}}],
    )
    # The numbered half of that pair, beside the containers rather than in.
    files["MEDIA/INVENTORY/BAG_ARMS_SLOT.DAT"] = write_dat(
        {0: "BAG_ARMS_SLOT"},
        [{"vars": {VAR_NAME: (TEXT, 0), VAR_SLOT_BASE: (2, 3322)}}],
    )
    # A slot file *beside* the containers: same idea, different space of
    # numbers, and its 0 is not container 0.
    files["MEDIA/INVENTORY/BAG.DAT"] = write_dat(
        {0: "BAG"}, [{"vars": {VAR_NAME: (TEXT, 0), VAR_SLOT_BASE: (2, 0)}}]
    )

    # Affixes.  An item's effect record names one of these rather than naming
    # an effect, and the name is shared: two of the affixes below are called
    # OFFLAME MELEEDAMAGEBONUS and grant different effects, which is the whole
    # reason effect_for exists.  Each node is named like the affix it belongs
    # to and carries the effect it actually grants.
    def affix(name: str, grants: str) -> dict:
        return {
            "vars": {
                VAR_NAME: (TEXT, string(name)),
                VAR_AFFIX_EFFECT: (TEXT, string(grants)),
            }
        }

    files["MEDIA/AFFIXES/ITEMS/AFFIXES.DAT"] = write_dat(
        strings,
        [
            {
                "kids": [
                    affix("OFTHEELEPHANT MAX MANA", "MAX MANA"),
                    affix("OFFLAME MELEEDAMAGEBONUS", "MAX MANA"),
                    affix("OFFLAME MELEEDAMAGEBONUS", "MELEEDAMAGEBONUS"),
                    affix("OFNOTHING", "MAX MANA"),
                    affix("OFNOTHING", "MELEEDAMAGEBONUS"),
                    affix("OFGHOST", "MELEEDAMAGEBONUS"),
                    affix("OFGHOST", "NO SUCH EFFECT"),
                    # An affix wearing an effect's name, which EFFECTSLIST wins.
                    affix("MAX MANA", "MELEEDAMAGEBONUS"),
                    # The affixes a set's rungs name.  Shaped like the real
                    # ones: the root carries nothing but the name, and one
                    # child per effect it grants, whose *node id* is the effect
                    # variable -- the rung's numbers live on those children
                    # rather than on the root, which is the difference from the
                    # affixes above.
                    {
                        "vars": {VAR_NAME: (TEXT, string("SET AFFIX TWO"))},
                        "kids": [
                            # MIN and MAX, as floats and in file order, then a
                            # third number that is a *parameter* of the effect
                            # rather than part of its value: only the first two
                            # scale with a curve.
                            {
                                "id": VAR_EFFECT_TYPE,
                                "vars": {
                                    VAR_AFFIX_EFFECT: (
                                        TEXT,
                                        string("SET DAMAGE BONUS"),
                                    ),
                                    VAR_MINDAMAGE: (FLOAT, 3.0),
                                    VAR_MAXDAMAGE: (FLOAT, 3.0),
                                    0x67A1010: (FLOAT, 7.0),
                                },
                            },
                            # Names a skill, which is what a [NAME] hole wants.
                            # The name on the node is the one the *skill* is
                            # filed under, and only the skill carries a display
                            # name.
                            {
                                "id": VAR_EFFECT_TYPE,
                                "vars": {
                                    VAR_AFFIX_EFFECT: (TEXT, string("SET PROC")),
                                    VAR_NAME: (TEXT, string("TEST_PROC")),
                                    VAR_MINDAMAGE: (FLOAT, 2.5),
                                    VAR_MAXDAMAGE: (FLOAT, 2.5),
                                },
                            },
                        ],
                    },
                    {
                        "vars": {VAR_NAME: (TEXT, string("SET AFFIX THREE"))},
                        "kids": [
                            # A duration, written as text as the real files
                            # write it, which is what puts the effect on the
                            # over-time wording.
                            {
                                "id": VAR_EFFECT_TYPE,
                                "vars": {
                                    VAR_AFFIX_EFFECT: (TEXT, string("SET BURN")),
                                    VAR_DURATION: (TEXT, string("5")),
                                    VAR_DAMAGE_TYPE: (TEXT, string("FIRE")),
                                    VAR_MINDAMAGE: (FLOAT, 5.0),
                                    VAR_MAXDAMAGE: (FLOAT, 5.0),
                                },
                            }
                        ],
                    },
                ]
            }
        ],
    )

    # Gem affixes.  A socketable's own file does not say which host each of its
    # bonuses is for -- it is one bonus *per* host, and the halves are separate
    # files -- so the hosts are read off these.  One file per way the archive
    # states it, because it is the *file's name* that states it on the newer
    # embers: each of these is a file rather than a node in a list, as in the
    # archive, and each carries the host node and then the effect node that the
    # real ones do.
    def gem_file(stem: str, grants: str, *hosts: tuple[int, str]) -> None:
        """One ``MEDIA/AFFIXES/GEMS/<stem>.DAT``.

        ``hosts`` pairs the field with its value rather than taking values
        alone, because the archive spells the field two ways -- ``UNITTYPE``
        on the newer files and ``UNITTYPES`` on the older gems -- and both
        spellings are read.
        """
        files[f"MEDIA/AFFIXES/GEMS/{stem}.DAT"] = write_dat(
            strings,
            [
                {
                    "vars": {VAR_NAME: (TEXT, string(stem))},
                    "kids": [
                        {"vars": {var: (TEXT, string(host))}} for var, host in hosts
                    ]
                    + [{"vars": {VAR_AFFIX_EFFECT: (TEXT, string(grants))}}],
                }
            ],
        )

    # A name that says nothing, so the children decide -- and like the older
    # gems it states the field under the plural spelling.
    gem_file("GEM_TEST", "DAMAGE BONUS", (VAR_UNITTYPES, "WEAPON"))
    # A name that says it, with children that agree.
    gem_file("GEM_TEST_ARMOR", "FIRE DEFENSE", (VAR_UNITTYPE, "TRINKET"))
    # The newer embers: the name says one host and the children say both.  The
    # name is the one that is right -- the reference database files dodge in
    # its Armor/Trinket pool -- so this is what tells the two apart.
    gem_file(
        "GEM_TEST_ARMOR_DODGE",
        "DODGE CHANCE BONUS",
        (VAR_UNITTYPE, "TRINKET"),
        (VAR_UNITTYPE, "WEAPON"),
    )
    # The mirror of it: a weapon affix whose children claim the other host.
    gem_file("GEM_TEST_WEAPON_CRIT", "PERCENT CRITICAL DAMAGE", (VAR_UNITTYPE, "TRINKET"))
    # One effect, two gems, two hosts -- and here the two claims are both from
    # children, so there is nothing to choose between them.  The second is a
    # named one so that a claim made by a name can be told from one made by a
    # child: the fish's attack speed is a trinket bonus and the ember's is a
    # weapon one, and only the second of those affixes says so itself.
    gem_file("GEM_TEST_DEVIL", "PERCENT ATTACK SPEED", (VAR_UNITTYPES, "TRINKET"))
    gem_file("GEM_TEST_WEAPON_HASTE", "PERCENT ATTACK SPEED", (VAR_UNITTYPE, "WEAPON"))
    # Both hosts on the children of one file, and no name to break the tie.
    gem_file(
        "GEM_TEST_UNIQUE",
        "PERCENT LIFE STOLEN",
        (VAR_UNITTYPE, "TRINKET"),
        (VAR_UNITTYPE, "WEAPON"),
    )

    # Item affixes that state the unit types they may be applied to, which is
    # where a *unique* socketable's hosts are read from -- its affixes live in
    # this directory, not under GEMS, and their names say nothing about a host.
    # Each is a file of its own, as in the archive: the root carries the name
    # and the children carry the list and then the effect it grants.
    def hosted_file(stem: str, grants: str, *words: str) -> None:
        files[f"MEDIA/AFFIXES/ITEMS/{stem}.DAT"] = write_dat(
            strings,
            [
                {
                    "vars": {VAR_NAME: (TEXT, string(stem))},
                    "kids": [
                        # The list, as the archive writes it: a child whose
                        # *node id* is the field's own hash -- a DAT list is a
                        # node whose variables repeat, and this is that node.
                        {"id": VAR_UNITTYPES, "vars": {VAR_UNITTYPE: (TEXT, string(w))}}
                        for w in words
                    ]
                    + [{"vars": {VAR_AFFIX_EFFECT: (TEXT, string(grants))}}],
                }
            ],
        )

    # A weapon one, with the unit type the archive puts beside the host.
    hosted_file("UNIQUE_TEST_WEAPON", "SET PROC", "UNIQUE SOCKETABLE", "WEAPON")
    # An armor one: the two words the game uses for the one host.
    hosted_file("UNIQUE_TEST_ARMOR", "SET BURN", "ARMOR", "TRINKET")
    # A unit type and nothing else, which is not a host to name.
    hosted_file("UNIQUE_TEST_STUD", "SET DAMAGE BONUS", "STUD")
    # Two files claiming one effect for two hosts, as the archive's own do.
    hosted_file("UNIQUE_TEST_CLASH_ARMOR", "MELEEDAMAGEBONUS", "TRINKET")
    hosted_file("UNIQUE_TEST_CLASH_WEAPON", "MELEEDAMAGEBONUS", "WEAPON")
    # A single host for an effect a gem already answers for, and one for an
    # effect two gems claim between them.
    hosted_file("UNIQUE_TEST_RUBY", "DAMAGE BONUS", "TRINKET")
    hosted_file("UNIQUE_TEST_STEAL", "PERCENT LIFE STOLEN", "WEAPON")

    # Sets.  The first is shaped like the ones that made the rules: a rung per
    # piece count, one count asked for twice, and a level per rung.  The
    # second exists for the one case the first cannot show -- a rung whose
    # level the curve does not state.
    def rung(count: int, level: int, affix_name: str) -> dict:
        return {
            "id": VAR_AFFIX,
            "vars": {
                VAR_COUNT: (INT, count),
                VAR_AFFIX_LEVEL: (INT, level),
                VAR_AFFIX: (TEXT, string(affix_name)),
            },
        }

    def set_file(set_id: str, shown: str, rungs: list[dict]) -> bytes:
        return write_dat(
            strings,
            [
                {
                    "vars": {
                        VAR_NAME: (TEXT, string(set_id)),
                        VAR_DISPLAY_NAME: (TEXT, string(shown)),
                    },
                    "kids": rungs,
                }
            ],
        )

    files["MEDIA/SETS/TEST_SET.DAT"] = set_file(
        "TEST_SET",
        "Test Set",
        [
            rung(2, 1, "SET AFFIX TWO"),
            rung(2, 1, "SET AFFIX TWO"),
            rung(3, 10, "SET AFFIX THREE"),
        ],
    )
    # A rung whose level the curve does not state, and one whose product is not
    # a whole number.  3 at 145.5% is 4.365, which the game shows as 5 -- the
    # ceiling, where rounding to nearest would give 4.
    files["MEDIA/SETS/TEST_OFF_CURVE.DAT"] = set_file(
        "TEST_OFF_CURVE",
        "Off Curve",
        [rung(2, 5, "SET AFFIX TWO")],
    )
    files["MEDIA/SETS/TEST_ROUND.DAT"] = set_file(
        "TEST_ROUND",
        "Round",
        [rung(2, 10, "SET AFFIX TWO")],
    )

    files["MEDIA/UNITS/ITEMS/SWORDS/DJINN FIRE SWORD.DAT"] = write_dat(
        {0: "Djinn Fire Sword"}, [{"vars": {VAR_NAME: (TEXT, 0)}}]
    )
    # Something the prefixes sweep up that is not a DAT at all.
    files["MEDIA/SKILLS/EMBER/EMBERBEAM.LAYOUT"] = b"<layout/>"
    # And something that is a DAT and will not parse.
    files["MEDIA/UNITS/ITEMS/BROKEN.DAT"] = b"\xff" * 40

    write_synthetic_pak(tmp_path / "PAKS", files)
    return tmp_path


@pytest.fixture
def game(tmp_path):
    # No reference database: the augment table is not game data and the tests
    # here are about the game's, so a machine that happens to have a checkout
    # of the reference beside this one must not change what they see.
    return GameData.load(install(tmp_path), augments={})


# --------------------------------------------------------------------------
# Finding the install
# --------------------------------------------------------------------------


def test_an_install_is_recognised_by_its_manifest(tmp_path):
    root = install(tmp_path)
    assert archive_path(root).is_file()
    assert find_install(explicit=root) == root


def test_the_paks_folder_can_be_named_instead(tmp_path):
    """Whichever of the two someone has to hand."""
    root = install(tmp_path)
    assert archive_path(root / "PAKS").is_file()
    assert find_install(explicit=root / "PAKS") == root / "PAKS"


def test_a_directory_that_is_not_an_install_is_not_returned(tmp_path):
    """No manifest, so it is not an install, however it was typed."""
    (tmp_path / "somewhere").mkdir()
    assert find_install(explicit=tmp_path / "somewhere") is None


def test_the_environment_variable_is_used_when_given(tmp_path, monkeypatch):
    root = install(tmp_path)
    monkeypatch.setenv("TL2_INSTALL", str(root))
    assert find_install() == root


def test_a_bad_environment_variable_does_not_fall_through(tmp_path, monkeypatch):
    """Pointed somewhere wrong on purpose means None, not a different install.

    Falling back to the search would quietly show the player stats from an
    installation they did not ask for -- and if the one it fell back to were
    modded, the numbers would be wrong rather than missing.
    """
    monkeypatch.setenv("TL2_INSTALL", str(tmp_path / "nowhere"))
    assert find_install() is None


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def test_the_wanted_files_are_read_and_the_rest_are_left(game):
    """Forty-one parse; the forty-second is a DAT that will not, and the
    forty-third is not a DAT at all."""
    assert game.files_read == 41
    assert [name for name, _ in game.failed] == ["MEDIA/UNITS/ITEMS/BROKEN.DAT"]


def test_a_file_that_will_not_parse_is_recorded_not_raised(game):
    """One bad file out of twelve thousand is not a reason to refuse to start.

    The items are in the save file and are unaffected either way, so the
    choice is between a tooltip with a line missing and a tool that does not
    open.
    """
    assert game.failed[0][1], "the reason was not kept"


def test_a_layout_file_is_never_offered_to_the_dat_parser(game):
    """It would fail, and calling that a broken data file would be a lie."""
    assert not any("LAYOUT" in name for name, _ in game.failed)


def test_a_manifest_that_is_not_there_raises(tmp_path):
    with pytest.raises(OSError):
        GameData.load(tmp_path / "nothing")


# --------------------------------------------------------------------------
# Looking things up
# --------------------------------------------------------------------------


def test_names_are_found_regardless_of_case(game):
    assert game.by_name("Djinn Fire Sword") is not None
    assert game.by_name("DJINN FIRE SWORD") is not None
    assert game.by_name("djinn fire sword") is not None
    assert game.by_name("Nobody") is None
    assert game.by_name("") is None


def test_an_effect_name_comes_from_the_effect_list(game):
    """Even when something else in the archive has the same name.

    Only EFFECTSLIST carries the description templates, so a node picked up
    from anywhere else would render an effect with no words.
    """
    node = game.by_name("MELEEDAMAGEBONUS")
    assert node is not None
    assert node.text(VAR_GOODDES) == "+[VALUE] Melee weapon damage bonus"


def test_an_effect_name_with_a_space_is_still_found(game):
    """The name is the one in the data, spaces and all.

    What the effect calls its *type* is a different string, and there the
    game puts an underscore in: the effect named ``MAX MANA`` declares itself
    ``KEFFECT_TYPE_MAX_MANA``.  Looking a name up uses the name.
    """
    node = game.by_name("MAX MANA")
    assert node is not None
    assert node.text(VAR_NAME) == "MAX MANA"
    assert node.text(VAR_EFFECT_TYPE) == "KEFFECT_TYPE_MAX MANA"


def test_effects_are_found_by_position_too(game):
    """The order in the file is the game's, and position is the fallback for
    a name that does not resolve."""
    assert game.effect_count == 5
    assert game.effect(0).text(VAR_NAME) == "MELEEDAMAGEBONUS"
    assert game.effect(1).text(VAR_NAME) == "MAX MANA"
    assert game.effect(4).text(VAR_NAME) == "SET BURN"
    assert game.effect(5) is None
    assert game.effect(-1) is None
    assert game.effect(9999) is None


def test_a_description_is_chosen_by_the_type_the_item_asked_for(game):
    """Which of the four an effect uses is decided by the item, not the data."""
    node = game.by_name("MELEEDAMAGEBONUS")

    assert game.effect_template(node, 0x00) == "+[VALUE] Melee weapon damage bonus"
    assert game.effect_template(node, 0x01) == "+[VALUE] Melee weapon damage bonus"
    assert game.effect_template(node, 0x02) == (
        "+[VALUE] Melee weapon damage bonus for [DURATION]"
    )
    assert game.effect_template(node, 0x03) == "-[VALUE] Melee weapon damage penalty"
    assert game.effect_template(node, 0x04) == (
        "-[VALUE] Melee weapon damage penalty for [DURATION]"
    )


def test_a_type_with_no_wording_gives_nothing_rather_than_a_wrong_line(game):
    """An effect with no description for this type shows no line in the game
    either, so the honest answer is to say nothing.

    Falling back to one of the other three would put a penalty on the tooltip
    of an item that has a bonus.
    """
    node = game.by_name("MELEEDAMAGEBONUS")
    assert game.effect_template(node, 0x05) is None
    assert game.effect_template(node, 0xFF) is None

    bare = game.by_name("MAX MANA")
    assert game.effect_template(bare, 0x03) is None, "there is no penalty wording"


# --------------------------------------------------------------------------
# From an affix to the effect it grants
# --------------------------------------------------------------------------


def test_an_affix_names_the_effect_it_grants(game):
    """What the save file calls the effect is an affix.

    ``OFTHEELEPHANT MAX MANA`` is the affix; the wording belongs to ``MAX
    MANA``, and the two are joined by the effect node inside the affix rather
    than by anything in the name.
    """
    assert game.effect_for("OFTHEELEPHANT MAX MANA") is game.by_name("MAX MANA")


def test_an_affix_name_shared_by_several_is_settled_by_the_one_it_ends_with(game):
    """The name alone cannot say which.

    Two affixes are called ``OFFLAME MELEEDAMAGEBONUS`` and grant different
    effects -- in the shipped game 107 share one name -- so a second rule is
    needed.  An affix is named for the item it suits plus the effect it
    grants, so the granted effect is *usually* the one the name ends with.

    Usually, not always: this is the fallback for a record whose index lands
    nowhere, and see
    ``test_an_affix_name_does_not_say_which_effect_it_grants`` for the names
    it gets wrong.
    """
    assert game.effect_for("OFFLAME MELEEDAMAGEBONUS") is game.by_name(
        "MELEEDAMAGEBONUS"
    )


def test_an_effect_named_outright_is_its_own_answer(game):
    """EFFECTSLIST is consulted first, which is why ``MAX MANA`` renders as
    the effect even though an affix below wears the same name."""
    assert game.effect_for("MAX MANA") is game.effect(1)
    assert game.effect_for("MELEEDAMAGEBONUS") is game.effect(0)


def test_an_affix_nothing_settles_gives_nothing(game):
    """Two candidates, neither of them a suffix of the name.

    There is no honest answer, so there is no answer: the caller shows the
    name the save file gave rather than a sentence that might be about
    something else.
    """
    assert game.effect_for("OFNOTHING") is None


def test_a_granted_name_the_game_has_no_effect_for_is_not_a_candidate(game):
    """One affix below grants an effect that is not in EFFECTSLIST.

    Counting it would turn a settled case into an ambiguous one -- and, worse,
    leave a name with no node to return.
    """
    assert game.effect_for("OFGHOST") is game.by_name("MELEEDAMAGEBONUS")


def test_a_name_that_is_nowhere_gives_nothing(game):
    assert game.effect_for("NOTHING AT ALL") is None
    assert game.effect_for("") is None


def test_precision_is_read_and_defaulted(game):
    assert game.display_precision(game.by_name("MELEEDAMAGEBONUS")) == 2

    # An effect that does not say.  All 239 in the shipped game do, so this is
    # the path a mod's effect would take.
    quiet = DatFile.parse(
        write_dat({}, [{"vars": {VAR_NAME: (TEXT, 0)}}])
    ).root
    assert game.display_precision(quiet) == DEFAULT_PRECISION


# --------------------------------------------------------------------------
# Which host a socketable's bonus is granted to
# --------------------------------------------------------------------------
#
# A gem is not one bonus but one per host, and the item's own file names only
# one of the two affixes -- so the host is read off the affixes, and the two
# words that come out are the game's own: WEAPON and TRINKET.


def test_a_gem_affix_that_names_its_host_is_read(game):
    """``GEM_TEST_ARMOR``'s fire defence is a trinket bonus, and says so.

    The commonest shape in the archive, and the one the older gems have: the
    affix's name carries ``_ARMOR`` and its children agree.
    """
    assert game.socket_target("FIRE DEFENSE") == "TRINKET"


def test_an_affix_whose_name_says_nothing_is_asked_through_its_children(game):
    """``GEM_TEST`` carries no marker, so what its children state is the answer.

    That is how every older gem works -- and they spell the field
    ``UNITTYPES``, the plural, which is why both spellings are read.  A file
    carrying no host at all then has no target, which is what ``None`` says.
    """
    assert game.socket_target("DAMAGE BONUS") == "WEAPON"
    assert game.socket_target("NO SUCH EFFECT") is None


def test_the_name_outranks_the_children_that_contradict_it(game):
    """The newer embers' affixes state *both* hosts and belong to one pool.

    ``GEM_TEST_ARMOR_DODGE`` calls itself armor and its children say TRINKET
    and WEAPON; ``GEM_TEST_WEAPON_CRIT`` is the mirror, a weapon affix whose
    children claim the other host.  Measured over the archive, all 69 affixes
    whose name and children disagree are embers, and the reference database
    files every one of them by the name -- dodge in its Armor/Trinket pool,
    critical damage in its weapon pool -- so the name is what is believed.
    """
    assert game.socket_target("DODGE CHANCE BONUS") == "TRINKET"
    assert game.socket_target("PERCENT CRITICAL DAMAGE") == "WEAPON"


def test_a_name_is_believed_over_another_affix_s_children(game):
    """Two gems grant attack speed and only one of them says to which host.

    ``GEM_TEST_DEVIL`` says TRINKET through its children and
    ``GEM_TEST_WEAPON_HASTE`` says WEAPON in its name.  A stated host is a
    better answer than a defaulted one, so the effect is a weapon bonus --
    which is also what the reference says of the chaos ember's attack speed.
    """
    assert game.socket_target("PERCENT ATTACK SPEED") == "WEAPON"


def test_an_effect_two_affixes_claim_equally_has_no_host(game):
    """A unique gem that grants percent life steal in either host.

    Both claims come from children, one per host, so nothing chooses between
    them -- and the honest answer is that the line is true wherever it is
    socketed, which is what not naming a host says.  An effect no gem affix
    grants at all answers the same way, since only a socketable's lines are
    written with a host.
    """
    assert game.socket_target("PERCENT LIFE STOLEN") is None
    assert game.socket_target("MAX MANA") is None
    assert game.socket_target("") is None


def test_a_host_is_found_whatever_case_the_record_names_it_in(game):
    """The save file and the archive do not agree on case."""
    assert game.socket_target("fire defense") == "TRINKET"


# --------------------------------------------------------------------------
# Which host a *unique* socketable's bonus is granted to
# --------------------------------------------------------------------------
#
# A gem's affixes are filed by host in their names.  A unique socketable's are
# not: they live under ``MEDIA/AFFIXES/ITEMS`` among the ordinary ones and wear
# names like ``UNIQUE_DEGRADE_ARMOR2``, which says ``_ARMOR`` and is a weapon
# affix.  What they do carry is the list of unit types they may be applied to,
# which is where the reference database reads the host from.


def test_an_item_affix_s_host_is_read_off_its_applicability_list(game):
    """``UNIQUE_TEST_WEAPON`` states ``WEAPON`` beside the unit type it is for.

    Both of the words in the archive's lists are here: a unit type, which is
    not a place, and the host, which is.
    """
    assert game.socket_target("SET PROC") == "WEAPON"


def test_the_two_words_for_the_one_host_are_read_as_one(game):
    """``ARMOR`` and ``TRINKET`` are one host, as the gems' are.

    An affix stating both -- which is how the archive writes "a ring or a
    breastplate" -- names the one host the card does, so the effect is a
    trinket bonus rather than an ambiguity.
    """
    assert game.socket_target("SET BURN") == "TRINKET"


def test_a_unit_type_in_the_list_is_not_a_host(game):
    """``STUD`` says where the affix may go, not where its bonus is granted.

    Most of what those lists hold is unit types -- ``COLLAR``, ``WAND``,
    ``STUD`` and ``UNIQUE SOCKETABLE`` are the archive's commonest -- so a
    reading that took every entry for a host would name hosts that do not
    exist.
    """
    assert game.socket_target("SET DAMAGE BONUS") is None


def test_two_item_affixes_claiming_one_effect_leave_it_without_a_host(game):
    """The same rule the gems are held to: two claims are not one answer."""
    assert game.socket_target("MELEEDAMAGEBONUS") is None


def test_a_gem_s_answer_outranks_an_item_affix_s(game):
    """``GEM_TEST`` says its damage bonus is a weapon one; this one says not.

    The gem is what the card is showing two halves of, so an item affix is
    heard only where no gem affix speaks -- and 39 of the effects the archive's
    item affixes name are ones no gem affix states at all.
    """
    assert game.socket_target("DAMAGE BONUS") == "WEAPON"


def test_an_item_affix_does_not_break_a_tie_the_gems_left(game):
    """A tie is not a gap: nothing is known about the host, so none is named.

    ``PERCENT LIFE STOLEN`` is granted to both hosts by the gems that carry it,
    and one item affix claiming it for a weapon does not make it a weapon
    bonus -- the effect is granted wherever either thing says, and the line
    would be wrong for the other.
    """
    assert game.socket_target("PERCENT LIFE STOLEN") is None


# --------------------------------------------------------------------------
# A set's ladder
# --------------------------------------------------------------------------


def test_a_ladder_is_gathered_by_piece_count(game):
    """Cheapest rung first, and both names a set answers to.

    An item's ``SET`` field spells the internal name and the card draws the
    display one, so both are indexed -- which is what lets the window and the
    tooltip ask in the spelling each of them happens to hold.
    """
    ladder = game.set_ladder("TEST_SET")
    assert [rung.count for rung in ladder] == [2, 3]
    assert game.set_ladder("test set") == ladder
    assert game.set_ladder("Test Set") == ladder


def test_two_rungs_at_one_count_are_one_rung(game):
    """Tundra asks for 2, 2 and 3, and the player reads one ``(2) Set``.

    What the file spells as two rungs is one to the player, so a count appears
    once in the ladder and the rungs at it are gathered in the file's order.
    """
    counted = {rung.count: rung for rung in game.set_ladder("TEST_SET")}
    assert len(counted[2].bonuses) == 4  # the two effects, twice
    assert [bonus.name for bonus in counted[2].bonuses] == [
        "SET DAMAGE BONUS",
        "SET PROC",
        "SET DAMAGE BONUS",
        "SET PROC",
    ]


def test_a_set_the_archive_has_not_got_has_no_ladder(game):
    """A mod's set is the case: the piece is drawn without a ladder."""
    assert game.set_ladder("NO SUCH SET") == ()
    assert game.set_ladder("") == ()


def test_a_rung_is_scaled_by_the_curve_its_effect_names(game):
    """The number the game shows is the nominal at the rung's affix *level*.

    TEST_CURVE is 200% at level 1 and 145.5% at level 10, and the effect's
    nominal is 3, so the same affix on a rung at each of those levels reads 6
    and 5 -- the level is the rung's own rather than the set's or the item's.
    """
    assert game.set_ladder("TEST_SET")[0].bonuses[0].values[0] == 6.0
    assert game.set_ladder("TEST_ROUND")[0].bonuses[0].values[0] == 5.0


def test_a_scaled_rung_rounds_up(game):
    """3 at 145.5% is 4.365 and the game shows 5.

    Ceiling, not rounding to nearest -- the same direction the game's display
    rounds an effect's value in -- which is what makes it 5 rather than 4.
    """
    rung = game.set_ladder("TEST_ROUND")[0]
    assert rung.bonuses[0].values[0] == 5.0


def test_only_the_value_pair_scales_never_the_parameters(game):
    """DRAW MANA's radius stays 3 however its value scales.

    An effect's numbers are its whole schema -- the low and high ends of the
    value, and then whatever else it needs (a pulse rate, a radius, a count).
    The curve is on the value, so everything past the first two numbers goes
    through as the file wrote it.
    """
    rung = game.set_ladder("TEST_ROUND")[0]
    assert rung.bonuses[0].values == (5.0, 5.0, 7.0)


def test_a_level_the_curve_does_not_state_leaves_the_numbers_alone(game):
    """Every one of the archive's rungs has its level in its curve.

    A mod's rung is the case this is written for: half a curve is not worth
    guessing from, and the nominal the file states is at least the file's own
    number rather than an invented one.  The rung below asks for level 5 and
    TEST_CURVE states 1 and 10.
    """
    rung = game.set_ladder("TEST_OFF_CURVE")[0]
    assert rung.bonuses[0].values[:2] == (3.0, 3.0)


def test_a_rung_s_own_name_is_the_skill_its_wording_can_cast(game):
    """``[NAME]`` is the skill, and on a rung it is the node's own name.

    The effect proper is ``SET PROC``, whose wording casts something; what it
    casts is filed under ``TEST_PROC`` -- the name on the rung's node -- and
    the display name on that node is what the player reads.
    """
    rung = {r.count: r for r in game.set_ladder("TEST_SET")}[2]
    assert rung.bonuses[1].skill == "TEST_PROC"
    assert game.display_name("TEST_PROC") == "Test Proc"
    # An effect node that states no name of its own has no skill to offer.
    assert rung.bonuses[0].skill is None


def test_a_duration_is_read_off_the_rung_as_text(game):
    """A data file writes ``DURATION`` as text, and it decides the wording."""
    rung = {r.count: r for r in game.set_ladder("TEST_SET")}[3]
    assert rung.bonuses[0].duration == 5.0
    # And a rung that states none has none, rather than the last one's.
    assert {r.count: r for r in game.set_ladder("TEST_SET")}[2].bonuses[0].duration == 0.0


def test_a_damage_type_the_file_writes_is_the_number_a_record_carries(game):
    rung = {r.count: r for r in game.set_ladder("TEST_SET")}[3]
    assert rung.bonuses[0].damage_type == 0x02  # FIRE, as a save record has it


# --------------------------------------------------------------------------
# Containers
# --------------------------------------------------------------------------


def test_the_stash_bags_are_named_and_ordered(game):
    assert game.stash_tabs == [24, 26]
    assert game.container_name(24) == "SHARED_STASH_BAG_ARMS"
    assert game.container_name(26) == "SHARED_STASH_BAG_SPELLS"


def test_a_tab_is_reported_as_the_player_counts_it(game):
    """The player sees "the first tab", not "container 24"."""
    assert game.stash_tab(24) == 1
    assert game.stash_tab(26) == 2


def test_the_slot_files_beside_the_containers_are_not_containers(game):
    """They index the same idea in a different space of numbers.

    ``MEDIA/INVENTORY/BAG.DAT`` and ``MEDIA/INVENTORY/CONTAINERS/BODY.DAT``
    both declare 0.  Taking both would have one silently overwrite the other
    and hand out a container name for a number that means something else.
    """
    assert game.container_name(0) is None
    assert "BAG" not in game.containers.values()


def test_a_container_the_data_does_not_name_has_no_name(game):
    assert game.container_name(999) is None
    assert game.stash_tab(999) is None
    assert game.stash_tab(21) is None


def test_a_container_says_where_its_cells_begin(game):
    """The join between a container and the numbers its cells carry.

    A container file names the slot files its cells come from -- one entry in
    its ``SLOTS`` list each, with a count of them -- and a slot file states the
    number its own first cell has.  The container says *which* file and the
    file says *which number*, so the two halves of an inventory's numbering
    are read rather than assumed.
    """
    assert game.slot_base(24) == 3322


def test_a_container_that_names_no_slot_file_has_no_base(game):
    """Which is every container whose cells are not numbered consecutively
    from one place, and the reason a caller has to be able to ask at all."""
    assert game.slot_base(26) is None
    assert game.slot_base(999) is None


def test_a_slot_file_no_container_names_is_not_reachable(game):
    """``MEDIA/INVENTORY/BAG.DAT`` declares 0 the way the containers do.

    It is the answer for a container that names it and for nothing else: the
    match is by name, so a slot file nobody names cannot settle a container's
    numbering, and its 0 cannot leak into a container's answer.
    """
    assert game.slot_base(0) is None


@needs_game
def test_the_shared_stash_tabs_begin_where_the_game_says(real_game):
    """The three tabs' first cells, read off the game's own files.

    Measured against the live registry: every item ever placed in container 24
    sits at 3322 or above, and the three tabs start 1000 apart -- 3322, 4322,
    5322 -- which is what makes the number usable as a slot to put something
    back into an empty tab.
    """
    assert [real_game.slot_base(tab) for tab in real_game.stash_tabs] == [
        3322,
        4322,
        5322,
    ]


# --------------------------------------------------------------------------
# An item's own numbers, worked out against the real data files
#
# These need the game installed, and they are the tests that matter: they ask
# for numbers that were read off the game's own item pages, so agreeing with
# them is evidence rather than self-consistency.
# --------------------------------------------------------------------------


@needs_game
def test_a_weapon_s_damage_is_worked_out_from_its_data_file(real_game):
    """The save file holds one number for a weapon and no split at all.

    ``HAMMER_U03B`` -- Bonebreaker -- stores its physical maximum as 239.  The
    player reads ``Physical 120-239`` and ``Fire 80-159``, and those four
    numbers exist only in the item's data file, as shares of a nominal damage
    that a by-level curve sizes.
    """
    it = item(guid=6933962607845725281)
    derived = real_game.derived_for(it)

    assert derived is not None and derived.kind == "damage"
    assert derived.parts == {"physical": (120, 239), "fire": (80, 159)}


@needs_game
def test_armour_is_worked_out_from_its_data_file(real_game):
    """``COLLAR_UNIQUE_DEGRADE06`` -- a level 45 Chokehold.

    Five parts, and the physical one is 85: ``85.224``, rounded to nearest
    rather than up.  A ceiling would put it at 86, which is what the game does
    *not* print, so this number is also what pins the rounding rule.
    """
    it = item(guid=-7711194175558023803)  # written negative; see below
    derived = real_game.derived_for(it)

    assert derived is not None and derived.kind == "armor"
    assert derived.parts == {
        "physical": (85, 85),
        "fire": (32, 32),
        "ice": (32, 32),
        "electric": (32, 32),
        "poison": (32, 32),
    }


@needs_game
def test_a_guid_written_negative_finds_the_same_file(real_game):
    """Half the archive writes the id as a negative decimal and the save file
    writes the same bytes as a large positive, so both spellings have to
    arrive at one file."""
    signed = -7711194175558023803
    assert real_game.derived_for(item(guid=signed)) is not None
    assert real_game.derived_for(item(guid=signed & 0xFFFFFFFFFFFFFFFF)) is not None


@needs_game
def test_an_item_the_data_files_do_not_know_gives_nothing(real_game):
    """A modded item, or one from a save whose install has moved on.  Nothing
    is the right answer; a plausible-looking guess is not."""
    assert real_game.derived_for(item(guid=0)) is None
    assert real_game.derived_for(item(guid=0xDEADBEEF)) is None


@needs_game
def test_a_skill_is_found_by_the_name_an_affix_shares_with_it(real_game):
    """``WC_PROC_FULLHEAL`` names an affix *and* a skill.

    Only the skill carries the display name, which is what makes looking the
    name up as a display name work where looking it up as a node does not.
    """
    assert real_game.display_name("WC_PROC_FULLHEAL") == "Fully Heal Self"
    assert real_game.display_name("wc_proc_fullheal") == "Fully Heal Self"
    # An affix that grants no skill has no display name to give.
    assert real_game.display_name("OFTHEBEAR DAMAGE BONUS") is None
    assert real_game.display_name("") is None


# --------------------------------------------------------------------------
# What a weapon leads with, against the reference database
#
# The three lines a weapon leads with are the three numbers nothing else in
# the tool has: the save file records a weapon's level and its own damage and
# nothing about the swing.  Every expectation below is a line the reference
# database publishes for the item, reached through the guid the save file
# writes -- so agreeing with them is the game's own data agreeing, in the
# order and the wording the player sees.
# --------------------------------------------------------------------------


@needs_game
def test_a_weapon_leads_with_its_output(real_game):
    """Three weapons with no added damage, so all three lines are the file's.

    Item guid, then what ``out/items.json`` publishes as ``dps``, ``sp`` and
    ``rng``.  The band words are not in that file -- it publishes seconds --
    and come off the game's own tooltips: 0.8 and 0.88 are Fast (0.72 is the
    last Very Fast), 0.56 is Very Fast, and the ranges are the floats the file
    stores, printed by ``%g``.
    """
    expected = {
        8006826267664839987: ("The Emperor's Wrath", "110", "0.8", "Fast", "12"),
        15175802192847760921: ("The Scorpion", "226", "0.88", "Fast", "12"),
        18055960497465174491: ("Bugstomper", "434", "0.56", "Very Fast", "0.5"),
    }
    for guid, (name, dps, seconds, band, reach) in expected.items():
        lead = real_game.weapon_lead(item(guid=guid))
        assert lead == (
            f"{dps} Damage per Second",
            f"{band} attack speed ({seconds} seconds)",
            f"Weapon Range {reach}",
        ), name


@needs_game
def test_the_flat_damage_an_item_carries_is_counted_whole_into_its_output(real_game):
    """Two weapons whose reference dps is not their damage over their swing.

    The Grimbone Wand's own range is 126-142 and 14-16, and 149 over 0.96 is
    155.208 -- which is the tool's ``155``, and not the ``180`` the reference
    publishes.  The 25 between them is the ``+25 Physical Damage`` the wand has
    been given, added to the total rather than folded in before the division.
    Bonebreaker is the same arithmetic with a half in it: its mean 299 over
    1.04 s is 287.5, and 301 is that half rounded *up* (giving 288) plus the
    flat 13.  Both flat numbers are the ones the items carry today, read out of
    the registry the tool keeps.

    Nothing but the save file has either number: the two flat lines are in the
    item's own added-damage records, so they are passed in here the way a
    registry row would carry them.
    """
    from tl2stash.item import AddedDamage

    flat = {
        9801002217302452269: (25.0, 180, "Grimbone Wand"),
        6933962607845725281: (13.0, 301, "Bonebreaker"),
    }
    for guid, (damage, dps, name) in flat.items():
        it = item(guid=guid, added_damages=[AddedDamage(0, word(damage), 0, 0x00)])
        assert real_game.weapon_lead(it)[0] == f"{dps} Damage per Second", name

        # Without it the number is the damage over the swing alone, which is
        # what a weapon nobody has enchanted leads with.
        bare = item(guid=guid)
        assert bare.added_damages == []
        assert int(real_game.weapon_lead(bare)[0].split()[0]) < dps, name


@needs_game
def test_a_swing_that_sits_on_the_ceiling_is_still_a_swing(real_game):
    """The Mace of the Twin Gods, at exactly the slowest speed the game ships.

    Its raw ``SPEED`` is 140 and its class divides by 250 thirds, which is
    1.68 -- the ceiling itself, not past it.  The reference database reaches
    the same two lines only by falling back to a second database, because it
    divides by the decimal 83.3333 instead: 140 over that is 1.6800007, which
    is past the ceiling and takes the whole lead with it.  So this is the item
    that pins the divisors being the fractions they are.

    Its dps is 575 there; 410 of it is the two 230-459 lines over the swing,
    and the other 165 the flat damage it carries.
    """
    from tl2stash.item import AddedDamage

    # Written negative, the way the archive spells this one's id.
    it = item(guid=-621765789189705235, added_damages=[AddedDamage(0, word(165.0), 0, 0x00)])
    assert real_game.weapon_lead(it) == (
        "575 Damage per Second",
        "Very Slow attack speed (1.68 seconds)",
        "Weapon Range 0.8",
    )


@needs_game
def test_a_weapon_with_no_damage_to_hit_for_still_leads_with_its_swing(real_game):
    """Each line stands on its own field, as the reference draws them.

    A greatmace the netherim swing states a speed and a reach and no damage at
    all -- the range is rolled when the creature spawns, and no file holds it
    -- so there is no Damage per Second to lead with and still something to
    say.  The reference publishes the same shape for it: ``sp 1.32`` and
    ``rng 0.8``, and no ``dps`` key at all.  Writing a zero instead would be a
    claim about the weapon rather than the absence of one.
    """
    lead = real_game.weapon_lead(item(guid=792130739766287015))

    assert lead == ("Very Slow attack speed (1.32 seconds)", "Weapon Range 0.8")
    assert not any(line.endswith("Damage per Second") for line in lead)


@needs_game
def test_what_is_not_a_weapon_leads_with_nothing(real_game):
    """The reach is the field that tells the two apart.

    ``RANGE`` is stated on all 1,419 weapons in the archive and on nothing
    else -- no piece of armour, no ring, no potion -- so an item that states
    none has no lead.  The Chokehold is the armour piece the damage tests
    already use, and an unknown guid is an item with no file behind it.
    """
    assert real_game.weapon_lead(item(guid=-7711194175558023803)) == ()
    assert real_game.weapon_lead(item(guid=0)) == ()
    assert real_game.weapon_lead(item(guid=0xDEADBEEF)) == ()


# --------------------------------------------------------------------------
# What an effect record names, settled against the game's own affix files
# --------------------------------------------------------------------------


@needs_game
def test_an_affix_name_does_not_say_which_effect_it_grants(real_game):
    """The fact the whole resolution order rests on.

    An affix node names, under ``TYPE``, the effect it grants.  369 distinct
    affix names between them grant 1,552 effects, and ``OFTHETURTLE ARMOR
    BONUS`` is one name for thirteen of them -- ``ARMOR BONUS``, which it ends
    with, and also ``PERCENT CRITICAL DAMAGE``, ``STRENGTH BONUS`` and ten
    others.

    So reading the effect off the name is not a rule, it is a guess that is
    usually right.  The record's own ``index`` is what settles it, and that is
    why it is consulted first.
    """
    effects, granted = _affix_effects(real_game)

    legal = granted["OFTHETURTLE ARMOR BONUS"]
    assert len(legal) >= 13, "the sweep has stopped finding affixes"
    named = {effects[position] for position in legal}
    assert "ARMOR BONUS" in named, "the name it ends with is one of them"
    assert {"PERCENT CRITICAL DAMAGE", "STRENGTH BONUS", "DEXTERITY BONUS"} <= named

    # And a name whose suffix is a real effect but not the only one.
    flame = {effects[p] for p in granted["OFFLAME DAMAGE BONUS"]}
    assert "DODGE CHANCE BONUS" in flame, "this is what the suffix rule gets wrong"


@needs_game
def test_every_record_index_names_an_effect_its_affix_may_grant(real_game):
    """The measurement that makes the index a fact rather than a preference.

    If ``index`` were a roll number or an affix id -- anything but the effect's
    position in ``EFFECTSLIST`` -- it would land outside the handful of effects
    its own affix name permits almost every time.  Across 400 real effect
    records on the user's items it never once did, including the 104 that carry
    no name at all and so cannot be resolved any other way.

    Bashdrill is the item this was found on, so it is the one pinned here.
    """
    effects, granted = _affix_effects(real_game)
    it = _bashdrill()

    checked = 0
    for record in list(it.effects) + list(it.effects2):
        if not record.name:
            continue
        legal = granted.get(record.name.upper())
        if legal is None:
            continue  # a modded affix the vanilla data has never heard of
        assert record.index in legal, (
            f"{record.name} carries index {record.index} = "
            f"{effects[record.index]!r}, which it may not grant"
        )
        checked += 1

    assert checked >= 7, "the item stopped exercising the rule"


@needs_game
def test_bashdrill_reads_as_the_game_shows_it(real_game):
    """The item the bug was reported on, line for line.

    Every one of these lines was wrong before: the armour bonus, the dodge
    chance and the silence all came out as other effects, because the effect
    was being read off the affix name instead of off the record's index.
    ``OFTHETURTLE ARMOR BONUS`` is called that and grants ``PERCENT ARMOR
    BONUS``; ``OFFLAME DAMAGE BONUS`` -- "of Flame", on a lightning weapon --
    grants ``DODGE CHANCE BONUS``.

    Three of the records carry no name at all, and the damage is not in the
    save file: both come out of the game's data, so this is the whole chain
    from a blob to a tooltip in one assertion.

    The requirement is the sharpest of these and the newest.  The tool used to
    print the level the *save file* records -- 45, which is the level Bashdrill
    is -- and the game withholds it until the character is 51, which is the
    number in ``fist_u04.dat`` and the one tl2db ships for it
    (``out/items.csv``: ``lv 45, lr 51, str_req 81, dex_req 40``).  The two
    attributes come out of the file's own hundredths of a curve: 47% of 170 is
    81 and 23% of 170 is 40 at level 45.
    """
    assert _tooltip(_bashdrill(), real_game) == [
        "Bashdrill",
        # The weapon's own output, which the save file does not hold: the
        # reference database has Bashdrill at 326, 0.48 s and range 0.5, and
        # ``fist_u04.dat`` is where all three come from.
        "326 Damage per Second",
        "Very Fast attack speed (0.48 seconds)",
        "Weapon Range 0.5",
        "Physical Damage 52-74",
        "Electric Damage 77-110",
        "+2% to Physical Armor",
        "+5% Attack Speed",
        "+2% Critical Hit Chance",
        "2% increase in the amount of gold found",
        "+5% to Electric Damage",
        "Charge rate increased by 5%",
        "+1% Dodge chance",
        "5% chance to Shock for 5 sec.",
        "Silence for 1 sec.",
        # The gate at the foot of the card, where the reference draws it and
        # in the reference's words: the word between the two groups is its own
        # line here because on the window it is its own element.
        "Requirements",
        "Player Level 51",
        "or",
        "Strength 81",
        "Dexterity 40",
        # The italic line.  It is not in the reference dump this was checked
        # against, and it was missing here until the flavour text stopped
        # being looked up by the item's *name*: a unique is not named what it
        # is called, so that found nothing for any of them.
        "If your enemies don't get the point, drill it into their heads.",
    ]


@needs_game
def test_a_unique_s_flavour_is_found_through_its_guid_and_not_its_name(real_game):
    """A unique is not *named* what it is called.

    The node behind Wanderlust Pants is ``wanderer_02_pants_alt_set``, so
    searching the archive for the display name finds nothing -- which is how
    every unique lost its flavour line.  The guid in the save file leads to
    the file, and it is the same route the damage and armour take.
    """
    it = _bashdrill()
    assert real_game.by_name(it.base_name) is None, "the name lookup started working"

    assert real_game.flavor_for(it) == (
        "If your enemies don't get the point, drill it into their heads."
    )


@needs_game
def test_an_item_the_archive_does_not_know_has_no_flavour(real_game):
    assert real_game.flavor_for(item(guid=0xDEADBEEF)) is None
    assert real_game.flavor_for(item(guid=0)) is None


# --------------------------------------------------------------------------
# What an item asks of the character who would use it
# --------------------------------------------------------------------------
#
# Two kinds of number in five fields, and getting it backwards is invisible
# from inside the tool.  The level is a level and is taken as the file states
# it; the four attributes are percentages of a curve and are scaled.  The
# synthetic curves in the fixture are small and unlike each other so that a
# field scaled by the wrong curve, or a curve indexed by the wrong level,
# lands somewhere a test can name.


def test_a_level_requirement_is_taken_as_the_file_states_it(game):
    """Not scaled, and the one field that is not.

    The items that state one are the ones authored to sit off the curve, so
    scaling it would move the gate: Bashdrill's stated 51 would come out as 24
    on a level 20 item, and the item would read as usable eleven levels before
    it can drop.
    """
    requires = game.requirements_for(item(guid=0x7004))

    assert requires.level == 99
    assert requires.stats == ()


def test_a_plain_item_reads_the_normal_curve(game):
    """An item with no rarity of its own is gated by a different curve.

    The game gates it on the level it may start dropping at, and that curve is
    shorter than the general one -- the fixture's stops where the game's does,
    at a lower level than the item's.
    """
    requires = game.requirements_for(item(guid=0x7001))

    assert requires.level == 8, "the NORMAL curve's value at level 10"
    assert requires.socketing is False


def test_a_socketable_reads_the_socketing_curve(game):
    """A socketable is not worn, so its gate is about the item that takes it.

    The level it asks for is the *host's*, which is what makes the socketing
    curve a different shape from every other one: it is not about the item's
    own level but about the level of the thing it goes into.
    """
    requires = game.requirements_for(item(guid=0x7003))

    assert requires.level == 12, "the SOCKETABLE curve's value at level 20"
    assert requires.socketing is True


def test_anything_else_reads_the_general_curve(game):
    requires = game.requirements_for(item(guid=0x7002))

    assert requires.level == 24, "the general curve's value at level 20"
    assert requires.socketing is False


def test_a_curve_that_does_not_reach_the_level_falls_through(game):
    """A short curve is not extrapolated, and the fall-through is not a gap.

    The game's Normal curve holds 50 points and the base game's items stop
    there, so a longer Normal curve would be an invention.  Past its end the
    answer comes from the general curve instead, which is the one every other
    item is on.
    """
    requires = game.requirements_for(item(guid=0x7006))

    assert requires.level == 57, "the general curve's value at level 50"


def test_an_attribute_is_a_percentage_of_its_own_curve(game):
    """The half that is easy to get wrong, and the two ways to get it wrong.

    A file stating ``100`` where the player reads ``100`` has not understood
    the field; so has one reading it off a curve belonging to another
    attribute.  At level 10 the strength curve is 50% and the magic curve is
    150%, so one stated pair of hundreds tells the two apart in one assertion.
    """
    requires = game.requirements_for(item(guid=0x7005))

    assert dict(requires.stats) == {"Strength": 50, "Focus": 150}


def test_an_attribute_stated_as_zero_is_no_requirement(game):
    """A zero and an absence are one thing here, and both are not a line.

    The archive writes a plain item's four requirements as zero rather than
    leaving them out, so reading a zero as a requirement would put ``0
    Vitality`` on most of the items in the game.
    """
    requires = game.requirements_for(item(guid=0x7005))

    assert "Vitality" not in dict(requires.stats)
    assert "Dexterity" not in dict(requires.stats)


def test_an_item_the_data_does_not_know_has_no_appearance(game):
    """A guid no file in the install carries: nothing raises and nothing is
    guessed."""
    assert game.appearance_for(item(guid=0xDEAD)) is None


def test_a_set_piece_carries_its_set_s_display_name(game):
    """The field is the set's *file* name; what the card draws is its title.

    ``TEST_SET`` is what the item states and ``Test Set`` is what the card, the
    collection row and the set filter all say -- one string, resolved here, so
    that a click on a name and a filter over names cannot be two different
    spellings of the same set.  The ladder is reachable by either name, which is
    what makes the click a lookup rather than a translation.
    """
    appearance = game.appearance_for(item(guid=0x7007))

    assert appearance.set_name == "Test Set", "the internal id reached the card"
    assert game.set_ladder(appearance.set_name), "the name does not find the set"
    # Everything else about the item is the item's own: membership rides beside
    # the rarity the file states rather than replacing it.
    assert appearance.tier == "Unique"


def test_an_item_of_no_set_says_so_with_nothing(game):
    """``None`` and not the empty string, which is what a mod's item gets too.

    The card draws a set's name only where there is one, and the collection
    stores the empty string for "no set" -- so the two have to be told apart
    somewhere, and this is where.
    """
    assert game.appearance_for(item(guid=0x7001)).set_name is None


def test_an_item_the_data_does_not_know_has_no_requirements(game):
    assert game.requirements_for(item(guid=0xDEADBEEF)) is None
    assert game.requirements_for(item(guid=0)) is None


@needs_game
def test_the_requirement_rule_reproduces_the_reference_database(real_game):
    """The whole of tl2db's own output, row by row.

    ``torchlight2_db`` is the reference this rule was settled against: its
    ``src/build.py`` states it, and its ``out/items.csv`` is that build's
    answer for 6,173 items.  Level requirements agree on *every* row it states
    one for, which is the claim this pins -- the residue is in the attributes
    and is the reference's own, so what this checks is that neither the rule
    nor the tables it reads have drifted.

    The two attribute divergences, both measured over that output:

    * 153 rows where tl2db prints the file's raw magnitude because its own
      source has no row for the unit.  Those units are monsters' and props'
      -- ``mon_axe_goblinchamp``, ``Prop_Shovel``, ``z_test_firesword`` -- and
      the reference's own note says a player never sees them.
    * 10 rows where that source is one below the exact product: 70% of the
      curve at 170 is 119 and it says 118, 50% at 50 is 58 and it says 57.
      Arithmetic, not a rule; the tool does the arithmetic.
    """
    import csv  # noqa: PLC0415 -- only this test reads a csv

    from tl2stash.dat import VAR_UNIT_GUID  # noqa: PLC0415
    from tl2stash.gamedata import _data_path  # noqa: PLC0415

    # Beside this project rather than beside the game: the reference is a
    # checkout a developer has, not something playing the game requires.
    repo = Path(__file__).resolve().parents[2] / "torchlight2_db"
    table = repo / "out" / "items.csv"
    if not table.is_file():
        pytest.skip("the reference database is not checked out beside this one")

    guids = {
        path: int(guid) & 0xFFFFFFFFFFFFFFFF
        for path, data in real_game._item_files.items()
        if (guid := data.root.text(VAR_UNIT_GUID))
    }

    seen = misses = unanswered = 0
    for row in csv.DictReader(table.open(encoding="utf-8-sig")):
        guid = guids.get(_data_path(row["dat_path"]))
        if guid is None or not row["lr"].strip():
            continue
        requires = real_game.requirements_for(item(guid=guid))
        if requires is None:
            # One item in the whole table, and the reason is a missing input
            # rather than a rule: ``staff_n00`` is a base staff whose file
            # inherits no LEVEL at all, so there is no level to index a curve
            # by and the tool declines to guess one.  The reference fills it
            # from its own source instead.
            unanswered += 1
            continue
        seen += 1
        if requires.level != int(row["lr"]):
            misses += 1

    assert seen > 5_000, "the reference table stopped being read"
    assert misses == 0, f"{misses} of {seen} level requirements disagree"
    assert unanswered <= 1, f"{unanswered} items became unanswerable"


# --------------------------------------------------------------------------
# What an item looks like: its rarity, its kind, its icon
# --------------------------------------------------------------------------


def test_the_tier_and_the_kind_are_two_words_in_one_string():
    """The rule, on the spellings the archive actually uses.

    There is no separator between the two, so the first word is a tier only
    when it is a word the game uses for one -- and when it is not, the string
    has no tier at all and is entirely the kind.

    The tier word that comes back is the *displayed* one rather than the file's
    token, because a card is what this feeds: the file's ``MAGIC`` is the blue
    the game calls rare.  See :data:`tl2stash.gamedata.QUALITY_WORDS`.
    """
    assert read_unit_type("UNIQUE 1HSWORD") == ("Unique", "1H Sword")
    assert read_unit_type("MAGIC BOOTS") == ("Rare", "Boots")
    assert read_unit_type("UNIQUE SHOULDER ARMOR") == ("Unique", "Shoulder Armor")
    # An underscore separates them as well as a space does.
    assert read_unit_type("UNIQUE_COLLAR") == ("Unique", "Collar")
    # No tier word, so the whole thing is the kind.
    assert read_unit_type("SWORD") == ("", "Sword")
    assert read_unit_type("POTION") == ("", "Potion")
    assert read_unit_type("FISH") == ("", "Fish")
    assert read_unit_type("") == ("", "")


def test_a_tier_word_run_together_with_its_kind_is_still_read():
    """``UNIQUECANNON`` is one real spelling of the game's, and one only.

    Measured over the archive it is the sole token where the tier and the kind
    are written with nothing between them: it parses to no tier at all when
    only whole words are tried, and the item it belongs to -- The Rabble-Rouser
    -- is a unique.  So the longest tier word the token *starts* with is taken
    and the rest is the kind.

    Splitting on a prefix is the kind of rule that can quietly eat a kind, so
    the second half of this is the guard: the split only happens where the
    token really does start with a tier word.  ``UNIQUEITEM`` is not an
    ``UNITTYPE`` the game writes -- the measured kinds are ``Fist``, ``Boots``,
    ``1H Mace`` and the like, and not one of them begins with a tier word --
    it is here to fail if the rule ever widens to a substring search.
    """
    assert read_unit_type("UNIQUECANNON") == ("Unique", "Cannon")
    assert read_unit_type("UNIQUEITEM") == ("Unique", "Item")
    assert read_unit_type("THEUNIQUECANNON") == ("", "Theuniquecannon")


@needs_game
def test_a_unique_is_read_as_a_unique_with_its_kind_and_its_icon(real_game):
    """Bashdrill: a unique fist weapon, and all of this from its own file.

    The save file carries none of it -- it knows a name, a level and a damage
    number, and that is all.  The item is ``FIST_U04.DAT``, which states only
    its icon and its base file; the tier and the kind come down the chain from
    ``base_fists_unique.dat``, which is the inheritance this reads through.
    """
    appearance = real_game.appearance_for(_bashdrill())

    assert appearance.tier == "Unique"
    assert appearance.type_name == "Fist"
    assert appearance.icon == "icon_weapon_fist14"
    assert appearance.set_name is None
    assert appearance.item_level == 45


@needs_game
def test_an_ember_reads_as_the_socketable_it_is(real_game):
    """``CHAOS EMBER`` is the game's kind for one; the reference's is Socketable.

    The four ember kinds are the game's own spelling and the reference database
    has none of them: it files all 178 ember and gem files under Socketable,
    which is where the rail puts them and what the card's type line says.  An
    ember keeps its name -- ``Chaos Ember`` -- and its kind is the one word.

    Read out of the item's own file, walked from the archive the way
    :func:`_an_item_of_tier` is, so the expectation is the game's.
    """
    guid, stated = _an_ember(real_game)

    appearance = real_game.appearance_for(item(guid=guid))

    assert stated in ("BLOOD EMBER", "CHAOS EMBER", "IRON EMBER", "VOID EMBER")
    assert appearance.type_name == "Socketable"


#: The embers' two pools, as the reference database's socketables page writes
#: them: an ``Armor / Trinket`` column and a ``Weapon`` column, each bonus by
#: the name the archive's own affix carries for it.  Nothing else in the world
#: states the pairing -- the game's files disagree with *themselves* about it,
#: 69 of the 177 gem affixes naming both hosts on their children and one of
#: them naming the ember rather than a host -- which is why the reference is
#: what this is measured against.  Its pools are also what makes the two words
#: the card writes, ``Armor/Trinket`` and ``Weapon``, the right two.
_EMBER_POOLS = {
    "TRINKET": (
        "POTION EFFICIENCY",
        "DODGE CHANCE BONUS",
        "MISSILE REFLECT",
        "PERCENT ARMOR BONUS",
        "PERCENT DAMAGE TAKEN",
        "PERCENT KNOCK BACK RESISTANCE",
        "PERCENT PET ARMOR",
        "PERCENT PET DAMAGE",
        "PERCENT SPEED",
        "MAX HP",
        "HP RECHARGE PLAYER",
        "DAMAGE REFLECTION",
        "MELEEDAMAGEBONUS",
        "RANGEDDAMAGEBONUS",
        "MAX MANA",
        "MANA RECHARGE PLAYER",
    ),
    "WEAPON": (
        "PERCENT ATTACK SPEED",
        "PERCENT CAST SPEED",
        "CRITICAL CHANCE",
        "PERCENT CRITICAL DAMAGE",
        "DUAL WIELDING BONUS",
        "PERCENT DUAL WIELDING ATTACK",
        "KNOCK BACK",
        "MISSILE RANGE BONUS",
        "SILENCE",
        "DAMAGE BONUS SECONDARY",
        "DEGRADE ARMOR",
        "DAMAGE BONUS",
        "LIFE STEAL",
        "MANA STEAL",
        "DAMAGE",
    ),
}


@needs_game
def test_the_embers_effects_land_in_the_pool_the_reference_files_them_in(real_game):
    """All four shards and the flame ember, effect by effect.

    The two pools are the point of the whole reading: a Chaos Ember is ``+8%
    Potion effectiveness`` in a ring and ``+?`` either way in a weapon, and
    which of the two a line is could not be read off the item's own file.  The
    effects come out of the archive's affixes, so a name the archive does not
    know would read as ``None`` here and fail rather than pass quietly.
    """
    for host, effects in _EMBER_POOLS.items():
        for effect in effects:
            assert real_game.socket_target(effect) == host, effect


@needs_game
def test_an_effect_both_hosts_get_is_not_given_one_of_them(real_game):
    """A unique gem's percent life steal is granted in a weapon *and* in a ring.

    Its affix states both hosts, and no other affix states either, so there is
    nothing to choose between them -- and naming one would be a fabrication
    the player could act on.  Measured over the archive: it is the only effect
    left without a host, every other one being claimed by a single pool.
    """
    assert real_game.socket_target("PERCENT LIFE STOLEN") is None


#: The two halves of a unique socketable, in the archive's own words: the
#: effects ``Vyrax's Heartfire``'s two affixes grant.  A gem's halves are filed
#: by host in their file names and a unique socketable's are not -- its affixes
#: are ``UNIQUE_PROCKILL_...`` and ``UNIQUE_...`` files under
#: ``MEDIA/AFFIXES/ITEMS`` -- so before the applicability list was read these
#: four lines of the user's own two socketables came out with no host at all.
_UNIQUE_SOCKETABLE_HALVES = {
    "TRINKET": "CAST SKILL ON STRUCK",
    "WEAPON": "CAST SKILL ON KILL AT TARGET",
}


@needs_game
def test_a_unique_socketable_s_two_halves_are_named_like_a_gem_s(real_game):
    """``Vyrax's Heartfire``: a chance to cast a spell when struck, and on kill.

    One of the two the user's own stash holds, and the case the request was
    made about: the embers were tagged and these were not.
    """
    for host, effect in _UNIQUE_SOCKETABLE_HALVES.items():
        assert real_game.socket_target(effect) == host, effect


@needs_game
def test_every_socketable_in_the_archive_has_both_of_its_halves_named(real_game):
    """Every socketable the game ships, affix by affix, out of its own files.

    The reading is the reference database's: an affix's applicability list says
    which hosts it is for, and every effect it grants is granted to them.  Six
    effects are left unnamed, and they are the ones the archive grants to both
    hosts *under one name* -- ``PERCENT DAMAGE BONUS`` is a weapon affix's and
    an armor affix's alike -- so no one word is true of it; they are pinned
    here rather than tolerated, because a seventh would mean a socketable whose
    card is missing a word it should have.

    The count is a floor and not the point: it is 105 unique socketables and 13
    plain ones out of the archive's 118, and each of them is a card.
    """
    #: The effects two affixes claim for one host each, which is what the last
    #: of the reading can do: the save file names the *effect*, so the two
    #: halves of one of these are the same word on the card.
    both_hosts = {
        "PERCENT DAMAGE BONUS",
        "PERCENT CHARGING BONUS",
        "FUMBLE CHANCE REDUCTION",
        "PERCENT MAGICAL DROP",
        "XP GAIN BONUS",
        "PERCENT GOLD DROP",
    }

    walked = 0
    unnamed: set[str] = set()
    for filed in real_game._item_files.values():
        if "SOCKETABLE" not in (filed.root.text(VAR_UNITTYPE) or "").upper():
            continue
        walked += 1
        for child in filed.root.children:
            for affix in child.texts(VAR_AFFIX):
                root = real_game.by_name(affix)
                assert root is not None, f"the archive has no affix {affix}"
                for granted in root.children:
                    effect = granted.text(VAR_AFFIX_EFFECT)
                    if effect and real_game.socket_target(effect) is None:
                        unnamed.add(effect.upper())

    assert walked > 100, "the socketables stopped being read"
    assert unnamed == both_hosts


@needs_game
def test_a_set_piece_is_shown_as_the_rarity_its_own_file_states(real_game):
    """The file calls a set piece magic or unique, and that is what is shown.

    Both spellings are real: four items in the archive belong to a set and
    state ``MAGIC`` themselves, and the rest inherit ``UNIQUE`` from a base
    file.  Membership is not a rarity and is carried separately, in
    ``set_name``, which is what lets the card say ``Unique Set Boots`` -- the
    tier says the one thing and the name the other.

    Read out of the game's own files rather than through the code under test:
    the item's file is found by its guid and the set's name is in the set's
    own file under ``DISPLAYNAME``, so the expectation cannot come from the
    tool.  The chain walk in :func:`_a_set_item` is not itself under test --
    that items inherit their tier is pinned by Bashdrill, which states neither
    a tier nor an icon and has both.
    """
    for wanted, shown_as in (("MAGIC", "Rare"), ("UNIQUE", "Unique")):
        guid, unit_type, set_id, shown = _a_set_item(real_game, wanted)

        assert unit_type.startswith(wanted), "the item's own tier word changed"
        assert set_id != shown, "the internal id is what is shown"

        appearance = real_game.appearance_for(item(guid=guid))
        assert appearance.tier == shown_as, (
            f"a {wanted} set piece should read as {shown_as}"
        )
        assert appearance.set_name == shown


@needs_game
def test_a_real_set_s_ladder_is_the_one_its_own_file_states(real_game):
    """Every set in the archive reads as a ladder, counted from the file.

    The expectation is gathered here rather than through the code under test:
    each set file is parsed again and its rungs counted by their ``COUNT``
    field, so what is compared is the game's own numbers against the tool's.
    Two rungs at one count are *one* rung to the player -- three of the
    archive's sets list one twice -- so the file's counts are deduplicated
    before the comparison, which is the only thing the tool does to them.

    Swept over all of them rather than one, because the failure this is here
    for is silent: a rung whose affix the tool cannot find contributes no
    bonuses and leaves the ladder one rung short, and no single set would
    show it.
    """
    from tl2stash.pak import PakFile, PakIndex

    man = archive_path(real_game.install)
    index = PakIndex.read(man)
    swept = 0
    with PakFile(man.with_name("DATA.PAK"), index) as archive:
        for entry in index.entries:
            if not entry.startswith("MEDIA/SETS/") or not entry.endswith(".DAT"):
                continue
            root = DatFile.parse(archive.read(entry)).root
            name = root.text(VAR_NAME)
            counts = {
                int(child.number(VAR_COUNT) or 0)
                for child in root.children
                if child.text(VAR_AFFIX)
            }
            assert counts, f"{entry} has no rungs at all"

            ladder = real_game.set_ladder(name)
            assert [rung.count for rung in ladder] == sorted(counts), entry
            assert all(bonus.name for rung in ladder for bonus in rung.bonuses), entry
            swept += 1

    assert swept > 80, "the sweep stopped finding set files"


@needs_game
def test_a_real_set_piece_carries_its_set_s_display_name_and_ladder(real_game):
    """The whole chain for one item: its ``SET`` field to the set's file, and
    that file to the bonuses the player reads as ``(2) Set``.

    :func:`_a_set_item` hands back the display name read straight from the set
    file, so the name is the game's own string; the ladder is the tool's, and
    every rung of it has to render as something with a word in it.
    """
    guid, _, set_id, shown = _a_set_item(real_game, "UNIQUE")

    assert real_game.display_name(set_id) == shown
    ladder = real_game.set_ladder(set_id)
    assert ladder, f"{set_id} has no ladder"
    assert ladder[0].count >= 2, "a rung is never one piece"
    for rung in ladder:
        for bonus in rung.bonuses:
            text = real_game.effect_template(
                real_game.by_name(bonus.name), 0x00
            )
            assert text, f"{bonus.name} has no wording"


@needs_game
def test_no_item_file_anywhere_calls_itself_a_set(real_game):
    """Why membership is a separate field and not a tier word.

    If some ``UNITTYPE`` read ``SET`` there would be a token to parse and the
    tier could carry membership by itself -- and an item could then be one and
    not the other.  There is none, so a set piece keeps the rarity of the file
    it displaced and membership rides beside it in ``set_name``, which is
    exactly the split ``tl2stash.card.TIER_KEYS`` documents.
    """
    from tl2stash.pak import PakFile, PakIndex

    man = archive_path(real_game.install)
    index = PakIndex.read(man)
    wanted = 0
    with PakFile(man.with_name("DATA.PAK"), index) as archive:
        for entry in index.entries:
            if not entry.startswith("MEDIA/UNITS/ITEMS/") or not entry.endswith(".DAT"):
                continue
            try:
                root = DatFile.parse(archive.read(entry)).root
            except Exception:  # a file that will not parse states nothing
                continue
            for node in root.walk():
                unit_type = node.text(VAR_UNITTYPE)
                if unit_type:
                    assert not unit_type.upper().startswith("SET"), entry
                    wanted += 1

    assert wanted > 1000, "the sweep stopped finding items with a unit type"


@needs_game
def test_an_item_the_archive_does_not_know_has_no_appearance(real_game):
    """A modded item's data is in the mod, not in ``DATA.PAK``.

    Nothing raises and nothing is guessed: the caller draws the item without
    a tier, a kind or an icon, and every stat line it does have still renders.
    """
    assert real_game.appearance_for(item(guid=0xDEADBEEF)) is None
    assert real_game.appearance_for(item(guid=0)) is None


def _an_item_of_tier(game, tier_word: str) -> tuple[int, str]:
    """``(guid, kind)`` for a real item file stating ``tier_word``.

    Walked out of the archive directly, like :func:`_a_set_item`, so the
    expectation cannot come from the tool.  Set pieces are skipped: a white
    item that belongs to a set would not be a plain one, and membership is
    :func:`_a_set_item`'s subject.

    The kind comes from :func:`read_unit_type` because it is not what this is
    for -- a caller that wants to check the parse has its own tests above.
    """
    from tl2stash.pak import PakFile, PakIndex

    man = archive_path(game.install)
    index = PakIndex.read(man)
    with PakFile(man.with_name("DATA.PAK"), index) as archive:
        for entry in index.entries:
            if not entry.startswith("MEDIA/UNITS/ITEMS/") or not entry.endswith(".DAT"):
                continue
            stated = game._item_files.get(entry.upper())
            if stated is None or stated.root.text(VAR_SET):
                continue
            guid = _inherited_text(game, stated.root, VAR_UNIT_GUID)
            unit_type = _inherited_text(game, stated.root, VAR_UNITTYPE)
            if not (guid and unit_type and unit_type.startswith(tier_word)):
                continue
            return int(guid) & 0xFFFFFFFFFFFFFFFF, read_unit_type(unit_type)[1]

    raise AssertionError(f"the archive has no {tier_word} item any more")


def _an_ember(game) -> tuple[int, str]:
    """``(guid, UNITTYPE)`` for a real ember, walked out of the archive.

    The kind is read with :func:`read_unit_type` because matching the raw token
    is the point -- what the tool *shows* is what the test asserts, and taking
    the expectation from the tool would make it no test at all.
    """
    from tl2stash.pak import PakIndex

    embers = ("BLOOD EMBER", "CHAOS EMBER", "IRON EMBER", "VOID EMBER")
    for entry in PakIndex.read(archive_path(game.install)).entries:
        if not entry.startswith("MEDIA/UNITS/ITEMS/") or not entry.endswith(".DAT"):
            continue
        stated = game._item_files.get(entry.upper())
        if stated is None:
            continue
        unit_type = _inherited_text(game, stated.root, VAR_UNITTYPE)
        guid = _inherited_text(game, stated.root, VAR_UNIT_GUID)
        if not (guid and unit_type):
            continue
        if read_unit_type(unit_type)[1].upper() in embers:
            return int(guid) & 0xFFFFFFFFFFFFFFFF, unit_type

    raise AssertionError("the archive has no ember any more")


def _a_socketable_with_a_gate(game) -> tuple[int, str]:
    """``(guid, UNITTYPE)`` for a real socketable that states a level.

    A socketable's gate is the one requirement that is about a *different*
    item -- the level of the host it may be put into -- so it is the one the
    wording has to get right, and an item with no level anywhere up its chain
    has no gate to read at all.  Both of those are real cases: the archive's
    plain ``SOCKETABLE`` files state no level (a gem goes in whatever you are
    wearing), while the embers' rank files do, one rank every fourteen levels.

    Walked out of the archive directly, like :func:`_an_ember`, so which item
    this is cannot come from the tool.  The kind is put through
    :func:`~tl2stash.taxonomy.canonical_kind` because that is what makes an
    ember a socketable -- the archive spells the four of them its own way.
    """
    from tl2stash.gamedata import _number, _text
    from tl2stash.pak import PakIndex
    from tl2stash.taxonomy import canonical_kind

    for entry in PakIndex.read(archive_path(game.install)).entries:
        if not entry.startswith("MEDIA/UNITS/ITEMS/") or not entry.endswith(".DAT"):
            continue
        stated = game._item_files.get(entry.upper())
        if stated is None:
            continue
        inherited = game._inherited(stated)
        guid = _text(inherited, VAR_UNIT_GUID)
        unit_type = _text(inherited, VAR_UNITTYPE)
        if not (guid and unit_type and _number(inherited, VAR_LEVEL)):
            continue
        if canonical_kind(read_unit_type(unit_type)[1]) == "Socketable":
            return int(guid) & 0xFFFFFFFFFFFFFFFF, unit_type

    raise AssertionError("the archive has no socketable with a level any more")


def _a_set_item(game, tier_word: str) -> tuple[int, str, str, str]:
    """``(guid, UNITTYPE, SET id, the set's display name)`` for a real one.

    ``tier_word`` picks which spelling of set piece to return.  Walked out of
    the archive directly, the way :func:`_affix_effects` is: what is being
    pinned is that the *game's* files say one thing and the tool reads it, so
    the expectation cannot come from the tool.
    """
    from tl2stash.pak import PakFile, PakIndex

    man = archive_path(game.install)
    index = PakIndex.read(man)
    with PakFile(man.with_name("DATA.PAK"), index) as archive:
        # Keyed by the set's own NAME rather than by its filename: an item's
        # SET field holds the former, and one of the 88 disagrees with the
        # latter -- ``TL2_STURMBEORN.DAT`` holds ``STURMBEORN``.
        shown_for: dict[str, str] = {}
        for entry in index.entries:
            if not entry.startswith("MEDIA/SETS/") or not entry.endswith(".DAT"):
                continue
            node = DatFile.parse(archive.read(entry)).root
            name = node.text(VAR_NAME)
            shown = node.text(VAR_DISPLAY_NAME)
            if name and shown:
                shown_for[name.upper()] = shown

        for entry in index.entries:
            if not entry.startswith("MEDIA/UNITS/ITEMS/") or not entry.endswith(".DAT"):
                continue
            stated = game._item_files.get(entry.upper())
            if stated is None:
                continue
            set_id = stated.root.text(VAR_SET)
            guid = _inherited_text(game, stated.root, VAR_UNIT_GUID)
            unit_type = _inherited_text(game, stated.root, VAR_UNITTYPE)
            if not (set_id and unit_type and guid):
                continue
            if not unit_type.startswith(tier_word):
                continue
            shown = shown_for.get(set_id.upper())
            assert shown, f"{set_id} is in no set file's NAME"
            return int(guid) & 0xFFFFFFFFFFFFFFFF, unit_type, set_id, shown

    raise AssertionError(f"no {tier_word}-tier set piece carries all three fields now")


def _inherited_text(game, node, var_id: int) -> str | None:
    """A field's value from the node or the nearest file up the base chain.

    The chain walk is not what this test is about -- it is pinned by Bashdrill,
    which states neither a tier nor an icon and resolves both.
    """
    from tl2stash.dat import VAR_BASEFILE
    from tl2stash.gamedata import _data_path

    for _ in range(16):  # every real chain is well under this
        stated = node.text(var_id)
        if stated:
            return stated
        above = node.text(VAR_BASEFILE)
        if not above:
            return None
        node = game._item_files[_data_path(above)].root
    raise AssertionError("the base chain is longer than any real one")


def _affix_effects(game) -> tuple[list[str], dict[str, set[int]]]:
    """``(EFFECTSLIST names in order, affix name -> the positions it may grant)``.

    Read out of the game's own files rather than from the code under test:
    every affix node carries the name of the effect it grants, and an effect
    name is a position in ``EFFECTSLIST``, so the two can be joined without
    asking ``GameData`` anything.
    """
    from tl2stash.gamedata import archive_path
    from tl2stash.pak import PakFile, PakIndex

    man = archive_path(game.install)
    index = PakIndex.read(man)
    with PakFile(man.with_name("DATA.PAK"), index) as archive:
        listed = DatFile.parse(archive.read("MEDIA/EFFECTSLIST.DAT"))
        effects = [node.text(VAR_NAME) for node in listed.root.children]
        position = {name.upper(): i for i, name in enumerate(effects)}

        granted: dict[str, set[int]] = {}
        for entry in index.entries:
            if not entry.startswith("MEDIA/AFFIXES/ITEMS/") or not entry.endswith(".DAT"):
                continue
            try:
                affixes = DatFile.parse(archive.read(entry))
            except Exception:  # a file that will not parse is not this test's business
                continue
            for node in affixes.root.walk():
                name = node.text(VAR_NAME)
                grants = node.text(VAR_AFFIX_EFFECT)
                if name and grants and grants.upper() in position:
                    granted.setdefault(name.upper(), set()).add(position[grants.upper()])

    return effects, granted


#: Bashdrill, as the save file holds it -- the item the stats bug was reported
#: on.  A real blob rather than a built one, because what is being pinned is
#: how *real* records are read: which of them carry a name, which carry none,
#: and what their indices are.
_BASH_DRILL = (
    "ALPWaN4JcEQkCQBCAGEAcwBoAGQAcgBpAGwAbAAAAAAAOjAYz2YfDvQ6MBjPZh8O9M0rst8gPFRd"
    "AAAAAAD///////////////////////////////8AAAAAAAAAAAsNGAAAAQEBAQABAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAACAPwAAAAAAAAAAAAAAAAAAAAAAAIA/AAAAAAAAAAAAAAAAAAAAAAAA"
    "gD8AAAAAAAAAAAAAAAAAAAAAAACAPy0AAAABAAAAAQAAAAAAAAAAAAAASAAAAP////8BAAAA////"
    "////////////AQAAAAAAAAAAAAQAAAAHAAAAQYAAABcATwBGAFQASABFAFQAVQBSAFQATABFACAA"
    "QQBSAE0ATwBSACAAQgBPAE4AVQBTAAIAAABAAAAAQAAAFwAAAAAAAAAAAAAALQAAAAAAesQAAAAA"
    "AAAAQAMAAABBgAAAHwBPAEYAVABIAEUAVABJAEcARQBSACAAUABFAFIAQwBFAE4AVAAgAEEAVABU"
    "AEEAQwBLACAAUwBQAEUARQBEAAIAAKBAAACgQAAAFgAAAAAAAAAAAAAALQAAAAAAesQAAAAAAACg"
    "QAMAAABBgAAAGwBPAEYAVABIAEUATQBBAFMAVABFAFIAIABDAFIASQBUAEkAQwBBAEwAIABDAEgA"
    "QQBOAEMARQACAAAAQAAAAEAAADcAAAAAAAAAAAAAAC0AAAAAAHrEAAAAAAAAAEADAAAAQYAAABwA"
    "TwBGAFQASABFAE0ASQBTAEUAUgAgAFAARQBSAEMARQBOAFQAIABHAE8ATABEACAARABSAE8AUAAC"
    "AAAAQAAAAEAAABwAAAAAAAAAAAAAAC0AAAAAAHrEAAAAAAAAAEADAAAAQYAAABgATwBGAEwASQBH"
    "AEgAVABOAEkATgBHACAARABBAE0AQQBHAEUAIABCAE8ATgBVAFMAAgAAoEAAAKBAAAAZAAAABAAA"
    "AAAAAAAtAAAAAAB6xAAAAAAAAKBAAwAAAEGAAAAAAAIAAKBAAACgQAAArgAAAAYAAAAAAAAALQAA"
    "AAAAesQAAAAAAACgQAMAAABBgAAAFABPAEYARgBMAEEATQBFACAARABBAE0AQQBHAEUAIABCAE8A"
    "TgBVAFMAAgAAgD8AAIA/AACyAAAABgAAAAAAAAAtAAAAAAB6xAAAAAAAAIA/AwAAAAAAAAACAAAA"
    "QaAAABsATwBGAFQASABFAE0AQQBTAFQARQBSACAAQwBSAEkAVABJAEMAQQBMACAAQwBIAEEATgBD"
    "AEUA1xEqlEfdU18CAACgQAAAoEAAAG0AAAAAAAAAAgAAAC0AAAAAAKBAAAAAAAAAoEAAAAAAQaAC"
    "AAAA3hFRqcbjD5kCAADIQgAAyEIAAIAAAAAAAAAAAgAAAC0AAAAAAIA/AAAAAAAAyEIAAAAADkUA"
    "RgBGAEUAQwBUAF8AU0BJAEwARQBOAEMARQAAAAAAAAAAAA=="
)


def _bashdrill():
    import base64

    from tl2stash.item import parse_item

    return parse_item(base64.b64decode(_BASH_DRILL))


def _tooltip(it, game) -> list[str]:
    from tl2stash.tooltip import render

    return render(it, game)
