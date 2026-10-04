"""Where the tool keeps what it owns.

Two shapes of the tool, two folders, for two different reasons.

From a checkout it is ``var/`` in the repository, beside the code that wrote
it -- which is also where every tool in ``tools/`` writes, and where a
developer looks for it.  A checkout is nobody's copy of the game, and a
developer running the parser should not be reading the collection they
actually play with.

Frozen into an executable it is ``tl2ia_save/`` inside the game's own
Torchlight 2 folder, beside ``save/`` and ``modsave/``.  That is where it
belongs rather than a matter of taste: the registry holds the items the stash
gave up, and this is the one folder the player already knows how to find,
already backs up, and already carries to another machine -- back up the game's
folder and the items come with the saves they came out of.  The game itself
scatters folders there (``mods``, ``logs``, ``guts``, ``settings.txt``), so
one more is nothing it has not seen.

That folder is also the only shape that *can* use it.  A bundled executable
unpacks itself into a temporary folder that Windows empties, so a database
written beside the code would be gone by the next launch; and the folder a
player puts an executable in is often one an ordinary process may not write
to at all -- Program Files.

The path is *derived* from ``tl2stash.saves.SAVE_ROOT`` rather than spelled
out again here, so the tool's folder follows the saves it belongs with: the
Documents folder Windows names -- or the one ``TL2IA_SAVES`` names -- decides
both, so a Documents folder redirected to OneDrive, saves on another account,
or saves on a stick all keep the database beside them instead of leaving it
behind in a profile folder the game no longer uses.

The folder may not exist yet, and making it is the writers' business rather
than this function's: :class:`tl2stash.registry.Registry` creates it on open
and :meth:`app.settings.Settings.set` on the first remembered choice.  A
function that made a folder as a side effect of being asked where the folder
is would quietly create directories for every caller that only meant to ask,
tests included.  On a machine where the game was never installed, the first
launch makes the whole chain under Documents -- which is exactly where the
game would have put its own.

``TL2IA_DATA`` moves the folder, for a player who keeps the tool on a stick
and wants the data beside it, and for a test that wants a folder of its own
without going through a window.  It overrides even ``TL2IA_SAVES``, which
moves this folder by moving the saves it follows: pointing the tool at saves
somewhere is a statement about the saves, and whoever also says where the
data goes has said the more specific thing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from tl2stash import saves

__all__ = ["APP_NAME", "ENV", "SAVE_FOLDER", "data_dir"]

#: One name for the tool wherever a person meets it: the executable, the
#: release it arrives in, and the window on the task bar.
APP_NAME = "Torchlight2ItemAssistant"

#: The tool's folder inside the game's own.  Lowercase with an underscore, to
#: sit quietly among the game's own ``save``, ``modsave``, ``mods`` and
#: ``logs`` rather than to stand out among them.
SAVE_FOLDER = "tl2ia_save"

#: The one environment variable that moves the folder.
ENV = "TL2IA_DATA"


def data_dir() -> Path:
    """The folder the tool owns, as a path that may not exist yet.

    Answered fresh on every call rather than kept in a module constant: the
    two callers ask once, at the moment a window or a help text is built, and
    a constant would freeze the answer at import -- before a test has had its
    say about ``sys.frozen``, the environment, or where the saves are.
    """
    chosen = os.environ.get(ENV)
    if chosen:
        return Path(chosen)

    if getattr(sys, "frozen", False):
        # Set by PyInstaller in the executable, and by nothing else.  A
        # source run of this tool is never frozen, so ``var/`` below is a
        # checkout's answer and this is a player's.  Read off the module
        # rather than imported as a name, so that the answer follows the
        # environment on every call instead of freezing at import.
        return saves.SAVE_ROOT / SAVE_FOLDER

    return Path(__file__).resolve().parent.parent / "var"
