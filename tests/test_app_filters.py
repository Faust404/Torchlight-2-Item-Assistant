"""Tests for narrowing the collection: the proxy, and the controls over it.

Three parts, and they are tested apart because they answer different questions.
:class:`~app.models.CollectionFilter` decides what a set of ticks *means*, and
is tested against a model built by hand so that every case can be stated
exactly -- including the ones the game's own data does not happen to have.
:class:`~app.sidebar.SidePanel` and :class:`~app.filters.FilterBar` decide what
the controls look like and what they say has been ticked -- the kinds down the
left edge, the search, the rarities and the level range across the top -- and
are tested against the shapes they will be handed.

They meet at one value, ``(group, subgroup, kind)``, and the sharpest test here
is about why that value is a triple rather than a kind word: the empty kind is
a real kind in two different groups, and a filter keyed on the word alone would
tick a quest object and an item from a mod at the same time.

One test at the end runs them against the real game, because the proxy being
right and the controls being right does not prove the window wired them to each
other.
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

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFontMetrics, QPalette, QStandardItem  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QGroupBox,
    QStyle,
    QStyleFactory,
    QStyleOptionSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.card import IconCache  # noqa: E402
from app.catalog import Catalog  # noqa: E402
from app.filters import INSET, WASH, FilterBar  # noqa: E402
from app.theme import BODY_PX, CHALK, RAIL_PX, apply_theme  # noqa: E402
from app.models import (  # noqa: E402
    COLLECTION_COLUMNS,
    FINGERPRINT_ROLE,
    GATE_ROLE,
    LEVEL_MAX,
    LEVEL_ROLE,
    PLACE_ROLE,
    TIER_ROLE,
    TIER_CHIPS,
    CollectionFilter,
    fill_collection,
    new_model,
)
from app.sidebar import UNCLASSIFIED, SidePanel  # noqa: E402
from tl2stash.card import TIER_INK  # noqa: E402
from tl2stash.taxonomy import OTHER  # noqa: E402

from test_gamedata import _an_item_of_tier  # noqa: E402
from test_dat import needs_game, real_game  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session; Qt allows no more."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def themed(qapp):
    """The application with the theme applied, and put back afterwards.

    The same dance as :mod:`tests.test_app_theme`, and for the same reason:
    there is one QApplication in the process and every GUI test in the suite
    shares it, so a palette left behind would be a colour scheme decided by
    test ordering.  Only the tests about what the controls are *drawn* in need
    this; the rest of the bar is the same widget either way.
    """
    name = qapp.style().objectName()
    palette = QPalette(qapp.palette())
    sheet = qapp.styleSheet()
    apply_theme(qapp)
    try:
        yield qapp
    finally:
        # By name rather than by object: setting a style hands it to Qt, which
        # deletes the one it replaced.
        restored = QStyleFactory.create(name) if name else None
        if restored is not None:
            qapp.setStyle(restored)
        qapp.setPalette(palette)
        qapp.setStyleSheet(sheet)


# --------------------------------------------------------------------------
# A collection, built by hand
# --------------------------------------------------------------------------

BOOTS = ("Armor", None, "Boots")
HELMET = ("Armor", None, "Helmet")
SWORD = ("Weapons", "One-Handed", "Sword")
CANNON = ("Weapons", "Two-Handed", "Cannon")
QUEST = ("Misc", None, "")
BROKEN = (OTHER, None, "")

#: Seven items, and between them every case the facets have to tell apart: two
#: kinds in one group, two groups, two rarities, an item with no rarity, and
#: the two different kinds of nothing.
#:
#: The number is the *gate* rather than the item's own level, because that is
#: what the level range is over and it is the only number these tests need --
#: a row built by hand has no item behind it.  The two roles are told apart in
#: :func:`test_the_range_follows_the_gate_rather_than_the_item_level`, which is
#: the one place the difference is the subject.
ITEMS = [
    ("Alpha", "Unique", BOOTS, 40),
    ("Beta", "Unique", BOOTS, 12),
    ("Gamma", "Rare", BOOTS, 40),
    ("Delta", "Unique", HELMET, 40),
    ("Epsilon", "Unique", SWORD, 5),
    ("Zeta", "", QUEST, 40),
    ("Eta", "", BROKEN, 40),
]


def _built(items=ITEMS):
    """A collection model carrying the roles, with no game and no catalog."""
    model = new_model(COLLECTION_COLUMNS)
    for name, tier, place, gate in items:
        cell = QStandardItem(name)
        cell.setData(name, FINGERPRINT_ROLE)
        cell.setData(tier, TIER_ROLE)
        cell.setData(place, PLACE_ROLE)
        cell.setData(gate, LEVEL_ROLE)
        cell.setData(gate, GATE_ROLE)
        model.appendRow(
            [cell, QStandardItem(str(gate)), QStandardItem("0"), QStandardItem("")]
        )
    return model


def _proxy(items=ITEMS) -> CollectionFilter:
    """A proxy over the hand-built collection, wired the way the window wires it.

    The key column and the case sensitivity are not decoration: the window sets
    both, and a proxy matching differently here would be testing a filter the
    player never gets.
    """
    proxy = CollectionFilter()
    proxy.setSourceModel(_built(items))
    proxy.setFilterKeyColumn(0)
    proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    return proxy


def _shown(proxy) -> list[str]:
    """The names the proxy is letting through, in its own order."""
    return [proxy.index(row, 0).data() for row in range(proxy.rowCount())]


# --------------------------------------------------------------------------
# The kinds facet
# --------------------------------------------------------------------------


def test_with_nothing_ticked_the_whole_collection_is_shown(qapp):
    """An untouched rail is not a filter at all -- which is what makes it safe
    to ignore, and what makes "Clear filters" a state rather than a reset."""
    proxy = _proxy()

    assert _shown(proxy) == [name for name, *_ in ITEMS]


def test_ticking_one_kind_leaves_only_that_kind(qapp):
    proxy = _proxy()

    proxy.set_places({BOOTS})

    assert _shown(proxy) == ["Alpha", "Beta", "Gamma"]


def test_ticking_two_kinds_leaves_both(qapp):
    proxy = _proxy()

    proxy.set_places({BOOTS, SWORD})

    assert _shown(proxy) == ["Alpha", "Beta", "Gamma", "Epsilon"]


def test_the_two_kinds_of_nothing_are_not_the_same_tick(qapp):
    """Why the rail speaks in places and not in kind words.

    A quest object is a ``QUESTITEM`` -- a tier and no kind at all -- and an
    item the game has no data file for is no kind at all either.  Both carry
    the empty kind and they belong to different groups, so a filter keyed on
    the word would show a modded item when the player asked for quest objects.
    """
    proxy = _proxy()
    assert _shown(proxy).count("Zeta") == 1 and "Eta" in _shown(proxy)

    proxy.set_places({QUEST})
    assert _shown(proxy) == ["Zeta"]

    proxy.set_places({BROKEN})
    assert _shown(proxy) == ["Eta"]


# --------------------------------------------------------------------------
# The facets AND
# --------------------------------------------------------------------------


def test_a_rarity_narrows_within_the_kinds_rather_than_replacing_them(qapp):
    proxy = _proxy()
    proxy.set_places({BOOTS})

    proxy.set_tiers({"Rare"})

    assert _shown(proxy) == ["Gamma"]


def test_an_item_with_no_rarity_is_shown_until_a_rarity_is_ticked(qapp):
    """The unclassified tail is not one of the chips, so no chip can reach it.

    It is visible while nothing is ticked, which is the honest answer: the
    player has not said they want only rarities.
    """
    proxy = _proxy()
    assert "Zeta" in _shown(proxy)

    proxy.set_tiers({"Unique"})
    assert "Zeta" not in _shown(proxy)
    assert _shown(proxy) == ["Alpha", "Beta", "Delta", "Epsilon"]


def test_the_level_bounds_are_inclusive(qapp):
    proxy = _proxy()

    proxy.set_level_range(40, 40)

    assert _shown(proxy) == ["Alpha", "Gamma", "Delta", "Zeta", "Eta"]


def test_the_default_range_is_the_whole_of_it(qapp):
    """The range used to come out of the boxes as ``(None, None)``, where zero
    stood for the word "Any": one number meaning both "level 0" and "do not
    ask", which cannot be told apart once it reaches here.  Now the default is
    the range that lets everything through, and it is the range it says --
    including the two ends of it, which are levels like any other.
    """
    items = [
        ("Alpha", "Unique", BOOTS, 1),
        ("Beta", "Unique", BOOTS, 40),
        ("Gamma", "Rare", BOOTS, LEVEL_MAX),
    ]
    proxy = _proxy(items)

    assert _shown(proxy) == ["Alpha", "Beta", "Gamma"]

    proxy.set_level_range(1, 1)
    assert _shown(proxy) == ["Alpha"], "zero is not in the range, one is"

    proxy.set_level_range(1, LEVEL_MAX - 1)
    assert _shown(proxy) == ["Alpha", "Beta"]


def test_an_item_gated_on_nothing_is_shown_whatever_the_range(qapp):
    """Zero is an answer, not a missing value.

    An item the game gates on nothing -- a potion, a quest object, a map --
    is one a character of any level can use, so no range excludes it.  That is
    why the predicate is a check on a truthy gate rather than ``or 0``: reading
    zero as a low level would hide exactly the items that have no high one.
    """
    items = [
        ("Potion", "", QUEST, 0),
        ("Beta", "Unique", BOOTS, 40),
    ]
    proxy = _proxy(items)

    for low, high in ((0, 0), (40, 40), (LEVEL_MAX, LEVEL_MAX), (1, 2)):
        proxy.set_level_range(low, high)
        shown = _shown(proxy)
        assert "Potion" in shown, f"{low}..{high} hid an item with no gate"
        assert ("Beta" in shown) == (low <= 40 <= high)


def test_the_range_follows_the_gate_rather_than_the_item_level(qapp):
    """A row carries both numbers and they are not the same one.

    The list shows the item's level and has always shown it; the range is over
    what the item *asks for*.  A level 45 unique that requires 51 is one a
    level 45 character cannot use, and a range that let it through would be
    answering a question nobody asked.
    """
    model = new_model(COLLECTION_COLUMNS)
    cell = QStandardItem("Bashdrill")
    cell.setData("Bashdrill", FINGERPRINT_ROLE)
    cell.setData("Unique", TIER_ROLE)
    cell.setData(BOOTS, PLACE_ROLE)
    cell.setData(45, LEVEL_ROLE)
    cell.setData(51, GATE_ROLE)
    model.appendRow([cell])

    proxy = CollectionFilter()
    proxy.setSourceModel(model)
    proxy.setFilterKeyColumn(0)

    proxy.set_level_range(45, 45)
    assert _shown(proxy) == [], "the item's own level is not what is asked"

    proxy.set_level_range(51, 51)
    assert _shown(proxy) == ["Bashdrill"]


def test_every_facet_at_once(qapp):
    proxy = _proxy()

    proxy.set_places({BOOTS, HELMET})
    proxy.set_tiers({"Unique"})
    proxy.set_level_range(20, 50)

    assert _shown(proxy) == ["Alpha", "Delta"]


# --------------------------------------------------------------------------
# The search box, which is not a facet
# --------------------------------------------------------------------------


def test_the_search_box_narrows_and_still_combines_with_the_ticks(qapp):
    """The search is what the proxy did before there were facets, and it has to
    keep behaving exactly as it did -- the rail is laid over it, not under."""
    proxy = _proxy()

    proxy.setFilterFixedString("a")
    assert _shown(proxy) == ["Alpha", "Beta", "Gamma", "Delta", "Zeta", "Eta"]

    proxy.set_places({BOOTS})
    assert _shown(proxy) == ["Alpha", "Beta", "Gamma"]

    proxy.setFilterFixedString("beta")
    assert _shown(proxy) == ["Beta"]


# --------------------------------------------------------------------------
# The counts, which are what a tick would leave
# --------------------------------------------------------------------------


def test_a_count_ignores_its_own_facet(qapp):
    """The whole reason the panel is worth reading.

    With ``Unique`` ticked, the number beside ``Rare`` has to stay the number
    of rares there *are* -- otherwise every chip but the ticked one reads zero
    and the player cannot see what they would get by ticking something else.
    """
    proxy = _proxy()
    proxy.set_tiers({"Unique"})

    assert proxy.counts(TIER_ROLE)["Rare"] == 1
    assert proxy.counts(TIER_ROLE)["Unique"] == 4


def test_a_count_respects_the_other_facets(qapp):
    """A count answers about the list you are looking at, not about everything."""
    proxy = _proxy()
    proxy.set_places({BOOTS})

    tiers = proxy.counts(TIER_ROLE)

    assert tiers["Unique"] == 2
    assert tiers["Rare"] == 1
    # Delta is a unique helmet, and the player has ticked boots -- so it is not
    # one of the two uniques counted here.
    assert sum(tiers.values()) == 3


def test_a_kind_count_ignores_the_kind_ticks_but_not_the_others(qapp):
    proxy = _proxy()
    proxy.set_places({BOOTS})
    proxy.set_tiers({"Unique"})

    places = proxy.counts(PLACE_ROLE)

    assert places[BOOTS] == 2
    # Not ticked, and still counted -- so the player can see the helmet is
    # there waiting.
    assert places[HELMET] == 1
    assert places[SWORD] == 1
    # The quest object has no rarity, so the unique chip has taken it out of
    # the kind counts entirely -- and a kind nothing would be left under is
    # absent rather than zero, which is what the rail's `get(place, 0)` reads.
    assert QUEST not in places


def test_the_search_box_narrows_the_counts(qapp):
    """The one thing a count does not ignore, because it is not a facet."""
    proxy = _proxy()
    proxy.setFilterFixedString("Beta")

    assert proxy.counts(PLACE_ROLE) == {BOOTS: 1}
    assert proxy.counts(TIER_ROLE) == {"Unique": 1}


# --------------------------------------------------------------------------
# The rail, which is the kinds and nothing else
# --------------------------------------------------------------------------


def _panel() -> SidePanel:
    """A rail on its own; the test that asks for it has already made the app."""
    return SidePanel()


def _rows(panel, branch=None, depth=0) -> list[str]:
    """Every row's label, in the order the rail draws them, indented to match.

    Recursive because a weapon's kind sits two rows down -- under ``Weapons``
    and then under ``One-Handed`` -- and a walk one level deep would report a
    rail that had lost its swords as correct.
    """
    branch = branch if branch is not None else panel.tree.invisibleRootItem()
    out = []
    for i in range(branch.childCount()):
        child = branch.child(i)
        out.append(f"{'  ' * depth}{child.text(0)}")
        out.extend(_rows(panel, child, depth + 1))
    return out


def test_the_rail_draws_only_the_groups_the_collection_has(qapp):
    panel = _panel()

    panel.set_shape([BOOTS, HELMET, SWORD, QUEST])

    assert _rows(panel) == [
        "Armor",
        "  Boots",
        "  Helmet",
        "Weapons",
        "  One-Handed",
        "    Sword",
        "Misc",
        f"  {UNCLASSIFIED}",
    ]
    # Nothing in the collection is a two-handed weapon, so the rail says
    # nothing about them.
    assert "Cannon" not in " ".join(_rows(panel))


def test_the_rail_keeps_its_shape_when_the_collection_has_not_changed(qapp):
    """A poll rebuilds the tables twice a second, and a rebuild that took the
    ticks with it would undo the player's filter every other second."""
    panel = _panel()
    panel.set_shape([BOOTS, SWORD])
    panel.tree.topLevelItem(0).child(0).setCheckState(0, Qt.CheckState.Checked)

    panel.set_shape([BOOTS, SWORD])

    assert panel.places() == {BOOTS}
    assert panel.tree.topLevelItem(0).child(0).checkState(0) == Qt.CheckState.Checked


def test_ticking_a_group_ticks_what_is_under_it(qapp):
    """A category *is* all its types ticked -- the reference's own rule."""
    panel = _panel()
    panel.set_shape([BOOTS, HELMET, SWORD, CANNON])

    panel.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)

    assert panel.places() == {BOOTS, HELMET}


def test_the_number_beside_a_kind_is_what_ticking_it_would_show(qapp):
    """The rail's own reason for having a second column."""
    panel = _panel()
    panel.set_shape([BOOTS, SWORD])

    panel.set_counts({BOOTS: 3})

    armor, weapons = panel.tree.topLevelItem(0), panel.tree.topLevelItem(1)
    assert armor.child(0).text(0) == "Boots"
    assert armor.child(0).text(1) == "3"
    # A group is what is under it ...
    assert armor.text(1) == "3"
    # ... and a kind with nothing behind it says so rather than going blank.
    sword = weapons.child(0).child(0)
    assert sword.text(0) == "Sword"
    assert sword.text(1) == "0"


def test_clearing_the_rail_puts_back_what_was_ticked(qapp):
    panel = _panel()
    panel.set_shape([BOOTS, SWORD])
    panel.tree.topLevelItem(0).child(0).setCheckState(0, Qt.CheckState.Checked)
    assert panel.places()

    panel.reset()

    assert panel.places() == set()


def test_the_rail_says_so_when_a_kind_moves(qapp):
    panel = _panel()
    panel.set_shape([BOOTS])
    heard = []
    panel.changed.connect(lambda: heard.append(1))

    panel.tree.topLevelItem(0).child(0).setCheckState(0, Qt.CheckState.Checked)

    assert len(heard) == 1


def test_rebuilding_the_rail_is_not_a_change_the_user_made(qapp):
    """The panel writes to its own widgets, and those writes must not come back
    round as ticks -- which is what the guard in it is for."""
    panel = _panel()
    heard = []
    panel.changed.connect(lambda: heard.append(1))

    panel.set_shape([BOOTS, SWORD])
    panel.set_counts({BOOTS: 3, SWORD: 1})

    assert heard == []


def test_a_tick_on_a_kind_the_collection_has_lost_goes_with_it(qapp):
    """Otherwise the filter hides everything and shows nothing ticked to say so."""
    panel = _panel()
    panel.set_shape([BOOTS, SWORD])
    panel.tree.topLevelItem(0).child(0).setCheckState(0, Qt.CheckState.Checked)

    panel.set_shape([SWORD])

    assert panel.places() == set()


def test_the_rail_gives_its_width_to_the_kinds_rather_than_to_the_counts(qapp):
    """The count is the rail's last column, and Qt stretches the last one.

    Which is how the rail came to draw a column of numbers with no words
    beside them: the counts were given the width and the kinds were left with
    what was over.  The kinds stretch and the counts take what their digits
    need, so what the rail spends its width on is the thing being chosen.
    """
    panel = _panel()
    panel.set_shape([BOOTS, HELMET, SWORD, QUEST])
    panel.set_counts({BOOTS: 2, HELMET: 1, SWORD: 7, QUEST: 3})
    panel.resize(180, 400)
    panel.show()
    qapp.processEvents()

    tree = panel.tree
    assert tree.columnWidth(0) > tree.columnWidth(1)
    assert tree.columnWidth(0) > 60


def test_a_kind_whose_name_does_not_fit_says_all_of_it_on_hover(qapp):
    """A narrow rail elides, and what it cuts is the end of the name."""
    panel = _panel()
    panel.set_shape([SWORD, QUEST])

    assert panel._leaves[SWORD].toolTip(0) == "Weapons / One-Handed / Sword"
    assert panel._leaves[QUEST].toolTip(0) == "Misc / Unclassified"


# --------------------------------------------------------------------------
# The bar, which is everything else
# --------------------------------------------------------------------------


def _bar() -> FilterBar:
    """A bar on its own; the test that asks for it has already made the app."""
    return FilterBar()


def test_the_bar_reads_back_what_is_in_it(qapp):
    """The window asks the bar for its facets rather than reaching into its
    widgets, so what the bar says is what the filter gets."""
    bar = _bar()

    assert bar.search_text() == ""
    assert bar.tiers() == set()
    assert bar.level_range() == (0, LEVEL_MAX), "the default is the whole range"

    bar.search.setText("drill")
    bar.chips["Unique"].setChecked(True)
    bar.low.setValue(45)

    assert bar.search_text() == "drill"
    assert bar.tiers() == {"Unique"}
    assert bar.level_range() == (45, LEVEL_MAX)


def test_the_bar_carries_a_chip_for_every_rarity_the_game_has(qapp):
    """The same five words the cards are inked with, and in the game's own
    order, because a chip and a card's kind line name the same thing."""
    bar = _bar()

    assert list(bar.chips) == list(TIER_CHIPS)
    assert "Legendary" in bar.chips


def test_the_level_boxes_start_on_the_whole_range(qapp):
    """Both ends of it, written as the two levels they are.

    The boxes used to read ``Any`` at zero, so the bar opened on a word about
    not asking.  A player setting 0 now means the level-0 items -- the
    socketables the collection holds -- and the default is the range that
    happens to let everything through rather than a special case.
    """
    bar = _bar()

    assert (bar.low.value(), bar.high.value()) == (0, LEVEL_MAX)
    assert bar.low.minimum() == 0
    assert bar.low.maximum() == bar.high.maximum() == LEVEL_MAX
    assert bar.low.specialValueText() == "", "a box shows a number, not a word"

    bar.high.setValue(45)
    assert bar.level_range() == (0, 45)


def test_the_counts_go_on_the_chips(qapp):
    """What :meth:`CollectionFilter.counts` is for: the number beside a rarity
    is what ticking it would show, so it stays worth reading while another
    rarity is ticked."""
    bar = _bar()

    bar.set_counts({"Unique": 4, "Rare": 1})

    assert bar.chips["Unique"].text() == "Unique  4"
    assert bar.chips["Rare"].text() == "Rare  1"
    # A rarity with nothing behind it says zero rather than going blank.
    assert bar.chips["Legendary"].text() == "Legendary  0"


def test_clearing_the_bar_puts_every_control_back(qapp):
    bar = _bar()
    bar.search.setText("drill")
    bar.chips["Unique"].setChecked(True)
    bar.low.setValue(20)
    bar.high.setValue(30)
    assert bar.search_text() and bar.tiers() and bar.level_range() != (0, LEVEL_MAX)

    bar.reset()

    assert bar.search_text() == ""
    assert bar.tiers() == set()
    assert bar.level_range() == (0, LEVEL_MAX)


def test_the_bar_says_so_when_anything_in_it_moves(qapp):
    """One signal for all four controls, because the window does one thing with
    it: re-apply every facet and re-count."""
    bar = _bar()
    heard = []
    bar.changed.connect(lambda: heard.append(1))

    bar.search.setText("drill")
    bar.chips["Rare"].setChecked(True)
    bar.low.setValue(10)

    assert len(heard) == 3


def test_putting_the_counts_on_the_chips_is_not_a_change_made(qapp):
    """Writing the numbers is the window's doing, not the player's, and a chip
    whose text was rewritten must not come back round as a tick."""
    bar = _bar()
    heard = []
    bar.changed.connect(lambda: heard.append(1))

    bar.set_counts({"Unique": 4})

    assert heard == []


def test_clearing_the_bar_is_one_change_rather_than_four(qapp):
    """A reset is the player pressing one button, so the window hears about it
    once -- four signals would be four redraws of the same list."""
    bar = _bar()
    bar.search.setText("drill")
    bar.chips["Unique"].setChecked(True)
    bar.low.setValue(20)
    heard = []
    bar.changed.connect(lambda: heard.append(1))

    bar.reset()

    assert len(heard) == 1


# --------------------------------------------------------------------------
# What the bar is drawn in, which is the one thing it does not say itself
# --------------------------------------------------------------------------


def _contents(box) -> list:
    """What a box is holding, in the order the box draws it."""
    layout = box.layout()
    return [layout.itemAt(i).widget() for i in range(layout.count())]


def test_the_two_boxes_hold_the_controls_they_are_named_for(qapp):
    """A box is a frame around the controls rather than a copy of them.

    The very widgets go in -- the chips and the two number boxes are the ones
    the window reads back -- so what is on screen and what the bar reports are
    the same objects, and there is no second set of them to keep in step.
    """
    bar = _bar()

    assert [bar.rarity_box.title(), bar.level_box.title()] == [
        "Rarity",
        "Player level",
    ]
    assert bar.rarity_box.objectName() == "filterbox"
    assert bar.level_box.objectName() == "filterbox"

    assert _contents(bar.rarity_box) == list(bar.chips.values())
    low, to, high = _contents(bar.level_box)
    assert (low, high) == (bar.low, bar.high)
    assert to.text() == "to"


def test_the_inset_is_what_a_group_box_puts_in_front_of_its_contents(themed):
    """Where the row stands, measured against the thing it lines up with.

    The bar is the collection box's *sibling* rather than its content -- the
    pane stacks the two -- so the only way the search box can stand over the
    cards' column is for the row's own inset to be the little a group box
    leaves inside itself.  Which is :data:`app.filters.INSET`, and this is
    that claim stated against a real box rather than against the number twice.

    A *child* box, as the three panes are: a group box that is a window of its
    own is laid out with a window's own margins, and would measure two pixels
    wider than this row has any reason to be.
    """
    host = QWidget()
    host.resize(400, 300)
    box = QGroupBox("In the tool", host)
    inside = QWidget(box)
    QVBoxLayout(box).addWidget(inside)
    QVBoxLayout(host).addWidget(box)
    host.show()
    themed.processEvents()

    assert inside.mapTo(box, QPoint(0, 0)).x() == INSET, (
        "a group box does not put the row's inset in front of its contents"
    )


def test_the_search_box_takes_every_width_the_row_has_over(themed):
    """The user's other half of the request: the box is widened, and this is
    where a wider pane has to put the width.

    Of the four controls in the row only one is worth widening -- the two
    facet boxes are as wide as the words in them, which is their own test, and
    the reset at the end is a button -- so the width a wide window leaves over
    belongs in the search box rather than as a gap between the controls, which
    is what the user was looking at when they asked for this.  Themed, so that
    the widths the row starts with are the ones the application ships rather
    than whatever font the machine running the tests happens to have.
    """
    bar = _bar()
    bar.show()
    bar.resize(1500, 44)
    themed.processEvents()

    narrow = bar.search.width()
    others = [bar.rarity_box.width(), bar.level_box.width(), bar.clear_button.width()]
    assert narrow > bar.search.minimumWidth(), (
        "the box opened on its floor, so nothing about its width can be read here"
    )

    bar.resize(1900, 44)
    themed.processEvents()

    assert bar.search.width() == narrow + 400, (
        "the width the row gained did not all reach the search box"
    )
    assert [
        bar.rarity_box.width(),
        bar.level_box.width(),
        bar.clear_button.width(),
    ] == others, "a control that is not the search box grew with the row"


def test_a_box_is_as_wide_as_what_is_in_it_and_no_wider(themed):
    """The title costs the row nothing, which is what it is there to prove.

    A ``QGroupBox`` asks for its contents plus its own margins and its frame
    -- the two pixels here are the sheet's one-pixel border on each side -- and
    the title is drawn in the gap the stylesheet's ``margin-top`` opens, so it
    is no part of the width at all.  That matters because this row is what
    sets the window's minimum width: a box that grew to fit the words
    ``Player level`` would be width the collection paid for.

    Themed, because the frame being measured is the sheet's -- without it the
    style's own frame is a different width and the sum proves nothing.
    """
    bar = _bar()

    for box in (bar.rarity_box, bar.level_box):
        layout = box.layout()
        margins = layout.contentsMargins()
        inside = sum(w.sizeHint().width() for w in _contents(box))
        inside += layout.spacing() * (layout.count() - 1)
        assert box.sizeHint().width() == inside + margins.left() + margins.right() + 2


def test_a_chip_s_word_is_the_windows_own_whichever_way_it_is_ticked(qapp):
    """The word is the window's control ink; the rarity is what the pill is
    *filled* with.

    Which is the other way round from how this started, and the user's own
    complaint is why: the word used to be inked in the tier and dimmed to a
    grey while unticked, and those greys sat so close to the bar they were
    drawn on that the row read as five words blending into it.  So both the
    outline and the word are that ink in both states, and what a tick changes
    is
    the fill -- a wash of the tier's colour for a rarity in play, the bare
    ground for one that is not.
    """
    bar = _bar()

    for chip in bar.chips.values():
        sheet = chip.styleSheet()
        assert f"color: {CHALK}" in sheet, "the word is the ink in both states"
        assert f"border: 1px solid {CHALK}" in sheet
        unticked = sheet.split("QCheckBox:!checked")[1]
        assert "border" not in unticked, (
            "the outline changes with the tick, so an unticked chip loses it"
        )
        assert "color" not in unticked, (
            "the word changes with the tick, so it blends in again when unticked"
        )
        assert "background: transparent" in unticked, (
            "the fill changes with the tick, and that is all that changes"
        )


def test_ticking_a_chip_washes_it_in_the_rarity_s_own_colour(themed):
    """And the fill is really drawn, at the strength the sheet asked for.

    Read off the pill's pixels rather than off the sheet, because a sheet is
    where a mistake about ``rgba()`` would live in silence: an alpha the parser
    does not understand is a declaration that is dropped, and a chip that was
    meant to be washed comes out as the ground with an outline.  So the
    ground and the wash are both measured, and the wash is checked against the
    arithmetic the sheet states -- the tier's colour at :data:`app.filters.
    WASH` over what was underneath.

    The ink is counted in the *middle* of the pill, clear of the outline at
    both ends, because the outline carries it in both states: what is being
    counted there is the word, which is the thing the user could not read.
    """
    bar = _bar()
    bar.resize(bar.sizeHint())
    bar.show()
    themed.processEvents()

    chip = bar.chips["Unique"]
    # In the bar's own frame, which is what the grab below is in: a chip's
    # geometry is measured against the box it sits in, and the box is not the
    # widget being read.
    rect = QRect(chip.mapTo(bar, chip.rect().topLeft()), chip.size())

    def probe() -> tuple[QColor, int]:
        """The fill at the pill's left end, and the ink in the middle."""
        image = bar.grab().toImage()
        middle = rect.center()
        word = sum(
            1
            for y in range(middle.y() - 4, middle.y() + 5)
            for x in range(rect.left() + 3, rect.right() - 2)
            if image.pixelColor(x, y).name() == CHALK
        )
        return image.pixelColor(rect.left() + 4, middle.y()), word

    ground, word_off = probe()
    chip.setChecked(True)
    themed.processEvents()
    washed, word_on = probe()

    assert word_off > 0, "an unticked chip's word is not in the ink"
    assert word_on > 0, "a ticked chip's word is not in the ink"

    ink = QColor(TIER_INK["unique"])
    share = WASH / 255
    wanted = [
        share * ink.red() + (1 - share) * ground.red(),
        share * ink.green() + (1 - share) * ground.green(),
        share * ink.blue() + (1 - share) * ground.blue(),
    ]
    assert [washed.red(), washed.green(), washed.blue()] == pytest.approx(
        wanted, abs=2
    ), "the tick's fill is not the tier's colour over the ground"


def test_the_rail_s_words_are_a_step_up_from_the_window_s_body(themed):
    """The user's third change, and the one place in the window that sets a
    size of its own: the rail is a column of kind names with height to spare,
    and the words there are what the player aims at.

    Measured on a real rail rather than read off the sheet, because the rule
    is written about an *object name* -- a tree that went unnamed would keep
    the window's 13px and nothing else would say so.  The rows come with the
    words, which is the other half of that spare height: a 15px word in a 13px
    row is a clipped word.
    """
    panel = _panel()
    panel.set_shape([BOOTS, SWORD])
    panel.resize(240, 300)
    panel.show()
    themed.processEvents()

    tree = panel.tree
    body = QFontMetrics(QApplication.font())
    row = tree.visualItemRect(tree.topLevelItem(0)).height()

    assert QApplication.font().pixelSize() == BODY_PX, "the body is not the body"
    assert tree.font().pixelSize() == RAIL_PX > BODY_PX
    assert tree.fontMetrics().horizontalAdvance("Boots") > body.horizontalAdvance(
        "Boots"
    ), "the rail is drawn no wider than the window's own text"
    assert row > body.height(), "the rows did not grow with the words"


def test_the_rails_boxes_are_outlined_and_fill_when_ticked(themed):
    """The first clause of the request, drawn rather than read off the sheet.

    A ticked box is a *filled* one: Qt's stylesheet language draws a check
    box's frame and its fill but not a check mark, which is an image file this
    application does not ship.  So what is counted here is ink pixels in the
    box itself -- a box that is off has to be visible, and one that is on has
    to be more of it -- which is also the check that the indicator rule
    reaches a ``QTreeWidget`` at all, a tree view being what it is.
    """
    panel = _panel()
    panel.set_shape([BOOTS, SWORD])
    panel.resize(180, 200)
    panel.show()
    themed.processEvents()

    boots = panel.tree.topLevelItem(0).child(0)

    def ink() -> int:
        """The ink in the front of that row, where the box is and the words
        are not."""
        rect = panel.tree.visualItemRect(boots)
        image = panel.tree.grab().toImage()
        return sum(
            1
            for y in range(rect.top(), rect.bottom() + 1)
            for x in range(rect.left(), rect.left() + 24)
            if image.pixelColor(x, y).name() == CHALK
        )

    off = ink()
    boots.setCheckState(0, Qt.CheckState.Checked)
    themed.processEvents()
    on = ink()

    assert off > 0, "an unticked box is invisible against the ground"
    assert on > off, "ticking it drew nothing"


def _stepper_boxes(spin):
    """Where the style puts the two buttons of a spin box, in widget pixels."""
    option = QStyleOptionSpinBox()
    spin.initStyleOption(option)
    return [
        spin.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox, option, which, spin
        )
        for which in (QStyle.SubControl.SC_SpinBoxUp, QStyle.SubControl.SC_SpinBoxDown)
    ]


def test_the_number_boxes_draw_their_own_steppers(themed):
    """Qt will outline a spin box or keep its stepper arrows, not both.

    The moment a rule touches the box's frame the stylesheet style takes the
    whole control over and draws the two buttons as flat blocks -- with no
    arrows at all, because an arrow in that language is an *image file* and
    this application ships none.  So the frame is the sheet's and the
    triangles are painted by :class:`app.filters.SpinBox`, and this is the
    check that they arrive: twelve ink pixels in each button, six across at
    the base and three rows deep, narrowing towards the end the arrow points
    at -- which is the whole of what says which of the two is which.
    """
    bar = _bar()  # held, or the box it hands over goes with it
    spin = bar.low
    spin.resize(spin.sizeHint())
    spin.show()
    themed.processEvents()

    image = spin.grab().toImage()
    rows = []
    for button in _stepper_boxes(spin):
        rows.append(
            [
                sum(
                    1
                    for x in range(button.left(), button.right() + 1)
                    if image.pixelColor(x, y).name() == CHALK
                )
                for y in range(button.top(), button.bottom() + 1)
            ]
        )

    # Only the rows with ink in them: how tall the button is belongs to the
    # style, and what the arrow does inside it does not.
    drawn = [[width for width in button if width] for button in rows]
    assert drawn == [[2, 4, 6], [6, 4, 2]], (
        "the up arrow is narrow at the top, the down one at the bottom"
    )


# --------------------------------------------------------------------------
# The two together, against the real game
# --------------------------------------------------------------------------


@needs_game
def test_the_real_collection_narrows_by_kind_and_by_rarity(real_game, qapp):
    """The wiring, on the game's own items.

    The model is filled the way the window fills it -- through the catalogue,
    from rows alike in the fields it reads -- so this is the whole path from a
    registry row to a filtered, coloured, illustrated row.
    """
    normal_guid, normal_kind = _an_item_of_tier(real_game, "NORMAL")
    unique_guid, unique_kind = _an_item_of_tier(real_game, "UNIQUE")

    def row(name, guid, prefix=""):
        return {
            "fingerprint": name,
            "name": name,
            "level": 20,
            "num_sockets": 0,
            "guid": f"{guid:016X}",
            "prefix": prefix,
            "suffix": None,
            "num_enchants": 0,
        }

    # The one shape the references could not describe: a white item with an
    # affix on it, which the game shows green.
    rows = [
        row("Green", normal_guid, "Demolishing [ITEM]"),
        row("Orange", unique_guid),
    ]
    catalog = Catalog(real_game, IconCache(real_game.install))
    model = new_model(COLLECTION_COLUMNS)
    fill_collection(model, rows, catalog)
    proxy = CollectionFilter()
    proxy.setSourceModel(model)

    green = model.item(0, 0)
    assert green.data(TIER_ROLE) == "Magic"
    assert green.foreground().color().name() == TIER_INK["magic"]
    assert green.icon() is not None
    assert model.item(1, 0).data(TIER_ROLE) == "Unique"

    # And the rail the window builds from those rows, ticked at one kind.
    panel = _panel()
    panel.set_shape([model.item(i, 0).data(PLACE_ROLE) for i in range(model.rowCount())])
    assert (normal_kind or UNCLASSIFIED) in " ".join(_rows(panel))
    assert (unique_kind or UNCLASSIFIED) in " ".join(_rows(panel))

    proxy.set_places({green.data(PLACE_ROLE)})
    proxy.set_tiers({"Magic"})
    assert _shown(proxy) == ["Green"]
