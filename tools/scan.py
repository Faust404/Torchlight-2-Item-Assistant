"""Scan every shared stash on this machine into the registry.

Usage::

    python tools/scan.py [--db PATH] [--file PATH]...

With no ``--file`` it scans every stash it can find, vanilla and modded.
Run it twice and the second run should report zero new items -- that is the
real test of the fingerprinting.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash import read_stash_file  # noqa: E402
from tl2stash.registry import Registry  # noqa: E402
from tl2stash.saves import SAVE_ROOT, find_save_locations  # noqa: E402

DEFAULT_DB = Path(__file__).resolve().parent.parent / "var" / "items.db"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--file", type=Path, action="append", default=None,
        help="scan this stash file instead of auto-discovery (repeatable)",
    )
    args = parser.parse_args(argv[1:])

    if args.file:
        targets = [(str(path), path) for path in args.file]
    else:
        locations = find_save_locations()
        if not locations:
            print(f"no shared stash files found under {SAVE_ROOT}", file=sys.stderr)
            return 2
        targets = [(str(loc), loc.path) for loc in locations]

    with Registry(args.db) as registry:
        for label, path in targets:
            print(f"== {label}")
            stash = read_stash_file(path)
            result = registry.scan(stash, source=label)
            print(f"   {result.summary}")
            for item in result.added:
                print(
                    f"   + lvl {item.level:3}  {item.display_name}"
                    f"   [container {item.location.container}"
                    f" slot {item.location.slot_index}]"
                )
            if result.vanished:
                print(f"   - {len(result.vanished)} item(s) no longer present")
            for entry in stash.failed:
                print(f"   ! unparseable partition {entry.index}: {entry.error}")

        print()
        print(f"registry: {args.db}")
        print(f"distinct items: {len(registry.rows())}  (copies: {registry.item_count()})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
