"""M2: OpenStreetMap -> clean city layout (Map/city.json) + error report.

OSM is only a *hint*: building shapes come from the variant library, roads are rebuilt from
centrelines + a width table, tube houses are infilled along block frontages. Dirty OSM data can
therefore only shift lots, never break geometry.

    python Map/osm_pipeline.py [Map/raw/thanhxuan.osm] [--out Map/out_test] [--no-trees] [--no-motos] [--no-props]

Outputs (Map/out/, or the --out folder):
  city.json           layout for Unity (metres, x = east, y = north, origin = centre of the bounds)
  report.png          map of the result; red = needs a human decision
  report.json         the same flags as a list
  *.geojson           cleaned layers in WGS84, to view/fix in QGIS

Manual fixes: Map/overrides.geojson (WGS84, edit in QGIS). Feature property "op":
  road         LineString near an OSM road, or {"osm_id": id}: {"width": m} or {"lanes": n}; "drop": true removes it
  road_add     LineString: new road, {"width": m, "class": "residential"}
  no_build     Polygon: nothing is placed inside (parks, yards, stations...)
  building     Polygon: big building replacing OSM ones it overlaps, {"levels": n}
  delete       Polygon: removes OSM big buildings intersecting it
  sidewalk     Polygon, {"mode": "add"}: becomes sidewalk (taken from road or block, nothing is built on it);
               {"mode": "cut"}: sidewalk inside becomes road surface. Kerbs follow the edited shape.
  tree         Point: adds a tree ({"species": "Sau" | "XaCu" | "Bang" | "HoaSua", "scale": 1.0} optional);
               Polygon: removes every generated tree inside (see out/trees.geojson).
Overrides are applied after the automatic steps, so re-downloading OSM keeps them.

This file only runs the steps in order; the steps live in Map/pipeline/:
  config     shared settings (paths, sidewalk table, street cross-section)
  osm        parsing, projection, geometry helpers, overrides file
  roads      carriageways, sidewalks, corner fillets, kerbs
  metro      elevated metro + the corridor under it
  flyover    road flyovers (plan from OSM, profile + piers from design rules)
  buildings  big buildings, tube-house lots, layout checks
  trees / motos / props   street trees, parked bikes, street props
  chunks     per-chunk export for Unity
  report     GeoJSON layers + report pictures
"""
import json, os, sys
from collections import defaultdict

import shapely
import shapely.prepared
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from pipeline.config import (CHUNK, HERE, KERB_ANGLE, KERB_H, KERB_LIP, KERB_PROFILE, KERB_STONE, KERB_VIEWS,
    KERB_W, OPEN_TAGS, OVERRIDES, RAIL_CLEAR, ROAD_Y, WATER_TAGS)
from pipeline.osm import Tiled, area_features, load_overrides, parse_osm, polygons_of, tag_match
from pipeline.roads import build_roads, fillet_corners, kerb_lines, sidewalk_overrides
from pipeline.metro import build_rails, metro_corridor
from pipeline.flyover import build_flyovers, report_flyover
from pipeline.traffic import build_lanes, report_traffic
from pipeline.buildings import build_big, checks, infill_lots
from pipeline.trees import TREE_SPECIES, place_trees
from pipeline.motos import place_motos
from pipeline.props import PROP_KINDS, place_props
from pipeline.chunks import chunk_meshes, chunk_motos, chunk_props, chunk_trees
from pipeline.report import report_png, save_geojson


def main(osm_path, out=os.path.join(HERE, 'out'), skip=()):
    os.makedirs(out, exist_ok=True)
    proj, area, nodes, ways, rels = parse_osm(osm_path)
    print(f"[osm] {len(nodes)} nodes, {len(ways)} ways, {len(rels)} relations, area {area.area / 1e6:.2f} km2")
    overrides = load_overrides(proj)
    flags = []

    roads, surface, sidewalk = build_roads(ways, nodes, area, overrides, flags)
    flyovers = build_flyovers(ways, nodes, roads, area, flags)
    traffic = build_lanes(roads, nodes, flyovers, area, flags)
    fly_foot = unary_union([f['_centre'].buffer(max(f['width']) / 2, cap_style='flat') for f in flyovers]
                           or [Polygon()]).intersection(area)
    rails, platforms = build_rails(ways, nodes, area)
    corridor, median = metro_corridor(rails, roads, surface)
    rail_clear = unary_union([r['centre'].buffer(RAIL_CLEAR) for r in rails]).intersection(area) if rails else Polygon()
    # under the viaduct: plain asphalt, no sidewalk; the median only marks where piers + planter frames go
    surface = surface.union(corridor).intersection(area)
    sidewalk = sidewalk.difference(corridor).difference(median)
    median = median.intersection(area)
    surface, sidewalk = sidewalk_overrides(surface, sidewalk, overrides, area)
    ramp_foot = unary_union([f['_ramp_foot'] for f in flyovers] or [Polygon()]).intersection(area)
    if not ramp_foot.is_empty:
        surface = surface.union(sidewalk.intersection(ramp_foot))
        sidewalk = sidewalk.difference(ramp_foot)
    surface, sidewalk = fillet_corners(surface, sidewalk)
    kerbs, skirts, walk_top = kerb_lines(surface, sidewalk)
    street = surface.union(sidewalk)
    water = unary_union([p for _, p, _ in area_features(ways, rels, nodes, lambda t: tag_match(t, WATER_TAGS))]
                        or [Polygon()]).intersection(area)
    open_ = unary_union([p for _, p, _ in area_features(ways, rels, nodes, lambda t: tag_match(t, OPEN_TAGS))]
                        + [g for p, g in overrides if p.get('op') == 'no_build'] or [Polygon()]).intersection(area)
    open_ = open_.difference(street).difference(water)
    blocked = street.union(water).union(corridor).union(rail_clear).union(fly_foot)
    origin = area.bounds[:2]
    blocked_t = Tiled(blocked, origin)
    street_t = Tiled(street, origin)
    print("[tiles] street/blocked indexed")

    big, big_union = build_big(ways, rels, nodes, area, blocked_t, overrides, flags)
    blocks_geom = area.difference(blocked).difference(open_).difference(big_union.buffer(1.0))
    blocks = [p for p in polygons_of(blocks_geom) if p.area >= 30]
    print(f"[blocks] {len(blocks)} blocks")
    lots = infill_lots(blocks, street_t, flags)
    res = checks(lots, big, street_t, flags)
    # nothing generated under a flyover (its median is sidewalk); hand-placed trees (kind 2) stay
    fly_p = shapely.prepared.prep(fly_foot.buffer(1.0)) if not fly_foot.is_empty else None
    def clear_of_flyover(items, keep=lambda it: False):
        n = len(items)
        items = [it for it in items if fly_p is None or keep(it) or not fly_p.contains(Point(it['x'], it['y']))]
        return items, n - len(items)
    trees, n_t = clear_of_flyover(place_trees(kerbs, roads, surface, sidewalk, open_, lots, big, origin, overrides),
                                  keep=lambda t: t['kind'] == 2)
    motos, n_m = clear_of_flyover(place_motos(lots, walk_top, surface, trees, origin, overrides))
    props, n_p = clear_of_flyover(place_props(kerbs, roads, surface, walk_top, trees, motos, origin, overrides))
    if 'trees' in skip: trees = []
    if 'motos' in skip: motos = []
    if 'props' in skip: props = []
    if fly_p is not None:
        print(f"[flyover] removed under the deck: {n_t} trees, {n_m} bikes, {n_p} props")

    # "sidewalk" = the flat top only (kerb band cut off); kerbs / skirts are swept in Unity
    chunks, (gx, gy, nx, ny) = chunk_meshes(area, {k: Tiled(g, origin, CHUNK) for k, g in
                                                   dict(road=surface, sidewalk=walk_top, water=water, green=open_).items()},
                                            lines=dict(kerb=kerbs, skirt=skirts))
    chunk_trees(chunks, trees, gx, gy, nx, ny)
    chunk_motos(chunks, motos, gx, gy, nx, ny)
    chunk_props(chunks, props, gx, gy, nx, ny)
    x0, y0, x1, y1 = area.bounds
    city = dict(
        version=1, source=os.path.basename(osm_path),
        origin=dict(lat=proj.lat0, lon=proj.lon0),
        coords="metres, x = east, y = north, origin = centre of the OSM bounds",
        bounds=[round(v, 2) for v in (x0, y0, x1, y1)],
        chunk=dict(size=CHUNK, x0=round(gx, 2), y0=round(gy, 2), nx=nx, ny=ny),
        # street cross-section: heights in metres above the block ground (road_y) / above the road (kerb_*);
        # profile = flat [across, up, ...], across 0 = road edge, negative = sidewalk side
        street=dict(road_y=ROAD_Y, kerb_h=KERB_H, kerb_lip=KERB_LIP, kerb_angle=KERB_ANGLE, kerb_w=KERB_W,
                    stone=KERB_STONE, profile=[v for xy in KERB_PROFILE for v in xy]),
        roads=[dict(id=r['id'], cls=r['cls'], width=r['width'], layer=r['layer'], bridge=r['bridge'],
                    name=r['name'], line=[[round(x, 2), round(y, 2)] for x, y in r['line'].coords]) for r in roads],
        buildings=[{k: v for k, v in b.items() if k not in ('rect', 'poly')} for b in big],
        lots=[{k: v for k, v in l.items() if k != 'rect'} for l in lots],
        # one entry per continuous piece of viaduct centreline, flat [x0, y0, x1, y1, ...] (JsonUtility-friendly)
        rails=[dict(ref=r['ref'], name=r['name'], layer=r['layer'], tracks=r['tracks'],
                    line=[round(v, 2) for xy in l.coords for v in xy])
               for r in rails for l in getattr(r['centre'], 'geoms', [r['centre']])],
        platforms=[dict(ring=[round(v, 2) for xy in p.exterior.coords for v in xy]) for p in platforms],
        # pier / planter-frame zone under the viaduct (cut at junctions), for the viaduct step
        medians=[dict(ring=[round(v, 2) for xy in p.exterior.coords for v in xy]) for p in polygons_of(median)],
        # road flyovers: line = flat [x, y, z(deck top above the road), ...] every ~FLY_STEP m, width per point;
        # segments (arc length s) = 'ramp' (solid approach between walls) | 'deck' (girder on piers);
        # piers: s, x, y, yaw (deg, 0 = north, clockwise), top = girder bottom height
        flyovers=[{k: v for k, v in f.items() if not k.startswith('_')} for f in flyovers],
        # traffic lanes (pipeline/traffic.py): lanes[] (pts flat [x, y, z above the road], next[], src / sink),
        # junction links are lanes of kind 'link'; conflicts = flat pairs of links that cross / merge
        traffic={k: v for k, v in traffic.items() if not k.startswith('_')},
        chunks=chunks,
        checks=res,
    )
    with open(os.path.join(out, 'city.json'), 'w', encoding='utf-8') as f:
        json.dump(city, f, separators=(',', ':'))
    with open(os.path.join(out, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(dict(checks=res, flags=flags), f, indent=1, ensure_ascii=False)

    raw_big_outlines = [p for _, p, t in area_features(ways, rels, nodes, lambda t: 'building' in t)]
    report_png(os.path.join(out, 'report.png'), area, raw_big_outlines, surface, sidewalk, water, open_, lots, big, flags,
               median=median, rails=rails)
    cx, cy = area.centroid.x, area.centroid.y
    report_png(os.path.join(out, 'report_zoom.png'), area, raw_big_outlines, surface, sidewalk, water, open_, lots, big,
               flags, zoom=(cx - 300, cy - 200, cx + 300, cy + 200), median=median, rails=rails)
    for i, (kx, ky) in enumerate(KERB_VIEWS):
        report_png(os.path.join(out, f'report_kerb_{i}.png'), area, raw_big_outlines, surface, sidewalk, water, open_,
                   lots, big, flags, zoom=(kx - 75, ky - 50, kx + 75, ky + 50), median=median, rails=rails,
                   kerbs=kerbs, skirts=skirts)
    report_png(os.path.join(out, 'report_metro.png'), area, raw_big_outlines, surface, sidewalk, water, open_, lots, big,
               flags, zoom=(-1100, -700, -100, 100), median=median, rails=rails)
    report_png(os.path.join(out, 'report_metro_n.png'), area, raw_big_outlines, surface, sidewalk, water, open_, lots, big,
               flags, zoom=(-300, 0, 500, 884), median=median, rails=rails)
    for name, zoom in (('report_trees.png', None), ('report_trees_0.png', (0, -250, 500, 100)),
                       ('report_trees_1.png', (-700, 150, -200, 500))):
        report_png(os.path.join(out, name), area, raw_big_outlines, surface, sidewalk, water, open_, lots, big, [],
                   zoom=zoom, median=median, rails=rails, trees=trees)
    save_geojson(out, 'trees.geojson', [(dict(species=TREE_SPECIES[t['sp']], scale=t['scale'], kind=t['kind']),
                                    Point(t['x'], t['y'])) for t in trees], proj)

    for name, zoom in (('report_motos_0.png', (100, -150, 250, -50)), ('report_motos_1.png', (-500, 250, -350, 350))):
        report_png(os.path.join(out, name), area, raw_big_outlines, surface, sidewalk, water, open_, lots, big, [],
                   zoom=zoom, median=median, rails=rails, trees=trees, motos=motos)
    save_geojson(out, 'props.geojson', [(dict(kind=PROP_KINDS[p['kind']], yaw=p['yaw']), Point(p['x'], p['y']))
                                   for p in props], proj)
    save_geojson(out, 'motos.geojson', [(dict(yaw=m['yaw']), Point(m['x'], m['y'])) for m in motos], proj)
    save_geojson(out, 'roads.geojson', [(dict(id=r['id'], cls=r['cls'], width=r['width'], name=r['name']), r['line']) for r in roads], proj)
    save_geojson(out, 'road_surface.geojson', [(dict(kind='road'), surface), (dict(kind='sidewalk'), sidewalk),
                                          (dict(kind='median'), median)], proj)
    save_geojson(out, 'sidewalk.geojson', [(dict(kind='sidewalk_top'), walk_top)]
                 + [(dict(kind='kerb'), k) for k in kerbs] + [(dict(kind='skirt'), k) for k in skirts], proj)
    save_geojson(out, 'rail.geojson', [(dict(ref=r['ref'], name=r['name'], layer=r['layer']), r['centre']) for r in rails]
                 + [(dict(kind='platform'), p) for p in platforms], proj)
    save_geojson(out, 'buildings.geojson', [(dict(id=b['id'], levels=b['levels'], name=b['name']), b['rect']) for b in big], proj)
    save_geojson(out, 'lots.geojson', [(dict(block=l['block'], width=l['width']), l['rect']) for l in lots], proj)
    for f in flyovers:
        report_flyover(os.path.join(out, f"report_flyover_{f['id']}.png"), f, surface, sidewalk)
    report_traffic(os.path.join(out, 'report_traffic.png'), traffic, surface)
    if flyovers:                           # the junction under the first flyover
        f = flyovers[0]
        m = f['_centre'].interpolate((f['clear_from'] + f['clear_to']) / 2)
        report_traffic(os.path.join(out, 'report_traffic_junction.png'), traffic, surface,
                       zoom=(m.x - 80, m.y - 55, m.x + 80, m.y + 55))
    save_geojson(out, 'flyover.geojson', [(dict(id=f['id'], name=f['name'], kind='centre'), f['_centre']) for f in flyovers]
                 + [(dict(id=f['id'], kind='pier', s=p['s'], top=p['top']), Point(p['x'], p['y']))
                    for f in flyovers for p in f['piers']], proj)
    save_geojson(out, 'flags.geojson', [(dict(kind=f['kind'], id=f['id'], msg=f['msg']), Point(f['xy'])) for f in flags], proj)
    if not os.path.exists(OVERRIDES):
        with open(OVERRIDES, 'w', encoding='utf-8') as f:
            json.dump(dict(type='FeatureCollection', features=[]), f)

    kinds = defaultdict(int)
    for f in flags:
        kinds[f['kind']] += 1
    size = os.path.getsize(os.path.join(out, 'city.json')) / 1e6
    print(f"[out] city.json {size:.1f} MB, {len(chunks)} chunks, flags {dict(kinds)}")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')    # Vietnamese names on a cp1252 console
    args = sys.argv[1:]
    out = os.path.join(HERE, 'out')
    if '--out' in args:                    # separate output folder (test areas), Map/out stays untouched
        i = args.index('--out')
        out = os.path.abspath(args[i + 1])
        del args[i:i + 2]
    skip = tuple(a[5:] for a in args if a in ('--no-trees', '--no-motos', '--no-props'))   # CityGenerator window
    args = [a for a in args if not a.startswith('--no-')]
    main(args[0] if args else os.path.join(HERE, 'raw', 'paris.osm'), out, skip)
