# Bitter, shipped with the tool

The item card sets its affix lines, its set-bonus ladder and its requirement
chips in Bitter, a slab serif, because that is the face the reference site sets
them in — see `web/app.css`'s `--doc` on the site, and `_serif` in
`app/card.py` here.  A font stack whose first family is missing is a stack that
silently falls back: on this machine Bitter is not installed, so the card would
have been drawn in Georgia, which is the site's *second* choice and a different
letterform.

So the face travels with the tool.  Nothing in the window is downloaded and
nothing depends on the machine's fonts.

## What is here

| file | what it is |
|---|---|
| `Bitter.ttf` | Bitter, the upstream variable font — one file, the `wght` axis from 100 to 900 |
| `OFL.txt` | the SIL Open Font License 1.1 the face ships under |

Bitter is OFL-1.1, which permits redistribution and embedding; the licence has
to travel with the font, which is why it is committed beside it.

It is the **variable** file rather than two static ones because upstream
publishes only that: `ofl/bitter/` on `google/fonts` holds `Bitter[wght].ttf`
and `Bitter-Italic[wght].ttf` and no static instances.  Qt 6 selects the axis
itself — `QFont.setWeight` moves `wght` and the named instances are exposed as
styles — so the one file covers both the 400 a stat line is set in and the 600
a lifted number is.  (The axis's own default is 100, so a caller that never
sets a weight would get Bitter Thin.)

## Provenance

    https://raw.githubusercontent.com/google/fonts/main/ofl/bitter/Bitter%5Bwght%5D.ttf
    https://raw.githubusercontent.com/google/fonts/main/ofl/bitter/OFL.txt

Fetched from the upstream `google/fonts` repository, which is where the site
took its own copy from.  Nothing here comes from the site's repository: its
copy is a `woff2` Latin subset, which Qt cannot read at all.
