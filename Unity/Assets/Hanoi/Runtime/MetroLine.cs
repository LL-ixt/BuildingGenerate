using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Splines;

/// <summary>
/// Elevated metro line (plan METRO V2): a hand-editable spline whose knots sit at RAIL TOP height.
/// Editor/MetroBuilder.cs sweeps the deck profiles of Export/Metro/metro.json along it and places
/// the piers (Export/Metro/FBX/SM_MetroPier.fbx) every ~span metres; the result goes under the
/// child "Generated" (never edit that by hand: it is rebuilt).
///
/// Lives in its own scene Assets/Hanoi/Metro/Metro.unity (CityPlacer rebuilds City_Main), loaded
/// additively next to the city (ChunkStreamer.Bootstrap, CityPlacer.OpenAll).
/// The spline was seeded once from city.json rails (menu Hanoi/Metro/Seed Spline From City); after
/// that it belongs to the scene. medianZones = the 5 m pier zones under the viaduct copied at seed
/// time: piers slide along the line (up to pierSlide m) to stand inside them, i.e. not in a junction.
/// </summary>
[ExecuteAlways]
[RequireComponent(typeof(SplineContainer))]
public class MetroLine : MonoBehaviour
{
    [Serializable] public struct Zone { public float s0, s1; }               // arc length along the line, m
    [Serializable] public struct PierOverride { public int index; public float shift; public bool skip; }
    [Serializable] public class Ring { public List<Vector2> pts = new List<Vector2>(); }   // world x, z

    [Tooltip("Ground under the piers (road level).")]
    public float groundY = 0f;
    [Tooltip("Target pier spacing; piers are spread evenly so both line ends get one.")]
    public float span = 30f;
    [Tooltip("How far a pier may slide along the line to land in a median zone.")]
    public float pierSlide = 15f;
    [Tooltip("Station zones: no girder / barrier there (the station deck goes in later). Arc length in m.")]
    public List<Zone> stationZones = new List<Zone>();
    [Tooltip("Per pier (index from the line start, see the log / pier names): shift along the line (m) or skip.")]
    public List<PierOverride> pierOverrides = new List<PierOverride>();
    [Tooltip("Rebuild the viaduct shortly after the spline or a setting changes (Editor only).")]
    public bool autoRebuild = true;
    [HideInInspector] public List<Ring> medianZones = new List<Ring>();

    public SplineContainer Container => GetComponent<SplineContainer>();

    MetroPath path;
    /// Arc-length sampling of the spline (cached; dropped when the spline changes in the Editor).
    public MetroPath Path
    {
        get
        {
            if (path == null && Container != null && Container.Spline != null && Container.Spline.Count > 1)
                path = new MetroPath(Container);
            return path;
        }
    }

    public void InvalidatePath() => path = null;

    /// Set by Editor/MetroBuilder ([InitializeOnLoad]); runtime code cannot see the Editor assembly.
    public static Action<MetroLine> RebuildRequested;

#if UNITY_EDITOR
    double dirtyAt = -1;
    bool live;          // OnValidate also runs when the scene loads (before OnEnable): no rebuild for that

    void OnEnable()
    {
        live = true;
        Spline.Changed += OnSplineChanged;
        UnityEditor.EditorApplication.update += EditorTick;
    }

    void OnDisable()
    {
        live = false;
        Spline.Changed -= OnSplineChanged;
        UnityEditor.EditorApplication.update -= EditorTick;
    }

    void OnSplineChanged(Spline s, int knot, SplineModification mod)
    {
        var c = Container;
        if (c != null && c.Spline == s) { path = null; MarkDirty(); }
    }

    void OnValidate() => MarkDirty();

    void MarkDirty()
    {
        if (live && !Application.isPlaying && autoRebuild) dirtyAt = UnityEditor.EditorApplication.timeSinceStartup;
    }

    void EditorTick()
    {
        // 0.3 s after the last change, and not while the mouse still drags a knot
        if (dirtyAt < 0 || UnityEditor.EditorApplication.timeSinceStartup - dirtyAt < 0.3 || GUIUtility.hotControl != 0) return;
        dirtyAt = -1;
        RebuildRequested?.Invoke(this);
    }
#endif
}
