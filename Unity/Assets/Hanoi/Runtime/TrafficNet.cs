using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// TRAFFIC T3: the lane graph of city.json "traffic" (Map/pipeline/traffic.py) in Unity space, serialized in the
/// traffic scene by Editor/TrafficBuilder. A lane is a polyline (road surface height included) with arc lengths,
/// signed curvature (+ = turning right), the lanes it continues into and, for junction links, the links it
/// conflicts with (they cross or merge: one vehicle at a time).
/// </summary>
[Serializable]
public class TrafficLane
{
    public Vector3[] pts;
    public float[] s;          // arc length at each point (3-D)
    public float[] k;          // signed horizontal curvature at each point, 1/m (+ = right)
    public int[] next;
    public int[] conflicts;
    public float turn;         // total heading change, deg (+ = right)
    public float width;        // m
    public float speed;        // m/s
    public bool src, sink, link, fly;
    public float Length => s[s.Length - 1];
}

[Serializable]
public class TrafficNet
{
    public List<TrafficLane> lanes = new List<TrafficLane>();

    /// Fills s / k of a lane from its points.
    public static void Measure(TrafficLane l)
    {
        int n = l.pts.Length;
        l.s = new float[n];
        l.k = new float[n];
        for (int i = 1; i < n; i++) l.s[i] = l.s[i - 1] + Vector3.Distance(l.pts[i - 1], l.pts[i]);
        for (int i = 0; i < n; i++)
        {
            int a = Mathf.Max(0, i - 1), b = Mathf.Min(n - 1, i + 1);
            if (b - a < 2) continue;
            float h0 = Heading(l.pts[a], l.pts[a + 1]), h1 = Heading(l.pts[b - 1], l.pts[b]);
            float ds = 0.5f * (l.s[b] - l.s[a]);
            l.k[i] = ds > 1e-3f ? Mathf.DeltaAngle(h0, h1) * Mathf.Deg2Rad / ds : 0f;
        }
        if (n >= 3) { l.k[0] = l.k[1]; l.k[n - 1] = l.k[n - 2]; }
        l.turn = n >= 2 ? Mathf.DeltaAngle(Heading(l.pts[0], l.pts[1]), Heading(l.pts[n - 2], l.pts[n - 1])) : 0f;
    }

    /// Compass heading in degrees (0 = +z, 90 = +x: increasing = turning right).
    static float Heading(Vector3 a, Vector3 b) => Mathf.Atan2(b.x - a.x, b.z - a.z) * Mathf.Rad2Deg;

    int Seg(TrafficLane l, float d)
    {
        int i = Array.BinarySearch(l.s, d);
        if (i < 0) i = ~i - 1;
        return Mathf.Clamp(i, 0, l.s.Length - 2);
    }

    /// Point at arc length d (clamped), `lat` m to the right.
    public Vector3 Pos(int lane, float d, float lat = 0f)
    {
        var l = lanes[lane];
        d = Mathf.Clamp(d, 0f, l.Length);
        int i = Seg(l, d);
        float t = (d - l.s[i]) / Mathf.Max(1e-5f, l.s[i + 1] - l.s[i]);
        var p = Vector3.Lerp(l.pts[i], l.pts[i + 1], t);
        if (lat != 0f) p += Right(l.pts[i + 1] - l.pts[i]) * lat;
        return p;
    }

    /// Unit tangent (3-D) at d.
    public Vector3 Dir(int lane, float d)
    {
        var l = lanes[lane];
        int i = Seg(l, Mathf.Clamp(d, 0f, l.Length));
        var v = l.pts[i + 1] - l.pts[i];
        return v.sqrMagnitude < 1e-8f ? Vector3.forward : v.normalized;
    }

    public float Curvature(int lane, float d)
    {
        var l = lanes[lane];
        d = Mathf.Clamp(d, 0f, l.Length);
        int i = Seg(l, d);
        float t = (d - l.s[i]) / Mathf.Max(1e-5f, l.s[i + 1] - l.s[i]);
        return Mathf.Lerp(l.k[i], l.k[i + 1], t);
    }

    public static Vector3 Right(Vector3 dir)
    {
        var r = Vector3.Cross(Vector3.up, dir);
        r.y = 0f;
        return r.sqrMagnitude < 1e-8f ? Vector3.right : r.normalized;
    }
}
