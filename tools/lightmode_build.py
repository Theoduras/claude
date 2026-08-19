#!/usr/bin/env python3
"""Assemble the light-mode artifact.

Stage A was one screen and a legend, for a yes/no on the look. Stage B added
the other screens and made the palette live. This is the editor: every screen
is now a surface you click into, and the thing you clicked is what you change
-- its colours, its text, its icon, its hover state and its motion.

Two scopes of edit, deliberately kept apart. The rail edits *tokens*, so one
swatch repaints every screen at once; the inspector edits *one element*, and
writes a real CSS rule for it. Neither can do the other's job, and collapsing
them would lose the distinction that makes a design system a system.

The page chrome around the screen is painted in literal colours, never from the
tokens being shown. The Restyler already paid for that lesson: a toolbar drawn
from the palette under edit disappears the moment someone sets the ground to
match the text.
"""
import os
import pathlib
import re

import lightmode_cutout as cutout
import lightmode_editor as editor
import lightmode_screens as screens
import lightmode_theme as theme

# Never the repo itself: this writes a throwaway 600KB+ build (video and logo
# art inlined as base64), not a source file, and it is not meant to be
# committed. LIGHTMODE_OUT overrides the default scratch location.
OUT = pathlib.Path(os.environ.get("LIGHTMODE_OUT", "/tmp/velvt-light.html"))

CHROME = """
:root {
  --c-ground: #16141C; --c-raised: #211E2A; --c-sunken: #100E16;
  --c-line: rgba(226,222,240,.12); --c-line-firm: rgba(226,222,240,.24);
  --c-text: #F2EFF7; --c-muted: #A49DB4; --c-faint: #6F6880;
  --c-accent: #8F7BF7;
  --ui: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  --code: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
* , *::before, *::after { box-sizing: border-box; }
html, body { margin: 0; }
body {
  background: var(--c-ground); color: var(--c-text);
  font-family: var(--ui); font-size: 15px; line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}
.page { max-width: 1120px; margin: 0 auto; padding: 2.4rem 1.5rem 4rem; }

header.top { margin-bottom: 2.2rem; }
.word { font-size: 1rem; font-weight: 700; letter-spacing: .2em; text-transform: uppercase; margin: 0 0 .5rem; }
.word span { color: var(--c-accent); }
.top p { margin: 0; color: var(--c-muted); max-width: 62ch; }

.split { display: grid; grid-template-columns: 390px 1fr; gap: 2.6rem; align-items: start; }
@media (max-width: 880px) { .split { grid-template-columns: 1fr; } }

.device {
  border-radius: 34px; padding: 10px; background: #08070C;
  box-shadow: 0 30px 80px -30px rgba(0,0,0,.9), 0 0 0 1px var(--c-line-firm);
  width: 410px;
}
.device .vl { border-radius: 26px; }
.device-cap { margin: .8rem 0 0; text-align: center; font-size: .78rem; color: var(--c-faint); font-family: var(--code); }

h2.sec { font-size: .7rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase;
         color: var(--c-faint); margin: 0 0 .9rem; }
.leg { display: flex; flex-direction: column; gap: .55rem; margin: 0 0 2.2rem; }
.leg-item { border: 1px solid var(--c-line); border-radius: 12px; padding: .7rem .85rem; background: var(--c-raised); }
.leg-item b { display: block; font-size: .85rem; font-weight: 600; margin-bottom: .15rem; }
.leg-item b em { font-style: normal; color: var(--c-accent); font-family: var(--code); font-size: .74rem;
                 font-weight: 500; margin-left: .45rem; }
.leg-item span { display: block; font-size: .82rem; color: var(--c-muted); line-height: 1.45; }
.leg-item code { font-family: var(--code); font-size: .76rem; color: #CFC4E8; }

.note { border-left: 2px solid var(--c-accent); padding: .1rem 0 .1rem .9rem; margin: 0 0 1rem; }
.note b { display: block; font-size: .85rem; margin-bottom: .1rem; }
.note span { font-size: .82rem; color: var(--c-muted); }

/* The editor needs the phone column to stay put while the inspector on the
   right grows and shrinks with whatever is selected. */
.split { align-items: start; }
.col-left { position: sticky; top: 1.5rem; }
@media (max-width: 880px) { .col-left { position: static; } }
"""


def build():
    import lightmode_assets as assets

    brand = assets.brand()
    art = (
        "  --film-still: url(%s);\n"
        "  --logo-art: url(%s);" % (brand["still"], brand["logo"])
    )

    legend = [
        ("The film is kept, and recoloured", "&mdash;",
         "The shipped hero video, not a redrawing of it. Its background was cut "
         "per frame with u2net segmentation, so the webm carries real alpha and "
         "composites onto a light ground as readily as onto the dark one. The "
         "still is the layer's own background, so a reduced-motion visit still "
         "downloads no video."),
        ("The scrim inverts", "&mdash;",
         "This is the recolour that actually matters, and it is not a palette "
         "swap. The dark landing lays a near-opaque <code>--ink</code> scrim "
         "over the film so pale type reads; here the type is dark, so the scrim "
         "lightens instead. Same five stops, same job, inverted &mdash; strong "
         "where the wordmark and buttons sit, nearly absent across the middle "
         "where the two of them meet."),
        ("The wordmark is art, not a font", "&mdash;",
         "<code>velvt-logo.svg</code> used as a mask, so the letterforms stay "
         "exactly as drawn and the fill stays ours. That is what lets a palette "
         "change reach it: on light it fills with the action purple instead of "
         "violet-into-champagne, and the sheen still sweeps across."),
        ("Velvet, not flat", "ch.01",
         "The pile is the film itself &mdash; these are felt characters, lit and "
         "shot. The CTA below them is purple <em>flat</em>, which is the rule: "
         "at button size the texture becomes dirt. The gradient-and-noise "
         "treatment for large purple surfaces belongs on the screens that have "
         "one; this screen's large surface is the film."),
        ("Content over chrome", "ch.01",
         "Nothing here has a border. The secondary button sits on "
         "<code>--e1</code>; chrome sheds a border wherever a shadow will do."),
        ("Purple leads, gold rewards", "ch.01",
         "No gold anywhere. This is not a delight moment, and gold that appears "
         "twice means one of them is wrong."),
        ("Type", "ch.03",
         "Inter alone, no second face. Display 28/34/700 at -3% tracking; body "
         "at 15/22 capped to 42ch. The headline takes exactly one two-tone "
         "break &mdash; <code>Two people,</code> in the action colour, the rest "
         "in ink. Pre-login, so it centres."),
        ("Space", "ch.04",
         "20px gutter, untouched by anything but the full-bleed film. 16px "
         "between the buttons, 20px under the wordmark."),
        ("Radius", "ch.04",
         "<code>--r-sm</code> 10px on both buttons &mdash; the step the guide "
         "assigns to buttons and fields. One scale, never an invented value."),
        ("Elevation", "ch.04",
         "<code>--e1</code> under the secondary button, and <code>--e-brand</code> "
         "putting a coloured shadow under the primary CTA &mdash; which the guide "
         "reserves for exactly that, the like, and the super-like."),
        ("Components", "ch.05",
         "52px full-width CTA, one primary per screen. Every tappable thing "
         "clears 44&times;44, the EN control included. Press is "
         "<code>scale(.97)</code> over 120ms."),
        ("Icons", "ch.07",
         "Outline, 2px at a 24 canvas, round caps and joins &mdash; read live "
         "from the app's committed <code>templates/_icons.html</code>, so the "
         "artifact and the app cannot drift."),
        ("Motion", "ch.07",
         "Everything moves on <code>cubic-bezier(.2,.8,.2,1)</code>: 120ms for "
         "a press, 200ms for colour. Nothing snaps."),
    ]

    leg_html = "\n".join(
        '<div class="leg-item"><b>%s<em>%s</em></b><span>%s</span></div>' % (t, c, d)
        for t, c, d in legend)

    departures = [
        ("Cards and chips lost their borders",
         "The mockup outlines them; the guide is explicit that selection is a "
         "fill change, never an outline, and that unselected chips sit on white "
         "with e1 and no border."),
        ("The serif headline is gone",
         "You chose the guide on this: one family, Inter, weights 400&ndash;800, "
         "no second face. The two-tone colour break carries the emphasis the "
         "serif was carrying."),
        ("The hero stayed the shipped video, recoloured",
         "Kept in on your instruction, in place of the mockup's flat purple "
         "block and the first draft's standing mascot pair. The felt "
         "characters already carry the guide's texture and its mascots "
         "principle at once, so nothing invented was needed on top."),
        ("The match-reveal pair is a placeholder",
         "Two hatched circles stand in for the felt mascots ch.06 puts here. "
         "Reading them out of the guide needs its HTML re-uploaded and "
         "<code>LIGHTMODE_GUIDE_HTML</code> pointed at it &mdash; the guide "
         "isn't in this session, so this build shipped without them rather "
         "than inventing art in their place."),
    ]
    dep_html = "\n".join(
        '<div class="note"><b>%s</b><span>%s</span></div>' % (t, d)
        for t, d in departures)

    html = """<title>Velvt Light</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
%(chrome)s
%(editor_css)s

/* ==== the light skin, from the guide's elements ==================== */
:root {
%(root)s

%(art)s
}
%(screen)s
%(landing)s
%(keyframes)s

/* ==== the same names, re-answered for the dark world ================ */
%(dark)s
</style>
<style id="tokens"></style>
<style id="overrides"></style>
<!-- written last so a custom rule wins without needing !important -->
<style id="custom"></style>

<div class="page">
  <header class="top">
    <p class="word">Velvt <span>Light</span></p>
    <p>Every screen in the app, built from the design system's elements rather
      than from the mockup's surface, and in both worlds. <b>Click anything in
      the phone</b> and the inspector opens on it: its colours, its words, its
      icon, what it does under the cursor, and whether it moves. The palette
      rail edits the other scope &mdash; a token, so one swatch repaints every
      screen at once. <b>Only colour is answered twice</b>: the mode switch
      changes which answer you are editing, while an icon, a word, a radius or
      a hover lift is the same decision in both worlds and lands in both at
      once.</p>
  </header>

  <div class="split">
    <div class="col-left">
      <div class="bar">
        <div class="modes" id="modes">
          <button data-mode="light" class="is-on">Light</button>
          <button data-mode="dark">Dark</button>
        </div>
        <span class="bar-note">%(count)d screens</span>
      </div>
      <div class="tabs">%(tabs)s</div>
      <div class="device">%(screens)s</div>
      <p class="device-cap">390 &times; 844 &mdash; the guide's baseline viewport</p>
      <div class="bar" style="margin-top:1rem;">
        <button class="btn-tool" id="reset-all" type="button">Reset every element</button>
        <span class="bar-note">click an element to begin</span>
      </div>
    </div>
    <div>
      <h2 class="sec">Inspector</h2>
      %(insp)s

      <div class="rail-head">
        <h2 class="sec" style="margin:0;">Palette &mdash; the active mode</h2>
        <button class="rail-reset" id="rail-reset" type="button">Reset</button>
      </div>
      %(rail)s

      <h2 class="sec">Export</h2>
      <div class="export">
        <p class="bar-note" style="margin:0 0 .5rem;">Per-element rules, both modes</p>
        <textarea id="export-css" readonly></textarea>
        <p class="bar-note" style="margin:.9rem 0 .5rem;">Palettes</p>
        <textarea id="export-tokens" readonly style="min-height:7rem;"></textarea>
      </div>

      <h2 class="sec" style="margin-top:2.2rem;">Where it departs from the mockup</h2>
      %(dep)s
      <h2 class="sec">Every element, and the chapter it comes from</h2>
      <div class="leg">%(leg)s</div>
    </div>
  </div>
</div>
%(script)s
""" % {
        "chrome": CHROME,
        "editor_css": editor.EDITOR_CSS,
        "keyframes": editor.KEYFRAMES,
        "art": art,
        "root": theme.root_block(),
        "dark": theme.dark_block(),
        "screen": theme.screen_css(),
        "landing": screens.LANDING_CSS,
        "count": len(screens.SCREENS),
        "tabs": editor.tabs_html(),
        "screens": screens.render_all(brand),
        "insp": editor.inspector_html(),
        "rail": editor.rail_html(),
        "script": editor.script(),
        "leg": leg_html,
        "dep": dep_html,
    }

    OUT.write_text(html, encoding="ascii")
    return OUT


if __name__ == "__main__":
    path = build()
    text = path.read_text(encoding="ascii")
    print("wrote %s -- %d bytes" % (path, len(text)))
    stray = sorted({c for c in text if ord(c) > 126})
    print("non-ascii:", stray if stray else "none")
    print("unresolved format tokens:", re.findall(r"NOISE_URL|%\(\w+\)s", text) or "none")
