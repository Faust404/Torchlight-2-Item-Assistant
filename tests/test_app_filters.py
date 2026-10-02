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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QStandardItem  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.card import IconCache  # noqa: E402
from app.catalog import Catalog  # noqa: E402
from app.filters import FilterBar  # noqa: E402
from app.models import (  # noqa: E402
    COLLECTION_COLUMNS,
    FINGERPRINT_ROLE,
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


# --------------------------------------------------------------------------
# A collection, built by hand
# --------------------------------------------------------------------------

BOOTS = ("Armor", None, "Boots")
HELMET = ("Armor", None, "Helmet")
SWORD = ("Weapons", "One-Handed", "Sword")
CANNON = ("Weapons", "Two-Handed", "Cannon")
QUEST = ("Misc", None, "")
BROKEN = (OTHER, None, "")

#: Six items, and between them every case the facets have to tell apart: two
#: kinds in one group, two groups, two rarities, an item with no rarity, and
#: the two different kinds of nothing.
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
    for name, tier, place, level in items:
        cell = QStandardItem(name)
        cell.setData(name, FINGERPRINT_ROLE)
        cell.setData(tier, TIER_ROLE)
        cell.setData(place, PLACE_ROLE)
        cell.setData(level, LEVEL_ROLE)
        model.appendRow(
            [cell, QStandardItem(str(level)), QStandardItem("0"), QStandardItem("")]
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
    """``0`` is a level -- a socketable's -- and every row has one.

    The range used to come out of the boxes as ``(None, None)``, where zero
    stood for the word "Any": one number meaning both "level 0" and "do not
    ask", which cannot be told apart once it reaches here.  Now the default is
    the range that lets everything through, and it is the range it says --
    including the two ends of it, which are levels like any other.
    """
    items = [
        ("Alpha", "Unique", BOOTS, 0),
        ("Beta", "Unique", BOOTS, 40),
        ("Gamma", "Rare", BOOTS, LEVEL_MAX),
    ]
    proxy = _proxy(items)

    assert _shown(proxy) == ["Alpha", "Beta", "Gamma"]

    proxy.set_level_range(0, 0)
    assert _shown(proxy) == ["Alpha"], "zero means level zero and nothing else"

    proxy.set_level_range(1, LEVEL_MAX - 1)
    assert _shown(proxy) == ["Beta"]


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
    fill_collection(model, rows, {}, catalog)
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
