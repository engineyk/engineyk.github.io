### 6.3.1 SnapToLowerLODGrid 实现详解

```
╭─────────────────────────────────────────────────────────╮
│  SnapToLowerLODGrid 功能说明                             │
│                                                         │
│  将 UV 坐标对齐到下一个更低的 LOD 级别网格上               │
│                                                         │
│  为什么需要？                                            │
│  LOD0 → LOD1 时，网格分辨率减半：                         │
│  LOD0: 64×64 网格（每像素间距 = 1/64）                    │
│  LOD1: 32×32 网格（每像素间距 = 1/32）                    │
│                                                         │
│  LOD0 的奇数顶点没有对应的 LOD1 顶点位置                  │
│  需要将奇数顶点对齐到最近的 LOD1 网格点上                  │
╰─────────────────────────────────────────────────────────╯

  UV 坐标对齐过程（LOD0 → LOD1）：
  
  ┌───┬───┬───┬───┬───┐  ← LOD0 网格点
  │ • │ • │ • │ • │ • │
  ├───┼───┼───┼───┼───┤
  │ • │ • │ • │ • │ • │
  ├───┼───┼───┼───┼───┤
  │ • │ • │ • │ • │ • │
  └───┴───┴───┴───┴───┘
  
  LOD0 奇数顶点：
  
  x = 0.2 (0.0~1.0)  →  LOD0 网格坐标：0.2 × 64 = 12.8
  
  LOD1 网格间距 = 1/32 = 0.03125
  
  Snap 到最近的 LOD1 网格点：
  snapped_x = round(0.2 / 0.03125) × 0.03125 ≈ 0.1875
  
  
  ╔══════════════════════════════════════════════╗
  ║  Visual Representation:                      ║
  ║                                              ║
  ║  Original Position (LOD0):  •                ║
  ║  LOD0 Grid:     │   │   │   │   │   │   │    ║
  ║  LOD1 Grid:     │     │     │     │     │    ║
  ║  Snapped Pos (LOD1):          •              ║
  ║                                              ║
  ║  Morph:        • → •                         ║
  ╚══════════════════════════════════════════════╝
```

```c
// SnapToLowerLODGrid 函数实现
// 将 UV 坐标对齐到指定 LOD 级别的网格上
// LOD0: 最高精度 (如 64×64 网格)
// LOD1: 精度减半 (32×32 网格)
// LOD2: 再减半 (16×16 网格)
// 以此类推...

/// <summary>
/// 将 UV 坐标对齐到下一个 LOD 级别的网格上
/// </summary>
/// <param name="uv">原始 UV 坐标 (0.0~1.0)</param>
/// <param name="currentLOD">当前 LOD 级别 (0 = 最高精度)</param>
/// <returns>对齐到下一级 LOD 网格的 UV 坐标</returns>
float2 SnapToLowerLODGrid(float2 uv, int currentLOD)
{
    // 基础网格分辨率（LOD0 的顶点数，如 64）
    int baseGridSize = _BaseGridSize; // 通常 64, 128, 256 等
    
    // 计算当前 LOD 的网格分辨率
    int currentGridSize = baseGridSize >> currentLOD; // 除以 2^LOD
    
    // 计算下一个 LOD 的网格分辨率（更低的精度）
    int nextLOD = currentLOD + 1;
    int nextGridSize = baseGridSize >> nextLOD;
    
    // 当前 LOD 的网格间距（网格点间的 UV 距离）
    float currentGridSpacing = 1.0 / (currentGridSize - 1);
    
    // 下一个 LOD 的网格间距（更大间距）
    float nextGridSpacing = 1.0 / (nextGridSize - 1);
    
    // 将 UV 转换到当前 LOD 的网格坐标
    float2 gridCoord = uv / currentGridSpacing;
    
    // 计算在下一个 LOD 网格上的最近网格点
    // 注意：LOD0 的奇数网格点会映射到 LOD1 的整数网格点
    float2 snappedGridCoord = round(gridCoord * 0.5) * 2.0;
    
    // 将网格坐标转回 UV 空间
    float2 snappedUV = snappedGridCoord * currentGridSpacing;
    
    // 可选：再对齐到下一个 LOD 的精确网格点，确保完全匹配
    // 这可以修复因浮点误差导致的微小偏移
    snappedUV = round(snappedUV / nextGridSpacing) * nextGridSpacing;
    
    // 确保 UV 在有效范围内 [0, 1]
    snappedUV = clamp(snappedUV, 0.0, 1.0);
    
    return snappedUV;
}

// 更高效的实现（使用位运算，避免浮点误差）
float2 SnapToLowerLODGrid_Fast(float2 uv, int currentLOD, int baseGridSize)
{
    // 将 UV 转换到固定精度整数表示
    // 使用 16.16 定点数或直接使用整数运算
    
    int maxCoord = (baseGridSize - 1) << 16; // 使用 16 位小数精度
    
    // UV → 定点数坐标
    int2 coord;
    coord.x = (int)(uv.x * maxCoord + 0.5f);
    coord.y = (int)(uv.y * maxCoord + 0.5f);
    
    // 计算当前 LOD 的掩码（保留高位的位）
    int mask = ~((1 << (16 + currentLOD)) - 1);
    
    // 清除低位，相当于对齐到下一级 LOD 网格
    int2 snappedCoord;
    snappedCoord.x = coord.x & mask;
    snappedCoord.y = coord.y & mask;
    
    // 定点数 → UV
    float2 snappedUV;
    snappedUV.x = (float)snappedCoord.x / maxCoord;
    snappedUV.y = (float)snappedCoord.y / maxCoord;
    
    return snappedUV;
}

// 简化的实现（只考虑 LOD0 → LOD1 的情况）
float2 SnapToLowerLODGrid_Simple(float2 uv, int currentLOD)
{
    // 假设基础网格是 2^N 的尺寸（如 64, 128, 256...）
    
    if (currentLOD == 0) // LOD0 → LOD1
    {
        // LOD0 有奇数顶点，需要对齐到 LOD1 的网格点
        
        // 计算 LOD1 的网格间距（LOD0 的两倍）
        float lod1Spacing = 2.0 / (_BaseGridSize - 1);
        
        // 对齐到最近的 LOD1 网格点
        float2 snapped;
        snapped.x = round(uv.x / lod1Spacing) * lod1Spacing;
        snapped.y = round(uv.y / lod1Spacing) * lod1Spacing;
        
        return clamp(snapped, 0.0, 1.0);
    }
    else if (currentLOD == 1) // LOD1 → LOD2
    {
        float lod2Spacing = 4.0 / (_BaseGridSize - 1);
        float2 snapped;
        snapped.x = round(uv.x / lod2Spacing) * lod2Spacing;
        snapped.y = round(uv.y / lod2Spacing) * lod2Spacing;
        
        return clamp(snapped, 0.0, 1.0);
    }
    
    // 更高的 LOD 依此类推...
    return uv;
}
```

### 6.3.2 Morphing 工作原理详解

```
╔══════════════════════════════════════════════╗
║  Vertex Morphing 数学原理                     ║
║                                              ║
║  Morph 因子计算：                             ║
║  morph = saturate((d - d0) / (d1 - d0))      ║
║  d: 当前距离到相机的距离                       ║
║  d0: LOD 开始过渡的距离                       ║
║  d1: LOD 完成过渡的距离                       ║
║                                              ║
║  d < d0:   morph = 0.0  → 保持当前 LOD        ║
║  d > d1:   morph = 1.0  → 完全使用下一 LOD    ║
║  d0 ~ d1:   morph 0→1 平滑过渡                ║
╚══════════════════════════════════════════════╝

  过渡区域示意图：
  
  相机距离 d
  ↑
  │
  d1 ────┐  ← LOD1 完全生效（低精度）
         │
         │ 过渡区（d0~d1）
         │  morph 从 0 → 1
  d0 ────┘  ← LOD0 完全生效（高精度）
  │
  └──────→ 位置
  
  为什么要有过渡区？
  • 避免 LOD 切换时的突变（pop-in）
  • 平滑的视觉效果
  • 减少视觉上的"跳跃感"
  
  典型过渡区宽度：
  • 10~20% 的 LOD 距离范围
  • 如 d0=80m, d1=100m，过渡区=20m
  
  ╔══════════════════════════════════════════════╗
  ║  Morphing 在 GPU 中的计算成本                 ║
  ║                                              ║
  ║  ✅ 优点：                                   ║
  ║  • 完全在顶点着色器中计算                      ║
  ║  • 不需要额外的几何数据                        ║
  ║  • 对 GPU 压力小                              ║
  ║                                              ║
  ║  ❌ 缺点：                                   ║
  ║  • 需要采样两次高度图（当前+snapped）           ║
  ║  • 增加顶点着色器指令数                        ║
  ║  • 对带宽有轻微影响                            ║
  ╚══════════════════════════════════════════════╝
```

### 6.3.3 完整的地形 Morphing 着色器

```hlsl
// 完整的地形顶点 morphing 着色器
// 支持多级 LOD 平滑过渡

Shader "Custom/TerrainMorphing"
{
    Properties
    {
        _HeightMap ("Height Map", 2D) = "black" {}
        _HeightScale ("Height Scale", Float) = 100
        _BaseGridSize ("Base Grid Size", Int) = 64
        _LODDistances ("LOD Distances", Vector) = (50, 100, 200, 400, 0, 0, 0, 0)
        _LODMorphRanges ("LOD Morph Ranges", Vector) = (10, 20, 40, 80, 0, 0, 0, 0)
    }
    
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        LOD 100
        
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            
            #include "UnityCG.cginc"
            
            struct appdata
            {
                float4 vertex : POSITION;
                float2 uv : TEXCOORD0;
            };
            
            struct v2f
            {
                float4 vertex : SV_POSITION;
                float2 uv : TEXCOORD0;
                float3 worldPos : TEXCOORD1;
            };
            
            sampler2D _HeightMap;
            float4 _HeightMap_ST;
            float _HeightScale;
            int _BaseGridSize;
            float4 _LODDistances;   // 每个 LOD 的切换距离
            float4 _LODMorphRanges; // 每个 LOD 的过渡范围
            
            // SnapToLowerLODGrid 函数（使用高效位运算版本）
            float2 SnapToLowerLODGrid(float2 uv, int currentLOD)
            {
                int maxCoord = (_BaseGridSize - 1) << 8; // 使用 8 位小数精度
                
                int2 coord;
                coord.x = (int)(uv.x * maxCoord + 0.5f);
                coord.y = (int)(uv.y * maxCoord + 0.5f);
                
                // 对于 currentLOD，需要对齐到 currentLOD+1 的网格
                int shift = 8 + currentLOD + 1; // 多加 1 表示下一级 LOD
                int mask = ~((1 << shift) - 1);
                
                int2 snappedCoord;
                snappedCoord.x = coord.x & mask;
                snappedCoord.y = coord.y & mask;
                
                float2 snappedUV;
                snappedUV.x = (float)snappedCoord.x / maxCoord;
                snappedUV.y = (float)snappedCoord.y / maxCoord;
                
                return snappedUV;
            }
            
            // 计算当前应该使用的 LOD 级别
            int GetCurrentLOD(float3 worldPos)
            {
                float dist = distance(worldPos, _WorldSpaceCameraPos);
                
                // 检查每个 LOD 距离阈值
                if (dist < _LODDistances.x) return 0;
                if (dist < _LODDistances.y) return 1;
                if (dist < _LODDistances.z) return 2;
                if (dist < _LODDistances.w) return 3;
                
                return 4; // 最低 LOD
            }
            
            // 计算 morph 因子（基于距离和当前 LOD）
            float CalculateMorphFactor(float dist, int currentLOD)
            {
                if (currentLOD >= 3) return 0.0; // 最低 LOD 没有 morph
                
                // 当前 LOD 的结束距离
                float lodEndDist = _LODDistances[currentLOD];
                
                // 下一 LOD 的开始距离
                float nextLODStartDist = _LODDistances[currentLOD + 1];
                
                // 过渡范围
                float morphRange = _LODMorphRanges[currentLOD];
                
                // 计算过渡区
                float morphStart = lodEndDist - morphRange * 0.5;
                float morphEnd = lodEndDist + morphRange * 0.5;
                
                // 确保过渡区不重叠
                morphStart = max(morphStart, 0.0);
                morphEnd = min(morphEnd, nextLODStartDist);
                
                // 计算 morph 因子
                float morph = saturate((dist - morphStart) / (morphEnd - morphStart));
                
                return morph;
            }
            
            v2f vert(appdata v)
            {
                v2f o;
                
                // 世界位置（先不考虑高度）
                o.worldPos = mul(unity_ObjectToWorld, v.vertex).xyz;
                
                // 计算当前 LOD 和 morph 因子
                int currentLOD = GetCurrentLOD(o.worldPos);
                float morphFactor = CalculateMorphFactor(distance(o.worldPos, _WorldSpaceCameraPos), currentLOD);
                
                // 计算 morph 后的 UV
                float2 uvMorphed;
                if (morphFactor > 0.001) // 需要 morph
                {
                    // 当前 UV（原始位置）
                    float2 uvCurrent = v.uv;
                    
                    // 对齐到下一级 LOD 的 UV
                    float2 uvSnapped = SnapToLowerLODGrid(v.uv, currentLOD);
                    
                    // Morph 插值
                    uvMorphed = lerp(uvCurrent, uvSnapped, morphFactor);
                }
                else
                {
                    uvMorphed = v.uv;
                }
                
                // 采样高度图（使用 morphed UV）
                float2 heightUV = TRANSFORM_TEX(uvMorphed, _HeightMap);
                float height = tex2Dlod(_HeightMap, float4(heightUV, 0, 0)).r * _HeightScale;
                
                // 应用高度到顶点位置
                float3 worldPos = o.worldPos;
                worldPos.y = height;
                
                o.vertex = mul(UNITY_MATRIX_VP, float4(worldPos, 1.0));
                o.uv = v.uv;
                
                return o;
            }
            
            fixed4 frag(v2f i) : SV_Target
            {
                // 基础地形颜色（这里简化为固定颜色）
                return fixed4(0.3, 0.6, 0.2, 1.0); // 绿色
            }
            ENDCG
        }
    }
}
```

### 6.3.4 注意事项与最佳实践

```
╔══════════════════════════════════════════════╗
║  重要注意事项                                 ║
╚══════════════════════════════════════════════╝

  1. 浮点精度问题
     • 使用整数/定点数运算减少浮点误差
     • 避免在不同 LOD 间产生微小裂缝
     
  2. 性能优化
     • Morph 因子可以在 CPU 预计算，作为 uniform 传入
     • 对远处 Chunk 可以禁用 morph（节约计算）
     • 使用分支预测优化（if/else 在顶点着色器中代价小）
     
  3. 与 LOD 系统的集成
     • 确保 morph 范围与 LOD 切换距离匹配
     • 避免不同 Chunk 间的 morph 不连续
     • 考虑相邻 Chunk 的 LOD 差约束
     
  4. 调试与可视化
     • 添加调试模式：可视化 morph 因子（颜色编码）
     • 可视化当前 LOD 级别
     • 检查边界对齐情况

╔══════════════════════════════════════════════╗
║  应用场景与变体                               ║
╚══════════════════════════════════════════════╝

  1. 只对边界顶点 morph（性能优化）
     • 内部顶点不需要 morph
     • 只在 Chunk 边界处启用 morph
     
  2. 多级 LOD 连续 morph
     • LOD0 → LOD1 → LOD2 连续过渡
     • 需要更复杂的插值策略
     
  3. 基于法线的 morph
     • 陡峭区域使用不同的 morph 参数
     • 平坦区域可以更早切换 LOD
     
  4. 动态 LOD 调整
     • 根据帧率动态调整 LOD 距离
     • 自适应 morph 范围
```

```c
// Calculate morph factor based on distance
float CalcMorphFactor(float dist, float lodStartDist, float lodEndDist)
{
    // Smooth transition in the overlap zone
    return saturate((dist - lodStartDist) / (lodEndDist - lodStartDist));
}

VertexOutput TerrainVertMorph(VertexInput v)
{
    VertexOutput o;
    
    float3 worldPos = TransformObjectToWorld(v.positionOS);
    float dist = distance(worldPos, _WorldSpaceCameraPos);
    
    // Sample height at current LOD position
    float2 uvCurrent = v.uv;
    float heightCurrent = tex2Dlod(_HeightMap, float4(uvCurrent, 0, 0)).r;
    
    // Sample height at next LOD position (snapped to lower LOD grid)
    float2 uvSnapped = SnapToLowerLODGrid(v.uv, _CurrentLOD);
    float heightSnapped = tex2Dlod(_HeightMap, float4(uvSnapped, 0, 0)).r;
    
    // Morph between current and snapped position
    float morphFactor = CalcMorphFactor(dist, _LODMorphStart, _LODMorphEnd);
    float finalHeight = lerp(heightCurrent, heightSnapped, morphFactor);
    
    worldPos.y = finalHeight * _HeightScale;
    o.positionCS = TransformWorldToHClip(worldPos);
    o.uv = uvCurrent;
    
    return o;
}
```
