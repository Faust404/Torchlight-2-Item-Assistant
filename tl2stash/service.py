"""The application's brain: registry, stash file, and the absorb/restore cycle.

Everything above this module is presentation.  Everything below it is a
mechanism that has already been tested on its own.  This is where they meet,
and it exists mostly to get one thing right: **a write is an answer**.

Absorbing has two halves -- the item's bytes go into the registry, and the item
comes out of the file -- and the second is the half the game can undo.  It
undoes it by not knowing about it: the game holds the shared stash in memory
for the whole session and rewrites the file from that memory at every save, so
an item taken out from under a loaded character is an item the game still has,
still offers, and will write back.

That is the wrong half to lose.  An item put *into* the file from under a
running game survives only until the next save, and the player finds out about
it as a stranded item -- recoverable, and told about.  An item taken *out* from
under it is a duplicate: the player can pick it up in game and end up holding
two of something the tool also has, and nothing afterwards can tell which of
the two was the real one.

So nothing here happens on its own.  The file is read whenever the game writes
it, and written only when the player asks -- absorbing, and the transfer
buttons -- at a moment when the player can see what the game is doing.  The
tool cannot tell a main menu from a loaded character and does not pretend to;
what it can do is never act in the gaps between two of the player's own
actions, which is where the duplicate came from.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
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
from .item import Item, parse_item
from .pile import shares
from .registry import Arrival, Registry, ScanResult, held_key, is_held
from .saves import SaveLocation
from .stash import Stash, read_stash

__all__ = [
    "AbsorbResult",
    "ItemService",
    "PileResult",
    "STATUS_ABSORBED",
    "STATUS_IN_STASH",
    "STATUS_RETURNED",
]

#: Status of an item the tool has taken.  The game may put it back, because it
#: holds the stash in memory and writes that memory over the file; when it
#: does, the item appears in the list over this one again, and stays there
#: until the player takes it -- nothing takes it back out on its own.
STATUS_ABSORBED = "absorbed"

#: Status of an item that belongs to the game right now.  Known to us, but not
#: ours to remove.
STATUS_IN_STASH = "in_stash"

#: Status of an item the player deliberately put back.
#:
#: Distinguishable from ``in_stash`` because the two are different things to
#: say about the same bytes: ``in_stash`` is an item the tool has only ever
#: seen in the file, and this one it used to hold.  Absorbing it again is
#: therefore a *retake*, and is reported as one -- a player who put something
#: back and later pressed Absorb everything meant it, and is owed the
#: difference between what came back and what is new.
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
    #: Items the tool has had before and has in its hands again: put back by
    #: the player, or put back by the game and written over the file, and left
    #: there until this press.  Worth reporting separately, because the player
    #: is being told that something they have seen before is coming back in,
    #: rather than that it is new.
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


@dataclass
class PileResult:
    """What one transfer from a pile did, counted in *fish*.

    A pile's buttons send fish, not slots: "Transfer 1" means one fish however
    many game slots the pile is spread over, and "Transfer all" means all of
    them however many slots that takes.  So what the player hears afterwards
    has to be counted the same way -- ``report.restored`` counts *requests*
    (which is the right number for a card that stands for one stack) and would
    read "put back 4" for four slots of five fish apiece.

    ``report`` is the write underneath, for the tab a refusal was about.  The
    three numbers are fish that went, fish the tab had no room for, and fish
    the file already held -- the last being a whole stack that never left,
    which is the ordinary skip :func:`~tl2stash.archive.restore_items` makes
    and not a failure.
    """

    report: RestoreReport
    restored: int = 0
    refused: int = 0
    skipped: int = 0


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

    def absorb_all(self, *, dry_run: bool = False) -> AbsorbResult:
        """Take every item currently in the stash.

        This is the whole intake model: the player puts things in the shared
        stash, and this empties it.  No filter, no selection -- the stash is
        the inbox -- and no automatic caller: the press of the Absorb button
        is the only way here, and the only thing in this tool that takes an
        item out of the game.

        Everything in the file goes, including an item the player put back
        earlier and has not since removed from the stash.  Those come back
        counted as retakes rather than as new, which is the one difference
        worth saying out loud.
        """
        self.refresh()
        result = AbsorbResult(unreadable=len(self.stash.failed))

        returned = self.registry.fingerprints_with_status(STATUS_RETURNED)
        # Both statuses mean the tool has had this item before, so taking it
        # again is a retake -- the player will recognise it as such, and a
        # returned item being swept up is exactly the case where they would
        # want to be told.
        already = self.registry.absorbed_fingerprints() | returned

        fingerprints: set[str] = set()
        for item in self.stash.items:
            fingerprints.add(item.fingerprint)
            (result.retaken if item.fingerprint in already else result.taken).append(item)

        if dry_run or not fingerprints:
            return result

        # Mark first, then write.  If the write fails, the items are recorded
        # as ours and are still in the file -- which is a state the player can
        # see and clear by pressing the button again, whereas the other order
        # could remove an item nothing had a copy of.
        self.registry.set_status(fingerprints, STATUS_ABSORBED)
        result.report = archive_stash(self.source, fingerprints)
        self.refresh()
        return result

    # -- restoring -------------------------------------------------------

    def restore(self, fingerprints: set[str], *, dry_run: bool = False) -> RestoreReport:
        """Put absorbed items back into the stash, near where they were.

        A restored item is marked ``returned``, which records whose it is: the
        game's and not the tool's.  It comes off the collection, and the next
        absorb says it came back rather than counting it as new.

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
        # A held row -- a copy of the tool's whose bytes the file also has, see
        # :func:`~tl2stash.registry.held_key` -- needs two things the ordinary
        # path does not: the skip that refuses bytes the file already holds
        # must not refuse the copy the player is asking to put back, and a copy
        # that lands takes the tool's row with it, since the bare fingerprint
        # now answers for the file's.  ``handed`` is the second half of that,
        # keyed by the bytes so the report can be read against it.
        handed: dict[str, str] = {}
        for print_ in sorted(fingerprints):
            row = self.registry.get(print_)
            if row is None:
                continue
            place = self.registry.last_placement(print_, self.source_key)
            container = place["container"] if place else self.tab_for(print_)
            slot = place["slot"] if place else None
            if slot is None or not self.slot_is_a_cell(container, slot):
                slot = self.first_slot(container)
            if is_held(print_):
                handed[parse_item(row["raw"]).fingerprint] = print_
            requests.append(
                RestoreRequest(
                    raw=row["raw"],
                    container=container,
                    slot=slot,
                    label=row["name"],
                    last_slot=self.last_slot(container),
                    may_repeat=is_held(print_),
                )
            )

        report = restore_items(self.source, requests, dry_run=dry_run)
        if not dry_run and report.restored:
            landed = {print_ for print_, _, _, _ in report.restored}
            self.registry.set_status(landed, STATUS_RETURNED)
            self.registry.forget({handed[p] for p in landed if p in handed})
        self.refresh()
        return report

    # -- putting a pile back ---------------------------------------------
    #
    # Fish are the case.  The game holds five to a slot and no more, so a pile
    # -- a 3-stack and a 1-stack of the same fish, or a 20-stack a modded game
    # allowed -- cannot go back the way :meth:`restore` sends an item, which is
    # whole.  It has to be divided, and dividing is the one thing in the tool
    # that changes an item's bytes: the stack count sits inside the
    # fingerprint, so every share the game is handed is a *new* row in the
    # registry and the stack it came from stops describing anything.  What
    # follows is that division and the bookkeeping that pays for it.
    #
    # The rule that keeps it honest is in :mod:`tl2stash.pile`: a share
    # re-counts a stack down and never up, so the tool gives away fish it holds
    # and never conjures one.  What is added here is the other half -- after
    # the write, every fish that went is off the source's books and every fish
    # that did not is still on them.

    def restore_pile(
        self, fingerprints: set[str], *, stack_limit: int, dry_run: bool = False
    ) -> PileResult:
        """Put a whole pile back: every fish the tool holds of it.

        A stack that fits a game slot goes back as it is, and one that does not
        is cut into slot-sized shares -- 20 becomes 5, 5, 5, 5 and 12 becomes
        5, 5, 2.  Whole stacks first, so a stack that exactly fills a slot is a
        slot freed rather than a slot shrunk.
        """
        return self._restore_split(
            fingerprints, stack_limit=stack_limit, dry_run=dry_run
        )

    def restore_a_stack(
        self, fingerprints: set[str], *, stack_limit: int, dry_run: bool = False
    ) -> PileResult:
        """Put one game slot's worth back: the largest stack the tool holds.

        One press, one slot -- a pile of ``{3, 1}`` gives 3 and not 4, and a
        stack bigger than the limit gives one ``limit``-sized share off its
        top.  It is the same act as :meth:`restore_pile` for a pile that is
        already all one stack, which is why the card leaves the button off
        when the two would do the same thing.
        """
        return self._restore_split(
            fingerprints, stack_limit=stack_limit, one_stack=True, dry_run=dry_run
        )

    def restore_units(
        self,
        fingerprints: set[str],
        units: int,
        *,
        stack_limit: int,
        dry_run: bool = False,
    ) -> PileResult:
        """Put exactly ``units`` fish back, out of whatever the tool holds.

        The count is asked for in fish rather than in stacks because that is
        the only question a pile can answer in general: the tool may hold a
        5-stack and a 1-stack, and "six" is a thing the player can want that
        "one stack" is not.  A whole stack goes back if one of exactly that
        size is held, and otherwise the fish are split off the smallest stack
        that can spare them.
        """
        return self._restore_split(
            fingerprints, stack_limit=stack_limit, take=units, dry_run=dry_run
        )

    def _restore_split(
        self,
        fingerprints: set[str],
        *,
        stack_limit: int,
        take: int | None = None,
        one_stack: bool = False,
        dry_run: bool = False,
    ) -> PileResult:
        """Plan a division of the pile, write it, and settle the registry.

        The three public methods differ only in what they ask
        :func:`tl2stash.pile.shares` for, so they share everything after that:
        one call per share into :func:`~tl2stash.archive.restore_items`, and
        then the part that is genuinely fiddly -- working out, from what the
        write actually did, which of the tool's stacks still exist and in what
        size.

        The write comes *first*, which is the opposite of the order
        :meth:`absorb_all` uses and deliberately so.  An absorb can be repeated
        by pressing the button again, so recording it before the file agrees
        costs nothing; a restore is not re-applied by anything, so
        writing the registry ahead of the file would put fish in the tool's
        books that the file never got -- and the next transfer would send them
        again, for real.  Every mark below is made from
        :attr:`~tl2stash.archive.RestoreReport.restored`, which is what the
        file has.
        """
        self.refresh()

        rows: dict[str, sqlite3.Row] = {}
        items: dict[str, Item] = {}
        held: list[tuple[str, int]] = []
        for print_ in sorted(fingerprints):
            row = self.registry.get(print_)
            if row is None or row["quantity"] <= 0:
                continue
            # Only what the tool holds, which is what a pile is.  A ``returned``
            # row is the file's account of an item rather than the tool's -- the
            # collection is drawn from the absorbed rows for the same reason --
            # and a share of it would be a share of the game's own stack.  A
            # caller that names one is asking for something the tool has not
            # got, and leaving it out is the answer rather than a guess.
            if row["status"] != STATUS_ABSORBED:
                continue
            rows[print_] = row
            items[print_] = parse_item(row["raw"])
            # A row's copies are byte-identical stacks of the same item, and a
            # pile is all of them: two rows of the same fish *and* a row
            # holding two of it are the same twenty fish to the player.
            for _ in range(max(1, row["copies"])):
                held.append((print_, row["quantity"]))

        result = PileResult(report=RestoreReport(path=self.source))
        plan = shares(held, take=take, one_stack=one_stack, limit=stack_limit)
        if not plan:
            return result

        # Where each source stack would go: its own last cell when the tool
        # remembers one, and otherwise its kind's tab and that tab's first
        # cell -- :meth:`restore`'s rule, asked once per stack rather than
        # once per share, so the shares of one stack come out adjacent.
        where: dict[str, tuple[int, int | None]] = {}
        for print_, row in rows.items():
            place = self.registry.last_placement(print_, self.source_key)
            container = place["container"] if place else self.tab_for(print_)
            slot = place["slot"] if place else None
            if slot is None or not self.slot_is_a_cell(container, slot):
                slot = self.first_slot(container)
            where[print_] = (container, slot)

        requests: list[RestoreRequest] = []
        raw_by_print: dict[str, bytes] = {}
        prints: list[str] = []
        # How many shares of each stack have been asked for already, so the
        # second share of a 20 can ask for the cell after the first's rather
        # than for the first's again -- :func:`~tl2stash.archive.next_free_slot`
        # would then fill the lowest hole in the tab instead, and four stacks
        # cut from one would come out scattered across it.  A cell that is
        # taken after all falls back to the hole-filling walk on its own.
        taken_before: dict[str, int] = {}
        for share in plan:
            row = rows[share.source]
            container, base = where[share.source]
            step = taken_before.get(share.source, 0)
            taken_before[share.source] = step + 1
            slot = None if base is None else base + step
            # ``print_`` is the *bytes'* fingerprint rather than the source
            # row's key.  The two differ for a held row, and the file, the
            # archive and every mark below are about bytes.
            if share.whole:
                raw = row["raw"]
                print_ = items[share.source].fingerprint
            else:
                raw = items[share.source].requantified(share.size)
                print_ = parse_item(raw).fingerprint
            raw_by_print.setdefault(print_, raw)
            prints.append(print_)
            requests.append(
                RestoreRequest(
                    raw=raw,
                    container=container,
                    slot=slot,
                    label=row["name"],
                    last_slot=self.last_slot(container),
                )
            )

        # A share may legitimately repeat bytes the file already has, both
        # because the shares of one stack are identical to each other ("the
        # second five taken from the same twenty fish") and because the file
        # may hold the same bytes from an earlier transfer.  The skip
        # :func:`~tl2stash.archive.restore_items` makes by default answers a
        # different question -- "this item never left" -- and it is the right
        # answer for a stack that goes back whole and the wrong one for shares
        # that only look alike, so only the bytes that repeat *within the plan*
        # may repeat in the file.
        #
        # A held row is the other exception, and not a guess: its bytes are in
        # the file by construction -- that is the whole reason it is keyed
        # apart -- so the skip would refuse to write the tool's copy back and
        # those fish would be stuck here for good.
        #
        # What repeats is counted over the tool's own rows only.  A ``returned``
        # row is the file's account of an item rather than the tool's -- the
        # collection is drawn from the absorbed ones for exactly that reason --
        # and a caller that names one anyway is asking for bytes the file
        # already has, which is the skip's own case and not a share.  Counting
        # it here would hand it the permission a share gets and write the game
        # a second copy of its own stack.
        mine = Counter(
            print_
            for print_, share in zip(prints, plan)
            if rows[share.source]["status"] == STATUS_ABSORBED
        )
        for request, print_, share in zip(requests, prints, plan):
            request.may_repeat = is_held(share.source) or mine[print_] > 1

        report = restore_items(self.source, requests, dry_run=dry_run)
        # Kept for the caller: the window reads the refusals out of it to name
        # the tab that had no room, and a refusal is the one outcome of a send
        # the player has to do something about.
        result.report = report
        landed = Counter(print_ for print_, _, _, _ in report.restored)
        refused = Counter(print_ for print_, _, _ in report.refused)

        # Which shares the file took, in plan order.  Shares that are
        # byte-identical are interchangeable, so a count per fingerprint is
        # exact even though it cannot say *which* of them landed -- and it does
        # not need to, since they are the same fish either way.
        tally: dict[str, list[int]] = {print_: [0, 0] for print_ in rows}
        taken: list[tuple[str, int]] = []
        for share, print_ in zip(plan, prints):
            if landed[print_]:
                landed[print_] -= 1
                tally[share.source][0 if share.whole else 1] += (
                    1 if share.whole else share.size
                )
                if not share.whole:
                    taken.append((print_, share.size))
                result.restored += share.size
            elif refused[print_]:
                refused[print_] -= 1
                result.refused += share.size
            else:
                # Written down nowhere: a stack the file already holds.  Its
                # fish stay the tool's, which the settle below leaves alone.
                result.skipped += share.size

        if not dry_run:
            if taken:
                # The shares the file took are rows now, and theirs is the
                # file: a stale ``absorbed`` on any of these bytes would have
                # the vacuum take the fish straight back out of the stash the
                # player just put them in.
                counts = Counter(print_ for print_, _ in taken)
                self.registry.add(
                    [
                        Arrival(item=parse_item(raw_by_print[print_]), copies=n)
                        for print_, n in counts.items()
                    ],
                    source=self.source_key,
                    status=STATUS_RETURNED,
                )
                self.registry.set_status(set(counts), STATUS_RETURNED)
            # Every fingerprint the file holds now: what it already had -- the
            # stash read above is the one from before the write -- plus
            # everything this call put there.  A share the file refused is in
            # neither, which is right: it is not there.
            in_file = {item.fingerprint for item in self.stash_items()} | set(landed)
            for print_, (whole, sent) in tally.items():
                self._settle_stack(
                    print_,
                    row=rows[print_],
                    item=items[print_],
                    whole=whole,
                    sent=sent,
                    where=where[print_],
                    in_file=in_file,
                )
            self.refresh()

        return result

    def _settle_stack(
        self,
        print_: str,
        *,
        row: sqlite3.Row,
        item: Item,
        whole: int,
        sent: int,
        where: tuple[int, int | None],
        in_file: set[str],
    ) -> None:
        """Say what is left of one of the tool's stacks after a transfer.

        ``whole`` is how many copies of it went back exactly as they were (they
        keep the stack's identity) and ``sent`` is how many fish went as
        re-counted shares (which do not).  Everything else about the stack --
        how many copies it had, how many fish each held -- is read off ``row``,
        the registry's own account of it from *before* the write rather than
        after: a stack that has already been re-counted is a different row, and
        settling one stack's books from another's would count the same fish
        twice.

        Three outcomes, and the first is the one worth naming: a stack no share
        of which landed is left *exactly* as it was.  That is not a special
        case bolted on at the end but the reason the write comes first -- a
        refusal, a full tab, a file that already had the bytes, and the whole
        transaction is a no-op for that stack.

        ``in_file`` is every fingerprint the file holds now, and it decides one
        thing: whether the fish that stayed keep their own key or get one apart
        from the file's.  See :func:`~tl2stash.registry.held_key` -- the short
        of it is that a leftover can be the very bytes the game was just
        handed, and one row cannot answer for both sides.
        """
        copies = max(1, row["copies"])
        quantity = row["quantity"]
        remaining = copies * quantity - whole * quantity - sent
        # The plan never takes more fish from a stack than it holds, so this
        # cannot go negative; if it ever does, the tool would be about to write
        # a count that is not a count, and that is worth stopping for.
        assert remaining >= 0, f"{row['name']}: {remaining} fish left of a stack"

        if whole == 0 and sent == 0:
            return

        if remaining == 0:
            # Nothing of this stack is the tool's any more, so the row that
            # described the tool's fish goes.  A row keyed by the bytes
            # themselves is the file's account as much as the tool's, though,
            # and the copies that went whole are still those bytes -- so it
            # stays, and the marks below settle it as the file's.  A held row
            # is only ever the tool's, and it goes either way.
            if not (whole and print_ == item.fingerprint):
                self.registry.forget({print_})
        else:
            container, slot = where
            leftover = parse_item(item.requantified(remaining))
            # One stack, whatever the row held before: the fish that stayed
            # are one pile again, and a pile is what the next transfer plans
            # from.  The key is the leftover's own unless those bytes are the
            # file's too -- five sent out of ten leaves the bytes the game was
            # just handed -- in which case the tool's copy is keyed apart so
            # the bare fingerprint keeps meaning *the file's*, and neither
            # side's count is spent on the other.
            self.registry.recount(
                print_,
                leftover,
                copies=1,
                status=STATUS_ABSORBED,
                source=self.source_key,
                key=(
                    held_key(leftover.fingerprint)
                    if leftover.fingerprint in in_file
                    else None
                ),
                first_seen=row["first_seen"],
                container=container,
                slot=slot,
            )

        if whole:
            # Copies that went back untouched are still these bytes and the
            # file has them now: record them, and say the file keeps them --
            # ``returned`` rather than a fresh ``in_stash``, because the player
            # put them there and the automatic pass spares what the player put
            # back.  ``add`` leaves a row it already holds alone, so the status
            # is set as well; the file holding them is the fact, however they
            # got there.
            self.registry.add(
                [Arrival(item=item, copies=whole)],
                source=self.source_key,
                status=STATUS_RETURNED,
            )
            self.registry.set_status({item.fingerprint}, STATUS_RETURNED)

    # -- stranded items --------------------------------------------------

    def stranded_rows(self) -> list[sqlite3.Row]:
        """The tool's items that no stash file has.

        A ``returned`` row is an item the tool wrote into the stash and handed
        to the game.  If the current file does not hold it, then it exists
        nowhere the player can see: the tool says the game has it, the file
        says the game does not, and neither pane lists it.  That is the state
        a write made during play ends in -- the game's own save rewrites the
        whole stash from memory, which never had the item -- and it is worth
        *finding* rather than only avoiding, because the write looked like it
        worked.

        The file decides, not the registry's memory of it.  Both an item the
        game erased and one the player picked up onto a character leave the
        same trace behind, and nothing short of reading the game's process
        could tell them apart; see :meth:`recover` for what follows from that.

        Read off the stash already in hand rather than re-read, like
        :meth:`stash_items` -- every caller is a window that has just
        refreshed, and the poll makes them very nearly fresh anyway.
        """
        present = {item.fingerprint for item in self.stash.items}
        return [
            row
            for row in self.registry.rows(status=STATUS_RETURNED)
            if row["fingerprint"] not in present
        ]

    def recover(self, fingerprints: set[str]) -> int:
        """Take stranded items back into the collection, writing nothing.

        This is the manual half of the stranded state, and it is manual on
        purpose.  "The game's save erased the write" and "the player took the
        item onto a character" are the same row, the same bytes and the same
        absence from the file; a tool that recovered them on its own would
        bounce back every item the player had successfully taken, and one that
        wrote them back into the stash on its own would duplicate a real item
        the player is carrying.  So the tool only ever offers, and this is
        what accepting it does: the row becomes ``absorbed`` -- an ordinary
        member of the collection, ours to keep -- and the game is not touched.
        The other answer to the same state is :meth:`remove`, for the stranded
        item the player can see is a duplicate.

        Only items that are stranded *now* are recovered.  An item the file
        holds is one the game really does have, and its own answer is the
        Absorb gesture, not this one; anything else in ``fingerprints`` is
        left exactly as it was.  Returns how many rows moved, which is the
        number of things the player would see join the collection.
        """
        stranded = {row["fingerprint"] for row in self.stranded_rows()}
        wanted = stranded & set(fingerprints)
        if not wanted:
            return 0
        return self.registry.set_status(wanted, STATUS_ABSORBED)

    def remove(self, fingerprints: set[str]) -> int:
        """Drop stranded items from the collection for good.

        The second of the two answers to the stranded state, and the answer
        that exists because the state itself is ambiguous: an item handed to
        the game and absent from the file now is either one the game's save
        erased -- recover it -- or one a character is carrying, which makes
        the tool's copy a duplicate the player never earned.  The file cannot
        say which, so both answers are offered and the player, who can see
        their own character, picks.  This is the destructive one, which is
        why the window asks before calling it.

        The guard is :meth:`recover`'s, for the same reason: only items that
        are stranded *now*.  An item the file holds is one the game really
        has, and deleting the tool's record of it would throw away something
        the player can still see in their own stash -- absorbing is that
        item's answer, and anything else in ``fingerprints`` is left exactly
        as it was.  The stash file is never touched either: what is being
        deleted is the tool's copy of the item, not the item.

        Returns how many rows were deleted, which the window's status line
        reports and which is 0 when the file moved in the player's favour
        between the confirmation and the delete.
        """
        stranded = {row["fingerprint"] for row in self.stranded_rows()}
        wanted = stranded & set(fingerprints)
        if not wanted:
            return 0
        return self.registry.forget(wanted)

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
