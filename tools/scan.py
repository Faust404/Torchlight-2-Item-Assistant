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
from tl2stash.saves import SAVE_ROOT, SaveLocation, find_save_locations  # noqa: E402

VAR_DIR = Path(__file__).resolve().parent.parent / "var"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, default=None,
        help="scan every stash into this one database, instead of giving each "
             "stash its own file under var/",
    )
    parser.add_argument(
        "--file", type=Path, action="append", default=None,
        help="scan this stash file instead of auto-discovery (repeatable)",
    )
    args = parser.parse_args(argv[1:])

    if args.file:
        # Identity comes from the same derivation discovery uses, so scanning
        # a file by hand and scanning it through the app name it identically.
        # They did not, before: the two routes produced two registry keys for
        # one stash, and neither could see the other's items.
        targets = [SaveLocation.at(path) for path in args.file]
    else:
        targets = find_save_locations()
        if not targets:
            print(f"no shared stash files found under {SAVE_ROOT}", file=sys.stderr)
            return 2

    for location in targets:
        db = args.db if args.db is not None else VAR_DIR / location.db_name
        print(f"== {location.label}   [{location.key}]")
        try:
            stash = read_stash_file(location.path)
        except OSError as exc:
            print(f"   ! could not read {location.path}: {exc}")
            continue

        with Registry(db) as registry:
            result = registry.scan(stash, source=location.key)
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

            print(f"   database: {db}")
            print(
                f"   distinct items: {len(registry.rows())}"
                f"  (copies: {registry.item_count()})"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
