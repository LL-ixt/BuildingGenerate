"""Plan TM step A: temporary tree textures for the hand-sculpted trees.

Plain Python (Pillow + numpy), no bpy:
    python Blender/scripts/build_tree_textures.py            build the textures
    python Blender/scripts/build_tree_textures.py --list     print the sprite boxes found in the sources

Writes to Export/Textures/Trees/:
    T_Foliage.png           2048 atlas, 2x2 cells in SPECIES_ORDER (Sau, XaCu, Bang, HoaSua), RGBA
    T_Foliage_preview.png   the atlas over grey (edge / halo check)
    T_Foliage_blob.json     average leaf colour per species (linear + sRGB), for the LOD2 blob
    T_Bark.png              bark, from TreeGenerate/bark_seamless.jpg

Each cell is a leaf cluster composed from sprites of the stock images (real alpha), rotated around
the cell centre so a card reads as a clump, not a single leaf. Replace a species by a Gemini image
later: put it in CELL_SOURCE[species] = 'file.png' (whole image = one cell).
"""
import os, sys, json, math, random
import numpy as np
from PIL import Image

ROOT = r"D:\Project III\BuildingGenerate"
TREE_SRC = r"D:\Project III\TreeGenerate"
OUT = os.path.join(ROOT, "Export", "Textures", "Trees")
N = 2048
CELL = N // 2
SPECIES_ORDER = ['Sau', 'XaCu', 'Bang', 'HoaSua']
CELL_POS = {'Sau': (0, 0), 'XaCu': (1, 0), 'Bang': (0, 1), 'HoaSua': (1, 1)}   # (col, row), row 0 = top

ATLAS = os.path.join(TREE_SRC, "leaves_atlas_transparent.png")
WHORL = os.path.join(TREE_SRC, "leaf_card_texture.png")

# per species: sprites (file, box l,t,r,b in px), copies around the centre, sprite scale (of the cell),
# radial offset (of the cell), hue tint (multiplier on RGB), seed
CLUSTERS = {
    # sau: pinnate compound leaves, small leaflets, dense rounded crown -> birch-like sprigs, many
    'Sau':    dict(sprites=[(ATLAS, 'row6')], copies=9, scale=0.42, radius=0.20, tint=(0.86, 1.00, 0.78), seed=1),
    # xa cu: pinnate, darker glossy oblong leaflets -> birch sprigs of rows 4-5 (no oak / maple), deeper green
    'XaCu':   dict(sprites=[(ATLAS, 'row4b'), (ATLAS, 'row5b')], copies=8, scale=0.46, radius=0.19,
                   tint=(0.72, 0.88, 0.70), seed=2),
    # bang: big obovate leaves in rosettes at the twig tips -> single ovate leaves arranged radially
    'Bang':   dict(sprites=[(ATLAS, 'row3')], copies=7, scale=0.40, radius=0.22, tint=(0.95, 1.02, 0.80), seed=3,
                   radial=True),
    # hoa sua: whorled leaves -> the 5-leaf whorl image, 3 whorls (scale, turn deg) to fill the card
    'HoaSua': dict(sprites=[(WHORL, None)], whorls=[(1.12, 0), (0.98, 36), (0.62, 18)], tint=(0.88, 1.00, 0.85),
                   seed=4),
}
# atlas bands in leaves_atlas_transparent.png (1024 px): y range, x range, min height/width (keeps the
# elongated ovate leaves, drops the round maple leaf); sprites themselves found by components()
ROWS = {'row3':  ((360, 530), (0, 1024), 1.25),
        'row4b': ((540, 700), (690, 1024), 0.0),
        'row5b': ((700, 865), (700, 1024), 0.0),
        'row6':  ((865, 1024), (0, 1024), 0.0)}


def components(alpha, thr=40, step=2, min_area=1200):
    """Bounding boxes of the opaque blobs (4-connected flood fill on a downsampled mask)."""
    m = alpha[::step, ::step] > thr
    h, w = m.shape
    seen = np.zeros_like(m)
    boxes = []
    for y0 in range(h):
        for x0 in range(w):
            if not m[y0, x0] or seen[y0, x0]:
                continue
            stack = [(y0, x0)]
            seen[y0, x0] = True
            t, l, b, r, n = y0, x0, y0, x0, 0
            while stack:
                y, x = stack.pop()
                n += 1
                t, b, l, r = min(t, y), max(b, y), min(l, x), max(r, x)
                for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= yy < h and 0 <= xx < w and m[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        stack.append((yy, xx))
            if n * step * step >= min_area:
                boxes.append((l * step, t * step, (r + 1) * step, (b + 1) * step))
    return boxes


def bleed(rgb, known, iters):
    """Fill rgb outside `known` with the average of known 4-neighbours, `iters` rings outwards."""
    rgb, filled = rgb.copy(), known.copy()
    for _ in range(iters):
        acc = np.zeros_like(rgb)
        cnt = np.zeros(filled.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            f = np.roll(filled, (dy, dx), (0, 1))
            acc += np.roll(rgb, (dy, dx), (0, 1)) * f[..., None]
            cnt += f
        new = (~filled) & (cnt > 0)
        if not new.any():
            break
        rgb[new] = acc[new] / cnt[new][:, None]
        filled |= new
    return rgb, filled


def defringe(im, ring=3):
    """The stock images were cut out from white: their soft edge pixels are leaf blended with white
    (a pale halo once alpha-clipped). Recolour every texel within `ring` px of the transparent area
    (and any whitish texel) from the solid interior, keep the alpha."""
    a = np.asarray(im, dtype=np.float32)
    al = a[..., 3]
    solid = al > 245
    for _ in range(ring):                                       # erode the solid mask
        solid &= np.roll(solid, 1, 0) & np.roll(solid, -1, 0) & np.roll(solid, 1, 1) & np.roll(solid, -1, 1)
    solid &= a[..., :3].min(-1) < 170                           # whitish texels are fringe too
    rgb, _ = bleed(a[..., :3], solid, ring + 4)
    a[..., :3] = rgb
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")


def sprites_of(path, band):
    im = Image.open(path).convert("RGBA")
    if band is None:
        return [defringe(im)]
    a = np.asarray(im)[..., 3]
    (y0, y1), (x0, x1), min_aspect = ROWS[band]
    out = []
    for l, t, r, b in components(a, min_area=3000):
        cy, cx = (t + b) / 2, (l + r) / 2
        if y0 <= cy < y1 and x0 <= cx < x1 and (b - t) >= min_aspect * (r - l):
            out.append(defringe(im.crop((max(0, l - 4), max(0, t - 4), r + 4, b + 4))))
    return out


def tinted(sp, tint):
    a = np.asarray(sp, dtype=np.float32)
    a[..., :3] = np.clip(a[..., :3] * np.array(tint, np.float32), 0, 255)
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def compose(cfg):
    """One leaf-cluster cell (CELL x CELL, RGBA)."""
    rng = random.Random(cfg['seed'])
    cell = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
    sprites = [s for p, band in cfg['sprites'] for s in sprites_of(p, band)]
    if not sprites:
        raise RuntimeError(f"no sprites for {cfg}")
    c = CELL / 2
    if 'whorls' in cfg:                                         # whole whorl image, centred, several turns
        for scale, turn in cfg['whorls']:
            sp = tinted(sprites[0], cfg['tint'])
            s = scale * CELL / max(sp.size)
            sp = sp.resize((max(1, int(sp.width * s)), max(1, int(sp.height * s))), Image.LANCZOS)
            rot = sp.rotate(turn, resample=Image.BICUBIC, expand=True)
            cell.alpha_composite(rot, (int(c - rot.width / 2), int(c - rot.height / 2)))
    n = cfg.get('copies', 0)
    order = list(range(n))
    rng.shuffle(order)                                          # paint order: not always the same leaf on top
    for k in order:
        sp = tinted(sprites[k % len(sprites)], cfg['tint'])
        ang = 360.0 * k / n + rng.uniform(-12, 12)
        target = cfg['scale'] * CELL * rng.uniform(0.85, 1.1)
        s = target / max(sp.size)
        sp = sp.resize((max(1, int(sp.width * s)), max(1, int(sp.height * s))), Image.LANCZOS)
        # sprites have the stem at the bottom: rotate so the leaf points away from the centre
        rot = sp.rotate(-ang if cfg.get('radial') else -ang + rng.uniform(-20, 20),
                        resample=Image.BICUBIC, expand=True)
        rad = cfg['radius'] * CELL
        a = math.radians(ang - 90)
        px = c + math.cos(a) * rad - rot.width / 2
        py = c + math.sin(a) * rad - rot.height / 2
        cell.alpha_composite(rot, (int(px), int(py)))
    # keep a 2% transparent border so mips / bilinear never bleed into the neighbour cell
    m = int(CELL * 0.02)
    a = np.asarray(cell).copy()
    a[:m, :, 3] = a[-m:, :, 3] = 0
    a[:, :m, 3] = a[:, -m:, 3] = 0
    return Image.fromarray(a, "RGBA")


def dilate_rgb(im, iters=24):
    """Bleed leaf colour into the transparent texels (no white / black halo with alpha clip + mips)."""
    a = np.asarray(im, dtype=np.float32)
    al = a[..., 3] > 8
    rgb, filled = bleed(a[..., :3], al, iters)
    mean = rgb[al].mean(0) if al.any() else np.array([60, 90, 40], np.float32)
    rgb[~filled] = mean
    a[..., :3] = rgb
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")


def srgb_to_lin(c):
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def main():
    if "--list" in sys.argv:
        for band in ROWS:
            sp = sprites_of(ATLAS, band)
            print(band, len(sp), [s.size for s in sp])
        return
    os.makedirs(OUT, exist_ok=True)
    atlas = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    blob = {}
    for sp in SPECIES_ORDER:
        cell = compose(CLUSTERS[sp])
        col, row = CELL_POS[sp]
        atlas.alpha_composite(cell, (col * CELL, row * CELL))
        a = np.asarray(cell, dtype=np.float32) / 255.0
        m = a[..., 3] > 0.5
        mean = a[..., :3][m].mean(0)
        blob[sp] = dict(srgb=[round(float(v), 4) for v in mean],
                        linear=[round(float(v), 4) for v in srgb_to_lin(mean)],
                        coverage=round(float(m.mean()), 3))
        print(f"[tex] {sp}: coverage {m.mean():.2f}, mean sRGB {np.round(mean, 3)}")
    atlas = dilate_rgb(atlas)
    atlas.save(os.path.join(OUT, "T_Foliage.png"))
    prev = Image.new("RGBA", (N, N), (128, 128, 128, 255))
    clip = np.asarray(atlas).copy()
    clip[..., 3] = np.where(clip[..., 3] > 127, 255, 0)        # as the shader sees it (alpha clip 0.5)
    prev.alpha_composite(Image.fromarray(clip, "RGBA"))
    prev.convert("RGB").resize((1024, 1024), Image.LANCZOS).save(os.path.join(OUT, "T_Foliage_preview.png"))
    json.dump(dict(order=SPECIES_ORDER, cell_pos=CELL_POS, blob=blob), open(os.path.join(OUT, "T_Foliage_blob.json"), "w"), indent=1)
    Image.open(os.path.join(TREE_SRC, "bark_seamless.jpg")).convert("RGB").save(os.path.join(OUT, "T_Bark.png"))
    print("[tex] wrote", OUT)


if __name__ == "__main__":
    main()
