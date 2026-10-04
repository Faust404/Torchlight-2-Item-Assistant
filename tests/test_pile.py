"""Tests for the arithmetic that turns a pile of fish into the game's stacks.

The rule under everything here is that a share may re-count a stack **down,
never up**: the tool gives away fish it holds and cannot conjure one, so a
plan's sizes are bounded by the stacks they come from.  Pure arithmetic, so it
is pinned pure -- no registry, no save file, no Qt -- and the invariants at the
bottom are held over every shape a pile can have rather than the handful of
examples above them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash.pile import Share, shares  # noqa: E402


def _sizes(plan: list[Share]) -> list[int]:
    return [share.size for share in plan]


# --------------------------------------------------------------------------
# Transfer all
# --------------------------------------------------------------------------


def test_a_stack_bigger_than_a_slot_comes_out_in_slot_sized_pieces():
    """The case the cap exists for: a modded game's 20-fish stack.

    Twenty fish are four slots of five wherever they came from, and a share of
    a re-counted stack is never *whole* -- the bytes have to be patched, so
    the registry re-keys it.
    """
    plan = shares([("a", 20)], limit=5)
    assert _sizes(plan) == [5, 5, 5, 5]
    assert [share.source for share in plan] == ["a"] * 4
    assert not any(share.whole for share in plan)


def test_the_last_share_carries_the_remainder():
    """Twelve fish are 5, 5 and 2 -- not 5, 5 and a dropped 2.

    The remainder is a share of its own and goes back as one, which is a slot
    the player sees half full rather than four fish lost.
    """
    assert _sizes(shares([("a", 12)], limit=5)) == [5, 5, 2]


def test_a_stack_that_fits_goes_back_whole():
    """The cheap case, and the common one on a vanilla save.

    A stack of five or fewer needs no patch at all: its bytes go back as they
    are held, so its identity is untouched and the registry has nothing to
    re-key.
    """
    plan = shares([("a", 3)], limit=5)
    assert plan == [Share("a", 3, whole=True)]

    exact = shares([("a", 5)], limit=5)
    assert exact == [Share("a", 5, whole=True)], "a full slot is still whole"


def test_every_held_stack_goes_in_the_order_it_was_held():
    """Nothing is sorted here: file order is the player's own stacks, and
    Transfer all is the button that gives all of them back."""
    plan = shares([("a", 5), ("b", 3), ("c", 1)], limit=5)
    assert plan == [
        Share("a", 5, whole=True),
        Share("b", 3, whole=True),
        Share("c", 1, whole=True),
    ]


# --------------------------------------------------------------------------
# Transfer a Stack
# --------------------------------------------------------------------------


def test_one_stack_is_one_slot_and_never_a_whole_pile():
    """Two buttons' worth of fish is two presses, which is the point of it.

    A pile of a 3-stack and a 1-stack gives the 3: one press, one slot, in the
    game's words rather than the tool's.
    """
    plan = shares([("a", 3), ("b", 1)], one_stack=True, limit=5)
    assert plan == [Share("a", 3, whole=True)]


def test_one_stack_out_of_a_bigger_one_is_cut_down_to_a_slot():
    """And the stack it was cut from is the caller's to re-key: what comes
    back here is the share, not the remainder."""
    plan = shares([("a", 20)], one_stack=True, limit=5)
    assert plan == [Share("a", 5, whole=False)]


def test_one_stack_takes_the_largest_held():
    """Largest first, so the button frees the most room in one press -- and a
    tie goes to the stack that came first, which is file order."""
    plan = shares([("a", 2), ("b", 5), ("c", 5)], one_stack=True, limit=5)
    assert plan == [Share("b", 5, whole=True)]


# --------------------------------------------------------------------------
# Transfer one
# --------------------------------------------------------------------------


def test_one_fish_comes_off_the_smallest_stack():
    """Because that is the stack whose count costs least to change.

    A split stack is a new row in the registry and a stack the player now
    holds two counts of, so the tool spends the stack it has least of.
    """
    assert shares([("a", 5)], take=1, limit=5) == [Share("a", 1, whole=False)]
    assert _sizes(shares([("a", 5), ("b", 3), ("c", 2)], take=1, limit=5)) == [1]


def test_one_fish_takes_a_one_stack_whole_and_leaves_the_big_one_alone():
    """A whole stack is no new identity at all, so a held 1 beats a split."""
    plan = shares([("a", 5), ("b", 1)], take=1, limit=5)
    assert plan == [Share("b", 1, whole=True)]


def test_a_count_larger_than_the_pile_is_the_pile():
    """Asking for 99 out of four fish is asking for four.

    Nothing raises: the buttons ask for what the player can see, and a pile
    that changed under them is the ordinary race rather than a mistake.
    """
    plan = shares([("a", 2), ("b", 2)], take=99, limit=5)
    assert _sizes(plan) == [2, 2]
    assert all(share.whole for share in plan)


def test_a_count_fills_up_with_whole_stacks_before_it_splits_one():
    """Four out of a 3-stack and a 1-stack is both of them, untouched."""
    plan = shares([("a", 3), ("b", 1)], take=4, limit=5)
    assert plan == [Share("a", 3, whole=True), Share("b", 1, whole=True)]


def test_only_the_last_stack_is_split():
    """Three out of two 2-stacks takes one whole and one fish off the other.

    Which of the two is split does not matter -- they are the same size and
    the plan is interchangeable -- but that only *one* of them is split does.
    """
    plan = shares([("a", 2), ("b", 2)], take=3, limit=5)
    assert _sizes(plan) == [2, 1]
    assert [share.whole for share in plan] == [True, False]


def test_a_split_off_a_stack_smaller_than_the_cap_leaves_a_patch_behind():
    """Two out of three: the share is the two, and the one left over is the
    caller's to write back."""
    assert shares([("a", 3)], take=2, limit=5) == [Share("a", 2, whole=False)]


# --------------------------------------------------------------------------
# Nothing to do, and mistakes that are the caller's
# --------------------------------------------------------------------------


def test_an_empty_pile_plans_nothing():
    assert shares([], limit=5) == []
    assert shares([("a", 0)], limit=5) == [], "a stack of no fish is not a stack"
    assert shares([], one_stack=True, limit=5) == []
    assert shares([("a", 0)], take=1, limit=5) == []


def test_a_limit_that_fits_nothing_is_a_mistake_not_a_plan():
    """Refused rather than answered, because a plan that gives nothing away
    would look exactly like a write that failed."""
    with pytest.raises(ValueError):
        shares([("a", 3)], limit=0)
    with pytest.raises(ValueError):
        shares([("a", 3)], one_stack=True, take=1, limit=5)
    with pytest.raises(ValueError):
        shares([("a", 3)], take=0, limit=5)
    with pytest.raises(ValueError):
        shares([("a", 3)], take=-1, limit=5)


# --------------------------------------------------------------------------
# The invariants, over every shape a pile can have
# --------------------------------------------------------------------------

#: Piles to hold the invariants against: one big stack, a full slot, the
#: remainders on either side of a slot, a pile of equal stacks, a lone fish,
#: and one that is already all slots.
PILES = [
    [("a", 1)],
    [("a", 5)],
    [("a", 6)],
    [("a", 12)],
    [("a", 20)],
    [("a", 3), ("b", 1)],
    [("a", 5), ("b", 3), ("c", 1)],
    [("a", 2), ("b", 2)],
    [("a", 5), ("b", 5)],
    [("a", 1), ("b", 1), ("c", 1), ("d", 1), ("e", 1), ("f", 1)],
]

STACK_LIMIT = 5


def _held(pile):
    return dict(pile)


@pytest.mark.parametrize("pile", PILES)
@pytest.mark.parametrize("take", [None, 1, 2, 4, 5, 7, 13, 99])
def test_a_share_never_asks_a_stack_for_more_than_it_holds(pile, take):
    """The whole safety property, in one assertion: **down, never up**.

    Every share's size is bounded by the stack it comes from and by the game's
    cap, and a share that says ``whole`` is the stack exactly as it is held --
    which is what lets the caller write it back without patching a byte.
    """
    plan = shares(pile, take=take, limit=STACK_LIMIT)
    held = _held(pile)

    for share in plan:
        assert 0 < share.size <= min(STACK_LIMIT, held[share.source]), share
        if share.whole:
            assert share.size == held[share.source], "a whole share is the stack"

    # And no stack is asked for more in total than it holds, which is the same
    # rule seen from the pile's side rather than the share's.
    for source, quantity in held.items():
        assert sum(s.size for s in plan if s.source == source) <= quantity


@pytest.mark.parametrize("pile", PILES)
@pytest.mark.parametrize("take", [None, 1, 2, 4, 5, 7, 13, 99])
def test_a_count_takes_exactly_what_was_asked_for(pile, take):
    """``take`` out of the pile, and never more -- the plan is a plan for a
    number of fish the player chose, so a share lost or doubled here is a
    stack the tool would take out of the game and not put back."""
    plan = shares(pile, take=take, limit=STACK_LIMIT)
    total = sum(quantity for _, quantity in pile)
    wanted = total if take is None else min(take, total)
    assert sum(s.size for s in plan) == wanted


@pytest.mark.parametrize("pile", PILES)
def test_one_stack_is_never_more_than_one_slot(pile):
    """One press, one slot: the largest held stack, capped at the game's own
    limit, and never the pile."""
    plan = shares(pile, one_stack=True, limit=STACK_LIMIT)
    largest = max(quantity for _, quantity in pile)
    if largest == 0:
        assert plan == []
        return
    assert len(plan) == 1
    assert plan[0].size == min(STACK_LIMIT, largest)
