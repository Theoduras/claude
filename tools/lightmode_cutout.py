#!/usr/bin/env python3
"""Free the mascots from their studio backdrop.

The four webps in the guide are shot on a uniform warm grey (~#DEDCD8), not on
transparency, so dropping one onto the light canvas would paint a visible box.

The obvious fix -- key every pixel near the backdrop colour -- is the one that
breaks: the characters' eyes are white, which is exactly as desaturated and
nearly as bright as the backdrop, so a global key punches two holes in every
face. Instead the mask is flood-filled inward from the border, so only
background *connected to the edge* is removed. The eyes are enclosed by the
head and are never reached.

Alpha is feathered over one pixel of the boundary; a hard cut leaves a grey
fringe from the original anti-aliasing, which reads as a halo on a light ground.
"""
import base64
import io
import pathlib

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = pathlib.Path("/tmp")   # debug output only, never the repo

# How far a pixel may sit from the sampled backdrop and still count as
# background. Generous on luminance (the backdrop has a soft vignette) but
# tight on saturation, which is what actually separates felt from paper.
LUMA_TOLERANCE = 26
SATURATION_CEILING = 22


def cut(img):
    rgb = np.asarray(img.convert("RGB")).astype(np.int16)
    # Sample the backdrop from the four corners rather than assuming a value.
    h, w, _ = rgb.shape
    corners = np.stack([rgb[0, 0], rgb[0, w - 1], rgb[h - 1, 0], rgb[h - 1, w - 1]])
    backdrop = corners.mean(axis=0)

    saturation = rgb.max(axis=2) - rgb.min(axis=2)
    distance = np.abs(rgb - backdrop).max(axis=2)
    backgroundish = (distance <= LUMA_TOLERANCE) & (saturation <= SATURATION_CEILING)

    # Only the region touching the frame edge is backdrop. Anything enclosed by
    # the character -- eyes, teeth, a highlight -- stays opaque.
    labels, count = ndimage.label(backgroundish)
    if count == 0:
        return img.convert("RGBA")
    edge = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    edge.discard(0)
    background = np.isin(labels, list(edge))

    alpha = np.where(background, 0.0, 255.0)
    # One-pixel feather: blur the mask, then keep it from eating into the body.
    alpha = ndimage.gaussian_filter(alpha, sigma=0.8)
    alpha = np.clip(alpha, 0, 255).astype(np.uint8)

    out = np.dstack([np.asarray(img.convert("RGB")), alpha])
    return Image.fromarray(out, "RGBA")


def trim(img):
    """Crop to the character, so layout positions the figure and not its margin."""
    box = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    return img.crop(box) if box else img


def encode(img, quality=88):
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=quality, method=6)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def cutouts():
    """{key: data-uri} of the four mascots, backdrop removed and trimmed."""
    import lightmode_assets as assets

    out = {}
    for key, uri in assets.mascots().items():
        raw = base64.b64decode(uri.split(",", 1)[1])
        out[key] = encode(trim(cut(Image.open(io.BytesIO(raw)))))
    return out


if __name__ == "__main__":
    import lightmode_assets as assets

    sheet = []
    for key, uri in assets.mascots().items():
        raw = base64.b64decode(uri.split(",", 1)[1])
        src = Image.open(io.BytesIO(raw))
        done = trim(cut(src))
        done.save(HERE / ("cut-%s.png" % key))
        sheet.append((key, done))
        print("%-9s %s -> %s  %d bytes as webp"
              % (key, src.size, done.size, len(encode(done))))

    # Composited on the real canvas colour, which is where a halo would show.
    pad, canvas = 16, (244, 243, 240, 255)
    width = sum(i.width for _, i in sheet) + pad * (len(sheet) + 1)
    height = max(i.height for _, i in sheet) + pad * 2
    proof = Image.new("RGBA", (width, height), canvas)
    x = pad
    for _, i in sheet:
        proof.paste(i, (x, pad), i)
        x += i.width + pad
    proof.save(HERE / "cut-proof.png")
    print("proof:", proof.size)
