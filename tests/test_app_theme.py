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

from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QStyleFactory  # noqa: E402

from app.card import BODY, GROUND, LABEL  # noqa: E402
from app.theme import apply_theme  # noqa: E402


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
