"""What a row of the collection list knows about its item, once per item.

Both lists are rebuilt on every poll -- the game saves, and the tables are
redrawn -- so everything on that path has to be cheap.  But the three things a
row shows beside its columns are not cheap: the tier comes down a chain of the
game's data files, the kind comes out of the same string, and the picture is a
crop out of a 512x512 sheet.  A hundred rows would do all of that a hundred
times, every two seconds.

:class:`Catalog` answers those questions once per item and keeps the answers,
keyed by fingerprint -- a hash of the item's own bytes, so an answer cannot go
stale and nothing ever needs invalidating.  A poll is then a dict lookup per
row, and the expensive path stays where it belongs: behind the selection, in
:mod:`tl2stash.tooltip`.

The tier is the one thing here that is not simply read out of a data file.  A
Normal item that has had magic put on it is shown green in the game, and no
data file says so, because it is the instance's and not the base file's --
``tl2stash.card.display_tier`` is where that is decided.  Which is why this
reads a registry row's own ``prefix``, ``suffix`` and ``num_enchants`` and not
only its ``guid``: the list and the card must not be able to come to different
answers about the same item, and the fields the answer is made of are already
in every row.

This is Qt, unlike the rest of ``tl2stash``, because it owns the finished
:class:`~PySide6.QtGui.QIcon`.  ``app.card`` says what a tile looks like and
``tl2stash.taxonomy`` says where a kind belongs; this is what joins them to an
item.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from tl2stash.card import TIER_INK, TIER_KEYS, TIER_NONE, display_tier
from tl2stash.taxonomy import OTHER, Place, group_of

from .card import IconCache, paint_tile

if TYPE_CHECKING:  # pragma: no cover
    from tl2stash.gamedata import GameData

__all__ = ["ICON_SIZE", "Catalog", "Entry", "Facts"]

#: How big a list row's picture is drawn.  Smaller than the card's own 58,
#: because a row is one line tall and the card's tile is a headline; both are
#: the same picture at two sizes, drawn by the same function.
#:
#: Small, because the width it costs comes out of the item's *name*: "In the
#: game" is a narrow pane by design, and a 40px tile in it left about fifty
#: pixels of text -- "Alhi... Amulet".  At 24 the whole name fits and the
#: picture still reads as what it is: the game's own art, in the tier's colour.
ICON_SIZE = 24


@dataclass(frozen=True)
class Facts:
    """An item's instance side: the four fields anything here reads.

    Two different things in this tool can answer for an item, and they do not
    share an interface.  A freshly selected item is a parsed
    :class:`~tl2stash.item.Item`, which answers to attributes.  A row of the
    collection is a ``sqlite3.Row``, which answers to keys and to nothing else
    -- reading ``row.prefix`` is an ``AttributeError``, not a missing field.
    Both are turned into this before anything is asked of them, so that the
    tier rule and the appearance lookup are written once rather than once per
    shape.

    ``guid`` is an ``int`` here whatever it arrived as.  The registry stores it
    as uppercase hex text, because a 64-bit guid does not fit SQLite's signed
    integer; the save file's own field is the integer, and that is what the
    data files are indexed by -- and it is all
    :meth:`~tl2stash.gamedata.GameData.requirements_for` needs, which is why
    that one is asked of these four fields rather than of a whole item.
    """

    guid: int
    prefix: str
    suffix: str
    num_enchants: int

    @classmethod
    def of(cls, item: object) -> "Facts":
        """Read the four fields off a parsed item, or off a registry row."""

        def read(name: str):
            try:
                return item[name]  # type: ignore[index]
            except TypeError:
                # Not a mapping: an Item, which answers to attributes.
                return getattr(item, name)

        guid = read("guid")
        return cls(
            guid=int(guid, 16) if isinstance(guid, str) else int(guid),
            prefix=read("prefix") or "",
            suffix=read("suffix") or "",
            num_enchants=read("num_enchants") or 0,
        )


@dataclass(frozen=True)
class Entry:
    """One item, as far as a list row and a sidebar need to know it.

    ``tier`` is the colour key -- one of ``TIER_KEYS``' values or
    ``TIER_NONE`` -- and ``tier_word`` is the same thing in the words the card
    prints (``Magic``, ``Unique``), or empty for an item with no rarity to
    show.  The list colours by the first and the rarity filter matches on the
    second, so a ticked chip and a drawn card are talking about the same thing.

    ``kind`` is the game's own word for what the thing is, ``Boots`` or
    ``1H Mace``, and is empty for an item whose file says none -- a spell, a
    fish, or anything on a machine with no game installed.  ``group`` and
    ``subgroup`` are where :func:`tl2stash.taxonomy.group_of` puts that kind.

    ``gate`` is the player level the game makes a character reach before it
    will let them use the item, which is *not* the item's own level: a level 45
    unique can ask for 51, and a potion asks for nothing at all.  ``None``
    means the question could not be answered -- no game installed, or an item
    the game's files have never heard of -- and is not the same as ``0``, which
    is the answer for an item the game gates on nothing.  A list with an
    unanswerable level in it falls back to the item's level, which is what the
    tool showed before it could ask; see :func:`app.models._describe`.
    """

    tier: str
    tier_word: str
    kind: str
    group: str
    subgroup: str | None
    icon: QIcon | None
    gate: int | None

    @property
    def place(self) -> Place:
        """Where this item sits in the rail, as :mod:`tl2stash.taxonomy` names
        it -- the one value the kind filter and the sidebar both speak in."""
        return (self.group, self.subgroup, self.kind)


class Catalog:
    """The answers above, one per item, kept for as long as the window is.

    With no game data every item comes back tier ``none``, kind ``''``, group
    ``Other`` and no icon at all -- which is not a failure state but the
    honest answer on a machine without the game, and a list of names is what
    that machine should show.
    """

    def __init__(
        self, game: "GameData | None", icons: IconCache | None = None
    ) -> None:
        self.game = game
        self.icons = icons
        self._entries: dict[str, Entry] = {}
        # Keyed by what a tile is made of rather than by item, because a tile
        # *is* that: two items wearing the same icon at the same tier are the
        # same picture, and there are a few hundred icons against thousands of
        # items.
        self._tiles: dict[tuple[str, str, str], QIcon] = {}

    def entry(self, fingerprint: str, item: object) -> Entry:
        """What this item is, computed once and remembered by fingerprint."""
        known = self._entries.get(fingerprint)
        if known is None:
            known = self._read(Facts.of(item))
            self._entries[fingerprint] = known
        return known

    def _read(self, facts: Facts) -> Entry:
        if self.game is None:
            return Entry(
                tier=TIER_NONE,
                tier_word="",
                kind="",
                group=OTHER,
                subgroup=None,
                icon=None,
                gate=None,
            )

        # What the item gates on, which the level filter needs and the row
        # itself does not draw.  Asked before the appearance because the two
        # are different questions: an item can be one the game has a gate for
        # and no *look* for, and the other way round.
        requires = self.game.requirements_for(facts)

        appearance = self.game.appearance_for(facts)
        if appearance is None:
            # The game is here and this item is not in it: a mod's item, or
            # one whose data file has been removed.  It gets a tile where the
            # others have pictures, because a hole in an illustrated column
            # reads as a missing row rather than as an unknown item.
            return Entry(
                tier=TIER_NONE,
                tier_word="",
                kind="",
                group=OTHER,
                subgroup=None,
                icon=self._tile(TIER_NONE, None, ""),
                gate=None if requires is None else requires.level,
            )

        word = display_tier(appearance.tier, facts)
        group, subgroup = group_of(appearance.type_name)
        return Entry(
            tier=TIER_KEYS.get(word, TIER_NONE),
            tier_word=word,
            kind=appearance.type_name,
            group=group,
            subgroup=subgroup,
            icon=self._tile(word, appearance.icon, appearance.type_name),
            gate=None if requires is None else requires.level,
        )

    def _tile(self, tier_word: str, icon_name: str | None, kind: str) -> QIcon:
        """The row's picture: the item's icon on the colour of its tier."""
        key = TIER_KEYS.get(tier_word, TIER_NONE)
        pixmap = self.icons.icon(icon_name) if self.icons is not None else None
        # The card's own fallback, at list size: the kind's initial, or a
        # question mark when there is not even a kind to take one from.
        letter = (kind.strip() or "?")[:1].upper()

        found = self._tiles.get((key, icon_name or "", letter))
        if found is None:
            found = self._tiles[(key, icon_name or "", letter)] = _draw_tile(
                TIER_INK[key], pixmap, letter
            )
        return found


def _draw_tile(ink: str, icon: QPixmap | None, letter: str) -> QIcon:
    """A tile painted into a pixmap, for the list to draw at row size."""
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_tile(painter, ICON_SIZE, ICON_SIZE, QColor(ink), icon, letter)
    painter.end()

    return QIcon(pixmap)
