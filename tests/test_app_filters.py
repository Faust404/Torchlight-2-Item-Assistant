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
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QFontMetrics,
    QPalette,
    QStandardItem,
)
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QGroupBox,
    QStyle,
    QStyleFactory,
    QStyleOptionSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.card import BODY, DIM, GOLD, HEAD, LABEL, MUTED, IconCache  # noqa: E402
from app.catalog import Catalog  # noqa: E402
from app.filters import INSET, WASH, FilterBar  # noqa: E402
from app.sidebar import COUNT_PX  # noqa: E402
from app.theme import BODY_PX, CHALK, FIELD, RAIL_PX, SHELL, apply_theme  # noqa: E402
from app.models import (  # noqa: E402
    CLASS_ROLE,
    COLLECTION_COLUMNS,
    ELEMENTS,
    ELEMENT_REST,
    FINGERPRINT_ROLE,
    GATE_ROLE,
    LEVEL_MAX,
    LEVEL_ROLE,
    NUMBER_MAX,
    PLACE_ROLE,
    REQS_ROLE,
    REQ_MAX,
    REQ_REST,
    SET_ROLE,
    SOCKETS_ROLE,
    SORT_KEYS,
    TIER_ROLE,
    TIER_CHIPS,
    TIER_LADDER,
    Advanced,
    CollectionFilter,
    fill_collection,
    new_model,
)
from app.sidebar import UNCLASSIFIED, SidePanel  # noqa: E402
from tl2stash.card import AFFIX, TIER_INK, Block, Card, Rung  # noqa: E402
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


def _fill(model, items, sets=None) -> None:
    """Put these items on a model as rows carrying the roles.

    Everything a row knows is one of the four fields above it plus the set it
    is in, and the set is the odd one: it comes off the item's own appearance
    rather than off the registry, so a row built by hand has to be told.  Every
    item not named in ``sets`` is in no set, which is the empty string a real
    row carries rather than nothing.

    Filling a model that already has rows is what a poll does -- the rows are
    thrown away and built again every couple of seconds -- so the tests that
    care what a sort does across one fill a model twice.
    """
    model.removeRows(0, model.rowCount())
    for name, tier, place, gate in items:
        cell = QStandardItem(name)
        cell.setData(name, FINGERPRINT_ROLE)
        cell.setData(tier, TIER_ROLE)
        cell.setData(place, PLACE_ROLE)
        cell.setData(gate, LEVEL_ROLE)
        cell.setData(gate, GATE_ROLE)
        cell.setData((sets or {}).get(name, ""), SET_ROLE)
        model.appendRow(
            [cell, QStandardItem(str(gate)), QStandardItem("0"), QStandardItem("")]
        )


def _built(items=ITEMS, sets=None):
    """A collection model carrying the roles, with no game and no catalog."""
    model = new_model(COLLECTION_COLUMNS)
    _fill(model, items, sets)
    return model


def _proxy(items=ITEMS, sets=None) -> CollectionFilter:
    """A proxy over the hand-built collection, wired the way the window wires it.

    The key column and the case sensitivity are not decoration: the window sets
    both, and a proxy matching differently here would be testing a filter the
    player never gets.
    """
    proxy = CollectionFilter()
    proxy.setSourceModel(_built(items, sets))
    proxy.setFilterKeyColumn(0)
    proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    return proxy


def _shown(proxy) -> list[str]:
    """The names the proxy is letting through, in its own order."""
    return [proxy.index(row, 0).data() for row in range(proxy.rowCount())]


def _listed(proxy) -> list[str]:
    """The names the proxy is letting through, in alphabetical order.

    Which rows survived, rather than what order they are in: a proxy orders
    what it lets through -- the wall opens on the rarity ladder, and that is
    pinned by :func:`test_the_wall_opens_on_the_rarity_ladder` -- so reading
    the names back in a fixed order is how every other test here says what its
    facet *kept* without the ladder in the way of reading it.
    """
    return sorted(_shown(proxy))


# --------------------------------------------------------------------------
# The kinds facet
# --------------------------------------------------------------------------


def test_with_nothing_ticked_the_whole_collection_is_shown(qapp):
    """An untouched rail is not a filter at all -- which is what makes it safe
    to ignore, and what makes "Clear filters" a state rather than a reset."""
    proxy = _proxy()

    assert _listed(proxy) == sorted(name for name, *_ in ITEMS)


def test_ticking_one_kind_leaves_only_that_kind(qapp):
    proxy = _proxy()

    proxy.set_places({BOOTS})

    assert _listed(proxy) == ["Alpha", "Beta", "Gamma"]


def test_ticking_two_kinds_leaves_both(qapp):
    proxy = _proxy()

    proxy.set_places({BOOTS, SWORD})

    assert _listed(proxy) == ["Alpha", "Beta", "Epsilon", "Gamma"]


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
    assert _listed(proxy) == ["Alpha", "Beta", "Delta", "Epsilon"]


def test_the_level_bounds_are_inclusive(qapp):
    proxy = _proxy()

    proxy.set_level_range(40, 40)

    assert _listed(proxy) == ["Alpha", "Delta", "Eta", "Gamma", "Zeta"]


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

    assert _listed(proxy) == ["Alpha", "Beta", "Gamma"]

    proxy.set_level_range(1, 1)
    assert _listed(proxy) == ["Alpha"], "zero is not in the range, one is"

    proxy.set_level_range(1, LEVEL_MAX - 1)
    assert _listed(proxy) == ["Alpha", "Beta"]


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
    assert _listed(proxy) == ["Alpha", "Beta", "Delta", "Eta", "Gamma", "Zeta"]

    proxy.set_places({BOOTS})
    assert _listed(proxy) == ["Alpha", "Beta", "Gamma"]

    proxy.setFilterFixedString("beta")
    assert _shown(proxy) == ["Beta"]


# --------------------------------------------------------------------------
# The set, which is arrived at rather than ticked
# --------------------------------------------------------------------------

#: Two of the seven are pieces of one set.  Written as the card draws the name,
#: because that is the whole interface between the card and this filter: an
#: item is of a set when the game's own file says that name for it.
SETS = {"Alpha": "Test Set", "Gamma": "Test Set"}


def test_showing_a_set_leaves_only_its_own_pieces(qapp):
    proxy = _proxy(sets=SETS)

    proxy.show_set("Test Set")

    assert _shown(proxy) == ["Alpha", "Gamma"]


def test_an_item_in_no_set_is_in_no_set(qapp):
    """The empty string a real row carries is not a name any click can produce --
    no card draws a set name for an item in no set -- so an item of none is out
    of every shown set, and showing *nothing* is the whole collection rather
    than the items of no set.
    """
    proxy = _proxy(sets=SETS)
    proxy.show_set("Test Set")
    assert "Beta" not in _shown(proxy)

    proxy.show_set("")
    assert _listed(proxy) == sorted(name for name, *_ in ITEMS)


def test_a_set_and_every_other_facet_and_together(qapp):
    """The one facet that is not set from a control is a facet all the same.

    The clearing of the other controls happens in the *bar*, one layer up --
    :meth:`app.filters.FilterBar.show_set` is what switches the player's other
    filters off -- so what the proxy has to do with a set is what it does with
    every other facet: narrow, and let the rest narrow further.
    """
    proxy = _proxy(sets=SETS)
    proxy.show_set("Test Set")

    proxy.set_places({BOOTS})
    assert _shown(proxy) == ["Alpha", "Gamma"]

    proxy.set_tiers({"Unique"})
    assert _shown(proxy) == ["Alpha"]

    proxy.set_level_range(40, 40)
    assert _shown(proxy) == ["Alpha"]

    proxy.set_level_range(0, 11)
    assert _shown(proxy) == []


def test_a_count_is_about_the_set_being_shown(qapp):
    """The counts ignore the three ticked facets and not this one.

    Those three exist to be chosen between, so the number beside one of them
    says what ticking it *would* leave.  A set is not chosen between -- it is
    the list in front of the player, arrived at by a click and left by clicking
    the chip -- so the numbers describe that list, exactly as they describe
    what the search box has already narrowed to.
    """
    proxy = _proxy(sets=SETS)
    proxy.show_set("Test Set")

    assert proxy.counts(TIER_ROLE) == {"Unique": 1, "Rare": 1}
    assert proxy.counts(PLACE_ROLE) == {BOOTS: 2}
    # And the kind ticks beside it are still ignored, set or no set.
    proxy.set_tiers({"Rare"})
    assert proxy.counts(TIER_ROLE) == {"Unique": 1, "Rare": 1}


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
# The eight the advanced search sets, which have no control in the row
# --------------------------------------------------------------------------

#: Four items and the six things the panel's facets read about them: the item's
#: own level, the player level the game gates it on, its sockets, what it asks
#: of a character, the one class that may use it, and its rarity.
#:
#: Between them they are every case the four rules have to tell apart -- a
#: socketed item and a socket-less one, a requirement and none, a class
#: restriction and none -- and one more the rules read from an odd side, which
#: is Fish: a socketable at level 0 that asks for nothing at all.
#:
#: Built here rather than by :func:`_fill`, because these six have to be
#: *stated*: the collection that function builds carries a kind, a rarity, a
#: set and a level and nothing else, which is exactly the shape a filter that
#: read none of the four would also agree with.
FACETED = [
    # name, level, gate, sockets, stats, class, tier
    ("Sword", 45, 51, 2, (("Strength", 60), ("Dexterity", 10)), "Embermage", "Unique"),
    ("Boots", 12, 12, 0, (), "", "Rare"),
    ("Axe", 60, 55, 1, (("Focus", 200),), "Outlander", "Unique"),
    ("Fish", 0, 0, 0, (("Strength", 5),), "", ""),
]


def _faceted() -> CollectionFilter:
    """A proxy over those four, wired the way the window wires it."""
    model = new_model(COLLECTION_COLUMNS)
    for name, level, gate, sockets, stats, cls, tier in FACETED:
        cell = QStandardItem(name)
        cell.setData(name, FINGERPRINT_ROLE)
        cell.setData(tier, TIER_ROLE)
        cell.setData(level, LEVEL_ROLE)
        cell.setData(gate, GATE_ROLE)
        cell.setData(sockets, SOCKETS_ROLE)
        cell.setData(stats, REQS_ROLE)
        cell.setData(cls, CLASS_ROLE)
        model.appendRow(
            [cell, QStandardItem(str(gate)), QStandardItem("0"), QStandardItem("")]
        )

    proxy = CollectionFilter()
    proxy.setSourceModel(model)
    return proxy


def _strength(pair) -> tuple[tuple[int, int], ...]:
    """The four attribute ranges with the first one moved and the rest at rest."""
    return (pair, *REQ_REST[1:])


def test_the_item_level_range_is_the_item_s_own_level(qapp):
    """Two ranges over two numbers, one row apart in the same section.

    The item level is how good the thing itself is; the player level is what
    the game makes a character grow into before it may be used.  A level 60 axe
    that asks for 55 is the pair that tells them apart -- and the same numbers
    set on the *other* range leave nothing at all, because no item here is
    gated on 60.
    """
    proxy = _faceted()

    proxy.set_item_levels(60, 60)
    assert _listed(proxy) == ["Axe"]

    proxy.set_level_range(60, 60)
    assert _listed(proxy) == []


def test_a_level_of_zero_is_a_number_inside_the_range(qapp):
    """The socketables carry it, which is why the range starts at nothing.

    So a resting range is the whole of itself rather than a question nobody
    asked, and the item at zero is one a range starting at zero shows -- the
    same reading the gate is given, seen from the other side.
    """
    proxy = _faceted()

    proxy.set_item_levels(0, LEVEL_MAX)
    assert _listed(proxy) == ["Axe", "Boots", "Fish", "Sword"]


def test_a_socket_count_is_exact_and_not_a_floor(qapp):
    """The chips are one to five and each means that many.

    A two-socket sword is not shown by a tick on one, and the item with no
    sockets at all is shown by none of them -- which is what starting the chips
    at one leaves out on purpose, and the reason no chip reading "any" is
    needed beside them.
    """
    proxy = _faceted()

    proxy.set_sockets({2})
    assert _listed(proxy) == ["Sword"]

    proxy.set_sockets({1, 2})
    assert _listed(proxy) == ["Axe", "Sword"]

    proxy.set_sockets(set())
    assert _listed(proxy) == ["Axe", "Boots", "Fish", "Sword"], "no tick is any number"


def test_a_requirement_is_a_number_that_has_to_fit_inside_the_range(qapp):
    """An item that requires nothing requires zero, and that is the whole rule.

    Which is why a floor and a ceiling do opposite things to the boots: they
    ask a character for nothing at all, so a floor of 20 leaves them out and a
    ceiling of 20 keeps them in.  The reference database reads its own four
    numbers the same way, and it is why an empty range is not the same thing as
    a range nobody moved.
    """
    proxy = _faceted()

    proxy.set_requirements(_strength((20, REQ_MAX)))
    assert _listed(proxy) == ["Sword"], "60 Strength, where nobody else asks for 20"

    proxy.set_requirements(_strength((0, 20)))
    assert _listed(proxy) == ["Axe", "Boots", "Fish"], "nothing at all is under 20"


def test_each_of_the_four_attributes_is_read_on_its_own(qapp):
    """Four ranges in one value, told apart by where they stand rather than by
    a name, so moving one of them narrows by that attribute only.

    The two weapons here are what says so: the axe is the only item asking for
    any Focus, and the sword the only one asking for any Dexterity -- ten of it,
    which is the floor set below, so the bound is inclusive at the edge it
    lands on.
    """
    proxy = _faceted()
    focus = (REQ_REST[0], REQ_REST[1], (100, REQ_MAX), REQ_REST[3])
    dexterity = (REQ_REST[0], (10, REQ_MAX), REQ_REST[2], REQ_REST[3])

    proxy.set_requirements(focus)
    assert _listed(proxy) == ["Axe"]

    proxy.set_requirements(dexterity)
    assert _listed(proxy) == ["Sword"]


def test_an_item_that_names_no_class_is_for_every_class(qapp):
    """The one rule that reads backwards, and the reference's own.

    A restriction is the exception rather than the rule -- most of the game's
    items are for everyone -- so an item naming no class passes every tick, and
    it is a class that is *somebody else's* that turns an item away.
    """
    proxy = _faceted()

    proxy.set_classes({"Embermage"})
    assert _listed(proxy) == ["Boots", "Fish", "Sword"], "the axe is the Outlander's"

    proxy.set_classes({"Berserker"})
    assert _listed(proxy) == ["Boots", "Fish"], "and nobody here is a Berserker's"


def test_the_four_narrow_the_counts_as_well_as_the_list(qapp):
    """The numbers beside the rail are the numbers of the list in front of the
    player, and a panel nobody can see is still narrowing that list.

    So a count that ignored the four would be a number about a collection that
    is not on screen -- which is the one lie a count must not tell.
    """
    proxy = _faceted()
    assert proxy.counts(TIER_ROLE) == {"Unique": 2, "Rare": 1, "": 1}

    proxy.set_sockets({2})

    assert proxy.counts(TIER_ROLE) == {"Unique": 1}


# --------------------------------------------------------------------------
# The three that read the card
#
# A card's damage, its armour and its property lines are built by walking the
# game's data files, which is not something to do for every row of a collection
# nobody has asked a question about -- so these three facets are answered from
# a *lookup* the window offers, and what is pinned here is both halves of that
# bargain: what each facet means, and that nothing is looked up until one of
# them is set.
# --------------------------------------------------------------------------

#: Three items and the cards behind them, which is what the last three facets
#: are answered from.  A weapon, a piece of armour and a shield, so that an
#: element asked for on a weapon is not found on the armour and a property
#: asked for on the armour is not found on the weapon -- and one element on
#: each of the two so that Damage and Armor are not one question asked twice.
#:
#: The shield is the reach of the rules: it is armour, its span is wide, and
#: its set ladder carries a line its own properties do not.
CARDS = {
    "Blade": Card(
        name="Blade",
        tier="unique",
        tier_word="Unique",
        type_name="Sword",
        set_name=None,
        icon=None,
        level=45,
        sockets=0,
        blocks=(Block(AFFIX, ("+15% to Fire Damage", "+38 to Strength")),),
        gems=(),
        set_ladder=(),
        flavor=None,
        damage=(("physical", 14, 28), ("fire", 40, 60)),
        armor=(),
    ),
    "Choker": Card(
        name="Choker",
        tier="rare",
        tier_word="Rare",
        type_name="Amulet",
        set_name=None,
        icon=None,
        level=30,
        sockets=0,
        blocks=(Block(AFFIX, ("+22 to Strength",)),),
        gems=(),
        set_ladder=(),
        flavor=None,
        damage=(),
        armor=(("physical", 85, 85), ("fire", 32, 32)),
    ),
    "Warder": Card(
        name="Warder",
        tier="set",
        tier_word="Set",
        type_name="Shield",
        set_name="Test Set",
        icon=None,
        level=20,
        sockets=0,
        blocks=(Block(AFFIX, ("+9 Physical Damage",)),),
        gems=(),
        set_ladder=(Rung(3, ("+15% to Fire Damage",)),),
        flavor=None,
        damage=(),
        armor=(("physical", 120, 180),),
    ),
}


def _carded(cards=None) -> CollectionFilter:
    """A proxy over those cards, wired the way the window wires it.

    The row carries the fingerprint and the lookup answers it with the card,
    which is the whole of the contract: a row on its own is a name and three
    numbers, and the item behind it is somewhere the proxy asks about.
    """
    cards = CARDS if cards is None else cards
    model = new_model(COLLECTION_COLUMNS)
    for name, card in cards.items():
        cell = QStandardItem(name)
        cell.setData(name, FINGERPRINT_ROLE)
        cell.setData(card.tier_word, TIER_ROLE)
        # Every row the window builds carries the item's own level, and the
        # two card-reading keys tie-break on it -- so a row built without one
        # would sort by name and quietly agree with a different rule.
        cell.setData(card.level, LEVEL_ROLE)
        model.appendRow(
            [
                cell,
                QStandardItem(str(card.level)),
                QStandardItem("0"),
                QStandardItem(""),
            ]
        )
    proxy = CollectionFilter()
    proxy.setSourceModel(model)
    proxy.set_detail(cards.get)
    return proxy


def test_a_fire_range_keeps_an_item_whose_fire_span_merely_overlaps_it(qapp):
    """The rule is overlap and not containment, and this is the pair that says
    which.

    The blade rolls 40-60 fire and the search asks for 20-45: neither span
    contains the other, and the item passes -- because neither end of either
    span is the real number, both being what a roll can land on.  A comparator
    that wanted the item's low inside the range, or the range inside the item,
    would turn it away.  The second half is the same item against a range it
    does not reach at all, so that the first half is not passing everything.
    """
    proxy = _carded()

    proxy.set_damage((("fire", 20, 45),))
    assert _listed(proxy) == ["Blade"]

    proxy.set_damage((("fire", 70, 90),))
    assert _listed(proxy) == []


def test_an_element_the_item_does_not_carry_turns_it_away(qapp):
    """The presence half, which is the half that is easy to leave out.

    The warder's armour is 120-180 physical, so its span *does* overlap a
    request for any amount of fire -- if naming an element were only a range,
    the shield would pass.  It does not: *a type named here has to be one the
    item carries*, which is the reference's own reading of an empty pair of
    boxes, and the choker is here to say the row is not simply matching
    nothing.
    """
    proxy = _carded()

    proxy.set_armor((("fire", 0, NUMBER_MAX),))

    assert _listed(proxy) == ["Choker"], "not the shield"


def test_the_armour_section_is_a_question_of_its_own(qapp):
    """Ten rows in two sections, and a weapon's damage has nothing to do with
    a chest's armour.

    One element, two items, one question each: the blade's fire is *damage* and
    the choker's fire is *armour*, so the same row in the two sections finds
    one item either way and a different item each way.
    """
    proxy = _carded()

    proxy.set_damage((("fire", 0, NUMBER_MAX),))
    assert _listed(proxy) == ["Blade"], "the sword's fire is damage"

    proxy.set_damage(())
    proxy.set_armor((("fire", 0, NUMBER_MAX),))
    assert _listed(proxy) == ["Choker"], "and the amulet's is armour"


def test_no_element_named_is_not_the_same_as_every_element_named(qapp):
    """An empty ``damage`` is the rest state -- nothing asked -- and a row
    covering everything is not the same thing.

    The one is a facet nobody has touched and the other is a row that has been
    moved, which is how the panel says *this element and no other*: what is
    left of the question is the presence half, and the blade's damage is not
    armour however wide the range is.
    """
    proxy = _carded()

    proxy.set_damage(())
    assert _listed(proxy) == ["Blade", "Choker", "Warder"]

    proxy.set_armor((("physical", 0, NUMBER_MAX),))
    assert _listed(proxy) == ["Choker", "Warder"], "the two that carry armour"


def test_a_stat_row_matches_by_text_and_then_by_the_number(qapp):
    """One row, two halves: the words, and the range they have to land in.

    The words are matched by containment rather than for equality, because
    what the picker offers is a fragment of a sentence -- ``to strength`` is
    nowhere in ``+38 to Strength`` as a whole word and is in it as a substring
    -- and what a row is typed from is that fragment.  The range is read off
    the first number on whichever line the words found.
    """
    proxy = _carded()

    proxy.set_stats((("to strength", 0, NUMBER_MAX),))
    assert _listed(proxy) == ["Blade", "Choker"], "the shield says nothing of it"

    proxy.set_stats((("to strength", 30, NUMBER_MAX),))
    assert _listed(proxy) == ["Blade"], "38 is over 30 and 22 is not"


def test_a_row_with_no_range_asks_only_whether_the_item_says_it(qapp):
    """The unbounded row, which is the reference's most common one.

    It is the whole of the question when the number is not what the player
    cares about -- a stat that only exists on a set ladder is asked for this
    way -- and it is what makes a row that has been typed into and not bounded
    do something rather than nothing.
    """
    proxy = _carded()

    proxy.set_stats((("physical damage", ELEMENT_REST[0], ELEMENT_REST[1]),))

    assert _listed(proxy) == ["Warder"], "the shield's own flat damage line"


def test_set_bonus_lines_are_invisible_until_the_box_is_ticked(qapp):
    """``Include set bonuses`` widens *where* a row may be answered from.

    ``+15% to Fire Damage`` is on the warder's ladder and not among its own
    lines, and it is on the blade's own lines and on no ladder -- so the same
    row finds exactly one item either way, and it is a different item each way.
    That is what says the ladder is a second pool rather than a second clause:
    a bonus nobody asked about is not a reason to turn an item away, which is
    why the shield is still shown when the box is ticked and a row asks for
    something else.
    """
    proxy = _carded()

    proxy.set_stats((("to fire damage", 0, NUMBER_MAX),))
    assert _listed(proxy) == ["Blade"]

    proxy.set_stats((("to fire damage", 0, NUMBER_MAX),), bonuses=True)
    assert _listed(proxy) == ["Blade", "Warder"]

    proxy.set_stats((("to strength", 0, NUMBER_MAX),), bonuses=True)
    assert _listed(proxy) == ["Blade", "Choker"], "the ladder is a pool, not a clause"


def test_every_row_has_to_be_answered_and_not_merely_one(qapp):
    """Rows AND together like every other facet here, and like the reference's:
    a form of two rows is a question with two parts."""
    proxy = _carded()

    proxy.set_stats(
        (("to strength", 0, NUMBER_MAX), ("to fire damage", 0, NUMBER_MAX))
    )
    assert _listed(proxy) == ["Blade"], "the choker has the strength and no fire"


def test_nothing_is_looked_up_until_one_of_the_three_is_set(qapp):
    """The bargain the lookup exists for.

    A card is built by walking the game's data files, so asking for one per row
    on every poll would be doing that work for a collection nobody has asked a
    question about.  The counter is the point of the test: three facets read
    the card, and every other one reads the row and never asks.
    """
    asked = []

    def counting(print_: str):
        asked.append(print_)
        return CARDS.get(print_)

    proxy = _carded()
    proxy.set_detail(counting)

    proxy.set_places(set())          # the kinds
    proxy.set_tiers(set())           # the rarities
    proxy.set_level_range(0, LEVEL_MAX)
    proxy.set_item_levels(0, LEVEL_MAX)
    proxy.set_sockets(set())
    proxy.set_requirements(REQ_REST)
    proxy.set_classes(set())
    proxy.counts(TIER_ROLE)
    assert asked == [], "a poll that asks nothing built a card"

    proxy.set_damage((("fire", 0, NUMBER_MAX),))
    assert asked, "the one facet that needs it did not ask"


def test_an_item_with_no_card_fails_a_search_that_asked(qapp):
    """``None`` is not a pass.  A row the tool cannot describe -- an item the
    parser could not read, or a collection assembled with no window behind it
    -- is not an item that matches a description of one.

    And nothing raises: the predicate runs inside a filter, where an exception
    is a crash in the middle of a repaint rather than a message.
    """
    proxy = _carded()
    proxy.set_detail(lambda print_: None)

    proxy.set_damage((("fire", 0, NUMBER_MAX),))

    assert _listed(proxy) == []


def test_a_proxy_with_no_lookup_at_all_narrows_to_nothing(qapp):
    """The same answer from the other side: a proxy that was never told how to
    get a card cannot honestly pass anything through one of these three."""
    proxy = _carded()
    proxy.set_detail(None)

    proxy.set_stats((("to strength", 0, NUMBER_MAX),))

    assert _listed(proxy) == []


def test_the_three_narrow_the_counts_as_well_as_the_list(qapp):
    """The same rule as the other five: a panel nobody is looking at is still
    narrowing the list in front of the player, so it is still what the numbers
    beside the rail are counted from."""
    proxy = _carded()

    proxy.set_damage((("fire", 0, NUMBER_MAX),))

    assert _listed(proxy) == ["Blade"]
    assert proxy.counts(TIER_ROLE) == {"Unique": 1}


# --------------------------------------------------------------------------
# The order, which is not a facet
# --------------------------------------------------------------------------

#: One item on every rung of the ladder, three levels inside one rung, and the
#: three ways a row can have no rarity at all: the empty word a row carries on
#: a machine with no game installed, and the game's own two words for the
#: objects that are not rarities at all -- ``QUESTITEM`` and ``LEVEL``, which
#: are 186 of the archive's 6,262 item files between them.  None of the three
#: is a rung, and the user's rule puts every one of them last.
#:
#: The names are in no order the ladder could be confused with.  That is the
#: point of them: an order read off this list could only come from the ladder.
LADDERED = [
    ("White", "Normal", BOOTS, 40),
    ("Green", "Magic", BOOTS, 40),
    ("Blue", "Rare", BOOTS, 40),
    ("Purple", "Set", BOOTS, 40),
    ("Red", "Legendary", BOOTS, 40),
    ("Low", "Unique", BOOTS, 3),
    ("Orange", "Unique", BOOTS, 40),
    ("High", "Unique", BOOTS, 97),
    ("Fish", "", QUEST, 40),
    ("Quest", "Quest", QUEST, 12),
    ("Level", "Level", QUEST, 7),
]

#: The same rows in the order the wall opens on: the ladder best first, the
#: item level running 1 to 100 inside each rung -- which is the whole of what
#: separates the three uniques -- and the three untiered last, in the one order
#: left to them.
LADDER_ORDER = [
    "Red",
    "Purple",
    "Low",
    "Orange",
    "High",
    "Blue",
    "Green",
    "White",
    "Level",
    "Quest",
    "Fish",
]


def test_the_wall_opens_on_the_ladder_the_user_asked_for(qapp):
    """The user's third change, and the one place this tool's order is not the
    reference's: *"legendary first, normal 2nd last, untiered last and within
    each tier level 1 to 100"*.

    Every rung is a word a card can be inked by -- which is why the ladder is
    written in the card's own words rather than in colour keys -- and Set is
    among them even though no item file wears it: a set piece states the
    rarity it displaced, so the rung is one the archive cannot prove and this
    is the fixture that pins it.

    Neither the names nor the order the rows arrive in is what comes out,
    which is the whole of what the ladder is for.
    """
    proxy = _proxy(LADDERED)

    assert TIER_LADDER == ("Legendary", "Set", "Unique", "Rare", "Magic", "Normal")
    assert _shown(proxy) == LADDER_ORDER
    assert _shown(proxy) != [name for name, *_ in LADDERED], (
        "the rows came out in the order they were handed over in"
    )


def test_the_arrow_turns_the_ladder_over_and_leaves_the_tiers_alone(qapp):
    """What the arrow does, and what it deliberately does not.

    The reference multiplies its whole comparison by the direction, so turning
    its ladder over turns every tier's items over with it and each one runs
    100 down to 1.  Here only the ladder answers to the arrow: a tier still
    runs 3, 40, 97 whichever way it is read, because *"within each tier level
    1 to 100"* is the user's rule and it is a rule about the tier rather than
    about the arrow.

    The untiered go with the ladder rather than holding still: they are its
    last rung and not a separate pile, so they are first when it is read the
    other way -- and still in level order among themselves.
    """
    proxy = _proxy(LADDERED)
    proxy.set_sort("Tier", True)

    assert _shown(proxy) == [
        "Level",
        "Quest",
        "Fish",
        "White",
        "Green",
        "Blue",
        "Low",
        "Orange",
        "High",
        "Purple",
        "Red",
    ]
    shown = _shown(proxy)
    assert shown.index("Low") < shown.index("High"), (
        "the tier was read upside down along with the ladder"
    )


def test_the_name_and_the_level_each_sort_as_they_say(qapp):
    """The two keys that read nothing but the row itself.

    The level is the item's own, the number the list has always shown.  As
    with the ladder, the arrow turns the first thing the key says and nothing
    else, so *Level* read backwards is 97 down to 3 with the names still
    running up inside one level -- the same rule, applied to the key a player
    who chose *Level* is reading.
    """
    proxy = _proxy(LADDERED)

    proxy.set_sort("Name")
    assert _shown(proxy) == [
        "Blue",
        "Fish",
        "Green",
        "High",
        "Level",
        "Low",
        "Orange",
        "Purple",
        "Quest",
        "Red",
        "White",
    ]

    proxy.set_sort("Level")
    assert _shown(proxy) == [
        "Low",
        "Level",
        "Quest",
        "Blue",
        "Fish",
        "Green",
        "Orange",
        "Purple",
        "Red",
        "White",
        "High",
    ]

    proxy.set_sort("Level", True)
    assert _shown(proxy) == [
        "High",
        "Blue",
        "Fish",
        "Green",
        "Orange",
        "Purple",
        "Red",
        "White",
        "Quest",
        "Level",
        "Low",
    ]


def test_the_type_sorts_by_the_kind_word_and_not_by_the_rail_s_path(qapp):
    """*Type* is the kind the card names, and not the path the rail files the
    item under.

    Sorting on the path would order by group first -- every piece of armour
    together, every weapon together -- which is not what a player choosing
    *Type* is asking for: the reference reads the kind word alone, and the
    four items here are in an order no group-first reading of them can
    produce, whichever way the groups themselves run.
    """
    typed = [
        ("Sword", "Unique", ("Weapons", "One-Handed", "Sword"), 40),
        ("Boots", "Unique", ("Armor", None, "Boots"), 40),
        ("Axe", "Unique", ("Weapons", "One-Handed", "Axe"), 40),
        ("Nothing", "Unique", QUEST, 40),
    ]
    proxy = _proxy(typed)
    proxy.set_sort("Type")

    assert _shown(proxy) == ["Nothing", "Axe", "Boots", "Sword"]


#: A fourth item for the two keys that read a card: one with nothing left of
#: it.  Zero damage is a *number* and the absence of damage is not one, which
#: is the whole of why the two sort differently -- see
#: :meth:`app.models.CollectionFilter._carried`.
STUB = Card(
    name="Stub",
    tier="normal",
    tier_word="Normal",
    type_name="Sword",
    set_name=None,
    icon=None,
    level=10,
    sockets=0,
    blocks=(),
    gems=(),
    set_ladder=(),
    flavor=None,
    damage=(("physical", 0, 0),),
    armor=(("physical", 0, 0),),
)


def test_damage_sorts_by_what_the_item_carries_most_first(qapp):
    """The reference's own reading: the midpoints of an item's parts, summed.

    Which is why the two-element sword is above a piece carrying the same span
    in one element -- a span is counted at its middle, and the two are the two
    things the item's damage really is.

    The last two rows are the shape of the rule rather than an accident of the
    fixture: the warder and the choker carry no damage at all and the stub
    carries none-worth, and *none* sorts below *none-worth* -- because zero is
    a number and the absence of one is not, so the absence is the worst value
    there is rather than the best.
    """
    proxy = _carded({**CARDS, "Stub": STUB})
    proxy.set_sort("Damage")

    assert _shown(proxy) == ["Blade", "Stub", "Warder", "Choker"]


def test_armor_sorts_the_same_way_over_the_other_number(qapp):
    """The same key over the other half of the card, and the two are not one
    question: the sword is top of one list and bottom of the other.

    The choker's 117 is 85 physical and 32 fire -- five elements summed at
    their middles -- against the warder's single 120-180.
    """
    proxy = _carded({**CARDS, "Stub": STUB})
    proxy.set_sort("Armor")

    assert _shown(proxy) == ["Warder", "Choker", "Stub", "Blade"]


def test_the_arrow_turns_a_card_key_over_and_leaves_the_ties_alone(qapp):
    """*Damage* read the other way is least first, and the rows the key cannot
    tell apart keep the order everything else here is read in.

    The reference multiplies its whole comparison by the direction, so its two
    four-hundred-damage weapons would swap places on the arrow for no reason a
    player could name.  Here only what the key *says* answers to the arrow --
    the same rule the ladder follows, and the reason the two rows carrying no
    damage come out in level order both ways.
    """
    proxy = _carded({**CARDS, "Stub": STUB})
    proxy.set_sort("Damage", True)

    shown = _shown(proxy)

    assert shown == ["Warder", "Choker", "Stub", "Blade"]
    assert shown.index("Warder") < shown.index("Choker"), (
        "the two rows the key ties were read upside down along with it"
    )


def test_a_card_key_asks_for_no_card_until_it_is_the_key(qapp):
    """The other half of the bargain the lookup makes: the wall is re-ordered
    after every poll, and a poll that asks every item for its card would build
    the whole collection's cards to sort a list nobody has re-ordered."""
    asked = []

    def counting(print_: str):
        asked.append(print_)
        return CARDS.get(print_)

    proxy = _carded()
    proxy.set_detail(counting)

    proxy.set_sort("Tier")
    _shown(proxy)
    assert asked == []

    proxy.set_sort("Damage")
    _shown(proxy)
    assert asked, "the one key that needs it did not ask"


def test_a_sort_is_not_a_filter_and_moves_no_number(qapp):
    """Nothing about *which* rows are on the wall changes, so nothing there is
    to count -- which is why the window hears a signal of its own and does not
    re-count the rail and the chips."""
    proxy = _proxy()
    was = _listed(proxy)
    counts = (proxy.counts(TIER_ROLE), proxy.counts(PLACE_ROLE))

    proxy.set_sort("Level")
    proxy.set_sort("Type", True)

    assert _listed(proxy) == was
    assert (proxy.counts(TIER_ROLE), proxy.counts(PLACE_ROLE)) == counts


def test_the_order_survives_the_rows_being_thrown_away_and_built_again(qapp):
    """A poll takes every row off the model and puts it back, and the order
    the player asked for is still the order when it does."""
    proxy = _proxy(LADDERED)
    proxy.set_sort("Name", True)

    # What the window does every couple of seconds.
    _fill(proxy.sourceModel(), LADDERED)

    assert _shown(proxy) == [
        "White",
        "Red",
        "Quest",
        "Purple",
        "Orange",
        "Low",
        "Level",
        "High",
        "Green",
        "Fish",
        "Blue",
    ]


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
        # Upper-cased on the way to the screen, which is how the reference
        # draws its own subgroup captions; the place keeps its spelling.
        "  ONE-HANDED",
        "    Sword",
        "Misc",
        f"  {UNCLASSIFIED}",
    ]
    # Nothing in the collection is a two-handed weapon, so the rail says
    # nothing about them.
    assert "Cannon" not in " ".join(_rows(panel))
    # And only the drawn word is upper-cased: what a tick on the leaf reports
    # is still the place, spelled the way the taxonomy spells it.
    panel.tree.topLevelItem(1).child(0).child(0).setCheckState(
        0, Qt.CheckState.Checked
    )
    assert panel.places() == {SWORD}


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


def test_clearing_a_rail_with_nothing_ticked_says_nothing(qapp):
    """The window redraws the wall for every signal it hears, and it clears the
    rail on paths that have already cleared it -- a different save file opens
    on an empty rail, and `Clear filters` is the bar's own reset.  A rail with
    nothing ticked has nothing to say about either."""
    panel = _panel()
    panel.set_shape([BOOTS, SWORD])
    heard = []
    panel.changed.connect(lambda: heard.append(1))

    panel.reset()

    assert heard == [], "an empty rail said something"


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
# The rail's voice, which is the reference's
# --------------------------------------------------------------------------


def test_the_rail_wears_the_reference_s_inks_and_sizes(qapp):
    """The user's second change: the reference's colours and headings.

    A group is its ``--head`` tan, a subgroup its ``--label`` upper-cased, a
    leaf the window's own body ink, and every count its ``--muted`` at 11px.
    Read off the drawn rows rather than off a constant, because what the
    player sees is what the rows are set to.

    Every one of the three *word* sizes is the rail's own, which is the later
    request and the reason this says equality rather than a ramp: the headings
    were 12 and 10 against the kinds' 15, and the user's complaint was exactly
    that -- a heading drawn smaller than the words it heads.  What separates
    the levels now is the ink above, the weight, and the upper case on the
    subgroup, all of which this test pins alongside.
    """
    panel = _panel()
    panel.set_shape([BOOTS, SWORD])
    panel.set_counts({BOOTS: 3, SWORD: 2})

    armor, weapons = panel.tree.topLevelItem(0), panel.tree.topLevelItem(1)
    one_handed = weapons.child(0)
    sword = one_handed.child(0)

    assert armor.foreground(0).color().name() == HEAD
    assert one_handed.foreground(0).color().name() == LABEL
    assert sword.foreground(0).color().name() == BODY
    for row in (armor, one_handed, sword):
        assert row.foreground(1).color().name() == MUTED
        assert row.font(1).pixelSize() == COUNT_PX

    # One size for the words and one for the counts.  A heading is not a size
    # under its kinds, and the kinds are not a size under their heading.
    assert armor.font(0).pixelSize() == RAIL_PX
    assert one_handed.font(0).pixelSize() == RAIL_PX
    assert sword.font(0).pixelSize() < 0, (
        "the leaves take their size from the sheet -- Qt's sentinel for a font "
        "with no size of its own is negative -- and setting one here would be a "
        "second place the rail's size is written"
    )
    assert armor.text(0) == "Armor" and one_handed.text(0) == "ONE-HANDED", (
        "the subgroup is not upper-cased, which is now one of the two things "
        "telling it from the group above it"
    )


def test_the_longest_heading_still_fits_the_rail_it_is_drawn_in(themed):
    """The check that the size change is one the rail can actually draw.

    Raising the headings to the kinds' size is only safe while the widest of
    them still fits the column -- and a heading that elides is a heading that
    reads as half a word, which is the one thing a size for *headings* cannot
    cost.  Measured rather than assumed: the rail's own name column, less the
    indent a subgroup row is drawn at, against the words themselves at the
    size the rows are set to.
    """
    panel = _panel()
    panel.set_shape([BOOTS, SWORD])
    panel.resize(180, 400)
    panel.show()
    themed.processEvents()

    tree = panel.tree
    room = tree.columnWidth(0) - tree.indentation()
    assert room > 0, "the rail was not laid out, so there is nothing to measure"

    for words in ("ACCESSORIES", "ONE-HANDED", "TWO-HANDED", "OFF-HAND"):
        font = QFont(QApplication.font())
        font.setPixelSize(RAIL_PX)
        drawn = QFontMetrics(font).horizontalAdvance(words)
        assert drawn < room, f"{words} is cut off at {drawn} of {room} pixels"


def test_the_rail_s_rows_are_drawn_with_air_between_them(themed):
    """The other half of the request: more of it between one kind and the next.

    Measured on a shown rail, because the heights are the fact -- a row the
    sheet's padding did not reach would be the old 18px whatever the constants
    say.  Every row is taller than the window's own body text, and a heading is
    taller again than the kinds it heads.
    """
    panel = _panel()
    panel.set_shape([BOOTS, SWORD])
    panel.resize(240, 300)
    panel.show()
    themed.processEvents()

    tree = panel.tree
    group = tree.visualItemRect(tree.topLevelItem(0)).height()
    subgroup = tree.visualItemRect(tree.topLevelItem(1).child(0)).height()
    leaf = tree.visualItemRect(tree.topLevelItem(1).child(0).child(0)).height()

    body = QFontMetrics(QApplication.font()).height()
    assert leaf > body, "the kinds did not gain their air"
    assert leaf == 26, "the sheet's padding is not the 4px it measures"
    assert group > leaf, "a group is not drawn above its kinds"
    assert subgroup < group, "a subgroup is not a size under its group"


def test_a_heading_says_what_a_click_on_it_would_do(qapp):
    """The reference's tri-state: all of it, some of it, none of it.

    A heading is a bulk toggle over the kinds under it, so its own row is the
    only thing that says what ticking it means -- and "everything under me" and
    "nothing under me" must not be the same row.
    """
    panel = _panel()
    panel.set_shape([BOOTS, HELMET, SWORD])
    panel.set_counts({BOOTS: 1, HELMET: 1, SWORD: 1})
    armor, weapons = panel.tree.topLevelItem(0), panel.tree.topLevelItem(1)

    assert armor.text(0) == "Armor" and armor.foreground(0).color().name() == HEAD

    # Some of it: a mark, and the heading keeps its own ink -- the dot is not
    # a fourth state, it is "the rest of this is not ticked".
    armor.child(0).setCheckState(0, Qt.CheckState.Checked)
    panel.set_counts({BOOTS: 1, HELMET: 1, SWORD: 1})
    assert armor.text(0) == "Armor ·"
    assert armor.foreground(0).color().name() == HEAD

    # All of it: gold, and the mark goes -- there is nothing left to say.
    armor.child(1).setCheckState(0, Qt.CheckState.Checked)
    panel.set_counts({BOOTS: 1, HELMET: 1, SWORD: 1})
    assert armor.text(0) == "Armor"
    assert armor.foreground(0).color().name() == GOLD

    # And the group next to it, with nothing ticked, is not gold.
    assert weapons.foreground(0).color().name() == HEAD


def test_a_row_with_nothing_behind_it_dims(qapp):
    """A count of zero is a kind the current filters cannot reach.

    The reference dims the whole row for it, and the number is what says so
    first: a kind nobody can get to should not look like one they can.
    """
    panel = _panel()
    panel.set_shape([BOOTS, HELMET, SWORD])
    panel.set_counts({BOOTS: 0, HELMET: 4, SWORD: 2})

    armor, weapons = panel.tree.topLevelItem(0), panel.tree.topLevelItem(1)
    boots, helmet = armor.child(0), armor.child(1)

    assert boots.foreground(0).color().name() == DIM
    assert helmet.foreground(0).color().name() == BODY

    # A heading dims when the filters have emptied it, whatever its boxes say:
    # the row's own number is what the reference reads, and a heading over
    # nothing but zeroes has the zero either way.
    panel.set_counts({BOOTS: 0, HELMET: 0, SWORD: 2})
    assert armor.foreground(0).color().name() == DIM
    assert weapons.foreground(0).color().name() == HEAD


def test_a_ticked_group_is_drawn_in_gold_and_the_row_under_the_pointer_lifts(themed):
    """Both halves, where the player reads them: on the drawn row.

    The inks are set on the item, but the row is what the eye lands on, so this
    counts them in the pixels.  Near them, rather than equal to them: a 12px
    heading is drawn anti-aliased, and the ink reaches its own colour only in
    the thickest part of a stroke -- the rest of a letter is the ink blended
    towards the ground.  The slack costs the test nothing, because the two inks
    it tells apart are 44 pixels of one and none at all of the other.

    The hover band is the other thing the reference's rail does that neither a
    palette nor an ink can say: the row under the pointer is drawn a step up
    from the ground the column sits on, and the row beside it is not.
    """
    panel = _panel()
    panel.set_shape([BOOTS, SWORD])
    panel.set_counts({BOOTS: 1, SWORD: 1})
    panel.resize(200, 220)
    panel.show()
    themed.processEvents()

    tree = panel.tree
    group = tree.topLevelItem(0)
    below = tree.topLevelItem(1)

    def drawn(ink: str) -> int:
        """How many pixels of the group's row are this ink, near enough."""
        rect = tree.visualItemRect(group)
        image = tree.viewport().grab().toImage()
        want = QColor(ink)
        return sum(
            1
            for y in range(rect.top(), rect.bottom() + 1)
            for x in range(rect.left(), rect.right() + 1)
            if max(
                abs(image.pixelColor(x, y).red() - want.red()),
                abs(image.pixelColor(x, y).green() - want.green()),
                abs(image.pixelColor(x, y).blue() - want.blue()),
            )
            <= 24
        )

    assert drawn(GOLD) == 0, "an unticked heading is already gold"
    assert drawn(HEAD) > 0, "an unticked heading is not drawn in its own tan"
    group.setCheckState(0, Qt.CheckState.Checked)
    panel.set_counts({BOOTS: 1, SWORD: 1})
    themed.processEvents()
    assert drawn(GOLD) > 0, "the fully-ticked heading is not drawn in gold"
    assert drawn(HEAD) == 0, "the gold heading kept its tan as well"

    # Nothing in the rail is the cursor's place, so nothing is drawn as one:
    # what this test is about is the band under the *pointer*.
    tree.setCurrentItem(None)
    themed.processEvents()

    def band(item) -> str:
        rect = tree.visualItemRect(item)
        themed.processEvents()
        image = tree.viewport().grab().toImage()
        return image.pixelColor(rect.left() + 2, rect.center().y()).name()

    # A row is drawn on the surface the sheet puts the column on -- read at the
    # row's left inset, where no box and no word stands -- and the row the
    # pointer is on is drawn a step up from it.
    assert band(below) == SHELL, "the rail is not drawn on the shell"
    QTest.mouseMove(tree.viewport(), tree.visualItemRect(below).center())
    themed.processEvents()
    assert band(below) == FIELD, "the row under the pointer did not lift"
    assert band(group) == SHELL, "a row the pointer is not on lifted too"


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
    """One signal for every control that narrows, because the window does one
    thing with it: re-apply every facet and re-count.  The sort is not one of
    them and has a signal of its own, below."""
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


def test_the_bar_says_when_it_was_cleared_rather_than_narrowed(qapp):
    """`Clear filters` is the whole window's starting state, and the kinds are
    ticked in the rail -- a widget this bar has no way to reach.  So the one
    button that shows everything again has to say *that it cleared*, which a
    signal about a control having moved cannot say."""
    bar = _bar()
    heard = []
    bar.cleared.connect(lambda: heard.append(1))

    bar.search.setText("drill")
    bar.chips["Unique"].setChecked(True)

    assert heard == [], "a narrowing is not a clearing"

    bar.reset()

    assert len(heard) == 1


def test_the_bar_keeps_the_eight_facets_the_panel_sets(qapp):
    """They are held rather than drawn, and the bar is where they are held.

    There is no room in the row for a second level range, five socket chips,
    four attribute pairs, four classes, ten element ranges and a list of
    property rows -- and no need of it, because the panel is where they are
    set.  What the bar is for is remembering them, so that the window can ask
    for the whole search and the panel can open on what is in force (below).
    """
    bar = _bar()

    assert bar.item_level_range() == (0, LEVEL_MAX)
    assert bar.sockets() == set()
    assert bar.requirement_ranges() == REQ_REST
    assert bar.classes() == set()
    assert bar.damage_ranges() == ()
    assert bar.armor_ranges() == ()
    assert bar.stat_rows() == ()
    assert bar.bonuses() is False
    assert bar.advanced_active() is False

    bar.adopt(
        Advanced(
            item_low=10,
            item_high=20,
            sockets=frozenset({2}),
            reqs=_strength((30, REQ_MAX)),
            classes=frozenset({"Embermage"}),
            damage=(("fire", 20, 40),),
            armor=(("physical", 100, 200),),
            stats=(("to fire damage", 0, NUMBER_MAX),),
            bonuses=True,
        )
    )

    assert bar.item_level_range() == (10, 20)
    assert bar.sockets() == {2}
    assert bar.requirement_ranges() == _strength((30, REQ_MAX))
    assert bar.classes() == {"Embermage"}
    assert bar.damage_ranges() == (("fire", 20, 40),)
    assert bar.armor_ranges() == (("physical", 100, 200),)
    assert bar.stat_rows() == (("to fire damage", 0, NUMBER_MAX),)
    assert bar.bonuses() is True
    assert bar.advanced_active() is True


def test_clearing_the_bar_puts_the_eight_back_too(qapp):
    """The button is on the row, so what it stands for is a facet of this bar.

    A ``Clear filters`` that left a class ticked behind a control the player
    has to open to see would be the one control here that does not do what it
    says.
    """
    bar = _bar()
    bar.adopt(
        Advanced(
            item_low=10,
            sockets=frozenset({1}),
            classes=frozenset({"Outlander"}),
            damage=(("fire", 20, 40),),
            armor=(("ice", 0, 5),),
            stats=(("to fire damage", 0, NUMBER_MAX),),
            bonuses=True,
        )
    )
    assert bar.advanced_active() is True

    bar.reset()

    assert bar.item_level_range() == (0, LEVEL_MAX)
    assert bar.sockets() == set()
    assert bar.requirement_ranges() == REQ_REST
    assert bar.classes() == set()
    assert bar.damage_ranges() == ()
    assert bar.armor_ranges() == ()
    assert bar.stat_rows() == ()
    assert bar.bonuses() is False
    assert bar.advanced_active() is False


def test_the_set_bonus_box_is_a_widening_and_not_a_facet_of_its_own(qapp):
    """Ticking it alone narrows nothing: it says *where* a property row may be
    answered from, so with no row to answer there is nothing for it to do.

    Which is why it is the one field of the eight that the button's ink does
    not read -- a gold button over a search that is showing everything would be
    the same lie from the other side.
    """
    bar = _bar()

    bar.adopt(Advanced(bonuses=True, stats=(("to fire damage", 0, NUMBER_MAX),)))
    assert bar.advanced_active() is True, "the row is what is narrowing"

    bar.adopt(Advanced(bonuses=True))
    assert bar.stat_rows() == ()
    assert bar.advanced_active() is False, "and with no row it says nothing"


def test_writing_a_search_onto_the_bar_is_not_a_change_it_says(qapp):
    """`Search` is one move the window makes, not nine the player did.

    So the controls are written silently and the window emits once, after it
    has moved the rail as well -- see :meth:`app.window.MainWindow.
    _advanced_search`.  A bar that emitted here would have the window apply
    half a search eight times over before it reached the finished one.
    """
    bar = _bar()
    heard = []
    bar.changed.connect(lambda: heard.append(1))

    bar.adopt(Advanced(text="drill", item_low=10, sockets=frozenset({2})))

    assert heard == []
    assert bar.search_text() == "drill"
    assert bar.item_level_range() == (10, LEVEL_MAX)


def test_the_bar_says_what_the_panel_would_open_on(qapp):
    """A draft starts from what is in force, so that ticking the one thing a
    player came for does not throw away what they set a moment ago.

    Which is why this reads the bar rather than the panel: the eight are one
    panel's old draft and the three controls are what the player has done
    since, and :meth:`app.filters.FilterBar.current` has to be the two of them
    together.  The kinds are the odd one out and the window is what fills them:
    they are ticked in the rail, which is not part of the bar.
    """
    bar = _bar()
    bar.adopt(
        Advanced(
            item_low=5,
            item_high=15,
            sockets=frozenset({3}),
            damage=(("fire", 20, 40),),
            stats=(("to fire damage", 0, NUMBER_MAX),),
        )
    )
    bar.search.setText("drill")
    bar.chips["Unique"].setChecked(True)
    bar.low.setValue(20)
    bar.high.setValue(30)

    state = bar.current()

    assert state.text == "drill"
    assert state.tiers == {"Unique"}
    assert (state.low, state.high) == (20, 30)
    assert (state.item_low, state.item_high) == (5, 15)
    assert state.sockets == {3}
    assert state.damage == (("fire", 20, 40),)
    assert state.stats == (("to fire damage", 0, NUMBER_MAX),)
    assert state.places == frozenset(), "the kinds are the rail's to fill in"


def test_the_button_says_when_one_of_the_eight_is_narrowing(qapp):
    """A facet with no control in the row must not be an invisible one.

    The eight have no widget here, so without the ink a collection narrowed by
    a panel nobody is looking at would read exactly like one narrowed by
    nothing -- which is why the button turns the rail's gold (see
    :func:`app.filters._advanced_style`).  Read off the sheet it was given
    rather than off the pixels, because what is being asked is what the button
    was told to wear; the gold itself is drawn like every other word in the
    window, and the rail's own ink test is where that is measured.
    """
    bar = _bar()

    assert GOLD not in bar.advanced.styleSheet()
    assert CHALK in bar.advanced.styleSheet()

    bar.adopt(Advanced(sockets=frozenset({1})))
    assert GOLD in bar.advanced.styleSheet()

    bar.reset()
    bar.adopt(Advanced(damage=(("fire", 20, 40),)))
    assert GOLD in bar.advanced.styleSheet()

    bar.reset()
    bar.adopt(Advanced(stats=(("to fire damage", 0, NUMBER_MAX),)))
    assert GOLD in bar.advanced.styleSheet()
    assert CHALK not in bar.advanced.styleSheet(), "the ink is one or the other"


def test_the_advanced_button_stands_on_the_line_the_rest_of_the_row_is_on(themed):
    """The user's *"more in-line with the other filter options"*, as a height.

    It wore two pixels of vertical padding against the chips' three, which left
    it 21 tall in a row of 23s -- a pixel or two short of every control beside
    it, which is the sort of thing that reads as a mistake long before anyone
    can say what is wrong.  Three is what the pills and the reset are drawn at,
    so three is what it wears; the number is pinned here rather than left to
    the sheet because the whole complaint was about a measurement.

    Themed, and shown, because a widget's height is its layout's answer and not
    its own: an unshown bar has not been laid out and every control in it is
    the same size.
    """
    bar = _bar()
    bar.show()
    bar.resize(1400, 44)
    themed.processEvents()

    chip = next(iter(bar.chips.values()))
    assert chip.height() == 23, "the row's own line moved, so nothing here reads"
    assert bar.advanced.height() == chip.height()
    assert bar.advanced.height() == bar.clear_button.height(), (
        "the button is a different height from the reset at the other end"
    )


def test_the_advanced_button_stands_between_the_search_box_and_the_sort(themed):
    """Where the user asked for it, stated as a position rather than as prose.

    What is behind the button is the rest of what *narrows* a collection, so it
    belongs with the controls that narrow and in front of the sort, which only
    orders what they leave.  The set chip stays outside it, hard against the
    search box, because the two answer one question between them -- and the
    chip is hidden except while a set is being shown, so on an ordinary day the
    button is the control immediately after the box.

    Both readings of the same claim: the order of the row's own layout, which
    is what a later reflow would change, and the x the three controls were
    actually drawn at on a shown bar.
    """
    bar = _bar()
    bar.show()
    bar.resize(1400, 44)
    themed.processEvents()

    row = bar.layout()
    drawn = [row.itemAt(i).widget() for i in range(row.count())]
    drawn = [w for w in drawn if w is not None]

    assert drawn.index(bar.set_chip) < drawn.index(bar.advanced), (
        "the set chip has come away from the search box it belongs to"
    )
    assert drawn.index(bar.search) < drawn.index(bar.advanced) < drawn.index(
        bar.sort_box
    )
    assert bar.search.x() < bar.advanced.x() < bar.sort_box.x()


# --------------------------------------------------------------------------
# The sort, which is in the row but is not a facet of it
# --------------------------------------------------------------------------


def test_the_bar_offers_every_key_the_reference_does(qapp):
    """The reference's own six, in its own order, opening on the ladder.

    *Damage* and *Armor* are the two that read the item's own card rather than
    its row -- see :meth:`app.models.CollectionFilter._carried` -- and they are
    here because the card is now something the collection is asked for.

    The first key is the wall's default, so the default the user asked for is
    the box's own first word rather than something the window has to say.
    """
    bar = _bar()

    assert [bar.sort.itemText(row) for row in range(bar.sort.count())] == list(
        SORT_KEYS
    )
    assert SORT_KEYS[-2:] == ("Damage", "Armor"), "the reference's last two"
    assert bar.sort_key() == "Tier"
    assert bar.sort_backwards() is False
    assert bar.reverse.text() == "↓"


def test_the_arrow_turns_the_key_over_and_says_so(qapp):
    """One switch rather than one per key, like the reference's: the arrow
    says which way the chosen key is read, and clicking it says the other."""
    bar = _bar()
    heard = []
    bar.resorted.connect(lambda: heard.append(1))

    bar.reverse.click()

    assert bar.sort_backwards() is True
    assert bar.reverse.text() == "↑"

    bar.reverse.click()

    assert bar.sort_backwards() is False
    assert bar.reverse.text() == "↓"
    assert len(heard) == 2


def test_the_arrow_beside_the_box_is_a_button_and_not_half_the_row(themed):
    """The user's other two halves of the row's geometry, in one reading.

    *"the sort drop down list can be a tiny bit wider and the arrow button can
    be reduced by half or even a bit more than half as needed"* -- against what
    they were: the box 76 wide and the arrow **80**, because an unstyled
    ``QPushButton`` under Fusion is floored at 80 pixels whatever is written on
    it.  So the arrow wore a single glyph in a button three times the width of
    the drop-down beside it.  The floor is not a number the style will let
    anyone lower, which is why both of these are the sheet's doing rather than
    ``setFixedWidth``'s: claiming the button in the stylesheet takes the floor
    away entirely, because a styled button is measured from its own box model
    -- and it leaves the widget's ``sizeHint()`` in step with its layout, which
    ``test_a_box_is_as_wide_as_what_is_in_it_and_no_wider`` is reading.

    Both measured off a shown bar rather than off the sheet, because a rule is
    not a width: what was asked about was what the player sees.
    """
    bar = _bar()
    bar.show()
    bar.resize(1400, 44)
    themed.processEvents()

    assert (bar.sort.width(), bar.sort.height()) == (88, 21), (
        "the box is not the little wider than its word that was asked for"
    )
    assert (bar.reverse.width(), bar.reverse.height()) == (35, 23), (
        "the arrow is not a small square button beside the box"
    )
    assert bar.reverse.width() < bar.sort.width() / 2, (
        "the arrow is still more than half the width of the box it turns over"
    )
    assert bar.reverse.height() == next(iter(bar.chips.values())).height(), (
        "the arrow is a different height from the controls on its own line"
    )


def test_the_bar_says_so_when_the_order_moves(qapp):
    """A signal of its own rather than the one for the facets: the window
    re-orders the wall and leaves the numbers where they are, because which
    rows are on it has not changed.

    What is turned over is a flag rather than the button's own glyph, so what
    the arrow says and what the window is told are one fact read twice.
    """
    bar = _bar()
    resorted, changed = [], []
    bar.resorted.connect(lambda: resorted.append(1))
    bar.changed.connect(lambda: changed.append(1))

    bar.sort.setCurrentText("Level")
    bar.reverse.click()

    assert len(resorted) == 2
    assert changed == []


def test_clearing_the_bar_leaves_the_order_alone(qapp):
    """Clearing asks to see everything again, which says nothing about what
    order any of it is in.  A player who asked for the newest first and then
    cleared the search box is still asking for the newest first."""
    bar = _bar()
    bar.sort.setCurrentText("Name")
    bar.reverse.click()

    bar.reset()

    assert bar.sort_key() == "Name"
    assert bar.sort_backwards() is True
    assert bar.search_text() == ""
    assert bar.tiers() == set()


# --------------------------------------------------------------------------
# The chip the bar grows when a set is shown
# --------------------------------------------------------------------------


def test_the_chip_is_there_only_while_a_set_is_shown(qapp):
    """An empty chip in the row every other day would be furniture.

    Shown for real rather than merely not hidden, because that is the question
    -- a widget in a layout takes width whether or not anyone can see it, and
    the row is the row it always was until the click that puts one here.
    """
    bar = _bar()
    bar.show()

    assert bar.shown_set() == ""
    assert not bar.set_chip.isVisible()

    bar.show_set("Test Set")
    assert bar.set_chip.isVisible()
    assert bar.set_chip.text() == "Test Set  ✕", "the cross says how it comes off"

    bar.clear_set()
    assert not bar.set_chip.isVisible()
    assert bar.set_chip.text() == ""


def test_showing_a_set_switches_the_rest_of_the_bar_off(qapp):
    """A narrowing inside a narrowing is the way to a wall with two cards on it
    and no explanation, so the click that shows a set takes the other four
    controls back to where the window starts them: whatever the player had
    typed or ticked is asking about a list they have just left.
    """
    bar = _bar()
    bar.search.setText("drill")
    bar.chips["Unique"].setChecked(True)
    bar.low.setValue(20)
    bar.high.setValue(30)

    bar.show_set("Test Set")

    assert bar.shown_set() == "Test Set"
    assert bar.search_text() == ""
    assert bar.tiers() == set()
    assert bar.level_range() == (0, LEVEL_MAX)
    # The chip is written *from* the set rather than read back off the widget,
    # so there is one account of what is being shown and nothing to disagree.
    assert bar.set_chip.text() == "Test Set  ✕"


def test_showing_a_set_is_one_change_rather_than_five(qapp):
    """To the window this is one move: re-apply every facet and re-count, once."""
    bar = _bar()
    bar.search.setText("drill")
    bar.chips["Unique"].setChecked(True)
    heard = []
    bar.changed.connect(lambda: heard.append(1))

    bar.show_set("Test Set")

    assert len(heard) == 1


def test_the_cross_on_the_chip_leaves_the_rest_of_the_bar_alone(qapp):
    """The other way round from showing one, and deliberately.

    The set is the one facet whose control is not a tick -- the chip is a
    statement of what is being shown rather than a box the player chose -- so
    taking it off is taking *it* off: a player who had narrowed the collection
    and then followed a set name back to it gets their own filters again, not
    a cleared bar.
    """
    bar = _bar()
    bar.show_set("Test Set")
    bar.search.setText("Blade")
    bar.chips["Unique"].setChecked(True)
    heard = []
    bar.changed.connect(lambda: heard.append(1))

    bar.clear_set()

    assert bar.shown_set() == ""
    assert bar.set_chip.text() == ""
    assert bar.search_text() == "Blade"
    assert bar.tiers() == {"Unique"}
    assert len(heard) == 1


def test_taking_a_set_off_when_none_is_shown_says_nothing(qapp):
    """The chip's cross is uncountable, and a move that changes nothing is not
    a change: emitting here would be a rebuild of the list per stray click."""
    bar = _bar()
    heard = []
    bar.changed.connect(lambda: heard.append(1))

    bar.clear_set()

    assert heard == []


def test_clearing_the_bar_takes_the_set_off_too(qapp):
    """``Clear filters`` is the whole window's starting state, and the set is
    part of it -- the rail is cleared by the window, which is where the rail
    lives; this is the half that lives in the bar."""
    bar = _bar()
    bar.show_set("Test Set")

    bar.reset()

    assert bar.shown_set() == ""
    assert bar.set_chip.text() == ""


# --------------------------------------------------------------------------
# What the bar is drawn in, which is the one thing it does not say itself
# --------------------------------------------------------------------------


def _contents(box) -> list:
    """What a box is holding, in the order the box draws it."""
    layout = box.layout()
    return [layout.itemAt(i).widget() for i in range(layout.count())]


def test_the_three_boxes_hold_the_controls_they_are_named_for(qapp):
    """A box is a frame around the controls rather than a copy of them.

    The very widgets go in -- the chips, the two number boxes and the sort's
    own pair are the ones the window reads back -- so what is on screen and
    what the bar reports are the same objects, and there is no second set of
    them to keep in step.
    """
    bar = _bar()

    assert [bar.sort_box.title(), bar.rarity_box.title(), bar.level_box.title()] == [
        "Sort",
        "Rarity",
        "Player level",
    ]
    assert bar.sort_box.objectName() == "filterbox"
    assert bar.rarity_box.objectName() == "filterbox"
    assert bar.level_box.objectName() == "filterbox"

    assert _contents(bar.sort_box) == [bar.sort, bar.reverse]
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

    Of the controls in the row only one is worth widening -- the three boxes
    are as wide as the words in them, which is their own test, and the reset at
    the end is a button -- so the width a wide window leaves over belongs in
    the search box rather than as a gap between the controls, which is what the
    user was looking at when they asked for this.  Themed, so that the widths
    the row starts with are the ones the application ships rather than whatever
    font the machine running the tests happens to have.
    """
    bar = _bar()
    bar.show()
    bar.resize(1500, 44)
    themed.processEvents()

    narrow = bar.search.width()
    others = [
        bar.sort_box.width(),
        bar.rarity_box.width(),
        bar.level_box.width(),
        bar.clear_button.width(),
    ]
    assert narrow > bar.search.minimumWidth(), (
        "the box opened on its floor, so nothing about its width can be read here"
    )

    bar.resize(1900, 44)
    themed.processEvents()

    assert bar.search.width() == narrow + 400, (
        "the width the row gained did not all reach the search box"
    )
    assert [
        bar.sort_box.width(),
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
    style's own frame is a different width and the sum proves nothing.  Shown
    for the same kind of reason, and it is worth knowing before this trips
    somebody up: a widget's ``sizeHint()`` is only the sheet's once the style
    has been asked about it, and until the *parent* is polished a freshly named
    child still answers with the bare style's hint -- the sort combo says 80
    before the box it lives in has been asked for its own hint, and 88 after.
    The two sides of this sum come from two levels, so the bar is shown to put
    them in one state; a window shows it too, and reads the same numbers.
    """
    bar = _bar()
    bar.show()
    bar.resize(1400, 44)
    themed.processEvents()

    for box in (bar.sort_box, bar.rarity_box, bar.level_box):
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


def test_the_set_chip_wears_the_set_s_own_purple(themed):
    """The rarity pills' treatment, in the one colour no tier uses.

    A set is not a rarity, so the chip cannot wear a rarity's colour; what it
    wears is the colour the set's own name is drawn in on the cards.  That is
    what makes the chip read as the name the player clicked, standing in the
    row, rather than as a sixth rarity that happens to be purple.

    Read off the pixels for the reason the wash above is: an ``rgba()`` the
    parser does not understand is a declaration that is dropped, and a chip
    that was meant to be filled comes out as the bare ground with an outline.
    """
    bar = _bar()
    bar.show_set("Test Set")
    bar.resize(bar.sizeHint())
    bar.show()
    themed.processEvents()

    chip = bar.set_chip
    assert chip.isVisible()
    image = bar.grab().toImage()
    rect = QRect(chip.mapTo(bar, chip.rect().topLeft()), chip.size())
    middle = rect.center()

    # The bar's own background, which is what the chip's wash is over: the
    # row's left inset, where nothing stands in any state of the bar.
    ground = image.pixelColor(2, middle.y())
    washed = image.pixelColor(rect.left() + 4, middle.y())
    ink = QColor(TIER_INK["set"])
    share = WASH / 255
    wanted = [
        share * ink.red() + (1 - share) * ground.red(),
        share * ink.green() + (1 - share) * ground.green(),
        share * ink.blue() + (1 - share) * ground.blue(),
    ]
    assert [washed.red(), washed.green(), washed.blue()] == pytest.approx(
        wanted, abs=2
    ), "the chip is not the set's colour over the ground"
    assert washed.blue() > washed.red() > washed.green(), "which is a purple"

    # And the word on it is the window's own ink, as it is on every control the
    # player reads -- the name, and the cross that says how it comes off.
    assert any(
        image.pixelColor(x, y).name() == CHALK
        for y in range(middle.y() - 4, middle.y() + 5)
        for x in range(rect.left() + 3, rect.right() - 2)
    ), "the chip's word is not in the ink"


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
