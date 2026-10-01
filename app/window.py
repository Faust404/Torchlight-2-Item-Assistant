"""The main window.

The layout is the argument.  On the left, what the game has; on the right,
what the tool has; and between them the two actions that move items across.
The player puts things in the shared stash and this empties it -- so the
window is arranged around a single gesture rather than around a file format,
because the file format is not what anyone wants to think about.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer
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

from tl2stash.saves import SaveLocation, find_save_locations, live_location
from tl2stash.service import STATUS_ABSORBED, ItemService
from tl2stash.watcher import StashWatcher

from .models import (
    COLLECTION_COLUMNS,
    STASH_COLUMNS,
    container_label,
    fill_collection,
    fill_stash,
    new_model,
)

#: How often to look at the save file.  The file is a few tens of kilobytes
#: and saves are seconds apart at the fastest, so this is generous; it exists
#: to feel immediate, not to keep up.
POLL_MS = 2000


class MainWindow(QMainWindow):
    def __init__(
        self,
        db_path: str | Path | None = None,
        source: str | Path | None = None,
        db_dir: str | Path | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Torchlight 2 Item Assistant")
        self.resize(1100, 640)

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
        self.collection_proxy = QSortFilterProxyModel()
        self.collection_proxy.setSourceModel(self.collection_model)
        self.collection_proxy.setFilterKeyColumn(0)
        self.collection_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.collection_view.setModel(self.collection_proxy)
        right.addWidget(self.collection_view)

        splitter.addWidget(self.collection_group)
        splitter.setSizes([420, 680])
        return splitter

    def _table(self, columns: list[str]) -> tuple[QTableView, object]:
        view = QTableView()
        view.setSortingEnabled(True)
        view.setAlternatingRowColors(True)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.verticalHeader().setVisible(False)
        view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        model = new_model(columns)
        view.setModel(model)
        return view, model

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

        fill_stash(self.stash_model, items)

        # Only what the tool holds.  An item that is in the game -- one that
        # never left, or one the player has just put back -- is in the left
        # panel's hands, not this one's.  Listing it here as well, tagged with
        # where it currently is, made these two lists overlap and left the
        # reader to work out which entries they were actually responsible for.
        rows = self.service.registry.rows(status=STATUS_ABSORBED)
        placements = self.service.registry.placements_for(self.service.source_key)
        placed = {
            print_: f"{container_label(p['container'])} · slot {p['slot']}"
            for print_, p in placements.items()
        }
        fill_collection(self.collection_model, rows, placed)

        self.stash_group.setTitle(f"In the game ({len(items)})")
        self.collection_group.setTitle(f"In the tool ({len(rows)})")

    def _in_game_count(self) -> int:
        assert self.service is not None
        return len(self.service.stash_items())

    def _filter_changed(self, text: str) -> None:
        self.collection_proxy.setFilterFixedString(text)

    def _describe(self) -> str:
        if self.service is None:
            return ""
        held = len(self.service.registry.absorbed_fingerprints())
        return f"{self._in_game_count()} in the game · {held} absorbed here"

    def _set_status(self, message: str) -> None:
        self.status.showMessage(message)

    # -- lifecycle -------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        self._timer.stop()
        if self.service is not None:
            self.service.close()
        super().closeEvent(event)
