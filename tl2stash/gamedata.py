"""The game's data, read once and kept.

The stash file says an item has the effect ``MELEEDAMAGEBONUS`` worth 25.  It
does not say that reads as "+25 Melee weapon damage bonus", because that
sentence lives in the game's data files, not in the save.  This is the layer
that supplies it.

Twelve and a half thousand files is a lot to read, and it works out cheap:
each is a few kilobytes, they are deflated separately in the archive so
reading one does not disturb the others, and the whole set loads in a fraction
of a second.  So it is loaded once, eagerly, at startup, and there is no cache
to invalidate, no lazy path to get wrong and no background thread.

Reading is forgiving by design.  A file that will not parse is recorded and
skipped rather than raised: the tool's job is showing the player their items,
and refusing to start because one of twelve thousand data files is odd would
be the wrong trade.  The items come from the save file and are unaffected
either way.

Format derived by reading ``DATA.PAK`` and ``DATA.PAK.MAN`` directly; see
:mod:`tl2stash.pak` and :mod:`tl2stash.dat`.  Not transcribed from another
implementation.
"""

from __future__ import annotations

import math
import os
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from . import augments as _augments
from .card import DAMAGE_PER_SECOND, Augment
from .dat import (
    VAR_AFFIX,
    VAR_AFFIX_EFFECT,
    VAR_AFFIX_LEVEL,
    VAR_BADDES,
    VAR_BADDESOT,
    VAR_COUNT,
    VAR_DISPLAYPRECISION,
    VAR_GOODDES,
    VAR_GOODDESOT,
    VAR_NAME,
    VAR_ARMOR_ELECTRIC,
    VAR_ARMOR_FIRE,
    VAR_ARMOR_ICE,
    VAR_ARMOR_MIN_WEIGHT,
    VAR_ARMOR_MULT,
    VAR_ARMOR_PHYSICAL,
    VAR_ARMOR_POISON,
    VAR_ARMOR_WEIGHT,
    VAR_BASEFILE,
    VAR_DAMAGE_ELECTRIC,
    VAR_DAMAGE_FIRE,
    VAR_DAMAGE_ICE,
    VAR_DAMAGE_PHYSICAL,
    VAR_DAMAGE_POISON,
    VAR_DAMAGE_TYPE,
    VAR_DEFENSE_REQUIRED,
    VAR_DEXTERITY_REQUIRED,
    VAR_DISPLAY_NAME,
    VAR_DURATION,
    VAR_EFFECT_GRAPH,
    VAR_EFFECT_TYPE,
    VAR_FLAVOR,
    VAR_ICON,
    VAR_LEVEL,
    VAR_LEVEL_REQUIRED,
    VAR_MAGIC_REQUIRED,
    VAR_MAXDAMAGE,
    VAR_MINDAMAGE,
    VAR_RANGE,
    VAR_RARITY_DMG_MOD,
    VAR_SET,
    VAR_SLOT_BASE,
    VAR_SPEED,
    VAR_SPEED_DMG_MOD,
    VAR_STRENGTH_REQUIRED,
    VAR_UNITTYPE,
    VAR_UNITTYPES,
    VAR_UNIT_GUID,
    DatFile,
    DatNode,
)
from .item import as_float
from .pak import PakFile, PakIndex
from .taxonomy import canonical_kind

__all__ = [
    "ARCHIVE_NAME",
    "Appearance",
    "Derived",
    "GameData",
    "Requirements",
    "SetBonus",
    "SetRung",
    "archive_path",
    "find_install",
    "read_unit_type",
]

#: The files worth reading, out of the archive's 70,443.  An item's numbers
#: come from the save file; what these supply is the *wording* -- effect
#: names, description templates, and the names of the stash's bags.  The rest
#: of the archive is models, textures, sounds and UI layouts.
WANTED = (
    "MEDIA/AFFIXES/ITEMS/",
    "MEDIA/AFFIXES/GEMS/",
    "MEDIA/SKILLS/",
    "MEDIA/UNITS/ITEMS/",
    "MEDIA/TRIGGERABLES/",
    "MEDIA/SETS/",
    "MEDIA/STATS/",
    "MEDIA/GRAPHS/STATS/",
    "MEDIA/UNITS/MONSTERS/PETS/",
    "MEDIA/INVENTORY/",
    "MEDIA/EFFECTSLIST.DAT",
)

#: The manifest, and the name of the file an install is recognised by.  Both
#: sit in ``PAKS`` rather than beside the executable.
ARCHIVE_DIR = "PAKS"
ARCHIVE_NAME = "DATA.PAK.MAN"

#: Only these parse as DAT.  The prefixes above also sweep up a couple of
#: thousand ``.LAYOUT`` files -- CEGUI window layouts, which are a different
#: format entirely and fail on the first count they read.
DATA_SUFFIX = ".DAT"

EFFECTSLIST = "MEDIA/EFFECTSLIST.DAT"

#: Where an item's own numbers live.  The save file records an item's level,
#: its armour and its physical maximum damage; everything else about how hard
#: it hits has to come from here, reached by the unit id the item carries.
ITEMS_DIR = "MEDIA/UNITS/ITEMS/"

#: A set's own file, named the way an item's ``SET`` field spells it --
#: ``U_TRUE_NORTH`` for ``MEDIA/SETS/U_TRUE_NORTH.DAT``.  What one of these
#: holds is the ladder: the set's name, and a rung per bonus.
SETS_DIR = "MEDIA/SETS/"

#: A socketable's affixes, and the one thing about a socketable that its own
#: file does not say.  A gem is not one bonus, it is one bonus *per host*: the
#: Flame Ember is ``+29 Fire Damage`` in a weapon and ``+58 Fire Armor`` in a
#: ring, and the item's file names only the affix for one of the two -- so
#: which bonus goes where is read here, off the affixes, into
#: :meth:`GameData.socket_target`.
GEMS_DIR = "MEDIA/AFFIXES/GEMS/"

#: The other shelf a socketable's affixes are kept on.  Only the gems live
#: under ``GEMS``: a *unique* socketable -- Vyrax's Heartfire, the Eyes of
#: Gallo -- keeps its affixes here among the ordinary ones, one file per host,
#: and states the host list the same way.  It is the directory :data:`WANTED`
#: already reads, named here because it is read for the same reason a gem's is.
ITEM_AFFIX_DIR = "MEDIA/AFFIXES/ITEMS/"

#: The damage types, as the four letters a data file writes them in, against
#: the number the save file's effect record uses.  All six words in the
#: archive's set ladders are here; the numbers are the ones
#: :mod:`tl2stash.tooltip` reads a record's ``damage_type`` with, so that a
#: bonus from a set file and a bonus from an item are written the same way.
#:
#: ``PHYSICAL`` is 0 rather than 1 because that is the number the game's own
#: records carry: 0 and 1 are both "Physical" there, and 0 is the one used.
DAMAGE_TYPE_IDS = {
    "PHYSICAL": 0x00,
    "FIRE": 0x02,
    "ICE": 0x03,
    "ELECTRIC": 0x04,
    "POISON": 0x05,
    "ALL": 0x06,
}

#: The by-level graphs: one curve per file, a list of nodes each carrying a
#: level and the value there -- the two field ids are plain small numbers
#: rather than hashed names, which is how a graph node is told apart from
#: every other node in the archive.
#:
#: Every file in the directory is read, not just the two named below, because
#: an effect names its own curve and 36 of them name one: a set rung's numbers
#: are a nominal scaled by whichever graph its effect points at.  The two here
#: are the ones the damage and armour arithmetic is built on.
GRAPHS_DIR = "MEDIA/GRAPHS/STATS/"
GRAPH_WEAPON_DAMAGE = "MEDIA/GRAPHS/STATS/BASE_WEAPON_DAMAGE.DAT"
GRAPH_ARMOR = "MEDIA/GRAPHS/STATS/ARMOR_PLAYER_BYLEVEL_FORSET.DAT"
GRAPH_LEVEL_VAR = 120
GRAPH_VALUE_VAR = 121

#: The divisor a set rung's nominal is scaled by: ``shown = nominal * curve /
#: 100``.  The same 100 that turns a share into a percentage, and the curves
#: are stated the same way -- ``STEAL_HEALTH_AND_MANA`` at level 1 is 5.25, so
#: a nominal 375 is shown as 20.
GRAPH_PERCENT = 100.0

#: The requirement graphs, by the field each answers for.
#:
#: Four of the five requirement fields are stated as a percentage of one of
#: these curves at the item's own level: an item stating ``MAGIC_REQUIRED``
#: 100 at level 70 asks for the level-70 value of ``ITEM_MAGIC_REQUIREMENTS``,
#: which is 170 -- the item's file says 100 and the player reads Focus 170.
#:
#: ``LEVEL_REQUIRED`` is the exception and the reason ``LEVEL`` is in here
#: separately: a level requirement is a level, not a magnitude, so a file that
#: states one is taken at its word.  The curve answers for the items that
#: state nothing -- which is most of them -- and then which curve depends on
#: the item: an item with no rarity of its own reads the ``NORMAL`` curve, a
#: socketable the ``SOCKETABLE`` one, and everything else the general curve.
#: Each of the two special curves stops early (NORMAL at level 50) and a level
#: past its end falls back to the general one.
REQUIREMENT_GRAPHS = {
    "LEVEL": "ITEM_LEVEL_REQUIREMENTS.DAT",
    "NORMAL": "ITEM_LEVEL_REQUIREMENTS_NORMAL.DAT",
    "SOCKETABLE": "ITEM_LEVEL_REQUIREMENTS_SOCKETABLE.DAT",
    "STRENGTH": "ITEM_STRENGTH_REQUIREMENTS.DAT",
    "DEXTERITY": "ITEM_DEXTERITY_REQUIREMENTS.DAT",
    "MAGIC": "ITEM_MAGIC_REQUIREMENTS.DAT",
    "DEFENSE": "ITEM_DEFENSE_REQUIREMENTS.DAT",
}

#: The four requirement fields that scale, and the attribute each one is shown
#: as.  The words are the game's, not the fields': Torchlight 2 renamed
#: Torchlight 1's Magic to Focus and its Defense to Vitality, and this is
#: where a tooltip stops saying the old ones.
REQUIREMENT_FIELDS = (
    ("STRENGTH", VAR_STRENGTH_REQUIRED, "Strength"),
    ("DEXTERITY", VAR_DEXTERITY_REQUIRED, "Dexterity"),
    ("MAGIC", VAR_MAGIC_REQUIRED, "Focus"),
    ("DEFENSE", VAR_DEFENSE_REQUIRED, "Vitality"),
)

#: The tiers that read the NORMAL level curve -- the ones with no rarity of
#: their own for the game to name.  ``Normal`` is the game's word for a plain
#: item; the other three are what :func:`read_unit_type` calls a file that
#: names no rarity at all, which is a potion, a quest item or a book.  The
#: curve is the game's, read off its own tooltips: nine Normal items of level
#: 6 to 13, watched in game, land on NORMAL exactly where the general curve
#: runs a flat five too high.
NORMAL_TIERS = frozenset({"Normal", "Quest", "Level", ""})

#: The damage types, in the order the game lists them, with the field each
#: one's share is stated in.
DAMAGE_TYPES = (
    ("physical", VAR_DAMAGE_PHYSICAL, VAR_ARMOR_PHYSICAL),
    ("fire", VAR_DAMAGE_FIRE, VAR_ARMOR_FIRE),
    ("ice", VAR_DAMAGE_ICE, VAR_ARMOR_ICE),
    ("electric", VAR_DAMAGE_ELECTRIC, VAR_ARMOR_ELECTRIC),
    ("poison", VAR_DAMAGE_POISON, VAR_ARMOR_POISON),
)

#: The default for a modifier an item does not state.  Both of these are
#: percentages of a nominal 100%.
NO_MODIFIER = 100.0

#: The divisor that turns an armour weight into a multiplier.
ARMOR_SCALE = 1e6

# -- what a weapon's output is -----------------------------------------------
#
# Three numbers a weapon is chosen for and the save file holds none of: the
# Damage per Second, the seconds between swings, and the reach.  All three come
# out of the item's own data file, and the field that states the speed does not
# state seconds -- see :data:`VAR_SPEED`.

#: The divisor that turns the DAT's raw ``SPEED`` into seconds per swing,
#: written as the two whole numbers it actually is rather than as a decimal:
#: ``(250, 3)`` reads *divided by 250 thirds*, and :meth:`GameData._swing_seconds`
#: multiplies by the fraction's underside instead of dividing by it, which is
#: the arithmetic that comes out whole.
#:
#: A constant per weapon class, measured rather than assumed: over the items
#: the reference database and the game's own tooltips both carry, a raw speed
#: over this reproduces the rendered seconds to within 0.005 on all but three,
#: and those three are items whose own UNITTYPE contradicts the weapon they
#: are.  It is *not* a one-handed/two-handed split, which is a different axis:
#: bows and crossbows are held in two hands and divide by 125 exactly like the
#: one-handers, and a rifle divides by 100.
#:
#: The archive states twelve raw speeds -- 50, 60, 70, 75, 80, 90, 100, 110,
#: 120, 130, 140, 150 -- and over them the divisors above are the ones the
#: data warrants: 250/3 turns 60 into 0.72 and 140 into 1.68 exactly, where
#: the decimal 83.3333 turns them into 0.7200003 and 1.6800007.  That dust is
#: not cosmetic.  It costs the reference two things it does not get back: the
#: corpus comes out with 36 distinct second-values where the exact divisors
#: give 30, and 1.6800007 is over :data:`MAX_SWING`, so a Mace of the Twin
#: Gods loses the very lines it leads with -- which the reference then restores
#: out of a second database, the one whose own numbers say the seconds are
#: 1.68.  The dust also reaches the Damage per Second, because the reference
#: divides by the unrounded value while printing the rounded one: over the
#: 1,351 weapons it prices, its published dps is one lower than this tool's on
#: 42, every one of them two-handed, and on 28 of those the game's own data
#: agrees with this tool.
SPEED_DIVISOR = {
    "1HAXE": (125, 1),
    "1HMACE": (125, 1),
    "1HSWORD": (125, 1),
    "FIST": (125, 1),
    "WAND": (125, 1),
    "PISTOL": (125, 1),
    "BOW": (125, 1),
    "CROSSBOW": (125, 1),
    "2HAXE": (250, 3),
    "2HMACE": (250, 3),
    "2HSWORD": (250, 3),
    "POLEARM": (250, 3),
    "STAFF": (250, 3),
    "CANNON": (1000, 11),
    "RIFLE": (100, 1),
}

#: The class tokens a weapon's UNITTYPE is searched for, longest first so that
#: ``1HSWORD`` wins over ``SWORD`` and ``CROSSBOW`` over ``BOW``.  The bare
#: spellings at the end are for the weapons that carry no handedness at all --
#: monster and NPC weapons, nearly all of which are items the game never hands
#: a player -- and :data:`BARE_CLASS` reads those as the one-handed class of
#: their kind.
SPEED_CLASS_TOKENS = (
    "1HAXE",
    "1HMACE",
    "1HSWORD",
    "2HAXE",
    "2HMACE",
    "2HSWORD",
    "CROSSBOW",
    "POLEARM",
    "PISTOL",
    "CANNON",
    "RIFLE",
    "STAFF",
    "SWORD",
    "MACE",
    "BOW",
    "AXE",
    "WAND",
    "FIST",
)

#: What a bare class token is read as.  Axe, sword and mace are the one-handed
#: ones; a polearm or a staff says so in its own token.
BARE_CLASS = {"AXE": "1HAXE", "SWORD": "1HSWORD", "MACE": "1HMACE"}

#: The slowest swing the game ships, and the fastest.  Every speed in the
#: corpus sits in 0.4-1.68 -- 30 distinct values, and the reference database
#: publishes exactly those 30, no more and no fewer -- so anything outside the
#: range is not a speed and is dropped rather than shown as one.  The ceiling
#: is one of the 30 rather than a round number above them: the Mace of the
#: Twin Gods swings at exactly 1.68.
MAX_SWING = 1.68

#: The words the game puts in front of an attack speed, by the slowest swing
#: each one covers -- the bands off the game's own tooltips, which cover all 30
#: of its speeds with no ambiguity.  The middle one is "Average": the game has
#: no "Normal" attack speed, and anything past the last cutoff is "Very Slow".
SPEED_BANDS = (
    ("Very Fast", 0.72),
    ("Fast", 0.88),
    ("Average", 1.08),
    ("Slow", 1.21),
)
SLOWEST_BAND = "Very Slow"

#: The inventory files that name a *container*.  Not the ones beside them:
#: ``MEDIA/INVENTORY/BAG_ARMS_SLOT.DAT`` and its neighbours declare the block
#: a container numbers its slots from, a different space of numbers that
#: happens to overlap -- both have an entry 0.
CONTAINERS_DIR = "MEDIA/INVENTORY/CONTAINERS/"

#: The three bags of the shared stash, in the order the game shows them.
SHARED_STASH = "SHARED_STASH_"

#: Which of an effect's four templates a ``description_type`` asks for, and
#: which to fall back on when the effect does not carry that one.  The two "OT"
#: variants are the ones whose text mentions ``[DURATION]``; the others
#: describe an effect that is simply always on.
#:
#: The fallback is because the pair is not always complete -- 208 of the 239
#: effects carry GOODDES and 198 carry BADDESOT -- and an always-on effect
#: with no duration in its wording is a far better thing to show than nothing.
TEMPLATE_FOR_TYPE = {
    0x00: (VAR_GOODDES, VAR_GOODDESOT),
    0x01: (VAR_GOODDES, VAR_GOODDESOT),
    0x02: (VAR_GOODDESOT, VAR_GOODDES),
    0x03: (VAR_BADDES, VAR_BADDESOT),
    0x04: (VAR_BADDESOT, VAR_BADDES),
}

#: What to assume when an effect does not say how precise to be.  All 239
#: effects in the shipped game do say, so this is for mods.
DEFAULT_PRECISION = 1

#: What ``MEDIA/INVENTORY/CONTAINERS/SHARED_STASH_BAG_ARMS.DAT`` is called.
#: The save file records container 24, which is that file's own number.
SHARED_STASH_ARMS = "SHARED_STASH_BAG_ARMS"


@dataclass(frozen=True)
class Derived:
    """Numbers worked out from an item's own data file.

    The save file keeps only a weapon's physical *maximum* and an armour
    piece's armour, both already scaled; it has no minimum and no elemental
    part at all.  The data file the item was made from has all of them, but
    stated as pre-scale shares, so the two are combined here: the shares come
    from the file, and the level curve turns them into the numbers the player
    is shown.

    ``kind`` is ``"damage"`` or ``"armor"``, which is the only thing deciding
    the word in front of each line.  ``parts`` maps a damage type to its low
    and high ends, both the same number where the item does not vary.
    """

    kind: str
    parts: dict[str, tuple[int, int]]


@dataclass(frozen=True)
class Requirements:
    """What the game asks of the character who would use an item.

    Two kinds of gate, and the game grants equip on either: the player level,
    or the whole set of attributes, whichever the character reaches first.
    That is why the tooltip writes them as alternatives rather than as one
    list -- "and" would be a statement the game does not make.

    ``level`` is the player level the item asks for, and 0 for an item that
    asks for none.  ``socketing`` says the number is not a player level at
    all: on a socketable the same field is the *item* level the thing may be
    put into, which is a different question asked of a different number, and
    the label has to say which one it is.

    ``stats`` is the other half, in the order the game lists them -- Strength,
    Dexterity, Focus, Vitality -- and empty for an item that asks for none.
    """

    level: int
    socketing: bool
    stats: tuple[tuple[str, int], ...]


#: The words the game puts in front of an item's kind to say how good it is,
#: with the number of the archive's 6,262 item files that resolve to each.
#: Read off the archive rather than invented: these six are every first word
#: of every inherited ``UNITTYPE`` that is a tier, and the words that are not
#: here are kinds -- SPELL, MAP, FISH, SWORD, POTION.
#:
#: The keys are the game's own tokens and the values are the words shown, and
#: they differ for exactly one tier: the files say ``MAGIC`` and the player is
#: shown "Rare".  That is what the item databases call it -- TIDBI's whole tier
#: vocabulary is ``{RARE, UNIQUE, LEGENDARY}``, with no MAGIC word anywhere in
#: it -- and it is also what the *game's* own UI calls that colour.  The
#: samples taken off its item overlay read ``magical #319C00   rare #2182FF
#: unique #EF6100``: the blue is "rare" in the game's own vocabulary, and
#: "magical" is the green -- which no file of the game's states, so it is not
#: in this table.
QUALITY_WORDS = {
    "MAGIC": "Rare",  # 2,061
    "UNIQUE": "Unique",  # 1,742
    "NORMAL": "Normal",  # 1,660
    "QUESTITEM": "Quest",  # 151
    "LEGENDARY": "Legendary",  # 92
    "LEVEL": "Level",  # 35
}

#: :data:`QUALITY_WORDS` longest word first, so that a tier written run
#: together with its kind is split at the longest one it starts with.
_QUALITY_BY_LENGTH = tuple(
    sorted(QUALITY_WORDS.items(), key=lambda pair: -len(pair[0]))
)


@dataclass(frozen=True)
class Appearance:
    """What an item looks like, as opposed to what it does.

    Everything here comes from the item's own data file, reached by the guid
    in the save blob, and every field is inherited: an item states only its
    differences, so ``BERSERKER_01_BOOTS.DAT`` carries no ``UNITTYPE`` of its
    own and takes ``'UNIQUE BOOTS'`` from three files up the chain.

    ``tier`` is one of :data:`QUALITY_WORDS`' values, or the empty string for
    an item whose file says something that is not a tier at all -- a spell, a
    fish, a potion.  The empty string is not a failure and not a guess: it
    means the item has no rarity to show, and it is drawn the way an unknown
    one is.

    A set piece carries the tier of the rarity it displaced: the archive's 556
    set items are all ``UNIQUE`` (346) or ``MAGIC`` (210), and not one calls
    itself a set.  So set membership is ``set_name`` rather than a tier -- it
    is something an item is *in*, not something it is, and the game colours a
    set piece as the rare or unique thing its own file says it is.

    ``icon`` is a name under ``MEDIA/UI/ICONS`` and is not a path; turning it
    into pixels is :mod:`tl2stash.icons`' job, and most items resolve.
    """

    tier: str
    type_name: str
    icon: str | None
    set_name: str | None
    item_level: int


def _appearance(stated: dict[int, DatNode]) -> Appearance:
    """Read the appearance fields off an item's inherited variables.

    The kind goes through :func:`~tl2stash.taxonomy.canonical_kind`, so the
    four words the game spells its own way -- ``CHAOS EMBER`` and its three
    siblings -- read as the ``Socketable`` they are, which is what the item's
    card says and what the rail files them under.
    """
    tier, type_name = read_unit_type(_text(stated, VAR_UNITTYPE) or "")
    return Appearance(
        tier=tier,
        type_name=canonical_kind(type_name),
        icon=_text(stated, VAR_ICON),
        set_name=_text(stated, VAR_SET),
        item_level=int(_number(stated, VAR_LEVEL) or 0),
    )


#: Where a gem affix says which host it is for, in its own file name, against
#: the word the game's files write that host in.  The name is read first and
#: the children only when it says nothing -- see :func:`_gem_hosts`.
_HOST_MARKERS = (("_ARMOR", "TRINKET"), ("_WEAPON", "WEAPON"))


def _gem_hosts(stem: str, data: DatFile) -> tuple[set[str], set[str], bool]:
    """A gem affix's hosts, what it grants, and whether its *name* said so.

    The effect and the host sit on different children -- ``GEM_RUBY.DAT``
    states ``WEAPON`` on one and ``DAMAGE BONUS`` on the next -- so the
    pairing is the *file's* and not the child's: everything an affix grants,
    it grants to every host that affix is for.  Measured over the archive's
    177 gem affixes: 302 children state a host as ``UNITTYPE`` and 20 as
    ``UNITTYPES``, and not one states both.

    The file's *name* is asked first, because on the newer embers it is the
    one that is right.  Those affixes state both hosts on their children and
    still belong to one pool: ``GEM_CHAOSEMBER_ARMOR_POTIONEFFICIENCY`` calls
    itself armor and its children say ``TRINKET`` and ``WEAPON``;
    ``GEM_VOIDEMBER_ARMOR_MANA`` says ``VOID EMBER``, which is not a host at
    all.  The reference database settles it -- potion efficiency, dodge and
    the rest of the ``_ARMOR`` family are its "one of 9" Armor/Trinket pool,
    and the ``_WEAPON`` family its "one of 11" weapon pool.  Over all 177
    names every ``_ARMOR`` one is in the first pool and every ``_WEAPON`` one
    in the second; the 69 where the name and the children disagree are all
    embers, and the children are the ones that are wrong.

    The older gems carry neither marker -- ``GEM_RUBY``, ``GEM_FISH_DEVIL``
    -- and there the children are what says it.  Which of the two spoke is
    the third thing returned, because the two are not worth the same at the
    lookup: see :meth:`GameData.socket_target`.
    """
    hosts: set[str] = set()
    granted: set[str] = set()
    for node in data.root.children:
        host = node.text(VAR_UNITTYPE) or node.text(VAR_UNITTYPES)
        if host:
            hosts.add(host.upper())
        effect = node.text(VAR_AFFIX_EFFECT)
        if effect:
            granted.add(effect.upper())
    named = {host for marker, host in _HOST_MARKERS if marker in stem.upper()}
    return (named or hosts), granted, bool(named)


#: The host words, as an affix's applicability list spells them against the
#: word :mod:`tl2stash.tooltip` writes.  ``ARMOR`` and ``TRINKET`` are *one*
#: host there: a gem in a ring and a gem in a breastplate are granted the same
#: bonus, and the game spells the host the one way for both, so the archive's
#: two words for it fold into one.
_SOCKET_HOST_WORDS = {"WEAPON": "WEAPON", "TRINKET": "TRINKET", "ARMOR": "TRINKET"}


def _applicability_hosts(data: DatFile) -> tuple[set[str], set[str]]:
    """An item affix's hosts and what it grants, read off its own children.

    A gem's affixes are filed by host in their *names*, and on the newer embers
    those names are the only thing that is right -- see :func:`_gem_hosts`.  An
    item affix has no such name to go on: ``UNIQUE_DEGRADE_ARMOR2`` wears
    ``_ARMOR`` and is a weapon affix, so applying the name-marker shortcut here
    would tag it with the opposite host.  What is read instead is the list the
    file itself states -- the one the reference database reads -- which is the
    child whose node id is ``UNITTYPES``, holding the unit types the affix may
    be applied to.  ``WEAPON`` and ``ARMOR`` are the two that name a host.

    Everything else in such a list is a *unit type* and is dropped: an affix
    for studs states ``STUD``, one for a unique socketable states ``UNIQUE
    SOCKETABLE``, and a unit type is not a place a bonus is granted to.  That
    is most of what is written there -- measured over the archive, 1,390 of the
    1,688 item affixes state an applicability list and the commonest word on
    them is ``UNIQUE SOCKETABLE`` at 636, against 451 weapons and 989 of the
    two armor words -- and 1,136 of those lists hold more than one entry, so it
    is also the reason the entries have to be read as a list rather than as the
    one value a mapping would have kept.

    Both host words are kept when both are stated, which is what makes the one
    ambiguous case fall out of :meth:`GameData.socket_target` on its own: an
    affix for either host grants its bonus to both, and there is no one of them
    to name.
    """
    hosts: set[str] = set()
    granted: set[str] = set()
    for node in data.root.children:
        if node.node_id == VAR_UNITTYPES:
            # Both spellings, as the gems' lists use both, and every entry of
            # them: see :meth:`DatNode.texts`.
            for word in node.texts(VAR_UNITTYPE) + node.texts(VAR_UNITTYPES):
                host = _SOCKET_HOST_WORDS.get(word.upper())
                if host is not None:
                    hosts.add(host)
        effect = node.text(VAR_AFFIX_EFFECT)
        if effect:
            granted.add(effect.upper())
    return hosts, granted


def read_unit_type(unit_type: str) -> tuple[str, str]:
    """``'UNIQUE 1HSWORD'`` into its tier and its kind.

    The two arrive in one string and there is no separator to trust: the
    archive writes ``'UNIQUE BOOTS'``, ``'UNIQUE SHOULDER ARMOR'`` and
    ``'UNIQUECANNON'`` alike.  So the first word is read as a tier when it is
    one of the six the game actually uses (see :data:`QUALITY_WORDS`), and
    when it is not, the tier is taken from the start of it instead -- longest
    quality word first, and only while a kind is left over.

    The run-together spelling is rare -- 23 of the archive's 6,262 item files
    are ``UNIQUECANNON`` -- but it is not nothing, and the reference database
    reads those items as Unique (``The Rabble-Rouser``, ``q: "Unique"``,
    ``ut: "UNIQUECANNON"``), which is what a player sees in the game.  A first
    word that merely *starts* with a quality word and has no such file behind
    it is unaffected: the words that are kinds -- ``SWORD``, ``POTION``,
    ``FISH``, ``SPELL`` -- begin with none of the six.

    The kind comes back as words for reading.  ``'1HSWORD'`` is the game's
    own spelling and the player is shown ``1H Sword``.

    A tier that is still not one of the six comes back as the empty string
    rather than as a guess: it means the string has no tier in it at all, and
    the whole of it is the kind.
    """
    words = unit_type.replace("_", " ").split()
    if not words:
        return "", ""

    tier = QUALITY_WORDS.get(words[0])
    if tier is not None:
        return tier, _readable_type(words[1:])

    for word, written in _QUALITY_BY_LENGTH:
        if words[0].startswith(word) and len(words[0]) > len(word):
            return written, _readable_type([words[0][len(word) :], *words[1:]])

    return "", _readable_type(words)


def _readable_type(words: list[str]) -> str:
    """A kind as words: ``['1HSWORD']`` is ``'1H Sword'``.

    The archive's kinds are run together and shouted, and the two-letter
    handedness prefixes are the only ones that split at a meaningful place --
    ``1HSWORD`` is a one-handed sword and ``2HSTAFF`` a two-handed staff,
    while ``SHOULDERARMOR`` is simply two words.
    """
    return " ".join(_spaced(word) for word in words)


def _spaced(word: str) -> str:
    return re.sub(r"^([12])H", r"\1H ", word).title()


@dataclass(frozen=True)
class SetBonus:
    """One effect a rung of a set's ladder grants, as the set's files state it.

    Shaped like an :class:`~tl2stash.item.Effect` on purpose.  A set bonus is
    written the way an item's own affix is -- the same wording, the same
    substitution -- so this goes to the same machinery a record out of the save
    file goes through, and there is one account of how a stat reads.

    The two are not *stored* the same way, which is the whole of the
    difference.  A save file's record holds its values as four bytes that are
    really a float; a data file states the same numbers as numbers, and as a
    list in the order the effect's own schema names them.  ``DRAW MANA`` is
    the case that shows it: its five numbers are the per-monster minimum, the
    per-monster maximum, the pulse rate, the radius and the target count, and
    its wording asks for the fourth of them by name.  So the first value is
    the one a ``[VALUE]`` hole wants and the rest follow in file order.

    ``damage_type`` is the number a save record would carry rather than the
    word the set file writes -- ``ICE`` is 3 -- so that a ``[DMGTYPE]`` hole
    is filled from one table instead of two.  It is always a number, never
    None: a bonus that states no type is Physical, which is what the game's
    records of those same bonuses carry.

    ``skill`` is the rung node's own ``NAME``, and it is what a ``[NAME]``
    hole wants.  The holes are rare among the set ladders -- a handful of
    rungs cast something -- and where they occur the name is the skill the
    cast runs, not the effect: VALKYRIE's rung is an effect under the name
    ``WC_Zombie Proc Skill``, whose display name is the ``raise shadowling``
    the player reads.  It is the node's ``NAME`` rather than the ``TYPE`` in
    ``values``' effect, and it is missing on 69 of the archive's 418 rung
    effects, which state their numbers and nothing else.

    A curve the effect names is *already applied* to ``values`` by the time
    this is built: what a set file states is a nominal, and the number the
    player reads is that nominal scaled to the rung's affix level.
    """

    #: The effect's own name, which is what ``EFFECTSLIST.DAT`` files it
    #: under: the node's ``TYPE``, not the affix name beside it.  It is unique
    #: where an affix name is not.
    name: str
    values: tuple[float, ...]
    duration: float
    damage_type: int
    skill: str | None = None

    @property
    def value(self) -> float:
        """What a ``[VALUE]`` hole wants, which is the first of the list.

        A set's bonus is not rolled, so there is no range to choose from:
        over the archive's 391 rungs, ``MIN`` and ``MAX`` are equal on every
        one of the 402 effects that state them.
        """
        return self.values[0] if self.values else 0.0


@dataclass(frozen=True)
class SetRung:
    """One rung of a set's ladder: how many pieces, and what that grants.

    ``count`` is how many of the set's pieces the player has to be wearing.  A
    rung can grant more than one effect -- 9 of the archive's 391 do, four
    apiece -- and a set can have more than one rung at the same count: Tundra
    asks for 2, 2 and 3, and the player reads one ``(2) Set`` with both of its
    lines under it.  So a count appears at most once here, and what the file
    spelled as two rungs is one.
    """

    count: int
    bonuses: tuple[SetBonus, ...]


def archive_path(install: str | Path) -> Path:
    """The manifest for an install, whether given the install or its ``PAKS``.

    Accepting both is not tidiness: the registry value the game writes is the
    install directory, but someone passing a path by hand will just as often
    point at the folder they can see the file in.
    """
    install = Path(install)
    if install.name.upper() == ARCHIVE_DIR:
        return install / ARCHIVE_NAME
    return install / ARCHIVE_DIR / ARCHIVE_NAME


class GameData:
    """The game's data files, indexed and ready."""

    __slots__ = (
        "containers",
        "failed",
        "files_read",
        "install",
        "_affix_effects",
        "_armor_curve",
        "_augments",
        "_by_name",
        "_display_names",
        "_effects",
        "_effect_curves",
        "_effect_order",
        "_item_files",
        "_item_guids",
        "_require_curves",
        "_sets",
        "_socket_targets",
        "_stash_tabs",
        "_weapon_curve",
    )

    def __init__(
        self,
        install: Path,
        by_name: dict[str, DatNode],
        display_names: dict[str, str],
        effects: dict[str, DatNode],
        effect_order: list[DatNode],
        affix_effects: dict[str, set[str]],
        containers: dict[int, str],
        sets: dict[str, DatNode],
        failed: list[tuple[str, str]],
        files_read: int,
        item_files: dict[str, DatFile],
        item_guids: dict[int, DatFile],
        weapon_curve: dict[int, float],
        armor_curve: dict[int, float],
        effect_curves: dict[str, dict[int, float]],
        socket_targets: dict[str, str],
        require_curves: dict[str, dict[int, float]] | None = None,
        augments: dict[str, tuple[Augment, ...]] | None = None,
    ) -> None:
        self.install = install
        self._by_name = by_name
        self._display_names = display_names
        self._effects = effects
        self._effect_curves = effect_curves
        self._effect_order = effect_order
        self._affix_effects = affix_effects
        self.containers = containers
        self._sets = sets
        self.failed = failed
        self.files_read = files_read
        self._item_files = item_files
        self._item_guids = item_guids
        self._weapon_curve = weapon_curve
        self._armor_curve = armor_curve
        self._socket_targets = socket_targets
        self._require_curves = require_curves or {}
        self._augments = augments or {}
        self._stash_tabs: list[int] | None = None

    def __repr__(self) -> str:
        return (
            f"<GameData {self.files_read} files, {len(self._by_name)} named, "
            f"{len(self._effects)} effects, {len(self.failed)} unreadable>"
        )

    # -- loading ----------------------------------------------------------

    @classmethod
    def load(
        cls,
        install: str | Path,
        augments: dict[str, tuple[Augment, ...]] | None = None,
    ) -> "GameData":
        """Read every file in :data:`WANTED` out of the archive.

        ``augments`` is the reference database's table of what an item's
        augment task would grant, which is not game data at all and is not in
        the archive -- see :mod:`tl2stash.augments`.  ``None`` looks for it in
        the usual places; ``{}`` says there is none, which is what a caller
        that wants a card drawn from the game's own files alone passes.

        Raises whatever :class:`~tl2stash.pak.PakError` the archive gives if
        it cannot be opened at all; individual files that will not parse are
        collected in :attr:`failed` instead.
        """
        install = Path(install)
        man_path = archive_path(install)
        index = PakIndex.read(man_path)
        pak_path = man_path.with_suffix("")

        by_name: dict[str, DatNode] = {}
        display_names: dict[str, str] = {}
        effects: dict[str, DatNode] = {}
        effect_order: list[DatNode] = []
        affix_effects: dict[str, set[str]] = {}
        containers: dict[int, str] = {}
        sets: dict[str, DatNode] = {}
        failed: list[tuple[str, str]] = []
        item_files: dict[str, DatFile] = {}
        item_guids: dict[int, DatFile] = {}
        curves: dict[str, dict[int, float]] = {}
        effect_curves: dict[str, dict[int, float]] = {}
        socket_hosts: dict[str, set[str]] = {}
        socket_named: dict[str, set[str]] = {}
        socket_items: dict[str, set[str]] = {}
        read = 0

        with PakFile(pak_path, index) as pak:
            for entry in index.matching(list(WANTED)):
                path = entry.name.upper()
                if not path.endswith(DATA_SUFFIX):
                    continue
                try:
                    data = DatFile.parse(pak.read(entry.name))
                except Exception as exc:  # noqa: BLE001 -- one bad file is not fatal
                    failed.append((entry.name, str(exc)))
                    continue
                read += 1

                if path.startswith(GRAPHS_DIR):
                    curves[path] = _graph_points(data)

                if path.startswith(ITEMS_DIR):
                    # An item file is kept whole, under its own path, because
                    # its numbers are partly its own and partly inherited: what
                    # it does not state it takes from the file it names as its
                    # base, and that chain has to be walked at lookup time.
                    item_files[_data_path(entry.name)] = data
                    guid = data.root.text(VAR_UNIT_GUID)
                    if guid:
                        # The file writes the id as a decimal string and the
                        # save file writes it as eight bytes, so the two have
                        # to be brought to the same shape.  The sign matters:
                        # half of the archive's ids are written negative, for
                        # the same bytes the save reads as a large positive.
                        try:
                            number = int(guid)
                        except ValueError:
                            pass
                        else:
                            item_guids.setdefault(number & 0xFFFFFFFFFFFFFFFF, data)

                if path == EFFECTSLIST:
                    effect_order = list(data.root.children)
                    # Keys are normalised once here rather than on every
                    # lookup; the file's own spelling is mixed case.
                    effects = {
                        node.name.upper(): node
                        for node in effect_order
                        if node.name
                    }

                if path.startswith(CONTAINERS_DIR):
                    found = _container_entry(data)
                    if found is not None:
                        containers[found[0]] = found[1]

                if path.startswith(GEMS_DIR):
                    # The two shelves again, one per kind of claim: what the
                    # affix's own name states, and what only its children do.
                    stem = path.rsplit("/", 1)[-1][: -len(DATA_SUFFIX)]
                    hosts, granted, stated = _gem_hosts(stem, data)
                    shelf = socket_named if stated else socket_hosts
                    for effect in granted:
                        shelf.setdefault(effect, set()).update(hosts)

                if path.startswith(ITEM_AFFIX_DIR):
                    # A unique socketable's affixes, which are read the way the
                    # reference database reads them -- off the applicability
                    # list -- and filed apart from the gems': what a gem affix
                    # says is the answer for an effect, and an item affix is
                    # only heard where no gem has one.
                    hosts, granted = _applicability_hosts(data)
                    if hosts:
                        for effect in granted:
                            socket_items.setdefault(effect, set()).update(hosts)

                if path.startswith(SETS_DIR):
                    # A set's file, kept whole: the root *is* the set, and its
                    # children are the rungs of its ladder.  Filed under both
                    # names it answers to, because its two callers have one
                    # each -- an item's ``SET`` field spells the internal name
                    # and the card draws the display name.
                    for spelling in (
                        data.root.text(VAR_NAME),
                        data.root.name,
                        data.root.text(VAR_DISPLAY_NAME),
                    ):
                        if spelling:
                            sets.setdefault(spelling.upper(), data.root)

                for node in data.root.walk():
                    name = node.name
                    if name:
                        # First wins: files are read in manifest order, which
                        # is stable, so the same node is picked every run.  An
                        # effect's name being taken from somewhere other than
                        # EFFECTSLIST is prevented in by_name.
                        by_name.setdefault(name.upper(), node)
                        # The name to *show* for a thing, where it has one.
                        # Only skills and monsters carry DISPLAYNAME, so a
                        # node without one never enters this index -- which is
                        # what makes it usable: an affix and the skill it
                        # grants can share a NAME, and the affix is not what
                        # the player is being told about.
                        shown = node.text(VAR_DISPLAY_NAME)
                        if shown:
                            display_names.setdefault(name.upper(), shown)
                        if path != EFFECTSLIST:
                            # An affix's effect node, naming the effect it
                            # grants.  EFFECTSLIST's own effect nodes carry
                            # this variable too, holding 'Value' or 'Percent'
                            # -- the label of the number, not an effect -- so
                            # they are left out.
                            granted = node.text(VAR_AFFIX_EFFECT)
                            if granted:
                                affix_effects.setdefault(name.upper(), set()).add(
                                    granted.upper()
                                )

        # Which of the two hosts each gem-granted effect belongs to.  An
        # affix that states its host in its own *name* is believed over one
        # that leaves it to its children, because the marker-named children
        # are the ones measured wrong: all 69 affixes whose name and children
        # disagree are embers, and the children are wrong in every one of them
        # -- naming both hosts, or naming the ember itself.  So PERCENT
        # ATTACK SPEED is a weapon bonus, the chaos ember's `_WEAPON` affix
        # saying so and a fish's children saying otherwise.
        #
        # An effect every host gets is not a fact about a host, and one that
        # two affixes claim for two *different* hosts with nothing to choose
        # between them -- PERCENT LIFE STOLEN -- is not a fact about the
        # effect.  Neither gets a target, so what comes out is only the
        # splits: the effects a socketable grants to exactly one of the two.
        socket_targets: dict[str, str] = {}
        gem_effects = socket_named.keys() | socket_hosts.keys()
        for effect in gem_effects:
            # `or` and not a plain get: a named claim is the one that decides,
            # and the children are only heard where no name speaks at all.
            hosts = socket_named.get(effect) or socket_hosts.get(effect, set())
            if len(hosts) == 1:
                socket_targets[effect] = next(iter(hosts))

        # And then the item affixes, which are what a *unique* socketable's
        # lines are read off -- its own file names the two affixes and says
        # nothing else about them.  They are heard only where no gem affix
        # mentions the effect at all, and a tie the gems left is not such a
        # place: naming one host for an effect the gems grant to both would
        # write the wrong word on the gem's own line.  39 effects come out of
        # here -- 'CAST SKILL ON KILL AT TARGET', 'IMMOBILIZE', 'POISON' --
        # every one of them a socketable's own, and not one of them an effect
        # any gem affix states.
        for effect, hosts in socket_items.items():
            if len(hosts) == 1 and effect not in gem_effects:
                socket_targets[effect] = next(iter(hosts))

        # Which curve each effect's numbers scale with, resolved once here
        # rather than on every rung lookup.  Read after the loop, so it does
        # not matter whether the manifest lists the effects or the graphs
        # first.  An effect whose graph is missing is simply absent, and its
        # numbers go through unscaled -- which is what an effect that names no
        # graph at all gets too, and what a mod's half-read archive gets.
        for name, node in effects.items():
            stem = node.text(VAR_EFFECT_GRAPH)
            if not stem:
                continue
            if not stem.upper().endswith(DATA_SUFFIX):
                stem += DATA_SUFFIX
            points = curves.get(_data_path(GRAPHS_DIR + stem))
            if points:
                effect_curves[name] = points

        # The seven requirement graphs, pulled out of the directory by name.
        # One is missing from some installs -- a mod's archive need not carry
        # the NORMAL curve -- and an absent curve is an absent answer rather
        # than an error, so each is taken only if it is there.
        require_curves = {
            field: curves[_data_path(GRAPHS_DIR + stem)]
            for field, stem in REQUIREMENT_GRAPHS.items()
            if _data_path(GRAPHS_DIR + stem) in curves
        }

        return cls(
            install,
            by_name,
            display_names,
            effects,
            effect_order,
            affix_effects,
            containers,
            sets,
            failed,
            read,
            item_files,
            item_guids,
            curves.get(GRAPH_WEAPON_DAMAGE, {}),
            curves.get(GRAPH_ARMOR, {}),
            effect_curves,
            socket_targets,
            require_curves,
            _augments.load(install) if augments is None else augments,
        )

    # -- looking things up ------------------------------------------------

    def by_name(self, name: str) -> DatNode | None:
        """The node called ``name``.

        Effects are checked first.  Only ``MEDIA/EFFECTSLIST.DAT`` carries the
        description templates, and a name is not unique across the archive --
        an affix and the effect it applies can share one, and the affix is no
        use for rendering.
        """
        if not name:
            return None
        key = name.upper()
        return self._effects.get(key) or self._by_name.get(key)

    def display_name(self, name: str) -> str | None:
        """What the player is shown for the thing ``name``, if it has a name.

        A node's ``NAME`` is its internal id and its ``DISPLAYNAME`` is what
        the player reads, and the two are not the same thing.  A skill is
        ``spell_fireball`` under the first and ``Fireball III`` under the
        second; a set is ``U_TRUE_NORTH`` and ``True North``.

        A handful of effects name a skill in their wording -- ``'[VALUE]%
        chance to cast [NAME] on kill'`` -- and the name that goes in the hole
        is the skill's.  The record in the save file names an affix, and for
        these the affix is named after the skill it grants: ``WC_PROC_FULLHEAL``
        is an affix under ``MEDIA/AFFIXES/ITEMS`` *and* a skill under
        ``MEDIA/SKILLS/ARBITER/WANDCHAOS``, and only the skill carries the
        display name ``'Fully Heal Self'``.  So the record's own name is the
        key, and it is looked up as a display name rather than as a node.

        ``None`` for a thing that has no second name, which is most of them.
        """
        if not name:
            return None
        return self._display_names.get(name.upper())

    def effect_for(self, name: str) -> DatNode | None:
        """The effect an item's effect record is talking about.

        The record in the save file names an *affix*, not an effect.  That
        name is not unique -- 107 different affixes are called ``OFFLAME
        DAMAGE BONUS``, granting everything from fire damage to dodge chance
        -- so the name alone cannot say which effect is meant.

        What each of those affixes does carry is a node naming the effect it
        grants, which is unique and which EFFECTSLIST has wording for.  When
        an affix name still leaves several, the item's own name settles it:
        ``OFTHEVAMPIRE LIFE STEAL`` is LIFE STEAL, not LIFE STEAL MASTER or
        PERCENT LIFE STOLEN, because that is the one it ends with.

        ``None`` when nothing settles it, which is the caller's cue to show
        the raw name rather than guess at wording.
        """
        if not name:
            return None
        key = name.upper()
        if key in self._effects:
            return self._effects[key]

        candidates = {
            granted
            for granted in self._affix_effects.get(key, ())
            if granted in self._effects
        }
        if len(candidates) == 1:
            return self._effects[next(iter(candidates))]
        for candidate in sorted(candidates, key=len, reverse=True):
            if key.endswith(candidate):
                return self._effects[candidate]
        return None

    def effect(self, index: int) -> DatNode | None:
        """The ``index``-th effect in ``MEDIA/EFFECTSLIST.DAT``.

        Position is meaningful there: each effect node's id spells out its own
        type name, so the file is a list and the order in it is the game's.
        """
        if 0 <= index < len(self._effect_order):
            return self._effect_order[index]
        return None

    @property
    def effect_count(self) -> int:
        return len(self._effect_order)

    def socket_target(self, node_name: str) -> str | None:
        """Which host a socketable's effect is granted to, or ``None``.

        ``'WEAPON'`` and ``'TRINKET'`` are the game's own words, as its affix
        files spell them; what the player is shown for them is
        :mod:`tl2stash.tooltip`'s business, the way every other wording is.

        Both shelves are read: a gem's affixes, filed by host in their names,
        and the item affixes a *unique* socketable's bonuses come off, whose
        host is the applicability list.  A gem's answer is the one that stands
        where the two have one between them.

        ``None`` covers the cases that have one answer here: an effect no
        socketable's affix describes at all -- every effect on every other kind
        of item -- one claimed for two hosts at once, and one two affixes claim
        for two different hosts with nothing to choose between them.  A line
        with no target is true wherever it is socketed, which is what not
        naming a host says.
        """
        if not node_name:
            return None
        return self._socket_targets.get(node_name.upper())

    def effect_template(self, node: DatNode, description_type: int) -> str | None:
        """The sentence this effect is written with, or ``None``.

        ``None`` means the data has no wording for this combination, which is
        ordinary: 31 of the game's 239 effects carry no positive description
        at all.
        """
        pair = TEMPLATE_FOR_TYPE.get(description_type)
        if pair is None:
            return None
        return node.text(pair[0]) or node.text(pair[1])

    def display_precision(self, node: DatNode) -> int:
        """How many decimals this effect's value is shown to."""
        value = node.number(VAR_DISPLAYPRECISION)
        return DEFAULT_PRECISION if value is None else int(value)

    # -- an item's own numbers --------------------------------------------

    def derived_for(self, item) -> Derived | None:
        """An item's damage or armour, as the game works it out.

        A save file records one number for a weapon -- its physical maximum,
        already scaled -- and nothing at all about how the damage is split
        between elements or what the low end is.  Bashdrill's whole damage
        story in the save file is ``72``.  What the player reads is
        ``Physical 52-74`` and ``Electric 77-110``, and the only place those
        exist is the item's own data file, which states the split as
        pre-scale shares rather than as numbers.

        So the two are combined.  The item's file gives how the damage is
        divided and how far the roll may vary; a by-level curve gives the
        magnitude at the item's level; and the arithmetic below turns the
        three into what is on screen.

        ``None`` when the item cannot be traced back to a file -- a potion or
        a spell has no unit id in the archive -- or when the file does not
        carry what the arithmetic needs.  A modded item lands here too, and
        the caller falls back to the save file's own number rather than
        showing nothing.
        """
        data = self._item_guids.get(item.guid & 0xFFFFFFFFFFFFFFFF)
        if data is None:
            return None

        stated = self._inherited(data)
        level = _number(stated, VAR_LEVEL)
        if level is None:
            return None
        level = int(level)

        shares = [
            (name, _number(stated, dmg) or 0.0) for name, dmg, _ in DAMAGE_TYPES
        ]
        total = sum(share for _, share in shares)

        if total > 0:
            curve = self._weapon_curve.get(level)
            low = _number(stated, VAR_MINDAMAGE)
            high = _number(stated, VAR_MAXDAMAGE)
            if curve is None or low is None or high is None:
                return None
            # The nominal hit is the curve's value for the level, adjusted by
            # the weapon's own speed and rarity, times the sum of the shares.
            nominal = (
                curve
                * _percent(_number(stated, VAR_SPEED_DMG_MOD))
                * _percent(_number(stated, VAR_RARITY_DMG_MOD))
                * total
                / 100.0
            )
            return Derived(
                "damage",
                {
                    name: _ends(low * nominal / 100.0 * share / total,
                                high * nominal / 100.0 * share / total)
                    for name, share in shares
                    if share
                },
            )

        weight = _number(stated, VAR_ARMOR_WEIGHT)
        mult = _number(stated, VAR_ARMOR_MULT)
        curve = self._armor_curve.get(level)
        if curve is None or not weight or not mult:
            return None
        low_weight = _number(stated, VAR_ARMOR_MIN_WEIGHT) or weight
        parts = {}
        for name, _, armor in DAMAGE_TYPES:
            value = _number(stated, armor)
            if value:
                parts[name] = _ends(
                    value * low_weight * mult / ARMOR_SCALE * curve,
                    value * weight * mult / ARMOR_SCALE * curve,
                )
        return Derived("armor", parts) if parts else None

    def weapon_lead(self, item) -> tuple[str, ...]:
        """The lines a weapon leads with, and none for anything else.

        ``110 Damage per Second``, ``Fast attack speed (0.8 seconds)``,
        ``Weapon Range 12`` -- the headline number, and the two things that
        qualify it.  They come from three fields the save file does not hold at
        all: the speed, which the data file states raw and a weapon class's own
        divisor turns into seconds, the reach, and the damage the two are
        applied to, which :meth:`derived_for` works out.

        A list rather than three fields because each line stands or falls on
        its own, which is what the reference does and what the data warrants:
        a weapon whose damage the data does not resolve has no Damage per
        Second to lead with and still has a swing and still reaches.  The two
        that need the speed go together -- a dps is a damage range over a
        swing, so with no swing there is no number to divide -- and the reach
        needs nothing.

        Empty for everything that is not a weapon, which the reach's own field
        settles: every weapon in the archive states a ``RANGE`` and nothing
        else does, so an item that states none -- a piece of armour, a ring, an
        item with no data file behind it -- has nothing to lead with.
        """
        data = self._item_guids.get(item.guid & 0xFFFFFFFFFFFFFFFF)
        if data is None:
            return ()

        stated = self._inherited(data)
        reach = _number(stated, VAR_RANGE)
        if not reach:
            return ()

        lines: list[str] = []
        seconds = self._swing_seconds(stated)
        if seconds is not None:
            dps = _damage_per_second(
                self.derived_for(item), seconds, _flat_damage(item)
            )
            if dps is not None:
                lines.append(f"{dps} {DAMAGE_PER_SECOND}")
            lines.append(
                f"{_speed_band(seconds)} attack speed ({_written(seconds)} seconds)"
            )
        lines.append(f"Weapon Range {_written(reach)}")
        return tuple(lines)

    def _swing_seconds(self, stated: dict[int, DatNode]) -> float | None:
        """Seconds between swings, or ``None`` for a weapon that does not say.

        The raw speed over its class's divisor, kept only when what comes out
        is a speed the game could have shipped.  A raw number that names no
        class -- or names one the table does not cover -- is nothing rather
        than a guess: the number without its divisor is not seconds, so there
        is no honest arithmetic that turns it into any.

        The divisor is applied as its upside-down fraction -- ``raw * 3 / 250``
        rather than ``raw / (250 / 3)``, which is the same sum and not the same
        number: the second form lands 1.6800000000000002 on a raw 140 whose
        seconds are exactly 1.68, and so loses a swing that sits right on the
        ceiling.  See :data:`SPEED_DIVISOR`.
        """
        raw = _number(stated, VAR_SPEED)
        divisor = SPEED_DIVISOR.get(_speed_class(_text(stated, VAR_UNITTYPE)))
        if not raw or raw <= 0 or divisor is None:
            return None
        over, under = divisor
        seconds = raw * under / over
        return seconds if seconds <= MAX_SWING else None

    def requirements_for(self, item) -> Requirements | None:
        """What the item's own file says it asks of a character.

        Two rules, because the five fields are two kinds of number.

        The level is taken as the file states it.  Most items state nothing --
        the field is authored only where the level is meant to depart from the
        curve -- and those read the curve instead: the game's *NORMAL* curve
        for an item that has no rarity of its own, its *SOCKETABLE* curve for
        an item that goes in a socket, and the general curve for everything
        else.  Both of the special curves stop early -- NORMAL at level 50 --
        and a level past the end falls through to the general one.

        The four attributes are percentages of their own curve at the item's
        level, and this is the half that is easy to get wrong: the file states
        100 where the player reads Focus 170, because 100 is the whole of the
        curve at level 70.  An item that states none asks for no attribute at
        all, which is not zero of one -- a zero is the same as no line.

        ``None`` when the item cannot be traced back to a file at all: a
        modded item, or a machine whose install has moved on.  A caller
        without an answer falls back to the level the save file records rather
        than showing nothing.
        """
        data = self._item_guids.get(item.guid & 0xFFFFFFFFFFFFFFFF)
        if data is None:
            return None

        stated = self._inherited(data)
        level = _number(stated, VAR_LEVEL)
        if level is None:
            return None
        level = int(level)

        appearance = _appearance(stated)
        return Requirements(
            level=self._gate_level(stated, level, appearance),
            socketing=appearance.type_name == "Socketable",
            stats=self._gate_stats(stated, level),
        )

    def _gate_level(
        self, stated: dict[int, DatNode], level: int, appearance: Appearance
    ) -> int:
        """The player level an item asks for, or 0 when it asks for none.

        A stated requirement is the answer and the curves are the fallback,
        which is the one place this departs from the arithmetic the four
        attributes use.  The file's own number is a *level*: the items that
        state one are the ones authored to sit off the curve, and scaling it
        would move a level-67 gate on a level-70 item down to 52 -- the item
        would read as usable eleven levels before it can drop.
        """
        written = _number(stated, VAR_LEVEL_REQUIRED)
        if written:
            return int(written)

        if appearance.type_name == "Socketable":
            socket = self._curve("SOCKETABLE", level)
            if socket is not None:
                return socket
        elif appearance.tier in NORMAL_TIERS:
            normal = self._curve("NORMAL", level)
            if normal is not None:
                return normal
        return self._curve("LEVEL", level) or 0

    def _gate_stats(
        self, stated: dict[int, DatNode], level: int
    ) -> tuple[tuple[str, int], ...]:
        """The attributes an item asks for, each of its own curve at ``level``.

        An item that states no requirement for one asks for none of it, and so
        does one whose file states zero -- the archive writes a plain item's
        four as zero rather than leaving them out.

        A level past the end of a curve leaves the file's own number standing,
        which is the one case where an unscaled value is shown: it is a value
        the game's data does not have a curve for, and it is better than the
        nothing the alternative would show.  No shipped item reaches it; the
        curves run to level 105 and the archive's items stop there.
        """
        out = []
        for field, var_id, label in REQUIREMENT_FIELDS:
            written = _number(stated, var_id)
            if not written:
                continue
            factor = self._curve(field, level)
            value = int(written) if factor is None else _scaled(written, factor)
            out.append((label, value))
        return tuple(out)

    def _curve(self, field: str, level: int) -> int | None:
        """One requirement curve's value at a level, as a whole number."""
        points = self._require_curves.get(field)
        found = points.get(level) if points else None
        return None if found is None else int(found)

    def flavor_for(self, item) -> str | None:
        """The italic line under the name, for an item that has one.

        Looked up through the item's own data file rather than by its name,
        because a unique is not *named* what it is called: the node behind
        Wanderlust Pants is ``wanderer_02_pants_alt_set``, and searching the
        archive for ``Wanderlust Pants`` finds nothing at all.  The guid in
        the save file is what leads there, and it is the same guid the damage
        and armour are worked out from.

        ``None`` when the item cannot be traced to a file, or when it has no
        flavour text, which is most items.
        """
        data = self._item_guids.get(item.guid & 0xFFFFFFFFFFFFFFFF)
        if data is None:
            return None
        node = self._inherited(data).get(VAR_FLAVOR)
        return node.text(VAR_FLAVOR) if node is not None else None

    def augment_for(self, item) -> tuple[Augment, ...]:
        """What the item's own task would grant, and none for most items.

        Keyed on the item file's own ``NAME`` rather than on the guid the two
        lookups above share, because the table is the reference database's and
        that is how it files one: ``hammer_u02`` is a name, and the archive's
        items are named after their files.  The guid is still the way *in* --
        it is what leads to the file that states the name -- for the same
        reason it leads to everything else, and it is the one key the save
        file and the archive agree on.

        Empty for the 6,099 items with no task, for one whose task is already
        finished (which the caller settles, not this), and for every item on a
        machine with no reference database.
        """
        data = self._item_guids.get(item.guid & 0xFFFFFFFFFFFFFFFF)
        if data is None:
            return ()
        return self._augments.get((data.root.text(VAR_NAME) or "").lower(), ())

    def appearance_for(self, item) -> Appearance | None:
        """What an item is, and what it looks like: its tier, kind and icon.

        The save file carries none of this.  It says an item is called
        ``Bashdrill`` and holds so much damage; that it is a *unique fist
        weapon* drawn with ``icon_weapon_fist14`` is only in the file it was
        made from, which the guid leads to -- and that file states neither,
        so it comes down a chain of base files to get here.

        ``None`` when the item cannot be traced to a file, which is what a
        modded item is -- its data lives in the mod, not in ``DATA.PAK``, and
        the item's ``guid`` matches nothing.  Callers draw the item without a
        tier rather than refusing to draw it.

        A set's name is resolved here too, because it is the same lookup: the
        ``SET`` field holds ``'U_TRUE_NORTH'`` and the set's own file is what
        calls that ``'True North'``.  ``MEDIA/SETS`` is read for its display
        names along with everything else, so this costs no extra work.
        """
        data = self._item_guids.get(item.guid & 0xFFFFFFFFFFFFFFFF)
        if data is None:
            return None

        appearance = _appearance(self._inherited(data))
        if appearance.set_name is None:
            return appearance

        # The set's player-facing name, where its file gives one.  Falling
        # back to the internal id rather than to nothing: 'U_TRUE_NORTH' is
        # not what the player sees, but it is better than an unnamed set.
        return replace(
            appearance,
            set_name=self.display_name(appearance.set_name) or appearance.set_name,
        )

    def set_ladder(self, name: str) -> tuple[SetRung, ...]:
        """A set's bonuses, one rung per piece count, cheapest rung first.

        ``name`` may be either of the two names a set answers to: an item's
        ``SET`` field spells the internal one (``U_TRUE_NORTH``) and the card
        draws the display one (``True North``).  Both are indexed at load.

        Reading a ladder is two lookups deep.  The set's own file says how
        many pieces a rung takes and *which affix* it grants; the affix states
        the numbers, under one ``EFFECT`` child per effect it grants.  A rung
        can name more than one -- 9 of the archive's 391 grant four apiece.

        Gathered by piece count rather than listed as the file has them, for
        two reasons.  The file's order is not to be trusted -- 87 of the
        archive's 88 sets list their rungs in order and ``OUTLANDER_B25``
        lists 2, 3, 2 -- and two rungs can ask for the same count, which is
        one rung to the player: Tundra's ladder is 2, 2, 3 and its card reads
        ``(2) Set`` once, with both lines under it.

        Empty for a set the archive has not got, which is what a mod's set is.
        The caller draws the piece without a ladder rather than nothing.
        """
        root = self._sets.get((name or "").upper())
        if root is None:
            return ()

        rungs: dict[int, list[SetBonus]] = {}
        for child in root.children:
            affix = self._by_name.get((child.text(VAR_AFFIX) or "").upper())
            if affix is None:
                continue
            level = int(child.number(VAR_AFFIX_LEVEL) or 1)
            bonuses = [
                bonus
                for bonus in (
                    _bonus(effect, self._effect_curves, level)
                    for effect in affix.children
                    if effect.node_id == VAR_EFFECT_TYPE
                )
                if bonus is not None
            ]
            if bonuses:
                count = int(child.number(VAR_COUNT) or 0)
                # In the file's order within a count, which is the order the
                # game draws them in too.
                rungs.setdefault(count, []).extend(bonuses)
        return tuple(
            SetRung(count, tuple(bonuses))
            for count, bonuses in sorted(rungs.items())
        )

    def _inherited(self, data: DatFile) -> dict[int, DatNode]:
        """Which node states each of an item's fields, base files included.

        An item file gives only its differences: Bashdrill says how much of
        its damage is physical and how much electric, while the minimum and
        maximum percentages it rolls between are two files further up.  So the
        chain is walked and the *nearest* statement of a field wins.

        The value recorded is the node, not the number, because the same field
        can be stored as an int in one file and a float in another and only
        the node knows which it is.

        A chain that loops back on itself stops rather than running forever --
        the shipped data has no such loop, but a bad file should not be able
        to hang the tool.
        """
        stated: dict[int, DatNode] = {}
        seen: set[str] = set()
        while data is not None:
            for var_id in data.root.variables:
                stated.setdefault(var_id, data.root)
            base = data.root.text(VAR_BASEFILE)
            if not base:
                break
            key = _data_path(base)
            if key in seen:
                break
            seen.add(key)
            data = self._item_files.get(key)
        return stated

    def container_name(self, container_id: int) -> str | None:
        """The game's name for the container with this id.

        ``None`` for an id the data does not name, which the caller should
        say plainly rather than paper over.
        """
        return self.containers.get(container_id)

    def stash_tab(self, container_id: int) -> int | None:
        """Which tab of the shared stash this is, counting from 1.

        The player sees three tabs.  Their internal names --
        ``SHARED_STASH_BAG_ARMS`` and so on -- describe what each bag was
        originally built for, but any item goes in any tab, so the name is not
        what the player is looking at.  The position is.
        """
        tabs = self.stash_tabs
        try:
            return tabs.index(container_id) + 1
        except ValueError:
            return None

    @property
    def stash_tabs(self) -> list[int]:
        """The shared stash's container ids, in the order the game shows."""
        if self._stash_tabs is None:
            self._stash_tabs = sorted(
                cid
                for cid, name in self.containers.items()
                if name.startswith(SHARED_STASH)
            )
        return self._stash_tabs


def _bonus(
    effect: DatNode,
    curves: Mapping[str, dict[int, float]] | None = None,
    level: int = 1,
) -> SetBonus | None:
    """One effect a rung of a set's ladder grants, read off the affix node.

    ``None`` for a node that names no effect at all, which the archive has not
    got but a hand-written file can.

    The name is the node's ``TYPE`` -- the field naming the effect proper,
    which is what ``EFFECTSLIST.DAT`` files the wording under -- rather than
    the ``NAME`` beside it, which is the affix's own and is not unique: 107
    different affixes are called ``OFFLAME DAMAGE BONUS``.  ``TYPE`` is
    present on all 418 of the archive's rung effects; ``NAME`` is missing on
    69 of them, which state their numbers and nothing else.

    The values are the node's numbers in the order the file writes them, and
    that order is the effect's own schema: measured over those 418, the count
    of numbers is the number of value slots the effect declares, and the first
    is ``MIN`` on every one of the 402 that states it.

    A node that states no damage type is Physical rather than unknown.  19 of
    the 418 state none, and the effects they grant are the armour-bonus family
    -- ``PERCENT ARMOR BONUS``, ``ARMOR BONUS``, ``DEFENSE`` -- whose wording
    still says ``[DMGTYPE]``.  Real records of those same affixes carry 0, or
    1, and both of those are Physical: the game fills the hole in from the
    same default, and a card that did not would read ``+6% to ? Armor``.

    ``curves`` and ``level`` are the scaling: a set file states a nominal and
    the game shows the nominal scaled to the rung's ``AFFIXLEVEL`` by whichever
    graph the effect names, as a percentage.  Only the first two numbers are
    scaled -- the value pair -- because the ones after them are the effect's
    *parameters* rather than its magnitude: DRAW MANA's five are the per-monster
    low and high, the pulse rate, the radius and the target count, and its
    printed radius stays 3 however the value scales.

    Measured over the archive's 391 rungs against the reference database's own
    set text: 326 agree exactly.  The one that does not is the third rung of
    ``EMBERMAGE_TRINKETS_FROST``, whose text reads ``+2 Mana/sec`` where this
    reads ``+4``: its nominal is 7.5 and ``MANA_PLAYER_GENERIC`` states 47.5 at
    its level and never anything near the 26.7 the reference's number would
    need, at any level of the curve.  Every other curve in the archive was
    checked the same way.  So the reference states that one rung differently
    from the game's own data, and this follows the data.

    A curve with no point at ``level``, or none at all, leaves the numbers as
    the file stated them -- which is the other half of the same rule rather
    than an exception to it: the ``-1.5%`` of ``DRAGONRIFT``'s second rung is
    a nominal written out in full, with no graph behind it, and the game shows
    it exactly as written.  Every one of the archive's scaled rungs has its
    level in its curve; a mod's rung is the case the fallback is written for.
    """
    name = effect.text(VAR_AFFIX_EFFECT) or effect.text(VAR_NAME) or effect.name
    if not name:
        return None

    curve = (curves or {}).get(name.upper())
    values = [
        value for value in effect.variables.values() if isinstance(value, float)
    ]
    if curve:
        factor = curve.get(level)
        if factor is not None:
            scale = factor / GRAPH_PERCENT
            # The scale lands on an integer, and it rounds *toward positive
            # infinity* -- the same direction the game's own display rounds an
            # effect's value in.  Measured: nominal 3.0 at 145.5% is 4.365 and
            # the game shows 5; nominal 0.5 at 79.5% is 0.3975 and it shows 1;
            # nominal -0.333 at 3840% is -12.787 and it shows -12, which is
            # the ceiling and not the truncation.  `float()` matters: the
            # value list is read back as float32 bit patterns downstream, and
            # an int would be unpacked as one.
            values = [
                float(math.ceil(value * scale)) if slot < 2 else value
                for slot, value in enumerate(values)
            ]

    return SetBonus(
        name=name,
        values=tuple(values),
        duration=_seconds(effect),
        damage_type=DAMAGE_TYPE_IDS.get(
            (effect.text(VAR_DAMAGE_TYPE) or "").upper(),
            DAMAGE_TYPE_IDS["PHYSICAL"],
        ),
        skill=effect.text(VAR_NAME),
    )


def _seconds(effect: DatNode) -> float:
    """How long an effect lasts, from the node's ``DURATION``.

    A data file writes the duration as *text* -- ``'5'``, ``'60'``, ``'0'`` --
    rather than as a number, which is why this is not just ``number()``.  What
    the value means is what the wording asks for: an effect whose duration is
    above zero is described with the over-time template, whose ``[DURATION]``
    and ``[VALUE_OT]`` holes are filled from it, and the game does the same
    with an effect record's duration rather than consulting anything else.

    Anything that is not a number reads as zero -- the archive writes no such
    value, but the field is free text and a duration the tool cannot read is
    better shown as no duration than as a crash.
    """
    text = effect.text(VAR_DURATION)
    if text is not None:
        try:
            return float(text)
        except ValueError:
            return 0.0
    return effect.number(VAR_DURATION) or 0.0


def _container_entry(data: DatFile) -> tuple[int, str] | None:
    """``(container id, name)`` for one ``MEDIA/INVENTORY/CONTAINERS`` file.

    Unlike the files beside it, these declare the container id itself -- the
    save file's container 24 is the file that calls itself 24 -- so no
    arithmetic is needed to tie the two together.
    """
    root = data.root
    name = root.text(VAR_NAME)
    cid = root.number(VAR_SLOT_BASE)
    if not name or cid is None:
        return None
    return int(cid), name


def _percent(value: float | None) -> float:
    """A modifier stated as a percentage, or the neutral one."""
    return (NO_MODIFIER if value is None else value) / 100.0


def _speed_class(unit_type: str | None) -> str | None:
    """Which divisor applies to a weapon, from its own ``UNITTYPE``.

    The tokens are searched longest first, so ``1HSWORD`` wins over ``SWORD``
    and ``CROSSBOW`` over ``BOW``.  ``None`` for a field that names no weapon
    class at all, and for an item that states none -- neither of which is a
    weapon whose speed can be worked out.

    One item in the archive is mislabelled rather than unnamed: the polearm the
    game calls ``sturm_polearm`` states ``NORMAL SWORD`` and swings at the
    polearm rate, so this reads it as a sword and gives it 0.8 seconds where
    the game shows 1.2 -- the only one of the 1,351 weapons the reference
    database prices where this tool's speed line disagrees with it.  The
    reference fixes that with a table of names, and this does not: one item's
    own file contradicting itself is a thing to know about, not a rule, and a
    table of exceptions is not what the field says.
    """
    spelled = (unit_type or "").upper()
    for token in SPEED_CLASS_TOKENS:
        if token in spelled:
            return BARE_CLASS.get(token, token)
    return None


def _speed_band(seconds: float) -> str:
    """The word the game puts in front of an attack speed."""
    for word, fastest in SPEED_BANDS:
        if seconds <= fastest:
            return word
    return SLOWEST_BAND


def _written(value: float) -> str:
    """A number as the reference writes one: ``0.96``, ``12``, not ``12.0``.

    ``%g`` rather than a format of its own because the reach is stored as a
    32-bit float: a mace's 0.6 is in the file as 0.6000000238418579, and six
    significant digits is what makes that read as the number the game shows.
    """
    return "%g" % value


def _damage_per_second(derived: Derived | None, seconds: float, flat: int) -> int | None:
    """A weapon's whole output: every damage type over the swing, plus the flat.

    The average of each type's range, summed, over the seconds per swing,
    rounded half *up* -- ``int(x + .5)``, because Python's ``round`` takes
    halves to even and the game does not: Bonebreaker's 299 mean over 1.04 s is
    287.5, and the reference reads 301 rather than 300, which is that half
    going up and the flat 13 then added.

    The flat is added to the total rather than folded into the damage before
    the division, which is what the game does and what makes the Grimbone Wand
    read 180 rather than 179.

    ``None`` when there is no damage to divide: an item the data file gives no
    range at all, or -- the Wraithboss weapons, the ones a monster swings --
    one whose shares resolve to zero.  A weapon with nothing to hit for has no
    output to state, which is not the same as an output of zero, and the
    reference draws the same line: it writes a dps only where its mean is
    non-zero and still writes the speed and the reach beside it.
    """
    if derived is None or derived.kind != "damage":
        return None
    mean = sum((low + high) / 2 for low, high in derived.parts.values())
    if not mean:
        return None
    return int(mean / seconds + 0.5) + flat


def _flat_damage(item) -> int:
    """The damage the item has been *given*, summed over its elements.

    One line per element on the card -- ``+13 Physical Damage`` -- and the same
    number counted into the Damage per Second, because every one of these is
    damage added to each hit.  It is not the weapon's own damage: the two
    independent references both miss it, and the save file is the only place it
    is written down.

    A record's three parts are an effect, a socket and an enchantment, which
    are three sources of one number; the player sees the total, so the total is
    what is counted.  It is written as the whole number the card's line shows,
    which is the ceiling -- ``format_value`` rounds a positive value up -- so
    that the lead and the lines under it add up.
    """
    total = 0
    for added in item.added_damages:
        given = sum(
            as_float(part)
            for part in (added.from_effect, added.from_socket, added.from_enchant)
        )
        if given > 0:
            total += math.ceil(given)
    return total


def _scaled(written: float, factor: int) -> int:
    """A stated requirement as the game shows it: the curve's share of it.

    ``floor``, not the half-away-from-zero the damage and armour ends use:
    measured over the whole archive against the numbers a player is shown,
    every one of the 7,600-odd attribute requirements is the floor of the
    product, and a stated 100 at level 70 is 170 exactly rather than 171.
    """
    return math.floor(written * factor / GRAPH_PERCENT)


def _ends(low: float, high: float) -> tuple[int, int]:
    """Round a pair of damage or armour ends the way the game does.

    Half away from zero on each end separately, not a round of the pair and
    not Python's round(), which would take the halves to even.  Each element
    is rounded on its own too, which is why the parts of a two-element weapon
    need not add up to a whole one.
    """
    return int(low + 0.5), int(high + 0.5)


def _number(stated: dict[int, DatNode], var_id: int) -> float | None:
    """The number a field holds, on whichever node ended up stating it."""
    node = stated.get(var_id)
    return node.number(var_id) if node is not None else None


def _text(stated: dict[int, DatNode], var_id: int) -> str | None:
    """The string a field holds, on whichever node ended up stating it.

    An empty string is treated as absent.  The archive writes ``SET`` as an
    empty string on the great majority of items and the two mean the same
    thing here -- there is no set -- so collapsing them saves every caller
    the same check.
    """
    node = stated.get(var_id)
    text = node.text(var_id) if node is not None else None
    return text or None


def _data_path(name: str) -> str:
    """One spelling for a path inside the archive, to look files up by.

    A ``BASEFILE`` is written the way Windows writes paths, with backslashes,
    and the manifest lists them with forward slashes.  Case is mixed in both.
    Nothing else about the two ever differs, so normalising the separators and
    the case is enough to make them the same key.
    """
    return name.replace("\\", "/").upper()


def _graph_points(data: DatFile) -> dict[int, float]:
    """``{level: value}`` from one of the by-level graph files.

    A graph is a flat list of nodes under the root, each holding a level and
    the value there.  Both are stated as plain numbers rather than named
    fields, which is exactly what distinguishes a graph row from a node that
    means something else, so a row missing either is not a row.
    """
    points: dict[int, float] = {}
    for child in data.root.children:
        level = child.number(GRAPH_LEVEL_VAR)
        value = child.number(GRAPH_VALUE_VAR)
        if level is not None and value is not None:
            points[int(level)] = value
    return points


# --------------------------------------------------------------------------
# Finding the game
# --------------------------------------------------------------------------

_STEAM_LIBRARY = re.compile(r'"path"\s+"([^"]+)"', re.IGNORECASE)

_GOG_PATHS = (
    r"C:\Program Files (x86)\GOG Galaxy\Games\Torchlight II",
    r"C:\Program Files\GOG Galaxy\Games\Torchlight II",
    r"C:\GOG Games\Torchlight II",
)

_STEAM_COMMON_PATHS = (
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
)


def find_install(explicit: str | Path | None = None) -> Path | None:
    """Where Torchlight II is installed, or ``None`` if it is not.

    The game writes its own install directory to the registry, which is the
    best answer when it is there.  Otherwise: Steam puts its libraries
    wherever it likes, often on a different drive from Steam itself, and the
    list of them is in ``libraryfolders.vdf`` -- so most of the work is
    finding *Steam*.  GOG's default locations are the last resort.

    ``explicit`` comes first when given, and ``TL2_INSTALL`` before the
    search, for a copy neither store installed -- or for a machine where the
    registry says something surprising.
    """
    if explicit is not None:
        candidate = Path(explicit)
        return candidate if archive_path(candidate).is_file() else None

    override = os.environ.get("TL2_INSTALL")
    if override:
        candidate = Path(override)
        return candidate if archive_path(candidate).is_file() else None

    for candidate in _candidates():
        if archive_path(candidate).is_file():
            return candidate
    return None


def _candidates():
    """Every plausible install directory, best guess first."""
    from_registry = _install_from_registry()
    if from_registry is not None:
        yield from_registry
    for library in _steam_libraries():
        yield library / "steamapps" / "common" / "Torchlight II"
    for path in _GOG_PATHS:
        yield Path(path)


def _install_from_registry() -> Path | None:
    """The install directory the game recorded when it was set up."""
    if sys.platform != "win32":
        return None
    import winreg

    for key in (
        r"SOFTWARE\WOW6432Node\Runic Games\torchlight ii",
        r"SOFTWARE\Runic Games\torchlight ii",
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                found, _ = winreg.QueryValueEx(handle, "instdir")
        except OSError:
            continue
        if found:
            return Path(found)
    return None


def _steam_libraries():
    """Every Steam library folder on this machine, without repeats."""
    seen: set[str] = set()
    for root in _steam_roots():
        for library in _libraries_in(root):
            key = str(library).lower()
            if key not in seen:
                seen.add(key)
                yield library


def _libraries_in(steam_root: Path):
    """A Steam root, plus every library its manifest names."""
    yield steam_root
    try:
        text = (steam_root / "steamapps" / "libraryfolders.vdf").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return
    for match in _STEAM_LIBRARY.finditer(text):
        # The vdf escapes its backslashes, because of course it does.
        yield Path(match.group(1).replace("\\\\", "\\"))


def _steam_roots():
    """Where Steam itself is installed."""
    yield from _steam_from_registry()
    for path in _STEAM_COMMON_PATHS:
        yield Path(path)


def _steam_from_registry():
    if sys.platform != "win32":
        return
    import winreg

    for hive, key, value in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ):
        try:
            with winreg.OpenKey(hive, key) as handle:
                found, _ = winreg.QueryValueEx(handle, value)
        except OSError:
            continue
        if found:
            yield Path(found)
