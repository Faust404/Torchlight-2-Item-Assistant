"""Tests for the icon index: which sheet an icon is on, and where on it.

Most of these build a small archive in the test, so they hold on a machine
that has never seen Torchlight II -- and they are the ones that matter, because
what they pin is the shape of the game's own files.  An imageset names a
``.dds`` that is not the picture that gets read.  The pictures are in one
folder and the imagesets are in two.  A sheet that will not parse is not a
reason to lose the other thirty-eight.

The tests against the real archive skip without the game, and they are what
says the index is worth having at all: 98% of the icon names the game's own
items ask for are in it, and a real one's rectangle lands inside the picture
it names.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash.dat import VAR_ICON  # noqa: E402
from tl2stash.icons import ELEMENT_MARKS, IconLibrary  # noqa: E402

from test_dat import needs_game, real_game  # noqa: E402
from test_pak import write_synthetic_pak  # noqa: E402

#: Enough of a PNG for the reader, which passes the sheet's bytes through and
#: never looks inside one.  The test that cares whether the picture is really
#: a picture is the one against the real archive.
_PNG = b"\x89PNG\r\n\x1a\n" + b"a sheet, pretending"


def imageset(*icons, imagefile: str = "media/ui/icons/x/x.dds") -> bytes:
    """An ``.IMAGESET`` as Ogre writes one, declaring the icons given.

    Each icon is ``(name, x, y, width, height)``; a coordinate of ``None`` is
    written out as the attribute's literal text, which is what a file with a
    hole in it looks like.
    """
    rows = "".join(
        f'<Image Name="{name}" XPos="{x}" YPos="{y}" '
        f'Width="{w}" Height="{h}" />'
        for name, x, y, w, h in icons
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Imageset Name="x" Imagefile="{imagefile}">{rows}</Imageset>'
    ).encode()


def library(tmp_path: Path, files: dict[str, bytes]) -> IconLibrary:
    """An install directory holding an archive of exactly ``files``."""
    write_synthetic_pak(tmp_path / "PAKS", files)
    return IconLibrary(tmp_path)


# --------------------------------------------------------------------------
# Reading the index
# --------------------------------------------------------------------------


def test_an_imageset_says_where_its_icons_are(tmp_path):
    """The whole job: name to rectangle, and the sheet's bytes at the end."""
    lib = library(
        tmp_path,
        {
            "MEDIA/UI/ICONS/ARMOR/ARMOR.IMAGESET": imageset(
                ("icons_armor_belt", 1, 1, 62, 62),
                ("icons_armor_boots", 65, 1, 62, 62),
            ),
            "MEDIA/UI/ICONS/ARMOR/ARMOR.PNG": _PNG,
        },
    )

    belt = lib.locate("icons_armor_belt")
    assert (belt.x, belt.y, belt.width, belt.height) == (1, 1, 62, 62)
    # The second one is beside it on the same sheet, which is what says the
    # index is of rectangles rather than of sheets.
    boots = lib.locate("icons_armor_boots")
    assert (boots.x, boots.y) == (65, 1)
    assert boots.atlas == belt.atlas

    assert lib.read(belt) == _PNG


def test_the_picture_read_is_the_png_and_not_the_dds_the_imageset_names(tmp_path):
    """The one thing an imageset does not say.

    Its ``Imagefile`` attribute names the ``.dds`` beside it, and a DDS needs
    a decoder written for it; the PNG beside it is the same picture and needs
    none.  So the sheet is the imageset's own name with the picture's
    extension, and this is what holds that rule in place -- a sheet read by
    way of the attribute would come back as the DDS.
    """
    lib = library(
        tmp_path,
        {
            "MEDIA/UI/ICONS/ARMOR/ARMOR.IMAGESET": imageset(
                ("icons_armor_belt", 1, 1, 62, 62)
            ),
            "MEDIA/UI/ICONS/ARMOR/ARMOR.PNG": _PNG,
            "MEDIA/UI/ICONS/ARMOR/ARMOR.DDS": b"DDS " + b"not this one",
        },
    )
    belt = lib.locate("icons_armor_belt")
    assert belt.atlas.endswith(".PNG")
    assert lib.read(belt) == _PNG


def test_a_name_is_found_however_it_is_spelled(tmp_path):
    """The sheets spell their icons one way and the items that use them
    another.  Only 20 of the 1,012 names real items ask for are in no sheet at
    all, so this is not a nicety -- it is most of the coverage."""
    lib = library(
        tmp_path,
        {
            "MEDIA/UI/ICONS/ARMOR/ARMOR.IMAGESET": imageset(
                ("icons_armor_belt", 1, 1, 62, 62)
            ),
            "MEDIA/UI/ICONS/ARMOR/ARMOR.PNG": _PNG,
        },
    )
    found = lib.locate("icons_armor_belt")
    assert lib.locate("ICONS_ARMOR_BELT") == found
    assert lib.locate("Icons_Armor_Belt") == found

    # And a name that is not there is absent rather than a guess: the card
    # draws a placeholder for it, which needs to be a thing that can happen.
    assert lib.locate("icons_armor_hat") is None
    assert lib.locate("") is None


def test_a_sheet_keeps_the_first_of_two_icons_with_one_name(tmp_path):
    """No name in the game's 1,471 is in two sheets, so this settles a mod's
    collision rather than the game's -- but it has to settle it somehow, and
    'whichever the archive happened to list first' is not an answer."""
    lib = library(
        tmp_path,
        {
            "MEDIA/UI/ICONS/ARMOR/ARMOR.IMAGESET": imageset(
                ("icons_thing", 1, 1, 62, 62)
            ),
            "MEDIA/UI/ICONS/ARMOR/ARMOR.PNG": _PNG,
            "MEDIA/UI/ICONS/SKILLS/SKILLS.IMAGESET": imageset(
                ("icons_thing", 400, 400, 62, 62)
            ),
            "MEDIA/UI/ICONS/SKILLS/SKILLS.PNG": _PNG,
        },
    )
    assert lib.locate("icons_thing").x == 1


# --------------------------------------------------------------------------
# What is not an icon
# --------------------------------------------------------------------------


def test_a_sheet_with_no_picture_contributes_no_icons(tmp_path):
    """Every one of the game's 39 has its picture.  A mod's that does not is
    an atlas nothing could be drawn from, so its icons are absent rather than
    placed at a rectangle no picture is behind."""
    lib = library(
        tmp_path,
        {
            "MEDIA/UI/ICONS/ARMOR/ARMOR.IMAGESET": imageset(
                ("icons_armor_belt", 1, 1, 62, 62)
            ),
            "MEDIA/UI/ICONS/ARMOR/ARMOR.DDS": b"DDS " + b"only this one",
        },
    )
    assert lib.locate("icons_armor_belt") is None


def test_a_sheet_outside_the_icons_folder_is_not_an_icon_sheet(tmp_path):
    """The one that bites: 63 imagesets in the archive are outside it, and
    those belong to the translated language packs, whose pictures are in the
    pack and not in ``DATA.PAK`` at all.  Sweeping for imagesets rather than
    looking in the folder named is what turns those into missing pictures."""
    lib = library(
        tmp_path,
        {
            "MEDIA/TRANSLATIONS/GERMAN/UI/CEGUIWIDGET.IMAGESET": imageset(
                ("icons_widget", 1, 1, 62, 62)
            ),
            "MEDIA/TRANSLATIONS/GERMAN/UI/CEGUIWIDGET.PNG": _PNG,
        },
    )
    assert lib.locate("icons_widget") is None


def test_a_sheet_that_will_not_parse_does_not_take_the_others_with_it(tmp_path):
    """One unreadable sheet out of 39, for the same reason a broken DAT file
    is not a reason to refuse to start."""
    lib = library(
        tmp_path,
        {
            "MEDIA/UI/ICONS/BROKEN/BROKEN.IMAGESET": b"<Imageset><Image",
            "MEDIA/UI/ICONS/BROKEN/BROKEN.PNG": _PNG,
            "MEDIA/UI/ICONS/ARMOR/ARMOR.IMAGESET": imageset(
                ("icons_armor_belt", 1, 1, 62, 62)
            ),
            "MEDIA/UI/ICONS/ARMOR/ARMOR.PNG": _PNG,
        },
    )
    assert lib.locate("icons_armor_belt") is not None


def test_a_declaration_with_no_rectangle_names_no_icon(tmp_path):
    """A guessed rectangle would draw the wrong icon rather than none."""
    lib = library(
        tmp_path,
        {
            "MEDIA/UI/ICONS/ARMOR/ARMOR.IMAGESET": imageset(
                ("icons_nowhere", None, None, None, None),
                ("icons_armor_belt", 1, 1, 62, 62),
            ),
            "MEDIA/UI/ICONS/ARMOR/ARMOR.PNG": _PNG,
        },
    )
    assert lib.locate("icons_nowhere") is None
    assert lib.locate("icons_armor_belt") is not None


def test_nothing_is_read_until_something_is_looked_up(tmp_path):
    """Constructing one is free, so the tool can hold it whether or not the
    game is installed -- and a save whose items are all in the sheets it has
    already read never pays for the rest."""
    missing = tmp_path / "no-game-here"
    lib = IconLibrary(missing)  # does not raise

    with pytest.raises(OSError):
        lib.locate("icons_armor_belt")


# --------------------------------------------------------------------------
# The element marks
# --------------------------------------------------------------------------


def test_a_mark_is_read_from_the_hud_sheet_and_not_from_the_icon_folder(tmp_path):
    """The two routes, and the reason they are two rather than one.

    A mark is not an item icon and does not live with them: it is on the sheet
    the in-game tooltip is drawn from.  Both routes are made to declare the
    *same word* here -- the icon folder a ``resist_firec`` of its own, the HUD
    sheet the real one -- so a ``mark`` that went through the general index
    would come back with the wrong picture.
    """
    lib = library(
        tmp_path,
        {
            "MEDIA/UI/ICONS/HUD/HUD.IMAGESET": imageset(
                ("resist_firec", 1, 1, 62, 62)
            ),
            "MEDIA/UI/ICONS/HUD/HUD.PNG": _PNG,
            "MEDIA/UI/HUD/INGAMETEXTURESHEETS4.IMAGESET": imageset(
                ("resist_physicalc", 996, 156, 27, 29),
                ("resist_firec", 996, 342, 27, 29),
            ),
            "MEDIA/UI/HUD/INGAMETEXTURESHEETS4.PNG": _PNG,
        },
    )

    fire = lib.mark("fire")
    assert (fire.x, fire.y, fire.width, fire.height) == (996, 342, 27, 29)
    assert fire.atlas.endswith("INGAMETEXTURESHEETS4.PNG")

    # And the icon route still finds its own, which is what says the mark did
    # not simply do a lookup in the index everyone else uses.
    assert lib.locate("resist_firec").x == 1


def test_a_mark_is_asked_for_by_the_element_s_name(tmp_path):
    """``fire`` rather than ``resist_firec``: the game's file name for the
    picture is this module's business, and no caller has it."""
    lib = library(
        tmp_path,
        {
            "MEDIA/UI/HUD/INGAMETEXTURESHEETS4.IMAGESET": imageset(
                ("resist_firec", 996, 342, 27, 29)
            ),
            "MEDIA/UI/HUD/INGAMETEXTURESHEETS4.PNG": _PNG,
        },
    )
    fire = lib.mark("fire")
    assert lib.mark("FIRE") == fire, "the lookup is case-insensitive"
    assert lib.locate("resist_firec") is None, "the sheet is not an icon sheet"

    # An element with no mark -- ``all``, which some items are written as --
    # and no element at all.
    assert lib.mark("all") is None
    assert lib.mark("") is None


def test_only_the_one_HUD_sheet_is_looked_in_for_a_mark(tmp_path):
    """The HUD has seven sheets and the five marks are on the fourth.  A
    declaration of the same name on another one is a different picture, so it
    is not a fallback -- naming the sheet is what keeps this from being a
    sweep of the HUD."""
    lib = library(
        tmp_path,
        {
            "MEDIA/UI/HUD/INGAMETEXTURESHEETS3.IMAGESET": imageset(
                ("resist_firec", 1, 1, 27, 29)
            ),
            "MEDIA/UI/HUD/INGAMETEXTURESHEETS3.PNG": _PNG,
        },
    )
    assert lib.mark("fire") is None


# --------------------------------------------------------------------------
# The real archive
# --------------------------------------------------------------------------


@needs_game
def test_a_real_icon_lands_inside_the_picture_it_names(real_game):
    """One icon, all the way from its name to its pixels.

    The rectangle is the whole load-bearing claim of the index: a sheet holds
    hundreds of icons and a rectangle one pixel out draws a neighbour.  The
    picture's own size is read out of its IHDR rather than taken on trust --
    the XML's extents are often a pixel smaller than the PNG, so it is the
    pixel dimensions that say whether a crop is inside one.
    """
    lib = IconLibrary(real_game.install)
    placed = lib.locate("icon_weapon_fist14")

    assert placed is not None
    assert placed.width == 62 and placed.height == 62

    png = lib.read(placed)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert placed.x + placed.width <= width
    assert placed.y + placed.height <= height


@needs_game
def test_almost_every_icon_a_real_item_asks_for_is_in_a_sheet(real_game):
    """98% of them, measured here rather than assumed.

    The twenty that are not are embers, glyphs, fish eyes and a handful of
    odds and ends -- items the game draws with a picture this tool cannot
    find, and which the card draws a placeholder for.  What this pins is that
    the index does not quietly shrink: the floor under the count is what keeps
    a vanished sweep from reading as a pass.
    """
    wanted: set[str] = set()
    for data in real_game._item_files.values():
        for node in data.root.walk():
            icon = node.text(VAR_ICON)
            if icon:
                wanted.add(icon)

    lib = IconLibrary(real_game.install)
    found = sum(1 for name in wanted if lib.locate(name) is not None)

    assert len(wanted) > 900, "the sweep stopped finding items"
    assert found / len(wanted) >= 0.98, f"only {found} of {len(wanted)} resolved"


@needs_game
def test_the_five_element_marks_come_off_the_real_hud_sheet(real_game):
    """All five, measured on the archive rather than taken from the notes.

    They are the one group of pictures this tool knows by a name the game
    never gives a caller, so the names are the claim: four are the shield-less
    ``...c`` variant of a resistance icon and ice is ``resist_iced``, with no
    ``resist_icec`` beside it.  Every one is 27x29 and inside the sheet it
    names, and none of them is in the icon folder -- which is what makes the
    marks a second route rather than a lookup that happened to work.
    """
    lib = IconLibrary(real_game.install)
    for element, name in ELEMENT_MARKS.items():
        placed = lib.mark(element)
        assert placed is not None, name
        assert (placed.width, placed.height) == (27, 29), name
        assert placed.atlas.endswith("INGAMETEXTURESHEETS4.PNG"), name
        assert lib.locate(name) is None, f"{name} is not an item icon"

    assert lib.mark("all") is None, "there is no mark for all damage"


@needs_game
def test_an_icon_the_game_has_not_got_is_absent_rather_than_somewhere_else(
    real_game,
):
    """The other half of the coverage number: a name real items ask for and
    the archive has no sheet for comes back as nothing.

    ``gem_fish_eye`` is a fish's icon, and it is one of the twenty.  A lookup
    that fell back to a near miss would put the wrong picture on the item, and
    an item with no picture is drawn with a placeholder on purpose.
    """
    lib = IconLibrary(real_game.install)
    assert lib.locate("gem_fish_eye") is None
