"""The row over the collection: the search box, the rarities, the level range.

Three of the four things that narrow a collection, in one row above the cards
rather than in a column beside them -- which is where the reference tool puts
them, and where they cost the wall none of its width.  The row sits over the
collection and not across the whole window, so that the controls are next to
the only pane they narrow.  The fourth, the kinds, stays in the rail: a kind
has a path (a sword is a one-handed weapon) and a tree is the only control
that says so, while a tree drawn across the top of a window is a tree nobody
reads.

The counts on the chips are what a tick *would* leave rather than what it does
leave -- see :meth:`app.models.CollectionFilter.counts` -- so the number beside
a chip stays worth reading while another one is ticked.

Nothing here decides anything.  It draws what it is told to draw, says what is
ticked, and emits :attr:`FilterBar.changed`; :class:`~app.models.
CollectionFilter` is what makes that mean anything.
"""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from tl2stash.card import TIER_INK

from .card import DIM
from .models import LEVEL_MAX, TIER_CHIPS

__all__ = ["FilterBar"]

#: How dim a chip is drawn when it is not ticked.
OFF_INK = "#6f6963"
OFF_BORDER = "#33302c"


def _chip_style(ink: str) -> str:
    """A rarity chip: the tier's own colour, in the reference's pill shape.

    Tinted while ticked and grey while not, so that a glance down the bar says
    which rarities are in play without reading a single word.  The indicator is
    collapsed to nothing and the pill itself is the control -- a checkbox's box
    beside a coloured pill is two things saying one thing.
    """
    return (
        "QCheckBox {"
        f" color: {ink};"
        f" border: 1px solid {ink};"
        " border-radius: 9px; padding: 3px 8px;"
        " background: rgba(255, 255, 255, 0.05);"
        "}"
        "QCheckBox::indicator { width: 0px; height: 0px; }"
        "QCheckBox:!checked {"
        f" color: {OFF_INK}; border-color: {OFF_BORDER}; background: transparent;"
        "}"
    )


def _heading(text: str) -> QLabel:
    """A small dim word introducing the controls beside it.

    Five pills reading their own names need no introduction; a pair of boxes
    saying "Any" and "Any" do, which is what this is for.
    """
    label = QLabel(text)
    label.setStyleSheet(f"QLabel {{ color: {DIM}; }}")
    return label


class FilterBar(QWidget):
    """The four controls that narrow a collection by something other than kind."""

    #: Something was typed, ticked or spun.  One signal for all of them, because
    #: the window does one thing with it: re-apply every facet and re-count.
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        #: True while this widget is writing to itself -- a reset, most of all
        #: -- so that its own writes do not come back round as the player
        #: having changed something.
        self._updating = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the collection…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(260)
        self.search.setToolTip(
            "Show only the items whose name contains this.\n"
            "It narrows what the ticks beside it leave."
        )
        self.search.textChanged.connect(self._moved)
        row.addWidget(self.search)

        row.addSpacing(10)
        row.addWidget(_heading("Rarity"))
        self.chips: dict[str, QCheckBox] = {}
        for word in TIER_CHIPS:
            chip = QCheckBox(word)
            chip.setStyleSheet(_chip_style(TIER_INK[word.lower()]))
            chip.setToolTip(f"Show only the {word.lower()} items.")
            chip.toggled.connect(self._moved)
            row.addWidget(chip)
            self.chips[word] = chip

        row.addSpacing(10)
        row.addWidget(_heading("Level"))
        self.low = self._spin(0)
        self.high = self._spin(LEVEL_MAX)
        row.addWidget(self.low)
        row.addWidget(QLabel("to"))
        row.addWidget(self.high)

        row.addStretch(1)
        self.clear_button = QPushButton("Clear filters")
        self.clear_button.setToolTip("Untick everything, in the bar and in the rail.")
        self.clear_button.clicked.connect(self.reset)
        row.addWidget(self.clear_button)

    def _spin(self, value: int) -> QSpinBox:
        """A min or a max: two levels, both ends included.

        The boxes used to read ``Any`` at zero, which was one word for "do not
        ask" -- two things a level box can mean, and only one of them is a
        level.  Zero is one: a socketable is level 0 and the collection holds
        them, so a box the player sets to 0 has to mean the thing it says.
        """
        spin = QSpinBox()
        spin.setRange(0, LEVEL_MAX)
        spin.setValue(value)
        spin.setToolTip(
            "The item levels to show, both ends included.\n"
            f"0 to {LEVEL_MAX} is the whole range, and is where these start."
        )
        spin.valueChanged.connect(self._moved)
        return spin

    # -- what the bar is told --------------------------------------------

    def set_counts(self, tiers: Mapping[str, int] | None = None) -> None:
        """Put the numbers on the chips.

        These are what the filters *would* leave rather than what they do
        leave, so a chip reading zero is a rarity that has nothing behind it
        under the current filters -- see :meth:`app.models.CollectionFilter.
        counts`.
        """
        self._updating = True
        try:
            for word, chip in self.chips.items():
                chip.setText(f"{word}  {(tiers or {}).get(word, 0)}")
        finally:
            self._updating = False

    # -- what the bar says -----------------------------------------------

    def search_text(self) -> str:
        """What is in the box, which the proxy matches as a fixed string."""
        return self.search.text()

    def tiers(self) -> set[str]:
        """The rarity words that are ticked."""
        return {word for word, chip in self.chips.items() if chip.isChecked()}

    def level_range(self) -> tuple[int, int]:
        """The bounds, both of them levels and both ends included.

        What comes out is the whole range until the player narrows it, so the
        two boxes say what they are letting through rather than standing in for
        a question nobody asked.
        """
        return (self.low.value(), self.high.value())

    # -- the user --------------------------------------------------------

    def _moved(self, *_) -> None:
        if not self._updating:
            self.changed.emit()

    def reset(self) -> None:
        """Put every control back, which is the state the window starts in."""
        self._updating = True
        try:
            self.search.clear()
            for chip in self.chips.values():
                chip.setChecked(False)
            self.low.setValue(0)
            self.high.setValue(LEVEL_MAX)
        finally:
            self._updating = False
        self.changed.emit()
