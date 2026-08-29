#!/usr/bin/env python3
"""Screenshot the built page, and measure it against the guide's hard numbers."""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

import os

PAGE = pathlib.Path(os.environ.get("LIGHTMODE_OUT", "/tmp/velvt-light.html"))

MEASURE = r"""
() => {
  const out = {errors: window.__err || []};
  const q = s => document.querySelector(s);
  const r = el => el ? el.getBoundingClientRect() : null;
  const cs = el => el ? getComputedStyle(el) : null;

  const cta = q('.btn-primary');
  const sec = q('.btn-secondary');
  const en  = q('.vl-top .btn');
  const hero = q('.hero');
  const mascots = [...document.querySelectorAll('.mascot')];
  const screen = q('.vl');

  out.cta      = cta ? {h: Math.round(r(cta).height), w: Math.round(r(cta).width),
                        radius: cs(cta).borderRadius, shadow: cs(cta).boxShadow.slice(0,44),
                        bgImage: cs(cta).backgroundImage} : null;
  out.secondary= sec ? {h: Math.round(r(sec).height), shadow: cs(sec).boxShadow.slice(0,40),
                        border: cs(sec).borderTopWidth} : null;
  out.enTap    = en ? {w: Math.round(r(en).width), h: Math.round(r(en).height)} : null;
  out.hero     = hero ? {h: Math.round(r(hero).height), radius: cs(hero).borderRadius,
                         hasGradient: cs(hero).backgroundImage.includes('gradient')} : null;
  const after = hero ? getComputedStyle(hero, '::after') : null;
  out.heroNoise = after ? {img: after.backgroundImage.slice(0, 46),
                           opacity: after.opacity, blend: after.mixBlendMode} : null;
  out.mascotHeights = mascots.map(m => Math.round(r(m).height));
  out.screenSize = screen ? {w: Math.round(r(screen).width), h: Math.round(r(screen).height)} : null;

  // Does the screen's content overflow its 844px box? .vl is overflow:hidden,
  // so an overflow paints over what follows instead of scrolling -- the exact
  // failure tools/check_hero_fits.py exists to catch in the shipped app.
  out.overflow = screen ? {scrollH: screen.scrollHeight, clientH: screen.clientHeight} : null;

  const h1 = q('.headline');
  out.headline = h1 ? {font: cs(h1).fontFamily.split(',')[0], size: cs(h1).fontSize,
                       lh: cs(h1).lineHeight, weight: cs(h1).fontWeight,
                       tracking: cs(h1).letterSpacing,
                       leadColor: cs(q('.headline .lead')).color,
                       restColor: cs(h1).color} : null;
  const sub = q('.sub');
  out.subWidth = sub ? Math.round(r(sub).width) : null;
  return out;
}
"""


def main():
    with sync_playwright() as p:
        # The bundled Playwright wants a build number this image does not carry;
        # the image ships its own chromium and says to point at it rather than
        # download a second one.
        b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        pg = b.new_page(viewport={"width": 1180, "height": 1000}, device_scale_factor=2)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append("console:" + m.text) if m.type == "error" else None)
        pg.goto(PAGE.as_uri())
        pg.wait_for_timeout(1400)   # webfont
        pg.evaluate("window.__err = %s" % json.dumps(errs))
        data = pg.evaluate(MEASURE)
        data["errors"] = errs
        pg.locator(".device").screenshot(path="/tmp/lightmode-a-screen.png")
        pg.screenshot(path="/tmp/lightmode-a-page.png", full_page=True)
        b.close()
    print(json.dumps(data, indent=2))
    return data


if __name__ == "__main__":
    sys.exit(0 if main() else 0)
