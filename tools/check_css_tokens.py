#!/usr/bin/env python3
"""Prove the tokenised stylesheet paints exactly what the literals did.

    python3 tools/check_css_tokens.py

tools/tokenise_css.py rewrites 192 colour literals into color-mix() over the
palette. That is only safe if every one of them resolves to the same colour it
did before, and "color-mix against transparent premultiplies" is a claim about
a browser, not something a Python test can assert. So this asks a real one.

Each replacement is evaluated twice in Chromium -- once as the original
literal, once as its color-mix form -- and the computed colours compared. A
single mismatch means the refactor changed the design, which is the one thing
it was not allowed to do.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from playwright.sync_api import sync_playwright   # noqa: E402
from tokenise_css import rgb_of, replacement        # noqa: E402

CSS = os.path.join(ROOT, "templates", "velvt.css")

# Returns each colour as [r, g, b, a*255] so the two serialisations compare.
COMPARE = """([a, b]) => {
  const el = document.getElementById('p');
  const read = (value) => {
    el.style.color = '';
    el.style.color = value;
    const s = getComputedStyle(el).color;
    let m = s.match(/^rgba?\\(([^)]+)\\)$/);
    if (m) {
      const n = m[1].split(/[,\\s/]+/).filter(Boolean).map(Number);
      return [n[0], n[1], n[2], (n.length > 3 ? n[3] : 1) * 255];
    }
    m = s.match(/^color\\(srgb\\s+([^)]+)\\)$/);
    if (m) {
      const n = m[1].split(/[\\s/]+/).filter(Boolean).map(Number);
      return [n[0] * 255, n[1] * 255, n[2] * 255, (n.length > 3 ? n[3] : 1) * 255];
    }
    return [NaN, NaN, NaN, NaN];
  };
  return [read(a), read(b)];
}"""


def pairs():
    """(literal, color-mix form) for every replacement the transform makes."""
    with open(CSS, "r", encoding="utf-8") as fh:
        css = fh.read()
    root = re.search(r":root\s*\{.*?\n\s*\}", css, re.S)
    tokens = dict(re.findall(r"^\s*(--[\w-]+)\s*:\s*([^;]+);", root.group(0), re.M))
    by_rgb = {}
    for name, value in tokens.items():
        got = rgb_of(value.strip())
        if got and got not in by_rgb:
            by_rgb[got] = name

    out = []
    body = css[root.end():]
    for match in re.finditer(
            r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", body):
        key = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        name = by_rgb.get(key)
        if name is None:
            continue
        # The same function the transform uses, so this cannot pass by
        # testing a rule the rewrite does not actually apply.
        out.append((match.group(0), replacement(name, match.group(4))))
    return sorted(set(out))


def main():
    todo = pairs()
    if not todo:
        print("no literals left to compare -- has the file already been "
              "tokenised? Run this against the pre-transform file.")
        return 0

    with open(CSS, "r", encoding="utf-8") as fh:
        root_block = re.search(r":root\s*\{.*?\n\s*\}", fh.read(), re.S).group(0)

    page_html = (
        "<!doctype html><meta charset=utf-8><style>%s\n"
        ":root{--gleam:#FFFFFF;--shade:#000000;}</style><b id=p>x</b>"
        % root_block)

    mismatches = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = browser.new_page()
        page.set_content(page_html)
        for literal, mixed in todo:
            got = page.evaluate(COMPARE, [literal, mixed])
            # Compared as numbers, never as strings: Chromium serialises a
            # color-mix() result as `color(srgb ...)` and a literal as
            # `rgba(...)`, so the same colour prints two different ways and a
            # string comparison calls every single replacement a failure.
            if max(abs(x - y) for x, y in zip(got[0], got[1])) > 0.51:
                mismatches.append((literal, mixed, got[0], got[1]))
        browser.close()

    print("compared %d distinct replacement(s)" % len(todo))
    for literal, mixed, was, now in mismatches:
        print("FAIL  %s\n      %s\n      %s != %s" % (literal, mixed, was, now))
    if mismatches:
        print("\n%d replacement(s) change the colour" % len(mismatches))
        return 1
    print("every replacement resolves to the colour it replaced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
