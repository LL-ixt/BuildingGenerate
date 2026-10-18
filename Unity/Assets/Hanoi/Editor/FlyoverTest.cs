using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// Plan FLY F2: the Chùa Bộc – Phạm Ngọc Thạch test area as its own small city (Assets/Hanoi/FlyoverTest,
/// chunk scenes FT_Chunk_*), from `python Map/osm_pipeline.py "<cầu vượt.osm>" --out Map/out_flyover`.
/// Same CityPlacer / ChunkBuilder chain as the main map through CityTarget.FlyoverTest; the main map,
/// its Build Settings and the metro scene are not touched.
/// Menu "Hanoi/Flyover Test/..." or batch: -executeMethod FlyoverTest.RunBatch
/// </summary>
public static class FlyoverTest
{
    [Serializable] class CityJ { public FlyJ[] flyovers; }
    [Serializable] class FlyJ { public string name; public float length, clear_from, clear_to; public float[] line; }

    [MenuItem("Hanoi/Flyover Test/Place City + HLOD")]
    public static void Place() => CityTarget.With(CityTarget.FlyoverTest, () => { CityPlacer.Run(); ChunkBuilder.Run(); });

    [MenuItem("Hanoi/Flyover Test/Build Flyovers")]
    public static void BuildFlyovers() => CityTarget.With(CityTarget.FlyoverTest, FlyoverBuilder.Build);

    [MenuItem("Hanoi/Flyover Test/Open Main + All Chunks")]
    public static void Open() => CityTarget.With(CityTarget.FlyoverTest, OpenInTarget);

    static void OpenInTarget()
    {
        CityPlacer.OpenAll();
        if (File.Exists(Path.Combine(HanoiSetup.ProjectDir, FlyoverBuilder.ScenePath)))
            EditorSceneManager.OpenScene(FlyoverBuilder.ScenePath, OpenSceneMode.Additive);
    }

    /// Point of the flyover centreline at arc length s (map x, y -> Unity x, z; ground level).
    static Vector3 At(FlyJ f, float s)
    {
        var l = f.line;
        float acc = 0f;
        for (int i = 3; i + 2 < l.Length; i += 3)
        {
            var a = new Vector3(l[i - 3], 0f, l[i - 2]);
            var b = new Vector3(l[i], 0f, l[i + 1]);
            float d = Vector3.Distance(a, b);
            if (acc + d >= s) return Vector3.Lerp(a, b, (s - acc) / Mathf.Max(d, 1e-4f));
            acc += d;
        }
        return new Vector3(l[l.Length - 3], 0f, l[l.Length - 2]);
    }

    /// The area around the flyover strip: from above, a drone view of the junction, eye level in the junction.
    public static void Shots()
    {
        CityTarget.With(CityTarget.FlyoverTest, () =>
        {
            CityPlacer.OpenAll();
            EditorSettings.asyncShaderCompilation = false;
            var f = JsonUtility.FromJson<CityJ>(File.ReadAllText(CityTarget.CityJson)).flyovers[0];
            var cam = Camera.main;
            var mid = At(f, (f.clear_from + f.clear_to) / 2f);                 // over the junction
            // the junction sits near the south edge of the OSM extract: look at it from the map centre side
            var inward = new Vector3(-mid.x, 0f, -mid.z).normalized;
            var mapMid = At(f, f.length / 2f);
            HanoiSetup.ShotSized(cam, "ft_f2_1_top", mapMid + Vector3.up * 300f, mapMid, 1600, 1600);
            HanoiSetup.Shot(cam, "ft_f2_2_drone", mid + inward * 70f + Vector3.up * 45f, mid);
            HanoiSetup.Shot(cam, "ft_f2_3_eye", mid + Vector3.up * 1.7f, At(f, f.clear_to + 60f) + Vector3.up * 2f);
            Debug.Log($"[FlyoverTest] shots in {HanoiSetup.ShotsDir}: {f.name}, junction centre {mid}");
        });
    }

    public static void RunBatch()
    {
        Place();
        Shots();
    }

    /// F3 views, two of them set up like the reference photos (only to compare, nothing is fitted to them):
    /// 1 high on the outer side of the bend (opening photo), 2 eye level under the bend at a pier (pier photo),
    /// 3 driving on the deck, 4 beside a solid ramp, 5 under the deck along the piers.
    public static void ShotsF3() => ShotsF3(CityTarget.FlyoverTest, "ft_f3_");

    /// Same views for any area (CityGenerator batch): shots are named prefix + number.
    public static void ShotsF3(CityTarget.T area, string pfx)
    {
        CityTarget.With(area, () =>
        {
            OpenInTarget();
            EditorSettings.asyncShaderCompilation = false;
            var (flys, roadY) = FlyoverBuilder.Load();
            var f = flys[0];
            var path = new FlyoverBuilder.Path3(f, roadY);
            float L = path.Length;
            Vector3 G(float s) { var p = path.Pos(s); p.y = 0.2f; return p; }       // ground under the centreline
            // apex of the bend = sharpest heading change over the clearance part
            float apex = f.clear_from, best = -1f;
            for (float s = f.clear_from; s <= f.clear_to; s += 2f)
            {
                float turn = Vector3.Angle(path.Dir(s - 10f), path.Dir(s + 10f));
                if (turn > best) { best = turn; apex = s; }
            }
            var M = G(apex);
            var Q = (G(60f) + G(L - 60f)) / 2f;
            var concave = (Q - M); concave.y = 0f; concave.Normalize();
            var cam = Camera.main;
            HanoiSetup.ShotSized(cam, pfx + "0_top", Q + Vector3.up * 330f, Q, 1600, 1600);
            HanoiSetup.Shot(cam, pfx + "1_photo_high", M - concave * 75f + Vector3.up * 32f, M + concave * 35f + Vector3.up * 3f);
            var pier = f.piers.OrderBy(p => Mathf.Abs(p.s - apex)).First();
            var P = new Vector3(pier.x, 0.2f, pier.y);
            var t = path.Dir(pier.s);
            HanoiSetup.Shot(cam, pfx + "2_photo_pier", P - concave * 26f - t * 10f + Vector3.up * 1.6f, P + Vector3.up * 4.5f + t * 6f);
            float sd = f.clear_from - 30f;
            var right = new Vector3(path.Dir(sd).z, 0f, -path.Dir(sd).x);
            HanoiSetup.Shot(cam, pfx + "3_deck", path.Pos(sd) + Vector3.up * 1.5f + right * 1.5f, path.Pos(sd + 60f) + Vector3.up * 1f);
            float sr = 40f;
            var rr = new Vector3(path.Dir(sr).z, 0f, -path.Dir(sr).x);
            HanoiSetup.Shot(cam, pfx + "4_ramp", G(sr) + rr * 9f + Vector3.up * 1.6f, G(sr + 70f) + Vector3.up * 3f);
            // like the ramp photo: from a little height beside the touchdown, looking up the long ramp
            var re = new Vector3(path.Dir(L - 5f).z, 0f, -path.Dir(L - 5f).x);
            HanoiSetup.Shot(cam, pfx + "6_photo_ramp", G(L - 5f) + re * 6.5f + Vector3.up * 5f, G(L - 90f) + Vector3.up * 2f);
            var mid = f.piers[f.piers.Length / 2];
            var tm = path.Dir(mid.s);
            var rm = new Vector3(tm.z, 0f, -tm.x);
            HanoiSetup.Shot(cam, pfx + "5_under", G(mid.s - 18f) + rm * 6f + Vector3.up * 1.6f, G(mid.s + 25f) + Vector3.up * 4f);
            Debug.Log($"[FlyoverTest] F3 shots: apex s = {apex:F0} m, pier at s = {pier.s:F0} m");
        });
    }

    public static void RunF3Batch()
    {
        BuildFlyovers();
        ShotsF3();
    }
}
