// Window glass with interior mapping: a fake room box behind each pane, ray-traced in tangent
// space, so close-up fly-bys see depth without any interior geometry.
// Pane coordinates come from the glass UVs, which fill the GLASSWIN trim region per pane.
// Room look (wall colour, curtains, lights on) is randomised per room from object-space
// position + per-house seed.
Shader "Hanoi/Window"
{
    Properties
    {
        _Smoothness ("Glass Smoothness", Range(0, 1)) = 0.95
        _GlassRect ("Window UV Rect", Vector) = (0.75146, 0.62646, 0.99854, 0.87354)

        [Header(Interior)]
        _RoomDepth ("Room Depth (x pane width)", Range(0.5, 6)) = 2.5
        _InteriorBrightness ("Interior Brightness (day)", Range(0, 1)) = 0.5
        _WallColorA ("Wall Color A", Color) = (0.85, 0.80, 0.70, 1)
        _WallColorB ("Wall Color B", Color) = (0.70, 0.78, 0.80, 1)
        _FloorColor ("Floor Color", Color) = (0.45, 0.32, 0.22, 1)
        _CeilingColor ("Ceiling Color", Color) = (0.92, 0.92, 0.90, 1)
        _CurtainChance ("Curtain Chance", Range(0, 1)) = 0.55
        _NightLights ("Lit Rooms Fraction", Range(0, 1)) = 0
        [HDR] _LightColor ("Room Light Color", Color) = (1.0, 0.8, 0.55, 1)
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" "UniversalMaterialType" = "Lit" "Queue" = "Geometry" }
        LOD 300

        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode" = "UniversalForward" }
            Cull Back
            ZWrite On

            HLSLPROGRAM
            #pragma target 2.0
            #pragma vertex HanoiVertex
            #pragma fragment HanoiFragment

            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE _MAIN_LIGHT_SHADOWS_SCREEN
            #pragma multi_compile _ _ADDITIONAL_LIGHTS
            #pragma multi_compile _ EVALUATE_SH_MIXED EVALUATE_SH_VERTEX
            #pragma multi_compile_fragment _ _REFLECTION_PROBE_BLENDING
            #pragma multi_compile_fragment _ _REFLECTION_PROBE_BOX_PROJECTION
            #pragma multi_compile_fragment _ _SHADOWS_SOFT _SHADOWS_SOFT_LOW _SHADOWS_SOFT_MEDIUM _SHADOWS_SOFT_HIGH
            #pragma multi_compile _ _CLUSTER_LIGHT_LOOP
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/RenderingLayers.hlsl"

            #pragma multi_compile _ LOD_FADE_CROSSFADE
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Fog.hlsl"
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/ProbeVolumeVariants.hlsl"

            #pragma multi_compile_instancing
            #pragma instancing_options renderinglayer
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DOTS.hlsl"

            #include "HanoiForward.hlsl"

            void HanoiSurface(HanoiVaryings input, half3 viewDirWS, inout SurfaceData s)
            {
                float2 st = saturate(HanoiRectST(input.uv, _GlassRect));

                // view ray in tangent space (x = pane right, y = pane up, z = into the room)
                float3 N = normalize(input.normalWS);
                float3 T = normalize(input.tangentWS.xyz);
                float3 B = input.tangentWS.w * cross(N, T);
                float3 d = -viewDirWS;
                float3 dir = float3(dot(d, T), dot(d, B), -dot(d, N) / max(_RoomDepth, 0.1));
                dir += 1e-5;

                // ray / box intersection, room = [-1,1]^3, window on z = -1
                float3 pos = float3(st * 2.0 - 1.0, -1.0);
                float3 id = 1.0 / dir;
                float3 k = abs(id) - pos * id;
                float kMin = min(min(k.x, k.y), k.z);
                float3 hit = pos + kMin * dir;

                float room = HanoiHash13(float3(floor(input.positionOS.x / 2.0), floor(input.positionOS.y / 3.3), input.seed.x * 131.0));
                float r1 = HanoiHash11(room * 17.1), r2 = HanoiHash11(room * 29.7), r3 = HanoiHash11(room * 41.3);
                float r4 = HanoiHash11(room * 53.9), r5 = HanoiHash11(room * 71.3);
                half3 wall = lerp(_WallColorA.rgb, _WallColorB.rgb, r1);

                half3 c;
                if (kMin == k.z)          // back wall, with a dark doorway / cupboard
                {
                    c = wall;
                    float2 q = hit.xy * 0.5 + 0.5;
                    float dx = lerp(0.15, 0.65, r2);
                    if (q.x > dx && q.x < dx + 0.22 && q.y < 0.75) c *= 0.35;
                    if (abs(q.y - 0.62) < 0.12 && abs(q.x - (1.0 - dx)) < 0.12) c = lerp(c, half3(0.25, 0.35, 0.45), 0.7);   // picture
                }
                else if (kMin == k.x)     // side walls
                {
                    c = wall * 0.8;
                }
                else if (dir.y < 0)       // floor (tiles)
                {
                    float2 q = hit.xz * 2.0;
                    c = _FloorColor.rgb * (0.85 + 0.15 * step(0.5, frac(q.x)) * step(0.5, frac(q.y)) + 0.1 * step(frac(q.x) , 0.5));
                }
                else                      // ceiling
                {
                    c = _CeilingColor.rgb;
                }
                c *= lerp(1.0, 0.45, saturate((hit.z + 1.0) * 0.5));    // light falls off away from the window

                // curtains hang on the window plane
                if (r3 < _CurtainChance)
                {
                    float cw = 0.12 + 0.28 * r4;
                    if (st.x < cw || st.x > 1.0 - cw)
                        c = lerp(half3(0.85, 0.78, 0.60), half3(0.62, 0.70, 0.82), r2) * (0.8 + 0.2 * sin(st.x * 90.0));
                }

                half lit = r5 < _NightLights ? 1.0 : 0.0;
                half3 interior = c * (_InteriorBrightness + lit * _LightColor.rgb * 1.2);

                s.albedo = half3(0.01, 0.012, 0.015);
                s.metallic = 0;
                s.smoothness = _Smoothness;
                s.emission = interior;
            }
            ENDHLSL
        }

        Pass
        {
            Name "ShadowCaster"
            Tags { "LightMode" = "ShadowCaster" }
            ZWrite On
            ZTest LEqual
            ColorMask 0
            Cull Back

            HLSLPROGRAM
            #pragma target 2.0
            #pragma vertex HanoiShadowVertex
            #pragma fragment HanoiShadowFragment
            #pragma multi_compile_instancing
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DOTS.hlsl"
            #pragma multi_compile _ LOD_FADE_CROSSFADE
            #pragma multi_compile_vertex _ _CASTING_PUNCTUAL_LIGHT_SHADOW
            #define HANOI_SHADOW_PASS
            #include "HanoiPasses.hlsl"
            ENDHLSL
        }

        Pass
        {
            Name "DepthOnly"
            Tags { "LightMode" = "DepthOnly" }
            ZWrite On
            ColorMask R
            Cull Back

            HLSLPROGRAM
            #pragma target 2.0
            #pragma vertex HanoiDepthVertex
            #pragma fragment HanoiDepthOnlyFragment
            #pragma multi_compile _ LOD_FADE_CROSSFADE
            #pragma multi_compile_instancing
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DOTS.hlsl"
            #include "HanoiPasses.hlsl"
            ENDHLSL
        }

        Pass
        {
            Name "DepthNormals"
            Tags { "LightMode" = "DepthNormals" }
            ZWrite On
            Cull Back

            HLSLPROGRAM
            #pragma target 2.0
            #pragma vertex HanoiDepthVertex
            #pragma fragment HanoiDepthNormalsFragment
            #pragma multi_compile _ LOD_FADE_CROSSFADE
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/RenderingLayers.hlsl"
            #pragma multi_compile_instancing
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DOTS.hlsl"
            #include "HanoiPasses.hlsl"
            ENDHLSL
        }
    }
    FallBack "Hidden/Universal Render Pipeline/FallbackError"
}
