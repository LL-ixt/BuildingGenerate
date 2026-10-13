#ifndef HANOI_FORWARD_INCLUDED
#define HANOI_FORWARD_INCLUDED

// UniversalForward pass shared by Hanoi/Building and Hanoi/Window.
// Vertex / GI plumbing mirrors URP 17.4 LitForwardPass.hlsl; the surface comes from
// HanoiSurface(), which each shader defines after including this file:
//     void HanoiSurface(HanoiVaryings input, half3 viewDirWS, inout SurfaceData s)

#include "HanoiCommon.hlsl"
#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
#if defined(LOD_FADE_CROSSFADE)
    #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/LODCrossFade.hlsl"
#endif

struct HanoiAttributes
{
    float4 positionOS       : POSITION;
    float3 normalOS         : NORMAL;
    float4 tangentOS        : TANGENT;
    float2 texcoord         : TEXCOORD0;
    float2 staticLightmapUV : TEXCOORD1;    // no baked lightmaps in this project: towers carry FacadeUV here
    float4 houseSeedPos     : TEXCOORD2;    // HLOD: house world position, w = 2 (missing UV2 reads w = 1)
    half4  color            : COLOR;
    UNITY_VERTEX_INPUT_INSTANCE_ID
};

struct HanoiVaryings
{
    float2 uv                 : TEXCOORD0;
    float3 positionWS         : TEXCOORD1;
    float3 normalWS           : TEXCOORD2;
    half4  tangentWS          : TEXCOORD3;
    half4  color              : TEXCOORD4;
    half   fogFactor          : TEXCOORD5;
    float3 positionOS         : TEXCOORD6;
    nointerpolation float2 seed : TEXCOORD7;
    DECLARE_LIGHTMAP_OR_SH(staticLightmapUV, vertexSH, 8);
    float4 facade             : TEXCOORD9;  // tower wall: xy = world metres from the wall centre, zw = half wall size
#ifdef USE_APV_PROBE_OCCLUSION
    float4 probeOcclusion     : TEXCOORD10;
#endif
    float4 positionCS         : SV_POSITION;
    UNITY_VERTEX_INPUT_INSTANCE_ID
    UNITY_VERTEX_OUTPUT_STEREO
};

HanoiVaryings HanoiVertex(HanoiAttributes input)
{
    HanoiVaryings output = (HanoiVaryings)0;
    UNITY_SETUP_INSTANCE_ID(input);
    UNITY_TRANSFER_INSTANCE_ID(input, output);
    UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);

    VertexPositionInputs vertexInput = GetVertexPositionInputs(input.positionOS.xyz);
    VertexNormalInputs normalInput = GetVertexNormalInputs(input.normalOS, input.tangentOS);

    output.uv = input.texcoord;
    output.positionWS = vertexInput.positionWS;
    output.positionOS = input.positionOS.xyz;
    output.normalWS = normalInput.normalWS;
    real sign = input.tangentOS.w * GetOddNegativeScale();
    output.tangentWS = half4(normalInput.tangentWS.xyz, sign);

    // FBX vertex colours are authored in sRGB; RGB = base colour, A = paint mask
    half4 c = input.color;
#if !defined(UNITY_COLORSPACE_GAMMA)
    c.rgb = SRGBToLinear(c.rgb);
#endif
    output.color = c;
    output.seed = HanoiSeeds(input.houseSeedPos);

    // Tower facade grid: FacadeUV (Blender) = object metres from the wall quad's centre. Towers are
    // stretched / squashed per building, so scale it to world metres along the wall and up; every
    // corner sits at +-half size, so abs() interpolates to the constant half wall size.
    float3x3 o2w = (float3x3)GetObjectToWorldMatrix();
    float3 edgeOS = float3(input.normalOS.z, 0.0, -input.normalOS.x);
    float el = length(edgeOS);
    float ku = el > 1e-3 ? length(mul(o2w, edgeOS / el)) : 1.0;
    float kv = length(mul(o2w, float3(0.0, 1.0, 0.0)));
    float2 fac = input.staticLightmapUV * float2(ku, kv);
    output.facade = float4(fac, abs(fac));

    output.fogFactor = ComputeFogFactor(vertexInput.positionCS.z);
    OUTPUT_LIGHTMAP_UV(input.staticLightmapUV, unity_LightmapST, output.staticLightmapUV);
    OUTPUT_SH4(vertexInput.positionWS, output.normalWS.xyz, GetWorldSpaceNormalizeViewDir(vertexInput.positionWS), output.vertexSH, output.probeOcclusion);

    output.positionCS = vertexInput.positionCS;
    return output;
}

void HanoiInitInputData(HanoiVaryings input, out InputData inputData)
{
    inputData = (InputData)0;
    inputData.positionWS = input.positionWS;
    inputData.normalWS = NormalizeNormalPerPixel(input.normalWS);
    inputData.viewDirectionWS = GetWorldSpaceNormalizeViewDir(input.positionWS);
#if defined(MAIN_LIGHT_CALCULATE_SHADOWS)
    inputData.shadowCoord = TransformWorldToShadowCoord(inputData.positionWS);
#else
    inputData.shadowCoord = float4(0, 0, 0, 0);
#endif
    inputData.fogCoord = InitializeInputDataFog(float4(input.positionWS, 1.0), input.fogFactor);
    inputData.normalizedScreenSpaceUV = GetNormalizedScreenSpaceUV(input.positionCS);

#if !defined(LIGHTMAP_ON) && (defined(PROBE_VOLUMES_L1) || defined(PROBE_VOLUMES_L2))
    inputData.bakedGI = SAMPLE_GI(input.vertexSH,
        GetAbsolutePositionWS(inputData.positionWS),
        inputData.normalWS,
        inputData.viewDirectionWS,
        input.positionCS.xy,
        input.probeOcclusion,
        inputData.shadowMask);
#else
    inputData.bakedGI = SAMPLE_GI(input.staticLightmapUV, input.vertexSH, inputData.normalWS);
    inputData.shadowMask = SAMPLE_SHADOWMASK(input.staticLightmapUV);
#endif
}

// defined by the including shader
void HanoiSurface(HanoiVaryings input, half3 viewDirWS, inout SurfaceData s);

void HanoiFragment(
    HanoiVaryings input
    , out half4 outColor : SV_Target0
#ifdef _WRITE_RENDERING_LAYERS
    , out uint outRenderingLayers : SV_Target1
#endif
)
{
    UNITY_SETUP_INSTANCE_ID(input);
    UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(input);

    HanoiClip(input.uv);
#ifdef LOD_FADE_CROSSFADE
    LODFadeCrossFade(input.positionCS);
#endif

    InputData inputData;
    HanoiInitInputData(input, inputData);

    SurfaceData s = (SurfaceData)0;
    s.albedo = input.color.rgb;
    s.alpha = 1;
    s.occlusion = 1;
    s.smoothness = _Smoothness;
    s.normalTS = half3(0, 0, 1);
    HanoiSurface(input, inputData.viewDirectionWS, s);

    half4 color = UniversalFragmentPBR(inputData, s);
    color.rgb = MixFog(color.rgb, inputData.fogCoord);
    color.a = 1;
    outColor = color;

#ifdef _WRITE_RENDERING_LAYERS
    outRenderingLayers = EncodeMeshRenderingLayer();
#endif
}

#endif
