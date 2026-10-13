"""Ground textures for Unity -> Export/Textures/Ground/*.png

    python Blender/scripts/tint_asphalt.py      # grey aggregate photo -> pale beige + blue-green stones (once)
    python Blender/scripts/build_ground_textures.py

  road.png / road_n.png / road_macro.png   asphalt (Textures/src/gemini/asphalt.png, one tile = 1 m x 1 m),
                                           its normal map, and a large-scale brightness noise used as a
                                           detail map so the 1 m tile does not repeat visibly
  kerb.png / kerb_n.png                    2048x256 = 4 kerb stones (1 m each) x 0.5 m of profile arc; built
                                           from the grey aggregate photo (stones differ, dark joints, dirty foot)
  sidewalk.png                             paving slabs (old/sidewalk.jpg) - unchanged
  block_ground.png                         lot ground (old/ground.png) - unchanged
Falls back to old/road.jpg for the asphalt when gemini/asphalt.png is missing.
"""
import os, sys
import numpy as np
from PIL import Image, ImageFilter

ROOT = r"D:\Project III\BuildingGenerate"
sys.path.insert(0, os.path.join(ROOT, "Blender", "scripts"))
from build_trim_texture import seamless

SRC = os.path.join(ROOT, "Textures", "src")
OUT = os.path.join(ROOT, "Export", "Textures", "Ground")
KERB_ARC = 0.5            # m of texture height; must match StreetBuilder.TexV
KERB_USED = 0.355         # m: profile arc length (slope + lip)
rng = np.random.default_rng(7)


def flat_tile(path, size, flatten, strength=1.0):
    """Colour image, lighting gradient removed (keeps the average colour), then made seamless."""
    im = Image.open(path).convert("RGB").resize((size, size), Image.LANCZOS)
    a = np.asarray(im, dtype=np.float32)
    low = np.asarray(im.filter(ImageFilter.GaussianBlur(flatten)), dtype=np.float32)
    mean = a.reshape(-1, 3).mean(0)
    out = np.clip(a - low * strength + mean * strength, 0, 255).astype(np.uint8)
    return seamless(Image.fromarray(out, "RGB"))


def lum(a):
    return a @ np.array([0.299, 0.587, 0.114], np.float32)


def normal_map(height, strength, wrap=True):
    """Tangent-space normal map (OpenGL / Unity convention, +Y up) from a height image 0..1."""
    h = height.astype(np.float32)
    if wrap:
        dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5
        dy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 0.5
    else:
        dx = np.gradient(h, axis=1)
        dy = np.gradient(h, axis=0)
    # image rows run top -> bottom, texture v runs bottom -> top
    n = np.stack([-dx * strength, dy * strength, np.ones_like(h)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return Image.fromarray(((n * 0.5 + 0.5) * 255 + 0.5).astype(np.uint8), "RGB")


def periodic_noise(size, lo, hi, seed):
    """Seamless band-limited noise 0..1 (FFT filtered white noise: periodic by construction)."""
    r = np.random.default_rng(seed)
    f = np.fft.fft2(r.standard_normal((size, size)))
    fy = np.fft.fftfreq(size)[:, None] * size
    fx = np.fft.fftfreq(size)[None, :] * size
    k = np.hypot(fx, fy)
    f *= ((k >= lo) & (k <= hi)) / np.maximum(k, 1.0) ** 0.8
    n = np.fft.ifft2(f).real
    n = (n - n.mean()) / (n.std() + 1e-6)
    return n


def build_road():
    src = os.path.join(SRC, "gemini", "asphalt.png")
    if os.path.exists(src):
        im = Image.open(src).convert("RGB").resize((1024, 1024), Image.LANCZOS)
        print("[ground] asphalt from", src)
    else:
        im = flat_tile(os.path.join(SRC, "old", "road.jpg"), 1024, 80)
        print("[ground] asphalt: gemini/asphalt.png missing, old road.jpg")
    im.save(os.path.join(OUT, "road.png"))
    a = np.asarray(im, np.float32) / 255.0
    g = lum(a)
    # stones read as bumps: blurred inverted luminance (dark chips) + fine grain
    h = 1.0 - g
    h = 0.7 * np.asarray(Image.fromarray((h * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255 + 0.3 * h
    normal_map(h, 5.0).save(os.path.join(OUT, "road_n.png"))
    # macro: patches of 3-30 m (tile = 24 m) -> detail albedo, neutral grey 0.5 = no change (MULX2)
    n = periodic_noise(512, 2, 24, 1) * 0.6 + periodic_noise(512, 24, 90, 2) * 0.4
    m = np.clip(0.5 + n * 0.022, 0.42, 0.58)       # URP multiplies by ~4.6 * linear(value): keep it gentle
    Image.fromarray((np.stack([m, m, m * 0.99], -1) * 255).astype(np.uint8), "RGB").save(os.path.join(OUT, "road_macro.png"))


def build_kerb():
    """4 stones side by side. Rows run top -> bottom in the file; v = 1 - row/(H-1), arc = v * KERB_ARC."""
    gray = os.path.join(SRC, "gemini", "asphalt_gray_src.png")
    if not os.path.exists(gray):
        gray = os.path.join(SRC, "gemini", "asphalt.png")
    g = lum(np.asarray(Image.open(gray).convert("RGB"), np.float32)) / 255.0
    W, H, N = 2048, 256, 4
    sw = W // N
    stone_h = np.zeros((H, W), np.float32)
    shade = np.zeros((H, W), np.float32)
    for i in range(N):
        sc = 1.3                                              # source px per output px
        cw, ch = int(sw * sc), int(H * sc)
        x0 = rng.integers(0, g.shape[1] - cw); y0 = rng.integers(0, g.shape[0] - ch)
        crop = g[y0:y0 + ch, x0:x0 + cw]
        crop = np.asarray(Image.fromarray((crop * 255).astype(np.uint8)).resize((sw, H), Image.LANCZOS), np.float32) / 255
        crop = (crop - crop.mean()) * 1.0 + crop.mean()
        stone_h[:, i * sw:(i + 1) * sw] = crop
        shade[:, i * sw:(i + 1) * sw] = rng.uniform(0.93, 1.07)
    # per-stone slow brightness drift
    drift = np.asarray(Image.fromarray(((periodic_noise(256, 1, 4, 5) * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8)).resize((W, H), Image.BICUBIC), np.float32) / 255
    base = np.clip(0.60 + (stone_h - stone_h.mean()) * 0.55, 0, 1) * shade * (0.97 + 0.06 * drift)
    # joints between stones (also at the wrap edge) and edge wear
    x = np.arange(W)[None, :]
    d = np.minimum(x % sw, sw - 1 - x % sw).astype(np.float32)
    joint = np.exp(-(d / 2.2) ** 2)
    base *= 1.0 - 0.45 * joint
    # dirt towards the road side (high arc), cleaner near the sidewalk side
    v = 1.0 - np.arange(H)[:, None] / (H - 1)
    arc = v * KERB_ARC
    dirt = np.clip((arc - 0.22) / (KERB_USED - 0.22), 0, 1)
    base *= 1.0 - 0.18 * dirt
    base *= 1.0 - 0.10 * np.clip((0.04 - arc) / 0.04, 0, 1)          # shaded top edge under the sidewalk lip
    col = np.stack([base * 0.94, base * 0.92, base * 0.88], -1)      # warm light grey; mean ~ 0.54
    Image.fromarray((np.clip(col, 0, 1) * 255).astype(np.uint8), "RGB").save(os.path.join(OUT, "kerb.png"))
    h = stone_h * 0.6 - joint * 0.5
    normal_map(h, 2.5).save(os.path.join(OUT, "kerb_n.png"))


def main():
    os.makedirs(OUT, exist_ok=True)
    build_road()
    build_kerb()
    flat_tile(os.path.join(SRC, "old", "ground.png"), 1024, 120).save(os.path.join(OUT, "block_ground.png"))
    Image.open(os.path.join(SRC, "old", "sidewalk.jpg")).convert("RGB").resize((512, 512), Image.LANCZOS).save(
        os.path.join(OUT, "sidewalk.png"))
    print("[ground] ->", OUT)


if __name__ == "__main__":
    main()
