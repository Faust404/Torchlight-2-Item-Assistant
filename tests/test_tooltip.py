"""Tests for the tooltip renderer.

The number formatter is tested on its own, because it is quirky in a way that
is invisible when it is wrong: a positive value rounds *up*, so
``0.30000000000000004`` at one decimal is ``0.4``, while a negative one is
shown as it was stored.  A table of cases is the only way that stays put.

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

from tl2stash.card import AFFIX, Rung, lines  # noqa: E402
from tl2stash.gamedata import (  # noqa: E402
    GameData,
    SetBonus,
    SetRung,
    find_install,
)
from tl2stash.item import (  # noqa: E402
    AddedDamage,
    Effect,
    Item,
    Location,
    parse_item,
)
from tl2stash.stash import read_stash_file  # noqa: E402
from tl2stash.tooltip import (  # noqa: E402
    PERMANENT,
    _added_damage_lines,
    _effect_lines,
    _set_ladder,
    _substitute,
    build,
    format_value,
    render,
    shown_value,
)

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
    index: int = -1,
) -> Effect:
    """A record as the item blob holds one.

    ``index`` defaults to -1, which is not a position in ``EFFECTSLIST.DAT``,
    so these records are resolved by name.  That is deliberate: a test that
    says ``WC_PROC_FULLHEAL`` means that name, and a real record's index would
    point at a real effect and win.  Pass an ``index`` to test that it does.
    """
    return Effect(
        type=0x8041,
        name=name,
        file=None,
        guid=None,
        num_values=len(values),
        values=[word(v) for v in values],
        index=index,
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


def test_a_negative_value_keeps_its_decimals():
    """The rounding is a ceiling and a ceiling does not apply to these.

    Across 6,173 items the game renders 42 numbers carrying a fraction, and
    every one is negative and shown exactly as stored -- ``-1.1%`` 24 times,
    ``-1.5%`` 15.  ``ceil(-1.1)`` is -1, so a ceiling cannot be what produced
    them, and there is no fractional *positive* in the corpus at all, which is
    what a ceiling would leave behind.
    """
    assert format_value(-1.1, 0) == "-1.1"
    assert format_value(-1.5, 0) == "-1.5"
    assert format_value(-7.5, 2) == "-7.5"
    # At least one decimal, so a stored float does not arrive with its noise.
    assert format_value(-19031.34375, 0) == "-19031.3"


def test_rounding_is_a_ceiling_only_above_zero():
    """The two halves of the rule, side by side."""
    assert shown_value(85.224, 0) == 86.0  # a positive fraction carries
    assert shown_value(-85.224, 0) == -85.2  # a negative one is kept
    assert shown_value(2.0, 1) == 2.0


def test_ceilings_after_scaling_so_float_noise_can_push_a_value_up():
    """The quirk this whole function exists for.

    0.1 + 0.2 is a hair over 0.3, and the game shows 0.4 because it rounds
    that hair up at one decimal and then cuts the string.  Rounding to nearest
    would give 0.3 and look entirely reasonable.
    """
    assert format_value(0.1 + 0.2, 1) == "0.4"


def test_a_whole_number_never_carries_a_point_and_a_zero():
    """Read off every stat line the game ships: 7,140 of them, and not one
    ends in '.0'.  '+5% Attack Speed' is every attack-speed line there is."""
    assert format_value(2.0, 1) == "2"
    assert format_value(100.0, 1) == "100"
    assert format_value(1.0, 2) == "1"
    assert format_value(1.0, 3) == "1"


def test_decimals_are_cut_to_length_and_not_padded():
    """A missing digit is not invented: 1.5 at two decimals is '1.5'."""
    assert format_value(1.5, 2) == "1.5"
    assert format_value(1.25, 3) == "1.25"


def test_a_precision_of_two_keeps_two_digits():
    assert format_value(1.42, 2) == "1.42"
    assert format_value(1.005, 2) == "1.01"
    assert format_value(0.125, 2) == "0.13"


# --------------------------------------------------------------------------
# Filling in a description
# --------------------------------------------------------------------------


def test_each_hole_gets_the_value_it_names():
    """One template, every tag, so the mapping is readable in one place."""
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
        "10|1|2|3|4|5|3|5 sec.|Fire|Fireball III|1 sec."
    )


def test_value_over_time_rounds_the_rate_before_multiplying():
    """Not the other way round, and the difference is visible on a real item.

    Bonebreaker's 'of the Bear' affix stores 11.259 over 5 seconds.  The game
    shows '+12 Physical Damage' and '60 Physical Damage over 5 sec.' -- 12 x 5,
    the number the player read times the duration.  Multiplying the stored
    float first gives 57, which is a number that appears nowhere in the game.
    """
    eff = effect("ANY", value=11.259, duration=5.0)
    assert _substitute("[VALUE_OT]", eff, 0, None, 11.259) == "60"
    # And where there is no rounding to do, it is a plain product.
    eff = effect("ANY", value=3.0, duration=4.0)
    assert _substitute("[VALUE_OT]", eff, 0, None, 3.0) == "12"


def test_a_duration_is_always_abbreviated():
    """'sec.', singular and plural alike.

    The game's stat lines use it 612 times, and the several hundred lines that
    spell out 'second' are all saying something else -- '+2 seconds of Burn',
    '7 Mana recovery per second'.  There is no singular form to get wrong.
    """
    assert _substitute("[DURATION]", effect("ANY", duration=1.0), 0, None, 0.0) == "1 sec."
    assert _substitute("[DURATION]", effect("ANY", duration=5.0), 0, None, 0.0) == "5 sec."
    assert _substitute("[DURATION]", effect("ANY", duration=5.0), 1, None, 0.0) == "5 sec."


def test_a_template_states_the_sign_and_the_hole_takes_the_magnitude():
    """One effect in the game needs this: '-[VALUE]% [DMGTYPE] Damage Taken
    for each monster within [VALUE3]m', whose records hold -3.  Without it the
    line reads '--3%'."""
    eff = effect("ANY", value=-3.0, values=(0.0, 0.0, 3.0), damage_type=0x00)
    got = _substitute(
        "-[VALUE]% [DMGTYPE] Damage Taken for each monster within [VALUE3]m",
        eff,
        0,
        None,
        -3.0,
    )
    assert got == "-3% Physical Damage Taken for each monster within 3m"


def test_a_value_is_otherwise_written_with_the_sign_it_has():
    """A record can ask for the positive wording and hold a negative number,
    and the game writes both out.  Choosing the wording by the sign instead
    reads 'increased by 2%', which is the same number and the opposite stat."""
    eff = effect("ANY", value=-1.1, damage_type=0x06)
    assert _substitute(
        "[DMGTYPE] Damage Taken is reduced by [VALUE]%", eff, 0, None, -1.1
    ) == "All Damage Taken is reduced by -1.1%"


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
def test_the_record_index_is_what_settles_which_effect_is_meant(game):
    """Not the name beside it.

    A record's ``index`` is its position in ``EFFECTSLIST.DAT``, and that is
    the game's own answer to which effect it refers to.  The ``name`` is an
    *affix* name -- 107 affixes are called ``OFFLAME DAMAGE BONUS`` -- so it
    is only a fallback.  Here the two disagree on purpose: index 4 is
    ``MAX MANA`` and the name says elephant.  The index wins.
    """
    assert game.effect(4).name == "MAX MANA"
    it = item()
    it.effects = [effect("OFTHEELEPHANT MAX HP", value=30.0, index=4)]
    assert "+30 Mana" in render(it, game)


@needs_game
def test_the_name_settles_it_when_the_index_lands_nowhere(game):
    """The fallback, and it is not a rare one: mods add effects the vanilla
    ``EFFECTSLIST`` has never heard of."""
    it = item()
    it.effects = [effect("OFTHEELEPHANT MAX HP", value=30.0, index=99999)]
    assert "+30 Health" in render(it, game)


@needs_game
def test_a_hole_naming_a_skill_gets_the_skill_s_name(game):
    """``[NAME]`` is the skill, and it is found through the affix.

    Only the templates for effects that cast or alter a skill use ``[NAME]``.
    ``WC_PROC_FULLHEAL`` is an affix under ``MEDIA/AFFIXES/ITEMS`` *and* a
    skill under ``MEDIA/SKILLS/ARBITER/WANDCHAOS``; only the skill carries the
    display name, which is why the lookup is by display name and not by node.
    """
    assert game.effect(203).name == "CAST SKILL ON KILL"
    it = item()
    it.effects = [effect("WC_PROC_FULLHEAL", value=2.0, index=203)]
    assert "2% chance to cast Fully Heal Self on kill" in render(it, game)


@needs_game
def test_an_effect_nobody_can_name_shows_its_raw_name(game):
    """The safety net.  Saying so beats guessing, and beats dropping the line."""
    it = item()
    it.effects = [effect("NOBODY KNOWS THIS ONE", value=1.0)]
    assert "NOBODY KNOWS THIS ONE" in render(it, game)


@needs_game
def test_colour_markup_is_stripped_from_the_wording(game):
    """The templates are display strings and carry the game's own colour
    codes: '|c00ff9933Charge|u rate increased by [VALUE]%'.  Both codes, and
    the spaces sit outside them, so removing them leaves the sentence."""
    assert game.effect(174).name == "PERCENT CHARGING BONUS"
    it = item()
    it.effects = [effect("", value=5.0, index=174)]
    assert "Charge rate increased by 5%" in render(it, game)


@needs_game
def test_an_item_s_own_armour_is_not_repeated_as_an_effect(game):
    """``INNATE FIRE DEFENSE`` and friends *are* the armour line.

    An item that states its own armour states it twice -- once as this effect
    and once as the ``ARMOR_*`` fields the armour line is worked out from --
    and the game shows the second.  Plain ``FIRE DEFENSE``, four lines above
    it in the list, is a stat an affix grants and is shown like any other.
    """
    assert game.effect(219).name == "INNATE FIRE DEFENSE"
    it = item()
    it.effects = [effect("", value=45.0, index=219)]
    assert render(it, game) == ["Test Item"]


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


@needs_game
def test_a_socketable_s_gate_is_written_as_an_item_level(game):
    """The one gate that is about a *different* item, in the game's own word.

    A socketable is not worn, so the level its file names is the level of the
    host it may go into, and the game writes ``Requires item level`` for that
    rather than the ``Requires Level`` it puts on a sword.  The item here is
    level 0 -- which is what the collection's own socketables are -- so the
    line cannot be the item's own level read back to it.

    Which number belongs there is ``tests/test_gamedata.py``'s business; what
    is pinned here is the wording, and that a number is there at all.
    """
    from test_gamedata import _a_socketable_with_a_gate

    guid, _ = _a_socketable_with_a_gate(game)
    card = build(item("Blood Ember", guid=guid, level=0), game)

    head, _, number = lines(card)[1].rpartition(" ")
    assert head == "Requires item level"
    assert number.isdigit() and int(number) > 0


def test_flat_damage_from_a_socket_or_enchant_is_its_own_line():
    """Recorded per element as three numbers -- how much came from an effect,
    from a socket and from an enchantment -- and the player sees the total.

    Bonebreaker carries one of these for 13 physical on top of the 120-239 its
    data file gives it, and the game lists both.
    """
    it = item(added_damages=[AddedDamage(0, word(13.0), 0, 0x00)])
    assert _added_damage_lines(it) == ["+13 Physical Damage"]


def test_flat_damage_sums_every_source_and_names_every_element():
    it = item(
        added_damages=[
            AddedDamage(word(2.0), word(3.0), word(4.0), 0x02),
            AddedDamage(0, word(22.0), 0, 0x04),
        ]
    )
    assert _added_damage_lines(it) == ["+9 Fire Damage", "+22 Electric Damage"]


def test_an_element_with_no_damage_is_not_a_line():
    """The records are one per element and most of them are zero: the list is
    sized by how many *types* the item can deal, not by how many it does."""
    it = item(added_damages=[AddedDamage(0, 0, 0, 0x02), AddedDamage(0, word(5.0), 0, 0x00)])
    assert _added_damage_lines(it) == ["+5 Physical Damage"]


def test_a_gem_renders_under_the_item_that_holds_it():
    gem = item("Flawless Ruby", level=0)
    gem.effects = [effect("OFFLAME DAMAGE BONUS", value=5.0, damage_type=0x02)]
    holder = item(num_sockets=1, gems=[gem])

    lines = render(holder, None)
    assert lines == [
        "Test Item",
        "Socketed",
        "    Flawless Ruby",
        "    OFFLAME DAMAGE BONUS",
    ]


# --------------------------------------------------------------------------
# What a socket added, kept apart from the item's own
# --------------------------------------------------------------------------


class _Node:
    """A data node with the one attribute the split reads off it."""

    def __init__(self, name: str):
        self.name = name


class _SocketGame:
    """Just enough of a :class:`~tl2stash.gamedata.GameData` to split one.

    The real thing is measured against the archive below; what this reaches is
    the rule itself -- two records at two indices, one of which the gem also
    carries -- without the game installed.
    """

    #: The index the item's own record sits at, and the one its socket shares
    #: with the gem's own record.  Both are the Gorget's numbers.
    OWN, SOCKET = 26, 38

    _NAMES = {26: "MAX HP", 38: "TRINKET_ICEDEFENSE"}

    def effect(self, index):
        name = self._NAMES.get(index)
        return _Node(name) if name else None

    def effect_for(self, name):
        # Every record here carries an index that lands somewhere, so the
        # name never has to be asked.
        return None

    def effect_template(self, node, description_type):
        return {
            "MAX HP": "+[VALUE] Health",
            "TRINKET_ICEDEFENSE": "+[VALUE] Ice Armor",
        }[node.name]

    #: Which host each of its effects is granted to.  Only one of the two has
    #: a host: the other is granted to both, which is the case a line with no
    #: host to name is about.
    _HOSTS = {"TRINKET_ICEDEFENSE": "TRINKET"}

    def socket_target(self, name):
        return self._HOSTS.get(name)

    def display_precision(self, node):
        return 0

    def display_name(self, name):
        return None


class _TwoHostGame(_SocketGame):
    """The same game with a bonus on each host, and a third on neither.

    What a real socketable is: one affix per host, so two lines, plus whatever
    it grants to both.  Its records reach the card in the order the game wrote
    them and in no other order -- the Flame Ember's weapon half is first -- so
    which line leads is the card's to decide.
    """

    _NAMES = {26: "MAX HP", 38: "TRINKET_ICEDEFENSE", 40: "WEAPON_DAMAGEBONUS"}

    def effect_template(self, node, description_type):
        return {
            "MAX HP": "+[VALUE] Health",
            "TRINKET_ICEDEFENSE": "+[VALUE] Ice Armor",
            "WEAPON_DAMAGEBONUS": "+[VALUE] Fire Damage",
        }[node.name]

    _HOSTS = {"TRINKET_ICEDEFENSE": "TRINKET", "WEAPON_DAMAGEBONUS": "WEAPON"}


class _Kind:
    """What an item *is*, as the host prefix reads it.

    Only one attribute is ever asked for, and it is the gate on the whole
    feature: a socketable's bonuses are granted *to a host*, one each, and the
    card is the only place the two can be read side by side -- whereas the
    same effect node on a sword is that sword's own, wherever it is worn.
    """

    def __init__(self, type_name: str):
        self.type_name = type_name


def test_a_socketable_s_line_names_the_host_it_is_granted_to():
    """A gem is one bonus per host, and the card says which is which.

    ``+120 Ice Armor`` in a ring is the same affix as ``+58 Ice Armor`` in a
    weapon, at the number that host gets -- so a line with no host on it is
    half a fact.  The two words are the reference database's, which writes
    ``Armor/Trinket`` where the game's files write ``TRINKET``: a gem in a
    ring and a gem in a breastplate are granted the same bonus, and the game
    spells the host the one way for both.
    """
    gem = item("Ice Ember", level=0)
    gem.effects = [effect("", value=120.0, index=_SocketGame.SOCKET)]

    own, socketed = _effect_lines(gem, _SocketGame(), _Kind("Socketable"))
    assert own == ["Armor/Trinket: +120 Ice Armor"]
    assert socketed == []


def test_a_socketable_leads_with_the_half_that_is_not_the_weapon_s():
    """The reference database's order: neither host, then Armor/Trinket, then
    Weapon.

    A socketable's two halves are recorded in whichever order the game wrote
    them -- the Flame Ember's weapon half comes first in its own record -- so
    the card is what puts them in the order a player reads them in.  The line
    granted to *both* hosts is not a host's line and so leads.
    """
    gem = item("Ice Ember", level=0)
    gem.effects = [
        effect("", value=26.0, index=40),  # the weapon half, recorded first
        effect("", value=120.0, index=_SocketGame.SOCKET),
        effect("", value=50.0, index=_SocketGame.OWN),  # granted to both
    ]

    own, socketed = _effect_lines(gem, _TwoHostGame(), _Kind("Socketable"))

    assert own == [
        "+50 Health",
        "Armor/Trinket: +120 Ice Armor",
        "Weapon: +26 Fire Damage",
    ]
    assert socketed == []


def test_the_same_effect_on_anything_else_is_named_to_no_host():
    """The gate, and the reason it is there: a sword is not worn two ways.

    *Armor* on a breastplate is the breastplate's armour and on a ring the
    ring's, but a weapon's damage bonus is the weapon's, and writing a host on
    it would be a claim about a thing that has only one.
    """
    sword = item("Test Sword", level=1)
    sword.effects = [effect("", value=120.0, index=_SocketGame.SOCKET)]

    own, socketed = _effect_lines(sword, _SocketGame(), _Kind("Sword"))
    assert own == ["+120 Ice Armor"]
    assert socketed == []


def test_an_effect_both_hosts_get_is_left_without_a_host():
    """Which is the honest line for a unique gem that works in either.

    ``socket_target`` answers ``None`` for an effect no affix claims for one
    host, and the line stands as it was -- true wherever the gem is put, which
    is what saying nothing says.
    """
    gem = item("Unique Gem", level=0)
    gem.effects = [effect("", value=82.0, index=_SocketGame.OWN)]

    own, socketed = _effect_lines(gem, _SocketGame(), _Kind("Socketable"))
    assert own == ["+82 Health"]


def test_a_socket_s_line_is_read_out_of_the_item_s_own_list():
    """A save file does not mark which of an item's records came from a socket.

    What a gem grants is *added to the item's own list*, at the value it has
    for that item -- so the one thing left to tell the two apart is the index,
    which the item's record shares with the gem's own record for the same
    effect.  Here the item carries two records and the gem one: index 26 is
    the item's own health and stays among its stats, index 38 is the socket's
    ice armour and goes under its own heading.
    """
    gem = item("Ice Ember", level=0)
    gem.effects = [effect("", value=58.0, index=_SocketGame.SOCKET)]
    holder = item(num_sockets=1, gems=[gem])
    holder.effects = [
        effect("", value=120.0, index=_SocketGame.SOCKET),
        effect("", value=82.0, index=_SocketGame.OWN),
    ]

    own, socketed = _effect_lines(holder, _SocketGame())
    assert own == ["+82 Health"]
    assert socketed == ["+120 Ice Armor"]


def test_a_record_the_gem_does_not_share_stays_the_item_s():
    """The other half of the rule, and the reason it is the index rather than
    "anything a gem has": an item rolled with health and a gem granting ice
    keeps its health, whatever else the gem does."""
    gem = item("Ice Ember", level=0)
    gem.effects = [effect("", value=58.0, index=_SocketGame.SOCKET)]
    holder = item(num_sockets=1, gems=[gem])
    holder.effects = [effect("", value=82.0, index=_SocketGame.OWN)]

    own, socketed = _effect_lines(holder, _SocketGame())
    assert own == ["+82 Health"]
    assert socketed == []


def test_a_record_with_no_index_can_never_read_as_a_socket_s():
    """``index`` is -1 on a record whose effect is settled by its name -- a
    mod's, mostly -- and -1 is not a position in any gem's list either, so
    such a record is always the item's own.  Nothing else in the file would
    say so, and guessing from the name is exactly what the index is here to
    avoid: 107 affixes share one name."""
    gem = item("Ice Ember", level=0)
    gem.effects = [effect("OFFLAME DAMAGE BONUS", value=58.0)]
    holder = item(num_sockets=1, gems=[gem])
    holder.effects = [effect("OFFLAME DAMAGE BONUS", value=120.0)]

    own, socketed = _effect_lines(holder, _SocketGame())
    assert socketed == []
    assert own == ["OFFLAME DAMAGE BONUS"], "the name stands in with no wording"


def _a_socketed_item():
    """The one item this machine stores with something in its socket.

    Read only, so a test can never write to it.  Measured: of the socketed
    rows here, one has a gem in it, and it is the item the split was measured
    on.  Returns ``None`` when there is nothing stored to read.
    """
    root = Path(__file__).resolve().parent.parent
    demo = root / "var" / "demo" / "sharedstash_v2.bin"
    if not demo.is_file():
        return None
    for entry in read_stash_file(demo).entries:
        try:
            it = parse_item(entry.blob)
        except Exception:  # noqa: BLE001 -- an unreadable blob is not this test's business
            continue
        if it.gems:
            return it
    return None


@needs_game
def test_a_real_socket_s_line_is_shown_apart_from_the_item_s_own(game):
    """The item the split was measured on: the Gorget of the Hill Giant Chief.

    Its Ice Ember reads ``+58 Ice Armor`` on its own card and ``+120 Ice
    Armor`` in the item's effect list, and both are true: the record holds
    what the ember grants *this gorget*.  What the split buys is the one thing
    that tells the player which is which -- the ice line reads under
    ``Socketed``, and the block above it is what the item would still have
    with the socket emptied.
    """
    gorget = _a_socketed_item()
    if gorget is None:
        pytest.skip("no socketed item is stored on this machine")

    card = build(gorget, game)
    flat = lines(card)

    (affix,) = [block for block in card.blocks if block.kind == AFFIX]
    assert not any("Ice Armor" in line for line in affix.lines), affix.lines

    assert card.socketed == ("+120 Ice Armor",)
    assert flat.count("+120 Ice Armor") == 1
    assert flat.index("Socketed") < flat.index("+120 Ice Armor")

    # And the gem under it is a card of its own, with the gem's own number.
    assert [gem.name for gem in card.gems] == ["Ice Ember"]
    assert any("+58 Ice Armor" in line for line in lines(card.gems[0]))


def _effect_index(game, name: str) -> int:
    """Where ``EFFECTSLIST`` keeps an effect, found by the name it is filed
    under rather than by a number copied out of the archive."""
    for index in range(game.effect_count):
        node = game.effect(index)
        if node is not None and (node.name or "").upper() == name.upper():
            return index
    raise AssertionError(f"the archive files no effect called {name!r}")


@needs_game
def test_a_real_socketable_s_two_halves_are_named_on_the_card(game):
    """The Flame Ember: ``+29 Fire Damage`` in a weapon, ``+58 Fire Armor``
    anywhere else.

    The ember's own card in the collection, as the player reads it -- and the
    numbers and the two indices are the ones its own records carry, read out of
    the archive's ``EFFECTSLIST`` here rather than from the tool.  It is the
    game's files that cannot answer which half is which: the effect nodes
    ``DAMAGE BONUS`` and ``FIRE DEFENSE`` are the flame ember's weapon and
    armor affixes, and neither the ember nor either affix file says so.

    The ember's own records are in the other order -- the weapon half is the
    first of the two in its item file -- so this is also what pins the order
    the two are written in.
    """
    ember = item("Flame Ember", level=0)
    ember.effects = [
        # The damage type is part of the record, which is why the weapon line
        # reads 'Fire' and the armour one does not: the armor template names
        # its element in the sentence.
        effect("", value=29.0, index=_effect_index(game, "DAMAGE BONUS"), damage_type=2),
        effect("", value=58.0, index=_effect_index(game, "FIRE DEFENSE"), damage_type=1),
    ]

    own, socketed = _effect_lines(ember, game, _Kind("Socketable"))

    assert own == ["Armor/Trinket: +58 Fire Armor", "Weapon: +29 Fire Damage"]
    assert socketed == []


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


# --------------------------------------------------------------------------
# A set's ladder
# --------------------------------------------------------------------------


class _SetGame:
    """Just enough of a :class:`~tl2stash.gamedata.GameData` for a ladder.

    The shipped archive has no set whose wording comes out empty, so the rule
    that a rung with nothing under it is dropped cannot be reached through the
    real data -- and a rule nothing can reach is a rule nothing keeps.  This
    stands in for the game: two rungs, one effect each, and a template that is
    a single space for the first of them -- which is what a half-translated
    file looks like, and what ``rstrip`` leaves empty.

    ``wording`` is what ``EFFECTSLIST`` would hold; leaving an effect out of it
    is the other half of the path, a mod's bonus naming an effect the game's
    own file has never heard of.
    """

    def __init__(self, wording: dict[str, str] | None = None):
        self._wording = {"SILENT": " ", "SPOKEN": "+[VALUE] Set damage"}
        if wording is not None:
            self._wording = wording

    def set_ladder(self, title: str) -> tuple[SetRung, ...]:
        return tuple(
            SetRung(count, (SetBonus(name, (1.0,), 0.0, 0x00, None),))
            for count, name in ((2, "SILENT"), (3, "SPOKEN"))
        )

    def effect_for(self, name: str):
        # Nothing is ever looked inside the node here -- only the template's
        # text is this stub's business, so the name stands in for the node.
        return name if name in self._wording else None

    def effect_template(self, node, description_type: int) -> str:
        return self._wording[node]

    def display_precision(self, node) -> int:
        return 0

    def display_name(self, name: str) -> str | None:
        return None


def test_a_rung_with_nothing_under_it_is_dropped():
    """A heading with nothing under it is not a section, which is the rule the
    card's blocks already keep -- and it has to hold here too, because the app
    draws each rung as a heading and would draw a bare ``(2) Set``.

    Only the silent rung goes, and its neighbour is the same ladder one
    template along -- so what is tested is the drop rather than the ladder's
    length.
    """
    assert _set_ladder("TEST", _SetGame()) == (Rung(3, ("+1 Set damage",)),)


def test_a_rung_with_no_wording_at_all_falls_back_to_the_effect_s_name():
    """An effect nobody has words for is shown under its own name, which is
    the same bargain an item's own effects make -- so the rung survives.

    A missing effect takes the same path: a bonus naming an effect that is not
    in ``EFFECTSLIST`` is a mod's set, not a reason to draw nothing.
    """
    ladder = _set_ladder("TEST", _SetGame({}))

    assert ladder == (
        Rung(2, ("SILENT",)),
        Rung(3, ("SPOKEN",)),
    )
