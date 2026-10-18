using UnityEngine;
using UnityEngine.InputSystem;

/// <summary>
/// CAR C4: drive a CarRig with physics in play mode (Assets/Hanoi/Vehicles/CarPhysicsTest.unity).
/// Arrow keys: up / down = throttle / reverse, left / right = steer, Space = brake. The camera follows.
/// </summary>
[RequireComponent(typeof(CarRig))]
public class CarTestDrive : MonoBehaviour
{
    public float motorTorque = 900f;
    public float maxSteer = 32f;
    public float brakeTorque = 3000f;
    public bool followCamera = true;

    CarRig rig;

    void Start()
    {
        rig = GetComponent<CarRig>();
        if (rig.colFL == null) rig.AddPhysics();
    }

    void FixedUpdate()
    {
        var kb = Keyboard.current;
        if (kb == null) return;
        float throttle = (kb.upArrowKey.isPressed ? 1f : 0f) - (kb.downArrowKey.isPressed ? 1f : 0f);
        float steer = (kb.rightArrowKey.isPressed ? 1f : 0f) - (kb.leftArrowKey.isPressed ? 1f : 0f);
        rig.SetControls(throttle * motorTorque, steer * maxSteer, kb.spaceKey.isPressed ? brakeTorque : 0f);
    }

    void LateUpdate()
    {
        var cam = Camera.main;
        if (!followCamera || cam == null) return;
        var target = transform.position - transform.forward * 8f + Vector3.up * 3f;
        cam.transform.position = Vector3.Lerp(cam.transform.position, target, 1f - Mathf.Exp(-4f * Time.deltaTime));
        cam.transform.LookAt(transform.position + Vector3.up * 1f);
    }
}
