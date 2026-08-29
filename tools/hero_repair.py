#!/usr/bin/env python3
"""Close the holes the hero film's matte punched through the characters.

The background was cut per frame with u2net segmentation, and where the two
of them come together it fails in the way segmentation always fails: it loses
the low-contrast seam. The gold arm crossing the purple torso is read as part
of the boundary, so the forearm is severed from the hand and a hole opens up
in the middle of the subject. On the dark ground it shipped against that hole
read as shadow; on a light one it is a rip.

Two facts make the repair exact rather than a guess:

* A fully transparent region that does not touch the frame edge cannot be
  background. Real background is one connected region reaching the border --
  a gap between an arm and a torso opens *outward*. Anything enclosed by the
  subject is a matte error by construction. This is the same border flood
  fill `lightmode_cutout.py` uses to keep the mascots' eyes, run the other
  way round.

* The colour is not lost, only the alpha. VP9 zeroes the colour plane where
  alpha is zero, so the webm's own pixels in a hole are black -- but the mp4
  sibling is the same 121 frames composited on --ink from a matte that did
  not tear, so it still carries the arm. Frame n of one is frame n of the
  other.

The mp4 is also what tells background from subject inside a hole, and that
distinction is needed: not every enclosed region is a mistake. Where the gold
character's cheek meets the purple one's shoulder, the two silhouettes touch
above and below and genuinely enclose a sliver of real backdrop. Filling that
paints a navy wedge into the middle of the picture -- traded one artefact for
another. But the mp4 is that same frame over a known colour, so a hole pixel
sitting on --ink is backdrop and a hole pixel that is not is subject, and the
composite equation runs backwards to recover both the coverage and the colour
underneath it. Antialiased hole edges come back as partial alpha rather than
a hard cut, which is what they were.

Every pixel the matte got right is left alone. That matters: the mp4 is
composited on near-black, so taking its colour along the *outer* boundary
would draw a dark fringe around the characters on a light canvas.
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image
from scipy import ndimage

# Below this the pixel is transparent enough that the matte meant to drop it.
# Well under the antialiased boundary, which climbs through the whole range.
SOLID_AT = 8
# A hole smaller than this is a stray pixel from the encoder's chroma
# subsampling, not a lost limb. Filling those is harmless but pointless, and
# the count is the number the report is read for.
REPORTABLE = 40

# How far a hole pixel must sit from the mp4's ground colour before it counts
# as subject. Below FLOOR it is backdrop and stays transparent; above CEIL it
# is opaque; between the two it is an antialiased edge and gets the coverage
# that distance implies.
INK_FLOOR = 16
INK_CEIL = 46


def ground_of(rgb):
    """The colour the mp4 was composited on, read off its four corners."""
    h, w, _ = rgb.shape
    return np.stack([rgb[0, 0], rgb[0, w - 1],
                     rgb[h - 1, 0], rgb[h - 1, w - 1]]).mean(axis=0)


def repair(rgba, source_rgb):
    """Return (fixed rgba, pixels recovered). `source_rgb` is the mp4 frame."""
    a = rgba.copy()
    solid = a[:, :, 3] > SOLID_AT

    labels, count = ndimage.label(~solid)
    if count == 0:
        return a, 0
    edge = (set(labels[0, :]) | set(labels[-1, :])
            | set(labels[:, 0]) | set(labels[:, -1]))
    edge.discard(0)
    background = np.isin(labels, list(edge))
    holes = (~solid) & (~background)
    if not holes.any():
        return a, 0

    ground = ground_of(source_rgb.astype(np.float64))
    src = source_rgb.astype(np.float64)[holes]
    # Coverage from how far the composite has been pulled off the ground.
    distance = np.abs(src - ground).max(axis=1)
    cover = np.clip((distance - INK_FLOOR) / (INK_CEIL - INK_FLOOR), 0.0, 1.0)

    # src = colour * cover + ground * (1 - cover). Solve for colour. Guard the
    # divide where coverage is nil; those pixels keep alpha 0 and never show.
    safe = np.maximum(cover, 1e-3)[:, None]
    colour = np.clip(ground + (src - ground) / safe, 0, 255)

    idx = np.nonzero(holes)
    a[idx[0], idx[1], 3] = np.round(cover * 255).astype(np.uint8)
    a[idx[0], idx[1], 0:3] = np.round(colour).astype(np.uint8)

    # Flatten the colour plane wherever nothing shows. VP9 stores colour and
    # alpha as two streams and the colour one has no idea the alpha exists, so
    # it spends bits describing a backdrop that is never drawn. The original
    # webm had this region at zero; the YUV -> RGB round trip through PNG
    # brings it back as low-amplitude noise, which is expensive precisely
    # because it is noise. Re-flattening it is most of the file size.
    a[a[:, :, 3] == 0, 0:3] = 0
    return a, int((cover > 0).sum())


def ffmpeg():
    """The binary, from imageio-ffmpeg if the system has none.

    Not a dependency of the app -- nothing here is imported by `app.py`. This
    runs by hand when the artwork changes.
    """
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
    """Decode `film` to RGBA pngs.

    `-c:v libvpx-vp9` is load-bearing and easy to lose: WebM carries VP9's
    alpha as a per-block side channel, and ffmpeg's default vp9 decoder throws
    it away without a word. You get 121 perfectly opaque frames and no error.
    """
    into.mkdir(parents=True, exist_ok=True)
    cmd = [ff, "-hide_banner", "-v", "error"]
    if alpha:
        cmd += ["-c:v", "libvpx-vp9"]
    cmd += ["-i", str(film), "-pix_fmt", "rgba", str(into / "%04d.png")]
    subprocess.run(cmd, check=True)
    return sorted(into.glob("*.png"))


def encode(ff, frames_dir, out):
    """Re-encode to VP9 with alpha.

    `-auto-alt-ref 0` is required -- alternate reference frames and an alpha
    channel do not coexist in libvpx. CRF 50 lands the repaired film *under*
    the size of the torn one it replaces, and on a 390px-wide hero it is not
    distinguishable from the source pngs.
    """
    subprocess.run([
        ff, "-hide_banner", "-v", "error", "-framerate", "24",
        "-i", str(frames_dir / "%04d.png"),
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
        "-crf", "50", "-b:v", "0", "-auto-alt-ref", "0",
        "-row-mt", "1", "-quality", "good", "-speed", "1",
        "-an", str(out), "-y"], check=True)


def main(film, sibling, out):
    film, sibling, out = map(pathlib.Path, (film, sibling, out))
    ff = ffmpeg()
    work = pathlib.Path(tempfile.mkdtemp(prefix="hero-"))
    webm = explode(ff, film, work / "webm", alpha=True)
    mp4 = explode(ff, sibling, work / "mp4", alpha=False)
    if len(webm) != len(mp4):
        raise SystemExit("frame counts differ: %d webm, %d mp4 -- they must be "
                         "the same 121 frames for the colour to line up"
                         % (len(webm), len(mp4)))
    fixed_dir = work / "fixed"
    fixed_dir.mkdir(parents=True, exist_ok=True)

    total, worst = 0, (0, None)
    for w, m in zip(webm, mp4):
        rgba = np.asarray(Image.open(w).convert("RGBA"))
        src = np.asarray(Image.open(m).convert("RGB"))
        if src.shape[:2] != rgba.shape[:2]:
            raise SystemExit("%s and %s are different sizes" % (w.name, m.name))
        fixed, n = repair(rgba, src)
        Image.fromarray(fixed, "RGBA").save(fixed_dir / w.name)
        total += n
        if n > worst[0]:
            worst = (n, w.name)
        if n >= REPORTABLE:
            print("  %s  %6d px" % (w.name, n))
    print("repaired %d frames, %d pixels; worst %s at %d"
          % (len(webm), total, worst[1], worst[0]))

    encode(ff, fixed_dir, out)
    print("wrote %s -- %d bytes (was %d)"
          % (out, out.stat().st_size, film.stat().st_size))

    # The poster is the resting frame, and it has to come from the same pass
    # or the still and the film disagree about where the arms are.
    still = out.with_suffix(".webp")
    Image.open(fixed_dir / webm[-1].name).convert("RGBA").save(
        still, "WEBP", quality=82, method=6)
    print("wrote %s -- %d bytes" % (still, still.stat().st_size))
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: hero_repair.py <torn.webm> <reference.mp4> <out.webm>\n"
            "  writes the repaired film and its .webp poster beside it")
    main(*sys.argv[1:4])
