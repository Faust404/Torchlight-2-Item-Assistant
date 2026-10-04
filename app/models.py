"""Table models for the two lists the window shows.

Two views, deliberately: what the game has and what the tool has.  Keeping
them side by side is what makes the intake model legible -- the player can
watch a thing leave the left column and appear in the right one, which is a
better explanation of what this tool does than any amount of prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor, QStandardItem, QStandardItemModel

from tl2stash.card import TIER_INK
from tl2stash.gamedata import DAMAGE_TYPES
from tl2stash.item import Item
from tl2stash.taxonomy import Place, stack_limit_for

from .catalog import Catalog, Entry

if TYPE_CHECKING:  # pragma: no cover
    from tl2stash.card import Card
    from tl2stash.gamedata import GameData

__all__ = [
    "CLASSES",
    "CLASS_ROLE",
    "COLLECTION_COLUMNS",
    "ELEMENTS",
    "ELEMENT_REST",
    "FINGERPRINT_ROLE",
    "GATE_ROLE",
    "LEVEL_ROLE",
    "MEMBERS_ROLE",
    "NUMBER_MAX",
    "PLACE_ROLE",
    "REQS_ROLE",
    "REQ_MAX",
    "REQ_REST",
    "REQ_WORDS",
    "SET_ROLE",
    "SOCKETS_ROLE",
    "SOCKET_COUNTS",
    "STACKS_ROLE",
    "STACK_ROLE",
    "STASH_COLUMNS",
    "TIER_ROLE",
    "Advanced",
    "CollectionFilter",
    "container_label",
    "fill_collection",
    "fill_stash",
    "new_model",
]

#: What each model's columns are.  The collection is not a table at all any
#: more -- it is a grid of cards drawn from the model's rows -- so its one
#: column is where a row keeps what it knows, and the model is what the filters
#: read.
#:
#: The stash keeps the item, the level it asks for, how many are in the stack
#: and how many sockets it has, which is what a row of that list is for.  The
#: socket count is a column rather than a line on the tooltip because it is the
#: one thing about an item still in the game that decides what happens *next*:
#: a socketed item has to be taken out of the game before its gems can be.  The
#: quantity is a column because a stack is what a fish or a potion *is*: one
#: row saying ``20`` says how much of the stash is that thing, where a line on
#: a tooltip would have to be hovered over twenty times to add up.  Where it sat
#: -- the tab and the slot -- stays on the name cell's tooltip, which costs
#: nothing and explains itself on hover, rather than in two columns nobody
#: reads.
#:
#: Two of the four columns are counts that are mostly nothing, and both are
#: blank rather than a number on every row: the sockets of an item with none,
#: and the quantity of everything that does not stack.  A column of noughts and
#: ones is a column nobody can read at a glance, which is the only reason to
#: have one at all.
STASH_COLUMNS = ["Item", "Lvl", "Qty", "Sockets"]
COLLECTION_COLUMNS = ["Item"]

#: The rarity chips' order and their words, which is the game's own order and
#: the reference's vocabulary.  ``Set`` is not among them because it is not a
#: rarity -- a set piece is Rare or Unique and is shown as what it is -- and
#: neither is the unclassified tail, which is shown when nothing is ticked.
TIER_CHIPS = ("Normal", "Magic", "Rare", "Unique", "Legendary")

#: The ladder the wall opens on, best first: the chips read the other way
#: about, with Legendary lifted off the top and Set put under it.  It is the
#: user's own rule for the default order -- *"legendary first, normal 2nd last,
#: untiered last, and within each tier level 1 to 100"* -- and the one place
#: the tool's order is not the reference's, which runs the other way up.
#:
#: Written as the chips turned round rather than as six words spelled again, so
#: that a rarity cannot be in one list and not the other.  Set is the word here
#: that no chip carries and, over the archive, no item wears either: a set
#: piece states the rarity it displaced and is sorted as what it is.  It is
#: still a rung, because it is one of the six words a card can be coloured by
#: (:data:`tl2stash.card.TIER_KEYS`) and the ladder is a list of those words.
#:
#: What the ladder does *not* name sorts after all of it: the empty word a
#: potion, a fish, a quest object or a mod's item carries, and the two words
#: the game writes that are not rarities at all (``Quest``, ``Level``).  That
#: is the "untiered last" half of the rule, and the reason the rank below is a
#: lookup with a floor rather than an ``index`` that would raise on the first
#: item the game never gave a rarity to.
TIER_LADDER = ("Legendary", "Set", *reversed(TIER_CHIPS[:-1]))

#: Where each of the ladder's words sits, and -- through
#: :data:`TIER_TAIL` -- where everything else does.
TIER_RANK = {word: rung for rung, word in enumerate(TIER_LADDER)}
TIER_TAIL = len(TIER_LADDER)

#: What the sort box offers, in the order it offers them.  The reference's own
#: list.  Its two number orders come last because they are the two that read
#: the item's *card* rather than its row -- the same numbers the panel's Damage
#: and Armor sections narrow -- so they are the two whose first sort builds
#: every card in the collection; see :meth:`CollectionFilter.set_detail`.
#:
#: The first key is what the wall opens on, so the default above is the default
#: here without any part of the window having to say so.
SORT_KEYS = ("Tier", "Name", "Level", "Type", "Damage", "Armor")

#: The top of the level range, and so the level of the box that ends it.
#: Measured over the archive: 5,974 item files state a level and the highest of
#: them is 105 -- the Wanderer's X07 set and a legendary wand -- so this is the
#: round number above the game's own top.  The character cap is 100, and the
#: game's items run past it, which is why the ceiling is not the cap.  A mod's
#: item above 110 would fall outside the default range, which is the one thing
#: this ceiling costs.
LEVEL_MAX = 110

#: The top of a *stat* requirement, and so of the box that ends one of the
#: four ranges in the advanced search.  Measured the same way: of the archive's
#: 6,061 item files that trace back to a requirement table at all, the highest
#: Strength, Dexterity or Focus any of them asks for is 486 and the highest
#: Vitality is 242 -- so, as with :data:`LEVEL_MAX`, this is the round number
#: above the game's own top, and a mod's item asking for more falls outside the
#: default range.
REQ_MAX = 500

#: The four attributes an item can ask of a character, in the order the game
#: lists them and the order the panel's four ranges are in.  The words are
#: :data:`tl2stash.gamedata.REQUIREMENT_FIELDS`'s: Torchlight 2 renamed the
#: first game's Magic to Focus and its Defense to Vitality, and these are the
#: two names the tooltip shows and the two fields it reads.
REQ_WORDS = ("Strength", "Dexterity", "Focus", "Vitality")

#: A range that asks nothing: the pair every requirement range starts at, and
#: so the four the facet rests in.  Spelled once because three places compare
#: against it -- the default, the setter's "has it moved" test and the panel's
#: reading of what is active -- and three spellings of one range is three
#: ranges that can come apart.
REQ_REST = ((0, REQ_MAX),) * len(REQ_WORDS)

#: The five damage and armour types, in the game's own order -- which is the
#: order the panel's five rows are in and the order a card's parts come back
#: in.  The words are the ones the game's own data file keys its shares by
#: (:data:`tl2stash.gamedata.DAMAGE_TYPES`), so an element is spelled one way
#: from the file it was read out of to the row that narrows it.
ELEMENTS = tuple(name for name, _, _ in DAMAGE_TYPES)

#: The top of a damage, armour or property number box, and so of every range
#: that reads one.  Nothing in the game comes near it: the widest span in the
#: reference's whole corpus is 5,610, on a level 100 two-hander, and armour is
#: two orders of magnitude below that again.  Round, and high enough that "and
#: up" is a thing a range can say without a special case for it.
NUMBER_MAX = 99999

#: The range over one element that asks nothing: the pair each of the panel's
#: five rows in both the Damage and the Armor section starts at, and -- like
#: :data:`REQ_REST` -- the one spelling of it that the default, the setter and
#: :meth:`CollectionFilter._attributes` all read.
ELEMENT_REST = (0, NUMBER_MAX)

#: The socket counts the panel offers a chip for.  The reference's own five,
#: and it says why: its corpus runs 1 to 5, so five chips cover every item that
#: can hold a socket at all.  A set of exact counts rather than a range, which
#: is what the game's own number is -- and zero is deliberately not among them,
#: so a socket-less item cannot be asked for *by count* and is found by every
#: search that says nothing about sockets.
SOCKET_COUNTS = (1, 2, 3, 4, 5)

#: The four classes, in the game's own order.  The words are the game's own:
#: an item's file states which class may use it, in a child node whose one
#: variable holds one of these four -- see
#: :func:`~tl2stash.gamedata._class_word`, which is what turns the file's
#: ``RAILMAN`` into the ``Engineer`` a player reads.  Four is the whole
#: vocabulary: a fifth box would be a word nothing in the collection could
#: match, and the game does not write one.
CLASSES = ("Embermage", "Outlander", "Berserker", "Engineer")


@dataclass(frozen=True)
class Advanced:
    """One narrowing, whole: everything the advanced search can set.

    The panel edits a *draft* and commits it with Search, and this is what a
    draft is -- one value rather than a dozen widgets read one at a time, so
    that opening the panel is one copy in and pressing Search is one copy out,
    and a half-applied search is not a thing that can happen on the way.

    It carries the bar's own three facets as well as the panel's seven,
    because the panel *shows* them: a player who opens it with a word in the
    search box and a rarity ticked must find both where they left them, and a
    control that silently dropped them would be a search that shows something
    nobody asked for.  The fields are all at rest in an ``Advanced()`` -- no
    word, no tick, a range that covers everything -- so the resting state is
    this type's default and not a second thing to write down.

    ``damage`` and ``armor`` name the elements the search asks about, which is
    not the same list as the elements an item carries (``Card.damage``): a row
    put back to the range that covers everything leaves the tuple, because a
    search that asks about every element and a search that asks about none of
    them are the same search -- see :meth:`CollectionFilter.set_damage`.

    ``stats`` is one row per property the player is looking for: the words to
    find among an item's lines, and the range its own number has to land in.  A
    stat is not a manifest constant like the four requirements, because the
    vocabulary is the collection's own -- what the items in front of the player
    happen to say -- so it is text rather than a word from a list.

    ``places`` is the odd one in that it belongs to neither: the kinds are
    ticked in the rail and the panel's Type grid is a second view of the same
    ticks, so whoever assembles a draft fills it from the rail -- see
    :meth:`app.filters.FilterBar.current`, which leaves it empty for exactly
    that reason.
    """

    #: The search box's word.
    text: str = ""
    #: The rarity words ticked, which is what the chips carry.
    tiers: frozenset[str] = frozenset()
    #: The *player* level range: the level an item asks of the character.
    low: int = 0
    high: int = LEVEL_MAX
    #: The *item* level range: how good the item itself is.
    item_low: int = 0
    item_high: int = LEVEL_MAX
    #: Exact socket counts, empty for any number of them.
    sockets: frozenset[int] = frozenset()
    #: The four attribute ranges, in :data:`REQ_WORDS` order.
    reqs: tuple[tuple[int, int], ...] = REQ_REST
    #: The class words ticked, empty for every class.
    classes: frozenset[str] = frozenset()
    #: The damage elements asked about, one ``(element, low, high)`` each.
    damage: tuple[tuple[str, int, int], ...] = ()
    #: The armour elements asked about, the same shape.
    armor: tuple[tuple[str, int, int], ...] = ()
    #: The property rows: ``(what to look for, low, high)``, in the order the
    #: player added them.
    stats: tuple[tuple[str, int, int], ...] = ()
    #: Whether a property row may be answered by a set's bonus as well as by
    #: the item's own lines.
    bonuses: bool = False
    #: The kinds ticked in the rail, which the Type grid mirrors.
    places: frozenset[Place] = frozenset()

#: What a row carries besides what it shows.
#:
#: The fingerprint is what a row *is* -- it is how a selection is turned back
#: into an item, and it has always been ``UserRole``.  The rest are what the
#: filters read, and they ride on the row's first cell because a row is one
#: thing: a proxy asked about row 12 is asking about the item in it.
#:
#: ``TIER_ROLE`` holds the tier *word* (``Magic``, ``Unique``) rather than the
#: colour key, so that a rarity chip and the card's kind line name the same
#: thing by the same name, and there is no translation between them to get
#: wrong.  An item with no rarity has the empty string, which no chip carries
#: -- such an item is shown when no chip is ticked, and is simply not one of
#: the rarities when one is.  The sort's ladder is over this same word, for
#: the same reason.
#:
#: ``PLACE_ROLE`` holds where the item sits in the rail -- ``('Weapons',
#: 'One-Handed', 'Sword')``.  The kind filter matches on that whole triple
#: rather than on the kind word alone, because the *empty* kind is a real kind
#: in two different groups: a quest item and an item whose data file the game
#: has not got are both kinds of nothing, and they are filed under Misc and
#: Other respectively.  A filter keyed on the word alone would tick both.
#:
#: ``MEMBERS_ROLE`` holds every fingerprint the row stands for.  A row is a
#: *tile*: the tool's copies of one item are gathered into one row however many
#: rolls of it there are, and this is what turns a selection of that row back
#: into the items it is made of.
#:
#: ``LEVEL_ROLE`` is the item's own level -- the number the list shows and has
#: always shown.  ``GATE_ROLE`` is a different number and the one the level
#: range filters on: the *player* level the item asks for, which is the level
#: the game withholds the item until.  The two differ -- a level 45 unique can
#: ask for 51 -- and where the gate is unknown, which is every item on a
#: machine with no game installed, the role carries the item's level so that
#: the range still means something rather than letting everything through.
#: Zero is a real gate value and the reason the two roles are not merged: an
#: item the game gates on nothing at all, a potion, is usable at any level and
#: is shown whatever range is asked for.
#:
#: ``SET_ROLE`` holds the display name of the set the item belongs to
#: (``True North``), and the empty string for the great majority that belong
#: to none.  It is the one facet of the collection that is not set from a
#: control: it is what a click on a card's set name puts there, and the name
#: is the same string the card draws because both come from the item's own
#: appearance -- see :meth:`CollectionFilter.show_set`.
#:
#: The last three are the advanced search's.  ``REQS_ROLE`` holds the item's
#: four attribute requirements as ``(name, value)`` pairs -- only the ones the
#: item states, so an item that asks for nothing carries an empty tuple and the
#: filter reads a missing attribute as the zero it is.  ``SOCKETS_ROLE`` holds
#: the socket count the item has, and ``CLASS_ROLE`` the one class that may use
#: it or the empty string for the many that restrict nothing.  None of the
#: three is drawn: they are on the row because a facet has to read something,
#: and they are read off the entry rather than worked out here.
#:
#: The last two are the *pile*'s, and neither is drawn either.  A stack the
#: game caps has to be counted in the things it holds rather than in cards or
#: stacks, and a tile is neither: a 3-stack and a 1-stack of one fish are one
#: card reading ``x4``, which is four fish, in stacks the card then has to say
#: the sizes of -- "Transfer a Stack" sends the biggest of them and nothing
#: else.  ``STACKS_ROLE`` is those sizes, one entry per stack the tool holds
#: (a registry row holding two byte-identical stacks contributes its size
#: twice), and ``STACK_ROLE`` is the game's own cap for the kind.  Both are
#: empty and ``None`` for everything the game does not cap, which is everything
#: but fish -- see :data:`tl2stash.taxonomy.STACK_LIMITS`.
FINGERPRINT_ROLE = Qt.ItemDataRole.UserRole
TIER_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 1)
PLACE_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 2)
LEVEL_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 3)
MEMBERS_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 4)
SET_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 5)
GATE_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 6)
REQS_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 7)
SOCKETS_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 8)
CLASS_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 9)
STACKS_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 10)
STACK_ROLE = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 11)


def container_label(container: int, data: "GameData | None" = None) -> str:
    """A display name for one of the shared stash's tabs.

    With the game's data to hand this is the tab's *position*: the player
    counts tabs from one, and each of the three takes one kind of thing -- the
    first everything that is neither consumed nor cast, the second the
    consumables, the third the spells, which is
    :func:`tl2stash.taxonomy.stash_tab_for`'s rule.  The internal names --
    ``SHARED_STASH_BAG_ARMS`` and so on -- say the same thing in the game's own
    words, and are on the cell's tooltip beside this.

    Without the data, the container id is the honest label -- better than
    inventing names that would be wrong the moment a mod added a tab.
    """
    if data is not None:
        tab = data.stash_tab(container)
        if tab is not None:
            return f"Tab {tab}"
        name = data.container_name(container)
        if name:
            return name
    return f"Tab {container}"


def new_model(columns: list[str]) -> QStandardItemModel:
    model = QStandardItemModel()
    model.setHorizontalHeaderLabels(columns)
    return model


def _cell(text: str = "") -> QStandardItem:
    """A cell the player cannot type into."""
    item = QStandardItem(text)
    item.setEditable(False)
    return item


def _describe(cell: QStandardItem, entry: Entry, level: int) -> None:
    """Put what the row knows onto its name cell, and leave the text alone.

    The picture rides in ``DecorationRole`` and the colour in
    ``ForegroundRole``, and the filters read their own roles -- so
    ``DisplayRole`` stays exactly what it was, and the search box that matches
    on it keeps working unchanged.

    ``level`` is the item's own, and the gate falls back to it when the game's
    data could not answer -- so a range over a collection the tool cannot trace
    behaves as it did before there was a gate at all.
    """
    cell.setData(entry.tier_word, TIER_ROLE)
    cell.setData(entry.place, PLACE_ROLE)
    cell.setData(level, LEVEL_ROLE)
    cell.setData(level if entry.gate is None else entry.gate, GATE_ROLE)
    cell.setData(entry.set_name or "", SET_ROLE)
    cell.setData(tuple(entry.stats), REQS_ROLE)
    cell.setData(entry.sockets, SOCKETS_ROLE)
    cell.setData(entry.cls or "", CLASS_ROLE)
    cell.setForeground(QBrush(QColor(TIER_INK[entry.tier])))
    if entry.icon is not None:
        cell.setIcon(entry.icon)


def fill_stash(
    model: QStandardItemModel,
    items: list[Item],
    data: "GameData | None" = None,
    catalog: Catalog | None = None,
) -> int:
    """Show what is in the save file right now, and say how many things that is.

    Four columns and no more: the item, the level it asks for, how many are in
    the stack and how many sockets it has.  Which tab and which slot it came
    out of is on the name cell's tooltip -- it is worth having when it is asked
    for and worth nothing in a column, since the row a player is looking at is
    the row they just put something in.

    The quantity is the stack the item *is*, which is one for nearly everything
    and twenty for a pile of potions, and the socket count is how many the item
    has.  Both are blank when there is nothing to say -- no sockets, or the one
    every unstackable item carries -- rather than a zero or a one on every row:
    a column of noughts and ones is a column nobody can read at a glance, which
    is the only reason to have one.

    One row is one *thing*, which for everything the game caps is more than one
    stack: a fish arrives five to a slot, and the file may be holding three
    slots of it, so the row's quantity is every fish of that kind in the file
    and its tooltip names every slot.  Without ``catalog`` there is no kind to
    read and so no cap to know, and the rows are one stack each -- which is
    also what every uncapped item is, so nothing else about this changes.

    ``data`` names the tabs; without it they fall back to the container id.
    ``catalog`` supplies the tier, the kind and the picture, and without it the
    rows are the plain names they were before there was one.

    The count that comes back is what the pane is showing, counted the way its
    quantity column counts: a stack of twenty potions is twenty and a pile of
    fish is every fish in it.  It is the window's ``In the game (N)``, and the
    number has to be that one rather than the number of rows for the same
    reason the merge exists -- a title counting three stacks over a row that
    says fifteen is the pane contradicting itself.
    """
    model.removeRows(0, model.rowCount())
    drawn = 0
    for group in _file_stacks(
        sorted(items, key=lambda i: (i.location.container, i.location.slot_index)),
        catalog,
    ):
        first = group[0]
        name = _cell(first.display_name)
        name.setData(first.fingerprint, FINGERPRINT_ROLE)
        if catalog is not None:
            _describe(name, catalog.entry(first.fingerprint, first), first.level)
        name.setToolTip(_where_they_sat(group, data))

        # A stack of one is not a stack, and the numbers are the save file's
        # own: the quantity is how many the item *is*, not how many of them the
        # tool has seen -- and for a pile of one kind it is every fish of that
        # kind the file holds, in however many slots.
        quantity = sum(item.quantity for item in group)
        sockets = _cell(str(first.num_sockets or ""))
        drawn += quantity
        model.appendRow(
            [
                name,
                _cell(str(first.level)),
                _cell(str(quantity if quantity > 1 else "")),
                sockets,
            ]
        )
    return drawn


def _file_stacks(items: list[Item], catalog: "Catalog | None") -> list[list[Item]]:
    """The file's items, gathered into one entry per thing the left pane draws.

    A fish is the case, and the reason this exists: the game holds five to a
    slot, so one kind of fish the player has been netting arrives as several
    stacks, and a row each meant the left pane counted stacks while the card
    beside it counted fish.  The stacks of one such kind are one row, and by
    the key the tool's own side of the window already gathers by
    (:func:`_gathered`): the same base item, wearing the same two affixes,
    under the same name.

    Which kinds is :func:`tl2stash.taxonomy.stack_limit_for`'s answer and not
    a list kept here.  Anything it does not know -- every potion, every sword
    -- is a group of one, keyed by its place in the list rather than by
    anything about the item, so that two identical items are still two rows
    and nothing moves out of file order.
    """
    if catalog is None:
        return [[item] for item in items]
    groups: dict[tuple, list[Item]] = {}
    for index, item in enumerate(items):
        entry = catalog.entry(item.fingerprint, item)
        if stack_limit_for(entry.kind) is None:
            groups[("one", index)] = [item]
            continue
        key = (
            "pile",
            item.guid,
            item.prefix.rstrip("\x00"),
            item.suffix.rstrip("\x00"),
            item.base_name,
        )
        groups.setdefault(key, []).append(item)
    return list(groups.values())


def _where_they_sat(items: list[Item], data: "GameData | None") -> str:
    """The name cell's tooltip: every tab and slot the row's stacks sat in.

    One line per tab, naming every cell in it -- ``Tab 2 · slots 3, 7`` -- and
    then the container's internal name, which is the second question the
    one-stack tooltip answers.  The internal name is the second line because
    it is the second question: ``SHARED_STASH_BAG_ARMS`` says what the bag was
    built for, which is not what the player is looking at but is what a save
    file or a bug report talks about.  How many sockets the item has is not
    here: it is a column of the same row.

    The slots are in the order the file holds them, which is the order the
    list is drawn in -- the player reading a line is looking at their stash,
    and sorting the numbers under them would be a second arrangement of the
    same thing.
    """
    lines: list[str] = []
    slots: dict[int, list[int]] = {}
    for item in items:
        slots.setdefault(item.location.container, []).append(item.location.slot_index)
    for container, cells in slots.items():
        word = "slot" if len(cells) == 1 else "slots"
        where = ", ".join(str(cell) for cell in cells)
        lines.append(f"{container_label(container, data)} · {word} {where}")
        if data is not None:
            internal = data.container_name(container)
            if internal:
                lines.append(internal)
    return "\n".join(lines)


def _gathered(rows: list) -> list[list]:
    """The registry rows, gathered into the tiles they draw as.

    Two rows are one tile when they are the same *item* rather than the same
    bytes: the same base item wearing the same two affixes, under the same
    name.  That is the reference tool's own rule, and it is why two
    differently-rolled copies of one unique are one card with a count rather
    than two cards that look alike.

    The name is part of the key and the level is not, which is the one thing
    here worth arguing about.  Two drops of one unique at two levels are one
    item -- its stats follow its level, and comparing the two rolls is exactly
    what the card's button is for.  Two rows with one guid and two names are
    two *things*, and no rule that merged them could be right: the name is
    what the card draws, so two names are two cards.  Over the player's own
    registry the two rules come to the same 37 tiles, which is the measurement
    that says the name costs nothing -- it is there for the item a mod writes
    its own guid for.

    Byte-identical copies never get here as two rows: the registry has already
    collapsed them into one with a copy count.
    """
    groups: dict[tuple, list] = {}
    for row in rows:
        key = (row["guid"], row["prefix"], row["suffix"], row["name"])
        groups.setdefault(key, []).append(row)
    return list(groups.values())


def fill_collection(
    model: QStandardItemModel,
    rows: list,
    catalog: Catalog | None = None,
) -> None:
    """Show what the tool holds, one row per *item* rather than per copy.

    ``rows`` are registry rows for items the tool has taken; the caller filters
    them, because this list answers exactly one question -- *what is in here?*
    An item sitting in the game is not in this list, whether it never left or
    the player just put it back.  It is in the panel on the left instead, which
    reads the file and so is the honest place to look for it.

    Listing everything the registry had ever seen, each row tagged with where
    it currently was, meant this list had to be read rather than trusted.  Now
    membership is the answer and the row is free to be the tile: the copies of
    one item are gathered by :func:`_gathered`, the first of them is what the
    tile draws, and ``MEMBERS_ROLE`` carries the rest so that selecting the
    tile is selecting every copy of it.

    What the row does *not* carry is where the game had the item.  The tool
    holds it now, so the tab and the slot it once sat in say nothing about
    where it is; the collection is a place of its own, and the panel beside it
    is where anything about the game's stash belongs.  Where a restored item
    lands is decided on the way back (see
    :meth:`tl2stash.service.ItemService.first_slot`), not by what it used to
    be.

    ``catalog`` supplies the tier, the kind and the picture, and reading it is
    what turns a row of text into a row of the game's own items.
    """
    model.removeRows(0, model.rowCount())
    for group in _gathered(rows):
        first = group[0]
        name = _cell(first["name"])
        name.setData(first["fingerprint"], FINGERPRINT_ROLE)
        name.setData(tuple(row["fingerprint"] for row in group), MEMBERS_ROLE)
        if catalog is not None:
            entry = catalog.entry(first["fingerprint"], first)
            _describe(name, entry, first["level"])
            limit = stack_limit_for(entry.kind)
            if limit is not None:
                # The card this row becomes counts in the things the game caps
                # rather than in stacks, so the sizes have to come with it:
                # ``STACKS_ROLE`` is one entry per stack the tool holds, which
                # is why a row carrying two byte-identical ones says its size
                # twice.
                name.setData(
                    tuple(
                        row["quantity"]
                        for row in group
                        for _ in range(max(1, row["copies"]))
                    ),
                    STACKS_ROLE,
                )
                name.setData(limit, STACK_ROLE)
        model.appendRow([name])


#: The sign a number may carry, and the number itself: a property line's value
#: is one number, and the game writes the rest of the sentence around it.
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _first_number(line: str) -> float | None:
    """The number a property line is worth, or ``None`` for a line with none.

    The *first* number, because that is where the game puts the value: every
    wording in its files leads with it and names the thing after -- ``+15% to
    Fire Damage``, ``58 Ice Armor``, ``10% Chance to Stun``.  A line with no
    number at all is a real kind of line (``Identify Item``, ``NA``) and is a
    line no range can be asked of; it answers a row that asks for the words
    alone and nothing more.
    """
    found = _NUMBER.search(line)
    return float(found.group()) if found else None


class CollectionFilter(QSortFilterProxyModel):
    """The collection, narrowed by what the controls above it have ticked.

    Twelve things narrow it and they AND, in three families.  Four are ones the
    window has a control for within reach -- the search box, the kinds ticked
    in the rail, the rarity chips, a range of player levels.  Five more have
    controls only in the advanced search's panel, and are set from it in one
    go: a range of *item* levels, a set of socket counts, four attribute
    ranges, the classes an item may be restricted to, and the property rows.
    The two level ranges are different numbers and the reason they are two
    controls: what an item asks of the character is not what it is.  The last
    two are the item's own *numbers*, read off its card rather than off the row
    -- a damage span and an armour span per element -- and they are the only
    facets here that cost anything to apply.  The twelfth is one set, and it is
    the odd one of the lot, because it is arrived at by clicking a *name on a
    card* rather than by a control, and because it is a name rather than a
    tick: a set is not a property an item may have several of.  A facet with
    nothing ticked is not a filter at all, so a window whose controls have just
    been cleared shows the whole collection -- which is what makes them safe to
    ignore.

    Ticking a *group* is the same as ticking everything in it, so the rail
    flattens its tree to a set of places and hands that over; there is no
    "which groups" anywhere in here.

    :meth:`counts` is the reason this is a class rather than a lambda.  It
    answers *how many rows would there be if this were ticked* -- computed with
    that one facet ignored, so the number beside "Unique" stays the number of
    uniques there *are* rather than dropping to zero the moment something else
    is ticked.  That is the reference database's own ``matches(o, skip)``, and
    it is the whole reason the numbers beside a control are worth reading.

    It also *orders* what it lets through, which is the one thing here that is
    not a narrowing: a proxy that has not been asked to sort hands the rows on
    in its source's order, which is the order the registry happens to be in and
    not an order anybody asked for.  So the sort is armed at construction and
    never off -- see :meth:`set_sort` -- and the ladder in :data:`TIER_LADDER`
    is what the wall opens on.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._places: set[Place] = set()
        self._tiers: set[str] = set()
        #: The level range, as the two boxes hand it over.  It starts as the
        #: whole of it, so the default is a range and not a special case.
        self._low: int = 0
        self._high: int = LEVEL_MAX
        #: The panel's four, all resting: an item level range, the socket
        #: counts ticked, the four attribute ranges in :data:`REQ_WORDS`
        #: order, and the class words.  Resting means the whole range for the
        #: first and the fourth, nothing ticked for the second, and
        #: :data:`REQ_REST` for the third -- every one of which is a range or a
        #: set that lets everything through rather than a flag saying "off".
        self._item_low: int = 0
        self._item_high: int = LEVEL_MAX
        self._sockets: set[int] = set()
        self._reqs: tuple[tuple[int, int], ...] = REQ_REST
        self._classes: set[str] = set()
        #: The three that read the item's *card* rather than its row: the
        #: damage and armour elements asked about, and the property rows.  All
        #: of them are empty at rest, and empty means no card is ever asked
        #: for -- see :meth:`set_detail`.
        self._damage: dict[str, tuple[int, int]] = {}
        self._armor: dict[str, tuple[int, int]] = {}
        self._stats: tuple[tuple[str, int, int], ...] = ()
        self._bonuses = False
        #: How to get an item's card from its fingerprint, or ``None`` when
        #: nobody has offered a way.  See :meth:`set_detail`.
        self._detail: Callable[[str], "Card | None"] | None = None
        #: The one set being shown, by the name the cards draw, or empty for
        #: all of them.
        self._set: str = ""
        #: What the rows are ordered by, and which way about it is read.  The
        #: first of :data:`SORT_KEYS` is the ladder, so the tool opens on the
        #: order the user asked for without any caller having to ask.
        self._sort: str = SORT_KEYS[0]
        self._backwards = False
        # Qt sorts on a *column* and an order, and neither of them is what
        # changes here: every key is read off the row's one cell, and the
        # arrow is this side's own.  ``sort`` is still the call that says the
        # proxy is sorting at all -- and with the dynamic sort on, which it is
        # by default, it is what keeps a poll's new rows arriving in place.
        self.sort(0)

    # -- what is ticked --------------------------------------------------

    def set_places(self, places) -> None:
        """Keep only these leaves of the rail, or all of them when given none."""
        wanted = {tuple(place) for place in places}
        if wanted != self._places:
            self._places = wanted
            self._refilter()

    def set_tiers(self, tiers) -> None:
        wanted = set(tiers)
        if wanted != self._tiers:
            self._tiers = wanted
            self._refilter()

    def show_set(self, name: str) -> None:
        """Keep only the items of this set, or all of them when given nothing.

        A name rather than a membership test, because the string that arrives
        is the one a card has just drawn: the click and the filter are the same
        word, and an item is in the set when the game's own file says that name
        for it.
        """
        wanted = name or ""
        if wanted != self._set:
            self._set = wanted
            self._refilter()

    def set_level_range(self, low: int, high: int) -> None:
        """Both bounds included, and both of them *player* levels.

        What the range is over is what the item asks of the character, not what
        the item is: the two are different numbers, and the one a player
        narrowing a collection has in mind is their own level.  Anything the
        game gates on nothing passes whatever the range, so the default range
        is the whole of it and not a special case.
        """
        if (low, high) != (self._low, self._high):
            self._low, self._high = low, high
            self._refilter()

    # -- the panel's four -------------------------------------------------

    def set_item_levels(self, low: int, high: int) -> None:
        """Both bounds included, and both of them *item* levels.

        The other half of the pair above and a different question: a level 45
        unique that asks a character to be 51 is level 45, and a player sorting
        out what to keep is asking about the item rather than about the
        character.  Both ranges exist because both questions are asked, and
        neither number can answer the other.
        """
        if (low, high) != (self._item_low, self._item_high):
            self._item_low, self._item_high = low, high
            self._refilter()

    def set_sockets(self, counts) -> None:
        """Keep only the items with exactly one of these socket counts.

        Exact counts rather than a range, because that is what the number on an
        item is -- a thing either has three sockets or does not.  Nothing
        ticked is every count, and one is deliberately not a member of the set
        a chip can put here: a socket-less item is asked for by saying nothing
        about sockets, and there is no chip that would hide it by accident.
        """
        wanted = {int(count) for count in counts}
        if wanted != self._sockets:
            self._sockets = wanted
            self._refilter()

    def set_requirements(self, ranges) -> None:
        """Keep only the items whose own attribute numbers fall in these ranges.

        ``ranges`` is four ``(low, high)`` pairs in :data:`REQ_WORDS` order, and
        the item's number has to sit *inside* one to pass it.  An item that
        asks for no strength requires none of it -- the zero the reference's
        own reader gives it -- so a floor excludes such an item and a ceiling
        does not: an item that requires nothing requires nothing *of* level 20
        either, so it is not one of the items a floor of 20 is looking for.
        Both bounds being zero and :data:`REQ_MAX` is the range that asks for
        nothing, which is where these rest.
        """
        wanted = tuple((int(low), int(high)) for low, high in ranges)
        if wanted != self._reqs:
            self._reqs = wanted
            self._refilter()

    def set_classes(self, words) -> None:
        """Keep only the items one of these classes may use.

        An item that names no class passes whatever is ticked, because it is
        one every class may use -- the reference's own rule, and the only one
        that does not turn a filter over 767 of its 6,173 records into a filter
        over the whole collection.  Nothing ticked is every class, as with the
        other sets.
        """
        wanted = set(words)
        if wanted != self._classes:
            self._classes = wanted
            self._refilter()

    # -- the three that read the card -------------------------------------

    def set_detail(self, lookup) -> None:
        """Say how to get an item's card from its fingerprint.

        The three facets below are the only ones whose numbers are not on the
        row: a card's damage, armour and property lines are built by walking
        the game's data files, and putting them on every row would be building
        a card for every item in the collection whether or not anyone asks
        about one.  So the proxy is given a *way* to ask instead, and it asks
        only while one of the three is set.

        The window passes its own memo -- see
        :meth:`app.window.MainWindow._detail_for` -- which is the same memo the
        wall draws from, so the first search that reads damage builds each
        card once and every search after it is a dictionary lookup.  A lookup
        that cannot answer returns ``None``, and ``None`` fails a search that
        asked: an item the tool cannot read is not an item that matches.
        """
        self._detail = lookup

    def set_damage(self, ranges) -> None:
        """Keep only the items that deal one of these elements, by these ranges.

        ``ranges`` is ``(element, low, high)`` triples for the elements the
        search is asking about, and only those: a row left at the range that
        covers everything is not asking anything and is not passed.  That is
        the reference's own reading -- it iterates the types that have a bound
        in them and no others -- and it is what makes the rest state free.

        Naming an element asks two things of it, and the second is the one to
        get wrong: the item has to *carry* it, and the two spans have to
        **overlap**.  Overlap rather than contain, because neither end of
        either span is the real one: a sword that rolls 14-28 does have damage
        in a 20-30 request, and a comparator that wanted 20 <= low would say it
        does not.  The presence half is the reference's *"a type named with no
        bound is a presence test"*, read against a fixed five-row form: here a
        row says which element it is asking about by being moved at all, so a
        moved row that the item does not carry turns it away.
        """
        wanted = {element: (int(low), int(high)) for element, low, high in ranges}
        if wanted != self._damage:
            self._damage = wanted
            self._refilter()

    def set_armor(self, ranges) -> None:
        """The armour half of :meth:`set_damage`, and the same rules exactly.

        A separate facet rather than one over both, because the two are
        separate sections on the panel and separate questions about an item: a
        chest's armour has nothing to do with a weapon's damage, and an item
        that carries one of the two usually carries nothing of the other.
        """
        wanted = {element: (int(low), int(high)) for element, low, high in ranges}
        if wanted != self._armor:
            self._armor = wanted
            self._refilter()

    def set_stats(self, rows, bonuses: bool | None = None) -> None:
        """Keep only the items with a line each of these rows is answered by.

        A row is ``(text, low, high)``: the words to find among the item's
        property lines, and the range the first number in such a line has to
        land in.  ``bonuses`` widens *where* a row may be answered from -- the
        set ladder as well as the item's own lines -- and is a widening rather
        than a second clause, which is the reference's own reading of its
        *Include set bonuses* box.

        The text is matched by containment rather than for equality, because
        the vocabulary is the collection's own sentences and a row is typed
        from them: ``to fire damage`` is what the picker offers and what a line
        says in the middle of ``+15% to Fire Damage``.  A row with no bounds --
        the resting pair -- asks only whether the item says it at all.
        """
        wanted = tuple(
            (str(text).strip(), int(low), int(high)) for text, low, high in rows
        )
        moved = bonuses is not None and bool(bonuses) != self._bonuses
        if moved:
            self._bonuses = bool(bonuses)
        if wanted != self._stats or moved:
            self._stats = wanted
            self._refilter()

    def set_sort(self, key: str, backwards: bool = False) -> None:
        """Order the rows by one of :data:`SORT_KEYS`, or read it the other way.

        ``key`` is one of the words the box offers -- what arrives is what the
        player read, and there is nothing to translate.  ``backwards`` is the
        arrow: the key's own order is the one written down here, and the arrow
        is what says the player wants the other one.

        ``invalidate`` rather than ``sort``, and that is the whole of why this
        method exists rather than the caller reaching for Qt's own.  ``sort``
        returns early when the column and the order are the ones it already has
        -- and here the column is always 0 and the order is always ascending,
        because the *comparator* is what a change of key moves.  Which only
        this side knows, so it is this side that says the order is not the one
        it was.

        As with the facets, nothing is remapped when nothing has moved: the
        window re-applies the sort after every poll, and a poll that changed
        nothing has no business reordering the rows under the player.
        """
        if (key, bool(backwards)) == (self._sort, self._backwards):
            return
        self._sort, self._backwards = key, bool(backwards)
        self.invalidate()

    def _refilter(self) -> None:
        """Tell the view the predicate changed.

        ``invalidateFilter`` would be the obvious call and Qt deprecated it in
        6.9; the pair below is what replaced it, and the direction says only
        rows are filtered, which is the cheaper of the two.

        Only called when a facet has actually moved.  The window re-applies
        every facet after every poll, and a poll that changed nothing has no
        business remapping the rows under the player's selection.
        """
        self.beginFilterChange()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    # -- what the sidebar shows ------------------------------------------

    def counts(self, facet: Qt.ItemDataRole) -> dict:
        """How many rows each value of one facet has, with that facet ignored.

        The search box is *not* ignored: it is a text filter rather than a
        facet, and a count that ignored what the player had typed would be a
        number for a list they are not looking at.  Neither is the set, for
        the same reason -- a click on a set name is a switch to a list of that
        set, and the numbers beside the rail are about the list in front of
        the player.  The three ticked facets *are* ignored, because they are
        the ones a count is meant to talk someone out of ticking.

        The advanced search's eight are ignored by nothing, and the reason is
        the same one seen from the other side: there is no number anywhere that
        is a count of them, so there is nothing for a count to talk anyone out
        of ticking.  They are applied to every row this walks, which is what
        makes the numbers beside the rail the numbers of the list in front of
        the player even while a panel nobody can see is narrowing it -- and it
        is why a set of property rows can be worth setting: the counts say how
        much of the collection is left under them.
        """
        tally: dict = {}
        for row in range(self.sourceModel().rowCount()):
            if self._accepts(row, QModelIndex(), ignoring=facet):
                value = self._value(QModelIndex(), row, facet)
                tally[value] = tally.get(value, 0) + 1
        return tally

    # -- the predicate ---------------------------------------------------

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:  # noqa: N802
        return self._accepts(row, parent)

    def _accepts(
        self,
        row: int,
        parent: QModelIndex,
        ignoring: Qt.ItemDataRole | None = None,
    ) -> bool:
        """Whether this row survives the search and every facet but ``ignoring``.

        The search comes first and is never skipped -- it is what
        ``setFilterFixedString`` drives, and deferring to the base class is
        what keeps the search box behaving exactly as it did before there were
        facets at all.
        """
        if not super().filterAcceptsRow(row, parent):
            return False

        if ignoring != PLACE_ROLE and self._places:
            if self._value(parent, row, PLACE_ROLE) not in self._places:
                return False

        if ignoring != TIER_ROLE and self._tiers:
            if self._value(parent, row, TIER_ROLE) not in self._tiers:
                return False

        # A name, not a set of them: an item belongs to one set or none, so
        # this is the one facet with no "ticked" state to be empty of -- it is
        # either showing a set or showing everything.
        if self._set and self._value(parent, row, SET_ROLE) != self._set:
            return False

        if ignoring != GATE_ROLE:
            # Not ``or 0``: zero is an item the game gates on nothing, and an
            # item nobody has to grow into is one every range includes.
            gate = self._value(parent, row, GATE_ROLE)
            if gate and (gate < self._low or gate > self._high):
                return False

        if ignoring != LEVEL_ROLE:
            # The item's own level, where the gate above is the player's.  No
            # ``or 0`` here either, and for the same reason seen from the other
            # side: a level is a level, so the zero a socketable carries is a
            # number inside any range that starts at zero.
            level = self._value(parent, row, LEVEL_ROLE)
            if level is not None and (level < self._item_low or level > self._item_high):
                return False

        if self._sockets:
            # Exact counts, so a socket-less item falls out of every setting --
            # which is the point of the chips starting at one.
            if self._value(parent, row, SOCKETS_ROLE) not in self._sockets:
                return False

        if self._classes:
            # An item naming no class is one every class may use, so it passes
            # whatever is ticked; only a *different* restriction turns it away.
            word = self._value(parent, row, CLASS_ROLE)
            if word and word not in self._classes:
                return False

        # The whole of the range at rest is still the range, as with the two
        # level pairs: nothing here is skipped when it has not been moved, and
        # the price is :data:`REQ_MAX`'s -- a mod's item asking for more than
        # 500 is outside a range nobody narrowed.
        stated = dict(self._value(parent, row, REQS_ROLE) or ())
        for word, (low, high) in zip(REQ_WORDS, self._reqs):
            # A missing attribute is the zero it is, so a floor of 20 excludes
            # an item requiring nothing and a ceiling of 20 does not -- the
            # reference's own reading of the same four numbers.
            if not low <= stated.get(word, 0) <= high:
                return False

        # The three that are not on the row at all.  Last, and behind one test,
        # because they are the only ones that cost anything: everything above
        # reads a role off the row, and these three have to have the item's
        # card built -- see :meth:`set_detail`.
        if self._damage or self._armor or self._stats:
            card = self._card(parent, row)
            if not self._elements(card, self._damage, "damage"):
                return False
            if not self._elements(card, self._armor, "armor"):
                return False
            if not all(self._line_says(card, row_) for row_ in self._stats):
                return False

        return True

    def _card(self, parent: QModelIndex, row: int) -> "Card | None":
        """One row's card, through the lookup the window offered.

        ``None`` for a row whose card nobody can build -- an item the parser
        could not read, or a collection assembled without a window behind it.
        A card-less item fails every one of the three facets, which is the
        honest reading: an item the tool cannot describe is not an item that
        matches a description.
        """
        if self._detail is None:
            return None
        print_ = self._value(parent, row, FINGERPRINT_ROLE)
        return self._detail(print_) if print_ else None

    def _elements(
        self, card: "Card | None", wanted: dict[str, tuple[int, int]], kind: str
    ) -> bool:
        """Whether an item answers every element this search asks about.

        The card keeps its parts as the tuple of triples the card is written
        with -- name, low, high, in the game's own order -- so they are keyed
        here rather than there: a dict on the card would be a second order for
        the same five elements, and the card's is the one the lines are drawn
        in.
        """
        if not wanted:
            return True
        if card is None:
            return False
        carried = {name: (low, high) for name, low, high in getattr(card, kind)}
        for element, (low, high) in wanted.items():
            ends = carried.get(element)
            # The presence half: an item that does not carry the element is not
            # an item this row is looking for, whatever range is asked for.
            if ends is None:
                return False
            # And the overlap half, neither span having to contain the other.
            if ends[1] < low or ends[0] > high:
                return False
        return True

    def _line_says(self, card: "Card | None", row) -> bool:
        """Whether one property row is answered by one of the item's lines.

        Every line of the item is tried, and a line answers the row when it
        says what the row is looking for *and* the first number in it lands in
        the row's range.  A row with no range is asking only whether the item
        says it, which is the reference's own most common row -- it is how a
        stat that exists only on set ladders is asked for at all.

        The set ladder joins the search only when the box is ticked, and it
        joins the *pool* rather than adding a clause: a row is answered by
        either place, and a bonus nobody asked about is not a reason to turn an
        item away.
        """
        text, low, high = row
        if card is None:
            return False
        said = card.properties
        if self._bonuses:
            said = said + tuple(
                line for rung in card.set_ladder for line in rung.lines
            )
        for line in said:
            if text.casefold() not in line.casefold():
                continue
            if (low, high) == ELEMENT_REST:
                return True
            number = _first_number(line)
            if number is not None and low <= number <= high:
                return True
        return False

    def _value(self, parent: QModelIndex, row: int, facet: Qt.ItemDataRole):
        """One facet of one row, read off the row's first cell.

        A row is one thing and its first cell is where it says so.  The
        collection is a single column -- what the player sees is the card the
        tile draws from the row, not the cells -- so the first cell is the
        whole of what there is to read.
        """
        return self.sourceModel().index(row, 0, parent).data(facet)

    # -- the order -------------------------------------------------------

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        """Whether one row comes before another, under the chosen key.

        Only the first thing the key says answers to the arrow.  Everything
        after it is a tie-break and is read the same way round in both
        directions, which is the one place this differs from the reference: it
        multiplies its whole comparison by the direction, so turning its ladder
        over turns its items over too and every tier runs 100 down to 1.  The
        rule here is the user's -- *"within each tier level 1 to 100"* -- and
        it holds whichever way the ladder is read.

        The arrow still turns the *untiered* tail, and that is not an
        exception: the tail is the last rung of the ladder rather than a
        separate pile, so it goes where the ladder goes.
        """
        here, there = self._sorting(left), self._sorting(right)
        if here[0] != there[0]:
            return here[0] > there[0] if self._backwards else here[0] < there[0]
        return here[1:] < there[1:]

    def _sorting(self, index: QModelIndex) -> tuple:
        """What one row is worth under the chosen key.

        Every key ends the same way -- the item's level, then the name it
        draws, then its fingerprint -- so that two rows the key itself cannot
        tell apart hold one order instead of keeping whatever the poll left
        them in.  The fingerprint is last because it is the only one of the
        three that is arbitrary *and* fixed: it is a hash of the item's own
        bytes, so it says the same thing on every poll and nothing about the
        item that a player would want to read.

        A level that reads as nothing sorts as zero rather than raising.  Every
        row the window builds carries the item's own level -- it is in the save
        bytes and needs no game -- so the fallback is for rows built elsewhere:
        a comparator is no place to raise, because it runs inside a sort, where
        an exception is not a message but a crash in the middle of a paint.
        """
        name = index.data(Qt.ItemDataRole.DisplayRole)
        level = index.data(LEVEL_ROLE) or 0
        print_ = index.data(FINGERPRINT_ROLE) or ""
        if self._sort == "Name":
            return (name.casefold(), level, print_)
        if self._sort == "Level":
            return (level, name.casefold(), print_)
        if self._sort == "Type":
            # The kind word, spelled as the card's type line spells it, which
            # is the reference's own reading of *Type*.  The two spellings of
            # one kind sit apart here -- the game writes both ``Sword`` and
            # ``1H Sword`` -- because they are two words, and the rail is where
            # they are made one.
            place = index.data(PLACE_ROLE) or ("", None, "")
            return (place[2].casefold(), level, name.casefold(), print_)
        if self._sort in ("Damage", "Armor"):
            # Negated, because the key's own order is the *most* of the thing
            # first -- the way the ladder is the best first -- and this
            # comparator reads a smaller number as the earlier row.
            carried = self._carried(print_, self._sort.lower())
            return (-carried, level, name.casefold(), print_)
        return (
            TIER_RANK.get(index.data(TIER_ROLE), TIER_TAIL),
            level,
            name.casefold(),
            print_,
        )

    def _carried(self, print_: str, kind: str) -> float:
        """How much of a thing an item carries, as one number.

        The sum of the midpoints of its parts, which is the reference's own
        reading of the same key -- a sword with two elements has more damage
        than one with the same span in one, which is right, and a span is
        counted at its middle because that is what the player expects to get.

        Minus one for an item that carries none at all, and the negation the
        caller applies is what makes that the *worst* value rather than the
        best: zero damage is a real number and the absence of damage is not a
        number at all, so it sorts below it -- the reference's own ``-1``.
        """
        card = self._detail(print_) if self._detail and print_ else None
        if card is None:
            return -1.0
        parts = getattr(card, kind, ())
        if not parts:
            return -1.0
        return sum((low + high) / 2 for _, low, high in parts)
