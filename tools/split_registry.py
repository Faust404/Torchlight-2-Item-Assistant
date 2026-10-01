"""Move the single old registry into one database per stash.

Usage::

    python tools/split_registry.py --dry-run   # say what would happen
    python tools/split_registry.py             # do it

The old ``var/items.db`` is left where it is.  It costs a few hundred
kilobytes and it is the only copy of anything that went wrong, which is a
trade worth making exactly once -- after this, ``var/items-<kind>-<id>.db``
is what the app reads.

Nothing is deleted and nothing is rescanned: rows are copied verbatim, and
each target is checked to hold the same items with the same statuses before
the run is allowed to finish.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash.migrate import split_registry  # noqa: E402

VAR_DIR = Path(__file__).resolve().parent.parent / "var"
DEFAULT_DB = VAR_DIR / "items.db"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="the registry to split")
    parser.add_argument("--out", type=Path, default=VAR_DIR, help="where to write the pieces")
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would happen, write nothing"
    )
    parser.add_argument(
        "--keep-original", action="store_true", default=True,
        help="leave the original file in place (this is the default)",
    )
    args = parser.parse_args(argv[1:])

    if not args.db.is_file():
        print(f"no registry at {args.db}", file=sys.stderr)
        return 2

    if not args.dry_run:
        backup = args.db.with_suffix(args.db.suffix + ".pre-split")
        if not backup.exists():
            shutil.copy2(args.db, backup)
            print(f"backed up  {args.db.name} -> {backup.name}")

    report = split_registry(args.db, args.out, dry_run=args.dry_run)

    for old, new in sorted(report.renamed.items()):
        print(f"renamed    {old}\n        -> {new}")
    print()
    for key, path in sorted(report.written.items()):
        verb = "would write" if args.dry_run else "wrote"
        print(f"{verb:>11}  {path.name}   {report.counts[key]} items")

    if report.orphans:
        print()
        print(f"{len(report.orphans)} item(s) name no stash and were not filed:")
        for fingerprint in report.orphans[:10]:
            print(f"    {fingerprint}")
        print("  (they are still in the original database)")

    print()
    print(f"{'would move' if args.dry_run else 'moved'}: {report.total} items")
    if not args.dry_run:
        print(f"the original is untouched at {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
