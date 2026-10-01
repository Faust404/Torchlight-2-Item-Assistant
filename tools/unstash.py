"""Take items out of a stash file.

This is the operation that makes items disappear from the game.  It is also
the only thing in the project that writes to a save file, so it defaults to
showing you what it would do and requires --yes to actually do it.

Usage::

    python tools/unstash.py --list
    python tools/unstash.py --index 3 --dry-run
    python tools/unstash.py --index 3 --yes
    python tools/unstash.py --name "The Caliphaze" --yes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash import read_stash_file  # noqa: E402
from tl2stash.archive import archive_stash  # noqa: E402
from tl2stash.saves import live_location  # noqa: E402


def resolve_target(args) -> Path:
    if args.file:
        return Path(args.file)
    location = live_location()
    if location is None:
        raise SystemExit("no Torchlight 2 stash found; pass --file")
    print(f"using {location} (most recently written)")
    return location.path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path)
    parser.add_argument("--list", action="store_true", help="show the contents and exit")
    parser.add_argument("--index", type=int, action="append", default=[])
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true", help="actually write")
    args = parser.parse_args(argv[1:])

    path = resolve_target(args)
    stash = read_stash_file(path)
    print(f"{path}\n{len(stash.items)} items\n")

    for i, item in enumerate(stash.items):
        print(f"  [{i:3}] lvl {item.level:3}  {item.display_name}")

    if args.list:
        return 0

    targets = []
    for index in args.index:
        if not 0 <= index < len(stash.items):
            raise SystemExit(f"index {index} out of range")
        targets.append(stash.items[index])
    for name in args.name:
        matches = [i for i in stash.items if name.lower() in i.display_name.lower()]
        if not matches:
            raise SystemExit(f"no item matching {name!r}")
        targets.extend(matches)
    if args.all:
        targets = list(stash.items)

    if not targets:
        raise SystemExit("nothing selected; use --index, --name or --all")

    fingerprints = {i.fingerprint for i in targets}
    print(f"\n{len(fingerprints)} item(s) selected:")
    for item in targets:
        print(f"  - {item.display_name}")

    dry_run = args.dry_run or not args.yes
    if dry_run and not args.dry_run:
        print("\n(this is a preview; re-run with --yes to write)")

    report = archive_stash(path, fingerprints, dry_run=dry_run)
    if report.changed:
        print(f"\nremoved {len(report.removed)}, kept {report.kept}")
        print(f"backup: {report.backup}")
    elif report.removed:
        print(f"\nwould remove {len(report.removed)}, keep {report.kept} (nothing written)")
    else:
        print("\nnothing matched; file untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
