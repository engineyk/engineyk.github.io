RDG Pass模块涉及了屏障、资源转换、RDGPass等概念：
RDG Pass和渲染Pass并非一一对应关系，有可能多个合并成一个渲染Pass，详见后面章节。RDG Pass最复杂莫过于多线程处理、资源状态转换以及依赖处理，不过本节先不涉及

```c++
// Engine\Source\Runtime\RHI\Public\RHI.h

// 用于表示RHI中挂起的资源转换的不透明数据结构.
struct FRHITransition
{
public:
    template <typename T>
    inline T* GetPrivateData()
    {
        uintptr_t Addr = Align(uintptr_t(this + 1), GRHITransitionPrivateData_AlignInBytes);
        return reinterpret_cast<T*>(Addr);
    }

    template <typename T>
    inline const T* GetPrivateData() const
    {
        return const_cast<FRHITransition*>(this)->GetPrivateData<T>();
    }

private:
    FRHITransition(const FRHITransition&) = delete;
    FRHITransition(FRHITransition&&) = delete;
    FRHITransition(ERHIPipeline SrcPipelines, ERHIPipeline DstPipelines);
    ~FRHITransition();

    // 获取总的分配尺寸.
    static uint64 GetTotalAllocationSize()
    // 获取对齐字节数.
    static uint64 GetAlignment();

    // 开始标记.
    inline void MarkBegin(ERHIPipeline Pipeline) const
    {
        int8 Mask = int8(Pipeline);
        int8 PreviousValue = FPlatformAtomics::InterlockedAnd(&State, ~Mask);
        if (PreviousValue == Mask)
        {
            Cleanup();
        }
    }
    // 结束标记.
    inline void MarkEnd(ERHIPipeline Pipeline) const
    {
        int8 Mask = int8(Pipeline) << int32(ERHIPipeline::Num);
        int8 PreviousValue = FPlatformAtomics::InterlockedAnd(&State, ~Mask);
        if (PreviousValue == Mask)
        {
            Cleanup();
        }
    }
    // 清理转换资源, 包含RHI转换和分配的内存.
    inline void Cleanup() const;

    mutable int8 State;

#if DO_CHECK
    mutable ERHIPipeline AllowedSrc;
    mutable ERHIPipeline AllowedDst;
#endif

#if ENABLE_RHI_VALIDATION
    // 栅栏.
    RHIValidation::FFence* Fence = nullptr;
    // 挂起的开始操作.
    RHIValidation::FOperationsList PendingOperationsBegin;
    // 挂起的结束操作.
    RHIValidation::FOperationsList PendingOperationsEnd;
#endif
};

// Engine\Source\Runtime\RenderCore\Public\RenderGraphPass.h

// RDG屏障批
class RENDERCORE_API FRDGBarrierBatch
{
public:
    FRDGBarrierBatch(const FRDGBarrierBatch&) = delete;
    bool IsSubmitted() const
    FString GetName() const;

protected:
    FRDGBarrierBatch(const FRDGPass* InPass, const TCHAR* InName);
    void SetSubmitted();
    ERHIPipeline GetPipeline() const

private:
    bool bSubmitted = false;
    // Graphics或AsyncCompute
    ERHIPipeline Pipeline;

#if RDG_ENABLE_DEBUG
    const FRDGPass* Pass;
    const TCHAR* Name;
#endif
};

// 屏障批开始
class RENDERCORE_API FRDGBarrierBatchBegin final : public FRDGBarrierBatch
{
public:
    FRDGBarrierBatchBegin(const FRDGPass* InPass, const TCHAR* InName, TOptional<ERHIPipeline> InOverridePipelineForEnd = {});
    ~FRDGBarrierBatchBegin();

    // 增加资源转换到批次.
    void AddTransition(FRDGParentResourceRef Resource, const FRHITransitionInfo& Info);

    const FRHITransition* GetTransition() const;
    bool IsTransitionValid() const;
    void SetUseCrossPipelineFence();
    // 提交屏障/资源转换.
    void Submit(FRHIComputeCommandList& RHICmdList);

private:
    TOptional<ERHIPipeline> OverridePipelineToEnd;
    bool bUseCrossPipelineFence = false;

    // 提交后存储的资源转换, 它在结束批处理时被赋回null.
    const FRHITransition* Transition = nullptr;
    // 要执行的异步资源转换数组.
    TArray<FRHITransitionInfo, TInlineAllocator<1, SceneRenderingAllocator>> Transitions;

#if RDG_ENABLE_DEBUG
    // 与Transitions数组匹配的RDG资源数组, 仅供调试.
    TArray<FRDGParentResource*, SceneRenderingAllocator> Resources;
#endif
};

// 屏障批结束
class RENDERCORE_API FRDGBarrierBatchEnd final : public FRDGBarrierBatch
{
public:
    FRDGBarrierBatchEnd(const FRDGPass* InPass, const TCHAR* InName);
    ~FRDGBarrierBatchEnd();

    // 预留内存.
    void ReserveMemory(uint32 ExpectedDependencyCount);
    // 在开始批处理上插入依赖项, 开始批可以插入多个结束批.
    void AddDependency(FRDGBarrierBatchBegin* BeginBatch);
    // 提交资源转换.
    void Submit(FRHIComputeCommandList& RHICmdList);

private:
    // 此结束批完成后可以唤起的开始批转换.
    TArray<FRDGBarrierBatchBegin*, TInlineAllocator<1, SceneRenderingAllocator>> Dependencies;
};

// RGD通道基础类.
class RENDERCORE_API FRDGPass
{
public:
    FRDGPass(FRDGEventName&& InName, FRDGParameterStruct InParameterStruct, ERDGPassFlags InFlags);
    FRDGPass(const FRDGPass&) = delete;
    virtual ~FRDGPass() = default;

    // 通道数据接口.
    const TCHAR* GetName() const;
    FORCEINLINE const FRDGEventName& GetEventName() const;
    FORCEINLINE ERDGPassFlags GetFlags() const;
    FORCEINLINE ERHIPipeline GetPipeline() const;
    // RDG Pass参数.
    FORCEINLINE FRDGParameterStruct GetParameters() const;
    FORCEINLINE FRDGPassHandle GetHandle() const;
    bool IsMergedRenderPassBegin() const;
    bool IsMergedRenderPassEnd() const;
    bool SkipRenderPassBegin() const;
    bool SkipRenderPassEnd() const;
    bool IsAsyncCompute() const;
    bool IsAsyncComputeBegin() const;
    bool IsAsyncComputeEnd() const;
    bool IsGraphicsFork() const;
    bool IsGraphicsJoin() const;
    // 生产者句柄.
    const FRDGPassHandleArray& GetProducers() const;
    // 跨管线生产者.
    FRDGPassHandle GetCrossPipelineProducer() const;
    // 跨管线消费者.
    FRDGPassHandle GetCrossPipelineConsumer() const;
    // 分叉Pass.
    FRDGPassHandle GetGraphicsForkPass() const;
    // 合并Pass.
    FRDGPassHandle GetGraphicsJoinPass() const;
    
#if RDG_CPU_SCOPES
    FRDGCPUScopes GetCPUScopes() const;
#endif
#if RDG_GPU_SCOPES
    FRDGGPUScopes GetGPUScopes() const;
#endif

private:
    // 前序屏障.
    FRDGBarrierBatchBegin& GetPrologueBarriersToBegin(FRDGAllocator& Allocator);
    FRDGBarrierBatchEnd& GetPrologueBarriersToEnd(FRDGAllocator& Allocator);
    // 后序屏障.
    FRDGBarrierBatchBegin& GetEpilogueBarriersToBeginForGraphics(FRDGAllocator& Allocator);
    FRDGBarrierBatchBegin& GetEpilogueBarriersToBeginForAsyncCompute(FRDGAllocator& Allocator);
    FRDGBarrierBatchBegin& GetEpilogueBarriersToBeginFor(FRDGAllocator& Allocator, ERHIPipeline PipelineForEnd);

    //////////////////////////////////////////////////////////////////////////
    //! User Methods to Override

    // 执行实现.
    virtual void ExecuteImpl(FRHIComputeCommandList& RHICmdList) = 0;

    //////////////////////////////////////////////////////////////////////////

    // 执行.
    void Execute(FRHIComputeCommandList& RHICmdList);

    // Pass数据.
    const FRDGEventName Name;
    const FRDGParameterStruct ParameterStruct;
    const ERDGPassFlags Flags;
    const ERHIPipeline Pipeline;
    FRDGPassHandle Handle;

    // Pass标记.
    union
    {
        struct
        {
            uint32 bSkipRenderPassBegin : 1;
            uint32 bSkipRenderPassEnd : 1;
            uint32 bAsyncComputeBegin : 1;
            uint32 bAsyncComputeEnd : 1;
            uint32 bAsyncComputeEndExecute : 1;
            uint32 bGraphicsFork : 1;
            uint32 bGraphicsJoin : 1;
            uint32 bUAVAccess : 1;
            IF_RDG_ENABLE_DEBUG(uint32 bFirstTextureAllocated : 1);
        };
        uint32 PackedBits = 0;
    };

    // 最新的跨管道生产者的句柄.
    FRDGPassHandle CrossPipelineProducer;
    // 最早的跨管线消费者的句柄.
    FRDGPassHandle CrossPipelineConsumer;

    // (仅限AsyncCompute)Graphics pass，该通道是异步计算间隔的fork / join.
    FRDGPassHandle GraphicsForkPass;
    FRDGPassHandle GraphicsJoinPass;

    // 处理此通道的前序/后续屏障的通道.
    FRDGPassHandle PrologueBarrierPass;
    FRDGPassHandle EpilogueBarrierPass;

    // 生产者Pass列表.
    FRDGPassHandleArray Producers;

    // 纹理状态.
    struct FTextureState
    {
        FRDGTextureTransientSubresourceState State;
        FRDGTextureTransientSubresourceStateIndirect MergeState;
        uint16 ReferenceCount = 0;
    };

    // 缓冲区状态.
    struct FBufferState
    {
        FRDGSubresourceState State;
        FRDGSubresourceState* MergeState = nullptr;
        uint16 ReferenceCount = 0;
    };

    // 将纹理/缓冲区映射到Pass中如何使用的信息。  
    TSortedMap<FRDGTexture*, FTextureState, SceneRenderingAllocator> TextureStates;
    TSortedMap<FRDGBuffer*, FBufferState, SceneRenderingAllocator> BufferStates;
    // 在执行此Pass期间，计划开始的Pass参数列表.
    TArray<FRDGPass*, TInlineAllocator<1, SceneRenderingAllocator>> ResourcesToBegin;
    TArray<FRDGPass*, TInlineAllocator<1, SceneRenderingAllocator>> ResourcesToEnd;
    // 在acquire完成*之后*，*在丢弃*之前*获取的纹理列表. 获取适用于所有分配的纹理.
    TArray<FRHITexture*, SceneRenderingAllocator> TexturesToAcquire;
    // 在Pass完成*之后*，获得(acquires)*之后*，丢弃的纹理列表. 丢弃仅适用于标记为瞬态(transient)的纹理，并且纹理的最后一个别名(alia)使用自动丢弃行为(为了支持更干净的切换到用户或返回池).
    TArray<FRHITexture*, SceneRenderingAllocator> TexturesToDiscard;

    FRDGBarrierBatchBegin* PrologueBarriersToBegin = nullptr;
    FRDGBarrierBatchEnd* PrologueBarriersToEnd = nullptr;
    FRDGBarrierBatchBegin* EpilogueBarriersToBeginForGraphics = nullptr;
    FRDGBarrierBatchBegin* EpilogueBarriersToBeginForAsyncCompute = nullptr;

    EAsyncComputeBudget AsyncComputeBudget = EAsyncComputeBudget::EAll_4;
};

// RDG Pass Lambda执行函数.
template <typename ParameterStructType, typename ExecuteLambdaType>
class TRDGLambdaPass : public FRDGPass
{
    (......)

    TRDGLambdaPass(FRDGEventName&& InName, const ParameterStructType* InParameterStruct, ERDGPassFlags InPassFlags, ExecuteLambdaType&& InExecuteLambda);

private:
    // 执行实现.
    void ExecuteImpl(FRHIComputeCommandList& RHICmdList) override
    {
        check(!kSupportsRaster || RHICmdList.IsImmediate());
        // 调用Lambda实例.
        ExecuteLambda(static_cast<TRHICommandList&>(RHICmdList));
    }

    Lambda实例.
    ExecuteLambdaType ExecuteLambda;
};

// 附带空Lambda的Pass.
template <typename ExecuteLambdaType>
class TRDGEmptyLambdaPass : public TRDGLambdaPass<FEmptyShaderParameters, ExecuteLambdaType>
{
public:
    TRDGEmptyLambdaPass(FRDGEventName&& InName, ERDGPassFlags InPassFlags, ExecuteLambdaType&& InExecuteLambda);

private:
    FEmptyShaderParameters EmptyShaderParameters;
};

// 用于前序/后序Pass.
class FRDGSentinelPass final : public FRDGPass
{
public:
    FRDGSentinelPass(FRDGEventName&& Name);

private:
    void ExecuteImpl(FRHIComputeCommandList&) override;
    FEmptyShaderParameters EmptyShaderParameters;
};
```