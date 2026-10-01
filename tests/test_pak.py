"""Tests for the archive reader.

The synthetic tests build a manifest and an archive that agree with each
other, which is what makes them worth having: a reader that returns plausible
bytes from the wrong offset passes a test that only checks the bytes came
back.  So the fixtures put a distinct payload in every entry and the tests ask
for them by name.

The real-file tests skip when the game is not installed -- an 869 MB archive
is not a fixture to check in, and a machine without the game is not a broken
machine.
"""

from __future__ import annotations

import random
import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash.gamedata import archive_path, find_install  # noqa: E402
from tl2stash.pak import (  # noqa: E402
    PakEntry,
    PakError,
    PakFile,
    PakIndex,
    open_archive,
)


# --------------------------------------------------------------------------
# Synthetic archive construction
# --------------------------------------------------------------------------


def _torch_text(text: str) -> bytes:
    """A Torchlight string: character count, then UTF-16LE."""
    encoded = text.encode("utf-16-le")
    return struct.pack("<H", len(encoded) // 2) + encoded


def write_synthetic_pak(
    directory: Path, files: dict[str, bytes], *, folders: int | None = None
) -> Path:
    """Build a ``DATA.PAK.MAN`` and its ``DATA.PAK`` holding ``files``.

    Each file is deflated separately and preceded by the three-word block
    header the reader seeks back over, and the manifest records where each
    payload starts.  ``folders`` overrides the folder count so a test can
    write a manifest that disagrees with its own contents.
    """
    directory.mkdir(parents=True, exist_ok=True)

    # Group by folder, the way the real manifest does, so entries within a
    # folder are named relative to it.  A key ending in a slash is a folder
    # entry, and its leaf keeps the slash -- which is exactly how the real
    # manifest spells one.
    grouped: dict[str, list[tuple[str, bytes]]] = {}
    for name, data in files.items():
        stripped = name[:-1] if name.endswith("/") else name
        folder, _, leaf = stripped.rpartition("/")
        if name.endswith("/"):
            leaf += "/"
        grouped.setdefault(f"{folder}/", []).append((leaf, data))

    archive = bytearray()
    entries: dict[str, tuple[int, int, int]] = {}  # name -> (offset, crc, kind)

    for folder, members in sorted(grouped.items()):
        for leaf, data in sorted(members):
            packed = zlib.compress(data)
            # The manifest records where the block starts plus four, not
            # where the payload starts.  The block is three words --
            # header, decoded size, encoded size -- and the reader seeks back
            # over the first of them, so the payload lands eight bytes after
            # the offset the manifest gives.
            block = len(archive)
            archive += struct.pack("<III", 0, len(data), len(packed))
            archive += packed
            entries[f"{folder}{leaf}"] = (block + 4, zlib.crc32(data), 0)

    manifest = bytearray()
    manifest += struct.pack("<H", 2)
    manifest += struct.pack("<I", 0)
    manifest += _torch_text("MEDIA/")
    manifest += struct.pack("<I", 0)
    manifest += struct.pack(
        "<I", len(grouped) if folders is None else folders
    )
    for folder, members in sorted(grouped.items()):
        manifest += _torch_text(folder)
        manifest += struct.pack("<I", len(members))
        for leaf, data in sorted(members):
            offset, crc, kind = entries[f"{folder}{leaf}"]
            manifest += struct.pack("<I", crc)
            manifest += struct.pack("<B", kind)
            manifest += _torch_text(leaf)
            manifest += struct.pack("<I", offset)
            manifest += struct.pack("<I", len(data))
            manifest += struct.pack("<I", 0)
            manifest += struct.pack("<I", 0)

    man_path = directory / "DATA.PAK.MAN"
    man_path.write_bytes(bytes(manifest))
    (directory / "DATA.PAK").write_bytes(bytes(archive))
    return man_path


@pytest.fixture
def pak(tmp_path):
    """An archive, its index, and the bytes each entry should return."""
    files = {
        "MEDIA/UNITS/ITEMS/SWORDS/BASE_SWORD.DAT": b"a sword",
        "MEDIA/UNITS/ITEMS/SWORDS/DJINN FIRE SWORD.DAT": b"a better sword",
        "MEDIA/EFFECTSLIST.DAT": b"effects" * 40,
        "MEDIA/SKILLS/EMBER/EMBERBEAM.LAYOUT": b"<layout/>",
    }
    directory = tmp_path / "PAKS"
    man_path = write_synthetic_pak(directory, files)
    return PakIndex.read(man_path), directory, files


# --------------------------------------------------------------------------
# Reading the manifest
# --------------------------------------------------------------------------


def test_the_manifest_lists_every_file(tmp_path):
    files = {"MEDIA/A.DAT": b"one", "MEDIA/B/C.DAT": b"two"}
    index = PakIndex.read(write_synthetic_pak(tmp_path / "PAKS", files))

    assert len(index) == 2
    assert "MEDIA/A.DAT" in index
    assert "MEDIA/B/C.DAT" in index
    assert index.root == "MEDIA/"


def test_lookups_ignore_case(tmp_path):
    """Mods are inconsistent about it and the game does not care."""
    index = PakIndex.read(
        write_synthetic_pak(tmp_path / "PAKS", {"MEDIA/Units/Items/Sword.DAT": b"x"})
    )

    assert index.get("media/units/items/sword.dat") is not None
    assert index.get("MEDIA/UNITS/ITEMS/SWORD.DAT") is not None
    assert "MeDiA/uNiTs/ItEmS/sWoRd.DaT" in index


def test_a_dot_dat_filter_is_what_keeps_the_layouts_out(tmp_path):
    """The prefixes sweep up files that are not DAT at all.

    ``MEDIA/SKILLS`` holds a couple of thousand ``.LAYOUT`` files -- CEGUI
    window layouts, a different format entirely, which fail on the first count
    they read.  Filtering on the extension is what keeps them out of the load;
    without it they arrive as 2,145 parse failures.
    """
    index = PakIndex.read(
        write_synthetic_pak(
            tmp_path / "PAKS",
            {
                "MEDIA/SKILLS/EMBER/EMBERBEAM.DAT": b"dat",
                "MEDIA/SKILLS/EMBER/EMBERBEAM.LAYOUT": b"layout",
            },
        )
    )

    found = [entry.name for entry in index.matching(["MEDIA/SKILLS/"])]
    assert len(found) == 2, "matching() is about prefixes, not extensions"
    assert len([n for n in found if n.upper().endswith(".DAT")]) == 1


def test_matching_returns_the_whole_subtree(tmp_path):
    index = PakIndex.read(
        write_synthetic_pak(
            tmp_path / "PAKS",
            {
                "MEDIA/UNITS/ITEMS/A.DAT": b"a",
                "MEDIA/UNITS/ITEMS/DEEP/B.DAT": b"b",
                "MEDIA/UNITS/MONSTERS/C.DAT": b"c",
            },
        )
    )

    names = sorted(entry.name for entry in index.matching(["MEDIA/UNITS/ITEMS/"]))
    assert names == ["MEDIA/UNITS/ITEMS/A.DAT", "MEDIA/UNITS/ITEMS/DEEP/B.DAT"]


def test_matching_several_prefixes_at_once(tmp_path):
    index = PakIndex.read(
        write_synthetic_pak(
            tmp_path / "PAKS",
            {"MEDIA/A/X.DAT": b"x", "MEDIA/B/Y.DAT": b"y", "MEDIA/C/Z.DAT": b"z"},
        )
    )

    found = {entry.name for entry in index.matching(["MEDIA/A/", "MEDIA/C/"])}
    assert found == {"MEDIA/A/X.DAT", "MEDIA/C/Z.DAT"}


def test_a_manifest_listing_nothing_is_an_error(tmp_path):
    """An empty index is a broken archive, not an empty one.

    Every Torchlight install has tens of thousands of files in it, so a
    manifest that claims none is a file that did not parse -- better said out
    loud than discovered later as a tooltip with nothing in it.
    """
    man_path = write_synthetic_pak(
        tmp_path / "PAKS", {"MEDIA/A.DAT": b"x"}, folders=0
    )

    with pytest.raises(PakError, match="no files"):
        PakIndex.read(man_path)


# --------------------------------------------------------------------------
# Reading the archive
# --------------------------------------------------------------------------


def test_each_file_comes_back_as_its_own_bytes(pak):
    """The test that would catch an off-by-one in the block header.

    Every payload is different, so a reader that seeks to the wrong place
    returns a different entry's bytes and this fails.  Checking only that
    something came back would pass.
    """
    index, directory, files = pak
    with PakFile(directory / "DATA.PAK", index) as archive:
        for name, expected in files.items():
            assert archive.read(name) == expected, name


def test_a_block_header_is_not_mistaken_for_payload(pak):
    """The four bytes before the payload are the header, not the data."""
    index, directory, _ = pak
    with PakFile(directory / "DATA.PAK", index) as archive:
        got = archive.read("MEDIA/EFFECTSLIST.DAT")
    assert got == b"effects" * 40
    assert not got.startswith(b"\x00\x00\x00\x00")


def test_reading_something_not_in_the_archive_says_so(pak):
    index, directory, _ = pak
    with PakFile(directory / "DATA.PAK", index) as archive:
        with pytest.raises(PakError, match="MISSING"):
            archive.read("MEDIA/MISSING.DAT")


def test_a_truncated_archive_is_an_error_not_a_short_read(tmp_path):
    """A half-copied archive must not come back as a plausible short file."""
    # Incompressible on purpose: a payload of repeated bytes would deflate to
    # a few dozen, and the truncated archive would still hold all of it.
    payload = bytes(random.Random(0).randrange(256) for _ in range(5000))
    man_path = write_synthetic_pak(tmp_path / "PAKS", {"MEDIA/BIG.DAT": payload})
    archive_path_ = tmp_path / "PAKS" / "DATA.PAK"
    archive_path_.write_bytes(archive_path_.read_bytes()[:40])

    index = PakIndex.read(man_path)
    with PakFile(archive_path_, index) as archive:
        with pytest.raises(PakError, match="wanted"):
            archive.read("MEDIA/BIG.DAT")


def test_an_entry_pointing_before_the_archive_is_refused(tmp_path):
    """Directory entries do this, which is why the reader skips them.

    Rather than trust that they are always skipped, the read itself refuses an
    offset that would seek to a negative position -- which is an ``OSError``
    from the file object, not something a caller would think to catch.
    """
    man_path = write_synthetic_pak(tmp_path / "PAKS", {"MEDIA/A.DAT": b"x"})
    index = PakIndex.read(man_path)
    index.entries["MEDIA/ZERO.DAT"] = PakEntry(
        name="MEDIA/ZERO.DAT", offset=0, size=0, crc=0, kind=0
    )

    with PakFile(tmp_path / "PAKS" / "DATA.PAK", index) as archive:
        with pytest.raises(PakError, match="before the archive starts"):
            archive.read("MEDIA/ZERO.DAT")


def test_directories_are_not_listed_as_files(tmp_path):
    """A folder's entry is its name with a slash on the end and no bytes.

    The real manifest indexes folders alongside files -- 3,402 of them.  Each
    is just a name ending in a slash, and each points at offset 0, which is
    the manifest's own header and not anywhere in the archive.  Keeping them
    would put entries in the index that cannot be read.
    """
    index = PakIndex.read(
        write_synthetic_pak(
            tmp_path / "PAKS",
            {"MEDIA/A.DAT": b"x", "MEDIA/SUBDIR/": b""},
        )
    )

    assert "MEDIA/A.DAT" in index
    assert "MEDIA/SUBDIR/" not in index
    assert not [name for name in index.entries if name.endswith("/")]


def test_open_archive_hands_out_one_index(pak, tmp_path):
    """Both halves must describe the same archive, not two copies of it.

    The read at the end is the point.  ``PakFile`` opens its handle lazily, so
    an assertion about the index alone passes even when ``open_archive`` has
    derived a filename that does not exist -- which it did: it stripped
    ``len(".pak.man")`` bytes off ``"DATA.PAK.MAN"`` and asked for ``"DATA"``.
    """
    index, _, files = pak
    again, archive = open_archive(tmp_path / "PAKS" / "DATA.PAK.MAN")
    try:
        assert archive.index is again
        assert len(again) == len(index)
        assert archive.path.name == "DATA.PAK"
        assert archive.read("MEDIA/EFFECTSLIST.DAT") == files["MEDIA/EFFECTSLIST.DAT"]
    finally:
        archive.close()


# --------------------------------------------------------------------------
# The real archive (skipped when the game is not installed)
# --------------------------------------------------------------------------


_INSTALL = find_install()

needs_game = pytest.mark.skipif(
    _INSTALL is None, reason="Torchlight II is not installed on this machine"
)


@needs_game
def test_the_real_manifest_parses():
    index = PakIndex.read(archive_path(_INSTALL))

    assert index.version == 2
    assert index.root == "MEDIA/"
    assert len(index) > 50_000, "the shipped archive holds tens of thousands"


@needs_game
def test_the_real_manifest_names_no_directories():
    """Whatever the manifest's folder entries look like, none survive."""
    index = PakIndex.read(archive_path(_INSTALL))
    stray = [name for name in index.entries if name.endswith("/")]
    assert not stray, f"{len(stray)} directory entries were kept"


@needs_game
def test_a_real_file_inflates_to_the_size_the_manifest_promised():
    """The reader checks this itself; the point is that it holds for the game's
    own archive rather than only for a fixture built to agree with it."""
    index = PakIndex.read(archive_path(_INSTALL))
    pak_path = archive_path(_INSTALL).with_name("DATA.PAK")

    with PakFile(pak_path, index) as archive:
        for name in (
            "MEDIA/EFFECTSLIST.DAT",
            "MEDIA/INVENTORY/ARMOR.DAT",
            "MEDIA/UNITS/ITEMS/SWORDS/BASE_SWORD.DAT",
        ):
            data = archive.read(name)
            assert data, name
            assert len(data) == index.get(name).size, name
