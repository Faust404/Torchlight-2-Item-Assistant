"""The window's own colours: dark, by default.

The things the eye spends its time on here are the cards, and a card is dark --
it is the game's own look, taken from the reference site's stylesheet, and
:mod:`app.card` says why.  An application that drew those cards on the
platform's light chrome would be arguing with itself about which of the two is
the screen.  So the window is built out of the card's own palette, which is to
say out of the reference stylesheet's colours under the names it gives them,
and the whole of the window is one surface rather than a document with cards
pasted onto it.

Three colours the card palette cannot supply, because a web page has no
buttons, no rows to select and nothing below a rule.  Each is derived here
rather than invented, one step from a colour that is already in the palette --
and each says which, so the next person who moves the palette can move these
with it.

A fourth is not derived from the palette at all: :data:`WHITE` outlines the
controls.  A web page has no controls to outline, so there is nothing in the
palette to derive it from -- and a control has to be the brightest thing on a
dark screen, or a box the player ticks reads as a decoration rather than as
something to press.

**The types.**  The site sets its page in 13px ``"Segoe UI", Roboto, Helvetica,
Arial, sans-serif`` and its stat lines in Bitter, which it ships; this sets the
same two, and :func:`apply_theme` loads the face out of ``app/fonts/`` before
any window exists, so a stat line cannot come out in a fallback the machine
happened to have.  Both carry the site's tabular figures, which is what keeps
the numbers in its columns and its stat lines in line with each other.  What is
*not* copied is the site's line height -- Qt has no ``line-height``, and a
font's own metrics are what it lays a label out with.

**The style matters as much as the palette.**  On Windows the default style
draws much of a widget out of the system theme and consults the palette only
for what the theme does not say, so setting colours alone gives a light window
with dark corners.  Fusion is the one Qt style that draws all of it out of the
palette on every platform, which is the whole reason it is chosen here.

And a palette cannot say everything either -- there is no role for a group
box's title or a header's sections, and none for which control is a control --
so a small stylesheet covers what is left.  It is deliberately short: every
rule it does not carry is the palette's job, and nearly every rule it does
carry is a colour that is a *border*, a *title* or an *idle sentence* rather
than a fill.  The one exception is the state of a check box, which nothing
else can say.

This is applied once, to the application, before any window is built: a style
set afterwards does not reach what is already on screen.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

from .card import (
    BODY,
    DIM,
    DIV,
    GROUND,
    HEAD,
    LABEL,
    LINE,
    PANEL,
    TABULAR,
    TABULAR_ON,
    TILE_BG,
)

__all__ = ["WHITE", "apply_theme"]

#: Where the faces that travel with the tool live.  Beside this file when the
#: tool runs out of a checkout, and under the bundle's own root when it is a
#: packaged executable -- PyInstaller points a frozen module's ``__file__`` at
#: the extracted copy, so the two layouts resolve the same way.
FONT_DIR = Path(__file__).resolve().parent / "fonts"

#: A button, and anything else that sits *on* the ground rather than in a
#: panel.  The palette has no raised neutral -- the site's cards are flat and
#: its buttons are its links -- so this is ``DIV`` (the chip border) with just
#: enough light added to read as a surface.
RAISED = "#232220"

#: A selected row.  The same step again from ``DIV``: the tile a click lands on
#: is outlined in ``HEAD``, and a table row has no outline to give, so it takes
#: the fill instead.  ``HEAD`` written on it is legible; ``BODY`` would not be.
SELECT = "#3a3227"

#: The bevels below every rule.  The darkest the palette goes, so that a
#: shadowed edge reads as an edge and not as dirt.
SHADOW = "#0c0b0a"

#: What everything the player operates is outlined in -- the check boxes in the
#: rail, the search box, the two filter boxes over the collection and the
#: number boxes in them.  The one colour in the window that is not the card
#: palette's and not derived from it: nothing in a dark warm palette is close
#: enough to read as *contrast*, and a hairline in ``DIV`` or ``LINE`` -- which
#: is what these were drawn in -- is a control the eye has to find before it
#: can use it.
WHITE = "#ffffff"

#: The site's own body font -- ``body{font:13px/1.45 "Segoe UI",Roboto,...}``
#: in its stylesheet -- with the same stack behind it.  It is what every line
#: the card does not size itself is set in: a stat line, a set rung, a tooltip,
#: a row of the collection.  Segoe UI is the first family on Windows and is
#: what the site's readers see there too; the rest are what the platform has if
#: it is not.
SANS = ("Segoe UI", "Roboto", "Helvetica", "Arial", "sans-serif")
#: And its size.  Qt's own default on Windows is the system's 9pt, which is
#: 12px at the 96dpi the site's own 13px is measured at, so this is one step up
#: rather than a different scheme.
BODY_PX = 13


def _load_fonts() -> tuple[str, ...]:
    """Register the faces that travel with the tool, before anything is drawn.

    A face has to be added to the application's own database rather than named
    in a stylesheet: the stylesheet asks for a *family*, and a family is only
    there once the file behind it has been registered.  ``addApplicationFont``
    is what registers it, and it has to happen before the first widget is
    built, because a widget resolves its font once.

    A missing or unreadable file is not an error here.  The tool would then be
    drawn in the fallbacks the stack already names, which is what it did before
    the face was shipped -- a worse card, not a broken one.

    Returns the families it registered.  A variable font answers with its named
    instances as well as its own name -- Bitter's ``wght`` axis is exposed as
    Thin, ExtraLight, Light, Regular and so on -- so the names are deduplicated
    and the family itself is always first.
    """
    families: dict[str, None] = {}
    for face in sorted(FONT_DIR.glob("*.ttf")):
        registered = QFontDatabase.addApplicationFont(str(face))
        for family in QFontDatabase.applicationFontFamilies(registered):
            families.setdefault(family, None)
    return tuple(families)


def _base_font() -> QFont:
    """The application's font: the site's body voice.

    Tabular figures as well, because the site asks for them wherever a number
    is lifted and a lifted number is most of what this window shows: the
    levels, counts and slots down the collection's columns, and any card line
    the card's own serif does not set.  Qt has no
    ``font-variant-numeric`` -- see :data:`app.card.TABULAR` -- and a face
    without such a figure set ignores the request.
    """
    font = QFont()
    font.setFamilies(list(SANS))
    font.setPixelSize(BODY_PX)
    font.setFeature(TABULAR, TABULAR_ON)
    return font


def _palette() -> QPalette:
    """The card palette, as Qt's roles.

    The mapping is the obvious one wherever the palette has a counterpart:
    the ground is the window, a panel is a table's background, the hairline is
    every border.  The rest are the roles Qt fills in from nothing, and each
    is chosen from the card palette rather than defaulted, because a default
    is a light-theme value.
    """
    role = QPalette.ColorRole
    group = QPalette.ColorGroup
    palette = QPalette()

    palette.setColor(role.Window, QColor(GROUND))
    palette.setColor(role.WindowText, QColor(BODY))
    #: A table's rows and an input's field: the card's panel, which is what a
    #: panel is.  Its alternate is the darker of the two grounds the site has,
    #: so alternating rows read as two shades of the same thing rather than as
    #: a stripe.
    palette.setColor(role.Base, QColor(PANEL))
    palette.setColor(role.AlternateBase, QColor(TILE_BG))
    palette.setColor(role.Text, QColor(BODY))
    palette.setColor(role.PlaceholderText, QColor(DIM))
    palette.setColor(role.Button, QColor(RAISED))
    palette.setColor(role.ButtonText, QColor(BODY))
    palette.setColor(role.BrightText, QColor(HEAD))
    palette.setColor(role.Highlight, QColor(SELECT))
    palette.setColor(role.HighlightedText, QColor(HEAD))
    palette.setColor(role.ToolTipBase, QColor(RAISED))
    palette.setColor(role.ToolTipText, QColor(BODY))
    palette.setColor(role.Link, QColor(LABEL))
    palette.setColor(role.Light, QColor(RAISED))
    palette.setColor(role.Midlight, QColor(DIV))
    palette.setColor(role.Mid, QColor(DIV))
    palette.setColor(role.Dark, QColor(LINE))
    palette.setColor(role.Shadow, QColor(SHADOW))

    # Disabled, said out loud.  Qt's own greys for this group are the light
    # theme's -- mid-grey on a dark ground, which is *brighter* than the text
    # around it.  The point of a disabled control here is that it recedes.
    for text in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(group.Disabled, text, QColor(DIM))
    palette.setColor(group.Disabled, role.Base, QColor(GROUND))
    palette.setColor(group.Disabled, role.Button, QColor(GROUND))
    palette.setColor(group.Disabled, role.Highlight, QColor(LINE))
    palette.setColor(group.Disabled, role.HighlightedText, QColor(DIM))
    return palette


#: What a palette cannot say.  A group box's title, a header view's sections,
#: the handle between two panes, and the two idle sentences -- the status line
#: and a missing item's placeholder -- are all drawn in a colour the palette
#: has no role for, and all of them are the same kind of thing: a word that is
#: there to be read second.  ``DIM`` and ``LABEL`` are the palette's own two
#: answers to that, and this is where they are spent.
#:
#: And what a palette cannot say *at all*: which control is a control.  Every
#: rule below that carries :data:`WHITE` is one of those -- the rail's check
#: boxes, the search box, the two filter boxes and the number boxes in them --
#: and they are here together rather than in the widgets that draw them,
#: because they are one decision: the controls are the only white in the
#: window.  The two boxes are found by object name because the three panes are
#: group boxes too, and a pane is a region rather than a control.
_STYLE = f"""
QGroupBox {{
    border: 1px solid {LINE};
    border-radius: 4px;
    margin-top: 9px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    color: {LABEL};
}}
QGroupBox#filterbox {{
    border: 1px solid {WHITE};
}}
QHeaderView::section {{
    background-color: {RAISED};
    color: {DIM};
    border: 0;
    border-bottom: 1px solid {LINE};
    padding: 3px 6px;
}}
QTableView {{
    border: 1px solid {LINE};
    gridline-color: {LINE};
    selection-background-color: {SELECT};
    selection-color: {HEAD};
}}
QTreeView {{
    border: 1px solid {LINE};
}}
/* A ticked box is a filled one rather than a ticked one: Qt's stylesheet
   language can draw a box's fill and its border but not a check mark, which
   needs an image file this application does not ship.  A solid white square
   against a hollow one is what the rarity chips beside it do -- their
   indicator is collapsed to nothing and the pill itself is the control -- and
   at 13px it is the reading a glance gets.  A group row is half filled, which
   is the same idea for a box that is neither on nor off. */
QTreeView::indicator {{
    width: 13px;
    height: 13px;
    border: 1px solid {WHITE};
    border-radius: 3px;
    background: transparent;
}}
QTreeView::indicator:checked {{
    background: {WHITE};
}}
QTreeView::indicator:indeterminate {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {WHITE}, stop: 0.5 {WHITE},
        stop: 0.5 rgba(255, 255, 255, 0), stop: 1 rgba(255, 255, 255, 0));
}}
QSplitter::handle {{
    background-color: {LINE};
}}
QSplitter::handle:horizontal {{
    width: 3px;
}}
QStatusBar {{
    color: {DIM};
}}
QStatusBar::item {{
    border: 0;
}}
QToolTip {{
    background-color: {RAISED};
    color: {BODY};
    border: 1px solid {LINE};
    padding: 4px;
}}
/* The search box is found by name because a spin box holds a line edit of its
   own, and a rule on ``QLineEdit`` would reach inside it and draw a second
   border a few pixels from the first. */
QLineEdit#search {{
    border: 1px solid {WHITE};
    border-radius: 3px;
    padding: 3px 6px;
}}
QSpinBox {{
    border: 1px solid {WHITE};
    border-radius: 3px;
    padding: 1px 3px;
}}
#banner {{
    color: {LABEL};
    font-size: 12px;
}}
"""


def apply_theme(app: QApplication) -> None:
    """Make the application dark, once, before any window exists.

    The faces first, then the style, the palette and the font, then the
    stylesheet: the style decides which roles it consults, so a palette set
    under a style that ignores it would be a colour scheme that never arrives,
    and a font set before the faces are registered would be resolved against a
    database that did not have them yet.
    """
    _load_fonts()

    style = QStyleFactory.create("Fusion")
    if style is not None:  # pragma: no cover -- Fusion ships with every Qt
        app.setStyle(style)
    app.setPalette(_palette())
    app.setFont(_base_font())
    app.setStyleSheet(_STYLE)
