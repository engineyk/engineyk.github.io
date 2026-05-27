---
layout:     post
title:      MobileLumen
date:       2026-05-05
author:     engineyk
header-img: img/post-bg-algorithm.jpg
catalog: true
tags:
    - 渲染
---

# 移动端 Lumen（Mobile Lumen）

> 官方文档：[移动端 Lumen](https://dev.epicgames.com/documentation/zh-cn/unreal-engine/using-lumen-global-illumination-on-mobile-in-unreal-engine) — UE **5.4+ 实验性**（UE5.6 仍为 Experimental），官方明确不推荐用于正式上线项目，但可做技术储备与预研。

## A.1 兼容性矩阵

**硬性前提**：手机端必须走 **Desktop Renderer + Vulkan SM5** 路径，**不是**默认的 Mobile Forward / Mobile Deferred。

| 维度         | 条件                                                                                                          |
| ------------ | ------------------------------------------------------------------------------------------------------------- |
| 平台         | Android（Vulkan SM5）。**iOS/iPadOS/tvOS 暂不支持**                                                           |
| 渲染路径     | `Desktop Renderer on Mobile`（手机桌面渲染器）                                                                |
| ShaderModel  | SM5（Vulkan）                                                                                                 |
| GPU 家族     | Adreno 7xx · Mali G7xx · Samsung Xclipse 9xx（典型代表：骁龙 8Gen1/2/3、天玑 9000+、Exynos 2200+）            |
| 设备描述文件 | `Android_Vulkan_SM5` / `Android_Adreno_Vulkan_SM5` / `Android_Mali_Vulkan_SM5` / `Android_Xclipse_Vulkan_SM5` |
| 硬件光追     | 可选；要求 Vulkan RT 扩展 + `r.RayTracing.RequireSM6=0`                                                       |

## A.2 启用步骤

**Step 1：项目开启 Desktop Renderer for Mobile**

Project Settings → Platforms → Android：

```ini
; DefaultEngine.ini
[/Script/AndroidRuntimeSettings.AndroidRuntimeSettings]
bSupportsVulkan=True
bSupportsVulkanSM5=True
bBuildForES31=False        ; 可选，裁掉 ES31 以减包
```

**Step 2：项目开启 Lumen**（与 PC 一致）

Project Settings → Engine → Rendering：
- Dynamic Global Illumination Method = **Lumen**
- Reflection Method = **Lumen**
- Generate Mesh Distance Fields = ✅

**Step 3：设备匹配**（让目标机型走 SM5 描述）

`Engine/Config/BaseDeviceProfiles.ini` 示例（Adreno 7xx 全面启用）：

```ini
+MatchProfile=(Profile="Android_Adreno_Vulkan_SM5",Match=(
    (SourceType=SRC_GpuFamily, CompareType=CMP_Regex, MatchString="Adreno \\(TM\\) 7[0-9][0-9]"),
    (SourceType=SRC_AndroidVersion, CompareType=CMP_Regex, MatchString="([0-9]+).*"),
    (SourceType=SRC_PreviousRegexMatch, CompareType=CMP_GreaterEqual, MatchString="10"),
    (SourceType=SRC_SM5Available, CompareType=CMP_Equal, MatchString="true")
))
```

**Step 4：关键 CVars**（`Android_Vulkan_SM5 DeviceProfile` 默认已带）

```ini
+CVars=r.Android.DisableVulkanSupport=0
+CVars=r.Android.DisableVulkanSM5Support=0
+CVars=r.DistanceFields=1                       ; Mesh SDF 必需
+CVars=r.RayTracing.RequireSM6=0                ; 允许 HWRT（可选）
+CVars=r.Vulkan.RayTracing.AllowCompaction=0
+CVars=r.Vulkan.RayTracing.TLASPreferFastTraceTLAS=0
```

## A.3 分级策略（与 PC/主机相同的 `sg.*` 体系）

Lumen 完全复用引擎 **Scalability Groups**。移动端推荐在 `UDeviceProfile` 或 `GameUserSettings` 中按机型动态切换：

| 级别          | `sg.GlobalIlluminationQuality` | `sg.ReflectionQuality` | Lumen 状态                                                | 目标机型                        |
| ------------- | ------------------------------ | ---------------------- | --------------------------------------------------------- | ------------------------------- |
| **Cinematic** | 4                              | 4                      | Lumen Epic + HWRT                                         | Matrix Awakens 级别 Demo        |
| **Epic**      | 3                              | 3                      | Lumen Epic（30 FPS 预算）                                 | 旗舰 PC / 主机 30FPS            |
| **High**      | 2                              | 2                      | Lumen High（**全局 SDF + 禁 Detail Trace**，60 FPS 预算） | **手机推荐起点**：8Gen2 / 9000+ |
| **Medium**    | 1                              | 1                      | **Lumen 关闭** → DFAO + SSAO + SSGI                       | 中端机                          |
| **Low**       | 0                              | 0                      | **Lumen 关闭** → 仅无阴影天光 + SkylightIntensity=0.7     | 低端机                          |

`BaseScalability.ini` 关键派生规则：
- **Medium** 用 `Distance Field Ambient Occlusion` 取代 Lumen GI（大尺度 AO）
- **Low** 仅保留无阴影 Skylight
- 这是由 Epic 官方默认差值，因此不同机型看起来会"质感一致、精度降级"

### 手机上的 Epic/High 级别补丁 CVars（建议下调）

```ini
; 探针密度减半（16×16 每探针 → 更疏）
+CVars=r.Lumen.ScreenProbeGather.DownsampleFactor=16
+CVars=r.Lumen.ScreenProbeGather.TracingOctahedronResolution=4

; 反射降分辨率 + 降粗糙度阈值
+CVars=r.Lumen.Reflections.DownsampleFactor=2
+CVars=r.Lumen.Reflections.MaxRoughnessToTrace=0.2

; Radiosity 降频（每 2 帧更新一次）
+CVars=r.Lumen.Radiosity.CardUpdateFrequencyScale=0.5

; 强制全局 SDF（不做 Detail MeshSDF Trace，省开销）
+CVars=r.Lumen.TraceMeshSDFs.Allow=0
+CVars=r.Lumen.HardwareRayTracing=0          ; 移动端 HWRT 极昂贵，默认关

; Surface Cache 图集收缩
+CVars=r.LumenScene.SurfaceCache.AtlasSize=2048   ; 默认 4096
+CVars=r.LumenScene.SurfaceCache.CardMaxResolution=256   ; 默认 512

; 追踪距离与视距收缩
+CVars=r.Lumen.MaxTraceDistance=10000        ; 默认 50000，手机收到 100m 内
```

## A.4 大世界（Open World）方案

UE5 Lumen 对大世界的支持本身就是"**相机为中心的滚动场景**"思路，以下是三层范围叠加的**标准做法**（Matrix Awakens 同款）：

```
         相机
          │
   ┌──────┼─────────────────────────────────────────┐
   │      │                                         │
   ▼ 0-200m（近）    ▼ 200-800m（中）             ▼ 800-1000m+（远）
┌──────────────┐  ┌──────────────────┐       ┌────────────────────┐
│ Lumen Scene  │  │ LumenSceneView   │       │ Far Field          │
│ 全量 Card +  │  │ Distance 扩到    │       │ r.LumenScene       │
│ Mesh SDF +   │  │ 800m，仅屏幕追   │       │ .FarField=1        │
│ Radiosity    │  │ 踪补全           │       │ + HLOD1 构建       │
└──────────────┘  └──────────────────┘       └────────────────────┘
        ↑                  ↑                         ↑
    后期处理           后期处理                `r.LumenScene
    默认              `Lumen Scene              .FarField
                      View Distance`            .MaxTraceDistance`
                      （最大 800m）             （默认 1e6 = 10km）
```

### A.4.1 中距离：LumenSceneViewDistance

- 后期处理体积字段 **Lumen Scene View Distance**（PPV → Global Illumination → Lumen）
- 默认 200m，**最大可推到 800m**
- 超过此距离只能靠 **Screen Trace**（看不到屏幕外的就没 GI）
- 代价：Card 图集占用 + 更新成本线性上升

### A.4.2 远距离：Far Field（**大世界关键！**）

启用命令：

```ini
[SystemSettings]
r.LumenScene.FarField=1
r.LumenScene.FarField.MaxTraceDistance=1000000     ; 10km（默认）
r.LumenScene.FarField.FarFieldDitherScale=200      ; 近远场过渡抖动带
r.LumenScene.SurfaceCache.FarField.CardDistance=40000    ; Card 剔除距离
r.LumenScene.SurfaceCache.FarField.CardTexelDensity=0.001 ; 远场纹素密度
```

**依赖 World Partition 的 HLOD1 构建**：
- Far Field 使用 World Partition 生成的 **HLOD Level 1** 网格来做光追几何
- 必须在每个 WP Grid Cell 上勾选 **Ray Tracing Far Field** 且构建 HLOD
- 否则远距离会穿光 / 漏光

**近-远场衔接**：
```
0 ──────── MaxTraceDistance(=200m) ─── FarFieldDither ──── FarField.MaxTraceDistance(=10km)
        ↑ Lumen Scene 范围              ↑ 抖动过渡             ↑ HLOD1 远场
```

为避免近场物体被 `r.RayTracing.Culling.Radius` 剔除留下空洞，建议：
```ini
r.RayTracing.Culling=3
r.RayTracing.Culling.Radius=20000     ; 与 Max Trace Distance 对齐
r.RayTracing.Culling.Angle=0.5
```

### A.4.3 大世界 Actor 级标注

每个 StaticMeshActor / Component 上：
- **Affect Distance Field Lighting** ✅（近场必要）
- **Ray Tracing Far Field** ✅（远场地标，如山体、远景建筑）
- **Visible In Ray Tracing** ❌（天空盒、装饰重叠物）

### A.4.4 快速相机移动（大世界跑图常态）

```ini
r.LumenScene.FastCameraMode=1          ; 质量降级换速度
r.LumenScene.SurfaceCache.CardCapturesPerFrame=600    ; 默认 300，跑图加倍
r.LumenScene.SurfaceCache.CardCaptureFactor=32        ; 默认 64，更新更密
```

否则会出现**相机停下后 GI 才慢慢追上来**的"走光"现象。

## A.5 手机端 Lumen 的坑（踩过的位置）

### ⚠️ 性能坑

1. **Desktop Renderer 本身就重**：相比 Mobile Forward 基线成本 +40%~+80%，Lumen 再叠加 3-8ms，中端机根本带不动。
2. **Surface Cache 图集显存大**：默认 4K×4K RGBA16F ≈ 128MB，加上 Depth/Opacity 等附加 Atlas，单 Lumen 显存消耗可超 **300MB**，骁龙 8Gen2 (LPDDR5X 8G) 都紧张。
3. **Mesh SDF 流送 IO 高**：大世界跑图时 Mesh SDF 每帧流进流出，易触发 GPU Stall，建议强制 `r.Lumen.TraceMeshSDFs.Allow=0` 切到 Global SDF。
4. **HWRT 几乎不可用**：Vulkan RT 驱动在 Android 上稳定性差，BVH 重建 + Surface Cache 反射一起开销爆炸，实测差距 10ms+。
5. **Nanite + Lumen 才是黄金组合**：非 Nanite 的高面数网格在 Card 捕获阶段会产生数千 DrawCall，手机 OOMPU / 直接 TDR。
6. **帧率/发热**：即使 8Gen2 开 Lumen High 也很难稳定 60FPS，实际项目要按 **30FPS 锁帧 + 动态分辨率**。

### ⚠️ 画质坑

1. **200m 硬边界**：走路型玩法勉强够，载具/飞行玩法远景会"光照戛然而止"，必须配 Far Field。
2. **Card 漏光**：薄墙（< 10cm）、分体网格拼接缝、薄植被都会漏光，手机下采样率低，漏光被放大。
3. **低采样噪点**：ScreenProbe 下采 16×16 → 每屏探针数 ≈ 8K，空间+时域降噪后仍有**萤火虫 (firefly)**，植被、毛发、动态角色特别明显。
4. **动态阴影与 Lumen 冲突**：开 Lumen 后 VSM 默认同步开启，VSM 在移动端本身就很贵（额外 2-4ms），要么改走传统 CSM（但 Lumen Direct Light 会对不上）。
5. **不支持 Landscape**：地形物体不进 Lumen 场景，只能靠 Heightfield Trace 粗略解决，有明显间接光不连续。
6. **骨骼网格无 GI**：角色只能走 Screen Trace 或 HWRT，关闭 HWRT 后角色"漂浮"感明显（没有接触光照）。
7. **后处理叠加问题**：TAA → TSR 的质量损失在 1080p 以下被放大，手机端开 Lumen 推荐搭配 **Mobile FSR**。
8. **Lightmap 兼容性**：项目一旦开 Lumen 就**强制禁用静态光照**，已烘焙场景会丢 Lightmap 数据，需要在关卡 World Settings 勾选 `Force No Precomputed Lighting` 并重新保存。

### ⚠️ 工具链坑

1. **设备描述文件匹配出错**：`MatchProfile` 正则漏写导致机型跑不到 SM5 路径，用 `ShowLog LogDeviceProfileManager` 确认。
2. **Shader 编译爆炸**：开 Lumen 后 SM5 Shader 变种数暴涨，**Cook 时间翻倍**，PSO Cache 必须提前收集（否则首次运行卡顿 2-5 秒）。
3. **包体增加**：Mesh SDF 数据 + Card 构建数据 + PSO 缓存，包体通常 **+80MB~+150MB**。
4. **Android Vulkan 驱动差异**：不同厂商的 Vulkan 驱动对 UAV、BDA、RT 扩展行为不一致，必须做真机 Farm 测试矩阵。

## A.6 需要改造的地方（上线前清单）

### 引擎层改造（源码级）

| 改造点                            | 原因                                     | 改造方向                                                   |
| --------------------------------- | ---------------------------------------- | ---------------------------------------------------------- |
| **1. 关闭 Translucency Lumen**    | 半透明 Volume + Lumen Scene 移动端跑不动 | 强制 `r.Lumen.TranslucencyVolume.Enable=0`                 |
| **2. 去 HWRT 代码路径编译**       | 节省 Shader 变种与包体                   | 为 Android 平台 `#if !PLATFORM_ANDROID` 剪掉 HWRT 相关 USF |
| **3. Surface Cache 图集动态伸缩** | 内存紧张时不能静态 4K                    | 按机型档位动态 `r.LumenScene.SurfaceCache.AtlasSize`       |
| **4. Radiosity 下采**             | 辐射度 Probe 在手机太贵                  | `r.LumenScene.Radiosity.ProbeSpacing=8`（默认 4）          |
| **5. ScreenProbe 固定低质量**     | 动态质量不稳，帧率抖                     | 冻结 DownsampleFactor=16，禁用 Adaptive                    |
| **6. 去掉 ReSTIR Gather**         | 移动端开销爆炸                           | 强制 `r.Lumen.ReSTIRGather=0`                              |
| **7. Card 捕获合批**              | 非 Nanite 网格 DrawCall 炸               | 强制合并或禁用高面数非 Nanite 网格进 Lumen                 |
| **8. 禁用 Far Field HWRT**        | 移动端只能软光追                         | `r.LumenScene.FarField.OcclusionOnly=1`（5.6 新增）        |

### 美术 / 资产层改造

| 改造点              | 规范                                                                             |
| ------------------- | -------------------------------------------------------------------------------- |
| **墙壁厚度**        | ≥ 10cm，避免 Card 漏光                                                           |
| **Mesh SDF 分辨率** | 重要物件 `Distance Field Resolution Scale=1.5~2.0`，其余保持默认                 |
| **Nanite 覆盖率**   | **所有 > 10K 三角形的 StaticMesh 必须开 Nanite**，否则 Lumen 卡死                |
| **HLOD1 全覆盖**    | WP Grid 必须 100% 有 HLOD1 Proxy，用于 Far Field                                 |
| **Actor 标注**      | 远景地标勾 `Ray Tracing Far Field`；天空盒/重叠大体积关 `Visible In Ray Tracing` |
| **植被**            | 不走 Lumen（`Affect Distance Field Lighting=0`），用 Skylight + ShortAO          |
| **自发光小物件**    | 加 `r.LumenScene.Radiosity.MaxRayIntensity` 限制，否则 firefly                   |

### Gameplay / Runtime 层改造

| 改造点               | 做法                                                                |
| -------------------- | ------------------------------------------------------------------- |
| **机型分级**         | 启动读 GPU 型号 + Vulkan Caps → 选择 Scalability 级别               |
| **低端机兜底**       | Medium 及以下关 Lumen，走 DFAO + SSGI + Skylight                    |
| **动态降级**         | 监测 `GPU Frame Time`，若 > 25ms 连续 60 帧则自动降一档             |
| **PSO 预热**         | 启动时跑完 Lumen 主要 PSO，避免 Shader Miss 卡顿                    |
| **相机快速移动检测** | 进入载具/飞行时动态 `r.LumenScene.FastCameraMode=1`                 |
| **内存回收**         | 大世界流送时周期性 `r.LumenScene.SurfaceCache.ForceEvictHiResPages` |

## A.7 推荐配置分档（工程参考）

```ini
; ====== Lumen_Mobile_High (骁龙 8Gen2 / 天玑 9200+ / Xclipse 940) ======
sg.GlobalIlluminationQuality=2
sg.ReflectionQuality=2
r.Lumen.ScreenProbeGather.DownsampleFactor=16
r.Lumen.ScreenProbeGather.TracingOctahedronResolution=4
r.Lumen.Reflections.DownsampleFactor=2
r.Lumen.Reflections.MaxRoughnessToTrace=0.2
r.Lumen.TraceMeshSDFs.Allow=0
r.Lumen.HardwareRayTracing=0
r.LumenScene.SurfaceCache.AtlasSize=2048
r.LumenScene.SurfaceCache.CardMaxResolution=256
r.LumenScene.Radiosity.ProbeSpacing=8
r.Lumen.MaxTraceDistance=10000
r.LumenScene.FarField=1                        ; 大世界必开
r.LumenScene.FarField.OcclusionOnly=1          ; 5.6+ 仅做遮挡，省 ~30%

; ====== Lumen_Mobile_Medium → 关 Lumen ======
sg.GlobalIlluminationQuality=1
sg.ReflectionQuality=1
; 自动 fallback: DFAO + SSGI + SSR + 无阴影 Skylight
```

## A.8 小结

手机 Lumen 的**当前定位**：

1. **技术储备**：实验性功能，**不推荐直接上线**，但值得预研，为下一代硬件（骁龙 8Gen4/5）铺路。
2. **适用场景**：封闭/半封闭关卡、中小地图、载具少/飞行少的玩法；**不适合大开放世界 + 全动态光照**的移动端项目。
3. **必选组合**：Desktop Renderer + Vulkan SM5 + Nanite + World Partition + HLOD1 + Mesh SDF + **Software RT Only**。
4. **大世界思路**：`0-200m Lumen Scene` + `200-800m Scene View Distance` + `800m-10km Far Field (HLOD1)` 三层叠加，但手机实测 **Far Field 依然偏贵**，多数项目只开前两层。
5. **画质取舍**：牺牲远景 GI 精度、牺牲高粗糙度反射，换帧率与发热；低端机直接走 DFAO + SSGI 兜底。

一句话总结：**手机 Lumen = "能跑但不一定能发"**，商业项目建议维持 Mobile Deferred + Lightmap + SSGI 方案，Lumen 留给旗舰机的 HDR 画质档，或等 UE5.7+ Epic 官方将其移出 Experimental。
