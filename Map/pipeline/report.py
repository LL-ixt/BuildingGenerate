"""GeoJSON layers for QGIS and the report pictures."""
import json, math, os
import numpy as np

import shapely
from shapely.geometry import mapping

from .osm import polygons_of
from .trees import TREE_SPECIES, tree_crowns



def save_geojson(out, name, feats, proj):
    def tr(g):
        if g is None or g.is_empty:               # e.g. no median in this area: transform needs a 2-D array
            return g
        return shapely.transform(g, lambda c: np.array([proj.inv(x, y) for x, y in c]).reshape(-1, 2))
    fc = dict(type='FeatureCollection', features=[
        dict(type='Feature', properties=props, geometry=mapping(tr(g))) for props, g in feats])
    with open(os.path.join(out, name), 'w', encoding='utf-8') as f:
        json.dump(fc, f)


def report_png(path, area, raw_buildings, surface, sidewalk, water, open_, lots, big, flags, zoom=None,
               median=None, rails=(), kerbs=(), skirts=(), trees=(), motos=()):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.path import Path
    from matplotlib.patches import PathPatch
    from matplotlib.collections import PatchCollection

    def patches(geoms, **kw):
        """Polygons with holes (the street network is one polygon whose holes are the blocks)."""
        ps = []
        for g in geoms:
            for p in polygons_of(g):
                rings = [p.exterior] + list(p.interiors)
                verts, codes = [], []
                for r in rings:
                    c = list(r.coords)
                    verts += c
                    codes += [Path.MOVETO] + [Path.LINETO] * (len(c) - 2) + [Path.CLOSEPOLY]
                ps.append(PathPatch(Path(verts, codes)))
        return PatchCollection(ps, **kw)

    x0, y0, x1, y1 = zoom or area.bounds
    w = 22
    fig, ax = plt.subplots(figsize=(w, w * (y1 - y0) / (x1 - x0)), dpi=110)
    ax.set_facecolor('#f4f1ea')
    ax.add_collection(patches([water], facecolor='#9cc7e6', edgecolor='none'))
    ax.add_collection(patches([open_], facecolor='#bfdcae', edgecolor='none'))
    ax.add_collection(patches([sidewalk], facecolor='#d9d4cc', edgecolor='none'))
    ax.add_collection(patches([surface], facecolor='#6e6e6e', edgecolor='none'))
    if median is not None:
        ax.add_collection(patches([median], facecolor='#2f7d32', edgecolor='none'))
    ax.add_collection(patches(raw_buildings, facecolor='none', edgecolor='#999999', linewidth=0.3))
    ax.add_collection(patches([l['rect'] for l in lots], facecolor='#e8a65d', edgecolor='#8a5a2b', linewidth=0.2))
    ax.add_collection(patches([b['rect'] for b in big], facecolor='#5b7bb5', edgecolor='#1f3460', linewidth=0.4))
    for r in rails:
        for l in getattr(r['centre'], 'geoms', [r['centre']]):
            ax.plot(*l.xy, color='#1f4fd1', linewidth=1.2, linestyle='--')
    for ls, col in ((kerbs, '#d11f1f'), (skirts, '#1f6fd1')):
        for l in ls:
            ax.plot(*l.xy, color=col, linewidth=0.8)
    for f in flags:
        ax.add_patch(plt.Circle(f['xy'], 12, fill=False, color='red', linewidth=1.5))
    if trees:
        crowns = tree_crowns()
        cols = ['#2e7d32', '#1b5e20', '#9ccc65', '#00897b']          # Sau, XaCu, Bang, HoaSua
        from matplotlib.collections import PatchCollection as PC
        for sp in range(len(TREE_SPECIES)):
            ts = [t for t in trees if t['sp'] == sp]
            ax.add_collection(PC([plt.Circle((t['x'], t['y']), crowns[sp] * t['scale']) for t in ts],
                                 facecolor=cols[sp], edgecolor='black', linewidth=0.2, alpha=0.55))
            ax.plot([], [], 'o', color=cols[sp], label=f"{TREE_SPECIES[sp]} ({len(ts)})")
        ax.legend(loc='upper right', fontsize=14)
    if motos:                                          # parked bikes: 0.72 x 2.0 m boxes, nose = dot
        from matplotlib.collections import PatchCollection as PC
        boxes = []
        for m in motos:
            a = math.radians(m['yaw'])
            fx, fy = math.sin(a), math.cos(a)
            sx, sy = fy, -fx
            cx, cy = m['x'], m['y']
            boxes.append(plt.Polygon([(cx + fx * hl + sx * hw, cy + fy * hl + sy * hw)
                                      for hl, hw in ((1.0, 0.36), (1.0, -0.36), (-1.0, -0.36), (-1.0, 0.36))]))
            ax.plot(cx + fx * 0.8, cy + fy * 0.8, '.', color='black', markersize=1.5)
        ax.add_collection(PC(boxes, facecolor='#e0218a', edgecolor='black', linewidth=0.2))
        ax.plot([], [], 's', color='#e0218a', label=f"xe may ({len(motos)})")
        ax.legend(loc='upper right', fontsize=14)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect('equal')
    ax.set_title('xam = duong | be = via he | xanh la dam = vung tru metro | net xanh = metro | cam = lo nha ong | xanh duong = nha lon/thap | vien xam = OSM goc | do = can xem')
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
