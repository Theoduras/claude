#!/usr/bin/env python3
"""Hold the hero film's matte against the sibling that never tore.

Where the two characters come together, u2net loses the low-contrast seam:
the gold arm crossing the purple torso reads as boundary, and the forearm is
cut away from the hand. On the dark ground the film shipped against, the gap
read as shadow. On a light one it is a rip through the middle of the picture,
and no amount of CSS reframing hides it.

The obvious test -- "a transparent region enclosed by the subject is a matte
error" -- is wrong here, and wrong in a way worth writing down. Where the gold
character's cheek meets the purple one's shoulder, the two silhouettes touch
above and below and genuinely enclose a sliver of backdrop. A check built on
that property fails the *correct* film.

What is true is that the mp4 is the same 121 frames from a matte that did not
tear, composited on a known near-black ground. So its silhouette is the
answer key: a pixel far enough off that ground is subject there, and must not
be transparent in the webm.

Two decoders, because neither can do both jobs. ffmpeg reads the mp4, which
this Chromium has no H.264 for; a browser opens the webm, because the failure
worth catching is a re-encode that drops the alpha side channel silently, and
only a browser proves the shipped bytes still carry it where it counts.

Run after touching static/velvt-hero.webm.
"""
import base64
import pathlib
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

STATIC = pathlib.Path(__file__).resolve().parent.parent / "static"
# How far off the mp4's ground a pixel must sit to count as subject. Above the
# antialiased boundary, where the two films are entitled to disagree.
SUBJECT_AT = 46
# Pixels per frame the silhouettes may differ by. Not zero, and not tight:
# the two films are separately encoded and both lossy, so they disagree along
# the boundary. Measured on the repaired frames before encoding, the gap is
# 2px total; after VP9 at crf 50 it is 60-120 per frame, which is a fraction
# of a one-pixel ring around a ~3000px perimeter. The tear this exists to
# catch ran 3,000-11,000 px per frame. Anywhere in the order of magnitude
# between those two separates them; this sits ~3x above the noise and ~7x
# below the smallest real tear.
TOLERATED = 400

fails = []


def ok(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        fails.append(what)


def ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError:
        raise SystemExit("no ffmpeg on PATH; `pip install imageio-ffmpeg` "
                         "supplies one")
    return imageio_ffmpeg.get_ffmpeg_exe()


def explode(ff, film, into, alpha):
    """Decode to RGBA pngs. `-c:v libvpx-vp9` is what keeps the alpha."""
    into.mkdir(parents=True, exist_ok=True)
    cmd = [ff, "-hide_banner", "-v", "error"]
    if alpha:
        cmd += ["-c:v", "libvpx-vp9"]
    cmd += ["-i", str(film), "-pix_fmt", "rgba", str(into / "%04d.png")]
    subprocess.run(cmd, check=True)
    return sorted(into.glob("*.png"))


def ground_of(rgb):
    h, w, _ = rgb.shape
    return np.stack([rgb[0, 0], rgb[0, w - 1],
                     rgb[h - 1, 0], rgb[h - 1, w - 1]]).mean(axis=0)


# ---- the silhouettes agree, frame for frame -------------------------------
ff = ffmpeg()
work = pathlib.Path(tempfile.mkdtemp(prefix="matte-"))
try:
    webm = explode(ff, STATIC / "velvt-hero.webm", work / "webm", alpha=True)
    mp4 = explode(ff, STATIC / "velvt-hero.mp4", work / "mp4", alpha=False)
    ok(len(webm) == len(mp4) and len(webm) > 100,
       "the two films are the same %d frames (%d / %d)"
       % (len(webm), len(webm), len(mp4)))

    worst, opaque, total, seam = (0, None), 0, 0, []
    for w, m in zip(webm, mp4):
        a = np.asarray(Image.open(w).convert("RGBA"))
        s = np.asarray(Image.open(m).convert("RGB")).astype(np.float64)
        subject = np.abs(s - ground_of(s)).max(axis=2) > SUBJECT_AT
        clear = a[:, :, 3] <= 8
        gone = int((subject & clear).sum())
        opaque += int((~clear).sum())
        total += clear.size
        if gone > TOLERATED:
            print("      %s: %d px of subject missing" % (w.name, gone))
        if gone > worst[0]:
            worst = (gone, w.name)
        seam.append(gone)

    ok(worst[0] <= TOLERATED,
       "no part of a character is cut out of the matte (worst %d px, %s; "
       "median seam %d)" % (worst[0], worst[1], sorted(seam)[len(seam) // 2]))
    # A film with no alpha at all scans clean against this, which would make
    # the check above vacuous -- so prove some of it is genuinely transparent.
    ok(opaque < total * 0.9,
       "and the matte is doing real work (%d%% of pixels opaque)"
       % round(100 * opaque / total))
finally:
    shutil.rmtree(work, ignore_errors=True)

# ---- and a browser still sees the alpha ----------------------------------
SCAN = r"""
async (src) => {
  const v = document.createElement("video");
  v.muted = true; v.playsInline = true; v.src = src;
  await new Promise((ok, no) => {
    v.onloadeddata = ok;
    v.onerror = () => no(new Error("the film did not decode"));
  });
  await new Promise(r => { v.onseeked = r; v.currentTime = v.duration * 0.5; });
  const c = document.createElement("canvas");
  c.width = v.videoWidth; c.height = v.videoHeight;
  const g = c.getContext("2d", { willReadFrequently: true });
  g.clearRect(0, 0, c.width, c.height);
  g.drawImage(v, 0, 0);
  const px = g.getImageData(0, 0, c.width, c.height).data;
  let clear = 0;
  for (let q = 3; q < px.length; q += 4) if (px[q] <= 8) clear++;
  return {w: c.width, h: c.height, dur: v.duration,
          clear: clear / (c.width * c.height)};
};
"""
uri = "data:video/webm;base64," + base64.b64encode(
    (STATIC / "velvt-hero.webm").read_bytes()).decode("ascii")
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    page = b.new_page()
    page.goto("about:blank")
    r = page.evaluate(SCAN, uri)
    b.close()

ok(r["w"] == 540 and r["h"] == 960, "a browser gets 540x960 (%dx%d)" % (r["w"], r["h"]))
ok(2 < r["dur"] < 8, "about five seconds (%.2fs)" % r["dur"])
ok(r["clear"] > 0.15,
   "and the alpha channel survived the encode (%d%% transparent mid-film)"
   % round(100 * r["clear"]))

print()
print("%d failed" % len(fails))
sys.exit(1 if fails else 0)
