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
    from tl2stash.gamedata import Requirements
    from tl2stash.item import Item

__all__ = [
    "AFFIX",
    "ARMOR",
    "AUGMENT_LOCKED",
    "Augment",
    "Block",
    "Card",
    "DAMAGE",
    "DAMAGE_PER_SECOND",
    "ITEM_LEVEL_TO_SOCKET",
    "PLAYER_LEVEL",
    "REQUIREMENTS",
    "Rung",
    "TIER_INK",
    "TIER_KEYS",
    "TIER_MAGIC",
    "TIER_NONE",
    "THE_ALTERNATIVE",
    "carried_magic",
    "display_tier",
    "lines",
    "requirements_lines",
]

#: What a block of lines is.
#:
#: ``DAMAGE`` and ``ARMOR`` are the item's own, and they are spelled the same
#: way :class:`~tl2stash.gamedata.Derived` spells them so the two vocabularies
#: are one.  ``AFFIX`` is everything the item's effects say -- *everything*:
#: flat damage an affix, a socket or an enchantment added is a property like
#: any other and is written here with the rest, which is what leaves the two
#: above as the only blocks the card marks with an element.
#:
#: Nothing else is a block.  The level an item requires is drawn beside its
#: name rather than among its stats, so it is a field on the card and where it
#: lands is the window's business.
DAMAGE = "damage"
ARMOR = "armor"
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
class Augment:
    """A task an item carries, and what finishing it would grant.

    The one part of a card that is not a fact about the item but a promise
    about it: ``Kill 20 Goblins to Upgrade``, and the stats that arrive once
    the count is done.  The game works the unlock out at runtime from the
    triggerable the item names and never writes the rewards down anywhere a
    file can be read, so this is the one thing on the card that comes from the
    reference database rather than from the game's own files -- which is why a
    machine without that database draws the card it always did.

    ``gains`` is what the item does *not* have yet.  An item that has finished
    its task has them among its own properties and no block here at all: the
    distinction is not drawn by the card, it is made before the card is built,
    because a reward that has been collected is a property like any other.
    """

    task: str
    gains: tuple[str, ...]


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
    its own because that is how the game draws one, and each carrying the whole
    of what the socket contributes: see below.

    ``quantity`` is how many of the item a stack holds: 1 for everything that
    does not stack, and the number a fish or a potion is carried in.  It is the
    save file's own field, and the count of *stacks* is a different number
    again -- the tile's, which is how many of these the tool holds.

    ``weapon_lead`` is the three lines a weapon leads with -- its Damage per
    Second, its attack speed and its reach -- and is empty on everything that
    is not a weapon.  They are the item's own numbers and the first thing the
    card shows of it, so they are a field rather than a block: a block is a
    section of the card, and this is the headline's other half.

    ``set_name`` is the set the item belongs to, when it belongs to one.  It is
    not a tier: a set piece is shown as the rare or unique thing its own file
    says it is, and this is the one place the membership is drawn out -- the
    kind line reads ``Unique Set Boots``.

    ``set_ladder`` is what wearing more of that set grants, cheapest rung
    first, and it is empty for an item in no set *and* for one in a set the
    game's data does not describe -- a mod's, or a machine with no game on it.
    The two are one empty tuple on purpose: what the card draws is the ladder,
    and there is nothing to draw either way.

    ``augments`` is what the item would gain from a task it has not finished,
    in the order the game chains them -- which is one block on 73 of the 74
    items that have one at all, and three on a developer's test sword.  Empty
    on everything else, on an item whose task is already done, and on a
    machine with no reference database to read.

    ``socketed`` is not a field here, and the reason is the shape of the data
    rather than of the card: a socket's contribution is not among the item's
    lines.  The gem's card under ``Socketed`` is where it is written, and it
    is written there alone.  What an item's effect list holds is the item's
    own effects, even when one of them is the very effect a gem in it grants
    -- the Gorget of the Hill Giant Chief's ``+120 Ice Armor`` is its own
    fixed stat, and the ember in its socket grants ``+58`` of the same thing,
    which is a number the gorget carries nowhere.

    ``requires`` is what the game gates the item on, worked out from the
    item's own data file.  ``level`` stays beside it because it is a different
    number from the requirement and is still wanted -- it is the level the
    *item* is, which is what the collection lists and sorts by -- and because
    a machine with no game installed can answer for one and not the other:
    ``requires`` is ``None`` there and the level is what the card falls back
    to showing.

    ``damage`` and ``armor`` are the same numbers the two blocks above are
    written from, kept apart from the sentence they are written into: one
    ``(element, low, high)`` per part, in the game's own order of elements, and
    empty where the item has none of that kind.  They are here because a
    filter has to ask about a *number* and not about a sentence -- ``Physical
    Damage 52-74`` is what the card draws, and ``('physical', 52, 74)`` is what
    a range is compared against -- and because working the sentence back apart
    would be a second reading of the same data with its own ways to be wrong.
    The element is spelled the way :data:`tl2stash.gamedata.DAMAGE_TYPES`
    spells it, which is what the derived numbers were keyed by in the first
    place.
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
    # Everything from here down has a default, which is why the stack size is
    # written here rather than beside the level and the sockets it belongs
    # with: a dataclass will not take a defaulted field before a required one.
    quantity: int = 1
    requires: Requirements | None = None
    weapon_lead: tuple[str, ...] = ()
    augments: tuple[Augment, ...] = ()
    damage: tuple[tuple[str, int, int], ...] = ()
    armor: tuple[tuple[str, int, int], ...] = ()

    @property
    def properties(self) -> tuple[str, ...]:
        """What the item says about itself, in the order the card draws it.

        The property block and nothing else.  The item's damage and armour are
        lines too, and are deliberately not here: a filter asking about those
        has the numbers above to read, and working the answer back out of the
        sentence would be a second reading of the same data.  Nor are a gem's
        lines here -- they are the socket's, not the item's, and they are drawn
        as a card of the gem's own.
        """
        return tuple(
            line
            for block in self.blocks
            if block.kind == AFFIX
            for line in block.lines
        )


#: The heading over the ways in.  The reference database puts one over them and
#: the card does too, now that they are a section at the foot rather than a
#: note on the headline: what is under it is a group -- one gate or the other,
#: never both -- and a group needs a word over it.
REQUIREMENTS = "Requirements"

#: The two words in front of the two kinds of gate.
#:
#: These are the *reference database's* wording rather than the game's, which
#: is a change: the game's own string table has ``Requires Level`` and, on a
#: socketable, ``Requires item level``.  Both ask the same two questions about
#: the same two fields, and the reference's spelling is the one asked for here
#: -- it says what the second number is *of*, which the game's ``item level``
#: leaves the reader to work out from the fact that they are looking at a gem.
PLAYER_LEVEL = "Player Level"
ITEM_LEVEL_TO_SOCKET = "Required Item Level to Socket"
#: The word the reference puts *between* the two kinds of gate, and it is the
#: word the requirement is: a character may equip the item on reaching the
#: level *or* on reaching the attributes, whichever comes first.  Drawing the
#: two as a conjunction would be a lie about the item, so the warning is kept
#: in the line itself -- and the reference is pointed about it, drawing the
#: word as its own element rather than as part of either chip.
THE_ALTERNATIVE = "or"

#: The tail of a weapon's headline line -- ``110 Damage per Second``.  Named
#: here because two modules need it: :mod:`tl2stash.tooltip` writes the line
#: with it, and ``app.card`` picks the line out by it to draw the one number
#: the card reserves a colour for.  A line is a string and the window reads it
#: as one, the same bargain ``element_of`` makes.
DAMAGE_PER_SECOND = "Damage per Second"

#: What the reference database says stands between an item and its augment's
#: rewards, drawn as a line of its own between the task and them.  Not the
#: game's wording -- the game has none, it simply stops drawing the rewards as
#: locked once they are not -- so it is the reference's, which is where the
#: whole block comes from in the first place.
AUGMENT_LOCKED = "locked until the task above is complete"


def requirements_lines(card: Card) -> list[str]:
    """The ways in, one chip to a line.

    The reference database draws these as a row of small boxes -- the level in
    one, the word :data:`THE_ALTERNATIVE` between them, each attribute in one
    of its own -- and this is that row flattened: a line per chip, with the
    word as a line of its own between the two groups.  The window draws the
    boxes; the flat list cannot, and writing the four attributes as one
    sentence would be the tool inventing a conjunction the reference does not
    draw, which is why the separator is a line here rather than a word folded
    into the one above it.

    A card with no answer from the game's data has only the save file's level
    to show, and says so the way the tool always has; a card whose data
    answered *nothing* -- a potion, a quest item, which the game gates on
    nothing at all -- shows nothing, which is not the same as showing zero.
    """
    requires = card.requires
    if requires is None:
        return [f"{PLAYER_LEVEL} {card.level}"] if card.level else []

    out: list[str] = []
    if requires.level:
        head = ITEM_LEVEL_TO_SOCKET if requires.socketing else PLAYER_LEVEL
        out.append(f"{head} {requires.level}")
    if requires.stats:
        # The word joins the two *groups* and never the members of the second:
        # the attributes are a conjunction among themselves, and a character
        # who reaches all four has met the requirement just as surely as one
        # who reached the level.
        if out:
            out.append(THE_ALTERNATIVE)
        out.extend(f"{label} {value}" for label, value in requires.stats)
    return out


def lines(card: Card) -> list[str]:
    """The card as the flat list of lines the game shows.

    This is the whole of the flattening, and the only place it is written down.
    ``render`` is this function over a built card, which is what keeps the
    window and the tooltip from disagreeing about what an item says.
    """
    out: list[str] = []
    if card.name:
        out.append(card.name)
    # A weapon's output, first under its name: the number a weapon is chosen
    # for is not one of its stats but what the stats are about.
    out.extend(card.weapon_lead)
    for block in card.blocks:
        out.extend(block.lines)
    # What is in a socket, under its own heading: the ember the player put
    # there, and the bonus it grants *this* item -- which is the item's own
    # number for the effect even though it is not among the item's lines, and
    # is why the heading is over the gem rather than over lines of its own.
    if card.gems:
        out.append("Socketed")
    # A gem reads as its own card, indented: in the game a socket's contents
    # are drawn as lines under the item that holds them.
    for gem in card.gems:
        out.extend(f"    {line}" for line in lines(gem))
    # What the item will become, under the sockets and over the set's ladder,
    # which is where the reference draws it -- the socket's lines are about the
    # item as it stands and these are about the item as it will be, so the two
    # remarks go together and before the things that are not about it at all.
    # The caption is a line of its own rather than a heading, because the task
    # above it is what it is about.
    for augment in card.augments:
        if augment.task:
            out.append(augment.task)
        if augment.gains:
            out.append(AUGMENT_LOCKED)
            out.extend(augment.gains)
    # The set last of the stats and first of the remarks, which is where the
    # game writes it: what wearing more of the set would grant is about the
    # item rather than on it, and the flavour line is the remark under both.
    for rung in card.set_ladder:
        out.append(f"({rung.count}) Set")
        out.extend(rung.lines)
    # What the item asks of the character, at the foot of the card under
    # everything the item *is* -- after its own stats, its sockets, what it
    # would become and what more of its set would give it.  That is where the
    # reference draws it and the reason is the card's own shape: everything
    # above this is a number belonging to the item, and these lines are the
    # only ones that are about the reader.
    said = requirements_lines(card)
    if said:
        out.append(REQUIREMENTS)
        out.extend(said)
    if card.flavor:
        out.append(card.flavor)
    return out
