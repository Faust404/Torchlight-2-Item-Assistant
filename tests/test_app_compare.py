"""Tests for the comparison panel: the copies of one item, side by side.

``app.tiles`` is where a wall of cards is tested, and the panel draws on the
same wall (see ``tests/test_app_tiles.py``).  What is tested here is what the
panel adds to one: a card per *copy* rather than per item, each saying its own
roll and its own last-seen place, and each with the one button that sends
exactly that copy back -- and the shape it opens in, a panel inset inside a
dimmed window rather than a screen of its own.

Two of the tests here are about geometry, which the rest of this suite leaves
to the widgets: a panel that is the window again is the thing the request was
about, so where the panel's edges land is the feature rather than a detail of
how it is drawn.

No pixels are asserted, for the reasons ``tests/test_app_card.py`` gives --
what is asserted is what the widgets say and which of them are on the wall.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Before the first PySide6 import, like tests/test_app.py.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 is not installed")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPalette  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QPushButton,
    QWidget,
)

from app.card import ItemCard  # noqa: E402
from app.compare import (  # noqa: E402
    MIN_INSET,
    CompareOverlay,
    ReplicaCard,
    inset_for,
)
from tl2stash.card import AFFIX, Block  # noqa: E402

from test_app_card import card  # noqa: E402
from test_app_tiles import row  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session; Qt allows no more."""
    app = QApplication.instance() or QApplication([])
    yield app


def texts(drawn, name: str) -> list[str]:
    return [
        label.text()
        for label in drawn.findChildren(QLabel)
        if label.objectName() == name
    ]


def two_copies() -> tuple:
    """The screen the feature was asked for: one item, two rolls of it.

    The two differ in the numbers a player actually compares -- the crit
    damage, as the reference's own screenshot does -- and in the fingerprint,
    which is what a copy *is*: a hash of its own bytes.
    """
    return (
        row(
            card(name="Miss Gazer Man", level=0, blocks=(Block(AFFIX, ("+8% Crit Damage",)),)),
            fingerprint="fp-a",
        ),
        row(
            card(name="Miss Gazer Man", level=0, blocks=(Block(AFFIX, ("+12% Crit Damage",)),)),
            fingerprint="fp-b",
        ),
    )


def opened(copies=None, size=(900, 600)) -> tuple[QWidget, CompareOverlay]:
    """An overlay over a window-sized widget, opened on these copies.

    The host is shown, which is not decoration: a hidden widget's children are
    never laid out, so the panel's geometry and the wall's scrolling are both
    things a hidden window does not have.
    """
    host = QWidget()
    host.resize(*size)
    host.show()
    overlay = CompareOverlay(parent=host)
    overlay.open_for(list(copies if copies is not None else two_copies()))
    QApplication.processEvents()
    return host, overlay


def press(widget, at: tuple[float, float] = (4.0, 4.0)) -> None:
    """A left press, sent to a widget the way a real one would arrive."""
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(*at),
        QPointF(*at),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)


# --------------------------------------------------------------------------
# What it shows
# --------------------------------------------------------------------------


def test_one_card_per_copy_rather_than_per_item(qapp):
    """The whole point of the screen.  A tile is one card for every copy, and
    this is the one place they come apart: two rolls, two cards, two sets of
    numbers -- which is what a player keeps both of them for."""
    _, overlay = opened()

    assert [copy.text() for copy in overlay.cards()] == [
        "Miss Gazer Man\n+8% Crit Damage",
        "Miss Gazer Man\n+12% Crit Damage",
    ]
    assert len(overlay.findChildren(ItemCard)) == 2
    assert texts(overlay, "ctitle") == ["Item Comparison"]


def test_the_overlay_covers_the_window_and_starts_hidden(qapp):
    host = QWidget()
    host.resize(900, 600)
    overlay = CompareOverlay(parent=host)
    assert overlay.isHidden(), "the overlay was up before anything asked for it"

    overlay.open_for(list(two_copies()))
    assert not overlay.isHidden()
    assert overlay.size() == host.size()


def test_every_copy_offers_transfer_to_stash(qapp):
    """The reference's own words for the button, and the collection's too.

    It used to read "Put back", which was this screen's private name for a
    thing the rest of the tool calls by one name.  A copy goes back to the
    stash it came from, and that is what the button says.
    """
    _, overlay = opened()

    for copy in overlay.cards():
        button = copy.findChild(QPushButton, "transfer")
        assert button is not None, "a copy with no way back to the game"
        assert button.text() == "Transfer to Stash"


def test_a_copy_does_not_say_where_it_was_last_seen(qapp):
    """A copy is the tool's now, so the tab and slot it once sat in say nothing
    about it.  What a copy is *is* its own numbers, which is the whole reason
    there is a card per copy."""
    _, overlay = opened()

    assert texts(overlay, "found") == []
    assert not any(
        "slot" in label.text().lower() for label in overlay.findChildren(QLabel)
    )


def test_a_copy_that_will_not_parse_is_a_sentence_here_too(qapp):
    """An item the parser cannot read has no tier to ink it with and no
    picture to draw, so it is the sentence -- and it is still a copy the
    player may want to put back."""
    _, overlay = opened(
        [
            row(card(name="Broken One"), fingerprint="fp-bad"),
            row("Could not read this item: not enough bytes", fingerprint="fp-bad"),
        ]
    )
    assert overlay.cards()[1].text() == "Could not read this item: not enough bytes"
    assert texts(overlay, "hint") == ["Could not read this item: not enough bytes"]


# --------------------------------------------------------------------------
# The panel, which is what it opens as
# --------------------------------------------------------------------------


def test_the_panel_is_inset_from_the_window_on_every_side(qapp):
    """A pop-up over the collection rather than a screen instead of it.

    The window is still there behind the panel, dimmed, so what a player is
    comparing against is not something they have to put away to look at.
    """
    host, overlay = opened()

    panel = overlay.panel().geometry()
    assert panel.left() >= MIN_INSET
    assert panel.top() >= MIN_INSET
    assert panel.right() <= host.width() - MIN_INSET
    assert panel.bottom() <= host.height() - MIN_INSET
    assert overlay.size() == host.size(), "the backdrop is still the whole window"


def test_the_backdrop_dims_the_window_rather_than_hiding_it(qapp):
    """The collection is still there behind the panel: that is the whole
    difference between a pop-up and a screen of its own.

    Read off a pale window drawn under the backdrop -- a white one, so that
    what comes back is the scrim's own arithmetic rather than two near-blacks
    that cannot be told apart.  Dimmer, because the window is dimmed; not
    black, because it is a window and not a curtain.
    """
    host = QWidget()
    host.resize(900, 600)
    host.setAutoFillBackground(True)
    palette = host.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
    host.setPalette(palette)
    host.show()
    QApplication.processEvents()
    before = host.grab().toImage().pixelColor(5, 5)

    overlay = CompareOverlay(parent=host)
    overlay.open_for(list(two_copies()))
    QApplication.processEvents()
    after = host.grab().toImage().pixelColor(5, 5)

    assert before.lightness() == 255, "the window under the backdrop is not pale"
    assert after.lightness() < before.lightness(), "the window was not dimmed"
    assert after.lightness() > 0, "the window was hidden rather than dimmed"


def test_the_inset_is_a_share_of_the_window_with_a_floor_under_it(qapp):
    """Worked out from the window rather than fixed, so a large screen gets a
    large panel -- and floored, because a share of a small window is a small
    fraction and the numbers in a card do not shrink with the window."""
    assert inset_for(900, 600) == round(600 * 0.06)
    assert inset_for(1600, 1200) > inset_for(900, 600)
    assert inset_for(400, 300) == MIN_INSET, "a small window must keep a panel"


def test_the_panel_follows_the_window_when_the_window_resizes(qapp):
    """The overlay filters its parent's resizes; the panel is pinned inside
    the backdrop rather than placed from it, so the whole of a resize is one
    margin."""
    host, overlay = opened()

    host.resize(400, 300)
    QApplication.processEvents()

    panel = overlay.panel().geometry()
    assert overlay.size() == host.size()
    assert (panel.left(), panel.top()) == (MIN_INSET, MIN_INSET)
    assert panel.right() <= 400 - MIN_INSET
    assert panel.bottom() <= 300 - MIN_INSET


def test_the_wall_scrolls_when_there_are_more_copies_than_fit(qapp):
    """The other half of the request: a player with twenty rolls of one unique
    gets a scrollbar rather than a screen with eleven of them on it."""
    copies = [
        row(
            card(
                name="Miss Gazer Man",
                level=0,
                blocks=(Block(AFFIX, (f"+{n}% Crit Damage",)),),
            ),
            fingerprint=f"fp-{n}",
        )
        for n in range(20)
    ]
    _, overlay = opened(copies)

    assert overlay.wall().verticalScrollBar().maximum() > 0, "nothing scrolled"
    assert len(overlay.cards()) == 20


def test_opening_again_does_not_leave_the_last_ones_behind(qapp):
    """The second click of the day replaces the first screen rather than
    piling onto it: an overlay still holding the last item's cards would
    offer to put back copies of something the player is no longer looking at."""
    copies = two_copies()
    _, overlay = opened(copies)
    overlay.open_for(copies[:1])

    assert len(overlay.cards()) == 1
    assert len(overlay.findChildren(ReplicaCard)) == 1


# --------------------------------------------------------------------------
# Putting one back
# --------------------------------------------------------------------------


def test_put_back_hands_up_the_one_copy_it_was_asked_for(qapp):
    """One fingerprint, not the group.  The overlay exists because the copies
    can be told apart; a button that returned all of them would be the
    collection's own button, which is still where it was."""
    _, overlay = opened()

    asked: list[str] = []
    overlay.put_back.connect(asked.append)
    (first, second) = overlay.cards()
    first.findChild(QPushButton, "transfer").click()

    assert asked == ["fp-a"], "the wrong copy was asked for"


def test_a_copy_that_has_gone_loses_its_card_and_the_last_one_closes_it(qapp):
    _, overlay = opened()

    overlay.drop("fp-a")
    assert [copy.row.fingerprint for copy in overlay.cards()] == ["fp-b"]
    assert not overlay.isHidden(), "the overlay closed with a copy still on it"

    overlay.drop("fp-b")
    assert overlay.cards() == []
    assert overlay.isHidden(), "the overlay stayed up with nothing in it"


# --------------------------------------------------------------------------
# Putting the overlay away
# --------------------------------------------------------------------------


def test_the_close_button_puts_the_overlay_away(qapp):
    _, overlay = opened()
    overlay.findChild(QPushButton, "cclose").click()
    assert overlay.isHidden()


def test_escape_puts_the_overlay_away(qapp):
    _, overlay = opened()
    QApplication.sendEvent(
        overlay,
        QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert overlay.isHidden()


def test_a_click_on_the_backdrop_puts_the_overlay_away(qapp):
    """What every pop-up does.  The backdrop is the part of the window the
    panel is not covering, and the way it knows a click was aimed at it is
    that the click reached it at all."""
    _, overlay = opened()
    press(overlay)
    assert overlay.isHidden()


def test_a_click_on_the_panel_does_not_put_it_away(qapp):
    """Now that there is a panel there are two places a press can land, and
    only one of them means "done looking" -- the title and the strip beside
    it are the pop-up, not the window behind it."""
    _, overlay = opened()
    panel = overlay.panel()

    press(panel)
    press(panel, at=(200.0, 20.0))

    assert not overlay.isHidden(), "a click on the panel closed it"


def test_a_click_inside_the_panel_stops_at_the_panel(qapp):
    """Nothing in the panel handles a press -- not the title, not the wall --
    so Qt walks each of them up to the nearest widget that does, which is the
    panel.  Without that the backdrop would take them too, and the pop-up
    would close on a click on its own title."""
    _, overlay = opened()

    press(overlay.findChild(QLabel, "ctitle"))
    press(overlay.wall().viewport())

    assert not overlay.isHidden()


def test_a_click_on_a_copy_does_not_put_it_away(qapp):
    """The one place a press must *not* close the screen: comparing two rolls
    is done by reading them, and a click on a card that closed the overlay
    would make that a two-handed job.

    The click is sent to the card's *card*, not to a button on it -- nothing
    inside the frame handles a press, so this is exactly the click that used
    to walk up to the overlay and dismiss it."""
    _, overlay = opened()
    drawn = overlay.cards()[0]
    press(drawn)
    press(drawn.findChild(ItemCard))
    press(drawn, at=(30.0, 60.0))
    assert not overlay.isHidden()
