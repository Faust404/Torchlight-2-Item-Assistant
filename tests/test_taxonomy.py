"""Tests for the kind taxonomy: the game's words, grouped.

The lists in ``tl2stash/taxonomy.py`` are a claim about what the game writes,
and a claim like that goes stale without saying so: the day a patch adds a kind
of thing, nothing here goes red unless something re-reads the archive.  So the
first test does, and it is the one that matters -- the rest pin the rules for
the kinds that are not in the archive at all, which is every modded item.

The sweep needs the game installed and skips without it.  Everything below the
sweep is pure and runs anywhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash.dat import VAR_UNITTYPE  # noqa: E402
from tl2stash.gamedata import archive_path, read_unit_type  # noqa: E402
from tl2stash.pak import PakIndex  # noqa: E402
from tl2stash.taxonomy import OTHER, TYPE_GROUPS, group_of  # noqa: E402

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

    # And the sweep is reading the same tree the tool does: if it were not,
    # UNIQUECANNON would still be split into a tier and no kind.
    assert "Uniquecannon" not in kinds
    assert "Cannon" in kinds


@needs_game
def test_the_two_spellings_of_one_kind_land_together(real_game):
    """The game writes ``Sword`` in 21 files and ``1H Sword`` in 18.

    They are the same kind of thing and the rail must not show them as two
    entries a row apart, which is what the group and subgroup are for.
    """
    assert group_of("Sword") == group_of("1H Sword") == ("Weapons", "One-Handed")
    assert group_of("Axe") == group_of("1H Axe") == ("Weapons", "One-Handed")
    assert group_of("Mace") == group_of("1H Mace") == ("Weapons", "One-Handed")

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


def test_an_item_with_no_kind_word_is_misc_and_not_other():
    """``QUESTITEM`` is a third of the archive and has no kind at all.

    The game never needed to say what a quest object *is*, so the token is a
    tier and nothing else.  Filing it under ``Other`` would both hide 150 real
    items there and cost the group its one meaning -- an item from a mod.
    """
    assert read_unit_type("QUESTITEM") == ("Quest", "")
    assert group_of("") == ("Misc", None)


def test_a_kind_is_matched_whatever_case_it_is_written_in():
    """A mod writes its own ``UNITTYPE`` and may not shout like the game."""
    assert group_of("boots") == group_of("BOOTS") == group_of("Boots")


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
