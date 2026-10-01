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

Qt-free, like the rest of ``tl2stash``: this says how the game's kinds group,
and ``app.sidebar`` says what that looks like.
"""

from __future__ import annotations

__all__ = ["OTHER", "TYPE_GROUPS", "group_of"]

#: The group an item lands in when its kind is not one of the game's.
#:
#: Not ``Misc``, which is a real answer -- "this is a potion, and potions are
#: neither armour nor a weapon".  ``Other`` is the answer for a kind nothing
#: here recognises, which in practice means an item from a mod, and a modded
#: item is a thing the player needs to be able to *see* rather than have filed
#: under a category that claims the tool knows what it is.
OTHER = "Other"

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
            "Blood Ember",
            "Chaos Ember",
            "Iron Ember",
            "Void Ember",
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
    """
    if not kind:
        return "Misc", None
    return _BY_KIND.get(kind.upper(), (OTHER, None))
