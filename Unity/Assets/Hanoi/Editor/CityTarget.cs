using System;
using System.IO;

/// <summary>
/// Which city CityPlacer / ChunkBuilder work on. Default = the main map (Map/out/city.json ->
/// Assets/Hanoi/City). A test area (FlyoverTest: Map/out_flyover from `osm_pipeline.py --out`) gets its
/// own folder, chunk-scene prefix and block-ground material, and leaves the Build Settings and the metro
/// scene alone. Not persisted: test-area entries switch with CityTarget.With(...), so a plain
/// "Hanoi/City/..." menu always means the main map.
/// </summary>
public static class CityTarget
{
    public class T
    {
        public string name, dir, json, prefix;
        public bool main;
    }

    public static readonly T Main = new T { name = "City", dir = "Assets/Hanoi/City", json = "../Map/out/city.json", prefix = "", main = true };
    public static readonly T FlyoverTest = new T
    {
        name = "FlyoverTest", dir = "Assets/Hanoi/FlyoverTest", json = "../Map/out_flyover/city.json", prefix = "FT_",
    };

    /// An area made by the CityGenerator window: Map/out_<slug>/city.json -> Assets/Hanoi/Areas/<slug>.
    public static T Area(string slug) => new T
    {
        name = slug, dir = "Assets/Hanoi/Areas/" + slug, json = "../Map/out_" + slug + "/city.json", prefix = slug + "_",
    };

    public static T Current { get; private set; } = Main;

    public static string Dir => Current.dir;
    public static string ChunkDir => Dir + "/Chunks";
    public static string HlodDir => Dir + "/HLOD";
    public static string MainScene => $"{Dir}/{Current.name}_Main.unity";      // main map: Assets/Hanoi/City/City_Main.unity
    public static string RecordPath => Dir + "/CityPlacement.asset";
    public static string CityJson => Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, Current.json));
    public static string BlockGroundMat => Current.main ? "M_BlockGround" : "M_BlockGround_" + Current.name;
    public static bool IsMain => Current.main;

    public static void With(T t, Action a)
    {
        var prev = Current;
        Current = t;
        try { a(); }
        finally { Current = prev; }
    }
}
