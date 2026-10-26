struct PS_INPUT {
half4 Interp0: TEXCOORD0;
half4 Interp1: TEXCOORD1;
half3 Interp2: TEXCOORD2;
half2 Interp3: TEXCOORD3;
half3 Interp4: TEXCOORD4;
half3 Interp5: TEXCOORD5;
#define Interpolator1D0 inp.Interp4.x
#define Interpolator1D1 inp.Interp5.x
#define Interpolator2D0 inp.Interp3.xy
#define Interpolator3D0 inp.Interp2.xyz
#define Interpolator4D0 inp.Interp0.xyzw
#define Interpolator4D1 inp.Interp1.xyzw
#ifdef profile_ps_3_0
half VFace : VFACE;
#endif
};

#if defined(profile_ps_1_1) || defined(profile_ps_1_2) || defined(profile_ps_1_3)
#define tex2Dprojected tex2D
#define tex3Dprojected tex3D
#else
#define tex2Dprojected tex2Dproj
#define tex3Dprojected tex3Dproj
#endif

#define ScreenUV ((half4)Interpolator4D0)
#define ScreenSUV ((half4)Interpolator4D1)
sampler BTextureNormalize;
#ifndef profile_ps_3_0
half3 NormalizeWithTexture(half3 val) { return (half3)texCUBE(BTextureNormalize, val).rgb * 2 - 1; }
#else
float3 NormalizeWithTexture(float3 val) { return normalize(val); }
half3 NormalizeWithTexture(half3 val) { return normalize(val); }
#endif

sampler Texture0;
sampler Texture1;

sampler ShadowTex;

const float4x3 InvWorldTransform;
const float4x3 WorldTransform;
const float4x3 WorldViewTransform;
const float4x4 FullTransform;
const float4 CameraPosition;
const float FloatValue0;
const float3 VectorValue0;

struct BumpUV {
half2 coord_;
half3 tangent_, binormal_;
half3 wtangent_, wbinormal_;
half3 camera_;
};
half2 bx2(half2 val) { return val * 2 - 1; }
half3 bx2(half3 val) { return val * 2 - 1; }
half3 sampleLightmap(sampler s, half2 coord) {
#ifdef hdr_enabled
half4 c = tex2D(s, coord);
return c.rgb * (half)pow(1.0273h, (half)(c.a * 255.0h));
#else
return tex2D(s, coord).rgb * 2;
#endif
}
half3 sampleLightmapPV(half4 val) {
#ifdef hdr_enabled
return val.rgb * (half)pow(1.0273h, (half)(val.a * 255.0h));
#else
return val.rgb * 2;
#endif
}
half3 sampleLightmapBiased(sampler s, half2 coord) {
#ifdef hdr_enabled
half4 c = tex2D(s, coord);
return bx2(c.rgb) * (half)pow(1.0273h, (half)(c.a * 255.0h));
#else
return bx2((half3)tex2D(s, coord).rgb) * 2;
#endif
}
half3 sampleLightmapBiasedPV(half4 val) {
#ifdef hdr_enabled
return bx2(val.rgb) * (half)pow(1.0273h, (half)(val.a * 255.0h));
#else
return bx2(val.rgb) * 2;
#endif
}
half3 sampleNormalMap(sampler s, half2 coord) {
half4 c = tex2D(s, coord);
half2 xy = bx2(half2(c.a, c.g));
return half3(xy.x, xy.y, sqrt(1.0h - saturate(dot(xy, xy))));
}
half3 MakeBinormal(half3 norm, half4 tangent) {
return cross(norm, tangent.xyz) * (1 - tangent.w * 2);
}
half CalcAttenuation(half dist, half atten) {
return 1 / (1 + dist * dist * atten);
}
static const float LightingScale = 1.0f;
static const float SRGrow = 0.1f;
static const float SRScale = 1 / (1 + 2 * SRGrow);

static const int TotalLights = 1;

#define input0 output0
#define input1 output1
#define input2 output2
#define input3 output3

half4 FogColor;

half4 calcColor(const PS_INPUT inp) {
half2 output0 = Interpolator2D0;
half3 output1 = tex2D(Texture0, input0).rgb;
half output2 = tex2D(Texture0, input0).a;
half3 output3;
{
half3 lcolor = Interpolator3D0;
half3 nlcolor = 0;
output3 = input1 * lcolor;
}
output3 = output3 - output3 * (half)tex2Dprojected(ShadowTex, ScreenUV).a;
return half4(input3, 1);
}

half3 calcFog(half3 color, half fog_alpha, const PS_INPUT inp) {
#ifndef DISABLE_INTERPOLATOR1D0
half dprod = Interpolator1D0;
half factor;
{
factor = saturate(FogColor.w - dprod);
}
return lerp(FogColor.rgb * fog_alpha, color, saturate(factor));
#else
return color;
#endif
}

half4 main(const PS_INPUT inp): COLOR {
half4 color = calcColor(inp);
half outa = smoothstep(0.05h, 1.0h, (half)Interpolator1D1);
return half4(calcFog(color.rgb, 1, inp), outa);
}