---
layout:     post
title:      Unreal Multi-Thread Rendering Dependency Graph
subtitle:   UE multi-thread rendering architecture and pipeline
date:       2023-4-7
author:     kang
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - Rendering
---


<center> Unreal Multi-Thread Rendering Dependency Graph 渲染依赖性图表</center>

# <center> Overview</center>

```
1. Base             |
                    |   Three Threads
                    |       → Game Thread (GT)
                    |           → ENQUEUE_RENDER_COMMAND
                    |       → Render Thread (RT)
                    |       → RHI Thread
                    |   Thread Data Flow
                    |
2. Builder          |
                    |   → Compiile
                    |   → Excute
                    |   → Pass
2. RDGEngine        |
                    |   → Compiile
                    |   → Excute
                    |   → Pass
                    |
```

Overview

Rendering Dependency Graph，渲染依赖性图表

- 基于有向无环图(Directed Acyclic Graph，DAG)的调度系统，用于执行渲染管线的整帧优化
- 利用现代的图形API（DirectX 12、Vulkan和Metal 2），实现自动异步计算调度以及更高效的内存管理和屏障管理来提升性能
- 传统的图形API（DirectX 11、OpenGL）要求驱动器调用复杂的启发法，以确定何时以及如何在GPU上执行关键的调度操作
- 清空缓存，管理和再使用内存，执行布局转换等等
- 接口存在即时模式特性，因此需要复杂的记录和状态跟踪才能处理各种极端情况。这些情况最终会对性能产生负面影响，并阻碍并行
- 现代的图形API（DirectX 12、Vulkan和Metal 2）与传统图形API不同，将低级GPU管理的负担转移到应用程序。
- 这使得应用程序可以利用渲染管线的高级情境来驱动调度，从而提高性能并且简化渲染堆栈。
- RDG的理念不在GPU上立即执行Pass，而是先收集所有需要渲染的Pass，然后按照依赖的顺序对图表进行编译和执行，期间会执行各类裁剪和优化。
- 依赖性图表数据结构的整帧认知与现代图形API的能力相结合，使RDG能够在后台执行复杂的调度任务：
  - 执行异步计算通道的自动调度和隔离
  - 在帧的不相交间隔期间，使资源之间的别名内存保持活跃状态
  - 尽早启动屏障和布局转换，避免管线延迟
- RDG并非UE独创的概念和技术，早在2017年的GDC中，寒霜就已经实现并应用了Frame Graph（帧图）的技术。
- Frame Graph旨在将引擎的各类渲染功能（Feature）和上层渲染逻辑（Renderer）和下层资源（Shader、RenderContext、图形API等）隔离开来
- FrameGraph是高层级的Render Pass和资源的代表，包含了一帧中所用到的所有信息
- UE的RDG正是基于Frame Graph之上定制和实现而成的
- RDG已经被大量普及，包含场景渲染、后处理、光追等等模块都使用了RDG代替原本直接调用RHI命令的方式