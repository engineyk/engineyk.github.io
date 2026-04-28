---
layout:     post
title:      unreal管线增加Pass
subtitle:   unreal管线增加Pass
date:       2025-04-27
author:     engineyk
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - GPU
    - 渲染
---

# Unreal Engine 渲染管线增加 Pass 完全指南

> 本文系统梳理在 UE5 渲染管线中增加自定义 Pass 的 **4 种主流方案**
> 从最轻量的 SceneViewExtension 到最底层的修改引擎 Renderer

---

## 1. UE5 渲染管线总览

### 1.1 延迟渲染管线（Deferred Shading）主要 Pass

```
FDeferredShadingSceneRenderer::Render()
│
├─ PrePass (Depth Only / EarlyZ)
│   └─ FDepthPassMeshProcessor
│
├─ Base Pass (GBuffer Fill)
│   └─ FBasePassMeshProcessor → GBuffer (Albedo, Normal, Roughness, Metallic...)
│
├─ Shadow Pass
│   └─ FShadowDepthPassMeshProcessor → Shadow Maps (CSM / VSM)
│
├─ Lighting Pass
│   ├─ Clustered Deferred Shading
│   ├─ Light Functions
│   └─ Shadow Projection
│
├─ Lumen GI / Reflections
│   ├─ Surface Cache Update
│   ├─ Screen Probe Gather
│   └─ Radiance Cache
│
├─ Translucency Pass
│   └─ Separate Translucency / Standard Translucency
│
├─ Post Processing
│   ├─ SSAO / GTAO
│   ├─ SSR
│   ├─ Bloom / DOF / Motion Blur
│   ├─ Tonemapping
│   └─ FXAA / TAA / TSR
│
└─ Custom Render Passes (可插入的扩展点)
```

### 1.2 关键类关系

```
FSceneRenderer (Base)
├─ FDeferredShadingSceneRenderer (PC/Console Deferred)
└─ FMobileSceneRenderer          (Mobile Forward/Deferred)

FMeshPassProcessor (Base for all mesh passes)
├─ FDepthPassMeshProcessor                                  // Pass-> PrePass
├─ FBasePassMeshProcessor                                   // Pass-> BasePass
├─ FShadowDepthPassMeshProcessor                            // Pass-> Shadow
├─ FCustomDepthPassMeshProcessor
└─ YourCustomMeshProcessor (自定义)

ISceneViewExtension (View Extension interface)
└─ FSceneViewExtensionBase (Base implementation)
    └─ YourViewExtension (自定义)

FCustomRenderPassBase (Custom Render Pass base)
└─ YourCustomRenderPass (自定义)
```

---

## 2. 方案总览与选型

| 方案                                 | 侵入性 | 复杂度 | 适用场景                   | 是否需要改引擎 |
| ------------------------------------ | ------ | ------ | -------------------------- | -------------- |
| **方案 A**: SceneViewExtension       | 最低   | 低     | 后处理插入、调试可视化     | ❌ 插件即可     |
| **方案 B**: FCustomRenderPassBase    | 低     | 中     | 独立的 Depth/BasePass 渲染 | ❌ 插件即可     |
| **方案 C**: 自定义 MeshPassProcessor | 中     | 高     | 新增 Mesh 绘制通道         | ✅ 需要改引擎   |
| **方案 D**: 直接修改 Renderer        | 最高   | 极高   | 深度定制渲染管线           | ✅ 需要改引擎   |

---

## 3. 方案 A：SceneViewExtension（推荐首选）

> **最轻量、最常用**的方案。通过 `ISceneViewExtension` 接口在渲染管线的各个阶段插入自定义逻辑，无需修改引擎源码。

### 3.1 ISceneViewExtension 接口扩展点

```
ISceneViewExtension 提供的渲染线程回调（按执行顺序）：

Game Thread:
  ├─ SetupViewFamily()          // 创建 ViewFamily 时
  ├─ SetupView()                // 创建 View 时
  ├─ SetupViewPoint()           // 创建 ViewPoint 时
  ├─ BeginRenderViewFamily()    // ViewFamily 即将渲染时
  └─ PostCreateSceneRenderer()  // SceneRenderer 创建后

Render Thread:
  ├─ PreRenderViewFamily_RenderThread()     // 渲染开始
  ├─ PreRenderView_RenderThread()           // 每个 View 渲染前
  ├─ PreInitViews_RenderThread()            // 初始化 Views 前
  ├─ PreRenderBasePass_RenderThread()       // Base Pass 前
  │
  ├─ ★ PostRenderBasePassDeferred_RenderThread()  // Base Pass 后（延迟渲染）
  ├─ ★ PostRenderBasePassMobile_RenderThread()    // Base Pass 后（移动端）
  │
  ├─ PrePostProcessPass_RenderThread()       // 后处理开始前
  ├─ ★ SubscribeToPostProcessingPass()       // 订阅后处理 Pass
  │   ├─ BeforeDOF
  │   ├─ AfterDOF
  │   ├─ TranslucencyAfterDOF
  │   ├─ SSRInput
  │   ├─ ReplacingTonemapper
  │   ├─ MotionBlur
  │   ├─ Tonemap
  │   ├─ FXAA
  │   └─ SMAA
  │
  ├─ PostRenderView_RenderThread()          // 每个 View 渲染后
  └─ PostRenderViewFamily_RenderThread()    // 所有渲染完成后
```

### 3.2 完整实现示例

```cpp
// ========================================
// MyCustomViewExtension.h
// ========================================
#pragma once

#include "SceneViewExtension.h"

class FMyCustomViewExtension : public FSceneViewExtensionBase
{
public:
    FMyCustomViewExtension(const FAutoRegister& AutoRegister);

    //~ Begin ISceneViewExtension Interface
    virtual void SetupViewFamily(FSceneViewFamily& InViewFamily) override;
    virtual void BeginRenderViewFamily(FSceneViewFamily& InViewFamily) override;

    // Render thread callbacks
    virtual void PreRenderViewFamily_RenderThread(
        FRDGBuilder& GraphBuilder,
        FSceneViewFamily& InViewFamily) override;

    // Insert pass after Base Pass (Deferred)
    virtual void PostRenderBasePassDeferred_RenderThread(
        FRDGBuilder& GraphBuilder,
        FSceneView& InView,
        const FRenderTargetBindingSlots& RenderTargets,
        TRDGUniformBufferRef<FSceneTextureUniformParameters> SceneTextures) override;

    // Subscribe to post-processing passes
    virtual void SubscribeToPostProcessingPass(
        EPostProcessingPass Pass,
        const FSceneView& InView,
        FPostProcessingPassDelegateArray& InOutPassCallbacks,
        bool bIsPassEnabled) override;

    // Control activation
    virtual bool IsActiveThisFrame_Internal(
        const FSceneViewExtensionContext& Context) const override;
    //~ End ISceneViewExtension Interface

private:
    // Post-process callback
    FScreenPassTexture PostProcessPassAfterTonemap_RenderThread(
        FRDGBuilder& GraphBuilder,
        const FSceneView& View,
        const FPostProcessMaterialInputs& InOutInputs);
};
```

```cpp
// ========================================
// MyCustomViewExtension.cpp
// ========================================
#include "MyCustomViewExtension.h"
#include "PostProcess/PostProcessMaterialInputs.h"
#include "ScreenPass.h"

FMyCustomViewExtension::FMyCustomViewExtension(const FAutoRegister& AutoRegister)
    : FSceneViewExtensionBase(AutoRegister)
{
}

void FMyCustomViewExtension::SetupViewFamily(FSceneViewFamily& InViewFamily)
{
    // Game thread: configure view family settings
}

void FMyCustomViewExtension::BeginRenderViewFamily(FSceneViewFamily& InViewFamily)
{
    // Game thread: prepare data before rendering
}

bool FMyCustomViewExtension::IsActiveThisFrame_Internal(
    const FSceneViewExtensionContext& Context) const
{
    // Return true to enable this extension
    return true;
}

void FMyCustomViewExtension::PreRenderViewFamily_RenderThread(
    FRDGBuilder& GraphBuilder,
    FSceneViewFamily& InViewFamily)
{
    // Render thread: called at the start of rendering
}

void FMyCustomViewExtension::PostRenderBasePassDeferred_RenderThread(
    FRDGBuilder& GraphBuilder,
    FSceneView& InView,
    const FRenderTargetBindingSlots& RenderTargets,
    TRDGUniformBufferRef<FSceneTextureUniformParameters> SceneTextures)
{
    // ★ Insert custom pass right after GBuffer fill
    // At this point, GBuffer is populated but lighting hasn't been applied yet
    // Perfect for: custom GBuffer modifications, decal-like effects, etc.

    // Example: Add a compute pass to process GBuffer data
    FRDGTextureRef SceneColorTexture = RenderTargets[0].GetTexture();

    // Create your custom pass parameters
    auto* PassParameters = GraphBuilder.AllocParameters<FMyCustomPassParameters>();
    PassParameters->SceneTextures = SceneTextures;
    // ... setup other parameters

    GraphBuilder.AddPass(
        RDG_EVENT_NAME("MyCustomPostBasePass"),
        PassParameters,
        ERDGPassFlags::Compute,
        [PassParameters](FRDGAsyncTask, FRHICommandList& RHICmdList)
        {
            // Execute your custom rendering logic here
        });
}

void FMyCustomViewExtension::SubscribeToPostProcessingPass(
    EPostProcessingPass Pass,
    const FSceneView& InView,
    FPostProcessingPassDelegateArray& InOutPassCallbacks,
    bool bIsPassEnabled)
{
    // Subscribe to the Tonemap pass to insert our effect after tonemapping
    if (Pass == EPostProcessingPass::Tonemap)
    {
        InOutPassCallbacks.Add(
            FAfterPassCallbackDelegate::CreateRaw(
                this,
                &FMyCustomViewExtension::PostProcessPassAfterTonemap_RenderThread));
    }
}

FScreenPassTexture FMyCustomViewExtension::PostProcessPassAfterTonemap_RenderThread(
    FRDGBuilder& GraphBuilder,
    const FSceneView& View,
    const FPostProcessMaterialInputs& InOutInputs)
{
    // ★ Insert custom post-process effect after tonemapping
    FScreenPassTexture SceneColor = InOutInputs.GetInput(EPostProcessMaterialInput::SceneColor);

    // If there's an override output (we're the last pass), we must write to it
    FScreenPassRenderTarget Output = InOutInputs.OverrideOutput;
    if (!Output.IsValid())
    {
        // Create our own output texture
        FRDGTextureDesc Desc = SceneColor.Texture->Desc;
        Desc.Reset();
        Desc.Flags |= TexCreate_RenderTargetable;
        FRDGTextureRef OutputTexture = GraphBuilder.CreateTexture(Desc, TEXT("MyPostProcessOutput"));
        Output = FScreenPassRenderTarget(OutputTexture, ERenderTargetLoadAction::ENoAction);
    }

    // Add your post-process pass here using GraphBuilder.AddPass(...)
    // ...

    return MoveTemp(Output);
}
```

```cpp
// ========================================
// Registration (in your module or subsystem)
// ========================================
// In your module's StartupModule() or game instance:
TSharedPtr<FMyCustomViewExtension> ViewExtension;

void FMyModule::StartupModule()
{
    ViewExtension = FSceneViewExtensions::NewExtension<FMyCustomViewExtension>();
}

void FMyModule::ShutdownModule()
{
    ViewExtension.Reset();
}
```

### 3.3 SceneViewExtension 要点总结

```
优点：
  ✅ 无需修改引擎源码（插件级别即可）
  ✅ 多个扩展点覆盖渲染管线各阶段
  ✅ 支持优先级排序（GetPriority）
  ✅ 支持动态启用/禁用（IsActiveThisFrame）
  ✅ 后处理链可以精确插入到任意 Pass 之间

局限：
  ❌ 不能新增 Mesh Pass 类型（不能参与 Mesh Draw Command 缓存）
  ❌ 不能修改 GBuffer 布局
  ❌ 后处理回调只能在固定的 Pass 之间插入
  ❌ 无法控制 Mesh 的可见性判断逻辑
```

---

## 4. 方案 B：FCustomRenderPassBase（独立渲染通道）

> UE5 提供的 **Custom Render Pass** 系统，允许创建独立的渲染通道，拥有自己的视图、渲染目标和渲染模式。
> 适合需要从不同视角或不同渲染设置渲染场景的需求。

### 4.1 核心类结构

```
FCustomRenderPassBase
├─ ERenderMode
│   ├─ DepthPass           // Only render depth pre-pass
│   └─ DepthAndBasePass    // Render depth + base pass
│
├─ ERenderOutput
│   ├─ SceneDepth          // Output scene depth
│   ├─ DeviceDepth         // Output device depth
│   ├─ SceneColorAndDepth  // Output color + depth
│   ├─ SceneColorAndAlpha  // Output color + alpha (throughput)
│   ├─ SceneColorNoAlpha   // Output color only
│   ├─ BaseColor           // Output base color
│   └─ Normal              // Output world normal
│
├─ Lifecycle Callbacks
│   ├─ OnBeginPass()       // Before PreRender
│   ├─ OnPreRender()       // Allocate render targets
│   ├─ OnPostRender()      // Post-process results
│   └─ OnEndPass()         // After PostRender
│
└─ Key Members
    ├─ RenderTargetTexture  // FRDGTextureRef output
    ├─ RenderTargetSize     // Resolution
    └─ Views[]              // Associated view infos
```

### 4.2 实现示例

```cpp
// ========================================
// Custom Render Pass Implementation
// ========================================
class FMyCustomRenderPass : public FCustomRenderPassBase
{
public:
    IMPLEMENT_CUSTOM_RENDER_PASS(FMyCustomRenderPass);

    FMyCustomRenderPass(const FIntPoint& InRenderTargetSize)
        : FCustomRenderPassBase(
            TEXT("MyCustomRenderPass"),
            ERenderMode::DepthAndBasePass,     // Render depth + base pass
            ERenderOutput::SceneColorAndAlpha, // Output scene color with alpha
            InRenderTargetSize)
    {
        bSceneColorWithTranslucent = true; // Include translucency
    }

    virtual void OnPreRender(FRDGBuilder& GraphBuilder) override
    {
        // Allocate render target before rendering
        const FRDGTextureDesc TextureDesc = FRDGTextureDesc::Create2D(
            RenderTargetSize,
            PF_FloatRGBA,
            FClearValueBinding::Black,
            TexCreate_RenderTargetable | TexCreate_ShaderResource);

        RenderTargetTexture = GraphBuilder.CreateTexture(
            TextureDesc, TEXT("MyCustomPassRT"));

        AddClearRenderTargetPass(
            GraphBuilder, RenderTargetTexture,
            FLinearColor::Black,
            FIntRect(FInt32Point(), RenderTargetSize));
    }

    virtual void OnPostRender(FRDGBuilder& GraphBuilder) override
    {
        // Post-process the rendered result
        // e.g., apply dilation, blur, or copy to external texture

        // Convert to external texture for CPU readback or other use
        FRDGTextureRef ProcessedTexture = RenderTargetTexture;
        // ... additional processing
    }
};
```

```cpp
// ========================================
// Enqueue the custom render pass
// ========================================
void EnqueueMyCustomPass(UWorld* World, const FVector& ViewLocation,
                          const FRotator& ViewRotation)
{
    FScene* Scene = World->Scene->GetRenderScene();
    if (!Scene) return;

    // Setup input parameters
    FCustomRenderPassRendererInput Input;
    Input.ViewLocation = ViewLocation;
    Input.ViewRotationMatrix = FInverseRotationMatrix(ViewRotation)
        * FMatrix(FPlane(0, 0, 1, 0), FPlane(1, 0, 0, 0),
                  FPlane(0, 1, 0, 0), FPlane(0, 0, 0, 1));
    Input.ProjectionMatrix = /* your projection matrix */;

    // Create and assign the custom render pass
    Input.CustomRenderPass = new FMyCustomRenderPass(FIntPoint(1024, 1024));

    // Enqueue - will execute next frame and be removed automatically
    Scene->AddCustomRenderPass(nullptr, Input);
}
```

### 4.3 引擎内部执行流程

```
FScene::AddCustomRenderPass()
  └─ CustomRenderPassRendererInputs.Add(Input)

FSceneRenderer::Render() (next frame)
  ├─ For each CustomRenderPassInfo:
  │   ├─ CustomRenderPass->BeginPass(GraphBuilder)
  │   ├─ CustomRenderPass->PreRender(GraphBuilder)
  │   │
  │   ├─ RenderPrePass (if DepthPass or DepthAndBasePass)
  │   │   └─ FDepthPassMeshProcessor processes visible meshes
  │   │
  │   ├─ RenderBasePass (if DepthAndBasePass)
  │   │   └─ FBasePassMeshProcessor processes visible meshes
  │   │   └─ RenderCustomRenderPassBasePass()
  │   │
  │   ├─ RenderTranslucency (if bSceneColorWithTranslucent)
  │   │
  │   ├─ CustomRenderPass->PostRender(GraphBuilder)
  │   └─ CustomRenderPass->EndPass(GraphBuilder)
  │
  └─ Remove from CustomRenderPassRendererInputs (one-shot)
```

### 4.4 使用场景

```
适用场景：
  ✅ Scene Capture（场景捕获，如安全摄像头视角）
  ✅ 水面信息渲染（Water Info Rendering）
  ✅ 合成/抠像（Compositing / Keying）
  ✅ 自定义深度/法线输出
  ✅ 多视角渲染（如小地图、后视镜）

不适用：
  ❌ 需要在主渲染管线中间插入逻辑
  ❌ 需要修改现有 Pass 的行为
  ❌ 需要自定义 Mesh 过滤/排序逻辑
```

---

## 5. 方案 C：自定义 MeshPassProcessor（新增 Mesh 绘制通道）

> **最核心的方案**，用于在引擎中新增一个完整的 Mesh 绘制通道，参与 Mesh Draw Command 缓存系统。需要修改引擎源码。

### 5.1 核心概念

```
Mesh Draw Command Pipeline (UE5):

1. EMeshPass::Type 枚举
   └─ 定义所有 Mesh Pass 类型（DepthPass, BasePass, CustomDepth, ...）

2. FMeshPassProcessor
   └─ 每种 Pass 对应一个 Processor，负责：
      ├─ 过滤哪些 Mesh 参与该 Pass（AddMeshBatch）
      ├─ 设置渲染状态（Blend, DepthStencil, Rasterizer）
      ├─ 选择 Shader（Vertex + Pixel）
      └─ 生成 FMeshDrawCommand

3. FPassProcessorManager
   └─ 管理所有 Pass 的工厂函数和标志
      ├─ RegisterMeshPassProcessor() → 注册工厂
      ├─ CreateMeshPassProcessor() → 创建 Processor 实例
      └─ GetPassFlags() → 获取 Pass 标志

4. FMeshDrawCommand
   └─ 缓存的绘制命令，包含：
      ├─ PSO (Pipeline State Object)
      ├─ Shader Bindings
      ├─ Vertex/Index Buffer
      └─ Draw Arguments
```

### 5.2 新增 MeshPass 的完整步骤

#### Step 1: 在 EMeshPass 枚举中添加新类型

```cpp
// File: Engine/Source/Runtime/Renderer/Public/MeshPassProcessor.h

namespace EMeshPass
{
    enum Type : uint8
    {
        DepthPass,
        BasePass,
        AnisotropyPass,
        SkyPass,
        SingleLayerWaterPass,
        SingleLayerWaterDepthPrepass,
        CSMShadowDepth,
        VSMShadowDepth,
        Distortion,
        Velocity,
        TranslucencyStandard,
        TranslucencyAfterDOF,
        TranslucencyAfterDOFModulate,
        TranslucencyAfterMotionBlur,
        TranslucencyAll,
        LumenTranslucencyRadianceCacheMark,
        LumenFrontLayerTranslucencyGBuffer,
        DitheredLODFadingOutMaskPass,
        CustomDepth,
        MobileBasePassCSM,
        MobileInverseOpacity,
        VirtualTexture,

        // ★ Add your custom pass here
        MyCustomPass,

#if WITH_EDITOR
        HitProxy,
        HitProxyOpaqueOnly,
        EditorSelection,
        EditorLevelInstance,
#endif
        DebugViewMode,
        SecondStageDepthPass,
        Num,
    };
}
```

#### Step 2: 实现 FMeshPassProcessor 子类

```cpp
// ========================================
// MyCustomPassProcessor.h
// ========================================
#pragma once

#include "MeshPassProcessor.h"

class FMyCustomPassMeshProcessor : public FSceneRenderingAllocatorObject<FMyCustomPassMeshProcessor>,
                                    public FMeshPassProcessor
{
public:
    FMyCustomPassMeshProcessor(
        const FScene* Scene,
        ERHIFeatureLevel::Type FeatureLevel,
        const FSceneView* InViewIfDynamicMeshCommand,
        FMeshPassDrawListContext* InDrawListContext);

    // ★ Core: decide which meshes participate in this pass
    virtual void AddMeshBatch(
        const FMeshBatch& RESTRICT MeshBatch,
        uint64 BatchElementMask,
        const FPrimitiveSceneProxy* RESTRICT PrimitiveSceneProxy,
        int32 StaticMeshId = -1) override final;

    // PSO pre-caching support
    virtual void CollectPSOInitializers(
        const FSceneTexturesConfig& SceneTexturesConfig,
        const FMaterial& Material,
        const FPSOPrecacheVertexFactoryData& VertexFactoryData,
        const FPSOPrecacheParams& PreCacheParams,
        TArray<FPSOPrecacheData>& PSOInitializers) override final;

private:
    bool Process(
        const FMeshBatch& MeshBatch,
        uint64 BatchElementMask,
        int32 StaticMeshId,
        const FPrimitiveSceneProxy* RESTRICT PrimitiveSceneProxy,
        const FMaterialRenderProxy& RESTRICT MaterialRenderProxy,
        const FMaterial& RESTRICT MaterialResource,
        ERasterizerFillMode MeshFillMode,
        ERasterizerCullMode MeshCullMode);

    FMeshPassProcessorRenderState PassDrawRenderState;
};
```

```cpp
// ========================================
// MyCustomPassProcessor.cpp
// ========================================
#include "MyCustomPassProcessor.h"
#include "MeshPassProcessor.inl"

FMyCustomPassMeshProcessor::FMyCustomPassMeshProcessor(
    const FScene* Scene,
    ERHIFeatureLevel::Type FeatureLevel,
    const FSceneView* InViewIfDynamicMeshCommand,
    FMeshPassDrawListContext* InDrawListContext)
    : FMeshPassProcessor(
        EMeshPass::MyCustomPass,  // ★ Use our new pass type
        Scene, FeatureLevel,
        InViewIfDynamicMeshCommand, InDrawListContext)
{
    // Setup render state for this pass
    PassDrawRenderState.SetBlendState(TStaticBlendState<>::GetRHI());
    PassDrawRenderState.SetDepthStencilState(
        TStaticDepthStencilState<true, CF_DepthNearOrEqual>::GetRHI());
}

void FMyCustomPassMeshProcessor::AddMeshBatch(
    const FMeshBatch& RESTRICT MeshBatch,
    uint64 BatchElementMask,
    const FPrimitiveSceneProxy* RESTRICT PrimitiveSceneProxy,
    int32 StaticMeshId)
{
    // ★ Filter: decide which meshes should be rendered in this pass
    if (MeshBatch.bUseForMaterial && PrimitiveSceneProxy)
    {
        const FMaterialRenderProxy* MaterialRenderProxy = MeshBatch.MaterialRenderProxy;
        const FMaterial* Material = MaterialRenderProxy->GetMaterialNoFallback(FeatureLevel);

        if (Material && Material->GetRenderingThreadShaderMap())
        {
            // Example: only render opaque materials
            if (IsOpaqueOrMaskedBlendMode(*Material))
            {
                Process(MeshBatch, BatchElementMask, StaticMeshId,
                    PrimitiveSceneProxy, *MaterialRenderProxy, *Material,
                    ComputeMeshFillMode(*Material, MeshBatch, FeatureLevel),
                    ComputeMeshCullMode(*Material, MeshBatch));
            }
        }
    }
}

bool FMyCustomPassMeshProcessor::Process(
    const FMeshBatch& MeshBatch,
    uint64 BatchElementMask,
    int32 StaticMeshId,
    const FPrimitiveSceneProxy* RESTRICT PrimitiveSceneProxy,
    const FMaterialRenderProxy& RESTRICT MaterialRenderProxy,
    const FMaterial& RESTRICT MaterialResource,
    ERasterizerFillMode MeshFillMode,
    ERasterizerCullMode MeshCullMode)
{
    // Setup shader bindings
    TMeshProcessorShaders<
        FMyCustomPassVS,  // Your vertex shader
        FMyCustomPassPS   // Your pixel shader
    > PassShaders;

    // Get shaders from material
    FMaterialShaderTypes ShaderTypes;
    ShaderTypes.AddShaderType<FMyCustomPassVS>();
    ShaderTypes.AddShaderType<FMyCustomPassPS>();

    FMaterialShaders Shaders;
    if (!MaterialResource.TryGetShaders(ShaderTypes, nullptr, Shaders))
    {
        return false;
    }

    Shaders.TryGetVertexShader(PassShaders.VertexShader);
    Shaders.TryGetPixelShader(PassShaders.PixelShader);

    // Build mesh draw command
    FMeshDrawCommandSortKey SortKey = CalculateMeshStaticSortKey(
        PassShaders.VertexShader, PassShaders.PixelShader);

    BuildMeshDrawCommands(
        MeshBatch,
        BatchElementMask,
        PrimitiveSceneProxy,
        MaterialRenderProxy,
        MaterialResource,
        PassDrawRenderState,
        PassShaders,
        MeshFillMode,
        MeshCullMode,
        SortKey,
        EMeshPassFeatures::Default,
        ShaderElementData);

    return true;
}

void FMyCustomPassMeshProcessor::CollectPSOInitializers(
    const FSceneTexturesConfig& SceneTexturesConfig,
    const FMaterial& Material,
    const FPSOPrecacheVertexFactoryData& VertexFactoryData,
    const FPSOPrecacheParams& PreCacheParams,
    TArray<FPSOPrecacheData>& PSOInitializers)
{
    // PSO pre-caching for faster shader compilation
    // Similar to Process() but only collects PSO data
}
```

#### Step 3: 注册 MeshPassProcessor 工厂

```cpp
// At file scope (typically at the bottom of your .cpp file)

// Factory function
FMeshPassProcessor* CreateMyCustomPassProcessor(
    ERHIFeatureLevel::Type FeatureLevel,
    const FScene* Scene,
    const FSceneView* InViewIfDynamicMeshCommand,
    FMeshPassDrawListContext* InDrawListContext)
{
    return new FMyCustomPassMeshProcessor(
        Scene, FeatureLevel,
        InViewIfDynamicMeshCommand, InDrawListContext);
}

// ★ Register with the pass processor manager
FRegisterPassProcessorCreateFunction RegisterMyCustomPass(
    &CreateMyCustomPassProcessor,
    EShadingPath::Deferred,        // Which shading path
    EMeshPass::MyCustomPass,       // Our pass type
    EMeshPassFlags::CachedMeshCommands | EMeshPassFlags::MainView  // Flags
);
```

#### Step 4: 在 Renderer 中调度 Pass

```cpp
// In FDeferredShadingSceneRenderer::Render() or appropriate location

void FDeferredShadingSceneRenderer::RenderMyCustomPass(
    FRDGBuilder& GraphBuilder,
    TArrayView<FViewInfo> InViews,
    FSceneTextures& SceneTextures)
{
    for (int32 ViewIndex = 0; ViewIndex < InViews.Num(); ViewIndex++)
    {
        FViewInfo& View = InViews[ViewIndex];

        // Get the parallel mesh draw command pass
        FParallelMeshDrawCommandPass* Pass =
            View.GetMeshPass(EMeshPass::MyCustomPass);

        if (!Pass || !Pass->HasAnyDraw())
        {
            continue;
        }

        // Setup render targets
        auto* PassParameters = GraphBuilder.AllocParameters<FMyCustomPassParameters>();
        PassParameters->View = View.GetShaderParameters();
        PassParameters->RenderTargets[0] = FRenderTargetBinding(
            SceneTextures.Color.Target, ERenderTargetLoadAction::ELoad);
        PassParameters->RenderTargets.DepthStencil = FDepthStencilBinding(
            SceneTextures.Depth.Target,
            ERenderTargetLoadAction::ELoad,
            FExclusiveDepthStencil::DepthRead_StencilRead);

        // Add the pass to RDG
        GraphBuilder.AddPass(
            RDG_EVENT_NAME("MyCustomPass"),
            PassParameters,
            ERDGPassFlags::Raster,
            [this, &View, Pass, PassParameters](FRDGAsyncTask, FRHICommandList& RHICmdList)
            {
                // Set viewport
                RHICmdList.SetViewport(
                    View.ViewRect.Min.X, View.ViewRect.Min.Y, 0.0f,
                    View.ViewRect.Max.X, View.ViewRect.Max.Y, 1.0f);

                // Submit cached mesh draw commands
                Pass->DispatchDraw(nullptr, RHICmdList,
                    &PassParameters->InstanceCullingDrawParams);
            });
    }
}
```

### 5.3 SetupMeshPass 流程解析

```c++
FSceneRenderer::SetupMeshPass() 核心流程：

for (PassIndex = 0; PassIndex < EMeshPass::Num; PassIndex++)
{
    PassType = (EMeshPass::Type)PassIndex;

    // 1. Check if this pass should run for current shading path
    if (GetPassFlags(ShadingPath, PassType) & EMeshPassFlags::MainView)
    {
        // 2. Skip if no mesh commands for this pass
        if (MeshCommands[PassIndex].IsEmpty() &&
            NumVisibleDynamicMeshElements[PassType] == 0)
            continue;

        // 3. Create the MeshPassProcessor via factory
        FMeshPassProcessor* Processor =
            FPassProcessorManager::CreateMeshPassProcessor(
                ShadingPath, PassType, FeatureLevel, Scene, &View, nullptr);

        // 4. Create parallel pass
        FParallelMeshDrawCommandPass& Pass = *View.CreateMeshPass(PassType);

        // 5. Dispatch pass setup (builds mesh draw commands in parallel)
        Pass.DispatchPassSetup(
            Scene, View, InstanceCullingContext,
            PassType, BasePassDepthStencilAccess,
            Processor,
            View.DynamicMeshElements,
            &View.DynamicMeshElementsPassRelevance,
            View.NumVisibleDynamicMeshElements[PassType],
            ViewCommands.DynamicMeshCommandBuildRequests[PassType],
            ...);
    }
}
```

### 5.4 Mesh Draw Command 缓存机制

```
Static Mesh Draw Commands (缓存路径):
  ├─ 场景加载时，对每个 Static Mesh 调用 AddMeshBatch()
  ├─ 生成 FMeshDrawCommand 并缓存在 FScene::CachedMeshDrawCommandStateBuckets
  ├─ 每帧只需要做可见性测试，不需要重新生成 Command
  └─ 性能极好：O(1) per visible mesh

Dynamic Mesh Draw Commands (每帧路径):
  ├─ 每帧对 Dynamic Mesh 调用 AddMeshBatch()
  ├─ 每帧重新生成 FMeshDrawCommand
  ├─ 通过 Parallel Task 并行构建
  └─ 适用于：骨骼网格、粒子、程序化生成的几何体

关键优化：
  ├─ PSO Pre-caching: CollectPSOInitializers() 预编译 PSO
  ├─ Instancing: 相同 PSO + Shader Bindings 的 Command 自动合并
  ├─ GPU Scene: 实例数据通过 StructuredBuffer 传递
  └─ Instance Culling: GPU 端剔除不可见实例
```

---

## 6. 方案 D：使用 AddSimpleMeshPass（轻量级 Mesh Pass）

> 不需要注册 EMeshPass 枚举，适合临时性的、不需要缓存的 Mesh 绘制。

### 6.1 AddSimpleMeshPass 模板函数

```cpp
// Engine/Source/Runtime/Renderer/Public/SimpleMeshDrawCommandPass.h

template <typename PassParametersType, typename AddMeshBatchesCallbackLambdaType>
void AddSimpleMeshPass(
    FRDGBuilder& GraphBuilder,
    PassParametersType* PassParameters,
    const FGPUScene& GPUScene,
    const FSceneView& View,
    FInstanceCullingManager* InstanceCullingManager,
    FRDGEventName&& PassName,
    const FIntRect& ViewPortRect,
    const ERDGPassFlags& PassFlags,
    AddMeshBatchesCallbackLambdaType AddMeshBatchesCallback);
```

### 6.2 使用示例

```cpp
void RenderMySimplePass(
    FRDGBuilder& GraphBuilder,
    const FViewInfo& View,
    FSceneTextures& SceneTextures,
    const FScene* Scene)
{
    auto* PassParameters = GraphBuilder.AllocParameters<FMySimplePassParameters>();
    PassParameters->View = View.GetShaderParameters();
    PassParameters->RenderTargets[0] = FRenderTargetBinding(
        SceneTextures.Color.Target, ERenderTargetLoadAction::ELoad);
    PassParameters->RenderTargets.DepthStencil = FDepthStencilBinding(
        SceneTextures.Depth.Target, ERenderTargetLoadAction::ELoad,
        FExclusiveDepthStencil::DepthRead_StencilRead);

    AddSimpleMeshPass(
        GraphBuilder,
        PassParameters,
        Scene->GPUScene,
        View,
        nullptr, // InstanceCullingManager
        RDG_EVENT_NAME("MySimplePass"),
        View.ViewRect,
        ERDGPassFlags::Raster,
        [&View, Scene](FDynamicPassMeshDrawListContext* DynamicMeshPassContext)
        {
            // Create a temporary mesh pass processor
            FMyCustomPassMeshProcessor PassMeshProcessor(
                Scene,
                Scene->GetFeatureLevel(),
                &View,
                DynamicMeshPassContext);

            // Iterate over mesh batches and add them
            for (int32 MeshIndex = 0; MeshIndex < View.DynamicMeshElements.Num(); MeshIndex++)
            {
                const FMeshBatchAndRelevance& MeshAndRelevance =
                    View.DynamicMeshElements[MeshIndex];

                if (MeshAndRelevance.GetPrimitiveSceneProxy())
                {
                    PassMeshProcessor.AddMeshBatch(
                        *MeshAndRelevance.Mesh,
                        ~0ull,
                        MeshAndRelevance.GetPrimitiveSceneProxy());
                }
            }
        });
}
```

### 6.3 AddSimpleMeshPass vs 注册 EMeshPass 对比

| 维度     | AddSimpleMeshPass    | 注册 EMeshPass             |
| -------- | -------------------- | -------------------------- |
| 缓存     | ❌ 每帧重建 Command   | ✅ Static Mesh Command 缓存 |
| 性能     | 中（适合少量 Mesh）  | 高（大量 Mesh 也高效）     |
| 复杂度   | 低（无需改引擎）     | 高（需要改引擎枚举）       |
| 灵活性   | 高（运行时动态决定） | 中（编译时确定）           |
| 适用场景 | 调试、少量特殊物体   | 生产级 Pass                |

---

## 7. RDG (Render Dependency Graph) Pass 基础

> 所有方案最终都通过 `FRDGBuilder::AddPass()` 提交到 RDG。理解 RDG 是增加 Pass 的基础。

### 7.1 AddPass 基本用法

```cpp
// Raster Pass (draw calls)
GraphBuilder.AddPass(
    RDG_EVENT_NAME("MyRasterPass"),
    PassParameters,
    ERDGPassFlags::Raster,
    [](FRDGAsyncTask, FRHICommandList& RHICmdList)
    {
        // Issue draw calls here
    });

// Compute Pass
GraphBuilder.AddPass(
    RDG_EVENT_NAME("MyComputePass"),
    PassParameters,
    ERDGPassFlags::Compute,
    [](FRDGAsyncTask, FRHICommandList& RHICmdList)
    {
        // Dispatch compute shader here
    });

// Async Compute Pass
GraphBuilder.AddPass(
    RDG_EVENT_NAME("MyAsyncComputePass"),
    PassParameters,
    ERDGPassFlags::AsyncCompute,
    [](FRDGAsyncTask, FRHICommandList& RHICmdList)
    {
        // Dispatch on async compute queue
    });

// Copy Pass
AddCopyTexturePass(GraphBuilder, SrcTexture, DstTexture);

// Clear Pass
AddClearRenderTargetPass(GraphBuilder, Texture, ClearColor);
```

### 7.2 Pass Parameters 声明

```cpp
// Declare pass parameters struct
BEGIN_SHADER_PARAMETER_STRUCT(FMyPassParameters, )
    SHADER_PARAMETER_STRUCT_REF(FViewUniformShaderParameters, View)
    SHADER_PARAMETER_RDG_TEXTURE(Texture2D, SceneColorTexture)
    SHADER_PARAMETER_RDG_TEXTURE_UAV(RWTexture2D<float4>, OutputTexture)
    SHADER_PARAMETER_RDG_BUFFER_SRV(StructuredBuffer<float4>, InputBuffer)
    SHADER_PARAMETER_SAMPLER(SamplerState, LinearSampler)
    SHADER_PARAMETER(FVector4f, CustomParameter)
    RENDER_TARGET_BINDING_SLOTS()  // For raster passes
END_SHADER_PARAMETER_STRUCT()
```

### 7.3 RDG 资源生命周期

```
RDG 资源管理规则：

1. 创建（Create）
   FRDGTextureRef Tex = GraphBuilder.CreateTexture(Desc, TEXT("Name"));
   FRDGBufferRef Buf = GraphBuilder.CreateBuffer(Desc, TEXT("Name"));

2. 引用（Reference）
   通过 PassParameters 声明依赖关系
   RDG 自动推导 Pass 之间的执行顺序

3. 外部资源（External）
   FRDGTextureRef ExtTex = GraphBuilder.RegisterExternalTexture(PooledRT);
   // 或反向：
   TRefCountPtr<IPooledRenderTarget> Pooled = GraphBuilder.ConvertToExternalTexture(RDGTex);

4. 提取（Extract）
   GraphBuilder.QueueTextureExtraction(RDGTex, &OutputPooledRT);
   // 在 Execute() 后可用

5. 执行（Execute）
   GraphBuilder.Execute();
   // 所有 Pass 按依赖顺序执行
   // 临时资源自动释放
```

---

## 8. 实战案例：自定义描边 Pass

> 以一个常见需求——**物体描边（Outline）**为例，展示完整的 Pass 实现流程。

### 8.1 方案选择

```
描边方案分析：
  ├─ 后处理描边（基于深度/法线边缘检测）→ 方案 A (SceneViewExtension)
  ├─ 独立 Pass 描边（渲染背面放大的 Mesh）→ 方案 C (MeshPassProcessor)
  └─ Stencil 描边（标记 + 膨胀）→ 方案 A + Custom Stencil

推荐：后处理描边最简单，使用 SceneViewExtension
```

### 8.2 后处理描边实现

```cpp
// In SubscribeToPostProcessingPass:
void FOutlineViewExtension::SubscribeToPostProcessingPass(
    EPostProcessingPass Pass,
    const FSceneView& InView,
    FPostProcessingPassDelegateArray& InOutPassCallbacks,
    bool bIsPassEnabled)
{
    if (Pass == EPostProcessingPass::AfterDOF)
    {
        InOutPassCallbacks.Add(
            FAfterPassCallbackDelegate::CreateRaw(
                this, &FOutlineViewExtension::RenderOutline_RenderThread));
    }
}

FScreenPassTexture FOutlineViewExtension::RenderOutline_RenderThread(
    FRDGBuilder& GraphBuilder,
    const FSceneView& View,
    const FPostProcessMaterialInputs& Inputs)
{
    FScreenPassTexture SceneColor = Inputs.GetInput(EPostProcessMaterialInput::SceneColor);
    FScreenPassTexture SceneDepth = Inputs.GetInput(EPostProcessMaterialInput::SceneDepth);

    // Create output
    FScreenPassRenderTarget Output = Inputs.OverrideOutput;
    if (!Output.IsValid())
    {
        FRDGTextureDesc Desc = SceneColor.Texture->Desc;
        Desc.Reset();
        Desc.Flags |= TexCreate_RenderTargetable | TexCreate_ShaderResource;
        Output = FScreenPassRenderTarget(
            GraphBuilder.CreateTexture(Desc, TEXT("OutlineOutput")),
            ERenderTargetLoadAction::ENoAction);
    }

    // Setup shader parameters
    auto* PassParameters = GraphBuilder.AllocParameters<FOutlinePassParameters>();
    PassParameters->InputTexture = SceneColor.Texture;
    PassParameters->DepthTexture = SceneDepth.Texture;
    PassParameters->InputSampler = TStaticSamplerState<SF_Point>::GetRHI();
    PassParameters->OutlineColor = FVector4f(1.0f, 0.5f, 0.0f, 1.0f);
    PassParameters->OutlineThickness = 2.0f;
    PassParameters->DepthThreshold = 0.01f;
    PassParameters->RenderTargets[0] = FRenderTargetBinding(
        Output.Texture, ERenderTargetLoadAction::ENoAction);

    // Get shader
    TShaderMapRef<FOutlinePS> PixelShader(View.ShaderMap);
    TShaderMapRef<FScreenPassVS> VertexShader(View.ShaderMap);

    // Add pass
    FPixelShaderUtils::AddFullscreenPass(
        GraphBuilder,
        View.ShaderMap,
        RDG_EVENT_NAME("OutlinePass"),
        PixelShader,
        PassParameters,
        View.ViewRect);

    return MoveTemp(Output);
}
```

```hlsl
// OutlineShader.usf
#include "/Engine/Private/Common.ush"
#include "/Engine/Private/ScreenPass.ush"

Texture2D InputTexture;
Texture2D DepthTexture;
SamplerState InputSampler;
float4 OutlineColor;
float OutlineThickness;
float DepthThreshold;

void MainPS(
    float4 SvPosition : SV_POSITION,
    out float4 OutColor : SV_Target0)
{
    float2 UV = SvPosition.xy * View.BufferSizeAndInvSize.zw;
    float2 TexelSize = View.BufferSizeAndInvSize.zw * OutlineThickness;

    // Sample depth at current pixel and neighbors
    float DepthCenter = DepthTexture.Sample(InputSampler, UV).r;
    float DepthLeft   = DepthTexture.Sample(InputSampler, UV + float2(-TexelSize.x, 0)).r;
    float DepthRight  = DepthTexture.Sample(InputSampler, UV + float2( TexelSize.x, 0)).r;
    float DepthUp     = DepthTexture.Sample(InputSampler, UV + float2(0, -TexelSize.y)).r;
    float DepthDown   = DepthTexture.Sample(InputSampler, UV + float2(0,  TexelSize.y)).r;

    // Sobel-like edge detection on depth
    float EdgeH = abs(DepthLeft - DepthRight);
    float EdgeV = abs(DepthUp - DepthDown);
    float Edge = max(EdgeH, EdgeV);

    // Original scene color
    float4 SceneColor = InputTexture.Sample(InputSampler, UV);

    // Blend outline
    float OutlineMask = step(DepthThreshold, Edge);
    OutColor = lerp(SceneColor, OutlineColor, OutlineMask * OutlineColor.a);
}
```

---

## 9. 面试高频问题

### Q1: UE5 中增加自定义渲染 Pass 有哪些方式？各自适用场景？

```
答：主要有 4 种方式：

1. SceneViewExtension（最推荐）
   - 通过 ISceneViewExtension 接口在管线各阶段插入回调
   - 适用：后处理效果、调试可视化、GBuffer 后处理
   - 优点：无需改引擎，插件级别即可
   - 扩展点：PostRenderBasePassDeferred、SubscribeToPostProcessingPass 等

2. FCustomRenderPassBase
   - 创建独立的渲染通道，有自己的视图和渲染目标
   - 适用：Scene Capture、多视角渲染、自定义深度输出
   - 通过 FScene::AddCustomRenderPass() 入队，执行一次后自动移除

3. 自定义 MeshPassProcessor（需改引擎）
   - 在 EMeshPass 枚举中新增类型，实现 FMeshPassProcessor 子类
   - 适用：需要参与 Mesh Draw Command 缓存的生产级 Pass
   - 通过 FRegisterPassProcessorCreateFunction 注册工厂函数
   - 在 SetupMeshPass() 中自动被调度

4. AddSimpleMeshPass（轻量级）
   - 模板函数，不需要注册枚举
   - 适用：少量 Mesh 的临时绘制、调试
   - 每帧重建 Command，不参与缓存
```

### Q2: FMeshPassProcessor 的 AddMeshBatch 做了什么？

```
答：AddMeshBatch 是 MeshPassProcessor 的核心函数，负责：

1. 过滤（Filter）
   - 判断该 Mesh 是否应该参与当前 Pass
   - 例如：CustomDepth Pass 只处理标记了 bRenderCustomDepth 的物体
   - BasePass 只处理不透明和 Masked 材质

2. 材质获取
   - 从 MeshBatch.MaterialRenderProxy 获取 FMaterial
   - 检查 Shader Map 是否可用

3. Shader 选择
   - 根据 Pass 类型选择对应的 VS/PS
   - 通过 FMaterialShaderTypes 指定需要的 Shader 类型

4. 渲染状态设置
   - Blend State、DepthStencil State、Rasterizer State
   - 通过 FMeshPassProcessorRenderState 配置

5. 生成 FMeshDrawCommand
   - 调用 BuildMeshDrawCommands() 生成缓存的绘制命令
   - 包含 PSO、Shader Bindings、VB/IB、Draw Arguments
   - Static Mesh 的 Command 会被缓存，Dynamic Mesh 每帧重建
```

### Q3: RDG (Render Dependency Graph) 的作用？如何添加 Pass？

```
答：
RDG 的作用：
  - 自动管理渲染资源的生命周期（创建、使用、释放）
  - 自动推导 Pass 之间的依赖关系和执行顺序
  - 自动插入资源屏障（Barrier）
  - 支持资源别名（Aliasing）减少内存占用
  - 支持异步计算（Async Compute）调度

添加 Pass 的步骤：
  1. 声明 Pass Parameters 结构体（BEGIN_SHADER_PARAMETER_STRUCT）
  2. 分配并填充参数（GraphBuilder.AllocParameters）
  3. 调用 GraphBuilder.AddPass() 提交
  4. 在 Lambda 中执行实际渲染逻辑

Pass 类型：
  - ERDGPassFlags::Raster        → 光栅化 Pass（Draw Calls）
  - ERDGPassFlags::Compute       → 同步计算 Pass
  - ERDGPassFlags::AsyncCompute  → 异步计算 Pass
  - ERDGPassFlags::Copy          → 资源拷贝 Pass
```

### Q4: SceneViewExtension 的 SubscribeToPostProcessingPass 如何工作？

```
答：
工作流程：
  1. 引擎在后处理开始时，遍历所有注册的 SceneViewExtension
  2. 对每个 Extension 调用 SubscribeToPostProcessingPass()
  3. Extension 通过 InOutPassCallbacks.Add() 注册回调到指定的 Pass 位置
  4. 引擎按顺序执行后处理链，在对应位置调用注册的回调

可订阅的位置（EPostProcessingPass）：
  - BeforeDOF → DOF 之前
  - AfterDOF → DOF 之后
  - SSRInput → SSR 输入
  - ReplacingTonemapper → 替换 Tonemapper
  - MotionBlur → 运动模糊后
  - Tonemap → Tonemapping 后
  - FXAA → FXAA 后

注意事项：
  - 如果回调是链中最后一个 Pass，OverrideOutput 会有效
  - 此时必须写入 OverrideOutput，否则画面会黑屏
  - 建议只在需要时才订阅，避免不必要的性能开销
```

### Q5: Mesh Draw Command 缓存机制是什么？为什么重要？

```
答：
UE4.22+ 引入的 Mesh Draw Command 缓存是渲染性能的关键优化：

传统方式（UE4 早期）：
  每帧 → 遍历所有可见 Mesh → 调用 DrawDynamicMesh → 生成 RHI 命令
  问题：CPU 开销大，DrawCall 多时严重瓶颈

缓存方式（UE4.22+/UE5）：
  场景加载时 → 对 Static Mesh 调用 AddMeshBatch → 生成 FMeshDrawCommand → 缓存
  每帧 → 可见性测试 → 直接提交缓存的 Command → 极低 CPU 开销

FMeshDrawCommand 包含：
  ├─ PSO (Pipeline State Object) → 完整的渲染管线状态
  ├─ ShaderBindings → Shader 参数绑定
  ├─ VertexStreams → 顶点缓冲区绑定
  ├─ IndexBuffer → 索引缓冲区
  └─ DrawArguments → 绘制参数（顶点数、实例数等）

性能收益：
  - Static Mesh     ：O(1) per visible mesh（只需可见性测试）
  - 自动 Instancing ：相同 PSO + Bindings 的 Command 合并
  - 并行构建        ：Dynamic Mesh 的 Command 通过 Task Graph 并行生成
  - PSO Pre-caching ：提前编译 PSO，避免运行时卡顿

这就是为什么自定义 MeshPassProcessor 需要注册到 EMeshPass：
  只有注册的 Pass 才能参与缓存系统，获得最佳性能。
```

---

## 10. 各方案决策树

```
需要增加自定义渲染 Pass？
│
├─ 是后处理效果？（全屏 Shader、滤镜、描边等）
│   └─ YES → 方案 A: SceneViewExtension + SubscribeToPostProcessingPass
│
├─ 需要在 GBuffer 填充后、光照前插入？
│   └─ YES → 方案 A: SceneViewExtension + PostRenderBasePassDeferred
│
├─ 需要独立视角/独立渲染目标？（Scene Capture、小地图）
│   └─ YES → 方案 B: FCustomRenderPassBase
│
├─ 需要自定义 Mesh 过滤/绘制逻辑？
│   ├─ 少量 Mesh / 临时需求？
│   │   └─ YES → 方案 D: AddSimpleMeshPass
│   └─ 大量 Mesh / 生产级需求？
│       └─ YES → 方案 C: 自定义 MeshPassProcessor + EMeshPass
│
└─ 需要深度修改渲染管线？（修改 GBuffer 布局、新增光照模型）
    └─ YES → 直接修改 FDeferredShadingSceneRenderer
```
