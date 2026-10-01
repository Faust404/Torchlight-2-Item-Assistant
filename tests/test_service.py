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

from tl2stash import StashWatcher  # noqa: E402
from tl2stash.registry import Registry  # noqa: E402
from tl2stash.service import STATUS_ABSORBED, STATUS_IN_STASH, ItemService  # noqa: E402

from test_archive import write_synthetic_stash  # noqa: E402


@pytest.fixture
def stash_path(tmp_path):
    return tmp_path / "sharedstash_v2.bin"


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "items.db"


@pytest.fixture
def service(stash_path, db_path):
    write_synthetic_stash(stash_path, ["Alpha", "Beta", "Gamma"])
    with ItemService(db_path, stash_path) as svc:
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
    assert service.registry.get(print_)["status"] == STATUS_IN_STASH


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
# Registry housekeeping
# --------------------------------------------------------------------------


def test_absorb_survives_a_reopened_database(stash_path, db_path):
    """The registry is the durable half, so it has to outlive the process."""
    write_synthetic_stash(stash_path, ["Alpha", "Beta"])
    with ItemService(db_path, stash_path) as svc:
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
