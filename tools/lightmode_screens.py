#!/usr/bin/env python3
"""The app's screens, drawn from the guide's elements.

Hand-authored rather than captured. The Restyler repaints screenshots of the
running app, which is why it needs an iframe per screen and a megabyte of
captured markup; these screens are written here, so they live directly in the
page and repaint from `document.documentElement.style.setProperty` with nothing
to isolate them from.
"""
import lightmode_assets as assets

_REG = assets.icons()
GLYPHS = _REG["glyphs"]
SLOTS = _REG["slots"]
STROKE = _REG["stroke"]
CAP = _REG["cap"]


def icon(slot, size=24, cls=""):
    """One glyph, at the guide's spec.

    ch.07 asks for 2px at a 24px canvas "scaling proportionally". Several
    glyphs are drawn on a 20 or 21 box, where a literal 2 would read heavier,
    so the stroke is written in the glyph's own units as 2 * box / 24 -- which
    lands at 2px on screen whatever size it is rendered at.
    """
    name = SLOTS.get(slot, slot)
    glyph = GLYPHS.get(name)
    if not glyph:
        return ""
    view_box, inner = glyph
    box = float(view_box.split(" ")[2])
    return (
        '<svg width="%d" height="%d" viewBox="%s" fill="none" '
        'stroke-width="%s" stroke-linecap="%s" stroke-linejoin="%s" '
        'aria-hidden="true" data-icon="%s"%s>%s</svg>'
        % (size, size, view_box, round(STROKE * box / 24.0, 2), CAP, CAP,
           name, ' class="%s"' % cls if cls else "", inner)
    )


def landing(brand):
    """Screen 1. Pre-login, so ch.03 centres the heading and body.

    Structurally this is the shipped landing, not a redesign of it: the hero
    film is the page's whole ground rather than an ornament in a corner, the
    still is that layer's own background so a reduced-motion visit downloads
    no video at all, and the wordmark is the real artwork used as a mask.

    What changes is the recolour, and it is not a palette swap. The dark
    landing lays a near-opaque --ink scrim over the film so pale type reads;
    here the type is dark, so the scrim has to lighten rather than darken. Same
    five stops, same job, inverted. It is strong where the type sits and gets
    out of the way across the middle, which is where the two of them meet.
    """
    return """
<div class="vl pre-login" data-screen="landing">
  <div class="film" aria-hidden="true">
    <video class="film-reel" autoplay muted loop playsinline
           poster="%(still)s"><source src="%(film)s" type="video/webm"></video>
  </div>

  <div class="vl-top">
    <span class="sr">Velvt</span>
    <span></span>
    <button class="btn btn-quiet t-caption lang">EN</button>
  </div>

  <div class="vl-main">
    <div class="logo" role="img" aria-label="Velvt"></div>

    <h1 class="t-display headline"><span class="lead">Two people,</span><br>
      five minutes,<br>one decision.</h1>
    <p class="t-bodyl measure sub">No endless swiping. Search when you're
      free, meet whoever is searching too.</p>

    <div class="grow"></div>

    <p class="live t-body"><i class="live-dot"></i>
      <span><b>7 people</b> searching right now</span></p>
  </div>

  <div class="vl-foot">
    <button class="btn btn-block btn-primary">Create an account</button>
    <button class="btn btn-block btn-secondary" style="margin-top:12px;">Sign in</button>
    <p class="t-caption fine">18+. Maastricht only, for now.</p>
  </div>
</div>""" % {"film": brand["film"], "still": brand["still"]}


def intro():
    """Screen 2: the "how a match works" explainer, ahead of a first search.

    Post-login, so ch.03 left-aligns it -- the one structural difference
    from the landing. Numbered steps here are a real sequence (reveal, then
    timed chat, then decide), which is what earns a 1/2/3 marker rather than
    decorating one on.
    """
    return """
<div class="vl" data-screen="intro">
  <div class="vl-top">
    <span class="vl-word">Velvt</span>
    <span></span><span></span>
  </div>
  <div class="vl-main vl-scroll">
    <p class="t-over">Before you start</p>
    <h1 class="t-h1">How a match<br>works here.</h1>
    <p class="t-body measure intro-lede">Velvt doesn't hand you a stack of
      profiles to swipe. You search, and you're paired the moment someone
      is looking for you too.</p>

    <ol class="intro-steps">
      <li><span class="intro-n">1</span>
        <div><h2 class="t-h3">You both get 20 seconds</h2>
          <p class="t-body">When you're paired, a card tells you who it is
            and what you have in common. Photos stay hidden for now.</p></div></li>
      <li><span class="intro-n">2</span>
        <div><h2 class="t-h3">Then 5 minutes to talk</h2>
          <p class="t-body">A real conversation on a clock. Long enough to
            find out whether there's anything there, short enough that
            neither of you is stuck being polite.</p></div></li>
      <li><span class="intro-n">3</span>
        <div><h2 class="t-h3">You both decide</h2>
          <p class="t-body">Go on, and the chat stays open and photos
            unlock. Either of you says no, and it ends there.</p></div></li>
    </ol>
  </div>
  <div class="vl-foot">
    <button class="btn btn-block btn-primary">Got it &mdash; start searching</button>
  </div>
</div>"""


def match_reveal():
    """Screen 3: the 20s reveal. The moment a search resolves into a person.

    ch.06's mascot pair would stand in for the two profile photos here --
    they're still locked at this phase -- but the pair needs the design
    guide's own art (see lightmode_assets.mascots) and isn't wired in yet,
    so this draws the app's own hatched stand-ins instead.
    """
    return """
<div class="vl" data-screen="reveal">
  <div class="vl-top">
    <span class="vl-word">Velvt</span>
    <span></span><span></span>
  </div>
  <div class="vl-main vl-scroll pre-login">
    <p class="t-over">Match found</p>
    <div class="pair"><span class="ph"></span><span class="ph"></span></div>
    <h1 class="t-h1">You matched with<br>Sanne, 27</h1>
    <p class="t-body measure">You were both looking for each other. Photos
      unlock once you both continue.</p>
    <p class="t-body live"><i class="live-dot"></i><span>Sanne is already in the room</span></p>

    <p class="t-over reveal-label">You both said</p>
    <div class="chipset reveal-chips">
      <span class="chip is-on">Live music</span>
      <span class="chip is-on">Hiking</span>
      <span class="chip">Long-term relationship</span>
    </div>
    <p class="t-caption">Ask her about <b>live music</b>.</p>

    <div class="ring" style="--deg: 252deg;">
      <div class="ring-inner">
        <span class="ring-num">14</span>
        <span class="ring-unit">seconds</span>
      </div>
    </div>
    <p class="t-caption">Say yes to start now &mdash; or wait, and the chat opens on its own.</p>
  </div>
  <div class="vl-foot reveal-foot">
    <button class="btn btn-quiet reveal-no">Not this one</button>
    <button class="btn btn-primary reveal-yes">Yes, start chatting</button>
  </div>
</div>"""


def chats_empty():
    """Screen 4: the chats list with nothing in it yet.

    An empty state earns exactly one thing to do next, stated once -- not a
    dead end and not a second competing CTA alongside the tab bar's own
    search icon.
    """
    return """
<div class="vl" data-screen="empty">
  <div class="vl-top">
    <span class="vl-word">Velvt</span>
    <span></span><span></span>
  </div>
  <div class="vl-main empty-main">
    <div class="empty-badge">%(icon)s</div>
    <h1 class="t-h2">No chats yet</h1>
    <p class="t-body measure">Start a search and we'll pair you the moment
      someone is looking for you too.</p>
    <button class="btn btn-primary empty-cta">Start a search</button>
  </div>
</div>""" % {"icon": icon("tab.chats", size=28)}


LANDING_CSS = """
/* ---- landing ------------------------------------------------------ */
/* The film is the ground, so it covers every pixel and the scrim can be a
   plain overlay: with no band edge there is no seam to give away. */
.vl .film {
  position: absolute; inset: 0; z-index: 0; overflow: hidden; pointer-events: none;
  background: var(--film-still) 50% 16% / cover no-repeat;
}
.vl .film-reel {
  width: 100%; height: 100%; display: block;
  /* The shot pushes in as they come together, so it rests on a head-and-
     shoulders embrace: anchoring near the top keeps both faces on screen,
     biased down a little so the earlier full-body run still has its feet. */
  object-fit: cover; object-position: 50% 16%;
}
/* The recolour that matters. The dark landing darkens the film so pale type
   reads over it; the light one lightens it so dark type does. Strong top and
   bottom where the wordmark, the headline and the buttons sit, and nearly
   absent across the middle third, which is where the two of them meet. */
.vl .film::after {
  content: ""; position: absolute; inset: 0;
  background: linear-gradient(180deg,
    rgba(244,243,240,0.95) 0%,
    rgba(244,243,240,0.90) 30%,
    rgba(244,243,240,0.62) 52%,
    rgba(244,243,240,0.86) 76%,
    rgba(244,243,240,0.96) 100%);
}
.vl-top, .vl-main, .vl-foot { position: relative; z-index: 1; }

/* The wordmark is artwork, not a typeface: the mask keeps the letterforms
   exactly as drawn and the fill stays ours, so a palette change reaches it.
   Three stops and an over-wide background so the sheen can sweep across. */
.vl .logo {
  width: min(80%, 270px); aspect-ratio: 753 / 391;
  max-height: 132px; margin: var(--space-2) auto var(--space-5); flex: 0 1 auto; min-height: 0;
  background: linear-gradient(115deg, var(--action), var(--velvet-2) 45%, var(--action) 90%);
  background-size: 260% 100%;
  -webkit-mask: var(--logo-art) center / contain no-repeat;
  mask: var(--logo-art) center / contain no-repeat;
  animation: sheen 7s ease-in-out infinite;
}
@keyframes sheen { 0%, 100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }
@media (prefers-reduced-motion: reduce) {
  .vl .logo { animation: none; background-position: 25% 50%; }
}

.vl .lang { min-width: 44px; min-height: 44px; padding: 0 var(--space-2); }  /* ch.05 tap target */
.vl .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
.vl .headline { margin-bottom: var(--space-4); }
.vl .sub { color: var(--body); }
.vl .grow { flex: 1 1 auto; min-height: var(--space-6); }
.vl .live { justify-content: center; color: var(--body); }
.vl .live b { font-weight: 600; color: var(--ink); }   /* ch.03: step through 600 */
.vl .fine { margin-top: var(--space-4); }

/* ---- shared: scrolling body, post-login shell ---------------------- */
/* Only .vl-main scrolls -- the wordmark row and the foot button stay put,
   same rule the app's own .wiz-fit/.wiz-scroll split follows. */
.vl .vl-scroll { overflow-y: auto; }
.vl .vl-word { flex: none; }

/* ---- intro (ch.05 numbered list -- a real sequence, so it earns 1/2/3) */
.vl .intro-lede { color: var(--body); margin: var(--space-3) 0 var(--space-6); }
.vl .intro-steps { list-style: none; margin: 0 0 var(--space-4); padding: 0;
                    display: flex; flex-direction: column; gap: var(--space-5); }
.vl .intro-steps li { display: flex; gap: var(--space-4); align-items: flex-start; }
.vl .intro-n { flex: none; width: 28px; height: 28px; border-radius: var(--r-pill);
               background: var(--action-wash); color: var(--ink-accent);
               display: inline-flex; align-items: center; justify-content: center;
               font-size: 13px; font-weight: 700; font-family: var(--code, inherit); }
.vl .intro-steps h2 { margin-bottom: 2px; }
.vl .intro-steps p { color: var(--body); }

/* ---- match reveal --------------------------------------------------- */
.vl .pair { display: flex; align-items: center; justify-content: center; margin: var(--space-5) 0; }
.vl .pair .ph { width: 92px; height: 92px; border-radius: var(--r-pill); flex: none;
                background: var(--field); box-shadow: 0 0 0 3px var(--surface), var(--e2); }
.vl .pair .ph + .ph { margin-left: -20px; }
.vl .reveal-label { margin-top: var(--space-5); }
.vl .reveal-chips { margin: var(--space-2) 0 var(--space-3); }
.vl .ring { position: relative; flex: none; width: 96px; height: 96px; border-radius: var(--r-pill);
            margin: var(--space-6) auto var(--space-3);
            background: conic-gradient(var(--action) 0deg var(--deg, 0deg), var(--hairline) var(--deg, 0deg) 360deg); }
.vl .ring::after { content: ""; position: absolute; inset: 7px; border-radius: var(--r-pill); background: var(--surface); }
.vl .ring-inner { position: absolute; inset: 0; z-index: 1; display: flex; flex-direction: column;
                   align-items: center; justify-content: center; gap: 1px; }
.vl .ring-num { font-weight: 700; font-size: 26px; line-height: 1; color: var(--ink); font-variant-numeric: tabular-nums; }
.vl .ring-unit { font-weight: 600; font-size: 9px; letter-spacing: .12em; text-transform: uppercase; color: var(--quiet); }
.vl .reveal-foot { display: flex; gap: var(--space-3); }
.vl .reveal-no { flex: 1; }
.vl .reveal-yes { flex: 2; }

/* ---- chats empty ----------------------------------------------------- */
.vl .empty-main { display: flex; flex-direction: column; align-items: center; justify-content: center;
                   text-align: center; gap: var(--space-3); flex: 1; }
.vl .empty-badge { width: 64px; height: 64px; border-radius: var(--r-pill); background: var(--field);
                    color: var(--quiet); display: flex; align-items: center; justify-content: center;
                    margin-bottom: var(--space-2); }
.vl .empty-cta { margin-top: var(--space-3); }
"""
