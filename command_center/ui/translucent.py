"""See-through fills on a canvas.

Tk has no transparency. Where it draws stipples (Windows, Linux) a fill is made see-through by filling
some of its pixels only ("gray50": half of them). Tk on macOS ignores stipples and fills everything:
there, the shapes are painted into an image with that share of opacity instead, and the image is put
on the canvas (one image for all the shapes of a call: where they overlap, it is no darker)."""
from __future__ import annotations

import base64
import struct
import sys
import tkinter as tk
import zlib

import numpy as np

STIPPLES = sys.platform != "darwin"          # False: stipples come out solid, images are used
OPACITY = {"gray12": 0.125, "gray25": 0.25, "gray50": 0.5, "gray75": 0.75}


def polygon_mask(polygons, width: int, height: int) -> np.ndarray:
    """The pixels (height x width, True: inside) of the union of polygons given as flat lists
    [x0, y0, x1, y1, ...] in pixels. A pixel is inside when its centre is."""
    out = np.zeros((height, width), bool)
    for flat in polygons:
        p = np.asarray(flat, float).reshape(-1, 2)
        if len(p) < 3:
            continue
        x0, y0 = max(0, int(np.floor(p[:, 0].min()))), max(0, int(np.floor(p[:, 1].min())))
        x1, y1 = min(width, int(np.ceil(p[:, 0].max())) + 1), min(height, int(np.ceil(p[:, 1].max())) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        rows = np.arange(y0, y1) + 0.5
        a, b = p, np.roll(p, -1, axis=0)
        e, r = np.nonzero((a[:, 1, None] <= rows) != (b[:, 1, None] <= rows))        # edge e crosses row r
        x = a[e, 0] + (rows[r] - a[e, 1]) * (b[e, 0] - a[e, 0]) / (b[e, 1] - a[e, 1])
        cols = np.clip(np.ceil(x - 0.5).astype(int) - x0, 0, x1 - x0)    # the first pixel right of the crossing
        flips = np.zeros((y1 - y0, x1 - x0 + 1), np.int32)                 # inside: an odd number of crossings on its left
        np.add.at(flips, (r, cols), 1)
        out[y0:y1, x0:x1] |= (np.cumsum(flips, axis=1)[:, :-1] & 1).astype(bool)
    return out


def png(rgba: np.ndarray) -> bytes:
    """A height x width x 4 array of bytes (red, green, blue, opacity) as a PNG file."""
    h, w = rgba.shape[:2]
    lines = np.zeros((h, 1 + w * 4), np.uint8)                              # each line: filter 0, then its pixels
    lines[:, 1:] = rgba.reshape(h, w * 4)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(lines.tobytes(), 1)) + chunk(b"IEND", b""))


def shade(cv: tk.Canvas, polygons, color: str, stipple: str, tags=()) -> None:
    """Fill the union of `polygons` (flat lists of canvas pixels) with `color`, see-through as `stipple`
    says. The items made carry `tags`."""
    polygons = [p for p in polygons if len(p) >= 6]
    if not polygons:
        return
    if STIPPLES:
        for p in polygons:
            cv.create_polygon(p, fill=color, stipple=stipple, outline="", tags=tags)
        return
    xs, ys = [x for p in polygons for x in p[0::2]], [y for p in polygons for y in p[1::2]]
    x0, y0 = max(0, int(min(xs))), max(0, int(min(ys)))                     # no further than the canvas
    w, h = min(cv.winfo_width(), int(max(xs)) + 2) - x0, min(cv.winfo_height(), int(max(ys)) + 2) - y0
    if w <= 0 or h <= 0:
        return
    mask = polygon_mask([np.asarray(p, float).reshape(-1, 2) - (x0, y0) for p in polygons], w, h)
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[mask] = [c >> 8 for c in cv.winfo_rgb(color)] + [round(255 * OPACITY.get(stipple, 0.5))]
    image = tk.PhotoImage(master=cv, data=base64.b64encode(png(rgba)))
    item = cv.create_image(x0, y0, image=image, anchor="nw", tags=tags)
    # Tk doesn't hold on to an item's image: the canvas does, until the item is gone
    kept = cv.__dict__.setdefault("_shade_images", {})
    for gone in [i for i in kept if not cv.type(i)]:
        del kept[gone]
    kept[item] = image
