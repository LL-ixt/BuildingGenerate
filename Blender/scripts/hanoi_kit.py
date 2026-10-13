"""Modular Hanoi tube-house kit: module geometry at LOD0 / LOD1.

Conventions (Blender, metres):
  - Module width 4 m (x = -2..2), facade plane y = 0 facing -Y, house depth +Y (12 m).
  - Ground floor 3.6 m, upper floors 3.3 m. Module origin = facade centre at floor level.
  - Every face carries UVs inside a trim-sheet region (hanoi_trim.REGIONS) and a preview
    colour; material slot 0 = M_HanoiKit, slot 1 = M_HanoiGlass.
"""
import math
from mathutils import Matrix, Vector
import hanoi_trim as trim

W = 4.0
HW = W / 2
FH = 3.3          # upper floor height
GH = 3.6          # ground floor height
DEPTH = 12.0
MAT_KIT, MAT_GLASS = 0, 1


# ---------------------------------------------------------------- mesh builder
def _newell(pts):
    n = Vector((0, 0, 0))
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        n.x += (p.y - q.y) * (p.z + q.z)
        n.y += (p.z - q.z) * (p.x + q.x)
        n.z += (p.x - q.x) * (p.y + q.y)
    return n


class MB:
    """Accumulates polygons with per-corner UVs, preview colour and material index."""

    def __init__(self):
        self.polys = []   # (pts[Vector], uvs[(u,v)], region, mat)

    # -- uv helpers -------------------------------------------------------
    @staticmethod
    def _to_uv(region, st):
        u0, v0, u1, v1 = trim.uv_rect(region)
        return [(u0 + s * (u1 - u0), v0 + t * (v1 - v0)) for s, t in st]

    @staticmethod
    def _st_world(pts, phys):
        ua = (pts[1] - pts[0]).normalized()
        vr = pts[-1] - pts[0]
        va = (vr - ua * vr.dot(ua)).normalized()
        s = [(p - pts[0]).dot(ua) / phys[0] for p in pts]
        t = [(p - pts[0]).dot(va) / phys[1] for p in pts]
        s0, t0 = min(s), min(t)
        s = [x - s0 for x in s]; t = [y - t0 for y in t]
        ms, mt = max(max(s), 1e-6), max(max(t), 1e-6)
        if ms > 1: s = [x / ms for x in s]
        if mt > 1: t = [y / mt for y in t]
        return list(zip(s, t))

    # -- primitives -------------------------------------------------------
    def quad(self, pts, region, n=None, uv='fit', phys=(4.0, 4.0), mat=MAT_KIT, double=False):
        """pts ordered bottom-left, bottom-right, top-right, top-left as seen from outside.
        If n is given and the winding disagrees, the quad is mirrored to face n."""
        pts = [Vector(p) for p in pts]
        if n is not None and _newell(pts).dot(Vector(n)) < 0:
            pts = [pts[1], pts[0], pts[3], pts[2]]
        st = [(0, 0), (1, 0), (1, 1), (0, 1)] if uv == 'fit' else self._st_world(pts, phys)
        self.polys.append((pts, self._to_uv(region, st), region, mat))
        if double:
            back = [pts[1], pts[0], pts[3], pts[2]]
            st = [(0, 0), (1, 0), (1, 1), (0, 1)] if uv == 'fit' else self._st_world(back, phys)
            self.polys.append((back, self._to_uv(region, st), region, mat))

    def poly(self, pts, region, n=None, phys=(4.0, 4.0), mat=MAT_KIT):
        """Arbitrary planar polygon, world-planar UVs."""
        pts = [Vector(p) for p in pts]
        if n is not None and _newell(pts).dot(Vector(n)) < 0:
            pts = pts[::-1]
        nn = _newell(pts).normalized()
        ua = (pts[1] - pts[0]).normalized()
        va = nn.cross(ua)
        s = [(p - pts[0]).dot(ua) for p in pts]
        t = [(p - pts[0]).dot(va) for p in pts]
        s0, t0 = min(s), min(t)
        st = [(min((x - s0) / phys[0], 1), min((y - t0) / phys[1], 1)) for x, y in zip(s, t)]
        self.polys.append((pts, self._to_uv(region, st), region, mat))

    def box(self, x0, x1, y0, y1, z0, z1, region, skip=(), uv='fit', phys=(4.0, 4.0),
            regions=None, mat=MAT_KIT):
        faces = {
            '-Y': ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], (0, -1, 0)),
            '+Y': ([(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)], (0, 1, 0)),
            '-X': ([(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)], (-1, 0, 0)),
            '+X': ([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], (1, 0, 0)),
            '+Z': ([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], (0, 0, 1)),
            '-Z': ([(x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0)], (0, 0, -1)),
        }
        for side, (pts, n) in faces.items():
            if side in skip:
                continue
            reg = (regions or {}).get(side, region)
            self.quad(pts, reg, n=n, uv=uv, phys=phys, mat=mat)

    def cylinder_x(self, x0, x1, cy, cz, r, seg, region, caps=True):
        """Horizontal cylinder along X (for the water tank)."""
        ring = [(cy + r * math.cos(2 * math.pi * i / seg), cz + r * math.sin(2 * math.pi * i / seg))
                for i in range(seg)]
        u0, v0, u1, v1 = trim.uv_rect(region)
        for i in range(seg):
            (ya, za), (yb, zb) = ring[i], ring[(i + 1) % seg]
            pts = [Vector((x0, ya, za)), Vector((x0, yb, zb)), Vector((x1, yb, zb)), Vector((x1, ya, za))]
            mid = Vector((0, (ya + yb) / 2 - cy, (za + zb) / 2 - cz))
            if _newell(pts).dot(mid) < 0:
                pts = [pts[1], pts[0], pts[3], pts[2]]
            sa, sb = i / seg, (i + 1) / seg
            uvs = [(u0 + sa * (u1 - u0), v0), (u0 + sb * (u1 - u0), v0),
                   (u0 + sb * (u1 - u0), v1), (u0 + sa * (u1 - u0), v1)]
            self.polys.append((pts, uvs, region, MAT_KIT))
        if caps:
            for x, nx in ((x0, -1), (x1, 1)):
                self.poly([(x, y, z) for y, z in ring], region, n=(nx, 0, 0), phys=(2 * r, 2 * r))

    def grid_quad(self, pts, style, fuv, color=None, mat=MAT_KIT):
        """Facade-grid quad for towers: UV0 selects the style region, FacadeUV carries
        (bay + s, floor + t) per corner; optional per-poly sRGB colour overrides the preview."""
        pts = [Vector(p) for p in pts]
        st = [(0, 0), (1, 0), (1, 1), (0, 1)][:len(pts)]
        self.polys.append((pts, self._to_uv(style, st), style, mat, {'fuv': list(fuv), 'col': color}))

    def set_color(self, color, start=0):
        """Override the preview colour of every poly added since index `start`."""
        for i in range(start, len(self.polys)):
            p = self.polys[i]
            extra = dict(p[4]) if len(p) > 4 else {}
            extra['col'] = color
            self.polys[i] = (*p[:4], extra)

    # -- combine ----------------------------------------------------------
    def extend(self, other, matrix):
        for p in other.polys:
            self.polys.append(([matrix @ v for v in p[0]], list(p[1]), *p[2:]))
        return self

    def tri_count(self):
        return sum(len(p[0]) - 2 for p in self.polys)

    def to_mesh(self, name, materials=()):
        """Build the Blender mesh. Polys are (pts, uvs, region, mat[, extra]); extra may hold
        'fuv' (FacadeUV corners) and 'col' (sRGB colour override). N-gons (concave tower caps)
        are triangulated so the FBX importer never has to guess."""
        import bpy, bmesh
        verts, faces = [], []
        for p in self.polys:
            faces.append(list(range(len(verts), len(verts) + len(p[0]))))
            verts.extend(p[0])
        me = bpy.data.meshes.get(name)
        if me is not None:
            me.clear_geometry()
        else:
            me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(v) for v in verts], [], faces)
        # slots must exist before material_index is written (clearing slots resets indices)
        me.materials.clear()
        for m in materials:
            me.materials.append(m)
        uvl = me.uv_layers.new(name='UVMap')
        has_fuv = any(len(p) > 4 and p[4].get('fuv') for p in self.polys)
        fuvl = me.uv_layers.new(name='FacadeUV') if has_fuv else None
        col = me.color_attributes.new('Col', 'BYTE_COLOR', 'CORNER')
        li = 0
        for pi, p in enumerate(self.polys):
            pts, uvs, reg, mat = p[:4]
            extra = p[4] if len(p) > 4 else {}
            me.polygons[pi].material_index = mat
            c = extra.get('col') or (1.0, 1.0, 1.0) if (reg in trim.TEXTURED and not extra.get('col')) else (extra.get('col') or trim.PREVIEW_COLORS.get(reg, (1, 0, 1)))
            a = 1.0 if reg in trim.PAINTABLE else 0.0      # alpha = paint mask (per-house tint)
            fuv = extra.get('fuv')
            for k in range(len(pts)):
                uvl.data[li].uv = uvs[k]
                if fuvl is not None:
                    fuvl.data[li].uv = fuv[k] if fuv else (0.0, 0.0)
                col.data[li].color_srgb = (c[0], c[1], c[2], a)
                li += 1
        if any(len(p[0]) > 4 for p in self.polys):
            bm = bmesh.new()
            bm.from_mesh(me)
            bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4],
                                  quad_method='BEAUTY', ngon_method='EAR_CLIP')
            bm.to_mesh(me)
            bm.free()
        me.validate()
        me.update()
        return me


# ---------------------------------------------------------------- shared parts
def facade_wall(mb, z0, z1, openings, lod, x0=-HW, x1=HW):
    """Wall at y=0 facing -Y from x0 to x1 (default: the 4 m front), with recessed openings.
    opening: dict(x0,x1,z0,z1,d, fill=callable(mb,o,lod) | (region, mat), reveal=region | dict)
    Plaster UVs tile every 4 m (cut lines are added at the tile seams)."""
    tiles = [x0 + 4.0 * k for k in range(1, int((x1 - x0 - 1e-6) // 4.0) + 1)]
    if lod >= 1:
        xs = [x0, *tiles, x1]
        zs = [z0, z1]
    else:
        xs = sorted({x0, x1, *tiles, *[o['x0'] for o in openings], *[o['x1'] for o in openings]})
        zs = sorted({z0, z1, *[o['z0'] for o in openings], *[o['z1'] for o in openings]})
    for xa, xb in zip(xs, xs[1:]):
        base = x0 + 4.0 * math.floor(((xa + xb) / 2 - x0) / 4.0)
        for za, zb in zip(zs, zs[1:]):
            cx, cz = (xa + xb) / 2, (za + zb) / 2
            if lod == 0 and any(o['x0'] < cx < o['x1'] and o['z0'] < cz < o['z1'] for o in openings):
                continue
            pts = [(xa, 0, za), (xb, 0, za), (xb, 0, zb), (xa, 0, zb)]
            st = [((p[0] - base) / 4.0, (p[2] - z0) / 4.0) for p in pts]
            mb.polys.append(([Vector(p) for p in pts], MB._to_uv('PLASTER', st), 'PLASTER', MAT_KIT))
    for o in openings:
        ox0, ox1, oz0, oz1 = o['x0'], o['x1'], o['z0'], o['z1']
        d = o['d'] if lod == 0 else 0.0
        if d > 0:
            rv = o.get('reveal', 'PLASTER')
            rv = rv if isinstance(rv, dict) else {'side': rv, 'top': rv, 'bottom': rv}
            mb.quad([(ox0, d, oz0), (ox0, 0, oz0), (ox0, 0, oz1), (ox0, d, oz1)], rv['side'], n=(1, 0, 0), uv='world')
            mb.quad([(ox1, 0, oz0), (ox1, d, oz0), (ox1, d, oz1), (ox1, 0, oz1)], rv['side'], n=(-1, 0, 0), uv='world')
            mb.quad([(ox0, 0, oz1), (ox1, 0, oz1), (ox1, d, oz1), (ox0, d, oz1)], rv['top'], n=(0, 0, -1), uv='world')
            mb.quad([(ox0, d, oz0), (ox1, d, oz0), (ox1, 0, oz0), (ox0, 0, oz0)], rv['bottom'], n=(0, 0, 1), uv='world')
        fy = d if d > 0 else -0.01
        fill = o['fill']
        if callable(fill):
            fill(mb, o, lod, fy)
        else:
            reg, mat = fill
            mb.quad([(ox0, fy, oz0), (ox1, fy, oz0), (ox1, fy, oz1), (ox0, fy, oz1)], reg, n=(0, -1, 0), mat=mat)


def pilasters(mb, H, lod):
    if lod == 0:
        for xa, xb in ((-HW, -HW + 0.2), (HW - 0.2, HW)):
            mb.box(xa, xb, -0.08, 0, 0, H, 'PLASTER', skip={'+Y', '-Z', '+Z'}, uv='world')


def cornice(mb, z0, z1, depth, lod):
    skip = {'+Y'} if lod == 0 else {'+Y', '-X', '+X', '+Z'}
    mb.box(-HW, HW, -depth, 0, z0, z1, 'CORNICE', skip=skip)


def step(mb, lod):
    skip = {'+Y', '-Z'} if lod == 0 else {'+Y', '-Z', '-X', '+X'}
    mb.box(-HW, HW, -0.35, 0, 0, 0.15, 'CONCRETE', skip=skip, uv='world', phys=(4, 1))


def signboard(mb, region, z0, z1, lod):
    skip = {'+Y'} if lod == 0 else {'+Y', '-X', '+X'}
    mb.box(-1.9, 1.9, -0.3, -0.05, z0, z1, 'DARK', skip=skip, regions={'-Y': region})


def window_frame(mb, o, lod, fy, glass=True):
    """Glazed window: glass pane + green frame and cross mullion (LOD0), flat trim quad (LOD1)."""
    ox0, ox1, oz0, oz1 = o['x0'], o['x1'], o['z0'], o['z1']
    if lod >= 1 or 'GLASSWIN' in trim.TEXTURED:
        # the window image already has frame + dark glass: one flat quad at every LOD (no interior)
        mb.quad([(ox0, fy, oz0), (ox1, fy, oz0), (ox1, fy, oz1), (ox0, fy, oz1)], 'GLASSWIN', n=(0, -1, 0))
        return
    mb.quad([(ox0, fy, oz0), (ox1, fy, oz0), (ox1, fy, oz1), (ox0, fy, oz1)], 'GLASSWIN',
            n=(0, -1, 0), mat=MAT_GLASS if glass else MAT_KIT)
    f, y0, y1 = 0.05, fy - 0.05, fy
    sk = {'+Y'}
    mb.box(ox0, ox1, y0, y1, oz0, oz0 + f, 'GREEN', skip=sk)
    mb.box(ox0, ox1, y0, y1, oz1 - f, oz1, 'GREEN', skip=sk)
    mb.box(ox0, ox0 + f, y0, y1, oz0 + f, oz1 - f, 'GREEN', skip=sk)
    mb.box(ox1 - f, ox1, y0, y1, oz0 + f, oz1 - f, 'GREEN', skip=sk)
    cx = (ox0 + ox1) / 2
    mb.box(cx - 0.025, cx + 0.025, y0, y1, oz0 + f, oz1 - f, 'GREEN', skip=sk)
    tz = oz0 + (oz1 - oz0) * 0.7
    mb.box(ox0 + f, ox1 - f, y0, y1, tz - 0.025, tz + 0.025, 'GREEN', skip=sk)


def _rail_pieces(run, height, sl):
    """[(width_m, u0, u1)] along a railing run: left cap, repeated middle, right cap.
    sl = {w, h, l, r}: image size in px and the cut positions (fractions of the width, at bar centres).
    None when the run is too short for slicing (the whole image is squeezed into it instead)."""
    s = height / sl['h']                                      # metres per image pixel
    cap_l, cap_r = sl['l'] * sl['w'] * s, (1 - sl['r']) * sl['w'] * s
    native = (sl['r'] - sl['l']) * sl['w'] * s
    mid = run - cap_l - cap_r
    if mid < 0.5 * native:
        return None
    n = max(1, round(mid / native))
    return [(cap_l, 0.0, sl['l'])] + [(mid / n, sl['l'], sl['r'])] * n + [(cap_r, sl['r'], 1.0)]


def rail_panels(mb, x0, x1, y, z0, z1, n_panels, lod, axis='x', region='RAIL_BAL'):
    """Iron railing (alpha-clip RAIL region), double-sided quads split into n panels.
    With a railing image the picture is sliced instead: the two thick frame posts appear only at the
    ends of the run and the middle part is repeated (cut at bar centres, so repeats join seamlessly)."""
    sl = trim.RAIL_SLICES.get(region)
    if sl and region in trim.TEXTURED:
        pieces = _rail_pieces(abs(x1 - x0), z1 - z0, sl)
        if pieces:
            cum = 0.0
            for w, u0, u1 in pieces:
                if axis == 'x':
                    pa, pb = x0 + cum, x0 + cum + w
                    pts = [(pa, y, z0), (pb, y, z0), (pb, y, z1), (pa, y, z1)]
                else:       # image-left is the far (larger y) end, see the whole-image branch below
                    pa, pb = x1 - cum, x1 - cum - w
                    pts = [(y, pa, z0), (y, pb, z0), (y, pb, z1), (y, pa, z1)]
                cum += w
                uvs = MB._to_uv(region, [(u0, 0), (u1, 0), (u1, 1), (u0, 1)])
                pts = [Vector(p) for p in pts]
                mb.polys.append((pts, uvs, region, MAT_KIT))
                mb.polys.append(([pts[1], pts[0], pts[3], pts[2]], [uvs[1], uvs[0], uvs[3], uvs[2]], region, MAT_KIT))
            return
    for i in range(n_panels):
        a = x0 + (x1 - x0) * i / n_panels
        b = x0 + (x1 - x0) * (i + 1) / n_panels
        if axis == 'x':
            pts = [(a, y, z0), (b, y, z0), (b, y, z1), (a, y, z1)]; n = (0, -1, 0)
        else:   # panel runs along Y at x = y-argument
            pts = [(y, b, z0), (y, a, z0), (y, a, z1), (y, b, z1)]; n = (1 if y > 0 else -1, 0, 0)
        mb.quad(pts, region, n=n, double=True)


def awning(mb, x0, x1, y_out, z_wall, z_out, lod):
    mb.quad([(x0, y_out, z_out), (x1, y_out, z_out), (x1, 0, z_wall), (x0, 0, z_wall)],
            'CORRUGATED', n=(0, -0.3, 1), double=True)


def _clip(pts, f, lo, hi):
    """Clip a convex polygon to lo <= f(p) <= hi (Sutherland-Hodgman, two half-planes)."""
    for sign, lim in ((1, lo), (-1, hi)):
        out = []
        for i, p in enumerate(pts):
            q = pts[(i + 1) % len(pts)]
            dp, dq = sign * (f(p) - lim), sign * (f(q) - lim)
            if dp >= 0:
                out.append(p)
            if (dp >= 0) != (dq >= 0):
                out.append(p.lerp(q, dp / (dp - dq)))
        pts = out
        if len(pts) < 3:
            return []
    return pts


def tiled_poly(mb, pts, region, n, tile=4.0, col=None, double=False, mat=MAT_KIT):
    """Convex planar polygon cut into tile x tile metre pieces so a repeating texture never
    stretches. UV s runs horizontally along the face, t up the slope (corrugations / tile
    courses go along t). col: optional sRGB override of the preview colour (roof colours)."""
    pts = [Vector(p) for p in pts]
    nn = Vector(n).normalized()
    if _newell(pts).dot(nn) < 0:
        pts = pts[::-1]
    ua = Vector((0, 0, 1)).cross(nn)
    ua = ua.normalized() if ua.length > 1e-6 else Vector((1, 0, 0))
    va = nn.cross(ua)
    fs, ft = (lambda p: p.dot(ua)), (lambda p: p.dot(va))
    s0, s1 = min(map(fs, pts)), max(map(fs, pts))
    t0, t1 = min(map(ft, pts)), max(map(ft, pts))
    extra = {'col': col} if col else {}
    for i in range(max(1, math.ceil((s1 - s0) / tile - 1e-6))):
        a = _clip(pts, fs, s0 + i * tile, s0 + (i + 1) * tile)
        for j in range(max(1, math.ceil((t1 - t0) / tile - 1e-6))):
            piece = _clip(a, ft, t0 + j * tile, t0 + (j + 1) * tile) if a else []
            if not piece:
                continue
            st = [((fs(p) - s0) / tile - i, (ft(p) - t0) / tile - j) for p in piece]
            uvs = MB._to_uv(region, st)
            mb.polys.append((piece, uvs, region, mat, extra))
            if double:
                mb.polys.append((piece[::-1], uvs[::-1], region, mat, extra))


# ---------------------------------------------------------------- shell (sides + back)
# Side walls are separate modules so the generator can open windows only where a wall is
# exposed (corner lots, taller than the neighbour). Every shell piece takes the lot depth.
SIDE_WIN = {'GF': (1.2, 2.4), 'UF': (1.0, 2.2)}    # window z range per floor type
SIDE_WIN_W = 0.8


SIDE_EDGE, SIDE_PITCH = 1.5, 2.5      # first window centre from the wall end, centre spacing
SIDE_ALIGNS = {'': 'centre', 'F': 'towards the street', 'B': 'towards the back'}


def side_windows_y(n, depth, align=''):
    """Window centres along the depth (y), measured from the facade.
    align: '' spread around the middle, 'F' packed near the street, 'B' packed near the back."""
    if n == 0:
        return []
    if align == 'F':
        return [SIDE_EDGE + SIDE_PITCH * i for i in range(n)]
    if align == 'B':
        return [depth - SIDE_EDGE - SIDE_PITCH * i for i in range(n)]
    return {1: [depth * 0.5], 2: [depth * 0.28, depth * 0.72]}[n]


def side_wall(H, n, s, kind, align=''):
    """One side wall (s = -1 left / +1 right, seen from the street) with n windows."""
    def build(lod, depth=DEPTH):
        z0, z1 = SIDE_WIN[kind]
        loc = MB()
        # built as a front wall in local space, then turned to face +-X
        cs = [c if s > 0 else -c for c in side_windows_y(n, depth, align)]
        wins = [dict(x0=c - SIDE_WIN_W / 2, x1=c + SIDE_WIN_W / 2, z0=z0, z1=z1, d=0.15, fill=window_frame)
                for c in cs]
        facade_wall(loc, 0, H, wins, lod, *((0.0, depth) if s > 0 else (-depth, 0.0)))
        if lod == 0:
            for o in wins:
                loc.box(o['x0'] - 0.06, o['x1'] + 0.06, -0.08, 0, z0 - 0.07, z0, 'CORNICE', skip={'+Y'})   # sill
        m = Matrix.Translation((s * HW, 0, 0)) @ Matrix.Rotation(math.radians(90 * s), 4, 'Z')
        return MB().extend(loc, m)
    return build


def back_wall(H):
    def build(lod, depth=DEPTH):
        mb = MB()
        mb.quad([(HW, depth, 0), (-HW, depth, 0), (-HW, depth, H), (HW, depth, H)], 'PLASTER', n=(0, 1, 0), uv='world')
        return mb
    return build


def body(H):
    """Plain shell: back wall + two blank side walls (kept for the old recipes)."""
    kind = 'GF' if H == GH else 'UF'

    def build(lod, depth=DEPTH):
        mb = back_wall(H)(lod, depth)
        for s in (-1, 1):
            mb.extend(side_wall(H, 0, s, kind)(lod, depth), Matrix.Identity(4))
        return mb
    return build


# ---------------------------------------------------------------- modules


def gf_shop(lod):
    mb = MB(); H = GH
    facade_wall(mb, 0, H, [dict(x0=-1.75, x1=1.75, z0=0.15, z1=2.8, d=0.9, fill=('SHOP', MAT_KIT),
                                reveal={'side': 'DARK', 'top': 'DARK', 'bottom': 'CONCRETE'})], lod)
    if lod == 0:
        mb.box(-1.8, 1.8, -0.12, 0, 2.8, 2.9, 'METAL', skip={'+Y'})          # pulled-up shutter box
    signboard(mb, 'SIGN_A', 2.92, 3.45, lod)
    pilasters(mb, H, lod)
    step(mb, lod)
    cornice(mb, 3.47, 3.6, 0.12, lod)
    return mb


def gf_roller(lod):
    mb = MB(); H = GH
    facade_wall(mb, 0, H, [dict(x0=-1.7, x1=1.7, z0=0.15, z1=2.75, d=0.12, fill=('ROLLER', MAT_KIT))], lod)
    skip = {'+Y'} if lod == 0 else {'+Y', '-X', '+X'}
    mb.box(-1.8, 1.8, -0.22, 0, 2.75, 2.95, 'METAL', skip=skip)            # roller housing
    signboard(mb, 'SIGN_B', 2.98, 3.45, lod)
    pilasters(mb, H, lod)
    step(mb, lod)
    cornice(mb, 3.47, 3.6, 0.12, lod)
    return mb


def gf_wooddoor(lod):
    """Closed panelled wooden door: one recessed plane (WOODDOOR region carries the look)."""
    mb = MB(); H = GH
    facade_wall(mb, 0, H, [dict(x0=-1.3, x1=1.3, z0=0.15, z1=2.7, d=0.15, fill=('WOODDOOR', MAT_KIT))], lod)
    if lod == 0:
        mb.box(-1.45, 1.45, -0.1, 0, 2.7, 2.85, 'CORNICE', skip={'+Y'})                 # door lintel
    pilasters(mb, H, lod)
    step(mb, lod)
    cornice(mb, 3.47, 3.6, 0.12, lod)
    return mb


def gf_foldgate(lod):
    """Closed steel folding gate (cửa kéo) across the whole shop front: one plane."""
    mb = MB(); H = GH
    facade_wall(mb, 0, H, [dict(x0=-1.75, x1=1.75, z0=0.15, z1=2.8, d=0.1, fill=('FOLDGATE', MAT_KIT))], lod)
    if lod == 0:
        mb.box(-1.75, 1.75, -0.06, 0, 2.8, 2.88, 'METAL', skip={'+Y'})                  # top track
    pilasters(mb, H, lod)
    step(mb, lod)
    cornice(mb, 3.47, 3.6, 0.12, lod)
    return mb


def _open_interior(mb, o, lod, fy):
    """Open front: flat light back wall + folding-gate leaves pushed to both jambs."""
    ox0, ox1, oz0, oz1 = o['x0'], o['x1'], o['z0'], o['z1']
    mb.quad([(ox0, fy, oz0), (ox1, fy, oz0), (ox1, fy, oz1), (ox0, fy, oz1)], 'INTERIOR', n=(0, -1, 0))
    gy = 0.06 if lod == 0 else -0.015
    for xa, xb in ((ox0, ox0 + 0.28), (ox1 - 0.28, ox1)):
        mb.quad([(xa, gy, oz0), (xb, gy, oz0), (xb, gy, oz1), (xa, gy, oz1)], 'FOLDGATE', n=(0, -1, 0))


def gf_open(lod):
    """Open ground floor: deep bright recess reads as a lit room (no interior modelling)."""
    mb = MB(); H = GH
    facade_wall(mb, 0, H, [dict(x0=-1.75, x1=1.75, z0=0.15, z1=2.8, d=2.0, fill=_open_interior,
                                reveal={'side': 'INTERIOR', 'top': 'INTERIOR', 'bottom': 'CONCRETE'})], lod)
    if lod == 0:
        mb.box(-1.75, 1.75, -0.06, 0, 2.8, 2.88, 'METAL', skip={'+Y'})                  # gate track
    pilasters(mb, H, lod)
    step(mb, lod)
    cornice(mb, 3.47, 3.6, 0.12, lod)
    return mb


def uf_window(lod):
    """Upper floor with a single glazed window."""
    mb = MB(); H = FH
    o = dict(x0=-0.8, x1=0.8, z0=0.9, z1=2.4, d=0.18, fill=window_frame)
    facade_wall(mb, 0, H, [o], lod)
    if lod == 0:
        mb.box(o['x0'] - 0.08, o['x1'] + 0.08, -0.1, 0, o['z0'] - 0.08, o['z0'], 'CORNICE', skip={'+Y'})   # sill
        mb.box(o['x0'] - 0.1, o['x1'] + 0.1, -0.1, 0, o['z1'], o['z1'] + 0.15, 'CORNICE', skip={'+Y'})      # lintel
    pilasters(mb, H, lod)
    cornice(mb, 3.1, 3.3, 0.15, lod)
    return mb


def uf_shutter(lod):
    mb = MB(); H = FH
    wins = [dict(x0=-1.45, x1=-0.55, z0=0.9, z1=2.5, d=0.18, fill=window_frame),
            dict(x0=0.55, x1=1.45, z0=0.9, z1=2.5, d=0.18, fill=window_frame)]
    facade_wall(mb, 0, H, wins, lod)
    for o in wins:
        # open louvred leaves folded flat against the wall
        for xa, xb in ((o['x0'] - 0.45, o['x0']), (o['x1'], o['x1'] + 0.45)):
            if lod == 0:
                mb.box(xa, xb, -0.04, 0, o['z0'], o['z1'], 'GREEN', skip={'+Y'}, regions={'-Y': 'SHUTTER'})
            else:
                mb.quad([(xa, -0.012, o['z0']), (xb, -0.012, o['z0']), (xb, -0.012, o['z1']), (xa, -0.012, o['z1'])],
                        'SHUTTER', n=(0, -1, 0))
        if lod == 0:
            mb.box(o['x0'] - 0.08, o['x1'] + 0.08, -0.1, 0, o['z0'] - 0.08, o['z0'], 'CORNICE', skip={'+Y'})
            mb.box(o['x0'] - 0.1, o['x1'] + 0.1, -0.1, 0, o['z1'], o['z1'] + 0.15, 'CORNICE', skip={'+Y'})
    pilasters(mb, H, lod)
    cornice(mb, 3.1, 3.3, 0.15, lod)
    return mb


def _balcony_doors(mb, o, lod, fy):
    ox0, ox1, oz0, oz1 = o['x0'], o['x1'], o['z0'], o['z1']
    if 'WOODDOOR' in trim.TEXTURED:      # glass door image (leaves + side lights + transom) over the opening
        mb.quad([(ox0, fy, oz0), (ox1, fy, oz0), (ox1, fy, oz1), (ox0, fy, oz1)], 'WOODDOOR', n=(0, -1, 0))
        return
    leaves = 4
    for i in range(leaves):
        a = ox0 + (ox1 - ox0) * i / leaves
        b = ox0 + (ox1 - ox0) * (i + 1) / leaves
        is_glass = i in (1, 2)
        reg = 'GLASSWIN' if is_glass else 'SHUTTER'
        mat = MAT_GLASS if (is_glass and lod == 0) else MAT_KIT
        mb.quad([(a, fy, oz0), (b, fy, oz0), (b, fy, oz1), (a, fy, oz1)], reg, n=(0, -1, 0), mat=mat)
    if lod == 0:
        mb.box(ox0, ox1, fy - 0.05, fy, oz1 - 0.06, oz1, 'GREEN', skip={'+Y'})
        for i in range(1, leaves):
            x = ox0 + (ox1 - ox0) * i / leaves
            mb.box(x - 0.025, x + 0.025, fy - 0.05, fy, oz0, oz1 - 0.06, 'GREEN', skip={'+Y'})


def uf_balcony(lod):
    mb = MB(); H = FH
    facade_wall(mb, 0, H, [dict(x0=-1.2, x1=1.2, z0=0.05, z1=2.6, d=0.15, fill=_balcony_doors)], lod)
    bd = 1.1   # balcony depth
    skip = {'+Y'} if lod == 0 else {'+Y'}
    mb.box(-HW, HW, -bd, 0, -0.15, 0.05, 'CONCRETE', skip=skip, uv='world', phys=(4, 1))
    rz0, rz1 = 0.05, 1.0
    rail_panels(mb, -HW + 0.05, HW - 0.05, -bd + 0.04, rz0, rz1, 3, lod)
    rail_panels(mb, -bd + 0.04, 0, -HW + 0.05, rz0, rz1, 1, lod, axis='y')
    rail_panels(mb, -bd + 0.04, 0, HW - 0.05, rz0, rz1, 1, lod, axis='y')
    if lod == 0:
        t = 0.04
        if 'RAIL_BAL' not in trim.TEXTURED:       # with the railing image the frame / posts are in the picture
            mb.box(-HW + 0.02, HW - 0.02, -bd + 0.02, -bd + 0.02 + 2 * t, rz1, rz1 + t, 'DARK')    # hand rail
            for x in (-HW + 0.05, HW - 0.05):
                mb.box(x - t, x + t, -bd + 0.02, 0, rz1, rz1 + t, 'DARK', skip={'+Y'})
            for x in (-HW + 0.05, -0.65, 0.65, HW - 0.05):
                mb.box(x - t, x + t, -bd + 0.04 - t, -bd + 0.04 + t, rz0, rz1, 'DARK', skip={'-Z', '+Z'})
        mb.box(-1.3, 1.3, -0.1, 0, 2.6, 2.75, 'CORNICE', skip={'+Y'})                              # door lintel
    awning(mb, -HW, HW, -bd - 0.15, 3.05, 2.8, lod)
    pilasters(mb, H, lod)
    cornice(mb, 3.1, 3.3, 0.15, lod)
    return mb


def uf_balcony_solid(lod):
    """Door + balcony with a solid (painted) parapet instead of the iron railing."""
    mb = MB(); H = FH
    facade_wall(mb, 0, H, [dict(x0=-1.2, x1=1.2, z0=0.05, z1=2.6, d=0.15, fill=_balcony_doors)], lod)
    bd, pt, ph = 1.1, 0.1, 1.0      # balcony depth, parapet thickness / height
    mb.box(-HW, HW, -bd, 0, -0.15, 0.05, 'CONCRETE', skip={'+Y'}, uv='world', phys=(4, 1))
    pskip = {'-Z'} if lod == 0 else {'-Z', '+Y'}
    mb.box(-HW, HW, -bd, -bd + pt, 0.05, ph, 'PLASTER', skip=pskip, uv='world')                  # front parapet
    for xa, xb in ((-HW, -HW + pt), (HW - pt, HW)):
        sskip = {'-Z', '-Y', '+Y'} if lod == 0 else {'-Z', '-Y', '+Y', '-X' if xa < 0 else '+X'}
        mb.box(xa, xb, -bd + pt, 0, 0.05, ph, 'PLASTER', skip=sskip, uv='world')                  # side parapets
    if lod == 0:
        mb.box(-HW - 0.03, HW + 0.03, -bd - 0.03, -bd + pt + 0.03, ph, ph + 0.06, 'CORNICE', skip={'-Z'})   # coping
        mb.box(-1.3, 1.3, -0.1, 0, 2.6, 2.75, 'CORNICE', skip={'+Y'})                              # door lintel
    pilasters(mb, H, lod)
    cornice(mb, 3.1, 3.3, 0.15, lod)
    return mb


def uf_cage(lod):
    mb = MB(); H = FH
    facade_wall(mb, 0, H, [dict(x0=-1.3, x1=1.3, z0=0.8, z1=2.5, d=0.15, fill=window_frame)], lod)
    cd, cx = 0.6, 1.4               # cage depth / half width
    cz0, cz1 = 0.65, 2.65
    skip = {'+Y'} if lod == 0 else {'+Y', '-X', '+X'}
    mb.box(-cx, cx, -cd, 0, cz0 - 0.08, cz0, 'CONCRETE', skip=skip)                                  # cage floor
    rail_panels(mb, -cx, cx, -cd, cz0, cz1, 2, lod, region='RAIL_CAGE')
    rail_panels(mb, -cd, 0, -cx, cz0, cz1, 1, lod, axis='y', region='RAIL_CAGE')
    rail_panels(mb, -cd, 0, cx, cz0, cz1, 1, lod, axis='y', region='RAIL_CAGE')
    if lod == 0 and 'RAIL_CAGE' not in trim.TEXTURED:
        t = 0.03
        for x in (-cx, 0.0, cx):
            mb.box(x - t, x + t, -cd - t, -cd + t, cz0, cz1, 'DARK', skip={'-Z'})
        mb.box(-cx, cx, -cd - t, -cd + t, cz1 - 2 * t, cz1, 'DARK')
        for x in (-cx, cx):
            mb.box(x - t, x + t, -cd, 0, cz1 - 2 * t, cz1, 'DARK', skip={'+Y'})
    awning(mb, -cx - 0.1, cx + 0.1, -cd - 0.15, 2.95, cz1 + 0.05, lod)
    pilasters(mb, H, lod)
    cornice(mb, 3.1, 3.3, 0.15, lod)
    return mb


def tum_rect(depth=DEPTH):
    """Stair head-house on the roof, against the back wall (7 m deep on a 12 m lot)."""
    return dict(x0=-HW, x1=0.8, y0=round(max(depth - 7.0, depth * 0.45), 3), y1=depth, h=2.8)


TUM = tum_rect()


def rf_terrace(lod, depth=DEPTH):
    mb = MB(); TUM = tum_rect(depth)
    # roof slab (top of the last floor)
    segs = math.ceil(depth / 4.0 - 1e-6)
    for i in range(segs):
        ya, yb = depth * i / segs, depth * (i + 1) / segs
        mb.quad([(-HW, ya, 0), (HW, ya, 0), (HW, yb, 0), (-HW, yb, 0)], 'ROOFTOP', n=(0, 0, 1), uv='world', phys=(4, 4))
    ph, pt = 1.1, 0.15
    pskip = {'-Z'} if lod == 0 else {'-Z', '-X', '+X'}
    mb.box(-HW, HW, 0, pt, 0, ph, 'PLASTER', skip=pskip, uv='world', regions={'+Z': 'CONCRETE'})      # front parapet
    if lod == 0:
        mb.box(-HW, HW, -0.06, pt + 0.06, ph, ph + 0.08, 'CONCRETE', skip={'-Z'})                     # coping
    side_skip = {'-Z', '-Y', '+Y'}
    mb.box(-HW, -HW + pt, pt, TUM['y0'], 0, ph, 'PLASTER', skip=side_skip, uv='world', regions={'+Z': 'CONCRETE'})
    mb.box(HW - pt, HW, pt, depth - pt, 0, ph, 'PLASTER', skip=side_skip, uv='world', regions={'+Z': 'CONCRETE'})
    mb.box(TUM['x1'], HW - pt, depth - pt, depth, 0, ph, 'PLASTER', skip={'-Z', '-X', '+X'}, uv='world',
           regions={'+Z': 'CONCRETE'})
    # tum (stair head-house)
    tx0, tx1, ty0, ty1, th = TUM['x0'], TUM['x1'], TUM['y0'], TUM['y1'], TUM['h']
    door = dict(x0=tx0 + 0.45, x1=tx0 + 1.35)
    if lod == 0:
        # front wall with door hole
        mb.quad([(tx0, ty0, 0), (door['x0'], ty0, 0), (door['x0'], ty0, th), (tx0, ty0, th)], 'PLASTER', n=(0, -1, 0), uv='world')
        mb.quad([(door['x1'], ty0, 0), (tx1, ty0, 0), (tx1, ty0, th), (door['x1'], ty0, th)], 'PLASTER', n=(0, -1, 0), uv='world')
        mb.quad([(door['x0'], ty0, 2.2), (door['x1'], ty0, 2.2), (door['x1'], ty0, th), (door['x0'], ty0, th)], 'PLASTER', n=(0, -1, 0), uv='world')
        mb.quad([(door['x0'], ty0 + 0.1, 0), (door['x1'], ty0 + 0.1, 0), (door['x1'], ty0 + 0.1, 2.2), (door['x0'], ty0 + 0.1, 2.2)],
                'SHUTTER', n=(0, -1, 0))
        mb.quad([(door['x0'], ty0 + 0.1, 0), (door['x0'], ty0, 0), (door['x0'], ty0, 2.2), (door['x0'], ty0 + 0.1, 2.2)], 'PLASTER', n=(1, 0, 0), uv='world')
        mb.quad([(door['x1'], ty0, 0), (door['x1'], ty0 + 0.1, 0), (door['x1'], ty0 + 0.1, 2.2), (door['x1'], ty0, 2.2)], 'PLASTER', n=(-1, 0, 0), uv='world')
        mb.quad([(door['x0'], ty0, 2.2), (door['x1'], ty0, 2.2), (door['x1'], ty0 + 0.1, 2.2), (door['x0'], ty0 + 0.1, 2.2)], 'PLASTER', n=(0, 0, -1), uv='world')
    else:
        mb.quad([(tx0, ty0, 0), (tx1, ty0, 0), (tx1, ty0, th), (tx0, ty0, th)], 'PLASTER', n=(0, -1, 0), uv='world')
        mb.quad([(door['x0'], ty0 - 0.01, 0), (door['x1'], ty0 - 0.01, 0), (door['x1'], ty0 - 0.01, 2.2), (door['x0'], ty0 - 0.01, 2.2)],
                'SHUTTER', n=(0, -1, 0))
    mb.box(tx0, tx1, ty0, ty1, 0, th, 'PLASTER', skip={'-Y', '-Z', '+Z'}, uv='world')                  # tum sides + back
    mb.box(tx0 - 0.1, tx1 + 0.1, ty0 - 0.2, ty1, th, th + 0.15, 'CONCRETE', skip={'+Y'} if lod == 0 else {'+Y', '-Z'})
    return mb


def rf_tileroof(lod, depth=DEPTH):
    """Gable tile roof sitting on top of the tum slab (origin = terrace level)."""
    mb = MB(); TUM = tum_rect(depth)
    base = TUM['h'] + 0.15
    x0, x1 = TUM['x0'] - 0.15, TUM['x1'] + 0.15
    y0, y1 = TUM['y0'] - 0.3, TUM['y1']
    xr = (x0 + x1) / 2
    rh = 1.1
    segs = 3
    for i in range(segs):
        ya, yb = y0 + (y1 - y0) * i / segs, y0 + (y1 - y0) * (i + 1) / segs
        mb.quad([(x0, yb, base), (x0, ya, base), (xr, ya, base + rh), (xr, yb, base + rh)], 'TILE', n=(-rh, 0, xr - x0), uv='world', phys=(3, 2))
        mb.quad([(x1, ya, base), (x1, yb, base), (xr, yb, base + rh), (xr, ya, base + rh)], 'TILE', n=(rh, 0, x1 - xr), uv='world', phys=(3, 2))
        if lod == 0:
            u = base - 0.03   # underside sits below the tiles (no z-fighting)
            mb.quad([(x0, ya, u), (x0, yb, u), (xr, yb, u + rh), (xr, ya, u + rh)], 'CONCRETE', n=(rh, 0, -(xr - x0)), uv='world')
            mb.quad([(x1, yb, u), (x1, ya, u), (xr, ya, u + rh), (xr, yb, u + rh)], 'CONCRETE', n=(-rh, 0, -(x1 - xr)), uv='world')
    mb.poly([(x0, y0, base), (x1, y0, base), (xr, y0, base + rh)], 'PLASTER', n=(0, -1, 0))
    mb.poly([(x1, y1, base), (x0, y1, base), (xr, y1, base + rh)], 'PLASTER', n=(0, 1, 0))
    if lod == 0:
        mb.box(xr - 0.1, xr + 0.1, y0 - 0.05, y1 + 0.05, base + rh - 0.06, base + rh + 0.1, 'TILE')    # ridge
    return mb


# ---------------------------------------------------------------- whole-house roofs
# Plain planes over the full footprint (origin = top of the last floor); every tile course or
# corrugation is left to the ROOF texture. The colour is baked into the vertex colour.
ROOF_COLORS = {'Red': (0.62, 0.17, 0.11), 'Blue': (0.11, 0.19, 0.38)}
ROOF_RISE = 1.5          # gable / hip ridge height above the eaves (4 m span -> ~37 deg)
ROOF_FRONT_OV, ROOF_BACK_OV = 0.4, 0.2


def _gable_end(mb, y, n, rise):
    mb.poly([(-HW, y, 0), (HW, y, 0), (0, y, rise)], 'PLASTER', n=n)


def roof(kind, color):
    col = ROOF_COLORS[color]

    def build(lod, depth=DEPTH):
        mb = MB()
        yf, yb = -ROOF_FRONT_OV, depth + ROOF_BACK_OV
        if kind == 'Shed':
            # one slope, low at the street, high at the back (~7 deg)
            rise = 0.12 * depth
            z = lambda y: y * rise / depth
            tiled_poly(mb, [(-HW, yf, z(yf)), (HW, yf, z(yf)), (HW, yb, z(yb)), (-HW, yb, z(yb))],
                       'ROOF', (0, -rise, depth), col=col, double=True)
            for s in (-1, 1):
                tiled_poly(mb, [(s * HW, 0, 0), (s * HW, depth, 0), (s * HW, depth, rise)], 'PLASTER', (s, 0, 0))
            mb.quad([(HW, depth, 0), (-HW, depth, 0), (-HW, depth, rise), (HW, depth, rise)], 'PLASTER', n=(0, 1, 0), uv='world')
        elif kind == 'Gable':
            # ridge along the depth, gable ends face the street and the back
            r = ROOF_RISE
            for s in (-1, 1):
                tiled_poly(mb, [(s * HW, yf, 0), (s * HW, yb, 0), (0, yb, r), (0, yf, r)],
                           'ROOF', (s * r, 0, HW), col=col, double=True)
            _gable_end(mb, 0, (0, -1, 0), r)
            _gable_end(mb, depth, (0, 1, 0), r)
        elif kind == 'Hip':
            # four slopes; the front / back ones run past the walls as eaves
            r, k = ROOF_RISE, ROOF_RISE / HW
            y0, y1 = HW, depth - HW                       # ridge ends (45 deg hips in plan)
            for s in (-1, 1):
                tiled_poly(mb, [(s * HW, 0, 0), (s * HW, depth, 0), (0, y1, r), (0, y0, r)],
                           'ROOF', (s * r, 0, HW), col=col, double=True)
            tiled_poly(mb, [(-HW, yf, yf * k), (HW, yf, yf * k), (HW, 0, 0), (0, y0, r), (-HW, 0, 0)],
                       'ROOF', (0, -r, HW), col=col, double=True)
            tiled_poly(mb, [(HW, yb, (depth - yb) * k), (-HW, yb, (depth - yb) * k), (-HW, depth, 0), (0, y1, r), (HW, depth, 0)],
                       'ROOF', (0, r, HW), col=col, double=True)
        return mb
    return build


def pr_ac(lod):
    """Air-conditioner outdoor unit; origin at wall, bottom centre."""
    mb = MB()
    skip = {'+Y'}
    mb.box(-0.4, 0.4, -0.32, 0, 0.0, 0.55, 'ACBODY', skip=skip, regions={'-Y': 'ACGRILL'})
    if lod == 0:
        for x in (-0.3, 0.3):
            mb.box(x - 0.02, x + 0.02, -0.38, 0, -0.06, 0.0, 'DARK', skip={'+Y'})
    return mb


def pr_watertank(lod):
    """Stainless horizontal water tank on two stands; origin bottom centre, axis along X."""
    mb = MB()
    r, L, cz = 0.45, 1.5, 0.75
    mb.cylinder_x(-L / 2, L / 2, 0, cz, r, 16 if lod == 0 else 8, 'METAL')
    if lod == 0:
        for x in (-0.45, 0.45):
            mb.box(x - 0.04, x + 0.04, -0.4, 0.4, 0, cz - r + 0.05, 'DARK', skip={'-Z'})
    return mb


MODULES = {
    'Body_GF':      body(GH),
    'Body_UF':      body(FH),
    'GF_Shop':      gf_shop,
    'GF_Roller':    gf_roller,
    'GF_WoodDoor':  gf_wooddoor,
    'GF_FoldGate':  gf_foldgate,
    'GF_Open':      gf_open,
    'UF_Window':    uf_window,
    'UF_Shutter':   uf_shutter,
    'UF_Balcony':   uf_balcony,          # door + open (railing) balcony
    'UF_BalconySolid': uf_balcony_solid,  # door + closed (solid parapet) balcony
    'UF_Cage':      uf_cage,
    'RF_Terrace':   rf_terrace,
    'RF_TileRoof':  rf_tileroof,
    'PR_AC':        pr_ac,
    'PR_WaterTank': pr_watertank,
}
for _k, _h in (('GF', GH), ('UF', FH)):
    MODULES[f'Back_{_k}'] = back_wall(_h)
    for _n in (0, 1, 2):
        for _a in (SIDE_ALIGNS if _n else ('',)):       # e.g. SideR_UF_1 (centre), SideR_UF_1F, SideR_UF_2B
            MODULES[f'SideL_{_k}_{_n}{_a}'] = side_wall(_h, _n, -1, _k, _a)
            MODULES[f'SideR_{_k}_{_n}{_a}'] = side_wall(_h, _n, 1, _k, _a)
for _kind in ('Shed', 'Gable', 'Hip'):
    for _c in ROOF_COLORS:
        MODULES[f'ROOF_{_kind}_{_c}'] = roof(_kind, _c)

# modules whose shape follows the lot depth: build(lod, depth=...)
DEPTH_MODULES = {k for k in MODULES
                 if k.startswith(('Body_', 'Back_', 'SideL_', 'SideR_', 'ROOF_', 'RF_'))}


def build_module(name, lod, depth=DEPTH):
    return MODULES[name](lod, depth=depth) if name in DEPTH_MODULES else MODULES[name](lod)
