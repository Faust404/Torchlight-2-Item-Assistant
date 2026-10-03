"""The application's brain: registry, stash file, and the absorb/restore cycle.

Everything above this module is presentation.  Everything below it is a
mechanism that has already been tested on its own.  This is where they meet,
and it exists mostly to get one thing right: **convergence**.

The game holds the shared stash in memory and rewrites the whole file at save
points.  So writing a file the game will later overwrite is not a mistake to
be avoided -- it is the only thing the tool can do, and it is enough, provided
the tool is willing to do it again.  Absorbing an item therefore has two
halves that must both persist:

1. the item's bytes are in the registry, marked ``absorbed``; and
2. the item is out of the file.

Half 2 gets undone every time the game saves, because the game still has the
item in memory.  Half 1 does not, because the registry is ours.  So the tool
re-applies half 2 whenever the file changes -- :meth:`ItemService.enforce` --
and the two halves converge on "the item is in the tool" no matter how many
times the game puts it back.  This is what the player experiences as the item
disappearing on save/transition, and it is why the tool can be simple: it
never has to be faster than the game, only more patient than it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .archive import (
    ArchiveReport,
    RestoreReport,
    RestoreRequest,
    archive_stash,
    restore_items,
)
from .crypto import read_save_file
from .item import Item
from .registry import Registry, ScanResult
from .saves import SaveLocation
from .stash import Stash, read_stash

__all__ = [
    "AbsorbResult",
    "ItemService",
    "STATUS_ABSORBED",
    "STATUS_IN_STASH",
    "STATUS_RETURNED",
]

#: Status of an item the tool has taken.  The game may put it back; we take it
#: out again.
STATUS_ABSORBED = "absorbed"

#: Status of an item that belongs to the game right now.  Known to us, but not
#: ours to remove.
STATUS_IN_STASH = "in_stash"

#: Status of an item the player deliberately put back.
#:
#: This has to be distinguishable from ``in_stash``, and not for bookkeeping
#: reasons.  With automatic intake on, every save runs the vacuum -- so an
#: item the player had just restored would be taken straight back out, every
#: single time, and "put it back" would be a button that does nothing.  An
#: item the player returned is therefore exempt from the automatic pass until
#: they ask for it back, with the Absorb button, which means it.
STATUS_RETURNED = "returned"

#: Which container to restore into when the item was never seen in a stash
#: (imported from elsewhere, say) and there is no game to ask what it is --
#: :meth:`ItemService.tab_for` is what answers that question normally, and it
#: answers by the item's kind.  This is the shared stash's *first* tab, the one
#: that takes everything the game files nowhere else.
DEFAULT_CONTAINER = 24


@dataclass
class AbsorbResult:
    """What one absorb pass did."""

    taken: list[Item] = field(default_factory=list)
    #: Items that were already ours and had reappeared -- the game putting
    #: them back.  Re-taken, and worth reporting separately: a steady trickle
    #: here is normal, and a flood means something is wrong.
    retaken: list[Item] = field(default_factory=list)
    report: ArchiveReport | None = None
    #: How many entries in the file the parser could not read.  They are left
    #: in the file rather than removed -- see
    #: :func:`tl2stash.archive.plan_removal` -- which is the safe outcome but
    #: also a visible one: an item the tool cannot read is an item it cannot
    #: store, so the player is told rather than left wondering why one thing
    #: will not go in.  It is counted from the file rather than from the
    #: report, so that a stash holding *only* such items still says so.
    unreadable: int = 0

    @property
    def count(self) -> int:
        return len(self.taken) + len(self.retaken)

    @property
    def summary(self) -> str:
        bits = []
        if self.taken:
            bits.append(f"{len(self.taken)} absorbed")
        if self.retaken:
            bits.append(f"{len(self.retaken)} taken back")
        if self.unreadable:
            bits.append(f"{self.unreadable} left that could not be read")
        return ", ".join(bits) or "nothing to absorb"


class ItemService:
    """Absorb items out of a stash file, and put them back.

    Use as a context manager, or call :meth:`close`.
    """

    def __init__(
        self,
        db_path: str | Path,
        location: SaveLocation,
        *,
        container_cells: Callable[[int], tuple[tuple[int, int], ...]] | None = None,
        container_of: Callable[[str], int | None] | None = None,
    ) -> None:
        self.registry = Registry(db_path)
        self.location = location
        self.source = Path(location.path)
        #: The cells each container is made of, by the game's own reckoning, or
        #: ``None`` on a machine without the game -- see :meth:`first_slot` and
        #: :meth:`last_slot`.  Taken as a callable rather than as the data
        #: itself so that reading the game's files, which takes a second, stays
        #: where it is: behind the window's first need for it.
        self._cells = container_cells
        #: Which tab an item belongs in, asked by fingerprint, for an item the
        #: tool has no placement of its own for -- see :meth:`tab_for`.  A
        #: callable for the same reason, and because the answer follows from
        #: the item's *kind*: that lives in the game's data files and not in
        #: the save, so the app is the one that can say it.
        self._container_of = container_of
        self._stash: Stash | None = None

    @property
    def source_key(self) -> str:
        """What the registry calls this stash.

        Always the location's key, never its path -- see
        :attr:`SaveLocation.key`.  Taking the location object rather than a
        bare path is what makes that unavoidable: there is no path here to
        accidentally key on.
        """
        return self.location.key

    def __enter__(self) -> "ItemService":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.registry.close()

    # -- reading ---------------------------------------------------------

    def refresh(self) -> ScanResult:
        """Re-read the stash file and fold it into the registry.

        Cheap enough to call on every file change, which is the point.
        """
        save = read_save_file(self.source)
        self._stash = read_stash(save)
        return self.registry.scan(self._stash, self.source_key)

    @property
    def stash(self) -> Stash:
        if self._stash is None:
            self.refresh()
        assert self._stash is not None
        return self._stash

    def stash_items(self) -> list[Item]:
        """What is in the file right now, in file order."""
        return list(self.stash.items)

    # -- absorbing -------------------------------------------------------

    def absorb_all(
        self, *, dry_run: bool = False, include_returned: bool = True
    ) -> AbsorbResult:
        """Take every item currently in the stash.

        This is the whole intake model: the player puts things in the shared
        stash, and this empties it.  No filter, no selection -- the stash is
        the inbox.

        ``include_returned=False`` spares items the player has deliberately
        put back, and is what the automatic pass uses.  Without it, returning
        an item would achieve nothing: the next save would vacuum it again,
        and the player would watch it refuse to stay.  The explicit Absorb
        gesture keeps the default, because clicking it is a decision that
        outranks the earlier one.
        """
        self.refresh()
        result = AbsorbResult(unreadable=len(self.stash.failed))

        returned = self.registry.fingerprints_with_status(STATUS_RETURNED)
        # Both statuses mean the tool has had this item before, so taking it
        # again is a retake -- the player will recognise it as such, and a
        # returned item being swept up is exactly the case where they would
        # want to be told.
        already = self.registry.absorbed_fingerprints() | returned
        spared = set() if include_returned else returned

        fingerprints: set[str] = set()
        for item in self.stash.items:
            if item.fingerprint in spared:
                continue
            fingerprints.add(item.fingerprint)
            (result.retaken if item.fingerprint in already else result.taken).append(item)

        if dry_run or not fingerprints:
            return result

        # Mark first, then write.  If the write fails, the items are recorded
        # as ours and the next enforce pass finishes the job -- whereas the
        # other order could remove an item nothing had a copy of.
        self.registry.set_status(fingerprints, STATUS_ABSORBED)
        result.report = archive_stash(self.source, fingerprints)
        self.refresh()
        return result

    def enforce(self, *, dry_run: bool = False) -> AbsorbResult | None:
        """Take back out anything ours that the game has put back.

        Called after every observed change to the stash file.  Returns
        ``None`` when there was nothing to do, which is the common case and
        should stay silent.
        """
        self.refresh()
        absorbed = self.registry.absorbed_fingerprints()
        reappeared = [i for i in self.stash.items if i.fingerprint in absorbed]
        if not reappeared:
            return None

        result = AbsorbResult(retaken=reappeared, unreadable=len(self.stash.failed))
        if dry_run:
            return result

        result.report = archive_stash(
            self.source, {i.fingerprint for i in reappeared}
        )
        self.refresh()
        return result

    # -- restoring -------------------------------------------------------

    def restore(self, fingerprints: set[str], *, dry_run: bool = False) -> RestoreReport:
        """Put absorbed items back into the stash, near where they were.

        A restored item is marked ``returned``, which does two jobs.  It keeps
        :meth:`enforce` from snatching it straight back out, and it keeps the
        automatic vacuum off it, so an item the player put back stays put
        until they say otherwise.

        Where each one lands is :func:`~tl2stash.archive.next_free_slot`'s
        answer: the slot it had, if the tool saw it in one and the game is not
        sitting in it, and otherwise the first empty cell of the tab.  A
        placement that names a cell the game does not number in that container
        is no placement at all -- see :meth:`slot_is_a_cell` -- and the tab an
        item with no placement goes in is its *kind*'s, which is
        :meth:`tab_for`'s answer.  Nothing is written down on the way back --
        which tab and which cell are the game's business, and the player asked
        only that the item be in the stash -- *except* when the tab has no
        room, which the item is refused over: a full tab is the one answer that
        has to be said out loud, because the item stays here and the player is
        the one who has to make the room.

        Only the items that went back are marked returned.  A refused one is
        not in the game, and marking it as though it were would take it off the
        collection's hands as well -- the item would then be nowhere the player
        can see, which is the whole of what this is careful about.
        """
        self.refresh()
        requests = []
        for print_ in sorted(fingerprints):
            row = self.registry.get(print_)
            if row is None:
                continue
            place = self.registry.last_placement(print_, self.source_key)
            container = place["container"] if place else self.tab_for(print_)
            slot = place["slot"] if place else None
            if slot is None or not self.slot_is_a_cell(container, slot):
                slot = self.first_slot(container)
            requests.append(
                RestoreRequest(
                    raw=row["raw"],
                    container=container,
                    slot=slot,
                    label=row["name"],
                    last_slot=self.last_slot(container),
                )
            )

        report = restore_items(self.source, requests, dry_run=dry_run)
        if not dry_run and report.restored:
            self.registry.set_status(
                {print_ for print_, _, _, _ in report.restored}, STATUS_RETURNED
            )
        self.refresh()
        return report

    def tab_for(self, print_: str) -> int:
        """Which tab an item goes in when the tool has no place of its own.

        The item's *kind* decides, because the three tabs are typed -- a potion
        goes in the consumables tab and nowhere else -- and the rule is
        :func:`tl2stash.taxonomy.stash_tab_for`'s.  The kind comes from the
        game's data files rather than from the save, so this asks the app for
        the container rather than working it out, and the app answers by
        fingerprint.

        Without the game there is no kind to read and no rule to apply, so the
        item goes to the tab the tool has always used for one it has no place
        for: the first, which is the tab that takes everything the game files
        nowhere else.
        """
        if self._container_of is not None:
            container = self._container_of(print_)
            if container is not None:
                return container
        return DEFAULT_CONTAINER

    def first_slot(self, container: int) -> int | None:
        """Where an item goes when the tool has no place of its own for it.

        Two answers, in the order of how much they are worth.  The game's data
        says where a container's cells begin -- the shared stash's first tab
        starts at 3322, and the game's own files are what say so -- and
        without the game on the machine, the lowest slot this save has ever
        held in that container, which is the same number arrived at the long
        way round.  ``None`` when neither can answer, which is the one case
        the placement refuses to guess at.
        """
        cells = self._cells(container) if self._cells is not None else ()
        if cells:
            return cells[0][0]
        return self.registry.first_slot(container, self.source_key)

    def last_slot(self, container: int) -> int | None:
        """A container's own final cell, when the game's data says what it is.

        This is what makes a full tab a refusal rather than a slot number the
        game has no cell for: 40 cells from 3322 end at 3361, and 3362 is not a
        slot in any container of the game.  ``None`` without the game, which is
        the honest answer rather than a disappointing one -- the registry knows
        the slots this save has *used*, and the highest of those is not the end
        of the container but only the last thing that happened to be in it.
        Measured that way, a tab holding one item in its last cell would read
        as full.
        """
        cells = self._cells(container) if self._cells is not None else ()
        if not cells:
            return None
        start, count = cells[-1]
        return start + count - 1

    def slot_is_a_cell(self, container: int, slot: int) -> bool:
        """Whether the game numbers this cell in this container.

        The tool's own placements are memories of where an item *was*, and one
        of them can name a cell the container does not have: before the ceiling
        existed a full tab made the search return one past its end, and the item
        was written there -- 3362 for the first tab, which no container of the
        game numbers.  A remembered cell like that is not a cell, and honouring
        it would put the item back where the game draws nothing.

        ``True`` when there is no game to ask, which is not the same answer as
        "yes" so much as the absence of a question: a placement the tool
        recorded is all it has to go on, and contradicting it against nothing
        would send every item to a tab's first cell instead of its own.
        """
        cells = self._cells(container) if self._cells is not None else ()
        return not cells or any(start <= slot < start + count for start, count in cells)
