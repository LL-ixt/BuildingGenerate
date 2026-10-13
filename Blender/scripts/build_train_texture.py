"""TRAIN T1 livery atlas (Ref/train.webp: Hanoi Metro Line 3, red front mask, lime-green cheeks and
lower body, black windscreen / window band, light grey roof). Plain Python 3.12 (numpy, PIL):
    python Blender/scripts/build_train_texture.py

Atlas 4096 x 2048 (pixels, top-left origin; atlas.json stores UV boxes u0, v0, u1, v1 with v up):
    SIDE_END  0,0 - 4096,512       end car side: u = along the car (rear -> front tip), v = height
                                   Z_SIDE[0] .. Z_SIDE[1] above rail top (top row = Z_SIDE[1])
    SIDE_MID  0,512 - 4096,1024    middle car side, same rule
    FRONT     0,1024 - 1024,2048   front, planar: u = across (A_FRONT), v = height (Z_FRONT)
    cells     1024+ , 1024+        flat palette cells 128 x 128 (CELLS)
Outputs Blender/train/T_Train.png (sRGB albedo), T_TrainData.png (R roughness, G metallic, B emission:
LED strips + destination display) and
atlas.json (also the car dimensions and door layout, read by hanoi_train.py).
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = r"D:\Project III\BuildingGenerate"
OUT = os.path.join(ROOT, "Blender", "train")
W, H = 4096, 2048
FONT = r"C:\Windows\Fonts\arialbd.ttf"

# car layout (metres) -- shared with hanoi_train.py through atlas.json
CAR = dict(end_len=20.0, mid_len=19.0, door_w=1.4, cab_len=2.4)
DOORS_MID = [-7.2, -2.4, 2.4, 7.2]            # door centres along the car (s, + = front)
DOORS_END = [-7.4, -2.6, 2.2]                  # the end car's front 2.4 m is the cab
Z_SIDE = (0.80, 3.62)                          # body side band covered by SIDE_* rows
A_FRONT = (-1.45, 1.45)
Z_FRONT = (0.30, 3.85)
Z = dict(skirt=0.98, win0=1.95, win1=2.95, stripe=3.03, roof=3.62)

RED = (196, 34, 52)
LIME = (178, 198, 34)
BLACK = (16, 19, 23)
GREY = (196, 199, 202)
DARK = (52, 54, 57)

REGIONS_PX = {
    'SIDE_END': (0, 0, 4096, 512),
    'SIDE_MID': (0, 512, 4096, 1024),
    'FRONT':    (0, 1024, 1024, 2048),
}
CELLS = {   # name: (colour sRGB, roughness, metallic)
    'ROOF':    ((188, 191, 194), 0.45, 0.3),
    'UNDER':   ((44, 45, 47), 0.8, 0.1),
    'GANGWAY': ((28, 29, 31), 0.85, 0.0),
    'RUBBER':  ((22, 22, 23), 0.9, 0.0),
    'AC':      ((172, 176, 178), 0.5, 0.4),
    'WHEEL':   ((96, 92, 88), 0.45, 0.9),
    'BOGIE':   ((38, 40, 42), 0.7, 0.3),
    'COUPLER': ((110, 112, 115), 0.5, 0.6),
    'LIME':    (LIME, 0.35, 0.15),
    'RED':     (RED, 0.35, 0.15),
}
CELL = 128


def cell_boxes():
    boxes = {}
    for i, name in enumerate(CELLS):
        x0 = 1024 + (i % 16) * CELL
        y0 = 1024 + (i // 16) * CELL
        boxes[name] = (x0, y0, x0 + CELL, y0 + CELL)
    return boxes


def uv_box(px):
    x0, y0, x1, y1 = px
    return [x0 / W, 1 - y1 / H, x1 / W, 1 - y0 / H]


class Canvas:
    """Albedo + data (roughness, metallic) drawn together."""

    def __init__(self):
        self.alb = Image.new('RGB', (W, H), (128, 128, 128))
        self.dat = Image.new('RGB', (W, H), (int(0.5 * 255), 0, 0))
        self.da = ImageDraw.Draw(self.alb)
        self.dd = ImageDraw.Draw(self.dat)

    def rect(self, box, col, rough, metal=0.0, radius=0):
        d = (int(rough * 255), int(metal * 255), 0)
        if radius:
            self.da.rounded_rectangle(box, radius, fill=col)
            self.dd.rounded_rectangle(box, radius, fill=d)
        else:
            self.da.rectangle(box, fill=col)
            self.dd.rectangle(box, fill=d)

    def poly(self, pts, col, rough, metal=0.0):
        self.da.polygon(pts, fill=col)
        self.dd.polygon(pts, fill=(int(rough * 255), int(metal * 255), 0))

    def line(self, pts, col, width, rough=0.3, metal=0.0):
        self.da.line(pts, fill=col, width=width)
        self.dd.line(pts, fill=(int(rough * 255), int(metal * 255), 0), width=width)


# ---------------------------------------------------------------- side
def side(c, region, length, doors, cab):
    x0, y0, x1, y1 = REGIONS_PX[region]
    s0 = -length / 2
    ppm = (x1 - x0) / length

    def X(s):
        return x0 + (s - s0) * ppm

    def Y(z):
        return y0 + (Z_SIDE[1] - z) / (Z_SIDE[1] - Z_SIDE[0]) * (y1 - y0)

    c.rect((x0, y0, x1, y1), LIME, 0.35, 0.15)                                     # body
    c.rect((x0, Y(Z['skirt']), x1, y1), DARK, 0.7, 0.1)                            # skirt
    c.rect((x0, Y(Z['roof']), x1, Y(Z['stripe'])), GREY, 0.45, 0.3)                # upper side
    c.rect((x0, Y(Z['stripe']), x1, Y(Z['win1'])), RED, 0.35, 0.15)                # red pinstripe
    # glass band with dark mullions every ~1.2 m between doors
    c.rect((x0, Y(Z['win1']), x1, Y(Z['win0'])), BLACK, 0.06, 0.0)
    band = np.asarray(c.alb.crop((int(x0), int(Y(Z['win1'])), int(x1), int(Y(Z['win0'])))), np.float32)
    g = np.linspace(0, 1, band.shape[0])[:, None, None]
    band = band + (1 - g) * 22                                                      # sky reflection on top
    c.alb.paste(Image.fromarray(np.clip(band, 0, 255).astype(np.uint8)), (int(x0), int(Y(Z['win1']))))
    s = s0 + 0.9
    while s < length / 2 - (cab + 0.6 if cab else 0.6):
        if all(abs(s - d) > CAR['door_w'] / 2 + 0.3 for d in doors):
            c.line([(X(s), Y(Z['win1'])), (X(s), Y(Z['win0']))], DARK, 7, 0.5)
        s += 1.2
    # doors: two lime leaves with a tall window each, dark outline, centre seam
    hw = CAR['door_w'] / 2
    for d in doors:
        c.rect((X(d - hw), Y(Z['win1'] + 0.02), X(d + hw), Y(Z['skirt'])), LIME, 0.35, 0.15)
        for side_ in (-1, 1):
            a, b = (d - hw + 0.12, d - 0.08) if side_ < 0 else (d + 0.08, d + hw - 0.12)
            c.rect((X(a), Y(Z['win1'] - 0.05), X(b), Y(Z['win0'] - 0.25)), BLACK, 0.06, 0.0, radius=10)
        c.line([(X(d), Y(Z['win1'] + 0.02)), (X(d), Y(Z['skirt']))], DARK, 6, 0.6)
        c.da.rectangle((X(d - hw), Y(Z['win1'] + 0.02), X(d + hw), Y(Z['skirt'])), outline=DARK, width=7)
    # cab (end car front): red upper wrap, black cab side window, lime below
    if cab:
        sc = length / 2 - cab
        c.rect((X(sc), Y(Z['roof']), x1, Y(1.62)), RED, 0.35, 0.15)
        c.poly([(X(sc + 0.35), Y(2.88)), (X(length / 2 - 0.5), Y(2.88)), (X(length / 2 - 0.15), Y(2.0)),
                (X(sc + 0.35), Y(2.0))], BLACK, 0.06)
        c.line([(X(sc), Y(Z['roof'])), (X(sc), Y(Z['skirt']))], DARK, 6, 0.6)     # cab door seam
    # car ends: dark gangway edge
    c.rect((x0, y0, x0 + 6, y1), DARK, 0.7)
    if not cab:
        c.rect((x1 - 6, y0, x1, y1), DARK, 0.7)


# ---------------------------------------------------------------- front
def front(c):
    x0, y0, x1, y1 = REGIONS_PX['FRONT']

    def X(a):
        return x0 + (a - A_FRONT[0]) / (A_FRONT[1] - A_FRONT[0]) * (x1 - x0)

    def Y(z):
        return y0 + (Z_FRONT[1] - z) / (Z_FRONT[1] - Z_FRONT[0]) * (y1 - y0)

    c.rect((x0, y0, x1, y1), RED, 0.33, 0.15)
    c.rect((x0, y0, x1, Y(3.47)), GREY, 0.45, 0.3)                                 # roof cap
    for sgn in (-1, 1):                                                             # lime cheeks + bumper corners
        pts = [(0.60, Z_FRONT[0]), (1.46, Z_FRONT[0]), (1.46, 1.88), (1.13, 1.88), (0.62, 0.98)]
        c.poly([(X(sgn * a), Y(z)) for a, z in pts], LIME, 0.35, 0.15)
    c.rect((X(-0.60), Y(0.62), X(0.60), Y(Z_FRONT[0])), LIME, 0.35, 0.15)          # bumper
    # windscreen with a soft reflection, wiper
    c.rect((X(-1.03), Y(3.0), X(1.03), Y(1.95)), BLACK, 0.05, 0.0, radius=34)
    ws = np.asarray(c.alb.crop((int(X(-1.03)), int(Y(3.0)), int(X(1.03)), int(Y(1.95)))), np.float32)
    g = np.linspace(0, 1, ws.shape[0])[:, None, None]
    mask = (ws.sum(-1, keepdims=True) < 120)
    ws = np.where(mask, ws + (1 - g) * 26, ws)
    c.alb.paste(Image.fromarray(np.clip(ws, 0, 255).astype(np.uint8)), (int(X(-1.03)), int(Y(3.0))))
    c.line([(X(0.05), Y(2.0)), (X(0.42), Y(2.62))], (40, 42, 45), 6, 0.5)
    # destination display "L3: Cầu Giấy" (orange LED)
    c.rect((X(-0.66), Y(3.36), X(0.66), Y(3.08)), BLACK, 0.1, 0.0, radius=6)
    font = ImageFont.truetype(FONT, int((Y(3.10) - Y(3.33)) * 0.95))
    txt = "L3: Cầu Giấy"
    tw = c.da.textlength(txt, font=font)
    c.da.text(((X(0) - tw / 2), Y(3.335)), txt, font=font, fill=(255, 168, 40))
    c.dd.text(((X(0) - tw / 2), Y(3.335)), txt, font=font, fill=(int(0.1 * 255), 0, 255))     # B = emission
    # LED headlight strips beside the windscreen (slanted) + lamp dots
    for sgn in (-1, 1):
        c.line([(X(sgn * 1.10), Y(1.98)), (X(sgn * 1.20), Y(2.86))], (250, 250, 245), 9, 0.2)
        c.dd.line([(X(sgn * 1.10), Y(1.98)), (X(sgn * 1.20), Y(2.86))], fill=(51, 0, 255), width=9)
        for k in range(6):
            z = 2.05 + k * 0.13
            a = sgn * (1.115 + (z - 1.98) / 0.88 * 0.10)
            c.da.ellipse((X(a) - 5, Y(z) - 5, X(a) + 5, Y(z) + 5), fill=(255, 255, 255))
            c.dd.ellipse((X(a) - 5, Y(z) - 5, X(a) + 5, Y(z) + 5), fill=(51, 0, 255))
    # Hanoi emblem: white ring + simple roof glyph
    r = (X(0.17) - X(0))
    cx, cy = X(0), Y(1.42)
    c.da.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(240, 238, 232), width=7)
    c.da.line([(cx - r * 0.6, cy - r * 0.05), (cx, cy - r * 0.6), (cx + r * 0.6, cy - r * 0.05)], fill=(240, 238, 232), width=7)
    c.da.line([(cx - r * 0.35, cy + r * 0.05), (cx - r * 0.35, cy + r * 0.55), (cx + r * 0.35, cy + r * 0.55),
               (cx + r * 0.35, cy + r * 0.05)], fill=(240, 238, 232), width=6)
    # lamp grilles in the lime corners, coupler pocket
    for sgn in (-1, 1):
        a0, a1 = sorted((sgn * 0.82, sgn * 1.18))
        c.rect((X(a0), Y(0.86), X(a1), Y(0.56)), (176, 180, 184), 0.3, 0.8)
        for k in range(5):
            z = 0.60 + k * 0.05
            c.line([(X(a0) + 4, Y(z)), (X(a1) - 4, Y(z))], (70, 72, 76), 4, 0.5, 0.5)
    c.rect((X(-0.24), Y(0.56), X(0.24), Y(Z_FRONT[0])), DARK, 0.6, 0.3)


def main():
    os.makedirs(OUT, exist_ok=True)
    c = Canvas()
    side(c, 'SIDE_END', CAR['end_len'], DOORS_END, CAR['cab_len'])
    side(c, 'SIDE_MID', CAR['mid_len'], DOORS_MID, 0)
    front(c)
    boxes = cell_boxes()
    for name, (col, rough, metal) in CELLS.items():
        c.rect(boxes[name], col, rough, metal)
    c.alb.save(os.path.join(OUT, 'T_Train.png'))
    c.dat.save(os.path.join(OUT, 'T_TrainData.png'))
    regions = {k: uv_box(v) for k, v in REGIONS_PX.items()}
    regions.update({k: uv_box(v) for k, v in boxes.items()})
    data = dict(regions=regions, car=CAR, doors_end=DOORS_END, doors_mid=DOORS_MID,
                z_side=Z_SIDE, a_front=A_FRONT, z_front=Z_FRONT)
    with open(os.path.join(OUT, 'atlas.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
    print('[train tex] T_Train.png + T_TrainData.png + atlas.json in', OUT)


if __name__ == '__main__':
    main()
