# GPU 渲染管线流程

---

## 1. 应用阶段（Application Stage）

> CPU 侧：准备渲染数据、剔除、提交 Draw Call

---

## 2. 几何阶段（Geometry Stage）

| 序号  | 阶段                              |  可控性  |
| :---: | --------------------------------- | :------: |
|   1   | **Vertex Shader** 顶点着色器      | ✅ 可编程 |
|   2   | **Geometry Shader** 几何着色器    | ✅ 可编程 |
|   3   | **投影**（Projection）            | ✅ 可配置 |
|   4   | **视锥体裁剪**（Frustum Culling） | ❌ 不可控 |
|   5   | **屏幕映射**（Screen Mapping）    | ❌ 不可控 |
|   6   | **背面剔除**（Back-face Culling） | ❌ 不可控 |

---

## 3. 光栅化阶段（Rasterization）

| 序号  | 阶段                                 |  可控性  |
| :---: | ------------------------------------ | :------: |
|   1   | **三角形设置**（Triangle Setup）     | ❌ 不可控 |
|   2   | **三角形遍历**（Triangle Traversal） | ❌ 不可控 |

---

## 4. 逐像素阶段（Per-Pixel Stage）

> 核心：Test & Blend

### 4.1 顶点属性插值（❌ 不可控）

光栅化后对顶点属性进行重心坐标插值。

### 4.2 PreZ（Opaque + Mask）

- **只写 Depth，不写 Color**
- 用于建立深度缓冲，为后续 EarlyZ 提供基础

### 4.3 EarlyZ

- 位于光栅化之后、Pixel Shader 之前
- 深度比较改为 **Equal**
- **不写 Depth，只写 Color**
- ⚠️ 不能开 `clip` / `discard`，否则退化为 LateZ

### 4.4 Pixel / Fragment Shader（✅ 可编程）

- 插值与像素着色
- 计算 **颜色（Color）** 和 **Alpha**

### 4.5 LateZ

- 当存在 `discard` / `alpha test` 时，**延迟 Depth Test / 写入**
- 在 Pixel Shader **之后**执行 Depth Test
- 若无 discard，则利用 **EarlyZ** 提前深度测试，先判断再着色

### 4.6 测试与混合（Test & Blending）

#### Test

```
┌────────────────────────────────────────────────────────
│                        Test 阶段                       
├──────────────┬─────────────────────────────────────────
│ Clip/Discard │ clip(alpha - threshold);                
│ (裁剪测试)    │ 或 if (alpha < threshold) discard;     
├──────────────┼─────────────────────────────────────────
│ Alpha Test   │ 无法在 frag 之前决定是否剔除            
│              │ 可在深度测试执行前运行                  
│              │ 根据物体透明度决定是否渲染              
├──────────────┼─────────────────────────────────────────
│ Stencil Test │ 判断像素是否通过模板缓冲区的规则        
├──────────────┼─────────────────────────────────────────
│ Depth Test   │ 位于像素处理阶段的测试合并阶段          
└──────────────┴─────────────────────────────────────────
```

#### Alpha Blend（✅ 可配置）

- 经过 Test 的片元进入 Blend
- 需要 **FrameBuffer 混合**
- ⚠️ 无法执行深度测试（半透明物体）
- 最终写入颜色缓冲区

---

## 流程总览

```
CPU 应用阶段
    │
    ▼
┌──────────────────── GPU ────────────────────
│                                             
│  Vertex Shader ──► Geometry Shader          
│       │                                     
│       ▼                                     
│  投影 ──► 视锥体裁剪 ──► 屏幕映射 ──► 背面剔除 
│       │                                     
│       ▼                                     
│  三角形设置 ──► 三角形遍历                  
│       │                                     
│       ▼                                     
│  PreZ (只写Depth)                           
│       │                                     
│       ▼                                     
│  EarlyZ (Depth==Equal, 只写Color)           
│       │                                     
│       ▼                                     
│  Pixel/Fragment Shader (计算颜色+Alpha)     
│       │                                     
│       ▼                                     
│  LateZ (有discard时延迟深度测试)            
│       │                                     
│       ▼                                     
│  Alpha Test ──► Stencil Test ──► Depth Test 
│       │                                     
│       ▼                                     
│  Alpha Blend ──► 写入 FrameBuffer           
│                                             
└─────────────────────────────────────────────
```
