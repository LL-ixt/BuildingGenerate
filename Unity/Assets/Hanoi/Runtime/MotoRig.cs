using UnityEngine;

/// <summary>
/// TRAFFIC T2: the riding motorbike (Editor/HanoiMotos builds it from Export/Vehicles/FBX/SM_Moto_SH_Rig.fbx).
/// Hierarchy: Lean (pivot on the ground under the wheelbase midpoint = the tyre contact line) holding Body_LODn,
/// Steer (pivot on the steering head: Steer_LODn + WheelF pivot) and WheelR; a rider (HanoiRiders.Ride) sits under
/// Lean too, so he leans with the bike. Origin = ground under the wheelbase midpoint, nose = +z.
///
/// Kinematic only (traffic moves the root along its lane): Drive(distance, steer, lean) rolls each wheel by
/// distance / its radius, turns Steer about steerAxis (vehicles.json rig.steer_axis, raked) and rolls Lean about
/// the contact line. LeanFor / SteerFor give the angles of a steady turn.
/// </summary>
public class MotoRig : MonoBehaviour
{
    public Transform lean, steer, wheelF, wheelR;
    public float wheelRadiusF = 0.259f, wheelRadiusR = 0.274f;
    [Tooltip("Steering axis in the Lean space (vehicles.json rig.steer_axis): up, its top leaning back.")]
    public Vector3 steerAxis = new Vector3(0f, 0.9543f, -0.299f);
    public float wheelbase = 1.353f;
    [Tooltip("Steering shown is clamped: the static rider's hands stay on the grips only for small angles.")]
    public float maxSteer = 12f;
    public float maxLean = 30f;
    [Tooltip("Bike renderers that take the paint material (not the rider's).")]
    public Renderer[] paintRenderers;

    float spinF, spinR;

    /// + steer / + lean = to the right.
    public void Drive(float distance, float steerDeg, float leanDeg)
    {
        spinF = Mathf.Repeat(spinF + distance / Mathf.Max(wheelRadiusF, 0.01f) * Mathf.Rad2Deg, 360f);
        spinR = Mathf.Repeat(spinR + distance / Mathf.Max(wheelRadiusR, 0.01f) * Mathf.Rad2Deg, 360f);
        if (wheelF) wheelF.localRotation = Quaternion.AngleAxis(spinF, Vector3.right);
        if (wheelR) wheelR.localRotation = Quaternion.AngleAxis(spinR, Vector3.right);
        if (steer) steer.localRotation = Quaternion.AngleAxis(Mathf.Clamp(steerDeg, -maxSteer, maxSteer), steerAxis.normalized);
        // Unity is left-handed: a positive roll about +z leans to -x (left)
        if (lean) lean.localRotation = Quaternion.AngleAxis(-Mathf.Clamp(leanDeg, -maxLean, maxLean), Vector3.forward);
    }

    public void SetPaint(Material m)
    {
        if (paintRenderers == null) return;
        foreach (var r in paintRenderers) if (r) r.sharedMaterial = m;
    }

    /// Lean (deg) of a steady turn at `speed` m/s on a path of `curvature` 1/m (+ = turning right).
    public static float LeanFor(float speed, float curvature) =>
        Mathf.Atan(speed * speed * curvature / 9.81f) * Mathf.Rad2Deg;

    /// Kinematic steering angle (deg) for that curvature.
    public float SteerFor(float curvature) => Mathf.Atan(wheelbase * curvature) * Mathf.Rad2Deg;
}
