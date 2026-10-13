using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// TRAIN T2: metro cars from Blender (Export/Metro: build_train.py --export -> FBX/SM_Train_{End,Mid}.fbx,
/// Train/T_Train*.png, train.json) as prefabs with LODGroups, and the trains on a MetroLine.
/// MetroBuilder.Rebuild calls Spawn: two 4-car trains (End, Mid, Mid, End turned round), one per track,
/// running in opposite directions (Runtime/MetroTrain.cs). Material M_Train = Hanoi/Vehicle with the
/// livery atlas (data map B = LED strips / destination display glow), no paint cell.
/// Menu "Hanoi/Metro/Import Train".
/// </summary>
public static class MetroTrains
{
    const string Root = "Assets/Hanoi/Metro";
    const string ModelsDir = Root + "/Models";
    const string TexDir = Root + "/Textures";
    static readonly string[] Ids = { "SM_Train_End", "SM_Train_Mid" };
    static readonly float[] LodHeights = { 0.25f, 0.06f, 0.004f };     // 20 m car: LOD1 ~80 m, LOD2 ~330 m, culled ~5 km
    const float TrackOffset = 2f;                                      // = metro.json track_spacing / 2

    static string ExportDir => Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, "../Export/Metro"));
    static string PrefabPath(string id) => $"{Root}/{id}.prefab";

    [Serializable] class CarJ { public string name, kind; public float length, front, rear; public float[] bogies; }
    [Serializable] class TrainJ { public float gap; public CarJ[] cars; }

    static TrainJ Spec() => JsonUtility.FromJson<TrainJ>(File.ReadAllText(Path.Combine(ExportDir, "train.json")));

    static Texture2D ImportTex(string file, bool albedo)
    {
        Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, TexDir));
        string dst = $"{TexDir}/{file}";
        File.Copy(Path.Combine(ExportDir, "Train", file), Path.Combine(HanoiSetup.ProjectDir, dst), true);
        AssetDatabase.ImportAsset(dst, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
        var imp = (TextureImporter)AssetImporter.GetAtPath(dst);
        imp.textureType = TextureImporterType.Default;
        imp.sRGBTexture = albedo;
        imp.alphaSource = TextureImporterAlphaSource.None;   // opaque: the vehicle shader's clip passes
        imp.mipmapEnabled = true;
        imp.maxTextureSize = 4096;
        imp.anisoLevel = 8;
        imp.wrapMode = TextureWrapMode.Clamp;
        imp.filterMode = FilterMode.Trilinear;
        var ps = imp.GetDefaultPlatformTextureSettings();
        ps.textureCompression = TextureImporterCompression.CompressedHQ;
        imp.SetPlatformTextureSettings(ps);
        imp.SaveAndReimport();
        return AssetDatabase.LoadAssetAtPath<Texture2D>(dst);
    }

    static Material TrainMaterial()
    {
        var m = HanoiSetup.MaterialAsset("M_Train", "Hanoi/Vehicle");
        m.SetTexture("_BaseMap", ImportTex("T_Train.png", true));
        m.SetTexture("_DataMap", ImportTex("T_TrainData.png", false));
        m.SetFloat("_Cutoff", 0.5f);
        m.SetFloat("_EmissionGain", 1.5f);
        m.SetVector("_PaintRect", new Vector4(2f, 2f, 3f, 3f));       // no paint cell
        m.SetColor("_PaintColor", Color.white);
        EditorUtility.SetDirty(m);
        AssetDatabase.SaveAssets();
        return m;
    }

    [MenuItem("Hanoi/Metro/Import Train")]
    public static void ImportTrain()
    {
        Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, ModelsDir));
        var mat = TrainMaterial();
        foreach (var id in Ids)
        {
            string path = $"{ModelsDir}/{id}.fbx";
            File.Copy(Path.Combine(ExportDir, "FBX", id + ".fbx"), Path.Combine(HanoiSetup.ProjectDir, path), true);
            AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
            var imp = (ModelImporter)AssetImporter.GetAtPath(path);
            imp.importNormals = ModelImporterNormals.Import;
            imp.importTangents = ModelImporterTangents.None;
            imp.importAnimation = false; imp.importCameras = false; imp.importLights = false;
            imp.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
            imp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "M_Train"), mat);
            imp.SaveAndReimport();

            var go = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(path));
            go.name = id;
            var lg = HanoiSetup.SetupLods(go, LodHeights);
            foreach (var r in go.GetComponentsInChildren<Renderer>())
            {
                r.sharedMaterial = mat;
                r.shadowCastingMode = ShadowCastingMode.On;
            }
            var b = go.GetComponentsInChildren<Renderer>().Select(r => r.bounds).Aggregate((x, y) => { x.Encapsulate(y); return x; });
            var tris = string.Join(", ", lg.GetLODs().Select((l, i) =>
                $"LOD{i} {l.renderers.Sum(r => r.GetComponent<MeshFilter>().sharedMesh.triangles.Length / 3)}"));
            Debug.Log($"[Train] {id}: {lg.lodCount} LODs ({tris}), bounds centre {b.center:F2} size {b.size:F2}");
            PrefabUtility.SaveAsPrefabAsset(go, PrefabPath(id));
            UnityEngine.Object.DestroyImmediate(go);
        }
        AssetDatabase.SaveAssets();
    }

    /// Two trains under `parent`: A on the right-hand track running towards increasing arc length,
    /// B on the other track running back. startA / startB = head arc lengths in edit mode.
    public static MetroTrain[] Spawn(MetroLine line, Transform parent, float startA, float startB)
    {
        if (AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath(Ids[0])) == null) ImportTrain();
        var spec = Spec();
        var end = spec.cars.First(c => c.kind == "end");
        var mid = spec.cars.First(c => c.kind == "mid");
        var consist = new[] { (end, false), (mid, false), (mid, false), (end, true) };
        var root = new GameObject("Trains").transform;
        root.SetParent(parent, false);
        var result = new MetroTrain[2];
        for (int k = 0; k < 2; k++)
        {
            var go = new GameObject(k == 0 ? "Train_A" : "Train_B");
            go.transform.SetParent(root, false);
            var tr = go.AddComponent<MetroTrain>();
            tr.line = line;
            tr.direction = k == 0 ? 1 : -1;
            tr.trackOffset = k == 0 ? TrackOffset : -TrackOffset;
            tr.startS = k == 0 ? startA : startB;
            float off = 0f;
            for (int i = 0; i < consist.Length; i++)
            {
                var (car, turned) = consist[i];
                if (i > 0) off += spec.gap;
                off += car.length / 2f;
                var inst = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath(car.name)), go.transform);
                inst.name = $"{go.name}_Car{i}";
                tr.cars.Add(new MetroTrain.Car
                {
                    t = inst.transform, offset = off, turned = turned,
                    bogieA = turned ? -car.bogies[1] : car.bogies[0],
                    bogieB = turned ? -car.bogies[0] : car.bogies[1],
                });
                off += car.length / 2f;
            }
            tr.length = off;
            tr.PlaceAt(tr.startS);
            result[k] = tr;
        }
        return result;
    }
}
