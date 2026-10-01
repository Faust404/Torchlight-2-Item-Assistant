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
| file watcher | done — acts on the game's own saves |
| a separate stash and database per save file | done |
| the game's data files (PAK/DAT) | done — 10,355 files in 0.74 s |
| in-game item stats | done — 202 of 208 named effects resolve |
| desktop GUI (PySide6) | done |
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
      watcher.py   noticing the game's saves
      service.py   absorb / restore, and the convergence between them
      pak.py       DATA.PAK.MAN and the archive beside it
      dat.py       the game's DAT trees, and the variables read from them
      gamedata.py  the install: an index by name, the effect list, the bags
      tooltip.py   an item's stat lines, written the way the game writes them
    app/
      __main__.py  entry point: python -m app
      window.py    the main window
      models.py    the two tables' models
    tools/
      dump_stash.py   validate the crypto and list a stash's contents
      scan.py         scan stashes into the registry
      unstash.py      take items out of a stash
      probe_item.py   field-by-field trace of one item (format debugging)
      split_registry.py  one database per save file, run once
    tests/

## Usage

    python -m app                                  # the whole thing
    python -m app --save=path/to/stash.bin         # open a stash that is not being played
    python -m app --game="C:\...\Torchlight II"    # where to read item wording from

    python tools/dump_stash.py                     # validate + list the vanilla stash
    python tools/dump_stash.py path/to/stash.bin
    python tools/scan.py                           # register every stash on the machine
    python tools/unstash.py --list
    python tools/unstash.py --index 3 --dry-run
    python tools/unstash.py --index 3 --yes        # writes; makes a backup first

`unstash.py` writes only with `--yes`, and always copies the file aside first.

In the window, the left panel is the save file and the right one is the tool.
Put things in the shared stash; on the game's next save they leave the file and
appear on the right, and selecting one shows the stats the game would show.
**Put back selected** returns it to the stash, where it stays until you ask for
it back. Each save file gets its own database under `var/`, so a modded stash
and a vanilla one never mix.

The game is found by itself when it is installed. Without it the tool still
stores and returns items exactly the same; only the wording is missing, and the
details pane says so.

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

**What an effect record actually names.** An item's effect record names an
*affix*, not an effect, and an affix name is not unique: 107 different affixes
in the shipped game are called `OFFLAME DAMAGE BONUS`, granting everything from
fire damage to dodge chance. What each one carries is a node naming the effect
it grants, which is unique and which `EFFECTSLIST.DAT` has wording for; where
that still leaves several, the affix's own name settles it, because it ends
with the effect it grants. FNIStash instead reads an index off the record and
uses it as a position in `EFFECTSLIST` — measured, that agrees on 92 of 176
real occurrences, and the same affix comes with different indices on different
items, so it is not a position in anything.

The other half is that a description is a template: `[VALUE]`, `[VALUE1..5]`,
`[DURATION]`, `[DMGTYPE]`, `[VALUE_OT]`, and `[NAME]`. All 808 were read to
build the list of twelve tags. The numbers are formatted the way the game
formats them, which is a ceiling followed by a cut: `23.04` armour is `24`, and
`0.30000000000000004` at one decimal is `0.4`.

Cross-checked against an independent reverse-engineering of the same format,
[heiybb/tl2-mikuro-runtime](https://github.com/heiybb/tl2-mikuro-runtime),
which describes the container layout, the checksum seed (`5331` = `0x14D3`)
and the scramble transform identically.

## Tests

    python -m pytest tests/ -q

Tests that need real save files skip automatically when none are present.
Nothing in the suite writes to a real save — the archive tests copy first.

## Requirements

Python 3.10+. `PySide6` for the window, `pytest` for the tests — see
`requirements.txt`.
