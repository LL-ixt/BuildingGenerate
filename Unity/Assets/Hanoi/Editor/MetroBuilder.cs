using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Unity.Mathematics;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;
using UnityEngine.Splines;
using LinePath = MetroPath;

/// <summary>
/// METRO V2: builds the elevated viaduct of a MetroLine (Runtime/MetroLine.cs) from the Blender kit
/// (Export/Metro: SM_MetroPier.fbx + metro.json, Blender/scripts/build_metro.py).
///  - Deck: every closed (x, y) profile of metro.json is swept along the spline (knots = rail top);
///    rings only where the line turns (> 0.75 deg) or every 15 m, so straights stay cheap. Pieces of
///    3 spans, each a LODGroup (LOD0 everything + barrier posts, LOD1 no rails / troughs, LOD2 one
///    U shell). Station zones leave a gap with capped ends. Meshes: Assets/Hanoi/Metro/Generated.
///  - Piers: spread evenly (~span m, one at each line end), slid along the line into the median
///    zones copied from city.json (not in junctions), MetroLine.pierOverrides last. The column is
///    stretched and the cap moved so the cap carries the girder at the spline height.
/// Scene Assets/Hanoi/Metro/Metro.unity (additive next to the city: CityPlacer.OpenAll, ChunkStreamer).
/// Menu "Hanoi/Metro/..." or batch -executeMethod MetroBuilder.RunBatch (Editor closed).
/// </summary>
[InitializeOnLoad]
public static class MetroBuilder
{
    const string Root = "Assets/Hanoi/Metro";
    const string ModelsDir = Root + "/Models";
    const string GenDir = Root + "/Generated";
    public const string ScenePath = Root + "/Metro.unity";
    const string PierPrefabPath = Root + "/SM_MetroPier.prefab";
    static readonly float[] PierLod = { 0.10f, 0.004f };              // 12 m pier: LOD1 past ~150 m, culled ~4 km
    static readonly float[] DeckLod = { 0.30f, 0.07f, 0.002f };       // ~90 m pieces
    const int PiersPerPiece = 3;
    const string ShotTag = "p1";                                        // Unity_logs/shots/metro_<tag>_*.png
    const float RingTurnDeg = 0.75f, RingMaxGap = 15f;

    static string ExportDir => Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, "../Export/Metro"));
    static string CityJson => Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, "../Map/out/city.json"));
    static string Abs(string assetPath) => Path.Combine(HanoiSetup.ProjectDir, assetPath);

    static MetroBuilder() { MetroLine.RebuildRequested = l => Rebuild(l); }

    // ------------------------------------------------------------------ metro.json / city.json
    [Serializable] class PostJ { public float step, w, d, x, y0, y1; public string mat; public int[] lods; }
    [Serializable] class UvJ { public string mode; public float u_len, u_off; }
    [Serializable] class ProfileJ { public string name, mat; public int[] lods; public bool closed; public float[] pts; public UvJ uv; }
    [Serializable] class MatJ { public string name, tex, normal; public float[] color, tint; public float roughness, metallic; }
    [Serializable] class FootJ { public float w, d; }
    [Serializable] class PlanterJ { public float w, t, h, soil; public ProfileJ[] profiles; }
    [Serializable] class ShrubJ { public int variants; public float step, row; public float[] scale; }
    [Serializable]
    class MetroJ
    {
        public float rail_top, deck_top, girder_bottom, cap_top, cap_bottom, column_default_top, track_spacing, gauge, span, half_width;
        public PostJ post; public MatJ[] materials; public ProfileJ[] profiles;
        public FootJ footing; public PlanterJ planter; public ShrubJ shrub;
    }
    [Serializable] class RailJ { public string name; public float[] line; }
    [Serializable] class RingJ { public float[] ring; }
    [Serializable] class CityRailsJ { public float[] bounds; public RailJ[] rails; public RingJ[] medians; }

    static MetroJ LoadSpec() => JsonUtility.FromJson<MetroJ>(File.ReadAllText(Path.Combine(ExportDir, "metro.json")));

    static Dictionary<string, Material> Materials(MetroJ spec, bool refresh)
    {
        var d = new Dictionary<string, Material>();
        foreach (var m in spec.materials)
        {
            var mat = AssetDatabase.LoadAssetAtPath<Material>($"Assets/Hanoi/Materials/{m.name}.mat");
            if (mat == null || refresh)
            {
                bool textured = !string.IsNullOrEmpty(m.tex) &&
                                File.Exists(Path.Combine(HanoiSetup.ExportTexDir, "Metro", m.tex));
                if (textured)
                {
                    // V3: Export/Textures/Metro (build_metro_texture.py); UVs are already in texture units
                    mat = HanoiSetup.GroundMaterial(m.name, 1f - m.roughness, "Metro/" + m.tex, Vector2.one,
                                                    string.IsNullOrEmpty(m.normal) ? null : "Metro/" + m.normal, 1f);
                    var t = m.tint != null && m.tint.Length == 3 ? new Color(m.tint[0], m.tint[1], m.tint[2]).gamma : Color.white;
                    mat.SetColor("_BaseColor", t);
                }
                else    // flat colour (json colours are linear)
                {
                    mat = HanoiSetup.LitMaterial(m.name, new Color(m.color[0], m.color[1], m.color[2]).gamma, 1f - m.roughness);
                    mat.SetTexture("_BaseMap", null);
                    mat.SetColor("_BaseColor", new Color(m.color[0], m.color[1], m.color[2]).gamma);
                }
                mat.SetFloat("_Metallic", m.metallic);
                EditorUtility.SetDirty(mat);
            }
            d[m.name] = mat;
        }
        AssetDatabase.SaveAssets();
        return d;
    }

    // ------------------------------------------------------------------ pier prefab
    [MenuItem("Hanoi/Metro/Import Pier")]
    public static void ImportPier()
    {
        Directory.CreateDirectory(Abs(ModelsDir));
        var spec = LoadSpec();
        var mats = Materials(spec, refresh: true);
        string path = $"{ModelsDir}/SM_MetroPier.fbx";
        File.Copy(Path.Combine(ExportDir, "FBX", "SM_MetroPier.fbx"), Abs(path), true);
        AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
        var imp = (ModelImporter)AssetImporter.GetAtPath(path);
        imp.importNormals = ModelImporterNormals.Import;
        imp.importTangents = ModelImporterTangents.None;
        imp.importAnimation = false; imp.importCameras = false; imp.importLights = false;
        imp.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
        foreach (var kv in mats)
            imp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), kv.Key), kv.Value);
        imp.SaveAndReimport();

        var go = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(path));
        go.name = "SM_MetroPier";
        var lg = HanoiSetup.SetupLods(go, PierLod);
        foreach (var r in go.GetComponentsInChildren<Renderer>()) r.shadowCastingMode = ShadowCastingMode.On;
        var tris = string.Join(", ", lg.GetLODs().Select((l, i) =>
            $"LOD{i} {l.renderers.Sum(r => r.GetComponent<MeshFilter>().sharedMesh.triangles.Length / 3)}"));
        var col = go.GetComponentsInChildren<Transform>().First(t => t.name.EndsWith("_Column_LOD0"));
        Debug.Log($"[Metro] pier prefab: {lg.lodCount} LODs ({tris}), size {lg.size:F1} m, column rot {col.rotation.eulerAngles}, " +
                  $"mats {string.Join("/", go.GetComponentsInChildren<Renderer>().SelectMany(r => r.sharedMaterials).Select(m => m ? m.name : "null").Distinct())}");
        PrefabUtility.SaveAsPrefabAsset(go, PierPrefabPath);
        UnityEngine.Object.DestroyImmediate(go);
        AssetDatabase.SaveAssets();
        ImportShrubs();
    }

    const string ShrubFbx = ModelsDir + "/SM_MetroShrub.fbx";

    /// P1: shrub clumps (Blender build_metro.py --export): LOD0 leaf cards on the tree leaf atlas
    /// (M_Foliage), LOD1 blob (M_FoliageBlob); MetroBuilder merges them per planter.
    public static void ImportShrubs()
    {
        string src = Path.Combine(ExportDir, "FBX", "SM_MetroShrub.fbx");
        if (!File.Exists(src)) return;
        File.Copy(src, Abs(ShrubFbx), true);
        AssetDatabase.ImportAsset(ShrubFbx, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
        var imp = (ModelImporter)AssetImporter.GetAtPath(ShrubFbx);
        imp.importNormals = ModelImporterNormals.Import;
        imp.importTangents = ModelImporterTangents.None;
        imp.importAnimation = false; imp.importCameras = false; imp.importLights = false;
        imp.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
        imp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "M_Foliage"), HanoiTrees.Foliage());
        imp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "M_FoliageBlob"), HanoiTrees.FoliageBlob());
        imp.SaveAndReimport();
        Debug.Log($"[Metro] shrubs imported: {string.Join(", ", ShrubMeshes(out _).Select(m => $"{m.name} {m.vertexCount} v"))}");
    }

    /// Shrub meshes [variant * 2 + lod] from the imported FBX (looked up by node name).
    static List<Mesh> ShrubMeshes(out int variants)
    {
        var res = new List<Mesh>();
        variants = 0;
        var model = AssetDatabase.LoadAssetAtPath<GameObject>(ShrubFbx);
        if (model == null) return res;
        var mfs = model.GetComponentsInChildren<MeshFilter>(true);
        for (int v = 0; ; v++)
        {
            var m0 = mfs.FirstOrDefault(f => f.name == $"SM_MetroShrub_{v}_LOD0");
            var m1 = mfs.FirstOrDefault(f => f.name == $"SM_MetroShrub_{v}_LOD1");
            if (m0 == null || m1 == null) break;
            res.Add(m0.sharedMesh); res.Add(m1.sharedMesh);
            variants++;
        }
        return res;
    }

    // ------------------------------------------------------------------ scene
    /// The MetroLine of Metro.unity: already loaded (e.g. next to the city) or opened / created.
    static MetroLine OpenLine()
    {
        var sc = SceneManager.GetSceneByPath(ScenePath);
        if (!sc.IsValid() || !sc.isLoaded)
        {
            if (File.Exists(Abs(ScenePath)))
                sc = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            else
            {
                Directory.CreateDirectory(Abs(Root));
                sc = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
                var go = new GameObject("MetroLine");
                go.AddComponent<MetroLine>();
                EditorSceneManager.SaveScene(sc, ScenePath);
            }
        }
        var line = sc.GetRootGameObjects().Select(g => g.GetComponentInChildren<MetroLine>()).FirstOrDefault(l => l != null);
        if (line == null)
        {
            var go = new GameObject("MetroLine");
            SceneManager.MoveGameObjectToScene(go, sc);
            line = go.AddComponent<MetroLine>();
        }
        return line;
    }

    static void AddToBuildSettings()
    {
        var list = EditorBuildSettings.scenes.ToList();
        if (list.Any(s => s.path == ScenePath)) return;
        list.Add(new EditorBuildSettingsScene(ScenePath, true));
        EditorBuildSettings.scenes = list.ToArray();
    }

    [MenuItem("Hanoi/Metro/Open Metro Scene (additive)")]
    public static void OpenAdditive()
    {
        if (!File.Exists(Abs(ScenePath))) { OpenLine(); return; }
        EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Additive);
    }

    // ------------------------------------------------------------------ seed from city.json
    [MenuItem("Hanoi/Metro/Seed Spline From City (overwrites the spline)")]
    public static void SeedMenu()
    {
        var line = OpenLine();
        if (line.Container.Spline != null && line.Container.Spline.Count > 1 &&
            !EditorUtility.DisplayDialog("Metro", "Replace the current (hand-edited) spline with the city.json line?", "Replace", "Cancel"))
            return;
        Seed(line);
        Rebuild(line);
        EditorSceneManager.SaveScene(line.gameObject.scene);
    }

    static void Seed(MetroLine line)
    {
        var spec = LoadSpec();
        var city = JsonUtility.FromJson<CityRailsJ>(File.ReadAllText(CityJson));
        var rail = city.rails.OrderByDescending(r => PolyLength(Flat(r.line))).First();
        var b = city.bounds;
        var pts = ClipToRect(Flat(rail.line), new Rect(b[0] + 10f, b[1] + 10f, b[2] - b[0] - 20f, b[3] - b[1] - 20f));
        pts = DouglasPeucker(pts, 1.5f);
        var spline = new Spline();
        foreach (var p in pts)
            spline.Add(new BezierKnot(new float3(p.x, spec.rail_top, p.y)), TangentMode.AutoSmooth);
        line.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
        line.transform.localScale = Vector3.one;
        line.Container.Spline = spline;
        line.span = spec.span;
        line.medianZones = (city.medians ?? new RingJ[0]).Select(m => new MetroLine.Ring { pts = Flat(m.ring) }).ToList();
        EditorUtility.SetDirty(line);
        EditorUtility.SetDirty(line.Container);
        Debug.Log($"[Metro] seeded '{rail.name}': {pts.Count} knots, {PolyLength(pts):F0} m, {line.medianZones.Count} median zones");
    }

    static List<Vector2> Flat(float[] f)
    {
        var l = new List<Vector2>(f.Length / 2);
        for (int i = 0; i + 1 < f.Length; i += 2) l.Add(new Vector2(f[i], f[i + 1]));
        return l;
    }

    static float PolyLength(List<Vector2> p)
    {
        float s = 0f;
        for (int i = 1; i < p.Count; i++) s += Vector2.Distance(p[i - 1], p[i]);
        return s;
    }

    /// Longest run of the polyline inside the rectangle (entry / exit points interpolated).
    static List<Vector2> ClipToRect(List<Vector2> p, Rect r)
    {
        List<Vector2> best = new List<Vector2>(), cur = new List<Vector2>();
        Vector2 Cross(Vector2 a, Vector2 b)        // a inside, b outside: point on the border
        {
            float lo = 0f, hi = 1f;
            for (int k = 0; k < 30; k++) { float m = (lo + hi) / 2; if (r.Contains(Vector2.Lerp(a, b, m))) lo = m; else hi = m; }
            return Vector2.Lerp(a, b, lo);
        }
        for (int i = 0; i < p.Count; i++)
        {
            bool inside = r.Contains(p[i]);
            if (inside)
            {
                if (cur.Count == 0 && i > 0) cur.Add(Cross(p[i], p[i - 1]));
                cur.Add(p[i]);
            }
            else if (cur.Count > 0)
            {
                cur.Add(Cross(p[i - 1], p[i]));
                if (PolyLength(cur) > PolyLength(best)) best = cur;
                cur = new List<Vector2>();
            }
        }
        if (PolyLength(cur) > PolyLength(best)) best = cur;
        return best;
    }

    static List<Vector2> DouglasPeucker(List<Vector2> p, float tol)
    {
        if (p.Count < 3) return p;
        var keep = new bool[p.Count];
        keep[0] = keep[p.Count - 1] = true;
        var stack = new Stack<(int, int)>();
        stack.Push((0, p.Count - 1));
        while (stack.Count > 0)
        {
            var (a, b) = stack.Pop();
            float dmax = 0f; int idx = -1;
            for (int i = a + 1; i < b; i++)
            {
                float d = SegDist(p[i], p[a], p[b]);
                if (d > dmax) { dmax = d; idx = i; }
            }
            if (idx >= 0 && dmax > tol) { keep[idx] = true; stack.Push((a, idx)); stack.Push((idx, b)); }
        }
        return p.Where((_, i) => keep[i]).ToList();
    }

    static float SegDist(Vector2 q, Vector2 a, Vector2 b)
    {
        var ab = b - a;
        float t = ab.sqrMagnitude < 1e-9f ? 0f : Mathf.Clamp01(Vector2.Dot(q - a, ab) / ab.sqrMagnitude);
        return Vector2.Distance(q, a + ab * t);
    }

    static bool InRing(Vector2 q, List<Vector2> r)
    {
        bool c = false;
        for (int i = 0, j = r.Count - 1; i < r.Count; j = i++)
            if ((r[i].y > q.y) != (r[j].y > q.y) && q.x < (r[j].x - r[i].x) * (q.y - r[i].y) / (r[j].y - r[i].y) + r[i].x)
                c = !c;
        return c;
    }

    static float RingDist(Vector2 q, List<Vector2> r)
    {
        float d = float.MaxValue;
        for (int i = 0, j = r.Count - 1; i < r.Count; j = i++) d = Mathf.Min(d, SegDist(q, r[j], r[i]));
        return d;
    }

    // ------------------------------------------------------------------ mesh accumulator
    class Acc
    {
        public readonly List<Vector3> v = new List<Vector3>();
        public readonly List<Vector3> n = new List<Vector3>();
        public readonly List<Vector2> uv = new List<Vector2>();
        public readonly SortedDictionary<string, List<int>> tri = new SortedDictionary<string, List<int>>();

        public int V(Vector3 pos, Vector3 nrm, Vector2 u) { v.Add(pos); n.Add(nrm); uv.Add(u); return v.Count - 1; }

        /// Triangle whose winding is fixed so that its face normal agrees with `want`.
        public void Tri(string mat, int a, int b, int c, Vector3 want)
        {
            if (!tri.TryGetValue(mat, out var l)) tri[mat] = l = new List<int>();
            if (Vector3.Dot(Vector3.Cross(v[b] - v[a], v[c] - v[a]), want) < 0f) (b, c) = (c, b);
            l.Add(a); l.Add(b); l.Add(c);
        }

        public Mesh Build(string name, Dictionary<string, Material> mats, out Material[] used)
        {
            var m = new Mesh { name = name };
            if (v.Count > 65000) m.indexFormat = IndexFormat.UInt32;
            m.SetVertices(v); m.SetNormals(n); m.SetUVs(0, uv);
            var keys = tri.Keys.ToList();
            m.subMeshCount = keys.Count;
            for (int i = 0; i < keys.Count; i++) m.SetTriangles(tri[keys[i]], i);
            m.RecalculateBounds();
            used = keys.Select(k => mats[k]).ToArray();
            return m;
        }

        public int Tris => tri.Values.Sum(l => l.Count) / 3;
    }

    struct Frame { public float s; public Vector3 p, r; }     // p = deck-top centre, r = horizontal right

    static Frame MakeFrame(LinePath lp, float s, float deckOff, float absY = float.NaN)
    {
        var dir = lp.Dir(s);
        var p = lp.Pos(s) + Vector3.up * deckOff;
        if (!float.IsNaN(absY)) p.y = absY;
        return new Frame { s = s, p = p, r = LinePath.Right(dir) };
    }

    /// Rings for [a, b]: both ends, then wherever the heading turned > RingTurnDeg or every RingMaxGap m.
    /// absY (planters): every ring at that height instead of spline height + deckOff.
    static List<Frame> Frames(LinePath lp, float a, float b, float deckOff, float absY = float.NaN)
    {
        var f = new List<Frame> { MakeFrame(lp, a, deckOff, absY) };
        var lastDir = lp.Dir(a);
        float last = a;
        for (float s = a + 1f; s < b - 0.5f; s += 1f)
        {
            var d = lp.Dir(s);
            if (Vector3.Angle(d, lastDir) > RingTurnDeg || s - last >= RingMaxGap)
            {
                f.Add(MakeFrame(lp, s, deckOff, absY));
                lastDir = d; last = s;
            }
        }
        f.Add(MakeFrame(lp, b, deckOff, absY));
        return f;
    }

    /// UV of profile point k (0..n, n = the seam again) at arc length s, by the profile's uv mode
    /// (= hanoi_metro.profile_uv): 'perimeter' (s / 4, arc / 4: tiled concrete), 'fraction' (s / u_len,
    /// arc / perimeter: profile atlas), 'height' ((s - u_off) / u_len, (y - ymin) / (ymax - ymin): panels).
    static Func<float, int, Vector2> ProfileUv(ProfileJ prof, List<Vector2> pts, float[] per)
    {
        int n = pts.Count;
        string mode = prof.uv != null ? prof.uv.mode : null;
        float ul = prof.uv != null && prof.uv.u_len > 0f ? prof.uv.u_len : 4f, uo = prof.uv != null ? prof.uv.u_off : 0f;
        if (mode == "fraction") return (s, k) => new Vector2(s / ul, per[k] / per[n]);
        if (mode == "height")
        {
            float y0 = pts.Min(p => p.y), y1 = pts.Max(p => p.y);
            return (s, k) => new Vector2((s - uo) / ul, (pts[k % n].y - y0) / Mathf.Max(1e-6f, y1 - y0));
        }
        return (s, k) => new Vector2(s * 0.25f, per[k] * 0.25f);
    }

    static void Sweep(Acc acc, List<Frame> fr, ProfileJ prof, bool capA, bool capB)
    {
        var pts = Flat(prof.pts);
        int n = pts.Count;
        var per = new float[n + 1];
        for (int k = 0; k < n; k++) per[k + 1] = per[k] + Vector2.Distance(pts[k], pts[(k + 1) % n]);
        var uvf = ProfileUv(prof, pts, per);
        Vector3 W(Frame f, Vector2 q) => f.p + f.r * q.x + Vector3.up * q.y;
        for (int k = 0; k < n; k++)
        {
            Vector2 a = pts[k], b = pts[(k + 1) % n], e = b - a;
            int prevA = -1, prevB = -1;
            Vector3 prevN = Vector3.zero;
            for (int i = 0; i < fr.Count; i++)
            {
                // outward normal of a counter-clockwise profile edge (dx, dy): (dy, -dx)
                var nrm = (fr[i].r * e.y - Vector3.up * e.x).normalized;
                int ia = acc.V(W(fr[i], a), nrm, uvf(fr[i].s, k));
                int ib = acc.V(W(fr[i], b), nrm, uvf(fr[i].s, k + 1));
                if (i > 0)
                {
                    acc.Tri(prof.mat, prevA, ia, ib, prevN);
                    acc.Tri(prof.mat, prevA, ib, prevB, prevN);
                }
                prevA = ia; prevB = ib; prevN = nrm;
            }
        }
        if (!prof.closed) return;
        var tris = EarClip(pts);
        void Cap(Frame f, Vector3 want)
        {
            int baseI = acc.v.Count;
            foreach (var q in pts) acc.V(W(f, q), want, q * 0.25f);
            for (int t = 0; t < tris.Count; t += 3)
                acc.Tri(prof.mat, baseI + tris[t], baseI + tris[t + 1], baseI + tris[t + 2], want);
        }
        if (capA) Cap(fr[0], -Vector3.Cross(fr[0].r, Vector3.up));                 // facing back along the line
        if (capB) Cap(fr[fr.Count - 1], Vector3.Cross(fr[fr.Count - 1].r, Vector3.up));
    }

    /// Counter-clockwise simple polygon -> triangle indices.
    static List<int> EarClip(List<Vector2> p)
    {
        var idx = Enumerable.Range(0, p.Count).ToList();
        var tris = new List<int>();
        float Cr(Vector2 a, Vector2 b) => a.x * b.y - a.y * b.x;
        bool InTri(Vector2 q, Vector2 a, Vector2 b, Vector2 c) =>
            Cr(b - a, q - a) >= 0f && Cr(c - b, q - b) >= 0f && Cr(a - c, q - c) >= 0f;
        int guard = 0;
        while (idx.Count > 3 && guard++ < 4 * p.Count)
        {
            bool clipped = false;
            for (int i = 0; i < idx.Count && !clipped; i++)
            {
                int a = idx[(i + idx.Count - 1) % idx.Count], b = idx[i], c = idx[(i + 1) % idx.Count];
                if (Cr(p[b] - p[a], p[c] - p[b]) <= 1e-8f) continue;          // reflex or flat corner
                bool blocked = false;
                foreach (int j in idx)
                    if (j != a && j != b && j != c && InTri(p[j], p[a], p[b], p[c])) { blocked = true; break; }
                if (blocked) continue;
                tris.Add(a); tris.Add(b); tris.Add(c);
                idx.RemoveAt(i);
                clipped = true;
            }
            if (!clipped) break;
        }
        if (idx.Count == 3) tris.AddRange(idx);
        return tris;
    }

    /// Barrier posts every post.step m (global grid, so pieces line up): oriented boxes, no bottom.
    static void Posts(Acc acc, LinePath lp, float a, float b, PostJ post, float deckOff)
    {
        float first = Mathf.Ceil((a - post.step / 2f) / post.step) * post.step + post.step / 2f;
        for (float s = first; s < b; s += post.step)
        {
            var dir = lp.Dir(s);
            var r = LinePath.Right(dir);
            var p = lp.Pos(s) + Vector3.up * deckOff;
            foreach (int side in new[] { -1, 1 })
            {
                var c = p + r * (side * post.x);
                Box(acc, post.mat, c + Vector3.up * post.y0, dir, r, post.w / 2f, post.d / 2f, post.y1 - post.y0);
            }
        }
    }

    static void Box(Acc acc, string mat, Vector3 c, Vector3 t, Vector3 r, float hw, float hd, float h)
    {
        var up = Vector3.up;
        Vector3[] q = { c - t * hw - r * hd, c + t * hw - r * hd, c + t * hw + r * hd, c - t * hw + r * hd };
        for (int k = 0; k < 4; k++)
        {
            var a = q[k]; var b = q[(k + 1) % 4];
            var nrm = Vector3.Cross(up, b - a).normalized;
            var mid = (a + b) / 2f - c; mid.y = 0f;
            if (Vector3.Dot(nrm, mid) < 0f) nrm = -nrm;
            int i0 = acc.V(a, nrm, Vector2.zero), i1 = acc.V(b, nrm, new Vector2(0.1f, 0f));
            int i2 = acc.V(b + up * h, nrm, new Vector2(0.1f, h * 0.25f)), i3 = acc.V(a + up * h, nrm, new Vector2(0f, h * 0.25f));
            acc.Tri(mat, i0, i1, i2, nrm); acc.Tri(mat, i0, i2, i3, nrm);
        }
        int j0 = acc.V(q[0] + up * h, up, Vector2.zero), j1 = acc.V(q[1] + up * h, up, Vector2.zero);
        int j2 = acc.V(q[2] + up * h, up, Vector2.zero), j3 = acc.V(q[3] + up * h, up, Vector2.zero);
        acc.Tri(mat, j0, j1, j2, up); acc.Tri(mat, j0, j2, j3, up);
    }

    // ------------------------------------------------------------------ piers
    static List<(int index, float s)> PierPositions(MetroLine line, LinePath lp, out string report)
    {
        float L = lp.Length;
        int n = Mathf.Max(1, Mathf.RoundToInt(L / Mathf.Max(5f, line.span)));
        float step = L / n;
        var res = new List<(int, float)>();
        int slid = 0, stuck = 0;
        var stuckList = new List<int>();
        for (int k = 0; k <= n; k++)
        {
            float s = k * step;
            int oi = line.pierOverrides.FindIndex(o => o.index == k);
            if (oi >= 0)
            {
                if (line.pierOverrides[oi].skip) continue;
                res.Add((k, Mathf.Clamp(s + line.pierOverrides[oi].shift, 0f, L)));
                continue;
            }
            float best = s;
            if (NeedsSlide(line, lp, s))
            {
                best = float.NaN;
                for (float d = 0.5f; d <= line.pierSlide && float.IsNaN(best); d += 0.5f)
                    foreach (float c in new[] { s - d, s + d })
                        if (c >= 0f && c <= L && !NeedsSlide(line, lp, c)) { best = c; break; }
                if (float.IsNaN(best)) { best = s; stuck++; stuckList.Add(k); }
                else slid++;
            }
            res.Add((k, best));
        }
        // even out the spans next to a slid pier: free piers move (<= 3 m per pass) towards the middle of
        // their neighbours as long as they stay valid (in a median zone where one is needed)
        var fixedIdx = new HashSet<int>(line.pierOverrides.Select(o => o.index));
        for (int pass = 0; pass < 6; pass++)
            for (int i = 1; i + 1 < res.Count; i++)
            {
                if (fixedIdx.Contains(res[i].Item1)) continue;
                float mid = (res[i - 1].Item2 + res[i + 1].Item2) / 2f;
                float cand = res[i].Item2 + Mathf.Clamp(mid - res[i].Item2, -3f, 3f);
                if (Mathf.Abs(cand - res[i].Item2) > 0.05f && !NeedsSlide(line, lp, cand))
                    res[i] = (res[i].Item1, cand);
            }
        var spans = res.Zip(res.Skip(1), (a, b) => b.Item2 - a.Item2).ToList();
        report = $"{res.Count} piers (target step {step:F1} m), {slid} slid into a median zone, {stuck} could not " +
                 $"(indices {string.Join(",", stuckList)}), spans {(spans.Count > 0 ? spans.Min() : 0):F1}..{(spans.Count > 0 ? spans.Max() : 0):F1} m";
        return res;
    }

    /// True when the point is close to a median zone (the line runs along a road there) but not inside one.
    static bool NeedsSlide(MetroLine line, LinePath lp, float s)
    {
        if (line.medianZones == null || line.medianZones.Count == 0) return false;
        var p3 = lp.Pos(s);
        var q = new Vector2(p3.x, p3.z);
        bool near = false;
        foreach (var z in line.medianZones)
        {
            if (z.pts.Count < 3) continue;
            if (InRing(q, z.pts)) return false;
            if (RingDist(q, z.pts) < 25f) near = true;
        }
        return near;
    }

    static void PlacePier(GameObject prefab, Transform parent, string name, MetroJ spec, MetroLine line, LinePath lp, float s)
    {
        var go = (GameObject)PrefabUtility.InstantiatePrefab(prefab, parent);
        go.name = name;
        var p = lp.Pos(s);
        go.transform.SetPositionAndRotation(new Vector3(p.x, line.groundY, p.z), Quaternion.LookRotation(lp.Dir(s), Vector3.up));
        // the cap carries the girder at the spline height: move the cap, stretch the column
        float capTop = p.y - (spec.rail_top - spec.cap_top);
        float capDy = capTop - line.groundY - spec.cap_top;
        float colScale = Mathf.Max(0.05f, (spec.cap_bottom + capDy) / spec.column_default_top);
        foreach (var t in go.GetComponentsInChildren<Transform>())
        {
            if (t.name.Contains("_Cap_")) t.position += Vector3.up * capDy;
            else if (t.name.Contains("_Column_"))
            {
                var local = t.InverseTransformDirection(Vector3.up);
                int ax = Mathf.Abs(local.x) > Mathf.Abs(local.y) ? (Mathf.Abs(local.x) > Mathf.Abs(local.z) ? 0 : 2) : (Mathf.Abs(local.y) > Mathf.Abs(local.z) ? 1 : 2);
                var sc = t.localScale; sc[ax] *= colScale; t.localScale = sc;
            }
        }
        go.GetComponent<LODGroup>().RecalculateBounds();
    }

    /// Unity_logs/metro_layout.json: the line every 5 m + piers (x, z, s, in a median zone 0/1) for
    /// Map/report_metro.py (2D check against the roads: no pier in a junction).
    static void WriteLayout(MetroLine line, LinePath lp, List<(int index, float s)> piers)
    {
        var sb = new System.Text.StringBuilder("{\"line\": [");
        var inv = System.Globalization.CultureInfo.InvariantCulture;
        for (float s = 0f; ; s = Mathf.Min(s + 5f, lp.Length))
        {
            var p = lp.Pos(s);
            sb.Append(string.Format(inv, "{0:F2},{1:F2},", p.x, p.z));
            if (s >= lp.Length) break;
        }
        sb.Length--;
        sb.Append("], \"piers\": [");
        foreach (var (k, s) in piers)
        {
            var p = lp.Pos(s);
            bool inZone = line.medianZones.Any(z => z.pts.Count > 2 && InRing(new Vector2(p.x, p.z), z.pts));
            sb.Append(string.Format(inv, "[{0},{1:F2},{2:F2},{3:F1},{4}],", k, p.x, p.z, s, inZone ? 1 : 0));
        }
        if (piers.Count > 0) sb.Length--;
        sb.Append("]}");
        File.WriteAllText(Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, "../Unity_logs/metro_layout.json")), sb.ToString());
    }

    // ------------------------------------------------------------------ planters (P1)
    static readonly float[] PlanterLod = { 0.12f, 0.015f };       // ~35 m pieces: shrub cards < ~170 m, blobs < ~1.4 km

    /// Planter runs = parts of the line inside a median zone, minus the pier footings (the footing kerb
    /// closes those ends); a run cut by a junction gets an end wall. Each run: kerbs + soil swept at
    /// ground level, two staggered rows of shrubs merged into one mesh per LOD (no shadows).
    static string BuildPlanters(MetroLine line, LinePath lp, MetroJ spec, List<(int index, float s)> piers,
                                Transform gen, Dictionary<string, Material> mats, HashSet<string> written)
    {
        if (spec.planter == null || spec.planter.profiles == null || spec.planter.profiles.Length == 0 ||
            line.medianZones == null || line.medianZones.Count == 0) return "no planters";
        var shrubs = ShrubMeshes(out int variants);
        var shrubMats = new[] { HanoiTrees.Foliage(), HanoiTrees.FoliageBlob() };
        float L = lp.Length, halfFoot = (spec.footing != null ? spec.footing.d : 3.4f) / 2f, step = 0.25f;
        var zones = line.medianZones.Where(z => z.pts.Count > 2).Select(z =>
        {
            var r = new Rect(z.pts[0], Vector2.zero);
            foreach (var q in z.pts) r = Rect.MinMaxRect(Mathf.Min(r.xMin, q.x), Mathf.Min(r.yMin, q.y), Mathf.Max(r.xMax, q.x), Mathf.Max(r.yMax, q.y));
            return (r, z.pts);
        }).ToList();
        bool InZone(float s)
        {
            var p = lp.Pos(s); var q = new Vector2(p.x, p.z);
            return zones.Any(z => z.r.Contains(q) && InRing(q, z.pts));
        }
        bool InFooting(float s) => piers.Any(pp => Mathf.Abs(pp.s - s) < halfFoot);
        int n = Mathf.FloorToInt(L / step) + 1;
        var ok = new bool[n];
        var foot = new bool[n];
        for (int i = 0; i < n; i++) { foot[i] = InFooting(i * step); ok[i] = !foot[i] && InZone(i * step); }

        var root = new GameObject("Planters").transform;
        root.SetParent(gen, false);
        var prof = spec.planter.profiles.Where(p => p.name != "planter_end").ToArray();
        var endProf = spec.planter.profiles.FirstOrDefault(p => p.name == "planter_end");
        int runs = 0, walls = 0, shrubCount = 0;
        float total = 0f;
        for (int i = 0; i < n; )
        {
            if (!ok[i]) { i++; continue; }
            int j = i;
            while (j + 1 < n && ok[j + 1]) j++;
            float a = i * step, b = j * step;
            bool capA = i == 0 || !foot[i - 1], capB = j == n - 1 || !foot[j + 1];
            i = j + 1;
            if (b - a < 3f) continue;
            string name = $"Planter_{runs++:000}";
            total += b - a;

            // frame: kerbs + soil (+ end walls where the run is not closed by a footing)
            var acc = new Acc();
            var frames = Frames(lp, a, b, 0f, line.groundY);
            foreach (var pr in prof) Sweep(acc, frames, pr, true, true);
            if (endProf != null)
            {
                if (capA) { Sweep(acc, Frames(lp, a, a + spec.planter.t, 0f, line.groundY), endProf, true, true); walls++; }
                if (capB) { Sweep(acc, Frames(lp, b - spec.planter.t, b, 0f, line.groundY), endProf, true, true); walls++; }
            }
            var frameMesh = acc.Build($"{name}_Frame", mats, out var frameMats);
            var go = new GameObject(name);
            go.transform.SetParent(root, false);
            var frameR = AddRenderer(go.transform, $"{name}_Frame", frameMesh, frameMats, ShadowCastingMode.On, written);

            // shrubs: two rows, the right one shifted half a step, random variant / yaw / scale
            var rnd = new System.Random(7919 * runs + 17);
            var ci = new List<CombineInstance>[] { new List<CombineInstance>(), new List<CombineInstance>() };
            if (variants > 0)
                for (float s = a + 0.45f; s < b - 0.45f; s += spec.shrub.step * (0.85f + 0.3f * (float)rnd.NextDouble()))
                    foreach (int side in new[] { -1, 1 })
                    {
                        float ss = s + (side > 0 ? 0.45f : 0f);
                        if (ss > b - 0.4f) continue;
                        float x = side * (spec.shrub.row + ((float)rnd.NextDouble() - 0.5f) * 0.3f);
                        var pos = lp.Track(ss, x); pos.y = line.groundY + spec.planter.soil;
                        float sc = Mathf.Lerp(spec.shrub.scale[0], spec.shrub.scale[1], (float)rnd.NextDouble());
                        var m = Matrix4x4.TRS(pos, Quaternion.Euler(0f, (float)rnd.NextDouble() * 360f, 0f), Vector3.one * sc);
                        int v = rnd.Next(variants);
                        for (int lod = 0; lod < 2; lod++)
                            ci[lod].Add(new CombineInstance { mesh = shrubs[v * 2 + lod], transform = m });
                        shrubCount++;
                    }
            var lods = new LOD[2];
            for (int lod = 0; lod < 2; lod++)
            {
                var rs = new List<Renderer> { frameR };
                if (ci[lod].Count > 0)
                {
                    var sm = new Mesh { name = $"{name}_Shrubs_LOD{lod}" };
                    if (ci[lod].Sum(c => c.mesh.vertexCount) > 65000) sm.indexFormat = IndexFormat.UInt32;
                    sm.CombineMeshes(ci[lod].ToArray(), true, true);
                    rs.Add(AddRenderer(go.transform, sm.name, sm, new[] { shrubMats[lod] }, ShadowCastingMode.Off, written));
                }
                lods[lod] = new LOD(PlanterLod[lod], rs.ToArray());
            }
            var lg = go.AddComponent<LODGroup>();
            lg.SetLODs(lods);
            lg.fadeMode = LODFadeMode.CrossFade;
            lg.animateCrossFading = true;
            lg.RecalculateBounds();
        }
        return $"{runs} planters ({total:F0} m, {walls} end walls), {shrubCount} shrubs";
    }

    static MeshRenderer AddRenderer(Transform parent, string name, Mesh mesh, Material[] mats, ShadowCastingMode shadows, HashSet<string> written)
    {
        string mp = $"{GenDir}/{name}.asset";
        AssetDatabase.CreateAsset(mesh, mp);
        written.Add(mp);
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        go.AddComponent<MeshFilter>().sharedMesh = mesh;
        var mr = go.AddComponent<MeshRenderer>();
        mr.sharedMaterials = mats;
        mr.shadowCastingMode = shadows;
        return mr;
    }

    // ------------------------------------------------------------------ rebuild
    [MenuItem("Hanoi/Metro/Rebuild Viaduct")]
    public static void RebuildMenu()
    {
        var line = UnityEngine.Object.FindFirstObjectByType<MetroLine>() ?? OpenLine();
        Rebuild(line);
    }

    public static void Rebuild(MetroLine line)
    {
        var t0 = DateTime.Now;
        var c = line.Container;
        if (c.Spline == null || c.Spline.Count < 2) { Debug.LogWarning("[Metro] the spline needs 2+ knots"); return; }
        var spec = LoadSpec();
        var mats = Materials(spec, refresh: false);
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(PierPrefabPath);
        if (prefab == null) { ImportPier(); prefab = AssetDatabase.LoadAssetAtPath<GameObject>(PierPrefabPath); }
        line.InvalidatePath();
        var lp = new LinePath(c);
        float L = lp.Length;
        float deckOff = spec.deck_top - spec.rail_top;

        var gen = line.transform.Find("Generated");
        if (gen != null) UnityEngine.Object.DestroyImmediate(gen.gameObject);
        gen = new GameObject("Generated").transform;
        gen.SetParent(line.transform, false);
        var pierRoot = new GameObject("Piers").transform; pierRoot.SetParent(gen, false);
        var deckRoot = new GameObject("Deck").transform; deckRoot.SetParent(gen, false);

        var piers = PierPositions(line, lp, out string pierReport);
        foreach (var (k, s) in piers) PlacePier(prefab, pierRoot, $"Pier_{k:000}", spec, line, lp, s);
        WriteLayout(line, lp, piers);

        // deck pieces: cut at every 3rd pier + station-zone edges; keep the solid ones
        var zones = line.stationZones.Select(z => (a: Mathf.Clamp(Mathf.Min(z.s0, z.s1), 0f, L), b: Mathf.Clamp(Mathf.Max(z.s0, z.s1), 0f, L)))
                        .Where(z => z.b - z.a > 0.5f).ToList();
        bool Solid(float s) => !zones.Any(z => s > z.a && s < z.b);
        var cuts = new SortedSet<float> { 0f, L };
        for (int i = PiersPerPiece; i < piers.Count - 1; i += PiersPerPiece) cuts.Add(piers[i].s);
        foreach (var z in zones) { cuts.Add(z.a); cuts.Add(z.b); }
        var cl = cuts.ToList();

        Directory.CreateDirectory(Abs(GenDir));
        var written = new HashSet<string>();
        int[] lodTris = new int[3];
        int pieceNo = 0;
        string planterReport = "no planters";
        AssetDatabase.StartAssetEditing();
        try
        {
            for (int i = 0; i + 1 < cl.Count; i++)
            {
                float a = cl[i], b = cl[i + 1];
                if (b - a < 0.25f || !Solid((a + b) / 2f)) continue;
                bool capA = a <= 0f || !Solid(a - 0.1f), capB = b >= L || !Solid(b + 0.1f);
                var frames = Frames(lp, a, b, deckOff);
                string pname = $"Deck_{pieceNo++:000}";
                var piece = new GameObject(pname);
                piece.transform.SetParent(deckRoot, false);
                var lods = new LOD[3];
                for (int lod = 0; lod < 3; lod++)
                {
                    var acc = new Acc();
                    foreach (var prof in spec.profiles)
                        if (lod >= prof.lods[0] && lod <= prof.lods[1]) Sweep(acc, frames, prof, capA, capB);
                    if (lod >= spec.post.lods[0] && lod <= spec.post.lods[1]) Posts(acc, lp, a, b, spec.post, deckOff);
                    var mesh = acc.Build($"{pname}_LOD{lod}", mats, out var used);
                    string mp = $"{GenDir}/{pname}_LOD{lod}.asset";
                    AssetDatabase.CreateAsset(mesh, mp);
                    written.Add(mp);
                    lodTris[lod] += acc.Tris;
                    var go = new GameObject($"{pname}_LOD{lod}");
                    go.transform.SetParent(piece.transform, false);
                    go.AddComponent<MeshFilter>().sharedMesh = mesh;
                    var mr = go.AddComponent<MeshRenderer>();
                    mr.sharedMaterials = used;
                    mr.shadowCastingMode = ShadowCastingMode.On;
                    lods[lod] = new LOD(DeckLod[lod], new Renderer[] { mr });
                }
                var lg = piece.AddComponent<LODGroup>();
                lg.SetLODs(lods);
                lg.fadeMode = LODFadeMode.CrossFade;
                lg.animateCrossFading = true;
                lg.RecalculateBounds();
            }
            planterReport = BuildPlanters(line, lp, spec, piers, gen, mats, written);
        }
        finally { AssetDatabase.StopAssetEditing(); }
        foreach (var f in Directory.GetFiles(Abs(GenDir), "*.asset"))
        {
            string ap = $"{GenDir}/{Path.GetFileName(f)}";
            if (!written.Contains(ap)) AssetDatabase.DeleteAsset(ap);
        }
        AssetDatabase.SaveAssets();
        // trains (TRAIN T2): A heads up the line from 30 %, B comes down towards it on the other track
        var trains = MetroTrains.Spawn(line, gen, L * 0.30f + 50f, L * 0.30f + 140f);
        EditorSceneManager.MarkSceneDirty(line.gameObject.scene);
        Debug.Log($"[Metro] {trains.Length} trains of {trains[0].length:F1} m");
        Debug.Log($"[Metro] rebuilt {L:F0} m in {(DateTime.Now - t0).TotalSeconds:F1} s: {pieceNo} deck pieces " +
                  $"(tris LOD0 {lodTris[0]}, LOD1 {lodTris[1]}, LOD2 {lodTris[2]}), {zones.Count} station zones; {pierReport}; {planterReport}");
    }

    // ------------------------------------------------------------------ shots
    [MenuItem("Hanoi/Metro/Metro Shots (city + metro)")]
    public static void Shots()
    {
        EditorSettings.asyncShaderCompilation = false;
        CityPlacer.OpenAll();                                  // main + chunks + Metro.unity
        var line = UnityEngine.Object.FindFirstObjectByType<MetroLine>();
        var lp = new LinePath(line.Container);
        var cam = Camera.main;
        float s = lp.Length * 0.30f;
        var dir = lp.Dir(s);
        var r = LinePath.Right(dir);
        var g = lp.Pos(s); g.y = line.groundY;
        var up = Vector3.up;
        HanoiSetup.Shot(cam, $"metro_{ShotTag}_1_drone", g - dir * 70f - r * 28f + up * 34f, g + dir * 90f + up * 8f);
        HanoiSetup.Shot(cam, $"metro_{ShotTag}_2_side", g - dir * 20f + r * 14f + up * 7f, g + dir * 90f + up * 9f);
        var pier = line.GetComponentsInChildren<LODGroup>().Where(l => l.name.StartsWith("Pier_"))
                       .OrderBy(l => Vector3.Distance(l.transform.position, g)).First().transform;
        var pd = pier.forward; var pr = pier.right;
        HanoiSetup.ShotSized(cam, $"metro_{ShotTag}_3_under", pier.position - pd * 7f + pr * 8.5f + up * 1.6f, pier.position + up * 8.2f, 900, 1200);
        var pg = pier.position;
        HanoiSetup.Shot(cam, $"metro_{ShotTag}_10_planter", pg - pd * 9f + pr * 4.5f + up * 1.5f, pg + pd * 6f + up * 0.4f);
        var top = lp.Pos(s);
        HanoiSetup.Shot(cam, $"metro_{ShotTag}_4_deck", top + up * 2.2f + r * 2f, top + dir * 60f + up * 0.5f);
        // north end: the line leaves the road and crosses blocks (deck vs houses)
        float sn = Mathf.Min(lp.Length - 50f, 2100f);
        var gn = lp.Pos(sn); gn.y = line.groundY;
        var dn = lp.Dir(sn); var rn = LinePath.Right(dn);
        HanoiSetup.Shot(cam, $"metro_{ShotTag}_6_north", gn - dn * 60f - rn * 45f + up * 40f, gn + dn * 40f + up * 6f);
        // trains: the front like Ref/train.webp (on the walkway ahead of train A), then train A on the
        // north curve (cars must follow the curve, bogies on the rails)
        var ta = line.GetComponentsInChildren<MetroTrain>().First(t => t.direction > 0);
        float hs = ta.Head;
        var eye = lp.Track(hs + 9f, ta.trackOffset + 1.75f) + up * 1.2f;
        HanoiSetup.Shot(cam, $"metro_{ShotTag}_7_train_front", eye, lp.Track(hs - 4f, ta.trackOffset) + up * 2.0f);
        float sCurve = Mathf.Min(lp.Length - 10f, 2135f);
        ta.PlaceAt(sCurve);
        var gc = lp.Pos(sCurve - 35f); var dc = lp.Dir(sCurve - 35f); var rc = LinePath.Right(dc);
        HanoiSetup.Shot(cam, $"metro_{ShotTag}_8_curve", gc - rc * 45f + up * 14f - dc * 25f, gc + up * 1f);
        HanoiSetup.ShotSized(cam, $"metro_{ShotTag}_9_curve_top", gc + up * 70f + rc * 1f, gc, 1200, 1200);
        ta.PlaceAt(ta.startS);
        HanoiSetup.Shot(cam, $"metro_{ShotTag}_5_far", g - dir * 450f - r * 200f + up * 260f, g + dir * 200f);
        Debug.Log($"[Metro] shots in {HanoiSetup.ShotsDir} (s = {s:F0} m, pier {pier.name})");
    }

    /// Batch check of the running trains: simulate 400 s in 20 s slices (both trains run off one end and
    /// come back from the other); car-to-car distances must stay the consist spacing, no NaN.
    public static void TrainTest()
    {
        var line = OpenLine();
        var trains = line.GetComponentsInChildren<MetroTrain>(true);
        float L = line.Path.Length;
        foreach (var tr in trains)
        {
            tr.PlaceAt(tr.startS);
            float worst = 0f; bool nan = false; int wraps = 0; float prev = tr.Head;
            for (int k = 0; k < 20; k++)
            {
                tr.Simulate(20f);
                if (Mathf.Abs(tr.Head - prev) > L / 2f) wraps++;
                prev = tr.Head;
                var on = tr.cars.Where(c => c.t.gameObject.activeSelf).ToList();
                for (int i = 0; i + 1 < tr.cars.Count; i++)
                {
                    var a = tr.cars[i]; var b = tr.cars[i + 1];
                    if (!a.t.gameObject.activeSelf || !b.t.gameObject.activeSelf) continue;
                    float want = b.offset - a.offset;
                    float got = Vector3.Distance(a.t.position, b.t.position);
                    if (float.IsNaN(got)) nan = true;
                    // chord vs arc on curves: allow 0.5 %
                    worst = Mathf.Max(worst, Mathf.Abs(got - want) / want);
                }
                if (k % 5 == 4)
                    Debug.Log($"[Train] {tr.name} t={20 * (k + 1)} s head {tr.Head:F0} m speed {tr.Speed:F1} m/s, {on.Count} cars visible");
            }
            Debug.Log($"[Train] {tr.name}: worst car spacing error {worst * 100f:F2} %, wraps {wraps}, NaN {nan}");
            tr.PlaceAt(tr.startS);
        }
    }

    /// Batch: rebuild the viaduct of the saved scene only (no import, no shots).
    public static void RebuildBatch()
    {
        var line = OpenLine();
        Rebuild(line);
        EditorSceneManager.SaveScene(line.gameObject.scene);
    }

    /// Batch (Editor closed): pier import, scene (seeded from city.json when the spline is empty), rebuild, shots.
    public static void RunBatch()
    {
        ImportPier();
        MetroTrains.ImportTrain();
        var line = OpenLine();
        if (line.Container.Spline == null || line.Container.Spline.Count < 2) Seed(line);
        Rebuild(line);
        EditorSceneManager.SaveScene(line.gameObject.scene);
        AddToBuildSettings();
        Shots();
    }
}
