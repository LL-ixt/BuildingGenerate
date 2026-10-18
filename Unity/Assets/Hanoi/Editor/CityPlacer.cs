using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

/// <summary>
/// M3: put the variant library on the cleaned map (Map/out/city.json) and write one scene per
/// 200 m chunk (Assets/Hanoi/City/Chunks) + a main scene listing them.
///  - Tube-house lots: consecutive lots along one block edge form a row; TubeHousePicker picks
///    the variants (no identical neighbours, side windows at row ends and height steps). The house
///    is stretched across the lot width (x) and to the lot depth (z).
///  - Big buildings: tower variant with the nearest floor count, stretched to the footprint rectangle.
///  - Roads / sidewalks / green / water: the chunk triangles of city.json as flat meshes.
///  - Manual edits survive re-runs: locked PlacedBuildings and hand-added objects are kept, lots
///    whose building was deleted by hand are tombstoned (CityPlacement.asset).
/// Map metres: x = east, y = north  ->  Unity x = east, z = north.
/// Menu "Hanoi/City/..." or batch: -executeMethod CityPlacer.RunBatch
/// </summary>
public static class CityPlacer
{
    // main map by default; a test area via CityTarget.With (FlyoverTest.cs)
    static string CityDir => CityTarget.Dir;
    static string ChunkDir => CityTarget.ChunkDir;
    static string MainScene => CityTarget.MainScene;
    static string RecordPath => CityTarget.RecordPath;
    const string LibPrefabDir = "Assets/Hanoi/Library/Prefabs";
    static string CityJson => CityTarget.CityJson;

    // ------------------------------------------------------------------ city.json
    [Serializable] class City { public float[] bounds; public Grid chunk; public StreetJ street; public Big[] buildings; public LotJ[] lots; public ChunkJ[] chunks; }
    [Serializable] class StreetJ { public float road_y, kerb_h, kerb_lip, kerb_angle, kerb_w, stone; public float[] profile; }
    [Serializable] class Grid { public float size, x0, y0; public int nx, ny; }
    [Serializable] class Big { public string id, name; public float levels, area, cx, cy, length, width; public float[] axis; }
    [Serializable] class LotJ { public float cx, cy, width, depth; public float[] front; public int block; }
    [Serializable] class ChunkJ
    {
        public int ix, iy;
        public float[] bounds, road, sidewalk, water, green;
        public float[] kerb, kerb_s, skirt;          // polylines: flat x,z / start distance; point counts in *_n
        public int[] kerb_n, skirt_n;
        public float[] tree;                         // flat [x, z, species, yaw, scale, kind] (kind 0 street, 1 park, 2 override)
        public float[] moto;                         // flat [x, z, yaw] parked bikes (osm_pipeline.place_motos)
        public float[] prop;                         // flat [x, z, kind, yaw] street props (osm_pipeline.place_props, HanoiProps.Ids)
    }

    static City LoadCity()
    {
        string txt = File.ReadAllText(CityJson);
        txt = Regex.Replace(txt, "\"levels\":\\s*null", "\"levels\": -1");     // JsonUtility has no nullable floats
        return JsonUtility.FromJson<City>(txt);
    }

    struct Placement
    {
        public string key, id;          // lot key, variant id
        public BuildingVariant variant; // valid only until the next scene is opened
        public Vector3 pos, scale;
        public Quaternion rot;
        public int seed;
        public bool exposed;
    }

    static int Hash(float x, float y) => unchecked((int)Mathf.Round(x * 10f) * 73856093 ^ (int)Mathf.Round(y * 10f) * 19349663);
    static string LotKey(float x, float y) => $"L{x:F1}_{y:F1}";
    static string ChunkName(int ix, int iy) => $"{CityTarget.Current.prefix}Chunk_{ix:00}_{iy:00}";

    // ------------------------------------------------------------------ tube houses
    static bool SameRow(LotJ a, LotJ b) =>
        a.block == b.block &&
        a.front[0] * b.front[0] + a.front[1] * b.front[1] > 0.999f &&
        Vector2.Distance(new Vector2(a.cx, a.cy), new Vector2(b.cx, b.cy)) < (a.width + b.width) / 2f + 0.3f;

    /// Point-in-lot lookup on a 20 m grid (lots + big building rectangles) for side-wall exposure.
    class Occupancy
    {
        struct R { public Vector2 c, u, v; public float hu, hv; public int id; }   // centre, axes, half sizes
        readonly Dictionary<(int, int), List<R>> grid = new Dictionary<(int, int), List<R>>();
        const float Cell = 20f;

        public void Add(int id, Vector2 c, Vector2 u, float hu, Vector2 v, float hv)
        {
            var r = new R { c = c, u = u, v = v, hu = hu, hv = hv, id = id };
            float ext = Mathf.Abs(u.x) * hu + Mathf.Abs(v.x) * hv, eyt = Mathf.Abs(u.y) * hu + Mathf.Abs(v.y) * hv;
            for (int gx = Mathf.FloorToInt((c.x - ext) / Cell); gx <= Mathf.FloorToInt((c.x + ext) / Cell); gx++)
                for (int gy = Mathf.FloorToInt((c.y - eyt) / Cell); gy <= Mathf.FloorToInt((c.y + eyt) / Cell); gy++)
                {
                    if (!grid.TryGetValue((gx, gy), out var l)) grid[(gx, gy)] = l = new List<R>();
                    l.Add(r);
                }
        }

        public bool Covered(Vector2 p, int self)
        {
            if (!grid.TryGetValue((Mathf.FloorToInt(p.x / Cell), Mathf.FloorToInt(p.y / Cell)), out var l)) return false;
            foreach (var r in l)
            {
                if (r.id == self) continue;
                var d = p - r.c;
                if (Mathf.Abs(Vector2.Dot(d, r.u)) <= r.hu && Mathf.Abs(Vector2.Dot(d, r.v)) <= r.hv) return true;
            }
            return false;
        }
    }

    static List<Placement> PlaceTubes(City city, List<BuildingVariant> lib, out int rows)
    {
        var res = new List<Placement>(city.lots.Length);
        rows = 0;
        var lots = city.lots;

        // what stands next to each side wall: other lots (any row, e.g. round a block corner) or big buildings
        var occ = new Occupancy();
        for (int k = 0; k < lots.Length; k++)
        {
            var l = lots[k];
            var f = new Vector2(l.front[0], l.front[1]);
            var t = new Vector2(-f.y, f.x);                              // viewer's right when facing the facade
            occ.Add(k, new Vector2(l.cx, l.cy) - f * (l.depth / 2f), t, l.width / 2f + 0.05f, f, l.depth / 2f);
        }
        foreach (var b in city.buildings)
        {
            var u = new Vector2(b.axis[0], b.axis[1]);
            occ.Add(-1, new Vector2(b.cx, b.cy), u, b.length / 2f, new Vector2(-u.y, u.x), b.width / 2f);
        }

        for (int i = 0; i < lots.Length;)
        {
            int j = i + 1;
            while (j < lots.Length && SameRow(lots[j - 1], lots[j])) j++;
            // lots along an edge are ordered along it, i.e. left -> right for a viewer facing the facades
            var row = new List<TubeHousePicker.Lot>(j - i);
            for (int k = i; k < j; k++)
            {
                var l = lots[k];
                var c = new Vector2(l.cx, l.cy);
                var f = new Vector2(l.front[0], l.front[1]);
                var t = new Vector2(-f.y, f.x);
                Vector2 Probe(float side) => c + t * side * (l.width / 2f + 0.8f) - f * 4f;   // 4 m behind the facade
                // the house need not fill the 12 m lot: 9..12 m deep uses the 9 m and 12 m buckets
                float h = (Hash(l.cx, l.cy) & 1023) / 1023f;
                row.Add(new TubeHousePicker.Lot
                {
                    depth = Mathf.Min(l.depth, 9f + 3f * h),
                    openLeft = !occ.Covered(Probe(-1f), k),
                    openRight = !occ.Covered(Probe(1f), k),
                });
            }
            var picks = TubeHousePicker.PickRow(lib, row, false, false, Hash(lots[i].cx, lots[i].cy));
            for (int k = i; k < j; k++)
            {
                var l = lots[k]; var c = picks[k - i];
                if (c.variant == null) continue;
                res.Add(new Placement
                {
                    key = LotKey(l.cx, l.cy), id = c.variant.variantId, variant = c.variant, seed = Hash(l.cx, l.cy),
                    pos = new Vector3(l.cx, 0f, l.cy),
                    rot = Quaternion.LookRotation(new Vector3(l.front[0], 0f, l.front[1])),    // facade = local +Z
                    scale = new Vector3(l.width / Mathf.Max(c.variant.frontage, 0.1f), 1f, c.depthScale),
                    exposed = c.exposedLeft || c.exposedRight,
                });
            }
            rows++;
            i = j;
        }
        return res;
    }

    // ------------------------------------------------------------------ big buildings
    class Tower { public BuildingVariant v; public Vector3 size, center; }

    static Tower Measure(BuildingVariant v)
    {
        var tmp = (GameObject)PrefabUtility.InstantiatePrefab(v.gameObject);
        tmp.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
        tmp.transform.localScale = Vector3.one;
        var rs = tmp.GetComponentsInChildren<Renderer>();
        var r = rs.FirstOrDefault(x => x.name.EndsWith("_LOD0")) ?? rs.First();
        var b = r.bounds;
        UnityEngine.Object.DestroyImmediate(tmp);
        return new Tower { v = v, size = b.size, center = b.center };
    }

    /// OSM gives no level count for most big buildings: guess a low-rise one from its area.
    static float Levels(Big b) => b.levels > 0 ? b.levels : b.area > 2500 ? 7 : b.area > 900 ? 5 : 4;

    static List<Placement> PlaceTowers(City city, List<Tower> towers)
    {
        var res = new List<Placement>();
        foreach (var b in city.buildings)
        {
            float lv = Levels(b);
            float jitter = (Hash(b.cx, b.cy) & 1023) / 1023f;
            // low / mid rise reads best as old housing blocks; tall ones choose freely by floor count
            var pool = lv <= 9 ? towers.Where(t => t.v.archetype.StartsWith("T3")).ToList() : towers;
            var t = pool.OrderBy(x => Mathf.Abs(Mathf.Log(lv / x.v.floors)) + 0.15f * Frac(jitter * 7.13f + x.v.floors * 0.37f)).First();
            float sy = Mathf.Clamp(lv / t.v.floors, 0.2f, 1.6f);
            float ax = b.axis[0], ay = b.axis[1];
            Quaternion rot; Vector3 scale;
            if (t.size.x >= t.size.z)
            {   // local X = long side
                rot = Quaternion.Euler(0f, Mathf.Atan2(-ay, ax) * Mathf.Rad2Deg, 0f);
                scale = new Vector3(b.length / t.size.x, sy, b.width / t.size.z);
            }
            else
            {   // local Z = long side
                rot = Quaternion.Euler(0f, Mathf.Atan2(ax, ay) * Mathf.Rad2Deg, 0f);
                scale = new Vector3(b.width / t.size.x, sy, b.length / t.size.z);
            }
            var target = new Vector3(b.cx, 0f, b.cy);
            var pos = target - rot * Vector3.Scale(scale, new Vector3(t.center.x, 0f, t.center.z));
            res.Add(new Placement { key = "B" + b.id, id = t.v.variantId, variant = t.v, pos = pos, rot = rot, scale = scale, seed = Hash(b.cx, b.cy) });
        }
        return res;
    }

    static float Frac(float x) => x - Mathf.Floor(x);

    // ------------------------------------------------------------------ ground meshes
    static void FlatMesh(Transform parent, string name, float[] tris, float y, Material mat)
    {
        if (tris == null || tris.Length < 6) return;
        int n = tris.Length / 6;
        var verts = new Vector3[n * 3];
        var uvs = new Vector2[n * 3];
        var idx = new int[n * 3];
        for (int t = 0; t < n; t++)
        {
            var a = new Vector3(tris[t * 6], y, tris[t * 6 + 1]);
            var b = new Vector3(tris[t * 6 + 2], y, tris[t * 6 + 3]);
            var c = new Vector3(tris[t * 6 + 4], y, tris[t * 6 + 5]);
            if (Vector3.Cross(b - a, c - a).y < 0) (b, c) = (c, b);          // face up
            verts[t * 3] = a; verts[t * 3 + 1] = b; verts[t * 3 + 2] = c;
            for (int k = 0; k < 3; k++)
            {
                var p = verts[t * 3 + k];
                uvs[t * 3 + k] = new Vector2(p.x / 4f, p.z / 4f);
                idx[t * 3 + k] = t * 3 + k;
            }
        }
        var mesh = new Mesh { name = name };
        if (verts.Length > 65000) mesh.indexFormat = IndexFormat.UInt32;
        mesh.vertices = verts; mesh.uv = uvs; mesh.triangles = idx;
        mesh.RecalculateNormals(); mesh.RecalculateBounds();
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        go.AddComponent<MeshFilter>().sharedMesh = mesh;
        var mr = go.AddComponent<MeshRenderer>();
        mr.sharedMaterial = mat;
        mr.shadowCastingMode = ShadowCastingMode.Off;
        GameObjectUtility.SetStaticEditorFlags(go, StaticEditorFlags.BatchingStatic);
    }

    static GameObject Root(Scene scene, string name)
    {
        var go = scene.GetRootGameObjects().FirstOrDefault(g => g.name == name);
        if (go == null) { go = new GameObject(name); SceneManager.MoveGameObjectToScene(go, scene); }
        return go;
    }

    // ------------------------------------------------------------------ run
    [MenuItem("Hanoi/City/Place City (all chunks)")]
    public static void Run()
    {
        var t0 = DateTime.Now;
        var city = LoadCity();
        foreach (var d in new[] { CityDir, ChunkDir })
            Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, d));

        var lib = AssetDatabase.FindAssets("t:Prefab", new[] { LibPrefabDir })
            .Select(g => AssetDatabase.LoadAssetAtPath<GameObject>(AssetDatabase.GUIDToAssetPath(g)))
            .Select(go => go != null ? go.GetComponent<BuildingVariant>() : null)
            .Where(v => v != null).ToList();
        var tubes = lib.Where(v => v.type == "tube").ToList();
        var towers = lib.Where(v => v.type == "tower").Select(Measure).ToList();
        if (tubes.Count == 0 || towers.Count == 0) { Debug.LogError("[City] library prefabs missing: run HanoiLibrary.ImportLibrary first"); return; }

        var st = city.street;
        if (st == null || st.profile == null) { Debug.LogError("[City] city.json has no 'street': run Map/osm_pipeline.py"); return; }
        var cross = new StreetBuilder.Cross { roadY = st.road_y, kerbH = st.kerb_h, stone = st.stone, profile = st.profile };

        var placements = PlaceTubes(city, tubes, out int rows);
        int nTubes = placements.Count, nExposed = placements.Count(p => p.exposed);
        placements.AddRange(PlaceTowers(city, towers));
        // every building stands at sidewalk height (its plinth reaches below the block ground)
        for (int i = 0; i < placements.Count; i++) { var pl = placements[i]; pl.pos.y += cross.WalkY; placements[i] = pl; }

        // group by chunk
        var g = city.chunk;
        var byChunk = placements.GroupBy(p => (
                Mathf.Clamp(Mathf.FloorToInt((p.pos.x - g.x0) / g.size), 0, g.nx - 1),
                Mathf.Clamp(Mathf.FloorToInt((p.pos.z - g.y0) / g.size), 0, g.ny - 1)))
            .ToDictionary(x => x.Key, x => x.ToList());

        // opening a scene unloads every asset nothing references (prefabs, materials, this record):
        // keep plain C# copies across the chunk loop and resolve assets again per chunk
        var record = AssetDatabase.LoadAssetAtPath<CityPlacement>(RecordPath);
        if (record == null) { record = ScriptableObject.CreateInstance<CityPlacement>(); AssetDatabase.CreateAsset(record, RecordPath); }
        var tomb = new HashSet<string>(record.tombstones);
        var prevKeys = record.placed.ToDictionary(c => c.chunk, c => c.keys.ToList());
        var newKeys = new Dictionary<string, List<string>>();
        Dictionary<string, Material> Mats() => new Dictionary<string, Material>
        {
            // chunk ground meshes have UV = metres / 4: tiling = 4 m / image size in metres
            // asphalt: one 1 m tile (UV = metres / 4 -> 4 repeats per UV unit) + 24 m brightness noise as detail map
            ["road"] = HanoiSetup.GroundMaterial("M_Asphalt", 0.12f, "Ground/road.png", new Vector2(4f, 4f),
                                                 "Ground/road_n.png", 0.9f, "Ground/road_macro.png", new Vector2(1f / 6f, 1f / 6f)),
            ["sidewalk"] = HanoiSetup.LitMaterial("M_Sidewalk", new Color(0.50f, 0.48f, 0.45f), 0.15f, "Ground/sidewalk.png", new Vector2(1.6f, 1.6f)),
            // kerb UV: u = metres / 4 (4 stones), v = arc / StreetBuilder.TexV (kerb.png = 4 stones x 0.5 m)
            ["kerb"] = HanoiSetup.GroundMaterial("M_Kerb", 0.15f, "Ground/kerb.png", Vector2.one, "Ground/kerb_n.png", 0.7f),
            ["green"] = HanoiSetup.LitMaterial("M_Green", new Color(0.22f, 0.32f, 0.16f), 0.05f),
            ["water"] = HanoiSetup.LitMaterial("M_Water", new Color(0.12f, 0.20f, 0.22f), 0.85f),
        };

        var main = new List<CityChunks.Chunk>();
        int kept = 0, newTombs = 0, placedTotal = 0, treesTotal = 0, motosTotal = 0, propsTotal = 0;
        foreach (var c in city.chunks)
        {
            string name = ChunkName(c.ix, c.iy);
            string path = $"{ChunkDir}/{name}.unity";
            bool existed = File.Exists(Path.Combine(HanoiSetup.ProjectDir, path));
            byChunk.TryGetValue((c.ix, c.iy), out var mine);
            mine ??= new List<Placement>();
            bool hasGround = new[] { c.road, c.sidewalk, c.green, c.water, c.kerb, c.tree, c.moto, c.prop }.Any(a => a != null && a.Length > 0);
            if (!existed && mine.Count == 0 && !hasGround) continue;

            var scene = existed ? EditorSceneManager.OpenScene(path, OpenSceneMode.Single)
                                : EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var bRoot = Root(scene, "Buildings").transform;
            var gRoot = Root(scene, "Ground").transform;

            // keep locked + hand-added buildings, drop the rest; tombstone what the user deleted
            var keep = new HashSet<string>();
            var present = new HashSet<string>();
            foreach (var t in bRoot.Cast<Transform>().ToArray())
            {
                var pb = t.GetComponent<PlacedBuilding>();
                if (pb == null) continue;
                present.Add(pb.lotKey);
                if (pb.locked) { keep.Add(pb.lotKey); kept++; }
                else UnityEngine.Object.DestroyImmediate(t.gameObject);
            }
            if (prevKeys.TryGetValue(name, out var prev))
                foreach (var k in prev)
                    if (!present.Contains(k) && tomb.Add(k)) newTombs++;
            var mats = Mats();

            foreach (var t in gRoot.Cast<Transform>().ToArray())
                UnityEngine.Object.DestroyImmediate(t.gameObject);
            FlatMesh(gRoot, name + "_Road", c.road, cross.roadY, mats["road"]);
            StreetBuilder.Build(gRoot, name, new StreetBuilder.Data
            {
                top = c.sidewalk, kerb = c.kerb, kerbS = c.kerb_s, kerbN = c.kerb_n, skirt = c.skirt, skirtN = c.skirt_n, bounds = c.bounds,
            }, cross, mats["sidewalk"], mats["kerb"]);
            FlatMesh(gRoot, name + "_Green", c.green, 0.04f, mats["green"]);
            FlatMesh(gRoot, name + "_Water", c.water, 0.00f, mats["water"]);

            // opening a scene unloads unused assets: resolve prefabs again for every chunk
            var prefabs = new Dictionary<string, GameObject>();
            foreach (var p in mine)
            {
                if (keep.Contains(p.key) || tomb.Contains(p.key)) continue;
                string vid = p.id;
                if (!prefabs.TryGetValue(vid, out var prefab))
                    prefabs[vid] = prefab = AssetDatabase.LoadAssetAtPath<GameObject>($"{LibPrefabDir}/{vid}.prefab");
                var go = (GameObject)PrefabUtility.InstantiatePrefab(prefab, bRoot);
                go.name = $"{vid}_{p.key}";
                go.transform.SetPositionAndRotation(p.pos, p.rot);
                go.transform.localScale = p.scale;
                var pb = go.AddComponent<PlacedBuilding>();
                pb.variantId = vid; pb.lotKey = p.key; pb.seed = p.seed;
            }
            newKeys[name] = bRoot.GetComponentsInChildren<PlacedBuilding>().Select(x => x.lotKey).ToList();
            placedTotal += bRoot.childCount;
            treesTotal += PlaceTrees(scene, c.tree, cross.WalkY);
            motosTotal += PlaceMotos(scene, c.moto, cross.WalkY, c.ix * 1000 + c.iy);
            propsTotal += PlaceProps(scene, c.prop, cross.WalkY);
            EditorSceneManager.SaveScene(scene, path);
            main.Add(new CityChunks.Chunk
            {
                ix = c.ix, iy = c.iy, scenePath = path, buildings = bRoot.childCount,
                boundsXZ = Rect.MinMaxRect(c.bounds[0], c.bounds[1], c.bounds[2], c.bounds[3]),
            });
        }
        record = AssetDatabase.LoadAssetAtPath<CityPlacement>(RecordPath);
        record.tombstones = tomb.ToList();
        record.placed = newKeys.Select(kv => new CityPlacement.ChunkKeys { chunk = kv.Key, keys = kv.Value }).ToList();
        EditorUtility.SetDirty(record);
        AssetDatabase.SaveAssets();

        BuildMainScene(g, main);

        // neighbour check: identical variants side by side in a row
        int same = 0;
        for (int i = 1; i < nTubes; i++)
            if (placements[i].id == placements[i - 1].id &&
                Vector3.Distance(placements[i].pos, placements[i - 1].pos) < 6f) same++;
        Debug.Log($"[City] {nTubes} tube houses in {rows} rows ({nExposed} with exposed side walls), " +
                  $"{placements.Count - nTubes} big buildings, {main.Count} chunk scenes, {placedTotal} objects in scenes; " +
                  $"kept locked {kept}, tombstones {tomb.Count} (+{newTombs}); identical neighbours {same}; {treesTotal} trees; " +
                  $"{motosTotal} parked bikes; {propsTotal} street props; " +
                  $"{(DateTime.Now - t0).TotalSeconds:F0} s");
        Debug.Log("[City] tube variants used: " + string.Join(", ",
            placements.Take(nTubes).GroupBy(p => p.id).OrderByDescending(x => x.Count()).Take(8)
                .Select(x => $"{x.Key}={x.Count()}")) + $" ... ({placements.Take(nTubes).Select(p => p.id).Distinct().Count()} distinct)");
    }

    /// Street / park trees of a chunk under the root "Trees" (rebuilt every run; edit the layout in QGIS
    /// with op "tree" overrides). Trees put by hand go under "TreesManual", which is never touched.
    static int PlaceTrees(Scene scene, float[] t, float walkY)
    {
        var root = Root(scene, "Trees").transform;
        Root(scene, "TreesManual");
        foreach (var ch in root.Cast<Transform>().ToArray())
            UnityEngine.Object.DestroyImmediate(ch.gameObject);
        if (t == null || t.Length == 0) return 0;
        // opening a scene unloads unused assets: resolve the prefabs again for every chunk
        var prefabs = HanoiTrees.SpeciesIds.Select(HanoiTrees.LoadPrefab).ToArray();
        int n = 0;
        for (int i = 0; i + 5 < t.Length; i += 6)
        {
            int sp = (int)t[i + 2], kind = (int)t[i + 5];
            var prefab = sp >= 0 && sp < prefabs.Length ? prefabs[sp] : null;
            if (prefab == null) continue;
            var go = (GameObject)PrefabUtility.InstantiatePrefab(prefab, root);
            go.name = $"{HanoiTrees.SpeciesIds[sp]}_{n:000}";
            // street trees stand on the sidewalk top, park trees on the green (FlatMesh at 0.04 m)
            float y = kind == 1 ? 0.04f : walkY;
            go.transform.SetPositionAndRotation(new Vector3(t[i], y, t[i + 1]), Quaternion.Euler(0f, t[i + 3], 0f));
            go.transform.localScale = Vector3.one * t[i + 4];
            n++;
        }
        return n;
    }

    /// Parked bikes of a chunk under the root "Motos" (rebuilt every run; QGIS overrides with op "moto"),
    /// a random paint colour each (seeded by chunk, so a re-run gives the same colours). Bikes put by
    /// hand go under "MotosManual", never touched. Not part of the HLOD (culled past ~90 m).
    static int PlaceMotos(Scene scene, float[] m, float walkY, int seed)
    {
        var root = Root(scene, "Motos").transform;
        Root(scene, "MotosManual");
        foreach (var ch in root.Cast<Transform>().ToArray())
            UnityEngine.Object.DestroyImmediate(ch.gameObject);
        if (m == null || m.Length == 0) return 0;
        var prefabs = Enumerable.Range(0, HanoiMotos.Paints.Length).Select(HanoiMotos.LoadParked).ToArray();
        if (prefabs.Any(p => p == null)) { Debug.LogWarning("[City] moto prefabs missing: run Hanoi/Motos/Import Motos"); return 0; }
        var rng = new System.Random(seed);
        int n = 0;
        for (int i = 0; i + 2 < m.Length; i += 3)
        {
            var go = (GameObject)PrefabUtility.InstantiatePrefab(prefabs[HanoiMotos.PickPaint(rng.NextDouble())], root);
            go.name = $"Moto_{n:000}";
            go.transform.SetPositionAndRotation(new Vector3(m[i], walkY, m[i + 1]), Quaternion.Euler(0f, m[i + 2], 0f));
            n++;
        }
        return n;
    }

    /// Street props of a chunk (signs at sidewalk corners, power poles, garbage carts) under the root
    /// "Props" (rebuilt every run; QGIS overrides with op "prop"). Props put by hand go under
    /// "PropsManual", never touched. Not part of the HLOD (LODGroups cull them at distance).
    static int PlaceProps(Scene scene, float[] p, float walkY)
    {
        var root = Root(scene, "Props").transform;
        Root(scene, "PropsManual");
        foreach (var ch in root.Cast<Transform>().ToArray())
            UnityEngine.Object.DestroyImmediate(ch.gameObject);
        if (p == null || p.Length == 0) return 0;
        var prefabs = Enumerable.Range(0, HanoiProps.Ids.Length).Select(HanoiProps.LoadPrefab).ToArray();
        if (prefabs.Any(x => x == null)) { Debug.LogWarning("[City] prop prefabs missing: run Hanoi/Props/Import Props"); return 0; }
        int n = 0;
        for (int i = 0; i + 3 < p.Length; i += 4)
        {
            int kind = (int)p[i + 2];
            if (kind < 0 || kind >= prefabs.Length) continue;
            var go = (GameObject)PrefabUtility.InstantiatePrefab(prefabs[kind], root);
            go.name = $"{HanoiProps.Ids[kind]}_{n:000}";
            go.transform.SetPositionAndRotation(new Vector3(p[i], walkY, p[i + 1]), Quaternion.Euler(0f, p[i + 3], 0f));
            n++;
        }
        return n;
    }

    static void BuildMainScene(Grid g, List<CityChunks.Chunk> chunks)
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
        HanoiLighting.Apply();
        var cam = Camera.main;
        cam.farClipPlane = 5000f; cam.nearClipPlane = 0.2f; cam.fieldOfView = 60f;
        float w = g.nx * g.size, h = g.ny * g.size;
        // the cube's top face maps UV 0..1 over the whole slab: repeat the ground image every 8 m
        // own material per city: its tiling depends on the map size
        var groundMat = HanoiSetup.LitMaterial(CityTarget.BlockGroundMat, new Color(0.36f, 0.35f, 0.33f), 0.1f,
            "Ground/block_ground.png", new Vector2((w + 400f) / 8f, (h + 400f) / 8f));
        HanoiSetup.Box("BlockGround", new Vector3(g.x0 + w / 2f, -0.06f, g.y0 + h / 2f), new Vector3(w + 400f, 0.1f, h + 400f), groundMat);
        var reg = new GameObject("CityChunks").AddComponent<CityChunks>();
        reg.chunkSize = g.size;
        reg.chunks = chunks;
        reg.loadMetro = CityTarget.IsMain;           // the metro scene is laid out on the main map
        reg.gameObject.AddComponent<ChunkStreamer>();
        EditorSceneManager.SaveScene(scene, MainScene);
        HanoiLighting.BakeEnvironment();
        EditorSceneManager.SaveScene(scene, MainScene);

        // build settings: main scene first, then every chunk (needed to stream them in a player build);
        // a test area never replaces the main map there
        if (!CityTarget.IsMain) return;
        EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(MainScene, true) }
            .Concat(chunks.Select(c => new EditorBuildSettingsScene(c.scenePath, true)))
            .Concat(File.Exists(Path.Combine(HanoiSetup.ProjectDir, MetroBuilder.ScenePath))
                ? new[] { new EditorBuildSettingsScene(MetroBuilder.ScenePath, true) } : new EditorBuildSettingsScene[0]).ToArray();
    }

    // ------------------------------------------------------------------ viewing
    [MenuItem("Hanoi/City/Open Main + All Chunks")]
    public static void OpenAll()
    {
        EditorSceneManager.OpenScene(MainScene, OpenSceneMode.Single);
        var reg = UnityEngine.Object.FindFirstObjectByType<CityChunks>();
        foreach (var c in reg.chunks)
            EditorSceneManager.OpenScene(c.scenePath, OpenSceneMode.Additive);
        if (CityTarget.IsMain && File.Exists(Path.Combine(HanoiSetup.ProjectDir, MetroBuilder.ScenePath)))      // elevated metro (own scene)
            EditorSceneManager.OpenScene(MetroBuilder.ScenePath, OpenSceneMode.Additive);
        reg.SyncHlod();                      // chunk loaded -> its HLOD is hidden (CityChunks.Update keeps it so)
    }

    public static void Shots()
    {
        OpenAll();
        EditorSettings.asyncShaderCompilation = false;
        var city = LoadCity();
        var cam = Camera.main;
        // a dense street (chunk 10,4 has the most lots) and the Royal City towers
        var focus = new Vector2(820f, 16f);
        var lot = city.lots.OrderBy(l => (new Vector2(l.cx, l.cy) - focus).sqrMagnitude).First();
        var p = new Vector3(lot.cx, 0f, lot.cy);
        var f = new Vector3(lot.front[0], 0f, lot.front[1]);
        var right = new Vector3(-f.z, 0f, f.x);
        HanoiSetup.Shot(cam, "m3_1_street", p + f * 5f + Vector3.up * 1.7f - right * 12f, p + right * 25f + Vector3.up * 6f + f * 1f);
        HanoiSetup.Shot(cam, "m3_2_drone", p + f * 70f + Vector3.up * 80f - right * 60f, p);
        var r5 = city.buildings.FirstOrDefault(b => b.name == "R5") ?? city.buildings[0];
        var t = new Vector3(r5.cx, 30f, r5.cy);
        HanoiSetup.Shot(cam, "m3_3_towers", t + new Vector3(-380f, 160f, -380f), t);
        HanoiSetup.Shot(cam, "m3_4_overview", new Vector3(-1100f, 1100f, -1500f), new Vector3(0f, 0f, 0f));
        Debug.Log($"[City] shots: street at lot ({lot.cx}, {lot.cy}), towers at {r5.name}");
    }

    public static void RunBatch()
    {
        Run();
        Shots();
    }

    /// Nguyễn Trãi under metro 2A (corridor between the two carriageways): drone, eye level, far HLOD.
    public static void MetroShots()
    {
        OpenAll();
        EditorSettings.asyncShaderCompilation = false;
        var cam = Camera.main;
        var a = new Vector3(-863f, 0f, -446f);          // two points on the viaduct centreline (city.json rails)
        var b = new Vector3(22f, 0f, 195f);
        var dir = (b - a).normalized;
        var p = Vector3.Lerp(a, b, 0.25f);
        HanoiSetup.Shot(cam, "r1_1_drone", p - dir * 90f + Vector3.up * 55f, p + dir * 120f);
        HanoiSetup.Shot(cam, "r1_2_street", p + Vector3.up * 1.7f, p + dir * 100f + Vector3.up * 3f);
        EditorSceneManager.OpenScene(MainScene, OpenSceneMode.Single);      // HLOD only
        HanoiSetup.Shot(Camera.main, "r1_3_hlod", p - dir * 300f + Vector3.up * 220f, p + dir * 150f);
    }

    /// Raised sidewalk + kerb checks: junction from above, eye level, close-up on the kerb, Nguyen Trai under the metro.
    public static void StreetShots()
    {
        OpenAll();
        EditorSettings.asyncShaderCompilation = false;
        var cam = Camera.main;
        var j = new Vector3(-641f, 0.22f, 294f);              // junction of report_kerb_0.png
        HanoiSetup.Shot(cam, "s2_1_junction_top", j + new Vector3(0f, 60f, -1f), j);
        HanoiSetup.Shot(cam, "s2_2_eye", new Vector3(-626f, 1.7f, 284f), new Vector3(-650f, 1.2f, 298f));
        HanoiSetup.Shot(cam, "s2_3_kerb_close", new Vector3(-646f, 1.0f, 291f), new Vector3(-652f, 0.1f, 298f));
        var n = new Vector3(-381f, 0.22f, -69f);              // Nguyen Trai x metro (report_kerb_1.png)
        HanoiSetup.Shot(cam, "s2_4_nguyentrai", n + new Vector3(30f, 25f, 40f), n);
        HanoiSetup.Shot(cam, "s2_5_nguyentrai_eye", n + new Vector3(18f, 1.7f, 22f), n + new Vector3(-12f, 1.5f, -8f));
    }

    public static void RunStreetBatch()
    {
        Run();
        StreetShots();
    }

    /// Re-run check: lock + move one house, delete another, place again -> both edits survive.
    public static void RunLockTest()
    {
        string path = $"{ChunkDir}/{ChunkName(10, 4)}.unity";
        var scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Single);
        var houses = Root(scene, "Buildings").GetComponentsInChildren<PlacedBuilding>();
        var moved = houses[0]; var deleted = houses[1];
        moved.locked = true;
        moved.transform.position += new Vector3(0f, 5f, 0f);
        string movedKey = moved.lotKey, deletedKey = deleted.lotKey;
        Vector3 movedPos = moved.transform.position;
        UnityEngine.Object.DestroyImmediate(deleted.gameObject);
        EditorSceneManager.SaveScene(scene);

        Run();

        scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Single);
        var after = Root(scene, "Buildings").GetComponentsInChildren<PlacedBuilding>();
        var m = after.FirstOrDefault(x => x.lotKey == movedKey);
        bool okMoved = m != null && m.locked && Vector3.Distance(m.transform.position, movedPos) < 0.01f;
        bool okDeleted = after.All(x => x.lotKey != deletedKey);
        Debug.Log($"[City] lock test: locked house kept at its edited position = {okMoved}, deleted lot stays empty = {okDeleted}");

        // undo the test edits: unlock + restore, forget the tombstone, place again
        if (m != null) { m.locked = false; EditorSceneManager.SaveScene(scene); }
        var record = AssetDatabase.LoadAssetAtPath<CityPlacement>(RecordPath);
        record.tombstones.Remove(deletedKey);
        EditorUtility.SetDirty(record);
        AssetDatabase.SaveAssets();
        Run();
    }
}
