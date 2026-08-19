#!/usr/bin/env python3
"""The light skin, written from the guide's elements rather than from taste.

Every number below is quoted from "Velvt - Design System & Style Guide v1.0":
the 4pt spacing scale and 20px gutter (ch.04), the six-step radius scale, the
five ink-tinted elevations, the motion durations and easing (ch.07), and the
type scale with its two-tone headline rule (ch.03).

Only the *colours* are the user's own -- read off the light mockup and exempted
from the guide by their instruction. Everything structural is the guide's.

The one principle that shapes the CSS more than any token is ch.01's first:

    Velvet, not flat. Brand purple is never a flat fill on large surfaces. It
    carries a directional gradient and a faint noise overlay so it reads as
    pile, not paint. Small elements (buttons, chips, icons) stay flat --
    texture at that size becomes dirt.

So `.velvet` exists for large surfaces only, and `.btn-primary` deliberately
does not use it.
"""

# Two palettes, one set of names. The screens are written once and painted by
# whichever mode is active, which is the whole point of naming a token for what
# it *paints* rather than for its colour: `--canvas` is the page's ground in
# both worlds, and nothing downstream has to know which world it is in.
#
# The light column is the user's mockup, exempted from the guide by their
# instruction. The dark column is not invented either -- it is the app's own
# shipped palette, read out of templates/velvt.css, so "dark mode" here is the
# product that exists rather than a guess at one.
PALETTE = [
    # (css custom property, control label, group, light, dark)
    ("canvas",        "Page background",   "Ground",   "#F4F3F0", "#0B0713"),
    ("surface",       "Card surface",      "Ground",   "#FBFAF8", "#150C22"),
    ("field",         "Field fill",        "Ground",   "#EFEEEA", "#1D1230"),
    ("hairline",      "Hairline",          "Ground",   "#E5E3DE", "#2A1B42"),

    ("ink",           "Headline",          "Text",     "#14121A", "#F7F1FB"),
    ("ink-accent",    "Headline accent",   "Text",     "#6D28D9", "#A855F7"),
    ("body",          "Body",              "Text",     "#3D3A45", "#B7A6CB"),
    ("quiet",         "Quiet",             "Text",     "#8B8794", "#7C6B92"),

    ("action",        "Button fill",       "Action",   "#6D28D9", "#8A2BE2"),
    ("on-action",     "Button label",      "Action",   "#FFFFFF", "#FFFFFF"),
    ("action-wash",   "Wash",              "Action",   "#EDE4FE", "#2B1247"),
    ("velvet-1",      "Velvet start",      "Action",   "#6739FF", "#A855F7"),
    ("velvet-2",      "Velvet middle",     "Action",   "#6D53F4", "#8A2BE2"),
    ("velvet-3",      "Velvet end",        "Action",   "#3C2E86", "#3B0B66"),

    # ch.01: gold rewards. On light it is the mockup's acid yellow; on dark it
    # is the guide's champagne, which is the same role played by the colour
    # that actually reads as a highlight on a near-black ground.
    ("delight",       "Delight",           "Delight",  "#FAE83E", "#E8D3A9"),
    ("on-delight",    "Delight text",      "Delight",  "#242424", "#241B0C"),
    ("delight-deep",  "Delight as text",   "Delight",  "#8A7C0C", "#E8D3A9"),

    ("live",          "Live dot",          "Status",   "#0E9F6E", "#1DA6A2"),
    ("success",       "Success",           "Status",   "#05B216", "#35D07F"),
    ("danger",        "Danger",            "Status",   "#EA4545", "#FF7A8A"),

    ("nav-shell",     "Nav shell",         "Nav",      "#1B1B1B", "#150C22"),
    ("nav-active",    "Active tab",        "Nav",      "#FFFFFF", "#FFFFFF"),
    ("nav-rest",      "Resting tab",       "Nav",      "#8C8C8C", "#7C6B92"),

    # The landing's film scrim. This is a token rather than a literal because
    # it is the one colour that *must* follow the mode: the scrim exists to
    # make type legible over the video, so it lightens under dark type and
    # darkens under pale type. Same five stops, same job, inverted.
    ("scrim",         "Film scrim",        "Film",     "#F4F3F0", "#0B0713"),
]

# ch.04, quoted. The comment on each is the guide's own "Use" column.
RADIUS = [
    ("r-xs",   "6px",   "badges"),
    ("r-sm",   "10px",  "buttons, fields"),
    ("r-md",   "14px",  "list rows, tiles"),
    ("r-lg",   "20px",  "cards, sheets"),
    ("r-xl",   "28px",  "swipe cards"),
    ("r-pill", "999px", "chips, nav, avatars"),
]

# Elevation cannot be one set of numbers across both modes. A shadow works by
# darkening the ground beneath it, and on a near-black ground there is nothing
# left to darken -- the light scale's 6% black is simply invisible there. The
# dark column therefore leans on deeper, wider shadows plus a hairline of lift,
# which is how depth reads when the ground is already at the bottom.
ELEVATION = [
    ("e1",      "0 1px 2px rgba(36,36,36,.06)",
                "0 1px 2px rgba(0,0,0,.5), 0 0 0 1px rgba(168,133,247,.10)", "rest"),
    ("e2",      "0 4px 12px rgba(36,36,36,.08)",
                "0 4px 14px rgba(0,0,0,.55), 0 0 0 1px rgba(168,133,247,.12)", "raised"),
    ("e3",      "0 8px 24px rgba(36,36,36,.10)",
                "0 10px 30px rgba(0,0,0,.6), 0 0 0 1px rgba(168,133,247,.14)", "overlay"),
    ("e-brand", "0 8px 20px rgba(109,83,244,.32)",
                "0 8px 26px rgba(138,43,226,.45)", "primary CTA, like, super-like only"),
    ("e-nav",   "0 8px 28px rgba(27,27,27,.24)",
                "0 8px 28px rgba(0,0,0,.65)", "floating tab bar"),
]

MOTION = [
    ("d-fast", "120ms", "press, ripple, chip toggle"),
    ("d-base", "200ms", "colour, opacity, focus ring"),
    ("d-slow", "280ms", "sheets, accordions, tab change"),
    ("d-page", "400ms", "screen transitions"),
    ("ease",   "cubic-bezier(.2,.8,.2,1)", "nothing snaps"),
]

SPACE = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16]

# ch.01's noise, at the guide's own settings.
NOISE = (
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence "
    "type='fractalNoise' baseFrequency='.9' numOctaves='3' stitchTiles='stitch'"
    "/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)'/%3E"
    "%3C/svg%3E\")"
)


def palette_block(mode):
    """Just the colours, for one mode. Index 3 is light, index 4 is dark."""
    i = 4 if mode == "dark" else 3
    return "\n".join("  --%s: %s;" % (row[0], row[i]) for row in PALETTE)


def elevation_block(mode):
    i = 2 if mode == "dark" else 1
    return "\n".join(
        "  --%s: %s;  /* %s */" % (row[0], row[i], row[3]) for row in ELEVATION)


def root_block():
    """The light world, plus everything that does not vary by mode.

    Radius, motion and space are the guide's structural scales -- they describe
    how big a corner is and how long a press takes, neither of which has a dark
    equivalent. Only colour and elevation are re-stated per mode.
    """
    lines = [palette_block("light"), ""]
    for name, value, use in RADIUS:
        lines.append("  --%s: %s;  /* %s */" % (name, value, use))
    lines.append("")
    lines.append(elevation_block("light"))
    lines.append("")
    for name, value, use in MOTION:
        lines.append("  --%s: %s;  /* %s */" % (name, value, use))
    lines.append("")
    for step in SPACE:
        lines.append("  --space-%d: %dpx;" % (step, step * 4))
    return "\n".join(lines)


def dark_block():
    """The dark world: the same names, re-answered.

    Scoped to an explicit `[data-mode="dark"]` stamp rather than to
    `prefers-color-scheme`, because this is a design tool -- the point is to
    look at either mode on demand, not to be handed whichever one the laptop
    happens to be set to.
    """
    return '[data-mode="dark"] {\n%s\n\n%s\n}' % (
        palette_block("dark"), elevation_block("dark"))


SCREEN_CSS = """
/* ====================================================================
   The screen: one 390x844 device, painted only from the tokens above.
   ==================================================================== */
.vl {
  --gutter: var(--space-5);          /* ch.04: fixed 20px, nothing but photography touches the edge */
  width: 390px; height: 844px;
  background: var(--canvas);
  color: var(--body);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 14px; line-height: 20px;      /* ch.03 Body */
  font-feature-settings: "cv05" 1;
  position: relative; overflow: hidden;
  display: flex; flex-direction: column;
  -webkit-font-smoothing: antialiased;
}
.vl *, .vl *::before, .vl *::after { box-sizing: border-box; }
.vl p, .vl h1, .vl h2, .vl h3, .vl figure { margin: 0; }

/* ---- ch.03 type scale ------------------------------------------- */
.vl .t-display { font-size: 28px; line-height: 34px; font-weight: 700; letter-spacing: -0.03em; color: var(--ink); }
.vl .t-h1      { font-size: 24px; line-height: 30px; font-weight: 700; letter-spacing: -0.02em; color: var(--ink); }
.vl .t-h2      { font-size: 20px; line-height: 26px; font-weight: 600; color: var(--ink); }
.vl .t-h3      { font-size: 17px; line-height: 24px; font-weight: 600; color: var(--ink); }
.vl .t-bodyl   { font-size: 15px; line-height: 22px; font-weight: 400; }
.vl .t-body    { font-size: 14px; line-height: 20px; font-weight: 400; }
.vl .t-caption { font-size: 12px; line-height: 16px; font-weight: 400; color: var(--quiet); }
.vl .t-over    { font-size: 11px; line-height: 14px; font-weight: 600; letter-spacing: 0.09em;
                 text-transform: uppercase; color: var(--quiet); }
/* ch.03: lead clause in the action colour, remainder in ink. One break, max. */
.vl .lead { color: var(--ink-accent); }
/* ch.03: body copy caps at 42ch -- break the paragraph rather than run wider. */
.vl .measure { max-width: 42ch; }
/* ch.03: pre-login screens centre; post-login left-align. */
.vl .pre-login { text-align: center; }
.vl .pre-login .measure { margin-left: auto; margin-right: auto; }

/* ---- ch.01 the velvet treatment --------------------------------- */
/* Large surfaces only. The gradient is the guide's own 148deg ramp; the noise
   sits over it at low opacity so the purple reads as pile rather than paint.
   --velvet-1 is the gradient-only vivid variant and must never be a solid. */
.vl .velvet {
  position: relative; isolation: isolate;
  background-image: linear-gradient(148deg,
      var(--velvet-1) 0%, var(--velvet-2) 46%, var(--velvet-3) 100%);
  color: #fff;
}
.vl .velvet::after {
  content: ""; position: absolute; inset: 0; z-index: -1;
  background-image: NOISE_URL;
  background-size: 140px 140px;
  opacity: 0.22; mix-blend-mode: overlay; border-radius: inherit;
  pointer-events: none;
}

/* ---- ch.05 buttons ----------------------------------------------- */
/* 52px for a full-width CTA, 44px minimum for anything tappable. Primary is
   a FLAT fill: at this size the velvet texture becomes dirt (ch.01). */
.vl .btn {
  display: inline-flex; align-items: center; justify-content: center; gap: var(--space-2);
  min-height: 44px; padding: 0 var(--space-5);
  border: 0; border-radius: var(--r-sm);
  font: inherit; font-size: 15px; line-height: 20px; font-weight: 600;  /* ch.03 Button */
  cursor: pointer; text-decoration: none;
  transition: transform var(--d-fast) var(--ease),
              background var(--d-base) var(--ease),
              box-shadow var(--d-base) var(--ease);
}
.vl .btn:active { transform: scale(.97); }         /* ch.05, 120ms */
.vl .btn-block  { display: flex; width: 100%; height: 52px; }
.vl .btn-primary   { background: var(--action); color: var(--on-action); box-shadow: var(--e-brand); }
.vl .btn-secondary { background: var(--surface); color: var(--ink); box-shadow: var(--e1); }
.vl .btn-quiet     { background: transparent; color: var(--body); box-shadow: none; }

/* ---- ch.05 cards ------------------------------------------------- */
/* ch.01 content over chrome: chrome sheds borders wherever a shadow will do,
   so a card is surface + elevation, never surface + hairline. */
.vl .card { background: var(--surface); border-radius: var(--r-lg); box-shadow: var(--e1); padding: var(--space-4); }
.vl .card-lg { padding: var(--space-5); }
.vl .row  { background: var(--surface); border-radius: var(--r-md); box-shadow: var(--e1); padding: var(--space-4); }

/* ---- ch.05 chips -------------------------------------------------- */
/* "Unselected chips sit on white with e1 -- no border. Selection is a fill
   change, never an outline." */
.vl .chip {
  display: inline-flex; align-items: center; gap: var(--space-1);
  min-height: 32px; padding: 0 14px;
  border: 0; border-radius: var(--r-pill);
  background: var(--surface); color: var(--body); box-shadow: var(--e1);
  font: inherit; font-size: 14px; font-weight: 500; cursor: pointer;
  transition: background var(--d-fast) var(--ease), color var(--d-fast) var(--ease);
}
.vl .chip svg { width: 16px; height: 16px; flex: none; }
.vl .chip.is-on { background: var(--action-wash); color: var(--ink-accent); box-shadow: none; }
/* Gold chips are for editorially featured interests only (ch.05). */
.vl .chip.is-featured { background: var(--delight); color: var(--on-delight); box-shadow: none; }
.vl .chipset { display: flex; flex-wrap: wrap; gap: var(--space-2); }

/* ---- fields (ch.05) ---------------------------------------------- */
.vl .field { background: var(--field); border: 0; border-radius: var(--r-sm);
             min-height: 44px; padding: 0 var(--space-4); width: 100%;
             font: inherit; color: var(--ink); }
.vl .field::placeholder { color: var(--quiet); }

/* ---- badges, live dot, progress ---------------------------------- */
.vl .badge { display: inline-flex; align-items: center; gap: 6px; border-radius: var(--r-xs);
             padding: 3px 8px; font-size: 11px; font-weight: 600; letter-spacing: .04em; }
.vl .live { display: inline-flex; align-items: center; gap: var(--space-2); }
.vl .live-dot { width: 7px; height: 7px; border-radius: var(--r-pill); background: var(--live);
                flex: none; box-shadow: 0 0 0 0 currentColor; }
.vl .bar { display: flex; gap: 4px; }
.vl .bar i { height: 3px; flex: 1; border-radius: var(--r-pill); background: var(--hairline); }
.vl .bar i.is-on { background: var(--action); }

/* ---- icons (ch.07) ------------------------------------------------ */
/* Outline, round caps and joins, 2px at a 24 canvas. The registry emits the
   stroke already scaled per canvas, so a 20-box glyph is not heavier. */
.vl svg { display: block; }
.vl .tap { min-width: 44px; min-height: 44px; display: inline-flex;
           align-items: center; justify-content: center; }

/* ---- mascots (ch.06) ---------------------------------------------- */
/* Never below 96px -- the velvet pile stops reading and turns to mush. */
.vl .mascot { height: 132px; width: auto; display: block; }
.vl .mascot-pair { display: flex; align-items: flex-end; justify-content: center; }
/* "They lean toward each other to form the V of Velvt." The art is shot
   standing, so the lean is ours. */
.vl .mascot-pair .mascot:first-child { transform: rotate(7deg);  transform-origin: bottom center; }
.vl .mascot-pair .mascot:last-child  { transform: rotate(-7deg); transform-origin: bottom center; }

/* ---- the shell ---------------------------------------------------- */
.vl-top { display: flex; align-items: center; justify-content: space-between;
          padding: var(--space-4) var(--gutter) var(--space-2); flex: none; gap: var(--space-2); }
.vl-word { font-size: 13px; font-weight: 700; letter-spacing: 0.22em; color: var(--ink); }
.vl-main { flex: 1 1 auto; min-height: 0; padding: 0 var(--gutter); display: flex; flex-direction: column; }
.vl-foot { flex: none; padding: var(--space-4) var(--gutter) var(--space-6); }
.vl .vl-scroll { overflow-y: auto; }
.vl-back { color: var(--body); flex: none; }
.vl-title { font-size: 15px; font-weight: 600; color: var(--ink); }

/* ---- the tab bar (ch.05) ------------------------------------------ */
/* A floating pill on its own shell colour, which is the one component the
   guide keeps dark in both modes -- it is chrome, and chrome that inverts
   with the ground stops reading as a fixed landmark. */
.vl-tabbar {
  flex: none; margin: var(--space-2) var(--gutter) var(--space-4);
  background: var(--nav-shell); border-radius: var(--r-pill); box-shadow: var(--e-nav);
  display: flex; align-items: center; justify-content: space-around;
  padding: var(--space-2) var(--space-3);
}
.vl-tabbar a { display: flex; flex-direction: column; align-items: center; gap: 2px;
               min-width: 44px; min-height: 44px; justify-content: center;
               color: var(--nav-rest); text-decoration: none; font-size: 10px; font-weight: 600; }
.vl-tabbar a.is-on { color: var(--nav-active); }
.vl-tabbar svg { width: 21px; height: 21px; }

/* ---- list rows and sections ---------------------------------------- */
.vl .stack { display: flex; flex-direction: column; gap: var(--space-3); }
.vl .stack-tight { display: flex; flex-direction: column; gap: var(--space-2); }
.vl .row-link { display: flex; align-items: center; gap: var(--space-3); text-decoration: none;
                color: inherit; }
.vl .row-main { flex: 1; min-width: 0; }
.vl .row-main strong { display: block; color: var(--ink); font-size: 15px; font-weight: 600; }
.vl .row-main span { display: block; color: var(--quiet); font-size: 13px;
                     overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vl .row-end { flex: none; color: var(--quiet); display: flex; align-items: center; gap: var(--space-2); }
.vl .avatar { width: 46px; height: 46px; border-radius: var(--r-pill); flex: none;
              background: var(--field); object-fit: cover; }
.vl .ph { background: var(--field); display: block; }
.vl .section-label { font-size: 11px; font-weight: 600; letter-spacing: .09em;
                     text-transform: uppercase; color: var(--quiet);
                     margin: var(--space-5) 0 var(--space-2); }
.vl .section-label:first-child { margin-top: 0; }

/* ---- tags (ch.05 badges) -------------------------------------------- */
.vl .tag { display: inline-flex; align-items: center; gap: 4px; border-radius: var(--r-xs);
           padding: 3px 7px; font-size: 10px; font-weight: 700; letter-spacing: .04em;
           text-transform: uppercase; background: var(--action-wash); color: var(--ink-accent); }
.vl .tag-gold { background: var(--delight); color: var(--on-delight); }
.vl .tag-quiet { background: var(--field); color: var(--quiet); }
.vl .tag-danger { background: var(--danger); color: var(--on-action); }

/* ---- switches (ch.05) ------------------------------------------------ */
/* Selection is a fill change, never an outline -- the same rule the chips
   follow, applied to the control that reads as its own object. */
.vl .switch { width: 44px; height: 26px; border-radius: var(--r-pill); background: var(--hairline);
              position: relative; flex: none; transition: background var(--d-base) var(--ease); }
.vl .switch::after { content: ""; position: absolute; top: 3px; left: 3px; width: 20px; height: 20px;
                     border-radius: var(--r-pill); background: var(--surface); box-shadow: var(--e1);
                     transition: transform var(--d-base) var(--ease); }
.vl .switch.is-on { background: var(--action); }
.vl .switch.is-on::after { transform: translateX(18px); }

/* ---- steps / progress ------------------------------------------------ */
.vl .steps { display: flex; gap: 4px; margin-bottom: var(--space-4); }
.vl .steps i { height: 3px; flex: 1; border-radius: var(--r-pill); background: var(--hairline); }
.vl .steps i.is-on { background: var(--action); }

/* ---- chat bubbles ---------------------------------------------------- */
.vl .log { display: flex; flex-direction: column; gap: var(--space-2); flex: 1;
           overflow-y: auto; padding: var(--space-3) 0; }
.vl .bubble { max-width: 78%; padding: 9px 13px; border-radius: var(--r-lg);
              font-size: 14px; line-height: 19px; }
.vl .bubble.them { align-self: flex-start; background: var(--surface); color: var(--ink);
                   box-shadow: var(--e1); border-bottom-left-radius: var(--r-xs); }
.vl .bubble.me { align-self: flex-end; background: var(--action); color: var(--on-action);
                 border-bottom-right-radius: var(--r-xs); }
.vl .composer { display: flex; gap: var(--space-2); align-items: center; }
.vl .composer .field { flex: 1; }
.vl .send { width: 44px; height: 44px; flex: none; border-radius: var(--r-pill);
            background: var(--action); color: var(--on-action); border: 0;
            display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }

/* ---- the timer strip ------------------------------------------------- */
.vl .strip { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3);
             background: var(--surface); border-radius: var(--r-md); box-shadow: var(--e1); }
.vl .strip-time { font-weight: 700; font-size: 17px; color: var(--ink);
                  font-variant-numeric: tabular-nums; flex: none; }

/* ---- prose (legal, faq, safety) -------------------------------------- */
.vl .prose h2 { font-size: 15px; font-weight: 600; color: var(--ink); margin: var(--space-5) 0 var(--space-1); }
.vl .prose h2:first-child { margin-top: 0; }
.vl .prose p { font-size: 14px; line-height: 21px; color: var(--body); margin-bottom: var(--space-3); }
.vl .qa { border-bottom: 1px solid var(--hairline); padding: var(--space-3) 0; }
.vl .qa:last-child { border-bottom: 0; }
.vl .qa summary { font-size: 14px; font-weight: 600; color: var(--ink); cursor: pointer;
                  list-style: none; display: flex; justify-content: space-between; gap: var(--space-3); }
.vl .qa summary::-webkit-details-marker { display: none; }
.vl .qa p { margin: var(--space-2) 0 0; font-size: 14px; line-height: 20px; color: var(--body); }

/* ---- forms ------------------------------------------------------------ */
.vl .form { display: flex; flex-direction: column; gap: var(--space-3); }
.vl .lbl { font-size: 12px; font-weight: 600; color: var(--quiet); display: block;
           margin-bottom: var(--space-1); }
.vl textarea.field { min-height: 84px; padding: var(--space-3) var(--space-4); line-height: 20px;
                     resize: none; font-family: inherit; }

/* ---- admin: denser, and unapologetically so --------------------------- */
.vl .adm-row { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) 0;
               border-bottom: 1px solid var(--hairline); }
.vl .adm-row:last-child { border-bottom: 0; }
.vl .adm-num { font-weight: 700; font-size: 20px; color: var(--ink); font-variant-numeric: tabular-nums; }
.vl .adm-stat { flex: 1; }
.vl .adm-stat span { display: block; font-size: 11px; color: var(--quiet); text-transform: uppercase;
                     letter-spacing: .08em; font-weight: 600; }

/* ---- error screens ----------------------------------------------------- */
.vl .mid { flex: 1; display: flex; flex-direction: column; align-items: center;
           justify-content: center; text-align: center; gap: var(--space-3); }
.vl .mid-badge { width: 64px; height: 64px; border-radius: var(--r-pill); background: var(--field);
                 color: var(--quiet); display: flex; align-items: center; justify-content: center; }
"""


def screen_css():
    return SCREEN_CSS.replace("NOISE_URL", NOISE)
