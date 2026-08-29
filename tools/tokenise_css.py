#!/usr/bin/env python3
"""Turn velvt.css's colour literals back into the tokens they were derived from.

    python3 tools/tokenise_css.py            # report only
    python3 tools/tokenise_css.py --write    # rewrite templates/velvt.css

A second palette is impossible while the first one is written out by hand in
192 places. `rgba(168, 85, 247, .42)` is --violet-crest at 42% alpha, but
nothing in the file says so, so a light palette would repaint the tokens and
leave every one of those literals painting the dark design underneath.

The transform is mechanical and reversible in meaning: a literal whose RGB
equals a token's RGB becomes

    color-mix(in srgb, var(--that-token) <alpha>%, transparent)

which resolves to exactly the same colour -- color-mix against `transparent`
in srgb premultiplies, so 42% of a colour *is* that colour at alpha .42.
tools/check_css_tokens.py proves that in a real browser rather than on the
strength of this paragraph.

White and black are not in the palette and become --gleam and --shade, which
exist so the two of them can stop meaning "lighter" and "darker" literally and
start meaning "toward the light side of this mode" and "toward its dark side".
On a light ground an inner glow is not white and a shadow is not pure black.

What is deliberately left alone: a handful of colours that are near a token
but not equal to it. Snapping them to the nearest token would be a design
change smuggled in as a refactor, and this script is not allowed to make one.
"""

import re
import sys

CSS = "templates/velvt.css"

# Added to :root by this script if absent. Not in the original palette because
# the original palette never needed to name them -- there was one mode.
NEW_TOKENS = [
    ("--gleam", "#FFFFFF", "the light side of this mode: inner glows, gleams"),
    ("--shade", "#000000", "its dark side: shadows, scrims, wells"),
]


def rgb_of(value):
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def percent(alpha):
    """An alpha as the percentage color-mix wants, without float noise."""
    text = ("%.4f" % (float(alpha) * 100)).rstrip("0").rstrip(".")
    return text or "0"


def replacement(name, alpha):
    """How a token plus an alpha is written in the tokenised sheet.

    A fully transparent literal is the exception, and it is not cosmetic.
    `rgba(11, 7, 19, 0)` and `transparent` look identical alone but
    interpolate differently: a gradient running from the first fades through
    the ink, and one running from the second fades through black. That is the
    grey-ghost seam at the top of every scrim, and color-mix(... 0%,
    transparent) would reintroduce it in 8 places. Relative colour syntax
    keeps the channels and drops only the alpha.
    """
    if alpha is None or float(alpha) >= 1:
        return "var(%s)" % name
    if float(alpha) == 0:
        return "rgb(from var(%s) r g b / 0)" % name
    return "color-mix(in srgb, var(%s) %s%%, transparent)" % (name, percent(alpha))


def transform(css):
    root = re.search(r":root\s*\{.*?\n\s*\}", css, re.S)
    tokens = dict(re.findall(r"^\s*(--[\w-]+)\s*:\s*([^;]+);", root.group(0), re.M))
    by_rgb = {}
    for name, value in tokens.items():
        got = rgb_of(value.strip())
        # First definition wins, so a duplicated colour keeps the name that
        # appears first in the file rather than whichever dict order gave.
        if got and got not in by_rgb:
            by_rgb[got] = name
    by_rgb.setdefault((255, 255, 255), "--gleam")
    by_rgb.setdefault((0, 0, 0), "--shade")

    head, body = css[:root.end()], css[root.end():]
    counts, skipped = {}, {}

    def swap(match):
        r, g, b, a = match.group(1), match.group(2), match.group(3), match.group(4)
        key = (int(r), int(g), int(b))
        name = by_rgb.get(key)
        if name is None:
            skipped[key] = skipped.get(key, 0) + 1
            return match.group(0)
        counts[name] = counts.get(name, 0) + 1
        return replacement(name, a)

    body = re.sub(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)",
        swap, body)

    # Bare hex outside :root, same idea. #000/#FFF dominate and are exactly
    # what --shade and --gleam are for.
    def swap_hex(match):
        key = rgb_of(match.group(0))
        name = by_rgb.get(key) if key else None
        if name is None:
            if key:
                skipped[key] = skipped.get(key, 0) + 1
            return match.group(0)
        counts[name] = counts.get(name, 0) + 1
        return "var(%s)" % name

    body = re.sub(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", swap_hex, body)

    if "--gleam" not in tokens:
        addition = "".join(
            "\n      %s:%s%s;  /* %s */" % (name, " " * max(1, 14 - len(name)), value, why)
            for name, value, why in NEW_TOKENS)
        head = head[:head.rstrip().rfind("}")] + addition + "\n    }\n"

    return head + body, counts, skipped


def main():
    with open(CSS, "r", encoding="utf-8") as fh:
        css = fh.read()
    out, counts, skipped = transform(css)

    print("replaced %d literal(s):" % sum(counts.values()))
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print("   %-16s x%d" % (name, n))
    print("\nleft as literals (near a token, but not equal to one): %d"
          % sum(skipped.values()))
    for key, n in sorted(skipped.items(), key=lambda kv: -kv[1]):
        print("   rgb%s x%d" % (key, n))

    if "--write" in sys.argv:
        with open(CSS, "w", encoding="utf-8") as fh:
            fh.write(out)
        print("\nwrote " + CSS)
    else:
        print("\n(report only -- pass --write to apply)")


if __name__ == "__main__":
    main()
