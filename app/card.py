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

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
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
    DAMAGE,
    DAMAGE_PER_SECOND,
    Card,
    TIER_INK,
    requirements_lines,
)
from tl2stash.icons import ELEMENT_MARKS, IconLibrary, Placement

__all__ = [
    "STYLE",
    "IconCache",
    "IconTile",
    "ItemCard",
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

    For a line that is already the emphasis: a weapon's Damage per Second is
    written in the one gold the card has, number and words together, so
    lifting its number would lift it out of the colour -- the brightest thing
    in the line would be the words that name the number rather than the
    number.  The site writes this line the same way, in one colour, with the
    words a shade quieter than the number beside them.
    """
    return f'<span style="color:{ink}">{html.escape(text)}</span>'


def _serif() -> QFont:
    """The card's stat voice.

    The site sets its affix lines and its chips in Bitter, which it embeds.
    Nothing here ships a font, so this is the site's own fallback stack and Qt
    takes the first family that exists.
    """
    font = QFont()
    font.setFamilies(["Bitter", "Georgia", "Times New Roman", "serif"])
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


class Hairline(QFrame):
    """The rule the site draws before every section but the first."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"background-color:{LINE}; border:0;")


class ItemCard(QFrame):
    """One item, drawn: the headline, then the sections under it."""

    def __init__(
        self, card: Card, icons: IconCache | None = None, parent=None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.card = card
        self._icons = icons

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
        """The corner: what the item asks of the player and what it holds."""
        pills = []
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

        # A weapon's output comes first under its name, and what the item asks
        # of the character after it -- the same order ``tl2stash.card.lines``
        # flattens them in, because the drawing and the flat list are one card.
        first = True
        if card.weapon_lead:
            first = self._part(column, first)
            for text in card.weapon_lead:
                column.addWidget(self._lead_line(text))
        self._requires(column, card)

        for kind, found in _sections(card.blocks):
            first = self._part(column, first)
            for text in found:
                column.addWidget(self._stat(text, kind))

        # What a socket added, as its own section: the lines the item's own
        # records carry *because* of the socket, then the gems themselves.
        # The two numbers differ on purpose -- the record holds what the gem
        # grants this item, the gem's own card what it is on its own -- and
        # the section is what says which is which.
        if card.gems or card.socketed:
            first = self._part(column, first)
            self._socketed(column, card)

        # The set's ladder, in the place the game writes it: after the item's
        # own stats and its sockets, before the remark under both.  The same
        # order ``tl2stash.card.lines`` flattens them in, because the drawing
        # and the flat list are the same card.
        if card.set_ladder:
            first = self._part(column, first)
            self._ladder(column, card)

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
            label = QLabel(plain(text, GOLD))
        else:
            label = QLabel(emphasis(text, DIM))
        label.setObjectName("lead")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        return label

    def _requires(self, column: QVBoxLayout, card: Card) -> None:
        """What the item asks of the character, above every stat.

        The game writes these above every stat, and they are the one thing on
        the card that decides whether any of the rest can be used at all -- so
        they take no rule and no section: they belong to the headline, and a
        rule over them would file a requirement as one of the item's stats.

        They are written in the colour the corner pills are written in, which
        is this window's word for a note about the item rather than a number
        of it.  The card cannot know whether the character meets them -- it is
        a collection, not a character sheet -- so the game's other colour, the
        red it turns an unmet requirement, is not available to it.
        """
        said = requirements_lines(card)
        for text in said:
            label = QLabel(text)
            label.setObjectName("gate")
            label.setWordWrap(True)
            column.addWidget(label)
        if said:
            column.addSpacing(6)

    def _socketed(self, column: QVBoxLayout, card: Card) -> None:
        """What a socket put on the item: the heading, its lines, the gems.

        The heading is this window's own word rather than the game's -- the
        game draws a socket's contents under the item with nothing over them,
        and it can afford to, because a player looking at the game's tooltip
        put the gem there a moment ago.  A collection may hold an item nobody
        alive has ever unsocketed, so the section says what it is.

        The lines come first and the gems under them: what the socket does to
        *this* item is the item's own number, and the gem's card under it is
        the gem's, which is a different number for the same effect -- an Ice
        Ember reads ``+120 Ice Armor`` on the Gorget it is sitting in and
        ``+58 Ice Armor`` on its own.
        """
        heading = QLabel("Socketed")
        heading.setObjectName("socketed")
        column.addWidget(heading)
        for text in card.socketed:
            column.addWidget(self._stat(text, AFFIX))
        for gem in card.gems:
            self._gem(column, gem)

    def _ladder(self, column: QVBoxLayout, card: Card) -> None:
        """What wearing more of the set grants: the set, then each rung.

        The set's name is drawn in the set purple -- the one colour no tier of
        an item is drawn in, because a set is not a tier -- and each rung under
        it as ``(2) Set`` with its lines below, which is how the site draws a
        ladder and how the game words one.
        """
        title = QLabel(card.set_name or "")
        title.setObjectName("setname")
        title.setStyleSheet(f"color:{TIER_INK['set']}")
        title.setWordWrap(True)
        column.addWidget(title)

        for rung in card.set_ladder:
            heading = QLabel(f"({rung.count}) Set")
            heading.setObjectName("rung")
            column.addWidget(heading)
            for text in rung.lines:
                # A rung's lines are affix lines -- a set's bonus is an effect
                # like any other -- so they are drawn like the item's own.
                column.addWidget(self._stat(text, AFFIX))

    def _part(self, column: QVBoxLayout, first: bool) -> bool:
        """Open a section.  Returns ``False``: nothing after this is first."""
        if not first:
            column.addSpacing(8)
            column.addWidget(Hairline())
            column.addSpacing(8)
        return False

    def _gem(self, column: QVBoxLayout, gem: Card) -> None:
        """A socket's contents, under the item that holds them."""
        heading = QLabel(gem.name)
        heading.setObjectName("gem")
        heading.setWordWrap(True)
        column.addWidget(heading)

        for kind, found in _sections(gem.blocks):
            for text in found:
                # Indented, because what is under a gem's name is the gem's
                # rather than the item's.
                column.addWidget(self._stat(text, kind, indent=12))

        if gem.flavor:
            flavour = QLabel(gem.flavor)
            flavour.setObjectName("flav")
            flavour.setWordWrap(True)
            flavour.setIndent(12)
            column.addWidget(flavour)

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
    font-size: 11px;
}}
#gem {{ color: {HEAD}; font-size: 12.5px; font-weight: 600; }}
#gate {{ color: {LABEL}; font-size: 12px; }}
#socketed {{ color: {LABEL}; font-size: 12px; font-weight: 600; }}
#setname {{ font-size: 13px; font-weight: 600; }}
#rung {{ color: {LABEL}; font-size: 12px; font-weight: 600; }}
#flav {{ color: {FLAVOUR}; font-size: 12px; font-style: italic; }}
#hint {{ color: {DIM}; font-size: 12.5px; }}
"""
