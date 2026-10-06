# Torchlight 2 Item Assistant — how it works

This is the companion to the [README](README.md), which is for playing the
game with the tool. This one is for reading the tool: how it does what it
does, what was reverse-engineered to make it possible, what is verified and
how, and what is still unknown.

Nothing here is needed to use it.

**Contents** — [Status](#status) · [How it works](#how-it-works) ·
[Layout](#layout) · [Running from a checkout](#running-from-a-checkout) ·
[Building the executable](#building-the-executable) ·
[Notes on the format](#notes-on-the-format) ·
[Notes on the game's data](#notes-on-the-games-data) ·
[How far this is verified](#how-far-this-is-verified) · [Tests](#tests) ·
[Requirements](#requirements)

## Status

| piece | state |
|---|---|
| save format: descramble, checksum, re-scramble | done, verified byte-exact |
| stash container and item parsing | done — 107/107 items across both saves |
| SQLite registry, move-stable identity | done |
| item removal (the mechanism that makes items vanish) | done, verified on copies |
| file watcher | done — the view follows the game's saves; nothing acts on them |
| a separate stash and database per save file | done |
| the game's data files (PAK/DAT) | done — 10,355 files in 0.74 s |
| in-game item stats | done — damage, armour, effects and flat damage all render |
| the class an item is for | done — read off the game's own item files; 768 of the 6,262 state one |
| checked against an independent item database | 17 of 30 match line for line; all 13 differences accounted for |
| desktop GUI (PySide6) | done |
| the item card, drawn as the tl2-db site draws it | done — tier ink, game art cut from the PAK, affix lines in the game's green |
| packaging to `.exe` (PyInstaller) | done — one file, no console; built and attached to Releases by CI on a tag |
| exporting and importing the collection | done — one JSON file; every blob re-parsed, and the file's word for it not taken |

## How it works

Torchlight 2 scrambles `sharedstash_v2.bin` and rewrites it from memory at
save points (exit to title, map transition, death). That rewrite is what makes
this tool possible *and* what constrains it. An external edit made while the
game runs survives only until the game's next save — and an edit that *removes*
something is worse than one that adds, because the game still has its own copy
in memory: the item can be picked up again in game, and the player ends up
holding two.

So the tool does not try to intercept the game, and it does not try to outlast
it either. It watches the file so that the list of what the game is holding is
never stale, and it writes the file in exactly one place — the button that
empties the stash. An earlier version absorbed on every save by itself, which
is precisely the removal described above, made behind the game's back; the
button is the fix, and pressing it at the main menu is what keeps it a fix.
There the game has already saved and let go, so the items are gone from the
file it wrote, and the next load reads a stash without them.

Removal is safe because nothing is ever re-encoded. Each item keeps its
original bytes, so taking one out means dropping its blob and decrementing a
count. The large parts of the format nobody has reverse-engineered ride along
untouched, and the surviving items come out byte-identical. An item's
container and slot live inside its own blob rather than in its file position,
so removing one does not shift any other, and the player just sees an empty
slot.

`tl2stash/service.py` is where the two halves meet, and its module docstring is
the full statement of the rule they live by: absorbing an item means its bytes
are in the registry *and* it is out of the file, and only the second half is
ever written — at a button, on the player's word. An item the game puts back is
not taken out again behind its back; it reappears under *In the game*, where
the player can see it and absorb it once more.

## Layout

    tl2stash/
      binary.py    byte reader; Torchlight strings, length-prefixed lists
      crypto.py    scramble/descramble, checksum, save-file envelope
      item.py      item blob parser
      stash.py     stash container
      archive.py   rebuilding a stash body, writing it back safely
      registry.py  SQLite item registry
      saves.py     locating save files on disk, under the Documents folder
                   Windows names -- and TL2IA_SAVES when that is not it
      watcher.py   noticing the game's saves
      service.py   absorb / restore, and the one rule about writing
      portable.py  the collection as one file, out and back in
      taxonomy.py  kinds, and which shared-stash tab each belongs in
      pak.py       DATA.PAK.MAN and the archive beside it
      dat.py       the game's DAT trees, and the variables read from them
      gamedata.py  the install: an index by name, the effect list, the bags
      augments.py  the augment blocks of an installed tl2-db reference, read
                   at runtime and never copied in (that dataset is GPL-3.0)
      tooltip.py   an item's stat lines, written the way the game writes them
      card.py      the pieces a card is drawn from
      icons.py     item art, cut out of the game's own archive
      processes.py is Torchlight2.exe running?
      migrate.py   the one-off split into one database per save file
    app/
      __main__.py  entry point: python -m app
      window.py    the main window
      models.py    the two tables' models
      tiles.py     the collection wall, as cards
      card.py      drawing a card
      compare.py   Compare & Transfer
      filters.py   the filter bar
      advsearch.py the advanced search panel
      sidebar.py   the type rail
      catalog.py   what the archive gives the window, read once
      theme.py     the palette, and the dark stylesheet
      settings.py  the few remembered choices
      paths.py     where the tool's own folders are, source run or frozen
      version.py   the version, read by the build and by --version
      fonts/       Bitter, and the licence it travels under
      icon.ico     the icon, drawn by tools/make_icon.py
    tl2ia.py         entry script the executable is built from
    Torchlight2ItemAssistant.spec  how the executable is built
    .github/workflows/  the suite on every push, a release on every tag
    tools/
      dump_stash.py   validate the crypto and list a stash's contents
      scan.py         scan stashes into the registry
      unstash.py      take items out of a stash
      probe_item.py   field-by-field trace of one item (format debugging)
      split_registry.py  one database per save file, run once
      make_icon.py    draw app/icon.ico at every size Windows asks for
    tests/

## Running from a checkout

    python -m app                                  # the whole thing
    python -m app --save=path/to/stash.bin         # open a stash that is not being played
    python -m app --game="C:\...\Torchlight II"    # where to read item wording from
    python -m app --version

    python tools/dump_stash.py                     # validate + list the vanilla stash
    python tools/dump_stash.py path/to/stash.bin
    python tools/scan.py                           # register every stash on the machine
    python tools/unstash.py --list
    python tools/unstash.py --index 3 --dry-run
    python tools/unstash.py --index 3 --yes        # writes; makes a backup first

`unstash.py` writes only with `--yes`, and always copies the file aside first.

A checkout keeps its databases in `var/` rather than in the game's folder —
deliberately, so that a developer running the parser is not reading the
collection they actually play with. `TL2IA_DATA` moves that folder, and the
same variable moves the executable's. `TL2IA_SAVES` names the folder holding
the game's saves, for a machine where that is not where Windows says Documents
is; the tool's own folder follows it, so a checkout can be pointed at a copied
stash without touching the one being played.

## Building the executable

    pip install -r requirements-build.txt
    python -m PyInstaller --noconfirm Torchlight2ItemAssistant.spec

That writes `dist/Torchlight2ItemAssistant.exe`: one file, no console, the
icon and the version stamp in it. Pushing a tag of the form `v0.1.0` builds
the same thing on CI, runs the suite first, and puts the exe and its checksum
on the Releases page — the tag must match `__version__` in `app/version.py`,
which the workflow checks before it builds. PyInstaller output is not
byte-reproducible, so a build of the same commit on two machines gives two
sizes and two hashes; the release's `SHA256SUMS.txt` covers the released file
and nothing else.

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

**An item's class is a child node, not a field.** Which class may use an item
is stated in the game's own files, though not the way a field is: an item that
only one class may use carries a *child* of its node, with no name of its own
and a single variable, `UNITTYPE`, holding one of four words. Three of them
spell themselves and the Engineer is `RAILMAN` — an internal name the shipped
files never corrected. 768 of the 6,262 item files state one (Embermage 194,
Outlander 193, Berserker 191, Engineer 190), 11 of them only in the file they
name as their base, and the sweep over all of them costs 0.01 s, so it runs at
load and the advanced search's four class boxes are drawn from the game's own
files. That agrees with the published database on all 767 records it states a
class for, and finds one it does not: `engineer_04_chest`, the Tunic of
Triangulation.

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

**The shared stash's tabs are typed, and the game's data does not say so.**
Three tabs of 40 slots each — containers 24, 25 and 26, whose cells begin at
3322, 4322 and 5322 — and an item can only be dragged into the tab its kind
belongs in. The six bag containers the archive does define are shaped alike (a
name, an id, a sort order and a slot list) and none of them lists what it will
take; no item file names a bag at all, measured over all 6,262 of them. So the
rule is the tool's own statement, in `tl2stash/taxonomy.py`, held by
`tests/test_taxonomy.py` against every kind the archive can produce.

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
| flat enchant/socket damage | 2 | rolled onto the item in play, so absent from a base-item database; the card writes the enchanter's share as a line of its own, apart from the item's |
| a socketed gem, indented | 1 | the reference does not model socket contents |
| `Learn <spell>` | 3 | same — spells are not what that database lists |
| `15% chance to Block` | 2 | a shield's own block, which it files under another field |
| `CHEATED ITEM` | 2 | a marker on items spawned by a console command |

The counts overlap — one item can differ in two ways — and in every one of
these the tool is showing something the game shows and the reference does not
model, or spacing the game does not have. Nothing in the list is a stat read
wrongly, which is what the comparison was for.

The comparison was made before the enchantment section existed. An item an
enchanter has been at now draws lines a base-item database has no counterpart
for: the `Enchantments (n)` heading, and, where the enchanter added flat
damage, a line of its own beside the item's share. The flat-damage row's two
items differ from the reference either way — it holds no such line at all —
but an item enchanted in play and otherwise matching would now differ by the
heading alone.

## Tests

    python -m pytest tests/ -q

Tests that need real save files skip automatically when none are present.
Nothing in the suite writes to a real save — the archive tests copy first, and
a fence in `tests/conftest.py` stops any test writing outside its own
temporary folder.

## Requirements

Python 3.10+. `PySide6` for the window, `pytest` for the tests — see
`requirements.txt`.

## Licence

BSD 3-Clause — see [LICENSE](LICENSE), which is the same licence FNIStash
carries. The save-format layer in `tl2stash/` is a port of FNIStash
(Daniel Austin, 2013), so its copyright notice sits in that file beside this
project's own, which is what the licence's first two conditions ask for.

The file holds the licence and nothing else, deliberately: GitHub reads a
licence file to work out which one it is, and attribution prose among the
terms is what makes it give up and say "Other". The sentences that were there
are these ones.

The window sets its text in Bitter, which travels in `app/fonts/` under its
own licence (`app/fonts/OFL.txt`) — the SIL Open Font License, not the one
above.
