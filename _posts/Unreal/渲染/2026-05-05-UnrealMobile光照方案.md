---
layout:     post
title:      UnrealMobile光照方案
date:       2026-05-05
author:     engineyk
header-img: img/post-bg-algorithm.jpg
catalog: true
tags:
    - 渲染
---

> **定位**：以 UE5.6 为基线，汇总一套**可落地**的移动端大世界光照方案。核心关注 5 个问题：
>
> 1. **GI 方案**：用什么做全局光照？
> 2. **近处阴影**：近景角色/建筑怎么投？
> 3. **远处阴影**：远山、远景大物件怎么投？
> 4. **分档适配**：旗舰/中端/低端/入门怎么切？
> 5. **带宽预算**：每一档的 GPU 带宽大概是多少？
> 6. **管线选型**：Mobile Forward / Mobile Deferred / Desktop Renderer 怎么选？

---

## 1. 总览：一张图看懂

```
┌────────────────────────────────────────────────────────────────────────────┐
│                Mobile Open World Lighting — UE5.6 推荐方案                  │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│   管线:  Mobile Deferred (默认) │ Mobile Forward (低端兜底) │ Desktop(旗舰)  │
│                                                                            │
│   GI:    Lightmap(静态)+ILC/VLM(动态) │ SSGI(中高端加餐) │ Lumen(Desktop旗舰)│
│                                                                            │
│   阴影:                                                                    │
│   ┌──── 近 (0-50m) ────┬──── 中 (50-150m) ────┬──── 远 (150m-1km+) ─────┐  │
│   │  CSM 1-2 级联      │  CSM 最后 1 级联      │  Distance Field         │  │
│   │  Stationary 主光   │  + Cascade Fade      │  Shadow (DFShadow)      │  │
│   │  1024²~2048² RT    │                      │  + Capsule/ModShadow    │  │
│   │  + Per-Obj Inset   │                      │  + Precomputed Shadow   │  │
│   │  (角色)            │                      │    Mask (烘焙静态)       │  │
│   └────────────────────┴──────────────────────┴─────────────────────────┘  │
│                                                                            │
│   分档:  Cinematic > High > Medium > Low > Minimal                         │
│   带宽:  25GB/s    18GB/s  12GB/s  8GB/s  5GB/s (1080p30 峰值)              │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

**一句话总结**：

> **大世界主流方案 = Mobile Deferred + 烘焙 Lightmap + CSM 近场 + DFShadow 远场 + 分档切管线**。
> 旗舰机可选 Desktop Renderer + Lumen，但仍建议 30FPS 锁帧。

---

## 2. 管线选型 (Mobile Rendering Paths)

UE5.6 在移动端提供三条独立管线，通过 `r.Mobile.ShadingPath` 或 Project Settings 切换：

| 管线                           | CVar                                                           | 典型带宽 (1080p30) | 适用场景                  | UE5.6 状态                    |
| ------------------------------ | -------------------------------------------------------------- | ------------------ | ------------------------- | ----------------------------- |
| **Mobile Forward**             | `r.Mobile.ShadingPath=0`                                       | **5-8 GB/s**       | 低端机、预计算光照、VR/AR | 正式                          |
| **Mobile Deferred**            | `r.Mobile.ShadingPath=1`                                       | **12-18 GB/s**     | 中高端机、大世界主选      | 正式（推荐）                  |
| **Desktop Renderer on Mobile** | `r.Android.DisableVulkanSM5Support=0` + Metal Desktop Renderer | **25-40 GB/s**     | 旗舰机 Demo、技术储备     | 实验性 (Android) / Beta (iOS) |

### 2.1 为什么大世界首选 Mobile Deferred？

```
Mobile Forward:            Mobile Deferred:
┌──────────────┐           ┌──────────────┐
│ BasePass     │           │ GBuffer Pass │
│ + 光照       │           │ (纯几何)     │
│ (Shader 炸)  │           │              │
└──────────────┘           ├──────────────┤
                           │ Light Pass   │
                           │ (Tile 内)    │
147 指令 / 2 sampler        └──────────────┘
                            34 指令 / 0 sampler
                            → CPU/GPU/RHI 三线减负
```

UE5.6 官方数据：同样的材质，**Forward 需要 147 指令、2 个采样器；Deferred 只需要 34 指令、0 个采样器**（因为光照拆到 Light Pass）。

**Mobile Deferred 独占光照功能**（大世界必备）：

- ✅ **光源函数 (Light Function)**：阳光透过树叶的阴影斑纹
- ✅ **光照贴花 (Decals)**：动态弹孔、水渍、血迹
- ✅ **IES 光源配置文件**：路灯、车灯物理光形
- ✅ **局部光源高效渲染**：夜景大量小灯泡（Clustered Lighting）
- ✅ **自发光贴花**：霓虹招牌、发光路牌

### 2.2 Tile 内存用法 (TBR/TBDR 架构关键)

Mobile Deferred 之所以在手机上能跑得动，核心是**GBuffer 永远不落系统内存**，全部留在 **Tile SRAM** 里：

| 平台                    | 访问方式                                            | Tile 内存特性     |
| ----------------------- | --------------------------------------------------- | ----------------- |
| **iOS (Apple GPU)**     | `framebuffer_fetch`                                 | 原生支持，零开销  |
| **Android Vulkan**      | Vulkan **Subpass** + `VK_FORMAT_*_LAZILY_ALLOCATED` | 最优，不分配显存  |
| **Adreno (GLES)**       | `GL_EXT_shader_framebuffer_fetch`                   | 骁龙系列原生支持  |
| **Mali/PowerVR (GLES)** | `GL_EXT_shader_pixel_local_storage` (PLS)           | 需扩展            |
| **立即模式 GPU**        | ❌ 不支持，GBuffer 退化到显存                        | 不推荐开 Deferred |

### 2.3 Mobile Deferred 的硬件约束（重要！）

运行 **Android Vulkan 的 Mali 设备**（以及为了统一行为，所有 Android Vulkan 设备默认都遵守）：

```bash
GBuffer         : ≤ 16 bytes/pixel (128 bit)
Input Att       : ≤ 4 个附件
Light Pass 读取 : ≤ 3 color attachment + 1 depth attachment
```

这意味着 UE 默认 GBuffer 布局就是 **4×RT32 紧凑打包**，法线用 **Octahedral Encoding**（UE5.6 新改动：`Mobile deferred uses octahedral encoding for normals which can't blend`），这也是**贴花不能混合法线**的原因——只能整覆盖。

如要放开限制（全 RGBA16F GBuffer）：

```ini
[/Script/Engine.RendererSettings]
MobileUsesExtendedGBuffer=True   ; 代价：带宽 +40%，Mali 低端机可能跑不起来
```

### 2.4 管线分档落地

```ini
; DeviceProfiles.ini - 按机型分派
[Android_Adreno_Vulkan_SM5 DeviceProfile]     ; 旗舰（骁龙8Gen2+）
+CVars=r.Mobile.ShadingPath=1                 ; Deferred
+CVars=r.Mobile.AllowDeferredShadingOpenGL=0  ; 强制 Vulkan
+CVars=r.Android.DisableVulkanSM5Support=0    ; 开 SM5
; 允许未来切 Desktop Renderer

[Android_Vulkan DeviceProfile]                 ; 中端（骁龙7Gen+ / 天玑8000+）
+CVars=r.Mobile.ShadingPath=1                 ; Deferred
+CVars=MobileUsesExtendedGBuffer=False        ; 紧凑 GBuffer

[Android_ES31 DeviceProfile]                   ; 低端（骁龙6系 / 天玑6000）
+CVars=r.Mobile.ShadingPath=0                 ; Forward 兜底
+CVars=r.Mobile.AllowDitheredLODTransition=0
```

## 2.5 双管线同时维护的注意事项（重要！）

当项目需要同时支持 **Mobile Deferred** 和 **Mobile Forward** 两套渲染管线时，必须注意以下7个关键点，避免运行时切换后出现画质问题或性能下降：

### 1. 材质系统（Shading Model）限制

- **预计算光照下着色模型限制**：当项目使用预计算光照时，Mobile Deferred **只支持两种着色模型**：
  - **DefaultLit**（默认光照）
  - **Unlit**（无光照）
  
  > 官方建议：**如果项目主要使用预计算光照，应首选 Mobile Forward**，而非 Mobile Deferred。

- **多着色模型性能开销**：在 Deferred 中同时支持多个复杂着色模型（如 ClearCoat、Subsurface、Hair 等）的开销**非常高**，应限制为仅必须使用的对象。

- **半透明材质的光照模式**：无论主管线如何，**半透明通道永远使用前向着色**。半透明材质（玻璃、水、粒子）的 `Lighting Mode` 必须设为 **Surface ForwardShading**，而非 Surface。

### 2. 着色器编译（Shader Compilation）策略

双管线必须为每个材质**生成两套着色器**（Forward 版 + Deferred 版），这会：

- **增加编译时间 2-3 倍**，特别是复杂材质。
- **增加 Shader 包体大小**，每套材质多占约 40-60% 包空间。
- **必须启用 `r.Mobile.ForceSeparateShaders=1`** 来确保两套独立编译。

**建议优化**：

1. 区分 **核心材质**（必须双份）和 **背景材质**（可只备 Forward 版）
2. 用 **ShaderPipelineCache** 预编译两套管线的热路径
3. 在低端机构建时，可配置剔除 Deferred 特有功能（如 Decal、LightFunction 相关 Shader）

### 3. 实时切换机制（Runtime Switching）

`r.Mobile.ShadingPath` **不能在运行时动态切换**，因为：

- 切换需要**重新构建 GBuffer 布局**（4×RT32 → RGBA16F 等）
- 需要**重新分配所有 RenderTargets**
- 已编译的 Shader 不兼容新管线

**正确做法**：

1. 启动时检测机型 → 确定使用 Forward 或 Deferred
2. 如果需要切换，必须**重启整个渲染器**（`FSceneRenderer` 重建）
3. 游戏内可提示用户“重启后画质提升”

### 4. 渲染功能兼容性（Rendering Features）

| 功能                          | Mobile Forward | Mobile Deferred | 注意事项                          |
| ----------------------------- | -------------- | --------------- | --------------------------------- |
| **MSAA**                      | ✅ 原生支持     | ❌ **不支持**    | Deferred 下自动退化为 TAA         |
| **光照贴花 (Decal)**          | ❌ 不支持       | ✅ 支持          | Forward 下 Decal 无光照效果       |
| **自发光贴花**                | ❌ 不支持       | ✅ 支持          | Forward 下自发光无效果            |
| **光源函数 (Light Function)** | ❌ 不支持       | ✅ 支持          | 如树叶斑纹、百叶窗阴影            |
| **IES 光源配置文件**          | ❌ 不支持       | ✅ 支持          | 车灯、路灯物理光形                |
| **法线贴花混合**              | ✅ 可混合       | ❌ **不能混合**  | Deferred 用八面体编码，只能整覆盖 |

**必须告知美术**：使用 Deferred 专用功能（如 IES 灯）时，要提供 Forward 回退方案（如静态光晕 Sprite）。

### 5. 后处理系统差异

| 后处理                 | Mobile Forward | Mobile Deferred | 双管线配置         |
| ---------------------- | -------------- | --------------- | ------------------ |
| **景深 (DoF)**         | 高斯 (Mobile)  | 散景 (Desktop)  | 两套独立配置       |
| **环境光遮蔽 (SSAO)**  | 可选           | 可选            | 质量参数需调整     |
| **屏幕空间反射 (SSR)** | 性能差         | 性能中          | 建议 Deferred 才开 |
| **泛光 (Bloom)**       | 标准           | 标准            | 参数基本一致       |
| **色调映射 (ToneMap)** | 标准           | 标准            | 需注意 HDR 范围    |

**关键坑点**：

- Forward 的 **Mobile DoF** 使用固定大小高斯核，而 Deferred 可用的 Desktop DoF 更耗性能
- **SSR 在 Forward 上基本不可用**（采样成本太高）
- **后处理体积需要两套设置**，通过蓝图检测 `r.Mobile.ShadingPath` 动态切换

### 6. 性能监控与分档

双管线需要**独立的性能预算表**：

| 指标              | Mobile Forward 预算 | Mobile Deferred 预算  |
| ----------------- | ------------------- | --------------------- |
| **DrawCall**      | ≤ 250 (1080p30)     | ≤ 350 (1080p30)       |
| **三角面/帧**     | ≤ 1.2M              | ≤ 2.0M                |
| **Shader 指令数** | ≤ 120/像素          | ≤ 60/像素 (BasePass)  |
| **纹理采样器**    | ≤ 8/材质            | ≤ 4/材质 (BasePass)   |
| **阴影渲染时间**  | ≤ 1.0ms             | ≤ 2.0ms (含 DFShadow) |
| **后处理总时间**  | ≤ 2.0ms             | ≤ 3.0ms               |

**监控工具**：

- 用 **Unreal Insights** 分别记录两管线的 `FMobileSceneRenderer` 各阶段耗时
- 在 `FMobileShadingRenderer.cpp` 中加自定义埋点，统计 Tile 命中率
- **必须验证**：同一场景两管线跑出来的 GPU 时间差应在预期内（Deferred 通常比 Forward 快 15-30%）

### 7. 测试验证清单

上线前必须通过以下 **双管线验证流程**：

```bash
# 1. 编译验证
./Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.exe ProjectName Android Development 
  -Target=ShaderCompileWorker -ShaderPlatform=SP_VULKAN_SM5 -Deferred
./Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.exe ProjectName Android Development 
  -Target=ShaderCompileWorker -ShaderPlatform=SP_OPENGL_ES3_1 -Forward

# 2. 渲染功能验证表
┌─────────────────────────────────┬───────┬───────┐
│ 功能测试项                       │Forward│Deferred│
├─────────────────────────────────┼───────┼───────┤
│ 1. 方向光源 CSM 阴影             │  ✅   │  ✅   │
│ 2. 点光源阴影 (1盏)              │  ✅   │  ✅   │
│ 3. 自发光材质                    │  ✅   │  ✅   │
│ 4. 光照贴花 (弹孔)               │  ❌   │  ✅   │
│ 5. IES 光源 (路灯)               │  ❌   │  ✅   │
│ 6. 半透明接收阴影                │  ✅   │  ✅*   │
│ 7. 反射捕获 (Reflection Capture) │  ✅   │  ✅   │
│ 8. 距离场阴影 (DFShadow)         │  ❌   │  ✅   │
│ 9. 屏幕空间反射 (SSR)            │  ⚠️   │  ✅   │
│10. 后处理景深 (DoF)              │  ✅   │  ✅   │
└─────────────────────────────────┴───────┴───────┘
  * Deferred 下需半透明设为 Surface ForwardShading

# 3. 画质对比（必须项）
- 取 5 个关键场景（室内、室外白天/黑夜、大远景、大量角色）
- 两管线并排截图，用脚本计算 PSNR ≥ 38dB（人眼基本无差异）
- 特别检查：法线贴花、半透明边缘、阴影过渡带、反射质量

# 4. 性能回归（必须项）
- 在高中低三档机器上，分别跑 Forward/Deferred 30分钟
- 记录：FPS 稳定性、内存增长、发热曲线、电池消耗
- 要求：Deferred 比 Forward 在同等画质下性能不差于 10%
```

**核心原则**：

1. **材质设计双管线思维**：关键材质必须考虑两套 Shader 的表现
2. **功能有主有次**：Deferred 是未来，Forward 是兜底，新功能优先按 Deferred 设计
3. **测试双线并跑**：CI 流水线必须同时编译、打包、测试两套配置
4. **监控指标分离**：性能分析工具要能区分当前运行的管线模式
5. **文档明确标注**：所有 Deferred-Only 的功能，在 Design Doc 中明确标出，并提供 Forward 回退方案

只有做到这7点，才能保证一个项目在 **Mobile Deferred（中高端） + Mobile Forward（低端）** 双管线下，既能享受 Deferred 的高质量光照，又能在老机上稳定运行。

---

## 3. GI 方案（大世界全局光照）

### 3.1 方案矩阵

```
┌──────────────────────────────────────────────────────────────────────────┐
│  移动端大世界 GI 方案对比 (UE5.6)                                          │
├───────────────┬──────────┬──────┬──────┬──────┬──────┬───────────────────┤
│  方案         │质量       │RT开销│内存  │烘焙时│动态  │适用档位            │
├───────────────┼─────────┼──────┼──────┼──────┼──────┼───────────────────┤
│  Lightmap     │★★★★★  │近零  │大    │长    │静态  │全档位主选          │
│  +Shadow Mask │          │      │      │      │      │                  │
├───────────────┼──────────┼──────┼──────┼──────┼──────┼──────────────────┤
│  ILC (间接    │★★★☆☆ │低    │中    │中    │半动态 │动态角色/载具       │
│  光照缓存)    │           │      │      │      │      │                  │
├───────────────┼──────────┼──────┼──────┼──────┼──────┼──────────────────┤
│  VLM (体积    │★★★★☆ │低    │中-大 │中    │半动态  │UE5 新推荐替代ILC  │
│  光照贴图)    │           │      │      │      │      │                  │
├───────────────┼──────────┼──────┼──────┼──────┼──────┼──────────────────┤
│  SH Probe     │★★★☆☆  │低    │小    │中    │静态   │中低端 + 动态物体   │
│  (PLM/Actor)  │          │      │      │      │      │                  │
├───────────────┼──────────┼──────┼──────┼──────┼──────┼──────────────────┤
│  Sky Light    │★★☆☆☆   │极低  │极小  │秒级  │动态   │全档位底座         │
│  + Ambient    │          │      │      │      │      │                  │
├───────────────┼──────────┼──────┼──────┼──────┼──────┼──────────────────┤
│  SSGI         │★★★☆☆   │中    │小    │0     │全动态│中高端加餐 (Defer) │
├───────────────┼──────────┼──────┼──────┼──────┼──────┼──────────────────┤
│  Lumen        │★★★★★   │很高  │大    │0     │全动态│Desktop Renderer旗 │
│  (Mobile实验) │           │+3-8ms│+300M │      │      │舰机 / 技术储备    │
└───────────────┴───────────┴──────┴──────┴──────┴──────┴──────────────────┘
```

### 3.2 推荐主方案：**Lightmap + VLM + Sky Light + (可选) SSGI**

这是目前 UE 在**大世界上线项目**的主流做法（《永劫无间手游》《黎明觉醒》《鸣潮》《原神》同类思路）。

#### (1) Lightmap — 静态场景的 90% GI

```
World Settings:
  Lightmass:
    Static Lighting Level Scale = 1.0     ; 大世界建议 0.5~1.0
    Num Indirect Lighting Bounces = 3-4
    Indirect Lighting Quality = 2         ; 质量×2 倍烘焙时间
  GI Replace Mode = Lightmass
```

**大世界分块烘焙 + World Partition 集成**（UE5 关键）：

```
World Partition + HLOD:
  ┌──────────────────────────────────────────┐
  │ Cell 0_0  │ Cell 1_0  │ Cell 2_0  │ ...  │
  │  4km×4km  │           │           │      │
  │ [Lightmap]│ [Lightmap]│ [Lightmap]│      │
  ├──────────────────────────────────────────┤
  │ Cell 0_1  │ Cell 1_1  │ Cell 2_1  │ ...  │
  └──────────────────────────────────────────┘
       ↓ HLOD1 Proxy Mesh (烘焙合并 Lightmap)
  远处只加载 HLOD + 低分辨率 Lightmap (256²)
```

**关键参数**：

- 单 Lightmap 纹理 ≤ **1024²**（移动端）
- **ASTC 6×6** 压缩，1024² ≈ 0.7MB
- Landscape 地形专用通道：`Static Lighting Resolution = 0.5~1`

#### (2) VLM (Volumetric Lightmap) — 动态物体的间接光

UE5.6 默认使用 **Volumetric Lightmap** 替代旧 ILC，是个**体素化的 SH 体积**：

```
Volumetric Lightmap:
  ┌─────────────────────────────┐
  │  稀疏体素网格（Adaptive）    │
  │  每个体素存 L1 SH (4×3 float)│
  │  光照表面附近加密            │
  │  远离表面稀疏                │
  └─────────────────────────────┘
     ↓
  运行时动态物体采样：
    float3 IndirectLight = SHEvalL1(SampleVLM(WorldPos), Normal);
```

**大世界关键配置**：

```ini
[/Script/Engine.VolumetricLightmap]
r.VolumetricLightmap.DetailCellSize=200     ; 单位 cm，默认 200=2m
r.VolumetricLightmap.BrickSize=4            ; Brick 分辨率（越大越占内存）
r.VolumetricLightmap.MaxBrickMemoryMb=30    ; 限制 VLM 总显存
```

#### (3) Sky Light — 天空盒间接光（全档位必开）

```
SkyLight (Stationary):
  Real Time Capture = False   ; 烘焙时捕获，省运行时
  Lower Hemisphere Is Solid = True   ; 地下全黑，省 GI 泄漏
  Recapture on Movement = False
```

**低端机 fallback**：关掉 VLM，只留 SkyLight + SH Probe 网格。

#### (4) SSGI — 中高端 Deferred 加餐（可选）

```ini
[SystemSettings]
r.SSGI.Enable=1           ; Deferred 下可用
r.SSGI.Quality=2          ; 1=低, 2=中, 3=高
r.SSGI.HalfRes=1          ; 半分辨率，省 50% 开销
```

**开销参考**（1080p，骁龙8Gen2）：

- SSGI Quality=2 半分 ≈ **+0.8ms GPU**
- SSGI Quality=3 全分 ≈ **+2.0ms GPU**（基本不建议移动端）

### 3.3 旗舰机选配：Lumen (Desktop Renderer)

仅在**旗舰机 + Desktop Renderer + Vulkan SM5** 路径下可用。完整方案与坑点见 [Mobile Lumen 独立笔记](/2026/05/05/MobileLumen.html)，核心要点：

- ✅ 0-200m 用 Lumen Scene（Card + Mesh SDF + Radiosity）
- ✅ 200-800m 用 `Lumen Scene View Distance` 推远
- ✅ 800m-10km 用 **Far Field + HLOD1** 补远景
- ❌ 手机 **HWRT** 基本不可用，强制 `r.Lumen.HardwareRayTracing=0`
- ❌ **Lumen 与静态 Lightmap 冲突**，一旦开 Lumen 必须关全场静态光
- 📊 预算：骁龙8Gen2 上 Lumen High 档约 **+5-8ms GPU**，30FPS 才稳

### 3.4 GI 分档配置

```ini
; ====== High (旗舰) ======
sg.GlobalIlluminationQuality=2
r.AllowStaticLighting=1
r.VolumetricLightmap.DetailCellSize=150     ; 更密
r.SSGI.Enable=1
r.SSGI.Quality=2
r.SSGI.HalfRes=1

; ====== Medium (中端) ======
sg.GlobalIlluminationQuality=1
r.AllowStaticLighting=1
r.VolumetricLightmap.DetailCellSize=250
r.SSGI.Enable=0                              ; 关 SSGI
; 只留 Lightmap + VLM + SkyLight

; ====== Low (低端) ======
sg.GlobalIlluminationQuality=0
r.AllowStaticLighting=1
r.VolumetricLightmap.DetailCellSize=400     ; 稀疏
; 关 VLM，改用静态 Actor SH Probe 方案
r.IndirectLightingCache.Quality=0

; ====== Minimal (入门机) ======
sg.GlobalIlluminationQuality=0
; 只留 Lightmap + SkyLight 常数色
```

---

## 4. 阴影方案（近场 / 远场）

### 4.1 阴影能力矩阵 (UE5.6 移动端)

| 阴影类型                             | Mobile Forward | Mobile Deferred             | Desktop Renderer | 距离           |
| ------------------------------------ | -------------- | --------------------------- | ---------------- | -------------- |
| **CSM (动态级联)**                   | ✅              | ✅                           | ✅                | 0-150m         |
| **Precomputed Shadow Mask (烘焙)**   | ✅              | ✅                           | ✅                | 全距离（静态） |
| **Per-Object Inset Shadow**          | ✅              | ✅                           | ✅                | 近距离角色     |
| **Modulated Shadow (调制)**          | ✅              | ✅                           | ✅                | 0-30m          |
| **Capsule Shadow**                   | ✅              | ✅                           | ✅                | 角色软阴影     |
| **Distance Field Shadow (DFShadow)** | ❌              | ✅ (需 `r.DistanceFields=1`) | ✅                | 150m-10km      |
| **Contact Shadow**                   | ❌              | ❌                           | ✅                | 屏幕空间细节   |
| **Virtual Shadow Maps (VSM)**        | ❌              | ❌                           | ✅ (旗舰)         | 全距离         |
| **Point Light Shadow**               | ✅              | ✅                           | ✅                | 局部           |
| **RT Shadow**                        | ❌              | ❌                           | ❌                | —              |

### 4.2 近处阴影（0-150m）：**CSM + Per-Object Inset**

#### (1) Directional Light CSM 设置

```bash
DirectionalLight (Stationary 推荐):
  Dynamic Shadow Distance (Stationary/Movable) = 15000   ; 150m
  Num Dynamic Shadow Cascades  = 2                       ; 移动端建议 2
  Cascade Distribution Exponent = 3.0                    ; 近处精细
  Cascade Transition Fraction   = 0.1                    ; 级联过渡带
  Shadow Distance Fade Out Frac = 0.15                   ; 最远处淡出
  Shadow Depth Bias             = 0.5
  Shadow Slope Bias             = 0.5
  Shadow Normal Bias            = 0.05
  Shadow Map Resolution         = 1024                   ; 中端
```

**CSM 分档建议**：

| 档位        | 级联数 | Shadow Map 分辨率 | Dynamic Shadow Dist | PCF Tap          | GPU 开销  |
| ----------- | ------ | ----------------- | ------------------- | ---------------- | --------- |
| High (旗舰) | 3      | 2048²             | 200m                | 4-tap            | 1.2-1.5ms |
| Medium      | 2      | 1024²             | 150m                | 4-tap            | 0.6-0.8ms |
| Low         | 2      | 512²              | 80m                 | 1-tap            | 0.3-0.4ms |
| Minimal     | 1      | 512²              | 50m                 | 1-tap (硬件 2x2) | 0.15ms    |

#### (2) Per-Object Inset Shadow（角色专用高精度阴影）

```bash
SkeletalMeshActor → Rendering:
  Cast Inset Shadow = true     ; 角色独立 Per-Object ShadowMap
```

- 只有角色自己一张 1024×1024 ShadowMap
- 与 CSM 独立，分辨率固定不受相机距离影响
- 角色身上的**自阴影质量显著提升**（比如布褶、武器阴影）
- 代价：+1 DrawCall/角色 Per-Frame

#### (3) Stable CSM（防游泳）

```ini
r.Shadow.TexelsPerPixel   =1.27324    ; 默认值，稳定
r.Shadow.FadePlaneSize    =500        ; Fade 带宽
r.Shadow.RadiusThreshold  =0.03       ; 小物体裁掉阴影
```

大世界强烈建议勾 DirectionalLight 的 **"Use Inset Shadows For Movable Objects"** 并启用 Stable CSM，否则相机快速移动时阴影边缘会闪烁。

### 4.3 远处阴影（150m - 10km）：**DFShadow + Precomputed Shadow**

#### (1) Distance Field Shadow（大世界远景关键）

```ini
; Project Settings → Rendering
r.DistanceFields=1                              ; 必开
r.GenerateMeshDistanceFields=1
r.DistanceFieldShadowing=1                      ; 开 DFShadow
r.DistanceFieldBuild.Compress=1
```

```bash
DirectionalLight:
  Distance Field Shadow Distance = 1000000      ; 10km
  Far Shadow Cascade Count       = 2            ; CSM 后面额外远距离级联
  Far Shadow Distance            = 30000        ; 300m 内用 Far CSM
                                                ; 300m 外用 DFShadow
```

**数据流**：

```bash
[Offline Build]:
  StaticMesh → 体素化 → Mesh Distance Field (3D Volume Texture)
  每个 Mesh 独立 SDF (R8UNorm, 典型 64³ = 256KB)
  合并到 Global Distance Field (World Space, 多级 Clipmap)

[Runtime]:
  Pixel WorldPos → Ray March Global SDF 指向光源方向
  命中距离 ≤ threshold → 在阴影中
  平滑衰减 → 柔软的远景阴影
```

- **优势**：
  - ✅ **无级联无锯齿**，远景山体阴影清晰
  - ✅ **自带 Soft Shadow**（SDF 的自然属性）
  - ✅ 成本与屏幕像素数相关，**与投射物数量无关**（1 棵树和 1 万棵树开销几乎一样）
- **代价**：
  - ⚠️ 内存：大世界 Global SDF Clipmap 约 **50-120MB**
  - ⚠️ 仅 Mobile Deferred / Desktop Renderer 支持
  - ⚠️ 精度有限（体素化后小物件细节丢失）
  - ⚠️ Skeletal Mesh **不参与 DFShadow**（只有静态网格体）

#### (2) Precomputed Shadow Mask（大面积静态阴影烘焙）

对于**完全不动的大世界静态物体**（山体、古建筑、大树干），强烈建议烘焙进 Shadow Mask：

```bash
Light Mobility = Stationary
Material → Use Shadow Map = true
Lighting Build → Precomputed Shadowmask = enabled

结果：
  - 静态物体对静态物体的阴影 → Lightmap
  - 静态物体对动态物体的阴影 → Shadow Mask Channel (R8)
  - 动态物体对静态/动态的阴影 → CSM + DFShadow 运行时
```

Stationary Light 的 **Shadow Mask** 只用 1 通道 R8，几乎零运行时开销，却能覆盖 80% 的"远山投影到地面"的效果。

#### (3) 远景阴影分距离方案总览

```
0m ──── 50m ──── 150m ──── 300m ──── 1km ──── 10km
 │        │        │         │         │        │
 │  CSM0  │  CSM1  │ Far CSM │  DFS    │ DFS+SM │
 │(2048²) │(1024²) │  (512²) │         │        │
 │        │        │         │         │        │
 │ Per-Obj Inset (角色)       │         │        │
 │        │        │         │         │        │
 │  Capsule (角色软阴影)      │         │        │
 │        │        │         │         │        │
 │ Modulated (可选兜底)       │         │        │
 │        │        │         │         │        │
 └──────── Precomputed Shadow Mask (静态物体,全距离) ─────┘
```

### 4.4 Capsule Shadow（角色廉价软阴影）

移动端**性价比最高**的角色软阴影方案：

```
SkeletalMesh → Rendering:
  Shadow Physics Asset = <capsule-only asset>
  Cast Capsule Shadows = true
```

- 用角色的 **Capsule Physics Asset** 做一个"胶囊阵列"近似几何体
- 对 **Indirect Light (Skylight)** 产生柔软的接触阴影
- **单位体积内 ~1-2 capsule/角色**，开销极低（< 0.1ms/角色）
- **与 CSM 无冲突**，互补使用

### 4.5 Modulated Shadow（低端机兜底）

当 CSM 开销过大时，低端机可以用 UE 移动端特有的 Modulated Shadow：

```
DirectionalLight:
  Cast Modulated Shadows = true
  Modulated Shadow Color = (0.3, 0.3, 0.4, 1.0)
```

```
流程：
  1. ShadowDepthPass (正常)
  2. Opaque BasePass
  3. Modulated Shadow Pass (全屏 Stencil Mask + SceneColor × ShadowColor)
     ★ 半透明物体已经在 SceneColor 中 → 自动接收阴影！
```

- ✅ 开销极低（1 次全屏 Pass）
- ✅ **半透明自动接收阴影**（植被、布料、粒子）
- ❌ 阴影会"穿透"物体（不区分遮挡关系）
- ❌ 乘法混合，暗部会更暗

### 4.6 阴影完整分档表

| 档位        | 近场方案                          | 远场方案                       | 角色            | 半透明                       | GPU 开销  |
| ----------- | --------------------------------- | ------------------------------ | --------------- | ---------------------------- | --------- |
| **High**    | CSM 3 级联 2048² + Per-Obj Inset  | DFShadow + Precomputed         | Capsule + Inset | Surface ForwardShading + CSM | 2.5-3.5ms |
| **Medium**  | CSM 2 级联 1024² + Per-Obj Inset  | DFShadow (近) + Precomputed    | Capsule         | Modulated                    | 1.2-1.8ms |
| **Low**     | CSM 2 级联 512²                   | Precomputed Only (关 DFShadow) | 无 Inset        | Modulated                    | 0.5-0.8ms |
| **Minimal** | Modulated Only 或 CSM 1 级联 512² | Precomputed Only               | 无              | Modulated (共用)             | 0.2-0.4ms |

---

## 5. 分档适配 (Device Scalability)

### 5.1 机型分档映射

| 档位        | 代表机型     | Android GPU                          | iOS 芯片   | 目标帧率 | 目标分辨率 |
| ----------- | ------------ | ------------------------------------ | ---------- | -------- | ---------- |
| **High**    | 旗舰 (2023+) | Adreno 7xx / Mali-G7xx / Xclipse 9xx | A16+ / M1+ | 60 FPS   | 1080p 100% |
| **Medium**  | 中端 (2021+) | Adreno 6xx 高端 / Mali-G6xx          | A13-A15    | 30 FPS   | 1080p 80%  |
| **Low**     | 入门 (2019+) | Adreno 6xx 入门 / Mali-G52           | A11-A12    | 30 FPS   | 720p 100%  |
| **Minimal** | 老旧         | Adreno 5xx / Mali-G31                | A10-以下   | 30 FPS   | 720p 75%   |

### 5.2 启动时机型检测 + 分档（伪代码）

```cpp
// GameInstance 启动时调用
EScalabilityLevel DetectLevel()
{
    FString GPUFamily = FPlatformMisc::GetPrimaryGPUBrand();
    int32 TotalMemMB = FPlatformMemory::GetPhysicalGBRam() * 1024;
    bool bSupportVulkan = FAndroidPlatformMisc::HasVulkanDriverSupport();
    bool bSupportSM5 = FAndroidPlatformMisc::SupportsSM5();

    if (bSupportSM5 && TotalMemMB >= 12000 &&
        GPUFamily.Contains("Adreno 7") || GPUFamily.Contains("Mali-G71"))
        return EScalabilityLevel::High;
    
    if (bSupportVulkan && TotalMemMB >= 6000)
        return EScalabilityLevel::Medium;
    
    if (TotalMemMB >= 4000)
        return EScalabilityLevel::Low;
    
    return EScalabilityLevel::Minimal;
}

void ApplyScalability(EScalabilityLevel Level)
{
    FString CfgName;
    switch (Level) {
        case High:    CfgName = TEXT("Scalability_High"); break;
        case Medium:  CfgName = TEXT("Scalability_Medium"); break;
        case Low:     CfgName = TEXT("Scalability_Low"); break;
        case Minimal: CfgName = TEXT("Scalability_Minimal"); break;
    }
    
    // 1. 应用 sg.* Group
    Scalability::LoadState(CfgName);
    
    // 2. 动态切 Renderer（需重启）
    if (Level == EScalabilityLevel::Minimal) {
        IConsoleManager::Get().FindConsoleVariable(TEXT("r.Mobile.ShadingPath"))
            ->Set(0); // 切回 Forward
    }
    
    // 3. 锁帧 & 动态分辨率
    if (Level <= EScalabilityLevel::Low)
        GEngine->SetMaxFPS(30);
    
    // 4. 温度监控（连续高温降档）
    ThermalManager::SetPolicy(Level);
}
```

### 5.3 完整分档 CVar 表

```ini
; ============ Scalability_High (旗舰) ============
[Scalability_High]
sg.ResolutionQuality=100
sg.ViewDistanceQuality=3
sg.AntiAliasingQuality=3
sg.ShadowQuality=3
sg.GlobalIlluminationQuality=2
sg.ReflectionQuality=2
sg.PostProcessQuality=3
sg.TextureQuality=3
sg.EffectsQuality=3
sg.FoliageQuality=3

r.Mobile.ShadingPath=1
r.DistanceFields=1
r.DistanceFieldShadowing=1
r.SSGI.Enable=1
r.SSGI.HalfRes=1
r.Shadow.MaxCSMResolution=2048
r.Shadow.CSM.MaxMobileCascades=3
r.MobileContentScaleFactor=1.0

; ============ Scalability_Medium (中端) ============
[Scalability_Medium]
sg.ResolutionQuality=80
sg.ShadowQuality=2
sg.GlobalIlluminationQuality=1
r.Mobile.ShadingPath=1
r.DistanceFields=1                    ; 保留 DFShadow
r.DistanceFieldShadowing=1
r.SSGI.Enable=0
r.Shadow.MaxCSMResolution=1024
r.Shadow.CSM.MaxMobileCascades=2
r.MobileContentScaleFactor=0.8

; ============ Scalability_Low (入门) ============
[Scalability_Low]
sg.ResolutionQuality=65
sg.ShadowQuality=1
sg.GlobalIlluminationQuality=0
r.Mobile.ShadingPath=1                 ; 仍走 Deferred
r.DistanceFields=0                     ; 关 SDF 省 100MB 内存
r.DistanceFieldShadowing=0
r.Shadow.MaxCSMResolution=512
r.Shadow.CSM.MaxMobileCascades=2
r.MobileContentScaleFactor=0.65
r.VolumetricLightmap.Enable=0          ; 关 VLM

; ============ Scalability_Minimal (老旧) ============
[Scalability_Minimal]
sg.ResolutionQuality=50
sg.ShadowQuality=0
sg.GlobalIlluminationQuality=0
r.Mobile.ShadingPath=0                 ; 切回 Forward (需重启)
r.Shadow.MaxCSMResolution=512
r.Shadow.CSM.MaxMobileCascades=1
r.MobileContentScaleFactor=0.5
; Modulated Shadow Only
```

### 5.4 Content Scale + MobileFSR（移动端分辨率缩放）

```ini
; 动态分辨率：2D Scaling 线程池内完成
r.MobileContentScaleFactor=0.8         ; 渲染缓冲 80%
r.DynamicRes.OperationMode=1           ; 基于帧时间自适应
r.DynamicRes.FrameTimeBudget=33.3      ; 30FPS 预算

; MobileFSR (UE5.3+) — 空间上采样
r.MobileFSR.Enabled=1
r.MobileFSR.Upscaling.Quality=1        ; 0=Performance 1=Quality 2=UltraQuality
```

高端机在 1080p 渲染后用 FSR 1.0 上采到原生屏幕（典型 1440p/2K），**GPU 开销可降 25-40%**。

---

## 6. 带宽预算（Bandwidth Budget）

移动端**带宽 = 电量 = 发热**。带宽是比 ALU 更稀缺的资源。

### 6.1 为什么带宽是移动端核心指标

```
Mobile SoC 带宽层次（骁龙8Gen2 为例）:
┌─────────────────────────────────────────────────┐
│  Tile SRAM (片上)      100+ GB/s   ~1mJ/GB      │  ← Deferred GBuffer 停留于此
├─────────────────────────────────────────────────┤
│  L2/L3 Cache           50 GB/s     ~2mJ/GB      │
├─────────────────────────────────────────────────┤
│  LPDDR5X System RAM    50-60 GB/s  ~100mJ/GB    │  ← 每次 Tile Flush 的代价
└─────────────────────────────────────────────────┘

同样 1GB 数据：
  Tile 内访问 ≈ 1 毫焦
  外部 DRAM 访问 ≈ 100 毫焦（差 100 倍！）
```

### 6.2 分档带宽预算（1080p × 30fps）

| 组件                                | 每帧带宽            | 每秒带宽 (30fps) | 说明                             |
| ----------------------------------- | ------------------- | ---------------- | -------------------------------- |
| **SceneColor** (R11G11B10F)         | 4B × 1080² ≈ 8 MB   | 240 MB/s         | Read + Write                     |
| **SceneDepth** (D24_S8)             | 4B × 1080² ≈ 8 MB   | 240 MB/s         | Read + Write                     |
| **GBuffer** (4×RT32, Deferred)      | 16B × 1080² ≈ 32 MB | 960 MB/s         | **全部留 Tile 内** → 实际落地 0! |
| **CSM Shadow Map** (2048² D16)      | 8 MB                | 240 MB/s         | 写入 + 读取                      |
| **DFShadow SDF Sample**             | ~2 MB               | 60 MB/s          | Ray March 采样                   |
| **Lightmap 采样**                   | ~4 MB               | 120 MB/s         | ASTC 6×6 压缩后                  |
| **RenderTargets 切换** (Tile Flush) | 1 次 = 32 MB        | 每次切换         | ★ 最昂贵 ★                       |
| **后处理** (Bloom, ToneMap)         | 16 MB               | 480 MB/s         | 半分辨率 Bloom                   |

### 6.3 各档位带宽实测参考（1080p × 30fps，骁龙8Gen2）

```
┌─────────────────────────────────────────────────────────┐
│  档位     │ Total BW │ DDR 访问 │ Tile 命中 │ 发热等级    │
├─────────────────────────────────────────────────────────┤
│  High     │ ~18 GB/s │  11 GB/s │   65%    │ 高（45℃）  │
│  Medium   │ ~12 GB/s │   7 GB/s │   72%    │ 中（40℃）  │
│  Low      │ ~8 GB/s  │   5 GB/s │   78%    │ 低（36℃）  │
│  Minimal  │ ~5 GB/s  │   3 GB/s │   70%    │ 极低（33℃）│
└─────────────────────────────────────────────────────────┘

对比：
  Lumen 旗舰档:     25-40 GB/s (DDR 访问 20+)  → 50℃+ 烫手
  Mobile Forward:  ~8 GB/s (基线)
```

### 6.4 带宽优化要点

#### (1) 合并 RenderPass，避免 Tile Flush

每次切换 RenderTarget **= 一次 Tile Resolve + 一次 Load** = 64 MB 峰值带宽浪费。

```
BAD (每次切 RT 都 Flush):
  BasePass → RT1
  PostEffect1 → RT2  (Flush RT1)
  PostEffect2 → RT3  (Flush RT2)
  Final → SwapChain  (Flush RT3)
  
  4 次 Flush = 128 MB 落地

GOOD (Subpass / Framebuffer Fetch):
  BasePass → GBuffer  (Tile 内)
     ↓
  Lighting → SceneColor  (同一 RenderPass, Subpass)
     ↓
  PostEffect (Full Screen Blit)  (一次落地)
  
  1 次 Flush = 32 MB 落地 (节省 75%)
```

UE 移动端实现在 **`FMobileSceneRenderer::Render()`** 中统一组织成一个大 RenderPass：

```cpp
// UE Source: MobileShadingRenderer.cpp
RenderPrePass();                  // Tile 内
RenderDepthPass();                // Tile 内
RenderBasePass();                 // Tile 内 (GBuffer)
RenderMobileLightPass();          // Tile 内 (Subpass/FramebufferFetch)
RenderTranslucency();             // Tile 内
// ↑ 以上全部在一个 Vulkan RenderPass 的多个 Subpass 中完成
ResolveSceneColor();              // 一次落地到 DDR
RenderPostProcess();              // 另一个 RenderPass
```

#### (2) Memoryless Depth/Stencil (iOS Metal)

```ini
r.Mobile.MemorylessDepthBuffer=1     ; Depth 只在 Tile 内存在，不落 DDR
r.Mobile.MemorylessMSAA=1            ; MSAA 也 Memoryless（TBR 免费）
```

#### (3) ASTC 压缩纹理

```
纹理     │ 未压缩 RGBA8      │ ASTC 4×4 │ ASTC 6×6 │ ASTC 8×8
─────────┼──────────────────┼──────────┼──────────┼──────────
 1024²   │    4.0 MB        │  1.0 MB  │  0.44 MB │  0.25 MB
 带宽峰值 │  100% (baseline) │  25%     │  11%     │  6%
```

大世界场景全 ASTC 6×6 比 ASTC 4×4 节省 **56% 纹理带宽**，画质损失在移动端几乎不可见。

#### (4) 关 MSAA

Mobile Deferred 本身**不支持 MSAA**（GBuffer 采样量会爆炸），且 TBR 上 MSAA "免费"的说法只在前向有效。推荐：

```ini
r.MobileMSAA=1          ; 关闭 (1=off)
r.AntiAliasingMethod=2  ; 改用 TAA（0.5ms 代价）
```

#### (5) 半分辨率后处理

```ini
r.Bloom.HalfResolutionFFT=1
r.SSR.HalfRes=1
r.SSAO.HalfRes=1
r.MotionBlurQuality=0          ; 移动端不建议开
r.DepthOfFieldQuality=0        ; 移动端不建议开
```

---

## 7. 工程化落地清单

### 7.1 上线前必查（Rendering Checklist）

```
□ 渲染管线
  □ 目标机型的 r.Mobile.ShadingPath 确认（Forward/Deferred）
  □ Desktop Renderer 仅用于白名单机型（不是所有旗舰都稳）
  □ Vulkan/Metal 启用，GLES 仅留老机兜底

□ GI
  □ 所有静态光源 = Stationary 或 Static
  □ 关键场景全部烘焙 Lightmap + Precomputed Shadow Mask
  □ World Partition + HLOD1 全覆盖
  □ VLM 分辨率合理（DetailCellSize 150-400cm）

□ 阴影
  □ DirectionalLight CSM 距离 ≤ 200m
  □ Num Cascades ≤ 3（移动端）
  □ Shadow Normal Bias 调试好，无漏光
  □ DFShadow 内存 < 120MB
  □ 角色开 Per-Object Inset + Capsule Shadow

□ 分档
  □ 启动时机型检测逻辑已测试（至少覆盖 20 款主力机）
  □ sg.* Group 每档 CVar 明确
  □ ThermalManager 监控工作
  □ 动态降档不引起画质闪烁

□ 带宽
  □ Scene RT 切换 ≤ 3 次/帧
  □ 纹理 100% ASTC
  □ Memoryless Depth 开启
  □ RenderDoc 验证 TBR tile 命中率 > 70%
  □ AGI/Snapdragon Profiler 带宽峰值 < 20GB/s (1080p30)

□ 发热
  □ 室温 25℃ 连续 30min，机身温度 < 45℃
  □ 30FPS 锁帧场景不超电 4%/10min
  □ 后台暂停渲染 (OnApplicationPause)
```

### 7.2 源码改造点（参考）

| 改造点                           | 原因                       | 改造路径                                                                |
| -------------------------------- | -------------------------- | ----------------------------------------------------------------------- |
| **1. Stationary CSM Caching**    | 相机静止时不重建 ShadowMap | `MobileShadowRendering.cpp::RenderShadowDepth` 加脏标记                 |
| **2. Particle 接收 CSM**         | 粒子默认无阴影             | `MobileBasePassPixelShader.usf` + `r.Mobile.EnableTranslucencyShadow=1` |
| **3. DFShadow Clipmap 动态收缩** | 大世界跑图时 DDR 压力大    | `DistanceFieldShadowing.cpp` 按速度调 Clipmap 半径                      |
| **4. 角色 Inset 合批**           | 多角色每个 1 DrawCall      | Collect 后合并到单 Atlas                                                |
| **5. Lightmap 流送**             | 大世界 Lightmap 总量 GB 级 | World Partition Streaming + Cell-Level Loader                           |

---

## 8. 小结

> **问题直接答案速查**（一页总结）：

```
┌────────────────────────────────────────────────────────────────────┐
│ Q1. GI 用什么？                                                     │
│   → 主方案: Lightmap + Volumetric Lightmap + Sky Light              │
│   → 加餐: SSGI (Deferred 中高端)                                    │
│   → 旗舰: Lumen (Desktop Renderer + Vulkan SM5，实验性)             │
├────────────────────────────────────────────────────────────────────┤
│ Q2. 近处阴影？                                                      │
│   → CSM 2-3 级联（1024²-2048²，0-150m）                             │
│   → Per-Object Inset Shadow（角色高精度）                           │
│   → Capsule Shadow（角色软阴影，性价比最高）                         │
├────────────────────────────────────────────────────────────────────┤
│ Q3. 远处阴影？                                                      │
│   → Distance Field Shadow（150m-10km，需 Deferred + r.DistanceFields│
│     =1，内存 ~100MB）                                               │
│   → Precomputed Shadow Mask（静态烘焙，全距离）                      │
│   → Far Shadow Cascade 补充衔接                                     │
├────────────────────────────────────────────────────────────────────┤
│ Q4. 分档？                                                          │
│   → High/Medium/Low/Minimal 4 档                                    │
│   → sg.GlobalIlluminationQuality / sg.ShadowQuality 等驱动          │
│   → 启动 GPU+内存检测 → 映射档位，ThermalManager 动态降级             │
├────────────────────────────────────────────────────────────────────┤
│ Q5. 带宽？                                                          │
│   → 1080p30 High: ~18 GB/s (DDR 实访问 11)                          │
│   →         Medium: ~12 GB/s                                       │
│   →         Low: ~8 GB/s                                           │
│   →         Minimal: ~5 GB/s                                       │
│   → 核心优化: Subpass/FBO Fetch + Memoryless + ASTC + 合并 RT       │
├────────────────────────────────────────────────────────────────────┤
│ Q6. 管线？                                                          │
│   → Mobile Deferred (r.Mobile.ShadingPath=1) ← 大世界主力           │
│   → Mobile Forward (r.Mobile.ShadingPath=0) ← 低端机兜底            │
│   → Desktop Renderer ← 旗舰机技术储备 (Vulkan SM5 + Metal Desktop)  │
└────────────────────────────────────────────────────────────────────┘
```

**核心原则**：

1. **大世界默认 Mobile Deferred**（UE5.6 推荐），仅入门机回退 Forward
2. **GI 靠烘焙**（Lightmap），不要幻想移动端全动态 GI 稳定在商业项目
3. **近 CSM + 远 DFShadow** 是大世界阴影的**黄金组合**，两者由 `Far Shadow Cascade` 自然衔接
4. **带宽决定发热**，所有优化最终都要落到 Tile 命中率、RT 切换次数、纹理压缩这三件事
5. **分档必须是代码级联动的**，不能只靠美术配置

## 9. 延伸阅读

- [Mobile Lumen 专题笔记（本站）](/2026/05/05/MobileLumen.html)
- [CSM 阴影调参详解（本站）](/2025/04/09/CSM阴影边缘颜色调节.html)
- [Mobile 半透明材质接收阴影（本站）](/2025/04/09/Mobile半透明材质接收阴影.html)
- [TBR 与 TBDR 架构（本站 engine_skill）](/2026/04/14/TBR与TBDR架构.html)
- UE 官方：[移动端渲染功能 (UE5.6)](https://dev.epicgames.com/documentation/zh-cn/unreal-engine/rendering-features-for-mobile-games-in-unreal-engine)
- UE 官方：[移动延迟着色模式 (UE5.6)](https://dev.epicgames.com/documentation/zh-cn/unreal-engine/using-the-mobile-deferred-shading-mode-in-unreal-engine)
- UE 官方：[移动端 Lumen (UE5.6)](https://dev.epicgames.com/documentation/zh-cn/unreal-engine/using-lumen-global-illumination-on-mobile-in-unreal-engine)
