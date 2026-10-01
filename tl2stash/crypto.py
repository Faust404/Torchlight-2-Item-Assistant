"""The save-file envelope: scrambling and checksum.

Torchlight 2 save files (including ``sharedstash_v2.bin``) are stored as::

    u32  version
    u8   dummy
    u32  checksum          -- over the *plaintext* body
    ...  scrambled body ...
    u32  file size         -- 4 + 1 + 4 + 4 + len(body)

The body is scrambled by a mirrored-nibble transform from Jonathan Gevaryahu
("Lord Nightmare")'s original C.  FNIStash implements it in
``FNIStash.File.Crypto``; the independent reverse-engineering in
heiybb/tl2-mikuro-runtime (``hook_savefix.cpp``) describes the identical
transform and checksum, which is a strong cross-check on both.

FNIStash reads the stored checksum and throws it away; we keep it, because
recomputing it over a descrambled body and comparing is the cheapest proof
that the descrambling is correct.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

__all__ = [
    "CS_SEED",
    "SaveFile",
    "checksum",
    "descramble",
    "scramble",
    "read_save_file",
    "write_save_file",
]

#: Rolling-checksum seed.  0x14D3 == 5331, matching mikuro-runtime's
#: ``h = 5331; h = 33 * h + byte``.
CS_SEED = 0x14D3

_HEADER = struct.Struct("<IBI")  # version, dummy, checksum
_SIZE = struct.Struct("<I")


def checksum(body: bytes) -> int:
    """TL2's rolling checksum: ``acc = acc * 33 + byte`` from seed 0x14D3."""
    acc = CS_SEED
    for byte in body:
        acc = (acc * 33 + byte) & 0xFFFFFFFF
    return acc


def descramble(data: bytes) -> bytes:
    """Undo the save-file scrambling.

    Each output byte is built from a forward byte and its mirror image:
    the high nibble comes from the reverse byte's low nibble, the low nibble
    from the forward byte's high nibble -- then the result is complemented,
    except for 0x00 and 0xFF which pass through uncomplemented.
    """
    n = len(data)
    reverse = data[::-1]
    out = bytearray(n)
    for i in range(n):
        fwd = data[i]
        rev = reverse[i]
        byte = ((rev & 0x0F) << 4) | ((fwd & 0xF0) >> 4)
        out[i] = byte if byte in (0x00, 0xFF) else byte ^ 0xFF
    return bytes(out)


def scramble(data: bytes) -> bytes:
    """Inverse of :func:`descramble` -- what gets written back to disk."""
    n = len(data)
    reverse = data[::-1]
    out = bytearray(n)
    for i in range(n):
        fwd = data[i]
        rev = reverse[i]
        fwd_low = fwd & 0x0F
        rev_high = (rev & 0xF0) >> 4
        high = fwd_low if fwd in (0x00, 0xFF) else fwd_low ^ 0x0F
        low = rev_high if rev in (0x00, 0xFF) else rev_high ^ 0x0F
        out[i] = (high << 4) | low
    return bytes(out)


@dataclass
class SaveFile:
    """A descrambled save container."""

    version: int
    dummy: int
    stored_checksum: int
    body: bytes
    stored_size: int
    path: str | None = None

    @property
    def computed_checksum(self) -> int:
        return checksum(self.body)

    @property
    def checksum_ok(self) -> bool:
        return self.stored_checksum == self.computed_checksum

    @property
    def size_ok(self) -> bool:
        return self.stored_size == 13 + len(self.body)


def read_save_file(path) -> SaveFile:
    """Read and descramble a TL2 save file from disk."""
    with open(path, "rb") as handle:
        raw = handle.read()
    if len(raw) < 13:
        raise ValueError(f"{path}: too short to be a save file ({len(raw)} bytes)")

    version, dummy, stored_checksum = _HEADER.unpack_from(raw, 0)
    (stored_size,) = _SIZE.unpack_from(raw, len(raw) - 4)
    body = descramble(raw[9:-4])
    return SaveFile(
        version=version,
        dummy=dummy,
        stored_checksum=stored_checksum,
        body=body,
        stored_size=stored_size,
        path=str(path),
    )


def write_save_file(path, save: SaveFile) -> None:
    """Re-scramble and write a save file back out."""
    body = save.body
    blob = (
        _HEADER.pack(save.version, save.dummy, checksum(body))
        + scramble(body)
        + _SIZE.pack(13 + len(body))
    )
    with open(path, "wb") as handle:
        handle.write(blob)
