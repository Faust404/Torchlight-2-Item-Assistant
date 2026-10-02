"""Tests for the window's colours.

One claim, and it is a claim about a *palette* rather than about the forty
lines that build it: the application is dark, its text is legible on it, and
its surfaces are a ramp of their own -- a shade *above* the cards the player
reads, and, in the one pane that holds them, a shade below.  What is not the
window's is the words: those are the cards' own greys, so a label on the window
and a label on a card are the same colour.

These are the only tests here that touch the process-wide QApplication, so
they put it back the way they found it: every other GUI test in the suite
shares that one instance, and a palette left behind would be a colour scheme
decided by test ordering.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Before the first PySide6 import, like the other GUI tests.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 is not installed")

from PySide6.QtGui import QColor, QFont, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QStyleFactory  # noqa: E402

from app.card import BODY, GROUND, LABEL, PANEL, TABULAR, _serif  # noqa: E402
from app.theme import (  # noqa: E402
    BODY_PX,
    CHALK,
    EDGE,
    FIELD,
    PALE,
    RAIL_PX,
    RAISED,
    SANS,
    SELECT,
    SHADOW,
    SHELL,
    STRIPE,
    WALL,
    _load_fonts,
    apply_theme,
)


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session; Qt allows no more."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def themed(qapp):
    """The application with the theme applied, and put back afterwards."""
    # The style is remembered by *name* rather than by object: setting a style
    # hands it to Qt, which deletes the one it replaced -- so the style this
    # found is gone the moment the theme lands, and putting it back means
    # building that style again.  The font is remembered the same way a palette
    # is, because ``apply_theme`` now sets one and every other GUI test in the
    # suite shares this application.
    name = qapp.style().objectName()
    palette = QPalette(qapp.palette())
    font = QFont(qapp.font())
    sheet = qapp.styleSheet()
    apply_theme(qapp)
    try:
        yield qapp
    finally:
        restored = QStyleFactory.create(name) if name else None
        if restored is not None:
            qapp.setStyle(restored)
        qapp.setPalette(palette)
        qapp.setFont(font)
        qapp.setStyleSheet(sheet)


def test_the_window_is_dark(themed):
    """Dark is the claim: the shell is darker than the words standing on it.

    And it is dark from *above*: the shell sits a shade higher than the cards
    do, which is the lightening the user asked for and the reason they asked
    for it -- what the player operates is outlined in :data:`app.theme.CHALK`,
    and a hairline on the cards' own near-black ground is glare rather than
    contrast.
    """
    palette = themed.palette()
    window = palette.color(QPalette.ColorRole.Window)
    text = palette.color(QPalette.ColorRole.WindowText)

    assert window.name() == SHELL
    assert text.name() == BODY
    assert window.lightness() < text.lightness()
    # Not merely darker: dark.  A mid-grey window with white text would pass
    # the line above and is not what "dark by default" means.
    assert window.lightness() < 64
    # And up rather than level: a shade above the surface the cards are drawn
    # on, which is what puts the white controls in tune with it.
    assert window.lightness() > QColor(GROUND).lightness()


def test_the_tool_s_ground_goes_below_the_cards(themed):
    """The one surface that goes the other way, and it goes further.

    :data:`app.theme.WALL` is what the tool's cards are drawn on -- the wall
    paints it in :mod:`app.tiles` -- and it is darker than a card, so an item
    lying in the tool reads as a card in a drawer rather than as a panel in a
    panel.  The window around it is lighter than the cards and the wall behind
    them is darker than them, which is the contrast the user asked for between
    the item cards and the pane they sit in.

    What is written on the shell is still the card's own body colour, so a
    label on the window and a label on a card are the same grey.
    """
    palette = themed.palette()

    assert QColor(WALL).lightness() < QColor(PANEL).lightness(), "not below a card"
    assert QColor(WALL).lightness() < QColor(SHELL).lightness()
    assert palette.color(QPalette.ColorRole.Text).name() == BODY


def test_what_a_palette_cannot_say_is_in_the_sheet(themed):
    """A group box's title has no palette role, so it is a rule in the sheet.

    The *style* -- Fusion, which is the one Qt style that draws all of a
    control out of the palette -- is deliberately not asserted here, because
    on this side of the API it cannot be: setting a stylesheet wraps the
    application's style in a stylesheet style, and the wrapper reports neither
    a name nor what it wraps.  What can be checked is that a sheet is in
    force, and that it spends the colours the palette has no role to spend.
    """
    sheet = themed.styleSheet()
    assert "QGroupBox::title" in sheet
    assert LABEL in sheet


def test_a_disabled_control_recedes(themed):
    """Disabled text is dimmer than the same text enabled.

    Qt's own greys for this are the light theme's -- mid-grey on a dark
    ground, which is *brighter* than the text around it, so a greyed-out
    control would be the loudest thing on the screen.
    """
    palette = themed.palette()
    enabled = palette.color(
        QPalette.ColorGroup.Active, QPalette.ColorRole.ButtonText
    )
    disabled = palette.color(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText
    )
    assert disabled.lightness() < enabled.lightness()


def test_applying_it_twice_changes_nothing(themed):
    """It is applied at startup and may be applied by a test; both are safe."""
    before = QPalette(themed.palette())
    sheet = themed.styleSheet()
    apply_theme(themed)
    assert themed.palette() == before
    assert themed.styleSheet() == sheet


def test_the_controls_are_chalk_and_not_white(themed):
    """The one colour in the window that is not the card palette's -- and the
    one the user asked to have toned down.

    Everything the player *operates* -- the check boxes down the rail, the
    search box, the two boxes over the collection, the number boxes in them and
    the word on every chip -- is outlined in :data:`app.theme.CHALK`, and
    nothing else in the window is.  A hairline in the palette's own greys does
    not read as a control against a ground this dark: the rail's check boxes
    were there to be found before they could be ticked.

    It started at 255 and the second request took it down a step, which is the
    claim here: a *dozen* of these outlines is a dozen of the brightest pixels
    the window can draw, and the two ends of that complaint are the lightening
    of the ground and this.  So it is the lightest ink in the window and it is
    not white -- both halves matter, because what it does is contrast and what
    it was doing too much of was glare.

    The panes are group boxes too, and they are *not* in this rule -- a pane
    is a region and a box over the collection is a control -- which is why
    the two are found by name rather than by being group boxes at all.
    """
    sheet = themed.styleSheet()

    assert QColor(CHALK).lightness() < QColor("#ffffff").lightness(), (
        "the point of it is that it is not white"
    )
    assert QColor(CHALK).lightness() > QColor(PALE).lightness(), (
        "the lightest ink in the window is the controls', not the cards'"
    )
    for shade in (WALL, SHELL, STRIPE, FIELD, RAISED, EDGE, SELECT, SHADOW, BODY):
        assert QColor(CHALK).lightness() > QColor(shade).lightness(), shade
    assert CHALK in sheet
    for selector in (
        "QTreeView::indicator",
        "QGroupBox#filterbox",
        "QLineEdit#search",
        "QSpinBox",
    ):
        assert selector in sheet, selector


def test_a_check_box_says_which_way_it_is(themed):
    """A box that is on has to look different from one that is off.

    Qt's stylesheet language can draw a check box's frame and its fill but not
    a check mark, which is an image file.  So a ticked box is a *filled* one: an
    outlined box, or a solid one, which at 13px is the reading a glance gets --
    and half filled for a group row, which is neither on nor off.
    """
    sheet = themed.styleSheet()

    for state in ("QTreeView::indicator:checked", "QTreeView::indicator:indeterminate"):
        assert state in sheet, state


def test_the_search_box_is_outlined_by_name(themed):
    """By name, because a spin box holds a line edit of its own.

    ``QLineEdit`` as a selector matches subclasses, and the field inside a
    number box is one -- so a rule on it would draw a second rectangle a few
    pixels inside the first.
    """
    sheet = themed.styleSheet()

    assert "QLineEdit#search" in sheet
    assert "QLineEdit {" not in sheet, "the search box is the only line edit here"


def test_the_window_is_set_in_the_site_s_own_voice(themed):
    """The body font is the site's, in the size it sets its page at.

    The site's stylesheet opens with ``body{font:13px/1.45 "Segoe UI",Roboto,
    Helvetica,Arial,sans-serif}``, and every line its card does not size itself
    -- a stat, a set rung, a row of its list -- is set in that.  Qt's own
    default on Windows is the system's 9pt, which is 12px at the 96dpi the
    site's 13 is measured at, so the tool was one step short of it everywhere
    it had not named a size itself.
    """
    font = themed.font()

    assert tuple(font.families()[: len(SANS)]) == SANS
    assert font.pixelSize() == BODY_PX


def test_the_rail_is_set_a_step_up_from_the_body(themed):
    """The one size the window sets of its own, and the box drawn at the head
    of every row is that size too.

    The rail is a column of kind names down the left edge with a window's
    worth of height to spare, and the words there are the thing the player
    aims at -- the user's own reading of it.  In the sheet rather than in
    :mod:`app.sidebar` because two things are drawn at it and this is the one
    place both can see: the rows, and the chalk square at the head of each of
    them, which the sheet draws as a square of a stated size rather than
    anything the style measures.  A square two pixels smaller than the words
    beside it is a small box in a big row, which is what the rail had before.
    """
    sheet = themed.styleSheet()

    assert "QTreeView#rail" in sheet, "the rail's rule is not in the sheet"
    assert RAIL_PX > BODY_PX, "the rail's size is a step up, not a step down"
    assert f"font-size: {RAIL_PX}px" in sheet
    assert f"width: {RAIL_PX}px" in sheet, "the box is not the size of the words"


def test_the_rail_carries_its_own_ground_and_its_rows_their_rhythm(themed):
    """The rail's three rules that are not a colour a widget can be handed.

    A view's viewport is painted in the palette's ``Base``, which is the field
    the wall of cards is drawn on: left alone the column would be the same
    surface as the wall beside it, and the band under the pointer -- the
    reference's own way of saying where the pointer is -- would be drawn in the
    colour it is already on.  So the column is given the shell as its ground,
    and the band is a step up from it.

    The rhythm is the third: the reference gets the air between one row and the
    next from a line height, Qt has no such property, so it is put back as
    padding.  What the padding *measures* is asserted on a drawn rail in
    :mod:`tests.test_app_filters`; this is that the rules are there at all.
    """
    sheet = themed.styleSheet()

    def rule(selector: str) -> str:
        """The declarations of one rule, out of the sheet."""
        assert selector in sheet, f"{selector} is not in the sheet"
        return sheet.split(selector, 1)[1].split("}", 1)[0]

    assert f"background: {SHELL}" in rule("QTreeView#rail {")
    assert "padding: 4px 0" in rule("QTreeView#rail::item {")
    assert f"background: {FIELD}" in rule("QTreeView#rail::item:hover {")


def test_a_number_is_set_in_figures_that_line_up(themed):
    """The site asks for tabular figures wherever it lifts a number, and this
    window lifts numbers in columns -- the levels and counts down the
    collection, the stats down a card.

    Qt's stylesheet language has no ``font-variant-numeric``, so the request is
    made to the face instead, and both of the voices the window draws numbers
    in carry it: the body font the window is set in and the card's own serif.
    A face without such figures ignores the request rather than failing on it,
    which is why this is a claim about what was asked for and not about what
    the glyphs did.
    """
    assert themed.font().featureTags() == [TABULAR]
    assert _serif().featureTags() == [TABULAR]


def test_the_face_the_card_sets_its_stats_in_travels_with_the_tool():
    """Bitter is registered from ``app/fonts/``, not hoped for.

    The stack in ``app.card._serif`` names Bitter first and Georgia second, and
    Georgia is what every machine that has not installed the face would give --
    a different letterform, silently, with nothing on screen to say the card
    had fallen back.  So the face is shipped and registered at startup, and
    this is the registration rather than the drawing: the family the file
    answers to has to be there before any stylesheet can ask for it.

    A variable font answers with its named instances as well as its own name,
    which is why the question is whether the *family* is among them and not
    what the whole list is.
    """
    assert "Bitter" in _load_fonts()


def test_the_serif_face_the_card_asks_for_is_the_one_that_was_loaded():
    """And the two names are the same, read from their own sides.

    A registration that produced ``Bitter Pro`` or ``Bitter Regular`` would
    pass the test above and change nothing on the card: the stack names a
    family, and a family that is not the one the file answers to is a family
    that is not found.  So the first name in the card's own stack is compared
    with what the file registered.
    """
    (asked,) = _serif().families()[:1]

    assert asked in _load_fonts()
