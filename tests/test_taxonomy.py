"""Tests for the kind taxonomy: the game's kinds, in the reference's words.

The lists in ``tl2stash/taxonomy.py`` are a claim about what the game writes and
what the reference calls it, and a claim like that goes stale without saying so:
the day a patch adds a kind of thing, nothing here goes red unless something
re-reads the archive.  So the first test does, and it is the one that matters --
the rest pin the rules for the kinds that are not in the archive at all, which
is every modded item.

The sweep needs the game installed and skips without it.  Everything below the
sweep is pure and runs anywhere.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash.augments import find_items_json  # noqa: E402
from tl2stash.dat import VAR_UNITTYPE  # noqa: E402
from tl2stash.gamedata import archive_path, read_unit_type  # noqa: E402
from tl2stash.pak import PakIndex  # noqa: E402
from tl2stash.taxonomy import (  # noqa: E402
    KIND_PLACES,
    OTHER,
    TYPE_GROUPS,
    canonical_kind,
    group_of,
)

from test_dat import needs_game, real_game  # noqa: E402
from test_gamedata import _inherited_text  # noqa: E402


# --------------------------------------------------------------------------
# The lists, against the game's own files
# --------------------------------------------------------------------------


def _every_kind(game) -> dict[str, int]:
    """Every kind the archive's item files resolve to, and how many each.

    The file list comes from the archive's own manifest rather than from the
    tool's index, so a file the loader skipped still turns up here.  The chain
    walk is :func:`tl2stash.gamedata._inherited`'s job and is pinned by
    Bashdrill; this only needs the ``UNITTYPE`` an item ends up with.
    """
    man = archive_path(game.install)
    kinds: dict[str, int] = {}
    for entry in PakIndex.read(man).entries:
        if not entry.startswith("MEDIA/UNITS/ITEMS/") or not entry.endswith(".DAT"):
            continue
        stated = game._item_files.get(entry.upper())
        if stated is None:
            continue
        stated_type = _inherited_text(game, stated.root, VAR_UNITTYPE)
        if not stated_type:
            continue
        _, kind = read_unit_type(stated_type)
        kinds[kind] = kinds.get(kind, 0) + 1
    return kinds


@needs_game
def test_every_kind_the_game_has_is_in_one_of_the_named_groups(real_game):
    """The drift alarm, and the reason the lists were read rather than guessed.

    A kind that reaches ``Other`` is a kind the game has and the rail cannot
    name, and the answer is to add it to :data:`TYPE_GROUPS` -- so this failing
    is not a bug, it is a patch to the game.
    """
    kinds = _every_kind(real_game)

    assert len(kinds) > 40, "the sweep stopped finding kinds"
    unplaced = sorted(k for k in kinds if group_of(k)[0] == OTHER)
    assert not unplaced, f"the game has kinds nothing here knows: {unplaced}"

    # And every one of the game's words lands on a kind the *reference's* list
    # has, in the reference's own spelling.  This is the cross-check the lists
    # were read out of: a word that missed would be a leaf the reference
    # database has never heard of, and an item filed under it would be filed
    # under a name the player cannot look up.
    listed = {kind for _, _, kinds in TYPE_GROUPS for kind in kinds}
    strays = sorted({canonical_kind(kind) for kind in kinds} - listed)
    assert not strays, f"the game writes kinds the reference has not got: {strays}"
    assert len(listed) == 43, "the reference's list is 43 types"

    # The four embers are real kinds in the archive and they are one kind here:
    # the reference database files all of them, embers and gems together, under
    # Socketable, and the two spellings come to the same 178 files it counts.
    embers = ("Blood Ember", "Chaos Ember", "Iron Ember", "Void Ember")
    for ember in embers:
        assert ember in kinds, f"{ember} is no longer written by any item file"
        assert group_of(ember) == group_of("Socketable") == ("Misc", None)
        assert canonical_kind(ember) == "Socketable"
    socketables = kinds.get("Socketable", 0) + sum(kinds[e] for e in embers)
    assert socketables == 178, "the socketable files no longer number what they did"

    # The potion family, the same kind of claim: the game writes six words
    # where the reference database has two, and all six are real in this
    # archive -- 56 potion files and 7 scroll files, counted by the sweep.
    family = {
        "Potion": 32,
        "Healthpotion": 8,
        "Manapotion": 8,
        "Rejuvpotion": 8,
        "Scroll": 6,
        "Identify Scroll": 1,
    }
    for word, count in family.items():
        assert kinds.get(word) == count, f"{word} no longer numbers {count} files"
    assert sum(family.values()) == 63, "the potion and scroll files moved"

    # And the sweep is reading the same tree the tool does: if it were not,
    # UNIQUECANNON would still be split into a tier and no kind.
    assert "Uniquecannon" not in kinds
    assert "Cannon" in kinds


@needs_game
def test_the_game_s_own_word_for_a_kind_is_the_reference_s_type(real_game):
    """The cross-check itself: the archive's items, against the reference.

    Every typed item file joins to a record in the reference database's own
    ``out/items.json`` -- keyed on the path both of them know it by -- and the
    kind this tool makes of the item's ``UNITTYPE`` is the type that record
    publishes.  Which is what makes ``PANTS`` a Leggings and ``RIFLE`` a
    Shotgonne here rather than a claim in a comment.

    The ``BASE_*`` templates join to nothing and are not items, so they are
    passed over; the count of the rest is asserted, because a join that quietly
    stopped matching would otherwise look like a clean run.

    The fish are the one exception, and they are the reference's rather than
    this tool's: see :data:`THE_FISH`.
    """
    src = find_items_json(real_game.install)
    if src is None:
        pytest.skip("the reference database is not on this machine")

    reference = {
        record["p"].upper(): record["t"]
        for record in json.loads(src.read_text(encoding="utf-8"))
        if record.get("p") and record.get("t")
    }

    joined = 0
    wrong: dict[str, tuple[str, str]] = {}
    for entry in PakIndex.read(archive_path(real_game.install)).entries:
        if not entry.startswith("MEDIA/UNITS/ITEMS/") or not entry.endswith(".DAT"):
            continue
        if "/BASE" in entry.upper() or entry.upper().endswith("ITEMS/BASE.DAT"):
            continue
        stated = real_game._item_files.get(entry.upper())
        if stated is None:
            continue
        unit_type = _inherited_text(real_game, stated.root, VAR_UNITTYPE)
        if not unit_type:
            continue
        theirs = reference.get(entry.upper())
        if theirs is None:
            continue
        joined += 1
        mine = canonical_kind(read_unit_type(unit_type)[1])
        if mine != theirs:
            wrong[entry.upper()] = (mine, theirs)

    assert joined > 6000, "the join stopped finding the archive's items"

    # And they disagree about the fish and nothing else -- which is the exact
    # claim, so a sixteenth is a failure and so is the fifteenth stopping.
    assert set(wrong) == THE_FISH, (
        "the tool and the reference disagree about something other than the "
        "fish:\n  "
        + "\n  ".join(f"{p}: {mine!r} against {theirs!r}"
                      for p, (mine, theirs) in sorted(wrong.items())
                      if p not in THE_FISH)
    )
    assert set(wrong.values()) == {("Potion", "Fish")}, wrong


#: The fifteen items the reference types ``Fish`` and this tool types ``Potion``.
#:
#: All fifteen carry ``UNITTYPE: MAGIC POTION``, exactly as a potion does, and
#: nothing in the game's files tells the two apart: every variable any of the
#: hundred-odd potion and fish files states, they state with the same shape of
#: value.  The reference resolves them one at a time out of TIDBI -- the
#: community's extracted tooltip table, where the game's own type line for
#: ``fish_caves_01`` reads ``Rare Fish`` and its ``ut`` column reads
#: ``MAGIC POTION``, the two side by side.  That table is not in the shipped
#: game and this tool does not read it, so here they stay potions; it is the
#: reference's own note in ``classify_type`` that ``POTION`` is *"the one token
#: that is genuinely ambiguous"*.
#:
#: The list is exact rather than a rule, and it is what the test above holds
#: the join to: a sixteenth fish, or one of these fifteen changing hands, means
#: the archive or the reference has moved and wants reading again.
THE_FISH = frozenset({
    "MEDIA/UNITS/ITEMS/FISH/FISH_GOLDFIND.DAT",
    "MEDIA/UNITS/ITEMS/POTIONS/FISH_CAVES_01.DAT",
    "MEDIA/UNITS/ITEMS/POTIONS/FISH_CAVES_02.DAT",
    "MEDIA/UNITS/ITEMS/POTIONS/FISH_CRYPTS_01.DAT",
    "MEDIA/UNITS/ITEMS/POTIONS/FISH_CRYPTS_02.DAT",
    "MEDIA/UNITS/ITEMS/POTIONS/FISH_FORTRESS_01.DAT",
    "MEDIA/UNITS/ITEMS/POTIONS/FISH_FORTRESS_02.DAT",
    "MEDIA/UNITS/ITEMS/POTIONS/FISH_LAVA_01.DAT",
    "MEDIA/UNITS/ITEMS/POTIONS/FISH_LAVA_02.DAT",
    "MEDIA/UNITS/ITEMS/POTIONS/FISH_MINES_01.DAT",
    "MEDIA/UNITS/ITEMS/POTIONS/FISH_MINES_02.DAT",
    "MEDIA/UNITS/ITEMS/POTIONS/FISH_PALACE_01.DAT",
    "MEDIA/UNITS/ITEMS/POTIONS/FISH_PALACE_02.DAT",
    "MEDIA/UNITS/ITEMS/POTIONS/FISH_RUINS_01.DAT",
    "MEDIA/UNITS/ITEMS/POTIONS/FISH_RUINS_02.DAT",
})


@needs_game
def test_the_two_spellings_of_one_kind_are_one_kind(real_game):
    """The game writes ``Sword`` in 21 files and ``1H Sword`` in 111.

    They are the same kind of thing and the rail must not show them as two
    entries a row apart -- so one of the two is *the* word and the other is an
    alias of it.  Which one is the word is the reference's answer rather than
    the game's: its list says ``Sword``, and its own records file both tokens
    under it.
    """
    assert canonical_kind("1H Sword") == canonical_kind("Sword") == "Sword"
    assert canonical_kind("1H Axe") == canonical_kind("Axe") == "Axe"
    assert canonical_kind("1H Mace") == canonical_kind("Mace") == "Mace"
    assert group_of("Sword") == group_of("1H Sword") == ("Weapons", "One-Handed")

    # Both spellings are real, so both are in the archive the sweep reads.
    kinds = _every_kind(real_game)
    for kind in ("Sword", "1H Sword", "Axe", "1H Axe", "Mace", "1H Mace"):
        assert kind in kinds, f"{kind} is no longer written by any item file"


# --------------------------------------------------------------------------
# The rules, without the game
# --------------------------------------------------------------------------


def test_a_kind_the_game_does_not_have_goes_to_other():
    """What a modded item is: not ``Misc``, which claims the tool knows."""
    assert group_of("Nothing Like This") == (OTHER, None)
    assert group_of("Shoulderpad") == (OTHER, None)


def test_an_item_with_no_kind_word_is_a_quest_item():
    """``QUESTITEM`` is a third of the archive and has no kind of its own.

    The game never needed to say what a quest object *is*, so the token is a
    tier and nothing else -- and the reference database calls such a thing a
    ``Quest Item``, which is what the empty word reads as.  Filing it under
    ``Other`` would both hide 150 real items there and cost the group its one
    meaning, an item from a mod.
    """
    assert read_unit_type("QUESTITEM") == ("Quest", "")
    assert canonical_kind("") == "Quest Item"
    assert group_of("") == ("Misc", None)


def test_a_kind_is_matched_whatever_case_it_is_written_in():
    """A mod writes its own ``UNITTYPE`` and may not shout like the game."""
    assert group_of("boots") == group_of("BOOTS") == group_of("Boots")
    assert canonical_kind("chaos ember") == canonical_kind("CHAOS EMBER")


def test_the_embers_are_socketables():
    """The archive writes four kinds the reference database has never heard of.

    ``BLOOD/CHAOS/IRON/VOID EMBER`` are how the game spells an ember's kind;
    a gem's file says ``SOCKETABLE``, and the reference files all 178 of them
    -- embers and gems alike -- as Socketable.  An ember that kept its own
    kind would be four leaves in the rail holding eight items each, beside the
    one leaf holding the 146 it belongs with.

    The ember's *name* still says which ember it is; this is its kind, which is
    the word the card's type line and the rail both read.
    """
    for ember in ("Blood Ember", "Chaos Ember", "Iron Ember", "Void Ember"):
        assert canonical_kind(ember) == "Socketable"
        assert group_of(ember) == ("Misc", None)


def test_the_potion_family_is_one_kind_each():
    """Six of the game's kind words are two of the reference's.

    ``HEALTHPOTION``, ``MANAPOTION`` and ``REJUVPOTION`` are three kinds of
    eight files each where the reference database has the one ``Potion``, and
    ``IDENTIFY SCROLL`` is one file where it has the one ``Scroll``.  A player
    browsing for a potion means all four words, and the reference's own records
    carry both spellings of each: ``ut: "MANAPOTION"`` with ``t: "Potion"``.
    """
    for word in ("Healthpotion", "Manapotion", "Rejuvpotion"):
        assert canonical_kind(word) == "Potion"
        assert group_of(word) == ("Misc", None)
    assert canonical_kind("Identify Scroll") == "Scroll"
    assert group_of("Identify Scroll") == ("Misc", None)

    # The plain words still mean themselves, and a kind that merely *sounds*
    # like one is untouched.
    assert canonical_kind("Potion") == "Potion"
    assert canonical_kind("Scroll") == "Scroll"
    assert canonical_kind("Healthpotionish") == "Healthpotionish"


def test_misc_holds_one_potion_kind_and_one_scroll_kind():
    """The four dead leaves are out of the list, and the two live ones stay.

    ``Healthpotion``, ``Manapotion``, ``Rejuvpotion`` and ``Identify Scroll``
    are absent from :data:`TYPE_GROUPS` for the same reason the embers are --
    :data:`KIND_ALIASES` is where they are made one with ``Potion`` and
    ``Scroll``.  Left in the list they would be four leaves the archive can no
    longer fill, beside the two that hold everything.
    """
    misc = next(kinds for group, _, kinds in TYPE_GROUPS if group == "Misc")
    assert [k for k in misc if "potion" in k.lower()] == ["Potion"]
    assert [k for k in misc if "scroll" in k.lower()] == ["Scroll"]

    # The list is the reference's own, in its order, which is the order the
    # rail draws Misc in: ``Quest Item`` and ``Tag`` are the names this tool
    # says for a quest object and a pet tag, and ``Location Item`` for the
    # level items.
    assert misc == (
        "Spell",
        "Socketable",
        "Quest Item",
        "Tag",
        "Map",
        "Fish",
        "Potion",
        "Location Item",
        "Scroll",
        "Gold",
        "Dynamite",
    )


def test_the_lists_are_the_reference_s_own():
    """The names the reference has and the game does not, and the other way
    round: the game's words are aliases here, and no longer kinds.

    A kind is a box in the panel and a leaf in the rail, and the point of
    taking the reference's vocabulary is that the two vocabularies cannot both
    be drawn -- so the game's word for a kind is never a leaf of its own.
    """
    listed = {kind for _, _, kinds in TYPE_GROUPS for kind in kinds}

    # The names this change is about, none of which any ``UNITTYPE`` writes.
    assert {
        "Claw",
        "Greataxe",
        "Greathammer",
        "Greatsword",
        "Leggings",
        "Location Item",
        "Quest Item",
        "Shotgonne",
        "Tag",
        "Armor",
    } <= listed

    # The game's words for them are not kinds at all, and every one of them
    # canonicalises to something that is.  ``2H Sword``, ``2H Mace``, ``Fist``
    # and ``Rifle`` are absent from this list on purpose: they are the four in
    # the block below, which are the game's words *and* the reference's names.
    for word in ("1H Sword", "1H Axe", "1H Mace", "2H Axe", "Fist Fire",
                 "Fist Electric", "Polararm Fire", "Polararm Ele", "Pants",
                 "Stud", "Item", ""):
        assert word not in listed, f"{word} is still a kind of its own"
        assert canonical_kind(word) in listed, f"{word} canonicalises to nothing"

    # ``Fist``, ``2H Sword``, ``2H Mace`` and ``Rifle`` are the other half of
    # that: the reference keeps them for a kind the corpus never carries, and
    # they are the same four names -- so the box is drawn and the game's items
    # for it are filed under the other spelling.
    assert {"Fist", "2H Sword", "2H Mace", "Rifle"} <= listed
    assert canonical_kind("Fist") == "Claw"
    assert canonical_kind("Rifle") == "Shotgonne"


def test_canonical_kind_leaves_every_other_kind_alone():
    """It renames the words in its table, and the guard is that it renames
    nothing else -- a rule that ate a word it only half matched would take a
    kind out of the rail silently."""
    assert canonical_kind("Socketable") == "Socketable"
    assert canonical_kind("Boots") == "Boots"
    assert canonical_kind("Shoulder Armor") == "Shoulder Armor"
    assert canonical_kind("Claw") == "Claw"
    assert canonical_kind("Ember") == "Ember", "only the four spelled-out words"
    assert canonical_kind("Chaos Emberish") == "Chaos Emberish"
    assert canonical_kind("Pantsuit") == "Pantsuit", "only the whole word"
    assert canonical_kind("Fists") == "Fists"


def test_no_kind_is_in_two_groups_at_once():
    """The map is built from the lists, so a duplicate would silently win."""
    seen: dict[str, tuple[str, str | None]] = {}
    for group, subgroup, kinds in TYPE_GROUPS:
        assert kinds, f"{group}/{subgroup} has no kinds in it"
        for kind in kinds:
            assert kind not in seen, f"{kind} is in {seen.get(kind)} and {group}"
            seen[kind] = (group, subgroup)

    # The lookup table is built from the same lists, and this is the one place
    # that would notice if it stopped being.
    for kind, where in seen.items():
        assert group_of(kind) == where, kind


def test_the_weapons_are_split_and_the_armour_is_not():
    """The rail's shape: a subgroup means two things are not alternatives."""
    subgroups = {(group, subgroup) for group, subgroup, _ in TYPE_GROUPS}
    assert ("Weapons", "One-Handed") in subgroups
    assert ("Weapons", "Two-Handed") in subgroups
    assert ("Weapons", "Off-Hand") in subgroups
    assert ("Armor", None) in subgroups
    # A weapon held in the off hand is still a weapon, which is the reference's
    # placement and not the obvious one.
    assert group_of("Shield") == ("Weapons", "Off-Hand")


def test_every_listed_kind_is_a_place_and_the_empty_kind_is_not():
    """What the advanced search's Type grid draws from: the whole taxonomy as
    places, so that it can offer a kind the collection has none of.

    A place and not a word, because that is what the rail holds and what the
    filter matches on -- and the empty kind is deliberately *not* in here, so a
    grid built from this list never draws a box for a kind that is not one.
    """
    assert KIND_PLACES == {
        (group, subgroup, kind)
        for group, subgroup, kinds in TYPE_GROUPS
        for kind in kinds
    }
    assert len(KIND_PLACES) == sum(len(kinds) for _, _, kinds in TYPE_GROUPS)
    assert not any(kind == "" for _, _, kind in KIND_PLACES)
    assert ("Weapons", "One-Handed", "Sword") in KIND_PLACES
    assert ("Other", None, "") not in KIND_PLACES, "the empty kind is no kind"

    # Every one of them is a kind :func:`group_of` agrees with, which is what
    # makes the grid's boxes and the rail's leaves the same leaves.
    for place in KIND_PLACES:
        assert group_of(place[2]) == (place[0], place[1]), place
