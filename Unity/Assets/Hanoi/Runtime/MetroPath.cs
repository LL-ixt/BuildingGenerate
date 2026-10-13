using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Splines;

/// <summary>
/// A MetroLine spline sampled every ~0.5 m in world space: positions / horizontal tangents by arc
/// length. Used by Editor/MetroBuilder (deck sweep, piers) and Runtime/MetroTrain (running trains).
/// </summary>
public class MetroPath
{
    const float SampleStep = 0.5f;
    readonly List<float> s = new List<float>();
    readonly List<Vector3> p = new List<Vector3>();
    public float Length => s[s.Count - 1];

    public MetroPath(SplineContainer c)
    {
        float approx = Mathf.Max(1f, c.CalculateLength());
        int n = Mathf.Max(200, Mathf.CeilToInt(approx / SampleStep));
        float acc = 0f;
        Vector3 prev = (Vector3)c.EvaluatePosition(0f);
        for (int i = 0; i <= n; i++)
        {
            Vector3 q = (Vector3)c.EvaluatePosition(i / (float)n);
            acc += Vector3.Distance(prev, q);
            s.Add(acc); p.Add(q);
            prev = q;
        }
    }

    public Vector3 Pos(float d)
    {
        d = Mathf.Clamp(d, 0f, Length);
        int i = s.BinarySearch(d);
        if (i >= 0) return p[i];
        i = ~i;
        if (i <= 0) return p[0];
        if (i >= s.Count) return p[p.Count - 1];
        float t = (d - s[i - 1]) / Mathf.Max(1e-6f, s[i] - s[i - 1]);
        return Vector3.Lerp(p[i - 1], p[i], t);
    }

    /// Horizontal unit tangent.
    public Vector3 Dir(float d)
    {
        float a = Mathf.Max(0f, d - 1f), b = Mathf.Min(Length, d + 1f);
        var v = Pos(b) - Pos(a);
        v.y = 0f;
        return v.sqrMagnitude < 1e-8f ? Vector3.forward : v.normalized;
    }

    public static Vector3 Right(Vector3 dir) => Vector3.Cross(Vector3.up, dir).normalized;

    /// Point on a track running `offset` m to the right of the line centre (rail top height).
    public Vector3 Track(float d, float offset) => Pos(d) + Right(Dir(d)) * offset;
}
