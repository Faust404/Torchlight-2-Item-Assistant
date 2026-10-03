"""Tests for the catalogue: what a list row knows about its item.

The catalogue exists for one reason -- the two lists are rebuilt on every poll,
and the three things a row shows beside its columns cost a data-file walk and an
icon crop each.  So the tests are mostly about the two ways that can go wrong:
an answer that is not true of the item, and an answer that is not remembered.

Two shapes have to be read the same way.  A selected item is a dataclass and a
stored one is a ``sqlite3.Row``, which answers to a key and never to an
attribute -- reading ``row.prefix`` raises rather than returning nothing -- so
the first tests pin both, against a real ``sqlite3.Row`` rather than a stand-in
for one.

No pixels are asserted anywhere else in this suite and none are here either,
with one exception that earns it: whether a 62-pixel picture is *scaled* into a
list row's tile or *clipped* by it is not a matter of taste -- the game's art
reaches every edge of its crop, so clipping shows the middle of the sword and
none of its ends.  That is checked by drawing a ringed square and looking at
what survived.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Before the first PySide6 import, like tests/test_app.py.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 is not installed")

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.card import IconCache, paint_tile  # noqa: E402
from app.catalog import ICON_SIZE, Catalog, Facts  # noqa: E402
from app.models import (  # noqa: E402
    CLASSES,
    COLLECTION_COLUMNS,
    FINGERPRINT_ROLE,
    GATE_ROLE,
    LEVEL_ROLE,
    PLACE_ROLE,
    SET_ROLE,
    TIER_ROLE,
    fill_collection,
    new_model,
)
from tl2stash.gamedata import GameData, Requirements  # noqa: E402
from tl2stash.taxonomy import OTHER  # noqa: E402

from test_dat import needs_game, real_game  # noqa: E402
from test_gamedata import _bashdrill, install as synthetic_install  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session; Qt allows no more."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def synthetic_game(tmp_path):
    """The install ``tests/test_gamedata.py`` builds, loaded.

    No augment table, for the reason that file's own fixture gives: it is not
    game data at all, and a machine with a checkout of the reference beside
    this one must not change what a test sees.  The classes are left to be
    read out of the archive, which is where they come from.
    """
    return GameData.load(synthetic_install(tmp_path), augments={})


# --------------------------------------------------------------------------
# The two shapes a fact arrives in
# --------------------------------------------------------------------------


def _a_row(**columns) -> sqlite3.Row:
    """A real ``sqlite3.Row``, because that is what the registry hands over.

    Written as a query rather than as a mapping on purpose: the whole reason
    :class:`Facts` exists is that a row is not an object, and a dict standing in
    for one would test the code that works and not the code that raised.
    """
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    names = ", ".join(columns)
    placeholders = ", ".join("?" * len(columns))
    connection.execute(f"CREATE TABLE items ({names})")
    connection.execute(f"INSERT INTO items VALUES ({placeholders})", tuple(columns.values()))
    return connection.execute("SELECT * FROM items").fetchone()


class _AnItem:
    """The attribute shape: a parsed item, as far as this module reads one."""

    def __init__(
        self,
        guid: int,
        prefix: str = "",
        suffix: str = "",
        num_enchants: int = 0,
        num_sockets: int = 0,
        level: int = 0,
    ):
        self.guid = guid
        self.prefix = prefix
        self.suffix = suffix
        self.num_enchants = num_enchants
        self.num_sockets = num_sockets
        self.level = level


def test_facts_read_an_item_that_answers_to_attributes():
    facts = Facts.of(_AnItem(0xABC, "Demolishing [ITEM]", "", 2, 3))

    assert facts == Facts(
        guid=0xABC, prefix="Demolishing [ITEM]", suffix="", num_enchants=2, num_sockets=3
    )


def test_facts_read_a_registry_row_which_answers_to_keys_only():
    """The row the registry actually returns -- hex guid text and all.

    A 64-bit guid does not fit SQLite's signed integer, so the registry stores
    it as uppercase hex; the data files are indexed by the number, so the text
    has to be turned back into one here.
    """
    row = _a_row(
        guid="0DEADBEEF1234567",
        prefix=None,
        suffix="of the Bear",
        num_enchants=0,
        num_sockets=2,
    )

    facts = Facts.of(row)

    assert facts.guid == 0x0DEADBEEF1234567
    # NULL is not missing: an item with no prefix has the empty string, so that
    # the tier rule can ask for one without every caller guarding it.
    assert facts.prefix == ""
    assert facts.suffix == "of the Bear"
    assert facts.num_enchants == 0
    assert facts.num_sockets == 2


def test_a_row_with_nothing_filled_in_is_still_an_item_with_no_magic():
    facts = Facts.of(
        _a_row(guid="ABCD", prefix=None, suffix=None, num_enchants=None, num_sockets=None)
    )

    assert (facts.prefix, facts.suffix, facts.num_enchants) == ("", "", 0)
    # Nothing in the column at all is none of them, which is what a socket-less
    # item is: the number a socket filter reads is zero and not unknown.
    assert facts.num_sockets == 0


# --------------------------------------------------------------------------
# What the catalogue answers
# --------------------------------------------------------------------------


def test_with_no_game_every_item_is_an_item_with_no_rarity(qapp):
    """The honest answer on a machine without the game, and not an error.

    No icon either: a column of identical placeholder tiles is not information,
    and a list of plain names is what that machine should show.  The gate goes
    the same way -- ``None``, which is *unanswered* rather than an item the
    game gates on nothing -- and the list falls back to the item's own level.
    """
    catalog = Catalog(None)
    entry = catalog.entry("anything", _AnItem(1))

    assert entry.tier == "none"
    assert entry.tier_word == ""
    assert entry.kind == ""
    assert (entry.group, entry.subgroup) == (OTHER, None)
    assert entry.icon is None
    assert entry.gate is None
    assert entry.set_name is None
    # And nothing for the advanced search to read but the socket count, which
    # is the item's own and not the game's: a machine with no game has no kind,
    # no requirement and no class to filter by, and says so with the empties
    # rather than by being a special case in the filter.
    assert (entry.sockets, entry.stats, entry.cls) == (0, (), None)


def test_the_answer_for_an_item_is_remembered_and_not_computed_twice(qapp):
    """The whole point of the object: a poll costs lookups, not a data walk."""
    catalog = Catalog(None)
    item = _AnItem(1)

    first = catalog.entry("print", item)
    assert catalog.entry("print", item) is first

    # Two items that share a fingerprint are the same item -- it is a hash of
    # the bytes, so the second argument is not even consulted.
    assert catalog.entry("print", _AnItem(999)) is first


@needs_game
def test_a_mapping_and_an_object_for_the_same_item_agree(qapp, real_game):
    """A green item is green in both lists, which is the whole reason for this.

    The registry row carries the three fields the tier rule reads, so the list
    can arrive at the answer the card does without parsing a single blob.
    """
    guid = next(iter(real_game._item_guids))
    catalog = Catalog(real_game, IconCache(real_game.install))

    from_item = catalog.entry("a", _AnItem(guid, prefix="Demolishing [ITEM]"))
    from_row = catalog.entry("b", _a_row(guid=guid, prefix="Demolishing [ITEM]",
                                         suffix=None, num_enchants=0, num_sockets=0))

    assert from_item == from_row


@needs_game
def test_a_row_carries_what_the_advanced_search_reads(qapp, real_game):
    """The three facets the bar has no control for.

    All three come down lookups the row is already making -- the item's own
    bytes and the tables built from the archive at load -- and they are *on the
    entry* rather than worked out per row, because the panel reads one of them
    for every row of every poll while it is set.  The sockets are the one that
    is the instance's and not the kind's: how many a sword can *hold* is in its
    data file, and how many this one has is on the item.
    """
    catalog = Catalog(real_game, IconCache(real_game.install))

    # An item that asks for an attribute.  One that asks for none would agree
    # with an empty tuple whether or not it was ever asked, which is the shape
    # of test that passes on the wrong code.
    for guid in real_game._item_guids:
        requires = real_game.requirements_for(_AnItem(guid))
        if requires is not None and requires.stats:
            break
    else:  # pragma: no cover -- the archive always has one
        pytest.skip("no item in this install states an attribute requirement")

    entry = catalog.entry("a", _AnItem(guid, num_sockets=2))

    assert entry.sockets == 2
    assert entry.stats == requires.stats
    # The class is read off the item's own file, like everything else on the
    # row -- and most items name none, so the item this reads is deliberately
    # one the archive *does* restrict: an entry that never asked would answer
    # ``None``, which is the same answer 5,494 of the 6,262 files give and so
    # the one shape of item that cannot tell a reading from a default.
    restricted = next(
        (
            guid
            for guid in real_game._item_guids
            if real_game.class_for(_AnItem(guid)) is not None
        ),
        None,
    )
    if restricted is None:  # pragma: no cover -- the archive always has one
        pytest.skip("no item in this install names a class")
    assert catalog.entry("b", _AnItem(restricted)).cls in CLASSES


@needs_game
def test_the_art_the_game_ships_lands_whole_in_a_list_row(qapp, real_game):
    """An item of the real game resolves a tier, a kind and a picture.

    The picture is the interesting one: the game's art is 62 pixels square
    whatever tile it lands in, and a list row's tile is smaller than that.
    """
    guid = next(
        guid for guid in real_game._item_guids
        if (real_game.appearance_for(_AnItem(guid)) or None) is not None
        and real_game.appearance_for(_AnItem(guid)).icon
    )
    catalog = Catalog(real_game, IconCache(real_game.install))
    entry = catalog.entry("a", _AnItem(guid))

    assert entry.icon is not None
    drawn = entry.icon.pixmap(ICON_SIZE, ICON_SIZE).toImage()
    assert not drawn.isNull()
    # Art rather than a flat fill: the placeholder tile is a colour and a
    # letter, and the game's icons are shaded pictures.
    assert len({drawn.pixel(x, y) for x in range(ICON_SIZE) for y in range(ICON_SIZE)}) > 100


@needs_game
def test_an_item_the_game_does_not_have_is_other_with_a_placeholder(real_game, qapp):
    """A modded item, or one whose data file has gone.

    It keeps a tile where the others have pictures, because a hole in an
    illustrated column reads as a missing row rather than as an unknown item.
    """
    missing = next(n for n in range(1, 1 << 20) if n not in real_game._item_guids)
    catalog = Catalog(real_game, IconCache(real_game.install))

    entry = catalog.entry("a", _AnItem(missing))

    assert (entry.tier, entry.tier_word, entry.kind) == ("none", "", "")
    assert (entry.group, entry.subgroup) == (OTHER, None)
    assert entry.icon is not None
    # And nothing to gate on: the files have never heard of it, which is not
    # the same answer as a file that says it is gated on nothing.
    assert entry.gate is None


# --------------------------------------------------------------------------
# The gate, which is not the item's level
# --------------------------------------------------------------------------


class _OneAnswer:
    """A game that answers the gate question and nothing else.

    :meth:`Catalog._read` asks three questions of the game -- what the item asks
    of a character, what it looks like, and which class it is for -- and a
    catalogue built on this gets the last two answered with nothing.  That is a
    real combination (an item the game has a gate for and no *look* for), and it
    is what keeps the three questions from being read as one.
    """

    def __init__(self, requires: Requirements):
        self._requires = requires

    def requirements_for(self, item):
        return self._requires

    def appearance_for(self, item):
        return None

    def class_for(self, item):
        """``None``, which is the answer for an item no class is restricted to
        -- most of the game's items, and the whole of an archive that names no
        class at all.  See
        :meth:`~tl2stash.gamedata.GameData.class_for` for what the real one
        reads, and its ``has_classes`` for the other question."""
        return None


def test_a_gate_of_nothing_is_zero_and_not_the_same_as_no_answer(qapp):
    """A potion is gated on nothing; a mod's item is gated on *unknown*.

    The game's files answer for the first and what they answer is that any
    character may use it, so the catalogue has a zero.  ``None`` means nobody
    was asked -- and merging the two would either hide every potion from every
    level range or show an unknown item through all of them.

    The number that must *not* appear is the item's own level: it is here, at
    45, and a catalogue that confused the two would answer with it.
    """
    catalog = Catalog(_OneAnswer(Requirements(level=0, socketing=False, stats=())))

    assert catalog.entry("a", _AnItem(1)).gate == 0
    assert Catalog(None).entry("b", _AnItem(1)).gate is None


@needs_game
def test_the_gate_is_the_player_level_the_files_ask_for(qapp, real_game):
    """Bashdrill: level 45 on the item, gated until 51.

    The two numbers the tool holds for one item, and the whole reason the list
    keeps them in separate roles -- the column is the level the item *is*, and
    the filter is over what it asks of the character.  Both are in the tool's
    hands here, so this is one assertion away from reading the wrong one.
    """
    bashdrill = _bashdrill()
    assert bashdrill.level == 45, "the item stopped being the one this is about"

    entry = Catalog(real_game, IconCache(real_game.install)).entry("a", bashdrill)

    assert entry.gate == 51


# --------------------------------------------------------------------------
# The tile: scaled into the row, not clipped by it
# --------------------------------------------------------------------------


def test_a_picture_bigger_than_the_tile_is_scaled_into_it_whole(qapp):
    """The regression that a screenshot would never catch.

    A ringed square, 62 pixels, drawn into a tile less than half that.  If the
    tile centres it and lets its own clip take the edges, the ring is outside
    the window and the tile is solid blue -- which is what the sword's tip and
    pommel would be.  Scaled, the ring is still at the tile's edge.
    """
    art = QPixmap(62, 62)
    art.fill(QColor("red"))
    ring = 10
    inner = QPainter(art)
    inner.fillRect(QRect(ring, ring, 62 - 2 * ring, 62 - 2 * ring), QColor("blue"))
    inner.end()

    tile = QPixmap(ICON_SIZE, ICON_SIZE)
    tile.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tile)
    paint_tile(painter, ICON_SIZE, ICON_SIZE, QColor("#ef6100"), art, "?")
    painter.end()

    # Sampled down the middle of the ring rather than at a fixed row: the ring
    # is ``ring`` of the picture's 62 pixels, so it is proportionally narrower
    # in a smaller tile, and a fixed row falls off it -- and off a fixed row,
    # the antialiased seam between red and blue is what gets measured.
    band = ICON_SIZE * ring // 62 // 2
    seen = tile.toImage()
    # Well inside the rounded corner and well inside the ring: red means the
    # edge of the picture reached the edge of the tile.
    assert seen.pixelColor(ICON_SIZE // 2, band).name() == "#ff0000"
    assert seen.pixelColor(ICON_SIZE // 2, ICON_SIZE - 1 - band).name() == "#ff0000"


# --------------------------------------------------------------------------
# What the model does with it
# --------------------------------------------------------------------------


def test_a_filled_row_shows_its_tier_without_changing_its_text(qapp):
    """The icon rides in the decoration and the colour in the foreground.

    ``DisplayRole`` is what the search box matches on, so it has to stay
    exactly the item's name -- the filters read their own roles instead.
    """
    row = _a_row(
        fingerprint="0" * 40,
        name="Demolishing War Mallet",
        level=12,
        num_sockets=0,
        prefix="Demolishing [ITEM]",
        suffix=None,
        num_enchants=0,
        guid=0,
    )
    catalog = Catalog(None)
    model = new_model(COLLECTION_COLUMNS)

    fill_collection(model, [row], catalog)
    cell = model.item(0, 0)

    assert cell.text() == "Demolishing War Mallet"
    assert cell.data(FINGERPRINT_ROLE) == "0" * 40
    assert cell.data(TIER_ROLE) == ""
    assert cell.data(PLACE_ROLE) == (OTHER, None, "")
    assert cell.data(LEVEL_ROLE) == 12
    # An item of no set carries the empty string rather than nothing, which is
    # what the set filter compares against when no set is being shown.
    assert cell.data(SET_ROLE) == ""
    assert cell.foreground().color().name() == "#8a8a8a"


def test_a_set_piece_s_row_carries_the_name_the_card_draws(qapp, synthetic_game):
    """The one facet of a row that is not read off a data file by the *model*.

    The set is on the item's appearance, resolved once per item by the
    catalogue, and the row keeps the same string the card's ladder is titled
    with -- which is what makes a click on that title a filter over these rows
    and not a translation between two spellings of one set.
    """
    row = _a_row(
        fingerprint="1" * 40,
        name="Test Set Blade",
        level=20,
        num_sockets=0,
        prefix="",
        suffix="",
        num_enchants=0,
        guid=f"{0x7007:016X}",
    )
    model = new_model(COLLECTION_COLUMNS)

    fill_collection(model, [row], Catalog(synthetic_game))
    assert model.item(0, 0).data(SET_ROLE) == "Test Set"

    # And the item beside it, which belongs to no set, is not one of its rows.
    plain = dict(row, fingerprint="2" * 40, name="Test Unique", guid=f"{0x7002:016X}")
    fill_collection(model, [_a_row(**plain)], Catalog(synthetic_game))
    assert model.item(0, 0).data(SET_ROLE) == ""


def test_a_row_keeps_the_gate_beside_the_item_s_own_level(qapp):
    """Two roles, because they are two numbers and only one of them is a level.

    The column shows the item's level and the level range filters on the gate,
    so a row that let one role stand in for the other would filter on the
    wrong number -- and the three cases below are the three answers a gate can
    have: one the game gives, none at all, and a zero for an item the game
    gates on nothing, which every range must show.
    """
    row = _a_row(
        fingerprint="0" * 40,
        name="Bashdrill",
        level=45,
        num_sockets=1,
        prefix="",
        suffix="",
        num_enchants=0,
        guid=0,
    )
    model = new_model(COLLECTION_COLUMNS)

    # No game: nobody was asked, so the range falls back to the item's level
    # and the two roles agree.
    fill_collection(model, [row], Catalog(None))
    cell = model.item(0, 0)
    assert (cell.data(LEVEL_ROLE), cell.data(GATE_ROLE)) == (45, 45)

    # The game answered, and with a number that is not the item's level.
    catalog = Catalog(_OneAnswer(Requirements(51, False, ())))
    fill_collection(model, [row], catalog)
    cell = model.item(0, 0)
    assert (cell.data(LEVEL_ROLE), cell.data(GATE_ROLE)) == (45, 51)

    # And a gate of nothing stays a zero rather than falling back: this is the
    # one value the filter has to be able to tell from "no answer".
    catalog = Catalog(_OneAnswer(Requirements(0, False, ())))
    fill_collection(model, [row], catalog)
    assert model.item(0, 0).data(GATE_ROLE) == 0


def test_a_socketable_s_row_gate_is_read_at_the_row_s_own_level(qapp, synthetic_game):
    """The gate a row shows is the copy's, not the item's file.

    A socketable is one file for every level it drops at, so the file's own
    level is the *lowest* version's -- the level-15 Eye of Kidrik's gate of 7
    on a level-45 one, which is the number the player saw.  The row holds the
    copy's level, and the facts carry it to the one gate that is read at it:
    Test Gem's file says 20 and this copy says 45, so the socketing curve
    answers 37 where the file's 12 used to stand.
    """
    row = _a_row(
        fingerprint="0" * 40,
        name="Test Gem",
        level=45,
        num_sockets=0,
        prefix="",
        suffix="",
        num_enchants=0,
        guid=f"{0x7003:016X}",
    )
    model = new_model(COLLECTION_COLUMNS)

    fill_collection(model, [row], Catalog(synthetic_game))

    cell = model.item(0, 0)
    assert (cell.data(LEVEL_ROLE), cell.data(GATE_ROLE)) == (45, 37)
