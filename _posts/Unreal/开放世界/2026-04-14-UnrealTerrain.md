---
layout:     post
title:      UnrealTerrain
subtitle:   Landscape 架构、LOD、Virtual Texture、World Partition、性能优化
date:       2026-04-14
author:     engineyk
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - Unreal
    - 地形
---

# Unreal 地形系统深度解析

```
目录
├── 1. 概述与核心挑战
├── 2. Landscape 系统架构
│   ├── 2.1 核心类层级
│   ├── 2.2 Component / Section / Quad 三级结构
│   ├── 2.3 高度图与权重图存储
│   └── 2.4 Landscape 坐标系统
├── 3. LOD 系统
│   ├── 3.1 基于距离的 LOD
│   ├── 3.2 Morphing（形变过渡）
│   ├── 3.3 邻接 LOD 缝合
│   └── 3.4 LOD 参数调优
├── 4. 地形材质系统
│   ├── 4.1 Layer Blend 原理
│   ├── 4.2 Texture Array vs 传统多层
│   ├── 4.3 材质复杂度与 Shader 变体
│   └── 4.4 距离混合与 Macro Variation
├── 5. Virtual Texture（VT）
│   ├── 5.1 Runtime Virtual Texture 原理
│   ├── 5.2 RVT 在地形中的应用
│   ├── 5.3 Streaming Virtual Texture
│   └── 5.4 VT 性能分析
├── 6. World Partition 与大世界
│   ├── 6.1 World Partition 架构
│   ├── 6.2 Landscape Streaming Proxy
│   ├── 6.3 HLOD 与地形
│   └── 6.4 Data Layer
├── 7. 地形物理与碰撞
│   ├── 7.1 碰撞数据生成
│   ├── 7.2 Physical Material 映射
│   └── 7.3 碰撞性能优化
├── 8. 地形植被（Foliage）集成
│   ├── 8.1 Procedural Foliage
│   ├── 8.2 Grass System
│   └── 8.3 Nanite Foliage
├── 9. 地形编辑工具
│   ├── 9.1 Sculpt / Paint 工具
│   ├── 9.2 Landscape Spline
│   ├── 9.3 Blueprint Brush
│   └── 9.4 外部工具导入（World Machine / Gaea）
├── 10. 渲染管线集成
│   ├── 10.1 地形在 Deferred 管线中的位置
│   ├── 10.2 Nanite Landscape（UE5.2+）
│   ├── 10.3 Lumen 与地形 GI
│   └── 10.4 Shadow 与地形
├── 11. 性能优化
│   ├── 11.1 Draw Call 优化
│   ├── 11.2 内存优化
│   ├── 11.3 GPU 性能优化
│   ├── 11.4 Streaming 优化
│   └── 11.5 移动端适配
├── 12. 面试高频问题
└── 13. 实践检查清单
```

---

## 1. 概述与核心挑战

```
地形渲染的核心矛盾：

  ┌─────────────────────────────────────────────────────┐
  │                                                     │
  │   巨大的面积（数十 km²）                              │
  │        ×                                            │
  │   高密度的细节（每米数个顶点）                         │
  │        ×                                            │
  │   多层材质混合（4-16 层纹理）                         │
  │        ×                                            │
  │   实时交互（编辑、物理、植被）                         │
  │        =                                            │
  │   海量数据 + 高渲染开销                               │
  │                                                     │
  └─────────────────────────────────────────────────────┘

Unreal 的解决方案：

  ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
  │  Landscape 系统   │   │  Virtual Texture │   │  World Partition  │
  │                  │   │                  │   │                  │
  │ • 分块管理       │   │ • 按需加载纹理   │   │ • 流式加载世界   │
  │ • 多级 LOD       │   │ • 减少材质开销   │   │ • 自动分区       │
  │ • GPU Morphing   │   │ • 统一缓存管理   │   │ • HLOD 集成      │
  └──────────────────┘   └──────────────────┘   └──────────────────┘
```

### Unreal 地形 vs 其他引擎

```
┌──────────────┬──────────────────┬──────────────────┬──────────────────┐
│   特性        │   Unreal         │   Unity          │   CryEngine      │
├──────────────┼──────────────────┼──────────────────┼──────────────────┤
│ 基础结构      │ Heightfield      │ Heightfield      │ Heightfield      │
│              │ Component-based  │ Terrain 单体     │ Sector-based     │
│ 最大尺寸      │ 理论无限         │ 单 Terrain 有限  │ 8km × 8km        │
│              │ (World Partition)│ (需拼接)         │                  │
│ LOD          │ Component 级     │ Patch 级         │ Sector 级        │
│ 材质混合      │ Layer Blend      │ Splat Map        │ Layer Painting   │
│ Virtual Tex  │ RVT + SVT        │ 无原生支持       │ 有               │
│ 植被集成      │ Grass + Foliage  │ Detail + Tree    │ Vegetation       │
│ Nanite 支持   │ UE5.2+           │ 无               │ 无               │
│ 物理材质      │ Per-Layer        │ Per-Layer        │ Per-Layer        │
└──────────────┴──────────────────┴──────────────────┴──────────────────┘
```

---

## 2. Landscape 系统架构

### 2.1 核心类层级

```
┌─────────────────────────────────────────────────────────────────┐
│                        ALandscapeProxy                         │
│  (Base class for all landscape actors)                         │
│                                                                │
│  ├── ALandscape                                                │
│  │   • 主 Landscape Actor                                      │
│  │   • 持有共享数据（LayerInfo、Material）                      │
│  │   • 编辑器中的编辑入口                                       │
│  │                                                             │
│  └── ALandscapeStreamingProxy                                  │
│      • 流式加载的子 Landscape                                   │
│      • World Partition 自动生成                                 │
│      • 每个 Proxy 包含若干 Component                            │
│                                                                │
│  内部组成：                                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  ULandscapeComponent (继承自 UPrimitiveComponent)        │   │
│  │  • 渲染和碰撞的基本单位                                   │   │
│  │  • 每个 Component 是一个独立的 Draw Call                   │   │
│  │  • 持有 HeightmapTexture、WeightmapTexture                │   │
│  │                                                          │   │
│  │  ┌─────────────────────────────────────────────────┐     │   │
│  │  │  ULandscapeHeightfieldCollisionComponent         │     │   │
│  │  │  • 碰撞数据                                      │     │   │
│  │  │  • 可独立于渲染 Component 存在                    │     │   │
│  │  └─────────────────────────────────────────────────┘     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
│  辅助类：                                                       │
│  • ULandscapeInfo          - 全局 Landscape 信息管理            │
│  • ULandscapeLayerInfoObject - 层信息（Physical Material 等）   │
│  • FLandscapeComponentSceneProxy - 渲染线程代理                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Component / Section / Quad 三级结构

```
═══ 层级关系 ═══

  Landscape
  └── Component（渲染/碰撞单位）
      └── Section（SubSection，LOD 单位）
          └── Quad（最小网格单元）

═══ 尺寸配置 ═══

  创建 Landscape 时的关键参数：

  ┌────────────────────────────────────────────────────────────┐
  │  Section Size:  每个 Section 的顶点数（边长）               │
  │    可选值: 7×7, 15×15, 31×31, 63×63, 127×127, 255×255     │
  │                                                            │
  │  Sections Per Component:  每个 Component 包含的 Section 数  │
  │    可选值: 1×1 或 2×2                                      │
  │                                                            │
  │  Number of Components:  Component 的总数                    │
  │    决定了 Landscape 的总尺寸                                │
  └────────────────────────────────────────────────────────────┘

  示例：Section Size = 63, Sections Per Component = 2×2

  ┌───────────────────────────────────────┐
  │          1 个 Component               │
  │  ┌─────────────┬─────────────┐        │
  │  │  Section 0  │  Section 1  │        │
  │  │  63×63 顶点 │  63×63 顶点 │        │
  │  ├─────────────┼─────────────┤        │
  │  │  Section 2  │  Section 3  │        │
  │  │  63×63 顶点 │  63×63 顶点 │        │
  │  └─────────────┴─────────────┘        │
  │                                       │
  │  Component 总顶点: 126×126 = 15876    │
  │  Component 总 Quad: 125×125 = 15625   │
  │  Component 总三角形: 31250             │
  └───────────────────────────────────────┘

═══ 推荐配置 ═══

  ┌──────────────────┬──────────────┬──────────────┬──────────────┐
  │  场景规模         │ Section Size │ Sections/Comp│ 说明          │
  ├──────────────────┼──────────────┼──────────────┼──────────────┤
  │  小型（< 2km²）  │ 63×63        │ 1×1          │ 精细 LOD 控制 │
  │  中型（2-16km²） │ 63×63        │ 2×2          │ 平衡选择      │
  │  大型（> 16km²） │ 127×127      │ 2×2          │ 减少 Component│
  │  超大（开放世界） │ 63×63        │ 2×2          │ + World Part. │
  └──────────────────┴──────────────┴──────────────┴──────────────┘

  ⚠️ 关键约束：
  • Component 是 Draw Call 的最小单位 → Component 越多，Draw Call 越多
  • Section 是 LOD 的最小单位 → Section 越小，LOD 过渡越精细
  • 总顶点数 = (SectionSize × SectionsPerComp × NumComponents)²
```

### 2.3 高度图与权重图存储

```
═══ 高度图（Heightmap）═══

  格式: RGBA8 或 R16（取决于平台）
  
  RGBA8 编码方式：
  ┌──────────────────────────────────────────────────┐
  │  R: Height 高 8 位                                │
  │  G: Height 低 8 位                                │
  │  B: Normal.X（Packed）                            │
  │  A: Normal.Y（Packed）                            │
  │                                                  │
  │  Height 精度: 16 bit → 65536 级                   │
  │  默认范围: -256m ~ +256m（可通过 Scale.Z 调整）    │
  │  精度: 512m / 65536 ≈ 0.0078m ≈ 0.78cm           │
  └──────────────────────────────────────────────────┘

  每个 Component 有独立的 Heightmap Texture
  相邻 Component 共享边界行/列（避免缝隙）

═══ 权重图（Weightmap）═══

  格式: R8（每层一个通道或一张纹理）
  
  存储方式：
  ┌──────────────────────────────────────────────────┐
  │  方式 1: Weight-Blended（默认）                    │
  │  • 每层一个 R8 通道                                │
  │  • 所有层权重之和 = 255                            │
  │  • 最多 16 层（受 Texture Sampler 限制）           │
  │                                                  │
  │  方式 2: Alpha-Blended                            │
  │  • 层按顺序叠加                                   │
  │  • 上层覆盖下层                                   │
  │  • 不受权重归一化约束                              │
  └──────────────────────────────────────────────────┘

  内存占用示例（4km × 4km，1m 分辨率，8 层）：
  • Heightmap: 4096 × 4096 × 4 bytes = 64 MB
  • Weightmap: 4096 × 4096 × 8 bytes = 128 MB
  • 总计: 192 MB（未压缩）
```

### 2.4 Landscape 坐标系统

```
  ┌──────────────────────────────────────────────────────────┐
  │  Landscape 使用自己的局部坐标系：                         │
  │                                                          │
  │  • 1 Landscape Unit = 1 Quad = 默认 100cm（1m）          │
  │  • Scale 可调：Scale(100,100,100) → 1 Quad = 1m          │
  │  • 顶点位置 = QuadIndex × Scale                          │
  │                                                          │
  │  坐标转换：                                               │
  │  World Position = LandscapeTransform × Local Position     │
  │                                                          │
  │  UV 计算：                                                │
  │  HeightmapUV = VertexPosition.xy / ComponentSize          │
  │  WeightmapUV = VertexPosition.xy / ComponentSize          │
  │  MaterialUV  = WorldPosition.xy / TextureTilingScale      │
  └──────────────────────────────────────────────────────────┘
```

---

## 3. LOD 系统

### 3.1 基于距离的 LOD

```
═══ LOD 级别 ═══

  每个 Section 独立计算 LOD 级别
  LOD 0 = 最高精度（所有顶点）
  LOD N = 每级减半顶点

  Section Size = 63 时的 LOD 级别：
  ┌───────┬──────────────┬──────────────┬──────────────┐
  │  LOD  │  顶点数(边长) │  Quad 数     │  三角形数     │
  ├───────┼──────────────┼──────────────┼──────────────┤
  │  0    │  63 × 63     │  62 × 62     │  7688        │
  │  1    │  32 × 32     │  31 × 31     │  1922        │
  │  2    │  16 × 16     │  15 × 15     │  450         │
  │  3    │  8 × 8       │  7 × 7       │  98          │
  │  4    │  4 × 4       │  3 × 3       │  18          │
  │  5    │  2 × 2       │  1 × 1       │  2           │
  └───────┴──────────────┴──────────────┴──────────────┘

═══ LOD 距离计算 ═══

  LOD 选择公式（简化）：
  LODLevel = clamp(
    log2(Distance / LOD0ScreenSize / ComponentSize),
    0,
    MaxLOD
  )

  关键参数：
  • LOD 0 Screen Size:  LOD 0 的屏幕占比阈值
  • LOD Distribution Setting:  LOD 分布曲线（0=均匀，>0=远处更激进）
  • LOD Falloff:  LOD 衰减类型（Linear / SquareRoot）
```

### 3.2 Morphing（形变过渡）

```
═══ 问题：LOD 切换时的 Popping ═══

  LOD N → LOD N+1 时，顶点数量突变
  导致地形表面突然跳变（Popping）

═══ 解决方案：GPU Morphing ═══

  在 Vertex Shader 中平滑过渡：

  ┌─────────────────────────────────────────────────────────┐
  │                                                         │
  │  LOD N 的顶点位置                                        │
  │       │                                                 │
  │       │  MorphFactor = f(Distance, LOD)                  │
  │       │  范围 [0, 1]                                     │
  │       ▼                                                 │
  │  FinalHeight = lerp(LOD_N_Height, LOD_N+1_Height,       │
  │                     MorphFactor)                         │
  │                                                         │
  │  当 MorphFactor = 0 → 完全使用当前 LOD                   │
  │  当 MorphFactor = 1 → 完全使用下一级 LOD                 │
  │       → 此时可以安全切换到 LOD N+1                       │
  │                                                         │
  └─────────────────────────────────────────────────────────┘

  Vertex Shader 伪代码：
  ```hlsl
  // LandscapeVertexFactory.usf
  float MorphAlpha = CalcLODMorphAlpha(Distance, LODLevel);
  
  // Even vertex: keep position
  // Odd vertex: morph toward even neighbor
  float3 MorphedPosition = Position;
  if (IsOddVertex)
  {
      float3 NeighborAvg = (Neighbor0.Position + Neighbor1.Position) * 0.5;
      MorphedPosition = lerp(Position, NeighborAvg, MorphAlpha);
  }
  ```

  原理图：
  LOD 0:  V0 --- V1 --- V2 --- V3 --- V4
                  ↓ morph
  LOD 1:  V0 --------- V2 --------- V4
          (V1 被 morph 到 V0-V2 中点，然后移除)
```

### 3.3 邻接 LOD 缝合

```
═══ 问题：相邻 Section LOD 不同导致 T-Junction ═══

  Section A (LOD 0)     Section B (LOD 1)
  V0 --- V1 --- V2      V0 --------- V2
                 ↑                    ↑
                 缝隙（T-Junction）

═══ 解决方案：边界顶点退化 ═══

  高 LOD Section 的边界顶点退化到低 LOD 的网格上：

  Section A (LOD 0)     Section B (LOD 1)
  V0 --- V1 --- V2      V0 --------- V2
          ↓ 退化
  V0 --------- V2      V0 --------- V2
  (V1 被移到 V0-V2 连线上)

  实现方式：
  • 每个 Section 存储 4 条边的邻接 LOD 信息
  • Vertex Shader 中根据邻接 LOD 差异调整边界顶点
  • 使用 Index Buffer 变体处理不同的邻接组合
  • 4 条边 × 最多 N 级 LOD 差异 → 预生成多套 Index Buffer
```

### 3.4 LOD 参数调优

```
  ┌──────────────────────────────────────────────────────────┐
  │  参数                        │ 建议值    │ 影响          │
  ├──────────────────────────────┼───────────┼───────────────┤
  │  LOD 0 Screen Size           │ 1.0-2.0   │ LOD 0 范围    │
  │  LOD Distribution Setting    │ 1.5-2.5   │ 远处 LOD 激进 │
  │  LOD Falloff                 │ SquareRoot│ 过渡曲线      │
  │  Forced LOD (调试用)          │ -1        │ 强制 LOD 级别 │
  │  Component Screen Size       │ 0.06      │ 整体剔除阈值  │
  │  Negative LOD Bias           │ 0         │ 全局 LOD 偏移 │
  └──────────────────────────────┴───────────┴───────────────┘

  调试命令：
  • r.ForceLOD N              - 强制所有地形使用 LOD N
  • r.LandscapeLODDistributionScale - 全局 LOD 分布缩放
  • ShowFlag.LODColoration 1  - 可视化 LOD 级别
  • stat landscape            - 地形性能统计
```

---

## 4. 地形材质系统

### 4.1 Layer Blend 原理

```
═══ 材质层混合流程 ═══

  ┌──────────────────────────────────────────────────────────┐
  │                                                          │
  │  Weightmap Texture (R8 per layer)                        │
  │  ┌─────┬─────┬─────┬─────┐                               │
  │  │ L0  │ L1  │ L2  │ L3  │  ← 每层一个权重通道           │
  │  │ 草地│ 泥土│ 岩石│ 沙地│                                │
  │  └──┬──┴──┬──┴──┬──┴──┬──┘                               │
  │     │     │     │     │                                  │
  │     ▼     ▼     ▼     ▼                                  │
  │  ┌─────────────────────────────────────────────┐         │
  │  │  FinalColor = Σ(LayerColor[i] × Weight[i])  │         │
  │  │  FinalNormal = Σ(LayerNormal[i] × Weight[i])│         │
  │  │  FinalRoughness = Σ(LayerRough[i] × Weight[i])│       │
  │  └─────────────────────────────────────────────┘         │
  │                                                          │
  └──────────────────────────────────────────────────────────┘

═══ 混合模式 ═══

  1. LB_WeightBlend（权重混合）
     • 所有层权重之和 = 1
     • 适合大多数场景
     • 添加新层会自动调整其他层权重

  2. LB_AlphaBlend（Alpha 混合）
     • 层按顺序叠加
     • 上层完全覆盖下层（Alpha=1 时）
     • 适合道路、河流等需要完全覆盖的场景

  3. LB_HeightBlend（高度混合）
     • 基于高度图的混合
     • 产生更自然的过渡效果
     • 额外采样高度纹理

  材质节点示例：
  ```
  [LandscapeLayerBlend]
    Layer 0: "Grass"   - WeightBlend
    Layer 1: "Dirt"    - WeightBlend  
    Layer 2: "Rock"    - HeightBlend (Height Texture)
    Layer 3: "Road"    - AlphaBlend
  ```
```

### 4.2 Texture Array vs 传统多层

```
═══ 传统方式（每层独立纹理）═══

  问题：
  • 每层需要 Diffuse + Normal + ORM = 3 个 Sampler
  • 8 层 = 24 个 Texture Sampler
  • 加上 Weightmap = 26+ Sampler
  • 超出硬件限制（通常 16 个）

═══ Texture Array 方式 ═══

  解决方案：
  • 将同类型纹理打包为 Texture2DArray
  • Diffuse Array + Normal Array + ORM Array = 3 个 Sampler
  • 加上 Weightmap = 5-6 个 Sampler
  • 大幅减少 Sampler 使用

  ┌──────────────────────────────────────────────────┐
  │  Texture2DArray: DiffuseArray                    │
  │  ┌─────┬─────┬─────┬─────┬─────┬─────┬─────┐    │
  │  │ [0] │ [1] │ [2] │ [3] │ [4] │ [5] │ [6] │    │
  │  │Grass│Dirt │Rock │Sand │Snow │Road │Mud  │    │
  │  └─────┴─────┴─────┴─────┴─────┴─────┴─────┘    │
  │                                                  │
  │  采样: DiffuseArray.Sample(UV, LayerIndex)        │
  └──────────────────────────────────────────────────┘

  约束：
  • 所有纹理必须相同分辨率和格式
  • 不支持独立的 Mip 设置
  • UE5 中推荐使用 Landscape Layer Coords 节点
```

### 4.3 材质复杂度与 Shader 变体

```
═══ Shader 变体爆炸问题 ═══

  Landscape 材质会根据 Component 使用的层组合生成不同的 Shader 变体：

  Component A 使用: Grass + Dirt + Rock     → Shader Variant 1
  Component B 使用: Grass + Sand + Snow     → Shader Variant 2
  Component C 使用: Dirt + Rock + Road      → Shader Variant 3

  8 层材质的理论组合数: C(8,3) = 56 种变体（假设每个 Component 最多 3 层）

═══ 优化策略 ═══

  1. 限制每个 Component 的最大层数
     • 默认最多 3 层/Component（可配置）
     • 超过限制的层会被忽略
     • 在 Landscape 属性中设置: Max Painted Layers Per Component

  2. 使用 Shared Wrap Material
     • 所有 Component 使用相同的 Shader
     • 通过 Weightmap 动态选择层
     • 减少变体但增加 Shader 复杂度

  3. 使用 RVT（Runtime Virtual Texture）
     • 将材质混合结果烘焙到 VT
     • 运行时只采样 VT，不做实时混合
     • 大幅降低 Pixel Shader 开销
```

### 4.4 距离混合与 Macro Variation

```
═══ 近景 Tiling 问题 ═══

  地形纹理在近处会出现明显的重复 Tiling
  解决方案：

  1. Detail Texture（近景细节）
     • 额外的高频细节纹理
     • 只在近距离可见
     • 与基础纹理相乘

  2. Distance Blend（远景简化）
     • 远处使用低频 Macro 纹理
     • 近处使用高频 Detail 纹理
     • 基于距离 lerp

═══ Macro Variation（宏观变化）═══

  解决远景 Tiling 重复感：

  ┌──────────────────────────────────────────────────┐
  │  方法 1: Macro Texture                           │
  │  • 覆盖整个地形的低分辨率纹理                     │
  │  • 与 Tiling 纹理相乘                            │
  │  • 打破重复感                                    │
  │                                                  │
  │  方法 2: World-Space Noise                       │
  │  • 基于世界坐标的噪声函数                         │
  │  • 调制颜色/亮度                                  │
  │  • 无额外纹理开销                                │
  │                                                  │
  │  方法 3: Stochastic Tiling                       │
  │  • 随机旋转/偏移 UV                              │
  │  • 消除规律性重复                                │
  │  • 需要额外的 Shader 计算                        │
  └──────────────────────────────────────────────────┘
```

---

## 5. Virtual Texture（VT）

### 5.1 Runtime Virtual Texture 原理

```
═══ RVT 核心概念 ═══

  Runtime Virtual Texture（RVT）是 UE4.23+ 引入的技术
  将复杂材质的渲染结果缓存到虚拟纹理中

  ┌─────────────────────────────────────────────────────────┐
  │                                                         │
  │  传统方式：                                              │
  │  每帧 → 采样 N 层纹理 → 混合 → 输出                     │
  │  开销: N × (Diffuse + Normal + ORM) 次采样/像素          │
  │                                                         │
  │  RVT 方式：                                              │
  │  预渲染 → 混合结果写入 VT Cache → 运行时只采样 Cache     │
  │  开销: 1 次 VT 采样/像素（+ 偶尔的 Cache Miss 更新）     │
  │                                                         │
  └─────────────────────────────────────────────────────────┘

═══ RVT 工作流程 ═══

  ┌──────────┐    ┌──────────────┐    ┌──────────────┐
  │ 相机移动  │ →  │ 确定可见 Page │ →  │ 检查 Cache   │
  └──────────┘    └──────────────┘    └──────┬───────┘
                                            │
                                    ┌───────┴───────┐
                                    │               │
                                ┌───▼───┐     ┌────▼────┐
                                │ Cache │     │ Cache   │
                                │ Hit   │     │ Miss    │
                                └───┬───┘     └────┬────┘
                                    │              │
                                    │         ┌────▼────────┐
                                    │         │ 渲染该 Page  │
                                    │         │ 到 VT Cache  │
                                    │         └────┬────────┘
                                    │              │
                                ┌───▼──────────────▼───┐
                                │  采样 VT Cache 渲染   │
                                └──────────────────────┘
```

### 5.2 RVT 在地形中的应用

```
═══ 地形 RVT 配置 ═══

  1. 创建 Runtime Virtual Texture Asset
     • Material Type: Base Color + Normal + Roughness + Specular
     • Size: 通常 8192 × 8192 或更大
     • Tile Size: 128 或 256

  2. 放置 Runtime Virtual Texture Volume
     • 覆盖整个地形区域
     • 设置合适的高度范围

  3. 地形材质中输出到 RVT
     • 使用 "Runtime Virtual Texture Output" 节点
     • 将混合后的材质属性输出到 RVT

  4. 其他物体（如 Mesh）采样 RVT
     • 使用 "Runtime Virtual Texture Sample" 节点
     • 实现地形-物体颜色融合

═══ RVT 的典型用途 ═══

  ┌──────────────────────────────────────────────────┐
  │  1. 降低地形材质开销                              │
  │     • 8 层混合 → 1 次 VT 采样                    │
  │     • Pixel Shader 指令数大幅减少                 │
  │                                                  │
  │  2. 物体与地形融合                                │
  │     • 岩石底部与地形颜色混合                      │
  │     • 建筑地基与地面过渡                          │
  │     • 无需手动绘制 Decal                          │
  │                                                  │
  │  3. 远景材质简化                                  │
  │     • 远处使用 RVT 低 Mip                        │
  │     • 近处使用完整材质                            │
  │     • 基于距离自动切换                            │
  └──────────────────────────────────────────────────┘
```

### 5.3 Streaming Virtual Texture

```
═══ SVT vs RVT ═══

  ┌──────────────────┬──────────────────┬──────────────────┐
  │  特性             │  RVT             │  SVT             │
  ├──────────────────┼──────────────────┼──────────────────┤
  │  数据来源         │  运行时渲染       │  磁盘预烘焙      │
  │  更新频率         │  每帧按需更新     │  流式加载        │
  │  GPU 开销         │  Cache Miss 时高 │  低（只有采样）   │
  │  磁盘占用         │  无              │  大              │
  │  动态内容         │  支持            │  不支持          │
  │  典型用途         │  地形材质混合     │  Lightmap/大纹理 │
  └──────────────────┴──────────────────┴──────────────────┘

  UE5 中 SVT 用于：
  • Virtual Texture Lightmap
  • 超大纹理的流式加载
  • Nanite 的 Virtual Texture 集成
```

### 5.4 VT 性能分析

```
  ┌──────────────────────────────────────────────────────────┐
  │  RVT 性能关键指标                                        │
  │                                                          │
  │  • Page Fault Rate:  Cache Miss 频率                     │
  │    理想: < 5% per frame                                  │
  │    过高原因: VT 分辨率不足 / Cache 太小 / 相机移动太快    │
  │                                                          │
  │  • Cache Size:  VT 物理缓存大小                          │
  │    默认: 4096 × 4096                                     │
  │    增大可减少 Page Fault 但增加内存                       │
  │                                                          │
  │  • Feedback Buffer:  反馈缓冲区分辨率                    │
  │    默认: 屏幕分辨率 / 16                                 │
  │    影响 Page 请求的精度                                  │
  │                                                          │
  │  调试命令：                                               │
  │  • r.VT.Borders 1           - 显示 VT Page 边界          │
  │  • r.VT.PageFaultWarning 1  - Page Fault 警告            │
  │  • stat virtualtexturing    - VT 性能统计                │
  └──────────────────────────────────────────────────────────┘
```

---

## 6. World Partition 与大世界

### 6.1 World Partition 架构

```
═══ UE5 World Partition 概述 ═══

  替代 UE4 的 World Composition / Level Streaming
  自动将世界划分为网格单元，按需加载

  ┌─────────────────────────────────────────────────────────┐
  │                                                         │
  │  World Partition Grid                                   │
  │  ┌─────┬─────┬─────┬─────┬─────┐                       │
  │  │     │     │ ██  │     │     │  ██ = 已加载           │
  │  ├─────┼─────┼─────┼─────┼─────┤                       │
  │  │     │ ██  │ ██  │ ██  │     │  □  = 未加载           │
  │  ├─────┼─────┼─────┼─────┼─────┤                       │
  │  │     │ ██  │ ⊕█  │ ██  │     │  ⊕  = 玩家位置        │
  │  ├─────┼─────┼─────┼─────┼─────┤                       │
  │  │     │ ██  │ ██  │ ██  │     │                       │
  │  ├─────┼─────┼─────┼─────┼─────┤                       │
  │  │     │     │ ██  │     │     │                       │
  │  └─────┴─────┴─────┴─────┴─────┘                       │
  │                                                         │
  │  加载半径由 Streaming Source 和 Grid 设置决定             │
  │                                                         │
  └─────────────────────────────────────────────────────────┘
```

### 6.2 Landscape Streaming Proxy

```
═══ 地形与 World Partition 集成 ═══

  启用 World Partition 后：
  • ALandscape 被自动拆分为多个 ALandscapeStreamingProxy
  • 每个 Proxy 包含若干 LandscapeComponent
  • Proxy 按 World Partition Grid 进行流式加载/卸载

  ┌─────────────────────────────────────────────────────────┐
  │  ALandscape (主 Actor，始终存在)                          │
  │  │                                                      │
  │  ├── ALandscapeStreamingProxy_0 (Grid Cell 0)           │
  │  │   ├── ULandscapeComponent_0                          │
  │  │   ├── ULandscapeComponent_1                          │
  │  │   └── ULandscapeComponent_2                          │
  │  │                                                      │
  │  ├── ALandscapeStreamingProxy_1 (Grid Cell 1)           │
  │  │   ├── ULandscapeComponent_3                          │
  │  │   └── ULandscapeComponent_4                          │
  │  │                                                      │
  │  └── ... (按需加载/卸载)                                 │
  └─────────────────────────────────────────────────────────┘

  注意事项：
  • 相邻 Proxy 的边界 Component 需要同时加载以避免缝隙
  • Heightmap/Weightmap 在边界处共享
  • LOD 在 Proxy 边界处需要正确缝合
```

### 6.3 HLOD 与地形

```
═══ Landscape HLOD ═══

  UE5 支持为地形生成 HLOD（Hierarchical LOD）：

  ┌──────────────────────────────────────────────────┐
  │  近处: 完整 Landscape Component（正常 LOD）       │
  │        ↓ 距离增加                                │
  │  中距: Landscape LOD 5-6（最低 LOD）             │
  │        ↓ 距离继续增加                            │
  │  远处: HLOD Mesh（简化的静态网格）               │
  │        • 预烘焙的低模                            │
  │        • 包含 RVT 采样的材质                     │
  │        • 极低的 Draw Call 和顶点数               │
  └──────────────────────────────────────────────────┘

  HLOD 生成设置：
  • HLOD Layer: 指定 HLOD 生成策略
  • Mesh Simplification: 简化比例
  • Material: 可使用 RVT 采样材质
```

### 6.4 Data Layer

```
═══ Data Layer 与地形 ═══

  Data Layer 允许同一区域有多个版本的地形：

  • 季节变化: 夏季地形 / 冬季地形
  • 任务状态: 战前地形 / 战后地形（弹坑等）
  • 多人模式: 不同阵营看到不同地形

  实现：
  • 每个 Data Layer 可以有独立的 Landscape Proxy
  • 运行时根据条件激活/停用 Data Layer
  • 共享底层 Heightmap，只覆盖差异部分
```

---

## 7. 地形物理与碰撞

### 7.1 碰撞数据生成

```
═══ Heightfield Collision ═══

  Unreal 使用 PhysX/Chaos 的 Heightfield Shape 进行地形碰撞：

  ┌──────────────────────────────────────────────────────────┐
  │  ULandscapeHeightfieldCollisionComponent                 │
  │                                                          │
  │  • 从 Heightmap 生成碰撞高度场                           │
  │  • 碰撞分辨率可独立于渲染分辨率                           │
  │  • Collision Mip Level: 碰撞使用的 LOD 级别              │
  │    - 0 = 与渲染相同精度                                  │
  │    - 1 = 1/2 精度                                       │
  │    - 2 = 1/4 精度                                       │
  │                                                          │
  │  Simple Collision Mip Level:                             │
  │  • 用于简单碰撞查询（如 Overlap）                        │
  │  • 通常设置更高的 Mip（更粗糙）                          │
  └──────────────────────────────────────────────────────────┘

  内存占用：
  • 碰撞数据 = ComponentSize² × sizeof(uint16) per Component
  • 4km × 4km, 1m 分辨率: 4096² × 2 = 32 MB
  • Collision Mip 1: 2048² × 2 = 8 MB（节省 75%）
```

### 7.2 Physical Material 映射

```
═══ 每层物理材质 ═══

  每个 Landscape Layer 可以关联一个 Physical Material：

  ┌──────────────────────────────────────────────────┐
  │  Layer "Grass"  → PM_Grass  (摩擦 0.8, 弹性 0.2)│
  │  Layer "Rock"   → PM_Rock   (摩擦 0.6, 弹性 0.4)│
  │  Layer "Sand"   → PM_Sand   (摩擦 0.9, 弹性 0.1)│
  │  Layer "Water"  → PM_Water  (摩擦 0.1, 弹性 0.0)│
  └──────────────────────────────────────────────────┘

  运行时查询：
  • Line Trace 返回 Hit Result
  • Hit Result 包含 Physical Material
  • 用于：脚步声、粒子效果、车辆物理等

  ```cpp
  // Query physical material at hit point
  FHitResult Hit;
  if (GetWorld()->LineTraceSingleByChannel(Hit, Start, End, ECC_Visibility))
  {
      UPhysicalMaterial* PhysMat = Hit.PhysMaterial.Get();
      if (PhysMat)
      {
          // Use PhysMat->SurfaceType for gameplay logic
          EPhysicalSurface Surface = PhysMat->SurfaceType;
      }
  }
  ```
```

### 7.3 碰撞性能优化

```
  ┌──────────────────────────────────────────────────────────┐
  │  优化策略                                                │
  │                                                          │
  │  1. 提高 Collision Mip Level                             │
  │     • 大多数游戏 Mip 1-2 足够                            │
  │     • 角色脚步不需要 cm 级精度                           │
  │                                                          │
  │  2. 使用 Simple Collision 替代 Complex                   │
  │     • Overlap 查询使用 Simple                            │
  │     • 只有精确射线检测使用 Complex                       │
  │                                                          │
  │  3. 碰撞通道优化                                         │
  │     • 地形只响应必要的碰撞通道                           │
  │     • 禁用不需要的 Object Type 响应                      │
  │                                                          │
  │  4. 异步碰撞查询                                         │
  │     • 大量射线检测使用 AsyncLineTrace                    │
  │     • 避免主线程阻塞                                     │
  └──────────────────────────────────────────────────────────┘
```

---

## 8. 地形植被（Foliage）集成

### 8.1 Procedural Foliage

```
═══ Procedural Foliage Spawner ═══

  基于规则自动生成植被分布：

  ┌──────────────────────────────────────────────────────────┐
  │  FProceduralFoliageInstance                              │
  │                                                          │
  │  规则参数：                                               │
  │  • Seed Density:     种子密度                             │
  │  • Initial Seed:     初始种子数                           │
  │  • Max Age:          最大生长年龄                         │
  │  • Spread Distance:  扩散距离                             │
  │  • Shade Tolerance:  遮挡容忍度                           │
  │  • Overlap Priority: 重叠优先级                           │
  │                                                          │
  │  生成流程：                                               │
  │  1. 在 Volume 内随机撒种子                                │
  │  2. 模拟生长（年龄递增）                                  │
  │  3. 竞争淘汰（遮挡、重叠）                                │
  │  4. 最终存活的实例放置到地形上                            │
  └──────────────────────────────────────────────────────────┘
```

### 8.2 Grass System

```
═══ Landscape Grass Type ═══

  基于地形 Weightmap 自动生成草地：

  ┌──────────────────────────────────────────────────────────┐
  │  ULandscapeGrassType                                     │
  │                                                          │
  │  • 绑定到 Landscape Material 的特定层                    │
  │  • 根据权重值自动生成草地实例                             │
  │  • 使用 Hierarchical Instanced Static Mesh（HISM）       │
  │  • 支持 LOD 和距离剔除                                   │
  │                                                          │
  │  关键参数：                                               │
  │  • Grass Density:      每平方米草的数量                   │
  │  • Start/End Cull Distance: 渲染距离范围                  │
  │  • Min/Max LOD:        LOD 范围                          │
  │  • Random Rotation:    随机旋转                          │
  │  • Align To Surface:   对齐地表法线                      │
  │  • Use Landscape Lightmap: 使用地形光照图                │
  │                                                          │
  │  性能特点：                                               │
  │  • 不持久化存储（运行时动态生成）                         │
  │  • 基于相机位置流式生成/销毁                              │
  │  • 使用 GPU Instancing 渲染                              │
  │  • 内存占用低（只存储规则，不存储实例）                   │
  └──────────────────────────────────────────────────────────┘
```

### 8.3 Nanite Foliage

```
═══ UE5 Nanite 植被 ═══

  UE5.0+: Nanite 支持 Foliage（有限制）
  UE5.1+: 改进的 Nanite Foliage 支持
  UE5.3+: Nanite Landscape + Nanite Foliage 完整集成

  优势：
  • 自动 LOD，无需手动制作 LOD 链
  • 支持百万级植被实例
  • 像素级剔除

  限制：
  • 不支持 World Position Offset（WPO）用于风动画
    → UE5.4+ 部分支持 Nanite WPO
  • 不支持 Masked 材质（Alpha Test）
    → UE5.1+ 支持 Nanite Masked
  • 增加 GPU 内存占用
```

---

## 9. 地形编辑工具

### 9.1 Sculpt / Paint 工具

```
═══ Sculpt 模式 ═══

  ┌──────────────────────────────────────────────────┐
  │  工具              │ 功能                        │
  ├──────────────────────────────────────────────────┤
  │  Sculpt            │ 自由雕刻高度                │
  │  Smooth            │ 平滑地形                    │
  │  Flatten           │ 压平到指定高度              │
  │  Erosion           │ 模拟侵蚀效果                │
  │  Hydro Erosion     │ 水力侵蚀                    │
  │  Noise             │ 噪声扰动                    │
  │  Retopologize      │ 重新拓扑                    │
  │  Mirror            │ 镜像编辑                    │
  └──────────────────────────────────────────────────┘

═══ Paint 模式 ═══

  • 绘制 Weightmap 权重
  • 支持 Brush Falloff 曲线
  • 支持 Brush Alpha（自定义笔刷形状）
  • Target Layer 选择
```

### 9.2 Landscape Spline

```
═══ Spline 系统 ═══

  用于在地形上创建道路、河流等线性结构：

  ┌──────────────────────────────────────────────────────────┐
  │  ULandscapeSplineComponent                               │
  │                                                          │
  │  功能：                                                   │
  │  • 沿 Spline 变形地形高度                                │
  │  • 沿 Spline 绘制材质层                                  │
  │  • 沿 Spline 放置 Mesh（护栏、路灯等）                   │
  │  • 支持交叉路口处理                                      │
  │                                                          │
  │  参数：                                                   │
  │  • Width:           道路宽度                              │
  │  • Side Falloff:    边缘衰减                              │
  │  • Raise/Lower Terrain: 抬升/降低地形                    │
  │  • Paint Layer:     绘制的材质层                          │
  └──────────────────────────────────────────────────────────┘
```

### 9.3 Blueprint Brush

```
═══ Landscape Blueprint Brush (UE5) ═══

  使用 Blueprint 或 C++ 程序化编辑地形：

  ```cpp
  // Custom Landscape Brush
  UCLASS()
  class ALandscapeBlueprintBrush : public ALandscapeBlueprintBrushBase
  {
      GENERATED_BODY()
  public:
      virtual UTextureRenderTarget2D* Render_Native(
          bool InIsHeightmap,
          UTextureRenderTarget2D* InCombinedResult,
          const FName& InWeightmapLayerName) override;
  };
  ```

  用途：
  • 程序化地形生成（噪声、分形）
  • 运行时地形修改（爆炸弹坑）
  • 基于规则的地形编辑（河流侵蚀模拟）
```

### 9.4 外部工具导入

```
═══ 常用外部地形工具 ═══

  ┌──────────────────┬──────────────────────────────────────┐
  │  工具             │ 特点                                 │
  ├──────────────────┼──────────────────────────────────────┤
  │  World Machine   │ 节点式地形生成，侵蚀模拟强           │
  │  Gaea            │ 现代 UI，GPU 加速，实时预览          │
  │  Houdini         │ 程序化生成，与 UE 深度集成           │
  │  World Creator   │ 实时地形雕刻，VR 支持                │
  │  Terragen        │ 超写实地形渲染                       │
  └──────────────────┴──────────────────────────────────────┘

  导入格式：
  • Heightmap: R16 PNG / RAW (16-bit grayscale)
  • Weightmap: R8 PNG per layer
  • 分辨率必须匹配 Landscape 配置

  推荐分辨率公式：
  Resolution = (ComponentSize × NumComponents) + 1
  例: 63 × 64 + 1 = 4033 → 使用 4033 × 4033

  ⚠️ Unreal 对 Heightmap 分辨率有严格要求：
  • 必须是 (N × ComponentQuadSize) + 1
  • 不匹配会导致导入失败或拉伸
```

---

## 10. 渲染管线集成

### 10.1 地形在 Deferred 管线中的位置

```
═══ 渲染顺序 ═══

  ┌──────────────────────────────────────────────────────────┐
  │  1. PrePass (Depth Only)                                 │
  │     └── Landscape Depth                                  │
  │                                                          │
  │  2. Base Pass (GBuffer)                                  │
  │     └── Landscape GBuffer                                │
  │         • Diffuse → GBufferA                             │
  │         • Normal → GBufferB                              │
  │         • Metallic/Specular/Roughness → GBufferC         │
  │                                                          │
  │  3. Shadow Depth Pass                                    │
  │     └── Landscape Shadow Maps                            │
  │                                                          │
  │  4. Lighting Pass                                        │
  │     └── 使用 GBuffer 数据计算光照                        │
  │                                                          │
  │  5. RVT Update (if needed)                               │
  │     └── 更新 Cache Miss 的 VT Page                       │
  └──────────────────────────────────────────────────────────┘
```

### 10.2 Nanite Landscape（UE5.2+）

```
═══ Nanite Landscape 原理 ═══

  UE5.2 引入 Nanite 对 Landscape 的支持：

  ┌──────────────────────────────────────────────────────────┐
  │  传统 Landscape:                                         │
  │  • 固定网格拓扑                                          │
  │  • 基于距离的 LOD                                        │
  │  • 每个 Component 一个 Draw Call                         │
  │                                                          │
  │  Nanite Landscape:                                       │
  │  • Nanite 虚拟几何体                                     │
  │  • 像素级 LOD（屏幕空间误差驱动）                        │
  │  • GPU Driven 渲染（极少 Draw Call）                     │
  │  • 自动处理 LOD 过渡和缝合                               │
  │                                                          │
  │  启用方式：                                               │
  │  Landscape Actor → Details → Nanite → Enable Nanite      │
  │                                                          │
  │  限制：                                                   │
  │  • 不支持运行时地形修改                                  │
  │  • 不支持 Landscape Spline 变形                          │
  │  • 材质必须兼容 Nanite                                   │
  │  • 增加 GPU 内存占用                                     │
  └──────────────────────────────────────────────────────────┘

  性能对比（8km × 8km 地形）：
  ┌──────────────────┬──────────────────┬──────────────────┐
  │  指标             │  传统 Landscape  │  Nanite Landscape│
  ├──────────────────┼──────────────────┼──────────────────┤
  │  Draw Call        │  200-500         │  1-5             │
  │  三角形数         │  固定（LOD 决定）│  自适应          │
  │  LOD Popping      │  可能            │  无              │
  │  GPU 内存         │  低              │  中-高           │
  │  CPU 开销         │  中              │  极低            │
  └──────────────────┴──────────────────┴──────────────────┘
```

### 10.3 Lumen 与地形 GI

```
═══ Lumen 对地形的处理 ═══

  ┌──────────────────────────────────────────────────────────┐
  │  Screen Space Trace:                                     │
  │  • 地形参与屏幕空间光线追踪                              │
  │  • 提供近距离 GI 反弹                                    │
  │                                                          │
  │  Surface Cache:                                          │
  │  • 地形的 Surface Cache 使用 RVT 数据                    │
  │  • 减少实时材质计算                                      │
  │                                                          │
  │  Distance Field:                                         │
  │  • 地形生成 Heightfield Distance Field                   │
  │  • 用于远距离 GI 和 AO                                   │
  │  • 比 Mesh Distance Field 更高效                         │
  │                                                          │
  │  注意事项：                                               │
  │  • 大面积地形的 Surface Cache 更新开销较大                │
  │  • 建议配合 RVT 使用以减少开销                           │
  │  • Lumen Scene 中地形的 Card 生成策略不同于普通 Mesh      │
  └──────────────────────────────────────────────────────────┘
```

### 10.4 Shadow 与地形

```
═══ 地形阴影优化 ═══

  ┌──────────────────────────────────────────────────────────┐
  │  1. Cascaded Shadow Map (CSM)                            │
  │     • 地形是 CSM 的主要消费者                             │
  │     • 每个 Cascade 都需要渲染地形 Depth                  │
  │     • 优化: 使用 Far Shadow（独立的远距离阴影 Cascade）   │
  │                                                          │
  │  2. Far Shadow                                           │
  │     • 专门为地形和大型物体设计                            │
  │     • 独立于 CSM 的远距离阴影                            │
  │     • 更新频率可以降低                                   │
  │     • 启用: Landscape → Cast Far Shadow = true            │
  │                                                          │
  │  3. Virtual Shadow Map (UE5)                             │
  │     • 替代 CSM 的新方案                                  │
  │     • 基于 Page 的虚拟阴影图                             │
  │     • 只更新变化的区域                                   │
  │     • 与 Nanite 深度集成                                 │
  │                                                          │
  │  4. Self-Shadow                                          │
  │     • 地形自阴影对山脉/悬崖很重要                        │
  │     • 可通过 Contact Shadow 增强近距离细节               │
  └──────────────────────────────────────────────────────────┘
```

---

## 11. 性能优化

### 11.1 Draw Call 优化

```
  ┌──────────────────────────────────────────────────────────┐
  │  地形 Draw Call = 可见 Component 数 × Pass 数             │
  │                                                          │
  │  减少 Draw Call 的方法：                                  │
  │                                                          │
  │  1. 增大 Component 尺寸                                  │
  │     • 更大的 Section Size → 更少的 Component              │
  │     • 权衡: LOD 粒度降低                                 │
  │                                                          │
  │  2. 使用 Nanite Landscape（UE5.2+）                      │
  │     • GPU Driven → 极少 Draw Call                        │
  │                                                          │
  │  3. 优化 Occlusion Culling                               │
  │     • 确保遮挡剔除正常工作                               │
  │     • 山脉后面的 Component 应被剔除                      │
  │                                                          │
  │  4. 减少 Pass 数                                         │
  │     • 避免不必要的 Custom Depth Pass                     │
  │     • 优化阴影 Cascade 数量                              │
  │                                                          │
  │  典型数据：                                               │
  │  • 4km × 4km, 63×63 Section, 2×2 Section/Comp           │
  │  • Component 数: ~1024                                   │
  │  • 可见 Component: ~200-400（视角依赖）                  │
  │  • Base Pass Draw Call: 200-400                          │
  │  • + Shadow Pass: ×3-4 Cascade = 600-1600                │
  │  • 总计: 800-2000 Draw Call（仅地形）                    │
  └──────────────────────────────────────────────────────────┘
```

### 11.2 内存优化

```
  ┌──────────────────────────────────────────────────────────┐
  │  地形内存组成                                             │
  │                                                          │
  │  ┌────────────────────────┬──────────┬──────────────────┐│
  │  │  数据类型               │ 大小估算  │ 优化方法         ││
  │  ├────────────────────────┼──────────┼──────────────────┤│
  │  │  Heightmap Texture     │ 64 MB    │ 压缩/Streaming   ││
  │  │  Weightmap Texture     │ 128 MB   │ 减少层数         ││
  │  │  Collision Data        │ 32 MB    │ 提高 Collision   ││
  │  │                        │          │ Mip Level        ││
  │  │  Vertex Buffer         │ 16 MB    │ LOD 减少         ││
  │  │  Index Buffer          │ 8 MB     │ 共享 IB          ││
  │  │  Material Textures     │ 变化大   │ VT / 压缩        ││
  │  │  Grass Instance Data   │ 变化大   │ 减少密度/距离    ││
  │  ├────────────────────────┼──────────┼──────────────────┤│
  │  │  总计（4km²，8层）     │ ~250 MB  │                  ││
  │  └────────────────────────┴──────────┴──────────────────┘│
  │                                                          │
  │  关键优化：                                               │
  │  • Texture Streaming: 远处使用低 Mip                     │
  │  • World Partition: 只加载可见区域                        │
  │  • Shared Index Buffer: 相同 LOD 的 Section 共享 IB      │
  │  • Collision Mip: 降低碰撞精度                           │
  └──────────────────────────────────────────────────────────┘
```

### 11.3 GPU 性能优化

```
  ┌──────────────────────────────────────────────────────────┐
  │  GPU 瓶颈分析                                            │
  │                                                          │
  │  1. Vertex Shader 瓶颈                                   │
  │     • 症状: 大量顶点处理                                 │
  │     • 优化: 调整 LOD 参数，减少近处 LOD 0 范围           │
  │                                                          │
  │  2. Pixel Shader 瓶颈（最常见）                          │
  │     • 症状: 多层材质混合开销大                           │
  │     • 优化:                                              │
  │       - 使用 RVT 缓存混合结果                            │
  │       - 减少每 Component 的层数                          │
  │       - 简化远处材质                                     │
  │       - 使用 Texture Array 减少采样次数                  │
  │                                                          │
  │  3. 带宽瓶颈                                             │
  │     • 症状: 大量纹理采样                                 │
  │     • 优化:                                              │
  │       - 使用纹理压缩（BC/ASTC）                          │
  │       - 减少纹理分辨率                                   │
  │       - VT 减少采样数                                    │
  │                                                          │
  │  4. Overdraw                                             │
  │     • 地形通常 Overdraw 较低（不透明）                   │
  │     • 但草地 Alpha Test 会导致严重 Overdraw              │
  │     • 优化: 草地使用 Dithered LOD Transition             │
  └──────────────────────────────────────────────────────────┘
```

### 11.4 Streaming 优化

```
  ┌──────────────────────────────────────────────────────────┐
  │  World Partition Streaming 调优                           │
  │                                                          │
  │  • Grid Cell Size:                                       │
  │    - 太小: 频繁加载/卸载，IO 压力大                      │
  │    - 太大: 内存浪费，加载延迟高                          │
  │    - 推荐: 256m - 512m                                   │
  │                                                          │
  │  • Loading Range:                                        │
  │    - 根据移动速度调整                                    │
  │    - 步行: 2-3 个 Cell                                   │
  │    - 载具: 4-6 个 Cell                                   │
  │                                                          │
  │  • Async Loading:                                        │
  │    - 使用异步加载避免卡顿                                │
  │    - 设置加载优先级                                      │
  │    - 预加载移动方向的 Cell                               │
  │                                                          │
  │  • IO 优化:                                              │
  │    - 使用 Pak 文件减少 IO 次数                           │
  │    - 启用 IO Store（UE5）                                │
  │    - SSD 推荐                                            │
  └──────────────────────────────────────────────────────────┘
```

### 11.5 移动端适配

```
  ┌──────────────────────────────────────────────────────────┐
  │  移动端地形优化清单                                       │
  │                                                          │
  │  几何：                                                   │
  │  □ 降低 Section Size（31×31 或 15×15）                   │
  │  □ 提高最低 LOD 级别                                     │
  │  □ 减少可见距离                                          │
  │                                                          │
  │  材质：                                                   │
  │  □ 限制最多 3-4 层                                       │
  │  □ 使用 ASTC 纹理压缩                                   │
  │  □ 简化 Shader（去掉 Parallax/Tessellation）             │
  │  □ 考虑使用 RVT 降低 PS 开销                             │
  │                                                          │
  │  内存：                                                   │
  │  □ 降低 Heightmap/Weightmap 分辨率                       │
  │  □ 提高 Collision Mip Level                              │
  │  □ 减少 Grass 密度和距离                                 │
  │                                                          │
  │  带宽（TBR 架构）：                                       │
  │  □ 减少 GBuffer RT 数量                                  │
  │  □ 使用 16-bit 精度                                      │
  │  □ 避免不必要的 Load/Store                               │
  └──────────────────────────────────────────────────────────┘
```

---

## 12. 面试高频问题

```
═══ Q1: Unreal 地形的 Component / Section / Quad 是什么关系？ ═══

A: 三级层次结构：
• Quad: 最小网格单元（2 个三角形）
• Section: LOD 的最小单位，包含 N×N 个 Quad
• Component: 渲染和碰撞的最小单位，包含 1×1 或 2×2 个 Section

Component 是 Draw Call 的粒度，Section 是 LOD 的粒度。
选择更大的 Section Size 减少 Draw Call 但降低 LOD 精度。

═══ Q2: 地形 LOD 如何避免 Popping 和 T-Junction？ ═══

A:
• Popping: 使用 GPU Morphing，在 Vertex Shader 中平滑过渡
  奇数顶点逐渐 morph 到偶数邻居的中点，MorphFactor 到 1 时安全切换 LOD
• T-Junction: 高 LOD Section 的边界顶点退化到低 LOD 的网格上
  预生成多套 Index Buffer 处理不同的邻接 LOD 组合

═══ Q3: Runtime Virtual Texture 在地形中的作用？ ═══

A:
1. 降低材质开销: 将多层混合结果缓存到 VT，运行时只需 1 次 VT 采样
2. 物体融合: 其他 Mesh 采样地形 RVT 实现颜色融合
3. 远景简化: 远处使用 RVT 低 Mip，近处使用完整材质

工作流程: 相机移动 → 确定可见 Page → Cache Hit 直接采样 / Cache Miss 渲染后缓存

═══ Q4: World Partition 如何管理地形的流式加载？ ═══

A:
• ALandscape 被拆分为多个 ALandscapeStreamingProxy
• 每个 Proxy 包含若干 Component，按 Grid Cell 加载/卸载
• 相邻 Proxy 的边界 Component 需要同时加载以避免缝隙
• 配合 HLOD 在远处使用简化的静态网格替代

═══ Q5: 地形材质层数过多会有什么问题？如何优化？ ═══

A:
问题:
• Shader 变体爆炸（不同 Component 使用不同层组合）
• Texture Sampler 超限（每层 3 个 Sampler × N 层）
• Pixel Shader 指令数增加

优化:
• 限制每 Component 最大层数（3-4 层）
• 使用 Texture Array 减少 Sampler 使用
• 使用 RVT 缓存混合结果
• 远处使用简化材质

═══ Q6: Nanite Landscape 相比传统 Landscape 有什么优势和限制？ ═══

A:
优势:
• GPU Driven 渲染，Draw Call 从数百降到个位数
• 像素级 LOD，无 Popping
• 自动处理 LOD 过渡和缝合
• CPU 开销极低

限制:
• 不支持运行时地形修改
• 不支持 Landscape Spline 变形
• 增加 GPU 内存占用
• 材质必须兼容 Nanite

═══ Q7: 地形的碰撞数据如何优化？ ═══

A:
• 提高 Collision Mip Level（1-2 级通常足够）
• 使用 Simple Collision 替代 Complex（Overlap 查询）
• 优化碰撞通道，禁用不需要的响应
• 大量射线检测使用 AsyncLineTrace
• World Partition 自动卸载远处碰撞数据

═══ Q8: 如何从外部工具（World Machine/Gaea）导入地形？ ═══

A:
• 导出 R16 PNG 或 RAW 格式的 Heightmap
• 分辨率必须匹配: (ComponentQuadSize × NumComponents) + 1
• Weightmap 每层一个 R8 PNG
• 在 Landscape 编辑器中使用 "Import from File"
• 注意坐标系和高度范围的映射

═══ Q9: 地形草地系统（Grass Type）的工作原理？ ═══

A:
• 绑定到 Landscape Material 的特定层
• 根据 Weightmap 权重运行时动态生成实例
• 使用 HISM（Hierarchical Instanced Static Mesh）渲染
• 不持久化存储，基于相机位置流式生成/销毁
• 内存占用低（只存储规则，不存储实例数据）
• 支持 LOD 和距离剔除

═══ Q10: 地形渲染的主要性能瓶颈在哪里？ ═══

A:
1. CPU: Draw Call 数量（Component 数 × Pass 数）
   → Nanite 或增大 Component 尺寸
2. VS: 顶点数量（LOD 0 范围过大）
   → 调整 LOD 参数
3. PS: 多层材质混合（最常见瓶颈）
   → RVT / Texture Array / 减少层数
4. 带宽: 大量纹理采样
   → 纹理压缩 / VT
5. 内存: Heightmap + Weightmap + Collision + Grass
   → Streaming / 降低精度 / 减少层数
```

---

## 13. 实践检查清单

```
═══ 地形创建 ═══
□ 根据场景规模选择合适的 Section Size 和 Sections Per Component
□ 计算总顶点数和 Component 数，评估 Draw Call 预算
□ 确定材质层数上限（建议 ≤ 8 层，每 Component ≤ 4 层）
□ 规划 Heightmap/Weightmap 分辨率和内存预算

═══ 材质设置 ═══
□ 使用 Texture Array 减少 Sampler 使用
□ 配置 RVT 缓存材质混合结果
□ 添加 Macro Variation 打破远景 Tiling
□ 设置 Distance Blend 近远景材质切换
□ 限制 Max Painted Layers Per Component

═══ LOD 调优 ═══
□ 设置合理的 LOD 0 Screen Size
□ 调整 LOD Distribution Setting
□ 验证 Morphing 过渡效果（无 Popping）
□ 检查邻接 LOD 缝合（无 T-Junction）
□ 使用 ShowFlag.LODColoration 可视化验证

═══ World Partition ═══
□ 启用 World Partition 并配置 Grid Cell Size
□ 验证 Landscape Streaming Proxy 正确生成
□ 设置合理的 Loading Range
□ 配置 HLOD 用于远景
□ 测试快速移动时的加载表现

═══ 性能验证 ═══
□ stat landscape 检查地形性能
□ stat virtualtexturing 检查 VT 性能
□ GPU Profiler 检查 PS 开销
□ 内存 Profiler 检查地形内存占用
□ 移动端实机测试帧率和内存

═══ 碰撞与物理 ═══
□ 设置合适的 Collision Mip Level
□ 配置每层 Physical Material
□ 验证 Line Trace 返回正确的 Physical Material
□ 测试碰撞性能（大量角色/载具场景）

═══ 植被集成 ═══
□ 配置 Grass Type 并绑定到材质层
□ 设置合理的 Grass 密度和剔除距离
□ 验证 Procedural Foliage 分布效果
□ 测试植被对帧率的影响
□ 考虑 Nanite Foliage（UE5.3+）
```

---

## 参考资源

```
• Unreal Documentation: Landscape Outdoor Terrain
  https://docs.unrealengine.com/en-US/landscape-outdoor-terrain/

• Unreal Documentation: Virtual Texturing
  https://docs.unrealengine.com/en-US/virtual-texturing/

• Unreal Documentation: World Partition
  https://docs.unrealengine.com/en-US/world-partition/

• GDC 2014: "Landscape in Unreal Engine 4"
• GDC 2019: "Large Worlds in UE4"
• Unreal Fest 2022: "Nanite & Landscape"
• Epic Games: "Building Open Worlds" (Fortnite Case Study)
```