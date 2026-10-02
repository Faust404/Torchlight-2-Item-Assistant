"""Tests for the window's colours.

One claim, and it is a claim about a *palette* rather than about the forty
lines that build it: the application is dark, its text is legible on it, and
the ground it is drawn on is the ground the cards are drawn on -- because a
window that is merely dark, and not the same dark as the thing it holds, is a
window with a seam down the middle of it.

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

from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QStyleFactory  # noqa: E402

from app.card import BODY, GROUND, LABEL  # noqa: E402
from app.theme import WHITE, apply_theme  # noqa: E402


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
    # building that style again.
    name = qapp.style().objectName()
    palette = QPalette(qapp.palette())
    sheet = qapp.styleSheet()
    apply_theme(qapp)
    try:
        yield qapp
    finally:
        restored = QStyleFactory.create(name) if name else None
        if restored is not None:
            qapp.setStyle(restored)
        qapp.setPalette(palette)
        qapp.setStyleSheet(sheet)


def test_the_window_is_dark(themed):
    """Dark is the claim: the ground is darker than the text standing on it."""
    palette = themed.palette()
    window = palette.color(QPalette.ColorRole.Window)
    text = palette.color(QPalette.ColorRole.WindowText)

    assert window.name() == GROUND
    assert text.name() == BODY
    assert window.lightness() < text.lightness()
    # Not merely darker: dark.  A mid-grey window with white text would pass
    # the line above and is not what "dark by default" means.
    assert window.lightness() < 64


def test_the_ground_is_the_cards_ground(themed):
    """The window and the cards are one surface rather than two.

    The cards are drawn on :data:`app.card.GROUND` by the wall itself, so the
    window behind them has to be the same colour -- otherwise the wall is a
    lighter rectangle floating in a darker window, which is the seam this
    avoids.
    """
    palette = themed.palette()
    assert palette.color(QPalette.ColorRole.Window).name() == GROUND

    # And what is written on it is the card's own body colour, so a label on
    # the window and a label on a card are the same grey.
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


def test_the_controls_are_outlined_in_white(themed):
    """The one colour in the window that is not the card palette's.

    Everything the player *operates* -- the check boxes down the rail, the
    search box, the two boxes over the collection and the number boxes in them
    -- is outlined in white, and nothing else in the window is.  A hairline in
    the palette's own greys does not read as a control against a ground this
    dark: the rail's check boxes were there to be found before they could be
    ticked.

    The panes are group boxes too, and they are *not* in this rule -- a pane
    is a region and a box over the collection is a control -- which is why
    the two are found by name rather than by being group boxes at all.
    """
    sheet = themed.styleSheet()

    assert QColor(WHITE).lightness() == 255, "the point of it is that it is white"
    assert WHITE in sheet
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
    a check mark, which is an image file.  So a ticked box is a *filled* one:
    white box, or a solid one, which at 13px is the reading a glance gets --
    and half filled for a group row, which is neither on nor off.
    """
    sheet = themed.styleSheet()

    for state in ("QTreeView::indicator:checked", "QTreeView::indicator:indeterminate"):
        assert state in sheet, state


def test_the_search_box_is_outlined_by_name(themed):
    """By name, because a spin box holds a line edit of its own.

    ``QLineEdit`` as a selector matches subclasses, and the field inside a
    number box is one -- so a rule on it would draw a second white rectangle a
    few pixels inside the first.
    """
    sheet = themed.styleSheet()

    assert "QLineEdit#search" in sheet
    assert "QLineEdit {" not in sheet, "the search box is the only line edit here"
