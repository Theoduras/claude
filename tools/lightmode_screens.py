#!/usr/bin/env python3
"""Every screen in the app, drawn from the guide's elements.

Hand-authored rather than captured. The Restyler repaints screenshots of the
running app, which is why it needs an iframe per screen and a megabyte of
captured markup; these screens are written here, so they live directly in the
page and repaint from `document.documentElement.style.setProperty` with nothing
to isolate them from.

The copy is the app's own -- lifted from `translations.py` and the templates --
rather than invented, so a decision made here is a decision about the product
that exists. Where a screen shows data, the data is the seed set's shape: one
city, demo-sized counts, Dutch names.

SCREENS at the foot is the running order and the section grouping; adding a
screen is a function plus a line there, and the artifact's tab rail, the
inspector and both palettes pick it up with no other change.
"""
import lightmode_assets as assets

_REG = assets.icons()
GLYPHS = dict(_REG["glyphs"])
SLOTS = dict(_REG["slots"])
STROKE = _REG["stroke"]
CAP = _REG["cap"]

# Marks these screens need that the app's registry does not have yet. Drawn to
# ch.07's own spec (24 box, 2px, round caps and joins) so they sit with the
# rest, and kept in a separate dict rather than merged silently: EXTRA is what
# adopting these screens would cost `templates/_icons.html`, and a design tool
# that quietly invents glyphs is how an icon set stops being a set.
#
# The alternative was worse. `icon()` returns "" for a slot it cannot resolve,
# so a mistyped or missing name draws nothing at all -- a tick that is simply
# absent reads as an unselected row, not as a bug.
def _g(d):
    """One glyph on the 24 canvas, stroked in currentColor.

    Every path below is written without its own stroke-width or caps: `icon()`
    emits those on the <svg> from ch.07's spec and they inherit, which is the
    same arrangement the app's registry uses and the reason a weight change is
    one edit rather than sixty.
    """
    return ["0 0 24 24", "".join(
        '<path d="%s" stroke="currentColor"/>' % p if not p.startswith("<") else p
        for p in d)]


EXTRA = {
    # -- the six the screens themselves needed --------------------------
    "check":   _g(["M20 6 9 17l-5-5"]),
    "send":    _g(["M4 12 20 4l-8 16-2-6-6-2Z"]),
    "more":    _g(['<circle cx="12" cy="5" r="1.4" fill="currentColor" stroke="none"/>'
                   '<circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/>'
                   '<circle cx="12" cy="19" r="1.4" fill="currentColor" stroke="none"/>']),
    "plus":    _g(["M12 5v14M5 12h14"]),
    "clock":   _g(['<circle cx="12" cy="12" r="8.5" stroke="currentColor"/>', "M12 7.5V12l3 2"]),
    "shield":  _g(["M12 3.5 19 6v5.5c0 4.2-2.9 7.5-7 9-4.1-1.5-7-4.8-7-9V6l7-2.5Z"]),

    # -- a working set, so the picker is a library rather than a sample --
    # Chosen for what an app of this shape actually needs a mark for, not to
    # pad a grid: every one of these has a place it would plausibly go.
    "search":     _g(['<circle cx="11" cy="11" r="6.5" stroke="currentColor"/>', "M15.8 15.8 20 20"]),
    "x":          _g(["M6 6l12 12M18 6 6 18"]),
    "menu":       _g(["M4 7h16M4 12h16M4 17h16"]),
    "settings":   _g(['<circle cx="12" cy="12" r="3" stroke="currentColor"/>',
                      "M12 3v2.2M12 18.8V21M3 12h2.2M18.8 12H21"
                      "M5.6 5.6l1.6 1.6M16.8 16.8l1.6 1.6M18.4 5.6l-1.6 1.6M7.2 16.8l-1.6 1.6"]),
    "bell":       _g(["M18 15V10a6 6 0 1 0-12 0v5l-1.6 2.5h15.2L18 15Z", "M10 20a2 2 0 0 0 4 0"]),
    "camera":     _g(["M3 8.5h3.4L8 6h8l1.6 2.5H21v11H3v-11Z",
                      '<circle cx="12" cy="13.5" r="3.6" stroke="currentColor"/>']),
    "image":      _g(["M3.5 4.5h17v15h-17z", "m3.5 16 5-5 4.5 4.5L16.5 12l4 4",
                      '<circle cx="9" cy="9" r="1.4" stroke="currentColor"/>']),
    "trash":      _g(["M4.5 6.5h15", "M9 6.5V4h6v2.5", "M6.5 6.5 7.6 21h8.8l1.1-14.5",
                      "M10.5 10.5v6M13.5 10.5v6"]),
    "edit":       _g(["M4 20h4L20 8l-4-4L4 16v4Z", "M14.5 5.5 18.5 9.5"]),
    "filter":     _g(["M3.5 5.5h17l-6.7 8v6l-3.6-2v-4L3.5 5.5Z"]),
    "share":      _g(['<circle cx="18" cy="6" r="2.6" stroke="currentColor"/>',
                      '<circle cx="6" cy="12" r="2.6" stroke="currentColor"/>',
                      '<circle cx="18" cy="18" r="2.6" stroke="currentColor"/>',
                      "M8.3 10.8 15.7 7.2M8.3 13.2l7.4 3.6"]),
    "download":   _g(["M12 4v11", "m7.5 10.5 4.5 4.5 4.5-4.5", "M4.5 19.5h15"]),
    "upload":     _g(["M12 20V9", "m7.5 13.5 4.5-4.5 4.5 4.5", "M4.5 4.5h15"]),
    "lock":       _g(["M5.5 10.5h13v10h-13z", "M8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3"]),
    "unlock":     _g(["M5.5 10.5h13v10h-13z", "M8.5 10.5V7.5a3.5 3.5 0 0 1 6.6-1.7"]),
    "mail":       _g(["M3.5 5.5h17v13h-17z", "m3.5 6.5 8.5 6.5 8.5-6.5"]),
    "phone":      _g(["M7.5 3.5h9v17h-9z", "M10.5 17.5h3"]),
    "calendar":   _g(["M3.5 6.5h17v14h-17z", "M3.5 10.5h17", "M8 4v4M16 4v4"]),
    "map":        _g(["m3.5 6.5 5.5-2.5 6 2.5 5.5-2.5v13l-5.5 2.5-6-2.5-5.5 2.5v-13Z",
                      "M9 4v13M15 6.5v13"]),
    "globe":      _g(['<circle cx="12" cy="12" r="8.5" stroke="currentColor"/>',
                      "M3.5 12h17", "M12 3.5c2.4 2.6 3.6 5.4 3.6 8.5s-1.2 5.9-3.6 8.5"
                      "c-2.4-2.6-3.6-5.4-3.6-8.5S9.6 6.1 12 3.5Z"]),
    "user":       _g(['<circle cx="12" cy="8.5" r="3.8" stroke="currentColor"/>',
                      "M4.8 20.5a7.4 7.4 0 0 1 14.4 0"]),
    "users":      _g(['<circle cx="9.5" cy="8.5" r="3.4" stroke="currentColor"/>',
                      "M3 20.5a6.7 6.7 0 0 1 13 0", "M16 5.6a3.4 3.4 0 0 1 0 5.8",
                      "M17.5 14.4a6.7 6.7 0 0 1 3.5 6.1"]),
    "minus":      _g(["M5 12h14"]),
    "arrow-up":   _g(["M12 20V4", "m5.5 10.5 6.5-6.5 6.5 6.5"]),
    "arrow-down": _g(["M12 4v16", "m5.5 13.5 6.5 6.5 6.5-6.5"]),
    "arrow-left": _g(["M20 12H4", "m10.5 5.5-6.5 6.5 6.5 6.5"]),
    "arrow-right": _g(["M4 12h16", "m13.5 5.5 6.5 6.5-6.5 6.5"]),
    "chevron-up": _g(["m5.5 15 6.5-6.5 6.5 6.5"]),
    "chevron-down": _g(["m5.5 9 6.5 6.5L18.5 9"]),
    "refresh":    _g(["M20 12a8 8 0 1 1-2.6-5.9", "M20 4v5h-5"]),
    "external":   _g(["M18 13.5v6h-13v-13h6", "M13 4h7v7", "M20 4l-8.5 8.5"]),
    "bookmark":   _g(["M6.5 3.5h11v17l-5.5-4-5.5 4v-17Z"]),
    "flag":       _g(["M6 21V4", "M6 4.5h12l-2.5 4 2.5 4H6"]),
    "sparkle":    _g(["M12 3.5 13.9 9.6 20 11.5l-6.1 1.9L12 19.5l-1.9-6.1L4 11.5l6.1-1.9L12 3.5Z"]),
    "moon":       _g(["M20 14.2A8.5 8.5 0 0 1 9.8 4 8.5 8.5 0 1 0 20 14.2Z"]),
    "sun":        _g(['<circle cx="12" cy="12" r="4" stroke="currentColor"/>',
                      "M12 2.5v2.6M12 18.9v2.6M2.5 12h2.6M18.9 12h2.6"
                      "M5.4 5.4 7.2 7.2M16.8 16.8l1.8 1.8M18.6 5.4l-1.8 1.8M7.2 16.8l-1.8 1.8"]),
    "play":       _g(["M7.5 4.5 19 12 7.5 19.5v-15Z"]),
    "pause":      _g(["M9 5v14M15 5v14"]),
    "eye-off":    _g(["M4 12s3.2-5.5 8-5.5c1.4 0 2.7.5 3.8 1.2M20 12s-3.2 5.5-8 5.5"
                      "c-1.5 0-2.8-.5-3.9-1.3", "M4 4l16 16",
                      '<circle cx="12" cy="12" r="2.6" stroke="currentColor"/>']),
    "info":       _g(['<circle cx="12" cy="12" r="8.5" stroke="currentColor"/>',
                      "M12 11v6", '<circle cx="12" cy="7.8" r="1" fill="currentColor" stroke="none"/>']),
    "warning":    _g(["M12 4 21 20H3L12 4Z", "M12 10v4.5",
                      '<circle cx="12" cy="17.4" r="1" fill="currentColor" stroke="none"/>']),
    "bolt":       _g(["M13.5 3 5 13.5h6L10.5 21 19 10.5h-6L13.5 3Z"]),
    "gift":       _g(["M3.5 8.5h17v4h-17z", "M5 12.5h14v8H5z", "M12 8.5v12",
                      "M12 8.5C10.5 5 8.5 4 7.3 4.8 6 5.7 6.8 8 12 8.5Z",
                      "M12 8.5c1.5-3.5 3.5-4.5 4.7-3.7C18 5.7 17.2 8 12 8.5Z"]),
    "coffee":     _g(["M4.5 5.5h12v8a5 5 0 0 1-10 0v-8Z", "M16.5 7.5h2.5a2.5 2.5 0 0 1 0 5h-2.5",
                      "M4 20.5h13"]),
    "music":      _g(['<circle cx="7" cy="17.5" r="2.8" stroke="currentColor"/>',
                      '<circle cx="18" cy="15.5" r="2.8" stroke="currentColor"/>',
                      "M9.8 17.5V6l11-2v11.5"]),
    "chat":       _g(["M4 5h16v11H9l-5 4V5Z"]),
    "grid":       _g(["M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"]),
    "list":       _g(["M8 6.5h12M8 12h12M8 17.5h12",
                      '<circle cx="4.4" cy="6.5" r="1" fill="currentColor" stroke="none"/>'
                      '<circle cx="4.4" cy="12" r="1" fill="currentColor" stroke="none"/>'
                      '<circle cx="4.4" cy="17.5" r="1" fill="currentColor" stroke="none"/>']),
}
GLYPHS.update(EXTRA)
SLOTS.update({
    "nav.back": "chevron-left",
    "nav.forward": "chevron-right",
    "nav.more": "more",
    "card.check": "check",
    "card.location": "pin",
    "card.age": "id-card",
    "chat.send": "send",
    "photo.add": "plus",
    "state.clock": "clock",
    "state.shield": "shield",
})


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


def tabbar(active="search"):
    """ch.05's floating bar. Four destinations, the active one in full white.

    Drawn from SLOTS like everything else, so changing which mark the search
    tab uses stays one line in the app's registry rather than an edit here.
    """
    items = [("search", "Search"), ("chats", "Chats"), ("you", "You"), ("info", "Info")]
    return '<nav class="vl-tabbar">%s</nav>' % "".join(
        '<a href="#"%s>%s<span>%s</span></a>'
        % (' class="is-on"' if key == active else "", icon("tab." + key, 21), label)
        for key, label in items)


def _head(title="", back=False, action=""):
    """The pinned top row: three slots, and the middle one is the brand.

    The wordmark here is the logo artwork, not the letters typed out -- the
    same `velvt-logo.svg` mask the landing uses, so the letterforms stay as
    drawn and a palette change still reaches the fill. Set in type it was a
    second, worse drawing of a mark we already own.

    The row is a grid of `1fr auto 1fr` rather than a flex with
    space-between, because centred has to mean centred: with a back arrow on
    one side and nothing on the other, space-between pushes the middle slot
    off-axis by half the arrow, and the mark visibly fails to line up with the
    headline under it. Equal-weight side columns hold the centre wherever the
    edges land.

    A screen deep enough to have a title puts that in the middle instead --
    on a detail view, what you are looking at outranks whose app it is.
    """
    left = ('<button class="btn btn-quiet tap vl-back">%s</button>' % icon("nav.back", 22)
            if back else "")
    middle = ('<span class="vl-title">%s</span>' % title if title
              else '<span class="vl-logo brand-fill" role="img" aria-label="Velvt"></span>')
    return ('<div class="vl-top"><span class="vl-slot">%s</span>%s'
            '<span class="vl-slot vl-slot-end">%s</span></div>'
            % (left, middle, action))


# ======================================================================
# Pre-login
# ======================================================================

def landing(brand):
    """Pre-login, so ch.03 centres the heading and body.

    Structurally this is the shipped landing, not a redesign of it: the hero
    film is the page's whole ground rather than an ornament in a corner, the
    still is that layer's own background so a reduced-motion visit downloads
    no video at all, and the wordmark is the real artwork used as a mask.

    What changes with the mode is the scrim, and it is not a palette swap. The
    scrim exists so type reads over the film: under dark type it lightens,
    under pale type it darkens. Same five stops, same job, inverted -- which is
    why `--scrim` is a token and the stops are built from it rather than
    written as literals.
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
    <div class="logo brand-fill" role="img" aria-label="Velvt"></div>

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


def age_gate():
    """The gate, stated once and without a dark pattern.

    One honest question and one honest way out. The "no" is a real button at
    the same weight as the yes, not a link hidden in the fine print -- an age
    gate whose refusal is hard to find is not a gate.
    """
    return """
<div class="vl pre-login" data-screen="age_gate">
  %(head)s
  <div class="vl-main mid">
    <div class="mid-badge">%(icon)s</div>
    <h1 class="t-h1">Are you 18 or over?</h1>
    <p class="t-body measure">Velvt is for adults. We ask once, and we ask
      plainly.</p>
  </div>
  <div class="vl-foot">
    <button class="btn btn-block btn-primary">Yes, I'm 18 or over</button>
    <button class="btn btn-block btn-secondary" style="margin-top:12px;">No, take me back</button>
  </div>
</div>""" % {"head": _head(), "icon": icon("card.age", 28)}


def register():
    """Account creation. Three fields and the consent, nothing else.

    The legal acceptance is a checkbox with the links live in it, not a
    pre-ticked box and not an "by continuing you agree" line -- consent that
    was never given cannot be recorded, and `legal_acceptances` records it.
    """
    return """
<div class="vl" data-screen="register">
  %(head)s
  <div class="vl-main vl-scroll">
    <h1 class="t-h1">Create your account</h1>
    <p class="t-body measure" style="margin-bottom:20px;">Maastricht only, for
      now. You can delete it whenever you like.</p>

    <div class="form">
      <div><label class="lbl">Email</label>
        <input class="field" type="email" value="sanne@example.nl"></div>
      <div><label class="lbl">Password</label>
        <input class="field" type="password" value="............"></div>
      <div><label class="lbl">Date of birth</label>
        <input class="field" type="text" value="14 / 03 / 1998"></div>

      <label class="consent">
        <span class="switch is-on"></span>
        <span class="t-caption">I'm 18 or over and I accept the
          <b>Terms</b> and the <b>Privacy notice</b>.</span>
      </label>
    </div>
  </div>
  <div class="vl-foot">
    <button class="btn btn-block btn-primary">Create account</button>
    <p class="t-caption fine">Already have one? <b>Sign in</b></p>
  </div>
</div>""" % {"head": _head(back=True, title="Register")}


def login():
    return """
<div class="vl" data-screen="login">
  %(head)s
  <div class="vl-main vl-scroll">
    <h1 class="t-h1">Welcome back</h1>
    <p class="t-body measure" style="margin-bottom:20px;">Sign in and start
      searching whenever you're free.</p>
    <div class="form">
      <div><label class="lbl">Email</label>
        <input class="field" type="email" value="sanne@example.nl"></div>
      <div><label class="lbl">Password</label>
        <input class="field" type="password" value="............"></div>
      <p class="t-caption"><b>Forgot your password?</b></p>
    </div>
  </div>
  <div class="vl-foot">
    <button class="btn btn-block btn-primary">Sign in</button>
    <p class="t-caption fine">New here? <b>Create an account</b></p>
  </div>
</div>""" % {"head": _head(back=True, title="Sign in")}


def forgot():
    """One field, and a reply that does not confirm whether the address exists.

    The message is the same either way on purpose: telling a stranger which
    addresses are registered turns a reset form into an account enumerator.
    """
    return """
<div class="vl" data-screen="forgot">
  %(head)s
  <div class="vl-main vl-scroll">
    <h1 class="t-h1">Reset your password</h1>
    <p class="t-body measure" style="margin-bottom:20px;">Give us the address
      you signed up with and we'll send a link.</p>
    <div class="form">
      <div><label class="lbl">Email</label>
        <input class="field" type="email" value="sanne@example.nl"></div>
    </div>
    <div class="card" style="margin-top:20px;">
      <p class="t-body">If that address has an account, a reset link is on its
        way. The link works once and expires in an hour.</p>
    </div>
  </div>
  <div class="vl-foot">
    <button class="btn btn-block btn-primary">Send the link</button>
  </div>
</div>""" % {"head": _head(back=True, title="Forgot")}


def reset():
    return """
<div class="vl" data-screen="reset">
  %(head)s
  <div class="vl-main vl-scroll">
    <h1 class="t-h1">Choose a new password</h1>
    <p class="t-body measure" style="margin-bottom:20px;">Setting it signs you
      out everywhere else.</p>
    <div class="form">
      <div><label class="lbl">New password</label>
        <input class="field" type="password" value="............"></div>
      <div><label class="lbl">Again</label>
        <input class="field" type="password" value="............"></div>
    </div>
  </div>
  <div class="vl-foot">
    <button class="btn btn-block btn-primary">Set password</button>
  </div>
</div>""" % {"head": _head(back=True, title="Reset")}


# ======================================================================
# Onboarding and search
# ======================================================================

def intro():
    """The explainer, ahead of a first search.

    Post-login, so ch.03 left-aligns it -- the one structural difference from
    the landing. Numbered steps here are a real sequence (reveal, then timed
    chat, then decide), which is what earns a 1/2/3 marker rather than
    decorating one on.
    """
    return """
<div class="vl" data-screen="intro">
  %(head)s
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
</div>""" % {"head": _head()}


def search_start():
    """Step 1 of two: what kind of connection.

    A checkbox group, not a radio -- someone can want more than one kind at
    once, which is why `searches.relationship_type` is a CSV. The city is
    stated rather than asked: SINGLE_CITY pins it server-side and a control
    that cannot change anything is worse than no control.
    """
    return """
<div class="vl" data-screen="search_start">
  %(head)s
  <div class="vl-main vl-scroll">
    <div class="steps"><i class="is-on"></i><i></i><i></i><i></i><i></i></div>
    <p class="t-over">Step 1 of 5</p>
    <h1 class="t-h1">What are you<br>looking for?</h1>
    <p class="t-body measure" style="margin-bottom:20px;">Pick as many as you
      mean. We'll only pair you with someone who wants one of the same.</p>

    <div class="stack-tight">
      <button class="row row-link is-on"><span class="row-main"><strong>Long-term relationship</strong></span>
        <span class="row-end">%(tick)s</span></button>
      <button class="row row-link is-on"><span class="row-main"><strong>Something casual</strong></span>
        <span class="row-end">%(tick)s</span></button>
      <button class="row row-link"><span class="row-main"><strong>New friends</strong></span></button>
      <button class="row row-link"><span class="row-main"><strong>Not sure yet</strong></span></button>
    </div>

    <p class="t-caption" style="margin-top:20px;">%(pin)s Maastricht &mdash;
      everyone on Velvt is here.</p>
  </div>
  <div class="vl-foot">
    <button class="btn btn-block btn-primary">Next</button>
  </div>
</div>""" % {"head": _head(back=True, title="Search"),
             "tick": icon("card.check", 20), "pin": icon("card.location", 14)}


def search_criteria():
    """Step 2: which filters matter, as switches.

    Each switch writes a `use_*` column, and a switch that is off leaves its
    panel's inputs disabled so those fields never reach the server at all. The
    live count under the heading is a real `searches_compatible()` figure, not
    an estimate -- which is what lets the screen offer to loosen something the
    moment it reaches zero.
    """
    return """
<div class="vl" data-screen="search_criteria">
  %(head)s
  <div class="vl-main vl-scroll">
    <div class="steps"><i class="is-on"></i><i class="is-on"></i><i></i><i></i><i></i></div>
    <p class="t-over">Step 2 of 5</p>
    <h1 class="t-h1">What matters<br>to you?</h1>
    <p class="t-body measure" style="margin-bottom:16px;"><b class="lead">12
      people</b> fit what you've asked for so far.</p>

    <div class="stack-tight">
      <div class="row row-link"><span class="row-main"><strong>Gender</strong>
        <span>Women</span></span><span class="switch is-on"></span></div>
      <div class="row row-link"><span class="row-main"><strong>Age</strong>
        <span>24 to 34</span></span><span class="switch is-on"></span></div>
      <div class="row row-link"><span class="row-main"><strong>Body type</strong>
        <span>No preference</span></span><span class="switch"></span></div>
      <div class="row row-link"><span class="row-main"><strong>Interests</strong>
        <span>Live music, hiking</span></span><span class="switch is-on"></span></div>
    </div>

    <p class="section-label">Interests</p>
    <div class="chipset">
      <span class="chip is-on">Live music</span>
      <span class="chip is-on">Hiking</span>
      <span class="chip">Cooking</span>
      <span class="chip">Cinema</span>
      <span class="chip">Running</span>
    </div>
  </div>
  <div class="vl-foot">
    <button class="btn btn-block btn-primary">Start searching</button>
  </div>
</div>""" % {"head": _head(back=True, title="What matters")}


def search_waiting():
    """The waiting screen: the pool, restated as chips you can edit in place.

    The animation is hand-rolled CSS rather than a Lottie -- the dotLottie
    player was fetched from a CDN the app's own CSP forbids, so it never ran in
    production, and vendoring a 250KB renderer onto the lightest screen in the
    app was the wrong trade.

    Each chip is priced with a real compatibility count, and the "loosen one
    thing" offer appears only when nothing fits -- never alongside a non-zero
    number, which would be asking someone to widen a search that is working.
    """
    return """
<div class="vl pre-login" data-screen="search_waiting">
  %(head)s
  <div class="vl-main vl-scroll">
    <div class="pulse" aria-hidden="true"><span></span><span></span><span></span></div>
    <h1 class="t-h2">Looking for someone<br>looking for you</h1>
    <p class="t-body measure">We'll pair you the moment it's mutual. You can
      close this &mdash; we'll hold your place while the tab is open.</p>

    <p class="section-label">You're searching for</p>
    <div class="chipset" style="justify-content:center;">
      <span class="chip">Women, 24&ndash;34</span>
      <span class="chip">Long-term relationship</span>
      <span class="chip">Something casual</span>
      <span class="chip">Live music</span>
    </div>
    <p class="t-caption" style="margin-top:12px;">Tap a chip to change it.</p>
  </div>
  <div class="vl-foot">
    <button class="btn btn-block btn-secondary">Stop searching</button>
  </div>
</div>""" % {"head": _head()}


# ======================================================================
# The match lifecycle
# ======================================================================

def match_reveal():
    """The 20s reveal. The moment a search resolves into a person.

    ch.06's mascot pair would stand in for the two profile photos here --
    they're still locked at this phase -- but the pair needs the design
    guide's own art (see lightmode_assets.mascots) and isn't wired in yet,
    so this draws the app's own hatched stand-ins instead.
    """
    return """
<div class="vl" data-screen="reveal">
  %(head)s
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
</div>""" % {"head": _head()}


def chat_timed():
    """The room, on the clock. The only screen where the transcript scrolls.

    The countdown in the strip is cosmetic: `send_message()` gates on the
    phase server-side, so a browser with a stopped clock buys nobody an extra
    minute.
    """
    return """
<div class="vl" data-screen="chat_timed">
  %(head)s
  <div class="vl-main">
    <div class="strip">
      <span class="strip-time">3:42</span>
      <p class="t-caption" style="flex:1;">left in this conversation. Photos
        unlock if you both continue.</p>
    </div>

    <div class="log">
      <div class="bubble them">Hi! Your search said live music too &mdash; what was the last thing you saw?</div>
      <div class="bubble me">Ha, good opener. Nubya Garcia at the Muziekgieterij, about a month ago.</div>
      <div class="bubble them">No way, I was there. Second balcony, stage left.</div>
      <div class="bubble me">That's either a lovely coincidence or you're very good at this.</div>
      <div class="bubble them">Bit of both.</div>
    </div>

    <div class="composer">
      <input class="field" type="text" placeholder="Say something">
      <button class="send">%(send)s</button>
    </div>
  </div>
</div>""" % {"head": _head(back=True, title="Sanne"), "send": icon("chat.send", 20)}


def chat_deciding():
    """Time is up, and the question is asked once, plainly.

    Continuing is a positive act on both sides: silence is not consent here,
    and the grace window lapsing ends the match rather than defaulting it open.
    """
    return """
<div class="vl pre-login" data-screen="chat_deciding">
  %(head)s
  <div class="vl-main vl-scroll">
    <p class="t-over">Time's up</p>
    <div class="pair"><span class="ph"></span><span class="ph"></span></div>
    <h1 class="t-h1">Continue with<br>Sanne?</h1>
    <p class="t-body measure">Your five minutes are over. If you both continue,
      the chat stays open and your photos unlock.</p>
    <p class="t-body live"><i class="live-dot"></i><span>Sanne hasn't answered yet</span></p>

    <div class="ring" style="--deg: 108deg;">
      <div class="ring-inner">
        <span class="ring-num">42</span>
        <span class="ring-unit">seconds</span>
      </div>
    </div>
    <p class="t-caption">No answer either way ends it. You owe nobody a reason.</p>
  </div>
  <div class="vl-foot reveal-foot">
    <button class="btn btn-quiet reveal-no">Unmatch</button>
    <button class="btn btn-primary reveal-yes">Continue</button>
  </div>
</div>""" % {"head": _head()}


def chat_ended():
    """An ending, without a scoreboard.

    No "they said no" -- the other person's answer is theirs, and a screen
    that reports it turns a private decision into a verdict delivered to you.
    """
    return """
<div class="vl" data-screen="chat_ended">
  %(head)s
  <div class="vl-main mid">
    <div class="mid-badge">%(icon)s</div>
    <h1 class="t-h2">This one's over</h1>
    <p class="t-body measure">The conversation is closed. Nothing is kept in a
      list and nobody is told anything about it.</p>
    <button class="btn btn-primary empty-cta">Search again</button>
  </div>
  %(tabs)s
</div>""" % {"head": _head(), "icon": icon("card.check", 28),
             "tabs": tabbar("chats")}


# ======================================================================
# Chats
# ======================================================================

def chats():
    """The list. Phase is a tag, because a room's state is the thing you scan
    for -- which of these is live right now, and which is history."""
    return """
<div class="vl" data-screen="chats">
  %(head)s
  <div class="vl-main vl-scroll">
    <h1 class="t-h1" style="margin-bottom:16px;">Chats</h1>
    <div class="stack">
      <a class="row row-link"><span class="avatar ph"></span>
        <span class="row-main"><strong>Sanne</strong>
          <span>Bit of both.</span></span>
        <span class="row-end"><span class="tag tag-gold">Timed</span></span></a>
      <a class="row row-link"><span class="avatar ph"></span>
        <span class="row-main"><strong>Merel</strong>
          <span>That market on Saturday, then?</span></span>
        <span class="row-end t-caption">2h</span></a>
      <a class="row row-link"><span class="avatar ph"></span>
        <span class="row-main"><strong>Fenna</strong>
          <span>No messages yet &mdash; say hi!</span></span>
        <span class="row-end"><span class="tag">It's a match</span></span></a>
      <a class="row row-link"><span class="avatar ph"></span>
        <span class="row-main"><strong>Deleted member</strong>
          <span>Thanks for the chat.</span></span>
        <span class="row-end"><span class="tag tag-quiet">Ended</span></span></a>
    </div>
  </div>
  %(tabs)s
</div>""" % {"head": _head(), "tabs": tabbar("chats")}


def chats_empty():
    """The list with nothing in it yet.

    An empty state earns exactly one thing to do next, stated once -- not a
    dead end and not a second competing CTA alongside the tab bar's own
    search icon.
    """
    return """
<div class="vl" data-screen="empty">
  %(head)s
  <div class="vl-main mid">
    <div class="mid-badge">%(icon)s</div>
    <h1 class="t-h2">No chats yet</h1>
    <p class="t-body measure">Start a search and we'll pair you the moment
      someone is looking for you too.</p>
    <button class="btn btn-primary empty-cta">Start a search</button>
  </div>
  %(tabs)s
</div>""" % {"head": _head(), "icon": icon("tab.chats", 28), "tabs": tabbar("chats")}


# ======================================================================
# Profile
# ======================================================================

def profile_view():
    """A pinned name over a scrolling stack of cards.

    All of it is columns `profiles` already has, so a new field is a new card
    rather than a new route. The carousel's segment bar is per photo, not a
    dot -- with six photos maximum, a bar says how far along you are and a row
    of dots only says how many there are.
    """
    return """
<div class="vl" data-screen="profile_view">
  %(head)s
  <div class="vl-main vl-scroll">
    <div class="pro-frame">
      <span class="ph"></span>
      <div class="bar pro-bar"><i class="is-on"></i><i></i><i></i><i></i></div>
    </div>
    <h1 class="t-h1" style="margin-top:16px;">Sanne, 27</h1>
    <p class="t-caption">%(pin)s Maastricht</p>

    <div class="stack" style="margin-top:20px;">
      <div class="card"><p class="section-label">Looking for</p>
        <div class="chipset"><span class="chip">Long-term relationship</span>
          <span class="chip">New friends</span></div></div>
      <div class="card"><p class="section-label">About me</p>
        <p class="t-body">Architect, bad guitarist, reliable source of the
          second-best coffee recommendation in any given street.</p></div>
      <div class="card"><p class="section-label">Interests</p>
        <div class="chipset"><span class="chip">%(note)s Live music</span>
          <span class="chip">%(note)s Hiking</span>
          <span class="chip">%(note)s Cooking</span></div></div>
      <div class="card"><p class="section-label">In short</p>
        <p class="t-body">Ask me about the Muziekgieterij. Don't ask me to
          pick a favourite album.</p></div>
    </div>
  </div>
  %(tabs)s
</div>""" % {"head": _head(back=True, action=icon("nav.more", 22)),
             "pin": icon("card.location", 13), "note": icon("card.interests", 15),
             "tabs": tabbar("you")}


def profile_edit():
    """Photo changes are staged and applied together on Save.

    The tile strip is the whole interaction: an x marks a photo for removal
    (Undo takes it back), tapping a tile makes it the main one, and dragging
    reorders. The browser transcribes the strip into three hidden fields,
    because a FileList is read-only and cannot be edited in place.
    """
    return """
<div class="vl" data-screen="profile_edit">
  %(head)s
  <div class="vl-main vl-scroll">
    <p class="section-label">Photos</p>
    <div class="tiles">
      <span class="tile is-main"><b>Main</b></span>
      <span class="tile"></span>
      <span class="tile"></span>
      <span class="tile tile-add">%(plus)s</span>
    </div>
    <p class="t-caption">Drag to reorder. Tap one to make it your main photo.</p>

    <p class="section-label">About you</p>
    <div class="form">
      <div><label class="lbl">Name</label><input class="field" type="text" value="Sanne"></div>
      <div><label class="lbl">About me</label>
        <textarea class="field">Architect, bad guitarist, reliable source of the second-best coffee recommendation in any given street.</textarea></div>
      <div><label class="lbl">Location</label>
        <p class="t-body" style="margin-top:4px;">%(pin)s Maastricht &mdash;
          everyone on Velvt is here, so there's nothing to choose.</p></div>
    </div>

    <p class="section-label">Profile strength</p>
    <div class="bar"><i class="is-on"></i><i class="is-on"></i><i class="is-on"></i><i></i></div>
    <p class="t-caption" style="margin-top:8px;">Add two more photos and your
      hobbies to finish it off.</p>
  </div>
  <div class="vl-foot">
    <button class="btn btn-block btn-primary">Save changes</button>
  </div>
</div>""" % {"head": _head(back=True, title="Edit profile"),
             "plus": icon("photo.add", 22), "pin": icon("card.location", 13)}


# ======================================================================
# Account, safety
# ======================================================================

def settings():
    """Rows, grouped, with the destructive one last and in danger colour.

    Sessions are listed because the cookie is not the login -- `sessions` is
    the authority, so revoking one here takes effect on that device
    immediately rather than whenever its cookie happens to expire.
    """
    return """
<div class="vl" data-screen="settings">
  %(head)s
  <div class="vl-main vl-scroll">
    <h1 class="t-h1" style="margin-bottom:16px;">Settings</h1>

    <p class="section-label">Account</p>
    <div class="stack-tight">
      <div class="row row-link"><span class="row-main"><strong>Change password</strong></span>
        <span class="row-end">%(go)s</span></div>
      <div class="row row-link"><span class="row-main"><strong>Signed-in devices</strong>
        <span>3 sessions</span></span><span class="row-end">%(go)s</span></div>
      <div class="row row-link"><span class="row-main"><strong>Download your data</strong></span>
        <span class="row-end">%(go)s</span></div>
    </div>

    <p class="section-label">Consent</p>
    <div class="stack-tight">
      <div class="row row-link"><span class="row-main"><strong>Product emails</strong>
        <span>Occasional, never your matches</span></span><span class="switch"></span></div>
      <div class="row row-link"><span class="row-main"><strong>Analytics</strong>
        <span>Aggregate only</span></span><span class="switch is-on"></span></div>
    </div>

    <p class="section-label">Language</p>
    <div class="chipset"><span class="chip is-on">English</span>
      <span class="chip">Nederlands</span></div>

    <p class="section-label">Danger</p>
    <div class="stack-tight">
      <div class="row row-link"><span class="row-main"><strong class="danger-text">Delete my account</strong>
        <span>30 days to change your mind</span></span><span class="row-end">%(go)s</span></div>
    </div>
  </div>
  %(tabs)s
</div>""" % {"head": _head(), "go": icon("nav.forward", 18), "tabs": tabbar("you")}


def report():
    """A reason, an optional note, and a statement of what happens next.

    Blocking is offered on the same screen because the two almost always go
    together, and making someone find the block separately after reporting is
    asking them to do the work twice.
    """
    return """
<div class="vl" data-screen="report">
  %(head)s
  <div class="vl-main vl-scroll">
    <h1 class="t-h1">Report Sanne</h1>
    <p class="t-body measure" style="margin-bottom:20px;">A moderator reads
      every report. You won't be told who acted on it, and Sanne isn't told
      you reported her.</p>

    <p class="section-label">What happened?</p>
    <div class="stack-tight">
      <div class="row row-link is-on"><span class="row-main"><strong>Harassment or abuse</strong></span>
        <span class="row-end">%(tick)s</span></div>
      <div class="row row-link"><span class="row-main"><strong>Fake profile</strong></span></div>
      <div class="row row-link"><span class="row-main"><strong>Underage</strong></span></div>
      <div class="row row-link"><span class="row-main"><strong>Something else</strong></span></div>
    </div>

    <p class="section-label">Anything to add?</p>
    <textarea class="field" placeholder="Optional. Whatever helps."></textarea>

    <div class="row row-link" style="margin-top:16px;">
      <span class="row-main"><strong>Block her too</strong>
        <span>You won't appear in each other's searches</span></span>
      <span class="switch is-on"></span></div>
  </div>
  <div class="vl-foot">
    <button class="btn btn-block btn-danger">Send report</button>
  </div>
</div>""" % {"head": _head(back=True, title="Report"), "tick": icon("card.check", 20)}


def safety():
    return """
<div class="vl" data-screen="safety">
  %(head)s
  <div class="vl-main vl-scroll prose">
    <h1 class="t-h1" style="margin-bottom:16px;">Staying safe</h1>
    <h2>Meet somewhere public first</h2>
    <p>A cafe, a bar, a walk through the Stadspark. Somewhere you can leave
      easily and nobody has to invite anyone anywhere.</p>
    <h2>Tell someone where you're going</h2>
    <p>Who, where, and when you expect to be home. It costs one message.</p>
    <h2>Keep it on Velvt until you're ready</h2>
    <p>There's no rush to hand over a phone number. If someone is pushing for
      one, that itself is information.</p>
    <h2>Report anything that felt wrong</h2>
    <p>Even if you're not sure. A moderator reads every report, and a pattern
      across several is often what makes a decision possible.</p>
    <div class="card" style="margin-top:20px;">
      <p class="t-body"><b>In immediate danger?</b> Call 112. Velvt is not an
        emergency service and cannot reach anyone on your behalf.</p>
    </div>
  </div>
  %(tabs)s
</div>""" % {"head": _head(), "tabs": tabbar("info")}


# ======================================================================
# Info and legal
# ======================================================================

def faq():
    return """
<div class="vl" data-screen="faq">
  %(head)s
  <div class="vl-main vl-scroll">
    <h1 class="t-h1" style="margin-bottom:12px;">Questions</h1>
    <details class="qa" open><summary>Why only five minutes?<span>%(go)s</span></summary>
      <p>Long enough to find out whether there's anything there, short enough
        that neither of you is stuck being polite. The clock is the point.</p></details>
    <details class="qa"><summary>Why can't I browse profiles?<span>%(go)s</span></summary>
      <p>Because a stack of profiles turns people into a catalogue. You're
        paired only when you're both actually looking, right then.</p></details>
    <details class="qa"><summary>When do photos unlock?<span>%(go)s</span></summary>
      <p>When you both continue past the decision. Not before, and not for
        anyone who isn't matched with you.</p></details>
    <details class="qa"><summary>Why Maastricht only?<span>%(go)s</span></summary>
      <p>A dating app with three people in your city is not a dating app.
        One city at a time, properly.</p></details>
    <details class="qa"><summary>What happens if I delete my account?<span>%(go)s</span></summary>
      <p>Thirty days to change your mind, then your profile, photos, searches
        and sessions are destroyed. Messages you sent stay in the other
        person's chat with your name removed &mdash; deleting yours shouldn't
        erase their conversation.</p></details>
  </div>
  %(tabs)s
</div>""" % {"head": _head(), "go": icon("nav.forward", 16), "tabs": tabbar("info")}


def terms():
    return """
<div class="vl" data-screen="terms">
  %(head)s
  <div class="vl-main vl-scroll prose">
    <h1 class="t-h1" style="margin-bottom:16px;">Terms</h1>
    <p class="t-caption">Last updated 12 August 2026</p>
    <h2>1. Who can use Velvt</h2>
    <p>You must be 18 or over and living in or around Maastricht. One account
      per person.</p>
    <h2>2. How you behave here</h2>
    <p>No harassment, no impersonation, no photographs of anyone who hasn't
      agreed to be there. We suspend accounts for this and we don't argue
      about it at length.</p>
    <h2>3. What we do with the service</h2>
    <p>We may change how matching works, and we'll say so plainly when it
      affects you. We don't sell your data and we don't run ads.</p>
    <h2>4. Ending it</h2>
    <p>You can delete your account at any time from Settings. We can close an
      account that breaks these terms, and we'll tell you why.</p>
  </div>
  %(tabs)s
</div>""" % {"head": _head(back=True, title="Terms"), "tabs": tabbar("info")}


def privacy():
    return """
<div class="vl" data-screen="privacy">
  %(head)s
  <div class="vl-main vl-scroll prose">
    <h1 class="t-h1" style="margin-bottom:16px;">Privacy</h1>
    <p class="t-caption">Last updated 12 August 2026</p>
    <h2>What we hold</h2>
    <p>Your email, date of birth, profile, photos, the searches you run and
      the messages you send. That's the list.</p>
    <h2>How long</h2>
    <p>Ended matches and their messages for 90 days. Cancelled searches for 7.
      Your exact search coordinates for 30 days, then rounded to about a
      kilometre rather than deleted. Resolved reports for a year, because a
      moderation decision needs a record.</p>
    <h2>Who else sees it</h2>
    <p>Your matches see your profile. A moderator sees what a report contains.
      Nobody else, and no advertiser at all.</p>
    <h2>Your rights</h2>
    <p>Export everything we hold from Settings, or delete the account outright.
      Deletion is real: after 30 days the profile, photos, searches, sessions
      and consents are destroyed.</p>
  </div>
  %(tabs)s
</div>""" % {"head": _head(back=True, title="Privacy"), "tabs": tabbar("info")}


def imprint():
    return """
<div class="vl" data-screen="imprint">
  %(head)s
  <div class="vl-main vl-scroll prose">
    <h1 class="t-h1" style="margin-bottom:16px;">Imprint</h1>
    <h2>Responsible for this service</h2>
    <p>Velvt<br>Maastricht, Netherlands</p>
    <h2>Contact</h2>
    <p>hello@velvt.app<br>Moderation reports go through the app, not this
      address &mdash; they reach a moderator faster.</p>
    <h2>Chamber of Commerce</h2>
    <p>KvK 00000000</p>
    <h2>Dispute resolution</h2>
    <p>We're not obliged to take part in dispute resolution before a consumer
      arbitration board, and we don't.</p>
  </div>
  %(tabs)s
</div>""" % {"head": _head(back=True, title="Imprint"), "tabs": tabbar("info")}


# ======================================================================
# Admin
# ======================================================================

def admin_members():
    """Where the real figure lives.

    Demo accounts are counted separately rather than folded in, because the
    landing page's claim is only honest if somebody can see the number it was
    computed from.
    """
    return """
<div class="vl" data-screen="admin_members">
  %(head)s
  <div class="vl-main vl-scroll">
    <h1 class="t-h1" style="margin-bottom:16px;">Members</h1>
    <div class="card">
      <div class="adm-row"><span class="adm-stat"><span>Real members</span></span>
        <b class="adm-num">18</b></div>
      <div class="adm-row"><span class="adm-stat"><span>Demo accounts</span></span>
        <b class="adm-num">40</b></div>
      <div class="adm-row"><span class="adm-stat"><span>Searching now</span></span>
        <b class="adm-num">7</b></div>
    </div>

    <p class="section-label">Recent</p>
    <div class="stack-tight">
      <a class="row row-link"><span class="avatar ph"></span>
        <span class="row-main"><strong>Sanne</strong><span>27 &middot; joined 2d ago</span></span>
        <span class="row-end">%(go)s</span></a>
      <a class="row row-link"><span class="avatar ph"></span>
        <span class="row-main"><strong>Joris</strong><span>31 &middot; joined 4d ago</span></span>
        <span class="row-end"><span class="tag tag-quiet">Demo</span></span></a>
      <a class="row row-link"><span class="avatar ph"></span>
        <span class="row-main"><strong>Fenna</strong><span>24 &middot; suspended</span></span>
        <span class="row-end"><span class="tag tag-danger">Suspended</span></span></a>
    </div>
  </div>
</div>""" % {"head": _head(back=True, title="Admin"), "go": icon("nav.forward", 18)}


def admin_reports():
    return """
<div class="vl" data-screen="admin_reports">
  %(head)s
  <div class="vl-main vl-scroll">
    <h1 class="t-h1" style="margin-bottom:16px;">Reports</h1>
    <p class="t-body measure" style="margin-bottom:16px;">An ended match with
      an unresolved report is never purged, whatever its age.</p>
    <div class="stack">
      <div class="card">
        <div class="row-link" style="margin-bottom:8px;">
          <span class="row-main"><strong>Harassment or abuse</strong>
            <span>Reported 3h ago &middot; match #418</span></span>
          <span class="tag tag-danger">Open</span></div>
        <p class="t-body">"Kept messaging after I said I wasn't interested."</p>
        <div class="chipset" style="margin-top:12px;">
          <span class="chip">Suspend</span><span class="chip">Dismiss</span>
          <span class="chip">Open the chat</span></div>
      </div>
      <div class="card">
        <div class="row-link">
          <span class="row-main"><strong>Fake profile</strong>
            <span>Resolved 6d ago &middot; no action</span></span>
          <span class="tag tag-quiet">Closed</span></div>
      </div>
    </div>
  </div>
</div>""" % {"head": _head(back=True, title="Reports")}


def admin_profile_new():
    return """
<div class="vl" data-screen="admin_profile_new">
  %(head)s
  <div class="vl-main vl-scroll">
    <h1 class="t-h1" style="margin-bottom:16px;">New profile</h1>
    <div class="form">
      <div><label class="lbl">Name</label><input class="field" type="text" value="Joris"></div>
      <div><label class="lbl">Date of birth</label><input class="field" type="text" value="02 / 11 / 1994"></div>
      <div><label class="lbl">Gender</label>
        <div class="chipset"><span class="chip is-on">Man</span>
          <span class="chip">Woman</span><span class="chip">Non-binary</span></div></div>
      <div><label class="lbl">Location</label>
        <p class="t-body" style="margin-top:4px;">%(pin)s Maastricht &mdash;
          pinned server-side, whatever the form says.</p></div>
      <div class="row row-link"><span class="row-main"><strong>Demo account</strong>
        <span>Excluded from every real search pool</span></span>
        <span class="switch is-on"></span></div>
    </div>
  </div>
  <div class="vl-foot">
    <button class="btn btn-block btn-primary">Create profile</button>
  </div>
</div>""" % {"head": _head(back=True, title="New profile"), "pin": icon("card.location", 13)}


# ======================================================================
# Errors
# ======================================================================

def csrf_error():
    """A 400 that says what to do, not what went wrong internally."""
    return """
<div class="vl" data-screen="csrf_error">
  %(head)s
  <div class="vl-main mid">
    <div class="mid-badge">%(icon)s</div>
    <h1 class="t-h2">That form went stale</h1>
    <p class="t-body measure">You were away long enough that we stopped
      trusting the page. Nothing was sent. Go back and try it again.</p>
    <button class="btn btn-primary empty-cta">Back to safety</button>
  </div>
</div>""" % {"head": _head(), "icon": icon("state.shield", 28)}


def rate_limited():
    return """
<div class="vl" data-screen="rate_limited">
  %(head)s
  <div class="vl-main mid">
    <div class="mid-badge">%(icon)s</div>
    <h1 class="t-h2">Slow down a moment</h1>
    <p class="t-body measure">That's a lot of tries in a short time. Give it a
      minute and you'll be able to carry on.</p>
    <p class="t-caption">This protects everyone's account, including yours.</p>
  </div>
</div>""" % {"head": _head(), "icon": icon("card.age", 28)}


# ======================================================================
# The running order
# ======================================================================
# (key, label, section, builder). `landing` takes the brand art, so it is the
# one entry the builder passes an argument to -- flagged by name rather than by
# inspecting the signature, since guessing at call shapes is how a rename turns
# into a silent blank screen.
SCREENS = [
    ("landing",           "Landing",        "Pre-login",  landing),
    ("age_gate",          "Age gate",       "Pre-login",  age_gate),
    ("register",          "Register",       "Pre-login",  register),
    ("login",             "Sign in",        "Pre-login",  login),
    ("forgot",            "Forgot",         "Pre-login",  forgot),
    ("reset",             "Reset",          "Pre-login",  reset),

    ("intro",             "How it works",   "Search",     intro),
    ("search_start",      "Type",           "Search",     search_start),
    ("search_criteria",   "Filters",        "Search",     search_criteria),
    ("search_waiting",    "Waiting",        "Search",     search_waiting),

    ("reveal",            "Reveal",         "Match",      match_reveal),
    ("chat_timed",        "Timed chat",     "Match",      chat_timed),
    ("chat_deciding",     "Decision",       "Match",      chat_deciding),
    ("chat_ended",        "Ended",          "Match",      chat_ended),

    ("chats",             "Chats",          "Chats",      chats),
    ("empty",             "Chats, empty",   "Chats",      chats_empty),

    ("profile_view",      "Profile",        "Profile",    profile_view),
    ("profile_edit",      "Edit profile",   "Profile",    profile_edit),

    ("settings",          "Settings",       "Account",    settings),
    ("report",            "Report",         "Account",    report),
    ("safety",            "Safety",         "Account",    safety),

    ("faq",               "FAQ",            "Info",       faq),
    ("terms",             "Terms",          "Info",       terms),
    ("privacy",           "Privacy",        "Info",       privacy),
    ("imprint",           "Imprint",        "Info",       imprint),

    ("admin_members",     "Members",        "Admin",      admin_members),
    ("admin_reports",     "Reports",        "Admin",      admin_reports),
    ("admin_profile_new", "New profile",    "Admin",      admin_profile_new),

    ("csrf_error",        "Stale form",     "Errors",     csrf_error),
    ("rate_limited",      "Rate limited",   "Errors",     rate_limited),
]


def render_all(brand):
    """Every screen's markup, in running order, with the first one shown."""
    out = []
    for i, (key, _label, _section, fn) in enumerate(SCREENS):
        html = fn(brand) if key == "landing" else fn()
        if i == 0:
            html = html.replace('<div class="vl', '<div class="vl is-on', 1)
        out.append(html)
    return "\n".join(out)


def sections():
    """The tab rail's grouping, in running order and without duplicates."""
    order = []
    for _key, _label, section, _fn in SCREENS:
        if section not in order:
            order.append(section)
    return [(s, [(k, l) for k, l, sec, _f in SCREENS if sec == s]) for s in order]


LANDING_CSS = """
/* ---- landing ------------------------------------------------------ */
/* The film is the whole screen and the whole frame -- nothing is cropped.

   Two wrong answers came before this one, and both cropped. `cover` across
   the full height scaled a 9:16 shot past 1:1 in a 9:19.5 box and cut
   through both faces. Cropping it to a band around the embrace lost the
   other end: the arms hang low, almost to the hem of the frame, so a window
   tight enough to enlarge the faces took the hands off with it -- two
   characters with stumps. The arms are thin and they are what the shot is
   about, so there is nothing in this frame that can be trimmed.

   So the layer stops where the buttons start and the frame is contained in
   what is left, hung from the top. `contain` against the full width would be
   693px tall in an 844px screen and finish 21px *into* the buttons; against
   the 675px that is actually free it comes out 380px wide instead of 390,
   which is a 5px gutter either side of a full-bleed ground and invisible,
   and nothing of the film is behind anything. Hanging the slack at the top
   rather than the bottom is the whole difference between the arms clearing
   the buttons and disappearing under them. 21% is the foot: the two
   buttons, the gap between them and the fine print, plus the padding around
   all of it. */
.vl .film {
  position: absolute; top: 0; left: 0; right: 0; bottom: 21%;
  z-index: 0; overflow: hidden; pointer-events: none;
}
.vl .film-reel {
  width: 100%; height: 100%; display: block;
  object-fit: contain; object-position: 50% 0%;
}
/* The recolour that matters, and the only thing that makes a full-frame film
   under a full page of copy readable. Every stop is mixed from --scrim rather
   than written as a literal, so switching mode inverts the whole thing: it
   lightens the film under dark type and darkens it under pale type.

   It eases rather than steps. The first curve here never dropped below 62%
   anywhere, which on a near-white ground is not a scrim but a lid -- the art
   came through as a milky smear with no subject in it. Now: solid behind the
   wordmark, thinning through the headline where the two of them are standing
   full-length and read as a presence behind bold dark type, and fully clear
   from two thirds down, which is where the arms come round and stays clear
   to the hem. The percentages are of the layer, and the layer now ends at
   the buttons, so they do not need re-deriving if the foot grows. */
.vl .film::after {
  content: ""; position: absolute; inset: 0;
  background: linear-gradient(180deg,
    var(--scrim) 0%,
    color-mix(in srgb, var(--scrim) 86%, transparent) 22%,
    color-mix(in srgb, var(--scrim) 60%, transparent) 38%,
    color-mix(in srgb, var(--scrim) 54%, transparent) 50%,
    color-mix(in srgb, var(--scrim) 10%, transparent) 60%,
    color-mix(in srgb, var(--scrim) 0%, transparent) 66%,
    color-mix(in srgb, var(--scrim) 0%, transparent) 93%,
    color-mix(in srgb, var(--scrim) 34%, transparent) 100%);
}
.vl-top, .vl-main, .vl-foot, .vl-tabbar { position: relative; z-index: 1; }

/* The big mark is the same drawing and the same travelling fill as the one
   in the bar -- `.brand-fill` carries both, so the colour cannot drift apart
   between the landing and every other screen. Only the size is local. */
.vl .logo {
  width: min(80%, 270px); aspect-ratio: 753 / 391;
  max-height: 132px; margin: var(--space-2) auto var(--space-5); flex: 0 1 auto; min-height: 0;
}

.vl .lang { min-width: 44px; min-height: 44px; padding: 0 var(--space-2); }  /* ch.05 tap target */
.vl .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
.vl .headline { margin-bottom: var(--space-4); }
.vl .sub { color: var(--body); }
.vl .grow { flex: 1 1 auto; min-height: var(--space-6); }
.vl .live { justify-content: center; color: var(--body); }
.vl .live b { font-weight: 600; color: var(--ink); }   /* ch.03: step through 600 */
.vl .fine { margin-top: var(--space-4); }

/* ---- intro (a real sequence, so it earns 1/2/3) --------------------- */
.vl .intro-lede { color: var(--body); margin: var(--space-3) 0 var(--space-6); }
.vl .intro-steps { list-style: none; margin: 0 0 var(--space-4); padding: 0;
                    display: flex; flex-direction: column; gap: var(--space-5); }
.vl .intro-steps li { display: flex; gap: var(--space-4); align-items: flex-start; }
.vl .intro-n { flex: none; width: 28px; height: 28px; border-radius: var(--r-pill);
               background: var(--action-wash); color: var(--ink-accent);
               display: inline-flex; align-items: center; justify-content: center;
               font-size: 13px; font-weight: 700; }
.vl .intro-steps h2 { margin-bottom: 2px; }
.vl .intro-steps p { color: var(--body); }

/* ---- match reveal / decision ---------------------------------------- */
.vl .pair { display: flex; align-items: center; justify-content: center; margin: var(--space-5) 0; }
.vl .pair .ph { width: 92px; height: 92px; border-radius: var(--r-pill); flex: none;
                box-shadow: 0 0 0 3px var(--canvas), var(--e2); }
.vl .pair .ph + .ph { margin-left: -20px; }
.vl .reveal-label { margin-top: var(--space-5); }
.vl .reveal-chips { margin: var(--space-2) 0 var(--space-3); justify-content: center; }
.vl .ring { position: relative; flex: none; width: 96px; height: 96px; border-radius: var(--r-pill);
            margin: var(--space-6) auto var(--space-3);
            background: conic-gradient(var(--action) 0deg var(--deg, 0deg), var(--hairline) var(--deg, 0deg) 360deg); }
.vl .ring::after { content: ""; position: absolute; inset: 7px; border-radius: var(--r-pill); background: var(--canvas); }
.vl .ring-inner { position: absolute; inset: 0; z-index: 1; display: flex; flex-direction: column;
                   align-items: center; justify-content: center; gap: 1px; }
.vl .ring-num { font-weight: 700; font-size: 26px; line-height: 1; color: var(--ink); font-variant-numeric: tabular-nums; }
.vl .ring-unit { font-weight: 600; font-size: 9px; letter-spacing: .12em; text-transform: uppercase; color: var(--quiet); }
.vl .reveal-foot { display: flex; gap: var(--space-3); }
.vl .reveal-no { flex: 1; }
.vl .reveal-yes { flex: 2; }

/* ---- empty / error middles ------------------------------------------ */
.vl .empty-cta { margin-top: var(--space-3); }

/* ---- the search pulse ------------------------------------------------ */
/* Hand-rolled, not a Lottie: the player was fetched from a CDN the app's own
   CSP forbids, so it never ran in production at all. */
.vl .pulse { position: relative; width: 120px; height: 120px; margin: var(--space-6) auto var(--space-5); flex: none; }
.vl .pulse span { position: absolute; inset: 0; border-radius: var(--r-pill);
                  border: 2px solid var(--action); opacity: 0;
                  animation: vl-ping 2.4s var(--ease) infinite; }
.vl .pulse span:nth-child(2) { animation-delay: .8s; }
.vl .pulse span:nth-child(3) { animation-delay: 1.6s; }
@keyframes vl-ping { 0% { transform: scale(.4); opacity: .9; } 100% { transform: scale(1); opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .vl .pulse span { animation: none; opacity: .35; } }

/* ---- rows that act like controls -------------------------------------- */
.vl button.row { width: 100%; text-align: left; border: 0; font: inherit; cursor: pointer; }
.vl .row.is-on { background: var(--action-wash); box-shadow: none; }
.vl .row.is-on strong { color: var(--ink-accent); }
.vl .row.is-on .row-end { color: var(--ink-accent); }
.vl .consent { display: flex; gap: var(--space-3); align-items: flex-start; margin-top: var(--space-2); }
.vl .consent b { color: var(--ink-accent); font-weight: 600; }
.vl .danger-text { color: var(--danger); }
.vl .btn-danger { background: var(--danger); color: var(--on-action); }

/* ---- profile ---------------------------------------------------------- */
.vl .pro-frame { position: relative; border-radius: var(--r-xl); overflow: hidden;
                 aspect-ratio: 4 / 5; background: var(--field); }
.vl .pro-frame > .ph { position: absolute; inset: 0; }
.vl .pro-bar { position: absolute; top: var(--space-3); left: var(--space-3);
               right: var(--space-3); }
.vl .pro-bar i { background: rgba(255,255,255,.45); }
.vl .pro-bar i.is-on { background: #fff; }
.vl .tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-2);
             margin-bottom: var(--space-2); }
.vl .tile { aspect-ratio: 3 / 4; border-radius: var(--r-md); background: var(--field);
            position: relative; display: flex; align-items: flex-end; justify-content: center;
            padding-bottom: 6px; }
.vl .tile b { font-size: 9px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
              color: var(--on-action); background: var(--action); border-radius: var(--r-xs);
              padding: 2px 5px; }
.vl .tile-add { align-items: center; justify-content: center; padding: 0;
                color: var(--quiet); background: transparent; box-shadow: inset 0 0 0 2px var(--hairline); }
"""
