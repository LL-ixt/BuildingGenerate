using UnityEngine;

/// <summary>
/// A building put on the map by CityPlacer (M3). Manual edits in the Editor set `locked`
/// (PlacedBuildingLocker), and re-running CityPlacer then leaves the building alone.
/// Objects under a chunk's Buildings root without this component are treated as hand-added.
/// </summary>
[DisallowMultipleComponent]
public class PlacedBuilding : MonoBehaviour
{
    public string variantId;
    public string lotKey;        // stable id of the lot / big-building footprint in city.json
    public int seed;
    public bool locked;
}
