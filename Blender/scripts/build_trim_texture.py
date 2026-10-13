"""T1a: assemble the trim-sheet texture Export/Textures/T_HanoiTrim.png from the source images.

Plain Python (Pillow + numpy), no bpy:
    python Blender/scripts/build_trim_texture.py

Layout comes from hanoi_trim.REGIONS (the only source of truth). A region with a source image is
textured; every other region is left white so the vertex colour / procedural shader keeps driving it.
Priority per region: Textures/src/gemini > cc0 > old. Writes:
    Export/Textures/T_HanoiTrim.png            2048x2048 atlas (sRGB)
    Export/Textures/T_HanoiTrim_preview.png    atlas with region frames + names
    Export/Textures/tile_test.png              repeating regions tiled 3x3 (seam check)
    Export/Textures/textured_regions.json      regions that carry an image (read by hanoi_trim)
"""
import os, sys, json
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = r"D:\Project III\BuildingGenerate"
sys.path.insert(0, os.path.join(ROOT, "Blender", "scripts"))
import hanoi_trim as trim

SRC = os.path.join(ROOT, "Textures", "src")
OUT = os.path.join(ROOT, "Export", "Textures")
CELL = trim.N // 8                    # 256 px


def find(*names):
    for sub in ("gemini", "cc0", "old"):
        for n in names:
            p = os.path.join(SRC, sub, n)
            if os.path.exists(p):
                return p
    return None


def load(path, crop=None):
    im = Image.open(path).convert("RGBA")
    if crop:                                        # fractions (l, t, r, b)
        w, h = im.size
        im = im.crop((int(crop[0] * w), int(crop[1] * h), int(crop[2] * w), int(crop[3] * h)))
    return im


def to_gray(im):
    a = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
    return a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def neutral(im, size, mean, contrast, flatten=0):
    """Luminance only, rescaled so the average brightness is `mean` and the detail amplitude is
    scaled by `contrast`: the shader / vertex colour then tints it (paint, roof colour).
    flatten > 0 removes the low-frequency lighting (blur radius in px) so photos tile cleanly."""
    g = to_gray(im.resize(size, Image.LANCZOS))
    if flatten:
        low = np.asarray(Image.fromarray((g * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(flatten)), dtype=np.float32) / 255.0
        g = g - low
    g = (g - g.mean()) * contrast + mean
    g = np.clip(g, 0, 1)
    return Image.fromarray((np.stack([g] * 3, -1) * 255).astype(np.uint8), "RGB")


def seamless(im):
    """Cross-fade with the half-offset copy so opposite edges match (cheap, good for noise)."""
    a = np.asarray(im, dtype=np.float32)
    h, w = a.shape[:2]
    wx = np.sin(np.pi * (np.arange(w) + 0.5) / w) ** 2
    wy = np.sin(np.pi * (np.arange(h) + 0.5) / h) ** 2
    wgt = (wy[:, None] * wx[None, :])[..., None]
    rolled = np.roll(np.roll(a, h // 2, 0), w // 2, 1)
    return Image.fromarray(np.clip(a * wgt + rolled * (1 - wgt), 0, 255).astype(np.uint8), "RGB")


def fit(im, size):
    bg = Image.new("RGB", size, (255, 255, 255))
    rgba = im.resize(size, Image.LANCZOS)
    bg.paste(rgba, (0, 0), rgba)
    return bg


def sign_band(im, size):
    """Gemini sign boards come on a white backdrop with a border: cut to the board, drop the
    border, and keep a central 4:1 band (the lettering area)."""
    g = to_gray(im)
    ys, xs = np.where(g < 0.92)
    im = im.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    w, h = im.size
    inset = int(0.07 * h)
    im = im.crop((inset, inset, w - inset, h - inset))
    w, h = im.size
    band = max(1, int(w * size[1] / size[0]))
    top = max(0, (h - band) // 2)
    return im.crop((0, top, w, top + min(band, h))).convert("RGB").resize(size, Image.LANCZOS)


def build(region, size):
    """RGB image of the region's pixel size, or None when no source image exists."""
    if region == "PLASTER":
        p = find("plaster.png", "wall_2.jpg")
        return p and seamless(neutral(load(p), size, 0.90, 2.2, flatten=24))
    if region == "CONCRETE":
        p = find("concrete.png", "wall_5.png")
        return p and seamless(neutral(load(p, (0.0, 0.1, 1.0, 0.75)), size, 0.68, 0.4, flatten=40))
    if region == "WOODDOOR":                               # glass entrance door (name kept for the module)
        p = find("wooddoor.png", "glassdoor.png", "glassdoor_black.png")
        return p and fit(load(p), size)
    if region in ("FOLDGATE", "SHUTTER", "GLASSWIN"):
        p = find(region.lower() + ".png")
        return p and fit(load(p), size)
    if region in ("SIGN_A", "SIGN_B"):
        p = find(region.lower() + ".png")
        return p and sign_band(load(p), size)
    if region == "INTERIOR":
        # no visible room: one warm yellow, slightly darker towards the floor (reads as depth)
        top, bot = np.array([255, 236, 172]), np.array([226, 190, 112])
        t = np.linspace(0, 1, size[1])[:, None, None]
        a = (top * (1 - t) + bot * t).astype(np.uint8)
        return Image.fromarray(np.repeat(a, size[0], axis=1), "RGB")
    if region == "ROOFTOP":
        p = find("rooftop.png", "flat_roof.png")
        return p and seamless(neutral(load(p), size, 0.74, 0.38, flatten=16))
    if region == "ROOF":
        # corrugated sheet: ridge shading from the CC0 ambient-occlusion map, tiled 2x across
        p = find("roof.png", "CorrugatedSteel005_AmbientOcclusion.jpg")
        if not p:
            return None
        im = load(p)
        two = Image.new("RGBA", (im.width * 2, im.height))
        two.paste(im, (0, 0)); two.paste(im, (im.width, 0))
        return neutral(two, size, 0.82, 1.1)
    if region == "CORRUGATED":
        p = find("awning.png", "CorrugatedSteel005_AmbientOcclusion.jpg")
        if not p:
            return None
        im = load(p)
        two = Image.new("RGBA", (im.width * 2, im.height))
        two.paste(im, (0, 0)); two.paste(im, (im.width, 0))
        g = np.asarray(neutral(two, size, 0.85, 1.1), dtype=np.float32) / 255.0
        tint = np.array([0.55, 0.70, 0.82], dtype=np.float32)              # pale blue sheet
        return Image.fromarray(np.clip(g * tint * 1.15 * 255, 0, 255).astype(np.uint8), "RGB")
    return None


def keyed(im, size):
    """Railing image -> RGBA. A real alpha channel wins; otherwise the plain light backdrop is
    keyed out (alpha from darkness), as Gemini cannot export transparency."""
    im = im.convert("RGBA").resize(size, Image.LANCZOS)
    a = np.asarray(im, dtype=np.float32) / 255.0
    if a[..., 3].min() < 0.98:
        return im
    lum = a[..., :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    alpha = np.clip((0.80 - lum) / 0.45, 0, 1)                             # white -> 0, dark metal -> 1
    out = a.copy(); out[..., :3] = a[..., :3] * 0.85                       # keep the metal dark at the edges
    out[..., 3] = alpha
    return Image.fromarray((out * 255).astype(np.uint8), "RGBA")


SUB_SOURCES = {"RAIL_BAL": "rail_balcony.png", "RAIL_CAGE": "rail_cage.png"}


def rail_cuts(im):
    """Cut positions for tiling a railing image: the centres of the first and last interior vertical
    bars (fractions of the width). The thick frame posts on both edges stay only in the end caps."""
    g = to_gray(im)
    h, w = g.shape
    dark = (g < 0.45)[int(0.2 * h):int(0.7 * h)]
    prof = dark.mean(0)
    cols = prof >= prof.min() + 0.85 * (prof.max() - prof.min())
    groups, start = [], None
    for x, on in enumerate(list(cols) + [False]):
        if on and start is None:
            start = x
        elif not on and start is not None:
            groups.append((start, x - 1)); start = None
    inner = [(a, b) for a, b in groups if a > 0.04 * w and b < 0.96 * w]
    if len(inner) < 3:
        return None
    c = [(a + b) / 2.0 for a, b in inner]
    return dict(w=w, h=h, l=round(c[0] / w, 5), r=round(c[-1] / w, 5), bars=len(inner))


def main():
    os.makedirs(OUT, exist_ok=True)
    atlas = Image.new("RGBA", (trim.N, trim.N), (255, 255, 255, 255))
    textured = []
    slices = {}
    for name, (cx0, cy0, cx1, cy1) in trim.REGIONS.items():
        if name.startswith("GRID_"):
            continue
        size = (int((cx1 - cx0) * CELL), int((cy1 - cy0) * CELL))
        img = build(name, size)
        if img is None:
            continue
        atlas.paste(img, (int(cx0 * CELL), trim.N - int(cy1 * CELL)))     # UV origin is bottom-left
        textured.append(name)
    # railings: sub-rectangles of the RAIL cell, with a keyed alpha (replaces the opaque white fill)
    for name, fname in SUB_SOURCES.items():
        p = find(fname)
        if not p:
            continue
        parent, s0, t0, s1, t1 = trim.SUBREGIONS[name]
        cx0, cy0, cx1, cy1 = trim.REGIONS[parent]
        w, h = (cx1 - cx0) * CELL, (cy1 - cy0) * CELL
        size = (int(round((s1 - s0) * w)), int(round((t1 - t0) * h)))
        x0, y0 = int(cx0 * CELL + s0 * w), trim.N - int(round(cy0 * CELL + t1 * h))
        box = (x0, y0, x0 + size[0], y0 + size[1])
        atlas.paste(Image.new("RGBA", size, (0, 0, 0, 0)), box)
        src = load(p)
        atlas.paste(keyed(src, size), box)
        textured.append(name)
        cut = rail_cuts(src)
        if cut:
            slices[name] = cut
            print(f"[trim] {name}: {cut['bars']} interior bars, cut at {cut['l']:.3f} / {cut['r']:.3f}")
    atlas.save(os.path.join(OUT, "T_HanoiTrim.png"))
    with open(os.path.join(OUT, "rail_slices.json"), "w") as f:
        json.dump(slices, f)
    with open(os.path.join(OUT, "textured_regions.json"), "w") as f:
        json.dump(sorted(textured), f)

    pv = atlas.convert('RGB'); d = ImageDraw.Draw(pv)
    for name, (cx0, cy0, cx1, cy1) in trim.REGIONS.items():
        if name.startswith("GRID_"):
            continue
        x0, y1 = int(cx0 * CELL), trim.N - int(cy0 * CELL)
        x1, y0 = int(cx1 * CELL), trim.N - int(cy1 * CELL)
        d.rectangle((x0, y0, x1 - 1, y1 - 1), outline=(255, 0, 255) if name in textured else (0, 160, 255), width=3)
        d.text((x0 + 8, y0 + 8), name, fill=(255, 0, 0))
    pv.save(os.path.join(OUT, "T_HanoiTrim_preview.png"))

    names = [n for n in ("PLASTER", "CONCRETE", "ROOF", "ROOFTOP") if n in textured]
    strip = Image.new("RGB", (max(len(names), 1) * 780, 780), (40, 40, 40))
    for i, n in enumerate(names):
        cx0, cy0, cx1, cy1 = trim.REGIONS[n]
        tile = atlas.convert('RGB').crop((int(cx0 * CELL), trim.N - int(cy1 * CELL), int(cx1 * CELL), trim.N - int(cy0 * CELL)))
        big = Image.new("RGB", (tile.width * 3, tile.height * 3))
        for a in range(3):
            for b in range(3):
                big.paste(tile, (a * tile.width, b * tile.height))
        big.thumbnail((760, 760))
        strip.paste(big, (i * 780 + 10, 10))
    strip.save(os.path.join(OUT, "tile_test.png"))
    print("[trim] textured regions:", ", ".join(sorted(textured)))
    print("[trim] untextured (vertex colour / procedural):",
          ", ".join(sorted(n for n in trim.REGIONS if not n.startswith("GRID_") and n not in textured)))


if __name__ == "__main__":
    main()
