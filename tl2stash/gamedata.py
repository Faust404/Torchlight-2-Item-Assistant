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

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .dat import (
    VAR_AFFIX_EFFECT,
    VAR_BADDES,
    VAR_BADDESOT,
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
    VAR_DISPLAY_NAME,
    VAR_FLAVOR,
    VAR_LEVEL,
    VAR_MAXDAMAGE,
    VAR_MINDAMAGE,
    VAR_RARITY_DMG_MOD,
    VAR_SLOT_BASE,
    VAR_SPEED_DMG_MOD,
    VAR_UNIT_GUID,
    DatFile,
    DatNode,
)
from .pak import PakFile, PakIndex

__all__ = [
    "ARCHIVE_NAME",
    "Derived",
    "GameData",
    "archive_path",
    "find_install",
]

#: The files worth reading, out of the archive's 70,443.  An item's numbers
#: come from the save file; what these supply is the *wording* -- effect
#: names, description templates, and the names of the stash's bags.  The rest
#: of the archive is models, textures, sounds and UI layouts.
WANTED = (
    "MEDIA/AFFIXES/ITEMS/",
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

#: The two by-level curves the damage and armour arithmetic are built on.  A
#: graph file is a list of nodes, each carrying a level and the value at that
#: level -- the two field ids are plain small numbers rather than hashed
#: names, which is how a graph node is told apart from every other node in the
#: archive.
GRAPH_WEAPON_DAMAGE = "MEDIA/GRAPHS/STATS/BASE_WEAPON_DAMAGE.DAT"
GRAPH_ARMOR = "MEDIA/GRAPHS/STATS/ARMOR_PLAYER_BYLEVEL_FORSET.DAT"
GRAPH_LEVEL_VAR = 120
GRAPH_VALUE_VAR = 121

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
        "_by_name",
        "_display_names",
        "_effects",
        "_effect_order",
        "_item_files",
        "_item_guids",
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
        failed: list[tuple[str, str]],
        files_read: int,
        item_files: dict[str, DatFile],
        item_guids: dict[int, DatFile],
        weapon_curve: dict[int, float],
        armor_curve: dict[int, float],
    ) -> None:
        self.install = install
        self._by_name = by_name
        self._display_names = display_names
        self._effects = effects
        self._effect_order = effect_order
        self._affix_effects = affix_effects
        self.containers = containers
        self.failed = failed
        self.files_read = files_read
        self._item_files = item_files
        self._item_guids = item_guids
        self._weapon_curve = weapon_curve
        self._armor_curve = armor_curve
        self._stash_tabs: list[int] | None = None

    def __repr__(self) -> str:
        return (
            f"<GameData {self.files_read} files, {len(self._by_name)} named, "
            f"{len(self._effects)} effects, {len(self.failed)} unreadable>"
        )

    # -- loading ----------------------------------------------------------

    @classmethod
    def load(cls, install: str | Path) -> "GameData":
        """Read every file in :data:`WANTED` out of the archive.

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
        failed: list[tuple[str, str]] = []
        item_files: dict[str, DatFile] = {}
        item_guids: dict[int, DatFile] = {}
        curves: dict[str, dict[int, float]] = {}
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

                if path in (GRAPH_WEAPON_DAMAGE, GRAPH_ARMOR):
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

        return cls(
            install,
            by_name,
            display_names,
            effects,
            effect_order,
            affix_effects,
            containers,
            failed,
            read,
            item_files,
            item_guids,
            curves.get(GRAPH_WEAPON_DAMAGE, {}),
            curves.get(GRAPH_ARMOR, {}),
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

    def skill_name(self, name: str) -> str | None:
        """What the player is shown for the skill ``name``, if it is one.

        A handful of effects name a skill in their wording -- ``'[VALUE]%
        chance to cast [NAME] on kill'`` -- and the name that goes in the hole
        is the skill's.  The record in the save file names an affix, and for
        these the affix is named after the skill it grants: ``WC_PROC_FULLHEAL``
        is an affix under ``MEDIA/AFFIXES/ITEMS`` *and* a skill under
        ``MEDIA/SKILLS/ARBITER/WANDCHAOS``, and only the skill carries the
        display name ``'Fully Heal Self'``.  So the record's own name is the
        key, and it is looked up as a display name rather than as a node.
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
