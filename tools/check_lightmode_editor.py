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

    # ---- saving: draft and kept ----
    page.locator("#reset-all").click()
    page.evaluate("() => localStorage.clear()")
    page.reload()
    page.wait_for_timeout(600)

    ok("nothing changed yet" in page.locator("#save-state").inner_text(),
       "a clean load says so")
    ok(page.locator("#draft-row").is_hidden(), "no draft offered when none exists")

    # Make an edit of each kind, so the save has to carry more than CSS.
    page.locator('.tab[data-target="landing"]').click()
    page.eval_on_selector('.vl[data-screen="landing"] .btn-primary', "el => el.click()")
    page.locator('input[type=text][data-set="background-color"][data-state="base"]').fill("#FAE83E")
    page.locator('.seg button[data-pane="text"]').click()
    page.locator("#insp-text").fill("Saved words")
    page.locator('.seg button[data-pane="icon"]').click()
    page.locator('#glyphs button[data-glyph="heart"]').click()
    page.locator('.rail-row input[data-token="--canvas"]').fill("#DDEEFF")
    page.locator('.seg button[data-pane="code"]').click()
    page.locator("#custom-css").fill(".vl .t-h1 { font-style: italic; }")
    page.wait_for_timeout(300)
    ok("unsaved" in page.locator("#save-state").inner_text(), "edits mark it unsaved")

    page.locator("#save-draft").click()
    page.wait_for_timeout(250)
    ok("draft saved" in page.locator("#save-state").inner_text(), "draft saves")

    # The real test: reload, and see whether the draft actually comes back.
    page.reload()
    page.wait_for_timeout(600)
    ok("draft is waiting" in page.locator("#save-state").inner_text(),
       "the draft is offered after a reload, not forced")
    fresh = page.eval_on_selector('.vl[data-screen="landing"] .btn-primary',
                                  "el => el.textContent.trim()")
    ok(fresh == "Create an account", "and the page loads clean until you ask for it")

    page.locator("#draft-restore").click()
    page.wait_for_timeout(400)
    got = page.evaluate(
        "() => { const b = document.querySelector('.vl[data-screen=\"landing\"] .btn-primary');"
        " const c = getComputedStyle(b);"
        " return [b.textContent.trim(), c.backgroundColor, !!b.querySelector('svg'),"
        " getComputedStyle(document.querySelector('.vl[data-screen=\"intro\"]')).backgroundColor,"
        " getComputedStyle(document.querySelector('.vl[data-screen=\"landing\"] .t-h1')"
        " || document.querySelector('.vl .t-h1')).fontStyle,"
        " document.getElementById('custom-css').value.length]; }")
    ok(got[0] == "Saved words", "restored: the words (%s)" % got[0])
    ok(got[1] == "rgb(250, 232, 62)", "restored: the per-element colour (%s)" % got[1])
    ok(got[2] is True, "restored: the icon")
    ok(got[3] == "rgb(221, 238, 255)", "restored: the token (%s)" % got[3])
    ok(got[4] == "italic", "restored: the custom CSS (%s)" % got[4])
    ok(got[5] > 0, "restored: the CSS text is back in the box")

    # Kept versions are named, listed, and survive a draft being discarded.
    page.on("dialog", lambda d: d.accept("Gold CTA"))
    page.locator("#save-keep").click()
    page.wait_for_timeout(300)
    ok(page.locator("#kept-list li").count() == 1, "a kept version is listed")
    ok("Gold CTA" in page.locator("#kept-list li b").inner_text(), "under the name given")
    page.locator("#draft-discard").click()
    page.wait_for_timeout(200)
    ok(page.locator("#kept-list li").count() == 1,
       "discarding the draft leaves kept versions alone")

    page.locator("#reset-all").click()
    # Reset closes the inspector, so the code pane has to be reopened before
    # its textarea can be reached.
    page.eval_on_selector('.vl[data-screen="landing"] .btn-primary', "el => el.click()")
    page.locator('.seg button[data-pane="code"]').click()
    page.locator("#custom-css").fill("")
    page.wait_for_timeout(250)
    page.locator('#kept-list button[data-restore="0"]').click()
    page.wait_for_timeout(400)
    ok(page.eval_on_selector('.vl[data-screen="landing"] .btn-primary',
       "el => el.textContent.trim()") == "Saved words", "a kept version restores")

    page.locator('#kept-list button[data-del="0"]').click()
    page.wait_for_timeout(250)
    ok(page.locator("#kept-list li").count() == 0, "and can be deleted")
    ok(page.locator("#kept-none").is_visible(), "the empty note comes back")

    page.evaluate("() => localStorage.clear()")

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
