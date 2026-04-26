---
layout:     post
title:      GBuffer和MRT
subtitle:   GBuffer和MRT
date:       2026-04-14
author:     engineyk
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - GPU
    - 渲染
---


# GBuffer 与 MRT（Multiple Render Targets）

---

## 1. 核心概念

### 1.1 什么是 MRT

**MRT（Multiple Render Targets）** 允许 Fragment Shader 在一次 Draw Call 中同时输出到多张 Render Texture。

```
传统渲染（Single RT）：
  Fragment Shader → 1 个颜色输出 → 1 张 RT

MRT 渲染：
  Fragment Shader → N 个颜色输出 → N 张 RT（同时写入）
```

### 1.2 为什么 GBuffer 需要 MRT

延迟渲染将 **几何/材质信息** 与 **光照计算** 分离为两个阶段：

```
┌─────────────────────────────────────────────────┐
│              Geometry Pass (Base Pass)          │
│                                                 │
│  对每个物体执行一次 Draw Call                     │
│  Fragment Shader 同时输出到多张 GBuffer：         │
│                                                 │
│  out vec4 GBufferA;  // RT0: BaseColor + AO     │
│  out vec4 GBufferB;  // RT1: Normal             │
│  out vec4 GBufferC;  // RT2: Metallic/Rough/Spec│
│  out vec4 GBufferD;  // RT3: Emissive / Custom  │
│  + Depth Buffer                                 │
│                                                 │
│  ✅ 一次 Draw Call 写入所有材质信息              │
│  ✅ 无需多 Pass 重复提交几何                     │
└─────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────┐
│              Lighting Pass                      │
│                                                 │
│  全屏 Quad / 光源体                              │
│  采样 GBuffer 各张纹理 → 计算光照                 │
│  输出最终颜色到 SceneColor                       │
└─────────────────────────────────────────────────┘
```

---

## 2. API 层面的 MRT 实现

### 2.1 OpenGL / OpenGL ES

```cpp
// 1. Create FBO with multiple color attachments
GLuint fbo;
glGenFramebuffers(1, &fbo);
glBindFramebuffer(GL_FRAMEBUFFER, fbo);

// 2. Attach textures to different color attachment points
glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, gbufferA, 0);
glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1, GL_TEXTURE_2D, gbufferB, 0);
glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT2, GL_TEXTURE_2D, gbufferC, 0);
glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT3, GL_TEXTURE_2D, gbufferD, 0);
glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,  GL_TEXTURE_2D, depthTex, 0);

// 3. Specify draw buffers
GLenum drawBuffers[] = {
    GL_COLOR_ATTACHMENT0,
    GL_COLOR_ATTACHMENT1,
    GL_COLOR_ATTACHMENT2,
    GL_COLOR_ATTACHMENT3
};
glDrawBuffers(4, drawBuffers);

// 4. Render geometry - shader writes to all 4 targets simultaneously
RenderScene();
```

**Fragment Shader (GLSL):**

```glsl
#version 300 es
precision highp float;

// MRT outputs - layout(location) maps to GL_COLOR_ATTACHMENTn
layout(location = 0) out vec4 GBufferA;  // → GL_COLOR_ATTACHMENT0
layout(location = 1) out vec4 GBufferB;  // → GL_COLOR_ATTACHMENT1
layout(location = 2) out vec4 GBufferC;  // → GL_COLOR_ATTACHMENT2
layout(location = 3) out vec4 GBufferD;  // → GL_COLOR_ATTACHMENT3

in vec3 vNormal;
in vec2 vTexCoord;

uniform sampler2D baseColorMap;
uniform float metallic;
uniform float roughness;

void main()
{
    vec3 baseColor = texture(baseColorMap, vTexCoord).rgb;
    vec3 normal    = normalize(vNormal) * 0.5 + 0.5; // encode to [0,1]

    GBufferA = vec4(baseColor, 1.0);                  // BaseColor
    GBufferB = vec4(normal, 1.0);                     // World Normal
    GBufferC = vec4(metallic, roughness, 0.0, 1.0);   // Material
    GBufferD = vec4(0.0);                             // Emissive
}
```

### 2.2 Metal

```cpp
// Create render pass descriptor with multiple color attachments
MTLRenderPassDescriptor *desc = [MTLRenderPassDescriptor renderPassDescriptor];

desc.colorAttachments[0].texture    = gbufferA;  // RGBA8
desc.colorAttachments[0].loadAction = MTLLoadActionClear;
desc.colorAttachments[0].storeAction = MTLStoreActionStore;

desc.colorAttachments[1].texture    = gbufferB;  // RGBA16F
desc.colorAttachments[1].loadAction = MTLLoadActionClear;
desc.colorAttachments[1].storeAction = MTLStoreActionStore;

desc.colorAttachments[2].texture    = gbufferC;  // RGBA8
desc.colorAttachments[2].loadAction = MTLLoadActionClear;
desc.colorAttachments[2].storeAction = MTLStoreActionStore;

desc.colorAttachments[3].texture    = gbufferD;  // RGBA8
desc.colorAttachments[3].loadAction = MTLLoadActionClear;
desc.colorAttachments[3].storeAction = MTLStoreActionStore;

desc.depthAttachment.texture = depthTexture;

id<MTLRenderCommandEncoder> encoder =
    [commandBuffer renderCommandEncoderWithDescriptor:desc];
```

**Metal Shader:**

```metal
struct GBufferOutput {
    half4 GBufferA [[color(0)]];  // maps to colorAttachments[0]
    half4 GBufferB [[color(1)]];  // maps to colorAttachments[1]
    half4 GBufferC [[color(2)]];  // maps to colorAttachments[2]
    half4 GBufferD [[color(3)]];  // maps to colorAttachments[3]
};

fragment GBufferOutput gbuffer_fragment(
    VertexOut        in       [[stage_in]],
    texture2d<half>  albedo   [[texture(0)]],
    constant Material &mat    [[buffer(0)]])
{
    GBufferOutput out;

    half4 baseColor = albedo.sample(linearSampler, in.texCoord);
    half3 normal    = half3(normalize(in.worldNormal)) * 0.5h + 0.5h;

    out.GBufferA = half4(baseColor.rgb, 1.0h);
    out.GBufferB = half4(normal, 1.0h);
    out.GBufferC = half4(mat.metallic, mat.roughness, 0.0h, 1.0h);
    out.GBufferD = half4(0.0h);

    return out;
}
```

### 2.3 Vulkan

```cpp
// Render Pass creation with multiple color attachments
std::array<VkAttachmentDescription, 5> attachments = {};
// [0] GBufferA - RGBA8
// [1] GBufferB - RGBA16F
// [2] GBufferC - RGBA8
// [3] GBufferD - RGBA8
// [4] Depth    - D32F

std::array<VkAttachmentReference, 4> colorRefs = {
    {0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL},
    {1, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL},
    {2, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL},
    {3, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL}
};

VkAttachmentReference depthRef = {
    4, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL
};

VkSubpassDescription subpass = {};
subpass.pipelineBindPoint       = VK_PIPELINE_BIND_POINT_GRAPHICS;
subpass.colorAttachmentCount    = 4;  // 4 MRT outputs
subpass.pColorAttachments       = colorRefs.data();
subpass.pDepthStencilAttachment = &depthRef;
```

**Vulkan GLSL Shader:**

```glsl
#version 450

layout(location = 0) out vec4 outGBufferA;
layout(location = 1) out vec4 outGBufferB;
layout(location = 2) out vec4 outGBufferC;
layout(location = 3) out vec4 outGBufferD;

void main() {
    outGBufferA = vec4(baseColor, ao);
    outGBufferB = vec4(encodeNormal, 1.0);
    outGBufferC = vec4(metallic, roughness, specular, shadingModel);
    outGBufferD = vec4(emissive, 1.0);
}
```

### 2.4 DirectX 11/12

```cpp
// DX11: Bind multiple render targets
ID3D11RenderTargetView* rtvs[4] = {
    gbufferA_RTV,  // SV_Target0
    gbufferB_RTV,  // SV_Target1
    gbufferC_RTV,  // SV_Target2
    gbufferD_RTV   // SV_Target3
};
context->OMSetRenderTargets(4, rtvs, depthStencilView);
```

**HLSL Shader:**

```hlsl
struct GBufferOutput
{
    float4 GBufferA : SV_Target0;  // BaseColor + AO
    float4 GBufferB : SV_Target1;  // Normal
    float4 GBufferC : SV_Target2;  // Metallic / Roughness / Specular
    float4 GBufferD : SV_Target3;  // Emissive / Custom
};

GBufferOutput PS_GBuffer(VSOutput input)
{
    GBufferOutput output;

    float3 baseColor = BaseColorTexture.Sample(sampler0, input.UV).rgb;
    float3 normal    = normalize(input.WorldNormal) * 0.5 + 0.5;

    output.GBufferA = float4(baseColor, ambientOcclusion);
    output.GBufferB = float4(normal, 1.0);
    output.GBufferC = float4(metallic, roughness, specular, shadingModelID);
    output.GBufferD = float4(emissive, 0.0);

    return output;
}
```

---

## 3. UE4/UE5 GBuffer 布局

### 3.1 默认 GBuffer 布局

```
┌──────────┬──────────┬──────────────────────────────────────────────┬──────────┐
│  Target  │  Format  │  R          G          B          A          │  Bytes   │
├──────────┼──────────┼──────────────────────────────────────────────┼──────────┤
│ GBufferA │  RGBA8   │ BaseColor.r BaseColor.g BaseColor.b  AO      │  4 B/px  │
│ GBufferB │ RGB10A2  │ Normal.x    Normal.y    Normal.z    PerObj   │  4 B/px  │
│ GBufferC │  RGBA8   │ Metallic    Specular    Roughness   ShadMdl  │  4 B/px  │
│ GBufferD │  RGBA8   │ CustomData  CustomData  CustomData  HasPxSh  │  4 B/px  │
│ GBufferE │  RGBA16F │ PrecompShadow / SubsurfaceColor              │  8 B/px  │ (optional)
│ GBufferF │  RGBA8   │ Tangent.x   Tangent.y   Tangent.z   Aniso    │  4 B/px  │ (optional)
│ Velocity │  RG16F   │ MotionVec.x MotionVec.y                      │  4 B/px  │ (optional)
│ Depth    │  D32F    │ HardwareDepth                                │  4 B/px  │
├──────────┼──────────┼──────────────────────────────────────────────┼──────────┤
│ 基础总计  │          │ A + B + C + D + Depth                        │ 20 B/px  │
│ 完整总计  │          │ + E + F + Velocity                           │ 36 B/px  │
└──────────┴──────────┴──────────────────────────────────────────────┴──────────┘
```

### 3.2 UE 源码中的 GBuffer 绑定

```cpp
// Engine/Source/Runtime/Renderer/Private/SceneRendering.cpp

// GBuffer allocation
void FSceneRenderer::AllocGBufferTargets(FRHICommandListImmediate& RHICmdList)
{
    // GBufferA: PF_B8G8R8A8 (BaseColor + AO)
    GBufferA = GRenderTargetPool.FindFreeElement(
        Desc, TEXT("GBufferA"));

    // GBufferB: PF_A2B10G10R10 (World Normal)
    GBufferB = GRenderTargetPool.FindFreeElement(
        Desc, TEXT("GBufferB"));

    // GBufferC: PF_B8G8R8A8 (Metallic/Specular/Roughness/ShadingModel)
    GBufferC = GRenderTargetPool.FindFreeElement(
        Desc, TEXT("GBufferC"));

    // GBufferD: PF_B8G8R8A8 (Custom Data)
    GBufferD = GRenderTargetPool.FindFreeElement(
        Desc, TEXT("GBufferD"));
}
```

### 3.3 Shading Model ID 编码

GBufferC.a 中存储 Shading Model ID，用于 Lighting Pass 分支：

```cpp
// Engine/Source/Runtime/Engine/Classes/Engine/EngineTypes.h
enum EMaterialShadingModel
{
    MSM_Unlit                = 0,
    MSM_DefaultLit           = 1,
    MSM_Subsurface           = 2,
    MSM_PreintegratedSkin    = 3,
    MSM_ClearCoat            = 4,
    MSM_SubsurfaceProfile    = 5,
    MSM_TwoSidedFoliage      = 6,
    MSM_Hair                 = 7,
    MSM_Cloth                = 8,
    MSM_Eye                  = 9,
    MSM_SingleLayerWater     = 10,
    MSM_ThinTranslucent      = 11,
    MSM_Strata               = 12,  // UE5 Substrate
    // ...
};
```

Lighting Pass 根据 ID 选择不同 BRDF：

```hlsl
// DeferredLightingCommon.ush
switch(GBuffer.ShadingModelID)
{
    case SHADINGMODELID_DEFAULT_LIT:
        Lighting = DefaultLitBxDF(GBuffer, N, V, L);
        break;
    case SHADINGMODELID_SUBSURFACE:
        Lighting = SubsurfaceBxDF(GBuffer, N, V, L);
        break;
    case SHADINGMODELID_CLEAR_COAT:
        Lighting = ClearCoatBxDF(GBuffer, N, V, L);
        break;
    // ...
}
```

---

## 4. Normal 编码方案

### 4.1 常见编码方式对比

```
┌─────────────────────┬─────────┬──────────┬──────────────┐
│ Method              │ Channels│ Quality  │ ALU Cost     │
├─────────────────────┼─────────┼──────────┼──────────────┤
│ Raw XYZ             │ 3 (RGB) │ ★★★☆   │ 0 (直接存储)  │
│ Spheremap (Lambert) │ 2 (RG)  │ ★★★★   │ ~8 ALU       │
│ Octahedron          │ 2 (RG)  │ ★★★★★  │ ~6 ALU       │
│ Stereographic       │ 2 (RG)  │ ★★★★   │ ~10 ALU      │
└─────────────────────┴─────────┴──────────┴──────────────┘
```

### 4.2 Octahedron 编码（UE5 默认）

```hlsl
// Encode: World Normal → 2 channels
float2 OctahedronEncode(float3 N)
{
    N /= (abs(N.x) + abs(N.y) + abs(N.z));
    if (N.z < 0)
    {
        N.xy = (1.0 - abs(N.yx)) * (N.xy >= 0.0 ? 1.0 : -1.0);
    }
    return N.xy * 0.5 + 0.5;
}

// Decode: 2 channels → World Normal
float3 OctahedronDecode(float2 Oct)
{
    Oct = Oct * 2.0 - 1.0;
    float3 N = float3(Oct, 1.0 - abs(Oct.x) - abs(Oct.y));
    if (N.z < 0)
    {
        N.xy = (1.0 - abs(N.yx)) * (N.xy >= 0.0 ? 1.0 : -1.0);
    }
    return normalize(N);
}
```

### 4.3 UE4 默认：RGB10A2 直接存储

```hlsl
// UE4 BasePassPixelShader.usf
// GBufferB uses R10G10B10A2 format
// 10 bits per channel → 1024 levels → sufficient for normals
GBufferB.rgb = EncodeNormal(WorldNormal);  // simple * 0.5 + 0.5
```

---

## 5. Lighting Pass 采样 GBuffer

### 5.1 全屏 Quad 方式

```hlsl
// DeferredLightPixelShader.usf
float4 PS_DeferredLight(float2 UV : TEXCOORD0) : SV_Target0
{
    // Sample all GBuffer textures
    float4 gbA = GBufferATexture.Sample(PointSampler, UV);
    float4 gbB = GBufferBTexture.Sample(PointSampler, UV);
    float4 gbC = GBufferCTexture.Sample(PointSampler, UV);
    float  depth = DepthTexture.Sample(PointSampler, UV).r;

    // Reconstruct GBuffer data
    float3 BaseColor   = gbA.rgb;
    float  AO          = gbA.a;
    float3 WorldNormal = DecodeNormal(gbB.rgb);
    float  Metallic    = gbC.r;
    float  Roughness   = gbC.b;
    float  Specular    = gbC.g;
    uint   ShadingModel = uint(gbC.a * 255.0);

    // Reconstruct world position from depth
    float3 WorldPos = ReconstructWorldPosition(UV, depth);

    // Calculate lighting
    float3 L = normalize(LightPosition - WorldPos);
    float3 V = normalize(CameraPosition - WorldPos);

    float3 Lighting = EvaluateBxDF(ShadingModel,
        BaseColor, Metallic, Roughness, Specular,
        WorldNormal, V, L, LightColor, Attenuation);

    return float4(Lighting * AO, 1.0);
}
```

### 5.2 Light Volume 方式（点光源/聚光灯）

```
┌──────────────────────────────────────────┐
│         Light Volume Rendering           │
│                                          │
│  Point Light  → Sphere Mesh              │
│  Spot Light   → Cone Mesh                │
│  Dir Light    → Fullscreen Quad          │
│                                          │
│  Stencil 优化：                           │
│  Pass 1: 背面渲染，Depth Fail → Stencil++ │
│  Pass 2: 正面渲染，Depth Fail → Stencil-- │
│  Pass 3: Stencil != 0 的像素执行光照       │
└──────────────────────────────────────────┘
```

---

## 6. 移动端 MRT 限制与优化

### 6.1 硬件限制

```
┌──────────────────┬──────────────────────────────────┐
│ Platform         │ Max MRT Count                    │
├──────────────────┼──────────────────────────────────┤
│ OpenGL ES 3.0+   │ 4 (guaranteed minimum)           │
│ Metal (iOS)      │ 8                                │
│ Vulkan (mobile)  │ 4~8 (device dependent)           │
│ Desktop GL 4.x   │ 8                                │
│ DX11/12          │ 8                                │
└──────────────────┴──────────────────────────────────┘
```

### 6.2 TBR 架构下的 MRT 带宽问题

```
问题：每张 GBuffer 都需要从 Tile SRAM → 显存 的 Store 操作

1080p, 4 × RGBA8 GBuffer + D32F:
  Store 带宽 = 1920 × 1080 × (4 × 4 + 4) = 41.5 MB/frame
  @ 60fps = 2.49 GB/s 仅 GBuffer Store

对比 Forward 单 RT:
  Store 带宽 = 1920 × 1080 × (4 + 4) = 16.6 MB/frame
  @ 60fps = 0.99 GB/s

→ GBuffer MRT 带宽是 Forward 的 2.5x
```

### 6.3 移动端优化策略

#### 策略 1：FrameBuffer Fetch（TBDR 专属）

在 TBDR 架构（Apple/PowerVR）上，可以在同一 Render Pass 内读取之前写入的 GBuffer，避免 Store→Load 往返：

```metal
// Metal: Single-pass deferred using tile memory
struct GBufferData {
    half4 gbA [[color(0)]];
    half4 gbB [[color(1)]];
    half4 gbC [[color(2)]];
};

// Geometry sub-pass writes GBuffer
fragment GBufferData geometry_pass(...) { ... }

// Lighting sub-pass reads GBuffer from tile memory (FREE!)
fragment half4 lighting_pass(
    GBufferData gBuffer [[color(0), color(1), color(2)]])
{
    // gBuffer data comes from tile SRAM, zero bandwidth cost
    half3 baseColor = gBuffer.gbA.rgb;
    half3 normal    = decodeNormal(gBuffer.gbB.rgb);
    // ... lighting calculation
}
```

#### 策略 2：Vulkan Subpass + Input Attachment

```cpp
// Subpass 0: Geometry Pass → writes GBuffer as color attachments
// Subpass 1: Lighting Pass → reads GBuffer as input attachments

VkSubpassDescription subpasses[2];

// Subpass 0: GBuffer write
subpasses[0].colorAttachmentCount = 4;
subpasses[0].pColorAttachments    = gbufferColorRefs;  // write GBuffer

// Subpass 1: Lighting read
subpasses[1].inputAttachmentCount = 4;
subpasses[1].pInputAttachments    = gbufferInputRefs;  // read GBuffer from tile
subpasses[1].colorAttachmentCount = 1;
subpasses[1].pColorAttachments    = &sceneColorRef;    // write final color

// Dependency: subpass 0 → subpass 1
VkSubpassDependency dep = {};
dep.srcSubpass = 0;
dep.dstSubpass = 1;
dep.srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
dep.dstStageMask = VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT;
dep.srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
dep.dstAccessMask = VK_ACCESS_INPUT_ATTACHMENT_READ_BIT;
dep.dependencyFlags = VK_DEPENDENCY_BY_REGION_BIT; // tile-local!
```

```glsl
// Vulkan GLSL - Lighting subpass
layout(input_attachment_index = 0, set = 0, binding = 0) uniform subpassInput gbufferA;
layout(input_attachment_index = 1, set = 0, binding = 1) uniform subpassInput gbufferB;
layout(input_attachment_index = 2, set = 0, binding = 2) uniform subpassInput gbufferC;

void main() {
    vec4 gA = subpassLoad(gbufferA);  // from tile SRAM, not texture fetch
    vec4 gB = subpassLoad(gbufferB);
    vec4 gC = subpassLoad(gbufferC);
    // ... lighting
}
```

#### 策略 3：GBuffer 压缩 — 减少 RT 数量

```
┌────────────────────────────────────────────────────────┐
│  Compact GBuffer (2 RT + Depth)                        │
│                                                        │
│  RT0 (RGBA8):                                          │
│    R: BaseColor.r                                      │
│    G: BaseColor.g                                      │
│    B: BaseColor.b                                      │
│    A: Roughness                                        │
│                                                        │
│  RT1 (RGB10A2):                                        │
│    R: Normal.x (10 bit)                                │
│    G: Normal.y (10 bit)                                │
│    B: Metallic (10 bit, overkill but free)             │
│    A: ShadingModel (2 bit → 4 models)                  │
│                                                        │
│  Depth (D32F):                                         │
│    Hardware depth                                      │
│                                                        │
│  Total: 12 B/px vs 20 B/px (40% reduction)             │
└────────────────────────────────────────────────────────┘
```

#### 策略 4：Memoryless（Apple Metal）

```objc
// GBuffer textures marked as memoryless
// They exist ONLY in tile SRAM, never allocated in system memory
MTLTextureDescriptor *desc = [MTLTextureDescriptor new];
desc.storageMode = MTLStorageModeMemoryless;  // iOS only
desc.usage = MTLTextureUsageRenderTarget;

// GBuffer RT never touches main memory
// → 0 bytes system memory
// → 0 bandwidth for store
// Requires single render pass with tile shading
```

---

## 7. Unity URP/HDRP 中的 GBuffer MRT

### 7.1 HDRP GBuffer 布局

```
┌──────────┬─────────────┬──────────────────────────────────────────┐
│  Target  │  Format     │  Content                                 │
├──────────┼─────────────┼──────────────────────────────────────────┤
│ GBuffer0 │  RGBA8      │ BaseColor.rgb + SpecularOcclusion        │
│ GBuffer1 │  RGBA8      │ Normal (Octahedron) + Perceptual Rough   │
│ GBuffer2 │  RGBA8      │ Metallic + Coat Mask + Material Features │
│ GBuffer3 │  R11G11B10F │ Baked Diffuse Lighting (Lightmap)        │
│ Depth    │  D32S8      │ Depth + Stencil (material classification)│
└──────────┴─────────────┴──────────────────────────────────────────┘
```

### 7.2 URP Deferred Path

```csharp
// UniversalRenderer.cs
public class UniversalRenderer : ScriptableRenderer
{
    // GBuffer pass - writes to MRT
    GBufferPass m_GBufferPass;

    // Deferred lighting pass - reads GBuffer
    DeferredPass m_DeferredPass;

    public override void Setup(ScriptableRenderContext context, ref RenderingData data)
    {
        // Allocate GBuffer RTs
        m_GBufferPass.Setup(/* ... */);

        // Configure MRT
        EnqueuePass(m_GBufferPass);     // writes 4 MRT
        EnqueuePass(m_DeferredPass);    // reads GBuffer textures
    }
}
```

---

## 8. 完整数据流图

```
                    Geometry Pass (MRT Write)
                    ========================

  Vertex Buffer ──→ Vertex Shader ──→ Rasterizer ──→ Fragment Shader
                                                          │
                                          ┌───────────────┼───────────────┐
                                          │               │               │
                                          ▼               ▼               ▼
                                     ┌─────────┐     ┌─────────┐     ┌─────────┐
                                     │GBufferA │     │GBufferB │     │GBufferC │  ...
                                     │BaseColor│     │ Normal  │     │Material │
                                     │  + AO   │     │         │     │ Props   │
                                     └────┬────┘     └────┬────┘     └────┬────┘
                                          │               │               │
                                          ▼               ▼               ▼
                    ┌─────────────────────────────────────────────────────────┐
                    │                    GPU Memory (VRAM)                    │
                    │              or Tile SRAM (mobile TBR)                  │
                    └──────────────────────┬──────────────────────────────────┘
                                           │
                                           ▼
                    Lighting Pass (Texture Read)
                    ===========================

                    Fullscreen Quad / Light Volume
                              │
                    Fragment Shader reads:
                    ├── texture(GBufferA, UV) → BaseColor, AO
                    ├── texture(GBufferB, UV) → Normal
                    ├── texture(GBufferC, UV) → Metallic, Roughness
                    └── texture(Depth, UV)    → Reconstruct Position
                              │
                              ▼
                    ┌──────────────┐
                    │ Scene Color  │ → Post Processing → Final Output
                    └──────────────┘
```

---

## 9. MRT 数量 vs 性能权衡

### 9.1 带宽量化分析

```
分辨率: 1920 × 1080 = 2,073,600 pixels

┌────────────┬──────────┬──────────────┬──────────────────┐
│ GBuffer 数 │ 格式      │ 每帧写入      │ @60fps 带宽      │
├────────────┼──────────┼──────────────┼──────────────────┤
│ 2 RT       │ 2×RGBA8  │ 16.6 MB      │ 0.99 GB/s        │
│ 4 RT       │ 4×RGBA8  │ 33.2 MB      │ 1.99 GB/s        │
│ 4 RT + D32 │ 4×RGBA8+D│ 41.5 MB      │ 2.49 GB/s        │
│ 6 RT + D32 │ mixed    │ 58.0 MB      │ 3.48 GB/s        │
│ 8 RT + D32 │ mixed    │ 74.6 MB      │ 4.48 GB/s        │
└────────────┴──────────┴──────────────┴──────────────────┘

注意：以上仅为 Store 带宽，Lighting Pass 还有等量的 Load 带宽
实际总带宽 ≈ Store + Load = 2× 以上数值
```

### 9.2 优化决策树

```
需要延迟渲染？
  ├── 否 → Forward Rendering（1 RT，最省带宽）
  └── 是
       ├── 桌面/主机？
       │    └── 标准 4~6 RT GBuffer（带宽充裕）
       └── 移动端？
            ├── TBDR (Apple/PowerVR)？
            │    └── Memoryless + Tile Shading（0 额外带宽）✅
            ├── TBR (Mali/Adreno)？
            │    ├── Vulkan Subpass（Tile 内完成）✅
            │    └── 压缩到 2~3 RT
            └── 低端设备？
                 └── Forward 管线（放弃延迟）
```

---

## 10. 面试高频问题

### Q1: MRT 的硬件限制是什么？

**A:** 
- OpenGL ES 3.0 保证最少 4 个 Color Attachment
- Metal/Vulkan/DX 支持最多 8 个
- **所有 RT 必须相同分辨率**（DX12 允许不同格式但相同尺寸）
- **所有 RT 的 MSAA 采样数必须一致**
- 移动端 MRT 数量越多，Tile SRAM 占用越大，可能触发 Tile Split

### Q2: 为什么 GBufferB 用 RGB10A2 而不是 RGBA8？

**A:**
- Normal 需要高精度，RGBA8 只有 256 级量化，会产生明显的法线 banding
- RGB10A2 提供 1024 级量化（10 bit），精度提升 4 倍
- 带宽与 RGBA8 相同（都是 4 bytes/pixel），性价比极高
- A2 的 2 bit 可存储 Per-Object Data 标记

### Q3: 延迟渲染如何处理半透明物体？

**A:**
延迟渲染 **无法直接处理半透明**，因为 GBuffer 每像素只存储一层材质信息。解决方案：

1. **混合管线**：不透明用 Deferred，半透明用 Forward（UE/Unity 默认方案）
2. **OIT（Order Independent Transparency）**：Per-Pixel Linked List 或 Weighted Blended OIT
3. **Stochastic Transparency**：随机采样模拟半透明

### Q4: 延迟渲染如何支持多种 Shading Model？

**A:**
在 GBuffer 中预留一个通道存储 Shading Model ID（如 UE 的 GBufferC.a），Lighting Pass 根据 ID 分支选择不同的 BRDF 函数。缺点是 Shader 中存在动态分支，但现代 GPU 的分支预测能力足以应对。

### Q5: MRT 在 TBR 架构上的带宽问题如何解决？

**A:**
三种方案：
1. **Vulkan Subpass / Metal Tile Shading**：GBuffer 留在 Tile SRAM 内，Lighting 在同一 Render Pass 的下一个 Subpass 中完成，GBuffer 无需 Store 到显存
2. **Memoryless Storage**（Metal）：GBuffer RT 标记为 Memoryless，不分配显存
3. **压缩 GBuffer**：减少 RT 数量到 2~3 张，降低 Tile SRAM 占用

### Q6: 如何从深度缓冲重建世界坐标？

**A:**
```hlsl
float3 ReconstructWorldPosition(float2 UV, float depth)
{
    // 1. UV → NDC
    float4 ndc = float4(UV * 2.0 - 1.0, depth, 1.0);
    ndc.y = -ndc.y; // Vulkan/Metal Y flip

    // 2. NDC → World via inverse VP matrix
    float4 worldPos = mul(InverseViewProjection, ndc);
    return worldPos.xyz / worldPos.w;
}
```

替代方案：存储 View-space Z + 用 Camera Ray 重建，节省一次矩阵乘法。

### Q7: MRT 和 MSAA 能同时使用吗？

**A:**
可以，但代价极高：
- 4 RT × RGBA8 × 4x MSAA = 每像素 64 bytes（vs 无 MSAA 的 16 bytes）
- 桌面端可行，移动端基本不可用
- 这也是延迟渲染传统上不支持 MSAA 的原因之一
- 替代方案：FXAA / TAA / SMAA 后处理抗锯齿

---

## 11. 实践检查清单

```
□ GBuffer 格式选择是否匹配目标平台带宽预算
□ Normal 编码精度是否足够（推荐 RGB10A2 或 Octahedron RG16）
□ Shading Model ID 是否有足够 bit 位
□ 移动端是否使用 Subpass / Tile Shading 避免 GBuffer Store
□ 移动端 GBuffer 是否标记为 Memoryless（Metal）
□ MRT 数量是否超过目标平台最小保证值
□ 所有 RT 分辨率和 MSAA 采样数是否一致
□ Lighting Pass 是否正确重建世界坐标
□ 半透明物体是否走单独的 Forward 路径
□ Depth 精度是否足够（推荐 Reversed-Z + D32F）
□ 是否有 GBuffer Debug 可视化工具
□ 带宽是否在目标帧率预算内
```