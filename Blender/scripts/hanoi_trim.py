"""Trim-sheet layout for the Hanoi tube-house kit (no texture yet).

REGIONS is the single source of truth for where each surface type lives on the future
2048x2048 trim sheet; hanoi_kit.py maps every face's UVs into one of these rects.
PREVIEW_COLORS is written to a per-corner colour attribute ('Col'): RGB = base colour,
A = paint mask. The Unity shader Hanoi/Building tints painted surfaces per house.
"""

N = 2048
INSET_PX = 3

# name -> (cx0, cy0, cx1, cy1) in 1/8-sheet cells, origin bottom-left (UV space)
REGIONS = {
    'PLASTER':    (0, 6, 2, 8),
    'FOLDGATE':   (2, 6, 4, 8),     # steel folding gate (cửa kéo), one plane per door
    'WOODDOOR':   (0, 4, 2, 6),     # panelled wooden door, one plane per door
    'INTERIOR':   (2, 4, 3, 5),     # flat light colour behind an open ground floor
    'ROOF':       (3, 4, 4, 6),     # whole-house roof planes; tiles / steel sheet live in the texture,
                                    # colour (red / dark blue) comes from the vertex colour
    'ROOFTOP':    (2, 5, 3, 6),     # terrace floor tiles
    'CORNICE':    (4, 7, 8, 8),
    'SHUTTER':    (4, 5, 6, 7),
    'GLASSWIN':   (6, 5, 8, 7),
    'TILE':       (4, 3, 6, 5),
    'CORRUGATED': (6, 3, 8, 5),
    'ROLLER':     (0, 2, 2, 4),
    'SHOP':       (2, 2, 4, 4),
    'RAIL':       (0, 0, 2, 2),
    'METAL':      (2, 1, 3, 2),
    'DARK':       (3, 1, 4, 2),
    'ACGRILL':    (2, 0, 3, 1),
    'ACBODY':     (3, 0, 4, 1),
    'SIGN_A':     (4, 2, 8, 3),
    'SIGN_B':     (4, 1, 8, 2),
    'CONCRETE':   (4, 0, 7, 1),
    # facade-grid styles for towers: UV0 only selects the style, the cell pattern is drawn by
    # the shader from the second UV layer 'FacadeUV' (bay index + s, floor index + t)
    'GRID_RES_LOGGIA': (7.00, 0, 7.25, 1),   # T1 white residential, recessed loggias
    'GRID_STRIPE':     (7.25, 0, 7.50, 1),   # T2 vertical panel stripes + dark glass
    'GRID_PUNCHED':    (7.50, 0, 7.75, 1),   # T3 old housing, punched square windows
    'GRID_CURTAIN':    (7.75, 0, 8.00, 1),   # T4 / podium, glass curtain wall
}
GRID_STYLES = ('GRID_RES_LOGGIA', 'GRID_STRIPE', 'GRID_PUNCHED', 'GRID_CURTAIN')
# solid-colour patches inside a parent region: (parent, s0, t0, s1, t1)
SUBREGIONS = {
    'GREEN': ('SHUTTER', 0.012, 0.15, 0.055, 0.85),   # plain shutter paint (frames, mullions)
    'RAIL_BAL':  ('RAIL', 0.0, 0.625, 1.0, 1.0),      # open balcony railing, 512x192 (panel 1.45 x 0.95 m)
    'RAIL_CAGE': ('RAIL', 0.0, 0.0, 1.0, 0.625),      # closed cage grille, 512x320 (panel 1.4 x 2.0 m)
}

# Regions tinted per house by the shader (vertex alpha = 1); their RGB is a neutral base.
PAINTABLE = {'PLASTER', 'CORNICE'}

# sRGB base colours, written to the 'Col' corner attribute (alpha = paint mask)
PREVIEW_COLORS = {
    'PLASTER':    (0.88, 0.87, 0.84),
    'FOLDGATE':   (0.40, 0.44, 0.47),
    'WOODDOOR':   (0.42, 0.25, 0.13),
    'INTERIOR':   (1.00, 0.95, 0.80),
    'ROOF':       (0.62, 0.17, 0.11),
    'ROOFTOP':    (0.66, 0.66, 0.64),
    'CORNICE':    (0.97, 0.96, 0.93),
    'SHUTTER':    (0.16, 0.40, 0.28),
    'GREEN':      (0.13, 0.33, 0.23),
    'GLASSWIN':   (0.80, 0.78, 0.70),
    'TILE':       (0.62, 0.27, 0.15),
    'CORRUGATED': (0.42, 0.52, 0.58),
    'ROLLER':     (0.62, 0.63, 0.64),
    'SHOP':       (0.20, 0.16, 0.14),
    'RAIL':       (0.09, 0.10, 0.09),
    'RAIL_BAL':   (0.09, 0.10, 0.09),
    'RAIL_CAGE':  (0.09, 0.10, 0.09),
    'METAL':      (0.78, 0.78, 0.80),
    'DARK':       (0.05, 0.05, 0.05),
    'ACGRILL':    (0.55, 0.55, 0.53),
    'ACBODY':     (0.86, 0.85, 0.80),
    'SIGN_A':     (0.75, 0.08, 0.06),
    'SIGN_B':     (0.08, 0.25, 0.60),
    'CONCRETE':   (0.55, 0.55, 0.53),
    'GRID_RES_LOGGIA': (0.92, 0.92, 0.90),
    'GRID_STRIPE':     (0.80, 0.80, 0.78),
    'GRID_PUNCHED':    (0.86, 0.85, 0.82),
    'GRID_CURTAIN':    (0.35, 0.45, 0.55),
}


def uv_rect(name):
    """UV rect (u0, v0, u1, v1) of a region, inset a few pixels against bleeding."""
    if name in SUBREGIONS:
        parent, s0, t0, s1, t1 = SUBREGIONS[name]
        u0, v0, u1, v1 = uv_rect(parent)
        return (u0 + s0 * (u1 - u0), v0 + t0 * (v1 - v0), u0 + s1 * (u1 - u0), v0 + t1 * (v1 - v0))
    cx0, cy0, cx1, cy1 = REGIONS[name]
    e = INSET_PX / N
    return (cx0 / 8 + e, cy0 / 8 + e, cx1 / 8 - e, cy1 / 8 - e)


# Regions that carry an image in Export/Textures/T_HanoiTrim.png (written by build_trim_texture.py).
# to_mesh leaves their vertex colour white so the texture is not tinted twice; paintable regions
# (PLASTER) and roofs (explicit colour override) still get tinted by alpha / the colour override.
def _load_textured():
    import json, os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Export", "Textures", "textured_regions.json")
    try:
        with open(p) as f:
            return frozenset(json.load(f))
    except (OSError, ValueError):
        return frozenset()


TEXTURED = _load_textured()


def _load_rail_slices():
    import json, os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Export", "Textures", "rail_slices.json")
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# where to cut each railing image so it can be tiled: {region: {w, h, l, r}} (see build_trim_texture.py)
RAIL_SLICES = _load_rail_slices()
