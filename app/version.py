"""The tool's version, in one place.

Three readers, and all three want the same string: the spec that builds the
executable stamps it into the file's Windows properties, so that a player can
right-click the download and read what they have; the release workflow
compares it against the tag it was pointed at and refuses to build a release
whose tag disagrees with the code inside it; and ``--version`` prints it for
someone running from a checkout.

Kept free of imports on purpose.  The spec loads this file by path, before the
tool's package is on ``sys.path`` at all, and a version is a fact about the
build rather than a thing that should be able to fail to import.
"""

from __future__ import annotations

__all__ = ["__version__"]

#: Major.minor.patch, and the tag is ``v`` in front of it.  The first two
#: move when the player can tell the difference; the third, for a fix.
__version__ = "0.1.5"
