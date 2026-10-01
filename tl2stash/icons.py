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

    def _read_placements(self) -> dict[str, Placement]:
        index = self._open().index
        placed: dict[str, Placement] = {}

        for entry in index.entries.values():
            name = entry.name
            upper = name.upper()
            if not upper.startswith(_PREFIX) or not upper.endswith(_IMAGESET):
                continue

            # The sheet is the imageset's own name with the picture's
            # extension, which is the one thing the imageset does not say:
            # its Imagefile attribute names the DDS beside it.
            atlas = index.get(name[: -len(_IMAGESET)] + _PNG)
            if atlas is None:
                # Every one of the game's 39 has its picture.  A mod's that
                # does not is an atlas nothing could be drawn from, so its
                # icons are absent rather than broken.
                continue

            try:
                with self._open() as archive:
                    declared = list(_rectangles(archive.read(name)))
            except (PakError, ET.ParseError):
                # One unreadable sheet out of 39, for the same reason a
                # broken DAT file is not a reason to refuse to start: the
                # icons in the other 38 are still there.
                continue

            for icon, x, y, width, height in declared:
                # ``setdefault``: a name in two sheets keeps the first, which
                # is the earlier one in the archive.  No name in the shipped
                # 1,471 is in two, so this settles a mod's collision rather
                # than the game's.
                placed.setdefault(icon.upper(), Placement(atlas.name, x, y, width, height))

        return placed
