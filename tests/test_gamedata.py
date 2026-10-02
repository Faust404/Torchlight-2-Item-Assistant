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
    VAR_MAXDAMAGE,
    VAR_MINDAMAGE,
    VAR_NAME,
    VAR_SET,
    VAR_SLOT_BASE,
    VAR_UNITTYPE,
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
from test_tooltip import item  # noqa: E402


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

    # Containers: each names itself and declares the id the save file records.
    for name, cid in (("ARMS", 24), ("SPELLS", 26)):
        files[f"MEDIA/INVENTORY/CONTAINERS/SHARED_STASH_BAG_{name}.DAT"] = write_dat(
            {0: f"SHARED_STASH_BAG_{name}"},
            [{"vars": {VAR_NAME: (TEXT, 0), VAR_SLOT_BASE: (2, cid)}}],
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
    return GameData.load(install(tmp_path))


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
    """Eleven parse; the twelfth is a DAT that will not, and the thirteenth is
    not a DAT at all."""
    assert game.files_read == 11
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
    """
    assert _tooltip(_bashdrill(), real_game) == [
        "Bashdrill",
        "Requires Level 45",
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
