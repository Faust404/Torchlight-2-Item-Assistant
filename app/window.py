"""The main window.

The layout is the argument.  On the left, what the game has; in the middle,
what the tool has; and on the right, the selected item drawn as the game draws
it.  The player puts things in the shared stash and this empties it -- so the
window is arranged around a single gesture rather than around a file format,
because the file format is not what anyone wants to think about.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QItemSelectionModel,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QTimer,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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

from .card import IconCache, ItemPane
from .catalog import ICON_SIZE, Catalog
from .models import (
    COLLECTION_COLUMNS,
    PLACE_ROLE,
    STASH_COLUMNS,
    TIER_ROLE,
    CollectionFilter,
    container_label,
    fill_collection,
    fill_stash,
    new_model,
)
from .sidebar import SidePanel

#: How often to look at the save file.  The file is a few tens of kilobytes
#: and saves are seconds apart at the fastest, so this is generous; it exists
#: to feel immediate, not to keep up.
POLL_MS = 2000

#: Shown in place of an item's stats when the game's data files cannot be
#: found.  Saying what to do about it is worth more than the space it takes.
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
        self.resize(1100, 700)

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

        self.absorb_button = QPushButton("Absorb everything")
        self.absorb_button.setToolTip(
            "Take every item out of the shared stash and keep it here.\n"
            "The stash is the inbox: whatever is in it goes."
        )
        self.absorb_button.clicked.connect(self._absorb_all)
        bar.addWidget(self.absorb_button)

        self.restore_button = QPushButton("Put back selected")
        self.restore_button.setToolTip("Return the selected items to the stash.")
        self.restore_button.clicked.connect(self._restore_selected)
        bar.addWidget(self.restore_button)

        self.auto_absorb = QCheckBox("Automatic")
        self.auto_absorb.setChecked(True)
        self.auto_absorb.setToolTip(
            "Absorb on every save, and keep absorbed items out.\n"
            "This is what makes an item vanish when the game saves."
        )
        bar.addWidget(self.auto_absorb)

        return bar

    def _build_splitter(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # The rail comes first because it is the first thing to reach for: a
        # collection of any size is narrowed before it is read.
        self.filter_group = QGroupBox("Filter")
        filters = QVBoxLayout(self.filter_group)
        self.sidebar = SidePanel()
        filters.addWidget(self.sidebar)
        splitter.addWidget(self.filter_group)

        self.stash_group = QGroupBox("In the game")
        left = QVBoxLayout(self.stash_group)
        self.stash_view, self.stash_model = self._table(STASH_COLUMNS)
        left.addWidget(self.stash_view)
        splitter.addWidget(self.stash_group)

        self.collection_group = QGroupBox("In the tool")
        right = QVBoxLayout(self.collection_group)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the collection…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_changed)
        right.addWidget(self.search)

        self.collection_view, self.collection_model = self._table(COLLECTION_COLUMNS)
        self.collection_view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.collection_proxy = CollectionFilter()
        self.collection_proxy.setSourceModel(self.collection_model)
        self.collection_proxy.setFilterKeyColumn(0)
        self.collection_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.collection_view.setModel(self.collection_proxy)
        self.sidebar.changed.connect(self._filters_changed)

        right.addWidget(self.collection_view)
        splitter.addWidget(self.collection_group)

        self.item_group = QGroupBox("Item")
        card = QVBoxLayout(self.item_group)
        self.details = ItemPane()
        self.details.display(self._details_hint())
        card.addWidget(self.details)
        splitter.addWidget(self.item_group)

        # Only a change of selection redraws the card.  The table beside it is
        # rebuilt whenever the game saves, so anything on that path has to be
        # cheap -- and building a card is not: it walks the game's data files
        # and cuts a picture out of a 512x512 sheet.
        self.collection_view.selectionModel().selectionChanged.connect(
            lambda *_: self._show_details()
        )

        splitter.setSizes([210, 360, 430, 330])
        return splitter

    def _table(self, columns: list[str]) -> tuple[QTableView, object]:
        view = QTableView()
        view.setSortingEnabled(True)
        view.setAlternatingRowColors(True)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.verticalHeader().setVisible(False)
        view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # The tier tile beside every name, at the size the catalogue paints it,
        # so the view is not asked to scale a picture per cell per redraw.
        view.setIconSize(QSize(ICON_SIZE, ICON_SIZE))

        model = new_model(columns)
        view.setModel(model)
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

    def _details_hint(self) -> str:
        """What the details pane says when it has no item to describe.

        A game that is not installed and one whose files will not open are
        different problems with different answers, so they do not get the same
        message -- the second one is a bug report waiting to happen, and it
        would be invisible if it read as "not found".
        """
        if self._game_data() is not None:
            return "Select an item to see its stats."
        if self._game_error:
            return (
                f"{GAME_DATA_MISSING}\n\n"
                f"The data files there would not open: {self._game_error}"
            )
        return GAME_DATA_MISSING

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
            self.restore_button.setEnabled(False)
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

        # A different stash is a different collection, and ticks left over from
        # the last one would silently hide most of it -- a narrowing nobody
        # asked for and, because the shape changes with it, one that can be
        # hard to see.  Cleared before the first read, not after.
        self.sidebar.reset()

        if self.service is not None:
            self.service.close()
        db_path = (
            self.db_path if self.db_path is not None else self.db_dir / location.db_name
        )
        self.service = ItemService(db_path, location)
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

    def _restore_selected(self) -> None:
        if self.service is None:
            return
        prints = self._selected_fingerprints()
        if not prints:
            QMessageBox.information(
                self, "Nothing selected", "Select items in the collection first."
            )
            return

        report = self.service.restore(prints)
        self.watcher.accept()
        self._refresh_views()

        if report.restored:
            self._set_status(
                f"put back {len(report.restored)} · they return to the game on its next load"
            )
        elif report.skipped:
            self._set_status(f"{len(report.skipped)} were already in the stash")

    def _selected_fingerprints(self) -> set[str]:
        prints = set()
        for index in self.collection_view.selectionModel().selectedRows():
            row = self.collection_proxy.mapToSource(index).row()
            prints.add(self.collection_model.item(row, 0).data(Qt.ItemDataRole.UserRole))
        return prints

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
        placements = self.service.registry.placements_for(self.service.source_key)
        placed = {
            print_: f"{container_label(p['container'], data)} · slot {p['slot']}"
            for print_, p in placements.items()
        }

        # Rebuilding the table drops the selection, and the table is rebuilt
        # on every save.  Keeping it means the details pane below stays on the
        # item being read instead of emptying itself every few seconds.
        selected = self._selected_fingerprints()
        fill_collection(self.collection_model, rows, placed, catalog)
        self._reselect(selected)

        # The rail describes what is *here*, so its shape comes from the rows
        # and not from the filters -- which is what keeps a row from vanishing
        # out from under the pointer the moment it is ticked.
        self.sidebar.set_shape(
            catalog.entry(row["fingerprint"], row).place for row in rows
        )
        self._filters_changed()

        self.stash_group.setTitle(f"In the game ({len(items)})")
        self.collection_group.setTitle(f"In the tool ({len(rows)})")

    def _reselect(self, fingerprints: set[str]) -> None:
        """Select the rows with these fingerprints, if they are still here."""
        if not fingerprints:
            return
        selection = self.collection_view.selectionModel()
        for row in range(self.collection_proxy.rowCount()):
            index = self.collection_proxy.index(row, 0)
            if index.data(Qt.ItemDataRole.UserRole) in fingerprints:
                selection.select(
                    index,
                    QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows,
                )

    # -- the card ---------------------------------------------------------

    def _show_details(self) -> None:
        """Draw the selected item's card.

        Called when the selection changes and nowhere else, so the poll that
        runs every two seconds never builds anything: a card is looked up by
        fingerprint and built only if it is not already known.
        """
        print_ = self._current_fingerprint()
        if print_ is None:
            self.details.display(self._details_hint())
            return

        content = self._details.get(print_)
        if content is None:
            content = self._render_stats(print_)
            self._details[print_] = content

        self.details.display(content, self._icons())

    def _current_fingerprint(self) -> str | None:
        """The item to describe: the last row of the selection, or nothing.

        The last rather than the first because a multiple selection is a
        working set -- what to put back, or what to look through -- and the
        row most recently added to it is the one that was just clicked.
        """
        rows = self.collection_view.selectionModel().selectedRows()
        if not rows:
            return None
        return rows[-1].data(Qt.ItemDataRole.UserRole)

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

    def _filter_changed(self, text: str) -> None:
        self.collection_proxy.setFilterFixedString(text)
        # The counts follow the search box as well as the facets: a number that
        # ignored what the player had typed would be a count of a list they are
        # not looking at.
        self._count_sidebar()

    def _filters_changed(self) -> None:
        """Apply what the sidebar has ticked, then say what each tick would leave."""
        self.collection_proxy.set_places(self.sidebar.places())
        self.collection_proxy.set_tiers(self.sidebar.tiers())
        self.collection_proxy.set_level_range(*self.sidebar.level_range())
        self._count_sidebar()

    def _count_sidebar(self) -> None:
        self.sidebar.set_counts(
            self.collection_proxy.counts(PLACE_ROLE),
            self.collection_proxy.counts(TIER_ROLE),
        )

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
            # Said here as well as in the details pane, because the pane stops
            # saying it once an item is selected -- and a stat line that reads
            # as a key rather than a sentence should have a reason visible
            # somewhere.
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
