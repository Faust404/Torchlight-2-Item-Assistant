"""Tests for carrying a collection between machines as one file.

Two properties matter more than the rest, and both are about what happens when
things go wrong.  A collection that goes out and comes back has to be the same
items -- the same *bytes*, not items that merely look alike -- because an item
is its bytes and everything else in this tool is downstream of that.  And a
file is evidence or it is nothing: every blob is parsed again and every
fingerprint recomputed, so a collection somebody has edited is refused item by
item rather than believed.

The third is what makes the feature usable at all: reading the same file back
in twice changes nothing the second time.  That is what lets a player keep an
export as a backup and read it back over a collection they have since added
to.  An import that reset statuses would be worse than useless -- an item the
player had returned to the game would be taken out of it again on the next
save, every time.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash import read_stash_file  # noqa: E402
from tl2stash.item import parse_item  # noqa: E402
from tl2stash.portable import (  # noqa: E402
    FORMAT,
    TOOL,
    CollectionError,
    collection_text,
    import_collection,
    read_collection,
    write_collection,
)
from tl2stash.registry import Registry  # noqa: E402
from tl2stash.saves import SaveLocation  # noqa: E402
from tl2stash.service import (  # noqa: E402
    STATUS_ABSORBED,
    STATUS_IN_STASH,
    STATUS_RETURNED,
)

from test_archive import write_stash_of, write_synthetic_stash  # noqa: E402
from test_format import synthetic_item, synthetic_tail  # noqa: E402

STEAM_ID = "76561198328811052"
VANILLA = f"vanilla/{STEAM_ID}"
MODDED = f"modded/{STEAM_ID}"
#: A second profile's vanilla stash: the same kind, a different save.
ANOTHER = "vanilla/76561198000000000"

#: Whatever the window would stamp into the file.  Not the tool's version.
VERSION = "0.0.0-test"


# --------------------------------------------------------------------------
# Building a collection
# --------------------------------------------------------------------------


def _absorbed(root: Path, path: Path) -> tuple[Registry, SaveLocation]:
    """A registry holding everything in ``path``, absorbed -- a collection."""
    location = SaveLocation.at(path)
    registry = Registry(root / "items.db")
    registry.scan(read_stash_file(path), location.key)
    registry.set_status(
        {row["fingerprint"] for row in registry.rows()}, STATUS_ABSORBED
    )
    return registry, location


def _holding(root: Path, names: list[str], kind: str = "vanilla"):
    """The ordinary setup: a stash of named synthetic items, then absorbed."""
    tree = "save" if kind == "vanilla" else "modsave"
    path = root / tree / STEAM_ID / "sharedstash_v2.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_synthetic_stash(path, names)
    return _absorbed(root, path)


def _holding_blobs(root: Path, blobs: list[bytes]):
    """A collection of items built blob-first, for the tests that edit bytes."""
    path = root / "save" / STEAM_ID / "sharedstash_v2.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_stash_of(path, [parse_item(blob) for blob in blobs])
    return _absorbed(root, path)


def _export(registry: Registry, location: SaveLocation) -> str:
    return collection_text(registry, location.key, version=VERSION)


def _entry(data: dict, name: str) -> dict:
    for entry in data["items"]:
        if entry["name"] == name:
            return entry
    raise AssertionError(f"no item called {name} in the file")


def _fresh(root: Path) -> Registry:
    return Registry(root / "elsewhere" / "items.db")


# --------------------------------------------------------------------------
# Out
# --------------------------------------------------------------------------


def test_the_file_is_the_items_own_bytes(tmp_path):
    """Nothing is re-encoded: what the stash held is what the file carries."""
    registry, location = _holding(tmp_path, ["Bashdrill"])
    data = json.loads(_export(registry, location))

    assert data["tool"] == TOOL
    assert data["format"] == FORMAT
    assert data["version"] == VERSION
    assert data["stash"] == VANILLA
    assert data["exported"]  # a timestamp, for a person reading the file

    row = registry.rows()[0]
    entry = data["items"][0]
    assert entry["fingerprint"] == row["fingerprint"]
    assert entry["name"] == row["name"]
    assert base64.b64decode(entry["blob"]) == bytes(row["raw"])


def test_export_carries_only_what_the_tool_holds(tmp_path):
    """The file is the wall, by construction: absorbed rows, and nothing else.

    An item the game still has is not the tool's to give away -- and reading
    one back in would record the tool as owning something it does not.
    """
    registry, location = _holding(tmp_path, ["Bashdrill", "Pioneer Belt"])
    kept = {
        row["fingerprint"] for row in registry.rows() if row["name"] == "Bashdrill"
    }
    registry.set_status(kept, STATUS_IN_STASH)

    data = json.loads(_export(registry, location))

    assert [entry["name"] for entry in data["items"]] == ["Pioneer Belt"]


def test_a_stack_keeps_its_count(tmp_path):
    """How many identical copies there were is the one thing bytes cannot say.

    Two byte-identical items are one registry row with ``copies = 2`` and one
    blob, so the count has to travel as a field of its own or a stack comes
    back as a single item.
    """
    torch = synthetic_item(name="Torch", slot=3322)[0]
    registry, location = _holding_blobs(tmp_path, [torch, torch])
    row = registry.rows()[0]
    assert row["copies"] == 2

    fresh = _fresh(tmp_path)
    import_collection(fresh, location.key, _export(registry, location))

    assert fresh.rows()[0]["copies"] == 2


# --------------------------------------------------------------------------
# Back in
# --------------------------------------------------------------------------


def test_a_collection_comes_back_the_same(tmp_path):
    registry, location = _holding(tmp_path, ["Bashdrill", "Pioneer Belt"])
    fresh = _fresh(tmp_path)

    report = import_collection(fresh, location.key, _export(registry, location))

    assert (report.total, report.added, report.already) == (2, 2, 0)
    assert (report.unreadable, report.refused) == (0, 0)
    assert {row["fingerprint"] for row in fresh.rows()} == {
        row["fingerprint"] for row in registry.rows()
    }
    assert {bytes(row["raw"]) for row in fresh.rows()} == {
        bytes(row["raw"]) for row in registry.rows()
    }
    # The tool holds them; the game does not.
    assert {row["status"] for row in fresh.rows()} == {STATUS_ABSORBED}


def test_reading_the_same_file_back_in_changes_nothing(tmp_path):
    """The property a backup needs: importing twice is importing once."""
    registry, location = _holding(tmp_path, ["Bashdrill"])
    text = _export(registry, location)
    fresh = _fresh(tmp_path)

    first = import_collection(fresh, location.key, text)
    before = [dict(row) for row in fresh.rows()]
    second = import_collection(fresh, location.key, text)

    assert (first.added, second.added, second.already) == (1, 0, 1)
    # Everything: copies, status, both timestamps, the bytes.
    assert [dict(row) for row in fresh.rows()] == before


def test_an_item_the_registry_already_has_keeps_its_status(tmp_path):
    """An import must not resurrect an item the game now holds.

    ``returned`` is what says an item is the game's and not the tool's.  If
    reading a collection reset it to ``absorbed``, the collection would list
    an item sitting in the player's stash -- one item claimed by two places,
    which is exactly what the status keeps straight.
    """
    registry, location = _holding(tmp_path, ["Bashdrill"])
    text = _export(registry, location)
    fresh = _fresh(tmp_path)
    import_collection(fresh, location.key, text)
    fresh.set_status({row["fingerprint"] for row in fresh.rows()}, STATUS_RETURNED)

    report = import_collection(fresh, location.key, text)

    assert report.added == 0
    assert {row["status"] for row in fresh.rows()} == {STATUS_RETURNED}


def test_the_files_metadata_is_ignored_and_the_bytes_are_believed(tmp_path):
    """The fields beside a blob are for a person reading the file.

    Editing the name of an entry cannot change what the item *is*, because the
    item is the blob and the blob is parsed.  This is the same rule that makes
    a hand-edited collection safe to read at all.
    """
    registry, location = _holding(tmp_path, ["Bashdrill"])
    data = json.loads(_export(registry, location))
    entry = data["items"][0]
    entry["name"] = "A Lie"
    entry["level"] = 99
    entry["copies"] = 7

    fresh = _fresh(tmp_path)
    import_collection(fresh, location.key, json.dumps(data))

    row = fresh.rows()[0]
    assert row["name"] == "Bashdrill"
    assert row["level"] == 5
    assert row["copies"] == 7  # ...but this one genuinely is the file's to say


# --------------------------------------------------------------------------
# Refusals, whole file
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, reason",
    [
        ("this is not json", "not JSON"),
        ("[1, 2, 3]", "not a JSON object"),
        (
            json.dumps({"tool": "Something Else", "format": 1, "items": []}),
            "not written by this tool",
        ),
        (
            json.dumps({"tool": TOOL, "format": FORMAT + 1, "items": []}),
            "collection format",
        ),
        (
            json.dumps({"tool": TOOL, "format": FORMAT, "items": []}),
            "does not say which stash",
        ),
        (
            json.dumps({"tool": TOOL, "format": FORMAT, "stash": VANILLA}),
            "lists no items",
        ),
    ],
)
def test_a_file_that_is_not_a_collection_is_refused_whole(tmp_path, text, reason):
    """A backup half-read is worse than one not read at all."""
    registry = _fresh(tmp_path)
    with pytest.raises(CollectionError, match=reason):
        import_collection(registry, VANILLA, text)
    assert registry.rows() == []


def test_a_modded_collection_cannot_be_imported_into_a_vanilla_stash(tmp_path):
    """The one thing the separate databases exist to prevent.

    Not because the items are wrong, but because the *game* is: a modded item
    put into a vanilla save is a save the game will not load.
    """
    modded, mod_location = _holding(tmp_path / "modded", ["Mod Blade"], kind="modded")
    text = _export(modded, mod_location)

    registry = _fresh(tmp_path)
    with pytest.raises(CollectionError, match="modded"):
        import_collection(registry, VANILLA, text)
    assert registry.rows() == []


# --------------------------------------------------------------------------
# Refusals, one item
# --------------------------------------------------------------------------


def test_a_blob_that_does_not_parse_is_skipped_and_named(tmp_path):
    """One unreadable item does not cost the other forty-nine."""
    doomed = synthetic_item(name="Doomed", slot=3322)[0]
    registry, location = _holding_blobs(
        tmp_path, [doomed, synthetic_item(name="Fine", slot=3323)[0]]
    )
    data = json.loads(_export(registry, location))
    entry = _entry(data, "Doomed")
    raw = base64.b64decode(entry["blob"])
    entry["blob"] = base64.b64encode(raw[: len(raw) // 2]).decode("ascii")

    fresh = _fresh(tmp_path)
    report = import_collection(fresh, location.key, json.dumps(data))

    assert (report.added, report.unreadable, report.refused) == (1, 1, 0)
    assert [row["name"] for row in fresh.rows()] == ["Fine"]
    assert "Doomed" in report.problems[0]


def test_a_blob_that_is_not_the_item_the_file_names_is_refused(tmp_path):
    """The fingerprint is recomputed, not read.

    A blob that parses but hashes to something other than the name the file
    gives it is a blob somebody has edited -- or a file that has been through
    something that rewrote it.  Either way the tool does not know what it
    would be holding, so it does not hold it.

    The byte flipped here is the last one of the item, which is past the end
    of everything the parser reads: the blob is otherwise a perfect item, and
    still does not match the name the file gives it.
    """
    doomed = synthetic_item(
        name="Doomed", slot=3322, tail=synthetic_tail(junk=b"\xAA\xAA")
    )[0]
    registry, location = _holding_blobs(
        tmp_path, [doomed, synthetic_item(name="Fine", slot=3323)[0]]
    )
    data = json.loads(_export(registry, location))
    entry = _entry(data, "Doomed")
    raw = bytearray(base64.b64decode(entry["blob"]))
    raw[-1] ^= 0xFF
    entry["blob"] = base64.b64encode(bytes(raw)).decode("ascii")

    fresh = _fresh(tmp_path)
    report = import_collection(fresh, location.key, json.dumps(data))

    assert (report.added, report.unreadable, report.refused) == (1, 0, 1)
    assert [row["name"] for row in fresh.rows()] == ["Fine"]
    assert "Doomed" in report.problems[0]


# --------------------------------------------------------------------------
# Placements
# --------------------------------------------------------------------------


def test_a_collection_from_this_very_stash_brings_its_placements(tmp_path):
    """Where an item sat is the file's to carry, and only for its own stash.

    An item read back into the stash it came from goes to the tab and cell it
    left, instead of to the first free one -- which is what a player restoring
    a lost database expects to see.
    """
    registry, location = _holding(tmp_path, ["Bashdrill", "Pioneer Belt"])
    fresh = _fresh(tmp_path)

    import_collection(fresh, location.key, _export(registry, location))

    for row in fresh.rows():
        mine = registry.last_placement(row["fingerprint"], location.key)
        theirs = fresh.last_placement(row["fingerprint"], location.key)
        assert (theirs["container"], theirs["slot"]) == (mine["container"], mine["slot"])
        # And *not* present: these are exactly the items the file lacks.
        assert theirs["present"] == 0


def test_a_collection_from_another_stash_lands_with_no_place_here(tmp_path):
    """Another profile's collection is the same kind, so it comes in.

    It is also a stranger: nothing in *this* stash is where that item sat, so
    it gets no placement and the tool falls back to the item's kind and the
    tab's first cell when it is put back.
    """
    registry, location = _holding(tmp_path, ["Bashdrill"])
    fresh = _fresh(tmp_path)

    report = import_collection(fresh, ANOTHER, _export(registry, location))

    assert report.added == 1
    assert fresh.placements_for(ANOTHER) == {}
    assert fresh.last_placement(fresh.rows()[0]["fingerprint"], ANOTHER) is None


# --------------------------------------------------------------------------
# The file on disk
# --------------------------------------------------------------------------


def test_a_bare_name_is_given_the_tools_own_suffix(tmp_path):
    """And a name with an extension the player chose is left alone."""
    assert write_collection(tmp_path / "backup", "{}") == tmp_path / "backup.tl2ia"
    assert (tmp_path / "backup.tl2ia").read_text(encoding="utf-8") == "{}"

    assert write_collection(tmp_path / "backup.json", "{}") == tmp_path / "backup.json"
    assert (tmp_path / "backup.json").read_text(encoding="utf-8") == "{}"


def test_a_file_that_is_not_there_is_a_message_not_a_traceback(tmp_path):
    with pytest.raises(CollectionError, match="Could not read"):
        read_collection(tmp_path / "missing.tl2ia")
