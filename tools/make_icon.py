"""Draw the tool's icon and write it to ``app/icon.ico``.

The icon is drawn rather than shipped as a picture because it is made of
things the tool already has: the warm gold of a card's magic line and the
near-black of the wall behind it, and the face its own cards are set in,
Bitter, which travels in ``app/fonts``.  A file committed next to a generator
that can redraw it is one that can be corrected when the palette moves, and
this one will be drawn at seven sizes by hand rather than scaled down from
one big one: a 256 drawn and then shrunk to 16 is a smudge, and 16 is the
size Explorer actually uses.

Run it from the repository root:

    python tools/make_icon.py            # writes app/icon.ico
    python tools/make_icon.py --preview  # also writes var/icon-<size>.png

The preview writes to ``var/``, which is throwaway -- and that is the point:
an icon is a thing to look at, not to reason about.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Before Qt is imported: this runs headless and draws into an image, so there
# is nothing to show and no display to need.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QImage,
    QPainter,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.card import GOLD  # noqa: E402
from app.theme import FONT_DIR, WALL  # noqa: E402

#: Every size Windows asks for, in the order the ICO wants them.  The small
#: ones are the ones in use -- Explorer's list view, the taskbar -- and the
#: large ones only ever appear in a file's property sheet and on a desktop
#: set to extra-large icons.
SIZES = (16, 24, 32, 48, 64, 128, 256)

#: The mark: the tool's initials, as the user asked for them -- ``TL2``, the
#: name the executable and the window both carry.  One string at every size
#: rather than something cleverer small: a shape that is not the letters would
#: be a second identity to keep.
MARK = "TL2"

#: How much of the square the letters may take, and how round the corners
#: are.  The letters are *fitted* to these rather than set at a fixed
#: proportion of the square: three glyphs are wider than they are tall, so a
#: size chosen for the width of the mark leaves it short, and the widths
#: differ per face.  Measured per size with the metrics of the face actually
#: drawing it, which is also what keeps a fallback face from overflowing.
FIT_W = 0.84
FIT_H = 0.60
CORNER = 0.18

#: The size the mark is measured at before being scaled to fit.  Any size
#: would do -- the metrics are linear -- and a big one keeps the rounding in
#: the division away from the answer.
REFERENCE = 100.0


def _face() -> str:
    """Bitter, registered from the copy that travels with the tool."""
    families: list[str] = []
    for path in sorted(FONT_DIR.glob("*.ttf")):
        for family in QFontDatabase.applicationFontFamilies(
            QFontDatabase.addApplicationFont(str(path))
        ):
            families.append(family)
    for family in families:
        if family.lower().startswith("bitter"):
            return family
    return families[0] if families else "serif"


def fitted(face: str, size: int) -> QFont:
    """The mark's font at this size: as large as fits, width or height.

    Both limits are real.  A wide mark runs into the sides of the square and
    a tall one into the corners, and which arrives first depends on the face:
    Bitter is a slab serif and its ``2`` is wide, where a fallback sans would
    fit differently.  Measuring answers for whichever face is in use.
    """
    font = QFont(face)
    font.setPixelSize(round(REFERENCE))
    font.setWeight(QFont.Weight.Bold)
    marks = QFontMetricsF(font).boundingRect(MARK)
    scale = min(
        size * FIT_W / marks.width(),
        size * FIT_H / marks.height(),
    )
    font.setPixelSize(max(1, round(REFERENCE * scale)))
    return font


def draw(size: int, face: str) -> QImage:
    """One size, drawn at that size: the gold field, the mark, the corners."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # The field.  Square to the edges and clipped round, so that the corners
    # are truly transparent rather than painted over the wall's own colour --
    # the icon has to sit on whatever the player's desktop is.
    box = QRectF(0, 0, size, size)
    radius = size * CORNER
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(GOLD))
    painter.drawRoundedRect(box, radius, radius)

    painter.setFont(fitted(face, size))
    painter.setPen(QColor(WALL))
    painter.drawText(box, Qt.AlignmentFlag.AlignCenter, MARK)

    painter.end()
    return image


def ico_bytes(images: list[QImage]) -> bytes:
    """The ICO, with each size stored as a PNG.

    The format is a directory of entries over a blob of images: six bytes of
    header, sixteen per image, then the images themselves.  PNG inside ICO is
    what Windows itself writes since Vista, and it is what keeps this readable
    -- the older BMP spelling needs a mask per size and a bottom-up row order.
    A 256 is written as 0 in the entry, which is the format's way of saying
    256: the field is one byte and 256 does not fit in it.
    """
    payloads: list[bytes] = []
    for image in images:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        payloads.append(bytes(buffer.data()))

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = []
    for image, payload in zip(images, payloads):
        edge = 0 if image.width() >= 256 else image.width()
        entries.append(
            struct.pack(
                "<BBBBHHII", edge, edge, 0, 0, 1, 32, len(payload), offset
            )
        )
        offset += len(payload)
    return header + b"".join(entries) + b"".join(payloads)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Held rather than dropped: Qt needs an application to exist before a font
    # can be loaded, and tearing it down between the two would take the font
    # database with it.  The underscore is the difference between "unused" and
    # "kept alive".
    _app = QApplication([])

    face = _face()
    images = [draw(size, face) for size in SIZES]

    out = ROOT / "app" / "icon.ico"
    out.write_bytes(ico_bytes(images))
    print(f"{out.relative_to(ROOT)}: {out.stat().st_size} bytes, sizes {SIZES}")

    if "--preview" in argv:
        for size, image in zip(SIZES, images):
            path = ROOT / "var" / f"icon-{size}.png"
            path.parent.mkdir(exist_ok=True)
            image.save(str(path))
            print(f"{path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
