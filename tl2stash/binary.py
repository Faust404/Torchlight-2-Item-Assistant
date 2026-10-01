"""Byte-level reader for Torchlight 2 binary structures.

Direct port of the "Get" half of FNIStash's ``FNIStash.File.General``.  The
important behaviours to preserve from the Haskell original:

* Reading past the end of the buffer is a hard error, never a zero fill.
* ``<|>`` in FNIStash's strict Get monad restarts from the position the parse
  began at, so callers save ``pos`` and restore it on ``ParseError``.
* Torchlight strings are a character count followed by that many UTF-16LE
  code units -- the count is a *character* count, so the byte length is
  double it.  Kicking this up to a byte count silently misparses.
"""

from __future__ import annotations

import struct

__all__ = ["ParseError", "Reader"]


class ParseError(Exception):
    """The byte stream does not match the structure being read."""


class Reader:
    """A cursor over an immutable buffer."""

    __slots__ = ("data", "pos")

    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    # -- positioning ------------------------------------------------------

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def at_end(self) -> bool:
        return self.pos >= len(self.data)

    # -- primitives -------------------------------------------------------

    def take(self, n: int) -> bytes:
        if n < 0:
            raise ParseError(f"negative length {n}")
        end = self.pos + n
        if end > len(self.data):
            raise ParseError(
                f"wanted {n} bytes at offset {self.pos}, "
                f"only {self.remaining()} left"
            )
        chunk = self.data[self.pos : end]
        self.pos = end
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return struct.unpack_from("<H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack_from("<I", self.take(4))[0]

    def u64(self) -> int:
        return struct.unpack_from("<Q", self.take(8))[0]

    # -- Torchlight strings ----------------------------------------------

    def torch_text(self) -> str:
        """u16 character count, then that many UTF-16LE code units."""
        n = self.u16()
        return self.take(n * 2).decode("utf-16-le", errors="replace")

    def torch_text_1byte(self) -> str:
        """Same, but with a u8 character count (used for effect extras)."""
        n = self.u8()
        return self.take(n * 2).decode("utf-16-le", errors="replace")

    # -- length-prefixed lists -------------------------------------------

    def count(self) -> int:
        """A u32 list count, sanity checked against the bytes available.

        FNIStash just calls ``replicateM``: a corrupt count eventually runs
        the buffer dry and the parse fails.  Checking up front reaches the
        same verdict without looping four billion times first.
        """
        n = self.u32()
        if n > self.remaining():
            raise ParseError(
                f"list count {n} exceeds {self.remaining()} remaining bytes"
            )
        return n

    def list_of(self, read_one):
        return [read_one() for _ in range(self.count())]
