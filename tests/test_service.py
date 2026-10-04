"""Tests for the watcher and the absorb/enforce/restore cycle.

The interesting property here is not that absorbing works once.  It is that
absorbing keeps working when the game undoes it -- which it does, every time
it saves, because it still has the item in memory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash import StashWatcher, parse_item, read_stash_file  # noqa: E402
from tl2stash.registry import Arrival, Registry  # noqa: E402
from tl2stash.saves import SaveLocation  # noqa: E402
from tl2stash.service import (  # noqa: E402
    DEFAULT_CONTAINER,
    STATUS_ABSORBED,
    STATUS_IN_STASH,
    STATUS_RETURNED,
    ItemService,
)

#: The container id of the shared stash's consumables tab, as the game numbers
#: it.  Only used to stand for "the app answered something other than the
#: default" -- the routing rule itself is not this module's to test.
CONSUMABLES_CONTAINER = 25

from test_archive import (  # noqa: E402
    write_stash_of,
    write_stash_with_rubbish,
    write_synthetic_stash,
)
from test_format import synthetic_item  # noqa: E402


@pytest.fixture
def stash_path(tmp_path):
    return tmp_path / "sharedstash_v2.bin"


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "items.db"


@pytest.fixture
def service(stash_path, db_path):
    write_synthetic_stash(stash_path, ["Alpha", "Beta", "Gamma"])
    with ItemService(db_path, SaveLocation.at(stash_path)) as svc:
        yield svc


# --------------------------------------------------------------------------
# The watcher
# --------------------------------------------------------------------------


def test_watcher_reports_the_first_poll_as_changed(tmp_path):
    """So the caller gets one pass over whatever is already on disk."""
    path = tmp_path / "sharedstash_v2.bin"
    path.write_bytes(b"x")
    watcher = StashWatcher(path)
    assert watcher.changed()


def test_watcher_settles_once_accepted(tmp_path):
    path = tmp_path / "sharedstash_v2.bin"
    path.write_bytes(b"x")
    watcher = StashWatcher(path)
    watcher.accept()
    assert not watcher.changed()
    assert not watcher.changed()  # polling repeatedly stays quiet


def test_watcher_notices_a_rewrite_of_the_same_size(tmp_path):
    """The likely case, not the exotic one.

    Items of similar size trade places all the time, so a save can leave the
    file exactly as long as it was.
    """
    path = tmp_path / "sharedstash_v2.bin"
    path.write_bytes(b"\x00" * 64)
    watcher = StashWatcher(path)
    watcher.accept()

    path.write_bytes(b"\xff" * 64)
    now = path.stat().st_mtime
    os.utime(path, (now + 10, now + 10))  # force a distinct mtime, whatever the FS resolution

    assert watcher.changed()


def test_watcher_ignores_a_missing_file(tmp_path):
    """The game has not saved yet; that is not a change to act on."""
    watcher = StashWatcher(tmp_path / "nothing-here.bin")
    assert not watcher.changed()
    watcher.accept()
    assert not watcher.changed()


def test_watcher_can_be_retargeted(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    watcher = StashWatcher(a)
    watcher.accept()
    assert not watcher.changed()

    watcher.retarget(b)
    assert watcher.changed()


def test_watcher_only_accepts_on_success(tmp_path):
    """The contract that makes a half-written save safe.

    A caller that fails to process the file simply does not accept, and the
    next poll reports the change again.
    """
    path = tmp_path / "sharedstash_v2.bin"
    path.write_bytes(b"v1")
    watcher = StashWatcher(path)
    watcher.accept()

    path.write_bytes(b"v2-longer")
    assert watcher.changed()
    assert watcher.changed(), "unaccepted change must survive a re-poll"


# --------------------------------------------------------------------------
# Absorbing
# --------------------------------------------------------------------------


def test_absorb_all_empties_the_stash(service, stash_path):
    result = service.absorb_all()

    assert len(result.taken) == 3
    assert result.retaken == []
    assert service.stash_items() == []

    names = sorted(row["name"] for row in service.registry.rows())
    assert names == ["Alpha", "Beta", "Gamma"]
    assert service.registry.absorbed_fingerprints() == {
        row["fingerprint"] for row in service.registry.rows()
    }


def test_absorb_keeps_the_bytes(service):
    service.absorb_all()
    for row in service.registry.rows():
        assert row["raw"], "an item we are now the only copy of must keep its bytes"


def test_absorb_all_on_an_empty_stash_is_a_no_op(service):
    service.absorb_all()
    again = service.absorb_all()
    assert again.count == 0
    assert again.summary == "nothing to absorb"


def test_absorb_all_leaves_an_item_it_could_not_read(stash_path, db_path):
    """The player is told, and the item is still in the file.

    An item the parser cannot read can be neither stored nor removed, so the
    pass does what it can and says what it could not do -- the alternative is a
    thing sitting in the shared stash that neither panel ever mentions.
    """
    write_stash_with_rubbish(stash_path, ["Alpha", "Beta"])
    with ItemService(db_path, SaveLocation.at(stash_path)) as service:
        result = service.absorb_all()

        assert len(result.taken) == 2
        assert result.unreadable == 1
        assert "could not be read" in result.summary

        after = read_stash_file(stash_path)
        assert [i.base_name for i in after.items] == []
        assert len(after.failed) == 1


def test_absorb_dry_run_takes_nothing(service, stash_path):
    """A dry run reports what it would take, and takes none of it.

    It still *looks*, so the items show up in the registry as known and
    present -- that is what refresh means, and refusing to look would make
    the preview useless.  What it must not do is mark them ours or write the
    file.
    """
    before = stash_path.read_bytes()

    result = service.absorb_all(dry_run=True)

    assert len(result.taken) == 3
    assert stash_path.read_bytes() == before
    assert service.registry.absorbed_fingerprints() == set()
    assert len(service.stash_items()) == 3


# --------------------------------------------------------------------------
# Convergence -- the property the whole approach rests on
# --------------------------------------------------------------------------


def test_the_game_putting_an_item_back_does_not_undo_the_absorb(service, stash_path):
    """What actually happens on the player's next save.

    Torchlight holds the stash in memory, so the next save rewrites the file
    with the absorbed items still in it.  The tool has to take them out again
    -- and again, for as long as the game keeps doing it.
    """
    write_synthetic_stash(stash_path, ["Alpha", "Beta", "Gamma"])
    game_saved = stash_path.read_bytes()
    service.absorb_all()
    assert service.stash_items() == []

    # The game saves: the file is back, items and all.
    stash_path.write_bytes(game_saved)
    result = service.enforce()

    assert result is not None
    assert len(result.retaken) == 3
    assert service.stash_items() == []


def test_enforce_is_quiet_when_there_is_nothing_to_do(service, stash_path):
    service.absorb_all()
    assert service.enforce() is None, "a save with nothing of ours in it is not news"


def test_enforce_leaves_items_the_player_just_put_in(service, stash_path):
    """Only items we have taken are taken again.  New loot is the player's."""
    service.absorb_all()
    write_synthetic_stash(stash_path, ["Delta"])

    assert service.enforce() is None
    assert [i.base_name for i in service.stash_items()] == ["Delta"]


def test_absorb_reports_retaken_separately_from_taken(service, stash_path):
    """A steady trickle of retaken items is normal; a flood is not."""
    write_synthetic_stash(stash_path, ["Alpha", "Beta"])
    service.absorb_all()

    write_synthetic_stash(stash_path, ["Alpha", "Beta", "Gamma"])
    result = service.absorb_all()

    assert [i.base_name for i in result.retaken] == ["Alpha", "Beta"]
    assert [i.base_name for i in result.taken] == ["Gamma"]


# --------------------------------------------------------------------------
# Restoring
# --------------------------------------------------------------------------


def test_restore_puts_an_item_back(service, stash_path):
    service.absorb_all()
    print_ = service.registry.rows()[0]["fingerprint"]

    report = service.restore({print_})

    assert report.changed
    assert len(service.stash_items()) == 1


def test_a_stack_is_stored_and_put_back_whole(service, stash_path):
    """A pile of potions is one item, and the pile is what has to survive.

    The count is a field of the save file's own record, so the tool's side of
    it is nothing more than not losing the bytes: the registry keeps the record
    and the count beside it, and putting the item back writes the record out
    again.  Read or written one field out, twenty potions come back as one
    potion with twenty sockets -- which is the mistake this pins.
    """
    stack = parse_item(synthetic_item(name="Neverending Fish", quantity=20)[0])
    write_stash_of(stash_path, [stack])

    result = service.absorb_all()
    assert [i.base_name for i in result.taken] == ["Neverending Fish"]

    (row,) = service.registry.rows()
    assert row["quantity"] == 20, "the stack size was not recorded with the item"

    service.restore({row["fingerprint"]})
    (back,) = service.stash_items()
    assert back.quantity == 20, "the stack came back as a single item"
    assert back.num_sockets == 0, "the count landed on the socket field"


def test_a_restored_item_is_not_snatched_straight_back(service, stash_path):
    """The trap in the vacuum model.

    Absorbed means "take this out of the game".  Restoring an item without
    clearing that mark would make the very next enforce pass remove it again,
    and the player would watch the item vanish the moment they put it back.
    """
    service.absorb_all()
    print_ = service.registry.rows()[0]["fingerprint"]
    service.restore({print_})

    assert service.enforce() is None, "enforce took back an item we had just restored"
    assert len(service.stash_items()) == 1
    assert service.registry.get(print_)["status"] == STATUS_RETURNED


def test_the_vacuum_spares_an_item_the_player_put_back(service, stash_path):
    """The other half of the same trap.

    enforce() is not the only thing that could re-take a returned item -- the
    automatic vacuum takes everything in the stash, and an item the player
    deliberately put back is in the stash.  Without the exemption the Restore
    button would work for exactly one save cycle.
    """
    service.absorb_all()
    print_ = service.registry.rows()[0]["fingerprint"]
    service.restore({print_})

    result = service.absorb_all(include_returned=False)

    assert result.count == 0, "the vacuum took back a returned item"
    assert len(service.stash_items()) == 1


def test_the_explicit_button_still_takes_returned_items(service, stash_path):
    """Spared by the vacuum, not by the user.

    Clicking Absorb is a later decision than the one that returned the item,
    and it wins.
    """
    service.absorb_all()
    print_ = service.registry.rows()[0]["fingerprint"]
    service.restore({print_})

    result = service.absorb_all()

    assert len(result.retaken) == 1
    assert service.stash_items() == []


def test_restore_all_returns_everything(service, stash_path):
    service.absorb_all()
    prints = {row["fingerprint"] for row in service.registry.rows()}

    report = service.restore(prints)

    assert len(report.restored) == 3
    assert len(service.stash_items()) == 3
    assert service.registry.absorbed_fingerprints() == set()


def test_restore_after_a_restore_is_a_no_op(service):
    service.absorb_all()
    prints = {row["fingerprint"] for row in service.registry.rows()}
    service.restore(prints)

    report = service.restore(prints)

    assert report.restored == []
    assert len(report.skipped) == 3
    assert len(service.stash_items()) == 3, "restoring twice must not clone"


def test_restore_finds_items_by_name(service):
    """The query the GUI's search box is built on."""
    service.absorb_all()
    hit = service.registry.search("Beta")
    assert [row["name"] for row in hit] == ["Beta"]

    service.restore({hit[0]["fingerprint"]})
    assert [i.base_name for i in service.stash_items()] == ["Beta"]


def test_search_narrows_with_every_term(service):
    """Terms are ANDed, so typing more always narrows.

    OR would be useless for finding one item among hundreds: every extra word
    would widen the list instead of shortening it.
    """
    service.absorb_all()

    assert {r["name"] for r in service.registry.search("Alpha")} == {"Alpha"}
    assert service.registry.search("Alpha Beta") == [], "no item matches both"
    assert service.registry.search("lph") != [], "matches inside a word"


# --------------------------------------------------------------------------
# A pile goes back a game slot at a time
# --------------------------------------------------------------------------
#
# The game holds five of a fish in a slot and no more, so a pile cannot go back
# the way an ordinary item does -- it has to be divided, and dividing is the one
# thing in the tool that changes an item's bytes.  The stack count is inside the
# fingerprint, so every share written is a *new* row in the registry and the
# stack it came from stops describing anything; these tests are about the books
# balancing afterwards, which is the part that is easy to get quietly wrong.
#
# Every one of them counts in *fish*, because that is what the player is
# counting: a 20-stack is twenty fish whether it goes back as one row of five
# copies or as four rows.


def _fish(stash_path) -> list[int]:
    """What the file holds, as stack sizes in slot order."""
    return [
        item.quantity
        for item in sorted(
            read_stash_file(stash_path).items, key=lambda i: i.location.slot_index
        )
    ]


def _books(service) -> list[tuple[str, int, int]]:
    """The registry's account of one item, as (status, quantity, copies)."""
    return sorted(
        (row["status"], row["quantity"], row["copies"])
        for row in service.registry.rows()
    )


@pytest.fixture
def pile(stash_path, db_path):
    """A service holding one 20-fish stack, absorbed, and nothing else."""

    def build(quantity: int, copies: int = 1, name: str = "Neverending Fish"):
        items = [
            parse_item(
                synthetic_item(name=name, quantity=quantity, slot=3322 + i)[0]
            )
            for i in range(copies)
        ]
        write_stash_of(stash_path, items)
        service = ItemService(db_path, SaveLocation.at(stash_path))
        service.absorb_all()
        return service

    return build


def test_a_twenty_stack_goes_back_as_four_slots_of_five(pile, stash_path):
    """The case the cap exists for, and the one the player sees.

    Twenty fish are four slots wherever they came from, and each is written
    beside the last rather than into whatever hole the tab has lowest -- four
    stacks cut from one ought to read as one block in the stash.
    """
    service = pile(20)
    with service:
        (row,) = service.registry.rows()
        result = service.restore_pile({row["fingerprint"]}, stack_limit=5)

        assert result.restored == 20, "counted in fish, not in slots"
        assert _fish(stash_path) == [5, 5, 5, 5]
        assert [
            item.location.slot_index
            for item in read_stash_file(stash_path).items
        ] == [3322, 3323, 3324, 3325]

        # The four are byte for byte the same record, so they are one row with
        # a copy count -- and the 20-stack's row is gone, because nothing in
        # the file or the tool holds those bytes any more.
        assert _books(service) == [(STATUS_RETURNED, 5, 4)]
        assert service.registry.get(row["fingerprint"]) is None


def test_twelve_fish_go_back_as_five_five_and_two(pile, stash_path):
    """The remainder is a slot of its own, not four fish dropped on the floor.

    A share may re-count a stack down and never up, so a pile that does not
    divide evenly ends in a stack smaller than the cap -- which is a slot the
    player sees half full, and the only honest shape for the last few.
    """
    service = pile(12)
    with service:
        (row,) = service.registry.rows()
        assert service.restore_pile({row["fingerprint"]}, stack_limit=5).restored == 12
        assert _fish(stash_path) == [5, 5, 2]


def test_transfer_a_stack_fills_one_slot_and_stops(pile, stash_path):
    """One press, one slot -- the fish left over stay the tool's.

    A 12-stack asked for one slot's worth gives five and keeps seven, and the
    row it keeps is a 7-stack: it is the tool's account of fish, not a record
    the game will ever be handed whole, so it is free to be a size no slot
    holds.  The next press divides it again.
    """
    service = pile(12)
    with service:
        (row,) = service.registry.rows()
        result = service.restore_a_stack({row["fingerprint"]}, stack_limit=5)

        assert result.restored == 5
        assert _fish(stash_path) == [5]
        assert _books(service) == [
            (STATUS_ABSORBED, 7, 1),
            (STATUS_RETURNED, 5, 1),
        ]


def test_transfer_one_comes_off_the_smallest_stack(pile, stash_path):
    """One fish, and the stack it costs least to re-count.

    A split stack is a new row and a stack the player now holds two counts of,
    so the smallest is the one to spend: a 3-stack and a 1-stack give the 1
    whole and leave the 3 alone.
    """
    service = pile(3, copies=1)
    with service:
        service.registry.add(
            [
                Arrival(
                    item=parse_item(
                        synthetic_item(name="Neverending Fish", quantity=1, slot=3323)[0]
                    )
                )
            ],
            source=service.source_key,
            status=STATUS_ABSORBED,
        )
        prints = {row["fingerprint"] for row in service.registry.rows()}
        result = service.restore_units(prints, 1, stack_limit=5)

        assert result.restored == 1
        assert _fish(stash_path) == [1]
        assert _books(service) == [(STATUS_ABSORBED, 3, 1), (STATUS_RETURNED, 1, 1)]


def test_the_fish_left_behind_are_the_tools_own_row(pile, stash_path):
    """Five out of ten leaves the bytes the game was just handed.

    A stack's count is inside its fingerprint, so a 10-stack sent five at a
    time leaves a 5-stack -- the *same record* the game now holds in its slot.
    One row cannot say both "the file has five of these" and "the tool has five
    more", so the tool's half is keyed apart from the file's and neither side's
    count is spent on the other.  Without that the tool's five fish are simply
    written off: the file's row says five, and the tool believes it.
    """
    service = pile(10)
    with service:
        (row,) = service.registry.rows()
        assert service.restore_a_stack({row["fingerprint"]}, stack_limit=5).restored == 5

        assert _fish(stash_path) == [5]
        assert _books(service) == [
            (STATUS_ABSORBED, 5, 1),
            (STATUS_RETURNED, 5, 1),
        ], "the tool's five fish are missing from its own books"

        # And the ten fish are still ten, whichever half they are on.
        assert sum(q * c for _, q, c in _books(service)) == 10


def test_the_copy_left_behind_can_still_be_sent(pile, stash_path):
    """The other half of the same mistake, and the one that strands fish.

    Two byte-identical 5-stacks, one sent: the tool keeps the other, as a row
    of its own.  Sending that one must actually write -- the archive's skip
    answers "this item never left", which is true of the file's copy and false
    of the tool's, and believing it here leaves five fish the player can see
    and can never send.
    """
    service = pile(5, copies=2)
    with service:
        (row,) = service.registry.rows()
        assert row["copies"] == 2
        assert service.restore_a_stack({row["fingerprint"]}, stack_limit=5).restored == 5
        assert _fish(stash_path) == [5]

        prints = {r["fingerprint"] for r in service.registry.rows()}
        result = service.restore_pile(prints, stack_limit=5)

        assert result.restored == 5, "the copy the tool kept was not sent"
        assert result.skipped == 0, (
            "the file's own copy was named as a share and written again"
        )
        assert _fish(stash_path) == [5, 5]
        assert _books(service) == [(STATUS_RETURNED, 5, 2)], (
            "the tool sent fish it did not hold, or kept fish it no longer has"
        )


def test_the_vacuum_spares_the_fish_the_player_put_back(pile, stash_path):
    """A pile is an item like any other, and ``returned`` means the same.

    The automatic pass runs on every save, so shares marked ``absorbed`` would
    be vacuumed straight back out of the stash the player had just filled --
    the same trap a single restored item has, with four times the fish in it.
    """
    service = pile(20)
    with service:
        (row,) = service.registry.rows()
        service.restore_pile({row["fingerprint"]}, stack_limit=5)

        assert service.absorb_all(include_returned=False).taken == []
        assert _fish(stash_path) == [5, 5, 5, 5]


def test_a_full_tab_refuses_and_every_fish_is_still_accounted_for(stash_path, db_path):
    """Nothing is lost when the write cannot happen.

    The books are settled from what the file took, so a refusal leaves the
    source stack exactly as it was -- a full tab, a save mid-write, anything
    the game does, and the fish the tool holds are still the fish it holds.
    """
    stack = parse_item(synthetic_item(name="Neverending Fish", quantity=20)[0])
    write_stash_of(stash_path, [stack])

    # A tab of one cell: the first share fits and nothing else can.
    def container_cells(container: int) -> tuple[tuple[int, int], ...]:
        return ((3322, 1),) if container == 24 else ()

    with ItemService(
        db_path, SaveLocation.at(stash_path), container_cells=container_cells
    ) as service:
        service.absorb_all()
        (row,) = service.registry.rows()
        result = service.restore_pile({row["fingerprint"]}, stack_limit=5)

        assert result.restored + result.refused + result.skipped == 20, (
            "fish went missing from the count"
        )
        assert result.refused == 15
        assert _fish(stash_path) == [5]
        assert sum(q * c for _, q, c in _books(service)) == 20


# --------------------------------------------------------------------------
# Stranded items
# --------------------------------------------------------------------------


def test_a_returned_item_the_save_erased_is_stranded(service, stash_path):
    """The third state, and the one only a save can produce.

    An item put back is in the file, and the tool knows the game has it.  If
    the game's own save then rewrites the whole stash from memory -- memory
    that never had the item, because the write landed while it was playing --
    the file loses it and the tool does not.  Returned, in no file, in
    neither pane: stranded.  Nothing about the registry says so; the answer
    is the difference between the two, which is why this is where it is
    worked out.
    """
    service.absorb_all()
    prints = {row["name"]: row["fingerprint"] for row in service.registry.rows()}
    service.restore({prints["Beta"]})
    service.refresh()
    assert service.stranded_rows() == [], "the file has it -- the game has it"

    # The save the game makes of a stash it never wrote Beta into, and the
    # next poll that reads it.
    write_stash_of(stash_path, [])
    service.refresh()

    assert [row["name"] for row in service.stranded_rows()] == ["Beta"]


def test_only_what_was_promised_to_the_game_can_be_stranded(service, stash_path):
    """Two ways to own something, and neither is stranded.

    An absorbed item is the tool's own and was never written anywhere, and an
    item that was never taken is still in the file.  Only the item that was
    handed to the game and is not there now is in neither pane.
    """
    assert service.stranded_rows() == [], "nothing has been put back yet"

    service.absorb_all()
    service.refresh()
    assert service.stranded_rows() == [], "absorbed items are not stranded"


def test_recovering_a_stranded_item_makes_it_a_member_again(service, stash_path):
    """The whole of the recovery, and the whole of its restraint.

    Recovering decides what the *tool* believes.  The item joins the
    collection and the file is left exactly as it was -- not re-written, not
    touched -- because the one thing the file's state cannot tell anyone is
    whether the game erased this item or a character is carrying it, and
    writing it back into the stash would be a second copy of the player's own
    item.
    """
    service.absorb_all()
    print_ = {row["name"]: row["fingerprint"] for row in service.registry.rows()}[
        "Beta"
    ]
    service.restore({print_})
    write_stash_of(stash_path, [])
    service.refresh()
    untouched = stash_path.read_bytes()

    assert service.recover({print_}) == 1

    assert service.registry.get(print_)["status"] == STATUS_ABSORBED
    assert print_ in service.registry.absorbed_fingerprints()
    assert service.stranded_rows() == [], "it is still being reported as stranded"
    assert stash_path.read_bytes() == untouched, "recovering wrote to the game"


def test_an_item_the_file_has_is_not_recovered_behind_the_player_s_back(service):
    """The guard, and what it is for.

    A returned item the file still holds is one the game really does have --
    the player has only to pick it up, or not.  Marking it ours would put it
    on the wrong side of the vacuum and the tool would take it back out of
    the player's stash on the next save, which is a thing nobody asked for.
    """
    service.absorb_all()
    print_ = {row["name"]: row["fingerprint"] for row in service.registry.rows()}[
        "Beta"
    ]
    service.restore({print_})

    assert service.recover({print_}) == 0

    assert service.registry.get(print_)["status"] == STATUS_RETURNED
    assert [item.fingerprint for item in service.stash_items()] == [print_]


def test_removing_a_stranded_item_deletes_its_row_and_its_place(service, stash_path):
    """The second answer to the stranded state, for the duplicate.

    Recovering keeps the tool's copy; removing is for the stranded item the
    player can see on a character, where the collection's copy is one the
    game never gave them.  The row goes, its bytes go, and its placement goes
    with them -- an item that is not in the registry has nowhere it was --
    while the file is left byte for byte alone, because the tool's copy is
    the only thing being deleted.
    """
    service.absorb_all()
    print_ = {row["name"]: row["fingerprint"] for row in service.registry.rows()}[
        "Beta"
    ]
    service.restore({print_})
    write_stash_of(stash_path, [])
    service.refresh()
    untouched = stash_path.read_bytes()

    assert service.remove({print_}) == 1

    assert service.registry.get(print_) is None, "the row is still there"
    assert print_ not in service.registry.placements_for(service.source_key), (
        "a placement outlived its item"
    )
    assert service.stranded_rows() == []
    assert stash_path.read_bytes() == untouched, "removing wrote to the game"


def test_only_what_is_stranded_can_be_removed(service):
    """The guard, and it is recovering's.

    An item the file still holds is one the game really has; deleting the
    tool's record of it would throw away something the player can see in
    their own stash, and absorbing is that item's answer.  Announcing a
    removal that did not happen would be worse than the removal -- the
    player would believe a duplicate was gone.
    """
    service.absorb_all()
    print_ = {row["name"]: row["fingerprint"] for row in service.registry.rows()}[
        "Beta"
    ]
    service.restore({print_})

    assert service.remove({print_}) == 0

    assert service.registry.get(print_)["status"] == STATUS_RETURNED
    assert [item.fingerprint for item in service.stash_items()] == [print_]


# --------------------------------------------------------------------------
# Where a returned item lands
# --------------------------------------------------------------------------


def test_a_tab_the_save_has_used_remembers_where_its_cells_begin(service):
    """The tool's own memory of a tab, for a machine with no game on it.

    The three synthetic items sit at 3322, 3323 and 3324, so the tab began at
    3322 -- and it still does once they have all been taken, because a
    placement is recorded and not removed.  That is the case this is for: a
    tab the player has swept out is exactly the one they are putting something
    back into.
    """
    service.absorb_all()

    assert service.registry.first_slot(24, service.source_key) == 3322
    assert service.first_slot(24) == 3322


def test_a_tab_nothing_has_ever_been_in_has_no_first_cell(service):
    """Which is the one case the tool has nothing to go on, and says so.

    ``None`` rather than a guess: a made-up number would put the item in a
    cell the game never numbered, and the caller can do better -- see
    :meth:`tl2stash.gamedata.GameData.slot_base`.
    """
    service.absorb_all()

    assert service.registry.first_slot(25, service.source_key) is None
    assert service.first_slot(25) is None


def test_the_game_s_answer_outranks_the_registry_s(stash_path, db_path):
    """The short way round and the long way round, for a tab nobody has used.

    An empty stash the tool has never absorbed anything from has no placements
    at all, so the registry cannot say where its first tab begins -- and the
    game's own files can, which is what makes the first item ever put into a
    fresh install land in the right cell.  The same answer carries the tab's
    *end*, which is what a full one is measured against.
    """
    write_synthetic_stash(stash_path, [])

    def container_cells(container: int) -> tuple[tuple[int, int], ...]:
        return ((3322, 40),) if container == 24 else ()

    with ItemService(
        db_path, SaveLocation.at(stash_path), container_cells=container_cells
    ) as svc:
        assert svc.first_slot(24) == 3322
        assert svc.last_slot(24) == 3361, "40 cells from 3322 end at 3361"
        assert svc.first_slot(25) is None, "a container the game does not number"
        assert svc.last_slot(25) is None, "and so has no end to measure against"


def test_a_full_tab_refuses_and_the_item_stays_ours(stash_path, db_path):
    """The item is left where the player can see it, and still marked ours.

    Both halves are the same fact seen twice: the item is not in the game, so
    it must not be marked as though it were.  A refused item marked
    ``returned`` would be exempt from the automatic vacuum *and* gone from the
    collection's own accounting -- sitting in neither place, which is the
    whole of what the refusal exists to avoid.
    """
    write_synthetic_stash(stash_path, ["Alpha", "Beta", "Gamma"])

    def container_cells(container: int) -> tuple[tuple[int, int], ...]:
        return ((3322, 3),) if container == 24 else ()

    with ItemService(
        db_path, SaveLocation.at(stash_path), container_cells=container_cells
    ) as service:
        service.absorb_all()
        (alpha,) = [r for r in service.registry.rows() if r["name"] == "Alpha"]
        print_ = alpha["fingerprint"]

        # The player fills the tab with new loot while Alpha waits in the tool.
        write_synthetic_stash(stash_path, ["Delta", "Epsilon", "Zeta"])
        report = service.restore({print_})

        assert report.refused == [(print_, "Alpha", 24)]
        assert report.restored == []
        assert service.registry.get(print_)["status"] == STATUS_ABSORBED
        assert service.registry.get(print_)["raw"], "its bytes are still ours to keep"
        assert "Alpha" not in {i.base_name for i in service.stash_items()}


def test_an_item_left_past_the_end_of_its_tab_comes_back_inside_it(stash_path, db_path):
    """The old bug's leftovers, which may be in the player's save right now.

    Before the ceiling existed, a full tab made the search return one cell past
    the end -- 3362 for the first tab, which no container of the game numbers
    -- and the item was written there.  The game draws nothing at such a slot,
    so the player never saw it land; the tool marked it returned and took it out
    of the collection's hands.  If the game saved while the item was there, it
    is in the file at that number and that is the placement the registry has
    remembered, and putting it back has to honour none of it: not the cell
    (there is no cell), and not the crash the search would raise on an empty
    tab it cannot walk out of.
    """
    write_stash_of(stash_path, [parse_item(synthetic_item(name="Stray", slot=3362)[0])])

    def container_cells(container: int) -> tuple[tuple[int, int], ...]:
        return ((3322, 40),) if container == 24 else ()

    with ItemService(
        db_path, SaveLocation.at(stash_path), container_cells=container_cells
    ) as service:
        service.absorb_all()
        (row,) = service.registry.rows()
        place = service.registry.last_placement(row["fingerprint"], service.source_key)
        assert place["slot"] == 3362, "the fixture did not reproduce the old write"
        assert not service.slot_is_a_cell(24, 3362)

        report = service.restore({row["fingerprint"]})

        assert report.refused == []
        (back,) = service.stash_items()
        assert back.location.slot_index == 3322, "back inside the tab, at its first cell"


def test_an_item_with_no_place_of_its_own_is_routed_by_the_app(stash_path, db_path):
    """The service asks; the app answers; the rule lives in neither.

    Which tab a potion goes in is a fact about kinds, and the kind is in the
    game's data files rather than in the save -- so the service holds a
    callable and the app is what fills it in.  What is pinned here is the
    asking, and that the answer is the one used.
    """
    write_synthetic_stash(stash_path, [])
    asked: list[str] = []

    # 25 is the consumables tab's container id -- what the app's own routing
    # answers with for a potion.  The service must not care why.
    def container_of(print_: str) -> int | None:
        asked.append(print_)
        return CONSUMABLES_CONTAINER

    with ItemService(
        db_path, SaveLocation.at(stash_path), container_of=container_of
    ) as service:
        assert service.tab_for("a potion's fingerprint") == CONSUMABLES_CONTAINER
        assert asked == ["a potion's fingerprint"]


def test_without_the_game_an_item_goes_to_the_first_tab(stash_path, db_path):
    """No game means no kind to read, and the first tab takes all of them.

    This is the machine without Torchlight installed, and the item imported
    from somewhere else entirely: there is nothing to work the kind out from,
    so the answer is the tab the game itself files nothing else into.
    """
    write_synthetic_stash(stash_path, [])
    with ItemService(db_path, SaveLocation.at(stash_path)) as service:
        assert service.tab_for("anything") == DEFAULT_CONTAINER

    def no_answer(print_: str) -> int | None:
        return None

    with ItemService(
        db_path, SaveLocation.at(stash_path), container_of=no_answer
    ) as service:
        assert service.tab_for("anything") == DEFAULT_CONTAINER


# --------------------------------------------------------------------------
# Registry housekeeping
# --------------------------------------------------------------------------


def test_absorb_survives_a_reopened_database(stash_path, db_path):
    """The registry is the durable half, so it has to outlive the process."""
    write_synthetic_stash(stash_path, ["Alpha", "Beta"])
    with ItemService(db_path, SaveLocation.at(stash_path)) as svc:
        svc.absorb_all()

    with Registry(db_path) as registry:
        assert len(registry.absorbed_fingerprints()) == 2
        assert {r["name"] for r in registry.rows()} == {"Alpha", "Beta"}


def test_scan_marks_removed_items_absent_rather_than_deleting(service):
    service.refresh()
    assert len(service.registry.rows()) == 3

    service.absorb_all()

    assert len(service.registry.rows()) == 3, "items must never be deleted"
    assert all(row["status"] == STATUS_ABSORBED for row in service.registry.rows())
