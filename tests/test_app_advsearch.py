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

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QFontMetrics, QKeyEvent, QMouseEvent, QPalette  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QWidget,
)

from app.advsearch import (  # noqa: E402
    ALL_TYPES,
    CLASSES_HINT,
    NO_CLASSES,
    PANEL_MAX,
    SUBGROUP_INDENT,
    AdvancedSearchOverlay,
    Section,
    vocabulary,
)
from app.card import GOLD, HEAD, LABEL  # noqa: E402
from app.compare import MIN_INSET, SCRIM  # noqa: E402
from app.models import (  # noqa: E402
    CLASSES,
    ELEMENTS,
    ELEMENT_REST,
    LEVEL_MAX,
    NUMBER_MAX,
    REQ_MAX,
    REQ_REST,
    REQ_WORDS,
    Advanced,
)
from app.sidebar import UNCLASSIFIED  # noqa: E402
from app.theme import CHALK  # noqa: E402
from tl2stash.card import Rung  # noqa: E402

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

#: A collection wide enough to say something about the grid's *shape*: six
#: armour kinds, which is a full row of four and one of two, and two weapon
#: subgroups, which is the one group that has headings inside it.
WIDE = [
    ("Armor", None, "Boots"),
    ("Armor", None, "Chest Armor"),
    ("Armor", None, "Gloves"),
    ("Armor", None, "Helmet"),
    ("Armor", None, "Pants"),
    ("Armor", None, "Shoulder Armor"),
    ("Weapons", "One-Handed", "Axe"),
    ("Weapons", "One-Handed", "Sword"),
    ("Weapons", "Two-Handed", "Bow"),
    ("Other", None, ""),
]


def opened(state=None, places=PLACES, classes=None, vocabulary=(), size=(900, 600)):
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
        vocabulary,
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


def sections(overlay) -> dict[str, Section]:
    """The panel's sections, by the caption over each of them.

    By caption rather than in the order they are found, because two of the
    seven are built before the column that holds them in the order it holds
    them -- and the caption is what a reader would name a section by anyway.
    """
    return {
        section.findChildren(QLabel)[0].text(): section
        for section in overlay.findChildren(Section)
    }


def notes(section) -> list[str]:
    """The side-notes drawn in one section, by their own shape.

    A note is a *wrapped* label -- the one thing in a section that has to be
    able to run onto a second line.  A caption and a row's name are one line
    each and are never wrapped, so this reads the notes out without needing to
    know the ink they are drawn in.
    """
    return [
        label.text() for label in section.findChildren(QLabel) if label.wordWrap()
    ]


def tabs(grid) -> dict[str, QPushButton]:
    """The grid's group buttons, by the word on them."""
    return {button.text(): button for button in grid.findChildren(QPushButton)}


def drawn(grid) -> list[str]:
    """Every word the grid is drawing, in the order it draws them.

    Read off a *shown* grid's geometry rather than off the list of widgets it
    holds: a row is a ``y`` and the order within it is the ``x``, which is what
    the player reads.  A grid that drew every kind at once but put the group
    headings somewhere else would pass a test written against the widget list
    and fail this one.
    """
    parts = [
        widget
        for widget in grid.findChildren(QWidget)
        if isinstance(widget, (QLabel, QCheckBox)) and widget.text()
    ]
    parts.sort(key=lambda widget: (widget.y(), widget.x()))
    return [widget.text() for widget in parts]


def rows(grid) -> list[list[QCheckBox]]:
    """The kind boxes as the grid draws them: one list per line."""
    lines: dict[int, list[QCheckBox]] = {}
    for box in grid.findChildren(QCheckBox):
        lines.setdefault(box.y(), []).append(box)
    return [
        sorted(lines[y], key=lambda box: box.x()) for y in sorted(lines)
    ]


def only(grid, *words: str) -> None:
    """Narrow the grid to these kinds, ticking them and unticking the rest.

    The grid opens with every box ticked -- see :meth:`app.advsearch.TypeGrid.
    tick` -- so asking for one kind is a matter of clearing the others, and
    this is that, written once for the tests that want a narrowed grid.
    """
    for word, box in boxes(grid).items():
        box.setChecked(word in words)


def pressed(button) -> None:
    """Press a button and lay out what the press built.

    A press on a group button rebuilds the grid, and a widget has no geometry
    until the layout has run -- so a test that read the boxes straight after
    one would read a grid of widgets all sitting at the origin.  A window
    lays out on the way back round the event loop, and so does this.
    """
    button.click()
    QApplication.processEvents()


def element_pairs(spins: dict) -> dict[str, tuple[int, int]]:
    """Where an element section's rows stand, with the resting ones left out.

    Which is the reading the panel itself does -- a row nobody has moved is not
    part of the search -- so a test asserting against this is asserting against
    the same rule the draft applies, one element at a time.
    """
    return {
        element: (low.value(), high.value())
        for element, (low, high) in spins.items()
        if (low.value(), high.value()) != ELEMENT_REST
    }


#: A search with every one of the twelve facets moved, so that "the panel
#: opened on it" and "the panel handed it back" are statements about all twelve
#: at once rather than about whichever control a test happened to look at.
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
    damage=(("fire", 20, 40),),
    armor=(("physical", 100, NUMBER_MAX),),
    stats=(("to fire damage", 0, NUMBER_MAX), ("to strength", 20, 60)),
    bonuses=True,
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
    """As wide as the form needs and no wider than a form should be.

    And the window behind it is dimmed rather than hidden, which is the scrim
    the comparison screen paints -- deliberately the same one: both are the
    window dimmed, and neither is a colour of its own.
    """
    host, overlay = opened(size=(1400, 800))

    assert overlay.panel().width() <= PANEL_MAX
    assert overlay.panel().width() < host.width()
    painted = overlay.palette().color(QPalette.ColorRole.Window)
    assert [painted.red(), painted.green(), painted.blue()] == list(SCRIM[:3])


def test_the_panel_opens_at_the_width_of_the_form_it_holds(qapp):
    """The user's *"expand the width of the pop up window itself to comfortably
    show everything"*, stated as what the panel is made of.

    The panel is as wide as the form wants to be drawn, so no section is
    squeezed below the size its own contents ask for -- which is the thing the
    user was buying: rows drawn whole rather than rows drawn narrow because a
    scroll area guessed a width for them.  And there is never a sideways bar:
    the policy is off rather than merely satisfied, because "nothing here is
    reached by scrolling across" and "the rows happen to fit today" are two
    different statements and only the first one is the request.
    """
    _, overlay = opened(size=(1400, 900))
    body = overlay.findChild(QScrollArea, "abody")
    inside = body.widget()

    assert body.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert not body.horizontalScrollBar().isVisible()
    assert body.viewport().width() >= inside.sizeHint().width(), (
        "the form is wider than the window it scrolls in"
    )
    for caption, section in sections(overlay).items():
        assert section.width() >= section.sizeHint().width(), f"{caption} is squeezed"


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
    assert element_pairs(overlay.damage_spins) == {"fire": (20, 40)}
    assert element_pairs(overlay.armor_spins) == {"physical": (100, NUMBER_MAX)}
    assert [row.value() for row in overlay.stat_rows] == [
        ("to fire damage", 0, NUMBER_MAX),
        ("to strength", 20, 60),
    ]
    assert overlay.bonuses_box.isChecked()
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
    only(overlay.types, "Sword")

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
# The two element sections and the property rows
# --------------------------------------------------------------------------


def test_the_two_element_sections_offer_the_game_s_five_elements_each(qapp):
    """Damage and Armor are the same five rows drawn twice, which is the whole
    reason they are built by one piece of code: a hand-written copy is a place
    for the fifth element to go missing from."""
    _, overlay = opened()

    assert list(overlay.damage_spins) == list(ELEMENTS)
    assert list(overlay.armor_spins) == list(ELEMENTS)
    assert [row[0].value() for row in overlay.damage_spins.values()] == [0] * 5
    assert [row[1].value() for row in overlay.damage_spins.values()] == [
        NUMBER_MAX
    ] * 5


def test_a_row_nobody_has_moved_is_not_part_of_the_search(qapp):
    """The rest reading, which is what makes a form of ten number boxes free.

    A row at 0 to :data:`~app.models.NUMBER_MAX` covers everything there is,
    so leaving it in the search would be asking a question with no answer but
    *yes* -- and the model would have to compare every pair against that range
    a second time to find out.
    """
    _, overlay = opened()

    assert overlay.draft().damage == ()

    overlay.damage_spins["fire"][1].setValue(60)
    assert overlay.draft().damage == (("fire", 0, 60),)

    overlay.damage_spins["fire"][1].setValue(NUMBER_MAX)
    assert overlay.draft().damage == (), "and back to the rest it goes"


def test_the_five_elements_come_out_in_the_game_s_own_order(qapp):
    """The model keys them, so the order is not what a dict happened to hold:
    it is the order the five rows are drawn in, which is the order the card
    draws its own parts in."""
    _, overlay = opened()

    overlay.damage_spins["poison"][0].setValue(1)
    overlay.damage_spins["physical"][0].setValue(1)

    assert overlay.draft().damage == (
        ("physical", 1, NUMBER_MAX),
        ("poison", 1, NUMBER_MAX),
    )


def test_the_four_named_sections_are_rows_and_nothing_else(qapp):
    """The user's *"remove the extra text"*, as what is in the panel.

    Under Stat Requirements, Damage, Armor and Stats there is nothing but the
    rows now.  Two notes were asked to stay and they are checked here with the
    same reading, because the point is what the panel's sections carry: the
    sockets sentence, which is the one thing a row of chips cannot say on its
    own, and the Class note, which is load-bearing -- it is what tells a player
    why those boxes are dark when the reference database is missing.

    Type is in the first list as well and not because it was named: the
    reference carries a note there ("nothing ticked means any type, as does
    everything ticked") and this panel deliberately does not, so a later
    reader adding it back has to mean to.
    """
    _, overlay = opened()
    by_caption = sections(overlay)

    for caption in ("Stat Requirements", "Damage", "Armor", "Stats", "Type"):
        assert notes(by_caption[caption]) == [], f"{caption} has kept its note"

    assert notes(by_caption["General"]) == [
        "No chip ticked means any number of sockets."
    ]
    assert notes(by_caption["Class"]) == [CLASSES_HINT]


def test_what_the_removed_notes_said_is_on_the_controls_they_were_about(qapp):
    """Nothing the four notes said has left the application.

    Both halves of the element rule -- that a type named has to be one the item
    carries, and that the two ranges have to overlap -- are on the low box of
    each element row, which is where the rest of that box's reading already is;
    the row-at-rest half is on the high box.  The property rows are the same
    way: the number read and the suggestions are on the controls that read and
    offer them.

    The one sentence that was *not* already on a control is the stat
    requirements': that an item is worn either by the player level or by these
    attributes.  It is on the low box of each of those four rows now, which is
    why this test reads the tips rather than the face of the panel.
    """
    _, overlay = opened()
    low, high = overlay.damage_spins["fire"]
    armor_low, armor_high = overlay.armor_spins["fire"]

    assert "has to be one the item carries" in low.toolTip()
    assert "overlap" in low.toolTip()
    assert "none of it is left out" in low.toolTip(), "the presence rule is gone"
    assert "asks nothing" in high.toolTip()
    assert armor_low.toolTip().splitlines()[1:] == low.toolTip().splitlines()[1:], (
        "the two sections are one rule drawn twice, differing in the word"
    )
    assert "asks nothing" in armor_high.toolTip()

    req_low = overlay.req_spins[REQ_WORDS[0]][0]
    assert "worn" in req_low.toolTip(), "the either/or rule left the application"

    overlay.findChild(QPushButton, "aadd").click()
    row = overlay.stat_rows[0]
    assert "first one" in row.low.toolTip(), "where the number is read from"
    assert "your collection actually shows" in row.text.toolTip(), (
        "where the words come from"
    )


def test_the_four_stat_requirements_stand_two_to_a_line(qapp):
    """The user's *"stat requirements can have only 2 rows like tl2db"*.

    The reference reads the four caps as a two-column grid of the same four
    rows, and the pairs come out in the game's own order rather than in the
    order the words happen to be long or short in.

    Read off the geometry, because *two rows* is a statement about where the
    boxes are drawn: a section holding four pairs in two lines and a section
    holding them in four would be the same list of widgets.
    """
    _, overlay = opened()
    section = sections(overlay)["Stat Requirements"]

    lines: dict[int, list[str]] = {}
    for word in REQ_WORDS:
        where = overlay.req_spins[word][0].mapTo(section, QPoint(0, 0))
        lines.setdefault(where.y(), []).append(word)

    assert [
        sorted(words, key=list(REQ_WORDS).index) for _, words in sorted(lines.items())
    ] == [["Strength", "Dexterity"], ["Focus", "Vitality"]], (
        "the four requirements are not two lines of two"
    )


def test_each_pair_of_requirements_is_named_by_the_word_beside_it(qapp):
    """What makes the grid above readable: a pair is *Dexterity's* because
    ``Dexterity`` stands at its left, in the ink every other row's name is
    written in -- not because of where it falls in a line of four."""
    _, overlay = opened()
    section = sections(overlay)["Stat Requirements"]

    for word in REQ_WORDS:
        label = next(
            label for label in section.findChildren(QLabel) if label.text() == word
        )
        name = label.mapTo(section, QPoint(0, 0))
        pair = overlay.req_spins[word][0].mapTo(section, QPoint(0, 0))
        assert name.y() == pair.y(), f"{word} is not on the line of its own boxes"
        assert name.x() < pair.x(), f"{word} does not stand at the left of its boxes"


def test_the_class_boxes_line_up_with_the_names_above_them(qapp):
    """The user's *"the class section also doesn't need the 'For' text so all
    the checkboxes can be moved a bit to the left"*, and then their second look
    at the result: *"the class checkboxes are way too much to the left, just
    make sure they align with the other sections like maybe the strength text
    of the previous stat requirements section"*.

    With ``For`` gone the boxes were flush with the section's own edge, which
    is too far left to read as part of the form.  They are set back in to where
    a *name* in the sections above begins -- measured here off the live
    ``Strength`` label's own face rather than off the indent the panel chose,
    so this reads as the alignment it is about and not as a restatement of the
    arithmetic that produced it.
    """
    _, overlay = opened()
    class_section = sections(overlay)["Class"]
    requirements = sections(overlay)["Stat Requirements"]

    strength = next(
        label
        for label in requirements.findChildren(QLabel)
        if label.text() == "Strength"
    )
    # Through globals, because ``mapTo`` is defined for an ancestor and the
    # requirements section is not one of the class section's.
    name = class_section.mapFromGlobal(strength.mapToGlobal(QPoint(0, 0)))
    names_begin = name.x() + strength.width() - QFontMetrics(
        strength.font()
    ).horizontalAdvance("Strength")

    assert "For" not in [label.text() for label in class_section.findChildren(QLabel)]
    first = next(iter(overlay.class_boxes.values())).mapTo(class_section, QPoint(0, 0))
    assert first.x() == names_begin, "the boxes do not start where the names above start"


def test_the_class_note_is_read_against_the_boxes_it_explains(qapp):
    """The note is drawn on the one machine that needs it -- the one without a
    reference database, where the boxes are dark and nothing else says why --
    and it follows them in to the same line, since a hint is read against the
    control it is about."""
    _, overlay = opened(classes=())
    section = sections(overlay)["Class"]

    assert overlay.class_note.isVisible(), "nothing says why the boxes are dark"
    first = next(iter(overlay.class_boxes.values())).mapTo(section, QPoint(0, 0))
    assert overlay.class_note.mapTo(section, QPoint(0, 0)).x() == first.x(), (
        "the note is not read against the boxes it explains"
    )


def test_a_property_row_can_be_added_typed_in_and_taken_away(qapp):
    """The dynamic half of the reference's Stats section: rows arrive from the
    button, and a row that was a mistake leaves by its own cross rather than by
    Reset throwing the rest of the form away with it."""
    _, overlay = opened()
    assert overlay.draft().stats == ()

    overlay.findChild(QPushButton, "aadd").click()
    overlay.stat_rows[0].text.setText("to fire damage")
    overlay.stat_rows[0].low.setValue(20)

    assert overlay.draft().stats == (("to fire damage", 20, NUMBER_MAX),)

    overlay.stat_rows[0].remove.click()

    assert overlay.stat_rows == []
    assert overlay.draft().stats == ()


def test_a_row_nobody_wrote_a_word_into_is_not_part_of_the_search(qapp):
    """An added-and-abandoned row is a row the player did not mean, and the
    same reading the element rows get from the other side: what has not been
    said is not being asked."""
    _, overlay = opened()

    overlay.findChild(QPushButton, "aadd").click()
    overlay.stat_rows[0].low.setValue(50)

    assert overlay.draft().stats == ()


def test_the_rows_offer_the_collection_s_own_stats_as_they_are_typed(qapp):
    """The suggestion list is what the items actually say, with the roll taken
    off the front -- which is the part that differs from item to item, so
    ``+15% to Fire Damage`` and ``+38% to Fire Damage`` are one suggestion.

    The match is by containment rather than from the start, which is the same
    reading the filter gives a row: a player who remembers ``fire damage``
    should not have to remember which words come before it.
    """
    _, overlay = opened(vocabulary=["to fire damage", "to strength"])

    assert overlay.draft() == Advanced(), "the vocabulary narrows nothing"

    overlay.findChild(QPushButton, "aadd").click()
    row = overlay.stat_rows[0]
    completer = row.text.completer()
    completer.setCompletionPrefix("fire")

    offered = completer.completionModel()
    assert [
        offered.index(i, 0).data() for i in range(offered.rowCount())
    ] == ["to fire damage"]


def test_the_set_bonus_box_is_the_last_thing_in_the_section(qapp):
    """It widens where a row may be answered from rather than being a row of
    its own, so it is offered under the rows and says what it does."""
    _, overlay = opened()

    assert overlay.draft().bonuses is False

    overlay.bonuses_box.setChecked(True)

    assert overlay.draft().bonuses is True
    assert "widens" in overlay.bonuses_box.toolTip() or "as well as" in (
        overlay.bonuses_box.toolTip()
    )


class Said:
    """A card standing in for a real one: the vocabulary reads one field off it."""

    def __init__(self, *lines: str) -> None:
        self.properties = lines


def test_the_vocabulary_strips_the_roll_and_deduplicates(qapp):
    """What the suggestions are made of.

    The roll is the part that differs from item to item -- two swords with the
    same affix say ``+15% to Fire Damage`` and ``+38% to Fire Damage`` -- so it
    is the part taken off, and what is left is the one name they share.  Sorted
    and deduplicated, so a collection of two hundred items with the same six
    stats offers six suggestions rather than two hundred.
    """
    said = [
        Said("+15% to Fire Damage", "+38 to Strength"),
        Said("+38% to Fire Damage", "Silence for 1 sec."),
    ]

    assert vocabulary(said) == [
        "silence for 1 sec.",
        "to fire damage",
        "to strength",
    ]


def test_a_card_with_nothing_to_say_offers_nothing(qapp):
    """The empty case, which is every piece of armour in a young collection: a
    suggestion list built from no lines is an empty list, not a broken one."""
    assert vocabulary([]) == []
    assert vocabulary([Said()]) == []


def test_only_the_item_s_own_lines_are_offered(qapp):
    """The vocabulary is what the items *show*, and a set's ladder is not the
    item's own lines -- it is what wearing more of the set would grant.  So the
    box offers it only as far as the card calls it a property, which is the
    same line the Stats filter draws (see
    :meth:`app.models.CollectionFilter._line_says`)."""
    card = Said("+22 to Strength")
    card.set_ladder = (Rung(3, ("+15% to Fire Damage",)),)

    assert vocabulary([card]) == ["to strength"]


def test_search_hands_over_the_three_new_fields_like_the_rest(qapp):
    """The panel is one move whatever the controls are: the fields the last
    commit added travel by the same road as the ones the first commit added."""
    _, overlay = opened()
    heard = watched(overlay)

    overlay.damage_spins["ice"][0].setValue(10)
    overlay.armor_spins["poison"][1].setValue(500)
    overlay.findChild(QPushButton, "aadd").click()
    overlay.stat_rows[0].text.setText("to strength")
    overlay.bonuses_box.setChecked(True)
    overlay.search_button.click()

    assert len(heard) == 1
    assert heard[0].damage == (("ice", 10, NUMBER_MAX),)
    assert heard[0].armor == (("poison", 0, 500),)
    assert heard[0].stats == (("to strength", 0, NUMBER_MAX),)
    assert heard[0].bonuses is True


def test_reset_empties_the_rows_and_the_boxes_with_the_rest(qapp):
    """`Reset` is the resting state, and the resting state of a dynamic list is
    an empty list rather than the rows that happened to be there."""
    _, overlay = opened(EVERYTHING)
    assert overlay.stat_rows, "the fixture has rows to lose"

    overlay.reset_button.click()

    assert overlay.stat_rows == []
    assert overlay.draft().damage == ()
    assert overlay.draft().armor == ()
    assert overlay.draft().bonuses is False


# --------------------------------------------------------------------------
# The type grid, which is the rail drawn in the panel
# --------------------------------------------------------------------------


def test_the_grid_draws_every_group_at_once_under_its_own_heading(qapp):
    """The rail's own shape in the rail's own order, all of it on screen.

    Which is the whole of what the user asked for: the strip over the grid is
    a *bulk toggle* and not a set of tabs, so nothing is hidden behind a press
    and there is no state a player can lose by making one.  The headings are
    read where they are drawn -- the group's word, then its kinds, then the
    next group's -- and the subgroup's is upper case, which is the rail's own
    way of telling the two apart now that they are one size.
    """
    _, overlay = opened(places=WIDE)

    assert drawn(overlay.types) == [
        "Armor",
        "Boots",
        "Chest Armor",
        "Gloves",
        "Helmet",
        "Pants",
        "Shoulder Armor",
        "Weapons",
        "ONE-HANDED",
        "Axe",
        "Sword",
        "TWO-HANDED",
        "Bow",
        "Other",
        UNCLASSIFIED,
    ]
    assert list(tabs(overlay.types)) == [ALL_TYPES, "Armor", "Weapons", "Other"], (
        "a group button per group the collection has, in the rail's order"
    )


def test_a_subgroup_is_set_in_under_the_group_it_belongs_to(qapp):
    """The other half of telling the two headings apart, since they are one
    size: the ink and the step in from the left, both drawn by the sheet."""
    _, overlay = opened(places=WIDE)
    headings = {label.text(): label for label in overlay.types.findChildren(QLabel)}

    assert f"padding: 2px 0 1px {SUBGROUP_INDENT}px;" in headings["ONE-HANDED"].styleSheet()
    assert f"{SUBGROUP_INDENT}px" not in headings["Weapons"].styleSheet(), (
        "the group's own heading is flush with the grid, not set in"
    )
    assert HEAD in headings["Weapons"].styleSheet()
    assert LABEL in headings["ONE-HANDED"].styleSheet(), (
        "the two headings are the rail's two tans, a step apart"
    )


def test_four_kinds_stand_on_every_line_of_the_grid(qapp):
    """The user's own number, read off a shown grid: lines by y, and the first
    line of a group with six kinds holding four of them.

    What it is for is legibility rather than arithmetic -- six armour kinds
    down one column is a column twice as long as it needs to be -- so this is
    about what is *drawn*, and a grid that laid its boxes out any other way
    would fail it.
    """
    _, overlay = opened(places=WIDE)
    lines = rows(overlay.types)

    assert [len(line) for line in lines] == [4, 2, 2, 1, 1]
    assert lines[0] == [
        boxes(overlay.types)[word]
        for word in ("Boots", "Chest Armor", "Gloves", "Helmet")
    ]
    assert lines[1][0].x() == lines[0][0].x(), (
        "the fifth kind went back to the left margin instead of under a column"
    )


def test_the_grid_opens_with_every_kind_ticked(qapp):
    """The panel is an allow-list whose empty state is *anything*, so the
    resting state of this control is everything on -- the reference's own
    reading of the same list, and the reason a Search pressed without touching
    the grid leaves the rail exactly where it was."""
    _, overlay = opened(places=PLACES)

    assert all(box.isChecked() for box in boxes(overlay.types).values())
    assert overlay.types.ticks() == set(), "the whole grid is no kind in particular"
    assert overlay.draft().places == frozenset()


def test_a_group_button_takes_the_whole_group_and_gives_it_back(qapp):
    """The user's *"hitting the respective buttons should select all items
    under that subsection"*, and the second press is how a group is cleared
    out of a grid that opened fully ticked.

    The reference's own rule: a button untickes its group when the group is
    already whole and tickes it otherwise.  What is asserted is the *boxes*,
    because a press that only moved the search and not the grid under it would
    be a button lying about what it did.
    """
    _, overlay = opened(places=WIDE)
    button = tabs(overlay.types)["Armor"]

    pressed(button)

    assert not any(box.isChecked() for box in rows(overlay.types)[0])
    assert boxes(overlay.types)["Sword"].isChecked(), "a weapon went with it"
    assert overlay.draft().places == {
        ("Weapons", "One-Handed", "Axe"),
        ("Weapons", "One-Handed", "Sword"),
        ("Weapons", "Two-Handed", "Bow"),
        ("Other", None, ""),
    }

    pressed(button)

    assert all(box.isChecked() for box in boxes(overlay.types).values())
    assert overlay.draft().places == frozenset(), "back to no narrowing at all"


def test_all_is_the_same_press_over_every_kind_there_is(qapp):
    """One button over the whole grid rather than over a group of it -- and
    the two ends of that toggle mean the same thing to the search, which is
    what makes an empty draft legal: no kind ticked is *any* kind, exactly as
    every kind ticked is."""
    _, overlay = opened(places=WIDE)
    button = tabs(overlay.types)[ALL_TYPES]

    pressed(button)

    assert not any(box.isChecked() for box in boxes(overlay.types).values())
    assert overlay.draft().places == frozenset()

    pressed(button)

    assert all(box.isChecked() for box in boxes(overlay.types).values())
    assert overlay.draft().places == frozenset()


def test_the_kinds_ticked_reach_the_search_as_places(qapp):
    """What makes the grid a second view rather than a second filter: what it
    hands over is the rail's own value, a set of places, so a player who ticks
    Boots here and one who ticks Boots on the rail have asked for the same
    collection.

    Read on a narrowed grid, because that is the one that says anything: a
    grid left alone hands over nothing at all.
    """
    _, overlay = opened(places=PLACES, state=Advanced(places=frozenset({HELMET})))

    assert boxes(overlay.types)["Helmet"].isChecked()
    assert overlay.draft().places == {HELMET}

    only(overlay.types, "Boots", "Helmet")

    assert overlay.draft().places == {BOOTS, HELMET}


def test_a_tick_on_a_kind_the_collection_has_lost_goes_with_it(qapp):
    """The collection is thrown away and built again every poll, and a kind
    that is no longer in it is no longer a thing to narrow by.

    When the lost kind was the *only* one ticked there is nothing left to
    narrow by, and the grid says so the way this control says everything: no
    kind ticked is any kind, which is also where three of the four ticks went
    when the grid opened -- see :meth:`app.advsearch.TypeGrid.set_kinds`.
    """
    _, overlay = opened(state=Advanced(places=frozenset({SWORD})))

    overlay.set_kinds([BOOTS, HELMET])

    assert SWORD not in overlay.types.ticks()
    assert overlay.draft().places == frozenset()
    assert not any(box.isChecked() for box in boxes(overlay.types).values()), (
        "a box for a kind that is gone stayed ticked"
    )


def test_a_grid_that_has_not_moved_is_not_built_again(qapp):
    """A grid rebuilt under the pointer is a grid that loses the click -- the
    same bargain the rail makes, and the reason the shape is compared first."""
    _, overlay = opened()
    drawn_before = overlay.types.findChildren(QCheckBox)

    overlay.types.set_kinds(list(PLACES))

    assert overlay.types.findChildren(QCheckBox) == drawn_before, "the grid was rebuilt"


def test_a_grid_left_whole_stays_whole_when_the_collection_moves(qapp):
    """A poll that gains a kind must not leave it unticked.

    The collection changes under the panel whenever the game writes the stash
    again, and the resting state of this control is *everything* -- so a grid
    nobody has touched has to come back from a poll still saying that, rather
    than coming back narrowed by whatever happened to arrive.  A grid the
    player *has* narrowed keeps only the ticks it still has.
    """
    _, overlay = opened(places=PLACES)

    overlay.set_kinds(PLACES + [("Weapons", "One-Handed", "Axe")])

    assert all(box.isChecked() for box in boxes(overlay.types).values())
    assert overlay.draft().places == frozenset()

    only(overlay.types, "Helmet")
    overlay.set_kinds(PLACES + [("Weapons", "One-Handed", "Axe")])

    assert overlay.draft().places == {HELMET}, (
        "a narrowed grid was widened by the poll rather than kept"
    )


def test_a_group_the_collection_has_lost_goes_off_the_strip(qapp):
    """Rather than staying on it as a button that toggles nothing."""
    _, overlay = opened(places=WIDE)

    overlay.set_kinds([BOOTS, HELMET])

    assert list(tabs(overlay.types)) == [ALL_TYPES, "Armor"]
    assert drawn(overlay.types) == ["Armor", "Boots", "Helmet"]


def test_a_group_s_button_says_how_much_of_it_is_ticked(qapp):
    """The rail's own statement about a heading, on the button that toggles
    it -- with the reference's *third* state, which its own note argues for:
    with every kind ticked at rest, a player who unticks one armour kind would
    otherwise see the Armor button go dark, which reads as *no armour* when it
    means *nearly all armour*.  So the border is the channel that carries the
    middle, and the ink is the one that carries the ends.
    """
    _, overlay = opened(places=WIDE)
    buttons = tabs(overlay.types)

    assert GOLD in buttons["Armor"].styleSheet(), "Armor is wholly ticked at rest"

    boxes(overlay.types)["Helmet"].setChecked(False)
    part = buttons["Armor"].styleSheet()

    assert GOLD in part and LABEL in part, "some of Armor: the middle state"
    assert CHALK not in part

    button = tabs(overlay.types)["Weapons"]
    pressed(button)

    assert not any(box.isChecked() for box in boxes(overlay.types).values() if
                   box.text() in ("Axe", "Sword", "Bow"))
    assert CHALK in buttons["Weapons"].styleSheet(), "none of Weapons"
    assert GOLD not in buttons["Weapons"].styleSheet()
