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
| in-game item stats | done — damage, armour, effects and flat damage all render |
| checked against an independent item database | 17 of 30 match line for line; all 13 differences accounted for |
| desktop GUI (PySide6) | done |
| the item card, drawn as the tl2-db site draws it | done — tier ink, game art cut from the PAK, affix lines in the game's green |
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
      fonts/       Bitter, and the licence it travels under
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
appear on the right, and each card shows the stats the game would show.
**Transfer to Stash** on a card returns it to the game, where it stays until
you ask for it back. Each save file gets its own database under `var/`, so a
modded stash and a vanilla one never mix.

The game is found by itself when it is installed. Without it the tool still
stores and returns items exactly the same; only the wording is missing, and a
line over the collection says so.

## Notes on the format

The save-format layer is a port of
[FNIStash](https://github.com/fluffynukeit/FNIStash) (Daniel Austin, 2013), the
only public TL2 save implementation that survives contact with real save files.
Two things were established here that FNIStash does not have:

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

## Notes on the game's data

`pak.py`, `dat.py`, `gamedata.py` and `tooltip.py` are not ports of anything.
They were written from the file format itself, by observing `DATA.PAK` and
cross-checking against the public DAT2TXT notes. What follows is what that
turned up.

**What an effect record names.** A record carries an `index`, a `name` and a
value, and the `index` is the effect's **position in `EFFECTSLIST.DAT`** — that
is what says which effect is meant.

The `name` beside it cannot, because it is an *affix* name and affix names are
shared: 369 of them between them grant 1,552 effects, and `OFTHETURTLE ARMOR
BONUS` is one name for thirteen — `ARMOR BONUS`, which it ends with, and also
`STRENGTH BONUS`, `DEXTERITY BONUS` and `PERCENT CRITICAL DAMAGE`. So the name
narrows the field without settling it, and reading the effect off it is a guess
that is usually right. Usually is not good enough: it is how Bashdrill's armour
bonus, dodge chance and silence were each read as some other stat.

Two measurements settle it. Across 400 real effect records, **every** index
lands inside the set its own affix name permits — 215 of 215 where the name is
one the game's files know. And 104 of those records carry **no name at all**,
so no name-based rule can resolve them; their index is the only handle there
is. The name is kept as the fallback for a record whose index lands nowhere,
which is what a mod's items do.

**A variable's id is a hash of its name.** Every field in a DAT file is
identified by a 32-bit number, and it is Knuth's DEK hash of the field's
uppercase name: `h` starts at the name's length, then each character does
`h = ((h << 5) ^ (h >> 27) ^ c)`. `NAME` is `0x00660DE5`. Of the 33 constants
in `dat.py`, 25 reproduce from their own name and 4 more hash correctly under
the name the *game* uses (`VAR_FLAVOR` is the field `DESCRIPTION`). The last 4
have no name yet.

**Damage and armour are not in the save file.** The save holds one number for a
weapon — its physical maximum — and no elemental split at all. The split comes
from the item's own data file, which gives each element a share of a nominal
damage, and the size comes from a by-level curve in
`MEDIA/GRAPHS/STATS/BASE_WEAPON_DAMAGE.DAT`. Bashdrill's lone `72` is the
`Physical Damage 52-74` and `Electric Damage 77-110` the player reads. Armour
is the same idea against `ARMOR_PLAYER_BYLEVEL_FORSET.DAT`.

**The numbers have two rules, not one.** A positive value rounds toward
positive infinity — `23.04` armour is `24`, `28.875` Mana is `29` — while a
negative one is left exactly as stored. That is not a rounding rule anyone
would choose, and it is not one rule: across a 6,173-item corpus, 42 rendered
numbers carry a fraction and every one of them is negative and verbatim
(`-1.1%`, never `-1%`), which no rounding produces. A whole number never ends
in `.0`: not one of 7,140 shipped stat lines does.

**Some effects are a skill's name.** A description is a template —
`[VALUE]`, `[VALUE1..5]`, `[DURATION]`, `[DMGTYPE]`, `[VALUE_OT]`, `[NAME]`,
twelve tags read off all 808 descriptions. `[NAME]` is the only one that is not
a number, and it is a *skill's* display name: `WC_PROC_FULLHEAL` is an affix
under `MEDIA/AFFIXES/ITEMS` and a skill under `MEDIA/SKILLS/ARBITER`, and only
the skill carries `Fully Heal Self`.

Description strings carry the game's own colour markup (`|c00ff9933Charge|u
rate`), and `[VALUE_OT]` rounds the rate *before* multiplying it by the
duration — a 5-second affix stored at 11.259 reads `+12 Physical Damage` and
`60 Physical Damage over 5 sec.`, where multiplying the stored float gives 57.

**A socket's bonus is granted to a host, and it is not in the item's effect
list.** An item's recorded effects are the item's own, and nothing a gem put
there is among them: a socketed smallsword holds exactly one record, its own
damage bonus, and none of the two things its ember grants. So a socket's
contribution is computed from the gem and drawn on the gem's own card, and the
item's lines are the item's. What the gem grants *to* is in the affixes — a
gem's under `MEDIA/AFFIXES/GEMS/`, filed by host in the file name, a unique
socketable's under `MEDIA/AFFIXES/ITEMS/`, where the name lies and the
applicability list does not (`UNIQUE_DEGRADE_ARMOR2` wears `_ARMOR` and is a
weapon affix). That list writes `WEAPON` and `ARMOR`, which are two hosts and
not three: a gem in a ring and a gem in a breastplate are granted the same
bonus, and the game spells the host the one way for both. Which of the two an
*item* is has one answer in the archive: an item that states a `RANGE` is a
weapon and nothing else states one — over all 6,262 item files, every weapon
kind states a reach and no ring, breastplate, shield, spell or potion does. A
shield is armour for the same reason it is armour everywhere else in the tool:
it is given an armour value and not a damage range.

### How far this is verified

The rendered lines are checked against an independent item database,
[tl2db](https://tl2db.hreddy.in), which publishes a pre-rendered tooltip for
each of 6,173 items. Comparing the set of stat lines, ignoring the numbers
(every roll differs, since that database holds base items and the tool holds
the player's rolled instances), **17 of the 30 items in the tool match line for
line.** The other 13 are all accounted for, and none of them is a wrong stat:

| difference | seen on | what it is |
|---|---|---|
| `Charge  rate` (two spaces) | 12 | the reference replaced the colour codes with a space; the game's own template is `Charge\|u rate`, so one space is right |
| flat enchant/socket damage | 2 | rolled onto the item in play, so absent from a base-item database |
| a socketed gem, indented | 1 | the reference does not model socket contents |
| `Learn <spell>` | 3 | same — spells are not what that database lists |
| `15% chance to Block` | 2 | a shield's own block, which it files under another field |
| `CHEATED ITEM` | 2 | a marker on items spawned by a console command |

The counts overlap — one item can differ in two ways — and in every one of
these the tool is showing something the game shows and the reference does not
model, or spacing the game does not have. Nothing in the list is a stat read
wrongly, which is what the comparison was for.

## Tests

    python -m pytest tests/ -q

Tests that need real save files skip automatically when none are present.
Nothing in the suite writes to a real save — the archive tests copy first.

## Requirements

Python 3.10+. `PySide6` for the window, `pytest` for the tests — see
`requirements.txt`.
