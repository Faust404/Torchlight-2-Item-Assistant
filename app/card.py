"""What the right-hand pane draws: an item as the website draws one.

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

Rebuilt on every selection change and never on the poll: a card is a hundred
widgets, and the table beside it is redrawn every time the game saves.
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
    QPalette,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tl2stash.card import ADDED, AFFIX, ARMOR, DAMAGE, Card, TIER_INK, lines
from tl2stash.icons import IconLibrary

__all__ = ["IconCache", "IconTile", "ItemCard", "ItemPane", "TIER_INK", "emphasis"]

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

#: The blocks the card draws as one run of lines.  A weapon's own damage, its
#: armour and what was socketed or enchanted onto it are three blocks in the
#: model and one section on the card, because that is how the game draws them
#: and how the site parts its sections.
_NUMERIC = (DAMAGE, ARMOR, ADDED)


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


def _serif() -> QFont:
    """The card's stat voice.

    The site sets its affix lines and its chips in Bitter, which it embeds.
    Nothing here ships a font, so this is the site's own fallback stack and Qt
    takes the first family that exists.
    """
    font = QFont()
    font.setFamilies(["Bitter", "Georgia", "Times New Roman", "serif"])
    return font


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
            self._icons[name] = self._load(name)
        return self._icons[name]

    def _load(self, name: str) -> QPixmap | None:
        try:
            placed = self._library.locate(name)
            if placed is None:
                return None
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


class IconTile(QWidget):
    """The 58x58 rarity tile: the item's icon on the tier's own colour.

    Painted rather than styled, because both of the things that make it read as
    a tile are a function of one colour -- the border is that colour at 48% and
    the glow is a radial gradient of it at 22% -- and Qt's stylesheet language
    can compute neither.
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

        # Half a pixel in, so a one-pixel pen lands on a pixel rather than
        # across two of them.
        box = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        shape = QPainterPath()
        shape.addRoundedRect(box, 4, 4)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TILE_BG))
        painter.drawPath(shape)

        painter.setBrush(self._glow(box))
        painter.drawPath(shape)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        border = QColor(self.ink)
        border.setAlphaF(BORDER_MIX)
        painter.setPen(QPen(border, 1))
        painter.drawPath(shape)

        # The site clips the icon to the tile's rounded box, so an icon a few
        # pixels larger than the tile loses the same corners here that it loses
        # there -- it is centred rather than scaled, which is the site's own
        # `align-items:center` over a fixed-size icon.
        painter.setClipPath(shape)
        if self.icon is not None:
            painter.drawPixmap(
                (self.width() - self.icon.width()) // 2,
                (self.height() - self.icon.height()) // 2,
                self.icon,
            )
            return

        painter.setPen(QColor(PLACEHOLDER))
        font = QFont(self.font())
        font.setPixelSize(15)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.letter)

    def _glow(self, box: QRectF) -> QRadialGradient:
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
        near = QColor(self.ink)
        near.setAlphaF(GLOW_ALPHA)
        far = QColor(self.ink)
        far.setAlphaF(0.0)
        glow.setColorAt(0.0, near)
        glow.setColorAt(1.0, far)
        return glow


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

        first = True
        for kind, found in _sections(card.blocks):
            first = self._part(column, first)
            for text in found:
                column.addWidget(self._stat(text, kind))

        for gem in card.gems:
            first = self._part(column, first)
            self._gem(column, gem)

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
                line = self._stat(text, kind)
                line.setIndent(12)
                column.addWidget(line)

        if gem.flavor:
            flavour = QLabel(gem.flavor)
            flavour.setObjectName("flav")
            flavour.setWordWrap(True)
            flavour.setIndent(12)
            column.addWidget(flavour)

    def _stat(self, text: str, kind: str) -> QLabel:
        """One line of stats: an affix in the game's green, the rest plain."""
        affix = kind == AFFIX
        label = QLabel(emphasis(text, MAGIC if affix else BODY))
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        if affix:
            # The affix block is the card's serif one; the damage and armour
            # lines keep the window's own voice.
            label.setFont(_serif())
        return label


#: Everything the widgets above are drawn with.  One stylesheet on the pane
#: rather than one per widget: Qt restyles a whole subtree whenever a
#: stylesheet changes, and a card is a hundred widgets built fresh on every
#: selection.
_STYLE = f"""
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
#flav {{ color: {FLAVOUR}; font-size: 12px; font-style: italic; }}
#hint {{ color: {DIM}; font-size: 12.5px; }}
"""


class ItemPane(QWidget):
    """The right-hand pane: one item's card, or a sentence saying why none.

    The ground is darker than the card, which is the site's own reason for the
    two being different colours -- a card painted in the ground's own colour is
    not a card, it is a panel.

    A card is drawn as widgets and read back as text.  ``toPlainText`` is the
    lines the model holds rather than the labels the pane built, so what the
    tests read is what the item says and not how it happens to be arranged --
    the level is a pill in the corner and a line of text here, and both are
    true at once.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text = ""

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        column.addWidget(self._scroll)

        self._content = QWidget()
        self._stack = QVBoxLayout(self._content)
        self._stack.setContentsMargins(10, 10, 10, 10)
        self._stack.setSpacing(0)
        self._scroll.setWidget(self._content)

        # A palette rather than a stylesheet: the scroll area's ground is its
        # viewport's, and a `background` rule on a QScrollArea does not reach
        # it -- which is the same trap that defeats `border-radius` on one.
        for widget in (self._scroll.viewport(), self._content):
            widget.setAutoFillBackground(True)
            palette = widget.palette()
            palette.setColor(QPalette.ColorRole.Window, QColor(GROUND))
            widget.setPalette(palette)

        self.setStyleSheet(_STYLE)

    def display(self, content: Card | str, icons: IconCache | None = None) -> None:
        """Draw an item's card, or a sentence in place of one.

        A sentence is what there is to show when nothing is selected, when the
        game's files cannot be found, and when one item will not parse -- and
        all three are cases where a card would be a lie about what is known.
        """
        self._clear()
        if isinstance(content, Card):
            self._text = "\n".join(lines(content))
            self._stack.addWidget(ItemCard(content, icons))
        else:
            self._text = content
            message = QLabel(content)
            message.setObjectName("hint")
            message.setWordWrap(True)
            message.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self._stack.addWidget(message)
        self._stack.addStretch(1)

        # A new card starts at its top: the pane is the last thing read, and
        # leaving it scrolled where the previous item was read to is the one
        # way selecting an item can show the wrong part of it.
        self._scroll.verticalScrollBar().setValue(0)

    def toPlainText(self) -> str:
        """The card's lines, or the sentence that stood in for it."""
        return self._text

    def _clear(self) -> None:
        while self._stack.count():
            item = self._stack.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
