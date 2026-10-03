"""The handful of choices the tool remembers between runs.

Everything else the tool knows is a fact about an item or a stash, and lives
in the registry beside the save file it belongs to.  These are facts about the
*person* -- "stop warning me about this" -- and a second stash must not ask
again, so they are in neither registry.  One small JSON file beside them
instead, which is also what makes it legible: a choice the tool remembers for
the player should be one they can read, and delete, without a tool.

A file that is missing, unreadable, or written over by something else is not
an error -- it is the defaults.  A remembered choice is a convenience, and the
worst that a lost one can mean is being asked a question twice.
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = ["Settings"]


class Settings:
    """One JSON object, read once and written through on every change."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._values = self._read()

    def _read(self) -> dict:
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return values if isinstance(values, dict) else {}

    def get(self, name: str, default):
        """What this choice was set to, or ``default`` if it never was.

        A value of the wrong type answers the default as well, and that is not
        pedantry: the file is meant to be editable by hand, and a ``"yes"``
        where a boolean belongs is a choice the tool has no reading of.  Saying
        what the default says beats guessing at what was meant.
        """
        value = self._values.get(name, default)
        return value if isinstance(value, type(default)) else default

    def set(self, name: str, value) -> None:
        """Remember a choice, now rather than at exit.

        Written on the spot because the *next* run is the one that has to read
        it, and a tool the player closes at the end of a session should not
        lose a choice made at the start of it.  A write that fails -- a
        read-only folder, a file something else is holding open -- is
        swallowed: what a remembered choice is worth does not justify an error
        message about a checkbox, and the cost of forgetting is one question
        asked again.
        """
        self._values[name] = value
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._values, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
