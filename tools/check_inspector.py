"""Verify the design inspector names the right token for what it clicked.

    python tools/check_inspector.py            # against a running dev server
    python tools/check_inspector.py :5099      # or a specific port

Needs a browser and an admin session, which is why it lives here rather than
beside the check_*.py suites: the inspector is a few hundred lines of script
inside /admin/design, and none of it runs under a Python test client.

Why it exists: the inspector used to resolve every token against a probe
element and then look the clicked element's *computed* colour up in that map.
Chromium serialises a color-mix() result as `color(srgb ...)` and a plain
var() as `rgb(...)`, so a mixed colour could never match, and
tools/tokenise_css.py had already rewritten 192 literals into color-mix()
over the palette. The result: nearly every colour in the app reported as
"written straight into the stylesheet rather than as a token", on the one
screen whose whole job is to say which token to reach for. Nothing failed --
the inspector was confidently, silently wrong, and no check looked at it.

So this asserts the two directions that matter, the way the other suites do:
a colour that *is* tokenised resolves to its token (including through a mix),
and a colour that genuinely is a literal is still called one.
"""

import os
import sys

BASE = "http://127.0.0.1" + (sys.argv[1] if len(sys.argv) > 1 else ":5099")
ADMIN_PASSWORD = os.environ.get("APP_ADMIN_PASSWORD", "admin12345")

# Each case: the preview chip to open, a selector inside the frame, whether to
# hover it first, and what the inspector must then say. `tokens` are token
# names that have to appear; `literal` is a fragment that has to appear when
# the colour really is written into the sheet.
CASES = [
    # The case from the bug report: a primary button's hover background is
    # color-mix(in srgb, var(--violet) 88%, var(--shade)) -- two real tokens,
    # and it used to read as an untokenised grey.
    ("Sign in", "button.btn", True,
     {"tokens": ["--violet", "--shade"]}),
    # Not hovered, the same button is a plain var(--violet).
    ("Sign in", "button.btn", False,
     {"tokens": ["--violet"]}),
    # A filled field's ground is --field, and it is set with the `background`
    # shorthand rather than background-color -- which the inspector has to
    # read too, or it calls the colour inherited.
    ("Sign in", "input[name=username]", False,
     {"tokens": ["--field"]}),
    # A deliberate literal stays a literal. 38 near-palette colours are left
    # as literals on purpose, and calling them tokens would be the same bug
    # pointing the other way.
    ("Edit profile", ".photo-tile-add", True,
     {"literal": "written straight into the stylesheet"}),
    # The palette holds more than colours, and clicking a button used to say
    # nothing about the face it is set in.
    ("Sign in", "button.btn", False,
     {"tokens": ["--sans"]}),
]

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright is not installed — skipping (this check needs a browser)")
    raise SystemExit(0)

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

failures = []
with sync_playwright() as p:
    kw = {"args": ["--no-sandbox"]}
    if os.path.exists(CHROME):
        kw["executable_path"] = CHROME
    browser = p.chromium.launch(**kw)
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.fill("input[name=username]", "admin")
    page.fill("input[name=password]", ADMIN_PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_timeout(600)
    page.goto(f"{BASE}/admin/design", wait_until="domcontentloaded")
    page.wait_for_timeout(1200)

    open_chip = None
    for chip, selector, hover, want in CASES:
        if chip != open_chip:
            page.click(f".dsg-chip:has-text('{chip}')")
            page.wait_for_timeout(1800)
            open_chip = chip
        frame = page.frame_locator("#dsg-frame")
        target = frame.locator(selector).first
        label = f"{chip} {selector}" + (" :hover" if hover else "")

        if target.count() == 0:
            print(f"FAIL  {label}: not on the screen")
            failures.append(label)
            continue

        # A hover has to be a real pointer move; dispatching a click alone
        # never puts the element into :hover, and the hover rule is the whole
        # point of half these cases.
        if hover:
            target.hover()
            page.wait_for_timeout(150)
            target.click(force=True)
        else:
            # And a non-hover case has to park the pointer somewhere else
            # first, or it inherits the previous case's :hover and quietly
            # asserts the wrong state.
            page.mouse.move(0, 0)
            page.wait_for_timeout(150)
            target.dispatch_event("click")
        page.wait_for_timeout(300)

        said = page.locator("#dsg-el-tokens").inner_text()
        missing = [t for t in want.get("tokens", []) if t not in said]
        if want.get("literal") and want["literal"] not in said:
            missing.append(want["literal"])
        # A token case must not also be talking about literals, or the report
        # is right by accident while still telling someone the wrong thing.
        if want.get("tokens") and "written straight into the stylesheet" in said:
            missing.append("(reported as a literal)")

        one_line = " / ".join(x.strip() for x in said.splitlines() if x.strip())
        if missing:
            print(f"FAIL  {label}: missing {missing} — said: {one_line}")
            failures.append(label)
        else:
            print(f"ok    {label}  — {one_line}")

    browser.close()

print()
if failures:
    print(f"{len(failures)} inspector case(s) failed: " + ", ".join(failures))
    raise SystemExit(1)
print("the inspector names the right token for everything it was asked about")
