"""The game's item kinds, grouped for browsing.

``read_unit_type`` turns ``'UNIQUE SHOULDER ARMOR'`` into the tier and the kind,
and the kind is the game's own word for what a thing is: ``Shoulder Armor``,
``1H Mace``, ``Fish``.  There are 53 of them in the shipped game, and 53 is too
many to put in a list -- so they are gathered into the groups the reference
database uses: Armor, Weapons split three ways, Accessories, and Misc.

The grouping is the reference's; the *words* are the game's.  That distinction
matters, because the two do not agree on them: the reference's list says
``Leggings``, ``Greatsword`` and ``Shotgonne``, and no ``UNITTYPE`` in any of
the archive's 6,262 item files says any of those.  What the game writes is
``Pants``, ``2H Sword`` and ``Cannon``, so that is what these lists hold.  They
were read out of the archive rather than transcribed, and
``tests/test_taxonomy.py`` re-reads it to notice the day the game disagrees.

Two other spellings the measurement turned up, both of which have to be listed
separately because the game really does write them both: a one-handed sword is
``Sword`` in 21 files and ``1H Sword`` in 18, and an axe ``Axe`` or ``1H Axe``.
Anything that reads these lists has to treat them as the same kind of thing,
which is what the group/subgroup split is for.

The embers are a third case, one step further along: the game writes
``CHAOS EMBER`` where a gem's file writes ``SOCKETABLE``, and the two are one
thing to anyone browsing.  The reference database files all four embers under
Socketable, and measured over the archive the two spellings come to 178 files
-- exactly its count -- so they are one kind, and :data:`KIND_ALIASES` is where
they are made one.

Qt-free, like the rest of ``tl2stash``: this says how the game's kinds group,
and ``app.sidebar`` says what that looks like.
"""

from __future__ import annotations

__all__ = [
    "KIND_ALIASES",
    "OTHER",
    "TYPE_GROUPS",
    "Place",
    "canonical_kind",
    "group_of",
]

#: One item's place in the rail: ``(group, subgroup, kind)``, with ``None`` for
#: the subgroup of a group that is not split.
#:
#: This is what the sidebar draws a leaf from and what the filter matches on,
#: and the three are kept together rather than as a bare kind word because the
#: *empty* kind is a real kind in two different groups.  A quest object is a
#: ``QUESTITEM``, which is a tier and no kind at all, and it is Misc; an item
#: whose data file is not there -- a mod's, or one from a game that has been
#: uninstalled -- is also no kind at all, and it is Other.  A filter keyed on
#: the word alone would tick both at once.
Place = tuple[str, str | None, str]

#: The group an item lands in when its kind is not one of the game's.
#:
#: Not ``Misc``, which is a real answer -- "this is a potion, and potions are
#: neither armour nor a weapon".  ``Other`` is the answer for a kind nothing
#: here recognises, which in practice means an item from a mod, and a modded
#: item is a thing the player needs to be able to *see* rather than have filed
#: under a category that claims the tool knows what it is.
OTHER = "Other"

#: Kinds the game names separately that are one thing to a browser.
#:
#: The archive's item files write ``BLOOD EMBER``, ``CHAOS EMBER``,
#: ``IRON EMBER`` and ``VOID EMBER`` -- eight files each -- where a gem's file
#: writes ``SOCKETABLE`` in 146.  The reference database does not know the
#: four words at all: it files all 178 as Socketable, which is the same count
#: the two spellings come to here.  So an ember is a socketable, and the alias
#: is written down once rather than spelled out four times in the lists below.
#:
#: Upper-cased like the rest of the lookup, so a spelling difference in case
#: cannot split the leaf in two.
KIND_ALIASES: dict[str, str] = {
    "BLOOD EMBER": "Socketable",
    "CHAOS EMBER": "Socketable",
    "IRON EMBER": "Socketable",
    "VOID EMBER": "Socketable",
}

#: Every kind of thing the game has, by the group it belongs to.
#:
#: ``(group, subgroup, kinds)``, in the order the rail draws them -- which is
#: the whole of the ordering rule, so a group appears once per subgroup and
#: ``Weapons`` appears three times, in the order its three subgroups are drawn.
#: A subgroup of ``None`` means the group is not split: ``Weapons`` is, because
#: a two-handed sword and a wand are not alternatives to each other, and
#: ``Armor`` is not, because a helmet and a pair of boots are.
#:
#: ``Shield`` is under ``Weapons`` where the reference puts it, not under
#: ``Armor`` where it feels like it belongs.
#:
#: The four ember kinds are deliberately absent: they are one kind with
#: ``Socketable``, and :data:`KIND_ALIASES` is where they are made one.  Listed
#: here they would be four leaves of eight items each, beside the one leaf
#: holding the 146 they belong with.
#:
#: The empty kind is deliberately absent: see :func:`group_of`.
TYPE_GROUPS: tuple[tuple[str, str | None, tuple[str, ...]], ...] = (
    (
        "Armor",
        None,
        (
            "Helmet",
            "Shoulder Armor",
            "Chest Armor",
            "Gloves",
            "Pants",
            "Boots",
        ),
    ),
    (
        "Weapons",
        "One-Handed",
        (
            "Sword",
            "1H Sword",
            "Axe",
            "1H Axe",
            "Mace",
            "1H Mace",
            "Dagger",
            "Wand",
            "Pistol",
            "Fist",
            "Fist Fire",
            "Fist Electric",
        ),
    ),
    (
        "Weapons",
        "Two-Handed",
        (
            "2H Sword",
            "2H Axe",
            "2H Mace",
            "Polearm",
            "Polararm Fire",
            "Polararm Ele",
            "Staff",
            "Bow",
            "Crossbow",
            "Rifle",
            "Cannon",
        ),
    ),
    ("Weapons", "Off-Hand", ("Shield",)),
    (
        "Accessories",
        None,
        (
            "Ring",
            "Necklace",
            "Collar",
            "Belt",
            "Stud",
        ),
    ),
    (
        "Misc",
        None,
        (
            "Spell",
            "Socketable",
            "Map",
            "Fish",
            "Potion",
            "Healthpotion",
            "Manapotion",
            "Rejuvpotion",
            "Gold",
            "Scroll",
            "Identify Scroll",
            "Item",
            "Dynamite",
        ),
    ),
)

#: Kind to ``(group, subgroup)``, upper-cased so that a kind differing only in
#: case -- which a mod's data file may well write -- still lands where it
#: belongs.
_BY_KIND: dict[str, tuple[str, str | None]] = {
    kind.upper(): (group, subgroup)
    for group, subgroup, kinds in TYPE_GROUPS
    for kind in kinds
}


def canonical_kind(kind: str) -> str:
    """The one word for a kind the game spells more than one way.

    ``canonical_kind('Chaos Ember')`` is ``'Socketable'`` and every other kind
    comes back untouched.  It is applied where a kind is *read* -- see
    :func:`tl2stash.gamedata._appearance` -- as well as by :func:`group_of`, so
    the rail, the filter and the card's type line all say the same word; the
    item's own name, ``Chaos Ember``, is where the ember stays named.
    """
    return KIND_ALIASES.get(kind.upper(), kind)


def group_of(kind: str) -> tuple[str, str | None]:
    """Where a kind belongs: ``('Weapons', 'One-Handed')`` for ``'1H Sword'``.

    An unknown kind comes back as ``(OTHER, None)``, and so does the empty one
    -- but the empty kind is *not* unknown, and that is worth being precise
    about because it is a third of the archive.  ``read_unit_type`` returns it
    for a token with no kind word in it, and the game writes ``QUESTITEM`` that
    way: a quest object is a Quest-tier item in which the game never needed to
    say *what* it is.  There is no group for quest objects and there should not
    be one, so they are ``Misc`` -- which is also what keeps ``Other`` meaning
    only one thing, an item whose kind nothing here recognises.

    A kind is canonicalised first, so a word the game spells its own way --
    ``Blood Ember`` -- lands with the kind it is, and a caller that reads kinds
    without going through :func:`canonical_kind` still gets the right group.
    """
    if not kind:
        return "Misc", None
    return _BY_KIND.get(canonical_kind(kind).upper(), (OTHER, None))
