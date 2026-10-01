"""An item's stat lines, written the way the game writes them.

The save file says an item has the effect ``OFTHEELEPHANT MAX HP`` worth
81.6.  It does not say that reads as ``+82 Health``.  That sentence is in the
game's data files, and this puts the two together.

Two things make it more than a lookup.

The first is that the effect a record names is an *affix*, whose name is not
unique -- 107 affixes are called ``OFFLAME DAMAGE BONUS``.  Which effect is
meant is settled in :meth:`~tl2stash.gamedata.GameData.effect_for`, and the
records that cannot be settled fall back to the name the save file gave.

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

Derived by reading what the game's own files say and checking the result
against real items; not transcribed from another implementation.
"""

from __future__ import annotations

import math
import re
import struct
from typing import TYPE_CHECKING

from .dat import VAR_DISPLAY_NAME, VAR_FLAVOR

if TYPE_CHECKING:  # pragma: no cover
    from .gamedata import GameData
    from .item import Effect, Item

__all__ = ["format_value", "render"]

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

#: The wording that states a penalty, for each description type.  An effect's
#: wording carries its own sign -- ``'+[VALUE] [DMGTYPE] Damage'`` against
#: ``'-[VALUE] [DMGTYPE] Damage'`` -- so a record that says "positive wording"
#: and then holds -10 cannot be written with the wording it asked for.  Real
#: items do this, so the sign of the value is what decides, and the magnitude
#: goes into whichever wording matches.  (Not observed from the game, which
#: cannot be run here: it is the only reading of the data that produces
#: ``-10 All Damage`` rather than ``+-10 All Damage``.)
_PENALTY_FOR = {0x00: 0x03, 0x01: 0x03, 0x02: 0x04, 0x03: 0x03, 0x04: 0x04}


def format_value(value: float, precision: int = 1) -> str:
    """A number as the game shows it.

    Rounds *up*, then cuts the decimal string to length -- which is not how
    anyone would choose to round.  It matters because it is what the game
    does, and because the two differ on ordinary input: 0.30000000000000004
    at one decimal is 0.3 by any sensible reading, and the game shows 0.4.

    Not zero-padded, so 1.5 at two decimals is '1.5' and not '1.50'; and the
    cut keeps one character more than the precision, so a number whose decimal
    string runs out early simply comes back short.
    """
    if precision <= 0:
        return str(math.ceil(value))

    scaled = math.ceil(value * 10**precision) / 10**precision
    whole, dot, fraction = repr(scaled).partition(".")
    if not dot:
        return whole
    return f"{whole}.{fraction[:precision]}"


def _as_float(word: int) -> float:
    """An effect value: four bytes that are really a float.

    ``Item`` hands these over as integers, because that is what the file
    holds.  A value of 15.0 arrives as 1097859072.
    """
    return struct.unpack("<f", struct.pack("<I", word & 0xFFFFFFFF))[0]


def _as_duration(seconds: float, precision: int) -> str:
    text = format_value(seconds, precision)
    return f"{text} second" if text == "1" else f"{text} seconds"


def _substitute(
    template: str,
    effect: "Effect",
    precision: int,
    name: str | None,
    value: float,
) -> str:
    """Fill in a description's holes.

    ``value`` is the number for ``[VALUE]``, which is the effect's own unless
    the sign moved it into the other wording.  ``[VALUE_OT]`` is that number
    multiplied by the duration; the game does not store the product, it writes
    it out here, which is why a damage-over-time effect carries a number that
    looks unrelated to what the player reads.
    """
    values = effect.values

    def at(index: int) -> str:
        if index < len(values):
            return format_value(_as_float(values[index]), precision)
        return "?"

    def fill(match: re.Match) -> str:
        tag = match.group(1)
        if tag == "VALUE":
            return format_value(value, precision)
        if tag == "VALUE_OT":
            return format_value(value * _as_float(effect.duration), precision)
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
        if not effect.name:
            # Nameless records are ordinary -- they carry values the item's
            # other lines already use, and the game shows nothing for them.
            continue

        node = data.effect_for(effect.name)
        if node is None:
            # Nothing settled which effect this is, so the name the save file
            # gave stands in for the sentence that would have been written.
            lines.append(effect.name)
            continue

        value = _as_float(effect.value)
        template = data.effect_template(node, effect.description_type)
        if value < 0:
            penalty = data.effect_template(
                node, _PENALTY_FOR.get(effect.description_type, 0x03)
            )
            if penalty:
                template, value = penalty, -value
        if not template:
            lines.append(effect.name)
            continue

        source = data.by_name(effect.name)
        name = source.text(VAR_DISPLAY_NAME) if source else None
        lines.append(
            _substitute(template, effect, data.display_precision(node), name, value)
        )
    return lines


def render(item: "Item", data: "GameData | None" = None) -> list[str]:
    """The lines of an item's tooltip, in the game's order.

    ``data`` may be ``None``: the game's files are not always somewhere the
    tool can find them, and without them the lines that need wording come back
    as the names the save file gave.
    """
    lines: list[str] = []

    title = item.display_name
    if title:
        lines.append(title)

    if item.level:
        lines.append(f"Requires Level {item.level}")

    # 0xFFFFFFFF is what the file holds where an item has none of a thing --
    # jewelry carries it as its armor, a ring as its damage.
    if item.max_damage not in (0, 0xFFFFFFFF):
        lines.append(f"Damage {item.max_damage}")
    if item.armor not in (0, 0xFFFFFFFF):
        lines.append(f"Armor {item.armor}")

    if data is not None:
        lines.extend(_effect_lines(item, data))
    else:
        lines.extend(e.name for e in item.effects + item.effects2 if e.name)

    # A gem renders as its own item, indented: in the game a socket's contents
    # read as lines under the item that holds them.
    for gem in item.gems:
        lines.extend(f"    {line}" for line in render(gem, data))

    if data is not None:
        source = data.by_name(item.base_name)
        flavor = source.text(VAR_FLAVOR) if source else None
        if flavor:
            lines.append(flavor)

    return lines
