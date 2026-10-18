// Motorbikes (Blender/scripts/build_moto.py) and cars (build_car.py): one material on a 1024 texture.
//  - _BaseMap: albedo, alpha = clip mask (transparent between the wheel spokes).
//  - _DataMap: R roughness, G metallic, B emission (lamps).
//  - UVs inside _PaintRect (the PAINT cell of the palette strip) take _PaintColor. One material per
//    colour (M_Moto_0..5); the city picks a random colour prefab per bike (no per-instance data).
//  - Cars (_PaintMaskMode 1): the paint is wherever _DataMap.a says (baked mask, paint baked neutral grey,
//    so its shading survives: albedo x _PaintColor / grey); _BumpMap = baked tangent-space normals.
//  - Riders (_PaintMaskMode 2): as 1 (shirt) + a second paint _PaintColor2 where _DataMap.b says (helmet shell);
//    B is then a mask, not emission.
Shader "Hanoi/Vehicle"
{
    Properties
    {
        [MainTexture] _BaseMap ("Atlas (RGB albedo, A clip)", 2D) = "white" {}
        [NoScaleOffset] _DataMap ("Data (R rough, G metal, B emission)", 2D) = "black" {}
        [MainColor] _BaseColor ("Base Color", Color) = (1, 1, 1, 1)
        _Cutoff ("Alpha Clip", Range(0, 1)) = 0.5
        _EmissionGain ("Lamp Glow", Range(0, 4)) = 1
        _PaintRect ("Paint Cell UV Rect", Vector) = (0, 0.875, 0.125, 1)
        _PaintColor ("Paint Color", Color) = (0.25, 0.36, 0.27, 1)
        [IntRange] _PaintMaskMode ("Paint Mask: 0 rect, 1 data A (cars), 2 data A + B (riders)", Range(0, 2)) = 0
        _PaintColor2 ("Paint Color 2 (data B, riders)", Color) = (0.62, 0.08, 0.09, 1)
        [Normal][NoScaleOffset] _BumpMap ("Normal Map", 2D) = "bump" {}
        _BumpScale ("Normal Scale", Range(0, 2)) = 1
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" "UniversalMaterialType" = "Lit" "Queue" = "AlphaTest" }
        LOD 300

        HLSLINCLUDE
        #define HANOI_VEHICLE
        #define HANOI_NORMALTS
        #include "HanoiCommon.hlsl"
        ENDHLSL

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
            #pragma multi_compile_fragment _ _ADDITIONAL_LIGHT_SHADOWS
            #pragma multi_compile_fragment _ _REFLECTION_PROBE_BLENDING
            #pragma multi_compile_fragment _ _REFLECTION_PROBE_BOX_PROJECTION
            #pragma multi_compile_fragment _ _SHADOWS_SOFT _SHADOWS_SOFT_LOW _SHADOWS_SOFT_MEDIUM _SHADOWS_SOFT_HIGH
            #pragma multi_compile_fragment _ _SCREEN_SPACE_OCCLUSION
            #pragma multi_compile_fragment _ _LIGHT_COOKIES
            #pragma multi_compile _ _LIGHT_LAYERS
            #pragma multi_compile _ _CLUSTER_LIGHT_LOOP
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/RenderingLayers.hlsl"

            #pragma multi_compile _ SHADOWS_SHADOWMASK
            #pragma multi_compile _ LOD_FADE_CROSSFADE
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Fog.hlsl"
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/ProbeVolumeVariants.hlsl"

            #pragma multi_compile_instancing
            #pragma instancing_options renderinglayer
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DOTS.hlsl"

            #include "HanoiForward.hlsl"

            void HanoiSurface(HanoiVaryings input, half3 viewDirWS, inout SurfaceData s)
            {
                float2 uv = input.uv;
                half3 albedo = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, uv).rgb * _BaseColor.rgb;
                half4 data4 = SAMPLE_TEXTURE2D(_DataMap, sampler_DataMap, uv);
                half3 data = data4.rgb;
                if (_PaintMaskMode > 0.5)
                {
                    albedo = lerp(albedo, albedo * _PaintColor.rgb / 0.604, data4.a);   // 0.604 = baked grey 0.8 sRGB, linear
                    if (_PaintMaskMode > 1.5)
                    {
                        albedo = lerp(albedo, albedo * _PaintColor2.rgb / 0.604, data4.b);
                        data.b = 0;
                    }
                }
                else if (HanoiInRect(uv, _PaintRect))
                    albedo = _PaintColor.rgb;
                s.normalTS = UnpackNormalScale(SAMPLE_TEXTURE2D(_BumpMap, sampler_BumpMap, uv), _BumpScale);
                s.albedo = albedo;
                s.smoothness = 1.0 - data.r;
                s.metallic = data.g;
                s.emission = albedo * data.b * _EmissionGain;
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
