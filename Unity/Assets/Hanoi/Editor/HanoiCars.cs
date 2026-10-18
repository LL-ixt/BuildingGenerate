using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// CAR C4: VinFast LUX A2.0 (Blender/scripts/build_car.py -> Export/Vehicles: FBX, baked textures, vehicles.json)
/// as Unity prefabs, a gallery and a physics test. Source model CC-BY-4.0 (vehicles.json "credit").
/// Menu "Hanoi/Cars/..." or batch: -executeMethod HanoiCars.RunBatch
/// Prefabs (Assets/Hanoi/Vehicles/Prefabs):
///   SM_Car_LuxA2_C0..C5  parked car, one prefab per paint colour (merged mesh per LOD), static BoxCollider.
///   SM_Car_LuxA2_Rig     driving car: Body, SteerFL/FR > WheelFL/FR, WheelRL/RR pivots + CarRig (kinematic
///                        Drive() or AddPhysics() -> Rigidbody + WheelColliders).
/// Materials M_Car_0..5 (Hanoi/Vehicle, _PaintMaskMode 1): baked albedo / data (A = paint mask) / normal map.
/// </summary>
public static class HanoiCars
{
    const string Root = "Assets/Hanoi/Vehicles";
    const string ModelsDir = Root + "/Models";
    const string PrefabDir = Root + "/Prefabs";
    const string TexDir = Root + "/Textures";
    const string GalleryScene = Root + "/CarGallery.unity";
    const string PhysicsScene = Root + "/CarPhysicsTest.unity";
    public const string ParkedId = "SM_Car_LuxA2";
    const string RigId = "SM_Car_LuxA2_Rig";

    // paint colours (sRGB, = hanoi_car.PAINT_COLOURS) and how common they are on Hanoi streets
    internal static readonly Color[] Paints =
    {
        new Color(0.92f, 0.92f, 0.90f), new Color(0.05f, 0.05f, 0.06f), new Color(0.62f, 0.64f, 0.66f),
        new Color(0.62f, 0.06f, 0.07f), new Color(0.08f, 0.14f, 0.32f), new Color(0.36f, 0.37f, 0.39f),
    };
    static readonly string[] PaintNames = { "white", "black", "silver", "red", "blue", "grey" };
    internal static readonly float[] PaintWeights = { 0.30f, 0.22f, 0.18f, 0.10f, 0.08f, 0.12f };

    // LODGroup size ~5 m, 60 deg FOV: LOD1 from ~40 m, LOD2 from ~90 m, culled past ~300 m
    internal static readonly float[] CarLodHeights = { 0.11f, 0.045f, 0.012f };

    static string ExportDir => Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, "../Export/Vehicles"));
    static string ColourId(int k) => $"{ParkedId}_C{k}";

    internal static int PickPaint(double u)
    {
        double acc = 0;
        for (int i = 0; i < PaintWeights.Length; i++)
            if (u < (acc += PaintWeights[i])) return i;
        return PaintWeights.Length - 1;
    }

    // ------------------------------------------------------------------ assets
    enum TexKind { Albedo, Data, Normal }

    static Texture2D ImportTex(string file, TexKind kind)
    {
        Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, TexDir));
        string dst = $"{TexDir}/{file}";
        File.Copy(Path.Combine(ExportDir, "Textures", file), Path.Combine(HanoiSetup.ProjectDir, dst), true);
        AssetDatabase.ImportAsset(dst, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
        var imp = (TextureImporter)AssetImporter.GetAtPath(dst);
        imp.textureType = kind == TexKind.Normal ? TextureImporterType.NormalMap : TextureImporterType.Default;
        imp.sRGBTexture = kind == TexKind.Albedo;
        // data: alpha = paint mask, kept as is
        imp.alphaSource = kind == TexKind.Data ? TextureImporterAlphaSource.FromInput : TextureImporterAlphaSource.None;
        imp.alphaIsTransparency = false;
        imp.mipmapEnabled = true;
        imp.maxTextureSize = 1024;
        imp.anisoLevel = 8;
        imp.wrapMode = TextureWrapMode.Clamp;
        imp.filterMode = FilterMode.Trilinear;
        var ps = imp.GetDefaultPlatformTextureSettings();
        ps.textureCompression = TextureImporterCompression.CompressedHQ;
        imp.SetPlatformTextureSettings(ps);
        imp.SaveAndReimport();
        return AssetDatabase.LoadAssetAtPath<Texture2D>(dst);
    }

    internal static Material[] CarMaterials()
    {
        var albedo = ImportTex("T_CarBody.png", TexKind.Albedo);
        var data = ImportTex("T_CarBodyData.png", TexKind.Data);
        var normal = ImportTex("T_CarBody_N.png", TexKind.Normal);
        var mats = new Material[Paints.Length];
        for (int k = 0; k < Paints.Length; k++)
        {
            var mat = HanoiSetup.MaterialAsset($"M_Car_{k}", "Hanoi/Vehicle");
            mat.SetTexture("_BaseMap", albedo);
            mat.SetTexture("_DataMap", data);
            mat.SetTexture("_BumpMap", normal);
            mat.SetFloat("_BumpScale", 1f);
            mat.SetFloat("_Cutoff", 0f);                       // nothing to clip on the car
            mat.SetFloat("_PaintMaskMode", 1f);
            mat.SetVector("_PaintRect", new Vector4(-1f, -1f, -1f, -1f));
            mat.SetColor("_PaintColor", Paints[k]);
            EditorUtility.SetDirty(mat);
            mats[k] = mat;
        }
        AssetDatabase.SaveAssets();
        return mats;
    }

    static GameObject ImportModel(string id, Material mat)
    {
        string dst = $"{ModelsDir}/{id}.fbx";
        File.Copy(Path.Combine(ExportDir, "FBX", id + ".fbx"), Path.Combine(HanoiSetup.ProjectDir, dst), true);
        AssetDatabase.ImportAsset(dst, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
        var imp = (ModelImporter)AssetImporter.GetAtPath(dst);
        imp.importNormals = ModelImporterNormals.Import;              // Blender's smooth-by-angle
        imp.importTangents = ModelImporterTangents.CalculateMikk;     // = Blender's baking tangents
        imp.importAnimation = false; imp.importCameras = false; imp.importLights = false;
        imp.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
        imp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "M_CarLuxA2"), mat);
        imp.SaveAndReimport();
        return AssetDatabase.LoadAssetAtPath<GameObject>(dst);
    }

    /// Body box from the LOD0 renderers' bounds (car space), bottom at the sill height, the wheels left out.
    static (Vector3 center, Vector3 size) BodyBox(GameObject go, string lod0Name)
    {
        var r = go.GetComponentsInChildren<MeshRenderer>().First(x => x.name == lod0Name);
        var b = r.GetComponent<MeshFilter>().sharedMesh.bounds;
        var m = go.transform.worldToLocalMatrix * r.transform.localToWorldMatrix;
        var c = m.MultiplyPoint3x4(b.center);
        float bottom = 0.25f, top = c.y + b.extents.y;
        return (new Vector3(c.x, (bottom + top) / 2f, c.z), new Vector3(b.size.x * 0.95f, top - bottom, b.size.z * 0.98f));
    }

    [MenuItem("Hanoi/Cars/Import Cars")]
    public static void ImportCars()
    {
        foreach (var d in new[] { ModelsDir, PrefabDir, TexDir })
            Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, d));
        var mats = CarMaterials();
        var sh = Shader.Find("Hanoi/Vehicle");
        Debug.Log($"[Cars] shader Hanoi/Vehicle: found={sh != null} hasError={(sh != null && ShaderUtil.ShaderHasError(sh))}");
        if (sh != null)
            foreach (var msg in ShaderUtil.GetShaderMessages(sh))
                Debug.Log($"[Cars]   {msg.severity} {msg.file}:{msg.line} {msg.message}");

        // parked: one prefab per paint colour, static collider
        var model = ImportModel(ParkedId, mats[0]);
        for (int k = 0; k < mats.Length; k++)
        {
            var go = (GameObject)PrefabUtility.InstantiatePrefab(model);
            go.name = ColourId(k);
            HanoiSetup.SetupLods(go, CarLodHeights);
            foreach (var r in go.GetComponentsInChildren<Renderer>())
            {
                r.sharedMaterial = mats[k];
                r.shadowCastingMode = r.name.EndsWith("_LOD2") ? ShadowCastingMode.Off : ShadowCastingMode.On;
            }
            var (c, s) = BodyBox(go, $"{ParkedId}_LOD0");
            var box = go.AddComponent<BoxCollider>();
            box.center = c; box.size = s;
            if (k == 0) Report(go);
            PrefabUtility.SaveAsPrefabAsset(go, $"{PrefabDir}/{ColourId(k)}.prefab");
            Object.DestroyImmediate(go);
        }
        Debug.Log($"[Cars] colour prefabs: {string.Join(", ", PaintNames.Select((n, k) => $"C{k} {n}"))}");

        // rig: the FBX is flat -> pivots rebuilt here (steer pivots hold the front wheels)
        model = ImportModel(RigId, mats[0]);
        var rigGo = (GameObject)PrefabUtility.InstantiatePrefab(model);
        PrefabUtility.UnpackPrefabInstance(rigGo, PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
        Transform Pivot(string part, Transform parent)
        {
            var src = rigGo.transform.Find(part + "_LOD0");
            var p = new GameObject(part).transform;
            p.SetParent(parent, false);
            p.position = src.position;
            foreach (var t in rigGo.GetComponentsInChildren<Transform>().Where(t => t.name.StartsWith(part + "_LOD")).ToArray())
                t.SetParent(p, true);
            return p;
        }
        var rig = rigGo.AddComponent<CarRig>();
        rig.body = Pivot("Body", rigGo.transform);
        rig.steerFL = new GameObject("SteerFL").transform; rig.steerFL.SetParent(rigGo.transform, false);
        rig.steerFR = new GameObject("SteerFR").transform; rig.steerFR.SetParent(rigGo.transform, false);
        rig.steerFL.position = rigGo.transform.Find("WheelFL_LOD0").position;
        rig.steerFR.position = rigGo.transform.Find("WheelFR_LOD0").position;
        rig.wheelFL = Pivot("WheelFL", rig.steerFL);
        rig.wheelFR = Pivot("WheelFR", rig.steerFR);
        rig.wheelRL = Pivot("WheelRL", rigGo.transform);
        rig.wheelRR = Pivot("WheelRR", rigGo.transform);
        rig.wheelRadius = rig.wheelFL.position.y;                  // axle height = radius (tyres on y = 0)
        (rig.boxCenter, rig.boxSize) = BodyBox(rigGo, "Body_LOD0");
        HanoiSetup.SetupLods(rigGo, CarLodHeights);
        foreach (var r in rigGo.GetComponentsInChildren<Renderer>())
        {
            r.sharedMaterial = mats[0];
            r.shadowCastingMode = r.name.EndsWith("_LOD2") ? ShadowCastingMode.Off : ShadowCastingMode.On;
        }
        Report(rigGo);
        PrefabUtility.SaveAsPrefabAsset(rigGo, $"{PrefabDir}/{RigId}.prefab");
        Object.DestroyImmediate(rigGo);
        AssetDatabase.SaveAssets();
    }

    static void Report(GameObject go)
    {
        var lg = go.GetComponent<LODGroup>();
        var tris = string.Join(", ", lg.GetLODs().Select((l, i) =>
            $"LOD{i} {l.renderers.Sum(r => r.GetComponent<MeshFilter>().sharedMesh.triangles.Length / 3)}"));
        var lo = go.GetComponentsInChildren<MeshRenderer>().Min(r => r.bounds.min.y);
        Debug.Log($"[Cars] {go.name}: {lg.lodCount} LODs ({tris}), size {lg.size:F2} m, lowest point y {lo:F4}");
    }

    public static GameObject LoadPrefab(string id) => AssetDatabase.LoadAssetAtPath<GameObject>($"{PrefabDir}/{id}.prefab");
    public static GameObject LoadParked(int k) => LoadPrefab(ColourId(k));

    // ------------------------------------------------------------------ gallery
    [MenuItem("Hanoi/Cars/Build Car Gallery")]
    public static void BuildGallery()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
        HanoiLighting.Apply();
        var cam = Camera.main;
        cam.farClipPlane = 2000f; cam.nearClipPlane = 0.05f; cam.fieldOfView = 60f;
        var asphalt = HanoiSetup.LitMaterial("M_Asphalt", new Color(0.18f, 0.18f, 0.19f), 0.2f);
        HanoiSetup.Box("Ground", new Vector3(0, -0.05f, 0), new Vector3(1000, 0.1f, 1000), asphalt);
        var root = new GameObject("CarGallery").transform;
        // a row of parked cars along X, one per colour, + a bike for scale
        for (int k = 0; k < Paints.Length; k++)
        {
            var c = (GameObject)PrefabUtility.InstantiatePrefab(LoadParked(k), root);
            c.transform.SetPositionAndRotation(new Vector3((k - 2.5f) * 2.6f, 0f, 0f), Quaternion.identity);
        }
        var bike = HanoiMotos.LoadParked(0);
        if (bike != null)
        {
            var b = (GameObject)PrefabUtility.InstantiatePrefab(bike, root);
            b.transform.SetPositionAndRotation(new Vector3(9.5f, 0f, 0f), Quaternion.identity);
        }
        // LOD comparison and the rig (steered), away from the row
        var lodRoot = new GameObject("LodCompare").transform;
        for (int k = 0; k < 3; k++)
        {
            var c = (GameObject)PrefabUtility.InstantiatePrefab(LoadParked(3), lodRoot);
            c.name = $"Car_forceLOD{k}";
            c.transform.SetPositionAndRotation(new Vector3(200f + k * 2.6f, 0f, 200f), Quaternion.identity);
        }
        var rig = (GameObject)PrefabUtility.InstantiatePrefab(LoadPrefab(RigId), lodRoot);
        rig.transform.SetPositionAndRotation(new Vector3(200f + 9f, 0f, 200f), Quaternion.identity);
        rig.GetComponent<CarRig>().Drive(0.7f, 25f);                  // steered + rolled, to show the pivots
        EditorSceneManager.SaveScene(scene, GalleryScene);
        Debug.Log($"[Cars] gallery -> {GalleryScene}");
        CaptureShots();
    }

    [MenuItem("Hanoi/Cars/Capture Car Shots")]
    public static void CaptureShots()
    {
        if (EditorSceneManager.GetActiveScene().path != GalleryScene)
            EditorSceneManager.OpenScene(GalleryScene);
        EditorSettings.asyncShaderCompilation = false;
        var cam = Camera.main;
        HanoiSetup.Shot(cam, "car_c4_1_row", new Vector3(-9f, 2.4f, 9.5f), new Vector3(0f, 0.6f, 0f));
        HanoiSetup.Shot(cam, "car_c4_2_front", new Vector3(-2.2f, 1.3f, 5.6f), new Vector3(-3.9f, 0.7f, 0f));   // nose = +z
        HanoiSetup.Shot(cam, "car_c4_3_rear", new Vector3(5.5f, 1.5f, -6.5f), new Vector3(3.9f, 0.7f, 0f));
        HanoiSetup.Shot(cam, "car_c4_4_wheel", new Vector3(-6.0f, 0.6f, -2.3f), new Vector3(-7.3f, 0.35f, -1.45f));
        var groups = Object.FindObjectsByType<LODGroup>(FindObjectsSortMode.None).Where(g => g.name.Contains("_forceLOD")).ToArray();
        foreach (var g in groups) g.ForceLOD(int.Parse(g.name.Substring(g.name.Length - 1)));
        HanoiSetup.Shot(cam, "car_c4_5_lods_rig", new Vector3(206f, 2.6f, 191f), new Vector3(206f, 0.6f, 200f));
        foreach (var g in groups) g.ForceLOD(-1);
        Debug.Log($"[Cars] shots in {HanoiSetup.ShotsDir}");
    }

    // ------------------------------------------------------------------ physics test
    /// The rig with AddPhysics() dropped on a flat ground (scripted simulation): it must settle on its four
    /// wheels at the modelled ride height, then drive straight and turn. Saves CarPhysicsTest.unity (press Play,
    /// arrow keys = CarTestDrive).
    [MenuItem("Hanoi/Cars/Physics Test")]
    public static void PhysicsTest()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
        HanoiLighting.Apply();
        var asphalt = HanoiSetup.LitMaterial("M_Asphalt", new Color(0.18f, 0.18f, 0.19f), 0.2f);
        HanoiSetup.Box("Ground", new Vector3(0, -0.05f, 0), new Vector3(1000, 0.1f, 1000), asphalt);
        GameObject.Find("Ground").AddComponent<BoxCollider>();      // HanoiSetup.Box drops colliders; top y = 0
        var go =(GameObject)PrefabUtility.InstantiatePrefab(LoadPrefab(RigId));
        go.transform.position = new Vector3(0f, 0.3f, 0f);           // dropped from 30 cm
        var rig = go.GetComponent<CarRig>();
        var rb = rig.AddPhysics();
        go.AddComponent<CarTestDrive>();
        Physics.SyncTransforms();

        var mode = Physics.simulationMode;
        Physics.simulationMode = SimulationMode.Script;
        const float dt = 0.02f;
        void Run(float seconds, float torque, float steer)
        {
            rig.SetControls(torque, steer);
            for (float t = 0; t < seconds; t += dt) { Physics.Simulate(dt); rig.SyncWheels(); }
        }
        float axleModel = rig.wheelRadius;
        Run(3f, 0f, 0f);
        float restY = go.transform.position.y;
        float wheelY = (rig.wheelFL.position.y + rig.wheelFR.position.y + rig.wheelRL.position.y + rig.wheelRR.position.y) / 4f;
        float tilt = Vector3.Angle(go.transform.up, Vector3.up);
        bool grounded = rig.colFL.isGrounded && rig.colFR.isGrounded && rig.colRL.isGrounded && rig.colRR.isGrounded;
        Debug.Log($"[Cars] physics rest: root y {restY:F3} (0 = modelled ride height), wheel centres y {wheelY:F3} " +
                  $"(axle {axleModel:F3}), tilt {tilt:F2} deg, all wheels grounded {grounded}, colliderLift {rig.colliderLift}");
        HanoiSetup.Shot(Camera.main, "car_c4_6_physics_rest", go.transform.position + new Vector3(-5f, 1.2f, -4f), go.transform.position + Vector3.up * 0.5f);

        var p0 = go.transform.position;
        Run(4f, 900f, 0f);
        var p1 = go.transform.position;
        float speed = rb.linearVelocity.magnitude;
        Run(3f, 600f, 25f);
        var p2 = go.transform.position;
        float yaw = Vector3.SignedAngle(Vector3.forward, go.transform.forward, Vector3.up);
        Run(3f, 0f, 0f);
        rig.SetControls(0f, 0f, 3000f);
        for (float t = 0; t < 2f; t += dt) { Physics.Simulate(dt); rig.SyncWheels(); }
        float minY = Mathf.Min(p1.y, p2.y, go.transform.position.y);
        Debug.Log($"[Cars] physics drive: straight 4 s -> {Vector3.Distance(p0, p1):F1} m along z {p1.z - p0.z:F1}, " +
                  $"speed {speed * 3.6f:F0} km/h; steering 3 s -> yaw {yaw:F0} deg; root y stays {minY:F3}..; " +
                  $"after braking speed {rb.linearVelocity.magnitude * 3.6f:F1} km/h, grounded " +
                  $"{rig.colFL.isGrounded && rig.colFR.isGrounded && rig.colRL.isGrounded && rig.colRR.isGrounded}");
        HanoiSetup.Shot(Camera.main, "car_c4_7_physics_drive", go.transform.position + new Vector3(-6f, 2f, -5f), go.transform.position + Vector3.up * 0.5f);
        Physics.simulationMode = mode;

        // the saved scene starts from rest at the origin (Play: arrow keys)
        go.transform.SetPositionAndRotation(new Vector3(0f, restY, 0f), Quaternion.identity);
        rb.linearVelocity = Vector3.zero; rb.angularVelocity = Vector3.zero;
        Camera.main.transform.SetPositionAndRotation(new Vector3(0f, 3f, -8f), Quaternion.Euler(12f, 0f, 0f));
        EditorSceneManager.SaveScene(scene, PhysicsScene);
    }

    public static void RunBatch()
    {
        ImportCars();
        BuildGallery();
        PhysicsTest();
    }
}
