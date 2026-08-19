"""Prove the durable save path, the one localStorage could not do.

The bug this exists for: in the artifact viewer, storage is partitioned per
load, so a write succeeds, reads back fine in the same session, and is gone on
reload. Nothing in a file:// test catches that, because there localStorage is
real. So this test does the opposite -- it turns localStorage OFF, stubs the
artifact capability, and asserts the page saves by publishing a new version of
itself, then loads that published HTML and checks the state comes back.

Served over HTTP, not file://, because the save path fetches its own URL to get
pristine source and file:// fetches are blocked.
"""
import json
import pathlib
import threading
import http.server
import functools
import re

from playwright.sync_api import sync_playwright

SRC = pathlib.Path("/tmp/velvt-light.html")
ROOT = pathlib.Path("/tmp/pubtest")
ROOT.mkdir(exist_ok=True)
fails = []


def ok(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        fails.append(what)


# The shell wraps the artifact source in a real document; reproduce that here
# so the fetch-and-splice path sees what it would see in production.
(ROOT / "index.html").write_text(
    "<!doctype html>\n<html>\n<head>\n<meta charset='utf-8'>\n</head>\n<body>\n"
    + SRC.read_text(encoding="ascii") + "\n</body>\n</html>", encoding="utf-8")

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d/index.html" % port

# Storage off, capability on -- the artifact viewer's actual shape.
STUB = """
(() => {
  try {
    Object.defineProperty(window, 'localStorage', {
      get() { throw new DOMException('denied', 'SecurityError'); }
    });
  } catch (e) {}
  window.__published = null;
  window.claude = {
    use: (name) => Promise.resolve(name === 'artifact' ? {
      publish: (html) => { window.__published = html; return Promise.resolve({version: 'v2'}); }
    } : null)
  };
})();
"""

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    page = b.new_page(viewport={"width": 1400, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(STUB)
    page.goto(URL)
    page.wait_for_timeout(700)

    ok(page.evaluate("() => { try { return !window.localStorage; } catch (e) { return true; } }"),
       "localStorage is genuinely unavailable in this run")
    ok(not errors, "no JS errors with storage denied: %s" % errors[:2])
    ok(page.locator("#save-note").is_hidden(),
       "no fallback warning shown when the capability is there")

    # Make one edit of each kind, then save the draft.
    page.eval_on_selector('.vl[data-screen="landing"] .btn-primary', "el => el.click()")
    page.locator('input[type=text][data-set="background-color"][data-state="base"]').fill("#FAE83E")
    page.locator('.rail-row input[data-token="--canvas"]').fill("#DDEEFF")
    page.locator('.seg button[data-pane="text"]').click()
    page.locator("#insp-text").fill("Published words")
    page.wait_for_timeout(250)
    page.locator("#save-draft").click()
    page.wait_for_timeout(900)

    published = page.evaluate("() => window.__published")
    ok(bool(published), "a save with no localStorage still publishes")
    ok("survives a reload" in page.locator("#save-state").inner_text(),
       "and says so: %s" % page.locator("#save-state").inner_text())

    if published:
        ok(published.lstrip().lower().startswith("<!doctype html"),
           "the published page is a complete document")
        ok('id="saved-state"' in published, "it carries the state block")
        m = re.search(r'<script type="application/json" id="saved-state">(.*?)</script>',
                      published, re.S)
        ok(bool(m), "the block is well formed")
        if m:
            raw = m.group(1)
            ok("\\u003c" in raw or "<" not in raw,
               "any < inside the JSON is escaped so it cannot close the tag early")
            state = json.loads(raw.replace("\\u003c", "<"))
            ok(state["draft"]["tokens"]["light"]["--canvas"] == "#ddeeff",
               "the token edit is in the published state")
            ok(state["draft"]["dom"]["text"], "the text edit is in the published state")
        ok(published.count('<script type="application/json" id="saved-state">') == 1,
           "exactly one state block (%d)"
           % published.count('<script type="application/json" id="saved-state">'))
        # It must not have swallowed the page: the screens are still there.
        ok(published.count('data-screen="') >= 30, "the screens survived the splice")

        # The real proof: serve the published page and see the state come back.
        (ROOT / "v2.html").write_text(published, encoding="utf-8")
        page2 = b.new_page(viewport={"width": 1400, "height": 1000})
        errs2 = []
        page2.on("pageerror", lambda e: errs2.append(str(e)))
        page2.add_init_script(STUB)
        page2.goto("http://127.0.0.1:%d/v2.html" % port)
        page2.wait_for_timeout(700)
        ok(not errs2, "the published page loads clean: %s" % errs2[:2])
        ok("draft is waiting" in page2.locator("#save-state").inner_text(),
           "the reloaded page knows a draft is there — the bug that started this")
        page2.locator("#draft-restore").click()
        page2.wait_for_timeout(400)
        got = page2.evaluate(
            "() => [document.querySelector('.vl[data-screen=\"landing\"] .btn-primary')"
            ".textContent.trim(), getComputedStyle(document.querySelector("
            "'.vl[data-screen=\"intro\"]')).backgroundColor]")
        ok(got[0] == "Published words", "restored across a reload: the words (%s)" % got[0])
        ok(got[1] == "rgb(221, 238, 255)", "restored across a reload: the token (%s)" % got[1])

    # And a second save must replace the block, not append another.
    page.locator("#save-draft").click()
    page.wait_for_timeout(800)
    again = page.evaluate("() => window.__published")
    ok(again and again.count('<script type="application/json" id="saved-state">') == 1,
       "saving twice keeps one block (%d)"
       % (again or "").count('<script type="application/json" id="saved-state">'))

    # With no capability and no storage, the page must say so rather than
    # pretending -- the exact failure the user hit.
    page3 = b.new_page(viewport={"width": 1400, "height": 1000})
    page3.add_init_script(STUB.replace("name === 'artifact' ?", "false ?"))
    page3.goto(URL)
    page3.wait_for_timeout(700)
    ok(page3.locator("#save-note").is_visible(), "with nowhere to save, it warns up front")
    ok("Copy state" in page3.locator("#save-note").inner_text(),
       "and points at the path that always works: %s" % page3.locator("#save-note").inner_text())
    page3.locator("#save-draft").click()
    page3.wait_for_timeout(400)
    ok("this tab only" in page3.locator("#save-state").inner_text(),
       "a save with nowhere to go is reported honestly: %s"
       % page3.locator("#save-state").inner_text())

    # Copy/Load state works with neither storage nor capability.
    page3.locator("#state-copy").click()
    page3.wait_for_timeout(200)
    blob = page3.locator("#state-box").input_value()
    ok(len(blob) > 20 and blob.startswith("{"), "Copy state produces a portable blob")
    page3.locator("#reset-all").click()
    page3.wait_for_timeout(200)
    page3.locator("#state-box").fill(blob)
    page3.locator("#state-paste").click()
    page3.wait_for_timeout(300)
    ok("state loaded" in page3.locator("#save-state").inner_text(), "and Load state takes it back")

    b.close()

srv.shutdown()
print()
print("%d failed" % len(fails))
