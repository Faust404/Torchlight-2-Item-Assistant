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

__all__ = [
    "ADDED",
    "AFFIX",
    "ARMOR",
    "Block",
    "Card",
    "DAMAGE",
    "TIER_KEYS",
    "TIER_NONE",
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

#: The colours a card's name and its icon tile can be inked, by the game's own
#: word for the tier.
#:
#: ``Magic`` is the blue one.  The website this is drawn after calls that
#: colour Rare, and calls the tier Rare with it; the game's files say ``MAGIC``
#: and nothing says RARE, so the game's word is the one used.  The colour is
#: the same blue either way.
TIER_KEYS = {
    "Normal": "normal",
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
    """

    name: str
    tier: str
    tier_word: str
    type_name: str
    icon: str | None
    level: int
    sockets: int
    blocks: tuple[Block, ...]
    gems: tuple[Card, ...]
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
    if card.flavor:
        out.append(card.flavor)
    return out
