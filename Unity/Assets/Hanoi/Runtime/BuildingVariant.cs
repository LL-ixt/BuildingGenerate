using UnityEngine;

/// <summary>
/// Identity of a library building prefab (written by HanoiLibrary from Export/Library/library.json).
/// The city placer reads it to match variants to lots.
/// </summary>
[DisallowMultipleComponent]
public class BuildingVariant : MonoBehaviour
{
    public string variantId;
    public string type;          // "tube" | "tower"
    public string archetype;     // towers only
    public int floors;
    public float frontage;       // metres along the street
    public float depth;          // metres away from the street (baked lot depth bucket)
    public float height;

    [Header("Tube houses")]
    // side walls that carry windows, seen from the street: "", "L", "R" or "LR".
    // Model space: facade faces +Z, so L = local +X, R = local -X.
    public string exposed;
    public string top;           // RF_Terrace | ROOF_Shed | ROOF_Gable | ROOF_Hip
    public string roofColor;     // Red | Blue | "" (terrace)
    public string ground;        // ground-floor module
    public Vector2 depthScale = new Vector2(1f, 1f);   // allowed localScale.z range at placement

    public bool ExposedLeft => exposed != null && exposed.Contains("L");
    public bool ExposedRight => exposed != null && exposed.Contains("R");
}
