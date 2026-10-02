"""An item's stat lines, written the way the game writes them.

The save file says an item has the effect ``OFTHEELEPHANT MAX HP`` worth
81.6.  It does not say that reads as ``+82 Health``.  That sentence is in the
game's data files, and this puts the two together.

Two things make it more than a lookup.

The first is that an effect record carries both an index and a name, and only
one of them is decisive.  The index is the effect's position in
``EFFECTSLIST.DAT``.  The name is an *affix* name, and affix names are shared
-- ``OFTHETURTLE ARMOR BONUS`` is one name for thirteen different effects --
so it is the fallback, for a record whose index lands nowhere.  A record
neither can settle shows the name the save file gave.

The second is that the wording is a template with holes in it.  ``[VALUE]`` is
the effect's value, ``[VALUE1]`` to ``[VALUE5]`` are its value list,
``[DURATION]`` is how long it lasts, ``[DMGTYPE]`` names the element.  Which
holes a template leaves is entirely up to the data: 79 of the 808 descriptions
have no hole at all ('Identify Item', 'NA'), and one uses ``[VALUE5]``, which
appears on four descriptions in the whole game.  So a tag is a dictionary
lookup and never an assumption that it is there.

Nothing here raises on data it does not understand.  An item with an effect
nobody can name still shows that name, because a tooltip missing a line is a
great deal better than a tool that will not draw one.

An item comes out of here as a :class:`~tl2stash.card.Card`: the lines above,
gathered into the sections the game draws them in, along with the tier and the
kind and the icon that the game puts above them.  ``render`` flattens that back
to the plain list it has always returned, and everything that only wants the
text goes on calling it.

Derived by reading what the game's own files say and checking the result
against real items; not transcribed from another implementation.
"""

from __future__ import annotations

import math
import re
import struct
from typing import TYPE_CHECKING

from .card import (
    ADDED,
    AFFIX,
    ARMOR,
    DAMAGE,
    TIER_KEYS,
    TIER_NONE,
    Block,
    Card,
    Rung,
    display_tier,
    lines,
)
from .dat import VAR_FLAVOR
from .item import strip_markup

if TYPE_CHECKING:  # pragma: no cover
    from .gamedata import GameData, SetBonus
    from .item import Effect, Item

__all__ = ["build", "format_value", "render"]

#: A description's holes.  The complete set was read off all 808 descriptions
#: in the game; a tag outside it is left standing rather than replaced with a
#: guess, so that a wording this does not know about is visible rather than
#: silently wrong.
_TAG = re.compile(r"\[([A-Z0-9_]+)\]")

#: Damage types, as the effect record numbers them.  Read off real items: an
#: "of Flame" affix carries 2, "of Ice" 3, "of Lightning" 4.
_DAMAGE_TYPES = {
    0x00: "Physical",
    0x01: "Physical",
    0x02: "Fire",
    0x03: "Ice",
    0x04: "Electric",
    0x05: "Poison",
    0x06: "All",
}

#: What the game writes as an effect's duration when it does not wear off.
PERMANENT = -1000.0

#: Which of an effect's four wordings a set's bonus is written with when it
#: lasts for no time at all: the timeless positive one, which is the wording an
#: effect record asks for with a description type of zero.  A set bonus that
#: *does* state a duration is written with the over-time wording instead --
#: ``UNEARTHLY``'s fourth rung reads ``2320 Physical Damage over 5 sec.``,
#: which is the type-2 wording, and its node states ``DURATION`` of '5'.
ALWAYS_ON = 0x00

#: The over-time wording, for the same reason.  The rule the game follows is
#: the data's own: the node's stated duration, above zero, picks this one.
OVER_TIME = 0x02

#: The effects that *are* an item's armour rather than a stat on it.  A piece
#: carrying one states its armour twice -- once as this effect and once as the
#: ``ARMOR_*`` fields the armour line is built from -- and the game shows the
#: armour line, not the effect.  The names are the only thing distinguishing
#: them: ``INNATE FIRE DEFENSE`` is an item's own fire armour, while plain
#: ``FIRE DEFENSE``, four lines above it in the list, is a stat an affix
#: grants and is shown like any other.
_INNATE_DEFENSE = re.compile(r"^INNATE .* DEFENSE$")

#: The added-damage line: ``+13 Physical Damage``.
_ADDED_DAMAGE = "+{value} {element} Damage"


def _places(value: float, precision: int) -> int:
    """How many decimals the game keeps for ``value``.  See :func:`shown_value`."""
    return max(precision, 1) if value < 0 else precision


def shown_value(value: float, precision: int) -> float:
    """The number the game writes, as a number.

    A positive value rounds *toward positive infinity* -- 28.875 Mana is
    ``29``, not ``29`` by luck but because 28.875 ceilings there, and 23.04
    armour is ``24``.  That is not how anyone would choose to round; it is
    what the game does, and the two differ on ordinary input.

    A negative value is left alone instead.  Across a 6,173-item corpus, 42
    rendered numbers carry a fraction and every one of them is negative and
    shown exactly as stored -- ``-1.1%``, never ``-1%`` -- which no rounding
    rule produces, so there is nothing to apply.  One decimal is kept as the
    floor, so that a value stored as ``-19031.34375`` does not arrive with
    five digits of noise attached.
    """
    places = _places(value, precision)
    scale = 10**places
    if value < 0:
        return math.floor(value * scale + 0.5) / scale
    return math.ceil(value * scale) / scale


def format_value(value: float, precision: int = 1) -> str:
    """A number as the game shows it.

    Not zero-padded: 1.5 at two decimals is '1.5' and not '1.50'.  And a whole
    number is never written with a point and a zero -- '+5% Attack Speed' is
    every attack-speed line in the shipped game, and not one of its 7,140 stat
    lines ends in '.0'.  Decimals appear only where there is a real fraction
    to show.
    """
    places = _places(value, precision)
    whole, dot, fraction = repr(shown_value(value, precision)).partition(".")
    if not dot:
        return whole
    text = f"{whole}.{fraction[:places]}" if places else whole
    return text[:-2] if text.endswith(".0") else text


def _as_float(word: int | float) -> float:
    """An effect value: four bytes that are really a float.

    ``Item`` hands these over as integers, because that is what the file
    holds.  A value of 15.0 arrives as 1097859072.

    A float is passed through, because not every effect comes out of a save
    file: a set's bonus is read out of the game's own data, where the same
    four bytes arrive already unpacked.  One reader for both is what lets a
    set bonus go through the same substitution an item's affix does.
    """
    if isinstance(word, float):
        return word
    return struct.unpack("<f", struct.pack("<I", word & 0xFFFFFFFF))[0]


def _as_duration(seconds: float, precision: int) -> str:
    """A length of time, as the game writes it: ``5 sec.`` and ``1 sec.``.

    One form for both, abbreviated, and with the stop.  The game's stat lines
    use it 612 times to nothing -- the several hundred lines that do say
    'second' are all saying something else ('+2 seconds of Burn', '7 Mana
    recovery per second').
    """
    return f"{format_value(seconds, precision)} sec."


def _substitute(
    template: str,
    effect: "Effect",
    precision: int,
    name: str | None,
    value: float,
) -> str:
    """Fill in a description's holes.

    ``value`` is the number for ``[VALUE]``.  ``[VALUE_OT]`` is that number
    multiplied by the duration; the game does not store the product, it writes
    it out here, which is why a damage-over-time effect carries a number that
    looks unrelated to what the player reads.

    A template that writes its own ``+`` or ``-`` in front of a hole has
    already stated the sign, so that hole gets the magnitude.  Only one effect
    in the game needs it -- ``'-[VALUE]% [DMGTYPE] Damage Taken for each
    monster within [VALUE3]m'``, whose records hold -3 -- and without it the
    line reads ``--3%``.  Everywhere else the value goes in as it stands,
    which is what the game does: a record whose wording already says
    "reduced by" and whose number is -10 reads ``reduced by -10%``.

    A hole at the very *start* of a template has nothing in front of it and is
    not signed, which is worth stating because the test for the character
    before a match is empty there: ``'[VALUE] Health recovery per second'`` is
    the wording of ``HP RECHARGE PLAYER``, and a negative number on it keeps
    its sign -- which is what the game shows for the Asphyx set, whose bonus
    is ``-12 health recovery per second``.
    """
    values = effect.values

    def fill(match: re.Match) -> str:
        tag = match.group(1)
        # re.sub hands back the whole template as the match's string, so the
        # character the tag was written after is one step to the left.  There
        # is no character when the tag *starts* the template -- and the empty
        # string is a substring of every string, so the test is written out
        # rather than left as `in`.
        written = template[match.start() - 1] if match.start() else ""
        fix = abs if written in ("+", "-") else (lambda number: number)

        def at(index: int) -> str:
            if index < len(values):
                return format_value(fix(_as_float(values[index])), precision)
            return "?"

        if tag == "VALUE":
            return format_value(fix(value), precision)
        if tag == "VALUE_OT":
            # The number the player read on the always-on line, times the
            # duration -- rounded first, and the product rounded after.  A
            # 5-second 'of the Bear' affix stored at 11.259 is '+12 Physical
            # Damage' and '60 Physical Damage over 5 sec.'; multiplying the
            # stored number instead gives 57.
            rate = shown_value(fix(value), precision)
            return format_value(fix(rate * _as_float(effect.duration)), precision)
        if tag == "DURATION":
            return _as_duration(_as_float(effect.duration), precision)
        if tag == "DMGTYPE":
            return _DAMAGE_TYPES.get(effect.damage_type, "?")
        if tag == "NAME":
            return name or "?"
        if tag == "VALUE1ASDURATION":
            # The first value, written as a length of time rather than as a
            # number: '5 seconds', not '5'.
            return _as_duration(_as_float(values[0]), precision) if values else "?"
        if tag == "VALUE3AND4":
            return at(2)
        if tag.startswith("VALUE") and tag[5:].isdigit():
            return at(int(tag[5:]) - 1)  # VALUE1 is the first value, not the second
        return match.group(0)

    return _TAG.sub(fill, template)


def _effect_lines(item: "Item", data: "GameData") -> list[str]:
    """Every effect on the item, in the order the game lists them.

    Both effect lists are read.  ``effects`` is what the item was rolled with;
    ``effects2`` is what its gems, its enchantments and its set bonuses added.
    Reading only the first is why a socketed item used to show fewer lines
    than the game does.
    """
    lines: list[str] = []
    for effect in list(item.effects) + list(item.effects2):
        # The record's index is a position in EFFECTSLIST.DAT, and that is
        # what says which effect is meant.  The name beside it is an affix
        # name -- and an affix name is not unique, so it is only a fallback
        # for a record whose index lands nowhere.
        node = data.effect(effect.index) or data.effect_for(effect.name)
        if node is None:
            # Nothing settled which effect this is, so the name the save file
            # gave stands in for the sentence that would have been written.
            # A record with no name either has nothing to show.
            if effect.name:
                lines.append(effect.name)
            continue

        if _INNATE_DEFENSE.match(node.name or ""):
            # An item that states its own armour states it twice: once here
            # and once as the ARMOR_* fields the armour line is worked out
            # from.  The game shows the second, so this one is not a line.
            continue

        # Which wording is used is what the record asks for and nothing else.
        # A record can ask for the positive wording and still hold a negative
        # number -- seven of the user's items do -- and the game writes both
        # out: 'Damage Taken is reduced by -2%'.  Choosing the wording from
        # the sign instead would read 'increased by 2%', which is the same
        # number and the opposite stat.
        template = data.effect_template(node, effect.description_type)
        if not template:
            if effect.name:
                lines.append(effect.name)
            continue

        # A template is a display string and carries the game's colour markup:
        # '|c00ff9933Charge|u rate increased by [VALUE]%'.  The codes run either
        # side of a word and the spaces sit outside them, so dropping them
        # leaves the sentence the player reads.
        template = strip_markup(template)

        line = _substitute(
            template,
            effect,
            data.display_precision(node),
            # [NAME] is the *skill* the effect casts or alters, not the effect
            # and not the affix.  See GameData.display_name.
            data.display_name(effect.name) or effect.name or None,
            _as_float(effect.value),
        )
        # Templates are written with a trailing space where a hole ends the
        # sentence ('... is reduced by [VALUE]% '); it is layout in the game's
        # tooltip, and a line of it here.
        lines.append(line.rstrip())
    return lines


def _set_ladder(title: str, data: "GameData") -> tuple[Rung, ...]:
    """What wearing more of the set ``title`` grants, rung by rung.

    A set's bonus is an effect like any other -- the same schema, the same
    wording, the same holes in it -- so it is written here by the same
    substitution an item's own effects go through, and ``+6% to Ice Damage``
    from a set cannot come out differently from the same line off an affix.

    Only the file it was read out of differs, and only in one way: a data
    file's effect *is* its numbers, where a save file's record has to be
    pointed at the effect it means.  So there is no index to trust here and no
    gem to blame -- a rung says which effect it grants by name, and the one
    thing the record would have said is read off the rung's own duration
    instead of being assumed.

    A rung left with no lines is dropped rather than drawn as a bare
    ``(3) Set``: the card's rule is that a heading with nothing under it is
    not a section.
    """
    out: list[Rung] = []
    for rung in data.set_ladder(title):
        written = tuple(
            line
            for line in (_bonus_line(bonus, data) for bonus in rung.bonuses)
            if line
        )
        if written:
            out.append(Rung(rung.count, written))
    return tuple(out)


def _bonus_line(bonus: "SetBonus", data: "GameData") -> str:
    """One effect a set grants, written the way the game writes it.

    The wording is ``EFFECTSLIST``'s and the numbers are the set file's.  An
    effect nobody has wording for is shown under its own name, which is the
    same bargain :func:`_effect_lines` makes for a record it cannot place.

    Two things are read off the bonus rather than assumed, because a set's
    ladder is written the same way an item's effects are and the game decides
    both the same way.  The duration -- above zero, the node states one of its
    own, and the wording is the over-time one with ``[DURATION]`` and
    ``[VALUE_OT]`` filled from it.  And the name: ``[NAME]`` is the *skill* an
    effect casts, which for a rung is the name on the rung's own node.
    """
    node = data.effect_for(bonus.name)
    if node is None:
        return bonus.name
    template = data.effect_template(
        node, OVER_TIME if bonus.duration > 0 else ALWAYS_ON
    )
    if not template:
        return bonus.name
    line = _substitute(
        strip_markup(template),
        bonus,
        data.display_precision(node),
        data.display_name(bonus.skill) or bonus.skill or None,
        bonus.value,
    )
    return line.rstrip()


def _added_damage_lines(item: "Item") -> list[str]:
    """Flat damage the item carries, one line per element.

    Separate from the weapon's own damage above: this is what a socket or an
    enchantment adds on top, and the save file records it per element as three
    numbers -- how much of it came from an effect, from a socket and from an
    enchantment.  The player sees the total, so that is what is shown.

    Bashdrill's own damage is worked out from its data file; its
    ``+13 Physical Damage`` is here instead.
    """
    lines = []
    for added in item.added_damages:
        total = sum(
            _as_float(part)
            for part in (added.from_effect, added.from_socket, added.from_enchant)
        )
        if not total:
            continue
        element = _DAMAGE_TYPES.get(added.damage_type)
        if element is None:
            continue
        lines.append(
            _ADDED_DAMAGE.format(value=format_value(total, 0), element=element)
        )
    return lines


def _damage_lines(derived) -> list[str]:
    """The damage or armour an item has, one line per element.

    A lone physical figure is written the plain way -- ``Armor 20``, not
    ``Physical Armor 20`` -- because that is the only kind of armour most
    pieces have and naming it says nothing.  As soon as there is a second
    element, or the one there is is not physical, the element is named,
    because then it is saying something.
    """
    word = "Damage" if derived.kind == "damage" else "Armor"
    parts = derived.parts
    plain = len(parts) == 1 and "physical" in parts

    lines = []
    for element, (low, high) in parts.items():
        span = str(low) if low == high else f"{low}-{high}"
        lines.append(f"{word} {span}" if plain else f"{element.title()} {word} {span}")
    return lines


def build(item: "Item", data: "GameData | None" = None) -> Card:
    """An item as a card: its headline, its blocks of lines, its gems.

    The lines are the same ones :func:`render` has always produced, in the same
    order -- what is new is that they arrive grouped by the section they belong
    to, and that the parts of an item which are not lines at all (its tier, its
    kind, its icon) come with them.  The window draws cards; everything else
    goes on reading the flattened list.

    ``data`` may be ``None``: the game's files are not always somewhere the
    tool can find them, and without them the lines that need wording come back
    as the names the save file gave, and the item has no tier, kind or icon.
    """
    blocks: list[tuple[str, list[str]]] = []

    # The save file holds one number for a weapon -- its physical maximum --
    # and no elemental part at all, so the game's own arithmetic is used
    # where it can be: the item's data file says how the damage divides, and
    # a by-level curve says how large it is.  Bashdrill's '72' becomes
    # 'Physical Damage 52-74' and 'Electric Damage 77-110'.
    derived = data.derived_for(item) if data is not None else None
    if derived is not None:
        kind = DAMAGE if derived.kind == "damage" else ARMOR
        blocks.append((kind, _damage_lines(derived)))
    else:
        # 0xFFFFFFFF is what the file holds where an item has none of a
        # thing -- jewelry carries it as its armor, a ring as its damage.
        if item.max_damage not in (0, 0xFFFFFFFF):
            blocks.append((DAMAGE, [f"Damage {item.max_damage}"]))
        if item.armor not in (0, 0xFFFFFFFF):
            blocks.append((ARMOR, [f"Armor {item.armor}"]))

    # Flat damage sits with the rest of the damage, above the effects.
    blocks.append((ADDED, _added_damage_lines(item)))

    if data is not None:
        blocks.append((AFFIX, _effect_lines(item, data)))
    else:
        blocks.append(
            (AFFIX, [e.name for e in item.effects + item.effects2 if e.name])
        )

    flavor = None
    if data is not None:
        # The item's own data file first, because a unique is not *named*
        # what it is called -- the node behind Wanderlust Pants is
        # ``wanderer_02_pants_alt_set``.  A base item usually is, so its name
        # is tried second and is what a guid-less item has to go on.
        flavor = data.flavor_for(item)
        if not flavor:
            source = data.by_name(item.base_name)
            flavor = source.text(VAR_FLAVOR) if source else None

    appearance = data.appearance_for(item) if data is not None else None
    # The base file's word is not always the one the player is shown: the game
    # gives a Normal item a green name the moment there is magic on it.  The
    # collection list comes through here for its tier too, so the two cannot
    # read different rarities off the same item.
    tier_word = display_tier(appearance.tier, item) if appearance else ""

    # What wearing more of the set would grant.  The name on the appearance is
    # the one the player reads -- 'True North', not 'U_TRUE_NORTH' -- and the
    # ladder answers to either spelling, so nothing here has to know which of
    # the two it is holding.
    ladder: tuple[Rung, ...] = ()
    if data is not None and appearance is not None and appearance.set_name:
        ladder = _set_ladder(appearance.set_name, data)

    return Card(
        name=item.display_name,
        tier=TIER_KEYS.get(tier_word, TIER_NONE),
        tier_word=tier_word,
        type_name=appearance.type_name if appearance else "",
        set_name=appearance.set_name if appearance else None,
        icon=appearance.icon if appearance else None,
        level=item.level,
        sockets=item.num_sockets,
        # An empty section is dropped rather than kept as a heading with
        # nothing under it, which is what lets `lines` concatenate them.
        blocks=tuple(Block(kind, tuple(found)) for kind, found in blocks if found),
        gems=tuple(build(gem, data) for gem in item.gems),
        set_ladder=ladder,
        flavor=flavor or None,
    )


def render(item: "Item", data: "GameData | None" = None) -> list[str]:
    """The lines of an item's tooltip, in the game's order.

    The card is the description and this is it flattened; see :func:`build`.
    """
    return lines(build(item, data))
