"""Tests for the card: an item grouped into the sections the game draws.

What is new here is not the lines -- those are ``tests/test_tooltip.py``'s
business and they are unchanged -- but the shape they arrive in: which block
each line belongs to, and the parts of an item that no line carries, which are
its tier, its kind and its icon.  The window draws from that, so a field that
stops being filled in is a card quietly losing a corner of itself rather than
a test going red; hence these.

Bashdrill is the real item used throughout, as everywhere else: the blob is a
real save record, and its card is checked against what the game's own files
say it is.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash.card import (  # noqa: E402
    ADDED,
    AFFIX,
    ARMOR,
    DAMAGE,
    TIER_NONE,
    Block,
    Card,
    Rung,
    carried_magic,
    display_tier,
    lines,
)
from tl2stash.item import AddedDamage  # noqa: E402
from tl2stash.tooltip import build, render  # noqa: E402

from test_dat import needs_game, real_game  # noqa: E402
from test_gamedata import _a_set_item, _an_item_of_tier, _bashdrill  # noqa: E402
from test_tooltip import effect, item, word  # noqa: E402


# --------------------------------------------------------------------------
# A real item, whole
# --------------------------------------------------------------------------


@needs_game
def test_a_real_item_reads_as_the_card_the_window_draws(real_game):
    """Bashdrill, field by field: everything on the card that is not a line.

    The headline is the part the game draws above the stats -- the tier that
    colours the name, the kind underneath it and the icon in the corner -- and
    none of it is in the save file.  It comes from the item's own data file by
    way of its guid, which is why this needs the game installed.
    """
    card = build(_bashdrill(), real_game)

    assert card.name == "Bashdrill"
    assert card.tier == "unique"
    assert card.tier_word == "Unique"
    assert card.type_name == "Fist"
    assert card.icon == "icon_weapon_fist14"
    assert card.level == 45
    # One socket and nothing in it, which is why the two are different
    # numbers: what an item *has* is in the save file, what is *in* it is
    # another item, and Bashdrill's socket is empty.
    assert card.sockets == 1
    assert card.gems == ()
    assert card.flavor == (
        "If your enemies don't get the point, drill it into their heads."
    )


@needs_game
def test_the_card_s_blocks_are_the_game_s_sections_in_the_game_s_order(real_game):
    """Two blocks for Bashdrill, and the damage one comes first.

    The order is most of why a card exists: the same lines flattened do not say
    which of them are the weapon's own damage and which are its affixes.
    """
    card = build(_bashdrill(), real_game)

    assert [block.kind for block in card.blocks] == [DAMAGE, AFFIX]

    damage, affixes = card.blocks
    assert damage.lines == ("Physical Damage 52-74", "Electric Damage 77-110")
    # Nine effect lines.  Which nine is tests/test_gamedata.py's business --
    # it reads them one by one against the game; what is checked here is only
    # that they all landed in the one block.
    assert len(affixes.lines) == 9
    assert affixes.lines[0] == "+2% to Physical Armor"
    assert affixes.lines[-1] == "Silence for 1 sec."


@needs_game
def test_a_set_piece_wears_the_rarity_of_the_file_it_displaced(real_game):
    """Where the two halves of the card join.

    ``appearance_for`` says what rarity the file states and what set the item
    belongs to; the card turns the first into the colour key the window looks
    its ink up by and carries the second beside it.  They are separate steps,
    and this is the one that would silently stop happening -- the failure being
    a set piece drawn in a colour the game never gives it.
    """
    for wanted, key, word in (("MAGIC", "rare", "Rare"), ("UNIQUE", "unique", "Unique")):
        guid, _, _, shown = _a_set_item(real_game, wanted)
        card = build(item(guid=guid), real_game)

        assert (card.tier, card.tier_word) == (key, word)
        # Membership is not lost by not being the tier: it is the one word the
        # kind line adds, and the reason it exists is the line it produces.
        assert card.set_name == shown

    # And an item with no data file to read has no tier rather than a guess.
    assert build(item(guid=0), real_game).tier == TIER_NONE


# --------------------------------------------------------------------------
# The tier the game shows, which is not always the one the file states
# --------------------------------------------------------------------------


def test_a_plain_item_carries_no_magic_and_keeps_the_tier_its_file_states():
    """The rule, on the shapes :class:`~tl2stash.item.Item` actually takes."""
    plain = item()
    assert not carried_magic(plain)
    assert display_tier("Normal", plain) == "Normal"

    # A name affix is the mark the player sees: 'Demolishing War Mallet' is
    # green in the game and its file says NORMAL 1HMACE.
    assert carried_magic(item(prefix="Demolishing [ITEM]"))
    assert display_tier("Normal", item(prefix="Demolishing [ITEM]")) == "Magic"
    assert carried_magic(item(suffix="of the Bear"))
    # An enchantment is the other mark, and it is the only one a name cannot
    # show: the enchanter leaves no affix on the item, only this count.
    assert carried_magic(item(num_enchants=1))


def test_magic_does_not_recolour_an_item_that_already_has_a_colour():
    """Only a Normal item moves; the tiers above it keep their own.

    A green item is not green *instead* of being rare -- the game colours a
    blue item blue however much is put on it, which is why the rule reads the
    base tier before it reads anything else.
    """
    dressed = item(prefix="Demolishing [ITEM]", num_enchants=2)

    assert display_tier("Rare", dressed) == "Rare"
    assert display_tier("Unique", dressed) == "Unique"
    assert display_tier("Set", dressed) == "Set"
    assert display_tier("", dressed) == ""


def test_the_effect_list_is_not_what_makes_an_item_magic():
    """The measurement that keeps the rule from painting everything green.

    An effect list is the obvious thing to reach for and it is the wrong one:
    read over every stored item it is non-empty on nearly all of them -- every
    unique, every set piece, every spell and every fish -- because it is the
    item's own stat records rather than a mark of something added.  This is
    the one line standing between the rule and a collection that is green
    corner to corner.
    """
    assert item().effects == []
    loaded = item(effects=[effect("OFTHEELEPHANT MAX HP", value=81.6)])

    assert loaded.effects, "the item stopped carrying effects"
    assert not carried_magic(loaded)


@needs_game
def test_a_white_item_with_magic_on_it_is_built_green(real_game):
    """The whole rule end to end, on a real item file of the game's.

    The rule is tested on its own above; what this pins is that ``build``
    asks it -- a rule nobody calls is a rule that is not there.  The item is
    a real ``NORMAL`` one out of the archive, given the two shapes the save
    file produces: nothing on it, and a name affix.  The affix is the whole
    difference, so nothing else on the card may move, and only the tier does.
    """
    guid, _ = _an_item_of_tier(real_game, "NORMAL")

    plain = build(item(guid=guid), real_game)
    assert (plain.tier, plain.tier_word) == ("normal", "Normal")
    assert plain.set_name is None

    dressed = build(item(guid=guid, prefix="Demolishing [ITEM]"), real_game)
    assert (dressed.tier, dressed.tier_word) == ("magic", "Magic")


# --------------------------------------------------------------------------
# The same, with no game data at all
# --------------------------------------------------------------------------


def test_without_the_game_there_is_a_card_with_nothing_in_the_corner():
    """``data=None`` is the path a machine without the game takes.

    The lines are already known to survive it; what must not happen is a tier,
    a kind or an icon being invented to fill the space.
    """
    card = build(item("Test Item"), None)

    assert card.tier == TIER_NONE
    assert card.tier_word == ""
    assert card.type_name == ""
    assert card.icon is None
    assert card.flavor is None
    assert lines(card) == ["Test Item"]


def test_a_weapon_s_own_damage_and_what_was_added_to_it_are_two_blocks():
    """The game draws them together and they come from different places.

    An item's own damage is worked out from its data file; flat damage is in
    the save file, as three numbers per element.  Kept apart here so that the
    window can draw them as one section without the model having merged them.
    """
    it = item(max_damage=72, added_damages=[AddedDamage(0, word(13.0), 0, 0x00)])
    card = build(it, None)

    assert [(block.kind, block.lines) for block in card.blocks] == [
        (DAMAGE, ("Damage 72",)),
        (ADDED, ("+13 Physical Damage",)),
    ]


def test_armour_is_its_own_kind_of_block():
    card = build(item(armor=20), None)
    assert [(block.kind, block.lines) for block in card.blocks] == [
        (ARMOR, ("Armor 20",))
    ]


def test_a_section_with_nothing_in_it_is_not_a_block():
    """A heading with nothing under it draws as a rule with nothing under it."""
    assert build(item(), None).blocks == ()


def test_a_gem_is_a_card_of_its_own():
    """In the game a socket's contents read as lines under the item holding
    them, so a gem is a whole card rather than a few more lines."""
    gem = item("Flawless Ruby")
    gem.effects = [effect("OFFLAME DAMAGE BONUS", value=5.0, damage_type=0x02)]
    card = build(item(num_sockets=1, gems=[gem]), None)

    (nested,) = card.gems
    assert isinstance(nested, type(card))
    assert nested.name == "Flawless Ruby"
    assert [block.kind for block in nested.blocks] == [AFFIX]

    # And it flattens the way it always has: indented, under the item.
    assert lines(card) == [
        "Test Item",
        "    Flawless Ruby",
        "    OFFLAME DAMAGE BONUS",
    ]


# --------------------------------------------------------------------------
# The flat list is the card, flattened
# --------------------------------------------------------------------------


def test_the_flat_lines_are_the_card_flattened():
    """``render`` is ``lines(build(...))`` and nothing else.

    This is what keeps the window and the tooltip from disagreeing: there is
    one account of what an item says, and the flat list is a view of it rather
    than a second one built alongside.
    """
    it = item("Test Blade", level=7, max_damage=72, armor=20)
    it.effects = [effect("OFTHEELEPHANT MAX HP", value=81.6)]
    it.gems = [item("Flawless Ruby")]

    assert render(it) == lines(build(it))
    assert render(it) == [
        "Test Blade",
        "Requires Level 7",
        "Damage 72",
        "Armor 20",
        "OFTHEELEPHANT MAX HP",
        "    Flawless Ruby",
    ]


# --------------------------------------------------------------------------
# A set's ladder, flattened
# --------------------------------------------------------------------------


def test_a_ladder_is_a_heading_and_its_lines_under_the_item_s_stats():
    """``(2) Set`` over what two pieces grant, and the ladder under the item's
    own affixes rather than among them.

    A rung is not a stat the item has -- it is what *more of the set* would
    grant -- so it comes after everything the item itself carries and before
    the flavour line, which is the remark under both.
    """
    card = Card(
        name="Test Blade",
        tier="unique",
        tier_word="Unique",
        type_name="Sword",
        set_name="Test Set",
        icon=None,
        level=7,
        sockets=0,
        blocks=(Block(AFFIX, ("+5 Strength",)),),
        gems=(),
        set_ladder=(
            Rung(2, ("+6 Set damage",)),
            Rung(3, ("+5 Set burn", "2.5% chance to cast Test Proc on kill")),
        ),
        flavor="A remark.",
    )

    assert lines(card) == [
        "Test Blade",
        "Requires Level 7",
        "+5 Strength",
        "(2) Set",
        "+6 Set damage",
        "(3) Set",
        "+5 Set burn",
        "2.5% chance to cast Test Proc on kill",
        "A remark.",
    ]


def test_a_rung_is_a_heading_over_the_lines_it_carries():
    """The heading is the piece count and nothing else, so a ladder's shape is
    readable down the left of it: ``(2) Set``, then ``(3) Set``.

    Dropping a rung that came out with nothing to say is ``_set_ladder``'s
    business and is tested there -- the flattening prints the rungs the card
    holds rather than filtering them a second time.
    """
    card = Card(
        name="Test Blade",
        tier="unique",
        tier_word="Unique",
        type_name="Sword",
        set_name="Test Set",
        icon=None,
        level=0,
        sockets=0,
        blocks=(),
        gems=(),
        set_ladder=(Rung(2, ("+6 Set damage",)), Rung(3, ("+5 Set burn",))),
        flavor=None,
    )

    assert lines(card) == [
        "Test Blade",
        "(2) Set",
        "+6 Set damage",
        "(3) Set",
        "+5 Set burn",
    ]


@needs_game
def test_a_real_set_piece_reads_its_ladder_under_its_own_stats(real_game):
    """End to end from the save file's guid to the words on the card.

    Which rung says what is ``tests/test_gamedata.py``'s business; what this
    pins is that ``build`` fills the ladder in at all -- a set that renders
    everywhere but on the card is a set the player never sees.
    """
    guid, _, set_id, _ = _a_set_item(real_game, "UNIQUE")
    card = build(item(guid=guid), real_game)

    assert card.set_ladder, f"{set_id} came out with no ladder"
    assert all(rung.count >= 2 for rung in card.set_ladder)
    assert all(rung.lines for rung in card.set_ladder)

    flat = lines(card)
    for rung in card.set_ladder:
        assert f"({rung.count}) Set" in flat
    # Under the stats and before the flavour, when there is one.
    first = min(flat.index(f"({rung.count}) Set") for rung in card.set_ladder)
    for block in card.blocks:
        for line in block.lines:
            assert flat.index(line) < first
