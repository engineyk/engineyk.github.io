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
- [各效果模块详解](#各效果模块详解)
  - [SSAO](#ssao-屏幕空间环境光遮蔽)
  - [SSGI](#ssgi-屏幕空间全局光照)
  - [SSR](#ssr-屏幕空间反射)
  - [HDR & AutoExposure](#hdr--autoexposure-自动曝光)
  - [ToneMapping](#tonemapping-色调映射)
  - [Bloom](#bloom-泛光)
  - [HeightFog](#heightfog-高度雾)
  - [VolumetricLighting](#volumetriclighting-体积光照)
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

---

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

## 各效果模块详解

### SSAO 屏幕空间环境光遮蔽

#### 原理

SSAO（Screen Space Ambient Occlusion）通过在屏幕空间对深度缓冲进行采样，估算每个像素周围的遮蔽程度，模拟环境光在凹陷、缝隙处的衰减效果。

#### 核心流程

```
RenderAmbientOcclusion()
  │
  ├── [1] AO Setup Pass
  │     ├── 输入: SceneDepth + GBufferA(Normal)
  │     ├── 降采样深度/法线到半分辨率
  │     └── 输出: HalfRes Depth + Normal
  │
  ├── [2] AO Compute Pass (Shader: AmbientOcclusion.usf)
  │     ├── 在半球面随机采样 N 个点（默认8~16个）
  │     ├── 将采样点投影到屏幕空间
  │     ├── 与深度缓冲比较判断遮蔽
  │     └── 输出: AO Mask (R8)
  │
  ├── [3] Blur Pass
  │     ├── 双边滤波（保边模糊）
  │     └── 输出: Blurred AO Mask
  │
  └── [4] Composite Pass
        ├── 将 AO Mask 乘入 SceneColor
        └── 输出: SceneColor with AO
```

#### 关键参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `AmbientOcclusionIntensity` | AO 强度 | 0.5 |
| `AmbientOcclusionRadius` | 采样半径（世界空间单位） | 200 |
| `AmbientOcclusionQuality` | 采样质量（影响采样数） | 50 |
| `AmbientOcclusionBias` | 深度偏移，防止自遮蔽 | 3.0 |
| `AmbientOcclusionFadeDistance` | AO 淡出距离 | 8000 |
| `AmbientOcclusionPower` | AO 对比度（Gamma） | 2.0 |

#### 相关 Shader 文件

```
Engine/Shaders/Private/
  ├── AmbientOcclusion.usf          // SSAO 主 Shader
  ├── PostProcessAmbientOcclusion.cpp // C++ 入口
  └── HZB.usf                       // Hierarchical Z-Buffer
```

#### 优化方向

- 使用 **GTAO**（Ground Truth AO）替代传统 SSAO，精度更高
- 半分辨率计算 + 时间性复用（TAA 积累）
- 使用 HZB（层级深度缓冲）加速遮蔽查询
- 移动端可用 **HBAO** 简化版或直接烘焙 AO 贴图

---

### SSGI 屏幕空间全局光照

#### 原理

SSGI（Screen Space Global Illumination）在屏幕空间追踪光线，利用已有的 SceneColor 作为光源，计算间接漫反射光照，是 Lumen 的低配替代方案。

#### 核心流程

```
RenderDiffuseIndirect()
  │
  ├── [1] 判断 GI 方案
  │     ├── Lumen → RenderLumenDiffuseIndirect()
  │     ├── SSGI  → RenderScreenSpaceGlobalIllumination()
  │     └── None  → 跳过
  │
  ├── [2] SSGI Trace Pass
  │     ├── 输入: GBuffer + SceneColor + SceneDepth + History
  │     ├── 每像素发射 N 条屏幕空间光线
  │     ├── 步进采样 SceneColor 作为间接光源
  │     └── 输出: Raw Indirect Diffuse
  │
  ├── [3] Temporal Accumulation
  │     ├── 与历史帧混合（减少噪点）
  │     ├── 使用 MotionVector 做重投影
  │     └── 输出: Denoised Indirect Diffuse
  │
  └── [4] Composite
        ├── 叠加到 SceneColor
        └── 输出: SceneColor + GI
```

#### 关键参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `ScreenSpaceGIEnabled` | 是否启用 SSGI | false |
| `r.SSGI.Quality` | 质量等级 1~4 | 4 |
| `r.SSGI.HalfRes` | 半分辨率计算 | 1 |
| `r.SSGI.MaxRayDistance` | 最大光线追踪距离 | 0（自动） |

#### 局限性

- 只能处理屏幕内可见的间接光，屏幕外物体无法贡献 GI
- 高频噪点需要时间性积累去噪，存在 Ghosting 问题
- 移动端性能开销过大，通常禁用

---

### SSR 屏幕空间反射

#### 原理

SSR（Screen Space Reflections）通过在屏幕空间进行光线步进（Ray Marching），利用深度缓冲查找反射交点，采样 SceneColor 作为反射颜色。

#### 核心流程

```
RenderReflections()
  │
  ├── [1] 判断反射方案
  │     ├── Lumen Reflections → RenderLumenReflections()
  │     ├── SSR              → RenderScreenSpaceReflections()
  │     └── Fallback         → 使用 Reflection Capture (IBL)
  │
  ├── [2] SSR Trace Pass (Shader: ScreenSpaceReflections.usf)
  │     ├── 输入: GBuffer(Roughness/Normal) + SceneColor + HZB
  │     ├── 根据粗糙度决定反射光线方向（镜面 → 模糊）
  │     ├── HZB 加速光线步进（层级深度跳跃）
  │     └── 输出: Raw SSR Color + Hit Mask
  │
  ├── [3] Temporal Filter
  │     ├── 历史帧重投影积累
  │     └── 输出: Filtered SSR
  │
  └── [4] Composite
        ├── 根据 Roughness 混合 SSR 与 IBL
        └── 输出: Final Reflection
```

#### 关键参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `ScreenSpaceReflectionIntensity` | SSR 强度 | 100 |
| `ScreenSpaceReflectionQuality` | 质量（影响步进次数） | 50 |
| `ScreenSpaceReflectionMaxRoughness` | 最大粗糙度（超过则用 IBL） | 0.6 |
| `r.SSR.HalfResScatter` | 半分辨率散射 | 0 |
| `r.SSR.Temporal` | 时间性积累 | 1 |

#### 优化方向

- 使用 HZB 替代逐步步进，大幅减少采样次数
- 半分辨率 + 时间性重建
- 粗糙度超过阈值时 Fallback 到 Reflection Capture
- 移动端用 **PlanarReflection** 替代（仅适用于平面）

---

### HDR & AutoExposure 自动曝光

#### 原理

AutoExposure（Eye Adaptation）模拟人眼对亮度的适应过程，通过计算场景亮度直方图，动态调整曝光值（EV），使画面亮度保持在合理范围。

#### 核心流程

```
AutoExposure 流程:
  │
  ├── [1] Luminance Histogram Pass
  │     ├── 输入: SceneColor HDR
  │     ├── 计算每个像素的亮度 (Luminance = dot(color, (0.2126, 0.7152, 0.0722)))
  │     ├── 构建亮度直方图（64 bins）
  │     └── 输出: Histogram Buffer
  │
  ├── [2] Exposure Compute Pass
  │     ├── 读取直方图
  │     ├── 计算加权平均亮度（排除极亮/极暗区域）
  │     ├── 与目标亮度比较，计算 EV 调整量
  │     ├── 按 SpeedUp/SpeedDown 平滑插值
  │     └── 输出: EV Value (存入 1x1 RenderTarget)
  │
  └── [3] Apply Exposure
        ├── ToneMapping 阶段读取 EV
        └── SceneColor *= EV
```

#### 关键参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `AutoExposureMethod` | 直方图/基础/手动 | Histogram |
| `AutoExposureBias` | 曝光补偿（EV） | 0 |
| `AutoExposureMinBrightness` | 最小亮度限制 | 0.03 |
| `AutoExposureMaxBrightness` | 最大亮度限制 | 8.0 |
| `AutoExposureSpeedUp` | 变亮速度（s） | 3.0 |
| `AutoExposureSpeedDown` | 变暗速度（s） | 1.0 |
| `AutoExposureLowPercent` | 直方图低百分位 | 80 |
| `AutoExposureHighPercent` | 直方图高百分位 | 98.3 |

#### HDR 输出

```
HDR 渲染流程:
  SceneColor (线性 HDR, FP16)
    └── AutoExposure 调整
          └── ToneMapping (HDR → LDR)
                └── Gamma Correction (Linear → sRGB)
                      └── 输出到显示器

支持 HDR 显示器时:
  SceneColor (线性 HDR)
    └── AutoExposure
          └── HDR ToneMapping (ST2084/PQ 曲线)
                └── 输出到 HDR 显示器 (Rec.2020)
```

---

### ToneMapping 色调映射

#### 原理

ToneMapping 将线性 HDR 场景颜色映射到显示器可显示的 LDR 范围（0~1），同时进行色彩分级（Color Grading）。

#### 核心流程

```
ToneMapping Pass (Shader: PostProcessTonemap.usf)
  │
  ├── 输入: SceneColor HDR + EV + LUT Texture
  │
  ├── [1] 应用 AutoExposure EV
  │     └── color *= EV
  │
  ├── [2] Bloom 叠加
  │     └── color += BloomTexture * BloomIntensity
  │
  ├── [3] Color Grading (LUT)
  │     ├── 将颜色映射到 32x32x32 LUT 纹理
  │     └── 支持: 饱和度/对比度/色调/阴影高光分离
  │
  ├── [4] Tonemapping 曲线
  │     ├── ACES (Academy Color Encoding System) ← 默认
  │     ├── Filmic (自定义 S 曲线)
  │     ├── Reinhard
  │     ├── Neutral (低 ALU，移动端推荐)
  │     └── Linear (不做映射)
  │
  ├── [5] Vignette / Grain
  │
  └── [6] Gamma Correction
        └── Linear → sRGB (pow(x, 1/2.2))
```

#### ACES 曲线特性

```
亮度映射:
  0.0  → 0.0   (纯黑保持)
  0.18 → 0.18  (中灰保持)
  1.0  → ~0.8  (高光压缩)
  ∞    → 1.0   (极亮收敛到白)

特点:
  - 高光区域自然压缩，避免过曝
  - 暗部细节保留
  - 色彩饱和度在高光区域适当降低（模拟胶片）
```

#### 关键参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `ToneCurveAmount` | Tonemapping 强度 | 1.0 |
| `FilmSlope` | 曲线斜率（对比度） | 0.88 |
| `FilmToe` | 暗部曲线 | 0.55 |
| `FilmShoulder` | 高光曲线 | 0.26 |
| `FilmBlackClip` | 黑点裁剪 | 0.0 |
| `FilmWhiteClip` | 白点裁剪 | 0.04 |
| `ColorSaturation` | 饱和度 | (1,1,1,1) |
| `ColorContrast` | 对比度 | (1,1,1,1) |

---

### Bloom 泛光

#### 原理

Bloom 模拟相机/人眼对强光的散射效果，提取超过阈值的高亮区域，进行多级模糊后叠加回原图。

#### 核心流程

```
Bloom 流程 (Shader: PostProcessBloom.usf)
  │
  ├── [1] Bloom Setup (提取高亮)
  │     ├── 输入: SceneColor HDR
  │     ├── 阈值过滤: color = max(0, color - Threshold)
  │     ├── 降采样到 1/4 分辨率
  │     └── 输出: Bloom Input
  │
  ├── [2] Downsample Chain (逐级降采样)
  │     ├── 1/4 → 1/8 → 1/16 → 1/32 → 1/64
  │     └── 每级使用 13-tap Karis Average 降采样
  │
  ├── [3] Upsample Chain (逐级上采样叠加)
  │     ├── 1/64 → 1/32 → 1/16 → 1/8 → 1/4
  │     ├── 每级使用 9-tap 双线性上采样
  │     └── 每级叠加对应尺寸的 Bloom 贡献
  │
  └── [4] Composite
        ├── Bloom Texture * Intensity 叠加到 SceneColor
        └── 在 ToneMapping Pass 中完成
```

#### 关键参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `BloomIntensity` | Bloom 整体强度 | 0.675 |
| `BloomThreshold` | 提取高亮阈值 | -1（自动） |
| `BloomSizeScale` | Bloom 扩散尺寸 | 4.0 |
| `Bloom1Size~6Size` | 各级 Bloom 尺寸 | 0.3~64 |
| `Bloom1Tint~6Tint` | 各级 Bloom 颜色 | 白色 |
| `BloomMethod` | Standard / Convolution | Standard |

---

### HeightFog 高度雾

#### 原理

HeightFog 根据像素深度和高度计算雾的浓度，模拟大气散射效果。支持指数高度雾（Exponential Height Fog）。

#### 核心流程

```
RenderFog() → RenderExponentialHeightFog()
  │
  ├── 输入: SceneColor + SceneDepth
  │
  ├── [1] 重建世界坐标
  │     └── 从 Depth + InvViewProj 重建像素世界位置
  │
  ├── [2] 计算雾密度
  │     ├── 指数高度雾公式:
  │     │   FogDensity = FogDensity * exp(-FogHeightFalloff * (WorldZ - FogHeight))
  │     ├── 积分视线方向上的雾密度
  │     └── 支持两层雾叠加
  │
  ├── [3] 计算雾颜色
  │     ├── 方向性散射（InscatteringColor）
  │     ├── 定向散射（DirectionalInscatteringColor）
  │     └── 与太阳方向相关的散射
  │
  └── [4] 混合
        └── SceneColor = lerp(SceneColor, FogColor, FogFactor)
```

#### 关键参数

| 参数 | 说明 |
|------|------|
| `FogDensity` | 雾基础密度 |
| `FogHeightFalloff` | 高度衰减系数（越大雾层越薄） |
| `FogMaxOpacity` | 最大不透明度 |
| `StartDistance` | 雾开始距离 |
| `FogInscatteringColor` | 雾散射颜色 |
| `DirectionalInscatteringExponent` | 定向散射指数 |
| `VolumetricFog` | 是否启用体积雾 |

---

### VolumetricLighting 体积光照

#### 原理

Volumetric Fog 通过 3D Froxel（视锥体体素）网格，在视锥体内计算每个体素的散射/吸收，模拟丁达尔效应（光柱）、烟雾、云层等体积效果。

#### 核心流程

```
RenderVolumetricFog()
  │
  ├── [1] Voxelize Pass
  │     ├── 将视锥体划分为 3D Froxel 网格（默认 160x90x64）
  │     ├── 注入参与介质参数（散射系数、吸收系数）
  │     └── 注入光源贡献（点光/方向光/聚光）
  │
  ├── [2] Light Scattering Pass
  │     ├── 对每个 Froxel 计算光照散射
  │     ├── 支持阴影（Shadow Map 采样）
  │     └── 输出: 3D Scattering Texture
  │
  ├── [3] Temporal Integration
  │     ├── 与历史帧 3D Texture 混合
  │     └── 减少时间性噪点
  │
  ├── [4] Ray Marching Integration
  │     ├── 沿视线方向积分 Froxel 数据
  │     └── 输出: 2D Integrated Scattering + Transmittance
  │
  └── [5] Apply Pass
        └── 将体积雾叠加到 SceneColor
```

#### 关键参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `VolumetricFogScatteringDistribution` | 散射分布（各向同性/各向异性） | 0.2 |
| `VolumetricFogAlbedo` | 散射颜色 | 白色 |
| `VolumetricFogExtinctionScale` | 消光系数缩放 | 1.0 |
| `VolumetricFogDistance` | 体积雾最大距离 | 6000 |
| `r.VolumetricFog.GridPixelSize` | Froxel 像素大小 | 8 |
| `r.VolumetricFog.GridSizeZ` | Z 方向 Froxel 数量 | 64 |

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
| HZB 加速   | 使用层级深度缓冲加速 SSR/SSAO 查询     | 高     |
| Tile-based | 基于 Tile 的后期处理，减少带宽         | 中     |

### 各模块改造方向

| 模块 | 改造方向 | 预期收益 |
|------|---------|----------|
| SSAO | 升级为 GTAO / HBAO+，使用 HZB 加速 | 质量提升，性能持平 |
| SSGI | 与 Lumen 结合，屏幕外用 Lumen 补充 | 解决屏幕边缘漏光 |
| SSR | HZB 步进 + 时间性重建 + 粗糙度分级 | 性能提升 40%+ |
| Bloom | 升级为 FFT Convolution Bloom | 更真实的镜头光晕 |
| ToneMapping | 支持 HDR10/Dolby Vision 输出 | HDR 显示器支持 |
| AutoExposure | 局部曝光（Local Tonemapping） | 高对比度场景改善 |
| VolumetricFog | 降低 Froxel 分辨率 + 时间性积累 | 移动端可用 |

### 自定义 Pass 接入方式

```cpp
// 方式1: PostOpaqueRender 委托
GetRendererModule().RegisterPostOpaqueRenderDelegate(
    FPostOpaqueRenderDelegate::CreateRaw(this, &FMyRenderer::RenderPostOpaque)
);

// 方式2: 继承 FSceneViewExtension
class FMyViewExtension : public FSceneViewExtensionBase
{
    virtual void PrePostProcessPass_RenderThread(
        FRDGBuilder& GraphBuilder,
        const FSceneView& View,
        const FPostProcessingInputs& Inputs) override;
};

// 方式3: 材质 PostProcess Domain
// 在材质编辑器中设置 Material Domain = Post Process
```

---

## 手机平台适配方案

### 移动端渲染器差异

```
FMobileSceneRenderer vs FDeferredShadingSceneRenderer

移动端特点:
  ├── Forward Rendering (前向渲染，非延迟)
  ├── Tile-based GPU 架构 (TBDR)
  ├── 带宽敏感（读写 Framebuffer 代价高）
  ├── 无 Compute Shader（部分低端设备）
  └── 内存限制（GBuffer 无法存储）
```

### 各效果移动端方案

| 效果 | PC 方案 | 移动端方案 | 说明 |
|------|---------|-----------|------|
| SSAO | 全质量 SSAO | Mobile SSAO（4采样）或烘焙 AO | 减少采样数，降低分辨率 |
| SSGI | 屏幕空间 GI | 禁用，改用 IBL + 烘焙 | 性能开销过大 |
| SSR | 全质量 SSR | PlanarReflection 或禁用 | 仅平面反射可用 |
| HDR | FP16 HDR | FP16 或 R11G11B10 | 根据设备选择 |
| AutoExposure | 直方图 | 基础 AutoExposure 或手动 | 避免 Compute Shader |
| ToneMapping | ACES | Neutral Tonemapper | 降低 ALU 消耗 |
| Bloom | 6级 Bloom | 2~3级 Bloom，降低分辨率 | 减少迭代次数 |
| HeightFog | 指数高度雾 | 简化高度雾（单层） | 禁用体积雾 |
| VolumetricFog | 3D Froxel | 禁用或极低质量 | 带宽/内存开销过大 |
| DOF | Bokeh DOF | Gaussian DOF 或禁用 | 简化模糊算法 |
| MotionBlur | 全质量 | 禁用或简化 | 移动端通常禁用 |
| TAA | TSR/TAA | FXAA 或 TAA 简化版 | 减少历史帧带宽 |

### 移动端性能分级方案

```
高端机 (Snapdragon 8 Gen2+ / Apple A16+):
  ├── Mobile SSAO (低采样)
  ├── PlanarReflection (替代 SSR)
  ├── 3级 Bloom
  ├── ACES Tonemapping
  ├── 单层 HeightFog
  └── TAA (简化)

中端机 (Snapdragon 7 Gen1 / Apple A14):
  ├── 烘焙 AO 贴图 (无实时 SSAO)
  ├── 禁用 SSR
  ├── 2级 Bloom (半分辨率)
  ├── Neutral Tonemapping
  └── FXAA

低端机 (Snapdragon 6xx / 入门级):
  ├── 禁用所有屏幕空间效果
  ├── 1级 Bloom 或禁用
  ├── Linear Tonemapping
  └── 无抗锯齿 或 FXAA
```

### 移动端关键 CVar 配置

```ini
; 移动端后期处理优化配置 (DefaultDeviceProfiles.ini)

[Mobile_High DeviceProfile]
r.MobileHDR=1
r.Mobile.TonemapperFilm=1
r.MobileAmbientOcclusion=1
r.SSR.Quality=0
r.BloomQuality=2
r.DepthOfFieldQuality=1
r.MotionBlurQuality=0
r.VolumetricFog=0
r.Fog=1

[Mobile_Medium DeviceProfile]
r.MobileHDR=1
r.Mobile.TonemapperFilm=0
r.MobileAmbientOcclusion=0
r.SSR.Quality=0
r.BloomQuality=1
r.DepthOfFieldQuality=0
r.MotionBlurQuality=0
r.VolumetricFog=0

[Mobile_Low DeviceProfile]
r.MobileHDR=0
r.Mobile.TonemapperFilm=0
r.MobileAmbientOcclusion=0
r.SSR.Quality=0
r.BloomQuality=0
r.DepthOfFieldQuality=0
r.MotionBlurQuality=0
r.VolumetricFog=0
r.Fog=0
```

### Tile-based 架构优化要点

```
TBDR (Tile-Based Deferred Rendering) 优化:

1. 减少 Framebuffer 读写
   ├── 避免在 Tile 内多次读写同一 RT
   ├── 使用 Subpass (Vulkan) / Pixel Local Storage (OpenGL ES)
   └── 合并 Pass 减少 Resolve 操作

2. 带宽优化
   ├── 使用 R11G11B10 替代 FP16 (节省 50% 带宽)
   ├── 深度/模板使用 Memoryless (不写回内存)
   └── 避免不必要的 MRT

3. 后期处理 Tile 化
   ├── 将多个后期 Pass 合并为单个 Full-screen Pass
   └── 利用 Subpass Input 在 Tile 内传递数据
```

### 移动端自定义后期处理

```cpp
// 移动端自定义后期 Pass 示例
void FMobileSceneRenderer::RenderPostProcessing(
    FRHICommandListImmediate& RHICmdList)
{
    // 使用轻量级 Shader
    TShaderMapRef<FMobilePostProcessVS> VertexShader(ShaderMap);
    TShaderMapRef<FMobilePostProcessPS> PixelShader(ShaderMap);
    
    // 避免额外 RT 切换，直接写入 BackBuffer
    FGraphicsPipelineStateInitializer GraphicsPSOInit;
    // ... 设置 PSO
    
    // 单 Pass 完成所有后期效果
    DrawRectangle(RHICmdList, ...);
}
```

---

## 参考资料

- [UE5 官方文档 - Post Process Effects](https://docs.unrealengine.com/5.0/en-US/post-process-effects-in-unreal-engine/)
- [UE5 源码 - Engine/Source/Runtime/Renderer/Private/PostProcess/](https://github.com/EpicGames/UnrealEngine)
- [ACES Color Encoding System](https://www.oscars.org/science-technology/sci-tech-projects/aces)
- [Volumetric Fog in UE4](https://www.unrealengine.com/en-US/blog/volumetric-fog)
