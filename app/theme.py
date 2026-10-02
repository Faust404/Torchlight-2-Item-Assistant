"""The window's own colours: dark, by default.

The things the eye spends its time on here are the cards, and a card is dark --
it is the game's own look, taken from the reference site's stylesheet, and
:mod:`app.card` says why.  An application that drew those cards on the
platform's light chrome would be arguing with itself about which of the two is
the screen.  So the window is dark too, and the colours below are its own: a
short ramp of black-greys, given from the ground up.

The ramp is anchored on -- and is not -- the card palette.  A card is what an
item is *compared against*, so its colours are the site's and are not the
window's to move: ``PANEL`` is the surface of every card in the tool, and it
stays that.  The window's own surfaces are a shade up from it, which is the
change the user asked for and the reason it was asked for: what the player
*operates* is outlined in :data:`CHALK` (:data:`CHALK` alone -- a web page has
no controls to outline, so there is nothing in the card palette to derive it
from), and a hairline on near-black is glare rather than contrast.  That is one
complaint with two ends, and both have now been moved: the ground came up, and
then the hairline came down.  The buttons that stand *on* a card are the same
argument one step down -- see :data:`PALE` -- because a card's footer is a word
at 11px.  One surface goes
the other way, and it goes further: :data:`WALL` is what the tool's cards are
drawn on, and it is darker than the cards, so that an item lying in the tool
reads as a card in a drawer rather than as a panel in a panel.

Each colour says below what it is a shade *of* -- a wall, a shell, a field --
and the shades that are derived say what they are derived from, so the ramp can
be moved by moving one end of it.  The one thing the window takes from the
cards is the words: the four text colours are :mod:`app.card`'s, so a label on
the window and a label on a card are the same grey.

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
    HEAD,
    LABEL,
    TABULAR,
    TABULAR_ON,
)

__all__ = ["CHALK", "EDGE", "FIELD", "PALE", "SHELL", "WALL", "apply_theme"]

#: Where the faces that travel with the tool live.  Beside this file when the
#: tool runs out of a checkout, and under the bundle's own root when it is a
#: packaged executable -- PyInstaller points a frozen module's ``__file__`` at
#: the extracted copy, so the two layouts resolve the same way.
FONT_DIR = Path(__file__).resolve().parent / "fonts"

#: What the tool's cards are drawn on: the darkest surface in the window, and
#: the one place the ramp goes *below* the cards.  A card is the same object in
#: both panes -- the game's stash and the tool -- so the two cannot differ in
#: what they put on a card; they differ in what they put a card on, and this is
#: the tool's: darker than a card, so an item in the tool reads as a card in a
#: drawer rather than as a panel in a panel.  The site has the same idea one
#: step gentler -- its page is darker than its cards -- and this is that idea
#: taken as far as the window's own ramp allows.
WALL = "#0b0a09"

#: The window itself, and every pane in it.  A shade *up* from the cards rather
#: than level with them: what the player operates is outlined in :data:`CHALK`
#: (below), and a hairline on a near-black ground is glare rather than contrast
#: -- the reason the user asked for the lightening, and what it buys.
SHELL = "#1e1c19"

#: A field: a table's rows, the box a value is typed into.  The palette's
#: ``Base``, one step up from the shell so that a field reads as a surface with
#: something on it rather than as a hole in the pane.
FIELD = "#242220"

#: The alternate row.  *Darker* than the field, because the two have to read as
#: two shades of one thing and not as a stripe -- and the recessed shade is the
#: one that says "every other", where the raised one would say "these ones".
STRIPE = "#1b1916"

#: A button, and anything else that sits *on* the ground rather than in a panel:
#: the header's sections, a tooltip.  The site's cards are flat and its buttons
#: are its links, so there is nothing in the card palette to take this from; it
#: is :data:`FIELD` with the same step added again.
RAISED = "#2e2b27"

#: The window's own hairlines -- a pane's frame, a gridline, the handle between
#: two panes.  The card palette's ``LINE`` is a hairline *inside* a card, drawn
#: a shade from the surface it is drawn on; on the shell that is invisible, so
#: the window's edges are their own colour, two steps further up the ramp.  The
#: cards keep ``LINE``: this is the window's, not theirs.
EDGE = "#37332e"

#: A selected row.  Warm rather than grey, because it is the same statement a
#: card's title makes and ``HEAD`` -- the card's own title colour -- is written
#: on it.  ``HEAD`` on this is legible; ``BODY`` would not be.
SELECT = "#453a29"

#: The bevels below every rule: shading rather than a surface, so :data:`WALL`
#: is darker without displacing it -- a wall is something to look at, and this
#: is what is drawn under one.  The darkest the *shading* goes, so that a
#: shadowed edge reads as an edge and not as dirt.
SHADOW = "#0c0b0a"

#: What everything the player operates is outlined in -- the check boxes in the
#: rail, the search box, the two filter boxes over the collection, the number
#: boxes in them and the word on every chip.  The one colour in the window that
#: is not a shade of *anything*: nothing in a dark warm ramp is close enough to
#: read as contrast, and a hairline in ``EDGE`` or ``DIV`` -- which is what
#: these were drawn in -- is a control the eye has to find before it can use it.
#:
#: Chalk rather than white, and the user's second thought about it rather than
#: their first.  A control here is an *outline*: this is not one bright thing
#: on a dark screen but a dozen of them, in a row across the top of the
#: collection and a column down the side of it, and at 255 each is the
#: brightest pixel the window can draw -- a glare the eye reads as a fault
#: rather than as contrast, which is the same complaint the lightening of
#: :data:`SHELL` answered from the other end.  Down a step, it is still the
#: lightest ink here, which is the whole of the job it has to do; what it stops
#: being is the only thing on the screen.
CHALK = "#e8e2d8"

#: The word on a button that stands *on* a card -- "Compare & Transfer",
#: "Transfer to Stash", "Transfer all" -- and the hairline that draws it.  The
#: one control the window draws on something the site owns, and the same
#: argument as :data:`CHALK` one step down: the card under it is near-black and
#: the button has to read as an action rather than as another line of the item,
#: which is what the tan it was drawn in -- the card's own ``LABEL`` -- failed
#: to do; but a word at 11px, on every card of a wall, is not where the
#: lightest ink in the window belongs either.  So the word and its outline are
#: :data:`CHALK` let down one step, and the hover is what takes them back up to
#: it.  One step and not two: the ink under it is the card's own ``BODY``, and
#: a button that landed on that would be a line of the item again.
PALE = "#dad4ca"

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
    """The window's ramp, as Qt's roles.

    The mapping is the obvious one wherever the palette has a counterpart: the
    shell is the window, a field is a table's background, an edge is a border.
    The rest are the roles Qt fills in from nothing, and each is chosen from
    the ramp rather than defaulted, because a default is a light-theme value.

    The words are the cards' own -- ``BODY``, ``DIM``, ``HEAD``, ``LABEL`` --
    and that is the one thing here that is *not* the window's.  A window in the
    same voice as what it holds is the point of a theme at all; the surfaces
    are what the user asked to move.
    """
    role = QPalette.ColorRole
    group = QPalette.ColorGroup
    palette = QPalette()

    palette.setColor(role.Window, QColor(SHELL))
    palette.setColor(role.WindowText, QColor(BODY))
    # A table's rows and an input's field: the ramp's field, with the recessed
    # shade for the alternate, so alternating rows read as two shades of one
    # surface rather than as a stripe.
    palette.setColor(role.Base, QColor(FIELD))
    palette.setColor(role.AlternateBase, QColor(STRIPE))
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
    # The bevel, read off the ramp: lit at the top-left, an edge through the
    # middle, shaded at the bottom-right.  A frame is the one thing Fusion draws
    # from all five, so they are given in the order the light would fall.
    palette.setColor(role.Light, QColor(RAISED))
    palette.setColor(role.Midlight, QColor(EDGE))
    palette.setColor(role.Mid, QColor(EDGE))
    palette.setColor(role.Dark, QColor(SHADOW))
    palette.setColor(role.Shadow, QColor(SHADOW))

    # Disabled, said out loud.  Qt's own greys for this group are the light
    # theme's -- mid-grey on a dark ground, which is *brighter* than the text
    # around it.  The point of a disabled control here is that it recedes.
    for text in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(group.Disabled, text, QColor(DIM))
    palette.setColor(group.Disabled, role.Base, QColor(SHELL))
    palette.setColor(group.Disabled, role.Button, QColor(SHELL))
    palette.setColor(group.Disabled, role.Highlight, QColor(EDGE))
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
#: rule below that carries :data:`CHALK` is one of those -- the rail's check
#: boxes, the search box, the two filter boxes and the number boxes in them --
#: and they are here together rather than in the widgets that draw them,
#: because they are one decision: the controls are the only *light* in the
#: window.  The two boxes are found by object name because the three panes are
#: group boxes too, and a pane is a region rather than a control.
_STYLE = f"""
QGroupBox {{
    border: 1px solid {EDGE};
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
    border: 1px solid {CHALK};
}}
QHeaderView::section {{
    background-color: {RAISED};
    color: {DIM};
    border: 0;
    border-bottom: 1px solid {EDGE};
    padding: 3px 6px;
}}
QTableView {{
    border: 1px solid {EDGE};
    gridline-color: {EDGE};
    selection-background-color: {SELECT};
    selection-color: {HEAD};
}}
QTreeView {{
    border: 1px solid {EDGE};
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
    border: 1px solid {CHALK};
    border-radius: 3px;
    background: transparent;
}}
QTreeView::indicator:checked {{
    background: {CHALK};
}}
QTreeView::indicator:indeterminate {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {CHALK}, stop: 0.5 {CHALK},
        stop: 0.5 rgba(255, 255, 255, 0), stop: 1 rgba(255, 255, 255, 0));
}}
QSplitter::handle {{
    background-color: {EDGE};
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
    border: 1px solid {EDGE};
    padding: 4px;
}}
/* The search box is found by name because a spin box holds a line edit of its
   own, and a rule on ``QLineEdit`` would reach inside it and draw a second
   border a few pixels from the first. */
QLineEdit#search {{
    border: 1px solid {CHALK};
    border-radius: 3px;
    padding: 3px 6px;
}}
QSpinBox {{
    border: 1px solid {CHALK};
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
