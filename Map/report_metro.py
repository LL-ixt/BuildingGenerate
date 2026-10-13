"""METRO V2 check: the viaduct line + piers from Unity (Unity_logs/metro_layout.json, written by
MetroBuilder.Rebuild) over the road surface / median zones of out/city.json.
Piers in a median zone = green, off the road = blue (the line crosses a block: fine),
on the road outside a median zone = red (a junction: wrong).

    python Map/report_metro.py      -> Map/out/report_metro_piers.png
"""
import json
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    city = json.load(open(os.path.join(HERE, 'out', 'city.json'), encoding='utf-8'))
    lay = json.load(open(os.path.join(ROOT, 'Unity_logs', 'metro_layout.json'), encoding='utf-8'))
    line = list(zip(lay['line'][0::2], lay['line'][1::2]))
    piers = lay['piers']
    lx, ly = zip(*line)
    box = (min(lx) - 60, min(ly) - 60, max(lx) + 60, max(ly) + 60)
    roads = [LineString(r['line']).buffer(r['width'] / 2, cap_style='flat')
             for r in city['roads'] if len(r['line']) > 1 and r.get('layer', 0) <= 0
             and LineString(r['line']).intersects(Polygon.from_bounds(*box))]
    surf = unary_union(roads)
    meds = [Polygon(list(zip(m['ring'][0::2], m['ring'][1::2]))) for m in city['medians']]
    from shapely.geometry import Point
    on_road = {p[0]: surf.contains(Point(p[1], p[2])) for p in piers}
    bad = [p for p in piers if not p[4] and on_road[p[0]]]
    zooms = bad[:5]
    n = 1 + len(zooms)
    fig = plt.figure(figsize=(8 + 5 * len(zooms), 9), dpi=100)
    for i, view in enumerate([None] + zooms):
        ax = fig.add_subplot(1, n, i + 1)
        for g in getattr(surf, 'geoms', [surf]):
            ax.fill(*g.exterior.xy, color='#c9c9c9', lw=0)
            for h in g.interiors:
                ax.fill(*h.xy, color='white', lw=0)
        for m in meds:
            ax.fill(*m.exterior.xy, color='#7fbf7f', lw=0)
        ax.plot(lx, ly, color='#2255cc', lw=1.0 if view is None else 2.0)
        for k, x, y, s, inz in piers:
            ax.plot(x, y, 'o', ms=3 if view is None else 9, color='#1a8f1a' if inz else ('#d62020' if on_road[k] else '#2a6fd6'))
            if view is not None and abs(x - view[1]) < 60 and abs(y - view[2]) < 60:
                ax.annotate(f"{k}", (x, y), xytext=(6, 6), textcoords='offset points', fontsize=9)
        if view is None:
            ax.set_xlim(box[0], box[2]); ax.set_ylim(box[1], box[3])
            ax.set_title(f"{len(piers)} trụ, {len(bad)} trên mặt đường ngoài dải giữa (đỏ), xanh dương = ngoài lòng đường")
        else:
            ax.set_xlim(view[1] - 60, view[1] + 60); ax.set_ylim(view[2] - 60, view[2] + 60)
            ax.set_title(f"trụ {view[0]} (s = {view[3]:.0f} m)")
        ax.set_aspect('equal')
        ax.tick_params(labelsize=7)
    fig.tight_layout()
    out = os.path.join(HERE, 'out', 'report_metro_piers.png')
    fig.savefig(out)
    print('report', out, 'bad piers', [p[0] for p in bad])


if __name__ == '__main__':
    main()
