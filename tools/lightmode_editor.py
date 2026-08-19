#!/usr/bin/env python3
"""The editor shell around the screens: select an element, change it, see it.

The palette rail edits *tokens* -- one swatch repaints every screen at once,
which is right for "is the action colour this purple or that one" and wrong for
"this one button should be gold". So the rail stays, and this adds the other
half: click any element in the phone and edit that element alone.

Overrides are written as real CSS rules into a live <style> block, keyed by a
generated `data-el` id, rather than as inline styles. Inline styles cannot
express `:hover`, which is half of what was asked for, and they cannot be
exported as something you paste into a stylesheet. A rule can do both.

The chrome around the phone is painted in literal colours, never from the
tokens under edit -- the same lesson the Restyler paid for: a toolbar drawn
from the palette disappears the moment someone sets the ground to match the
text.
"""
import json

import lightmode_screens as screens
import lightmode_theme as theme

# The properties the inspector offers, per state. Deliberately short: these are
# the four that change how an element *reads*, and a panel that offers forty
# properties is a CSS editor, not a design tool.
PROPS = [
    ("color", "Text", "color"),
    ("background-color", "Background", "color"),
    ("box-shadow", "Shadow", "shadow"),
    ("border-radius", "Radius", "radius"),
]

SHADOWS = [
    ("", "None"),
    ("var(--e1)", "e1 - rest"),
    ("var(--e2)", "e2 - raised"),
    ("var(--e3)", "e3 - overlay"),
    ("var(--e-brand)", "e-brand - CTA"),
    ("var(--e-nav)", "e-nav - tab bar"),
]

RADII = [
    ("", "Inherit"),
    ("var(--r-xs)", "xs - 6px"),
    ("var(--r-sm)", "sm - 10px"),
    ("var(--r-md)", "md - 14px"),
    ("var(--r-lg)", "lg - 20px"),
    ("var(--r-xl)", "xl - 28px"),
    ("var(--r-pill)", "pill"),
]

# ch.07's motion, as named effects rather than raw keyframes. Every one runs on
# the guide's easing and its own duration token, so a hand-tuned 340ms cannot
# creep in through this panel.
ANIMATIONS = [
    ("", "None"),
    ("vl-pulse", "Pulse"),
    ("vl-float", "Float"),
    ("vl-sheen", "Sheen sweep"),
    ("vl-breathe", "Breathe"),
    ("vl-shimmer", "Shimmer"),
]

# Hover is a transform plus the colour changes above. These are the three moves
# the guide sanctions; anything else is a new rule, not a preset.
LIFTS = [
    ("", "None"),
    ("translateY(-2px)", "Lift 2px"),
    ("translateY(-4px)", "Lift 4px"),
    ("scale(1.03)", "Grow 3%"),
    ("scale(.97)", "Press 3%"),
]

# ch.04's 4pt scale, as the only spacing values the box pane will offer. Named
# by their pixel value because that is what a designer reading a mockup has in
# hand, but written as the token so the export stays on the scale.
SPACE_STEPS = [("", "Inherit"), ("0", "0")] + [
    ("var(--space-%d)" % n, "%dpx" % (n * 4)) for n in theme.SPACE]

# Margin gets the same scale plus auto (for centring) and the negative steps a
# full-bleed child needs to cancel the gutter with.
MARGIN_STEPS = SPACE_STEPS + [("auto", "auto")] + [
    ("calc(-1 * var(--space-%d))" % n, "-%dpx" % (n * 4)) for n in (2, 4, 5, 6)]

KEYFRAMES = """
/* ch.07 motion, as named effects. Each runs on the guide's own easing. */
@keyframes vl-pulse   { 0%, 100% { opacity: 1; } 50% { opacity: .45; } }
@keyframes vl-float   { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
@keyframes vl-sheen   { 0%, 100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }
@keyframes vl-breathe { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.045); } }
@keyframes vl-shimmer { 0%, 100% { filter: brightness(1); } 50% { filter: brightness(1.18); } }
/* A family rule targets a class, not a `data-el`, so the old guard here missed
   exactly the edits most likely to animate a lot of things at once. CSS cannot
   select by animation name, so this covers everything inside a screen -- which
   costs nothing, since the two built-in animations (the sheen and the search
   pulse) already switch themselves off under the same query. */
@media (prefers-reduced-motion: reduce) {
  .vl *, .vl *::before, .vl *::after { animation-name: none !important; }
}
"""

EDITOR_CSS = """
/* ==== the editor shell ============================================== */
/* Thirty screens will not fit a flat row of pills, and a dropdown hides the
   map. Grouped by section, the rail stays scannable and says how the app is
   actually shaped. */
.tabs { display: flex; flex-direction: column; gap: .5rem; margin: 0 0 1rem; }
.tab-sec { display: flex; align-items: baseline; gap: .5rem; flex-wrap: wrap; }
.tab-sec > h4 { flex: none; width: 4.6rem; margin: 0; font-size: .62rem; font-weight: 700;
                letter-spacing: .11em; text-transform: uppercase; color: var(--c-faint); }
.tab-sec > div { display: flex; gap: .3rem; flex-wrap: wrap; flex: 1; }
.tab { border: 1px solid var(--c-line); background: var(--c-raised); color: var(--c-muted);
       border-radius: 999px; padding: .3rem .72rem; font: inherit; font-size: .74rem;
       font-weight: 600; cursor: pointer; }
.tab:hover { color: var(--c-text); border-color: var(--c-line-firm); }
.tab.is-on { background: var(--c-accent); color: #fff; border-color: var(--c-accent); }
.device .vl { display: none; }
.device .vl.is-on { display: flex; }

/* The mode switch. Painted in chrome colours like everything else out here,
   so it stays legible whatever either palette is set to. */
.modes { display: flex; gap: .25rem; background: var(--c-sunken); border-radius: 9px; padding: 3px; }
.modes button { border: 0; background: none; color: var(--c-muted); border-radius: 6px;
                padding: .34rem .8rem; font: inherit; font-size: .74rem; font-weight: 600; cursor: pointer; }
.modes button.is-on { background: var(--c-raised); color: var(--c-text); box-shadow: 0 1px 3px rgba(0,0,0,.4); }

/* Selection is drawn with outline, not border: a border would relayout the
   element being inspected and move the thing under the cursor. */
.picking .device .vl *:hover { outline: 1px dashed rgba(143,123,247,.75); outline-offset: 1px; cursor: crosshair; }
.device .vl [data-sel] { outline: 2px solid #8F7BF7; outline-offset: 1px; }

.bar { display: flex; align-items: center; gap: .5rem; margin: 0 0 1rem; flex-wrap: wrap; }
.btn-tool { border: 1px solid var(--c-line); background: var(--c-raised); color: var(--c-text);
            border-radius: 8px; padding: .42rem .8rem; font: inherit; font-size: .78rem;
            font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: .35rem; }
.btn-tool:hover { border-color: var(--c-line-firm); }
.btn-tool.is-on { background: var(--c-accent); border-color: var(--c-accent); color: #fff; }
.bar-note { font-size: .74rem; color: var(--c-faint); font-family: var(--code); }

/* the inspector */
.insp { border: 1px solid var(--c-line); border-radius: 14px; background: var(--c-raised);
        padding: 1rem; margin: 0 0 1.4rem; }
.insp-empty { color: var(--c-faint); font-size: .84rem; margin: 0; }
.insp-what { display: flex; align-items: baseline; justify-content: space-between; gap: .6rem;
             margin: 0 0 .85rem; padding-bottom: .7rem; border-bottom: 1px solid var(--c-line); }
.insp-what b { font-size: .9rem; }
.insp-what code { font-family: var(--code); font-size: .7rem; color: var(--c-accent); }

.seg { display: flex; flex-wrap: wrap; gap: .25rem; background: var(--c-sunken);
       border-radius: 9px; padding: 3px; margin: 0 0 .9rem; }
.seg button { flex: 1 0 auto; border: 0; background: none; color: var(--c-muted); border-radius: 6px;
              padding: .35rem .2rem; font: inherit; font-size: .74rem; font-weight: 600; cursor: pointer; }
.seg button.is-on { background: var(--c-raised); color: var(--c-text); box-shadow: 0 1px 3px rgba(0,0,0,.4); }

.pane { display: none; }
.pane.is-on { display: block; }
.f { display: flex; align-items: center; gap: .6rem; margin: 0 0 .6rem; }
.f > label { flex: none; width: 6.6rem; font-size: .78rem; color: var(--c-muted); }
.f input[type=color] { width: 30px; height: 28px; border-radius: 7px; border: 1px solid var(--c-line-firm);
                       padding: 0; background: none; cursor: pointer; flex: none; }
.f select, .f input[type=text], .f input[type=range] { flex: 1; min-width: 0; }
.f select, .f input[type=text] { background: var(--c-sunken); border: 1px solid var(--c-line);
                                 color: var(--c-text); border-radius: 7px; padding: .35rem .5rem;
                                 font: inherit; font-size: .78rem; }
.f textarea { flex: 1; background: var(--c-sunken); border: 1px solid var(--c-line); color: var(--c-text);
              border-radius: 7px; padding: .45rem .55rem; font: inherit; font-size: .8rem;
              line-height: 1.5; resize: vertical; min-height: 4.5rem; }
.f-clear { border: 0; background: none; color: var(--c-faint); cursor: pointer; font: inherit;
           font-size: .72rem; text-decoration: underline; flex: none; }
.f-clear:hover { color: var(--c-text); }
.f-val { flex: none; width: 3.2rem; text-align: right; font-family: var(--code); font-size: .72rem; color: var(--c-faint); }
/* Which scope an edit lands in is the one thing about this panel a person
   cannot infer from looking, so it is stated on the control itself rather
   than in a paragraph nobody reads twice. */
.f > label em { font-style: normal; display: block; font-size: .62rem; letter-spacing: .06em;
                text-transform: uppercase; color: var(--c-faint); margin-top: 1px; }
.scope-note { font-size: .74rem; color: var(--c-faint); margin: 0 0 .8rem;
              padding-left: .55rem; border-left: 2px solid var(--c-line-firm); }
.scope-note b { color: var(--c-muted); font-weight: 600; }
/* The sliders and checkboxes were still painting in the browser's own blue,
   which is the one colour on this page that belongs to neither palette. */
.insp input[type=range] { accent-color: var(--c-accent); }
.f-scope { margin-bottom: .45rem; }
.f-head { font-size: .7rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
          color: var(--c-faint); margin: 1rem 0 .45rem; display: flex; gap: .5rem; align-items: baseline; }
.f-head:first-child { margin-top: 0; }
.f-head em { font-style: normal; font-size: .62rem; letter-spacing: .06em; color: var(--c-faint);
             text-transform: uppercase; font-weight: 600; }

/* Four sides on one row: the box model is spatial, so the controls are laid
   out the way the sides actually sit rather than as four stacked dropdowns. */
.sides { display: grid; grid-template-columns: repeat(4, 1fr); gap: .35rem; margin: 0 0 .6rem; }
.sides label { display: flex; flex-direction: column; gap: .2rem; font-size: .62rem;
               font-weight: 700; color: var(--c-faint); letter-spacing: .08em; }
.sides select { background: var(--c-sunken); border: 1px solid var(--c-line); color: var(--c-text);
                border-radius: 7px; padding: .3rem .3rem; font: inherit; font-size: .72rem; width: 100%; }

/* Walking the tree. Reaching an element by clicking is fine until the thing
   you want is a parent that its own children cover completely -- a card, a
   row, the screen itself -- which is most of the containers worth editing. */
.walk { display: flex; gap: .3rem; margin: 0 0 .7rem; }
.walk button { flex: 0 0 auto; border: 1px solid var(--c-line); background: var(--c-sunken);
               color: var(--c-muted); border-radius: 7px; padding: .28rem .6rem;
               font: inherit; font-size: .72rem; font-weight: 600; cursor: pointer; }
.walk button:hover:not(:disabled) { color: var(--c-text); border-color: var(--c-line-firm); }
.walk button:disabled { opacity: .35; cursor: default; }

.code-area { width: 100%; min-height: 8rem; background: var(--c-sunken); border: 1px solid var(--c-line);
             color: var(--c-text); border-radius: 8px; padding: .6rem; font-family: var(--code);
             font-size: .74rem; line-height: 1.5; resize: vertical; margin-bottom: .7rem; }
.code-area::placeholder { color: var(--c-faint); }
.code-bad { border-color: #E5484D; }
#js-out.is-bad { color: #FF8A8F; }
#js-out.is-ok { color: #7BE0A8; }
#icon-find { flex: 1; }
.f-scope select { font-family: var(--code); font-size: .74rem; }
/* Editing a whole family is the one state where a stray click does real work,
   so the panel says so in the accent rather than leaving it to the dropdown. */
.insp.is-family { border-color: var(--c-accent); }
.insp.is-family .f-scope select { border-color: var(--c-accent); color: var(--c-accent); }
.insp.is-family .scope-note { border-left-color: var(--c-accent); }

/* the glyph grid */
.glyphs { display: grid; grid-template-columns: repeat(auto-fill, minmax(42px, 1fr)); gap: .3rem;
          max-height: 15rem; overflow-y: auto; padding: .2rem; margin: 0 0 .7rem; }
.glyphs button { aspect-ratio: 1; border: 1px solid var(--c-line); background: var(--c-sunken);
                 border-radius: 8px; color: var(--c-text); cursor: pointer; display: flex;
                 align-items: center; justify-content: center; padding: 0; }
.glyphs button:hover { border-color: var(--c-accent); color: var(--c-accent); }
.glyphs button.is-on { border-color: var(--c-accent); background: rgba(143,123,247,.16); color: var(--c-accent); }
.glyphs svg { width: 20px; height: 20px; }

.rail-head { display: flex; align-items: baseline; justify-content: space-between; margin: 0 0 .9rem; }
.rail-reset { border: 1px solid var(--c-line); background: transparent; color: var(--c-muted);
              border-radius: 8px; padding: .3rem .7rem; font: inherit; font-size: .74rem; cursor: pointer; }
.rail-reset:hover { color: var(--c-text); border-color: var(--c-line-firm); }
.rail-group { margin: 0 0 1.1rem; }
.rail-group h3 { font-size: .68rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase;
                  color: var(--c-faint); margin: 0 0 .5rem; }
.rail-row { display: flex; align-items: center; gap: .6rem; padding: .35rem 0; }
.rail-row input[type=color] { width: 30px; height: 30px; border-radius: 8px; border: 1px solid var(--c-line-firm);
                               padding: 0; background: none; cursor: pointer; flex: none; }
.rail-row label { flex: 1; font-size: .82rem; color: var(--c-text); }
.rail-row code { display: block; font-family: var(--code); font-size: .7rem; color: var(--c-faint); margin-top: 1px; }

/* export */
.export { border: 1px solid var(--c-line); border-radius: 14px; background: var(--c-raised); padding: 1rem; }
.export textarea { width: 100%; min-height: 12rem; background: var(--c-sunken); border: 1px solid var(--c-line);
                   color: var(--c-text); border-radius: 9px; padding: .6rem; font-family: var(--code);
                   font-size: .72rem; line-height: 1.6; resize: vertical; }
"""


def _opts(pairs):
    return "".join('<option value="%s">%s</option>' % (v, l) for v, l in pairs)


def inspector_html():
    """The panel itself. Every control is inert until something is selected."""
    return """
<div class="insp" id="insp">
  <p class="insp-empty" id="insp-empty">Pick an element in the phone to edit it
    &mdash; its colours, its text, its icon, what it does on hover, and whether
    it moves.</p>

  <div id="insp-body" hidden>
    <div class="insp-what">
      <b id="insp-name">&nbsp;</b>
      <code id="insp-path">&nbsp;</code>
    </div>

    <div class="walk" id="insp-walk">
      <button data-walk="parent" title="Select the element around this one">&uarr; Outer</button>
      <button data-walk="child" title="Select the first element inside this one">&darr; Inner</button>
      <button data-walk="prev" title="Previous sibling">&larr;</button>
      <button data-walk="next" title="Next sibling">&rarr;</button>
    </div>

    <div class="f f-scope"><label>Apply to</label>
      <select id="insp-scope"></select>
      <span class="f-val" id="insp-scope-n">&mdash;</span></div>
    <p class="scope-note" id="insp-scope-note">Edits land on this one element.</p>

    <div class="seg" id="insp-seg">
      <button data-pane="paint" class="is-on">Paint</button>
      <button data-pane="box">Box</button>
      <button data-pane="text">Text</button>
      <button data-pane="icon">Icon</button>
      <button data-pane="hover">Hover</button>
      <button data-pane="motion">Motion</button>
      <button data-pane="code">Code</button>
    </div>

    <div class="pane is-on" data-pane="paint">
      <p class="scope-note">Colour is answered per mode. <b>Everything else on
        this panel &mdash; type, radius, shadow, icons, words, hover and motion
        &mdash; applies to light and dark at once.</b></p>
      <div class="f"><label>Text<em>this mode</em></label>
        <input type="color" data-set="color" data-state="base">
        <input type="text" data-set="color" data-state="base" placeholder="var(--ink)">
        <button class="f-clear" data-clear="color" data-state="base">clear</button></div>
      <div class="f"><label>Background<em>this mode</em></label>
        <input type="color" data-set="background-color" data-state="base">
        <input type="text" data-set="background-color" data-state="base" placeholder="var(--surface)">
        <button class="f-clear" data-clear="background-color" data-state="base">clear</button></div>
      <div class="f"><label>Shadow<em>both modes</em></label>
        <select data-set="box-shadow" data-state="base">%(shadows)s</select></div>
      <div class="f"><label>Radius<em>both modes</em></label>
        <select data-set="border-radius" data-state="base">%(radii)s</select></div>
    </div>

    <div class="pane" data-pane="box">
      <p class="scope-note">Spacing steps are the 4pt scale from ch.04. The
        picker offers those and nothing between them, so a hand-tuned 13px
        cannot get in this way.</p>
      <p class="f-head">Padding<em>both modes</em></p>
      <div class="sides">
        <label>T<select data-set="padding-top" data-state="base">%(space)s</select></label>
        <label>R<select data-set="padding-right" data-state="base">%(space)s</select></label>
        <label>B<select data-set="padding-bottom" data-state="base">%(space)s</select></label>
        <label>L<select data-set="padding-left" data-state="base">%(space)s</select></label>
      </div>
      <p class="f-head">Margin<em>both modes</em></p>
      <div class="sides">
        <label>T<select data-set="margin-top" data-state="base">%(margins)s</select></label>
        <label>R<select data-set="margin-right" data-state="base">%(margins)s</select></label>
        <label>B<select data-set="margin-bottom" data-state="base">%(margins)s</select></label>
        <label>L<select data-set="margin-left" data-state="base">%(margins)s</select></label>
      </div>
      <p class="f-head">Border<em>width and style share; colour is per mode</em></p>
      <div class="f"><label>Width<em>both modes</em></label>
        <select data-set="border-width" data-state="base">
          <option value="">None</option><option value="1px">1px hairline</option>
          <option value="2px">2px</option><option value="3px">3px</option>
        </select></div>
      <div class="f"><label>Style<em>both modes</em></label>
        <select data-set="border-style" data-state="base">
          <option value="">None</option><option value="solid">Solid</option>
          <option value="dashed">Dashed</option><option value="dotted">Dotted</option>
        </select></div>
      <div class="f"><label>Colour<em>this mode</em></label>
        <input type="color" data-set="border-color" data-state="base">
        <input type="text" data-set="border-color" data-state="base" placeholder="var(--hairline)">
        <button class="f-clear" data-clear="border-color" data-state="base">clear</button></div>
      <p class="bar-note">ch.01 says content over chrome: a border is the last
        resort, after a shadow and a fill have both failed.</p>
    </div>

    <div class="pane" data-pane="text">
      <div class="f"><textarea id="insp-text" placeholder="This element has no text of its own."></textarea></div>
      <div class="f"><label>Family<em>both modes</em></label>
        <select data-set="font-family" data-state="base">
          <option value="">Inter (the guide's)</option>
          <option value="Georgia, 'Iowan Old Style', serif">Serif</option>
          <option value="var(--code), ui-monospace, monospace">Monospace</option>
          <option value="system-ui, sans-serif">System sans</option>
        </select></div>
      <div class="f"><label>Weight<em>both modes</em></label>
        <select data-set="font-weight" data-state="base">
          <option value="">Inherit</option><option value="400">400 regular</option>
          <option value="500">500 medium</option><option value="600">600 semibold</option>
          <option value="700">700 bold</option><option value="800">800 heavy</option>
        </select></div>
      <div class="f"><label>Size<em>both modes</em></label>
        <input type="range" min="9" max="44" step="1" data-set="font-size" data-state="base" data-unit="px">
        <span class="f-val" data-val="font-size">&mdash;</span>
        <button class="f-clear" data-clear="font-size" data-state="base">clear</button></div>
      <div class="f"><label>Line height<em>both modes</em></label>
        <input type="range" min="90" max="220" step="5" data-set="line-height" data-state="base" data-unit="/100">
        <span class="f-val" data-val="line-height">&mdash;</span>
        <button class="f-clear" data-clear="line-height" data-state="base">clear</button></div>
      <div class="f"><label>Tracking<em>both modes</em></label>
        <input type="range" min="-6" max="20" step="1" data-set="letter-spacing" data-state="base" data-unit="/100em">
        <span class="f-val" data-val="letter-spacing">&mdash;</span>
        <button class="f-clear" data-clear="letter-spacing" data-state="base">clear</button></div>
      <div class="f"><label>Align<em>both modes</em></label>
        <select data-set="text-align" data-state="base">
          <option value="">Inherit</option><option value="left">Left</option>
          <option value="center">Centre</option><option value="right">Right</option>
        </select></div>
      <div class="f"><label>Case<em>both modes</em></label>
        <select data-set="text-transform" data-state="base">
          <option value="">As written</option><option value="uppercase">UPPERCASE</option>
          <option value="lowercase">lowercase</option><option value="capitalize">Capitalise</option>
        </select></div>
      <div class="f"><label>Style<em>both modes</em></label>
        <select data-set="font-style" data-state="base">
          <option value="">Normal</option><option value="italic">Italic</option>
        </select></div>
      <div class="f"><label>Decoration<em>both modes</em></label>
        <select data-set="text-decoration" data-state="base">
          <option value="">None</option><option value="underline">Underline</option>
          <option value="underline dotted">Underline dotted</option>
          <option value="line-through">Strikethrough</option>
        </select></div>
      <div class="f"><label>Numerals<em>both modes</em></label>
        <select data-set="font-variant-numeric" data-state="base">
          <option value="">Proportional</option>
          <option value="tabular-nums">Tabular &mdash; for figures that tick</option>
        </select></div>
      <div class="f"><label>Wrap<em>both modes</em></label>
        <select data-set="text-wrap" data-state="base">
          <option value="">Default</option><option value="balance">Balance</option>
          <option value="pretty">Pretty</option><option value="nowrap">No wrap</option>
        </select></div>
    </div>

    <div class="pane" data-pane="icon">
      <p class="insp-empty" id="icon-none" hidden>No icon here. Pick one below and
        it is added to this element.</p>
      <div class="f"><input type="text" id="icon-find" placeholder="Find a mark by name">
        <span class="f-val" id="icon-count">&mdash;</span></div>
      <div class="glyphs" id="glyphs"></div>
      <div class="f"><label>Size<em>both modes</em></label>
        <input type="range" min="12" max="48" step="2" id="icon-size">
        <span class="f-val" id="icon-size-val">24px</span></div>
      <div class="f"><label>Stroke<em>both modes</em></label>
        <input type="range" min="1" max="3" step="0.25" id="icon-stroke">
        <span class="f-val" id="icon-stroke-val">2</span></div>
      <div class="f"><label>Colour<em>this mode</em></label>
        <input type="color" data-set="color" data-state="icon">
        <input type="text" data-set="color" data-state="icon" placeholder="currentColor">
        <button class="f-clear" data-clear="color" data-state="icon">clear</button></div>
      <div class="f"><button class="btn-tool" id="icon-remove">Remove icon</button></div>
    </div>

    <div class="pane" data-pane="hover">
      <div class="f"><label>Text<em>this mode</em></label>
        <input type="color" data-set="color" data-state="hover">
        <input type="text" data-set="color" data-state="hover" placeholder="unchanged">
        <button class="f-clear" data-clear="color" data-state="hover">clear</button></div>
      <div class="f"><label>Background<em>this mode</em></label>
        <input type="color" data-set="background-color" data-state="hover">
        <input type="text" data-set="background-color" data-state="hover" placeholder="unchanged">
        <button class="f-clear" data-clear="background-color" data-state="hover">clear</button></div>
      <div class="f"><label>Shadow<em>both modes</em></label>
        <select data-set="box-shadow" data-state="hover">%(shadows)s</select></div>
      <div class="f"><label>Move<em>both modes</em></label>
        <select data-set="transform" data-state="hover">%(lifts)s</select></div>
      <div class="f"><label>Over<em>both modes</em></label>
        <select data-set="transition-duration" data-state="base">
          <option value="">Default</option>
          <option value="var(--d-fast)">120ms - press</option>
          <option value="var(--d-base)">200ms - colour</option>
          <option value="var(--d-slow)">280ms - sheets</option>
        </select></div>
      <p class="bar-note">Hover the element in the phone to try it.</p>
    </div>

    <div class="pane" data-pane="motion">
      <div class="f"><label>Effect<em>both modes</em></label>
        <select data-set="animation-name" data-state="base">%(anims)s</select></div>
      <div class="f"><label>Duration<em>both modes</em></label>
        <input type="range" min="0.4" max="8" step="0.2" data-set="animation-duration" data-state="base" data-unit="s">
        <span class="f-val" data-val="animation-duration">&mdash;</span></div>
      <div class="f"><label>Repeat<em>both modes</em></label>
        <select data-set="animation-iteration-count" data-state="base">
          <option value="infinite">Forever</option><option value="1">Once</option>
          <option value="2">Twice</option><option value="3">Three times</option>
        </select></div>
      <p class="bar-note">Everything eases on cubic-bezier(.2,.8,.2,1). A
        reduced-motion visit gets none of it.</p>
    </div>

    <div class="pane" data-pane="code">
      <p class="scope-note">The escape hatch, for the thing the panels above
        do not have a control for. <b>Both of these are global</b> &mdash; they
        are not filed under an element or a mode, so write your own selectors
        and your own <code>[data-mode="dark"]</code> blocks.</p>

      <p class="f-head">Custom CSS</p>
      <textarea id="custom-css" class="code-area" spellcheck="false"
        placeholder="/* Applies live as you type. Screens are .vl -- e.g.
   .vl .btn-primary { text-transform: uppercase; }
   [data-mode=&quot;dark&quot;] .vl .card { backdrop-filter: blur(6px); } */"></textarea>

      <p class="f-head">Custom JavaScript</p>
      <textarea id="custom-js" class="code-area" spellcheck="false"
        placeholder="// Runs when you press Run, not as you type.
// `screens` is every .vl element; `$` and `$$` query inside them.
// $$('.btn-primary').forEach(b => b.textContent = 'Go');"></textarea>
      <div class="f">
        <button class="btn-tool" id="js-run">Run</button>
        <span class="bar-note" id="js-out">not run yet</span>
      </div>
      <p class="bar-note">JavaScript changes the page in place, so
        &ldquo;Reset every element&rdquo; cannot take them back &mdash; reload
        the artifact for that.</p>
    </div>
  </div>
</div>""" % {
        "shadows": _opts(SHADOWS),
        "radii": _opts(RADII),
        "lifts": _opts(LIFTS),
        "anims": _opts(ANIMATIONS),
        "space": _opts(SPACE_STEPS),
        "margins": _opts(MARGIN_STEPS),
    }


def glyph_json():
    """Every glyph, as JSON, so the icon picker can render and swap them."""
    return json.dumps(
        {name: {"box": g[0], "d": g[1]} for name, g in sorted(screens.GLYPHS.items())},
        separators=(",", ":"))


def script():
    """The editor. Plain DOM, no framework -- the page is one file.

    Overrides live in a single generated stylesheet rather than on the elements
    themselves, so `:hover` is expressible and the whole session exports as CSS
    you can paste. Each edited element earns a `data-el` id the first time it is
    touched; untouched elements stay exactly as built.
    """
    return """
<script>
(function () {
  var GLYPHS = %(glyphs)s;
  var sheet = document.getElementById("overrides");
  /* What is per mode, and what is not.
     Only *colour* is a per-mode answer: a hex that works on a light ground
     rarely works on a dark one, so `color` and `background-color` are filed
     under the mode they were chosen in. Everything else describes the thing
     rather than the palette -- how heavy the type is, how round the corner
     is, how far it lifts on hover, whether it moves -- and a button that is
     600 weight in light and 400 in dark is not one button, it is two.
     Those go to `shared` and apply in both worlds at once.
     Shadow is shared for the same reason and one more: the values on offer
     are the elevation tokens, and those already carry their own per-mode
     answer, so "raised" means raised in both without being restated.
     Text and icon swaps are shared too, and more simply -- they are edits to
     the DOM itself, which both modes are looking at. */
  var COLOR_PROPS = { "color": 1, "background-color": 1, "border-color": 1 };
  /* Keyed by *selector*, not by element. A rule aimed at one button is filed
     under `[data-el="el-3"]`; the same rule aimed at the family is filed
     under `.btn-primary` and needs no id at all. Making the key a selector
     rather than an id plus a flag means one code path writes both, and the
     export is the CSS you would have written by hand either way. */
  var rules = { light: {}, dark: {}, shared: {} };  /* store -> "sel|state" -> {prop: value} */
  var texts = {};                        /* "el-3" -> original textContent */
  var scope = "";                        /* "" = this element, else a class name */

  function storeFor(prop) { return COLOR_PROPS[prop] ? mode : "shared"; }
  var seq = 0;
  var sel = null;

  function idOf(node) {
    if (!node.dataset.el) { node.dataset.el = "el-" + (++seq); }
    return node.dataset.el;
  }

  /* What the current edit is aimed at. */
  function target(node) {
    return scope ? "." + scope : '[data-el="' + idOf(node) + '"]';
  }

  /* Every element the current scope reaches, across all screens -- a family
     edit is meant to be app-wide, not confined to whichever screen is open. */
  function matched(node) {
    if (!scope) { return [node]; }
    return Array.prototype.slice.call(
      document.querySelectorAll('.device .vl .' + scope));
  }

  /* The families this element could belong to. State classes are left out:
     `.is-on` is a mode a chip is in, not a kind of thing it is, and offering
     it as a family invites a rule that repaints every selected control in the
     app the moment one is selected. */
  function familiesOf(node) {
    var cls = (node.className && node.className.baseVal !== undefined)
      ? node.className.baseVal : (node.className || "");
    return String(cls).trim().split(/\\s+/).filter(function (c) {
      return c && c.indexOf("is-") !== 0 && c !== "vl";
    });
  }

  /* Light has to exclude dark explicitly. An unqualified `.vl [data-el]`
     matches in both worlds -- the dark stamp only *adds* a selector -- so a
     colour chosen on the light ground would follow you into the dark one and
     quietly override its answer. `shared` wants exactly that reach, so it is
     the one that stays unqualified. */
  var SCOPE = {
    shared: "",
    light: ':root:not([data-mode="dark"]) ',
    dark: '[data-mode="dark"] '
  };

  function render() {
    var out = [];
    ["shared", "light", "dark"].forEach(function (store) {
      Object.keys(rules[store]).forEach(function (key) {
        var parts = key.split("|"), what = parts[0], state = parts[1];
        var decls = rules[store][key], body = [];
        Object.keys(decls).forEach(function (p) {
          if (decls[p] !== "") { body.push("  " + p + ": " + decls[p] + ";"); }
        });
        if (!body.length) { return; }
        var s = SCOPE[store] + '.vl ' + what;
        if (state === "hover") { s += ":hover"; }
        if (state === "icon")  { s += " svg"; }
        out.push(s + " {\\n" + body.join("\\n") + "\\n}");
      });
    });
    sheet.textContent = out.join("\\n\\n");
    /* The export is what you would paste into velvt.css, so it has to carry
       the custom block too -- otherwise the one part the panels could not
       express is the one part that does not survive the trip out. */
    var custom = (document.getElementById("custom-css") || {}).value || "";
    var all = out.join("\\n\\n");
    if (custom.trim()) {
      all += (all ? "\\n\\n" : "") + "/* ---- custom ---- */\\n" + custom.trim();
    }
    document.getElementById("export-css").value = all || "/* nothing overridden yet */";
  }

  function setProp(node, state, prop, value) {
    var key = target(node) + "|" + state;
    /* The companions written alongside a value below are all structural --
       an easing, a duration, a transition list -- so they follow the property
       that triggered them into whichever store it belongs to, which for every
       one of them is `shared`. */
    var st = storeFor(prop);
    rules[st][key] = rules[st][key] || {};
    /* An animation is nothing without a duration and an easing, and asking the
       user for the easing would let a non-guide curve in. So the shorthand
       companions are written alongside the name rather than exposed. */
    if (prop === "animation-name" && value) {
      rules[st][key]["animation-timing-function"] = "var(--ease)";
      rules[st][key]["animation-iteration-count"] =
        rules[st][key]["animation-iteration-count"] || "infinite";
      rules[st][key]["animation-duration"] = rules[st][key]["animation-duration"] || "3s";
    }
    /* A border colour or style with no width paints nothing, and a width with
       no style paints nothing either -- CSS defaults border-style to none. So
       setting either one implies the other rather than leaving the user to
       discover why their border is invisible. */
    if (prop.indexOf("border-") === 0 && value) {
      var bk = target(node) + "|" + state;
      rules.shared[bk] = rules.shared[bk] || {};
      if (!rules.shared[bk]["border-style"]) { rules.shared[bk]["border-style"] = "solid"; }
      if (!rules.shared[bk]["border-width"]) { rules.shared[bk]["border-width"] = "1px"; }
    }
    if (prop === "transform" && state === "hover") {
      var base = target(node) + "|base";
      rules.shared[base] = rules.shared[base] || {};
      rules.shared[base]["transition-property"] = "color, background-color, box-shadow, transform";
      rules.shared[base]["transition-timing-function"] = "var(--ease)";
      rules.shared[base]["transition-duration"] =
        rules.shared[base]["transition-duration"] || "var(--d-base)";
    }
    rules[st][key][prop] = value;
    render();
  }

  function readProp(node, state, prop) {
    var key = target(node) + "|" + state;
    var st = storeFor(prop);
    return (rules[st][key] && rules[st][key][prop]) || "";
  }

  /* ---- selection --------------------------------------------------- */
  function label(node) {
    var tag = node.tagName.toLowerCase();
    var cls = (node.className && node.className.baseVal !== undefined)
      ? node.className.baseVal : (node.className || "");
    var first = String(cls).trim().split(/\\s+/)[0];
    return first ? tag + "." + first : tag;
  }

  function pathOf(node) {
    var bits = [];
    while (node && !node.classList.contains("vl")) {
      bits.unshift(label(node));
      node = node.parentElement;
    }
    return bits.slice(-3).join(" > ");
  }

  /* ---- scope: this element, or every one like it --------------------- */
  var scopeSel = document.getElementById("insp-scope");

  function buildScope(node) {
    var fams = familiesOf(node);
    scopeSel.innerHTML = '<option value="">This element only</option>' +
      fams.map(function (c) {
        var n = document.querySelectorAll(".device .vl ." + c).length;
        return '<option value="' + c + '">Every .' + c + " (" + n + ")</option>";
      }).join("");
    /* A family the element no longer belongs to would silently write rules
       nothing on screen matches, so the scope resets whenever it cannot be
       carried over to the new selection. */
    if (scope && fams.indexOf(scope) === -1) { scope = ""; }
    scopeSel.value = scope;
    paintScope();
  }

  function paintScope() {
    var n = scope ? matched(sel).length : 1;
    document.getElementById("insp-scope-n").textContent = n + (n === 1 ? " el" : " els");
    document.getElementById("insp").classList.toggle("is-family", !!scope);
    document.getElementById("insp-scope-note").innerHTML = scope
      ? "Edits land on <b>every ." + scope + " in the app</b>, on every screen. " +
        "Words stay on the one you picked."
      : "Edits land on this one element.";
  }

  scopeSel.addEventListener("change", function () {
    scope = this.value;
    paintScope();
    syncPanel();
  });

  function select(node) {
    document.querySelectorAll("[data-sel]").forEach(function (n) { delete n.dataset.sel; });
    sel = node;
    node.dataset.sel = "1";
    document.getElementById("insp-empty").hidden = true;
    document.getElementById("insp-body").hidden = false;
    document.getElementById("insp-name").textContent = label(node);
    document.getElementById("insp-path").textContent = pathOf(node);
    buildScope(node);
    syncWalk(node);
    syncPanel();
  }

  /* ---- walking the tree ---------------------------------------------- */
  /* Clicking reaches whatever is on top, which is never the container. The
     screen root itself is the ceiling: above it are the device frame and the
     editor's own chrome, which are not the app and must not be editable. */
  function walkTargets(node) {
    var root = node.closest("[data-screen]");
    var atRoot = node === root;
    var kids = node ? Array.prototype.filter.call(node.children, function (c) {
      return c.nodeType === 1 && c.tagName.toLowerCase() !== "svg";
    }) : [];
    var sibs = node.parentElement && !atRoot
      ? Array.prototype.filter.call(node.parentElement.children, function (c) { return c.nodeType === 1; })
      : [];
    var i = sibs.indexOf(node);
    return {
      parent: atRoot ? null : node.parentElement,
      child: kids[0] || null,
      prev: i > 0 ? sibs[i - 1] : null,
      next: i > -1 && i < sibs.length - 1 ? sibs[i + 1] : null
    };
  }

  function syncWalk(node) {
    var t = walkTargets(node);
    document.querySelectorAll("#insp-walk button").forEach(function (b) {
      b.disabled = !t[b.dataset.walk];
    });
  }

  document.getElementById("insp-walk").addEventListener("click", function (e) {
    var btn = e.target.closest("button");
    if (!btn || !sel || btn.disabled) { return; }
    var next = walkTargets(sel)[btn.dataset.walk];
    if (next) { select(next); }
  });

  document.querySelector(".device").addEventListener("click", function (e) {
    /* The screen root counts as an element: its ground, its gutter and its
       radius are all real decisions. Only the device frame around it is out
       of bounds, which the second closest() stops at. */
    var node = e.target.closest("[data-screen] *") || e.target.closest("[data-screen]");
    if (!node) { return; }
    e.preventDefault();
    e.stopPropagation();
    /* Clicking an icon should select the thing carrying it, not a <path>. */
    if (node.tagName.toLowerCase() !== "svg" && node.closest("svg")) {
      node = node.closest("svg").parentElement;
    }
    select(node);
  }, true);

  /* ---- panel <-> element sync ---------------------------------------- */
  function syncPanel() {
    if (!sel) { return; }
    document.querySelectorAll("[data-set]").forEach(function (input) {
      var v = readProp(sel, input.dataset.state, input.dataset.set);
      if (input.type === "range") {
        var n = parseFloat(v);
        if (!isNaN(n)) { input.value = n; }
        showVal(input);
      } else if (input.type === "color") {
        if (/^#[0-9a-f]{6}$/i.test(v)) { input.value = v; }
      } else {
        input.value = v;
      }
    });
    var txt = document.getElementById("insp-text");
    var own = ownText(sel);
    txt.value = own === null ? "" : own;
    txt.disabled = own === null;
    syncIconPane();
  }

  /* Only an element whose children are all inline decoration has "its own"
     text worth editing; rewriting textContent on a container would flatten
     everything inside it. */
  function ownText(node) {
    if (node.querySelector("svg, img, video, input, ol, ul, div")) { return null; }
    return node.textContent;
  }

  document.getElementById("insp-text").addEventListener("input", function () {
    if (!sel) { return; }
    /* Remember what it said before the first keystroke, or Reset has nothing
       to put back -- clearing the rules alone would leave the new words on a
       screen claiming to be untouched. */
    var id = idOf(sel);
    if (!(id in texts)) { texts[id] = sel.textContent; }
    sel.textContent = this.value;
  });

  document.querySelectorAll("[data-set]").forEach(function (input) {
    input.addEventListener("input", function () {
      if (!sel) { return; }
      var v = input.value;
      if (input.dataset.unit === "px") { v = v + "px"; }
      if (input.dataset.unit === "s") { v = v + "s"; }
      if (input.dataset.unit === "/100em") { v = (parseFloat(v) / 100) + "em"; }
      /* line-height stays unitless: a ratio scales with the font size,
         a px value silently stops doing so the moment the size changes. */
      if (input.dataset.unit === "/100") { v = String(parseFloat(v) / 100); }
      setProp(sel, input.dataset.state, input.dataset.set, v);
      showVal(input);
      /* The two controls for one property (swatch and free text) must agree:
         a var() typed on the right has no hex for the picker, and that is
         fine -- the text field is the authority when it holds a value. */
      document.querySelectorAll('[data-set="' + input.dataset.set +
        '"][data-state="' + input.dataset.state + '"]').forEach(function (other) {
        if (other !== input && other.type !== "range") { other.value = input.value; }
      });
    });
  });

  function showVal(input) {
    var out = document.querySelector('[data-val="' + input.dataset.set + '"]');
    if (!out || input.type !== "range") { return; }
    var u = input.dataset.unit;
    out.textContent = u === "/100em" ? (input.value / 100) + "em"
                    : u === "/100" ? String(input.value / 100)
                    : input.value + (u || "");
  }

  document.querySelectorAll("[data-clear]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (!sel) { return; }
      setProp(sel, btn.dataset.state, btn.dataset.clear, "");
      syncPanel();
    });
  });

  /* ---- panes ---------------------------------------------------------- */
  document.getElementById("insp-seg").addEventListener("click", function (e) {
    var btn = e.target.closest("button");
    if (!btn) { return; }
    this.querySelectorAll("button").forEach(function (b) { b.classList.remove("is-on"); });
    btn.classList.add("is-on");
    document.querySelectorAll(".pane").forEach(function (p) {
      p.classList.toggle("is-on", p.dataset.pane === btn.dataset.pane);
    });
  });

  /* ---- icons ---------------------------------------------------------- */
  var grid = document.getElementById("glyphs");
  Object.keys(GLYPHS).forEach(function (name) {
    var g = GLYPHS[name];
    var b = document.createElement("button");
    b.type = "button";
    b.dataset.glyph = name;
    b.title = name;
    var box = parseFloat(g.box.split(" ")[2]);
    b.innerHTML = '<svg viewBox="' + g.box + '" fill="none" stroke="currentColor" ' +
      'stroke-width="' + (2 * box / 24).toFixed(2) +
      '" stroke-linecap="round" stroke-linejoin="round">' + g.d + '</svg>';
    grid.appendChild(b);
  });

  /* Ninety-odd marks is a library, and a library needs a way in other than
     scrolling it. Filtering by name is enough because the names say what the
     thing *is* -- which is the registry's own rule. */
  var iconFind = document.getElementById("icon-find");
  function filterGlyphs() {
    var q = iconFind.value.trim().toLowerCase();
    var shown = 0;
    grid.querySelectorAll("button").forEach(function (b) {
      var hit = !q || b.dataset.glyph.indexOf(q) !== -1;
      b.hidden = !hit;
      if (hit) { shown++; }
    });
    document.getElementById("icon-count").textContent = shown + " of " +
      Object.keys(GLYPHS).length;
  }
  iconFind.addEventListener("input", filterGlyphs);
  filterGlyphs();

  function currentSvg() { return sel ? sel.querySelector("svg") : null; }

  function syncIconPane() {
    var svg = currentSvg();
    document.getElementById("icon-none").hidden = !!svg;
    grid.querySelectorAll("button").forEach(function (b) {
      b.classList.toggle("is-on", !!svg && b.dataset.glyph === svg.dataset.icon);
    });
    if (svg) {
      document.getElementById("icon-size").value = parseInt(svg.getAttribute("width"), 10) || 24;
      document.getElementById("icon-stroke").value = 2;
      document.getElementById("icon-size-val").textContent =
        document.getElementById("icon-size").value + "px";
    }
  }

  function drawIcon(name) {
    if (!sel) { return; }
    var g = GLYPHS[name];
    var size = document.getElementById("icon-size").value || 24;
    var stroke = document.getElementById("icon-stroke").value || 2;
    var box = parseFloat(g.box.split(" ")[2]);
    /* An icon is a DOM change, not a rule, so a family edit has to touch each
       member rather than be expressed once as CSS. Same scope, different
       mechanism -- which is why this walks matched() instead of writing a
       selector. */
    matched(sel).forEach(function (node) {
      var svg = node.querySelector("svg");
      if (!svg) {
        svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        node.insertBefore(svg, node.firstChild);
      }
      svg.setAttribute("viewBox", g.box);
      svg.setAttribute("width", size);
      svg.setAttribute("height", size);
      svg.setAttribute("fill", "none");
      svg.setAttribute("stroke-linecap", "round");
      svg.setAttribute("stroke-linejoin", "round");
      /* ch.07 asks for 2px at a 24 canvas "scaling proportionally", so a glyph
         drawn on a 20 box gets 2 * 20/24 in its own units and still lands at
         2px on screen. Reproduced here so the picker cannot break the spec. */
      svg.setAttribute("stroke-width", (stroke * box / 24).toFixed(2));
      svg.dataset.icon = name;
      svg.innerHTML = g.d;
    });
    syncIconPane();
  }

  grid.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (b) { drawIcon(b.dataset.glyph); }
  });
  ["icon-size", "icon-stroke"].forEach(function (id) {
    document.getElementById(id).addEventListener("input", function () {
      document.getElementById(id + "-val").textContent =
        this.value + (id === "icon-size" ? "px" : "");
      var svg = currentSvg();
      if (svg) { drawIcon(svg.dataset.icon); }
    });
  });
  document.getElementById("icon-remove").addEventListener("click", function () {
    if (!sel) { return; }
    matched(sel).forEach(function (node) {
      var svg = node.querySelector("svg");
      if (svg) { svg.remove(); }
    });
    syncIconPane();
  });

  /* ---- the token rail: one swatch, every screen, per mode ------------- */
  /* Token overrides go into their own stylesheet rather than onto the root's
     inline style, because inline style wins over both mode blocks at once --
     one drag in light mode would silently repaint dark mode too. Written as
     rules, each mode's overrides land in that mode's own selector. */
  var tokenSheet = document.getElementById("tokens");
  var tokens = { light: {}, dark: {} };
  var mode = "light";
  var rail = document.querySelectorAll(".rail-row input[type=color]");

  function renderTokens() {
    var out = [];
    ["light", "dark"].forEach(function (m) {
      var body = [];
      Object.keys(tokens[m]).forEach(function (t) {
        body.push("  " + t + ": " + tokens[m][t] + ";");
      });
      if (!body.length) { return; }
      /* Same trap as the element rules, and worse here: a bare `:root` ties
         with the dark block on specificity and wins on source order, because
         this sheet is written after it. */
      var s = m === "dark" ? '[data-mode="dark"]' : ':root:not([data-mode="dark"])';
      out.push(s + " {\\n" + body.join("\\n") + "\\n}");
    });
    tokenSheet.textContent = out.join("\\n\\n");
    document.getElementById("export-tokens").value =
      out.join("\\n\\n") || "/* both palettes unchanged */";
  }

  function syncRail() {
    rail.forEach(function (input) {
      var t = input.dataset.token;
      input.value = tokens[mode][t] || input.dataset[mode];
    });
  }

  rail.forEach(function (input) {
    input.addEventListener("input", function () {
      tokens[mode][input.dataset.token] = input.value;
      renderTokens();
    });
  });

  document.getElementById("rail-reset").addEventListener("click", function () {
    tokens[mode] = {};
    syncRail();
    renderTokens();
  });

  /* ---- the mode switch ------------------------------------------------ */
  document.getElementById("modes").addEventListener("click", function (e) {
    var btn = e.target.closest("button");
    if (!btn) { return; }
    mode = btn.dataset.mode;
    this.querySelectorAll("button").forEach(function (b) {
      b.classList.toggle("is-on", b === btn);
    });
    if (mode === "dark") { document.documentElement.dataset.mode = "dark"; }
    else { delete document.documentElement.dataset.mode; }
    syncRail();
    /* The colour fields now point at the other mode's answer; the structural
       ones are shared and will read back identical. Re-syncing both is
       simpler than tracking which is which out here. */
    syncPanel();
  });

  /* ---- screens -------------------------------------------------------- */
  document.querySelectorAll(".tab").forEach(function (tab) {
    tab.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (t) { t.classList.remove("is-on"); });
      document.querySelectorAll(".device .vl").forEach(function (s) { s.classList.remove("is-on"); });
      tab.classList.add("is-on");
      document.querySelector('.device .vl[data-screen="' + tab.dataset.target + '"]').classList.add("is-on");
    });
  });

  document.getElementById("reset-all").addEventListener("click", function () {
    rules = { light: {}, dark: {}, shared: {} };
    Object.keys(texts).forEach(function (id) {
      var node = document.querySelector('[data-el="' + id + '"]');
      if (node) { node.textContent = texts[id]; }
    });
    texts = {};
    scope = "";
    render();
    document.querySelectorAll("[data-sel]").forEach(function (n) { delete n.dataset.sel; });
    sel = null;
    document.getElementById("insp-empty").hidden = false;
    document.getElementById("insp-body").hidden = true;
  });

  /* ---- the escape hatches -------------------------------------------- */
  /* Custom CSS goes into its own sheet, written last so it beats both the
     generated rules and the base stylesheet without needing !important. It is
     deliberately unscoped: the point of an escape hatch is to reach what the
     panels cannot, and prefixing every selector with `.vl` would put the
     screen root itself out of reach. */
  var cssBox = document.getElementById("custom-css");
  var cssSheet = document.getElementById("custom");
  cssBox.addEventListener("input", function () {
    cssSheet.textContent = this.value;
    /* A stylesheet with a syntax error drops only the bad rule, so there is
       nothing to catch -- but a rule that parsed and a rule that survived are
       different things, and the count says which happened. */
    var kept = cssSheet.sheet ? cssSheet.sheet.cssRules.length : 0;
    this.classList.toggle("code-bad", !!this.value.trim() && kept === 0);
    render();
  });

  var jsOut = document.getElementById("js-out");
  document.getElementById("js-run").addEventListener("click", function () {
    var code = document.getElementById("custom-js").value;
    if (!code.trim()) { jsOut.textContent = "nothing to run"; jsOut.className = "bar-note"; return; }
    /* Run it rather than sandbox it: this is the user's own page and their
       own code, and a sandbox that blocks the DOM would make the feature
       pointless. What it does get is a try/catch, so a typo reports itself
       instead of silently killing the rest of the editor's listeners. */
    try {
      var screensEls = Array.prototype.slice.call(document.querySelectorAll(".device .vl"));
      var $ = function (s) { return document.querySelector(".device .vl " + s); };
      var $$ = function (s) {
        return Array.prototype.slice.call(document.querySelectorAll(".device .vl " + s));
      };
      new Function("screens", "$", "$$", code)(screensEls, $, $$);
      jsOut.textContent = "ran cleanly";
      jsOut.className = "bar-note is-ok";
    } catch (err) {
      jsOut.textContent = String(err);
      jsOut.className = "bar-note is-bad";
    }
  });

  syncRail();
  render();
  renderTokens();
  filterGlyphs();
})();
</script>""" % {"glyphs": glyph_json()}


def rail_html():
    """Both palettes, in one rail.

    Every swatch carries both of its values and shows whichever mode is
    active, rather than the rail being duplicated per mode. Two rails would
    make the pair of values look like two unrelated settings; one rail with a
    mode switch above it says the true thing -- that these are one token with
    two answers, and that changing the mode changes which answer you are
    looking at.
    """
    groups = {}
    for name, label, group, light, dark in theme.PALETTE:
        groups.setdefault(group, []).append((name, label, light, dark))
    return "\n".join(
        '<div class="rail-group"><h3>%s</h3>\n%s\n</div>' % (
            group,
            "\n".join(
                '<div class="rail-row"><input type="color" value="%s" '
                'data-token="--%s" data-light="%s" data-dark="%s">'
                '<label>%s<code>--%s</code></label></div>'
                % (light, name, light, dark, label, name)
                for name, label, light, dark in rows),
        )
        for group, rows in groups.items())


def tabs_html():
    """The screen rail, grouped by section."""
    return "".join(
        '<div class="tab-sec"><h4>%s</h4><div>%s</div></div>' % (
            section,
            "".join('<button class="tab%s" data-target="%s">%s</button>'
                    % (" is-on" if key == screens.SCREENS[0][0] else "", key, label)
                    for key, label in rows))
        for section, rows in screens.sections())
