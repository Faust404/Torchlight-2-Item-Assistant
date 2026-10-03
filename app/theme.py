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
than a fill.  Three exceptions, and all of them are the rail's: the state of a
check box, which nothing else can say; the rail's row rhythm -- the air the
reference gets from a line height, which Qt has no property for at all; and the
rail's ground, which the palette would otherwise paint as the field the wall of
cards is drawn on.

This is applied once, to the application, before any window is built: a style
set afterwards does not reach what is already on screen.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QComboBox, QStyleFactory

from .card import (
    BODY,
    DIM,
    HEAD,
    LABEL,
    TABULAR,
    TABULAR_ON,
)

__all__ = [
    "CHALK",
    "EDGE",
    "FIELD",
    "PALE",
    "SHELL",
    "WALL",
    "Dropdown",
    "apply_theme",
]

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

#: The rail's own size, one step up from the body's, and the size *every* row
#: of it is drawn at -- the kinds and the headings over them alike.
#:
#: The rail is a column of kind names down the left edge with a window's worth
#: of height to spare and nothing else in it, and its words are the one thing
#: the player aims at there; the user's own reading, and the reason they asked
#: for it.  A step rather than a jump: the column the words are drawn in is
#: about 180 pixels wide at a 1920 window -- 260 at 2560 -- and the longest
#: kind names are already the ones that elide, so a size the column cannot
#: hold would trade a small word for half a word.
#:
#: The headings used to be a step *below* this, which is what the user then
#: asked to have put right -- a heading smaller than the words it heads reads
#: as an afterthought -- so :mod:`app.sidebar` names this constant for all
#: three levels and tells them apart by ink, weight and case instead.  Measured
#: before the change went in: the longest heading, ``TWO-HANDED``, comes to
#: 105 of the 130 pixels a subgroup row has at the pane's default width.
#:
#: Three things are drawn at this size and they are one number written once --
#: the rows, the box at the head of each of them, which is a square in the
#: theme's own sheet rather than anything the style measures, and every heading
#: in :mod:`app.sidebar`.  That is why it is here and not in that module: the
#: sheet is what draws two of the three.
RAIL_PX = 15


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
/* The rail's own voice, and the one place a widget sets its own size: it is a
   column of kind names with height to spare, so the words are set a step up
   from the window's body -- see RAIL_PX.  That is the size of every row, not
   only of the kinds: the headings are set the same size from the same constant
   in app.sidebar, and are told apart by their ink instead.  Found by name
   rather than as ``QTreeView`` because this is a rule about the rail, not about
   trees.

   Its ground is here for the same reason.  A view's viewport is painted in the
   palette's ``Base``, which is the field -- so left alone the rail would be the
   same surface as the wall of cards beside it, and the band under the pointer
   below would be drawn in the colour it is already on.  The reference's own
   column sits on the shell with a lighter row under the pointer; this is that
   pairing, and it is what makes the band read as a lift. */
QTreeView#rail {{
    font-size: {RAIL_PX}px;
    background: {SHELL};
}}
/* The rail's row rhythm, which is the reference's: it draws a facet row at
   ``padding:2px 4px`` with a line height of 1.7, and Qt has no ``line-height``
   -- so the air between one kind and the next is put back as padding, and 4px
   is what measures 26px at RAIL_PX.  The band under the pointer is the
   reference's too: a step up from the ground the row sits on. */
QTreeView#rail::item {{
    padding: 4px 0;
}}
QTreeView#rail::item:hover {{
    background: {FIELD};
}}
/* A ticked box is a filled one rather than a ticked one: Qt's stylesheet
   language can draw a box's fill and its border but not a check mark, which
   needs an image file this application does not ship.  A solid white square
   against a hollow one is what the rarity chips beside it do -- their
   indicator is collapsed to nothing and the pill itself is the control -- and
   at the size of the words beside it, it is the reading a glance gets.  A
   group row is half filled, which is the same idea for a box that is neither
   on nor off. */
QTreeView::indicator {{
    width: {RAIL_PX}px;
    height: {RAIL_PX}px;
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
/* The text boxes -- the search box over the collection, the advanced search's
   Name row, and one per property row in its Stats section -- are found by name
   because a spin box holds a line edit of its own, and a rule on ``QLineEdit``
   would reach inside it and draw a second border a few pixels from the first.
   The three that are named are the three there are: everything else that takes
   typing in this application is a number box. */
QLineEdit#search, QLineEdit#advname, QLineEdit#advstat {{
    border: 1px solid {CHALK};
    border-radius: 3px;
    padding: 3px 6px;
}}
QSpinBox {{
    border: 1px solid {CHALK};
    border-radius: 3px;
    padding: 1px 3px;
}}
/* The sort box, outlined like the number boxes it stands between -- and
   outlined *only*: the moment the sheet claims the drop-down subcontrol, Qt
   draws it as an empty rectangle, because an arrow in the stylesheet language
   is an image file and this application ships none.  Left to the style, the
   arrow is Fusion's own, and the list it opens is built from the palette --
   a field for the rows, the window's selection on the one under the
   pointer -- so the popup comes out dark without a rule of its own.

   Its padding is what makes the box a little wider than its longest word
   needs, which is the user's own ask: the drop-down should not read as
   tight against the key it is showing.  Six more pixels either side of the
   word, and the *box* is the thing that grows, so the arithmetic that says a
   filter box is as wide as its contents and no wider still holds. */
QComboBox#sort {{
    border: 1px solid {CHALK};
    border-radius: 3px;
    padding: 1px 9px;
}}
/* The reverse arrow, which is the one control in the row that has to be told
   how wide it is: left to the style it is a bare ``QPushButton``, and Fusion
   gives those a *floor* of 80 pixels whatever is written on them -- so a
   single glyph sat in a button three times the width of the drop-down beside
   it, which is what the user pointed at.  The floor is not a number the
   style will let anyone lower; claiming the widget in this sheet is what
   takes it away, because a styled button is measured from its own box model.
   The outline is the one the combo beside it wears, so the two still read as
   one control with two halves. */
QPushButton#reverse {{
    color: {CHALK};
    border: 1px solid {CHALK};
    border-radius: 3px;
    padding: 3px 12px;
}}
/* The stranded toggle while it is on, which is the one thing on the row that
   stands for a *view* rather than for an action -- and a view that is showing
   something other than the collection is exactly the thing a player cannot
   tell from the outside.  So it wears the window's own word for "this one is
   chosen", the same warm fill and tan ink a selected row and the collection's
   ticks wear, and it wears it only while it is on: at rest it is an ordinary
   button beside ``Refresh``, because a control that is always lit cannot say
   that the view it opens is the one on screen.

   Claimed in the sheet for the size as much as for the colour.  The moment a
   state has a rule, that state is measured from its own box model instead of
   Fusion's -- so the padding is the one that measures *exactly* what the
   unchecked button measures (146x23 against 146x23, measured), and the button
   does not twitch as it is ticked.  Only ``:checked`` is claimed, so the two
   states still sit on the row as two states of one control. */
QPushButton#stranded:checked {{
    background: {SELECT};
    color: {HEAD};
    border: 1px solid {EDGE};
    border-radius: 3px;
    padding: 3px 6px;
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


class Dropdown(QComboBox):
    """A combo box whose list opens *downwards*, whatever entry is showing.

    The sheet above is what this is for.  A stylesheet puts
    ``QStyleSheetStyle`` in front of Fusion for every widget it touches, and
    that style answers ``SH_ComboBox_Popup`` with *yes* -- Qt's menu-like
    mode, which places the popup so that the entry that is currently showing
    sits exactly over the box and the entries above it hang above the box.  At
    the first entry that cannot be seen; at any other the list opens upwards,
    which is what the user reported on the save box, whose second entry is the
    other save.  Measured with the sheet applied: the popup's top lands 23
    pixels above the box at the second entry -- one row -- and just below it at
    the first, so the same box opened two ways depending on which save was
    showing.  Without the sheet every Windows style answers the hint with *no*
    and opens below the box, which is what a combo box on this platform is
    expected to do.

    So the list is put below the box: the container Qt has just placed and
    shown is moved down until its top edge is at the box's bottom edge, and it
    is pulled back up only by the part of it the screen cannot hold.  Nothing
    else about the popup is touched -- the row under the pointer, the
    highlight, the scrolling, the closing are all still Qt's -- and the
    position no longer depends on which entry is showing.

    Only for the two boxes this window has, both a handful of rows: the
    menu-like mode is also what gives a long list its scrollers, and a list
    long enough to need them would be a different question.
    """

    def showPopup(self) -> None:
        super().showPopup()
        popup = self.view().window()
        if popup is self:  # pragma: no cover -- no native menu popups here
            return
        screen = QGuiApplication.screenAt(self.mapToGlobal(self.rect().center()))
        if screen is None:  # pragma: no cover -- a box on no screen
            return

        below = self.mapToGlobal(QPoint(0, self.height())).y()
        room = screen.availableGeometry()
        top = max(min(below, room.bottom() + 1 - popup.height()), room.top())
        popup.move(popup.mapToGlobal(QPoint(0, 0)).x(), top)

