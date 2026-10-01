"""The game's data archive: what it holds, and how to get one file out.

Torchlight 2 keeps its data in two files that sit next to each other:

``DATA.PAK.MAN``  the manifest -- a directory of every path in the archive
                  and where its bytes start.
``DATA.PAK``      the archive itself, 869 MB of them.

Each entry is separately deflated, so reading one file means seeking to its
offset and inflating a few kilobytes -- the size of the archive costs nothing
at read time.  That is what makes it practical to pull a few thousand data
files out at startup.

Format derived by reading the two files directly: the manifest's shape was
confirmed by decoding it and finding a plausible MEDIA/ tree (3,403 folders,
73,845 entries), and the per-entry layout by inflating entries and finding
well-formed DAT files.  Not transcribed from another implementation.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from .binary import ParseError, Reader

__all__ = ["PakEntry", "PakFile", "PakIndex", "PakError"]


class PakError(Exception):
    """The archive is not shaped the way the manifest says it is."""


@dataclass(frozen=True)
class PakEntry:
    """One file in the archive, as the manifest describes it."""

    name: str
    offset: int
    size: int  # the decoded size
    crc: int
    kind: int  # a small file-type code; 0 for the data files we read


class PakIndex:
    """The manifest, read into memory.

    Names are stored upper-cased.  The archive is case-insensitive in
    practice -- the game looks paths up regardless of case, and mods are
    inconsistent about it -- so normalising once here keeps every caller from
    having to remember.
    """

    __slots__ = ("version", "root", "entries", "path")

    def __init__(
        self, version: int, root: str, entries: dict[str, PakEntry], path: Path
    ) -> None:
        self.version = version
        self.root = root
        self.entries = entries
        self.path = path

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, name: str) -> bool:
        return name.upper() in self.entries

    def __iter__(self):
        return iter(self.entries.values())

    def get(self, name: str) -> PakEntry | None:
        return self.entries.get(name.upper())

    def matching(self, prefixes: tuple[str, ...] | list[str]) -> list[PakEntry]:
        """Every entry under any of ``prefixes``.

        The manifest lists 73,845 files and this tool wants about ten
        thousand of them.  Filtering here rather than inflating everything
        and deciding afterwards is the difference between reading 60 MB and
        reading 900 MB.
        """
        wanted = tuple(prefix.upper() for prefix in prefixes)
        return [
            entry
            for name, entry in self.entries.items()
            if name.startswith(wanted)
        ]

    @classmethod
    def read(cls, man_path: str | Path) -> "PakIndex":
        man_path = Path(man_path)
        reader = Reader(man_path.read_bytes())

        version = reader.u16()
        reader.u32()  # unknown; constant across the shipped archives
        root = reader.torch_text()
        reader.u32()  # unknown
        folder_count = reader.u32()

        entries: dict[str, PakEntry] = {}
        for _ in range(folder_count):
            folder = reader.torch_text()
            # A folder's own count is not sanity-checked against the bytes
            # left the way Reader.count does: entries are variable length, so
            # the remaining-bytes check would be meaningless here.
            entry_count = reader.u32()
            for _ in range(entry_count):
                crc = reader.u32()
                kind = reader.u8()
                name = reader.torch_text()
                offset = reader.u32()
                size = reader.u32()
                reader.u32()
                reader.u32()
                full = f"{folder}{name}"
                if full.endswith("/"):
                    # The manifest indexes folders as well as files -- 3,402
                    # of them.  A folder's entry is its name with a slash on
                    # the end, and it has no bytes: it points at offset 0,
                    # which is the manifest's own header rather than anything
                    # in the archive.  Keeping them would mean every walk had
                    # to remember to skip them, and reading one would seek to
                    # a negative offset.
                    continue
                entries[full.upper()] = PakEntry(
                    name=full, offset=offset, size=size, crc=crc, kind=kind
                )

        if not entries:
            raise PakError(f"{man_path} listed no files")
        return cls(version, root, entries, man_path)


class PakFile:
    """Random access into the archive.  Use as a context manager."""

    def __init__(self, pak_path: str | Path, index: PakIndex) -> None:
        self.path = Path(pak_path)
        self.index = index
        self._handle = None

    def __enter__(self) -> "PakFile":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    @property
    def handle(self):
        if self._handle is None:
            self._handle = open(self.path, "rb")
        return self._handle

    def read(self, name: str) -> bytes:
        """The decoded bytes of one file.

        The manifest points at the entry's payload, and the four bytes before
        it are the block header -- so the reader seeks to ``offset - 4`` and
        reads the header, the compressed length and the payload from there.
        """
        entry = self.index.get(name)
        if entry is None:
            raise PakError(f"{name} is not in {self.index.path.name}")
        if entry.offset < 4:
            raise PakError(f"{name} points at offset {entry.offset}, before the archive starts")

        handle = self.handle
        handle.seek(entry.offset - 4)
        block = handle.read(12)
        if len(block) < 12:
            raise PakError(f"{name}: truncated block header at {entry.offset - 4}")
        _header, decoded_size, encoded_size = struct.unpack("<III", block)

        if encoded_size == 0:
            return b""
        payload = handle.read(encoded_size)
        if len(payload) < encoded_size:
            raise PakError(f"{name}: wanted {encoded_size} bytes, got {len(payload)}")

        try:
            data = zlib.decompress(payload)
        except zlib.error as exc:
            raise PakError(f"{name}: could not inflate: {exc}") from exc

        if len(data) != decoded_size:
            raise ParseError(
                f"{name}: inflated to {len(data)} bytes, manifest says {decoded_size}"
            )
        return data


def open_archive(man_path: str | Path) -> tuple[PakIndex, PakFile]:
    """Read the manifest beside ``man_path``'s archive and return both.

    One index, shared: the manifest is 5.3 MB and parsing it twice to hand out
    two objects that describe the same file would be both slow and a trap --
    callers would compare ``index.entries`` against ``pak.index.entries`` and
    find they were never the same dict.
    """
    man_path = Path(man_path)
    # ``with_suffix("")`` drops the ".MAN": DATA.PAK.MAN -> DATA.PAK.  Not a
    # slice of the suffix's length, which is easy to get wrong in a way that
    # is invisible -- the archive handle opens lazily, so a wrong name here
    # does not fail until something tries to read.
    index = PakIndex.read(man_path)
    return index, PakFile(man_path.with_suffix(""), index)
