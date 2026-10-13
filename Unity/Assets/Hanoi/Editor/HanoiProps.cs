using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// Street props from Blender (Export/Props: build_props.py -> SM_SignNgo / SM_PowerPole with the
/// props atlas, build_cart.py -> SM_Cart_Rac with the vehicle atlas) as prefabs with LODGroups, placed
/// in the city from Map/osm_pipeline.place_props (city.json chunk.prop = [x, z, kind, yaw]) by
/// CityPlacer.PlaceProps. Kind index = Ids (0 sign at sidewalk corners / alley mouths, 1 power pole,
/// 2 garbage cart). Menu "Hanoi/Props/..." or batch -executeMethod HanoiProps.RunCityBatch.
/// Materials (Hanoi/Vehicle, no per-instance data): M_StreetProps = props atlas, no paint cell;
/// M_Cart = the moto atlas with the green paint of Ref/xe rac.jpg.
/// </summary>
public static class HanoiProps
{
    const string Root = "Assets/Hanoi/Props";
    const string ModelsDir = Root + "/Models";
    const string PrefabDir = Root + "/Prefabs";
    const string TexDir = Root + "/Textures";
    public static readonly string[] Ids = { "SM_SignNgo", "SM_PowerPole", "SM_Cart_Rac" };
    // LODGroup heights per kind: sign 3 m (LOD1 ~20 m, culled ~130 m), pole 8.5 m (LOD1 ~60 m,
    // culled ~900 m: seen above the roofs), cart 1.7 m (like the parked bikes)
    static readonly float[][] LodHeights = { new[] { 0.10f, 0.015f }, new[] { 0.12f, 0.008f }, new[] { 0.11f, 0.05f, 0.018f } };
    static readonly Color CartGreen = new Color(88 / 255f, 190 / 255f, 52 / 255f);

    static string ExportDir => Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, "../Export/Props"));

    static Texture2D ImportTex(string file, bool albedo)
    {
        Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, TexDir));
        string dst = $"{TexDir}/{file}";
        File.Copy(Path.Combine(ExportDir, "Textures", file), Path.Combine(HanoiSetup.ProjectDir, dst), true);
        AssetDatabase.ImportAsset(dst, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
        var imp = (TextureImporter)AssetImporter.GetAtPath(dst);
        imp.textureType = TextureImporterType.Default;
        imp.sRGBTexture = albedo;                          // data map = linear roughness / metallic
        imp.alphaSource = TextureImporterAlphaSource.None; // opaque: alpha reads 1, the vehicle clip passes
        imp.mipmapEnabled = true;
        imp.maxTextureSize = 2048;
        imp.anisoLevel = 8;
        imp.wrapMode = TextureWrapMode.Clamp;
        imp.filterMode = FilterMode.Trilinear;
        var ps = imp.GetDefaultPlatformTextureSettings();
        ps.textureCompression = TextureImporterCompression.CompressedHQ;
        imp.SetPlatformTextureSettings(ps);
        imp.SaveAndReimport();
        return AssetDatabase.LoadAssetAtPath<Texture2D>(dst);
    }

    static (Material props, Material cart) Materials()
    {
        var props = HanoiSetup.MaterialAsset("M_StreetProps", "Hanoi/Vehicle");
        props.SetTexture("_BaseMap", ImportTex("T_StreetProps.png", true));
        props.SetTexture("_DataMap", ImportTex("T_StreetPropsData.png", false));
        props.SetFloat("_Cutoff", 0.5f);
        props.SetVector("_PaintRect", new Vector4(2f, 2f, 3f, 3f));      // no paint cell in this atlas
        props.SetColor("_PaintColor", Color.white);
        EditorUtility.SetDirty(props);

        var moto = HanoiMotos.MotoMaterials();                            // imports the vehicle atlas
        var cart = HanoiSetup.MaterialAsset("M_Cart", "Hanoi/Vehicle");
        cart.CopyPropertiesFromMaterial(moto[0]);
        cart.SetColor("_PaintColor", CartGreen);
        EditorUtility.SetDirty(cart);
        AssetDatabase.SaveAssets();
        return (props, cart);
    }

    [MenuItem("Hanoi/Props/Import Props")]
    public static void ImportProps()
    {
        foreach (var d in new[] { ModelsDir, PrefabDir, TexDir })
            Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, d));
        var (propsMat, cartMat) = Materials();
        for (int k = 0; k < Ids.Length; k++)
        {
            string id = Ids[k];
            var mat = id == "SM_Cart_Rac" ? cartMat : propsMat;
            File.Copy(Path.Combine(ExportDir, "FBX", id + ".fbx"), Path.Combine(HanoiSetup.ProjectDir, ModelsDir, id + ".fbx"), true);
            string path = $"{ModelsDir}/{id}.fbx";
            AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
            var imp = (ModelImporter)AssetImporter.GetAtPath(path);
            imp.importNormals = ModelImporterNormals.Import;
            imp.importTangents = ModelImporterTangents.None;
            imp.importAnimation = false; imp.importCameras = false; imp.importLights = false;
            imp.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
            imp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "M_HanoiProps"), propsMat);
            imp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "M_HanoiMoto"), cartMat);
            imp.SaveAndReimport();

            var go = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(path));
            go.name = id;
            var lg = HanoiSetup.SetupLods(go, LodHeights[k]);
            foreach (var r in go.GetComponentsInChildren<Renderer>())
            {
                r.sharedMaterial = mat;
                r.shadowCastingMode = ShadowCastingMode.On;
            }
            var tris = string.Join(", ", lg.GetLODs().Select((l, i) =>
                $"LOD{i} {l.renderers.Sum(r => r.GetComponent<MeshFilter>().sharedMesh.triangles.Length / 3)}"));
            Debug.Log($"[Props] {id}: {lg.lodCount} LODs ({tris}), size {lg.size:F2} m, material {mat.name}");
            PrefabUtility.SaveAsPrefabAsset(go, $"{PrefabDir}/{id}.prefab");
            Object.DestroyImmediate(go);
        }
        AssetDatabase.SaveAssets();
    }

    public static GameObject LoadPrefab(int kind) =>
        kind >= 0 && kind < Ids.Length ? AssetDatabase.LoadAssetAtPath<GameObject>($"{PrefabDir}/{Ids[kind]}.prefab") : null;

    // ------------------------------------------------------------------ city shots
    [System.Serializable] class ShotJ { public string name; public float[] camera, target; }
    [System.Serializable] class ShotsJ { public ShotJ[] shots; }

    /// Street views with signs, a pole, parked bikes, trees and a cart: spots and cameras picked by
    /// Map/find_props_shot.py (camera on the street centreline at eye height, + a higher view).
    [MenuItem("Hanoi/Props/City Props Shots")]
    public static void CityShots()
    {
        EditorSettings.asyncShaderCompilation = false;
        EditorSceneManager.OpenScene("Assets/Hanoi/City/City_Main.unity", OpenSceneMode.Single);
        var reg = Object.FindFirstObjectByType<CityChunks>();
        var cam = Camera.main;
        var all = JsonUtility.FromJson<ShotsJ>(File.ReadAllText(Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, "../Map/out/props_shot.json"))));
        foreach (var s in all.shots)
        {
            var pos = new Vector3(s.camera[0], s.camera[1], s.camera[2]);
            var tgt = new Vector3(s.target[0], s.target[1], s.target[2]);
            HanoiTrees.LoadAround(reg, tgt, 300f);
            HanoiSetup.Shot(cam, s.name, pos, tgt);
        }
        Debug.Log($"[Props] {all.shots.Length} city shots in {HanoiSetup.ShotsDir}");
    }

    /// Whole chain after the props or their layout changed: import, place the city, HLOD, shots.
    public static void RunCityBatch()
    {
        CityBenchmarkBuild.ConfigureRendering();
        HanoiTrees.ImportTrees();
        HanoiMotos.ImportMotos();
        ImportProps();
        CityPlacer.Run();
        ChunkBuilder.Run();
        CityShots();
    }
}
