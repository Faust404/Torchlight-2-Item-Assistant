# Torchlight 2 Item Assistant

An external item store for Torchlight 2 — an out-of-game stash that does not
run out of room.

Drop items into your shared stash in game, and the tool takes them out of the
save file and keeps them. Put them back into the game whenever you want them.

**Contents** — [Download](#download) · [Using it](#using-it) ·
[FAQ](#frequently-asked-questions) · [Building it yourself](#building-it-yourself) ·
[Going deeper](#going-deeper)

## Download

The [Releases](../../releases) page carries a prebuilt
`Torchlight2ItemAssistant.exe` for Windows: one file, nothing to install, no
Python needed. Put it wherever you like and run it.

Windows will warn you the first time ("Windows protected your PC"), because
the file is not code-signed — a certificate is an annual cost this tool does
not carry. *More info* → *Run anyway* is the way past it. `SHA256SUMS.txt`
sits beside the download for anyone who wants to check the file arrived
whole:

    Get-FileHash .\Torchlight2ItemAssistant.exe -Algorithm SHA256

The tool keeps its own files in `tl2ia_save`, inside the game's own folder
next to `save` and `modsave` — one database per stash, plus the settings. That
folder, not the executable, is the thing to back up, and it sits where backing
up is easy: copy the Torchlight 2 folder and your stored items come with the
saves they came out of. It is deliberately *not* beside the executable,
because the folder you download a program into is often one a program may not
write to at all. Set `TL2IA_DATA` to a path to keep it somewhere else.

## Using it

### The loop

1. **In game, drop what you want to keep into the shared stash.** Any tab,
   anything — the tool does not care what it is.
2. **Let the game save.** Exit to the title screen, change map, die. Anything
   that makes it write its save.
3. **The items appear in the tool**, under *In the tool*. They have left the
   stash at the same time: they are gone the next time the game reads it.
4. **To get something back**, click **Transfer to Stash** on its card. It goes
   into the shared stash and is there the next time you load a character.

That is the whole of it. The stash is the inbox: whatever is in it when the
game saves, the tool takes.

### Reading the window

Three panes, left to right:

| pane | what it is |
|---|---|
| **Type** | the rail of item kinds. Tick one to narrow the collection to it. |
| **In the game** | what is in the shared stash *right now*, as of the last look. |
| **In the tool** | your collection — everything the tool is holding for this stash. |

Above them, a bar. The tool finds your stash files by itself and lists them in
**Save:** — one for a normal game, one for a modded game, each with its own
database — and that box is which one you are looking at. Then **Refresh**,
**Show Stranded Items**, and at the right **Export Collection** and **Import
Collection**.

Over the "In the game" pane sit the two controls that decide what leaves the
save file:

* **Absorb everything** — empty the shared stash into the tool, now.
* **Automatic** (ticked by default) — do that on every save by itself, and
  keep your absorbed items from reappearing. This is what makes an item vanish
  on its own.

Over the collection are the filters: a search box, the **Advanced** button
(the full search — type, damage ranges, stat requirements, classes, and any
property line in your collection), a sort box, and **Clear filters**.

Each card is an item, drawn with the stats the game itself would show —
damage split by element, armour, effects, requirements. **Compare & Transfer**
opens it beside one you already hold; **Transfer to Stash** sends it back.

The wall opens on the first fifty cards of what the filters leave; the strip
under it, **Show All Items (550)**, says how many are still behind them. One
click draws the lot and takes the strip away, and it stays away while you
read — until a filter, the search box, or the sort moves, which puts the wall
back to its opening fifty. That is what keeps the search box quick: a search
narrows to fifty cards at a time rather than to several hundred. A save
arriving in the background changes none of that. **Show Stranded Items** is
not capped — every stranded item is one you have to decide about, and one
hidden behind a strip is one you would never decide about.

### When to do what

There is one rule, and the tool warns you when you are about to break it:

**Send items back to the stash while you are at the main menu.**

The game holds the shared stash in memory and rewrites the whole file when it
saves. An item put into that file while a character is loaded is therefore
erased by the game's next save, which never knew about it. From the main menu
nothing overwrites it, and the item is there when you load a character.

Taking items *out* has no such rule and no such timing: the tool takes them
out again after every save, as many times as the game puts them back, so you
can play normally and let it do the work. Ticking **Automatic** is all that is
needed.

If you do send one at the wrong moment, it is not lost — see
[stranded items](#i-sent-an-item-back-and-it-vanished).

### Export and Import

**Export Collection** writes everything the tool holds for the stash you are
looking at into one `.tl2ia` file: the items themselves, in the same bytes the
stash held them, with the copy counts and the place each one sat alongside for
a person reading the file. **Import Collection** reads one back in.

Items the tool already has are left exactly as they are, so reading the same
file in twice changes nothing the second time. A file from a modded stash will
not go into a vanilla one. Neither button touches a save file.

The file is JSON, meant to be readable — and editable — by hand. What is
*believed* is the bytes: every item is parsed again on the way in and its
identity recomputed, so an entry somebody has changed is refused by name while
the rest of the file still comes in.

## Frequently asked questions

### When exactly do my items disappear from the game?

When the game next *reads* the stash, not the instant you save. The tool acts
on the file the game writes; the game then shows you what it has in memory
until it reads the file again — which is when the stash is opened or a
character is loaded. So: drop items in, exit to the title screen, and they are
gone from the stash when you next look at it.

### I sent an item back and it vanished.

That is the case the warning is about: a write made while a character was
loaded, erased by the game's next save. The item is not lost — it is what the
tool calls *stranded*.

The **Show Stranded Items** button carries the count. It shows the cards that
are in no stash file, and **Recover Stranded Item** on such a card takes it
back into your collection. Nothing is written to the game at that moment: the
tool cannot tell "the game erased the write" from "the player picked it up on
a character", and re-sending a copy the game might already have would duplicate
a real item. So it only ever offers, and you decide.

From then on, send items back from the main menu and it does not happen.

### Can I lose items?

Not through the tool. It never deletes an item it has not stored first, never
drops anything it could not read, and nothing is ever re-encoded — each item
keeps its original bytes, so an item that comes back out is the item that went
in. The one way an item can go missing is the game erasing a write, above, and
that is recoverable.

### Can I choose which tab an item goes into?

No, and the game does not let you either. The shared stash's three tabs are
*typed* — 40 slots each, and a potion cannot be dragged into the arms tab — so
the tool puts an item where its kind belongs: spells in the third tab, potions
and scrolls and the rest of what is consumed in the second, everything else in
the first. An item it has seen before goes back to the slot it had, if that
slot is free.

If that tab is full, the item stays in the tool and the status line says so.
A full tab is a refusal rather than an overflow: writing past the last cell
would put the item somewhere the game draws nothing.

### Can it store things from a character's inventory or bags?

No. It works on `sharedstash_v2.bin`, the shared stash, because that is the
one container every character sees. Move an item from a bag into the shared
stash in game and it is the tool's within a save.

### Will it corrupt my save file?

The tool is written around that question:

* **The original is copied aside before every write** — `sharedstash_v2.bin`
  gains a sibling like `sharedstash_v2.bin.20261003-171500.tl2ia-bak`, and the
  ten most recent are kept.
* **Writes are staged and swapped**, so an interrupted write cannot leave a
  half-written stash where the real one was.
* **Nothing is re-encoded.** Removing an item means dropping its bytes and
  decrementing a count; the rest of the file is carried through untouched, and
  the tool refuses to rewrite a file it could not read whole.
* **Nothing unread is deleted.** An item whose bytes defeat the parser stays
  in the stash — it is counted and reported instead.

### Does it work with mods?

Yes, and modded items keep to their own stash. There is one database per
stash *file*, so the modded `modsave` stash and the vanilla `save` stash never
mix: a modded item cannot be restored into a vanilla save, not because the
code checks but because the vanilla database has never held it. Pick the stash
in the **Save:** box at the top.

An item the tool's parser cannot read — a mod's is the usual reason — is left
in the file rather than stored, and the status line counts it.

### The cards show no stats, or strange names.

The stats come from the game's own data files, which the tool finds by itself:
the install directory the game recorded when it was set up, then your Steam
libraries, then the usual GOG locations. If it cannot find them, items are
still stored and returned exactly the same — the wording is what is missing,
and a line over the collection says so.

To point it at the game, set `TL2_INSTALL` to the folder that holds `PAKS`
(the Torchlight II folder itself), or run it with `--game="<that folder>"`.
The environment variable is the one that works for the executable as well.

### Is this cheating?

The tool edits your own save files, on your own disk, between sessions. It
does not run inside the game, does not touch the game's process, and sends
nothing anywhere. Whether a stash that never fills up fits how you want to
play is your call.

### My antivirus flagged the download.

Common for PyInstaller-built executables, which is what this is: the packer is
the same one a lot of malware uses, so heuristic scanners treat the shape of
the file as suspicious. The file is not code-signed (see
[Download](#download)). `SHA256SUMS.txt` on the release page lets you confirm
the bytes, and the source beside it is the source the exe was built from — the
release workflow builds it from the tag, and never from anything else.

### Where does the tool keep its files, and how do I back them up?

`tl2ia_save`, inside the game's own Torchlight 2 folder beside `save` and
`modsave` — one database per stash file, plus your settings and the folder
remembered for export files. Back that folder up and your whole collection
goes with it.

**Export Collection** is the portable way: one file, readable, yours to keep
anywhere. Do that before reinstalling Windows, and **Import Collection** puts
it back on the other side.

### I ran it from the source instead of the exe — where did my collection go?

The two shapes of the tool keep their data in two places on purpose. The
executable uses `tl2ia_save` in the game's folder, because that is the folder
a player already backs up. A run from a checkout (`python -m app`) uses `var/`
in the repository, so that a developer poking at the parser is not reading the
collection they actually play with. Export from one and import into the other
to move a collection across.

### Does it need the game closed?

No. It watches the save file and acts when the game writes it. The only thing
timing affects is sending items *back* — see
[When to do what](#when-to-do-what).

### What does it need?

Windows, and the game's saves in the usual place
(`Documents\My Games\Runic Games\Torchlight 2`), which is where both the Steam
and the GOG versions put them. The executable needs nothing else. From source
it is Python 3.10+ with `PySide6`.

## Building it yourself

    pip install -r requirements-build.txt
    python -m PyInstaller --noconfirm Torchlight2ItemAssistant.spec

That writes `dist/Torchlight2ItemAssistant.exe`: one file, no console, the
icon and the version stamp in it. Pushing a tag of the form `v0.1.0` builds
the same thing on CI, runs the suite first, and puts the exe and its checksum
on the Releases page — the tag must match `__version__` in `app/version.py`,
which the workflow checks before it builds.

To run it from a checkout instead:

    pip install -r requirements.txt
    python -m app

which keeps its data in `var/` rather than in the game's folder, as above.
`python -m app --help` lists the arguments.

## Going deeper

[`TECHNICAL.md`](TECHNICAL.md) is the other half of this documentation: how the
tool works and why it is built this way, the save format and what was
reverse-engineered from it, the notes on the game's own data files, how far the
rendered stats are verified, the module layout, the command-line tools in
`tools/`, and how to run the tests.

## Licence

BSD 3-Clause — see [LICENSE](LICENSE), which is the same licence FNIStash
carries. The save-format layer in `tl2stash/` is a port of FNIStash
(Daniel Austin, 2013), so its copyright notice sits in that file beside this
project's own. The window sets its text in Bitter, which travels in
`app/fonts/` under the SIL Open Font License (`app/fonts/OFL.txt`).
