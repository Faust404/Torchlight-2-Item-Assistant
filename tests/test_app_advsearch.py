"""Tests for the advanced search panel: the facets the bar has no room for.

What the four facets *mean* is ``app.models``' and is pinned in
``tests/test_app_filters.py``, against rows built by hand and with the bar out
of the way.  What is tested here is the panel: that it opens on the search in
force, that it is a draft -- nothing narrows until `Search`, and Esc, the cross
and the backdrop put it away with the collection exactly as it was -- and that
what `Search` hands over is the whole of what the controls say.

It is the comparison screen's shape, so it is tested the same way: a host the
size of a window with the panel over it (see ``tests/test_app_compare.py``),
which is what makes the geometry a thing that can be read.  What the *window*
does with the value the panel hands over -- the rail's ticks, the bar's chips
and the wall -- is the window's own wiring and is tested there
(``tests/test_app.py``).

No pixels are asserted, for the reasons ``tests/test_app_card.py`` gives: what
is asserted is what the controls say and which of them are on the wall.
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
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPalette  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QPushButton,
    QWidget,
)

from app.advsearch import (  # noqa: E402
    ALL_TYPES,
    CLASSES_HINT,
    NO_CLASSES,
    PANEL_MAX,
    AdvancedSearchOverlay,
)
from app.card import GOLD  # noqa: E402
from app.compare import MIN_INSET, SCRIM  # noqa: E402
from app.models import CLASSES, LEVEL_MAX, REQ_MAX, REQ_REST, Advanced  # noqa: E402
from app.sidebar import UNCLASSIFIED  # noqa: E402
from app.theme import CHALK  # noqa: E402

from test_app_filters import BOOTS, BROKEN, HELMET, SWORD  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session; Qt allows no more."""
    app = QApplication.instance() or QApplication([])
    yield app


#: What a small collection holds: two kinds under Armor, one under Weapons, and
#: the empty kind -- which is a real kind in a group of its own, and the reason
#: a kind is a triple rather than a word.
PLACES = [BOOTS, HELMET, SWORD, BROKEN]

#: The words the grid draws over those four, in the rail's own order.
PLACE_WORDS = ["Boots", "Helmet", "Sword", UNCLASSIFIED]


def opened(state=None, places=PLACES, classes=None, size=(900, 600)):
    """A panel over a window-sized widget, opened on this search.

    The host is shown, which is not decoration: a hidden widget's children are
    never laid out, so the panel's geometry is a thing a hidden window does not
    have.  ``classes`` is ``None`` for the four the game has; the other case is
    a machine without the reference database, which is a test of its own.
    """
    host = QWidget()
    host.resize(*size)
    host.show()
    overlay = AdvancedSearchOverlay(parent=host)
    overlay.set_kinds(list(places))
    overlay.open_for(
        Advanced() if state is None else state,
        CLASSES if classes is None else classes,
    )
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


def escaped(widget) -> None:
    """The Escape key, sent the way the platform would send it."""
    QApplication.sendEvent(
        widget,
        QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def watched(overlay) -> list:
    """Everything the panel hands over, which is only ever what `Search` sends."""
    heard = []
    overlay.searched.connect(heard.append)
    return heard


def boxes(grid) -> dict[str, QCheckBox]:
    """The kind boxes the grid is drawing, by the word on them."""
    return {box.text(): box for box in grid.findChildren(QCheckBox)}


def tabs(grid) -> dict[str, QPushButton]:
    """The grid's group buttons, by the word on them."""
    return {button.text(): button for button in grid.findChildren(QPushButton)}


#: A search with every one of the nine facets moved, so that "the panel opened
#: on it" and "the panel handed it back" are statements about all nine at once
#: rather than about whichever control a test happened to look at.
EVERYTHING = Advanced(
    text="drill",
    tiers=frozenset({"Unique"}),
    low=20,
    high=60,
    item_low=5,
    item_high=45,
    sockets=frozenset({2, 3}),
    reqs=((30, REQ_MAX), (0, REQ_MAX), (10, 400), REQ_REST[3]),
    classes=frozenset({"Embermage"}),
    places=frozenset({SWORD}),
)


# --------------------------------------------------------------------------
# Opening and closing
# --------------------------------------------------------------------------


def test_the_overlay_covers_the_window_and_starts_hidden(qapp):
    """A child of the window rather than a window of its own: what it narrows
    is behind it, and a second window can be lost behind the game."""
    host = QWidget()
    host.resize(900, 600)
    overlay = AdvancedSearchOverlay(parent=host)

    assert overlay.isHidden(), "the panel was up before anything asked for it"

    overlay.open_for(Advanced())

    assert not overlay.isHidden()
    assert overlay.size() == host.size()


def test_the_panel_is_inset_from_the_window_on_every_side(qapp):
    """A panel over the collection rather than a screen instead of it."""
    host, overlay = opened()

    panel = overlay.panel().geometry()
    assert panel.left() >= MIN_INSET
    assert panel.top() >= MIN_INSET
    assert panel.right() <= host.width() - MIN_INSET
    assert panel.bottom() <= host.height() - MIN_INSET
    assert overlay.size() == host.size(), "the backdrop is still the whole window"


def test_the_panel_is_capped_and_the_backdrop_dims_the_window(qapp):
    """Wide enough for the two-column grid of kinds, and no wider.

    And the window behind it is dimmed rather than hidden, which is the scrim
    the comparison screen paints -- deliberately the same one: both are the
    window dimmed, and neither is a colour of its own.
    """
    host, overlay = opened(size=(1400, 800))

    assert overlay.panel().width() <= PANEL_MAX
    assert overlay.panel().width() < host.width()
    painted = overlay.palette().color(QPalette.ColorRole.Window)
    assert [painted.red(), painted.green(), painted.blue()] == list(SCRIM[:3])


def test_escaping_the_panel_puts_it_away_and_applies_nothing(qapp):
    _, overlay = opened()
    heard = watched(overlay)
    overlay.socket_chips[2].setChecked(True)

    escaped(overlay)

    assert overlay.isHidden()
    assert heard == [], "Esc handed a search over"


def test_the_cross_puts_it_away_and_applies_nothing(qapp):
    _, overlay = opened()
    heard = watched(overlay)

    overlay.findChild(QPushButton, "aclose").click()

    assert overlay.isHidden()
    assert heard == []


def test_a_press_on_the_backdrop_puts_it_away(qapp):
    """Everything outside the panel is the window, so a press there says the
    player is done here."""
    _, overlay = opened()
    heard = watched(overlay)

    press(overlay)

    assert overlay.isHidden()
    assert heard == []


def test_a_press_on_the_panel_is_not_a_press_on_the_backdrop(qapp):
    """The panel takes its own presses, which is what leaves the backdrop the
    presses actually aimed at it.

    This is the whole reason the panel is a frame that accepts what it is sent:
    a widget that ignored the press would pass it up to its parent, and a click
    on the title would put away the panel the player was filling in.
    """
    _, overlay = opened()

    press(overlay.panel(), at=(30.0, 30.0))

    assert not overlay.isHidden(), "a press inside the panel closed it"


# --------------------------------------------------------------------------
# What it opens on, and what it hands back
# --------------------------------------------------------------------------


def test_the_panel_opens_on_the_search_already_in_force(qapp):
    """The draft starts from what is narrowing the collection, so that ticking
    the one thing a player came for does not throw away the rest of it."""
    _, overlay = opened(EVERYTHING)

    assert overlay.draft() == EVERYTHING


def test_every_control_the_panel_has_is_in_that_draft(qapp):
    """Named one by one, because the line above is one equality and this is
    which control each of its fields came off."""
    _, overlay = opened(EVERYTHING)

    assert overlay.name.text() == "drill"
    assert {
        word for word, chip in overlay.rarity_chips.items() if chip.isChecked()
    } == {"Unique"}
    assert (overlay.player_low.value(), overlay.player_high.value()) == (20, 60)
    assert (overlay.item_low.value(), overlay.item_high.value()) == (5, 45)
    assert {
        count for count, chip in overlay.socket_chips.items() if chip.isChecked()
    } == {2, 3}
    assert [
        (overlay.req_spins[word][0].value(), overlay.req_spins[word][1].value())
        for word in ("Strength", "Dexterity", "Focus", "Vitality")
    ] == [(30, REQ_MAX), (0, REQ_MAX), (10, 400), (0, REQ_MAX)]
    assert {
        word for word, box in overlay.class_boxes.items() if box.isChecked()
    } == {"Embermage"}
    assert overlay.types.ticks() == {SWORD}


def test_the_resting_panel_is_the_default_search(qapp):
    """Not a second state written down: every field is at rest in an empty
    ``Advanced()``, which is what makes Reset and the opening state the same
    state rather than two that happen to agree."""
    _, overlay = opened()

    assert overlay.draft() == Advanced()


def test_search_hands_over_the_whole_search_and_closes(qapp):
    """One press, one value: the window is told everything at once, because it
    applies the bar, the rail and the wall as a single move."""
    _, overlay = opened()
    heard = watched(overlay)

    overlay.name.setText("drill")
    overlay.rarity_chips["Unique"].setChecked(True)
    overlay.item_low.setValue(5)
    overlay.socket_chips[2].setChecked(True)
    overlay.req_spins["Strength"][0].setValue(30)
    overlay.class_boxes["Embermage"].setChecked(True)
    boxes(overlay.types)["Sword"].setChecked(True)

    overlay.search_button.click()

    assert len(heard) == 1, "Search is one move"
    assert overlay.isHidden(), "Search left the panel up"
    assert heard[0] == overlay.draft(), "what was handed over is not what was said"
    assert heard[0].text == "drill"
    assert heard[0].tiers == {"Unique"}
    assert (heard[0].item_low, heard[0].item_high) == (5, LEVEL_MAX)
    assert heard[0].sockets == {2}
    assert heard[0].reqs[0] == (30, REQ_MAX)
    assert heard[0].classes == {"Embermage"}
    assert heard[0].places == {SWORD}


def test_ticking_things_says_nothing_at_all(qapp):
    """The draft is the point: a panel that applied as it was filled in would
    be a panel whose cross is a lie."""
    _, overlay = opened()
    heard = watched(overlay)

    overlay.name.setText("drill")
    overlay.rarity_chips["Unique"].setChecked(True)
    overlay.socket_chips[2].setChecked(True)
    boxes(overlay.types)["Sword"].setChecked(True)

    assert heard == []


def test_reset_puts_every_control_back_and_applies_nothing(qapp):
    """`Reset` and `Search` are two words, and this is the difference between
    them: one empties the form, the other one runs it."""
    _, overlay = opened(EVERYTHING)
    heard = watched(overlay)

    overlay.reset_button.click()

    assert overlay.draft() == Advanced()
    assert heard == []
    assert not overlay.isHidden(), "Reset closed the panel"


# --------------------------------------------------------------------------
# The class boxes, which are only sometimes worth having
# --------------------------------------------------------------------------


def test_the_class_boxes_are_offered_when_the_reference_database_is_found(qapp):
    _, overlay = opened()

    assert list(overlay.class_boxes) == list(CLASSES)
    assert all(box.isEnabled() for box in overlay.class_boxes.values())
    assert overlay.class_note.isHidden(), "the note is for the other case"
    assert overlay.class_note.text() == CLASSES_HINT
    assert "names no class" in CLASSES_HINT, "the rule the boxes read is said"


def test_the_class_section_says_so_when_there_is_nothing_to_narrow_by(qapp):
    """A machine without the reference database: the restrictions are in no
    file of the game's, so the section could only ever match nothing -- and a
    control that can only match nothing is a control that lies."""
    _, overlay = opened(Advanced(classes=frozenset({"Embermage"})), classes=())

    assert not any(box.isEnabled() for box in overlay.class_boxes.values())
    assert not any(box.isChecked() for box in overlay.class_boxes.values())
    assert not overlay.class_note.isHidden()
    assert overlay.class_note.text() == NO_CLASSES
    assert overlay.draft().classes == frozenset(), "a dark box is not a tick"


# --------------------------------------------------------------------------
# The type grid, which is the rail drawn in the panel
# --------------------------------------------------------------------------


def test_the_grid_draws_the_kinds_the_collection_holds(qapp):
    """The rail's own shape in the rail's own order: a button per group, and
    the kinds of the chosen one under it -- the empty kind written with the
    word the rail writes over it."""
    _, overlay = opened()

    grid = overlay.types
    assert list(tabs(grid)) == [ALL_TYPES, "Armor", "Weapons", "Other"]
    assert tabs(grid)[ALL_TYPES].isChecked()
    assert [box.text() for box in grid.findChildren(QCheckBox)] == PLACE_WORDS


def test_a_group_button_shows_only_that_group_s_kinds(qapp):
    _, overlay = opened()

    tabs(overlay.types)["Weapons"].click()

    assert [box.text() for box in overlay.types.findChildren(QCheckBox)] == ["Sword"]


def test_the_kinds_ticked_reach_the_search_as_places(qapp):
    """What makes the grid a second view rather than a second filter: what it
    hands over is the rail's own value, a set of places, so a player who ticks
    Boots here and one who ticks Boots on the rail have asked for the same
    collection."""
    _, overlay = opened()

    boxes(overlay.types)["Helmet"].setChecked(True)
    assert overlay.draft().places == {HELMET}

    boxes(overlay.types)["Helmet"].setChecked(False)
    assert overlay.draft().places == frozenset()


def test_a_tick_on_a_kind_the_collection_has_lost_goes_with_it(qapp):
    """The collection is thrown away and built again every poll, and a kind
    that is no longer in it is no longer a thing to narrow by."""
    _, overlay = opened(EVERYTHING)

    overlay.set_kinds([BOOTS, HELMET])

    assert SWORD not in overlay.types.ticks()
    assert overlay.draft().places == frozenset()


def test_a_grid_that_has_not_moved_is_not_built_again(qapp):
    """A grid rebuilt under the pointer is a grid that loses the click -- the
    same bargain the rail makes, and the reason the shape is compared first."""
    _, overlay = opened()
    drawn = overlay.types.findChildren(QCheckBox)

    overlay.types.set_kinds(list(PLACES))

    assert overlay.types.findChildren(QCheckBox) == drawn, "the grid was rebuilt"


def test_a_group_the_collection_has_lost_goes_back_to_showing_everything(qapp):
    """Rather than to a tab that matches nothing."""
    _, overlay = opened()
    tabs(overlay.types)["Weapons"].click()

    overlay.set_kinds([BOOTS, HELMET])

    assert tabs(overlay.types)[ALL_TYPES].isChecked()
    assert [box.text() for box in overlay.types.findChildren(QCheckBox)] == [
        "Boots",
        "Helmet",
    ]


def test_a_group_with_every_kind_under_it_ticked_is_drawn_in_gold(qapp):
    """The rail's own statement about a heading, on the button: gold for a
    group that is wholly ticked, the control ink for one that is not."""
    _, overlay = opened()
    buttons = tabs(overlay.types)

    assert GOLD not in buttons["Armor"].styleSheet()

    boxes(overlay.types)["Boots"].setChecked(True)
    boxes(overlay.types)["Helmet"].setChecked(True)

    assert GOLD in buttons["Armor"].styleSheet()
    assert CHALK in buttons["Weapons"].styleSheet(), "nothing under it is ticked"
