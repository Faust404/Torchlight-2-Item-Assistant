# torchlight2_item_assistant

An external item store for Torchlight 2 — an out-of-game stash that does not
run out of room.

Drop items into your shared stash in game, and the tool takes them out of the
save file and into its own database.

## Status

| piece | state |
|---|---|
| save format: descramble, checksum, re-scramble | done, verified byte-exact |
| stash container and item parsing | done — 107/107 items across both saves |
| SQLite registry, move-stable identity | done |
| item removal (the mechanism that makes items vanish) | done, verified on copies |
| file watcher | not started |
| desktop GUI (PySide6) | not started |
| packaging to `.exe` (PyInstaller) | not started |

## How it works

Torchlight 2 scrambles `sharedstash_v2.bin` and rewrites it from memory at
save points (exit to title, map transition, death). That rewrite is what makes
this tool possible *and* what constrains it: an external edit made while the
game runs survives only until the game's next save.

So the tool does not try to intercept the game. It waits for the game to write
the file, then rewrites it without the items you have taken. Applied after
every save, this converges: on the next load the items are gone, and they are
sitting in the tool instead. The items disappear when the stash is next *read*
— opening the stash or re-entering the character — not the instant you save.

Removal is safe because nothing is ever re-encoded. Each item keeps its
original bytes, so taking one out means dropping its blob and decrementing a
count. The large parts of the format nobody has reverse-engineered ride along
untouched, and the surviving items come out byte-identical. An item's
container and slot live inside its own blob rather than in its file position,
so removing one does not shift any other, and the player just sees an empty
slot.

## Layout

    tl2stash/
      binary.py    byte reader; Torchlight strings, length-prefixed lists
      crypto.py    scramble/descramble, checksum, save-file envelope
      item.py      item blob parser
      stash.py     stash container
      archive.py   rebuilding a stash body, writing it back safely
      registry.py  SQLite item registry
      saves.py     locating save files on disk
    tools/
      dump_stash.py   validate the crypto and list a stash's contents
      scan.py         scan stashes into the registry
      unstash.py      take items out of a stash
      probe_item.py   field-by-field trace of one item (format debugging)
    tests/

## Usage

    python tools/dump_stash.py                     # validate + list the vanilla stash
    python tools/dump_stash.py path/to/stash.bin
    python tools/scan.py                           # register every stash on the machine
    python tools/unstash.py --list
    python tools/unstash.py --index 3 --dry-run
    python tools/unstash.py --index 3 --yes        # writes; makes a backup first

`unstash.py` writes only with `--yes`, and always copies the file aside first.

## Notes on the format

The format layer is a port of [FNIStash](https://github.com/fluffynukeit/FNIStash)
(Daniel Austin, 2013), the only public TL2 save implementation that survives
contact with real save files. Two things were established here that FNIStash
does not have:

**The extra-record count.** Each item carries a `u32` that FNIStash describes
as "added for the new stash format" and skips straight past. It is a *count* of
8-byte records that follow it. Every vanilla item has a count of zero, which is
why skipping it appears to work — but items in the potions and spells tabs
carry one, and reading them with FNIStash's layout puts every later field 8
bytes early, so the item fails to parse. Reading `8 * count` bytes reduces to
FNIStash's behaviour when the count is zero. This is why 71 items in a modded
save went from unreadable to readable.

**Identity that survives a move.** An item's fingerprint hashes its blob with
the four location bytes zeroed. Hashing the blob whole would give a moved item
a new identity — and since placing an item into the stash *is* a move, that
would break the main flow.

Cross-checked against an independent reverse-engineering of the same format,
[heiybb/tl2-mikuro-runtime](https://github.com/heiybb/tl2-mikuro-runtime),
which describes the container layout, the checksum seed (`5331` = `0x14D3`)
and the scramble transform identically.

## Tests

    python -m pytest tests/ -q

Tests that need real save files skip automatically when none are present.
Nothing in the suite writes to a real save — the archive tests copy first.

## Requirements

Python 3.10+. `PySide6` for the GUI (not yet used). `pytest` for tests.
