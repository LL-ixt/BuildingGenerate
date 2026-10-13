"""Sky HDRI for Unity (skybox + ambient + reflections) -> Export/Textures/Sky/HDRI_HanoiDay.hdr

    python Blender/scripts/build_sky_hdri.py [source.hdr] [--desat 0.3]

The Poly Haven sun is ~1e5 bright: used as-is it leaks into the ambient probe as a second sun, so it
is clamped (the Directional Light is the sun). The sky can be desaturated towards the hazy, pale
Hanoi sky of Ref/ref.jpg. Sun direction + horizon colour go to HDRI_HanoiDay.json for HanoiLighting.cs.
"""
import argparse, json, os
import numpy as np

ROOT = r"D:\Project III\BuildingGenerate"
SRC = os.path.join(ROOT, "Textures", "src", "hdri", "sun_2k.hdr")
OUT = os.path.join(ROOT, "Export", "Textures", "Sky", "HDRI_HanoiDay.hdr")
OUT_JSON = OUT[:-4] + ".json"
CLAMP = 12.0
DESATURATE = 0.3
LUM = np.array([0.2126, 0.7152, 0.0722])


def read_hdr(path):
    data = open(path, "rb").read()
    i = data.index(b"\n\n") + 2
    j = data.index(b"\n", i)
    res = data[i:j].decode().split()
    h, w = int(res[1]), int(res[3])
    p = j + 1
    img = np.zeros((h, w, 4), np.uint8)
    for y in range(h):
        assert data[p] == 2 and data[p + 1] == 2, "only new-style RLE supported"
        p += 4
        for c in range(4):
            x = 0
            while x < w:
                n = data[p]; p += 1
                if n > 128:
                    n -= 128
                    img[y, x:x + n, c] = data[p]; p += 1
                else:
                    img[y, x:x + n, c] = np.frombuffer(data[p:p + n], np.uint8); p += n
                x += n
    e = img[..., 3].astype(np.int32)
    scale = np.where(e > 0, np.ldexp(1.0, e - 136), 0.0)
    return img[..., :3] * scale[..., None]


def write_hdr(path, rgb):
    h, w, _ = rgb.shape
    m = rgb.max(axis=2)
    mant, expo = np.frexp(m)
    scale = np.where(m > 1e-32, mant * 256.0 / np.maximum(m, 1e-32), 0.0)
    rgbe = np.zeros((h, w, 4), np.uint8)
    rgbe[..., :3] = np.clip(rgb * scale[..., None], 0, 255).astype(np.uint8)
    rgbe[..., 3] = np.where(m > 1e-32, expo + 128, 0).astype(np.uint8)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n")
        f.write(f"-Y {h} +X {w}\n".encode())
        f.write(rgbe.tobytes())   # flat (non-RLE) scanlines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", default=SRC)
    ap.add_argument("--desat", type=float, default=DESATURATE)
    args = ap.parse_args()

    rgb = read_hdr(args.src)
    while rgb.shape[1] > 2048:   # Unity imports it at 2048 anyway
        h2, w2 = rgb.shape[0] // 2 * 2, rgb.shape[1] // 2 * 2
        rgb = rgb[:h2, :w2].reshape(h2 // 2, 2, w2 // 2, 2, 3).mean(axis=(1, 3))
    h, w, _ = rgb.shape
    lum = rgb @ LUM
    y, x = np.unravel_index(np.argmax(lum), lum.shape)
    u, v = (x + 0.5) / w, (y + 0.5) / h

    grey = (rgb @ LUM)[..., None]
    rgb = grey + (rgb - grey) * (1.0 - args.desat)
    lum = rgb @ LUM
    rgb *= np.minimum(1.0, CLAMP / np.maximum(lum, 1e-6))[..., None]
    write_hdr(OUT, rgb.astype(np.float32))

    horizon = rgb[int(h * 0.46):int(h * 0.49)].reshape(-1, 3).mean(0)
    info = {"source": os.path.basename(args.src), "sun_u": round(float(u), 4),
            "sun_elevation": round(float(90 - v * 180), 2), "horizon": [round(float(c), 4) for c in horizon],
            "clamp": CLAMP, "desaturate": args.desat}
    with open(OUT_JSON, "w") as f:
        json.dump(info, f, indent=1)
    print(json.dumps(info))
    print(f"written {OUT} ({w}x{h})")


if __name__ == "__main__":
    main()
