"""An item drawn as the website draws one.

The design is the tl2-db site's, taken from its own stylesheet rather than
reinvented -- a dark card on a darker ground, the item's tier inked into a tile
beside its name, a kind line, the corner pills, and the stats in
hairline-separated sections with the numbers lifted out of the words.  The
colours below are that stylesheet's, by the names it gives them.

Two things had to be computed here rather than declared.  The site inks the
tile's border and its glow from one declaration -- ``currentColor`` at 48% for
the border, the same colour in a radial gradient at 22% for the glow -- and
Qt's stylesheet language has neither ``currentColor`` nor ``color-mix``.  So
:class:`IconTile` paints itself, and those two are computed per card.  That is
the whole of the custom painting in here.

Nothing here decides what an item says.  The lines are
:mod:`tl2stash.card`'s and the wording is :mod:`tl2stash.tooltip`'s; this draws
them.  Its one piece of judgement is the site's own emphasis rule -- every
number in a line lifts to the header colour -- which is one regular expression,
and which is what makes a card scannable rather than merely coloured.

A card is a drawing, and drawing is all it does -- bar one word.  A set's name
is a link on the cards that are asked to link it: the set is a thing the tool
holds more of, and :class:`LinkLabel` is how the name says so and how the click
gets out.  Which cards those are is the holder's decision, not this module's --
see :meth:`ItemCard._set_name`.

A card is built once per item and then left alone: it is a hundred widgets, and
:mod:`app.tiles` draws one per thing the tool holds and rebuilds that wall on
every save.  So the cost of a card is paid when the item is first seen and
never again, which is what the memo in the window is for.
"""

from __future__ import annotations

import html
import math
import re
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tl2stash.card import (
    AFFIX,
    ARMOR,
    AUGMENT_LOCKED,
    DAMAGE,
    DAMAGE_PER_SECOND,
    REQUIREMENTS,
    THE_ALTERNATIVE,
    Augment,
    Card,
    TIER_INK,
    requirements_lines,
)
from tl2stash.icons import ELEMENT_MARKS, IconLibrary, Placement

__all__ = [
    "STYLE",
    "ChipRow",
    "IconCache",
    "IconTile",
    "ItemCard",
    "LOCKED",
    "LinkLabel",
    "MARK",
    "TIER_INK",
    "element_of",
    "emphasis",
    "paint_tile",
    "plain",
]

# -- the site's palette (``web/app.css``), by the name it gives each colour --

#: The ground behind the card.  Darker than the card's own panel, which is what
#: makes the card read as a card rather than as a panel -- the site's own
#: argument for the two being different, and why neither is the window's.
GROUND = "#12110f"
PANEL = "#171614"
#: The card's hairline, and the rules between its sections.
LINE = "#211e1c"
#: The chip border, a shade warmer than the hairline.
DIV = "#2b251b"
#: The colour a number is lifted to, and the colour a gem is named in.
HEAD = "#dec2a3"
#: The corner pills.
LABEL = "#a88054"
#: The card's ordinary text, and the kind line's muted grey.
BODY = "#c9c2b6"
DIM = "#8b837b"
#: The site's ``--gold``, which it keeps for one thing: a weapon's Damage per
#: Second.  It is the only number on the card that is a verdict rather than a
#: stat -- the reason a weapon is picked up at all -- and the two lines that
#: qualify it are written in the dim above.
GOLD = "#e3ba6b"
#: The game's magical-item green, which is what an affix line is written in.
MAGIC = "#7cc24a"
#: The site's ``.fx.locked`` grey, for a stat an item has not been given yet.
#: It is a shade off :data:`DIM` on purpose and reads as one of the card's
#: side-notes rather than as a stat -- which is the whole of the distinction an
#: augment needs, because green on this card means the item *has* it.
LOCKED = "#8d8579"
MUTED = "#999999"
FLAVOUR = "#8d8579"
TILE_BG = "#100f0e"
PLACEHOLDER = "#5c5650"

# The colour each tier is drawn in now lives in ``tl2stash.card``, beside the
# tier table it is keyed by: the collection list inks a whole column of items
# with it and has no business importing a widget to do that.  It is re-exported
# from here because this is where the card's own code and its tests have always
# read it from.

#: The tile's two computed effects.  The site writes both as a function of the
#: tier colour: the border is that colour mixed 48% toward transparent, and the
#: glow is a radial gradient of it at 22%.
BORDER_MIX = 0.48
GLOW_ALPHA = 0.22
#: ``radial-gradient(circle at 50% 58%, currentColor, transparent 70%)``.  The
#: stops of a CSS circle gradient are measured against the farthest corner, so
#: the 70% is 70% of that distance rather than a radius in pixels.
GLOW_AT = (0.50, 0.58)
GLOW_STOP = 0.70

#: The tile, at the site's 58px.
TILE = 58

#: The site's emphasis rule, kept character for character: a sign, a number, an
#: optional decimal part with a full stop or a comma in it, and an optional
#: percent.  The comma is not decoration -- the game writes decimal commas in
#: some languages and the numbers are shown as they are stored.
_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?%?")

#: The blocks the card draws as one run of lines, and the only ones whose lines
#: are damage or armour the *item* has: its own damage and its own armour are
#: two blocks in the model and one section on the card, because that is how the
#: game draws them and how the site parts its sections.  What an affix, a
#: socket or an enchantment added is not among them -- it is a property, and a
#: property is written with the properties.
_NUMERIC = (DAMAGE, ARMOR)


def mark(text: str) -> str:
    """A line with its numbers lifted out of it, as HTML.

    The site's rule (``app.js:883-890``), and the site's reason for it: the
    value is what a reader scans for, and it is already in the string, so
    lifting it is emphasis rather than a claim about the stat.  The sign, the
    decimal part and the percent travel with the number -- splitting ``+8``
    from its ``%`` would print one value in two colours.
    """
    out: list[str] = []
    last = 0
    for match in _NUMBER.finditer(text):
        out.append(html.escape(text[last : match.start()]))
        out.append(
            f'<span style="color:{HEAD};font-weight:600">'
            f"{html.escape(match.group())}</span>"
        )
        last = match.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


def emphasis(text: str, ink: str) -> str:
    """A whole line of the card, in ``ink`` with its numbers lifted."""
    return f'<span style="color:{ink}">{mark(text)}</span>'


def plain(text: str, ink: str) -> str:
    """A whole line of the card in ``ink``, with nothing lifted out of it.

    For a line that is already the emphasis, or one whose numbers are not the
    item's: an augment's task takes the card's gold and has no number in it to
    lift, and the stats that task would grant keep their numbers in the grey
    they are written in, because they are the one block on the card that is not
    about the item as it stands.

    A weapon's Damage per Second is the other line drawn without a lift, and it
    is set at two sizes instead: see :func:`_dps`.
    """
    return f'<span style="color:{ink}">{html.escape(text)}</span>'


def _as_a_label(text: str) -> str:
    """A section word, in the case the card prints section words in.

    The site keeps these words in sentence case in its markup and uppercases
    them in the stylesheet -- ``text-transform:uppercase`` on ``.rhead``,
    ``.fxh``, ``.cond`` and ``.ror`` -- which Qt's stylesheet language does not
    have at all.  So the case is applied here, at the four labels that have it,
    and the model's wording stays the sentence the game and the site both
    write: the same words, in the two presentations they are read in.
    """
    return text.upper()


def _dps(text: str) -> str:
    """A weapon's Damage per Second, at the site's two sizes.

    The site writes this line as a number and the name of the number, and the
    two are not the same size: 15px at 600 for the number, 12.5px for what it
    is a number *of* -- ``.dps`` and ``.dps span``, and the only line on the
    card that is set at two sizes.  It is the whole reason this line takes no
    lift: a number drawn half again as large as the words around it is already
    the brightest thing in the line, and lifting it out of the gold would only
    take it out of the colour the line is.

    Split at the first space rather than by :data:`_NUMBER`, because the model
    writes the line the way the game does -- the number, then its unit -- and
    the words can carry numbers of their own.
    """
    number, _, words = text.partition(" ")
    # The site fades the unit a little further as well (``opacity:.82`` on the
    # span); the size is what carries the distinction here, so that the line
    # stays the one thing on the card written in the one gold.
    return (
        f'<span style="color:{GOLD};font-size:15px;font-weight:600">'
        f"{html.escape(number)}</span>"
        f'<span style="color:{GOLD};font-size:12.5px"> {html.escape(words)}</span>'
    )


#: The site's rule for every number it lifts -- ``font-variant-numeric:
#: tabular-nums`` on ``.aff .n``, ``.ln b``, ``.rchip b`` and the collection's
#: own counts -- as the font feature it really is.  Bitter's figures are
#: proportional by default, so without this a column of stat lines steps in and
#: out of alignment; the numbers are what a card is scanned for, and they line
#: up down the card.  Qt has no ``font-variant-numeric``, so the request goes
#: to the face instead, and a fallback with no such figure set ignores it.  A
#: font feature is switched on by asking for it at a value of 1, so this is the
#: tag and :data:`TABULAR_ON` is the request.
TABULAR = QFont.Tag("tnum")
TABULAR_ON = 1


def _serif() -> QFont:
    """The card's stat voice.

    The site sets its affix lines and its chips in Bitter, which it embeds; the
    face travels with this tool for the same reason, and :mod:`app.theme`
    registers it before any card is built.  The stack behind it is the site's
    own, so a machine whose copy of the file cannot be read falls back the way
    the site does.

    Tabular figures, which is the site's rule for a lifted number and not a
    choice made here -- see :data:`TABULAR`.
    """
    font = QFont()
    font.setFamilies(["Bitter", "Georgia", "Times New Roman", "serif"])
    font.setFeature(TABULAR, TABULAR_ON)
    return font


#: How big an element mark is drawn: the height of a stat line, so that a mark
#: sits *in* its line rather than over it.  The game's own tiles are 27x29 --
#: drawn at their own size they would be the loudest thing on the card, and the
#: reference draws the same five at 15x16, which is legible on a web page and
#: a little small for a glyph that is the point of the line.
MARK = (18, 19)


def element_of(text: str, kind: str) -> str | None:
    """Which element a damage or armour line is about, or ``None``.

    Read off the line rather than carried with it, which is a deliberate
    bargain: the lines are :mod:`tl2stash.card`'s -- one list of strings that
    the tooltip, the tests and the card all read -- and hanging an element on
    each one would make the card's model richer than the item's own text.
    The wording is this module's sibling's, so the two shapes it writes are
    knowable: an element is the first word (``Fire Damage 52-74``), and the
    bare word is physical (``Damage 20``), written without a name precisely
    because saying so says nothing.

    ``kind`` is the guard, and it is the whole of the guard: only the damage
    and armour blocks are the item's *own* numbers.  What the item has been
    *given* -- the flat ``+13 Physical Damage`` a socket or an enchantment
    granted -- is a property, written in the properties block with the rest,
    and a property takes no mark: the mark is for the damage the weapon *is*.
    The same guard is what keeps an affix that happens to begin with a colour
    -- ``Fire Damage Taken is reduced by 10%`` -- from reading as this item
    dealing fire.
    """
    if kind not in _NUMERIC:
        return None
    words = text.lower().split()
    if not words:
        return None
    if words[0] in ELEMENT_MARKS:
        return words[0]
    return "physical" if words[0] in ("damage", "armor") else None


def _marked(picture: QPixmap, label: QLabel, indent: int) -> QWidget:
    """A stat line with its element's mark in front of it.

    Two widgets rather than one, because a picture cannot go in a label's
    text: Qt will lay out a pixmap and a sentence side by side only if it is
    given two things to lay out, so the row is built here.  The mark is pinned
    to the top rather than centred -- a stat long enough to wrap would
    otherwise leave its mark floating halfway down the card.
    """
    row = QWidget()
    line = QHBoxLayout(row)
    line.setContentsMargins(indent, 2, 0, 0)
    line.setSpacing(5)

    mark = QLabel()
    mark.setObjectName("emark")
    mark.setPixmap(picture)
    mark.setFixedSize(picture.size())

    holder = QVBoxLayout()
    holder.setContentsMargins(0, 0, 0, 0)
    holder.addWidget(mark)
    holder.addStretch(1)
    line.addLayout(holder)
    line.addWidget(label, 1)
    return row


def _sections(blocks) -> list[tuple[str, tuple[str, ...]]]:
    """The card's blocks, run together where the game runs them together."""
    out: list[tuple[str, tuple[str, ...]]] = []
    for block in blocks:
        if out and out[-1][0] in _NUMERIC and block.kind in _NUMERIC:
            kind, found = out[-1]
            out[-1] = (kind, found + block.lines)
            continue
        out.append((block.kind, block.lines))
    return out


class IconCache:
    """The game's icon sheets, decoded once each, and one crop per icon.

    A sheet is 512x512 and holds hundreds of icons, so it is decoded the first
    time one of its icons is drawn and kept; a crop is kept as well, because
    the same icon is on every item that wears it.  Both are per window, so a
    window that closes takes its pictures with it and nothing is global.

    Every failure is a missing icon rather than an error.  A sheet that will
    not decode, a name no sheet declares, an archive that is not there at all:
    the tile draws the placeholder, which is what the site does for the 2% of
    items whose icon is in no sheet.
    """

    def __init__(self, install: str | Path) -> None:
        # The library reads nothing until it is asked, so this is free even
        # when there is no archive to read.
        self._library = IconLibrary(install)
        self._sheets: dict[str, QImage] = {}
        self._icons: dict[str, QPixmap | None] = {}

    def icon(self, name: str | None) -> QPixmap | None:
        """The picture for an icon name, or ``None`` if there is not one."""
        if not name:
            return None
        if name not in self._icons:
            self._icons[name] = self._crop(self._locate(name))
        return self._icons[name]

    def element(self, word: str | None) -> QPixmap | None:
        """The mark for a damage element, or ``None`` if there is no game.

        Cached with the icons and under a key of its own -- a mark's name and
        an icon's name are different vocabularies, and ``element:fire`` cannot
        collide with a file called ``fire``.  Scaled on the way out rather than
        per line: the sheet's tiles are 27x29 and a card wants them smaller,
        and the same five are on every card.
        """
        if not word:
            return None
        key = "element:" + word.lower()
        if key not in self._icons:
            placed = self._crop(self._place(word))
            self._icons[key] = (
                placed.scaled(
                    *MARK,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                if placed is not None
                else None
            )
        return self._icons[key]

    def _locate(self, name: str) -> Placement | None:
        try:
            return self._library.locate(name)
        except Exception:  # noqa: BLE001 -- an icon is never worth an error
            return None

    def _place(self, word: str) -> Placement | None:
        try:
            return self._library.mark(word)
        except Exception:  # noqa: BLE001
            return None

    def _crop(self, placed: Placement | None) -> QPixmap | None:
        """One rectangle of one sheet, decoded once per sheet."""
        if placed is None:
            return None
        try:
            sheet = self._sheets.get(placed.atlas)
            if sheet is None:
                sheet = QImage.fromData(self._library.read(placed))
                if sheet.isNull():
                    return None
                self._sheets[placed.atlas] = sheet
        except Exception:  # noqa: BLE001 -- an icon is never worth an error
            return None
        cropped = sheet.copy(
            QRect(placed.x, placed.y, placed.width, placed.height)
        )
        return QPixmap.fromImage(cropped)


def paint_tile(
    painter: QPainter,
    width: int,
    height: int,
    ink: QColor,
    icon: QPixmap | None,
    letter: str,
) -> None:
    """The rarity tile, drawn into whatever painter is handed one.

    The card's tile is 58 pixels and a list row's is 40, and they are the same
    picture: the item's icon on the tier's own colour, or the type's initial
    when there is no icon to draw.  One account of it, so that the two sizes
    cannot drift into looking like two different things -- which is why this is
    a function taking a painter rather than a widget's ``paintEvent``.

    ``ink`` is the tier colour, and both of the things that make the tile read
    as one are a function of it: the border is that colour at
    :data:`BORDER_MIX`, and the glow is a radial gradient of it at
    :data:`GLOW_ALPHA`.  Neither is expressible in Qt's stylesheet language,
    which is why this is painted at all.
    """
    # Half a pixel in, so a one-pixel pen lands on a pixel rather than across
    # two of them.
    box = QRectF(0.5, 0.5, width - 1, height - 1)
    shape = QPainterPath()
    shape.addRoundedRect(box, 4, 4)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(TILE_BG))
    painter.drawPath(shape)

    painter.setBrush(_glow(box, ink))
    painter.drawPath(shape)

    painter.setBrush(Qt.BrushStyle.NoBrush)
    border = QColor(ink)
    border.setAlphaF(BORDER_MIX)
    painter.setPen(QPen(border, 1))
    painter.drawPath(shape)

    # Clipped to the tile's rounded box whatever size it comes out -- a tile is
    # a tile and its corners are round, and the site's own crop does the same
    # to the art it draws.  The fit is what keeps the art whole inside it.
    painter.setClipPath(shape)
    if icon is not None:
        picture = _fit(icon, width, height)
        painter.drawPixmap(
            (width - picture.width()) // 2,
            (height - picture.height()) // 2,
            picture,
        )
        return

    painter.setPen(QColor(PLACEHOLDER))
    font = QFont(painter.font())
    # The card's 15 pixels at its own 58, and proportionally less in a list
    # row.  The site sets no size at all and lets the letter fill the tile.
    font.setPixelSize(max(9, round(height * 15 / TILE)))
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.drawText(QRect(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, letter)


def _fit(icon: QPixmap, width: int, height: int) -> QPixmap:
    """The icon at a size the tile can hold, whole.

    The game's art is 62 pixels square whatever tile it lands in -- measured
    over the archive, every crop is 62x62 and the art reaches every edge of it.
    So at the card's 58 it is a shade too big, and at a list row's 40 it is
    half again too big, and the difference between scaling it and centring it
    is the difference between a smaller picture and most of a picture: a
    40-pixel window onto a 62-pixel sword loses its tip and its pommel.

    An icon that already fits is handed straight back, so a small one is never
    resampled for nothing.
    """
    if icon.width() <= width and icon.height() <= height:
        return icon
    return icon.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _glow(box: QRectF, ink: QColor) -> QRadialGradient:
    """The tier colour, brightest under the middle of the icon."""
    centre = QPointF(box.width() * GLOW_AT[0], box.height() * GLOW_AT[1])
    reach = max(
        math.hypot(corner.x() - centre.x(), corner.y() - centre.y())
        for corner in (
            QPointF(x, y)
            for x in (box.left(), box.right())
            for y in (box.top(), box.bottom())
        )
    )

    glow = QRadialGradient(centre, reach * GLOW_STOP)
    near = QColor(ink)
    near.setAlphaF(GLOW_ALPHA)
    far = QColor(ink)
    far.setAlphaF(0.0)
    glow.setColorAt(0.0, near)
    glow.setColorAt(1.0, far)
    return glow


class IconTile(QWidget):
    """The 58x58 rarity tile: the item's icon on the tier's own colour.

    A widget over :func:`paint_tile`, which is where the drawing is: the card
    puts one beside the item's name and the list puts the same picture, smaller
    and as a pixmap, at the head of every row.
    """

    def __init__(
        self, ink: str, icon: QPixmap | None, letter: str, parent=None
    ) -> None:
        super().__init__(parent)
        self.ink = QColor(ink)
        self.icon = icon
        #: The site's fallback for an icon it has not got: the type's initial,
        #: and a question mark when there is not even a type.
        self.letter = letter
        self.setFixedSize(TILE, TILE)

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_tile(painter, self.width(), self.height(), self.ink, self.icon, self.letter)


class LinkLabel(QLabel):
    """A word on a card that can be clicked, and says so.

    The card has exactly one of these and it is a set's name: the ladder under
    it is what the *set* grants rather than what this piece does, so a player
    reading one piece wants the rest of the set -- and the collection has it,
    one click away.  See :meth:`app.window.MainWindow._show_set`.

    What makes a word a link is that something happens when it is clicked, so
    this is drawn only where something does.  The same set name on the same
    card in the comparison overlay is not a link, because that overlay is
    already showing every copy of one item and has nowhere to take anyone.

    The mark is the hand and the underline and nothing else.  The name is
    already in the set's purple -- the one colour on the card that is neither
    a tier's nor a stat's -- and a second colour meaning "this is a link" would
    be a second meaning for one word.

    The underline is written into the text as rich text rather than set on the
    widget's font, because the card's sheet owns the font: a ``#setname`` rule
    is what sizes this word, and a font set here would be a second account of
    the same thing, resolved by whichever of the two Qt applied last.
    """

    clicked = Signal()

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        #: The word as the item has it, kept so that the two drawings of it --
        #: plain, and underlined under the pointer -- cannot drift apart.
        self._word = text
        #: Whether the last press landed here and has not been let go of yet.
        self._down = False
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._draw(False)

    def word(self) -> str:
        """The name as written, without the markup that underlines it."""
        return self._word

    # -- the mouse -------------------------------------------------------

    def enterEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        self._draw(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        self._draw(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        # Accepted rather than passed on, because the card this sits on reads a
        # press as "this card was picked" -- and clicking the name inside the
        # card you are already reading is not picking it again.
        self._down = event.button() == Qt.MouseButton.LeftButton
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        was = self._down
        self._down = False
        # A press that wandered off the word before letting go is not a click
        # on it, which is what every link everywhere means by letting go.
        if was and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        event.accept()

    def _draw(self, underlined: bool) -> None:
        word = html.escape(self._word)
        self.setText(f"<u>{word}</u>" if underlined else word)


class Hairline(QFrame):
    """The rule the site draws before every section but the first."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"background-color:{LINE}; border:0;")


#: The gap between two chips in the gate's row, and between two lines of them.
#: The site's own ``.rrow{gap:5px}``.
CHIP_GAP = 5


class ChipRow(QWidget):
    """A row of chips that wraps when the card is too narrow for one line.

    The site writes the gate as a flex row with ``flex-wrap: wrap``, and Qt has
    no such thing: a box layout lays its children out along one line and
    something has to give when they do not fit.  What gives here is the line --
    the row measures its chips and starts another where the next would overrun
    -- which is the half of ``flex-wrap`` a card needs, and it costs a
    ``heightForWidth`` where a real layout would have cost a QLayout subclass
    with the same three methods on it.

    It is not a nicety: the card is 340px at its narrowest and a level chip,
    the word between the groups and two attribute chips already come to more,
    so without this a four-attribute requirement would be drawn with its last
    two chips cut off -- and the four-attribute items are 43 of the game's
    6,262 and the ones most worth reading.

    The children are not all chips.  The word between the two groups is a
    separator on the site rather than a box, and is drawn as one here; the row
    neither knows nor cares which of its children is which, because a chip is
    a chip by its *style* and this only places them.
    """

    def __init__(self, chips: list[QWidget], parent=None) -> None:
        super().__init__(parent)
        self._chips = chips
        for chip in chips:
            chip.setParent(self)
        policy = QSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _lines(self, width: int) -> list[list[QWidget]]:
        """The chips split into the lines they fit on at ``width``."""
        rows: list[list[QWidget]] = []
        row: list[QWidget] = []
        used = 0
        for chip in self._chips:
            need = chip.sizeHint().width()
            if row and used + CHIP_GAP + need > width:
                rows.append(row)
                row, used = [], 0
            row.append(chip)
            # The first chip on a line pays no gap, which is what makes the
            # comparison above exact rather than a gap too generous.
            used += need + (CHIP_GAP if used else 0)
        if row:
            rows.append(row)
        return rows

    @staticmethod
    def _tall(row: list[QWidget]) -> int:
        """How tall a line is: its tallest chip, since they sit on one line."""
        return max((chip.sizeHint().height() for chip in row), default=0)

    def _room(self, rows: list[list[QWidget]]) -> int:
        return sum(self._tall(row) for row in rows) + CHIP_GAP * max(
            len(rows) - 1, 0
        )

    def hasHeightForWidth(self) -> bool:  # noqa: N802 -- Qt naming
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 -- Qt naming
        return self._room(self._lines(width))

    def sizeHint(self):  # noqa: N802 -- Qt naming
        """One line, which is the shape the row has when nothing has to wrap."""
        across = sum(chip.sizeHint().width() for chip in self._chips)
        across += CHIP_GAP * max(len(self._chips) - 1, 0)
        return QSize(across, self._tall(self._chips))

    def minimumSizeHint(self):  # noqa: N802 -- Qt naming
        """As narrow as the widest chip, because a chip does not break in two."""
        widest = max((chip.sizeHint().width() for chip in self._chips), default=0)
        return QSize(widest, self._tall(self._chips))

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        super().resizeEvent(event)
        y = 0
        for row in self._lines(self.width()):
            tall = self._tall(row)
            x = 0
            for chip in row:
                chip.setGeometry(x, y, chip.sizeHint().width(), tall)
                x += chip.sizeHint().width() + CHIP_GAP
            y += tall + CHIP_GAP


class ItemCard(QFrame):
    """One item, drawn: the headline, then the sections under it."""

    #: A click on the set name, with the name that was clicked -- drawn only
    #: where the card was asked to link it; see :class:`LinkLabel`.
    set_clicked = Signal(str)

    def __init__(
        self,
        card: Card,
        icons: IconCache | None = None,
        parent=None,
        *,
        links_sets: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.card = card
        self._icons = icons
        #: Whether this card's set name is a link.  Off unless the holder says
        #: otherwise, because the one thing worse than a name that does not
        #: take you anywhere is a name that *looks* like it will.
        self._links_sets = links_sets

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._headline(card, icons))
        column.addWidget(self._body(card))

    # -- the headline ----------------------------------------------------

    def _headline(self, card: Card, icons: IconCache | None) -> QWidget:
        """The tile, the name and the corner: what the item is, before a stat.

        Nothing in this row is padded, which is the site's own note about it --
        the tile bleeds to the card's edge, and that is what makes the row read
        as a headline rather than as the first of the ruled sections.
        """
        ink = TIER_INK.get(card.tier, TIER_INK["none"])
        head = QWidget()
        head.setObjectName("ahead")
        row = QHBoxLayout(head)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        icon = icons.icon(card.icon) if icons is not None else None
        letter = (card.type_name.strip() or "?").strip()[:1].upper()
        row.addWidget(IconTile(ink, icon, letter), 0, Qt.AlignmentFlag.AlignTop)

        # Two pixels down, against the tile: the names sit on the tile's first
        # line rather than on its top edge.
        name = QWidget()
        column = QVBoxLayout(name)
        column.setContentsMargins(0, 2, 0, 0)
        column.setSpacing(2)

        title = QLabel(card.name)
        title.setObjectName("an")
        title.setStyleSheet(f"color:{ink}")
        title.setWordWrap(True)
        column.addWidget(title)

        kind = self._kind_line(card, ink)
        if kind is not None:
            column.addWidget(kind)
        row.addWidget(name, 1)

        corner = QWidget()
        pills = QVBoxLayout(corner)
        pills.setContentsMargins(0, 2, 0, 0)
        pills.setSpacing(3)
        for text in self._pills(card):
            pill = QLabel(text)
            pill.setObjectName("pill")
            pill.setFont(_serif())
            # A stretch beside it rather than an alignment on it: a chip that
            # is given the column's width is a bar, and the two chips in the
            # corner are different widths -- "Level 45" and "3 Sockets".
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            line.addStretch(1)
            line.addWidget(pill)
            pills.addLayout(line)
        row.addWidget(corner, 0, Qt.AlignmentFlag.AlignTop)
        return head

    def _kind_line(self, card: Card, ink: str) -> QLabel | None:
        """``<tier> <type>`` -- ``Unique Fist`` -- with the tier in its colour.

        The tier word is the one word in the line carrying something the type
        does not, so it is the one word painted in the tier's own colour.  A
        set piece adds the one word its tier cannot say, in the site's own
        order: ``Unique Set Boots``.  An item with none of the three has no
        line at all rather than an empty one.
        """
        if not (card.type_name or card.tier_word or card.set_name):
            return None

        said: list[str] = []
        if card.tier_word:
            word = html.escape(card.tier_word)
            said.append(f'<span style="color:{ink}">{word}</span>')
        if card.set_name:
            said.append("Set")
        if card.type_name:
            said.append(html.escape(card.type_name))

        label = QLabel(f'<span style="color:{MUTED}">{" ".join(said)}</span>')
        label.setObjectName("dtype")
        label.setTextFormat(Qt.TextFormat.RichText)
        return label

    def _pills(self, card: Card) -> list[str]:
        """The corner: what the item asks of the player and what it holds.

        The stack size leads, because it is the one of the three that changes
        how the card is *read*: ``×20`` is twenty potions and not one, and the
        level and the sockets under it are the level and the sockets of each of
        them -- the pile is one item, which is why the count is a pill here and
        not a line of the body with the stats.

        A multiplication sign rather than the word for it, because the corner
        already reads ``Level 45`` and ``3 Sockets``: the sign is the one mark
        that says how many of a thing there are without being taken for another
        stat of the one item.  A stack of one draws nothing, like the sockets
        of an item with none -- nearly every card is a stack of one.
        """
        pills = []
        if card.quantity > 1:
            pills.append(f"×{card.quantity}")
        if card.level:
            pills.append(f"Level {card.level}")
        if card.sockets:
            word = "Socket" if card.sockets == 1 else "Sockets"
            pills.append(f"{card.sockets} {word}")
        return pills

    # -- the body --------------------------------------------------------

    def _body(self, card: Card) -> QWidget:
        body = QWidget()
        body.setObjectName("body")
        column = QVBoxLayout(body)
        column.setContentsMargins(13, 12, 13, 13)
        column.setSpacing(2)

        # A weapon's output comes first under its name, and the item's own
        # stats under that -- the same order ``tl2stash.card.lines`` flattens
        # them in, because the drawing and the flat list are one card.
        first = True
        if card.weapon_lead:
            first = self._part(column, first)
            for text in card.weapon_lead:
                column.addWidget(self._lead_line(text))

        for kind, found in _sections(card.blocks):
            first = self._part(column, first)
            for text in found:
                column.addWidget(self._stat(text, kind))

        # What is in a socket, as its own section: the ember the player put
        # there and the bonus it grants this item.  The heading is over the
        # gem rather than over lines of the item's own, because the item's own
        # effect list does not hold the socket's contribution at all.
        if card.gems:
            first = self._part(column, first)
            self._socketed(column, card)

        # What the item will become, under the sockets and over the set's
        # ladder: the same place ``tl2stash.card.lines`` puts it, because the
        # drawing and the flat list are one card.
        if card.augments:
            first = self._part(column, first)
            for augment in card.augments:
                self._augment(column, augment)

        # The set's ladder, in the place the game writes it: after the item's
        # own stats and its sockets, before the remark under both.  The same
        # order ``tl2stash.card.lines`` flattens them in, because the drawing
        # and the flat list are the same card.
        if card.set_ladder:
            first = self._part(column, first)
            self._ladder(column, card)

        # What the item asks of the character, last of the sections and last
        # but the flavour: everything above is a number the item has and these
        # two lines are the only ones about the reader.  The same order
        # ``tl2stash.card.lines`` flattens them in, because the drawing and
        # the flat list are the same card.
        if requirements_lines(card):
            first = self._part(column, first)
            self._requires(column, card)

        # The flavour line is not a section and takes no rule, which is the
        # site's own note about it: it is a remark about the item rather than
        # one of its stats.
        if card.flavor:
            column.addSpacing(8)
            flavour = QLabel(card.flavor)
            flavour.setObjectName("flav")
            flavour.setWordWrap(True)
            column.addWidget(flavour)
        return body

    def _lead_line(self, text: str) -> QLabel:
        """One of the three lines a weapon leads with.

        The site's own treatment of them, and its reason for it: the Damage per
        Second is the number a weapon is chosen for, so it takes the one gold
        the card has, and the two lines that qualify it -- how fast it swings
        and how far it reaches -- are dim, their numbers lifted like any other
        line's.  The dps is the one line on the card written *without* the
        lift, because it does not need it: it is already the loudest thing
        here, and lifting its number would take it out of the gold.

        Which line is which is read off the text rather than carried beside it,
        because the model is one list of strings and a card says what an item
        says and nothing else.  It is the same bargain :func:`element_of` makes.

        The site splits the two qualifying lines finer than this -- the band
        word brighter than the words around it, the seconds a shade fainter
        still -- and this does not, because the card has one rule for a number
        in a line and one for the words around it, and a second rule for these
        two lines would be the only place on the card where a number is not the
        brightest thing in its line.
        """
        if text.endswith(DAMAGE_PER_SECOND):
            label = QLabel(_dps(text))
        else:
            label = QLabel(emphasis(text, DIM))
        label.setObjectName("lead")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        return label

    def _requires(self, column: QVBoxLayout, card: Card) -> None:
        """What the item asks of the character, at the foot of the card.

        It is drawn last and drawn as a section, which is the reference's own
        arrangement and the one the user asked for: every line above this is a
        number belonging to the item, and these are the only ones about the
        reader -- so they are the last thing read and the first thing to be
        looked for, and a rule over them says they are their own part of the
        card rather than a footnote to the stats.

        The gates are chips, which is the site's treatment and worth keeping: a
        requirement is something the character must be, and the one thing that
        used to be drawn under them -- the band the item drops in -- is off the
        card altogether, so that the only boxed numbers on it are the ones it
        actually asks for.

        The card cannot know whether the character meets any of it -- this is a
        collection, not a character sheet -- so the game's other colour for a
        requirement, the red it turns an unmet one, is not available here.
        """
        said = requirements_lines(card)
        if said:
            heading = QLabel(_as_a_label(REQUIREMENTS))
            heading.setObjectName("rhead")
            column.addWidget(heading)
            column.addWidget(ChipRow([self._chip(text) for text in said]))

    def _chip(self, text: str) -> QWidget:
        """One of the ways in -- or the word between the two groups.

        A chip is the site's ``.rchip``: a hairline box, the label in the dim
        and the number lifted, which is the card's own rule for a number and
        not a second one.  The word between the groups is that rule's one
        exception, because it is not a chip at all -- no box, and drawn in the
        dim without a number to lift -- and the site is explicit about why it
        gets to be different: it is the one thing on the card that must not be
        misread, so it is padded and spaced rather than made faint.
        """
        if text == THE_ALTERNATIVE:
            label = QLabel(_as_a_label(THE_ALTERNATIVE))
            label.setObjectName("ror")
            return label

        label = QLabel(emphasis(text, DIM))
        label.setObjectName("rchip")
        label.setFont(_serif())
        label.setTextFormat(Qt.TextFormat.RichText)
        return label

    def _socketed(self, column: QVBoxLayout, card: Card) -> None:
        """What is in a socket: the heading, and the gems under it.

        The heading is this window's own word rather than the game's -- the
        game draws a socket's contents under the item with nothing over them,
        and it can afford to, because a player looking at the game's tooltip
        put the gem there a moment ago.  A collection may hold an item nobody
        alive has ever unsocketed, so the section says what it is.

        The gems are the whole of the section, because they are the whole of
        what a socket contributes: an item's own effect list does not carry
        it.  The Gorget of the Hill Giant Chief's ``+120 Ice Armor`` reads
        among the item's own stats -- it is its own fixed stat -- and the
        ``+58 Ice Armor`` the ember in it grants is on the ember's card here,
        which is the only place that number exists.
        """
        heading = QLabel(_as_a_label("Socketed"))
        heading.setObjectName("socketed")
        column.addWidget(heading)
        for gem in card.gems:
            self._gem(column, gem)

    def _ladder(self, column: QVBoxLayout, card: Card) -> None:
        """What wearing more of the set grants: the set, then each rung.

        The set's name is drawn in the set purple -- the one colour no tier of
        an item is drawn in, because a set is not a tier -- and each rung under
        it as ``(2) Set`` with its lines below, which is how the site draws a
        ladder and how the game words one.

        The name is the card's one clickable word, on the cards that link it:
        it is the name of a thing the collection holds more of, so a click on
        it is a question the tool can answer.  See :meth:`_set_name`.
        """
        column.addWidget(self._set_name(card))

        for rung in card.set_ladder:
            heading = QLabel(f"({rung.count}) Set")
            heading.setObjectName("rung")
            column.addWidget(heading)
            for text in rung.lines:
                # A rung's lines are affix lines -- a set's bonus is an effect
                # like any other -- so they are drawn like the item's own.
                column.addWidget(self._stat(text, AFFIX))

    def _set_name(self, card: Card) -> QLabel:
        """The set's name: a link where a click on it means something.

        Which is the collection, and only the collection.  The card there
        stands for an item the tool holds and the set it belongs to is very
        likely in the tool as well, so a click can show it.  A card in the
        comparison overlay draws the same name and does not link it: that
        overlay is already showing every copy of one item, and a hand there
        would promise a place to go that does not exist.
        """
        name = card.set_name or ""
        if not self._links_sets:
            title = QLabel(name)
        else:
            title = LinkLabel(name)
            title.setToolTip(
                f"Show every piece of {name} in the collection,\n"
                "and nothing else."
            )
            title.clicked.connect(lambda: self.set_clicked.emit(name))
        title.setObjectName("setname")
        title.setStyleSheet(f"color:{TIER_INK['set']}")
        title.setWordWrap(True)
        return title

    def _augment(self, column: QVBoxLayout, augment: Augment) -> None:
        """A task, and the stats finishing it would grant.

        The one block on the card that is not about the item as it stands, so
        the one block whose lines are not written in the affix green: the green
        means the item *has* it, and the site's own note about this block is
        exactly that -- the locked stats pointedly do not take it.

        The task takes the gold, as it does on the site, where it is a chip:
        the same colour the Damage per Second takes, and for the same reason
        -- it is not a stat of the item but the thing about it that is worth
        acting on.  It is not drawn as a chip here, because the card has no
        other chip on it and one would be a device rather than a word.

        The caption between the two is the site's, at the site's size and
        tracking, and on the site it is the same gold as the task with a dashed
        rule either side of it.  Here it is a side-note in the dim the card
        writes those in, because the two lines are told apart by their colour
        rather than by their furniture and a second gold line would only
        compete with the first.
        """
        if augment.task:
            label = QLabel(plain(augment.task, GOLD))
            label.setObjectName("augtask")
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setWordWrap(True)
            column.addWidget(label)

        if not augment.gains:
            return
        caption = QLabel(_as_a_label(AUGMENT_LOCKED))
        caption.setObjectName("auglock")
        caption.setWordWrap(True)
        column.addWidget(caption)
        for text in augment.gains:
            label = QLabel(plain(text, LOCKED))
            label.setObjectName("augfx")
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setWordWrap(True)
            column.addWidget(label)

    def _part(self, column: QVBoxLayout, first: bool) -> bool:
        """Open a section.  Returns ``False``: nothing after this is first."""
        if not first:
            column.addSpacing(8)
            column.addWidget(Hairline())
            column.addSpacing(8)
        return False

    def _gem(self, column: QVBoxLayout, gem: Card) -> None:
        """A socket's contents, under the item that holds them.

        The gem's name and its lines, and nothing under them: the card it comes
        from carries no requirements -- the gem is already in something -- and
        no flavour text, which is the sentence about inserting it, so there is
        nothing here to draw but the two things the player is looking at.
        """
        heading = QLabel(gem.name)
        heading.setObjectName("gem")
        heading.setWordWrap(True)
        column.addWidget(heading)

        for kind, found in _sections(gem.blocks):
            for text in found:
                # Indented, because what is under a gem's name is the gem's
                # rather than the item's.
                column.addWidget(self._stat(text, kind, indent=12))

    def _stat(self, text: str, kind: str, indent: int = 0) -> QWidget:
        """One line of stats: an affix in the game's green, the rest plain.

        A damage or armour line leads with its element's mark when the game's
        own pictures can be read, which is a thing a number cannot say: the
        element is what a player scans a weapon for, and it is the one word in
        ``Fire Damage 52-74`` that is already two colours of its own on the
        card.  Without the game there is no picture and the line is the line.
        """
        affix = kind == AFFIX
        label = QLabel(emphasis(text, MAGIC if affix else BODY))
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        if affix:
            # The affix block is the card's serif one; the damage and armour
            # lines keep the window's own voice.
            label.setFont(_serif())
        label.setIndent(indent)

        element = element_of(text, kind)
        picture = self._icons.element(element) if self._icons and element else None
        if picture is None:
            return label
        return _marked(picture, label, indent)


#: Everything the widgets above are drawn with.  One stylesheet on whatever
#: holds the cards -- the grid, now -- rather than one per widget: Qt restyles
#: a whole subtree whenever a stylesheet changes, and a card is a hundred
#: widgets.  It is exported because the holder is what applies it, and the
#: holder is another module.
STYLE = f"""
#card {{
    background-color: {PANEL};
    border: 1px solid {LINE};
    border-radius: 4px;
}}
#an {{ font-size: 16px; font-weight: 600; }}
#dtype {{ font-size: 12px; }}
#pill {{
    border: 1px solid {DIV};
    border-radius: 3px;
    padding: 1px 6px;
    color: {LABEL};
    font-size: 11.5px;
}}
#gem {{ color: {HEAD}; font-size: 12.5px; font-weight: 600; }}
/* The card's labels -- a section heading, a socketable's slot, the note under a
   task, the word between the requirement chips -- are one treatment, and it is
   the site's own (``.rhead``, ``.fxh``, ``.cond``, ``.ror``): small, tracked, at
   weight 400, so that a label is found and then read past rather than competing
   with the thing under it.  The tracking is the site's letter-spacing over its
   own size (and Qt sizes in whole pixels, so the site's 9.5 is drawn at 10),
   and the capitals are the one part of the treatment Qt cannot take from a
   sheet -- see ``_as_a_label``. */
#rhead {{
    color: {LABEL};
    font-size: 9.5px;
    font-weight: 400;
    letter-spacing: 1.33px;
}}
#rchip {{
    border: 1px solid {DIV};
    border-radius: 3px;
    padding: 1px 6px;
    color: {DIM};
    font-size: 11.5px;
}}
#ror {{
    color: {DIM};
    font-size: 10px;
    letter-spacing: 1.6px;
}}
#socketed {{
    color: {LABEL};
    font-size: 10px;
    font-weight: 400;
    letter-spacing: 1.3px;
}}
#setname {{ font-size: 12.5px; font-weight: 600; }}
#rung {{ color: {LABEL}; font-size: 12px; font-weight: 600; }}
#augtask {{ font-size: 12.5px; }}
#auglock {{ color: {DIM}; font-size: 10px; letter-spacing: 1.4px; }}
#augfx {{ font-size: 12.5px; }}
#flav {{ color: {FLAVOUR}; font-size: 12px; font-style: italic; }}
#hint {{ color: {DIM}; font-size: 12.5px; }}
"""
