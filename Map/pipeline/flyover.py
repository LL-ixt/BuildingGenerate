"""Road flyovers: plan from OSM, vertical profile and piers from generic design rules (never fitted to photos)."""
import math
import numpy as np

import shapely
from shapely.geometry import LineString, Polygon, box
from shapely.ops import linemerge, substring, unary_union

from .osm import area_features, polygons_of, tangent, way_coords


# road flyovers (bridge=yes + layer>=1 roads). The vertical profile is derived only from the OSM
# plan (touchdown ends, roads crossing underneath) + these generic design rules, never fitted to photos.
FLY_MIN_LEN = 60.0        # m: shorter road bridges (over canals, culverts) are left to the street
FLY_CLEAR = 4.75          # m: vertical clearance over the carriageways underneath
FLY_CLEAR_PAD = 1.0       # m: clearance kept past each crossing carriageway edge
FLY_GRADE = 0.04          # design grade of the approaches...
FLY_MAX_GRADE = 0.06      # ...steeper only when the approach is too short (then flagged above this)
FLY_VCURVE = 20.0         # m: parabolic vertical curve at each grade change
FLY_SLAB = 0.25           # m: deck slab; girder depth = longest span / FLY_DEPTH_RATIO (steel box girder)
FLY_DEPTH_RATIO = 22.0
FLY_DEPTH_MIN, FLY_DEPTH_MAX = 1.2, 2.4
FLY_RAMP_SOFFIT = 0.0     # m: where the girder bottom is lower than this, the approach is solid (walls); 0 = only
                          # where the girder would reach the ground, the girder on piers runs down to there (ramp photo)
FLY_SPAN, FLY_SPAN_MAX = 30.0, 45.0   # m: target / flagged pier spacing
FLY_PIER_MIN = 0.8        # m: lowest column (girder bottom above the ground); lower down the girder rests on the end walls
FLY_PIER_R = 0.85         # m: round column radius
FLY_PIER_KERB = 0.5       # m: free ground kept between the column and the carriageway edge
FLY_STEP = 2.0            # m: sampling step of the exported line
FLY_PARAPET = 0.5         # m: parapet + edge strip each side, for the fallback width (lanes x 3.25 + 2 x this)


def _smooth(vals, k):
    """Moving average over 2k+1 samples (shorter at the ends)."""
    return [sum(vals[max(0, i - k):i + k + 1]) / len(vals[max(0, i - k):i + k + 1]) for i in range(len(vals))]


def _fly_profile(L, s_lo, s_hi, top):
    """Deck-top height z(s): 0 at both touchdown ends, `top` over [s_lo, s_hi], straight approaches
    at FLY_GRADE (steeper if too short), parabolic vertical curves (FLY_VCURVE) at every grade change,
    placed so the full height is reached at s_lo / s_hi. Returns (z(s), grades (in, out))."""
    vc = FLY_VCURVE
    g_in = max(FLY_GRADE, top / max(s_lo - vc, 1.0))
    g_out = max(FLY_GRADE, top / max(L - s_hi - vc, 1.0))
    a0 = max(0.0, s_lo - vc - top / g_in)          # foot of the up ramp (start of its sag curve)
    b1 = min(L, s_hi + vc + top / g_out)           # end of the down ramp's sag curve

    def z(s):
        if s <= a0 or s >= b1:
            return 0.0
        if s < s_hi:                               # rising side (or plateau)
            if s < a0 + vc:                        # sag curve: grade 0 -> g_in over vc
                return g_in * (s - a0) ** 2 / (2 * vc)
            if s < s_lo - vc:
                return g_in * (s - a0 - vc / 2)
            if s < s_lo:                           # crest curve: g_in -> 0
                return top - g_in * (s_lo - s) ** 2 / (2 * vc)
            return top
        d = b1 - s                                 # mirror for the falling side
        if d < vc:
            return g_out * d ** 2 / (2 * vc)
        if s > s_hi + vc:
            return g_out * (d - vc / 2)
        return top - g_out * (s - s_hi) ** 2 / (2 * vc)
    return z, (g_in, g_out)


def build_flyovers(ways, nodes, roads, area, flags):
    """Road flyovers -> list of dicts for city.json "flyovers" + report.
    Plan: OSM centreline, width from a man_made=bridge outline when there is one.
    Height: computed (see FLY_*): clearance over every ground road crossing underneath, approaches at a
    design grade down to the two ends where the OSM way meets the ground roads, girder depth from the
    longest span between the piers placed here; low approach parts become solid ramps."""
    elevated = [r for r in roads if r['layer'] >= 1 and r['bridge']]
    ground = [r for r in roads if r['layer'] <= 0 and not r['bridge']]
    if not elevated:
        return []
    outlines = [p for _, p, t in area_features(ways, [], nodes, lambda t: t.get('man_made') == 'bridge')]
    # ground carriageways as in build_roads (round ends fill the core of a junction); not closed, so the
    # traffic islands / medians between one-way carriageways stay free for piers
    carriage = unary_union([r['line'].buffer(r['width'] / 2, cap_style='flat') for r in ground]
                           + [r['line'].buffer(r['width'] / 2) for r in ground if r['cls'] != 'service']
                           ) if ground else Polygon()
    shapely.prepare(carriage)
    merged = unary_union([LineString(way_coords(r['refs'], nodes)) for r in elevated])
    if merged.geom_type != 'LineString':           # a single way (or two ways that union into one line) is already merged
        merged = linemerge(merged)
    out = []
    for k, line in enumerate(getattr(merged, 'geoms', [merged])):
        L = line.length
        if L < FLY_MIN_LEN:
            continue
        rs = [r for r in elevated if r['line'].distance(line) < 1.0]
        name = next((r['name'] for r in rs if r['name']), '')
        lanes = max((r['lanes'] or 0 for r in rs), default=0) or 2
        # roads crossing underneath (not the ones joining at the touchdown ends)
        lo, hi, crossings = None, None, []
        for r in ground:
            x = r['line'].intersection(line)
            for p in getattr(x, 'geoms', [x]) if not x.is_empty else []:
                if p.geom_type != 'Point':
                    continue
                s = line.project(p)
                if s < 5.0 or s > L - 5.0:
                    continue
                tx, ty = tangent(line, s)
                rx, ry = tangent(r['line'], r['line'].project(p))
                sin = max(abs(tx * ry - ty * rx), 0.3)
                half = (r['width'] / 2 + FLY_CLEAR_PAD) / sin
                crossings.append((s, r['id'], r['name'], half))
                lo = s - half if lo is None else min(lo, s - half)
                hi = s + half if hi is None else max(hi, s + half)
        if lo is None:
            print(f"[flyover] {name or k}: {L:.0f} m but no road underneath, left as a street")
            continue
        lo, hi = max(lo, 0.0), min(hi, L)

        # width + centre offset from the outline, sampled every FLY_STEP
        ss = np.linspace(0.0, L, max(2, int(math.ceil(L / FLY_STEP)) + 1)).tolist()
        # only outlines drawn for this bridge (a small canal bridge under one end also touches the line)
        outline = unary_union([o for o in outlines if o.intersection(line).length > 0.5 * L] or [Polygon()])
        w_min = lanes * 3.0 + 2 * 0.3
        w_def = lanes * 3.25 + 2 * FLY_PARAPET
        widths, offs = [], []
        for s in ss:
            p = line.interpolate(s)
            tx, ty = tangent(line, s)
            nx, ny = -ty, tx
            cut = LineString([(p.x - nx * 15, p.y - ny * 15), (p.x + nx * 15, p.y + ny * 15)]).intersection(outline) \
                if not outline.is_empty else Polygon()
            if cut.is_empty or cut.length < w_min:
                widths.append(w_def if cut.is_empty else w_min); offs.append(0.0)
                continue
            # the piece under the centreline (on a bend the cut can also reach the other arm of the outline)
            seg = min((g for g in getattr(cut, 'geoms', [cut]) if g.geom_type == 'LineString'), key=lambda g: g.distance(p))
            if seg.distance(p) > 2.0 or seg.length < w_min:
                widths.append(w_min); offs.append(0.0)
                continue
            m = seg.interpolate(0.5, normalized=True)
            widths.append(min(seg.length, 2 * w_def))
            offs.append(max(-2.0, min(2.0, (m.x - p.x) * nx + (m.y - p.y) * ny)))
        k5 = int(5.0 / FLY_STEP)
        widths, offs = _smooth(widths, k5), _smooth(offs, k5)
        pts = []
        for s, o in zip(ss, offs):
            p = line.interpolate(s)
            tx, ty = tangent(line, s)
            pts.append((p.x - ty * o, p.y + tx * o))
        centre = LineString(pts)
        ss = [0.0] + np.cumsum([math.dist(a, b) for a, b in zip(pts, pts[1:])]).tolist()   # arc length on the new centre

        def pier_free(s):
            p = centre.interpolate(min(max(s, 0.0), centre.length))
            return not carriage.intersects(p.buffer(FLY_PIER_R + FLY_PIER_KERB))

        # profile <-> piers: the girder depth follows the longest span, the spans follow the deck part
        depth = (FLY_DEPTH_MIN + FLY_DEPTH_MAX) / 2
        for _ in range(3):
            top = FLY_CLEAR + depth
            z, grades = _fly_profile(centre.length, lo, hi, top)
            zs = [z(s) for s in ss]
            deck = [s for s, h in zip(ss, zs) if h - depth >= FLY_RAMP_SOFFIT]
            d0, d1 = deck[0], deck[-1]
            # piers: every 0.5 m spot that is off the carriageways and tall enough is a candidate; dynamic
            # programming picks the fewest piers with spans <= FLY_SPAN where the free spots allow, else the
            # least excess, and evens out the spans (small quadratic term)
            cands = [d0] + [float(s) for s in np.arange(d0 + 5.0, d1 - 5.0 + 1e-6, 0.5)
                            if z(s) - depth >= FLY_PIER_MIN and pier_free(s)] + [d1]
            cost = [0.0] + [math.inf] * (len(cands) - 1)
            prev = [0] * len(cands)
            for j in range(1, len(cands)):
                for i in range(j - 1, -1, -1):
                    sp = cands[j] - cands[i]
                    if sp > 3 * FLY_SPAN_MAX:
                        break
                    c = cost[i] + 1.0 + 0.001 * sp * sp + (1e3 * (sp - FLY_SPAN) ** 2 if sp > FLY_SPAN else 0.0)
                    if c < cost[j]:
                        cost[j], prev[j] = c, i
            supports, j = [d1], len(cands) - 1                # the deck ends rest on the ramp / abutment walls
            while j > 0:
                j = prev[j]
                supports.insert(0, cands[j])
            piers = supports[1:-1]
            stuck = sum(1 for a, b in zip(supports, supports[1:]) if b - a > FLY_SPAN + 1e-6)
            span = max(b - a for a, b in zip(supports, supports[1:]))
            new_depth = min(FLY_DEPTH_MAX, max(FLY_DEPTH_MIN, span / FLY_DEPTH_RATIO))
            if abs(new_depth - depth) < 0.05:
                break
            depth = round(new_depth, 2)

        segments = [dict(s0=0.0, s1=round(d0, 2), kind='ramp'), dict(s0=round(d0, 2), s1=round(d1, 2), kind='deck'),
                    dict(s0=round(d1, 2), s1=round(centre.length, 2), kind='ramp')]
        pier_out = []
        for s in piers:
            p = centre.interpolate(s)
            tx, ty = tangent(centre, s)
            pier_out.append(dict(s=round(s, 2), x=round(p.x, 2), y=round(p.y, 2),
                                 yaw=round(math.degrees(math.atan2(tx, ty)), 2), top=round(z(s) - depth, 3)))
        g_max = max(grades)
        if g_max > FLY_MAX_GRADE + 1e-6:
            flags.append(dict(kind='flyover_grade', id=name or k, xy=tuple(line.interpolate(lo if grades[0] > grades[1] else hi).coords[0]),
                              msg=f"approach grade {g_max * 100:.1f}% > {FLY_MAX_GRADE * 100:.0f}%"))
        if span > FLY_SPAN_MAX:
            flags.append(dict(kind='flyover_span', id=name or k, xy=tuple(centre.interpolate((d0 + d1) / 2).coords[0]),
                              msg=f"longest span {span:.0f} m > {FLY_SPAN_MAX:.0f} m ({stuck} spans over {FLY_SPAN:.0f} m: no free spot for a pier)"))
        fly = dict(id=k, name=name, lanes=lanes, length=round(centre.length, 2),
                   clear=FLY_CLEAR, slab=FLY_SLAB, depth=depth, top=round(top, 3),
                   grade_in=round(grades[0], 4), grade_out=round(grades[1], 4), clear_from=round(lo, 2), clear_to=round(hi, 2),
                   line=[round(v, 3) for (x, y), h in zip(pts, zs) for v in (x, y, h)],
                   width=[round(w, 2) for w in widths], segments=segments, piers=pier_out,
                   crossings=[dict(s=round(s, 1), road=rid, name=rn) for s, rid, rn, _ in sorted(crossings)])
        fly['_centre'], fly['_outline'], fly['_zs'], fly['_ss'], fly['_span'] = centre, outline, zs, ss, span
        # ground under the solid ramps: road, not sidewalk (near the touchdown the ramp is lower than a sidewalk top)
        fly['_ramp_foot'] = unary_union([
            substring(centre, sg['s0'], sg['s1']).buffer(
                np.mean([w for s, w in zip(ss, widths) if sg['s0'] <= s <= sg['s1']] or [w_def]) / 2, cap_style='flat')
            for sg in segments if sg['kind'] == 'ramp' and sg['s1'] - sg['s0'] > 0.5])
        fly['_carriage'] = carriage
        out.append(fly)
        print(f"[flyover] {name or k}: {centre.length:.0f} m, clearance over s {lo:.0f}-{hi:.0f} "
              f"({len(crossings)} crossings), top {top:.2f} m, grades {grades[0] * 100:.1f}% / {grades[1] * 100:.1f}%, "
              f"girder {depth:.2f} m, ramps 0-{d0:.0f} / {d1:.0f}-{centre.length:.0f} m, {len(piers)} piers "
              f"(longest span {span:.0f} m, {stuck} spans over {FLY_SPAN:.0f} m), width {min(widths):.1f}-{max(widths):.1f} m")
    return out


def report_flyover(path, fly, surface, sidewalk):
    """Plan (outline, deck edges, piers over the street) + long section (deck, girder bottom, clearance)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    centre, zs, ss = fly['_centre'], fly['_zs'], fly['_ss']
    x0, y0, x1, y1 = centre.buffer(40).bounds
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(16, 16 * (y1 - y0) / (x1 - x0) + 5),
                                 gridspec_kw=dict(height_ratios=[(y1 - y0) / (x1 - x0) * 3, 1]), dpi=110)
    for g, col in ((sidewalk, '#d9d4cc'), (surface, '#b8b8b8'), (fly['_carriage'], '#6a6a6a')):
        for p in polygons_of(g.intersection(box(x0, y0, x1, y1))):
            ax.fill(*p.exterior.xy, color=col, lw=0)
            for h in p.interiors:
                ax.fill(*h.xy, color='#f4f1ea', lw=0)
    for p in polygons_of(fly['_outline']):
        ax.plot(*p.exterior.xy, color='red', lw=1.2, ls='--', label='OSM man_made=bridge')
    left, right = [], []
    for i, s in enumerate(ss):
        p = centre.interpolate(s)
        tx, ty = tangent(centre, s)
        h = fly['width'][i] / 2
        left.append((p.x - ty * h, p.y + tx * h)); right.append((p.x + ty * h, p.y - tx * h))
    for seg in fly['segments']:
        idx = [i for i, s in enumerate(ss) if seg['s0'] - 1e-6 <= s <= seg['s1'] + 1e-6]
        ring = [left[i] for i in idx] + [right[i] for i in reversed(idx)]
        ax.fill(*zip(*ring), color='#e0a030' if seg['kind'] == 'ramp' else '#3a6fd8', alpha=0.45, lw=0)
    ax.plot(*centre.xy, color='black', lw=0.8)
    for pr in fly['piers']:
        ax.add_patch(plt.Circle((pr['x'], pr['y']), FLY_PIER_R, color='black'))
        ax.add_patch(plt.Circle((pr['x'], pr['y']), FLY_PIER_R + FLY_PIER_KERB, fill=False, color='black', lw=0.6))
    for cr in fly['crossings']:
        p = centre.interpolate(cr['s'])
        ax.plot(p.x, p.y, 'x', color='magenta', ms=8)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect('equal')
    ax.set_title(f"{fly['name']}: xam dam = long duong mat dat (tru phai tranh), cam = doc dac (tuong), "
                 f"xanh = dam tren tru, den = tru, x = duong cat duoi cau, do = outline OSM", fontsize=10)
    ax.legend(loc='upper left', fontsize=9)
    bx.fill_between(ss, [h - fly['depth'] for h in zs], zs, color='#3a6fd8', alpha=0.5, label='dam (mat cau -> day dam)')
    bx.plot(ss, zs, color='black', lw=1, label='mat cau')
    bx.axhspan(0, fly['clear'], xmin=fly['clear_from'] / ss[-1], xmax=fly['clear_to'] / ss[-1], color='magenta', alpha=0.15,
               label=f"tinh khong {fly['clear']} m")
    for pr in fly['piers']:
        bx.plot([pr['s'], pr['s']], [0, pr['top']], color='black', lw=3)
    for seg in fly['segments']:
        if seg['kind'] == 'ramp':
            bx.axvspan(seg['s0'], seg['s1'], color='#e0a030', alpha=0.15)
    bx.set_xlim(0, ss[-1]); bx.set_ylim(0, fly['top'] + 1.5)
    bx.set_xlabel('s (m) doc tim cau'); bx.set_ylabel('z (m)')
    bx.set_title(f"doc vao {fly['grade_in'] * 100:.1f}% / ra {fly['grade_out'] * 100:.1f}%, dam {fly['depth']} m, "
                 f"nhip lon nhat {fly['_span']:.0f} m (truc dung phong dai)", fontsize=11)
    bx.legend(loc='upper right', fontsize=9)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
