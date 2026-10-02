"""An item as a card: the headline, and the blocks of lines under it.

:mod:`tl2stash.tooltip` turns an item into the lines the game shows.  A card is
those lines *before* they are flattened -- gathered into the sections the game
draws them in, alongside the parts of an item that no line carries: the tier
that colours its name, the kind of thing it is, the icon beside it.

The card is the description and the flat list is its projection, so there is
one account of what an item says rather than two that can drift apart.  Nothing
here writes a line: the wording is :mod:`tl2stash.tooltip`'s, and it is there
that a card is built (``build``) and flattened (``render``).

Qt-free, like the rest of ``tl2stash``.  This says what a card *is*;
``app.card`` says what it looks like.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover
    from tl2stash.item import Item

__all__ = [
    "ADDED",
    "AFFIX",
    "ARMOR",
    "Block",
    "Card",
    "DAMAGE",
    "Rung",
    "TIER_INK",
    "TIER_KEYS",
    "TIER_MAGIC",
    "TIER_NONE",
    "carried_magic",
    "display_tier",
    "lines",
]

#: What a block of lines is.
#:
#: The first two are the item's own damage and its own armour, and they are
#: spelled the same way :class:`~tl2stash.gamedata.Derived` spells them so the
#: two vocabularies are one.  ``ADDED`` is flat damage from a socket or an
#: enchantment, which the game draws with the item's own damage and which is
#: kept apart here only because it comes from somewhere else.  ``AFFIX`` is
#: everything the item's effects say.
#:
#: Nothing else is a block.  The level an item requires is drawn beside its
#: name rather than among its stats, so it is a field on the card and where it
#: lands is the window's business.
DAMAGE = "damage"
ARMOR = "armor"
ADDED = "added"
AFFIX = "affix"

#: The tier word the player is shown, by the colour it is drawn in.
#:
#: Three of these are also the game's own data tokens, unchanged: ``Normal``,
#: ``Unique`` and ``Legendary``.  The other two are where the words and the
#: data part company, and the game says so itself.  Its own tutorial text
#: reads *"Green items have minor enchantments.  Blue items are more rare and
#: powerful."*, and the samples taken off its overlay read ``magical #319C00
#: rare #2182FF   unique #EF6100`` -- so *magical* is the green in the game's
#: vocabulary and *rare* is the blue.  The catch is that the data's token for
#: the blue is ``MAGIC``, so the file's ``MAGIC`` is shown as "Rare" here and
#: "Magic" is the green one.  ``gamedata.QUALITY_WORDS`` is the one place that
#: translation happens, and :func:`display_tier` is the one place the green is
#: arrived at.
#:
#: ``Set`` is not a tier and is not drawn as one: it is a membership, and a set
#: piece wears the Rare or Unique colour its own file gives it.  The key is
#: kept because the site paints the set *ladder* purple, and this tool will
#: want the same colour the day it draws one.
TIER_KEYS = {
    "Normal": "normal",
    "Rare": "rare",
    "Magic": "magic",
    "Unique": "unique",
    "Legendary": "legendary",
    "Set": "set",
}

#: The key for an item with no tier to show: a quest item, a potion, a fish --
#: the game draws those plainly too -- or one whose data file could not be
#: found, which a modded item never can be.  Always a key the colours have, so
#: that drawing a card is a lookup and never a check.
TIER_NONE = "none"

#: The colour each tier key is drawn in, by the key :data:`TIER_KEYS` gives it.
#: The site's ``--t-*``, which it read out of the game's quality overlays rather
#: than guessing.  ``magic`` is its ``--magic`` -- the game's ``magical
#: #319C00`` lifted along its own hue the same way ``set`` is, because the
#: overlay colours are glows meant to sit on icon art and the unlifted purple
#: is unreadable as text.  The lift lands on exactly the green an affix line is
#: written in, which is what the game does too: a green item has green lines.
#:
#: Every key is present -- including ``none`` -- so drawing one is a lookup and
#: never a check.
TIER_INK = {
    "normal": "#e6e6e6",
    "rare": "#2182ff",
    "magic": "#7cc24a",
    "unique": "#ef6100",
    "set": "#a855f7",
    "legendary": "#ff3100",
    "none": "#8a8a8a",
}

#: The tier a Normal item is shown as once there is magic on it.
TIER_MAGIC = "Magic"


class CarriesMagic(Protocol):
    """What :func:`carried_magic` needs, and all it needs.

    The parsed :class:`~tl2stash.item.Item` has these, and so does a registry
    row for an item the tool has already taken -- which is the point: the
    window can colour a list of rows without parsing a single blob.
    """

    prefix: str
    suffix: str
    num_enchants: int


def carried_magic(item: Item | CarriesMagic) -> bool:
    """True when the item carries magic a plain Normal item would not.

    Two marks, and both are marks of something *added* rather than of what the
    base item rolled with: a name affix (``Demolishing War Mallet``), and an
    enchantment count, which is what an enchanter leaves behind.  A damage
    enchantment needs no separate test -- it is an enchantment, so it is
    already in the count.

    The effect list deliberately is not consulted, though it is the obvious
    thing to reach for.  Measured over every item in every registry, it is
    non-empty on nearly all of them -- 214 of 217 spells and fish, and all 72
    unique, 36 set and 27 rare items -- because it is the item's own stats
    rather than a mark of anything added.  Reading it as one would paint the
    whole collection green.
    """
    return bool(item.prefix.strip() or item.suffix.strip() or item.num_enchants)


def display_tier(base_tier: str, item: Item | CarriesMagic) -> str:
    """The tier the game shows for this *instance*, given its base file's.

    ``UNITTYPE`` gives the base file's rarity, and everything above Normal
    keeps it however much magic is put on: a unique stays orange and a rare
    stays blue when they are enchanted.  A Normal item is the one case that
    moves -- put an affix or an enchantment on it and the game gives it a green
    name and calls it magic.

    No data file has a word for that state, because it is the instance's and
    not the file's.  This is where it is arrived at, and it is the only place:
    the tooltip and the collection list both read it, so they cannot come to
    different answers about the same item.
    """
    if base_tier == "Normal" and carried_magic(item):
        return TIER_MAGIC
    return base_tier


@dataclass(frozen=True)
class Block:
    """One section of a card's lines, and what they are.

    Blocks are in the order the game draws them, and an empty one is left out
    entirely rather than kept as a heading with nothing under it -- which is
    also why :func:`lines` can concatenate them without checking.
    """

    kind: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Rung:
    """One rung of the set an item belongs to: a piece count, and its lines.

    ``count`` is how many of the set's pieces it takes to get the lines under
    it, and the lines are written by the same machinery that writes the item's
    own -- a set's bonus is an effect like any other, and only the file it was
    read out of differs.  A rung with no lines is not drawn: the card keeps
    the rule that a heading with nothing under it is not a section.
    """

    count: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Card:
    """One item, whole.

    ``name``, ``tier_word`` and ``type_name`` are the headline -- ``Bashdrill``,
    ``Unique``, ``Fist``.  They come from two different files, the name from
    the save file and the rest from the item's own data file, and an item whose
    data file cannot be found has no tier word and no type rather than an
    invented one.

    ``tier`` is the colour key, always one of :data:`TIER_KEYS`' values or
    :data:`TIER_NONE`.  ``level`` is what the save file records the item as
    requiring, and 0 when it records none.  ``sockets`` is how many it has, not
    how many are filled -- the gems that fill them are ``gems``, each a card of
    its own because that is how the game draws one.

    ``set_name`` is the set the item belongs to, when it belongs to one.  It is
    not a tier: a set piece is shown as the rare or unique thing its own file
    says it is, and this is the one place the membership is drawn out -- the
    kind line reads ``Unique Set Boots``.

    ``set_ladder`` is what wearing more of that set grants, cheapest rung
    first, and it is empty for an item in no set *and* for one in a set the
    game's data does not describe -- a mod's, or a machine with no game on it.
    The two are one empty tuple on purpose: what the card draws is the ladder,
    and there is nothing to draw either way.
    """

    name: str
    tier: str
    tier_word: str
    type_name: str
    set_name: str | None
    icon: str | None
    level: int
    sockets: int
    blocks: tuple[Block, ...]
    gems: tuple[Card, ...]
    set_ladder: tuple[Rung, ...]
    flavor: str | None


def lines(card: Card) -> list[str]:
    """The card as the flat list of lines the game shows.

    This is the whole of the flattening, and the only place it is written down.
    ``render`` is this function over a built card, which is what keeps the
    window and the tooltip from disagreeing about what an item says.
    """
    out: list[str] = []
    if card.name:
        out.append(card.name)
    if card.level:
        out.append(f"Requires Level {card.level}")
    for block in card.blocks:
        out.extend(block.lines)
    # A gem reads as its own card, indented: in the game a socket's contents
    # are drawn as lines under the item that holds them.
    for gem in card.gems:
        out.extend(f"    {line}" for line in lines(gem))
    # The set last of the stats and first of the remarks, which is where the
    # game writes it: what wearing more of the set would grant is about the
    # item rather than on it, and the flavour line is the remark under both.
    for rung in card.set_ladder:
        out.append(f"({rung.count}) Set")
        out.extend(rung.lines)
    if card.flavor:
        out.append(card.flavor)
    return out
