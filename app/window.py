"""The main window.

The layout is the argument.  Above everything, what to show and what to do with
it -- the filters in one row and the actions in the row over them.  Below it,
the kinds the collection holds down the left, what the game has in the middle,
and what the tool has on the right, drawn as the game draws it, one card per
item.  The player puts things in the shared stash and this empties it -- so the
window is arranged around a single gesture rather than around a file format,
because the file format is not what anyone wants to think about.

The cards are the reason there is no item pane: a tile *is* the card, so a
second copy of the same card beside the grid would be a second answer to a
question already answered on screen.  What one item needs a closer look at is
what :mod:`app.compare` is for.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tl2stash.card import Card
from tl2stash.gamedata import GameData, find_install
from tl2stash.item import parse_item
from tl2stash.saves import SaveLocation, find_save_locations, live_location
from tl2stash.service import STATUS_ABSORBED, ItemService
from tl2stash.tooltip import build
from tl2stash.watcher import StashWatcher

from .card import IconCache
from .catalog import ICON_SIZE, Catalog
from .compare import CompareOverlay
from .filters import FilterBar
from .models import (
    COLLECTION_COLUMNS,
    FINGERPRINT_ROLE,
    MEMBERS_ROLE,
    PLACE_ROLE,
    STASH_COLUMNS,
    TIER_ROLE,
    CollectionFilter,
    fill_collection,
    fill_stash,
    new_model,
)
from .sidebar import SidePanel
from .tiles import TileGrid, TileRow

#: How often to look at the save file.  The file is a few tens of kilobytes
#: and saves are seconds apart at the fastest, so this is generous; it exists
#: to feel immediate, not to keep up.
POLL_MS = 2000

#: Shown in place of an item's stats when the game's data files cannot be
#: found.  Saying what to do about it is worth more than the space it takes --
#: but not more than a line of it, so this is the banner's *tooltip* and the
#: banner itself is the one sentence.
GAME_DATA_MISSING = (
    "Torchlight II's data files were not found, so an item's stats are shown\n"
    "with the names the save file uses rather than the words the game does.\n"
    "\n"
    "Items are stored and put back exactly the same either way.\n"
    "\n"
    "To point the tool at the game, name the folder holding PAKS:\n"
    "    python -m app --game=\"<the Torchlight II folder>\"\n"
    "or set TL2_INSTALL to it."
)


def _copies_note(rows: list[TileRow]) -> str:
    """Say which of the cards that went back stood for more than one item.

    A card is every copy of one item, so one click can put back three things.
    Without this the status line would say "3" and the player would remember
    clicking one card.
    """
    duplicates = [row for row in rows if row.copies > 1]
    if not duplicates:
        return ""
    said = ", ".join(f"{row.copies} of {row.name}" for row in duplicates[:2])
    return f" · {said}"


class MainWindow(QMainWindow):
    def __init__(
        self,
        db_path: str | Path | None = None,
        source: str | Path | None = None,
        db_dir: str | Path | None = None,
        game: str | Path | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Torchlight 2 Item Assistant")
        # Wide enough for the three panes on the day it opens: the rail, the
        # game's list with a name in it, and a row of cards.  The window's own
        # minimum is what the bar of filters needs, so this is a starting size
        # rather than a floor -- and Qt clamps it to the screen it opens on.
        self.resize(1440, 900)

        # ``db_path`` given means one database for every stash, which is what
        # --db asks for.  Left out, each stash gets its own file in ``db_dir``
        # -- the default, because a player with both a vanilla and a modded
        # stash has two separate stashes, and pooling them would make "put
        # this back" a question with two possible answers.
        self.db_path = Path(db_path) if db_path is not None else None
        self.db_dir = (
            Path(db_dir) if db_dir is not None
            else Path(__file__).resolve().parent.parent / "var"
        )
        self.service: ItemService | None = None
        self.watcher: StashWatcher | None = None
        self._sources: list[SaveLocation] = []

        # The game's own data files, which supply the wording of an item's
        # stats.  Named rather than searched for when --game says where; see
        # _game_data for why it is not read here.
        self.game_path = Path(game) if game is not None else None
        self._game: GameData | None = None
        self._game_looked = False
        self._game_error: str | None = None
        self._icon_cache: IconCache | None = None
        self._catalog: Catalog | None = None
        #: Built cards by fingerprint -- or, for an item that will not parse, a
        #: sentence saying so.  A fingerprint is a hash of the item's own
        #: bytes, so an entry can never go stale and nothing ever needs
        #: invalidating.
        self._details: dict[str, Card | str] = {}

        self._build_ui()
        self._load_sources(source)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_MS)

    # -- construction ----------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(self._build_toolbar())
        layout.addWidget(self._build_splitter(), stretch=1)
        self.setCentralWidget(central)

        # The copies of one item, over everything -- built here rather than on
        # demand so that it is a child of the window it covers and follows it
        # in size.  Hidden until a card's button asks for it.
        self.compare = CompareOverlay(self._icons(), central)
        self.compare.put_back.connect(self._put_back_one)

        self.status = self.statusBar()
        self.status.showMessage("starting up")

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()

        bar.addWidget(QLabel("Save:"))
        self.source_box = QComboBox()
        self.source_box.setMinimumWidth(280)
        self.source_box.currentIndexChanged.connect(self._source_changed)
        bar.addWidget(self.source_box)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(lambda: self._sync(write=False))
        bar.addWidget(self.refresh_button)

        bar.addStretch(1)
        return bar

    def _build_absorb_row(self) -> QHBoxLayout:
        """What decides which items leave the save file, over the list they leave.

        These two used to sit in the bar at the top, beside the box naming the
        save file -- which put them two panes away from the thing they act on.
        ``Absorb everything`` empties the game's stash into the tool's, and
        ``Automatic`` is whether that happens on its own every time the game
        saves; both are about this one list, so both are over it.
        """
        row = QHBoxLayout()

        self.absorb_button = QPushButton("Absorb everything")
        self.absorb_button.setToolTip(
            "Take every item out of the shared stash and keep it here.\n"
            "The stash is the inbox: whatever is in it goes."
        )
        self.absorb_button.clicked.connect(self._absorb_all)
        row.addWidget(self.absorb_button)

        self.auto_absorb = QCheckBox("Automatic")
        self.auto_absorb.setChecked(True)
        self.auto_absorb.setToolTip(
            "Absorb on every save, and keep absorbed items out.\n"
            "This is what makes an item vanish when the game saves."
        )
        row.addWidget(self.auto_absorb)
        row.addStretch(1)

        return row

    def _build_filters(self) -> FilterBar:
        """The controls that narrow the collection, over the cards they narrow."""
        self.filters = FilterBar()
        self.filters.changed.connect(self._filters_changed)
        return self.filters

    def _build_splitter(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # The rail comes first because it is the first thing to reach for: a
        # collection of any size is narrowed before it is read.  It is narrow,
        # because what it holds is one column of kind names and nothing else --
        # every other control is in the bar above.
        self.type_group = QGroupBox("Type")
        kinds = QVBoxLayout(self.type_group)
        self.sidebar = SidePanel()
        kinds.addWidget(self.sidebar)
        splitter.addWidget(self.type_group)

        self.stash_group = QGroupBox("In the game")
        left = QVBoxLayout(self.stash_group)
        left.addLayout(self._build_absorb_row())
        self.stash_view, self.stash_model = self._table(STASH_COLUMNS)
        left.addWidget(self.stash_view)
        splitter.addWidget(self.stash_group)

        self.collection_group = QGroupBox("In the tool")
        right = QVBoxLayout(self.collection_group)

        # One line, with the whole of it -- what is missing and how to point
        # the tool at the game -- on its tooltip.  It used to be a pane of
        # prose, which is a lot of window for a machine that has no game.
        self.banner = QLabel()
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.setVisible(False)
        right.addWidget(self.banner)

        self.collection_model = new_model(COLLECTION_COLUMNS)
        self.collection_proxy = CollectionFilter()
        self.collection_proxy.setSourceModel(self.collection_model)
        self.collection_proxy.setFilterKeyColumn(0)
        self.collection_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.grid = TileGrid(self._icons())
        self.grid.compare.connect(self._compare_copies)
        self.grid.transfer.connect(self._transfer_row)
        self.grid.set_chosen.connect(self._show_set)
        right.addWidget(self.grid, stretch=1)

        # The filters stand directly over the collection and span nothing else.
        # They narrow one pane, and a row reaching across the window reads as
        # if it narrowed all three -- while the pane it does narrow is the one
        # it should be next to, which is what makes them easier to reach.
        self.collection_pane = QWidget()
        pane = QVBoxLayout(self.collection_pane)
        pane.setContentsMargins(0, 0, 0, 0)
        pane.addWidget(self._build_filters())
        pane.addWidget(self.collection_group, stretch=1)
        splitter.addWidget(self.collection_pane)

        self.sidebar.changed.connect(self._filters_changed)

        # The rail holds a kind word and its count and nothing else, so it is
        # given the width the longest of them needs -- "Unclassified", indented
        # under its group -- and every pixel past that goes to the cards, which
        # are the thing here worth looking at.  The handle is the player's;
        # this is only where it starts.
        #
        # The game's list is the narrowest of the three, because what it holds
        # is a row per item sitting in a tab the player has just used: a name,
        # a level, a socket count, gone by the next save.  What the tool holds
        # is the thing worth the window.
        #
        # Narrow, but not *narrower than its own columns*: a name, a level and
        # a socket count want about 300 pixels between them, and the two
        # numbers cost a fixed 96 of that whether the pane is 200 wide or 400.
        # Below that the name -- the only column here worth reading -- is what
        # pays, so this is the share that keeps it legible rather than the
        # smallest the pane could be drawn at.
        splitter.setSizes([180, 340, 900])
        return splitter

    def _table(self, columns: list[str]) -> tuple[QTableView, object]:
        """The game's list: rows, ordered the way the stash is.

        Not sortable, which is a decision rather than an omission.  The list is
        thrown away and rebuilt on every poll, so a column the player sorted by
        would come back in stash order at the next save -- a control that does
        not hold is worse than no control.  And the order it *is* in is the one
        worth having here: tab, then slot, which is where the player just put
        things.

        Turning sorting off also takes the sort indicator off the header, and
        that is worth more than it sounds.  Qt reserves its twenty pixels in
        *every* section whether or not that section is the one sorted, so it
        was sixty pixels of a three-hundred-pixel pane -- while the arrow it
        drew sat over the Item column claiming the rows were in name order, and
        they were in slot order.
        """
        view = QTableView()
        view.setAlternatingRowColors(True)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.verticalHeader().setVisible(False)
        # The tier tile beside every name, at the size the catalogue paints it,
        # so the view is not asked to scale a picture per cell per redraw.
        view.setIconSize(QSize(ICON_SIZE, ICON_SIZE))

        model = new_model(columns)
        view.setModel(model)

        # After the model, because setting one rebuilds the header's sections
        # and puts every one of them back to Qt's default: 100px and
        # interactive.  Set before it, these modes were silently dropped and a
        # 300px pane showed a 100px name column with the rest of the width
        # sitting empty beside it.
        #
        # The name takes whatever the other columns do not, and the others take
        # exactly what they need: a level is two digits and the two counts
        # beside it are one or two, and none of them is worth the 100px Qt would
        # give it.  That the name stretches is the whole reason a wide row stays
        # readable in a narrow pane: the three numbers cost what they cost, and
        # every pixel left over is name.
        header = view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(columns)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        return view, model

    # -- the game's data -------------------------------------------------

    def _game_data(self) -> GameData | None:
        """The game's data files, read once, or ``None`` if there are none.

        Reading them takes about a second, and nothing needs them to *store*
        an item -- only to describe one.  So it happens on first use, and the
        answer is remembered either way: a machine without the game would
        otherwise re-run a disk search on every refresh to keep failing.

        ``None`` is not an error state.  Without it an item shows the names
        the save file gives its effects instead of the sentences the game
        writes; everything else about the tool is unaffected.
        """
        if self._game_looked:
            return self._game
        self._game_looked = True
        try:
            install = find_install(self.game_path)
            if install is not None:
                self._game = GameData.load(install)
        except Exception as exc:  # noqa: BLE001 -- never fatal, only degraded
            self._game_error = str(exc)
        return self._game

    def _slot_base(self, container: int) -> int | None:
        """Where the game says this container's cells begin.

        Handed to :class:`~tl2stash.service.ItemService` as a callable rather
        than as an answer, because reading the game's files takes a second and
        is only needed when an item is being put back into a tab the tool has
        never seen it in.  ``None`` without the game, which the service has an
        answer of its own for.
        """
        game = self._game_data()
        return game.slot_base(container) if game is not None else None

    def _note_game(self) -> None:
        """Say, in one line, that there is no game data -- if there is not.

        A game that is not installed and one whose files will not open are
        different problems with different answers, so they do not get the same
        sentence: the second is a bug report waiting to happen and would be
        invisible if it read as "not found".  Either way the details are on the
        tooltip rather than in the window, because the window is for the items.
        """
        game = self._game_data()
        if game is not None:
            self.banner.setVisible(False)
            return

        text = (
            "Torchlight II's data files were not found, so items are shown by "
            "the names the save file uses."
        )
        tip = GAME_DATA_MISSING
        if self._game_error:
            text = (
                "Torchlight II's data files would not open, so items are shown "
                "by the names the save file uses."
            )
            tip = f"{GAME_DATA_MISSING}\n\nThe data files there would not open: {self._game_error}"
        self.banner.setText(text)
        self.banner.setToolTip(tip)
        self.banner.setVisible(True)

    # -- sources ---------------------------------------------------------

    def _load_sources(self, preferred: str | Path | None) -> None:
        self._sources = find_save_locations()

        if preferred is not None:
            target = Path(preferred)
            if not any(loc.path == target for loc in self._sources):
                # An explicitly named file that discovery did not find.  It is
                # still what the caller asked for, so use it -- falling back
                # to whichever save happens to sort first would quietly point
                # the tool at a *different* stash, and this tool's whole job
                # is deciding which items leave which file.
                self._sources.insert(0, SaveLocation.at(target))

        if not self._sources:
            self._set_status("No Torchlight 2 shared stash found on this machine.")
            self.absorb_button.setEnabled(False)
            return

        self.source_box.blockSignals(True)
        for location in self._sources:
            self.source_box.addItem(f"{location.label}", str(location.path))
            index = self.source_box.count() - 1
            self.source_box.setItemData(
                index,
                f"{location.kind} stash\n{location.path}",
                Qt.ItemDataRole.ToolTipRole,
            )
        self.source_box.blockSignals(False)

        if preferred is not None:
            target = Path(preferred)
        else:
            live = live_location()
            target = live.path if live else self._sources[0].path

        index = next(
            (i for i, loc in enumerate(self._sources) if loc.path == target), 0
        )
        self.source_box.setCurrentIndex(index)
        self._source_changed(index)

    def _source_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._sources):
            return
        location = self._sources[index]

        # A different stash is a different collection, and filters left over
        # from the last one would silently hide most of it -- a narrowing
        # nobody asked for and, because the shape changes with it, one that can
        # be hard to see.  Cleared before the first read, not after.
        self.sidebar.reset()
        self.filters.reset()

        if self.service is not None:
            self.service.close()
        db_path = (
            self.db_path if self.db_path is not None else self.db_dir / location.db_name
        )
        self.service = ItemService(db_path, location, slot_base=self._slot_base)
        self.watcher = StashWatcher(location.path)

        self._sync(write=False)

    # -- the loop --------------------------------------------------------

    def _poll(self) -> None:
        if self.watcher is None or self.service is None:
            return
        # A change is only consumed once it has been processed -- see the
        # watcher's docstring.  A save caught half-written is retried here
        # rather than being accepted and skipped.
        if self.watcher.changed():
            self._sync()

    def _sync(self, *, write: bool = True) -> None:
        """Re-read the file, take what is ours, and redraw.

        The order matters: absorb first (new items), then enforce (items the
        game has put back).  On an ordinary save only one of them does
        anything, and on most polls neither does.

        ``write=False`` is for looking without acting -- opening the window,
        or pressing Refresh.  Starting up must not vacuum what it finds: the
        stash may hold a session's worth of things the player has not decided
        about yet, and "I opened the app" is not a decision.  The automatic
        pass is for *changes*, which is what a save is.
        """
        if self.service is None or self.watcher is None:
            return

        try:
            self.service.refresh()
        except FileNotFoundError:
            self.watcher.accept()
            self._refresh_views()
            self._set_status("The game has not written a shared stash yet.")
            return
        except Exception as exc:  # noqa: BLE001 -- a bad save must not kill the app
            # Deliberately not accepted: the file may be mid-write, so the
            # next poll should try again rather than move on and forget.
            self._set_status(f"Could not read the stash: {exc}")
            return

        self.watcher.accept()

        if write and self.auto_absorb.isChecked():
            note = self._take_pass()
        else:
            note = ""

        self._refresh_views()
        self._set_status(note or self._describe())

    def _take_pass(self) -> str:
        """Absorb new items, then take back anything the game has put back.

        The vacuum spares items the player has returned.  It is still a
        vacuum -- it takes everything else, without asking -- but an item
        someone deliberately put back and then watched disappear again would
        make the Restore button a lie.
        """
        assert self.service is not None
        absorbed = self.service.absorb_all(include_returned=False)
        if absorbed.count:
            self.watcher.accept()
            self.service.refresh()
            return f"{absorbed.summary} · {self._in_game_count()} left in the game"

        retaken = self.service.enforce()
        if retaken is not None:
            self.watcher.accept()
            self.service.refresh()
            return f"the game put {retaken.count} back · taken out again"

        return ""

    # -- actions ---------------------------------------------------------

    def _absorb_all(self) -> None:
        if self.service is None:
            return
        try:
            items = self.service.stash_items()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Could not read the stash", str(exc))
            return

        if not items:
            QMessageBox.information(
                self, "Nothing to absorb", "The shared stash is already empty."
            )
            return

        answer = QMessageBox.question(
            self,
            "Absorb everything?",
            f"Take all {len(items)} item(s) out of the shared stash?\n\n"
            "They will be stored here and removed from the game. "
            "You can put them back afterwards.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return

        result = self.service.absorb_all()
        self.watcher.accept()
        self._refresh_views()

        backup = result.report.backup if result.report else None
        note = f"{result.summary}"
        if backup is not None:
            note += f" · backup {backup.name}"
        self._set_status(note)

    # -- the copies ------------------------------------------------------

    def _compare_copies(self, row: TileRow) -> None:
        """Show every copy of one item side by side.

        The tile draws one card for all of them -- that is what makes the
        collection readable -- so this is the one place the copies are told
        apart.  Each is built from its own bytes, which is where its own
        numbers and its own fingerprint come from.
        """
        prints = row.members or (row.fingerprint,)
        self.compare.open_for(
            [
                TileRow(
                    fingerprint=print_,
                    name=row.name,
                    members=(print_,),
                    card=self._card_for(print_),
                )
                for print_ in prints
            ]
        )

    def _transfer_row(self, row: TileRow) -> None:
        """Send a card's copies back, from a button on the card itself.

        One copy is the button that says so and several are ``Transfer all
        (N)``, and both land here because both are the same act: a card stands
        for its fingerprints, and this puts back the ones it says it has.  The
        comparison overlay is where they come apart -- there a card *is* one
        copy -- and this is the collection's own way through, for a player who
        already knows they want the lot gone.
        """
        if self.service is None:
            return
        prints = set(row.members or (row.fingerprint,))
        if not prints:
            return

        report = self.service.restore(prints)
        self.watcher.accept()
        self._refresh_views()

        if report.restored:
            note = f"put back {len(report.restored)}{_copies_note([row])}"
            tail = "it returns" if len(report.restored) == 1 else "they return"
            self._set_status(f"{note} · {tail} to the game on its next load")
        elif report.skipped:
            self._set_status(f"{len(report.skipped)} were already in the stash")

    def _put_back_one(self, print_: str) -> None:
        """Return exactly one copy to the game, from the comparison.

        One fingerprint, not a group: the whole point of the overlay is that
        the copies can be told apart, and a button that put back all of them
        would be the collection's button again.
        """
        if self.service is None:
            return
        report = self.service.restore({print_})
        self.watcher.accept()
        self._refresh_views()

        if report.restored:
            # The card comes down whether or not the overlay stays: what it
            # drew is a thing the tool no longer holds.
            self.compare.drop(print_)
            self._set_status("put back 1 · it returns to the game on its next load")
        elif report.skipped:
            self._set_status("that copy was already in the stash")

    # -- display ---------------------------------------------------------

    def _refresh_views(self) -> None:
        if self.service is None:
            return
        try:
            items = self.service.stash_items()
        except Exception:  # noqa: BLE001
            items = []

        data = self._game_data()
        catalog = self._catalog_for(data)
        fill_stash(self.stash_model, items, data, catalog)

        # Only what the tool holds.  An item that is in the game -- one that
        # never left, or one the player has just put back -- is in the left
        # panel's hands, not this one's.  Listing it here as well, tagged with
        # where it currently is, made these two lists overlap and left the
        # reader to work out which entries they were actually responsible for.
        rows = self.service.registry.rows(status=STATUS_ABSORBED)
        fill_collection(self.collection_model, rows, catalog)

        # The rail describes what is *here*, so its shape comes from the rows
        # and not from the filters -- which is what keeps a row from vanishing
        # out from under the pointer the moment it is ticked.  The grid is
        # rebuilt with them, because what it draws is what the filters left.
        self.sidebar.set_shape(
            catalog.entry(row["fingerprint"], row).place for row in rows
        )
        self._filters_changed()

        self._note_game()
        self.stash_group.setTitle(f"In the game ({len(items)})")
        self.collection_group.setTitle(f"In the tool ({len(rows)})")

    def _rebuild_collection(self) -> None:
        """Draw what the tool holds as the game's own cards.

        The rows come through the proxy, because the proxy is what the filters
        narrow: the grid draws what the filters left and re-implements none of
        them.  Each card is looked up in the memo, so an item is drawn the
        first time it is seen and never again, however many saves go by.
        """
        rows = []
        for row in range(self.collection_proxy.rowCount()):
            index = self.collection_proxy.index(row, 0)
            fingerprint = index.data(FINGERPRINT_ROLE)
            rows.append(
                TileRow(
                    fingerprint=fingerprint,
                    name=index.data(Qt.ItemDataRole.DisplayRole),
                    members=tuple(index.data(MEMBERS_ROLE) or (fingerprint,)),
                    card=self._card_for(fingerprint),
                )
            )
        self.grid.set_rows(rows, empty=self._empty_text())

    def _empty_text(self) -> str:
        """What the wall says when there is nothing on it.

        Two different nothings: a collection with nothing in it, and a
        collection with nothing *showing*.  A player who has just ticked a box
        wants to know which one they are looking at.
        """
        if self.collection_model.rowCount():
            return "Nothing in the collection matches these filters."
        return (
            "Nothing here yet.  Put something in the shared stash in the game "
            "and it will move in here."
        )

    # -- the cards --------------------------------------------------------

    def _card_for(self, print_: str) -> Card | str:
        """One item's card, built once and then kept.

        The memo is the point of this method.  A card is built by walking the
        game's data files and cutting a picture out of a 512x512 sheet, and the
        wall of them is rebuilt on every save -- every couple of seconds in
        play.  A fingerprint is a hash of the item's own bytes, so a card built
        under one can never go stale, and nothing ever needs invalidating.
        """
        card = self._details.get(print_)
        if card is None:
            card = self._render_stats(print_)
            self._details[print_] = card
        return card

    def _render_stats(self, print_: str) -> Card | str:
        """The game's own card for one stored item, or why there is not one.

        The registry keeps each item's bytes, so the card is built from the
        item itself rather than from the columns summarising it -- the same
        parse the game would do.  An item that has gone and an item that will
        not parse are both sentences rather than cards: neither is something to
        draw a tier and an icon for.
        """
        assert self.service is not None
        row = self.service.registry.get(print_)
        if row is None:
            return "This item is no longer in the collection."
        try:
            return build(parse_item(row["raw"]), self._game_data())
        except Exception as exc:  # noqa: BLE001 -- one bad item is not fatal
            return f"Could not read this item: {exc}"

    def _icons(self) -> IconCache | None:
        """The game's icon sheets, or ``None`` when there is no game.

        Built on first use and kept, and it reads nothing here: the library
        behind it opens the archive when an icon is first asked for, so a
        window whose items have no icons never pays for one.
        """
        game = self._game_data()
        if game is None:
            return None
        if self._icon_cache is None:
            self._icon_cache = IconCache(game.install)
        return self._icon_cache

    def _catalog_for(self, data: GameData | None) -> Catalog:
        """The per-item answers both lists are drawn from, built once.

        It shares the card's icon cache rather than opening a second one: a
        sheet is 512x512 and decodes once, and two caches would decode every
        sheet twice and hold two copies of it.  Which game's data is in use is
        settled on first use and never changes, so a catalogue built once stays
        right for the window's life -- and it is the memo *inside* it that
        matters, because this is on the poll's path.
        """
        if self._catalog is None:
            self._catalog = Catalog(data, self._icons())
        return self._catalog

    def _in_game_count(self) -> int:
        assert self.service is not None
        return len(self.service.stash_items())

    def _show_set(self, name: str) -> None:
        """Show every piece of one set, and nothing else.

        What a click on a set name on a card means.  The ladder under that name
        is what the *set* grants rather than what this one piece does, so a
        player reading one piece of a set is the player most likely to want the
        rest of it -- and the tool is where the rest of it is, because the tool
        is where the items went.

        A switch rather than a narrowing: the rail goes back to showing every
        kind and the bar back to its defaults, so what is left on the wall is
        the set.  The bar's own clearing is
        :meth:`app.filters.FilterBar.show_set`'s; the rail is not part of the
        bar, so it is cleared here -- which is two rebuilds of the wall for one
        click, and a click is not a poll.
        """
        self.sidebar.reset()
        self.filters.show_set(name)
        self._set_status(
            f"showing every piece of {name} · click its chip to see everything again"
        )

    def _filters_changed(self) -> None:
        """Apply every facet, then say what each one would leave.

        One slot for the whole job, whether it was a kind ticked in the rail, a
        chip ticked in the bar or a set name clicked on a card: the proxy holds
        all five facets at once, so applying four of them and rebuilding would
        be a redraw of a list the player is not looking at.  Each setter
        returns without touching the rows when its facet has not moved, which
        is what keeps this free on the polls that changed nothing.
        """
        self.collection_proxy.setFilterFixedString(self.filters.search_text())
        self.collection_proxy.set_places(self.sidebar.places())
        self.collection_proxy.set_tiers(self.filters.tiers())
        self.collection_proxy.set_level_range(*self.filters.level_range())
        self.collection_proxy.show_set(self.filters.shown_set())
        self._count_facets()
        self._rebuild_collection()

    def _count_facets(self) -> None:
        """Put the numbers on the rail and the chips.

        Both are what the filters *would* leave rather than what they do, and
        both follow the search box: a number that ignored what the player had
        typed would be a count of a list they are not looking at.
        """
        self.sidebar.set_counts(self.collection_proxy.counts(PLACE_ROLE))
        self.filters.set_counts(self.collection_proxy.counts(TIER_ROLE))

    def _describe(self) -> str:
        if self.service is None:
            return ""
        held = len(self.service.registry.absorbed_fingerprints())
        note = f"{self._in_game_count()} in the game · {held} absorbed here"
        # An item the parser could not read is in neither count and is left in
        # the file untouched, so without this line it would be invisible: the
        # player sees something in the stash that neither list mentions.
        unreadable = len(self.service.stash.failed)
        if unreadable:
            note += f" · {unreadable} in the file could not be read"
        if self._game is None:
            # Said on the banner over the grid as well, because it explains why
            # the cards read as keys rather than as sentences.
            note += " · no game data"
        return note

    def _set_status(self, message: str) -> None:
        self.status.showMessage(message)

    # -- lifecycle -------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        self._timer.stop()
        if self.service is not None:
            self.service.close()
        super().closeEvent(event)
