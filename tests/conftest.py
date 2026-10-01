"""Safety net for a test suite that is capable of writing to save files.

This tool's job is to modify a file the player cares about, which means a
mistake in a test is not a failed assertion -- it is the player's stash.  That
is not hypothetical: an earlier version of these tests constructed the window
with a path it did not honour, the window fell back to the first save it could
find, and a test that meant to absorb four synthetic items emptied a real
stash instead.

So writes are fenced.  Every function that can write a stash file is wrapped
for the duration of a test and refuses a path outside that test's temporary
directory.  The fence is the point: it turns "a test wandered into the
player's Documents folder" from silent data loss into a loud failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tl2stash.archive as _archive  # noqa: E402
import tl2stash.service as _service  # noqa: E402

_WRITERS = ("archive_stash", "restore_items")


@pytest.fixture(autouse=True)
def no_writes_outside_tmp(tmp_path, monkeypatch):
    """Refuse to write any stash file that is not inside this test's tmp dir."""

    allowed = tmp_path.resolve()

    def guard(name: str, original):
        def wrapper(path, *args, **kwargs):
            target = Path(path).resolve()
            if target != allowed and allowed not in target.parents:
                raise AssertionError(
                    f"{name}() was asked to write {target}, which is outside "
                    f"the test's temporary directory. A test must never "
                    f"modify a real save file."
                )
            return original(path, *args, **kwargs)

        wrapper.__name__ = name
        return wrapper

    # Patch where each is *used*, not only where it is defined: these modules
    # did ``from .archive import ...``, so rebinding the name in archive.py
    # would leave the already-imported references pointing at the original.
    for module in (_archive, _service):
        for name in _WRITERS:
            if hasattr(module, name):
                monkeypatch.setattr(module, name, guard(name, getattr(module, name)))
