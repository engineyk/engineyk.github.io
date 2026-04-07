```c++
void FRDGBuilder::Compile()
{
    uint32 RasterPassCount = 0;
    uint32 AsyncComputePassCount = 0;

    // Pass标记位.
    FRDGPassBitArray PassesOnAsyncCompute(false, Passes.Num());
    FRDGPassBitArray PassesOnRaster(false, Passes.Num());
    FRDGPassBitArray PassesWithUntrackedOutputs(false, Passes.Num());
    FRDGPassBitArray PassesToNeverCull(false, Passes.Num());

    const FRDGPassHandle ProloguePassHandle = GetProloguePassHandle();
    const FRDGPassHandle EpiloguePassHandle = GetEpiloguePassHandle();

    const auto IsCrossPipeline = [&](FRDGPassHandle A, FRDGPassHandle B)
    {
        return PassesOnAsyncCompute[A] != PassesOnAsyncCompute[B];
    };

    const auto IsSortedBefore = [&](FRDGPassHandle A, FRDGPassHandle B)
    {
        return A < B;
    };

    const auto IsSortedAfter = [&](FRDGPassHandle A, FRDGPassHandle B)
    {
        return A > B;
    };

    // 在图中构建生产者/消费者依赖关系，并构建打包的元数据位数组，以便在搜索符合特定条件的Pass时获得更好的缓存一致性.
    // 搜索根也被用来进行筛选. 携带了不跟踪的RHI输出(e.g. SHADER_PARAMETER_{BUFFER, TEXTURE}_UAV)的Pass不能被裁剪, 也不能写入外部资源的任何Pass.
    // 资源提取将生命周期延长到尾声(epilogue)Pass，尾声Pass总是图的根。前言和尾声是辅助Pass，因此永远不会被淘汰。
    {
        SCOPED_NAMED_EVENT(FRDGBuilder_Compile_Culling_Dependencies, FColor::Emerald);

        // 增加裁剪依赖.
        const auto AddCullingDependency = [&](FRDGPassHandle& ProducerHandle, FRDGPassHandle PassHandle, ERHIAccess Access)
        {
            if (Access != ERHIAccess::Unknown)
            {
                if (ProducerHandle.IsValid())
                {
                    // 增加Pass依赖.
                    AddPassDependency(ProducerHandle, PassHandle);
                }

                // 如果可写, 则存储新的生产者.
                if (IsWritableAccess(Access))
                {
                    ProducerHandle = PassHandle;
                }
            }
        };

        // 遍历所有Pass, 处理每个Pass的纹理和缓冲区状态等.
        for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
        {
            FRDGPass* Pass = Passes[PassHandle];

            bool bUntrackedOutputs = Pass->GetParameters().HasExternalOutputs();

            // 处理Pass的所有纹理状态.
            for (auto& TexturePair : Pass->TextureStates)
            {
                FRDGTextureRef Texture = TexturePair.Key;
                auto& LastProducers = Texture->LastProducers;
                auto& PassState = TexturePair.Value.State;

                const bool bWholePassState = IsWholeResource(PassState);
                const bool bWholeProducers = IsWholeResource(LastProducers);

                // 生产者数组需要至少和pass状态数组一样大.
                if (bWholeProducers && !bWholePassState)
                {
                    InitAsSubresources(LastProducers, Texture->Layout);
                }

                // 增加裁剪依赖.
                for (uint32 Index = 0, Count = LastProducers.Num(); Index < Count; ++Index)
                {
                    AddCullingDependency(LastProducers[Index], PassHandle, PassState[bWholePassState ? 0 : Index].Access);
                }

                bUntrackedOutputs |= Texture->bExternal;
            }

            // 处理Pass的所有缓冲区状态.
            for (auto& BufferPair : Pass->BufferStates)
            {
                FRDGBufferRef Buffer = BufferPair.Key;
                AddCullingDependency(Buffer->LastProducer, PassHandle, BufferPair.Value.State.Access);
                bUntrackedOutputs |= Buffer->bExternal;
            }

            // 处理Pass的其它标记和数据.
            const ERDGPassFlags PassFlags = Pass->GetFlags();
            const bool bAsyncCompute = EnumHasAnyFlags(PassFlags, ERDGPassFlags::AsyncCompute);
            const bool bRaster = EnumHasAnyFlags(PassFlags, ERDGPassFlags::Raster);
            const bool bNeverCull = EnumHasAnyFlags(PassFlags, ERDGPassFlags::NeverCull);

            PassesOnRaster[PassHandle] = bRaster;
            PassesOnAsyncCompute[PassHandle] = bAsyncCompute;
            PassesToNeverCull[PassHandle] = bNeverCull;
            PassesWithUntrackedOutputs[PassHandle] = bUntrackedOutputs;
            AsyncComputePassCount += bAsyncCompute ? 1 : 0;
            RasterPassCount += bRaster ? 1 : 0;
        }

        // prologue/epilogue设置为不追踪, 它们分别负责外部资源的导入/导出.
        PassesWithUntrackedOutputs[ProloguePassHandle] = true;
        PassesWithUntrackedOutputs[EpiloguePassHandle] = true;

        // 处理提取纹理的裁剪依赖.
        for (const auto& Query : ExtractedTextures)
        {
            FRDGTextureRef Texture = Query.Key;
            for (FRDGPassHandle& ProducerHandle : Texture->LastProducers)
            {
                AddCullingDependency(ProducerHandle, EpiloguePassHandle, Texture->AccessFinal);
            }
            Texture->ReferenceCount++;
        }

        // 处理提取缓冲区的裁剪依赖.
        for (const auto& Query : ExtractedBuffers)
        {
            FRDGBufferRef Buffer = Query.Key;
            AddCullingDependency(Buffer->LastProducer, EpiloguePassHandle, Buffer->AccessFinal);
            Buffer->ReferenceCount++;
        }
    }

    // -------- 处理Pass裁剪 --------
    
    if (GRDGCullPasses)
    {
        TArray<FRDGPassHandle, TInlineAllocator<32, SceneRenderingAllocator>> PassStack;
        // 所有Pass初始化为剔除.
        PassesToCull.Init(true, Passes.Num());

        // 收集Pass的根列表, 符合条件的是那些不追踪的输出或标记为永不剔除的Pass.
        for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
        {
            if (PassesWithUntrackedOutputs[PassHandle] || PassesToNeverCull[PassHandle])
            {
                PassStack.Add(PassHandle);
            }
        }

        // 非递归循环的栈遍历, 采用深度优先搜索方式, 标记每个根可达的Pass节点为不裁剪.
        while (PassStack.Num())
        {
            const FRDGPassHandle PassHandle = PassStack.Pop();

            if (PassesToCull[PassHandle])
            {
                PassesToCull[PassHandle] = false;
                PassStack.Append(Passes[PassHandle]->Producers);

            #if STATS
                --GRDGStatPassCullCount;
            #endif
            }
        }
    }
    else // 不启用Pass裁剪, 所有Pass初始化为不裁剪.
    {
        PassesToCull.Init(false, Passes.Num());
    }
    
    // -------- 处理Pass屏障 --------

    // 遍历经过筛选的图，并为每个子资源编译屏障, 某些过渡是多余的, 例如read-to-read。
    // RDG采用了保守的启发式，选择不合并不一定意味着就要执行转换. 
    // 它们是两个不同的步骤。合并状态跟踪第一次和最后一次的Pass间隔. Pass的引用也会累积到每个资源上. 
    // 必须在剔除后发生，因为剔除后的Pass不能提供引用.

    {
        SCOPED_NAMED_EVENT(FRDGBuilder_Compile_Barriers, FColor::Emerald);

        for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
        {
            // 跳过被裁剪或无参数的Pass.
            if (PassesToCull[PassHandle] || PassesWithEmptyParameters[PassHandle])
            {
                continue;
            }

            // 合并子资源状态.
            const auto MergeSubresourceStates = [&](ERDGParentResourceType ResourceType, FRDGSubresourceState*& PassMergeState, FRDGSubresourceState*& ResourceMergeState, const FRDGSubresourceState& PassState)
            {
                // 跳过未知状态的资源合并.
                if (PassState.Access == ERHIAccess::Unknown)
                {
                    return;
                }

                if (!ResourceMergeState || !FRDGSubresourceState::IsMergeAllowed(ResourceType, *ResourceMergeState, PassState))
                {
                    // 跨管线、不可合并的状态改变需要一个新的pass依赖项来进行防护.
                    if (ResourceMergeState && ResourceMergeState->Pipeline != PassState.Pipeline)
                    {
                        AddPassDependency(ResourceMergeState->LastPass, PassHandle);
                    }

                    // 分配一个新的挂起的合并状态，并将其分配给pass状态.
                    ResourceMergeState = AllocSubresource(PassState);
                    ResourceMergeState->SetPass(PassHandle);
                }
                else
                {
                    // 合并Pass状态进合并后的状态.
                    ResourceMergeState->Access |= PassState.Access;
                    ResourceMergeState->LastPass = PassHandle;
                }

                PassMergeState = ResourceMergeState;
            };

            const bool bAsyncComputePass = PassesOnAsyncCompute[PassHandle];

            // 获取当前处理的Pass实例.
            FRDGPass* Pass = Passes[PassHandle];

            // 处理当前Pass的纹理状态.
            for (auto& TexturePair : Pass->TextureStates)
            {
                FRDGTextureRef Texture = TexturePair.Key;
                auto& PassState = TexturePair.Value;

                // 增加引用数量.
                Texture->ReferenceCount += PassState.ReferenceCount;
                Texture->bUsedByAsyncComputePass |= bAsyncComputePass;

                const bool bWholePassState = IsWholeResource(PassState.State);
                const bool bWholeMergeState = IsWholeResource(Texture->MergeState);

                // 为简单起见，合并/Pass状态维度应该匹配.
                if (bWholeMergeState && !bWholePassState)
                {
                    InitAsSubresources(Texture->MergeState, Texture->Layout);
                }
                else if (!bWholeMergeState && bWholePassState)
                {
                    InitAsWholeResource(Texture->MergeState);
                }

                const uint32 SubresourceCount = PassState.State.Num();
                PassState.MergeState.SetNum(SubresourceCount);

                // 合并子资源状态.
                for (uint32 Index = 0; Index < SubresourceCount; ++Index)
                {
                    MergeSubresourceStates(ERDGParentResourceType::Texture, PassState.MergeState[Index], Texture->MergeState[Index], PassState.State[Index]);
                }
            }

            // 处理当前Pass的缓冲区状态.
            for (auto& BufferPair : Pass->BufferStates)
            {
                FRDGBufferRef Buffer = BufferPair.Key;
                auto& PassState = BufferPair.Value;

                Buffer->ReferenceCount += PassState.ReferenceCount;
                Buffer->bUsedByAsyncComputePass |= bAsyncComputePass;

                MergeSubresourceStates(ERDGParentResourceType::Buffer, PassState.MergeState, Buffer->MergeState, PassState.State);
            }
        }
    }

    // 处理异步计算Pass.
    if (AsyncComputePassCount > 0)
    {
        SCOPED_NAMED_EVENT(FRDGBuilder_Compile_AsyncCompute, FColor::Emerald);

        FRDGPassBitArray PassesWithCrossPipelineProducer(false, Passes.Num());
        FRDGPassBitArray PassesWithCrossPipelineConsumer(false, Passes.Num());

        // 遍历正在执行的活动Pass，以便为每个Pass找到最新的跨管道生产者和最早的跨管道消费者, 以便后续构建异步计算重叠区域时缩小搜索空间.
        for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
        {
            if (PassesToCull[PassHandle] || PassesWithEmptyParameters[PassHandle])
            {
                continue;
            }

            FRDGPass* Pass = Passes[PassHandle];

            // 遍历生产者, 处理生产者和消费者的引用关系.
            for (FRDGPassHandle ProducerHandle : Pass->GetProducers())
            {
                const FRDGPassHandle ConsumerHandle = PassHandle;

                if (!IsCrossPipeline(ProducerHandle, ConsumerHandle))
                {
                    continue;
                }

                FRDGPass* Consumer = Pass;
                FRDGPass* Producer = Passes[ProducerHandle];

                // 为生产者查找另一个管道上最早的消费者.
                if (Producer->CrossPipelineConsumer.IsNull() || IsSortedBefore(ConsumerHandle, Producer->CrossPipelineConsumer))
                {
                    Producer->CrossPipelineConsumer = PassHandle;
                    PassesWithCrossPipelineConsumer[ProducerHandle] = true;
                }

                // 为消费者查找另一个管道上的最新生产者.
                if (Consumer->CrossPipelineProducer.IsNull() || IsSortedAfter(ProducerHandle, Consumer->CrossPipelineProducer))
                {
                    Consumer->CrossPipelineProducer = ProducerHandle;
                    PassesWithCrossPipelineProducer[ConsumerHandle] = true;
                }
            }
        }

        // 为异步计算建立fork / join重叠区域, 用于栅栏及资源分配/回收. 在fork/join完成之前，异步计算Pass不能分配/释放它们的资源引用，因为两个管道是并行运行的。因此，异步计算的所有资源生命周期都被扩展到整个异步区域。

        const auto IsCrossPipelineProducer = [&](FRDGPassHandle A)
        {
            return PassesWithCrossPipelineConsumer[A];
        };

        const auto IsCrossPipelineConsumer = [&](FRDGPassHandle A)
        {
            return PassesWithCrossPipelineProducer[A];
        };

        // 查找跨管道生产者.
        const auto FindCrossPipelineProducer = [&](FRDGPassHandle PassHandle)
        {
            FRDGPassHandle LatestProducerHandle = ProloguePassHandle;
            FRDGPassHandle ConsumerHandle = PassHandle;

            // 期望在其它管道上找到最新的生产者，以便建立一个分叉点. 因为可以用N个生产者通道消耗N个资源，所以只关心最后一个.
            while (ConsumerHandle != Passes.Begin())
            {
                if (!PassesToCull[ConsumerHandle] && !IsCrossPipeline(ConsumerHandle, PassHandle) && IsCrossPipelineConsumer(ConsumerHandle))
                {
                    const FRDGPass* Consumer = Passes[ConsumerHandle];

                    if (IsSortedAfter(Consumer->CrossPipelineProducer, LatestProducerHandle))
                    {
                        LatestProducerHandle = Consumer->CrossPipelineProducer;
                    }
                }
                --ConsumerHandle;
            }

            return LatestProducerHandle;
        };

        // 查找跨管道消费者.
        const auto FindCrossPipelineConsumer = [&](FRDGPassHandle PassHandle)
        {
            check(PassHandle != EpiloguePassHandle);

            FRDGPassHandle EarliestConsumerHandle = EpiloguePassHandle;
            FRDGPassHandle ProducerHandle = PassHandle;

            // 期望找到另一个管道上最早的使用者，因为这在管道之间建立了连接点。因为可以在另一个管道上为N个消费者生产，所以只关心第一个执行的消费者. 
            while (ProducerHandle != Passes.End())
            {
                if (!PassesToCull[ProducerHandle] && !IsCrossPipeline(ProducerHandle, PassHandle) && IsCrossPipelineProducer(ProducerHandle))
                {
                    const FRDGPass* Producer = Passes[ProducerHandle];

                    if (IsSortedBefore(Producer->CrossPipelineConsumer, EarliestConsumerHandle))
                    {
                        EarliestConsumerHandle = Producer->CrossPipelineConsumer;
                    }
                }
                ++ProducerHandle;
            }

            return EarliestConsumerHandle;
        };

        // 将图形Pass插入到异步计算Pass的分叉中.
        const auto InsertGraphicsToAsyncComputeFork = [&](FRDGPass* GraphicsPass, FRDGPass* AsyncComputePass)
        {
            FRDGBarrierBatchBegin& EpilogueBarriersToBeginForAsyncCompute = GraphicsPass->GetEpilogueBarriersToBeginForAsyncCompute(Allocator);

            GraphicsPass->bGraphicsFork = 1;
            EpilogueBarriersToBeginForAsyncCompute.SetUseCrossPipelineFence();

            AsyncComputePass->bAsyncComputeBegin = 1;
            AsyncComputePass->GetPrologueBarriersToEnd(Allocator).AddDependency(&EpilogueBarriersToBeginForAsyncCompute);
        };

        // 将异步计算Pass插入到图形Pass的合并中.
        const auto InsertAsyncToGraphicsComputeJoin = [&](FRDGPass* AsyncComputePass, FRDGPass* GraphicsPass)
        {
            FRDGBarrierBatchBegin& EpilogueBarriersToBeginForGraphics = AsyncComputePass->GetEpilogueBarriersToBeginForGraphics(Allocator);

            AsyncComputePass->bAsyncComputeEnd = 1;
            EpilogueBarriersToBeginForGraphics.SetUseCrossPipelineFence();

            GraphicsPass->bGraphicsJoin = 1;
            GraphicsPass->GetPrologueBarriersToEnd(Allocator).AddDependency(&EpilogueBarriersToBeginForGraphics);
        };

        FRDGPass* PrevGraphicsForkPass = nullptr;
        FRDGPass* PrevGraphicsJoinPass = nullptr;
        FRDGPass* PrevAsyncComputePass = nullptr;

        // 遍历所有Pass, 扩展资源的生命周期, 处理图形Pass和异步计算Pass的交叉和合并节点.
        for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
        {
            if (!PassesOnAsyncCompute[PassHandle] || PassesToCull[PassHandle])
            {
                continue;
            }

            FRDGPass* AsyncComputePass = Passes[PassHandle];

            // 找到分叉Pass和合并Pass.
            const FRDGPassHandle GraphicsForkPassHandle = FindCrossPipelineProducer(PassHandle);
            const FRDGPassHandle GraphicsJoinPassHandle = FindCrossPipelineConsumer(PassHandle);

            AsyncComputePass->GraphicsForkPass = GraphicsForkPassHandle;
            AsyncComputePass->GraphicsJoinPass = GraphicsJoinPassHandle;

            FRDGPass* GraphicsForkPass = Passes[GraphicsForkPassHandle];
            FRDGPass* GraphicsJoinPass = Passes[GraphicsJoinPassHandle];

            // 将异步计算中使用的资源的生命周期延长到fork/join图形Pass。
            GraphicsForkPass->ResourcesToBegin.Add(AsyncComputePass);
            GraphicsJoinPass->ResourcesToEnd.Add(AsyncComputePass);

            // 将图形分叉Pass插入到异步计算分叉Pass.
            if (PrevGraphicsForkPass != GraphicsForkPass)
            {
                InsertGraphicsToAsyncComputeFork(GraphicsForkPass, AsyncComputePass);
            }

            // 将异步计算合并Pass插入到图形合并Pass.
            if (PrevGraphicsJoinPass != GraphicsJoinPass && PrevAsyncComputePass)
            {
                InsertAsyncToGraphicsComputeJoin(PrevAsyncComputePass, PrevGraphicsJoinPass);
            }

            PrevAsyncComputePass = AsyncComputePass;
            PrevGraphicsForkPass = GraphicsForkPass;
            PrevGraphicsJoinPass = GraphicsJoinPass;
        }

        // 图中的最后一个异步计算Pass需要手动连接回epilogue pass.
        if (PrevAsyncComputePass)
        {
            InsertAsyncToGraphicsComputeJoin(PrevAsyncComputePass, EpiloguePass);
            PrevAsyncComputePass->bAsyncComputeEndExecute = 1;
        }
    }

    // 遍历所有图形管道Pass, 并且合并所有具有相同RT的光栅化Pass到同一个RHI渲染Pass中.
    if (GRDGMergeRenderPasses && RasterPassCount > 0)
    {
        SCOPED_NAMED_EVENT(FRDGBuilder_Compile_RenderPassMerge, FColor::Emerald);

        TArray<FRDGPassHandle, SceneRenderingAllocator> PassesToMerge;
        FRDGPass* PrevPass = nullptr;
        const FRenderTargetBindingSlots* PrevRenderTargets = nullptr;

        const auto CommitMerge = [&]
        {
            if (PassesToMerge.Num())
            {
                const FRDGPassHandle FirstPassHandle = PassesToMerge[0];
                const FRDGPassHandle LastPassHandle = PassesToMerge.Last();
                
                // 给定一个Pass的间隔合并成一个单一的渲染Pass: [B, X, X, X, X, E], 开始Pass(B)和结束Pass(E)会分别调用BeginRenderPass/EndRenderPass.
                // 另外，begin将处理整个合并间隔的所有序言屏障，end将处理所有尾声屏障, 这可以避免渲染通道内的资源转换，并更有效地批量处理资源转换.
                // 假设已经在遍历期间完成了过滤来自合并集的Pass之间的依赖关系. 
                
                // (B)是合并序列里的首个Pass.
                {
                    FRDGPass* Pass = Passes[FirstPassHandle];
                    Pass->bSkipRenderPassEnd = 1;
                    Pass->EpilogueBarrierPass = LastPassHandle;
                }

                // (X)是中间Pass.
                for (int32 PassIndex = 1, PassCount = PassesToMerge.Num() - 1; PassIndex < PassCount; ++PassIndex)
                {
                    const FRDGPassHandle PassHandle = PassesToMerge[PassIndex];
                    FRDGPass* Pass = Passes[PassHandle];
                    Pass->bSkipRenderPassBegin = 1;
                    Pass->bSkipRenderPassEnd = 1;
                    Pass->PrologueBarrierPass = FirstPassHandle;
                    Pass->EpilogueBarrierPass = LastPassHandle;
                }

                // (E)是合并序列里的最后Pass.
                {
                    FRDGPass* Pass = Passes[LastPassHandle];
                    Pass->bSkipRenderPassBegin = 1;
                    Pass->PrologueBarrierPass = FirstPassHandle;
                }

            #if STATS
                GRDGStatRenderPassMergeCount += PassesToMerge.Num();
            #endif
            }
            PassesToMerge.Reset();
            PrevPass = nullptr;
            PrevRenderTargets = nullptr;
        };

        // 遍历所有光栅Pass, 合并所有相同RT的Pass到同一个渲染Pass中.
        for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
        {
            // 跳过已被裁剪的Pass.
            if (PassesToCull[PassHandle])
            {
                continue;
            }

            // 是光栅Pass才处理.
            if (PassesOnRaster[PassHandle])
            {
                FRDGPass* NextPass = Passes[PassHandle];

                // 用户控制渲染Pass的Pass不能与其他Pass合并，光栅UAV的Pass由于潜在的相互依赖也不能合并.
                if (EnumHasAnyFlags(NextPass->GetFlags(), ERDGPassFlags::SkipRenderPass) || NextPass->bUAVAccess)
                {
                    CommitMerge();
                    continue;
                }

                // 图形分叉Pass不能和之前的光栅Pass合并.
                if (NextPass->bGraphicsFork)
                {
                    CommitMerge();
                }

                const FRenderTargetBindingSlots& RenderTargets = NextPass->GetParameters().GetRenderTargets();

                if (PrevPass)
                {
                    // 对比RT, 以判定是否可以合并.
                    if (PrevRenderTargets->CanMergeBefore(RenderTargets)
                    #if WITH_MGPU
                        && PrevPass->GPUMask == NextPass->GPUMask
                    #endif
                        )
                    {
                        // 如果可以, 添加Pass到PassesToMerge列表.
                        if (!PassesToMerge.Num())
                        {
                            PassesToMerge.Add(PrevPass->GetHandle());
                        }
                        PassesToMerge.Add(PassHandle);
                    }
                    else
                    {
                        CommitMerge();
                    }
                }

                PrevPass = NextPass;
                PrevRenderTargets = &RenderTargets;
            }
            else if (!PassesOnAsyncCompute[PassHandle])
            {
                // 图形管道上的非光栅Pass将使RT合并无效.
                CommitMerge();
            }
        }

        CommitMerge();
    }
}
```