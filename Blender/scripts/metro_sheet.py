"""METRO preview sheet: refs + renders of build_metro.py --preview + the deck cross-section with
dimensions (drawn from Export/Metro/metro.json).

Plain Python 3.12:  python Blender/scripts/metro_sheet.py [tag]      (tag default v1)
Writes Blender/previews/metro_<tag>_sheet.png.
"""
import json
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon as MplPolygon
from PIL import Image

ROOT = r"D:\Project III\BuildingGenerate"
TAG = sys.argv[1] if len(sys.argv) > 1 else "v1"
SRC = os.path.join(ROOT, "Blender", "previews", f"metro_{TAG}")
OUT = os.path.join(ROOT, "Blender", "previews", f"metro_{TAG}_sheet.png")
PANELS = [("Ref/overallview.jpeg", "ref tổng quan"), ("drone.png", "drone (giống ref)"),
          ("Ref/metro1.jpg", "ref mép dầm / xà mũ"), ("side.png", "dọc tuyến, cao 7.5 m"),
          ("Ref/cot.jpg", "ref trụ"), ("under.png", "gầm cầu, mắt người"),
          ("Ref/cot_shape.png", "ref hình xà mũ"), ("section.png", "mặt cắt đầu tuyến (ortho)"),
          ("deck.png", "trên dầm"), ("curve.png", "đoạn cong R 220 m")]
COLOURS = {'M_MetroConcrete': '#b9b9b4', 'M_MetroConcreteDark': '#7d7d7a', 'M_MetroBarrier': '#dde8ee',
           'M_MetroSteel': '#55585c', 'M_MetroYellow': '#e2b52a'}


def section(ax, data):
    for p in data['profiles']:
        if p['lods'][0] != 0:
            continue
        ax.add_patch(MplPolygon(np.array(p['pts']).reshape(-1, 2), closed=True, fc=COLOURS.get(p['mat'], '#ccc'),
                                ec='#333', lw=0.5))
    hw = data['half_width']
    ax.annotate('', (-hw, -2.6), (hw, -2.6), arrowprops=dict(arrowstyle='<->', lw=0.8))
    ax.text(0, -2.85, f"{2 * hw:.1f} m", ha='center', va='top', fontsize=8)
    d = data['deck_top'] - data['girder_bottom']
    ax.annotate('', (hw + 0.5, 0), (hw + 0.5, -d), arrowprops=dict(arrowstyle='<->', lw=0.8))
    ax.text(hw + 0.65, -d / 2, f"dầm {d:.1f} m", va='center', fontsize=8)
    ts = data['track_spacing']
    for x in (-ts / 2, ts / 2):
        ax.axvline(x, color='#c33', lw=0.5, ls='--')
    ax.text(0, 3.0, f"tim ray cách {ts:.1f} m, khổ {data['gauge']} m — đỉnh ray y {data['rail_top']} m, "
                    f"đỉnh trụ {data['cap_top']:.2f} m", ha='center', fontsize=8)
    ax.set_xlim(-hw - 0.8, hw + 2.4); ax.set_ylim(-3.3, 3.3)
    ax.set_aspect('equal'); ax.set_title('mặt cắt dầm LOD0 (m)', fontsize=10)
    ax.tick_params(labelsize=7)


def main():
    data = json.load(open(os.path.join(ROOT, "Export", "Metro", "metro.json"), encoding='utf-8'))
    panels = []
    for name, title in PANELS:
        p = os.path.join(ROOT, name) if name.startswith("Ref/") else os.path.join(SRC, name)
        if os.path.exists(p):
            panels.append((title, np.asarray(Image.open(p).convert('RGB'))))
    cols = 4
    n = len(panels) + 1
    nrow = (n + cols - 1) // cols
    fig = plt.figure(figsize=(cols * 5.0, nrow * 4.6), dpi=110)
    for i, (title, im) in enumerate(panels):
        ax = fig.add_subplot(nrow, cols, i + 1)
        ax.imshow(im)
        ax.set_title(title, fontsize=10); ax.axis('off')
    section(fig.add_subplot(nrow, cols, n), data)
    fig.tight_layout()
    fig.savefig(OUT)
    print('sheet', OUT)


if __name__ == '__main__':
    main()
