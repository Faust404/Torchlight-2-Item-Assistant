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
from pathlib import Path

from .dat import (
    VAR_AFFIX_EFFECT,
    VAR_BADDES,
    VAR_BADDESOT,
    VAR_DISPLAYPRECISION,
    VAR_GOODDES,
    VAR_GOODDESOT,
    VAR_NAME,
    VAR_SLOT_BASE,
    DatFile,
    DatNode,
)
from .pak import PakFile, PakIndex

__all__ = ["ARCHIVE_NAME", "GameData", "archive_path", "find_install"]

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
        "_by_name",
        "_effects",
        "_effect_order",
        "_stash_tabs",
    )

    def __init__(
        self,
        install: Path,
        by_name: dict[str, DatNode],
        effects: dict[str, DatNode],
        effect_order: list[DatNode],
        affix_effects: dict[str, set[str]],
        containers: dict[int, str],
        failed: list[tuple[str, str]],
        files_read: int,
    ) -> None:
        self.install = install
        self._by_name = by_name
        self._effects = effects
        self._effect_order = effect_order
        self._affix_effects = affix_effects
        self.containers = containers
        self.failed = failed
        self.files_read = files_read
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
        effects: dict[str, DatNode] = {}
        effect_order: list[DatNode] = []
        affix_effects: dict[str, set[str]] = {}
        containers: dict[int, str] = {}
        failed: list[tuple[str, str]] = []
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
            effects,
            effect_order,
            affix_effects,
            containers,
            failed,
            read,
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
