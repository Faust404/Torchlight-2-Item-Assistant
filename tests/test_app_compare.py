"""Tests for the comparison overlay: the copies of one item, side by side.

``app.tiles`` is where a wall of cards is tested, and the overlay draws on the
same wall (see ``tests/test_app_tiles.py``).  What is tested here is what the
overlay adds to one: a card per *copy* rather than per item, each saying its
own roll and its own last-seen place, and each with the one button that sends
exactly that copy back.

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
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QPushButton,
    QWidget,
)

from app.card import ItemCard  # noqa: E402
from app.compare import CompareOverlay, ReplicaCard  # noqa: E402
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
            found="Tab 1 · slot 2",
        ),
        row(
            card(name="Miss Gazer Man", level=0, blocks=(Block(AFFIX, ("+12% Crit Damage",)),)),
            fingerprint="fp-b",
            found="Tab 2 · slot 7",
        ),
    )


def opened(copies=None) -> tuple[QWidget, CompareOverlay]:
    """An overlay over a window-sized widget, opened on these copies."""
    host = QWidget()
    host.resize(900, 600)
    overlay = CompareOverlay(parent=host)
    overlay.open_for(list(copies if copies is not None else two_copies()))
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


def test_each_copy_says_where_it_was_last_seen(qapp):
    """A copy's place is its own.  The tile says the first copy's, which is
    the one thing about the group it can be sure of."""
    _, overlay = opened()
    assert texts(overlay, "found") == ["Tab 1 · slot 2", "Tab 2 · slot 7"]


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
    first.findChild(QPushButton, "putback").click()

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


def test_a_click_on_the_ground_puts_the_overlay_away(qapp):
    """What every overlay does, and it costs nothing to build: the header and
    its labels do not handle a press, so Qt hands it to the widget under
    them, which is the overlay itself."""
    _, overlay = opened()
    press(overlay)
    assert overlay.isHidden()


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
