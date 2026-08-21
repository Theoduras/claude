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
        'aria-hidden="true"%s>%s</svg>'
        % (size, size, view_box, round(STROKE * box / 24.0, 2), CAP, CAP,
           ' class="%s"' % cls if cls else "", inner)
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
"""
