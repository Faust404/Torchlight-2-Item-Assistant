"""The game's item kinds, in the reference database's own words.

``read_unit_type`` turns ``'UNIQUE SHOULDER ARMOR'`` into the tier and the kind,
and the kind is the game's own word for what a thing is: ``Shoulder Armor``,
``1H Mace``, ``Pants``.  There are 53 of them in the shipped game, and 53 is too
many to put in a list -- so they are gathered into the groups the reference
database uses: Armor, Weapons split three ways, Accessories, and Misc.

The grouping is the reference's, and so are the *words*.  The two vocabularies
do not agree, and where they do not the reference's is the one this tool says:
the game writes ``Pants`` where it says ``Leggings``, ``2H Sword`` for its
``Greatsword``, ``Rifle`` for its ``Shotgonne``, ``Stud`` for its ``Tag``.  One
word per kind is the whole point -- it is what lets the rail, the advanced
search's grid and the card's type line agree with each other and with the
database the player will look the item up in.  :data:`KIND_ALIASES` is where
the game's spellings are folded into it.

The lists are the reference's own, and were checked against it item by item: the
archive's 6,172 typed items join to a record in its ``out/items.json`` -- the
eighty-nine that do not are the ``BASE_*`` templates, which are no item at all
-- and every one of them lands on the type the reference gives it.
``tests/test_taxonomy.py`` re-reads the archive to notice the day the game
disagrees.

Four of the types no item in the corpus carries are kept, because the reference
keeps them: ``Fist``, ``2H Sword``, ``2H Mace`` and ``Rifle`` stand in its list
*"because UNITTYPE can still emit them"*.  Each is the game's own word for a
kind the reference files under the other spelling of the same thing -- a fist is
its ``Claw``, a ``2H Sword`` its ``Greatsword`` -- and the pair are listed
separately there and here for one reason: a box is a *name* a kind can go by,
and a name the game can still write is not a name to drop.

The embers are the same story one step along: the game writes
``CHAOS EMBER`` where a gem's file writes ``SOCKETABLE``, and the two are one
thing to anyone browsing.  The reference database files all four embers under
Socketable, and measured over the archive the two spellings come to 178 files
-- exactly its count -- so they are one kind, and :data:`KIND_ALIASES` is where
they are made one.

The potion family is the largest of them: the game writes
``HEALTHPOTION``, ``MANAPOTION`` and ``REJUVPOTION`` as kinds of their own --
eight files each -- beside the plain ``POTION`` kind's 32, and it writes
``IDENTIFY SCROLL`` beside ``SCROLL``.  The reference database has one ``Potion``
type and one ``Scroll``, and its own records say so: ``Health Potion`` and
``Mana Potion`` both carry ``ut: "HEALTHPOTION"``/``"MANAPOTION"`` with
``t: "Potion"``, and ``Identify Scroll`` carries ``ut: "IDENTIFY SCROLL"`` with
``t: "Scroll"``.  So the six words are three kinds and two here, made one in
:data:`KIND_ALIASES` the same way the embers are.  Which potion it is stays on
the item's *name* -- ``Mana Potion``, ``Grand Health Potion`` -- which is where
a player reads it anyway.

Qt-free, like the rest of ``tl2stash``: this says how the game's kinds group,
and ``app.sidebar`` says what that looks like.
"""

from __future__ import annotations

__all__ = [
    "KIND_ALIASES",
    "KIND_PLACES",
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
#: empty kind is one of them.  An item whose data file is not there at all -- a
#: mod's, or one from a game that has been uninstalled -- is no kind, and it is
#: ``Other``; its group is not something its kind could say, because there is no
#: kind to ask.  Read the other way round, :func:`group_of` reads the empty word
#: as the ``Quest Item`` the game's own ``QUESTITEM`` token names, which is
#: ``Misc`` -- so the same nothing is two places, and a filter keyed on the word
#: alone would tick both at once.
Place = tuple[str, str | None, str]

#: The group an item lands in when its kind is not one of the game's.
#:
#: Not ``Misc``, which is a real answer -- "this is a potion, and potions are
#: neither armour nor a weapon".  ``Other`` is the answer for a kind nothing
#: here recognises, which in practice means an item from a mod, and a modded
#: item is a thing the player needs to be able to *see* rather than have filed
#: under a category that claims the tool knows what it is.
OTHER = "Other"

#: The game's words for a kind, against the one word this tool says.
#:
#: Two different things are going on in this table, and they are worth telling
#: apart because only one of them is a translation.
#:
#: **The game spells one kind more than one way.**  A one-handed sword is
#: ``Sword`` in 21 item files and ``1H Sword`` in 111, an axe ``Axe`` or
#: ``1H Axe``, a mace ``Mace`` or ``1H Mace``; and the archive's four ember
#: words, three potion words and one scroll word are each one kind beside the
#: plain word they belong with.  Left alone they would be leaves of their own in
#: the rail, a row apart from the leaf holding everything else of that kind.
#:
#: * The embers: the game writes ``BLOOD EMBER``, ``CHAOS EMBER``, ``IRON
#:   EMBER`` and ``VOID EMBER`` -- eight files each -- where a gem's file writes
#:   ``SOCKETABLE`` in 146.  The reference database does not know the four words
#:   at all: it files all 178 as Socketable, which is the same count the two
#:   spellings come to here.
#: * The potion family: ``HEALTHPOTION``, ``MANAPOTION`` and ``REJUVPOTION``
#:   are three kinds of eight files each where the reference has the one
#:   ``Potion`` -- its own records carry the game's ``ut`` token and its ``t:
#:   "Potion"`` side by side -- and ``IDENTIFY SCROLL`` is one file where it has
#:   the one ``Scroll``.  A player browsing for a potion wants the 32 plain
#:   potions and the 24 of the three family names in one leaf, not four.
#:
#: **The game's word for a kind is not the reference's.**  This is the rest of
#: the table, and it is a rename rather than a fold: there is one word on each
#: side and they are different words.  Measured over the archive, item by item,
#: against the reference's own records -- 6,172 items, every one of them
#: agreeing -- the game writes ``PANTS`` where the reference says Leggings
#: (305 items), ``2HSWORD``/``2HAXE``/``2HMACE`` where it says
#: Greatsword/Greataxe/Greathammer (262), ``RIFLE`` where it says Shotgonne
#: (83), ``FIST`` where it says Claw (88), ``STUD`` where it says Tag (91),
#: ``LEVEL ITEM`` and ``ITEM`` where it says Location Item (36), and the typo
#: ``POLARARM`` for Polearm (2).
#:
#: Three of them are worth a word of their own:
#:
#: * ``QUESTITEM`` is a tier with no kind word at all, so it reaches here as the
#:   empty string -- and the reference types its 150 items ``Quest Item``, so
#:   that is the word.  The empty kind is *only* a quest object when it came out
#:   of an item file; an item with no file at all is ``Other`` and never gets
#:   this far, which is what :data:`Place` is about.
#: * ``FIST_FIRE`` and ``FIST_ELECTRIC`` are one item each, and they are the
#:   Varkolyn's axes: both are filed under ``MEDIA/UNITS/ITEMS/AXES``, both draw
#:   ``icon_weapon_axe_varkolyn01``, and the reference reads them as Axe.  The
#:   game's own token is simply wrong about them.
#: * ``LEVEL ITEM`` is the game's token and ``Item`` is the kind it reads as --
#:   ``LEVEL`` is a rarity word, which :func:`tl2stash.gamedata.read_unit_type`
#:   takes off the front -- so the entry that catches those files is ``ITEM``.
#:
#: Upper-cased like the rest of the lookup, so a spelling difference in case
#: cannot split the leaf in two.
KIND_ALIASES: dict[str, str] = {
    "BLOOD EMBER": "Socketable",
    "CHAOS EMBER": "Socketable",
    "IRON EMBER": "Socketable",
    "VOID EMBER": "Socketable",
    "HEALTHPOTION": "Potion",
    "MANAPOTION": "Potion",
    "REJUVPOTION": "Potion",
    "IDENTIFY SCROLL": "Scroll",
    "1H SWORD": "Sword",
    "1H AXE": "Axe",
    "1H MACE": "Mace",
    "2H SWORD": "Greatsword",
    "2H AXE": "Greataxe",
    "2H MACE": "Greathammer",
    "FIST": "Claw",
    "FIST FIRE": "Axe",
    "FIST ELECTRIC": "Axe",
    "PANTS": "Leggings",
    "RIFLE": "Shotgonne",
    "STUD": "Tag",
    "ITEM": "Location Item",
    "POLARARM FIRE": "Polearm",
    "POLARARM ELE": "Polearm",
    "": "Quest Item",
}

#: Every kind of thing the game has, in the reference database's own list.
#:
#: ``(group, subgroup, kinds)``, and the *group* order is the rail's --
#: ``Weapons`` appears three times, once per subgroup, in the order its three
#: subgroups are drawn.  A subgroup of ``None`` means the group is not split:
#: ``Weapons`` is, because a two-handed sword and a wand are not alternatives to
#: each other, and ``Armor`` is not, because a helmet and a pair of boots are.
#: The leaves of a group are drawn in alphabetical order by
#: :func:`app.sidebar.arranged`, so the order inside a tuple here is the
#: reference's own and nothing else's.
#:
#: ``Shield`` is under ``Weapons`` where the reference puts it, not under
#: ``Armor`` where it feels like it belongs.  ``Armor`` is a kind as well as a
#: group name -- the reference keeps one for the armour that is not a slot --
#: and the four it keeps for kinds no item of the corpus carries are named and
#: explained in the module docstring.
#:
#: The words are the reference's and so are the spellings: ``Leggings`` where
#: the game writes ``PANTS``, ``Shotgonne`` where it writes ``RIFLE``.  What the
#: game writes is in :data:`KIND_ALIASES`, against the word here it means.
#:
#: The four ember kinds, the three potion family names and ``Identify Scroll``
#: are deliberately absent: each is one kind with the word above it, and
#: :data:`KIND_ALIASES` is where they are made one.  Listed here they would be
#: eight leaves of eight items each beside the leaf holding the 178 they belong
#: with.
#:
#: The empty kind is deliberately absent: :data:`KIND_ALIASES` reads it as
#: ``Quest Item``, which is here.
TYPE_GROUPS: tuple[tuple[str, str | None, tuple[str, ...]], ...] = (
    (
        "Armor",
        None,
        (
            "Helmet",
            "Shoulder Armor",
            "Chest Armor",
            "Gloves",
            "Leggings",
            "Boots",
            "Armor",
        ),
    ),
    (
        "Weapons",
        "One-Handed",
        (
            "Sword",
            "Axe",
            "Mace",
            "Dagger",
            "Claw",
            "Wand",
            "Pistol",
            "Fist",
        ),
    ),
    (
        "Weapons",
        "Two-Handed",
        (
            "Greatsword",
            "Greataxe",
            "Greathammer",
            "Polearm",
            "Staff",
            "Bow",
            "Crossbow",
            "Shotgonne",
            "Cannon",
            "2H Sword",
            "2H Mace",
            "Rifle",
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
        ),
    ),
    (
        "Misc",
        None,
        (
            "Spell",
            "Socketable",
            "Quest Item",
            "Tag",
            "Map",
            "Fish",
            "Potion",
            "Location Item",
            "Scroll",
            "Gold",
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

#: Every kind in :data:`TYPE_GROUPS` as the rail's own :data:`Place`: the whole
#: list at once, unarranged -- putting them in the rail's order is
#: :func:`app.sidebar.arranged`'s job, and this is only the vocabulary.
#:
#: It is here for the one control that offers the *game's* kinds rather than
#: the collection's: the advanced search's Type grid, which is a form and has
#: to be able to ask for a kind the player owns none of -- a search that could
#: only name what is already on hand could only ever narrow the wall.  That the
#: list is the reference's own, and in its own words, is what makes the panel's
#: grid the same list of boxes as the reference's own advanced search, down to
#: the four no item of the corpus lands in -- ``Fist``, ``2H Sword``, ``2H
#: Mace`` and ``Rifle``, which the reference keeps *"because UNITTYPE can still
#: emit them"*.
#:
#: Not the empty kind, which is deliberately absent from the lists above: an
#: item with no kind word is a ``Quest Item`` and reads as one, and an item with
#: no data file at all is in ``Other`` by the tool's own decision.  The aliased
#: spellings are absent for the reason :data:`KIND_ALIASES` gives -- they are
#: the same leaves.
KIND_PLACES: frozenset[Place] = frozenset(
    (group, subgroup, kind)
    for group, subgroup, kinds in TYPE_GROUPS
    for kind in kinds
)


def canonical_kind(kind: str) -> str:
    """The one word for a kind, whatever the game calls it.

    ``canonical_kind('Chaos Ember')`` is ``'Socketable'``,
    ``canonical_kind('Healthpotion')`` is ``'Potion'``,
    ``canonical_kind('1H Sword')`` is ``'Sword'``,
    ``canonical_kind('Rifle')`` is ``'Shotgonne'``, and every other kind comes
    back untouched.  It is applied where a kind is *read* -- see
    :func:`tl2stash.gamedata._appearance` -- as well as by :func:`group_of`, so
    the rail, the filter and the card's type line all say the same word; the
    item's own name, ``Chaos Ember`` or ``Grand Health Potion``, is where the
    item stays named.
    """
    return KIND_ALIASES.get(kind.upper(), kind)


def group_of(kind: str) -> tuple[str, str | None]:
    """Where a kind belongs: ``('Weapons', 'One-Handed')`` for ``'1H Sword'``.

    An unknown kind comes back as ``(OTHER, None)``.  The empty one does not:
    :data:`KIND_ALIASES` reads it as the ``Quest Item`` the game's ``QUESTITEM``
    token names, which is ``Misc`` -- a quest object is a Quest-tier item in
    which the game never needed to say *what* it is, and there is no group for
    quest objects and should not be one.  That is what keeps ``Other`` meaning
    only one thing, an item whose kind nothing here recognises; an item with no
    data file at all never reaches this function, because its kind is ``Other``
    by the tool's own decision and not by anything the game wrote.

    A kind is canonicalised first, so every word the game writes lands with the
    kind it is -- ``Blood Ember`` with Socketable, ``PANTS`` with Leggings, an
    empty word with Quest Item -- and a caller that reads kinds without going
    through :func:`canonical_kind` still gets the right group.
    """
    if not kind:
        return "Misc", None
    return _BY_KIND.get(canonical_kind(kind).upper(), (OTHER, None))
