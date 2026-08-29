"""Drive the light-mode editor the way a person would, and assert it responded.

A build that renders is not a build that works: every control here writes
through JavaScript, so the only honest check is to click one and read the
result back out of the DOM.
"""
import sys
from playwright.sync_api import sync_playwright

URL = "file:///tmp/velvt-light.html"
fails = []


def ok(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        fails.append(what)


with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    page = b.new_page(viewport={"width": 1400, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(URL)
    page.wait_for_timeout(600)

    ok(not errors, "no JS errors on load: %s" % errors[:3])

    # ---- screens ----
    n_screens = page.locator(".device .vl").count()
    n_tabs = page.locator(".tab").count()
    ok(n_screens == 30, "every screen present (%d)" % n_screens)
    ok(n_tabs == n_screens, "a tab per screen (%d tabs)" % n_tabs)
    ok(page.locator(".device .vl.is-on").count() == 1, "exactly one screen shown")

    # Every tab must actually reach its screen, and that screen must have real
    # height -- a screen that renders empty still satisfies "is-on".
    bad = []
    for i in range(n_tabs):
        tab = page.locator(".tab").nth(i)
        key = tab.get_attribute("data-target")
        tab.click()
        shown = page.locator('.device .vl[data-screen="%s"].is-on' % key)
        if shown.count() != 1:
            bad.append(key + ":not-shown")
            continue
        box = shown.bounding_box()
        if not box or box["height"] < 700:
            bad.append(key + ":empty")
    ok(not bad, "every tab shows a screen with real content (%s)" % (bad or "all 30 ok"))

    # No screen may silently draw a blank icon: icon() returns "" for a slot it
    # cannot resolve, which is invisible rather than loud.
    empties = page.eval_on_selector_all(
        ".device .vl svg", "els => els.filter(e => !e.innerHTML.trim()).length")
    ok(empties == 0, "no empty icons (%d)" % empties)

    page.locator('.tab[data-target="landing"]').click()

    # ---- selection ----
    page.locator('.vl[data-screen="landing"] .btn-primary').click()
    ok(page.locator("#insp-body").is_visible(), "inspector opens on click")
    ok("btn" in page.locator("#insp-name").inner_text(), "inspector names the element")

    # ---- colour, per element ----
    page.locator('input[type=text][data-set="background-color"][data-state="base"]').fill("#FAE83E")
    page.wait_for_timeout(200)
    bg = page.eval_on_selector(
        '.vl[data-screen="landing"] .btn-primary',
        "el => getComputedStyle(el).backgroundColor")
    ok(bg == "rgb(250, 232, 62)", "per-element background applied (%s)" % bg)
    ok("background-color" in page.locator("#export-css").input_value(), "export shows the rule")

    # ---- text ----
    page.locator('.seg button[data-pane="text"]').click()
    page.locator("#insp-text").fill("Join Velvt")
    page.wait_for_timeout(150)
    ok(page.locator('.vl[data-screen="landing"] .btn-primary').inner_text() == "Join Velvt",
       "text edit reaches the screen")

    # ---- hover ----
    page.locator('.seg button[data-pane="hover"]').click()
    page.select_option('select[data-set="transform"][data-state="hover"]', "translateY(-4px)")
    page.wait_for_timeout(150)
    css = page.locator("#export-css").input_value()
    ok(":hover" in css and "translateY(-4px)" in css, "hover rule written")
    ok("transition-duration" in css, "hover implies a transition")

    # ---- motion ----
    page.locator('.seg button[data-pane="motion"]').click()
    page.select_option('select[data-set="animation-name"][data-state="base"]', "vl-float")
    page.wait_for_timeout(150)
    anim = page.eval_on_selector(
        '.vl[data-screen="landing"] .btn-primary',
        "el => getComputedStyle(el).animationName")
    ok(anim == "vl-float", "animation applied (%s)" % anim)

    # ---- icons ----
    page.locator('.seg button[data-pane="icon"]').click()
    n = page.locator("#glyphs button").count()
    ok(n > 20, "glyph picker holds the registry (%d glyphs)" % n)
    page.locator("#glyphs button").first.click()
    page.wait_for_timeout(150)
    ok(page.locator('.vl[data-screen="landing"] .btn-primary svg').count() == 1,
       "icon added to an element that had none")
    page.locator("#glyphs button").nth(3).click()
    page.wait_for_timeout(150)
    ok(page.locator('.vl[data-screen="landing"] .btn-primary svg').count() == 1,
       "picking again swaps rather than stacks")
    page.locator("#icon-remove").click()
    page.wait_for_timeout(150)
    ok(page.locator('.vl[data-screen="landing"] .btn-primary svg').count() == 0, "icon removed")

    # ---- token rail ----
    page.locator('.rail-row input[data-token="--canvas"]').fill("#101010")
    page.wait_for_timeout(200)
    canvas = page.eval_on_selector(
        '.vl[data-screen="intro"]', "el => getComputedStyle(el).backgroundColor")
    ok(canvas == "rgb(16, 16, 16)", "token repaints a screen that is not even shown (%s)" % canvas)
    ok("--canvas" in page.locator("#export-tokens").input_value(), "token export")
    page.locator("#rail-reset").click()
    page.wait_for_timeout(200)
    canvas = page.eval_on_selector(
        '.vl[data-screen="intro"]', "el => getComputedStyle(el).backgroundColor")
    ok(canvas == "rgb(244, 243, 240)", "rail reset restores the token (%s)" % canvas)

    # ---- reset all ----
    page.locator("#reset-all").click()
    page.wait_for_timeout(200)
    bg = page.eval_on_selector(
        '.vl[data-screen="landing"] .btn-primary',
        "el => getComputedStyle(el).backgroundColor")
    ok(bg == "rgb(109, 40, 217)", "reset returns the element to the token (%s)" % bg)
    label = page.locator('.vl[data-screen="landing"] .btn-primary').inner_text()
    ok(label == "Create an account", "reset puts the original words back (%s)" % label)

    # ---- dark mode ----
    page.locator('#modes button[data-mode="dark"]').click()
    page.wait_for_timeout(250)
    ok(page.evaluate("document.documentElement.dataset.mode") == "dark", "dark stamp applied")
    dark_bg = page.eval_on_selector(
        '.vl[data-screen="landing"]', "el => getComputedStyle(el).backgroundColor")
    ok(dark_bg == "rgb(11, 7, 19)", "dark palette repaints the screen (%s)" % dark_bg)
    dark_ink = page.eval_on_selector(
        '.vl[data-screen="settings"] .t-h1', "el => getComputedStyle(el).color")
    ok(dark_ink == "rgb(247, 241, 251)", "dark text token applies (%s)" % dark_ink)
    e1 = page.eval_on_selector(
        '.vl[data-screen="chats"] .row', "el => getComputedStyle(el).boxShadow")
    ok("rgba(0, 0, 0" in e1, "dark elevation is its own scale (%s)" % e1[:44])

    # A token edited in dark must not leak into light, which is exactly what an
    # inline style on :root would have done.
    page.locator('.rail-row input[data-token="--canvas"]').fill("#123456")
    page.wait_for_timeout(200)
    ok(page.eval_on_selector('.vl[data-screen="landing"]',
       "el => getComputedStyle(el).backgroundColor") == "rgb(18, 52, 86)", "dark token applies")
    page.locator('#modes button[data-mode="light"]').click()
    page.wait_for_timeout(250)
    light_bg = page.eval_on_selector(
        '.vl[data-screen="landing"]', "el => getComputedStyle(el).backgroundColor")
    ok(light_bg == "rgb(244, 243, 240)", "dark edit did not leak into light (%s)" % light_bg)
    ok('[data-mode="dark"]' in page.locator("#export-tokens").input_value(),
       "dark palette exports under its own selector")

    # And the other direction: a light token must not win in dark mode just by
    # being written to a later stylesheet.
    page.locator('.rail-row input[data-token="--surface"]').fill("#00FF00")
    page.wait_for_timeout(200)
    page.locator('#modes button[data-mode="dark"]').click()
    page.wait_for_timeout(250)
    surf = page.eval_on_selector('.vl[data-screen="chats"] .row',
                                 "el => getComputedStyle(el).backgroundColor")
    ok(surf != "rgb(0, 255, 0)", "light token did not leak into dark (%s)" % surf)
    page.locator('#modes button[data-mode="light"]').click()
    page.locator("#rail-reset").click()
    page.wait_for_timeout(200)

    # A per-element edit is filed under the mode it was made in.
    page.locator('.vl[data-screen="landing"] .btn-secondary').click()
    page.locator('.seg button[data-pane="paint"]').click()
    page.locator('input[type=text][data-set="background-color"][data-state="base"]').fill("#FF0000")
    page.wait_for_timeout(200)
    ok(page.eval_on_selector('.vl[data-screen="landing"] .btn-secondary',
       "el => getComputedStyle(el).backgroundColor") == "rgb(255, 0, 0)", "light element edit applies")
    page.locator('#modes button[data-mode="dark"]').click()
    page.wait_for_timeout(250)
    ok(page.eval_on_selector('.vl[data-screen="landing"] .btn-secondary',
       "el => getComputedStyle(el).backgroundColor") != "rgb(255, 0, 0)",
       "that edit did not follow it into dark")
    page.locator('#modes button[data-mode="light"]').click()
    page.wait_for_timeout(200)

    # ---- structural edits are shared, colour is not ----
    # Radius, weight, hover lift, motion, text and icons describe the element
    # rather than the palette, so they must land in both worlds at once.
    page.locator('.tab[data-target="register"]').click()
    page.locator('.vl[data-screen="register"] .btn-primary').click()
    page.locator('.seg button[data-pane="paint"]').click()
    page.select_option('select[data-set="border-radius"][data-state="base"]', "var(--r-pill)")
    page.locator('.seg button[data-pane="text"]').click()
    page.locator("#insp-text").fill("Join Velvt")
    page.locator('.seg button[data-pane="icon"]').click()
    page.locator("#glyphs button").nth(2).click()
    page.locator('.seg button[data-pane="motion"]').click()
    page.select_option('select[data-set="animation-name"][data-state="base"]', "vl-breathe")
    page.wait_for_timeout(250)
    btn = '.vl[data-screen="register"] .btn-primary'
    light = page.evaluate(
        "s => { const e = document.querySelector(s), c = getComputedStyle(e);"
        " return [c.borderRadius, c.animationName, e.textContent.trim(),"
        " !!e.querySelector('svg')]; }", btn)
    page.locator('#modes button[data-mode="dark"]').click()
    page.wait_for_timeout(250)
    dark = page.evaluate(
        "s => { const e = document.querySelector(s), c = getComputedStyle(e);"
        " return [c.borderRadius, c.animationName, e.textContent.trim(),"
        " !!e.querySelector('svg')]; }", btn)
    ok(light[0] == dark[0] and light[0] != "10px", "radius is shared (%s / %s)" % (light[0], dark[0]))
    ok(light[1] == dark[1] == "vl-breathe", "motion is shared (%s / %s)" % (light[1], dark[1]))
    ok(light[2] == dark[2] == "Join Velvt", "text is shared (%s / %s)" % (light[2], dark[2]))
    ok(light[3] and dark[3], "icon is shared (%s / %s)" % (light[3], dark[3]))
    page.locator('#modes button[data-mode="light"]').click()
    page.locator("#reset-all").click()
    page.wait_for_timeout(200)

    # ---- the top bar carries the logo, centred ----
    page.locator('.tab[data-target="settings"]').click()
    page.wait_for_timeout(250)
    ok(page.locator('.vl[data-screen="settings"] .vl-logo').count() == 1,
       "top bar shows the logo, not the word")
    ok(page.locator('.vl[data-screen="settings"] .vl-word').count() == 0,
       "the typed wordmark is gone")
    off = page.eval_on_selector(
        '.vl[data-screen="settings"]',
        "el => { const s = el.getBoundingClientRect(),"
        " l = el.querySelector('.vl-logo').getBoundingClientRect();"
        " return Math.abs((l.left + l.right) / 2 - (s.left + s.right) / 2); }")
    ok(off < 1, "logo is centred on the screen (off by %.2fpx)" % off)
    # A back arrow on one side and nothing on the other is exactly what a
    # space-between row gets wrong, so check a screen that has one.
    page.locator('.tab[data-target="profile_view"]').click()
    page.wait_for_timeout(250)
    off2 = page.eval_on_selector(
        '.vl[data-screen="profile_view"]',
        "el => { const s = el.getBoundingClientRect(),"
        " l = el.querySelector('.vl-logo').getBoundingClientRect();"
        " return Math.abs((l.left + l.right) / 2 - (s.left + s.right) / 2); }")
    ok(off2 < 1, "still centred beside a back arrow (off by %.2fpx)" % off2)

    # ---- the mark: one animated fill, at the size asked for --------------
    # Two failures this catches, both of which look like "nothing happened":
    # a mark filled with a flat colour, and a mark whose gradient never
    # moves. Neither shows up in a still screenshot.
    marks = page.evaluate(
        """() => {
          const out = [];
          document.querySelectorAll('.device .vl').forEach(v => {
            const was = v.classList.contains('is-on');
            v.classList.add('is-on');
            const l = v.querySelector('.vl-logo');
            if (l) {
              const c = getComputedStyle(l), r = l.getBoundingClientRect(),
                    t = v.querySelector('.vl-top').getBoundingClientRect();
              out.push({key: v.dataset.screen, h: Math.round(r.height),
                        anim: c.animationName, grad: c.backgroundImage.includes('gradient'),
                        masked: (c.maskImage || c.webkitMaskImage || '').includes('url('),
                        inside: r.top >= t.top - 0.5 && r.bottom <= t.bottom + 0.5});
            }
            if (!was) v.classList.remove('is-on');
          });
          return out;
        }""")
    ok(len(marks) > 5, "the bar mark appears across the app (%d screens)" % len(marks))
    ok(all(m["h"] == 66 for m in marks),
       "every bar mark is 66px high (%s)" % sorted({m["h"] for m in marks}))
    ok(all(m["inside"] for m in marks),
       "and none of them is clipped by its own bar (%s)"
       % [m["key"] for m in marks if not m["inside"]])
    ok(all(m["anim"] == "brand-travel" for m in marks),
       "the colour animation is on the bar mark (%s)" % sorted({m["anim"] for m in marks}))
    ok(all(m["grad"] and m["masked"] for m in marks),
       "it is a gradient through a mask, not a flat fill")

    page.locator('.tab[data-target="landing"]').click()
    page.wait_for_timeout(300)
    big = page.eval_on_selector(
        '.vl[data-screen="landing"] .logo',
        "el => { const c = getComputedStyle(el);"
        " return [c.animationName, c.backgroundImage.includes('gradient'),"
        " Math.round(el.getBoundingClientRect().height)]; }")
    ok(big[0] == "brand-travel" and big[1],
       "the big landing mark animates from the same rule (%s)" % big[0])
    ok(big[2] > 60, "and is still the hero-sized one (%dpx)" % big[2])
    # The gradient has to actually travel: sample the computed position twice.
    moved = page.evaluate(
        """() => new Promise(res => {
             const el = document.querySelector('.vl[data-screen="landing"] .logo');
             const a = getComputedStyle(el).backgroundPositionX;
             setTimeout(() => res([a, getComputedStyle(el).backgroundPositionX]), 900);
           })""")
    ok(moved[0] != moved[1], "the fill travels rather than sitting still (%s)" % moved)

    # ---- the film shows the whole frame, and clears the buttons ----------
    # Three layouts failed here before this check existed, all of them looking
    # fine in a still of the first frame. `cover` scaled past 1:1 and cut
    # through both faces. Full-bleed on the floor of the screen put the arms
    # under the two buttons -- two heads and no hug. Cropping to a band around
    # the embrace took the hands off instead, because the arms hang nearly to
    # the hem of the frame. All of it only shows at the end of the film, so
    # the check drives to the embrace before it measures anything.
    film = page.evaluate(
        """async () => {
          const s = document.querySelector('.vl[data-screen="landing"]');
          const f = s.querySelector('.film'), v = f.querySelector('.film-reel');
          await new Promise(r => {
            if (v.readyState >= 2) return r();
            v.onloadeddata = r; setTimeout(r, 3000);
          });
          v.pause();
          await new Promise(r => { v.onseeked = r; v.currentTime = v.duration * 0.985; });
          const cv = getComputedStyle(v), cf = getComputedStyle(f);
          const R = e => e.getBoundingClientRect();
          const cta = R(s.querySelector(".btn-primary"));
          const copy = R(s.querySelector(".sub"));
          const band = R(f), screen = R(s);
          return {fit: cv.objectFit, layerBg: cf.backgroundImage,
                  poster: v.getAttribute("poster") ? v.getAttribute("poster").slice(0, 11) : null,
                  vw: v.videoWidth, vh: v.videoHeight, err: v.error && v.error.code,
                  inside: band.top >= screen.top - 1 && band.bottom <= screen.bottom + 1,
                  tall: (band.height / screen.height),
                  wide: Math.abs(band.width - screen.width) < 2,
                  layerWidth: band.width,
                  // Where the frame is actually painted. `contain` fits the
                  // tighter of the two axes, and which one that is has
                  // already flipped once here -- so it is computed, not
                  // assumed. The slack sits at the top, so the drawn rect
                  // starts at the layer's top, and its bottom is the number
                  // that decides whether the arms clear the buttons.
                  drawnBottom: (band.top - screen.top) + Math.min(
                      band.width * v.videoHeight / v.videoWidth, band.height),
                  drawnWidth: Math.min(
                      band.width, band.height * v.videoWidth / v.videoHeight),
                  // Where the scrim actually lets the film through, read off
                  // the gradient rather than assumed: the first and last stop
                  // whose alpha is zero. Chromium prints a fully transparent
                  // mix as `/ 0)`, and an opaque one with no slash at all.
                  clear: (() => {
                    const g = getComputedStyle(f, "::after").backgroundImage;
                    const stops = [...g.matchAll(/(rgba?\([^)]*\)|color\([^)]*\))\s+([\d.]+)%/g)];
                    const open = stops.filter(m => /\/\s*0\s*\)/.test(m[1]))
                                      .map(m => parseFloat(m[2]));
                    if (!open.length) return null;
                    const y = pc => band.top + band.height * pc / 100;
                    return {top: y(Math.min(...open)) - screen.top,
                            bottom: y(Math.max(...open)) - screen.top};
                  })(),
                  copyEnds: copy.bottom - screen.top,
                  ctaStarts: cta.top - screen.top};
        }""")
    ok(film["err"] is None, "the hero film decodes (%s)" % film["err"])
    ok(film["vw"] and film["vh"], "and has real dimensions (%sx%s)" % (film["vw"], film["vh"]))
    # The band's own box is allowed to reach past the copy and the buttons --
    # its edges are dissolved, that is the point. What must not is the part
    # the scrim leaves open, which is where the pair are actually visible.
    ok(film["clear"] is not None, "the scrim opens somewhere over the band")
    if film["clear"]:
        ok(film["clear"]["bottom"] <= film["ctaStarts"],
           "the film is clear above the buttons, not behind them "
           "(open to %dpx, buttons at %dpx)"
           % (film["clear"]["bottom"], film["ctaStarts"]))
        ok(film["clear"]["top"] >= film["copyEnds"],
           "and opens below the last line of copy (open from %dpx, copy ends %dpx)"
           % (film["clear"]["top"], film["copyEnds"]))
        ok(film["clear"]["bottom"] - film["clear"]["top"] > 60,
           "with a real window, not a seam (%dpx)"
           % (film["clear"]["bottom"] - film["clear"]["top"]))
    ok(film["inside"] and film["wide"], "the layer spans the screen and stays inside it")
    ok(film["fit"] == "contain",
       "the whole frame is shown, nothing cropped (%s)" % film["fit"])
    # The arms hang almost to the hem of the frame and they are what the shot
    # is about, so the *drawn* rectangle -- not the layer -- has to finish
    # above the buttons. Bottom-anchoring it put them underneath.
    # The subject touches the left and right edge of the source frame in all
    # 121 frames -- the camera pushes in and the shot is framed tight -- so
    # the footage's own crop is going to show whatever this does. Full-bleed
    # puts that edge on the screen edge, where it reads as the shot
    # continuing past the phone. A gutter of even a few pixels turns it into
    # a hard vertical line through an arm with canvas beyond it, which reads
    # as damage.
    ok(abs(film["drawnWidth"] - film["layerWidth"]) < 2,
       "the film bleeds to the screen edge, so the footage's own crop does "
       "not read as a cut (%dpx drawn into %dpx)"
       % (film["drawnWidth"], film["layerWidth"]))
    ok(film["drawnBottom"] <= film["ctaStarts"] + 26,
       "and finishes at the buttons, bar the ground under their feet "
       "(%dpx, buttons at %dpx)" % (film["drawnBottom"], film["ctaStarts"]))
    # The film's alpha is real, so anything painted behind it shows through --
    # and a still of a *different* moment of the same shot came through as a
    # second, offset pair. The still belongs on the video's own poster, which
    # a painted frame replaces, and nowhere else.
    ok(film["layerBg"] == "none",
       "nothing is painted behind the alpha film (%s)" % film["layerBg"][:40])
    ok(film["poster"] == "data:image/",
       "the still is carried by the poster instead (%s)" % film["poster"])
    # The scrim dissolves the band's two cut edges and must leave the middle
    # -- the embrace -- completely alone.
    stops = page.eval_on_selector(
        '.vl[data-screen="landing"] .film',
        "el => getComputedStyle(el, '::after').backgroundImage")
    ok("/ 0)" in stops or "/ 0 )" in stops or "transparent" in stops,
       "the scrim reaches fully clear somewhere over the embrace")

    # An icon inside a sentence must sit on the line, not above it.
    same_line = page.eval_on_selector(
        '.vl[data-screen="profile_view"] .t-caption',
        "el => { const s = el.querySelector('svg');"
        " return s ? Math.abs(s.getBoundingClientRect().top - el.getBoundingClientRect().top) < 8 : null; }")
    ok(same_line is True, "an inline icon stays on its line (%s)" % same_line)

    # ---- family scope: one edit, every element like it ----
    page.locator('.tab[data-target="chats"]').click()
    # Click the row itself, not whichever child sits under the cursor: the
    # picker deliberately selects the deepest element at the click point.
    page.eval_on_selector('.vl[data-screen="chats"] .row', "el => el.click()")
    opts = page.locator("#insp-scope option").count()
    ok(opts >= 2, "scope offers the element's families (%d options)" % opts)
    page.select_option("#insp-scope", "row")
    page.wait_for_timeout(150)
    page.locator('.seg button[data-pane="hover"]').click()
    page.select_option('select[data-set="transform"][data-state="hover"]', "translateY(-4px)")
    page.wait_for_timeout(200)
    css = page.locator("#export-css").input_value()
    ok(".row:hover" in css, "family rule is written against the class")
    ok('[data-el' not in css.split(".row:hover")[0][-60:], "and not against one id")
    # Every .row in the app, not just the ones on this screen.
    reach = page.evaluate(
        "() => { const all = document.querySelectorAll('.device .vl .row');"
        " let n = 0; all.forEach(e => { if (getComputedStyle(e).transitionDuration !== '0s') n++; });"
        " return [all.length, n]; }")
    ok(reach[0] == reach[1] and reach[0] > 5,
       "the rule reaches every .row across all screens (%d of %d)" % (reach[1], reach[0]))

    # An icon picked under family scope lands on all of them.
    page.locator('.seg button[data-pane="icon"]').click()
    page.locator("#glyphs button").nth(5).click()
    page.wait_for_timeout(250)
    icons = page.evaluate(
        "() => { const all = document.querySelectorAll('.device .vl .row');"
        " return [all.length, Array.from(all).filter(e => e.querySelector('svg')).length]; }")
    ok(icons[0] == icons[1], "an icon lands on the whole family (%d of %d)" % (icons[1], icons[0]))

    # Words stay where you put them, even under family scope: a chip carries
    # its own text and belongs to a family, which is the case that would break.
    page.locator('.tab[data-target="search_criteria"]').click()
    page.eval_on_selector('.vl[data-screen="search_criteria"] .chip', "el => el.click()")
    page.select_option("#insp-scope", "chip")
    page.locator('.seg button[data-pane="text"]').click()
    page.locator("#insp-text").fill("Changed one")
    page.wait_for_timeout(200)
    n_changed = page.evaluate(
        "() => Array.from(document.querySelectorAll('.device .vl .chip'))"
        ".filter(e => e.textContent.trim() === 'Changed one').length")
    total_chips = page.locator(".device .vl .chip").count()
    ok(n_changed == 1 and total_chips > 5,
       "text stays on the picked chip (%d of %d)" % (n_changed, total_chips))

    # But a colour under the same scope does reach the whole family.
    page.locator('.seg button[data-pane="paint"]').click()
    page.locator('input[type=text][data-set="background-color"][data-state="base"]').fill("#FAE83E")
    page.wait_for_timeout(250)
    gold = page.evaluate(
        "() => { const all = document.querySelectorAll('.device .vl .chip');"
        " return [all.length, Array.from(all).filter(e =>"
        " getComputedStyle(e).backgroundColor === 'rgb(250, 232, 62)').length]; }")
    ok(gold[0] == gold[1], "a colour reaches the whole family (%d of %d)" % (gold[1], gold[0]))

    page.locator("#reset-all").click()
    page.wait_for_timeout(200)

    # ---- box: padding, margin, borders ----
    page.locator('.tab[data-target="chats"]').click()
    page.eval_on_selector('.vl[data-screen="chats"] .row', "el => el.click()")
    page.select_option("#insp-scope", "")
    page.locator('.seg button[data-pane="box"]').click()
    page.select_option('select[data-set="padding-top"][data-state="base"]', "var(--space-6)")
    page.select_option('select[data-set="margin-left"][data-state="base"]', "var(--space-4)")
    page.wait_for_timeout(200)
    box = page.eval_on_selector('.vl[data-screen="chats"] .row',
        "el => { const c = getComputedStyle(el); return [c.paddingTop, c.marginLeft]; }")
    ok(box == ["24px", "16px"], "padding and margin apply from the 4pt scale (%s)" % box)

    # A border colour with no width paints nothing, so setting one implies the
    # other rather than leaving an invisible result.
    page.locator('input[type=text][data-set="border-color"][data-state="base"]').fill("#EA4545")
    page.wait_for_timeout(200)
    bd = page.eval_on_selector('.vl[data-screen="chats"] .row',
        "el => { const c = getComputedStyle(el);"
        " return [c.borderTopWidth, c.borderTopStyle, c.borderTopColor]; }")
    ok(bd == ["1px", "solid", "rgb(234, 69, 69)"], "border colour implies width and style (%s)" % bd)
    # ...and the colour half is per mode, while width and style are not.
    css = page.locator("#export-css").input_value()
    ok(':root:not([data-mode="dark"])' in css and "border-color" in css,
       "border colour is filed per mode")
    ok("border-width" in css.split("border-color")[0] or "border-width" in css,
       "border width is filed as shared")
    page.locator("#reset-all").click()
    page.wait_for_timeout(200)

    # ---- walking to inner and outer elements ----
    page.eval_on_selector('.vl[data-screen="chats"] .row .row-main strong', "el => el.click()")
    before = page.locator("#insp-name").inner_text()
    page.locator('#insp-walk button[data-walk="parent"]').click()
    page.wait_for_timeout(150)
    after = page.locator("#insp-name").inner_text()
    ok(before != after and "row-main" in after, "Outer selects the parent (%s -> %s)" % (before, after))
    page.locator('#insp-walk button[data-walk="child"]').click()
    page.wait_for_timeout(150)
    ok(page.locator("#insp-name").inner_text() != after, "Inner selects a child")
    # The screen root is the ceiling: the device frame is not the app.
    page.eval_on_selector('.vl[data-screen="chats"]', "el => el.click()")
    page.wait_for_timeout(150)
    ok(page.locator('#insp-walk button[data-walk="parent"]').is_disabled(),
       "cannot walk out past the screen itself")

    # ---- the icon library and its filter ----
    page.locator('.seg button[data-pane="icon"]').click()
    total = page.locator("#glyphs button").count()
    ok(total > 80, "the picker is a library (%d marks)" % total)
    page.locator("#icon-find").fill("arrow")
    page.wait_for_timeout(200)
    shown = page.eval_on_selector_all("#glyphs button", "els => els.filter(e => !e.hidden).length")
    ok(0 < shown < total, "the filter narrows it (%d of %d)" % (shown, total))
    page.locator("#icon-find").fill("")
    page.wait_for_timeout(150)

    # ---- custom CSS ----
    page.locator('.seg button[data-pane="code"]').click()
    page.locator("#custom-css").fill(".vl .t-h1 { text-transform: uppercase; }")
    page.wait_for_timeout(250)
    tt = page.eval_on_selector('.vl[data-screen="chats"] .t-h1',
                               "el => getComputedStyle(el).textTransform")
    ok(tt == "uppercase", "custom CSS applies live (%s)" % tt)
    ok("custom" in page.locator("#export-css").input_value(), "custom CSS reaches the export")
    page.locator("#custom-css").fill("")
    page.wait_for_timeout(200)

    # ---- custom JS ----
    page.locator("#custom-js").fill("$$('.t-h1').forEach(h => h.dataset.touched = '1');")
    page.locator("#js-run").click()
    page.wait_for_timeout(250)
    touched = page.eval_on_selector_all(".device .vl .t-h1[data-touched]", "els => els.length")
    ok(touched > 3, "custom JS runs against the screens (%d touched)" % touched)
    ok("ran cleanly" in page.locator("#js-out").inner_text(), "and reports success")
    # A thrown error must be reported, not left to kill the editor's listeners.
    page.locator("#custom-js").fill("this is not javascript(")
    page.locator("#js-run").click()
    page.wait_for_timeout(200)
    ok("is-bad" in (page.locator("#js-out").get_attribute("class") or ""),
       "a broken script reports itself (%s)" % page.locator("#js-out").inner_text()[:40])
    page.locator("#custom-js").fill("")
    # The editor must still work after that error.
    page.locator('.tab[data-target="landing"]').click()
    page.wait_for_timeout(200)
    ok(page.locator('.vl[data-screen="landing"].is-on').count() == 1,
       "the editor still works after a script error")

    # ---- saving: one list, and an active state ----
    page.locator("#reset-all").click()
    page.evaluate("() => localStorage.clear()")
    page.reload()
    page.wait_for_timeout(600)

    ok("nothing changed yet" in page.locator("#save-state").inner_text(),
       "a clean load says so")
    ok(page.locator("#kept-list li").count() == 0, "the list starts empty")
    ok(page.locator("#kept-none").is_visible(), "with a note explaining the two saves")

    # An edit of each kind, so a save has to carry more than CSS.
    page.locator('.tab[data-target="landing"]').click()
    page.eval_on_selector('.vl[data-screen="landing"] .btn-primary', "el => el.click()")
    page.locator('input[type=text][data-set="background-color"][data-state="base"]').fill("#FAE83E")
    page.locator('.seg button[data-pane="text"]').click()
    page.locator("#insp-text").fill("Saved words")
    page.locator('.seg button[data-pane="icon"]').click()
    page.locator('#glyphs button[data-glyph="heart"]').click()
    page.locator('.rail-row input[data-token="--canvas"]').fill("#DDEEFF")
    page.wait_for_timeout(300)
    ok("unsaved" in page.locator("#save-state").inner_text(), "edits mark it unsaved")

    # A draft is listed, but not switched on.
    page.locator("#save-draft").click()
    page.wait_for_timeout(300)
    ok(page.locator("#kept-list li").count() == 1, "the draft appears in the list")
    # inner_text() returns rendered text, and the tag is uppercased in CSS.
    ok("work in progress" in page.locator("#kept-list li").inner_text().lower(),
       "labelled as a draft")
    ok(page.locator("#kept-list li.is-active").count() == 0, "and is not active by itself")

    # Save names it AND switches it on.
    page.on("dialog", lambda d: d.accept("Gold CTA"))
    page.locator("#save-keep").click()
    page.wait_for_timeout(400)
    ok(page.locator("#kept-list li").count() == 2, "the saved state joins the same list")
    ok(page.locator("#kept-list li.is-active").count() == 1, "exactly one row is active")
    ok("Gold CTA" in page.locator("#kept-list li.is-active").inner_text(),
       "and it is the one just saved")

    # The point of all this: reload and the work is on screen.
    page.reload()
    page.wait_for_timeout(700)
    ok("showing" in page.locator("#save-state").inner_text(),
       "a reload says which state it opened with: %s" % page.locator("#save-state").inner_text())
    got = page.evaluate(
        "() => { const b = document.querySelector('.vl[data-screen=\"landing\"] .btn-primary');"
        " return [b.textContent.trim(), getComputedStyle(b).backgroundColor,"
        " !!b.querySelector('svg'),"
        " getComputedStyle(document.querySelector('.vl[data-screen=\"intro\"]')).backgroundColor]; }")
    ok(got[0] == "Saved words", "applied on load: the words (%s)" % got[0])
    ok(got[1] == "rgb(250, 232, 62)", "applied on load: the colour (%s)" % got[1])
    ok(got[2] is True, "applied on load: the icon")
    ok(got[3] == "rgb(221, 238, 255)", "applied on load: the token (%s)" % got[3])
    ok(page.locator("#kept-list li").count() == 2, "the list survives the reload")

    # Switching off returns the artifact to the design as authored.
    page.locator('#kept-list li.is-active button[data-active]').click()
    page.wait_for_timeout(300)
    ok(page.locator("#kept-list li.is-active").count() == 0, "it can be switched off")
    page.reload()
    page.wait_for_timeout(700)
    ok(page.eval_on_selector('.vl[data-screen="landing"] .btn-primary',
       "el => el.textContent.trim()") == "Create an account",
       "and then the artifact opens as authored")

    # Setting active from the list applies it immediately, not just next load.
    rows = page.locator("#kept-list li")
    idx = 0 if "Gold CTA" in rows.nth(0).inner_text() else 1
    rows.nth(idx).locator("button[data-active]").click()
    page.wait_for_timeout(400)
    ok(page.eval_on_selector('.vl[data-screen="landing"] .btn-primary',
       "el => el.textContent.trim()") == "Saved words",
       "setting active applies it there and then")

    # Deleting the active row must not leave the pointer dangling.
    page.locator('#kept-list li.is-active button[data-del]').click()
    page.wait_for_timeout(400)
    ok(page.locator("#kept-list li.is-active").count() == 0,
       "deleting the active row clears active")
    page.reload()
    page.wait_for_timeout(700)
    ok("could not be read" not in page.locator("#save-state").inner_text(),
       "so the next load is not left pointing at nothing")
    ok(page.locator("#kept-list li").count() == 1, "the draft is still listed")

    # Restore is separate from active: it applies without switching on.
    page.locator('#kept-list button[data-restore]').first.click()
    page.wait_for_timeout(300)
    ok(page.locator("#kept-list li.is-active").count() == 0,
       "Restore does not silently make it active")

    page.evaluate("() => localStorage.clear()")

    # ---- the save bar stays put ----
    # The whole point of moving it out of the column: on a long screen you
    # scroll what you are editing into view and Save must not leave with it.
    page.locator('.tab[data-target="privacy"]').click()
    page.evaluate("() => window.scrollTo(0, 3000)")
    page.wait_for_timeout(300)
    box = page.locator(".savebar").bounding_box()
    ok(box is not None and box["y"] <= 1, "the save bar is still at the top after scrolling")
    ok(page.locator("#save-keep").is_visible() and page.locator("#save-draft").is_visible(),
       "and both buttons are reachable from there")
    ok(page.locator(".insp #save-keep").count() == 0, "they are no longer inside the inspector")
    colours = page.evaluate(
        "() => [getComputedStyle(document.getElementById('save-keep')).backgroundColor,"
        " getComputedStyle(document.getElementById('save-draft')).backgroundColor]")
    ok(colours[0] == "rgb(30, 158, 99)", "Save is green (%s)" % colours[0])
    ok(colours[1] == "rgb(62, 123, 232)", "Save draft is blue (%s)" % colours[1])
    # A fixed bar that covers the first line of the page is a worse trade.
    overlap = page.evaluate(
        "() => { const h = document.querySelector('.savebar').getBoundingClientRect().height;"
        " return getComputedStyle(document.body).paddingTop === h.toFixed(3) + 'px'"
        " || parseFloat(getComputedStyle(document.body).paddingTop) >= h - 1; }")
    ok(overlap, "the body reserves the bar's height instead of hiding under it")
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(200)

    ok(not errors, "no JS errors after driving it: %s" % errors[:3])

    page.locator("#reset-all").click()
    page.locator("#rail-reset").click()
    page.locator('.tab[data-target="landing"]').click()
    page.wait_for_timeout(500)
    page.screenshot(path="/tmp/editor-light.png")
    page.locator('#modes button[data-mode="dark"]').click()
    page.locator('.tab[data-target="chats"]').click()
    page.wait_for_timeout(500)
    page.locator(".device").screenshot(path="/tmp/editor-dark.png")
    b.close()

print()
print("%d failed" % len(fails))
sys.exit(1 if fails else 0)
