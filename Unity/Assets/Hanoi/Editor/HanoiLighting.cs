using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// One look for every Hanoi scene: hazy noon sun. HDRI sky (Export/Textures/Sky, built by
/// Blender/scripts/build_sky_hdri.py) drives skybox + ambient + reflections; the Directional Light is
/// the sun, aimed where the HDRI's sun is; exponential fog in the HDRI horizon colour.
public static class HanoiLighting
{
    const string Dir = "Assets/Hanoi/Lighting";
    const string HdriName = "HDRI_HanoiDay.hdr";
    const string SkyMatPath = Dir + "/M_SkyHanoiDay.mat";
    const string PipelinePath = "Assets/Settings/PC_RPAsset.asset";

    // written by build_sky_hdri.py next to the .hdr: sun pixel u, elevation, horizon colour
    [System.Serializable]
    class SkyInfo { public float sun_u = 0.5f, sun_elevation = 45f; public float[] horizon = { 0.65f, 0.72f, 0.81f }; }

    static SkyInfo Sky()
    {
        string json = Path.Combine(HanoiSetup.ProjectDir, "../Export/Textures/Sky", Path.ChangeExtension(HdriName, ".json"));
        return File.Exists(json) ? JsonUtility.FromJson<SkyInfo>(File.ReadAllText(json)) : new SkyInfo();
    }

    public const float SunIntensity = 2.6f, SunKelvin = 5600f;
    public const float FogDensity = 0.0015f;
    public const float ShadowDistance = 150f;

    [MenuItem("Hanoi/Lighting/Apply to Open Scene")]
    public static void ApplyMenu()
    {
        Apply();
        BakeEnvironment();
        EditorSceneManager.MarkSceneDirty(EditorSceneManager.GetActiveScene());
    }

    /// Sky, ambient, sun, fog on the active scene + shadow settings on the PC pipeline asset.
    public static Light Apply()
    {
        var sky = Sky();
        RenderSettings.skybox = SkyMaterial();
        RenderSettings.ambientMode = AmbientMode.Skybox;
        RenderSettings.ambientIntensity = 1f;
        RenderSettings.defaultReflectionMode = DefaultReflectionMode.Skybox;
        RenderSettings.defaultReflectionResolution = 256;
        RenderSettings.reflectionIntensity = 1f;

        RenderSettings.fog = true;
        RenderSettings.fogMode = FogMode.ExponentialSquared;
        RenderSettings.fogDensity = FogDensity;
        RenderSettings.fogColor = new Color(sky.horizon[0], sky.horizon[1], sky.horizon[2]);

        var sun = Object.FindAnyObjectByType<Light>();
        if (sun == null)
            sun = new GameObject("Directional Light").AddComponent<Light>();
        sun.type = LightType.Directional;
        sun.transform.rotation = Quaternion.LookRotation(-SunDirection(sky));
        sun.useColorTemperature = true;
        sun.colorTemperature = SunKelvin;
        sun.color = Color.white;
        sun.intensity = SunIntensity;
        sun.shadows = LightShadows.Soft;
        sun.shadowStrength = 1f;
        RenderSettings.sun = sun;

        ConfigurePipeline();
        ConfigureSsao();
        ApplyPostProcessing();
        return sun;
    }

    /// Global Volume with VP_HanoiDay + post-processing / SMAA on the main camera (FlyCamera reuses it).
    public static void ApplyPostProcessing()
    {
        var vol = Object.FindAnyObjectByType<Volume>();
        if (vol == null)
            vol = new GameObject("GlobalVolume").AddComponent<Volume>();
        vol.isGlobal = true;
        vol.priority = 0;
        vol.sharedProfile = DayProfile();

        var cam = Camera.main;
        if (cam != null)
        {
            var data = cam.GetUniversalAdditionalCameraData();
            data.renderPostProcessing = true;
            data.antialiasing = AntialiasingMode.SubpixelMorphologicalAntiAliasing;
            data.antialiasingQuality = AntialiasingQuality.High;
            EditorUtility.SetDirty(data);
        }
    }

    public const string ProfilePath = Dir + "/VP_HanoiDay.asset";

    static VolumeProfile DayProfile()
    {
        var p = AssetDatabase.LoadAssetAtPath<VolumeProfile>(ProfilePath);
        if (p == null)
        {
            p = ScriptableObject.CreateInstance<VolumeProfile>();
            AssetDatabase.CreateAsset(p, ProfilePath);
        }

        var tm = Component<Tonemapping>(p);
        tm.mode.Override(TonemappingMode.ACES);

        var ca = Component<ColorAdjustments>(p);
        ca.postExposure.Override(0.35f);
        ca.contrast.Override(12f);
        ca.saturation.Override(-8f);

        var wb = Component<WhiteBalance>(p);
        wb.temperature.Override(6f);
        wb.tint.Override(0f);

        // cool shadows, warm highlights: tropical noon
        var smh = Component<ShadowsMidtonesHighlights>(p);
        smh.shadows.Override(new Vector4(0.96f, 0.99f, 1.06f, 0f));
        smh.midtones.Override(new Vector4(1f, 1f, 1f, 0f));
        smh.highlights.Override(new Vector4(1.04f, 1.01f, 0.96f, 0f));

        var bloom = Component<Bloom>(p);
        bloom.threshold.Override(1.1f);
        bloom.intensity.Override(0.25f);
        bloom.scatter.Override(0.6f);

        var vig = Component<Vignette>(p);
        vig.intensity.Override(0.15f);
        vig.smoothness.Override(0.4f);

        EditorUtility.SetDirty(p);
        AssetDatabase.SaveAssets();
        return p;
    }

    static T Component<T>(VolumeProfile p) where T : VolumeComponent
    {
        if (p.TryGet(out T c)) return c;
        c = p.Add<T>(true);
        c.name = typeof(T).Name;
        AssetDatabase.AddObjectToAsset(c, p);   // otherwise the override is lost on reload
        return c;
    }

    /// SSAO renderer feature on PC_Renderer: a wider radius darkens the gaps between tube houses,
    /// wall feet and the underside of eaves.
    static void ConfigureSsao()
    {
        foreach (var o in AssetDatabase.LoadAllAssetsAtPath(RendererPath))
        {
            if (o == null || o.GetType().Name != "ScreenSpaceAmbientOcclusion") continue;
            var so = new SerializedObject(o);
            so.FindProperty("m_Settings.Intensity").floatValue = 0.7f;
            so.FindProperty("m_Settings.Radius").floatValue = 1.0f;
            so.FindProperty("m_Settings.DirectLightingStrength").floatValue = 0.15f;
            so.ApplyModifiedPropertiesWithoutUndo();
        }
    }

    const string RendererPath = "Assets/Settings/PC_Renderer.asset";

    /// Ambient probe + default reflection from the skybox. Baked/realtime GI are off, so this only
    /// computes the environment (a second or two).
    public static void BakeEnvironment()
    {
        if (!Lightmapping.TryGetLightingSettings(out var settings))
        {
            const string path = Dir + "/LS_Hanoi.lighting";
            settings = AssetDatabase.LoadAssetAtPath<LightingSettings>(path);
            if (settings == null)
            {
                settings = new LightingSettings { name = "LS_Hanoi" };
                AssetDatabase.CreateAsset(settings, path);
            }
            Lightmapping.lightingSettings = settings;
        }
        settings.bakedGI = false;
        settings.realtimeGI = false;
        Lightmapping.Bake();
    }

    /// Unit vector towards the sun. Skybox/Panoramic samples u = 0.5 - atan2(z, x) / 2pi.
    static Vector3 SunDirection(SkyInfo sky)
    {
        float phi = (0.5f - sky.sun_u) * 2f * Mathf.PI;
        float el = sky.sun_elevation * Mathf.Deg2Rad;
        return new Vector3(Mathf.Cos(phi) * Mathf.Cos(el), Mathf.Sin(el), Mathf.Sin(phi) * Mathf.Cos(el)).normalized;
    }

    static Material SkyMaterial()
    {
        string dst = $"{Dir}/{HdriName}";
        string src = Path.Combine(HanoiSetup.ProjectDir, "../Export/Textures/Sky", HdriName);
        Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, Dir));
        if (!File.Exists(Path.Combine(HanoiSetup.ProjectDir, dst)) ||
            File.GetLastWriteTimeUtc(src) > File.GetLastWriteTimeUtc(Path.Combine(HanoiSetup.ProjectDir, dst)))
        {
            File.Copy(src, Path.Combine(HanoiSetup.ProjectDir, dst), true);
            AssetDatabase.ImportAsset(dst, ImportAssetOptions.ForceUpdate);
        }
        var imp = (TextureImporter)AssetImporter.GetAtPath(dst);
        if (imp.mipmapEnabled || imp.wrapModeU != TextureWrapMode.Repeat || imp.textureCompression != TextureImporterCompression.Uncompressed)
        {
            imp.textureShape = TextureImporterShape.Texture2D;
            imp.mipmapEnabled = false;           // mips leave a seam where u wraps
            imp.wrapModeU = TextureWrapMode.Repeat;
            imp.wrapModeV = TextureWrapMode.Clamp;
            imp.textureCompression = TextureImporterCompression.Uncompressed;
            imp.maxTextureSize = 2048;
            imp.SaveAndReimport();
        }
        var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(dst);

        var mat = AssetDatabase.LoadAssetAtPath<Material>(SkyMatPath);
        if (mat == null)
        {
            mat = new Material(Shader.Find("Skybox/Panoramic"));
            AssetDatabase.CreateAsset(mat, SkyMatPath);
        }
        mat.SetTexture("_MainTex", tex);
        mat.SetFloat("_Mapping", 1f);       // latitude-longitude
        mat.SetFloat("_ImageType", 0f);     // 360
        mat.SetFloat("_Rotation", 0f);
        mat.SetFloat("_Exposure", 1f);
        mat.SetColor("_Tint", new Color(0.5f, 0.5f, 0.5f));
        EditorUtility.SetDirty(mat);
        return mat;
    }

    static void ConfigurePipeline()
    {
        var asset = AssetDatabase.LoadAssetAtPath<UniversalRenderPipelineAsset>(PipelinePath);
        if (asset == null) return;
        asset.shadowDistance = ShadowDistance;
        asset.shadowCascadeCount = 4;
        asset.cascade4Split = new Vector3(6f, 20f, 50f) / ShadowDistance;
        asset.colorGradingMode = ColorGradingMode.HighDynamicRange;
        EditorUtility.SetDirty(asset);
    }
}
