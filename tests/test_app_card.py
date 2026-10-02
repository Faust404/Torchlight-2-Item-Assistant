"""Tests for the card the collection draws.

:mod:`tl2stash.card` is the model and ``tests/test_card.py`` is its business --
what an item says.  This is the drawing: which colour a tier is inked with,
where the rules fall, what the corner says, and what happens to an item whose
icon is in no sheet.

No pixels are asserted.  Qt resolves fonts through the platform, and under the
offscreen platform it resolves none -- every glyph measures as a box -- so a
width or a rendered image would be a test of this machine's font setup.  What
is asserted instead is what the widgets say (``text()``, ``objectName()``) and
the colours they were built with, which is the part this module decides.

What a card is put *in* -- the tile, its footer and the grid of them -- is
``tests/test_app_tiles.py``.
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

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.card import (  # noqa: E402
    HEAD,
    MUTED,
    TIER_INK,
    Hairline,
    IconCache,
    IconTile,
    ItemCard,
    emphasis,
    mark,
)
from tl2stash.card import (  # noqa: E402
    ADDED,
    AFFIX,
    ARMOR,
    DAMAGE,
    Block,
    Card,
    Rung,
)

from test_dat import needs_game, real_game  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session; Qt allows no more."""
    app = QApplication.instance() or QApplication([])
    yield app


def lifted(number: str) -> str:
    """A number as :func:`mark` writes one: the header colour, at 600."""
    return f'<span style="color:{HEAD};font-weight:600">{number}</span>'


def card(**kwargs) -> Card:
    """A card with the fields a test is not about filled in."""
    fields = {
        "name": "Bashdrill",
        "tier": "unique",
        "tier_word": "Unique",
        "type_name": "Fist",
        "set_name": None,
        "icon": None,
        "level": 45,
        "sockets": 1,
        "blocks": (),
        "gems": (),
        "socketed": (),
        "set_ladder": (),
        "flavor": None,
    }
    fields.update(kwargs)
    return Card(**fields)


def texts(drawn: ItemCard, name: str) -> list[str]:
    return [
        label.text()
        for label in drawn.findChildren(QLabel)
        if label.objectName() == name
    ]


# --------------------------------------------------------------------------
# The emphasis rule
# --------------------------------------------------------------------------


def test_a_number_lifts_out_of_the_line_it_sits_in():
    """The site's own rule, and the reason a card is scannable: what a reader
    looks for in a stat line is the number, and it is already in the string."""
    assert mark("Charge rate increased by 5%") == (
        f"Charge rate increased by {lifted('5%')}"
    )
    assert mark("Silence for 1 sec.") == f"Silence for {lifted('1')} sec."


def test_a_sign_a_percent_and_a_decimal_comma_travel_with_their_number():
    """Splitting ``+8`` from its ``%`` would print one value in two colours,
    and the comma is a decimal point in the languages that write one."""
    assert lifted("+8%") in mark("Charge rate increased by +8%")
    assert lifted("-2%") in mark("Damage Taken is reduced by -2%")
    assert lifted("1,5%") in mark("1,5% of nothing")
    assert lifted("+11.259") in mark("+11.259 Physical Damage")


def test_each_number_in_a_range_lifts_on_its_own():
    """Which is what the site's regex does with ``52-74``: the sign belongs to
    the second number, not to the hyphen that joins them."""
    assert mark("Physical Damage 52-74") == (
        f"Physical Damage {lifted('52')}{lifted('-74')}"
    )


def test_a_line_with_no_number_in_it_is_left_exactly_as_it_was():
    assert mark("Identify Item") == "Identify Item"
    assert "&lt;" in mark("a < b"), "the line is escaped before it is marked up"


def test_a_whole_line_is_written_in_the_colour_it_is_drawn_in():
    """Qt's stylesheet language does not reach inside rich text, so a line's
    own colour is written into the markup rather than onto the label."""
    assert emphasis("Silence for 1 sec.", "#123456").startswith(
        '<span style="color:#123456">'
    )


# --------------------------------------------------------------------------
# The headline
# --------------------------------------------------------------------------


def test_the_name_and_the_tile_are_inked_with_the_item_s_tier(qapp):
    drawn = ItemCard(card(tier="unique"))

    name = drawn.findChild(QLabel, "an")
    assert name.text() == "Bashdrill"
    assert TIER_INK["unique"] in name.styleSheet()

    assert drawn.findChild(IconTile).ink.name() == TIER_INK["unique"]


def test_a_tier_that_is_not_a_key_is_inked_as_no_tier(qapp):
    """Drawing a card is a lookup and never a check -- which is what keeps a
    modded item, whose tier nothing in the data files can name, from being a
    crash rather than a card."""
    drawn = ItemCard(card(tier="something-new"))

    assert drawn.findChild(IconTile).ink.name() == TIER_INK["none"]


def test_the_kind_line_names_the_tier_in_its_colour_and_the_kind_in_grey(qapp):
    """``Unique Fist``: the tier word carries what the type does not, so it is
    the one word in the line painted in the tier's colour."""
    drawn = ItemCard(card(tier="unique", tier_word="Unique", type_name="Fist"))
    (kind,) = texts(drawn, "dtype")

    assert "Unique" in kind and "Fist" in kind
    assert TIER_INK["unique"] in kind


def test_an_item_with_no_kind_and_no_tier_has_no_kind_line(qapp):
    drawn = ItemCard(card(tier_word="", type_name=""))
    assert texts(drawn, "dtype") == []


def test_a_set_piece_says_so_in_the_one_word_its_tier_cannot(qapp):
    """``Unique Set Boots``: the tier says the rarity and the membership rides
    beside it, which is the site's own line and the only place a card names a
    set at all."""
    drawn = ItemCard(
        card(tier="unique", tier_word="Unique", type_name="Boots", set_name="Berserker")
    )
    (kind,) = texts(drawn, "dtype")

    # The membership is not what the item *is*, so it does not get the tier's
    # colour: the ink opens and closes around the rarity word and nothing else.
    inner = kind.removeprefix(f'<span style="color:{MUTED}">').removesuffix("</span>")
    assert inner == f'<span style="color:{TIER_INK["unique"]}">Unique</span> Set Boots'


def test_a_green_item_is_inked_green(qapp):
    """The tier the references could not tell us about, drawn.

    A magic item's name and tile take the same green the game gives it, which
    is the same green an affix line is written in.
    """
    drawn = ItemCard(card(tier="magic", tier_word="Magic", type_name="1H Mace"))

    name = drawn.findChild(QLabel, "an")
    assert TIER_INK["magic"] in name.styleSheet()
    assert drawn.findChild(IconTile).ink.name() == TIER_INK["magic"]
    (kind,) = texts(drawn, "dtype")
    assert TIER_INK["magic"] in kind


def test_the_corner_says_what_the_item_asks_and_what_it_holds(qapp):
    drawn = ItemCard(card(level=45, sockets=1))
    assert texts(drawn, "pill") == ["Level 45", "1 Socket"]

    assert texts(ItemCard(card(level=0, sockets=3)), "pill") == ["3 Sockets"]
    assert texts(ItemCard(card(level=7, sockets=0)), "pill") == ["Level 7"]
    assert texts(ItemCard(card(level=0, sockets=0)), "pill") == []


# --------------------------------------------------------------------------
# The icon
# --------------------------------------------------------------------------


def test_an_item_with_no_icon_draws_the_type_s_initial(qapp):
    """The site's own fallback for the 2% of items whose icon is in no sheet
    -- and for every item on a machine with no game installed at all."""
    tile = ItemCard(card(type_name="Fist")).findChild(IconTile)
    assert tile.icon is None
    assert tile.letter == "F"

    # Not even a type to take a letter from: the site's question mark.
    assert ItemCard(card(type_name="")).findChild(IconTile).letter == "?"


# --------------------------------------------------------------------------
# The body
# --------------------------------------------------------------------------


def test_the_first_section_has_no_rule_above_it_and_the_rest_have_one(qapp):
    """The site's rule, and the reason it is a rule about *sections*: an empty
    one takes its rule with it rather than leaving a stray line on the card."""
    assert ItemCard(card(blocks=())).findChildren(Hairline) == []

    one = ItemCard(card(blocks=(Block(AFFIX, ("Silence for 1 sec.",)),)))
    assert one.findChildren(Hairline) == []

    two = ItemCard(
        card(
            blocks=(
                Block(DAMAGE, ("Physical Damage 52-74",)),
                Block(AFFIX, ("Silence for 1 sec.",)),
            )
        )
    )
    assert len(two.findChildren(Hairline)) == 1


def test_a_weapon_s_own_damage_and_what_was_added_to_it_are_one_section(qapp):
    """Three blocks in the model, one run of lines on the card: the game draws
    them together and so does the site, so a rule between them would be this
    window's own invention."""
    drawn = ItemCard(
        card(
            blocks=(
                Block(DAMAGE, ("Physical Damage 52-74",)),
                Block(ADDED, ("+13 Physical Damage",)),
                Block(ARMOR, ()),
            )
        )
    )
    assert drawn.findChildren(Hairline) == []


def test_an_affix_line_is_green_and_a_damage_line_is_not(qapp):
    """Green means "this item has it", which is the game's own meaning for it,
    and it is why the two blocks do not look alike."""
    drawn = ItemCard(
        card(
            blocks=(
                Block(DAMAGE, ("Physical Damage 52-74",)),
                Block(AFFIX, ("Silence for 1 sec.",)),
            )
        )
    )
    body = [label.text() for label in drawn.findChildren(QLabel) if label.objectName() == ""]

    assert any("#7cc24a" in text for text in body), "no affix line was written green"
    assert any("#c9c2b6" in text for text in body), "no damage line was written plain"


def test_the_flavour_line_is_drawn_and_takes_no_rule(qapp):
    """"It is a remark about the item rather than one of its stats" -- the
    site's own note, and the reason it sits under the last rule."""
    drawn = ItemCard(
        card(
            blocks=(Block(AFFIX, ("Silence for 1 sec.",)),),
            flavor="If your enemies don't get the point, drill it into their heads.",
        )
    )
    assert texts(drawn, "flav") == [
        "If your enemies don't get the point, drill it into their heads."
    ]
    assert drawn.findChildren(Hairline) == []


def test_a_gem_is_drawn_under_the_item_that_holds_it(qapp):
    gem = card(
        name="Flawless Ruby",
        tier="magic",
        tier_word="Magic",
        type_name="Gem",
        level=0,
        sockets=0,
        blocks=(Block(AFFIX, ("+5 Fire Damage",)),),
    )
    drawn = ItemCard(
        card(
            sockets=1,
            gems=(gem,),
            blocks=(Block(DAMAGE, ("Physical Damage 52-74",)),),
        )
    )

    assert texts(drawn, "gem") == ["Flawless Ruby"]
    # Ruled off from the item's own stats above it, like any other section.
    assert len(drawn.findChildren(Hairline)) == 1


def test_what_a_socket_added_is_drawn_under_its_own_heading(qapp):
    """The heading is this window's word, and it is what tells the two numbers
    apart: an Ice Ember reads ``+120 Ice Armor`` on the gorget it sits in and
    ``+58`` on its own, and a player deciding whether to empty the socket
    needs to know which line the item would keep.

    The socket's lines come under the heading, the gem's own card under them,
    and the item's own stats above both -- so the section is ruled off from
    the item once and the gem takes no second rule of its own.
    """
    gem = card(
        name="Ice Ember",
        tier="magic",
        tier_word="Magic",
        type_name="Socketable",
        level=50,
        sockets=0,
        blocks=(Block(AFFIX, ("+58 Ice Armor",)),),
    )
    drawn = ItemCard(
        card(
            sockets=1,
            gems=(gem,),
            blocks=(Block(AFFIX, ("15 Health stolen on hit",)),),
            socketed=("+120 Ice Armor",),
        )
    )

    assert texts(drawn, "socketed") == ["Socketed"]
    assert texts(drawn, "gem") == ["Ice Ember"]

    body = [label.text() for label in drawn.findChildren(QLabel) if label.objectName() == ""]
    # The number is lifted into its own colour by ``mark``, so the line is
    # checked for its words and for the green the whole line is inked with.
    assert any("Ice Armor" in text and "120" in text for text in body), body
    assert any("#7cc24a" in text and "Ice Armor" in text for text in body), body
    assert any("Health stolen on hit" in text for text in body), body
    assert len(drawn.findChildren(Hairline)) == 1


def test_an_item_with_nothing_in_its_sockets_draws_no_socketed_heading(qapp):
    """A socketed item with an empty socket is the common case -- 47 of the 48
    socketed rows this machine holds -- and it has nothing to show for it: no
    heading, no section, no line."""
    drawn = ItemCard(card(sockets=3, blocks=(Block(AFFIX, ("+5 Strength",)),)))

    assert texts(drawn, "socketed") == []
    assert drawn.findChildren(Hairline) == []


def test_a_set_s_ladder_is_drawn_under_the_item_s_own_stats(qapp):
    """The set's name, then each rung as ``(2) Set`` over its lines.

    The name is drawn in the set purple, which is the one colour no tier uses
    -- a set is not a rarity, and the card already says the rarity in its own
    colour in the kind line.  The ladder is a section like any other, so it
    takes a rule above it and none between its own lines.
    """
    drawn = ItemCard(
        card(
            set_name="Test Set",
            blocks=(Block(AFFIX, ("+5 Strength",)),),
            set_ladder=(
                Rung(2, ("+6 Set damage",)),
                Rung(3, ("+5 Set burn", "2.5% chance to cast Test Proc on kill")),
            ),
        )
    )

    title = drawn.findChild(QLabel, "setname")
    assert title.text() == "Test Set"
    assert TIER_INK["set"] in title.styleSheet()
    assert texts(drawn, "rung") == ["(2) Set", "(3) Set"]

    # The rung's lines are affix lines, drawn the way the item's own are: the
    # number in a rung's line is lifted into its own colour, so the line is
    # checked for its words and for the green the whole line is inked with.
    body = [label.text() for label in drawn.findChildren(QLabel) if label.objectName() == ""]
    for words in ("Set damage", "Set burn", "chance to cast Test Proc"):
        assert any(words in text for text in body), words
    assert any("#7cc24a" in text and "Set burn" in text for text in body)
    # One rule for the whole ladder, not one per rung.
    assert len(drawn.findChildren(Hairline)) == 1


def test_an_item_in_no_set_draws_no_ladder_at_all(qapp):
    """An item in a set the data does not describe -- a mod's -- is the same
    empty tuple as one in no set, and draws the same nothing."""
    drawn = ItemCard(card(blocks=(Block(AFFIX, ("+5 Strength",)),)))

    assert texts(drawn, "setname") == []
    assert texts(drawn, "rung") == []
    assert drawn.findChildren(Hairline) == []


# --------------------------------------------------------------------------
# The real archive
# --------------------------------------------------------------------------


@needs_game
def test_a_real_item_s_icon_is_cut_out_of_a_real_sheet(qapp, real_game):
    """The whole chain, and the only test that can hold it: a name to a
    rectangle, the rectangle to the sheet it sits on, and the sheet's bytes
    decoded and cropped.  A tile drawn from it is 62x62 because that is what
    the game's own imageset declares."""
    icons = IconCache(real_game.install)

    cut = icons.icon("icon_weapon_fist14")
    assert cut is not None
    assert (cut.width(), cut.height()) == (62, 62)
    assert icons.icon("icon_weapon_fist14") is cut, "the second cut was not cached"

    # A name no sheet declares, and no name at all: both are the placeholder.
    assert icons.icon("gem_fish_eye") is None
    assert icons.icon(None) is None
