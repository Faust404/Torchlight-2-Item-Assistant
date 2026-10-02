"""Tests for the one thing on a card the game's own files do not hold.

An augment block is not game data: the unlock is a triggerable the game
resolves at runtime, and nothing in the archive points at it.  So these tests
come in two halves -- the reader, which is fed files written by hand, and the
card, which is fed the real archive with a two-line table hung on it.

The item the card half is about is real, because it has to be: the table is
keyed by the unit name the *item file* states, and the only way to a name is
the guid in a save file.  Grimbone Wand is ``wand_u02b``, and the block below
is the one the reference database publishes for it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash.augments import (  # noqa: E402
    ITEMS_JSON_VAR,
    find_items_json,
    load,
    read,
)
from tl2stash.card import AUGMENT_LOCKED, Augment, lines  # noqa: E402
from tl2stash.gamedata import GameData, find_install  # noqa: E402
from tl2stash.item import AddedDamage  # noqa: E402
from tl2stash.tooltip import (  # noqa: E402
    _added_damage_lines,
    _augment_blocks,
    build,
)

from test_tooltip import item, word  # noqa: E402

_INSTALL = find_install()

needs_game = pytest.mark.skipif(
    _INSTALL is None, reason="Torchlight II is not installed on this machine"
)

#: Grimbone Wand, whose guid the save file writes as eight bytes and its own
#: file writes as the decimal string ``9801002217302452269``.
WANDB = 9801002217302452269

#: Rat Killer, a task whose whole reward is one flat damage line -- which is
#: what makes it the item to test the *finished* case with, because a save
#: file's own record of a flat damage line is a thing a test can write.
RATKILLER = 8856327082397544077

#: A great mace with no task of its own, for the other half of the question.
PLAIN_GUID = 792130739766287015

#: The block the reference database publishes for the wand, and the one the
#: tests hang on the archive.
BLOCK = Augment(
    "Kill 50 Ezrohir to Upgrade",
    (
        "6% chance to cast Acid Rain from target",
        "15% chance to Stun target for 2 sec.",
    ),
)

#: And the rat's, whose single reward is ``+2 Physical Damage``.
RAT_BLOCK = Augment("Kill 5 Ratlins to Upgrade", ("+2 Physical Damage",))


@pytest.fixture(scope="module")
def game():
    """The real game's files, with two items' task tables beside them."""
    return GameData.load(
        _INSTALL, augments={"wand_u02b": (BLOCK,), "ratkiller": (RAT_BLOCK,)}
    )


def reference(path: Path, records: list) -> Path:
    """A reference database's item file, written where a test can point at."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Finding the file
# --------------------------------------------------------------------------


def test_the_environment_variable_is_looked_at_first(tmp_path, monkeypatch):
    """It is the answer that is always right when it is set, because the one
    who set it is the one who knows where the file is."""
    mine = reference(tmp_path / "items.json", [])
    monkeypatch.setenv(ITEMS_JSON_VAR, str(mine))

    assert find_items_json() == mine
    # And an install pointed at does not overrule it.
    assert find_items_json(tmp_path) == mine


def test_a_variable_that_points_at_nothing_is_not_a_fallback(tmp_path, monkeypatch):
    """It is a statement about where the file is, so a wrong one is answered
    with nothing rather than with a guess at what was meant."""
    monkeypatch.setenv(ITEMS_JSON_VAR, str(tmp_path / "gone.json"))
    assert find_items_json() is None


def test_the_install_is_the_last_place_looked_at(tmp_path, monkeypatch):
    """For a copy of the reference sitting beside a copy of the game.

    The sibling checkout is taken away for the duration of the test, because
    on a machine that has one -- which is every machine this was developed on
    -- the second answer is the one that comes back and the third is never
    reached.
    """
    monkeypatch.delenv(ITEMS_JSON_VAR, raising=False)
    # The sibling is found by walking up from this module's own file, so the
    # file is what has to move: two directories up, with nothing above it.
    monkeypatch.setattr(
        "tl2stash.augments.__file__",
        str(tmp_path / "here" / "there" / "augments.py"),
    )

    elsewhere = tmp_path / "elsewhere"
    assert find_items_json(elsewhere) is None
    beside = reference(elsewhere / "out" / "items.json", [])
    assert find_items_json(elsewhere) == beside


# --------------------------------------------------------------------------
# Reading it
# --------------------------------------------------------------------------


def test_only_the_two_fields_that_are_wanted_are_read(tmp_path):
    """``id`` and ``aug``, out of a file whose 6,173 records carry forty fields
    apiece.  The rest belongs to the reference and stays there."""
    path = reference(
        tmp_path / "items.json",
        [
            {
                "id": "hammer_u02",
                "n": "The Hammer",
                "dps": 300,
                "aug": [
                    {
                        "task": "Kill 20 Goblins to Upgrade",
                        "fx": ["+15% to Fire Damage"],
                    }
                ],
            },
            {"id": "sword_u01", "n": "A Sword With No Task"},
            {"id": "wand_u02b", "n": "Grimbone Wand", "aug": []},
        ],
    )

    assert read(path) == {
        "hammer_u02": (
            Augment("Kill 20 Goblins to Upgrade", ("+15% to Fire Damage",)),
        )
    }


def test_an_item_that_chains_three_tasks_keeps_them_in_order(tmp_path):
    """One developer's test sword does, which is why the field is a tuple:
    what the game shows is three blocks, one under the other."""
    path = reference(
        tmp_path / "items.json",
        [
            {
                "id": "zzz_testsword_augment_many",
                "aug": [
                    {"task": "Kill 10 to Upgrade", "fx": ["+1% to All Damage"]},
                    {"task": "Kill 20 to Upgrade", "fx": ["+2% to All Damage"]},
                    {"task": "Kill 30 to Upgrade", "fx": ["+3% to All Damage"]},
                ],
            }
        ],
    )

    blocks = read(path)["zzz_testsword_augment_many"]
    assert [block.task for block in blocks] == [
        "Kill 10 to Upgrade",
        "Kill 20 to Upgrade",
        "Kill 30 to Upgrade",
    ]


def test_the_key_is_a_unit_name_and_not_the_way_it_is_spelled(tmp_path):
    """The archive's own spelling of a name is not fixed, and the field this
    is matched against is lower-cased anyway."""
    path = reference(
        tmp_path / "items.json",
        [{"id": "HAMMER_U02", "aug": [{"task": "T", "fx": ["F"]}]}],
    )
    assert list(read(path)) == ["hammer_u02"]


def test_a_record_that_is_not_an_item_is_passed_over(tmp_path):
    """The file is the reference's, and one that has grown a summary row, or a
    block of a shape this does not know, is not a reason to fail to draw."""
    path = reference(
        tmp_path / "items.json",
        [
            "not a record",
            {"n": "no id at all", "aug": [{"task": "T", "fx": ["F"]}]},
            {"id": "hammer_u02", "aug": ["not a block", {"task": "T", "fx": ["F"]}]},
        ],
    )
    assert read(path) == {"hammer_u02": (Augment("T", ("F",)),)}


def test_a_file_that_is_not_a_list_of_items_is_a_failure(tmp_path):
    """``read`` is the caller that says so and ``load`` is the one that does
    not care, which is the whole of the difference between them -- a test
    should be told that the shape changed."""
    path = reference(tmp_path / "items.json", [])
    path.write_text('{"items": []}', encoding="utf-8")
    with pytest.raises(ValueError):
        read(path)


def test_no_file_is_an_empty_table_and_not_an_error(tmp_path, monkeypatch):
    """The reference database is not the game.  A machine without one is a
    machine this tool has always run on."""
    monkeypatch.setenv(ITEMS_JSON_VAR, str(tmp_path / "gone.json"))
    assert load() == {}

    # And one that is there but no longer readable as the reference's.
    broken = tmp_path / "broken.json"
    broken.write_text("{oh no", encoding="utf-8")
    monkeypatch.setenv(ITEMS_JSON_VAR, str(broken))
    assert load() == {}


@needs_game
def test_the_project_looks_for_the_reference_beside_itself():
    """Not a requirement of the suite -- the file may well not be there.  But
    the sibling checkout is where it is found on the machine this was built
    on, and a resolution rule that quietly stopped working would show up only
    as every augment block disappearing."""
    found = find_items_json(_INSTALL)
    if found is None:
        pytest.skip("no reference database on this machine")
    assert found.name == "items.json"
    assert found.parent.name == "out"


# --------------------------------------------------------------------------
# What the item will become
# --------------------------------------------------------------------------


@needs_game
def test_an_item_with_a_task_is_told_what_it_would_grant(game):
    """Keyed on the item file's own name, which the guid is the way to."""
    assert game.augment_for(item(guid=WANDB)) == (BLOCK,)


@needs_game
def test_nothing_else_has_a_task(game):
    """Six thousand and ninety-nine of the game's items carry none, and an
    item the files do not know cannot be looked up at all."""
    assert game.augment_for(item(guid=0)) == ()
    assert game.augment_for(item(guid=0xDEADBEEF)) == ()
    # A real weapon whose file is found and whose name the table has not got.
    assert game.augment_for(item(guid=PLAIN_GUID)) == ()


@needs_game
def test_the_block_is_drawn_under_the_item_s_own_lines(game):
    """The order the reference draws it in: the stats, then the task, then
    what finishing it grants."""
    card = build(item("Grimbone Wand", guid=WANDB), game)
    said = lines(card)
    start = said.index(BLOCK.task)
    block = [BLOCK.task, AUGMENT_LOCKED, *BLOCK.gains]

    assert card.augments == (BLOCK,)
    assert said[start : start + len(block)] == block
    # And nothing above it is a reward: what stands before the task is the
    # item's own lines, which is where they stop.
    own = [line for line in card.blocks for line in line.lines]
    assert own and all(gain not in own for gain in BLOCK.gains)


@needs_game
def test_a_finished_task_is_no_block_at_all(game):
    """The game stops drawing the rewards as locked the moment they are the
    item's own, and so does this.

    The save file does not record that a task was *finished* -- it records the
    item's effect list with the rewards in it -- so the test is whether the
    item already says every line the task grants.  Rat Killer's whole reward
    is one flat damage line, and a flat damage line is a thing a save file
    really does hold, so this is that test end to end.
    """
    done = item(
        "Rat Killer", guid=RATKILLER, added_damages=[AddedDamage(0, word(2.0), 0, 0x00)]
    )
    properties = _added_damage_lines(done)

    assert properties == list(RAT_BLOCK.gains)
    assert _augment_blocks(done, game, properties) == ()
    card = build(done, game)
    assert card.augments == ()
    assert RAT_BLOCK.task not in lines(card)
    # And the reward is among the item's own properties, where the game puts
    # it: the block is gone because the line moved, not because it vanished.
    assert list(card.blocks[-1].lines) == properties


@needs_game
def test_a_task_half_done_is_not_done(game):
    """Every line or none: an item given one of the two has not finished the
    task, and half a block would be a worse lie than the whole of one."""
    it = item(guid=WANDB)
    assert _augment_blocks(it, game, [BLOCK.gains[0]]) == (BLOCK,)
    assert _augment_blocks(it, game, ["+25 Physical Damage"]) == (BLOCK,)
    assert _augment_blocks(it, game, []) == (BLOCK,)
    # The rat's one reward, on the wrong weapon: a line is not a reward until
    # it is this item's line.
    assert _augment_blocks(it, game, list(RAT_BLOCK.gains)) == (BLOCK,)


@needs_game
def test_the_two_spellings_of_a_line_are_the_same_line(game):
    """The two sides are the same sentence written by two different parts of
    the game -- the reference scraped one out of a tooltip and the archive
    hands over the other -- so case, spacing and the full stop are not meant
    to match."""
    twice = [
        "   15%  chance to STUN target for 2 sec",
        "6% chance to cast Acid Rain from target.",
    ]
    assert _augment_blocks(item(guid=WANDB), game, twice) == ()


@needs_game
def test_an_item_with_no_task_of_its_own_is_drawn_none(game):
    """And neither is a card built with no game data at all, which is every
    card on a machine with no game installed."""
    assert build(item("Test Blade", level=7, guid=PLAIN_GUID), game).augments == ()
    assert build(item("Test Blade", level=7, max_damage=72), None).augments == ()
