"""Regenerate the avatar images inside static/velvet-searching.lottie.

The animation is a stock LottieFiles piece whose four avatars were photos of
animals. Everything that moves -- the frames, strokes and masks -- is vector
shape data in the animation JSON; the animals live only in the four PNGs
inside the .lottie archive. So swapping them for on-brand placeholders is a
pure asset swap: repack the zip with new image bytes and leave the geometry
alone.

    python make_search_avatars.py            # rewrite the .lottie in place
    python make_search_avatars.py --check     # report only, touch nothing

Pillow is deliberately not a dependency (see app.py's photo-upload notes), so
the PNGs are encoded from scratch the same way seed_demo.py's
make_gradient_png() does it: raw scanlines, zlib, hand-built chunks.
"""

import argparse
import json
import struct
import sys
import zipfile
import zlib
from math import sqrt

LOTTIE_PATH = "static/velvet-searching.lottie"

# The image layers anchor at [509, 664] -- the exact centre of a 1018x1328
# asset -- and the asset entries declare those dimensions. Both must stay as
# they are: the layer scale (~39.46%) is calibrated to them, so shipping
# smaller pixels would shrink the avatars inside their frames. The size win
# comes from flat colour compressing far better than a photograph.
IMG_W, IMG_H = 1018, 1328

# Straight from :root in templates/base.html. Each avatar gets its own tint so
# the four circles stay distinguishable as they orbit; --violet-deep is paired
# with a lighter glyph since the tint itself is too dark to read as the figure.
INK_RAISED = (0x15, 0x0C, 0x22)
TINTS = [
    ((0x8A, 0x2B, 0xE2), None),  # --violet
    ((0xA8, 0x55, 0xF7), None),  # --violet-crest
    ((0xE8, 0xD3, 0xA9), None),  # --champagne
    ((0x3B, 0x0B, 0x66), (0xA8, 0x85, 0xF7)),  # --violet-deep, lifted glyph
]


def mix(a, b, t):
    """Blend two RGB tuples, t=0 -> a, t=1 -> b."""
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def encode_png(width, height, pixels):
    """Minimal RGB PNG encoder -- same approach as seed_demo.py."""
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter type: none
        rows.extend(pixels[y])

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
            + chunk(b"IEND", b""))


def make_avatar(tint, glyph_rgb=None):
    """An empty-profile glyph: head circle over a shoulders capsule.

    Spans are computed analytically per scanline (a circle's half-width at row
    y is sqrt(r^2 - (y-cy)^2)) rather than by testing every pixel, with
    fractional coverage on the two boundary pixels for anti-aliasing. Flat
    interiors are what keep the encoded PNG small.
    """
    bg = mix(INK_RAISED, tint, 0.22)
    fg = glyph_rgb or mix(tint, (0xFF, 0xFF, 0xFF), 0.12)

    cx = IMG_W / 2.0
    # Keep the whole glyph inside a centred circle of diameter <= IMG_W. The
    # mask is rectangular today, but this way the icons survive unharmed if it
    # ever morphs circular across its keyframes.
    cy = IMG_H / 2.0

    head_r = IMG_W * 0.155
    head_cy = cy - IMG_W * 0.145

    # Shoulders: a capsule (rounded top corners) clipped to a flat bottom.
    sh_r = IMG_W * 0.255           # corner radius / half-width of the round top
    sh_cy = cy + IMG_W * 0.235     # centre of the capsule's rounded end
    sh_bottom = cy + IMG_W * 0.40

    def span(half, centre_x):
        if half <= 0:
            return None
        return (centre_x - half, centre_x + half)

    rows = []
    for y in range(IMG_H):
        row = bytearray()
        py = y + 0.5

        spans = []
        dy = py - head_cy
        if abs(dy) < head_r:
            spans.append(span(sqrt(head_r * head_r - dy * dy), cx))

        if py <= sh_bottom:
            if py >= sh_cy:
                spans.append(span(sh_r, cx))          # straight sides
            else:
                dys = sh_cy - py
                if dys < sh_r:
                    spans.append(span(sqrt(sh_r * sh_r - dys * dys), cx))

        spans = [s for s in spans if s]

        # Per-pixel coverage, but only the handful of pixels near a boundary
        # ever land between 0 and 1.
        for x in range(IMG_W):
            px0, px1 = x, x + 1
            cov = 0.0
            for x0, x1 in spans:
                overlap = min(px1, x1) - max(px0, x0)
                if overlap > 0:
                    cov = max(cov, min(overlap, 1.0))
            row.extend(mix(bg, fg, cov) if cov else bg)
        rows.append(bytes(row))

    return encode_png(IMG_W, IMG_H, rows)


def recolour(node, swaps):
    """Walk the animation JSON, retargeting literal colour arrays.

    Colours live in {"c": {"k": [r, g, b, a]}} nodes scattered through the
    shape tree, so this rewrites by value rather than by path.
    """
    hits = 0
    if isinstance(node, dict):
        k = node.get("k")
        if isinstance(k, list) and 3 <= len(k) <= 4 and all(
            isinstance(v, (int, float)) for v in k
        ):
            key = tuple(round(float(v), 3) for v in k[:3])
            if key in swaps:
                new = swaps[key]
                for i in range(3):
                    node["k"][i] = new[i]
                hits += 1
        for v in node.values():
            hits += recolour(v, swaps)
    elif isinstance(node, list):
        for v in node:
            hits += recolour(v, swaps)
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report the archive's contents without rewriting it")
    args = ap.parse_args()

    with open(LOTTIE_PATH, "rb") as fh:
        original = fh.read()
    src = zipfile.ZipFile(__import__("io").BytesIO(original))
    names = src.namelist()
    anim_name = next(n for n in names if n.endswith(".json") and n != "manifest.json")
    anim = json.loads(src.read(anim_name))
    pngs = [n for n in names if n.lower().endswith(".png")]

    print(f"{LOTTIE_PATH}: {len(original):,} bytes, {len(names)} entries")
    print(f"  animation: {anim_name}  {anim['w']}x{anim['h']}  "
          f"{len(anim['layers'])} layers, {len(anim.get('assets', []))} assets")
    for n in pngs:
        print(f"  image: {n}  ({src.getinfo(n).file_size:,} bytes)")
    if args.check:
        return

    # --- 1. new avatars, one tint per distinct asset -----------------------
    new_images = {}
    for i, name in enumerate(sorted(pngs)):
        tint, glyph = TINTS[i % len(TINTS)]
        new_images[name] = make_avatar(tint, glyph)
        print(f"  regenerated {name}: {len(new_images[name]):,} bytes")

    # --- 2. retarget the stock chrome to the app's palette -----------------
    # Black strokes read as a harsh seam on the dark violet card, and the two
    # decorative ellipses are filled near-white.
    swaps = {
        (0.0, 0.0, 0.0): (0.659, 0.333, 0.969),        # -> --violet-crest
        (0.945, 0.945, 0.945): (0.231, 0.043, 0.400),  # -> --violet-deep
    }
    hits = recolour(anim.get("layers", []), swaps)
    print(f"  recoloured {hits} colour node(s)")

    # --- 3. repack, preserving entry names and order ----------------------
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        for name in names:
            if name in new_images:
                out.writestr(name, new_images[name])
            elif name == anim_name:
                out.writestr(name, json.dumps(anim, separators=(",", ":")))
            else:
                out.writestr(name, src.read(name))

    data = buf.getvalue()
    with open(LOTTIE_PATH, "wb") as fh:
        fh.write(data)
    print(f"\nwrote {LOTTIE_PATH}: {len(data):,} bytes "
          f"({100 - len(data) * 100 // len(original)}% smaller)")


if __name__ == "__main__":
    sys.exit(main())
