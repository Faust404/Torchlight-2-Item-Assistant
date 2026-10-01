"""Tests for the tooltip renderer.

The number formatter is tested on its own, because it is quirky in a way that
is invisible when it is wrong: it rounds up and then cuts the decimal string,
so ``0.30000000000000004`` at one decimal is ``0.4``.  A table of cases is the
only way that stays put.

The rest splits in two.  Items are built by hand and rendered against the
*real* game data, skipped when the game is not installed -- which is the test
that matters, because it puts a real affix name through the real template and
checks the sentence that comes out.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash.gamedata import GameData, find_install  # noqa: E402
from tl2stash.item import Effect, Item, Location  # noqa: E402
from tl2stash.tooltip import PERMANENT, _substitute, format_value, render  # noqa: E402

_INSTALL = find_install()

needs_game = pytest.mark.skipif(
    _INSTALL is None, reason="Torchlight II is not installed on this machine"
)


@pytest.fixture(scope="module")
def game():
    return GameData.load(_INSTALL)


def word(value: float) -> int:
    """A float as the item blob stores it."""
    return struct.unpack("<I", struct.pack("<f", value))[0]


def effect(
    name: str,
    *,
    value: float = 0.0,
    values: tuple[float, ...] = (),
    description_type: int = 0,
    damage_type: int = 0,
    duration: float = PERMANENT,
) -> Effect:
    return Effect(
        type=0x8041,
        name=name,
        file=None,
        guid=None,
        num_values=len(values),
        values=[word(v) for v in values],
        index=0,
        damage_type=damage_type,
        description_type=description_type,
        item_level=0,
        duration=word(duration),
        value=word(value),
        link=0,
        extra_string=None,
    )


def item(name: str = "Test Item", **kwargs) -> Item:
    fields = dict(
        raw=b"",
        location_offset=0,
        guid=0,
        name=name,
        prefix="",
        suffix="",
        random_id=b"",
        extra_records=b"",
        num_enchants=0,
        location=Location(slot_index=0, container=24),
        identified=1,
        level=0,
        quantity=1,
        num_sockets=0,
    )
    fields.update(kwargs)
    return Item(**fields)


# --------------------------------------------------------------------------
# The number formatter
# --------------------------------------------------------------------------


def test_values_round_up_not_to_nearest():
    """The game's rounding is a ceiling, so a fraction always carries.

    23.04 armour is 24, and a quarter of a point of anything is 1.  Rounding
    to nearest would agree on the first of these and quietly differ on the
    second.
    """
    assert format_value(23.04, 0) == "24"
    assert format_value(81.6, 0) == "82"
    assert format_value(0.4, 0) == "1"
    assert format_value(1.4175, 0) == "2"


def test_a_whole_number_is_shown_without_decimals_at_zero_precision():
    assert format_value(15.0, 0) == "15"
    assert format_value(100.0, 0) == "100"
    assert format_value(-10.0, 0) == "-10"


def test_the_ceiling_applies_to_negative_numbers_towards_positive_infinity():
    """Which is what a ceiling does, and is not what "round away from zero"
    would give: -1.5 is -1."""
    assert format_value(-1.5, 0) == "-1"
    assert format_value(-1.55, 1) == "-1.5"


def test_ceilings_after_scaling_so_float_noise_can_push_a_value_up():
    """The quirk this whole function exists for.

    0.1 + 0.2 is a hair over 0.3, and the game shows 0.4 because it rounds
    that hair up at one decimal and then cuts the string.  Rounding to nearest
    would give 0.3 and look entirely reasonable.
    """
    assert format_value(0.1 + 0.2, 1) == "0.4"


def test_decimals_are_cut_to_length_and_not_padded():
    """A trailing zero is kept, a missing digit is not invented.

    2.0 at one decimal is '2.0' -- the game keeps what the string gave it --
    while 1.0 at three decimals is only '1.0', because there was nothing left
    to cut.
    """
    assert format_value(2.0, 1) == "2.0"
    assert format_value(100.0, 1) == "100.0"
    assert format_value(1.0, 2) == "1.0"
    assert format_value(1.0, 3) == "1.0"


def test_a_precision_of_two_keeps_two_digits():
    assert format_value(1.42, 2) == "1.42"
    assert format_value(1.005, 2) == "1.01"
    assert format_value(0.125, 2) == "0.13"


# --------------------------------------------------------------------------
# Filling in a description
# --------------------------------------------------------------------------


def test_each_hole_gets_the_value_it_names():
    """One template, every tag, so the mapping is readable in one place.

    Note ``[VALUE1ASDURATION]`` here is '1.0 seconds': the singular is decided
    by the *written* text being exactly '1', which one decimal never is.
    """
    eff = effect(
        "ANY",
        value=10.0,
        values=(1.0, 2.0, 3.0, 4.0, 5.0),
        damage_type=0x02,
        duration=5.0,
    )
    got = _substitute(
        "[VALUE]|[VALUE1]|[VALUE2]|[VALUE3]|[VALUE4]|[VALUE5]|"
        "[VALUE3AND4]|[DURATION]|[DMGTYPE]|[NAME]|[VALUE1ASDURATION]",
        eff,
        precision=1,
        name="Fireball III",
        value=10.0,
    )
    assert got == (
        "10.0|1.0|2.0|3.0|4.0|5.0|3.0|5.0 seconds|Fire|Fireball III|1.0 seconds"
    )


def test_value_over_time_is_the_value_times_the_duration():
    """The game stores the rate and writes the product, not the product."""
    eff = effect("ANY", value=3.0, duration=4.0)
    assert _substitute("[VALUE_OT]", eff, 0, None, 3.0) == "12"


def test_a_duration_of_one_is_singular():
    eff = effect("ANY", duration=1.0)
    assert _substitute("[DURATION]", eff, 0, None, 0.0) == "1 second"
    assert _substitute("[DURATION]", eff, 1, None, 0.0) == "1.0 seconds"


def test_a_tag_this_does_not_know_is_left_standing():
    """Four hundred descriptions were read to build the tag list, and a fifth
    hundredth tag would be a wording nobody has seen.  Leaving it visible says
    so; replacing it with a guess would not."""
    eff = effect("ANY", value=1.0)
    assert _substitute("[NONSENSE] and [VALUE]", eff, 0, None, 1.0) == (
        "[NONSENSE] and 1"
    )


def test_a_value_the_record_does_not_carry_is_marked_not_invented():
    """A template can ask for more values than the effect has."""
    eff = effect("ANY", values=(1.0,))
    assert _substitute("[VALUE1]|[VALUE4]", eff, 0, None, 0.0) == "1|?"


def test_a_description_with_no_holes_comes_back_whole():
    """79 of the 808 have nothing to fill in.  They are not broken."""
    eff = effect("ANY")
    assert _substitute("Identify Item", eff, 1, None, 0.0) == "Identify Item"


# --------------------------------------------------------------------------
# Whole items, rendered against the real game data
# --------------------------------------------------------------------------


@needs_game
def test_an_affix_renders_as_the_sentence_the_player_reads(game):
    """The whole chain, on real names and real wording.

    ``OFTHEELEPHANT MAX HP`` is what the save file calls the effect.  It is an
    affix, not an effect; the effect is ``MAX HP``, whose wording is
    ``+[VALUE] Health`` and whose precision is 0.  So 81.6 reads +82.
    """
    it = item(level=30)
    it.effects = [effect("OFTHEELEPHANT MAX HP", value=81.6)]
    assert render(it, game) == [
        "Test Item",
        "Requires Level 30",
        "+82 Health",
    ]


@needs_game
def test_an_ambiguous_affix_is_settled_by_which_effect_its_name_ends_with(game):
    """107 affixes are called `OFFLAME DAMAGE BONUS`, granting everything from
    fire damage to dodge chance.  Their names alone cannot say which.

    The item's own name settles it: an ``of Flame`` item means DAMAGE BONUS,
    and the element comes from the record's damage type rather than from the
    affix, which is why the same affix name renders as every element there is.
    """
    fire = item()
    fire.effects = [
        effect("OFFLAME DAMAGE BONUS", value=10.0, damage_type=0x02)
    ]
    assert "+10 Fire Damage" in render(fire, game)

    ice = item()
    ice.effects = [effect("OFICE DAMAGE BONUS", value=10.0, damage_type=0x03)]
    assert "+10 Ice Damage" in render(ice, game)


@needs_game
def test_a_negative_value_takes_the_wording_that_states_a_penalty(game):
    """Real items record a negative value under the positive wording.

    ``+[VALUE] All Damage`` cannot say minus ten -- substituting into it gives
    '+-10 All Damage' -- so the sign decides, and the magnitude goes into the
    wording the data keeps for exactly this.
    """
    it = item()
    it.effects = [effect("OFTHEBEAR DAMAGE BONUS", value=-10.0, damage_type=0x06)]
    assert "-10 All Damage" in render(it, game)


@needs_game
def test_an_effect_nobody_can_name_shows_its_raw_name(game):
    """The safety net, on a name taken from the user's own items.

    ``WC_PROC_FULLHEAL`` names two different effects depending on where it is
    read from, so nothing settles it.  Saying so beats guessing, and beats
    dropping the line.
    """
    it = item()
    it.effects = [effect("WC_PROC_FULLHEAL", value=1.0)]
    assert "WC_PROC_FULLHEAL" in render(it, game)


@needs_game
def test_a_nameless_record_is_not_a_line(game):
    """They are ordinary, and the game shows nothing for them."""
    it = item()
    it.effects = [effect("", value=44.4), effect("OFTHEELEPHANT MAX HP", value=6.0)]
    assert render(it, game) == ["Test Item", "+6 Health"]


def test_without_the_game_the_names_stand_in_for_the_wording():
    """The tool still works when it cannot find the game's files."""
    it = item()
    it.effects = [effect("OFTHEELEPHANT MAX HP", value=81.6)]
    assert render(it, None) == ["Test Item", "OFTHEELEPHANT MAX HP"]


# --------------------------------------------------------------------------
# The lines around the effects
# --------------------------------------------------------------------------


def test_damage_and_armour_are_shown_when_the_item_has_them():
    assert "Damage 72" in render(item(max_damage=72), None)
    assert "Armor 20" in render(item(armor=20), None)


def test_the_no_value_sentinel_is_not_shown_as_a_number():
    """0xFFFFFFFF is what the file holds where an item has none of a thing --
    jewelry carries it as its armour, a ring as its damage.  Printing
    'Armor 4294967295' would be worse than printing nothing."""
    lines = render(item(max_damage=0xFFFFFFFF, armor=0xFFFFFFFF), None)
    assert lines == ["Test Item"]
    assert render(item(max_damage=0, armor=0), None) == ["Test Item"]


def test_the_level_line_is_left_out_when_there_is_no_level():
    assert render(item(), None) == ["Test Item"]


def test_a_gem_renders_under_the_item_that_holds_it():
    gem = item("Flawless Ruby", level=0)
    gem.effects = [effect("OFFLAME DAMAGE BONUS", value=5.0, damage_type=0x02)]
    holder = item(num_sockets=1, gems=[gem])

    lines = render(holder, None)
    assert lines == ["Test Item", "    Flawless Ruby", "    OFFLAME DAMAGE BONUS"]


@needs_game
def test_flavour_text_is_shown_for_an_item_that_has_it(game):
    """The italic line under a unique item's name.

    It is in the item's own data file rather than in the save, which is why
    this needs the game installed at all.  2,321 nodes in the archive carry
    one, most of them skills rather than items.
    """
    it = item("A3-Crystal_Fire")
    assert render(it, game) == [
        "A3-Crystal_Fire",
        "The heat from the crystal burns to the touch.",
    ]
