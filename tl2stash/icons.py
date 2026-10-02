"""Where an icon's pixels are: the game's own atlases, out of the archive.

An item's data file names its icon -- ``icon_weapon_fist14`` -- and that name is
not a file.  It is a rectangle inside one of the 39 sheets under
``MEDIA/UI/ICONS``, and the sheet's ``.IMAGESET`` is what says so: it is Ogre
XML, one ``<Image Name=... XPos=... YPos=... Width=... Height=...>`` per icon,
read into one name-to-rectangle index here.

Each sheet is stored three times -- ``.DDS``, ``.PNG`` and ``.IMAGESET`` -- and
the PNG is the one used.  It is the same picture, and every toolkit reads a PNG
without being taught a thing; the DDS would need a decoder written for it, and
the ``Imagefile`` attribute in the imageset names the DDS rather than the PNG,
so the archive's own path is what the PNG is derived from.

What comes back is therefore *where* an icon is, and the sheet's bytes when
they are asked for.  Turning that into something on screen is ``app.card``'s
job, and Qt does the rest of it.

Two routes, because there are two kinds of picture.  An *item's* icon is in
``MEDIA/UI/ICONS`` and is found by searching that one directory, which is what
makes a name a name here.  The five *element marks* the game writes beside a
damage line are not item icons and are not in that directory at all: they are
on the HUD sheet the in-game tooltip is drawn from, and they are found by
naming it.  That they are a second route rather than a fallback is the point
-- an ``.IMAGESET`` under ``MEDIA/UI/ICONS`` is about an item, and one that
happens to declare ``resist_firec`` would be a different picture of the same
word.

Qt-free, like the rest of ``tl2stash``, and lazy in both directions: the index
costs 132 KB of XML and is not built until something is looked up, and a sheet
is read only when an icon inside it is.  Somebody who never opens a weapon
never decompresses a weapon sheet.

Derived by reading the archive; not transcribed from another implementation.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .gamedata import archive_path
from .pak import PakFile, PakIndex, PakError, open_archive

__all__ = ["IconLibrary", "Placement"]

#: Where the sheets live.  Named rather than searched for: an ``.IMAGESET``
#: elsewhere in the archive belongs to a different thing -- the translated
#: language packs have their own, whose pictures are in the pack and not in
#: ``DATA.PAK`` at all.
_PREFIX = "MEDIA/UI/ICONS/"

_IMAGESET = ".IMAGESET"
_PNG = ".PNG"

#: The element marks, by the word this tool calls the element.
#:
#: Names measured off the HUD sheet rather than guessed: the game spells the
#: five with a trailing ``c`` -- the *shield-less* variant of each resistance
#: icon, which is the one the item tooltip names -- except ice, which is
#: ``resist_iced`` and has no ``resist_icec`` beside it.  All five are 27x29.
ELEMENT_MARKS = {
    "physical": "resist_physicalc",
    "fire": "resist_firec",
    "ice": "resist_iced",
    "electric": "resist_electricc",
    "poison": "resist_poisonc",
}

#: The one HUD sheet those five are on, of the seven the HUD has.
_MARKS_SHEET = "MEDIA/UI/HUD/INGAMETEXTURESHEETS4"


@dataclass(frozen=True)
class Placement:
    """One icon: which sheet it is on, and the rectangle it occupies.

    ``atlas`` is the archive's own name for the sheet, which is what a caller
    caches a decoded picture by -- a sheet holds hundreds of icons and is worth
    decoding once.  It is not a path on disk: nothing is ever unpacked.
    """

    atlas: str
    x: int
    y: int
    width: int
    height: int


def _rectangles(data: bytes) -> Iterator[tuple[str, int, int, int, int]]:
    """Every icon an imageset declares, as its name and its rectangle.

    ``iter`` rather than ``findall``: the shipped files are flat, and a mod's
    need not be.
    """
    for image in ET.fromstring(data).iter("Image"):
        name = image.get("Name")
        try:
            rectangle = (
                int(image.get("XPos")),
                int(image.get("YPos")),
                int(image.get("Width")),
                int(image.get("Height")),
            )
        except (TypeError, ValueError):
            # A declaration missing a coordinate names no rectangle, and a
            # guess at one would draw the wrong icon rather than none.
            continue
        if name:
            yield (name, *rectangle)


class IconLibrary:
    """The archive's icon sheets, and what is where in them.

    Nothing is read until something is looked up, so constructing one is free
    and the tool can hold it whether or not the game is installed.
    """

    def __init__(self, install: str | Path) -> None:
        self.install = Path(install)
        self._archive: PakFile | None = None
        self._index: PakIndex | None = None
        self._placed: dict[str, Placement] | None = None
        self._marks: dict[str, Placement] | None = None

    # -- looking up -------------------------------------------------------

    def locate(self, name: str) -> Placement | None:
        """Where the icon called ``name`` is, or ``None`` if there is none.

        Case-insensitively, because the data files are inconsistent about it:
        the sheets spell their icons one way and the items that use them
        another, and only 20 of the 1,012 names real items ask for are in no
        sheet at all -- embers, glyphs and a handful of odds and ends.
        """
        if not name:
            return None
        return self._placements().get(name.upper())

    def mark(self, element: str) -> Placement | None:
        """Where the mark for a damage element is, or ``None`` if there is none.

        By the element's *name* -- ``fire`` rather than ``resist_firec`` --
        because the word is what every caller has: it is what the save file's
        damage types and the game's own damage lines are written in, and the
        game's file name for the picture is this module's business rather than
        theirs.  An element no mark is known for -- ``all``, which some items
        are written as -- has none rather than the wrong one.
        """
        name = ELEMENT_MARKS.get(element.lower() if element else "")
        if name is None:
            return None
        # The sheet's names are held upper-cased, like every name in the index.
        return self._markset().get(name.upper())

    def read(self, placement: Placement) -> bytes:
        """The sheet a placement sits in, as PNG bytes.

        The whole sheet rather than the one icon: a decode serves every icon on
        it, and cropping is the toolkit's job.  The handle is opened for the
        read and closed after it, so holding one of these costs nothing.
        """
        with self._open() as archive:
            return archive.read(placement.atlas)

    # -- reading ----------------------------------------------------------

    def _open(self) -> PakFile:
        if self._archive is None:
            # The manifest is 5.3 MB and parsing it twice to hand out two
            # objects describing the same file would be a trap, so it is
            # parsed here once and kept.
            self._index, self._archive = open_archive(
                archive_path(self.install)
            )
        return self._archive

    def _placements(self) -> dict[str, Placement]:
        if self._placed is None:
            self._placed = self._read_placements()
        return self._placed

    def _markset(self) -> dict[str, Placement]:
        if self._marks is None:
            self._marks = self._sheet_placements(_MARKS_SHEET)
        return self._marks

    def _read_placements(self) -> dict[str, Placement]:
        """Every icon under ``MEDIA/UI/ICONS``, in the archive's order."""
        index = self._open().index
        placed: dict[str, Placement] = {}

        for entry in index.entries.values():
            name = entry.name
            upper = name.upper()
            if not upper.startswith(_PREFIX) or not upper.endswith(_IMAGESET):
                continue

            sheet = self._sheet_placements(name[: -len(_IMAGESET)])
            for icon, placement in sheet.items():
                # ``setdefault``: a name in two sheets keeps the first, which
                # is the earlier one in the archive.  No name in the shipped
                # 1,471 is in two, so this settles a mod's collision rather
                # than the game's.
                placed.setdefault(icon, placement)

        return placed

    def _sheet_placements(self, stem: str) -> dict[str, Placement]:
        """One imageset's rectangles, by the name it declares them under.

        The shared half of the two routes: an imageset is an imageset whatever
        it is of, and the two differ only in how they are found -- the item
        icons by walking a directory, the marks by naming one sheet.

        ``stem`` is the archive's own path without its extension, because an
        imageset is stored beside its picture: the ``Imagefile`` attribute
        inside one names the DDS rather than the PNG, so the sheet is derived
        from the path rather than read out of the file.
        """
        index = self._open().index
        declared = index.get(stem + _IMAGESET)
        atlas = index.get(stem + _PNG)
        if declared is None or atlas is None:
            # Every one of the game's 39 item sheets has its picture, and so
            # does the HUD's.  A mod's that does not is an atlas nothing could
            # be drawn from, so what it declares is absent rather than broken.
            return {}

        try:
            with self._open() as archive:
                found = list(_rectangles(archive.read(declared.name)))
        except (PakError, ET.ParseError):
            # One unreadable sheet out of 39, for the same reason a broken DAT
            # file is not a reason to refuse to start: the icons in the other
            # 38 are still there.
            return {}

        return {
            icon.upper(): Placement(atlas.name, x, y, width, height)
            for icon, x, y, width, height in found
        }
