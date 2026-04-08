---
layout:     post
title:      后期处理
subtitle:   后期处理
date:       2024-01-10
author:     kang
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - 渲染
---

# Unreal Engine 后期处理系统

## 目录

- [系统架构](#系统架构)
- [后期处理系统架构](#后期处理系统架构)
- [初始化流程](#初始化流程)
- [生命周期](#生命周期)
- [各效果模块](#各效果模块)
- [改造方向与优化点](#改造方向与优化点)
- [手机平台适配方案](#手机平台适配方案)

---

## 系统架构

```
UWorld
  └── APostProcessVolume (AActor)
        └── FPostProcessSettings (参数结构体)
              ├── Bloom
              ├── AmbientOcclusion (SSAO)
              ├── ScreenSpaceGlobalIllumination (SSGI)
              ├── ScreenSpaceReflections (SSR)
              ├── AutoExposure (HDR/EV)
              ├── ToneMapping
              ├── HeightFog
              ├── VolumetricLighting
              └── ...

FSceneRenderer
  ├── FDeferredShadingSceneRenderer
  │     └── Render()
  │           ├── RenderBasePass
  │           ├── RenderLights
  │           ├── RenderAmbientOcclusion   ← SSAO
  │           ├── RenderDiffuseIndirect    ← SSGI
  │           ├── RenderReflections        ← SSR
  │           ├── RenderFog                ← HeightFog / VolumetricFog
  │           └── AddPostProcessingPasses  ← Bloom/Tonemap/etc
  └── FMobileSceneRenderer
        └── Render() (移动端简化流程)
```

---

## 后期处理系统架构

### 整体架构

```
UEngine
  └── UGameViewportClient
        └── FViewport
              └── FSceneRenderer (FDeferredShadingSceneRenderer / FMobileSceneRenderer)
                    └── FPostProcessing
                          ├── FRenderingCompositePassContext
                          ├── FPostProcessPassParameters
                          └── PostProcess Passes (各效果Pass)
```

### 核心类关系

| 类名                        | 职责                         |
| --------------------------- | ---------------------------- |
| `FPostProcessing`           | 后期处理总入口，管理所有Pass |
| `FRenderingCompositeGraph`  | Pass依赖图，管理Pass执行顺序 |
| `FRenderingCompositePass`   | 单个后期Pass基类             |
| `APostProcessVolume`        | 场景中的后期处理体积         |
| `FPostProcessSettings`      | 后期处理参数集合结构体       |
| `UPostProcessComponent`     | 后期处理组件（挂载到Actor）  |
| `FFinalPostProcessSettings` | 混合后的最终参数             |

### 渲染管线位置

```
GBuffer Pass
  └── Lighting Pass
        └── Translucency Pass
              └── [POST PROCESS BEGIN]
                    ├── Temporal AA (TAA/TSR)
                    ├── Depth of Field (DOF)
                    ├── Motion Blur
                    ├── Bloom
                    ├── Lens Flare
                    ├── Eye Adaptation (Auto Exposure)
                    ├── Color Grading / Tonemapping
                    ├── SSAO / SSGI
                    ├── SSR
                    ├── Vignette / Grain
                    └── [POST PROCESS END]
                          └── UI / HUD
```

## 初始化流程

### 引擎启动阶段

```
FEngineLoop::Init()
  └── UEngine::Init()
        ├─── FSceneInterface::CreateScene()
        │     └── FScene::FScene()
        │           └── 注册 PostProcessVolume 管理器
        └── FRendererModule::CreateScene()
              └── FScene::FScene()
                    └── 注册后期处理相关RHI资源
```

### 场景渲染器创建

```
FRendererModule::BeginRenderingViewFamily()
  └── CreateSceneRenderer()
        ├── 判断平台 → FDeferredShadingSceneRenderer (PC/主机)
        │                  或 FMobileSceneRenderer (移动端)
        └── FSceneRenderer::FSceneRenderer()
              └── 初始化 ViewFamily、Views、PostProcessSettings
```

### 场景渲染器初始化
```
FSceneRenderer::CreateSceneRenderer()
  ├── FDeferredShadingSceneRenderer (PC/主机)
  │     └── InitViews()
  │           └── FSceneView::SetupCommonViewUniformBufferParameters()
  │                 └── 初始化 PostProcessSettings
  └── FMobileSceneRenderer (移动端)
        └── InitViews()
              └── 初始化移动端简化后期参数
```

### PostProcess Volume 注册流程

```
APostProcessVolume::BeginPlay()
  └── UPostProcessComponent::OnRegister()
        └── GetWorld()->Scene->AddPostProcessVolume(this)
              └── FScene::AddPostProcessVolume()
                    └── 加入 FScene::PostProcessVolumes 列表排序（Priority）
                          └── 按优先级排序 按 Priority + bUnbound 决定混合权重
```
### 参数混合初始化

```
FSceneRenderer::InitViews()
  └── FSceneView::StartFinalPostprocessSettings()
        └── 遍历所有 PostProcessVolumes
              └── FSceneView::OverridePostProcessSettings()
                    └── 按权重混合参数到 FFinalPostProcessSettings
```

### 渲染参数收集

```
FSceneRenderer::ComputeViewVisibility()
  └── FPostProcessSettings 混合计算
        ├── 遍历所有 PostProcessVolume
        ├── 计算 BlendWeight（距离/范围）
        └── 最终 FinalPostProcessSettings 写入 FSceneView
```

---

## 生命周期

### 渲染帧生命周期

```
Game Thread:
  UWorld::Tick()
    └── FScene::UpdatePostProcessVolume()
          └── 更新 Volume 参数到渲染线程

Render Thread:
  FDeferredShadingSceneRenderer::Render()
    │
    ├── [1] PrePass (Depth Prepass)
    ├── [2] BasePass (GBuffer 填充)
    │         GBufferA: Normal
    │         GBufferB: Metallic/Specular/Roughness
    │         GBufferC: BaseColor
    │         GBufferD: CustomData
    │         SceneDepth: 深度
    │
    ├── [3] RenderAmbientOcclusion()       ← SSAO
    ├── [4] RenderDiffuseIndirect()        ← SSGI
    ├── [5] RenderReflections()            ← SSR
    ├── [6] RenderLights()                 ← 光照
    ├── [7] RenderFog()                    ← HeightFog / VolumetricFog
    │
    └── [8] AddPostProcessingPasses()
              ├── Bloom (提取高亮 → 模糊 → 叠加)
              ├── AutoExposure (亮度直方图/EV计算)
              ├── ToneMapping (ACES/Filmic)
              ├── DepthOfField
              ├── MotionBlur
              ├── ChromaticAberration
              ├── Vignette
              └── Final Output (Gamma/sRGB)
```

### PostProcess Pass 执行顺序

| 顺序 | Pass 名称        | 输入                         | 输出             |
| ---- | ---------------- | ---------------------------- | ---------------- |
| 1    | SSAO             | GBuffer + Depth              | AO Mask          |
| 2    | SSGI             | GBuffer + Depth + History    | Indirect Diffuse |
| 3    | SSR              | GBuffer + SceneColor + Depth | Reflection       |
| 4    | Lighting Combine | GBuffer + AO + SSGI + SSR    | SceneColor HDR   |
| 5    | HeightFog        | SceneColor + Depth           | SceneColor + Fog |
| 6    | Bloom Extract    | SceneColor HDR               | Bright Mask      |
| 7    | Bloom Blur       | Bright Mask                  | Bloom Texture    |
| 8    | AutoExposure     | SceneColor HDR               | EV Luma          |
| 9    | ToneMapping      | SceneColor HDR + EV          | SceneColor LDR   |
| 10   | Final Post       | SceneColor LDR               | Backbuffer       |

### 每帧渲染生命周期

```
FDeferredShadingSceneRenderer::Render()
  │
  ├── 1. PrePass (深度预通道)
  ├── 2. BasePass (GBuffer填充)
  ├── 3. ShadowDepths
  ├── 4. Lighting
  ├── 5. Translucency
  │
  └── 6. PostProcessing ← 后期处理入口
        │
        ├── AddPostProcessingPasses()
        │     ├── 构建 FRenderingCompositeGraph
        │     ├── 注册所有激活的 Pass
        │     └── 解析 Pass 依赖关系
        │
        ├── FRenderingCompositeGraph::Execute()
        │     ├── 拓扑排序 Pass
        │     └── 按序执行每个 Pass
        │           ├── Pass::Process()
        │           │     ├── SetShader()
        │           │     ├── SetParameters()
        │           │     └── DrawRectangle() / Dispatch()
        │           └── 输出写入 RenderTarget
        │
        └── 最终输出到 BackBuffer
```

### PostProcessVolume 生命周期

```
Actor Spawn
  └── APostProcessVolume::PostInitializeComponents()
        └── UPostProcessComponent::OnRegister()
              └── 注册到 FScene

每帧
  └── FSceneView::StartFinalPostprocessSettings()
        └── 检测摄像机是否在 Volume 内
              ├── 在内部 → 按 BlendWeight 混合参数
              └── 在外部 → 检查 Unbound 标志

Actor Destroy
  └── UPostProcessComponent::OnUnregister()
        └── FScene::RemovePostProcessVolume()
```

### 自定义 Pass 生命周期

```
注册阶段：
  FRendererModule::RegisterPostOpaqueRenderDelegate()
  或
  GetRendererModule().RegisterOverlayRenderDelegate()

执行阶段（每帧）：
  FPostOpaqueRenderParameters 回调
    └── 自定义渲染逻辑

注销阶段：
  FDelegateHandle::Reset()
```

---

## 各效果模块

详见各子文档：
- [SSAO 文档](./SSAO.md)
- [SSGI 文档](./SSGI.md)
- [SSR 文档](./SSR.md)
- [HDR & AutoExposure 文档](./HDR_AutoExposure.md)
- [ToneMapping 文档](./ToneMapping.md)
- [HeightFog 文档](./HeightFog.md)
- [VolumetricLighting 文档](./VolumetricLighting.md)
- [Bloom 文档](./Bloom.md)

---

## 改造方向与优化点

### 通用优化策略

| 优化方向   | 说明                                   | 优先级 |
| ---------- | -------------------------------------- | ------ |
| 异步计算   | 将 SSAO/SSR 等移至 AsyncCompute Queue  | 高     |
| 时间性复用 | TAA/TSR 复用历史帧数据减少采样数       | 高     |
| 分辨率缩放 | 以半分辨率运行 SSAO/SSR/Bloom          | 高     |
| Pass 合并  | 合并多个小 Pass 减少 RenderTarget 切换 | 中     |
| 遮挡剔除   | 对不可见区域跳过后期计算               | 中     |

### 手机平台专项

| 优化方向         | 说明                             |
| ---------------- | -------------------------------- |
| 禁用 SSGI        | 移动端改用 Lumen 简化版或纯 IBL  |
| SSR → 平面反射   | 用 PlanarReflection 替代 SSR     |
| SSAO 简化        | 使用 Mobile SSAO（低采样数）     |
| ToneMapping 简化 | 使用 Neutral Tonemapper 降低 ALU |
| Bloom 降质       | 减少 Bloom 迭代次数              |

---

## 手机平台适配方案

详见 [手机平台适配方案](./Mobile_Adaptation.md)

