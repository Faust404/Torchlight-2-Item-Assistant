"""Dump a TL2 shared stash file: validate the crypto, list the items.

Usage::

    python tools/dump_stash.py [path/to/sharedstash_v2.bin]

With no argument it uses the vanilla Steam save.  The validation section is
the point: if the checksum we compute over the descrambled body matches the
one stored in the file, the descrambling is provably byte-correct, and if
re-scrambling reproduces the original bytes then the writer works too.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash import descramble, read_save_file, read_stash_file, scramble  # noqa: E402
from tl2stash.saves import SAVE_ROOT, STASH_FILENAME  # noqa: E402

#: The author's own vanilla Steam save -- the one this probe defaulted to
#: before it was a tool -- under whichever Documents the tool found, which is
#: what makes it work on a machine whose Documents folder has moved.
DEFAULT = SAVE_ROOT / "save" / "76561198328811052" / STASH_FILENAME


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2

    original = path.read_bytes()
    save = read_save_file(path)
    print(f"file        : {path}")
    print(f"size        : {len(original):,} bytes")
    print(f"version     : 0x{save.version:08X}")
    print(f"dummy       : 0x{save.dummy:02X}")
    print(f"body        : {len(save.body):,} bytes")
    print()

    print("-- validation " + "-" * 50)
    print(
        f"checksum    : stored 0x{save.stored_checksum:08X} "
        f"computed 0x{save.computed_checksum:08X} "
        f"[{'OK' if save.checksum_ok else 'MISMATCH'}]"
    )
    print(
        f"size field  : stored {save.stored_size:,} "
        f"expected {13 + len(save.body):,} "
        f"[{'OK' if save.size_ok else 'MISMATCH'}]"
    )
    rescrambled = (
        save.version.to_bytes(4, "little")
        + bytes([save.dummy])
        + save.stored_checksum.to_bytes(4, "little")
        + scramble(save.body)
        + save.stored_size.to_bytes(4, "little")
    )
    print(
        f"round trip  : re-scrambled body "
        f"{'is byte-identical to the original file' if rescrambled == original else 'DIFFERS'}"
        f" [{'OK' if rescrambled == original else 'FAIL'}]"
    )
    print(
        f"symmetry    : descramble(scramble(x)) == x "
        f"[{'OK' if descramble(scramble(save.body)) == save.body else 'FAIL'}]"
    )
    print()

    stash = read_stash_file(path)
    print(f"-- items: {len(stash.items)} parsed, {len(stash.failed)} failed " + "-" * 30)
    for entry in stash.entries:
        if not entry.ok:
            print(f"[{entry.index:3}] PARSE FAILED: {entry.error}")
            continue
        item = entry.item
        loc = item.location
        where = (
            "socketed"
            if loc.in_socket
            else f"container {loc.container} slot {loc.slot_index}"
        )
        flags = []
        if item.quantity > 1:
            flags.append(f"x{item.quantity}")
        if not item.identified:
            flags.append("unidentified")
        if item.num_sockets:
            flags.append(f"{item.num_sockets} socket(s)")
        if item.num_enchants:
            flags.append(f"{item.num_enchants} enchant(s)")
        if item.effects or item.effects2:
            flags.append(f"{len(item.effects) + len(item.effects2)} effect(s)")
        if item.stats:
            flags.append(f"{len(item.stats)} stat(s)")
        suffix = f"  ({', '.join(flags)})" if flags else ""
        print(
            f"[{entry.index:3}] lvl {item.level:3}  {item.display_name}{suffix}\n"
            f"      {where}  guid {item.guid:016X}  blob {len(item.raw)}B"
        )

    if stash.failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
