"""Verify the landing hero fits above the buttons, in every language.

    python tools/check_hero_fits.py            # against a running dev server
    python tools/check_hero_fits.py :5099      # or a specific port

Needs a browser, which is why it lives here rather than beside the check_*.py
suites: those run anywhere Python does.

Why it exists: .wiz-fit clips with overflow:hidden, so when the hero grew
taller than its box the lede was drawn *on top of* the buttons rather than
scrolling. Nothing in the page's scrollHeight changed, so every check that
measured document overflow -- which was all of them -- reported the page as
clean while a phone showed text through text.

So this measures three things a person would notice instead:
  * the hero's content fits the box it is given
  * the lede is inside that box rather than clipped out of it
  * nothing is painted over the first button, by hit-test rather than by
    rectangle (getBoundingClientRect ignores ancestor clipping, and reports
    an overlap for content that is merely scrolled out of sight)
"""

import sys

BASE = "http://127.0.0.1" + (sys.argv[1] if len(sys.argv) > 1 else ":5099")

# Widths and heights of phones that exist, including the short viewports a
# browser leaves once its own chrome is on screen.
SIZES = [(360, 640), (412, 690), (390, 700), (360, 740),
         (412, 780), (390, 844), (412, 915)]

PROBE = """() => {
  const body = document.querySelector('.wiz-body');
  const lede = document.querySelector('.landing-lede');
  const btn  = document.querySelector('.landing-actions .btn');
  if (!body || !lede || !btn) return {missing: true};
  const br = body.getBoundingClientRect(), lr = lede.getBoundingClientRect();
  const r = btn.getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + 4);
  return {
    over: body.scrollHeight - body.clientHeight,
    ledeInside: lr.top >= br.top - 1 && lr.bottom <= br.bottom + 1,
    buttonClear: !!(hit && hit.closest('.landing-actions')),
    ledeFont: parseFloat(getComputedStyle(lede).fontSize),
  };
}"""

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright is not installed — skipping (this check needs a browser)")
    raise SystemExit(0)

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

failures = []
with sync_playwright() as p:
    kw = {"args": ["--no-sandbox"]}
    import os
    if os.path.exists(CHROME):
        kw["executable_path"] = CHROME
    browser = p.chromium.launch(**kw)
    for lang in ("en", "nl"):
        for w, h in SIZES:
            ctx = browser.new_context(viewport={"width": w, "height": h})
            page = ctx.new_page()
            page.goto(f"{BASE}/lang/{lang}?next=/", wait_until="domcontentloaded")
            page.wait_for_timeout(300)
            m = page.evaluate(PROBE)
            ctx.close()
            if m.get("missing"):
                print(f"FAIL  {lang} {w}x{h}: the hero did not render")
                failures.append(f"{lang} {w}x{h}")
                continue
            # 14px is the floor for body copy someone is expected to read on a
            # phone; shrinking past it to win space is not a fix.
            ok = (m["over"] <= 1 and m["ledeInside"] and m["buttonClear"]
                  and m["ledeFont"] >= 14)
            print(f"{'ok  ' if ok else 'FAIL'}  {lang} {w}x{h}"
                  f"  overflow={m['over']}px lede_visible={m['ledeInside']}"
                  f" button_clear={m['buttonClear']} lede={m['ledeFont']}px")
            if not ok:
                failures.append(f"{lang} {w}x{h}")
    browser.close()

print()
if failures:
    print(f"{len(failures)} viewport(s) failed: " + ", ".join(failures))
    raise SystemExit(1)
print("the hero fits in every language at every size tested")
