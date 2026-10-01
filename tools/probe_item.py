"""Walk one stash partition field by field, showing offsets and values.

When an item fails to parse, the useful question is never "did it fail" but
"at which field did the reader and the bytes disagree".  This prints the
fixed-size preamble with offsets so a layout difference is visible directly,
then reports what the tail does.

Usage::

    python tools/probe_item.py <stash-file> <partition-index> [--hex START END]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash import read_stash_file  # noqa: E402
from tl2stash.binary import ParseError, Reader  # noqa: E402
from tl2stash import item as item_mod  # noqa: E402


def hexdump(blob: bytes, start: int, end: int) -> None:
    start = max(0, start)
    end = min(len(blob), end)
    for off in range(start, end, 16):
        chunk = blob[off : off + 16]
        text = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
        print(f"{off:5}  {chunk.hex(' '):<47}  {text}")


def walk_preamble(blob: bytes) -> int:
    """Print the fixed-layout fields; return the offset of the tail."""
    r = Reader(blob)

    def field(label: str, reader_fn, fmt=str):
        pos = r.pos
        value = reader_fn()
        print(f"{pos:5}  {label:<20} {fmt(value)}")
        return value

    field("lead u8", r.u8, lambda v: f"0x{v:02X}")
    field("guid u64", r.u64, lambda v: f"{v:016X}")
    field("name", lambda: r.torch_text(), repr)
    field("prefix", lambda: r.torch_text(), repr)
    field("suffix", lambda: r.torch_text(), repr)
    field("random_id 24B", lambda: r.take(24), lambda v: v[:8].hex(" "))
    field("bytes0 u32", r.u32, lambda v: f"{v} (0x{v:08X})")
    field("bytes1 29B", lambda: r.take(29), lambda v: f"{v.hex(' ')}")
    field("num_enchants u32", r.u32)
    field("  [location]", lambda: (r.u16(), r.u16()), lambda v: f"slot={v[0]} container={v[1]}")
    field("bytes2 6B", lambda: r.take(6), lambda v: v.hex(" "))
    field("identified u8", r.u8)
    field("bytes3 8B", lambda: r.take(8), lambda v: v.hex(" "))
    field("bytes4 80B", lambda: r.take(80), lambda v: v[:20].hex(" ") + " ...")
    field("level u32", r.u32)
    field("quantity u32", r.u32, lambda v: f"{v} (as float {_as_float(v)})")
    field("num_sockets u32", r.u32)
    field("gem count u32", r.u32)
    field("bytes6 4B", lambda: r.take(4), lambda v: v.hex(" "))
    field("max_damage u32", r.u32)
    field("armor u32", r.u32)
    field("bytes7 4B", lambda: r.take(4), lambda v: v.hex(" "))
    field("bytes8 12B", lambda: r.take(12), lambda v: v.hex(" "))
    field("num_dmg_types u16", r.u16)
    return r.pos


def _as_float(word: int) -> str:
    import struct

    return f"{struct.unpack('<f', struct.pack('<I', word))[0]:g}"


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    path, index = argv[1], int(argv[2])

    stash = read_stash_file(path)
    entry = stash.entries[index]
    blob = entry.blob
    print(f"partition {index}: {len(blob)} bytes")
    print(f"parse result   : {'OK' if entry.ok else 'FAILED: ' + str(entry.error)}")
    print()

    print("-- preamble " + "-" * 50)
    try:
        tail = walk_preamble(blob)
    except ParseError as exc:
        print(f"  preamble overran: {exc}")
        return 0
    print(f"{tail:5}  [tail begins here, {len(blob) - tail} bytes]")

    print()
    print("-- tail attempts " + "-" * 44)
    r = Reader(blob, tail)
    n_types = blob[tail - 2] | (blob[tail - 1] << 8)
    for strategy in item_mod._TAIL_STRATEGIES:
        r.pos = tail
        try:
            added = strategy(r, n_types)
            after_dmg = r.pos
            effects = item_mod._read_effect_lists(r)
            after_eff = r.pos
            effects2 = item_mod._read_effect_lists(r)
            after_eff2 = r.pos
            triggers = r.list_of(lambda: r.torch_text())
            stats = r.list_of(lambda: item_mod.Stat(r.u64(), r.take(4)))
            print(
                f"  {strategy.__name__:<22} OK  added={len(added)} "
                f"effects={len(effects)} effects2={len(effects2)} "
                f"triggers={len(triggers)} stats={len(stats)} "
                f"ends at {r.pos} ({len(blob) - r.pos} left)"
            )
        except ParseError as exc:
            print(f"  {strategy.__name__:<22} FAIL at {r.pos}: {exc}")

    if "--hex" in argv:
        i = argv.index("--hex")
        start, end = int(argv[i + 1]), int(argv[i + 2])
        print()
        print(f"-- bytes {start}..{end} " + "-" * 40)
        hexdump(blob, start, end)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
