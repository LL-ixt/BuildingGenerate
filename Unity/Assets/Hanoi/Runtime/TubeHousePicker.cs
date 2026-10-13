using System.Collections.Generic;
using System.Linq;
using UnityEngine;

/// <summary>
/// Chooses library tube houses for a row of lots along one street (B4; reused by the city placer).
///  - Lot depth -> nearest baked depth bucket + localScale.z inside the variant's depthScale range.
///  - Side windows only where a wall is exposed: row ends at a corner / gap, or a house taller than
///    its neighbour. The row is ordered from the viewer's left to right when facing the facades.
/// Deterministic for a given seed.
/// </summary>
public static class TubeHousePicker
{
    public struct Lot
    {
        public float depth;                  // metres from the facade line to the back of the house
        public bool openLeft, openRight;     // nothing built right beside that side wall (gap, corner)
    }

    public struct Choice
    {
        public BuildingVariant variant;
        public float depthScale;             // localScale.z
        public bool exposedLeft, exposedRight;
    }

    /// Height difference (m) above which the taller house gets side windows (about two floors);
    /// a one-floor step just shows a bit of blank party wall, as in real Hanoi streets.
    public const float ExposeStep = 6.0f;
    /// Chance that the next house in a row stays within one floor of the previous one.
    public const float SmoothSkyline = 0.75f;

    /// Best baked depth bucket for a lot and the scale that makes it fit.
    public static (float bucket, float scale) FitDepth(IEnumerable<float> buckets, float lotDepth, Vector2 range)
    {
        float best = 0, bestScale = 1, bestErr = float.MaxValue;
        foreach (var b in buckets.Distinct())
        {
            float s = lotDepth / b;
            float clamped = Mathf.Clamp(s, range.x, range.y);
            float err = Mathf.Abs(clamped * b - lotDepth) * 10f + Mathf.Abs(Mathf.Log(clamped));
            if (err < bestErr) { bestErr = err; best = b; bestScale = clamped; }
        }
        return (best, bestScale);
    }

    static string Tag(bool l, bool r) => l && r ? "LR" : l ? "L" : r ? "R" : "";

    public static Choice[] PickRow(IReadOnlyList<BuildingVariant> library, IReadOnlyList<Lot> lots,
                                   bool cornerLeft, bool cornerRight, int seed)
    {
        var tubes = library.Where(v => v != null && v.type == "tube").ToArray();
        var buckets = tubes.Select(v => v.depth).ToArray();
        var range = tubes.Length > 0 ? tubes[0].depthScale : Vector2.one;
        var rng = new System.Random(seed);
        int n = lots.Count;
        var res = new Choice[n];
        var fit = new (float bucket, float scale)[n];

        // pass 1: party-wall houses everywhere, avoiding the same variant twice in a row
        for (int i = 0; i < n; i++)
        {
            fit[i] = FitDepth(buckets, lots[i].depth, range);
            var pool = tubes.Where(v => v.exposed == "" && Mathf.Approximately(v.depth, fit[i].bucket)).ToArray();
            BuildingVariant prev = i > 0 ? res[i - 1].variant : null;
            var cand = pool.Where(p => p != prev).ToArray();
            if (prev != null && rng.NextDouble() < SmoothSkyline)
            {
                var near = cand.Where(p => Mathf.Abs(p.floors - prev.floors) <= 1).ToArray();
                if (near.Length > 0) cand = near;
            }
            var v = Pick(cand, rng) ?? Pick(pool, rng);
            res[i] = new Choice { variant = v, depthScale = fit[i].scale };
        }

        // pass 2: exposure from row ends and height steps, then swap in a variant with side windows
        // of the same depth, preferring the same number of floors (keeps the skyline from pass 1)
        var heights = res.Select(c => c.variant != null ? c.variant.height : 0f).ToArray();
        for (int i = 0; i < n; i++)
        {
            bool l = lots[i].openLeft || (i == 0 ? cornerLeft : heights[i] > heights[i - 1] + ExposeStep);
            bool r = lots[i].openRight || (i == n - 1 ? cornerRight : heights[i] > heights[i + 1] + ExposeStep);
            res[i].exposedLeft = l; res[i].exposedRight = r;
            if (!l && !r) continue;
            string tag = Tag(l, r);
            // a free-standing house may also use a one-side variant (the other wall stays blank):
            // there are only a couple of LR variants per depth
            var pool = tubes.Where(v => (tag == "LR" ? v.exposed != "" : v.exposed == tag) &&
                                        Mathf.Approximately(v.depth, fit[i].bucket)).ToArray();
            if (pool.Length == 0)       // e.g. no LR of this depth: any depth with the right exposure
                pool = tubes.Where(v => v.exposed == tag).ToArray();
            if (pool.Length == 0) continue;
            int floors = res[i].variant != null ? res[i].variant.floors : 3;
            var left = i > 0 ? res[i - 1].variant : null;
            var rightN = i < n - 1 ? res[i + 1].variant : null;
            var distinct = pool.Where(v => v != left && v != rightN).ToArray();
            if (distinct.Length > 0) pool = distinct;
            int bestDiff = pool.Min(v => Mathf.Abs(v.floors - floors));
            var v2 = Pick(pool.Where(v => Mathf.Abs(v.floors - floors) <= bestDiff + 1).ToArray(), rng);
            var f2 = FitDepth(new[] { v2.depth }, lots[i].depth, v2.depthScale);
            res[i].variant = v2; res[i].depthScale = f2.scale;
        }
        return res;
    }

    static BuildingVariant Pick(BuildingVariant[] pool, System.Random rng) =>
        pool.Length == 0 ? null : pool[rng.Next(pool.Length)];
}
