#!/usr/bin/env python3
"""What the light-mode artifact borrows rather than redraws.

Two sources, both read at build time so neither can quietly drift:

  * templates/_icons.html -- the app's committed icon registry. Taken as
    viewBox + inner markup rather than as rendered <svg> strings, because the
    artifact re-renders every glyph whenever the stroke, cap or size control
    moves. A rendered string would freeze the spec the page exists to change.

  * the design system document -- the four mascots, already inline as base64
    webp. Chapter 06 gives them a purple pair and a gold pair; the order they
    appear in the document is the order the captions describe, so the index is
    the identity. This file is NOT in the repo: it is "Velvt -- Design System
    & Style Guide v1.0", uploaded to a chat session rather than committed.
    Point LIGHTMODE_GUIDE_HTML at wherever it lands in a fresh session
    (`export LIGHTMODE_GUIDE_HTML=/path/to/velvt-style-guide.html`) before
    calling mascots(); icons() and brand() need no upload and always work.
"""
import os
import pathlib
import re

TEMPLATES = pathlib.Path("/home/user/claude/templates")
STATIC = pathlib.Path("/home/user/claude/static")
GUIDE = pathlib.Path(os.environ.get("LIGHTMODE_GUIDE_HTML", "")) if os.environ.get(
    "LIGHTMODE_GUIDE_HTML") else None

# Chapter 06's own captions, in document order.
MASCOT_NAMES = [
    ("purple-a", "Purple - male"),
    ("purple-b", "Purple - female"),
    ("gold-a", "Gold - male"),
    ("gold-b", "Gold - female"),
]


def icons():
    """ICONS as {name: [viewBox, inner-markup]}, plus SLOTS and the spec."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(loader=FileSystemLoader(str(TEMPLATES)),
                      autoescape=select_autoescape(["html"]))
    mod = env.get_template("_icons.html").make_module()
    glyphs = {name: [g[0], g[1]] for name, g in mod.ICONS.items()}
    return {
        "glyphs": glyphs,
        "slots": dict(mod.SLOTS),
        "stroke": mod.ICON_STROKE,
        "cap": mod.ICON_CAP,
    }


def _uri(path, mime):
    import base64
    return "data:%s;base64,%s" % (
        mime, base64.b64encode(path.read_bytes()).decode("ascii"))


def brand():
    """The landing's own art, inlined so the artifact is self-contained.

    The hero film is the shipped asset, not a redrawing of it: the webm carries
    a real alpha channel (the background was cut per frame with u2net
    segmentation), so it composites onto a light ground as readily as onto the
    dark one. Its mp4 sibling cannot -- that file is pre-composited on --ink
    for Safari, which has no VP9-alpha support, so it is deliberately left out
    here and flagged instead.

    The wordmark is artwork used as a mask, not a typeface, so the letterforms
    stay exactly as drawn while whatever fills them stays ours.
    """
    return {
        "film": _uri(STATIC / "velvt-hero.webm", "video/webm"),
        "still": _uri(STATIC / "velvt-hero.webp", "image/webp"),
        "logo": _uri(STATIC / "velvt-logo.svg", "image/svg+xml"),
    }


def mascots():
    """The four velvet characters as {key: data-uri}.

    Requires LIGHTMODE_GUIDE_HTML -- see the module docstring. Not needed by
    the landing screen as shipped, which uses the app's own hero film instead;
    kept for the onboarding / empty-state / match-reveal screens Stage B adds.
    """
    if GUIDE is None:
        raise SystemExit(
            "LIGHTMODE_GUIDE_HTML is not set -- point it at the uploaded "
            "'Velvt Design System & Style Guide v1.0' HTML file to read the "
            "four mascots out of chapter 06")
    found = re.findall(r"data:image/[a-z+]+;base64,[A-Za-z0-9+/=]+",
                       GUIDE.read_text(encoding="utf-8"))
    if len(found) != len(MASCOT_NAMES):
        raise SystemExit(
            "expected %d mascots in the guide, found %d -- the document "
            "changed shape, so the captions can no longer be trusted to "
            "match by position" % (len(MASCOT_NAMES), len(found)))
    return {key: uri for (key, _label), uri in zip(MASCOT_NAMES, found)}


if __name__ == "__main__":
    ic = icons()
    ms = mascots()
    print("glyphs: %d" % len(ic["glyphs"]))
    print("slots:  %d" % len(ic["slots"]))
    print("spec:   stroke=%s cap=%s" % (ic["stroke"], ic["cap"]))
    print("mascots:", ", ".join("%s %dB" % (k, len(v)) for k, v in ms.items()))
