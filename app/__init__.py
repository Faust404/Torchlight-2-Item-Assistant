"""The desktop application.

Presentation only: every decision about the save format, the registry and the
file writes lives in :mod:`tl2stash`, which knows nothing about Qt and can be
tested without a display.  Nothing in here should need to know what a
fingerprint is beyond passing it back.
"""

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    from .__main__ import main as _main

    return _main(argv)
