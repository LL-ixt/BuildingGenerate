using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

/// <summary>
/// Plan FLY F3: road flyovers of city.json "flyovers" (Map/osm_pipeline.build_flyovers) swept as meshes
/// into their own scene (CityTarget dir / Flyovers.unity). Everything that sets the size and the place —
/// centreline, deck height z(s), width per point, ramp / deck parts, girder depth, piers — comes from
/// city.json; only the look of the cross-section below (steel box girder with sloped cantilevers, concrete
/// curb + galvanised railing, round piers with a collar) follows the reference photos.
///  - 'deck' parts: slab + box girder on round piers; 'ramp' parts: solid approach between walls.
///  - Pieces of ~60 m, each a LODGroup: LOD0 body + railing + markings, LOD1 body only.
/// Menu "Hanoi/Flyover Test/Build Flyovers" (FlyoverTest.cs) or batch FlyoverTest.RunF3Batch.
/// </summary>
public static class FlyoverBuilder
{
    // cross-section (m, across a / up v from the deck-top centre)
    const float CurbW = 0.35f, CurbH = 0.50f;         // concrete curb carrying the railing
    const float RailIn = 0.15f, RailTop = 1.10f, RailBar = 0.06f;
    const float RailTile = 1.5f, PostW = 0.12f;       // railing texture tile = post spacing; flat post width
    const float PostOver = 0.03f;                     // posts stand this far above the top rail tube
    const float MidRailV = 0.52f, MidRailW = 0.05f;   // second rail: height (fraction of the panel) and thickness
    const float Fascia = 0.30f;                       // deck edge below the road surface
    const float RampInset = 0.45f;                    // ramp retaining wall set back under the deck edge
    const float CantSlope = 0.20f;                    // cantilever underside drop per metre towards the box
    const float BoxRatio = 0.42f, BoxMin = 2.6f;      // box bottom width = max(BoxMin, ratio x deck width)
    const float LineW = 0.15f, EdgeLineIn = 0.25f, LineLift = 0.006f;
    const float PierR = 0.85f, CollarR = 0.98f, CollarH = 0.35f, CollarBelow = 0.55f, FootR = 1.2f, FootH = 0.35f;
    const int PierSides = 28;
    const float PieceLen = 60f;
    static readonly float[] LodHeights = { 0.05f, 0.003f };
    const string MatDir = "Assets/Hanoi/Materials";

    public static string ScenePath => $"{CityTarget.Dir}/Flyovers.unity";
    static string GenDir => $"{CityTarget.Dir}/Generated";

    // ------------------------------------------------------------------ city.json
    [Serializable] class CityJ { public StreetJ street; public FlyJ[] flyovers; }
    [Serializable] class StreetJ { public float road_y; }
    [Serializable] public class FlyJ
    {
        public int id, lanes;
        public string name;
        public float length, depth, top, clear_from, clear_to;
        public float[] line, width;
        public SegJ[] segments;
        public PierJ[] piers;
    }
    [Serializable] public class SegJ { public float s0, s1; public string kind; }
    [Serializable] public class PierJ { public float s, x, y, yaw, top; }

    internal static (FlyJ[] flys, float roadY) Load()
    {
        var c = JsonUtility.FromJson<CityJ>(File.ReadAllText(CityTarget.CityJson));
        return (c.flyovers ?? new FlyJ[0], c.street != null ? c.street.road_y : 0.02f);
    }

    /// The flyover centreline in Unity space: deck-top centre at arc length s (horizontal metres).
    internal class Path3
    {
        readonly List<float> s = new List<float>();
        readonly List<Vector3> p = new List<Vector3>();
        readonly List<float> w = new List<float>();
        public float Length => s[s.Count - 1];

        public Path3(FlyJ f, float roadY)
        {
            var l = f.line;
            for (int i = 0; i + 2 < l.Length; i += 3)
            {
                var q = new Vector3(l[i], roadY + l[i + 2], l[i + 1]);          // map x, y, z -> Unity x, z, y
                s.Add(p.Count == 0 ? 0f : s[s.Count - 1] + Vector2.Distance(new Vector2(q.x, q.z), new Vector2(p[p.Count - 1].x, p[p.Count - 1].z)));
                p.Add(q);
                w.Add(f.width[Mathf.Min(i / 3, f.width.Length - 1)]);
            }
        }

        int Seg(float d)
        {
            int i = s.BinarySearch(d);
            if (i < 0) i = ~i - 1;
            return Mathf.Clamp(i, 0, s.Count - 2);
        }

        public Vector3 Pos(float d)
        {
            d = Mathf.Clamp(d, 0f, Length);
            int i = Seg(d);
            return Vector3.Lerp(p[i], p[i + 1], (d - s[i]) / Mathf.Max(1e-5f, s[i + 1] - s[i]));
        }

        public float Width(float d)
        {
            d = Mathf.Clamp(d, 0f, Length);
            int i = Seg(d);
            return Mathf.Lerp(w[i], w[i + 1], (d - s[i]) / Mathf.Max(1e-5f, s[i + 1] - s[i]));
        }

        /// Horizontal unit tangent.
        public Vector3 Dir(float d)
        {
            var v = Pos(Mathf.Min(Length, d + 1f)) - Pos(Mathf.Max(0f, d - 1f));
            v.y = 0f;
            return v.sqrMagnitude < 1e-8f ? Vector3.forward : v.normalized;
        }

        /// a, every sample point strictly between, b.
        public List<float> Stations(float a, float b)
        {
            var r = new List<float> { a };
            r.AddRange(s.Where(x => x > a + 0.05f && x < b - 0.05f));
            r.Add(b);
            return r;
        }
    }

    struct Ring
    {
        public float s, h;              // arc length, half width
        public Vector3 o, r, t;         // deck-top centre, horizontal right, horizontal forward
        public Vector3 P(Vector2 q) => o + r * q.x + Vector3.up * q.y;
        public Vector3 N(Vector2 n) => (r * n.x + Vector3.up * n.y).normalized;
    }

    static Ring MakeRing(Path3 path, float s)
    {
        var t = path.Dir(s);
        return new Ring { s = s, h = path.Width(s) / 2f, o = path.Pos(s), t = t, r = new Vector3(t.z, 0f, -t.x) };
    }

    // ------------------------------------------------------------------ mesh accumulator
    class Acc
    {
        public readonly List<Vector3> v = new List<Vector3>();
        public readonly List<Vector2> uv = new List<Vector2>();
        public readonly Dictionary<Material, List<int>> sub = new Dictionary<Material, List<int>>();

        public int V(Vector3 p, Vector2 t) { v.Add(p); uv.Add(t); return v.Count - 1; }

        /// Triangle facing `want` (winding picked from the geometry, so callers never think about it).
        public void Tri(Material m, int a, int b, int c, Vector3 want)
        {
            if (!sub.TryGetValue(m, out var l)) sub[m] = l = new List<int>();
            var n = Vector3.Cross(v[b] - v[a], v[c] - v[a]);
            if (Vector3.Dot(n, want) >= 0f) { l.Add(a); l.Add(b); l.Add(c); }
            else { l.Add(a); l.Add(c); l.Add(b); }
        }

        public int Tris => sub.Values.Sum(l => l.Count) / 3;
    }

    /// Strip between two section points along the rings; n = outward normal in the section (a, v).
    /// pa / pb / n get the ring index. UV: metres / 4 (s, across), or panelUV: (s, 0..1) for the railing texture.
    static void Strip(Acc acc, Material m, List<Ring> rings, Func<int, Vector2> pa, Func<int, Vector2> pb,
                      Func<int, Vector2> n, bool panelUV = false)
    {
        if (m == null) return;
        int b0 = acc.v.Count;
        for (int i = 0; i < rings.Count; i++)
        {
            var g = rings[i];
            Vector2 a = pa(i), b = pb(i);
            float len = Vector2.Distance(a, b);
            acc.V(g.P(a), panelUV ? new Vector2(g.s / RailTile, 0f) : new Vector2(g.s / 4f, 0f));
            acc.V(g.P(b), panelUV ? new Vector2(g.s / RailTile, 1f) : new Vector2(g.s / 4f, len / 4f));
        }
        for (int i = 0; i + 1 < rings.Count; i++)
        {
            int a0 = b0 + 2 * i, a1 = a0 + 1, c0 = a0 + 2, c1 = a0 + 3;
            var want = rings[i].N(n(i));
            acc.Tri(m, a0, a1, c0, want);
            acc.Tri(m, a1, c1, c0, want);
        }
    }

    // ------------------------------------------------------------------ cross-sections
    /// Closed section polygon + material of each edge (edge i = p[i] -> p[i+1]); null = never seen.
    delegate (Vector2[] p, Material[] m) Profile(Ring g);

    static float BoxHalf(Ring g) => Mathf.Max(BoxMin, BoxRatio * 2f * g.h) / 2f;

    static Profile DeckProfile(float depth, Mats M) => g =>
    {
        float h = g.h, bh = BoxHalf(g), ca = Mathf.Min(bh + 0.3f, h - 0.2f);
        float cv = Mathf.Max(-Fascia - (h - ca) * CantSlope, -depth + 0.2f);
        var right = new[] { new Vector2(h - CurbW, 0f), new Vector2(h - CurbW, CurbH), new Vector2(h, CurbH),
                            new Vector2(h, -Fascia), new Vector2(ca, cv), new Vector2(bh, -depth) };
        var rm = new[] { M.curb, M.curb, M.girder, M.girder, M.girder, M.girder };      // ..., last = bottom of the box
        return Mirror(right, rm, M.road);
    };

    /// Solid approach: the curb + deck edge overhang a retaining wall set back by RampInset (ramp photo),
    /// so only a slim wall shows under the edge band. Walls go down to y = 0.
    static Profile RampProfile(Mats M) => g =>
    {
        float h = g.h, ground = -g.o.y, f = Mathf.Min(Fascia, g.o.y);                 // edge band shrinks to 0 at the touchdown
        var right = new[] { new Vector2(h - CurbW, 0f), new Vector2(h - CurbW, CurbH), new Vector2(h, CurbH),
                            new Vector2(h, -f), new Vector2(h - RampInset, -f), new Vector2(h - RampInset, ground) };
        var rm = new[] { M.curb, M.curb, M.girder, M.girder, M.wall, null };          // bottom (in the ground) never seen
        return Mirror(right, rm, M.road);
    };

    /// right half (from the road edge round to the bottom) -> full polygon: right, mirrored left back up,
    /// closing edge = road surface. rm[k] = material of the edge leaving right[k]; the last one crosses the centre.
    static (Vector2[] p, Material[] m) Mirror(Vector2[] right, Material[] rm, Material road)
    {
        int n = right.Length;
        var p = new Vector2[2 * n];
        var m = new Material[2 * n];
        for (int k = 0; k < n; k++)
        {
            p[k] = right[k];
            m[k] = rm[k];
            p[2 * n - 1 - k] = new Vector2(-right[k].x, right[k].y);
            if (k < n - 1) m[2 * n - 2 - k] = rm[k];
        }
        m[2 * n - 1] = road;
        return (p, m);
    }

    static float SignedArea(Vector2[] p)
    {
        float a = 0f;
        for (int i = 0; i < p.Length; i++) { var q = p[i]; var w = p[(i + 1) % p.Length]; a += q.x * w.y - w.x * q.y; }
        return a / 2f;
    }

    static void Sweep(Acc acc, List<Ring> rings, Profile prof, bool capStart, bool capEnd)
    {
        var first = prof(rings[0]);
        int n = first.p.Length;
        float sgn = Mathf.Sign(SignedArea(first.p));                   // CCW: outward normal = (dy, -dx)
        var profs = rings.Select(g => prof(g).p).ToList();
        for (int e = 0; e < n; e++)
        {
            int e0 = e, e1 = (e + 1) % n;
            Strip(acc, first.m[e], rings, i => profs[i][e0], i => profs[i][e1],
                  i => { var d = profs[i][e1] - profs[i][e0]; return new Vector2(d.y, -d.x) * sgn; });
        }
        if (capStart) Cap(acc, rings[0], profs[0], first.m, -rings[0].t);
        if (capEnd) Cap(acc, rings[rings.Count - 1], profs[profs.Count - 1], first.m, rings[rings.Count - 1].t);
    }

    /// End face of a sweep (ear clipping of the section), in the curb / wall / girder material of its outline.
    static void Cap(Acc acc, Ring g, Vector2[] poly, Material[] edgeMats, Vector3 want)
    {
        var mat = edgeMats.FirstOrDefault(x => x != null && x.name.Contains("Wall")) ??
                  edgeMats.FirstOrDefault(x => x != null && x.name.Contains("Girder")) ?? edgeMats.First(x => x != null);
        int b = acc.v.Count;
        foreach (var q in poly) acc.V(g.P(q), new Vector2(q.x / 4f, q.y / 4f));
        foreach (var (i, j, k) in EarClip(poly)) acc.Tri(mat, b + i, b + j, b + k, want);
    }

    static List<(int, int, int)> EarClip(Vector2[] poly)
    {
        var idx = Enumerable.Range(0, poly.Length).ToList();
        if (SignedArea(poly) < 0) idx.Reverse();                        // work counter-clockwise
        var res = new List<(int, int, int)>();
        int guard = 0;
        while (idx.Count > 3 && guard++ < 1000)
        {
            bool cut = false;
            for (int i = 0; i < idx.Count; i++)
            {
                int a = idx[(i + idx.Count - 1) % idx.Count], b = idx[i], c = idx[(i + 1) % idx.Count];
                Vector2 A = poly[a], B = poly[b], C = poly[c];
                if ((B.x - A.x) * (C.y - A.y) - (B.y - A.y) * (C.x - A.x) <= 1e-7f) continue;     // reflex / flat
                bool inside = false;
                foreach (int o in idx)
                    if (o != a && o != b && o != c && InTri(poly[o], A, B, C)) { inside = true; break; }
                if (inside) continue;
                res.Add((a, b, c));
                idx.RemoveAt(i);
                cut = true;
                break;
            }
            if (!cut) break;
        }
        if (idx.Count == 3) res.Add((idx[0], idx[1], idx[2]));
        return res;
    }

    static bool InTri(Vector2 p, Vector2 a, Vector2 b, Vector2 c)
    {
        float d1 = (p.x - b.x) * (a.y - b.y) - (a.x - b.x) * (p.y - b.y);
        float d2 = (p.x - c.x) * (b.y - c.y) - (b.x - c.x) * (p.y - c.y);
        float d3 = (p.x - a.x) * (c.y - a.y) - (c.x - a.x) * (p.y - a.y);
        return !((d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0));
    }

    // ------------------------------------------------------------------ details
    static void Markings(Acc acc, List<Ring> rings, int lanes, Mats M)
    {
        var up = new Vector2(0f, 1f);
        if (lanes >= 2)                                                 // two-way: solid yellow centre line
            Strip(acc, M.yellow, rings, i => new Vector2(-LineW / 2f, LineLift), i => new Vector2(LineW / 2f, LineLift), i => up);
        foreach (float sd in new[] { -1f, 1f })
            Strip(acc, M.white, rings, i => new Vector2(sd * (rings[i].h - CurbW - EdgeLineIn - LineW / 2f), LineLift),
                  i => new Vector2(sd * (rings[i].h - CurbW - EdgeLineIn + LineW / 2f), LineLift), i => up);
    }

    static void Railing(Acc acc, Path3 path, List<Ring> rings, Mats M)
    {
        foreach (float sd in new[] { -1f, 1f })
        {
            float A(int i) => sd * (rings[i].h - RailIn);
            // post + mid-rail panel (alpha-clipped texture, two-sided), top rail tube (box section)
            Strip(acc, M.rail, rings, i => new Vector2(A(i), CurbH), i => new Vector2(A(i), RailTop + PostOver),
                  i => new Vector2(sd, 0f), panelUV: true);
            float r0 = RailBar / 2f;
            Strip(acc, M.railSolid, rings, i => new Vector2(A(i) - r0, RailTop), i => new Vector2(A(i) + r0, RailTop), i => new Vector2(0f, 1f));
            Strip(acc, M.railSolid, rings, i => new Vector2(A(i) - r0, RailTop - RailBar), i => new Vector2(A(i) + r0, RailTop - RailBar), i => new Vector2(0f, -1f));
            Strip(acc, M.railSolid, rings, i => new Vector2(A(i) + r0, RailTop - RailBar), i => new Vector2(A(i) + r0, RailTop), i => new Vector2(1f, 0f));
            Strip(acc, M.railSolid, rings, i => new Vector2(A(i) - r0, RailTop - RailBar), i => new Vector2(A(i) - r0, RailTop), i => new Vector2(-1f, 0f));
        }
    }

    /// Box without a bottom face; half = (across, up, along).
    static void Box(Acc acc, Material m, Vector3 c, Vector3 r, Vector3 t, Vector3 half)
    {
        var up = Vector3.up;
        void Face(Vector3 n, Vector3 u, Vector3 v, float hn, float hu, float hv)
        {
            var o = c + n * hn;
            int i0 = acc.V(o - u * hu - v * hv, Vector2.zero), i1 = acc.V(o + u * hu - v * hv, Vector2.right),
                i2 = acc.V(o + u * hu + v * hv, Vector2.one), i3 = acc.V(o - u * hu + v * hv, Vector2.up);
            acc.Tri(m, i0, i1, i2, n); acc.Tri(m, i0, i2, i3, n);
        }
        Face(r, t, up, half.x, half.z, half.y); Face(-r, t, up, half.x, half.z, half.y);
        Face(t, r, up, half.z, half.x, half.y); Face(-t, r, up, half.z, half.x, half.y);
        Face(up, r, t, half.y, half.x, half.z);
    }

    static void Cylinder(Acc acc, Material m, Vector3 c, float r, float y0, float y1, bool top)
    {
        int b = acc.v.Count;
        float circ = 2f * Mathf.PI * r;
        for (int j = 0; j <= PierSides; j++)
        {
            float a = j * 2f * Mathf.PI / PierSides;
            var d = new Vector3(Mathf.Cos(a), 0f, Mathf.Sin(a));
            acc.V(new Vector3(c.x, y0, c.z) + d * r, new Vector2(j * circ / PierSides / 4f, y0 / 4f));
            acc.V(new Vector3(c.x, y1, c.z) + d * r, new Vector2(j * circ / PierSides / 4f, y1 / 4f));
        }
        for (int j = 0; j < PierSides; j++)
        {
            float a = (j + 0.5f) * 2f * Mathf.PI / PierSides;
            var want = new Vector3(Mathf.Cos(a), 0f, Mathf.Sin(a));
            int p0 = b + 2 * j;
            acc.Tri(m, p0, p0 + 1, p0 + 2, want);
            acc.Tri(m, p0 + 1, p0 + 3, p0 + 2, want);
        }
        if (!top) return;
        int ci = acc.V(new Vector3(c.x, y1, c.z), Vector2.zero);
        int rb = acc.v.Count;
        for (int j = 0; j < PierSides; j++)
        {
            float a = j * 2f * Mathf.PI / PierSides;
            acc.V(new Vector3(c.x + Mathf.Cos(a) * r, y1, c.z + Mathf.Sin(a) * r), Vector2.zero);
        }
        for (int j = 0; j < PierSides; j++) acc.Tri(m, ci, rb + j, rb + (j + 1) % PierSides, Vector3.up);
    }

    // ------------------------------------------------------------------ materials
    class Mats { public Material road, girder, curb, wall, pier, rail, railSolid, white, yellow; }

    static Material Lit(string name, Color c, float smooth, float metal = 0f)
    {
        var m = HanoiSetup.LitMaterial(name, c, smooth);
        m.SetFloat("_Metallic", metal);
        EditorUtility.SetDirty(m);
        return m;
    }

    /// Railing panel: one RailTile (1.5 m) x panel height tile = a flat post centred on the tile edge (half at each
    /// side, so tiles join) + a mid rail across; open elsewhere. The top rail is the geometry tube, not in here.
    /// Shaded lighter in the middle of each bar, darker at the edges (alpha = mask).
    static Texture2D RailTexture()
    {
        const int W = 512, H = 256;
        string path = $"{MatDir}/T_FlyRail.asset";
        var tex = new Texture2D(W, H, TextureFormat.RGBA32, true) { name = "T_FlyRail", wrapModeU = TextureWrapMode.Repeat, wrapModeV = TextureWrapMode.Clamp };
        var px = new Color32[W * H];
        float postHalf = PostW / 2f / RailTile * W;                     // px
        float railHalf = MidRailW / 2f / (RailTop + PostOver - CurbH) * H;
        for (int y = 0; y < H; y++)
            for (int x = 0; x < W; x++)
            {
                float dx = Mathf.Min(x + 0.5f, W - x - 0.5f) / postHalf;                 // 0 at the post axis
                float dy = Mathf.Abs(y + 0.5f - MidRailV * H) / railHalf;
                float t = dx < 1f ? dx : dy < 1f ? dy : 2f;
                byte g = (byte)(255f * (1f - 0.28f * t * t));
                px[y * W + x] = t < 1f ? new Color32(g, g, g, 255) : new Color32(255, 255, 255, 0);
            }
        tex.SetPixels32(px);
        tex.Apply(true);
        AssetDatabase.DeleteAsset(path);
        AssetDatabase.CreateAsset(tex, path);
        return tex;
    }

    static Mats Materials()
    {
        var M = new Mats
        {
            road = AssetDatabase.LoadAssetAtPath<Material>($"{MatDir}/M_Asphalt.mat") ?? Lit("M_FlyRoad", new Color(0.3f, 0.3f, 0.3f), 0.15f),
            girder = Lit("M_FlyGirder", new Color(0.80f, 0.81f, 0.82f), 0.40f),           // painted steel box
            curb = Lit("M_FlyCurb", new Color(0.72f, 0.71f, 0.68f), 0.15f),
            wall = Lit("M_FlyWall", new Color(0.66f, 0.65f, 0.62f), 0.10f),
            pier = Lit("M_FlyPier", new Color(0.78f, 0.79f, 0.80f), 0.35f),
            railSolid = Lit("M_FlyRailSolid", new Color(0.74f, 0.76f, 0.77f), 0.55f, 0.6f),  // galvanised
            white = Lit("M_FlyLineWhite", new Color(0.92f, 0.92f, 0.90f), 0.30f),
            yellow = Lit("M_FlyLineYellow", new Color(0.95f, 0.74f, 0.16f), 0.30f),
        };
        var rail = Lit("M_FlyRail", new Color(0.74f, 0.76f, 0.77f), 0.55f, 0.6f);
        rail.SetTexture("_BaseMap", RailTexture());
        rail.SetColor("_BaseColor", new Color(0.74f, 0.76f, 0.77f));
        rail.SetFloat("_AlphaClip", 1f);
        rail.SetFloat("_Cutoff", 0.5f);
        rail.EnableKeyword("_ALPHATEST_ON");
        rail.SetFloat("_Cull", 0f);                                     // two-sided panel
        rail.renderQueue = (int)RenderQueue.AlphaTest;
        EditorUtility.SetDirty(rail);
        M.rail = rail;
        AssetDatabase.SaveAssets();
        return M;
    }

    // ------------------------------------------------------------------ build
    static Mesh SaveMesh(Acc a, string name, out Material[] mats)
    {
        var keys = a.sub.Keys.ToArray();
        var m = new Mesh { name = name };
        if (a.v.Count > 65000) m.indexFormat = IndexFormat.UInt32;
        m.SetVertices(a.v);
        m.SetUVs(0, a.uv);
        m.subMeshCount = keys.Length;
        for (int i = 0; i < keys.Length; i++) m.SetTriangles(a.sub[keys[i]], i);
        m.RecalculateNormals();
        m.RecalculateBounds();
        m.RecalculateTangents();
        AssetDatabase.CreateAsset(m, $"{GenDir}/{name}.asset");
        mats = keys;
        return m;
    }

    static MeshRenderer Renderer(Transform parent, string name, Acc a, string meshName)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        go.AddComponent<MeshFilter>().sharedMesh = SaveMesh(a, meshName, out var mats);
        var mr = go.AddComponent<MeshRenderer>();
        mr.sharedMaterials = mats;
        return mr;
    }

    static (int body, int detail) BuildOne(FlyJ f, float roadY, Transform root, Mats M)
    {
        var path = new Path3(f, roadY);
        var fo = new GameObject($"Flyover_{f.id}").transform;
        fo.SetParent(root, false);
        int piece = 0, tBody = 0, tDetail = 0;
        foreach (var seg in f.segments)
        {
            float a = Mathf.Max(0f, seg.s0), b = Mathf.Min(seg.s1, path.Length);
            if (b - a < 0.5f) continue;
            bool ramp = seg.kind == "ramp";
            int n = Mathf.Max(1, Mathf.RoundToInt((b - a) / PieceLen));
            for (int k = 0; k < n; k++)
            {
                float pa = a + (b - a) * k / n, pb = a + (b - a) * (k + 1) / n;
                var rings = path.Stations(pa, pb).Select(s => MakeRing(path, s)).ToList();
                var body = new Acc();
                var detail = new Acc();
                Sweep(body, rings, ramp ? RampProfile(M) : DeckProfile(f.depth, M), k == 0, k == n - 1);
                Markings(detail, rings, f.lanes, M);
                Railing(detail, path, rings, M);
                string name = $"F{f.id}_{piece:00}_{seg.kind}";
                var go = new GameObject(name);
                go.transform.SetParent(fo, false);
                var rb = Renderer(go.transform, "Body", body, name + "_Body");
                var rd = Renderer(go.transform, "Detail", detail, name + "_Detail");
                var lg = go.AddComponent<LODGroup>();
                lg.SetLODs(new[] { new LOD(LodHeights[0], new Renderer[] { rb, rd }), new LOD(LodHeights[1], new Renderer[] { rb }) });
                lg.RecalculateBounds();
                tBody += body.Tris; tDetail += detail.Tris;
                piece++;
            }
        }
        var piers = new GameObject("Piers").transform;
        piers.SetParent(fo, false);
        for (int i = 0; i < f.piers.Length; i++)
        {
            var p = f.piers[i];
            var acc = new Acc();
            var c = new Vector3(p.x, 0f, p.y);
            float top = roadY + p.top;
            Cylinder(acc, M.pier, c, FootR, 0f, FootH, true);                              // footing ring
            Cylinder(acc, M.pier, c, PierR, FootH, top, false);                            // column, up to the girder bottom
            Cylinder(acc, M.pier, c, CollarR, top - CollarBelow - CollarH, top - CollarBelow, true);   // collar
            var go = new GameObject($"Pier_{i:00}");
            go.transform.SetParent(piers, false);
            go.AddComponent<MeshFilter>().sharedMesh = SaveMesh(acc, $"F{f.id}_Pier_{i:00}", out var mats);
            go.AddComponent<MeshRenderer>().sharedMaterials = mats;
            tBody += acc.Tris;
        }
        Debug.Log($"[Flyover] {f.name}: {path.Length:F0} m, {piece} pieces, {f.piers.Length} piers, tris body + piers {tBody}, detail {tDetail}");
        return (tBody, tDetail);
    }

    /// Rebuild the flyovers of the current CityTarget into ScenePath (the scene holds nothing else).
    public static void Build()
    {
        var (flys, roadY) = Load();
        if (flys.Length == 0) { Debug.LogError($"[Flyover] no 'flyovers' in {CityTarget.CityJson}: run Map/osm_pipeline.py"); return; }
        bool existed = File.Exists(Path.Combine(HanoiSetup.ProjectDir, ScenePath));
        var scene = existed ? EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single)
                            : EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        foreach (var g in scene.GetRootGameObjects().Where(g => g.name == "Flyovers").ToArray())
            UnityEngine.Object.DestroyImmediate(g);
        AssetDatabase.DeleteAsset(GenDir);
        AssetDatabase.CreateFolder(CityTarget.Dir, "Generated");
        var M = Materials();
        var root = new GameObject("Flyovers");
        SceneManager.MoveGameObjectToScene(root, scene);
        foreach (var f in flys) BuildOne(f, roadY, root.transform, M);
        AssetDatabase.SaveAssets();
        EditorSceneManager.SaveScene(scene, ScenePath);
    }
}
