"""Where the tool keeps what it owns.

Two shapes of the tool, two folders.  From a checkout it is ``var/`` in the
repository, beside the code that wrote it -- which is also where every tool in
``tools/`` writes, and where a developer looks for it.  Frozen into an
executable it is ``%LOCALAPPDATA%\\Torchlight2ItemAssistant``, and that is not
a matter of taste.  A bundled executable unpacks itself into a temporary
folder that Windows empties, so a database written beside the code would be
gone by the next launch; and the folder a player puts an executable in is
often one an ordinary process may not write to at all -- Program Files.  The
player's own profile is the one place that is always both writable and theirs.

This is the folder that matters most in the whole tool: the registry is the
player's items, and in the vacuum model sometimes the *only* copy of them.  A
tool that lost that folder would lose what the stash gave up.  So it is worth
being boring about, and there is one function here rather than a default
spelled out at each of the two places that need it.

``TL2IA_DATA`` moves the folder, for a player who keeps the tool on a stick
and wants the data beside it, and for a test that wants a folder of its own
without going through a window.

Nothing here creates the folder.  Both writers already make what they need --
:class:`tl2stash.registry.Registry` on open and :meth:`app.settings.Settings.set`
on the first remembered choice -- and a function that made a folder as a side
effect of being asked where the folder is would quietly create directories for
every caller that only meant to ask, tests included.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = ["APP_NAME", "ENV", "data_dir"]

#: One name for the tool wherever a person meets it: the executable, the
#: folder in the player's profile, and the release the two arrive in.
APP_NAME = "Torchlight2ItemAssistant"

#: The one environment variable that moves the folder.
ENV = "TL2IA_DATA"


def data_dir() -> Path:
    """The folder the tool owns, as a path that may not exist yet.

    Answered fresh on every call rather than kept in a module constant: the
    two callers ask once, at the moment a window or a help text is built, and
    a constant would freeze the answer at import -- before a test has had its
    say about ``sys.frozen`` or the environment.
    """
    chosen = os.environ.get(ENV)
    if chosen:
        return Path(chosen)

    if getattr(sys, "frozen", False):
        # Set by PyInstaller in the executable, and by nothing else.  A
        # source run of this tool is never frozen, so ``var/`` below is a
        # checkout's answer and this is a player's.
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME
        # LOCALAPPDATA is set on every Windows this tool runs on; the
        # fallback is here so that a stripped environment costs a database in
        # an unusual place rather than a crash at launch.
        return Path.home() / "AppData" / "Local" / APP_NAME

    return Path(__file__).resolve().parent.parent / "var"
