using UnityEngine;

/// <summary>
/// CAR C4: the driving car prefab (Editor/HanoiCars builds it from Export/Vehicles/FBX/SM_Car_LuxA2_Rig.fbx).
/// Hierarchy: Body (Body_LODn), SteerFL / SteerFR pivots on the front axles holding WheelFL / WheelFR, WheelRL /
/// WheelRR pivots on the rear axles. Origin = ground under the wheelbase midpoint, so the tyres touch y = 0.
///
/// Two ways to move it:
///  - kinematic (traffic along a path, like MetroTrain): move the root yourself and call Drive(distance, steer)
///    every frame -> the wheels roll by distance / radius and the front pivots steer;
///  - physics: AddPhysics() adds a Rigidbody, a body BoxCollider and four WheelColliders on the axles (rest
///    position = the modelled ride height); the visual wheels then follow the colliders (LateUpdate).
/// </summary>
public class CarRig : MonoBehaviour
{
    public Transform body;
    public Transform steerFL, steerFR;
    public Transform wheelFL, wheelFR, wheelRL, wheelRR;
    public float wheelRadius = 0.33f;
    [Tooltip("Body collider (car space), from the LOD0 body bounds.")]
    public Vector3 boxCenter, boxSize;

    [Header("Physics (AddPhysics)")]
    public float mass = 1700f;
    public float suspensionDistance = 0.2f;
    [Tooltip("Static sag of the springs under the car's weight (sets the spring rate).")]
    public float sag = 0.05f;
    [Tooltip("WheelColliders sit this far above the axles so that, loaded, the wheels rest on the modelled axles " +
             "(measured by HanoiCars.PhysicsTest).")]
    public float colliderLift = 0.10f;
    public WheelCollider colFL, colFR, colRL, colRR;

    float spin;

    /// Distance between the front and rear axles (m), from the wheel pivots.
    public float wheelbase => wheelFL != null && wheelRL != null
        ? Mathf.Abs(transform.InverseTransformPoint(wheelFL.position).z - transform.InverseTransformPoint(wheelRL.position).z) : 2.9f;

    Transform[] Wheels => new[] { wheelFL, wheelFR, wheelRL, wheelRR };

    /// Kinematic driving: roll the wheels over `distance` metres (negative = reversing), steer the front wheels.
    public void Drive(float distance, float steerDeg)
    {
        spin += distance / Mathf.Max(wheelRadius, 0.01f) * Mathf.Rad2Deg;
        var roll = Quaternion.AngleAxis(spin, Vector3.right);
        foreach (var w in Wheels) if (w) w.localRotation = roll;
        var steer = Quaternion.AngleAxis(steerDeg, Vector3.up);
        if (steerFL) steerFL.localRotation = steer;
        if (steerFR) steerFR.localRotation = steer;
    }

    /// Rigidbody + body box + WheelColliders, lifted by colliderLift so that the loaded car rests at its modelled
    /// ride height (tyres on the ground, body as in the FBX).
    public Rigidbody AddPhysics()
    {
        var rb = GetComponent<Rigidbody>();
        if (rb == null) rb = gameObject.AddComponent<Rigidbody>();
        rb.mass = mass;
        rb.interpolation = RigidbodyInterpolation.Interpolate;
        rb.centerOfMass = new Vector3(0f, 0.55f, 0f);              // low, between the axles
        var box = GetComponent<BoxCollider>();
        if (box == null) box = gameObject.AddComponent<BoxCollider>();
        box.center = boxCenter;
        box.size = boxSize;
        colFL = MakeWheel("ColFL", wheelFL);
        colFR = MakeWheel("ColFR", wheelFR);
        colRL = MakeWheel("ColRL", wheelRL);
        colRR = MakeWheel("ColRR", wheelRR);
        return rb;
    }

    WheelCollider MakeWheel(string name, Transform visual)
    {
        var t = transform.Find(name);
        if (t == null) t = new GameObject(name).transform;
        t.SetParent(transform, false);
        t.localPosition = transform.InverseTransformPoint(visual.position) + Vector3.up * colliderLift;
        t.localRotation = Quaternion.identity;
        var wc = t.GetComponent<WheelCollider>();
        if (wc == null) wc = t.gameObject.AddComponent<WheelCollider>();
        wc.radius = wheelRadius;
        wc.mass = 20f;
        wc.suspensionDistance = suspensionDistance;
        float sprung = mass / 4f;
        // spring rate from the static sag; damping 0.6 of critical (2 sqrt(k m))
        float k = sprung * -Physics.gravity.y / sag;
        wc.suspensionSpring = new JointSpring { spring = k, damper = 0.6f * 2f * Mathf.Sqrt(k * sprung), targetPosition = 0.5f };
        wc.forceAppPointDistance = 0.1f;
        return wc;
    }

    /// Physics: front wheels steer, rear wheels drive / everything brakes.
    public void SetControls(float motorTorque, float steerDeg, float brakeTorque = 0f)
    {
        if (colFL == null) return;
        colFL.steerAngle = colFR.steerAngle = steerDeg;
        colRL.motorTorque = colRR.motorTorque = motorTorque;
        colFL.brakeTorque = colFR.brakeTorque = colRL.brakeTorque = colRR.brakeTorque = brakeTorque;
    }

    void LateUpdate() => SyncWheels();

    /// Visual wheels follow the WheelColliders (position = suspension travel, rotation = steer + roll).
    public void SyncWheels()
    {
        if (colFL == null) return;
        Sync(colFL, wheelFL); Sync(colFR, wheelFR); Sync(colRL, wheelRL); Sync(colRR, wheelRR);
    }

    static void Sync(WheelCollider c, Transform w)
    {
        if (c == null || w == null) return;
        c.GetWorldPose(out var p, out var q);
        w.SetPositionAndRotation(p, q);
    }
}
