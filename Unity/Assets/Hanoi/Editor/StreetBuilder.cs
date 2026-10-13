using System.Collections.Generic;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// Raised sidewalks + sloped kerbs for one chunk (data from Map/osm_pipeline.py, city.json "street").
///  - Sidewalk object: flat top at road_y + kerb_h (triangles = sidewalk minus the kerb band) plus a
///    vertical skirt wall along every edge that does not touch the road (lines oriented with the sidewalk on the LEFT).
///  - Kerb object: the cross-section profile (across, up; 0 = road edge, negative = sidewalk side) swept along
///    every kerb polyline (oriented with the road on the RIGHT). Mitred joins, caps where the sidewalk really ends.
///    UV: u = distance / (4 stones), v = arc length along the profile / TexV.
/// All shape parameters come from city.json, so changing the pipeline constants changes the mesh.
/// </summary>
public static class StreetBuilder
{
    public const float TexV = 0.5f;          // metres of kerb texture height (face + lip)
    const float SkirtBottom = -0.02f;        // just below the block ground slab
    const float SplitDot = -0.2f;            // corners sharper than ~100 deg are not mitred, the kerb is split there

    public class Cross
    {
        public float roadY, kerbH, stone;
        public float[] profile;              // flat [across, up, ...], last segment = vertical lip
        public float WalkY => roadY + kerbH;
    }

    public class Data
    {
        public float[] top, kerb, kerbS, skirt, bounds;
        public int[] kerbN, skirtN;
    }

    class Acc
    {
        public readonly List<Vector3> p = new List<Vector3>(), n = new List<Vector3>();
        public readonly List<Vector2> uv = new List<Vector2>();
        public readonly List<int> idx = new List<int>();

        public int V(Vector3 pos, Vector3 nrm, Vector2 t) { p.Add(pos); n.Add(nrm); uv.Add(t); return p.Count - 1; }

        /// Triangle wound so that it faces `facing` (Unity: front = Cross(b - a, c - a) side).
        public void Tri(int a, int b, int c, Vector3 facing)
        {
            if (Vector3.Dot(Vector3.Cross(p[b] - p[a], p[c] - p[a]), facing) < 0f) (b, c) = (c, b);
            idx.Add(a); idx.Add(b); idx.Add(c);
        }

        public Mesh ToMesh(string name)
        {
            var m = new Mesh { name = name };
            if (p.Count > 65000) m.indexFormat = IndexFormat.UInt32;
            m.SetVertices(p); m.SetNormals(n); m.SetUVs(0, uv); m.SetTriangles(idx, 0);
            m.RecalculateBounds();
            m.RecalculateTangents();
            return m;
        }
    }

    public static void Build(Transform parent, string chunk, Data d, Cross c, Material walkMat, Material kerbMat)
    {
        var walk = new Acc();
        Top(walk, d.top, c.WalkY);
        Skirt(walk, d, c);
        Emit(parent, chunk + "_Sidewalk", walk, walkMat);

        var kerb = new Acc();
        Kerbs(kerb, d, c);
        Emit(parent, chunk + "_Kerb", kerb, kerbMat);
    }

    static void Emit(Transform parent, string name, Acc a, Material mat)
    {
        if (a.idx.Count == 0) return;
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        go.AddComponent<MeshFilter>().sharedMesh = a.ToMesh(name);
        var mr = go.AddComponent<MeshRenderer>();
        mr.sharedMaterial = mat;
        mr.shadowCastingMode = ShadowCastingMode.Off;
        GameObjectUtility.SetStaticEditorFlags(go, StaticEditorFlags.BatchingStatic);
    }

    // ------------------------------------------------------------------ flat top
    static void Top(Acc m, float[] tris, float y)
    {
        if (tris == null) return;
        for (int t = 0; t + 5 < tris.Length; t += 6)
        {
            int[] v = new int[3];
            for (int k = 0; k < 3; k++)
            {
                float x = tris[t + k * 2], z = tris[t + k * 2 + 1];
                v[k] = m.V(new Vector3(x, y, z), Vector3.up, new Vector2(x / 4f, z / 4f));
            }
            m.Tri(v[0], v[1], v[2], Vector3.up);
        }
    }

    // ------------------------------------------------------------------ skirt walls (sidewalk on the left)
    static void Skirt(Acc m, Data d, Cross c)
    {
        if (d.skirt == null || d.skirtN == null) return;
        int off = 0;
        foreach (int n in d.skirtN)
        {
            float s = 0f;
            for (int j = 0; j + 1 < n; j++)
            {
                var a = new Vector2(d.skirt[(off + j) * 2], d.skirt[(off + j) * 2 + 1]);
                var b = new Vector2(d.skirt[(off + j + 1) * 2], d.skirt[(off + j + 1) * 2 + 1]);
                float len = (b - a).magnitude;
                if (len < 1e-4f) continue;
                var dir = (b - a) / len;
                var nrm = new Vector3(dir.y, 0f, -dir.x);                 // right = outside
                float h = c.WalkY - SkirtBottom;
                int v0 = m.V(new Vector3(a.x, SkirtBottom, a.y), nrm, new Vector2(s / 4f, 0f));
                int v1 = m.V(new Vector3(a.x, c.WalkY, a.y), nrm, new Vector2(s / 4f, h / 4f));
                int v2 = m.V(new Vector3(b.x, c.WalkY, b.y), nrm, new Vector2((s + len) / 4f, h / 4f));
                int v3 = m.V(new Vector3(b.x, SkirtBottom, b.y), nrm, new Vector2((s + len) / 4f, 0f));
                m.Tri(v0, v1, v2, nrm); m.Tri(v0, v2, v3, nrm);
                s += len;
            }
            off += n;
        }
    }

    // ------------------------------------------------------------------ kerb sweep (road on the right)
    static void Kerbs(Acc m, Data d, Cross c)
    {
        if (d.kerb == null || d.kerbN == null) return;
        int off = 0;
        for (int i = 0; i < d.kerbN.Length; i++)
        {
            int n = d.kerbN[i];
            var pts = new List<Vector2>(n);
            for (int j = 0; j < n; j++)
            {
                var p = new Vector2(d.kerb[(off + j) * 2], d.kerb[(off + j) * 2 + 1]);
                if (pts.Count == 0 || (p - pts[pts.Count - 1]).sqrMagnitude > 1e-6f) pts.Add(p);
            }
            off += n;
            if (pts.Count >= 2) Line(m, pts, d.kerbS[i], d, c);
        }
    }

    static bool OnBounds(Vector2 p, float[] b) =>
        b != null && b.Length >= 4 && (Mathf.Abs(p.x - b[0]) < 0.02f || Mathf.Abs(p.x - b[2]) < 0.02f ||
                                       Mathf.Abs(p.y - b[1]) < 0.02f || Mathf.Abs(p.y - b[3]) < 0.02f);

    static void Line(Acc m, List<Vector2> pts, float s0, Data d, Cross c)
    {
        int n = pts.Count;
        bool closed = n >= 4 && (pts[0] - pts[n - 1]).sqrMagnitude < 1e-4f;
        var cum = new float[n];
        for (int i = 1; i < n; i++) cum[i] = cum[i - 1] + (pts[i] - pts[i - 1]).magnitude;

        // split at sharp corners (open lines only)
        var cuts = new List<int> { 0 };
        if (!closed)
            for (int i = 1; i < n - 1; i++)
                if (Vector2.Dot((pts[i] - pts[i - 1]).normalized, (pts[i + 1] - pts[i]).normalized) < SplitDot) cuts.Add(i);
        cuts.Add(n - 1);

        for (int r = 0; r + 1 < cuts.Count; r++)
        {
            int lo = cuts[r], hi = cuts[r + 1];
            var run = pts.GetRange(lo, hi - lo + 1);
            bool capA = !closed && lo == 0 && !OnBounds(run[0], d.bounds);
            bool capB = !closed && hi == n - 1 && !OnBounds(run[run.Count - 1], d.bounds);
            Sweep(m, run, cum, lo, s0, closed, capA, capB, c);
        }
    }

    static void Sweep(Acc m, List<Vector2> P, float[] cum, int lo, float s0, bool closed, bool capA, bool capB, Cross c)
    {
        int cnt = P.Count, N = c.profile.Length / 2;
        // ring = profile points, with the point before the lip duplicated (hard edge slope | lip)
        var across = new List<float>(); var up = new List<float>(); var arc = new List<float>(); var ringNrm = new List<Vector2>();
        var segN = new Vector2[N - 1]; var segLen = new float[N - 1];
        for (int j = 0; j < N - 1; j++)
        {
            float da = c.profile[(j + 1) * 2] - c.profile[j * 2], du = c.profile[(j + 1) * 2 + 1] - c.profile[j * 2 + 1];
            segLen[j] = Mathf.Sqrt(da * da + du * du);
            segN[j] = new Vector2(-du, da).normalized;                      // outward: up and towards the road
        }
        float a0 = 0f;
        for (int j = 0; j < N; j++)
        {
            if (j > 0) a0 += segLen[j - 1];
            Vector2 nn = j == 0 ? segN[0] : j == N - 1 ? segN[N - 2] : (segN[j - 1] + segN[j]).normalized;
            if (j == N - 2) nn = j == 0 ? segN[0] : segN[j - 1];            // top of the lip: smooth slope normal
            across.Add(c.profile[j * 2]); up.Add(c.profile[j * 2 + 1]); arc.Add(a0); ringNrm.Add(nn);
            if (j == N - 2)                                                  // duplicate: starts the lip
            {
                across.Add(c.profile[j * 2]); up.Add(c.profile[j * 2 + 1]); arc.Add(a0); ringNrm.Add(segN[N - 2]);
            }
        }
        int R = across.Count;

        var D = new Vector2[cnt - 1];
        for (int j = 0; j < cnt - 1; j++) D[j] = (P[j + 1] - P[j]).normalized;
        var mDir = new Vector2[cnt]; var mScale = new float[cnt];
        for (int k = 0; k < cnt; k++)
        {
            var dp = k > 0 ? D[k - 1] : closed ? D[cnt - 2] : D[0];
            var dn = k < cnt - 1 ? D[k] : closed ? D[0] : D[cnt - 2];
            var rp = new Vector2(dp.y, -dp.x); var rn = new Vector2(dn.y, -dn.x);   // road side (right)
            var mm = rp + rn;
            mm = mm.sqrMagnitude < 1e-6f ? rn : mm.normalized;
            mDir[k] = mm;
            mScale[k] = 1f / Mathf.Max(Vector2.Dot(mm, rn), 0.5f);
        }

        int baseIdx = m.p.Count;
        for (int k = 0; k < cnt; k++)
        {
            float u = (s0 + cum[lo + k]) / (4f * c.stone);
            for (int j = 0; j < R; j++)
            {
                var pos2 = P[k] + mDir[k] * (across[j] * mScale[k]);
                var nrm = new Vector3(mDir[k].x * ringNrm[j].x, ringNrm[j].y, mDir[k].y * ringNrm[j].x).normalized;
                m.V(new Vector3(pos2.x, c.roadY + up[j], pos2.y), nrm, new Vector2(u, arc[j] / TexV));
            }
        }
        for (int k = 0; k + 1 < cnt; k++)
            for (int j = 0; j + 1 < R; j++)
            {
                if (Mathf.Approximately(arc[j], arc[j + 1])) continue;             // the duplicated ring point
                int a = baseIdx + k * R + j, b = baseIdx + k * R + j + 1, cI = baseIdx + (k + 1) * R + j + 1, dI = baseIdx + (k + 1) * R + j;
                var nrm = m.n[a] + m.n[b] + m.n[cI] + m.n[dI];
                m.Tri(a, b, cI, nrm); m.Tri(a, cI, dI, nrm);
            }

        if (capA) Cap(m, P[0], mDir[0], mScale[0], new Vector3(-D[0].x, 0f, -D[0].y), c);
        if (capB) Cap(m, P[cnt - 1], mDir[cnt - 1], mScale[cnt - 1], new Vector3(D[cnt - 2].x, 0f, D[cnt - 2].y), c);
    }

    /// Closes the open end of a kerb: the profile polygon plus the back-bottom corner at road level.
    static void Cap(Acc m, Vector2 p, Vector2 mDir, float scale, Vector3 facing, Cross c)
    {
        int N = c.profile.Length / 2;
        var ids = new List<int>();
        for (int j = 0; j <= N; j++)
        {
            float a = j < N ? c.profile[j * 2] : c.profile[0];
            float u = j < N ? c.profile[j * 2 + 1] : 0f;
            var q = p + mDir * (a * scale);
            ids.Add(m.V(new Vector3(q.x, c.roadY + u, q.y), facing, new Vector2(a, u) / TexV));
        }
        for (int j = 1; j + 1 < ids.Count; j++) m.Tri(ids[0], ids[j], ids[j + 1], facing);
    }
}
