---
layout:     post
title:      UnrealEngine文件系统(UFS)
subtitle:   UnrealEngine文件系统(UFS)
date:       2026-04-19
author:     engineyk
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - 文件资源
---

# Unreal Engine 文件系统 (UFS)

> IPlatformFile / FPakFile / IO Store / Async Loading / Pak Format

---
四层架构图（Application → VFS → IO → OS），核心设计理念

## 目录

- [Unreal Engine 文件系统 (UFS)](#unreal-engine-文件系统-ufs)
  - [目录](#目录)
  - [1. 架构总览](#1-架构总览)
    - [1.1 UFS 分层架构](#11-ufs-分层架构)
    - [1.2 核心设计理念](#12-核心设计理念)
  - [2. IPlatformFile 平台抽象层](#2-iplatformfile-平台抽象层)
    - [2.1 接口定义](#21-接口定义)
    - [2.2 IFileHandle 接口](#22-ifilehandle-接口)
    - [2.3 责任链构建](#23-责任链构建)
    - [2.4 文件查找流程](#24-文件查找流程)
  - [3. FPakPlatformFile — Pak 文件系统](#3-fpakplatformfile--pak-文件系统)
    - [3.1 核心结构](#31-核心结构)
    - [3.2 Mount 流程](#32-mount-流程)
    - [3.3 OpenRead 流程](#33-openread-流程)
  - [4. Pak 文件格式](#4-pak-文件格式)
    - [4.1 文件布局](#41-文件布局)
    - [4.2 FPakInfo (Footer)](#42-fpakinfo-footer)
    - [4.3 FPakEntry (文件条目)](#43-fpakentry-文件条目)
    - [4.4 压缩方式](#44-压缩方式)
  - [5. FPakFile 核心类](#5-fpakfile-核心类)
    - [5.1 类定义](#51-类定义)
    - [5.2 Path Hash Index (UE4.25+)](#52-path-hash-index-ue425)
    - [5.3 Encoded Pak Entries (紧凑编码)](#53-encoded-pak-entries-紧凑编码)
  - [6. 文件读取流程](#6-文件读取流程)
    - [6.1 同步读取](#61-同步读取)
    - [6.2 FPakFileHandle 实现](#62-fpakfilehandle-实现)
  - [7. IO Store (UE5)](#7-io-store-ue5)
    - [7.1 IO Store 架构](#71-io-store-架构)
    - [7.2 FIoChunkId](#72-fiochunkid)
    - [7.3 FIoDispatcher](#73-fiodispatcher)
    - [7.4 .utoc 文件格式](#74-utoc-文件格式)
    - [7.5 IO Store vs Pak 对比](#75-io-store-vs-pak-对比)
  - [8. 异步加载系统](#8-异步加载系统)
    - [8.1 异步 I/O 架构](#81-异步-io-架构)
    - [8.2 FAsyncPackage 状态机](#82-fasyncpackage-状态机)
    - [8.3 Zen Loader (UE5) — 深度分析](#83-zen-loader-ue5--深度分析)
      - [8.3.1 Zen Loader vs Legacy Loader 对比](#831-zen-loader-vs-legacy-loader-对比)
      - [8.3.2 核心架构](#832-核心架构)
      - [8.3.3 核心类关系](#833-核心类关系)
      - [8.3.4 Package Store — 预计算依赖图](#834-package-store--预计算依赖图)
      - [8.3.5 Export Bundle — 批量序列化](#835-export-bundle--批量序列化)
      - [8.3.6 FAsyncPackage2 状态机](#836-fasyncpackage2-状态机)
      - [8.3.7 事件驱动模型](#837-事件驱动模型)
      - [8.3.8 I/O 批量调度](#838-io-批量调度)
      - [8.3.9 Global Import Store — 跨包引用解析](#839-global-import-store--跨包引用解析)
      - [8.3.10 并行反序列化](#8310-并行反序列化)
      - [8.3.11 优先级系统](#8311-优先级系统)
      - [8.3.12 取消加载](#8312-取消加载)
      - [8.3.13 Arena 内存分配](#8313-arena-内存分配)
      - [8.3.14 性能对比数据](#8314-性能对比数据)
      - [8.3.15 Zen Loader 启用条件](#8315-zen-loader-启用条件)
      - [8.3.16 源码路径索引](#8316-源码路径索引)
      - [8.3.17 面试常见问题](#8317-面试常见问题)
  - [9. FFileManager](#9-ffilemanager)
    - [9.1 接口](#91-接口)
    - [9.2 FFileManager 与 IPlatformFile 的关系](#92-ffilemanager-与-iplatformfile-的关系)
  - [10. Mounting 机制](#10-mounting-机制)
    - [10.1 Pak 挂载顺序](#101-pak-挂载顺序)
    - [10.2 自动挂载](#102-自动挂载)
    - [10.3 运行时挂载 (DLC/Hotfix)](#103-运行时挂载-dlchotfix)
  - [11. 加密与签名](#11-加密与签名)
    - [11.1 AES 加密](#111-aes-加密)
    - [11.2 签名验证](#112-签名验证)
  - [12. Shader / Bulk Data 特殊处理](#12-shader--bulk-data-特殊处理)
    - [12.1 Shader Code Library](#121-shader-code-library)
    - [12.2 Bulk Data](#122-bulk-data)
  - [13. 平台差异](#13-平台差异)
  - [14. 性能优化](#14-性能优化)
    - [14.1 优化策略](#141-优化策略)
  - [15. 面试高频问题](#15-面试高频问题)
    - [Q1: UE 的文件系统是如何分层的？](#q1-ue-的文件系统是如何分层的)
    - [Q2: Pak 文件的格式是什么？如何读取？](#q2-pak-文件的格式是什么如何读取)
    - [Q3: IO Store 和 Pak 的区别？](#q3-io-store-和-pak-的区别)
    - [Q4: Pak 的 Mount 机制是什么？如何实现热更新？](#q4-pak-的-mount-机制是什么如何实现热更新)
    - [Q5: 异步加载的流程？PostLoad 为什么必须在主线程？](#q5-异步加载的流程postload-为什么必须在主线程)
    - [Q6: Pak 加密是如何工作的？](#q6-pak-加密是如何工作的)
  - [16. 完整调用流程图](#16-完整调用流程图)
    - [16.1 从 LoadObject 到磁盘读取](#161-从-loadobject-到磁盘读取)
    - [16.2 源码文件映射](#162-源码文件映射)
  - [参考](#参考)

---

## 1. 架构总览

### 1.1 UFS 分层架构

```
┌─────────────────────────────────────────────────────────────────┐
│              Unreal File System (UFS) Architecture              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Application Layer (应用层)                                      │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  FFileManager (IFileManager)                           │     │
│  │  ├── CreateFileReader() / CreateFileWriter()           │     │
│  │  ├── FileExists() / DirectoryExists()                  │     │
│  │  ├── FindFiles() / FindFilesRecursive()                │     │
│  │  └── Copy() / Move() / Delete()                        │     │
│  └────────────────────────────────────────────────────────┘     │
│                           ↓                                     │
│  Virtual File System Layer (虚拟文件系统层)                      │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  IPlatformFile Chain (责任链模式)                       │     │
│  │                                                        │     │
│  │  ┌──────────────────┐                                  │     │
│  │  │ FPakPlatformFile │ ← Pak files (.pak)               │     │
│  │  │ (topmost)        │                                  │     │
│  │  └────────┬─────────┘                                  │     │
│  │           ↓ fallthrough                                │     │
│  │  ┌──────────────────┐                                  │     │
│  │  │ FSandboxPlatform │ ← Sandbox/redirect (Editor)      │     │
│  │  │ File (optional)  │                                  │     │
│  │  └────────┬─────────┘                                  │     │
│  │           ↓ fallthrough                                │     │
│  │  ┌──────────────────┐                                  │     │
│  │  │ FLoggedPlatform  │ ← Logging wrapper (debug)        │     │
│  │  │ File (optional)  │                                  │     │
│  │  └────────┬─────────┘                                  │     │
│  │           ↓ fallthrough                                │     │
│  │  ┌──────────────────┐                                  │     │
│  │  │ Physical Platform│ ← Actual OS file system          │     │
│  │  │ File (底层)      │   (FWindowsPlatformFile, etc.)   │     │
│  │  └──────────────────┘                                  │     │
│  └────────────────────────────────────────────────────────┘     │
│                           ↓                                     │
│  IO Layer (IO 层)                                               │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  UE4: FPakFile + FArchive (sequential read)            │     │
│  │  UE5: FIoStore + FIoDispatcher (batch I/O)             │     │
│  │       FIoStoreReader / FIoChunkId                      │     │
│  └────────────────────────────────────────────────────────┘     │
│                           ↓                                     │
│  OS Layer (操作系统层)                                           │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  Windows: CreateFileW / ReadFile / IOCP                │     │
│  │  Linux: open / pread / io_uring                        │     │
│  │  Android: AAssetManager / pread                        │     │
│  │  iOS: NSFileManager / dispatch_io                      │     │
│  │  Console: Platform-specific APIs                       │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 核心设计理念

```
UFS 的核心设计：

1. 责任链模式 (Chain of Responsibility)
   IPlatformFile 形成链表，每层可以拦截或转发文件操作
   Pak 层拦截 → 找到则从 Pak 读取
   找不到 → 转发给下一层（物理文件系统）

2. 透明替换
   上层代码不关心文件来自 Pak 还是磁盘
   统一的 IFileHandle / FArchive 接口

3. 优先级覆盖
   后挂载的 Pak 优先级更高
   支持 Patch/DLC 覆盖基础包内容

4. 异步 I/O
   UE5 的 IO Store 支持批量异步读取
   减少 I/O 调度开销，提高吞吐量
```

---

## 2. IPlatformFile 平台抽象层

### 2.1 接口定义

```cpp
// Runtime/Core/Public/HAL/IPlatformFile.h

class IPlatformFile
{
public:
    // Chain management
    virtual IPlatformFile* GetLowerLevel() = 0;
    virtual void SetLowerLevel(IPlatformFile* NewLowerLevel) = 0;
    virtual const TCHAR* GetName() const = 0;
    
    // File operations
    virtual bool FileExists(const TCHAR* Filename) = 0;
    virtual int64 FileSize(const TCHAR* Filename) = 0;
    virtual bool DeleteFile(const TCHAR* Filename) = 0;
    virtual bool MoveFile(const TCHAR* To, const TCHAR* From) = 0;
    virtual bool SetReadOnly(const TCHAR* Filename, bool bNewReadOnlyValue) = 0;
    
    // Directory operations
    virtual bool DirectoryExists(const TCHAR* Directory) = 0;
    virtual bool CreateDirectory(const TCHAR* Directory) = 0;
    virtual bool DeleteDirectory(const TCHAR* Directory) = 0;
    
    // File handle
    virtual IFileHandle* OpenRead(const TCHAR* Filename, 
                                  bool bAllowWrite = false) = 0;
    virtual IFileHandle* OpenWrite(const TCHAR* Filename, 
                                   bool bAppend = false, 
                                   bool bAllowRead = false) = 0;
    
    // Iteration
    virtual bool IterateDirectory(const TCHAR* Directory, 
                                  FDirectoryVisitor& Visitor) = 0;
    virtual bool IterateDirectoryRecursively(const TCHAR* Directory, 
                                             FDirectoryVisitor& Visitor) = 0;
    
    // Timestamps
    virtual FDateTime GetTimeStamp(const TCHAR* Filename) = 0;
    virtual FDateTime GetAccessTimeStamp(const TCHAR* Filename) = 0;
};
```

### 2.2 IFileHandle 接口

```cpp
// Runtime/Core/Public/HAL/IFileHandle.h

class IFileHandle
{
public:
    virtual ~IFileHandle() {}
    
    virtual int64 Tell() = 0;                    // Current position
    virtual bool Seek(int64 NewPosition) = 0;    // Seek absolute
    virtual bool SeekFromEnd(int64 NewPositionRelativeToEnd = 0) = 0;
    virtual bool Read(uint8* Destination, int64 BytesToRead) = 0;
    virtual bool Write(const uint8* Source, int64 BytesToWrite) = 0;
    virtual bool Flush(bool bFullFlush = false) = 0;
    virtual bool Truncate(int64 NewSize) = 0;
    virtual int64 Size() = 0;
};
```

### 2.3 责任链构建

```cpp
// Engine startup: build the platform file chain

void FPlatformFileManager::InitializeNewAsyncIO()
{
  // 1. Start with physical platform file (OS level)
  IPlatformFile* PhysicalPlatformFile = 
      &IPlatformFile::GetPlatformPhysical();
  // Windows → FWindowsPlatformFile
  // Linux   → FLinuxPlatformFile
  // Android → FAndroidPlatformFile

  // 2. Optionally wrap with logging
  #if !UE_BUILD_SHIPPING

  IPlatformFile* LoggedFile = new FLoggedPlatformFile();
  LoggedFile->SetLowerLevel(PhysicalPlatformFile);
  PhysicalPlatformFile = LoggedFile;
  #endif

  // 3. Wrap with Pak file system
  FPakPlatformFile* PakPlatformFile = new FPakPlatformFile();
  PakPlatformFile->SetLowerLevel(PhysicalPlatformFile);
  PakPlatformFile->Initialize(&IPlatformFile::GetPlatformPhysical(), 
                                TEXT(""));

  // 4. Set as active platform file
  FPlatformFileManager::Get().SetPlatformFile(*PakPlatformFile);
}

// Chain visualization:
//   FPakPlatformFile → [FSandboxPlatformFile] → FPhysicalPlatformFile
//   ↑ topmost                                    ↑ bottommost (OS)
```

### 2.4 文件查找流程

```
FileExists("../Content/Textures/T_Hero.uasset"):

  FPakPlatformFile::FileExists()
  ├── Search in all mounted Pak files
  │   ├── Pak_Patch.pak → found? → return true
  │   ├── Pak_Main.pak  → found? → return true
  │   └── Not in any Pak
  │
  └── LowerLevel->FileExists()  (fallthrough)
      └── FPhysicalPlatformFile::FileExists()
          └── OS stat() / GetFileAttributes()
              → File on disk? → return true/false
```

---

## 3. FPakPlatformFile — Pak 文件系统

### 3.1 核心结构

```cpp
// Runtime/PakFile/Public/IPlatformFilePak.h

class FPakPlatformFile : public IPlatformFile
{
private:
    // Lower level platform file (physical FS)
    IPlatformFile* LowerLevel;
    
    // All mounted pak files, sorted by priority
    TArray<FPakListEntry> PakFiles;
    
    struct FPakListEntry
    {
        FString PakFilename;                // Path to .pak file
        TRefCountPtr<FPakFile> PakFile;     // Parsed pak data
        int32 ReadOrder;                    // Priority (higher = checked first)
    };
    
    // Index: filename → which pak contains it
    // Built from all mounted paks for fast lookup
    TMap<FString, FPakDirectory> DirectoryIndex;
    
    // Encryption keys
    TMap<FGuid, FAES::FAESKey> Keys;
    
public:
    // Mount a pak file
    bool Mount(const TCHAR* InPakFilename, uint32 PakOrder, 
               const TCHAR* InPath = nullptr, 
               bool bLoadIndex = true);
    
    // Unmount
    bool Unmount(const TCHAR* InPakFilename);
    
    // IPlatformFile overrides
    virtual bool FileExists(const TCHAR* Filename) override;
    virtual IFileHandle* OpenRead(const TCHAR* Filename, 
                                  bool bAllowWrite = false) override;
    // ...
};
```

### 3.2 Mount 流程

```
FPakPlatformFile::Mount("Game.pak", order=100):

  1. Open physical file
     LowerLevel->OpenRead("Game.pak")
     → OS file handle

  2. Create FPakFile
     FPakFile* Pak = new FPakFile(FileHandle, PakFilename)

  3. Read & validate Pak footer
     Pak->LoadIndex()
     ├── Seek to end - sizeof(FPakInfo)
     ├── Read FPakInfo (magic, version, index offset, hash)
     ├── Validate magic number (0x5A6F12E1)
     ├── Seek to index offset
     ├── Read mount point string
     ├── Read file entry count
     └── For each entry:
         ├── Read filename (relative path)
         ├── Read FPakEntry (offset, size, compressed size, hash, etc.)
         └── Add to Pak's internal index

  4. Insert into PakFiles array (sorted by ReadOrder)
     PakFiles.Add({PakFilename, Pak, PakOrder})
     // Higher order = checked first

  5. Rebuild directory index
     For each file in Pak:
       DirectoryIndex[filename] = PakEntry
```

### 3.3 OpenRead 流程

```cpp
IFileHandle* FPakPlatformFile::OpenRead(
    const TCHAR* Filename, bool bAllowWrite)
{
    // 1. Normalize path
    FString StandardFilename = NormalizeFilename(Filename);
    
    // 2. Search in Pak files (highest priority first)
    FPakEntry FileEntry;
    FPakFile* PakFile = nullptr;
    
    for (auto& PakListEntry : PakFiles)  // sorted by ReadOrder desc
    {
        if (PakListEntry.PakFile->Find(StandardFilename, &FileEntry))
        {
            PakFile = PakListEntry.PakFile;
            break;  // Found in highest priority pak
        }
    }
    
    if (PakFile)
    {
        // 3a. Found in Pak → create Pak file handle
        return new FPakFileHandle(*PakFile, FileEntry, 
                                  /*bIsCompressed=*/false);
    }
    else
    {
        // 3b. Not in Pak → fallthrough to physical FS
        return LowerLevel->OpenRead(Filename, bAllowWrite);
    }
}
```

---

## 4. Pak 文件格式

### 4.1 文件布局

```
┌──────────────────────────────────────────────────────────────────┐
│                    .pak File Layout                              │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  Data Section (文件数据区)                              │      │
│  │  ┌──────────────────────────────────────────────┐      │      │
│  │  │  File 0 data (possibly compressed/encrypted) │      │      │
│  │  ├──────────────────────────────────────────────┤      │      │
│  │  │  File 1 data                                 │      │      │
│  │  ├──────────────────────────────────────────────┤      │      │
│  │  │  File 2 data                                 │      │      │
│  │  ├──────────────────────────────────────────────┤      │      │
│  │  │  ...                                         │      │      │
│  │  ├──────────────────────────────────────────────┤      │      │
│  │  │  File N data                                 │      │      │
│  │  └──────────────────────────────────────────────┘      │      │
│  └────────────────────────────────────────────────────────┘      │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  Index Section (索引区)                                 │      │
│  │  ┌──────────────────────────────────────────────┐      │      │
│  │  │  Mount Point (string)                        │      │      │
│  │  │  e.g., "../../../ProjectName/Content/"       │      │      │
│  │  ├──────────────────────────────────────────────┤      │      │
│  │  │  Entry Count (int32)                         │      │      │
│  │  ├──────────────────────────────────────────────┤      │      │
│  │  │  File Entry 0:                               │      │      │
│  │  │    Filename (FString)                        │      │      │
│  │  │    FPakEntry struct                          │      │      │
│  │  ├──────────────────────────────────────────────┤      │      │
│  │  │  File Entry 1: ...                           │      │      │
│  │  ├──────────────────────────────────────────────┤      │      │
│  │  │  ...                                         │      │      │
│  │  └──────────────────────────────────────────────┘      │      │
│  └────────────────────────────────────────────────────────┘      │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  Footer (FPakInfo) — 固定大小，在文件末尾                │      │
│  │  ┌──────────────────────────────────────────────┐      │      │
│  │  │  Magic: 0x5A6F12E1 (uint32)                  │      │      │
│  │  │  Version: (int32) e.g., 11 for UE5           │      │      │
│  │  │  IndexOffset: (int64) offset to index section│      │      │
│  │  │  IndexSize: (int64) size of index section    │      │      │
│  │  │  IndexHash: (FSHAHash) SHA1 of index         │      │      │
│  │  │  bEncryptedIndex: (bool)                     │      │      │
│  │  │  EncryptionKeyGuid: (FGuid)                  │      │      │
│  │  │  CompressionMethods: (TArray<FName>)         │      │      │
│  │  └──────────────────────────────────────────────┘      │      │
│  └────────────────────────────────────────────────────────┘      │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

Reading order:
  1. Seek to (FileSize - sizeof(FPakInfo)) → read Footer
  2. Seek to Footer.IndexOffset → read Index
  3. For each file: seek to Entry.Offset → read Data
```

### 4.2 FPakInfo (Footer)

```cpp
// Runtime/PakFile/Public/IPlatformFilePak.h

struct FPakInfo
{
    static const uint32 PakFile_Magic = 0x5A6F12E1;
    
    int32 Magic;                    // Must be PakFile_Magic
    int32 Version;                  // Pak format version
    int64 IndexOffset;              // Byte offset to index
    int64 IndexSize;                // Size of index data
    FSHAHash IndexHash;             // SHA1 hash of index
    bool bEncryptedIndex;           // Is index encrypted?
    FGuid EncryptionKeyGuid;        // Key GUID for decryption
    
    // Version >= PakFile_Version_CompressionMethodNames
    TArray<FName> CompressionMethods; // e.g., ["Zlib", "Oodle"]
    
    // Size depends on version:
    // V8: 61 bytes
    // V9+: variable (compression method names)
    
    static int64 GetSerializedSize(int32 InVersion);
};

// Pak versions:
enum
{
    PakFile_Version_Initial = 1,
    PakFile_Version_NoTimestamps = 2,
    PakFile_Version_CompressionEncryption = 3,
    PakFile_Version_IndexEncryption = 4,
    PakFile_Version_RelativeChunkOffsets = 5,
    PakFile_Version_DeleteRecords = 6,
    PakFile_Version_EncryptionKeyGuid = 7,
    PakFile_Version_FNameBasedCompression = 8,
    PakFile_Version_FrozenIndex = 9,
    PakFile_Version_PathHashIndex = 10,
    PakFile_Version_Fnv64BugFix = 11,
    
    PakFile_Version_Latest = PakFile_Version_Fnv64BugFix
};
```

### 4.3 FPakEntry (文件条目)

```cpp
struct FPakEntry
{
    int64 Offset;              // Offset in pak file (to data start)
    int64 Size;                // Uncompressed size
    int64 UncompressedSize;    // Same as Size if not compressed
    
    // Compression
    int32 CompressionMethodIndex; // Index into FPakInfo::CompressionMethods
    // 0 = None, 1+ = index into methods array
    
    // Compression blocks (for block-based compression)
    TArray<FPakCompressedBlock> CompressionBlocks;
    int32 CompressionBlockSize;  // e.g., 65536 (64KB)
    
    // Flags
    uint8 Flags;
    // Flag_Encrypted = 0x01
    // Flag_Deleted   = 0x02
    
    // Hash
    FSHAHash Hash;             // SHA1 of uncompressed data
    
    bool IsEncrypted() const { return (Flags & Flag_Encrypted) != 0; }
    bool IsDeleteRecord() const { return (Flags & Flag_Deleted) != 0; }
};

struct FPakCompressedBlock
{
    int64 CompressedStart;     // Offset in pak file
    int64 CompressedEnd;       // End offset
    // CompressedSize = CompressedEnd - CompressedStart
};
```

### 4.4 压缩方式

```
┌──────────────────────────────────────────────────────────────┐
│  Compression Methods                                         │
├──────────────┬──────────┬──────────┬─────────────────────────┤
│  Method      │ Ratio    │ Speed    │ Notes                   │
├──────────────┼──────────┼──────────┼─────────────────────────┤
│  None        │ 1:1      │ Fastest  │ No CPU cost             │
│  Zlib        │ ~2:1     │ Medium   │ Default in UE4          │
│  Oodle       │ ~2.5:1   │ Fast     │ Default in UE5          │
│  LZ4         │ ~1.8:1   │ Fastest  │ Good for streaming      │
│  Gzip        │ ~2:1     │ Slow     │ Legacy                  │
└──────────────┴──────────┴──────────┴─────────────────────────┘

Block-based compression:
  File is split into blocks (default 64KB)
  Each block compressed independently
  → Random access: only decompress needed block
  → Parallel decompression possible

  File (1MB) → [Block0 64KB][Block1 64KB]...[Block15 64KB]
  Read offset 100000:
    Block index = 100000 / 65536 = 1
    Block offset = 100000 % 65536 = 34464
    → Decompress Block 1 only
    → Read from offset 34464 in decompressed block
```

---

## 5. FPakFile 核心类

### 5.1 类定义

```cpp
// Runtime/PakFile/Private/IPlatformFilePak.cpp

class FPakFile : public FRefCountBase
{
private:
    FString PakFilename;           // Path to .pak file
    FName PakFilenameName;         // FName version
    
    FPakInfo Info;                 // Footer data
    FString MountPoint;            // Mount point path
    
    // File index (two lookup methods):
    // Method 1: Full directory index (legacy)
    TMap<FString, FPakDirectory> Index;
    
    // Method 2: Path hash index (UE4.25+, faster)
    TMap<uint64, FPakEntryLocation> PathHashIndex;
    // Hash of normalized path → entry location
    
    // Method 3: Full directory index (encoded, UE4.25+)
    // Encoded as a compact trie structure
    TArray<uint8> EncodedPakEntries;
    
    int32 NumEntries;              // Total file count
    int64 CachedTotalSize;         // Total pak file size
    
    // Encryption
    FGuid EncryptionKeyGuid;
    
    // Underlying file handle
    TUniquePtr<IFileHandle> PakFileHandle;
    
public:
    // Find a file in this pak
    bool Find(const FString& Filename, FPakEntry* OutEntry) const;
    
    // Get all files
    void GetPrunedFilenames(TArray<FString>& OutFilenames) const;
    
    // Read data from pak
    bool ReadRawData(int64 Offset, int64 Size, uint8* Dest) const;
};
```

### 5.2 Path Hash Index (UE4.25+)

```
Problem: TMap<FString, FPakEntry> is slow for large paks
  - String comparison is expensive
  - Memory: each FString has heap allocation
  - 100K files → significant memory and lookup time

Solution: Path Hash Index
  - Hash each normalized path to uint64 (FNV64)
  - Store hash → entry location mapping
  - O(1) lookup instead of string comparison
  - Much less memory (8 bytes per entry vs ~100+ bytes)

  Lookup:
    uint64 hash = FCrc::StrCrc32(*NormalizedPath);
    // or FNV64 in newer versions
    FPakEntryLocation* Location = PathHashIndex.Find(hash);
    if (Location)
        DecodeEntry(Location, OutEntry);

  Collision handling:
    Extremely rare with 64-bit hash
    If collision → fall back to full directory index
```

### 5.3 Encoded Pak Entries (紧凑编码)

```
Problem: FPakEntry is 200+ bytes per entry
  100K files × 200 bytes = 20MB just for index!

Solution: Encoded entries (bit-packed)
  Most fields have predictable values:
  - CompressionBlockSize: usually 65536 (1 bit flag)
  - CompressionMethodIndex: usually 0 or 1 (2 bits)
  - Flags: usually 0 (1 bit)
  - Offset: can be delta-encoded
  - Size: can be variable-length encoded

  Encoding:
  ┌──────────────────────────────────────────────────┐
  │  Bit 0: IsOffset32Bit (1=32bit, 0=64bit)        │
  │  Bit 1: IsSize32Bit                              │
  │  Bit 2: IsUncompressedSize32Bit                  │
  │  Bit 3: IsCompressed                             │
  │  Bit 4: IsEncrypted                              │
  │  Bit 5-6: CompressionBlockCount encoding         │
  │  Followed by: variable-length fields              │
  └──────────────────────────────────────────────────┘

  Result: ~20-40 bytes per entry (vs 200+)
  100K files: ~3MB instead of 20MB
```

---

## 6. 文件读取流程

### 6.1 同步读取

```
FArchive* Reader = IFileManager::Get().CreateFileReader(
    TEXT("../Content/Textures/T_Hero.uasset"));

  ┌─────────────────────────────────────────────────────────┐
  │  IFileManager::CreateFileReader()                       │
  │  │                                                      │
  │  ├── FPakPlatformFile::OpenRead()                       │
  │  │   ├── Normalize path                                 │
  │  │   ├── Search PathHashIndex in each mounted Pak       │
  │  │   │   ├── Hash path → uint64                         │
  │  │   │   ├── Lookup in PathHashIndex                    │
  │  │   │   └── Found in "Game.pak" at entry #1234       │
  │  │   │                                                  │
  │  │   ├── Decode FPakEntry from encoded data             │
  │  │   │   ├── Offset: 0x1A2B3C4D                         │
  │  │   │   ├── Size: 524288 (512KB)                       │
  │  │   │   ├── Compressed: Yes (Oodle)                    │
  │  │   │   └── Blocks: 8 × 64KB                           │
  │  │   │                                                  │
  │  │   └── Create FPakFileHandle                          │
  │  │       ├── References FPakFile (ref counted)          │
  │  │       ├── Stores FPakEntry                           │
  │  │       └── Current position = 0                       │
  │  │                                                      │
  │  └── Wrap in FArchiveFileReaderGeneric                  │
  │      └── Provides FArchive interface (<<, Serialize)    │
  └─────────────────────────────────────────────────────────┘

Reader->Serialize(Buffer, Size):
  ┌─────────────────────────────────────────────────────────┐
  │  FPakFileHandle::Read(Buffer, Size)                     │
  │  │                                                      │
  │  ├── Calculate which compression blocks to read         │
  │  │   StartBlock = CurrentPos / CompressionBlockSize     │
  │  │   EndBlock = (CurrentPos + Size) / CompressionBlockSize │
  │  │                                                      │
  │  ├── For each needed block:                             │
  │  │   ├── Seek to block's CompressedStart in pak file    │
  │  │   ├── Read compressed data                           │
  │  │   ├── If encrypted: AES decrypt                      │
  │  │   ├── Decompress (Oodle/Zlib/LZ4)                    │
  │  │   └── Copy relevant portion to output buffer         │
  │  │                                                      │
  │  └── Update current position                            │
  └─────────────────────────────────────────────────────────┘
```

### 6.2 FPakFileHandle 实现

```cpp
class FPakFileHandle : public IFileHandle
{
    TRefCountPtr<FPakFile> PakFile;   // The pak this file is in
    FPakEntry Entry;                  // This file's entry data
    int64 Position;                   // Current read position
    
    // Cached decompression buffer
    TArray<uint8> DecompressedBlock;
    int32 CachedBlockIndex;           // Which block is cached
    
public:
    virtual bool Read(uint8* Dest, int64 BytesToRead) override
    {
        if (!Entry.IsCompressed())
        {
            // Uncompressed: direct read from pak
            PakFile->ReadRawData(
                Entry.Offset + Position, BytesToRead, Dest);
        }
        else
        {
            // Compressed: block-by-block decompression
            while (BytesToRead > 0)
            {
                int32 BlockIndex = Position / Entry.CompressionBlockSize;
                int32 BlockOffset = Position % Entry.CompressionBlockSize;
                
                if (BlockIndex != CachedBlockIndex)
                {
                    // Read and decompress this block
                    FPakCompressedBlock& Block = 
                        Entry.CompressionBlocks[BlockIndex];
                    int64 CompressedSize = 
                        Block.CompressedEnd - Block.CompressedStart;
                    
                    TArray<uint8> CompressedData;
                    CompressedData.SetNumUninitialized(CompressedSize);
                    PakFile->ReadRawData(
                        Block.CompressedStart, CompressedSize, 
                        CompressedData.GetData());
                    
                    // Decrypt if needed
                    if (Entry.IsEncrypted())
                        DecryptData(CompressedData);
                    
                    // Decompress
                    FCompression::UncompressMemory(
                        Entry.CompressionMethodIndex,
                        DecompressedBlock.GetData(),
                        Entry.CompressionBlockSize,
                        CompressedData.GetData(),
                        CompressedSize);
                    
                    CachedBlockIndex = BlockIndex;
                }
                
                // Copy from decompressed block
                int64 BytesFromBlock = FMath::Min(
                    BytesToRead, 
                    (int64)Entry.CompressionBlockSize - BlockOffset);
                FMemory::Memcpy(
                    Dest, 
                    DecompressedBlock.GetData() + BlockOffset, 
                    BytesFromBlock);
                
                Dest += BytesFromBlock;
                Position += BytesFromBlock;
                BytesToRead -= BytesFromBlock;
            }
        }
        return true;
    }
};
```

---

## 7. IO Store (UE5)

### 7.1 IO Store 架构

```
┌─────────────────────────────────────────────────────────────────┐
│              IO Store Architecture (UE5)                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Problem with Pak files:                                        │
│  - One file handle per pak → limited parallelism                │
│  - Sequential reads → poor NVMe utilization                     │
│  - Per-file compression → overhead per small file               │
│  - String-based lookup → slow for many files                    │
│                                                                 │
│  IO Store solution:                                             │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  .utoc (Table of Contents)                             │     │
│  │  ├── Chunk ID → offset/size mapping                    │     │
│  │  ├── Compression block info                            │     │
│  │  └── Directory index (optional)                        │     │
│  │                                                        │     │
│  │  .ucas (Container Archive Store)                       │     │
│  │  ├── Raw data blocks (compressed)                      │     │
│  │  ├── Aligned for direct I/O                            │     │
│  │  └── No per-file headers                               │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                 │
│  Key differences from Pak:                                      │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  Pak:      filename → FPakEntry → read from .pak       │     │
│  │  IO Store: FIoChunkId → offset → read from .ucas       │     │
│  │                                                        │     │
│  │  Pak:      per-file compression blocks                 │     │
│  │  IO Store: global compression blocks (shared)          │     │
│  │                                                        │     │
│  │  Pak:      single file handle, sequential              │     │
│  │  IO Store: FIoDispatcher, batch I/O, parallel          │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 FIoChunkId

```cpp
// Runtime/Core/Public/IO/IoDispatcher.h

struct FIoChunkId
{
    uint8 Id[12];  // 96-bit chunk identifier
    
    // Constructed from:
    // - Package ID (FPackageId) + chunk type
    // - Or: custom hash
    
    // Chunk types:
    enum EIoChunkType : uint8
    {
        ExportBundleData = 0,    // UObject exports
        BulkData = 1,            // Bulk data (textures, audio)
        OptionalBulkData = 2,    // Optional bulk data
        MemoryMappedBulkData = 3,// Memory-mapped bulk data
        ScriptObjects = 4,       // Blueprint bytecode
        ContainerHeader = 5,     // Container metadata
        ExternalFile = 6,        // External file reference
        ShaderCodeLibrary = 7,   // Shader bytecode
        ShaderCode = 8,          // Individual shader
        PackageStoreEntry = 9,   // Package store
    };
};

// Example: Create chunk ID for a package's export data
FIoChunkId ChunkId = CreateIoChunkId(
    PackageId,                        // FPackageId (hash of package name)
    0,                                // Chunk index
    EIoChunkType::ExportBundleData    // Type
);
```

### 7.3 FIoDispatcher

```cpp
// Runtime/Core/Public/IO/IoDispatcher.h

class FIoDispatcher
{
public:
    // Batch read interface
    FIoBatch NewBatch();
    
    // Single read
    FIoRequest ReadChunk(const FIoChunkId& ChunkId, 
                         FIoReadOptions Options = {});
    
    // Batch read (efficient)
    void ReadChunks(TArrayView<FIoChunkId> ChunkIds,
                    FIoReadCallback Callback);
    
    // Mount a container (.utoc + .ucas)
    TIoStatusOr<FIoContainerHandle> Mount(
        const FString& ContainerPath,
        int32 Order,
        const FGuid& EncryptionKeyGuid = FGuid());
};

// Usage:
FIoDispatcher& Dispatcher = FIoDispatcher::Get();

// Single async read
FIoRequest Request = Dispatcher.ReadChunk(ChunkId);
Request.Then([](TIoStatusOr<FIoBuffer> Result) {
    if (Result.IsOk())
    {
        FIoBuffer& Buffer = Result.ValueOrDie();
        // Process data...
    }
});

// Batch read (more efficient)
FIoBatch Batch = Dispatcher.NewBatch();
FIoRequest Req1 = Batch.ReadChunk(ChunkId1);
FIoRequest Req2 = Batch.ReadChunk(ChunkId2);
FIoRequest Req3 = Batch.ReadChunk(ChunkId3);
Batch.Issue(); // Submit all at once
// → I/O scheduler can optimize ordering
```

### 7.4 .utoc 文件格式

```
┌──────────────────────────────────────────────────────────────┐
│  .utoc (Table of Contents) Layout                            │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Header:                                                     │
│  ├── Magic (uint8[16])                                       │
│  ├── Version (uint32)                                        │
│  ├── HeaderSize (uint32)                                     │
│  ├── EntryCount (uint32)                                     │
│  ├── CompressedBlockEntryCount (uint32)                      │
│  ├── CompressedBlockEntrySize (uint32)                       │
│  ├── CompressionMethodNameCount (uint32)                     │
│  ├── CompressionMethodNameLength (uint32)                    │
│  ├── CompressionBlockSize (uint32)                           │
│  ├── DirectoryIndexSize (uint32)                             │
│  ├── PartitionCount (uint32)                                 │
│  ├── ContainerId (FIoContainerId)                            │
│  ├── EncryptionKeyGuid (FGuid)                               │
│  └── ContainerFlags (EIoContainerFlags)                      │
│                                                              │
│  Chunk ID Table:                                             │
│  ├── FIoChunkId[EntryCount]                                  │
│  │   12 bytes each                                           │
│                                                              │
│  Chunk Offset/Length Table:                                  │
│  ├── FIoOffsetAndLength[EntryCount]                          │
│  │   ├── Offset (5 bytes, 40-bit)                            │
│  │   └── Length (5 bytes, 40-bit)                            │
│  │   10 bytes each                                           │
│                                                              │
│  Compression Block Table:                                    │
│  ├── FIoStoreTocCompressedBlockEntry[BlockCount]             │
│  │   ├── Offset (5 bytes)                                    │
│  │   ├── CompressedSize (3 bytes)                            │
│  │   ├── UncompressedSize (3 bytes)                          │
│  │   └── CompressionMethodIndex (1 byte)                     │
│  │   12 bytes each                                           │
│                                                              │
│  Compression Method Names:                                   │
│  ├── char[MethodCount][MethodNameLength]                     │
│                                                              │
│  Directory Index (optional):                                 │
│  ├── Encoded directory tree for filename lookup              │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 7.5 IO Store vs Pak 对比

```
┌──────────────────┬──────────────────┬──────────────────────────┐
│  Aspect          │ Pak (.pak)       │ IO Store (.utoc/.ucas)   │
├──────────────────┼──────────────────┼──────────────────────────┤
│  Lookup          │ String path      │ FIoChunkId (96-bit hash) │
│  Lookup speed    │ O(1) hash map    │ O(1) sorted array        │
│  Index memory    │ ~20-40 bytes/file│ ~22 bytes/chunk          │
│  I/O model       │ Single handle    │ Batch dispatcher         │
│  Parallelism     │ Limited          │ Full NVMe queue depth    │
│  Compression     │ Per-file blocks  │ Global block table       │
│  Alignment       │ Not guaranteed   │ Sector-aligned           │
│  Patching        │ Priority mount   │ Priority mount           │
│  Encryption      │ Per-file AES     │ Per-container AES        │
│  UE version      │ UE4 + UE5        │ UE5 (Zen Loader)         │
│  Coexistence     │ Yes              │ Yes (both can be used)   │
└──────────────────┴──────────────────┴──────────────────────────┘
```

---

## 8. 异步加载系统

### 8.1 异步 I/O 架构

```
┌─────────────────────────────────────────────────────────────────┐
│              Async Loading Architecture                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Game Thread                                                    │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  LoadPackageAsync("Hero")                              │     │
│  │  ├── Create FAsyncPackage                              │     │
│  │  ├── Add to AsyncLoadingThread queue                   │     │
│  │  └── Return FStreamableHandle                          │     │
│  └────────────────────────────────────────────────────────┘     │
│                           ↓                                     │
│  Async Loading Thread (ALT)                                     │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  FAsyncLoadingThread::TickAsyncLoading()               │     │
│  │  ├── Process pending packages                          │     │
│  │  ├── For each FAsyncPackage:                           │     │
│  │  │   ├── Phase 1: CreateLinker                         │     │
│  │  │   │   └── Open package file (from Pak/IO Store)     │     │
│  │  │   ├── Phase 2: FinishLinker                         │     │
│  │  │   │   └── Parse package summary, name map, imports  │     │
│  │  │   ├── Phase 3: CreateImports                        │     │
│  │  │   │   └── Resolve import dependencies               │     │
│  │  │   ├── Phase 4: CreateExports                        │     │
│  │  │   │   └── Allocate UObjects                         │     │
│  │  │   ├── Phase 5: PreLoadObjects                       │     │
│  │  │   │   └── Deserialize object data                   │     │
│  │  │   ├── Phase 6: PostLoadObjects                      │     │
│  │  │   │   └── PostLoad() on game thread                 │     │
│  │  │   └── Phase 7: FinishObjects                        │     │
│  │  │       └── Complete, fire callbacks                  │     │
│  │  └── Yield to game thread for PostLoad                 │     │
│  └────────────────────────────────────────────────────────┘     │
│                           ↓                                     │
│  I/O Thread(s)                                                  │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  FAsyncIOManager / FIoDispatcher                       │     │
│  │  ├── Process I/O requests from ALT                     │     │
│  │  ├── Read from Pak / IO Store                          │     │
│  │  ├── Decompress blocks                                 │     │
│  │  ├── Decrypt if needed                                 │     │
│  │  └── Signal completion to ALT                          │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 FAsyncPackage 状态机

```
FAsyncPackage States:

  ┌──────────────┐
  │ CreateLinker │ → Open file, create FLinkerLoad
  └──────┬───────┘
         ↓
  ┌──────────────┐
  │ FinishLinker │ → Parse summary, names, imports, exports
  └──────┬───────┘
         ↓
  ┌──────────────┐
  │ CreateImports│ → Resolve imported packages (may trigger more loads)
  └──────┬───────┘
         ↓
  ┌──────────────┐
  │ CreateExports│ → Allocate UObject memory, call constructors
  └──────┬───────┘
         ↓
  ┌──────────────┐
  │ PreLoad      │ → Deserialize (Serialize()) on async thread
  └──────┬───────┘
         ↓
  ┌──────────────┐
  │ PostLoad     │ → PostLoad() on GAME THREAD (must be main thread)
  └──────┬───────┘
         ↓
  ┌──────────────┐
  │ Finish       │ → Fire completion callbacks, cleanup
  └──────────────┘

  ★ PostLoad MUST run on game thread ★
  This is the main source of loading hitches!
  Complex PostLoad (e.g., building physics, navigation) → frame spike
```

### 8.3 Zen Loader (UE5) — 深度分析

> Zen Loader 是 UE5 全新的异步资源加载系统，完全替代了 UE4 的 FLinkerLoad，
> 与 IO Store (.utoc/.ucas) 深度集成，实现了事件驱动、批量 I/O、并行反序列化的现代加载管线。

#### 8.3.1 Zen Loader vs Legacy Loader 对比

```
┌──────────────────────────────────────────────────────────────────────────┐
│              Zen Loader vs Legacy Loader (FLinkerLoad)                    │
├──────────────────┬──────────────────────────┬────────────────────────────┤
│  维度            │  Legacy (UE4)            │  Zen Loader (UE5)          │
├──────────────────┼──────────────────────────┼────────────────────────────┤
│  核心类          │  FLinkerLoad             │  FAsyncPackage2            │
│  数据源          │  Pak File (FPakFile)     │  IO Store (.utoc/.ucas)    │
│  依赖解析        │  运行时解析 Import Table │  预计算 Package Store      │
│  I/O 模型        │  同步/轮询式异步         │  事件驱动 (Callback)       │
│  I/O 粒度        │  单文件读取              │  批量 Chunk 读取           │
│  序列化          │  逐 Export 反序列化      │  Export Bundle 批量反序列化│
│  PostLoad        │  全部主线程              │  部分可并行                │
│  线程模型        │  ALT + Game Thread       │  ALT + IO Thread + Workers │
│  依赖图          │  运行时构建              │  Cook 时预计算             │
│  内存分配        │  逐对象 new              │  Arena 批量分配            │
│  取消支持        │  有限                    │  完整取消/优先级调整       │
│  适用场景        │  UE4 全版本              │  UE5 (IO Store 模式)       │
└──────────────────┴──────────────────────────┴────────────────────────────┘
```

#### 8.3.2 核心架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    Zen Loader Architecture                                │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Game Thread                                                             │
│  ┌────────────────────────────────────────────────────────────────┐      │
│  │  LoadPackage() / StreamableManager / Async Load Request        │      │
│  │       │                                                        │      │
│  │       ▼                                                        │      │
│  │  FAsyncLoadingThread2 (ALT2)                                   │      │
│  │  ├── Package Store (预计算依赖图)                              │      │
│  │  ├── FAsyncPackage2 状态机                                     │      │
│  │  └── Event Queue (事件驱动)                                    │      │
│  └────────────────────────────────────────────────────────────────┘      │
│       │                                                                  │
│       │ CreateIoRequest()                                                │
│       ▼                                                                  │
│  ┌────────────────────────────────────────────────────────────────┐      │
│  │  FIoDispatcher                                                 │      │
│  │  ├── FIoBatch (批量请求)                                       │      │
│  │  ├── FIoRequest → FIoChunkId                                   │      │
│  │  └── Completion Callback → 触发 ALT2 状态推进                  │      │
│  └────────────────────────────────────────────────────────────────┘      │
│       │                                                                  │
│       │ Platform I/O                                                     │
│       ▼                                                                  │
│  ┌────────────────────────────────────────────────────────────────┐      │
│  │  IO Store Backend                                              │      │
│  │  ├── .utoc (Table of Contents) — ChunkId → offset/size        │      │
│  │  ├── .ucas (Container Archive) — 连续数据块                    │      │
│  │  └── Platform File I/O (async read)                            │      │
│  └────────────────────────────────────────────────────────────────┘      │
│                                                                          │
│  Worker Threads (TaskGraph)                                              │
│  ┌────────────────────────────────────────────────────────────────┐      │
│  │  ├── Serialize Export Objects (并行反序列化)                    │      │
│  │  ├── PostLoad (部分可并行的 PostLoad)                          │      │
│  │  └── CreateExport (对象构造)                                   │      │
│  └────────────────────────────────────────────────────────────────┘      │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

#### 8.3.3 核心类关系

```cpp
// Runtime/CoreUObject/Private/Serialization/AsyncLoading2.cpp

// ═══════════════════════════════════════════════════════════════
// FAsyncLoadingThread2 — Zen Loader 的主调度器
// ═══════════════════════════════════════════════════════════════
class FAsyncLoadingThread2 : public FRunnable
{
    // Package Store: 预计算的包依赖图
    FPackageStore PackageStore;
    
    // 活跃的异步包列表
    TArray<FAsyncPackage2*> AsyncPackages;
    
    // 事件队列 (替代轮询)
    FAsyncLoadEventQueue2 EventQueue;
    
    // IO Dispatcher 引用
    FIoDispatcher& IoDispatcher;
    
    // 全局 Import Store (跨包引用解析)
    FGlobalImportStore GlobalImportStore;
    
    // 线程：独立的 Async Loading Thread
    FRunnableThread* Thread;
    
public:
    // 入口：请求加载一个包
    int32 LoadPackage(
        const FString& InName,
        FName InPackageNameToLoad,
        FLoadPackageAsyncDelegate InCompletionDelegate,
        EPackageFlags InPackageFlags,
        int32 InPIEInstanceID,
        int32 InPackagePriority,
        const FLinkerInstancingContext* InstancingContext);
    
    // 主循环 (事件驱动)
    uint32 Run() override;
    
    // Tick: 处理事件队列中的完成事件
    EAsyncPackageState::Type TickAsyncLoadingFromGameThread(
        bool bUseTimeLimit, float TimeLimit);
};
```

```cpp
// ═══════════════════════════════════════════════════════════════
// FAsyncPackage2 — 单个包的加载状态机
// ═══════════════════════════════════════════════════════════════
class FAsyncPackage2
{
    // 包描述信息 (来自 Package Store)
    FPackageStoreEntry StoreEntry;
    
    // 包的所有 Export Bundles
    TArray<FExportBundleEntry> ExportBundles;
    
    // 当前状态
    EAsyncPackageLoadingState2 LoadingState;
    
    // I/O 请求句柄
    FIoRequest IoRequest;
    
    // 已加载的 Export 对象
    TArray<FExportObject> Exports;
    
    // 依赖的其他包
    TArray<FAsyncPackage2*> Dependencies;
    
    // 引用计数
    FThreadSafeCounter RefCount;
    
    // 优先级 (可运行时调整)
    int32 Priority;
    
    // Arena 分配器 (批量内存分配)
    FArenaAllocator ArenaAllocator;
};
```

#### 8.3.4 Package Store — 预计算依赖图

```cpp
// Runtime/CoreUObject/Private/Serialization/PackageStore.h

// Cook 时生成，运行时直接加载
// 避免了 Legacy Loader 运行时解析 Import Table 的开销
struct FPackageStoreEntry
{
    FPackageId PackageId;           // 包的唯一 ID (FName hash)
    
    // 预计算的依赖列表 (Cook 时确定)
    TArray<FPackageId> ImportedPackages;
    
    // Export Bundle 信息
    TArray<FExportBundleHeader> ExportBundleHeaders;
    
    // Export 信息 (类型、名称、外部对象引用)
    TArray<FExportMapEntry> ExportMap;
    
    // 包的 IO Chunk IDs (用于 IO Store 读取)
    TArray<FIoChunkId> ChunkIds;
    
    // 包的大小信息
    uint64 HeaderSize;
    uint64 ExportBundlesSize;
};

// ═══════════════════════════════════════════════════════════════
// FPackageStore — 全局包注册表
// ═══════════════════════════════════════════════════════════════
class FPackageStore
{
    // PackageId → StoreEntry 映射
    TMap<FPackageId, FPackageStoreEntry> StoreEntries;
    
    // 从 .utoc 的 PackageStore chunk 加载
    void LoadContainerHeader(const FIoContainerHeader& Header);
    
    // 查找包信息 (O(1) hash lookup)
    const FPackageStoreEntry* FindStoreEntry(FPackageId PackageId) const;
    
    // 重定向支持 (包重命名/移动)
    TMap<FPackageId, FPackageId> Redirects;
};
```

**Package Store 的优势**：
```
Legacy (UE4):
  LoadPackage("CharacterBP")
  → Open .uasset file
  → Read header
  → Parse ImportTable (逐条解析字符串引用)
  → Resolve each import to actual package (字符串比较!)
  → Recursively load dependencies
  ★ 运行时开销大，字符串操作多 ★

Zen Loader (UE5):
  LoadPackage("CharacterBP")
  → PackageStore.FindStoreEntry(PackageId)  // O(1) hash lookup
  → entry.ImportedPackages[] 已经是 PackageId 列表
  → 直接触发依赖加载，无需解析
  ★ Cook 时已完成所有解析工作 ★
```

#### 8.3.5 Export Bundle — 批量序列化

```
┌──────────────────────────────────────────────────────────────────────────┐
│              Export Bundle Concept                                        │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Legacy (UE4): 每个 Export 独立序列化                                    │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                       │
│  │Export 0 │ │Export 1 │ │Export 2 │ │Export 3 │  ← 逐个读取/反序列化   │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘                       │
│  4 次 I/O + 4 次独立反序列化                                            │
│                                                                          │
│  Zen Loader (UE5): Export 按 Bundle 分组                                 │
│  ┌─────────────────────────────────────────────┐                        │
│  │  Export Bundle 0                            │                        │
│  │  ├── Export 0 (UObject header)              │                        │
│  │  ├── Export 1 (Component A)                 │  ← 1 次 I/O 读取整个  │
│  │  ├── Export 2 (Component B)                 │     Bundle，批量反序列化│
│  │  └── Export 3 (Mesh reference)              │                        │
│  └─────────────────────────────────────────────┘                        │
│  1 次 I/O + 批量反序列化 (可并行)                                       │
│                                                                          │
│  Bundle 分组策略 (Cook 时决定):                                          │
│  ├── 同一个 Actor 的所有 Component → 同一 Bundle                        │
│  ├── 相互引用的 Export → 同一 Bundle                                    │
│  └── 独立的 Export → 可能单独 Bundle (支持按需加载)                     │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

```cpp
// Export Bundle 头信息
struct FExportBundleHeader
{
    // Bundle 中第一个 Export 的索引
    uint32 FirstEntryIndex;
    // Bundle 中 Entry 的数量
    uint32 EntryCount;
};

// Export Bundle Entry (描述 Bundle 内每个操作)
struct FExportBundleEntry
{
    // 对应 ExportMap 中的索引
    uint32 LocalExportIndex;
    // 操作类型
    EExportCommandType CommandType;
    // Create → Serialize → PostLoad 的顺序
};

enum class EExportCommandType : uint32
{
    ExportCommandType_Create,     // 构造 UObject
    ExportCommandType_Serialize,  // 反序列化数据
    ExportCommandType_Count
};
```

#### 8.3.6 FAsyncPackage2 状态机

```
┌──────────────────────────────────────────────────────────────────────────┐
│              FAsyncPackage2 State Machine                                 │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────┐                                                        │
│  │ NewPackage  │  初始状态，刚创建                                       │
│  └──────┬──────┘                                                        │
│         │ 检查 Package Store，确认依赖                                   │
│         ▼                                                                │
│  ┌─────────────────────┐                                                │
│  │ WaitingForIo        │  发起 IO Store 读取请求                        │
│  │                     │  等待 FIoDispatcher 完成回调                    │
│  └──────┬──────────────┘                                                │
│         │ I/O 完成 (事件驱动，非轮询)                                   │
│         ▼                                                                │
│  ┌─────────────────────┐                                                │
│  │ ProcessNewImports   │  处理 Import 引用                              │
│  │                     │  确认依赖包已加载或触发加载                     │
│  └──────┬──────────────┘                                                │
│         │ 所有依赖就绪                                                   │
│         ▼                                                                │
│  ┌─────────────────────┐                                                │
│  │ WaitingForDependencies│ 等待所有依赖包完成                           │
│  └──────┬──────────────┘                                                │
│         │ 依赖全部完成                                                   │
│         ▼                                                                │
│  ┌─────────────────────┐                                                │
│  │ ProcessExportBundles│  ★ 核心阶段 ★                                 │
│  │                     │  遍历 ExportBundleEntries:                      │
│  │                     │  ├── Create: 构造 UObject (NewObject)           │
│  │                     │  └── Serialize: 反序列化属性数据                │
│  │                     │  可在 Worker Thread 并行执行                    │
│  └──────┬──────────────┘                                                │
│         │ 所有 Export 序列化完成                                         │
│         ▼                                                                │
│  ┌─────────────────────┐                                                │
│  │ PostLoad            │  调用 UObject::PostLoad()                      │
│  │                     │  ├── 部分可在 Worker Thread (IsPostLoadThreadSafe)│
│  │                     │  └── 其余必须在 Game Thread                    │
│  └──────┬──────────────┘                                                │
│         │ PostLoad 完成                                                  │
│         ▼                                                                │
│  ┌─────────────────────┐                                                │
│  │ DeferredPostLoad    │  延迟 PostLoad (Game Thread)                   │
│  │                     │  ├── 蓝图编译                                   │
│  │                     │  ├── 组件注册                                   │
│  │                     │  └── 委托广播                                   │
│  └──────┬──────────────┘                                                │
│         │                                                                │
│         ▼                                                                │
│  ┌─────────────────────┐                                                │
│  │ Complete            │  加载完成                                       │
│  │                     │  触发 Completion Delegate                       │
│  │                     │  释放引用计数                                   │
│  └─────────────────────┘                                                │
│                                                                          │
│  ★ 关键区别：Legacy Loader 在每个状态都要轮询检查 ★                    │
│  ★ Zen Loader 通过事件回调自动推进状态 ★                                │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

#### 8.3.7 事件驱动模型

```cpp
// Legacy (UE4) — 轮询模型
// FAsyncLoadingThread::Run()
while (!bShouldStop)
{
    // 每帧轮询所有活跃包的状态
    for (FAsyncPackage* Package : AsyncPackages)
    {
        EAsyncPackageState::Type State = Package->Tick(TimeLimit);
        // Tick 内部检查 I/O 是否完成...
        // 即使没有任何进展也要遍历
    }
    FPlatformProcess::Sleep(0.001f); // 1ms 轮询间隔
}

// ═══════════════════════════════════════════════════════════════
// Zen Loader (UE5) — 事件驱动模型
// FAsyncLoadingThread2::Run()
// ═══════════════════════════════════════════════════════════════
uint32 FAsyncLoadingThread2::Run()
{
    while (!bShouldStop)
    {
        // 阻塞等待事件 (不浪费 CPU)
        EventQueue.Wait();
        
        // 处理所有待处理事件
        while (FAsyncLoadEvent2 Event = EventQueue.Pop())
        {
            switch (Event.Type)
            {
            case EAsyncLoadEvent2::IoComplete:
                // I/O 完成 → 推进对应包的状态
                Event.Package->ProcessIoCompletion(Event.IoBuffer);
                break;
                
            case EAsyncLoadEvent2::DependencyComplete:
                // 依赖完成 → 检查是否可以继续
                Event.Package->OnDependencyLoaded(Event.DependencyPackage);
                break;
                
            case EAsyncLoadEvent2::NewRequest:
                // 新加载请求 → 创建 FAsyncPackage2
                CreateAsyncPackage(Event.PackageId, Event.Priority);
                break;
                
            case EAsyncLoadEvent2::PriorityChange:
                // 优先级变更 → 调整 I/O 优先级
                Event.Package->UpdatePriority(Event.NewPriority);
                break;
            }
        }
        
        // 推进所有可推进的包
        ProcessReadyPackages();
    }
    return 0;
}
```

**事件驱动 vs 轮询的性能差异**：
```
场景：同时加载 100 个包，其中 95 个在等待 I/O

Legacy (轮询):
  每帧遍历 100 个包 × Tick() 开销
  95 个包 Tick 后发现"还没好" → 纯浪费
  CPU 占用：~0.5-1ms/帧 (即使无进展)

Zen Loader (事件):
  只有 I/O 完成的包才会被处理
  95 个等待中的包 → 零 CPU 开销
  CPU 占用：仅在有事件时才工作
  ★ 空闲时 CPU 占用接近 0 ★
```

#### 8.3.8 I/O 批量调度

```cpp
// Zen Loader 的 I/O 请求是批量的
void FAsyncPackage2::StartIoRequests()
{
    // 从 Package Store 获取所有需要的 ChunkIds
    const TArray<FIoChunkId>& ChunkIds = StoreEntry.ChunkIds;
    
    // 创建批量 I/O 请求
    FIoBatch Batch = IoDispatcher.NewBatch();
    
    for (const FIoChunkId& ChunkId : ChunkIds)
    {
        // 每个 Chunk 一个请求，但作为 Batch 一起提交
        FIoReadOptions Options;
        Options.SetPriority(Priority);
        
        Batch.Read(ChunkId, Options, 
            [this, ChunkId](TIoStatusOr<FIoBuffer> Result)
            {
                // ★ I/O 完成回调 → 推送事件到 ALT2 ★
                if (Result.IsOk())
                {
                    EventQueue.Push(FAsyncLoadEvent2{
                        .Type = EAsyncLoadEvent2::IoComplete,
                        .Package = this,
                        .IoBuffer = Result.ConsumeValueOrDie(),
                        .ChunkId = ChunkId
                    });
                }
            });
    }
    
    // 一次性提交所有请求
    // IO Store 后端可以优化读取顺序 (合并相邻读取、NVMe 队列深度利用)
    Batch.Issue();
}
```

**批量 I/O 的优势**：
```
Legacy (逐个请求):
  Read(Export0) → Wait → Read(Export1) → Wait → Read(Export2) → Wait
  NVMe Queue Depth = 1 (严重浪费 NVMe 并行能力)
  3 次 syscall, 3 次上下文切换

Zen Loader (批量请求):
  Batch.Read(Chunk0)
  Batch.Read(Chunk1)
  Batch.Read(Chunk2)
  Batch.Issue()  ← 一次提交
  NVMe Queue Depth = 3 (充分利用 NVMe 并行)
  1 次 syscall (io_uring / IOCP)
  
  ★ NVMe SSD 在 Queue Depth 32 时吞吐量是 QD1 的 4-8 倍 ★
  ★ 批量提交是发挥 NVMe 性能的关键 ★
```

#### 8.3.9 Global Import Store — 跨包引用解析

```cpp
// Runtime/CoreUObject/Private/Serialization/AsyncLoading2.cpp

// 全局 Import Store: 管理所有已加载对象的引用
class FGlobalImportStore
{
    // ScriptObjectPath → UObject* 映射
    // 用于解析跨包引用 (如 /Script/Engine.StaticMeshComponent)
    TMap<FPackageObjectIndex, UObject*> ScriptObjects;
    
    // PackageId + ExportIndex → UObject* 映射
    // 用于解析包间 Export 引用
    struct FPublicExport
    {
        UObject* Object;
        FPackageId SourcePackageId;
        uint32 ExportIndex;
    };
    TMap<FPackageObjectIndex, FPublicExport> PublicExports;
    
public:
    // 注册已加载的对象 (包加载完成时调用)
    void RegisterPublicExport(FPackageObjectIndex Index, UObject* Object);
    
    // 解析引用 (其他包需要引用此对象时)
    UObject* ResolveImport(FPackageObjectIndex Index) const;
};
```

```
跨包引用解析流程:

Package A 引用 Package B 中的 StaticMesh:
  1. Package A 的 ImportMap 中记录: PackageObjectIndex = Hash(B, ExportIdx)
  2. 加载 Package A 时:
     ├── 检查 GlobalImportStore.ResolveImport(Index)
     ├── 如果 B 已加载 → 直接返回 UObject*
     └── 如果 B 未加载 → 触发 B 的加载，A 进入 WaitingForDependencies
  3. Package B 加载完成:
     ├── GlobalImportStore.RegisterPublicExport(Index, MeshObject)
     └── 通知所有等待 B 的包 → 事件推进

★ 对比 Legacy: 运行时通过字符串路径查找 → O(N) 字符串比较
★ Zen Loader: 通过 Hash Index 查找 → O(1) 
```

#### 8.3.10 并行反序列化

```cpp
// ProcessExportBundles 阶段可以并行执行

void FAsyncPackage2::ProcessExportBundles()
{
    for (const FExportBundleHeader& BundleHeader : ExportBundles)
    {
        for (uint32 i = 0; i < BundleHeader.EntryCount; i++)
        {
            const FExportBundleEntry& Entry = 
                ExportBundleEntries[BundleHeader.FirstEntryIndex + i];
            
            switch (Entry.CommandType)
            {
            case EExportCommandType::ExportCommandType_Create:
            {
                // 构造 UObject
                // ★ 可以在 Worker Thread 执行 ★
                const FExportMapEntry& ExportMapEntry = 
                    StoreEntry.ExportMap[Entry.LocalExportIndex];
                
                UObject* Object = StaticConstructObject_Internal(
                    ExportMapEntry.ClassObject,
                    ExportMapEntry.OuterObject,
                    ExportMapEntry.ObjectName);
                
                Exports[Entry.LocalExportIndex].Object = Object;
                break;
            }
            
            case EExportCommandType::ExportCommandType_Serialize:
            {
                // 反序列化属性数据
                // ★ 可以在 Worker Thread 并行执行 ★
                UObject* Object = Exports[Entry.LocalExportIndex].Object;
                
                FMemoryReaderView Ar(IoBuffer.GetView());
                Ar.Seek(ExportOffsets[Entry.LocalExportIndex]);
                
                Object->Serialize(Ar);
                break;
            }
            }
        }
    }
}
```

**并行度分析**：
```
Legacy (UE4):
  Export 0: Create → Serialize ─┐
  Export 1: Create → Serialize ─┤ 全部串行 (单线程)
  Export 2: Create → Serialize ─┤
  Export 3: Create → Serialize ─┘
  总耗时 = Sum(所有 Export 耗时)

Zen Loader (UE5):
  Worker 0: Export 0 Create → Serialize ─┐
  Worker 1: Export 1 Create → Serialize ─┤ 并行执行
  Worker 2: Export 2 Create → Serialize ─┤
  Worker 3: Export 3 Create → Serialize ─┘
  总耗时 ≈ Max(单个 Export 耗时)  (理想情况)

  ★ 实际受限于:
  ★ - Export 间的依赖关系 (Outer/Class 引用)
  ★ - UObject 构造必须在特定线程
  ★ - 某些 Serialize 有线程安全问题
  ★ 实际加速比: 2-4x (取决于包复杂度)
```

#### 8.3.11 优先级系统

```cpp
// Zen Loader 支持运行时动态调整加载优先级

// 优先级定义
namespace EAsyncLoadingPriority
{
    const int32 Highest = 0;      // 立即需要 (同步等待)
    const int32 High = 50;        // 即将需要 (预加载)
    const int32 Normal = 100;     // 正常加载
    const int32 Low = 200;        // 后台预热
    const int32 Lowest = 1000;    // 空闲时加载
}

// 动态调整优先级
void FAsyncPackage2::UpdatePriority(int32 NewPriority)
{
    if (NewPriority < Priority)
    {
        Priority = NewPriority;
        
        // 同时提升所有依赖包的优先级
        for (FAsyncPackage2* Dep : Dependencies)
        {
            if (NewPriority < Dep->Priority)
            {
                Dep->UpdatePriority(NewPriority);
            }
        }
        
        // 通知 IO Dispatcher 调整 I/O 优先级
        if (IoRequest.IsValid())
        {
            IoRequest.UpdatePriority(NewPriority);
        }
    }
}

// 使用场景:
// 玩家走向某个区域 → 该区域资源优先级提升
// 玩家离开某个区域 → 该区域资源优先级降低
// 同步等待某资源 → 优先级提升到 Highest
```

#### 8.3.12 取消加载

```cpp
// Zen Loader 支持完整的加载取消

void FAsyncLoadingThread2::CancelAsyncLoading(int32 RequestId)
{
    FAsyncPackage2* Package = FindPackageByRequestId(RequestId);
    if (!Package) return;
    
    // 取消 I/O 请求 (如果还在等待)
    if (Package->IoRequest.IsValid())
    {
        Package->IoRequest.Cancel();
        // IO Store 后端会尝试取消底层 I/O
        // 已提交到 NVMe 的请求可能无法取消，但结果会被忽略
    }
    
    // 标记为取消
    Package->bCancelled = true;
    
    // 检查是否有其他包依赖此包
    // 如果有 → 不能真正释放，只是标记
    // 如果没有 → 可以立即释放内存
    if (Package->RefCount.GetValue() == 0)
    {
        ReleasePackage(Package);
    }
}

// ★ Legacy Loader 的取消支持非常有限:
// ★ - 一旦开始反序列化就无法取消
// ★ - 取消后可能留下半初始化的对象
// ★ Zen Loader 的取消是干净的:
// ★ - 任何阶段都可以取消
// ★ - Arena 分配器一次性释放所有内存
```

#### 8.3.13 Arena 内存分配

```cpp
// Zen Loader 使用 Arena 分配器减少内存碎片

class FArenaAllocator
{
    // 大块预分配内存
    struct FBlock
    {
        uint8* Memory;
        uint32 Size;
        uint32 Used;
    };
    TArray<FBlock> Blocks;
    
public:
    // 从 Arena 分配 (极快，只是移动指针)
    void* Allocate(size_t Size, size_t Alignment)
    {
        // Bump allocator: O(1)
        FBlock& Current = Blocks.Last();
        uint32 AlignedOffset = Align(Current.Used, Alignment);
        if (AlignedOffset + Size <= Current.Size)
        {
            void* Ptr = Current.Memory + AlignedOffset;
            Current.Used = AlignedOffset + Size;
            return Ptr;
        }
        // 需要新 Block
        return AllocateNewBlock(Size, Alignment);
    }
    
    // 一次性释放所有内存 (包取消或卸载时)
    void FreeAll()
    {
        for (FBlock& Block : Blocks)
        {
            FMemory::Free(Block.Memory);
        }
        Blocks.Empty();
    }
};

// 优势:
// 1. 分配速度: O(1) bump pointer vs O(log N) 通用分配器
// 2. 释放速度: O(1) 整块释放 vs O(N) 逐对象释放
// 3. 缓存友好: 连续内存布局，减少 cache miss
// 4. 无碎片: 整块分配/释放，不产生碎片
```

#### 8.3.14 性能对比数据

```
┌──────────────────────────────────────────────────────────────────────────┐
│              Zen Loader vs Legacy Loader 性能对比                         │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  测试场景: 加载一个大型开放世界关卡 (500+ 资源包)                           │
│  硬件: NVMe SSD, 8 核 CPU                                                │
│                                                                          │
│  ┌────────────────────┬──────────────┬──────────────┬──────────────┐     │
│  │  指标              │  Legacy      │  Zen Loader  │  提升         │    │
│  ├────────────────────┼──────────────┼──────────────┼──────────────┤     │
│  │  总加载时间         │  4.2s        │  1.8s        │  2.3x        │     │
│  │  I/O 等待时间      │  1.5s         │  0.4s        │  3.75x       │     │
│  │  反序列化时间       │  2.0s        │  0.8s        │  2.5x        │     │
│  │  依赖解析时间       │  0.5s        │  0.05s       │  10x         │     │
│  │  PostLoad 时间     │  0.2s        │  0.15s       │  1.3x         │    │
│  │  主线程卡顿         │  50-200ms    │  5-20ms      │  10x         │     │
│  │  ALT CPU 占用      │  15-30%      │  5-10%       │  2-3x        │     │
│  │  NVMe 利用率       │  20-40%      │  70-90%      │  2-3x        │     │
│  │  内存碎片           │  高          │  极低        │  显著        │     │
│  └────────────────────┴──────────────┴──────────────┴──────────────┘    │
│                                                                          │
│  关键提升来源:                                                            │
│  ├── I/O 批量提交 → NVMe 队列深度利用 → I/O 吞吐 3-4x                      │
│  ├── 预计算依赖图 → 无运行时字符串解析 → 依赖解析 10x                       │
│  ├── Export Bundle → 减少 I/O 次数 + 并行反序列化 → 2.5x                  │
│  ├── 事件驱动 → 无轮询开销 → CPU 占用降低                                  │
│  └── Arena 分配 → 减少 malloc/free → 内存操作加速                          │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

#### 8.3.15 Zen Loader 启用条件

```cpp
// Zen Loader 的启用条件:
// 1. UE5 项目
// 2. 使用 IO Store 打包 (Cook 时生成 .utoc/.ucas)
// 3. 项目设置中启用 (默认启用)

// 检查是否使用 Zen Loader:
bool bUseZenLoader = FIoDispatcher::IsInitialized() && 
                     !GEventDrivenLoaderEnabled; // Legacy 开关

// 配置:
// DefaultEngine.ini
[Core.System]
; 强制使用 IO Store (UE5 默认)
IoStoreEnabled=True

// 命令行参数:
// -NoIoStore    → 强制使用 Legacy Pak 加载
// -ZenLoader   → 强制使用 Zen Loader (默认)
// -NoZenLoader → 强制使用 Legacy FLinkerLoad

// ★ 注意: Editor 模式下通常使用 Legacy Loader ★
// ★ 因为 Editor 需要支持热重载、资源修改等 ★
// ★ Cooked Build (打包后) 才使用 Zen Loader ★
```

#### 8.3.16 源码路径索引

```
Zen Loader 核心源码 (UE5):

主调度器:
├── Runtime/CoreUObject/Private/Serialization/AsyncLoading2.cpp
│   └── FAsyncLoadingThread2 — 主循环、事件处理
├── Runtime/CoreUObject/Private/Serialization/AsyncLoading2.h
│   └── FAsyncPackage2 — 包状态机
└── Runtime/CoreUObject/Private/Serialization/AsyncPackageLoader.cpp
    └── 包加载入口

Package Store:
├── Runtime/CoreUObject/Private/Serialization/PackageStore.h
│   └── FPackageStore, FPackageStoreEntry
└── Runtime/CoreUObject/Private/Serialization/PackageStore.cpp
    └── 加载/查询逻辑

Export Bundle:
├── Runtime/CoreUObject/Public/Serialization/AsyncPackage.h
│   └── FExportBundleHeader, FExportBundleEntry
└── Runtime/CoreUObject/Private/Serialization/AsyncLoading2.cpp
    └── ProcessExportBundles()

IO Store 集成:
├── Runtime/Core/Public/IO/IoDispatcher.h
│   └── FIoDispatcher, FIoBatch, FIoRequest
├── Runtime/Core/Private/IO/IoDispatcher.cpp
│   └── 请求调度、完成回调
└── Runtime/Core/Private/IO/IoStore.cpp
    └── .utoc/.ucas 读取

Global Import Store:
└── Runtime/CoreUObject/Private/Serialization/AsyncLoading2.cpp
    └── FGlobalImportStore — 跨包引用解析

Cook 时生成:
├── Developer/IoStoreUtilities/Private/IoStoreUtilities.cpp
│   └── 生成 .utoc/.ucas, Package Store
└── Developer/DerivedDataCache/Private/PackageBuildDependencyTracker.cpp
    └── 依赖图预计算
```

#### 8.3.17 面试常见问题

**Q1: Zen Loader 相比 Legacy Loader 的核心改进是什么？**
```
5 大核心改进:
1. 事件驱动 (非轮询) → CPU 空闲时零开销
2. 批量 I/O (FIoBatch) → 充分利用 NVMe 队列深度
3. Export Bundle → 减少 I/O 次数 + 支持并行反序列化
4. Package Store → 预计算依赖图，消除运行时字符串解析
5. Arena 分配 → 减少内存碎片，加速分配/释放
```

**Q2: Zen Loader 的事件驱动模型是如何工作的？**
```
1. ALT2 线程阻塞在 EventQueue.Wait()
2. I/O 完成时，IO Store 后端触发回调
3. 回调将事件推入 EventQueue
4. ALT2 被唤醒，处理事件，推进对应包的状态
5. 如果包进入新状态需要 I/O → 发起新请求 → 回到步骤 2
★ 对比轮询: 无事件时 CPU 占用为 0，有事件时立即响应
```

**Q3: Export Bundle 是什么？为什么能提升性能？**
```
Export Bundle = Cook 时将相关 Export 打包在一起的数据块
优势:
1. 减少 I/O 次数: 一个 Bundle 一次 I/O (vs 每个 Export 一次)
2. 支持并行: Bundle 内的 Export 可以并行反序列化
3. 缓存友好: 相关数据连续存储，减少 cache miss
4. 预排序: Create/Serialize 顺序在 Cook 时确定，无需运行时排序
```

**Q4: Package Store 解决了什么问题？**
```
Legacy 问题: 运行时解析 Import Table
  - 每个 Import 是字符串路径 (如 "/Game/Meshes/Hero.Hero")
  - 需要字符串比较找到对应包
  - 需要遍历目标包的 Export Table 找到对象
  - O(N×M) 复杂度 (N=imports, M=exports)

Package Store 解决:
  - Cook 时预计算所有依赖关系
  - 运行时通过 PackageId (hash) 直接查找 → O(1)
  - 无字符串操作，无遍历
  - 依赖解析速度提升 10x+
```

**Q5: Zen Loader 在 Editor 中使用吗？**
```
不使用。Editor 使用 Legacy FLinkerLoad，原因:
1. Editor 需要支持资源热重载 (修改后立即生效)
2. Editor 不使用 IO Store (直接读 .uasset 文件)
3. Editor 需要支持 Import/Export 的动态修改
4. Cook 过程本身需要 Legacy Loader 来读取源资源

只有 Cooked Build (打包后的游戏) 才使用 Zen Loader + IO Store。
```

---

## 9. FFileManager

### 9.1 接口

```cpp
// Runtime/Core/Public/HAL/FileManager.h

class IFileManager
{
public:
    static IFileManager& Get();
    
    // Archive creation (for serialization)
    virtual FArchive* CreateFileReader(
        const TCHAR* Filename, 
        uint32 ReadFlags = 0) = 0;
    virtual FArchive* CreateFileWriter(
        const TCHAR* Filename, 
        uint32 WriteFlags = 0) = 0;
    
    // File operations
    virtual bool Delete(const TCHAR* Filename, 
                        bool bRequireExists = false, 
                        bool bEvenReadOnly = false) = 0;
    virtual bool Copy(const TCHAR* Dest, const TCHAR* Src, 
                      bool bReplace = true) = 0;
    virtual bool Move(const TCHAR* Dest, const TCHAR* Src, 
                      bool bReplace = true) = 0;
    
    // Queries
    virtual bool FileExists(const TCHAR* Filename) = 0;
    virtual int64 FileSize(const TCHAR* Filename) = 0;
    virtual bool DirectoryExists(const TCHAR* InDirectory) = 0;
    
    // Find files
    virtual void FindFiles(TArray<FString>& FileNames, 
                           const TCHAR* Filename, 
                           bool bFiles, bool bDirectories) = 0;
    virtual void FindFilesRecursive(
        TArray<FString>& FileNames, 
        const TCHAR* StartDirectory, 
        const TCHAR* Filename, 
        bool bFiles, bool bDirectories) = 0;
};
```

### 9.2 FFileManager 与 IPlatformFile 的关系

```
FFileManager (IFileManager)
  └── Uses FPlatformFileManager::Get().GetPlatformFile()
      └── Returns the topmost IPlatformFile in the chain
          └── Usually FPakPlatformFile

CreateFileReader("path"):
  1. FFileManagerGeneric::CreateFileReader()
  2. → IPlatformFile::OpenRead("path")
  3. → FPakPlatformFile::OpenRead("path")
  4.   → Search in Pak files
  5.   → Or fallthrough to physical FS
  6. → Wrap IFileHandle in FArchiveFileReaderGeneric
  7. → Return FArchive*

Note: FFileManager is the HIGH-LEVEL API
      IPlatformFile is the LOW-LEVEL API
      Most engine code uses FFileManager
      Resource loading uses FLinkerLoad → IPlatformFile directly
```

---

## 10. Mounting 机制

### 10.1 Pak 挂载顺序

```
Pak Mount Order (priority system):

  ┌────────────────────────────────────────────────────────┐
  │  Order │ Pak File              │ Purpose               │
  ├────────┼───────────────────────┼───────────────────────┤
  │  4     │ Patch_001.pak         │ Latest patch (highest)│
  │  3     │ DLC_Map01.pak         │ DLC content           │
  │  2     │ Game_Content.pak      │ Main game content     │
  │  1     │ Engine_Content.pak    │ Engine content        │
  │  0     │ Startup.pak           │ Startup content       │
  └────────────────────────────────────────────────────────┘

  Higher order = checked FIRST
  → Patch can override any file in base game
  → DLC can add new files or override existing

  File lookup: "Textures/T_Hero.uasset"
    Check Patch_001.pak → not found
    Check DLC_Map01.pak → not found
    Check Game_Content.pak → FOUND → use this
    (stop searching)
```

### 10.2 自动挂载

```cpp
// Engine startup auto-mounts paks from:
// 1. <ProjectDir>/Content/Paks/
// 2. <ProjectDir>/Saved/Paks/  (downloaded content)
// 3. Command line: -pakdir=<path>

void FPakPlatformFile::Initialize(IPlatformFile* Inner, 
                                   const TCHAR* CmdLine)
{
    // Auto-discover and mount pak files
    TArray<FString> PakFolders;
    GetPakFolders(CmdLine, PakFolders);
    
    for (const FString& PakFolder : PakFolders)
    {
        TArray<FString> PakFiles;
        FindAllPakFiles(PakFolder, PakFiles);
        
        // Sort by name (alphabetical → determines priority)
        PakFiles.Sort();
        
        for (const FString& PakFile : PakFiles)
        {
            // Mount with auto-calculated order
            int32 PakOrder = GetPakOrderFromFilename(PakFile);
            Mount(*PakFile, PakOrder);
        }
    }
}

// Pak order from filename:
// "pakchunk0-platform.pak" → order 0
// "pakchunk1-platform.pak" → order 1
// "pakchunk99-platform.pak" → order 99
// "*_P.pak" (patch) → order + 1000
// Higher chunk number = higher priority
```

### 10.3 运行时挂载 (DLC/Hotfix)

```cpp
// Mount a downloaded DLC pak at runtime
bool MountDLCPak(const FString& PakPath)
{
    FPakPlatformFile* PakPlatformFile = 
        (FPakPlatformFile*)(FPlatformFileManager::Get()
            .FindPlatformFile(TEXT("PakFile")));
    
    if (PakPlatformFile)
    {
        // Mount with high priority (overrides base content)
        const int32 PakOrder = 1000; // High priority
        
        if (PakPlatformFile->Mount(*PakPath, PakOrder))
        {
            // Register mount point for asset registry
            FPackageName::RegisterMountPoint(
                TEXT("/DLC/"), 
                FPaths::GetPath(PakPath));
            
            // Scan for new assets
            FAssetRegistryModule& AssetRegistry = 
                FModuleManager::LoadModuleChecked<FAssetRegistryModule>(
                    "AssetRegistry");
            AssetRegistry.Get().ScanPathsSynchronous(
                {TEXT("/DLC/")}, true);
            
            return true;
        }
    }
    return false;
}
```

---

## 11. 加密与签名

### 11.1 AES 加密

```
Pak Encryption:
  - AES-256-CBC encryption
  - Can encrypt: index, individual files, or both
  - Key identified by GUID (EncryptionKeyGuid in FPakInfo)

  Encryption scope:
  ┌────────────────────────────────────────────────────────┐
  │  Level          │ What's encrypted                     │
  ├─────────────────┼──────────────────────────────────────┤
  │  Index only     │ File listing (names, offsets)        │
  │                 │ Data is readable but you don't know  │
  │                 │ what files exist                     │
  ├─────────────────┼──────────────────────────────────────┤
  │  Data only      │ File contents                        │
  │                 │ Index is readable (file names visible)│
  ├─────────────────┼──────────────────────────────────────┤
  │  Index + Data   │ Everything encrypted                 │
  │                 │ Maximum security                     │
  └─────────────────┴──────────────────────────────────────┘
```

```cpp
// Key registration
void RegisterEncryptionKey(const FGuid& Guid, const FAES::FAESKey& Key)
{
    FPakPlatformFile* PakPlatformFile = ...;
    PakPlatformFile->RegisterEncryptionKey(Guid, Key);
}

// Decryption during read
void DecryptData(uint8* Data, int64 Size, const FAES::FAESKey& Key)
{
    // AES-256 operates on 16-byte blocks
    check(Size % FAES::AESBlockSize == 0);
    FAES::DecryptData(Data, Size, Key);
}
```

### 11.2 签名验证

```
Pak Signing:
  - RSA signature of chunk hashes
  - Verifies pak file integrity (anti-tamper)
  - Separate .sig file alongside .pak

  Verification:
  1. Read .sig file → RSA signature + chunk hashes
  2. Verify RSA signature with public key
  3. On each chunk read → compute SHA1
  4. Compare with signed hash → tamper detection

  If verification fails:
  → FPakPlatformFile::BroadcastPakChunkSignatureCheckFailure()
  → Game can handle (crash, disconnect, report)
```

---

## 12. Shader / Bulk Data 特殊处理

### 12.1 Shader Code Library

```
Shader Code Library:
  Shaders are NOT stored in regular .uasset files
  Instead: ShaderArchive-*.ushaderbytecode

  ┌────────────────────────────────────────────────────────┐
  │  FShaderCodeLibrary                                    │
  │  ├── Stores compiled shader bytecode                   │
  │  ├── Indexed by shader hash (FSHAHash)                 │
  │  ├── Shared across all materials using same shader     │
  │  ├── Loaded from Pak or IO Store                       │
  │  └── Platform-specific format (DXBC, SPIR-V, Metal)    │
  │                                                        │
  │  In IO Store: EIoChunkType::ShaderCodeLibrary          │
  │  In Pak: ShaderArchive-<Platform>.ushaderbytecode      │
  └────────────────────────────────────────────────────────┘
```

### 12.2 Bulk Data

```
Bulk Data:
  Large data (textures, audio, animation) stored separately
  from UObject serialization data

  Types:
  ┌────────────────────────────────────────────────────────┐
  │  FByteBulkData:                                        │
  │  ├── Inline: stored in .uasset (small data)            │
  │  ├── End-of-file: appended to .uasset                  │
  │  ├── Separate file: .ubulk file                        │
  │  ├── Optional: .uptnl file (optional download)         │
  │  └── Memory-mapped: .m.ubulk (direct mmap)             │
  │                                                        │
  │  Loading modes:                                        │
  │  ├── BULKDATA_PayloadAtEndOfFile                       │
  │  ├── BULKDATA_PayloadInSeperateFile                    │
  │  ├── BULKDATA_OptionalPayload                          │
  │  ├── BULKDATA_MemoryMappedPayload                      │
  │  └── BULKDATA_ForceInlinePayload                       │
  └────────────────────────────────────────────────────────┘

  In IO Store:
    Bulk data → separate FIoChunkId
    EIoChunkType::BulkData
    EIoChunkType::OptionalBulkData
    EIoChunkType::MemoryMappedBulkData
```

---

## 13. 平台差异

```
┌─────────────────────────────────────────────────────────────────┐
│  Platform-Specific File System Implementations                  │
├──────────────┬──────────────────────────────────────────────────┤
│  Platform    │  Details                                         │
├──────────────┼──────────────────────────────────────────────────┤
│  Windows     │  FWindowsPlatformFile                            │
│              │  CreateFileW / ReadFile / WriteFile              │
│              │  Overlapped I/O for async                        │
│              │  Memory-mapped files supported                   │
│              │  Long path support (\\?\)                        │
├──────────────┼──────────────────────────────────────────────────┤
│  Linux       │  FLinuxPlatformFile                              │
│              │  open / pread / pwrite (thread-safe)             │
│              │  io_uring for async (kernel 5.1+)                │
│              │  mmap for memory-mapped files                    │
├──────────────┼──────────────────────────────────────────────────┤
│  Android     │  FAndroidPlatformFile                            │
│              │  APK assets via AAssetManager                    │
│              │  OBB files as regular files                      │
│              │  ★ APK files: read-only, offset-based access ★  │
│              │  Storage: internal + external + OBB              │
├──────────────┼──────────────────────────────────────────────────┤
│  iOS         │  FApplePlatformFile                              │
│              │  POSIX + dispatch_io for async                   │
│              │  App bundle is read-only                         │
│              │  Documents dir for writable storage              │
├──────────────┼──────────────────────────────────────────────────┤
│  Consoles    │  Platform-specific (NDA)                         │
│              │  PS5: custom SSD API (ultra-fast)                │
│              │  Xbox: Win32 subset                              │
│              │  Switch: nn::fs                                  │
└──────────────┴──────────────────────────────────────────────────┘
```

---

## 14. 性能优化

### 14.1 优化策略

```
┌──────────────────────────────────────────────────────────────────┐
│  Performance Optimization Strategies                             │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Pak Chunk Organization                                       │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  Group related assets into same pak chunk              │      │
│  │  ├── pakchunk0: Engine + startup content               │      │
│  │  ├── pakchunk1: Main menu + UI                         │      │
│  │  ├── pakchunk2: Level 1 assets                         │      │
│  │  ├── pakchunk3: Level 2 assets                         │      │
│  │  └── pakchunkN: DLC content                            │      │
│  │                                                        │      │
│  │  Benefits:                                             │      │
│  │  ├── Sequential reads within chunk                     │      │
│  │  ├── Only load needed chunks                           │      │
│  │  └── Better download granularity                       │      │
│  └────────────────────────────────────────────────────────┘      │
│                                                                  │
│  2. Compression Selection                                        │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  Oodle (UE5 default): Best ratio + speed balance       │      │
│  │  LZ4: Fastest decompression (streaming)                │      │
│  │  None: For SSD/NVMe (I/O faster than decompression)    │      │
│  │  Zlib: Legacy, avoid in new projects                   │      │
│  └────────────────────────────────────────────────────────┘      │
│                                                                  │
│  3. IO Store Benefits (UE5)                                      │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  ├── Batch I/O: submit multiple reads at once          │      │
│  │  ├── Aligned reads: no partial sector reads            │      │
│  │  ├── Reduced overhead: no per-file headers             │      │
│  │  ├── Better NVMe utilization: deep queue depth         │      │
│  │  └── Pre-computed dependencies: faster loading         │      │
│  └────────────────────────────────────────────────────────┘      │
│                                                                  │
│  4. Memory-Mapped Files                                          │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  For uncompressed bulk data (textures, audio):         │      │
│  │  ├── mmap instead of read+copy                         │      │
│  │  ├── OS handles page faults → demand paging            │      │
│  │  ├── Zero-copy: GPU can read directly                  │      │
│  │  └── .m.ubulk files for memory-mapped bulk data        │      │
│  └────────────────────────────────────────────────────────┘      │
│                                                                  │
│  5. Preloading & Prioritization                                  │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  ├── Priority system for async loads                   │      │
│  │  ├── Preload hints during loading screens              │      │
│  │  ├── Streaming levels: load before player arrives      │      │
│  │  └── Shader pre-compilation during splash              │      │
│  └────────────────────────────────────────────────────────┘      │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 15. 面试高频问题

### Q1: UE 的文件系统是如何分层的？

```
UE 文件系统采用责任链模式 (Chain of Responsibility)：

  FPakPlatformFile → [FSandboxPlatformFile] → FPhysicalPlatformFile

  每层实现 IPlatformFile 接口
  文件查找从最上层开始，找到则返回，找不到则转发给下一层
  FPakPlatformFile 拦截 Pak 文件中的内容
  FPhysicalPlatformFile 访问真实 OS 文件系统

  上层代码通过 IFileManager 或 IPlatformFile 接口访问
  完全透明，不关心文件来自 Pak 还是磁盘
```

### Q2: Pak 文件的格式是什么？如何读取？

```
Pak 文件格式：
  [Data Section] [Index Section] [Footer (FPakInfo)]

  Footer 在文件末尾，固定大小，包含：
  - Magic number (0x5A6F12E1)
  - Version, IndexOffset, IndexSize, Hash

  读取流程：
  1. Seek to end - sizeof(FPakInfo) → read footer
  2. Validate magic number
  3. Seek to IndexOffset → read index (file entries)
  4. Each entry: filename + offset + size + compression info
  5. 读取文件：seek to entry.offset → read data → decompress if needed

  压缩：block-based (64KB blocks)
  → 支持随机访问（只解压需要的 block）
```

### Q3: IO Store 和 Pak 的区别？

```
Pak (.pak):
  - 基于文件名字符串查找
  - 单文件句柄，顺序读取
  - 每个文件独立的压缩块
  - UE4 + UE5 都支持

IO Store (.utoc + .ucas):
  - 基于 FIoChunkId (96-bit hash) 查找
  - FIoDispatcher 批量异步 I/O
  - 全局压缩块表，扇区对齐
  - 充分利用 NVMe 队列深度
  - UE5 Zen Loader 专用

核心改进：从"按文件读取"变为"按 chunk 批量读取"
适合现代 SSD/NVMe 的高并发 I/O 模型
```

### Q4: Pak 的 Mount 机制是什么？如何实现热更新？

```
Mount 机制：
  每个 Pak 有一个 ReadOrder (优先级)
  查找文件时从高优先级到低优先级遍历
  第一个找到的结果被使用

热更新实现：
  1. 下载 Patch.pak (高优先级)
  2. 运行时 Mount: FPakPlatformFile::Mount("Patch.pak", 1000)
  3. Patch.pak 中的文件自动覆盖基础包中的同名文件
  4. 注册新的 mount point
  5. 扫描 Asset Registry 发现新资源

  无需修改基础包，只需添加高优先级的 Patch Pak
```

### Q5: 异步加载的流程？PostLoad 为什么必须在主线程？

```
异步加载流程：
  1. Game Thread: LoadPackageAsync() → 创建 FAsyncPackage
  2. Async Loading Thread:
     CreateLinker → FinishLinker → CreateImports →
     CreateExports → PreLoad (deserialize)
  3. Game Thread: PostLoad()
  4. Complete: fire callbacks

PostLoad 必须在主线程的原因：
  - PostLoad 可能访问/修改其他 UObject
  - UObject 不是线程安全的
  - PostLoad 可能触发 GC、注册组件、修改 World
  - 蓝图 PostLoad 可能执行蓝图代码
  - 这是加载卡顿的主要来源

优化：
  - 减少 PostLoad 中的重计算
  - 使用 Async PostLoad (UE5 部分支持)
  - 在 loading screen 时提高 time budget
```

### Q6: Pak 加密是如何工作的？

```
Pak 加密：
  - AES-256-CBC 加密
  - 可以加密 Index（文件列表）和/或 Data（文件内容）
  - 每个 Pak 有一个 EncryptionKeyGuid
  - 运行时注册 Key: RegisterEncryptionKey(Guid, Key)
  - 读取时自动解密（在解压之前）

签名：
  - RSA 签名验证 Pak 完整性
  - .sig 文件包含 chunk hash 的签名
  - 防篡改：修改 Pak 内容会导致签名验证失败
```

---

## 16. 完整调用流程图

### 16.1 从 LoadObject 到磁盘读取

```
┌────────────────────────────────────────────────────────────────────────┐
│              Complete Call Flow: LoadObject → Disk Read                │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  UObject* Obj = LoadObject<UTexture2D>(                                │
│      nullptr, TEXT("/Game/Textures/T_Hero"));                          │
│  │                                                                     │
│  ├── StaticLoadObject()                                                │
│  │   └── StaticLoadObjectInternal()                                    │
│  │       └── LoadPackage()                                             │
│  │           └── LoadPackageInternal()                                 │
│  │               │                                                     │
│  │               ├── 1. Create FLinkerLoad                             │
│  │               │   └── FLinkerLoad::CreateLinker()                   │
│  │               │       └── CreatePackageReader()                     │
│  │               │           └── IFileManager::CreateFileReader()      │
│  │               │               └── FPakPlatformFile::OpenRead()      │
│  │               │                   ├── Search Pak index              │
│  │               │                   │   PathHash → FPakEntry          │
│  │               │                   └── Create FPakFileHandle         │
│  │               │                                                     │
│  │               ├── 2. Read Package Summary                           │
│  │               │   └── FLinkerLoad::LoadAndVerifyLinkerAttachments() │
│  │               │       ├── Read FPackageFileSummary                  │
│  │               │       │   (magic, version, name count, etc.)        │
│  │               │       ├── Read NameMap (FName table)                │
│  │               │       ├── Read ImportMap (external references)      │
│  │               │       └── Read ExportMap (objects in this package)  │
│  │               │                                                     │
│  │               ├── 3. Resolve Imports                                │
│  │               │   └── For each import:                              │
│  │               │       ├── Find/load dependency package              │
│  │               │       └── Resolve to UObject*                       │
│  │               │                                                     │
│  │               ├── 4. Create & Serialize Exports                     │
│  │               │   └── For each export:                              │
│  │               │       ├── Allocate UObject                          │
│  │               │       ├── Seek to export data offset                │
│  │               │       │   └── FPakFileHandle::Seek()                │
│  │               │       ├── Deserialize                               │
│  │               │       │   └── UObject::Serialize(FArchive&)         │
│  │               │       │       └── FArchive::Serialize()             │
│  │               │       │           └── FPakFileHandle::Read()        │
│  │               │       │               ├── Seek in pak file          │
│  │               │       │               ├── Read compressed block     │
│  │               │       │               ├── AES decrypt (if needed)   │
│  │               │       │               ├── Decompress (Oodle/Zlib)   │
│  │               │       │               └── Copy to output buffer     │
│  │               │       └── PostLoad()                                │
│  │               │                                                     │
│  │               └── 5. Return loaded UObject*                         │
│  │                                                                     │
│  └── Return UTexture2D*                                                │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### 16.2 源码文件映射

```
┌───────────────────────────────────────────────────────────────────────┐
│  Key Source Files                                                     │
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  Core File System:                                                    │
│  ├── Runtime/Core/Public/HAL/IPlatformFile.h                          │
│  ├── Runtime/Core/Public/HAL/PlatformFileManager.h                    │
│  ├── Runtime/Core/Public/HAL/FileManager.h                            │
│  ├── Runtime/Core/Private/HAL/FileManagerGeneric.cpp                  │
│  └── Runtime/Core/Public/GenericPlatform/GenericPlatformFile.h        │
│                                                                       │
│  Pak File System:                                                     │
│  ├── Runtime/PakFile/Public/IPlatformFilePak.h                        │
│  ├── Runtime/PakFile/Private/IPlatformFilePak.cpp                     │
│  ├── Runtime/PakFile/Public/IoDispatcherFileBackend.h                 │
│  └── Runtime/PakFile/Private/IoDispatcherFileBackend.cpp              │
│                                                                       │
│  IO Store (UE5):                                                      │
│  ├── Runtime/Core/Public/IO/IoDispatcher.h                            │
│  ├── Runtime/Core/Private/IO/IoDispatcher.cpp                         │
│  ├── Runtime/Core/Public/IO/IoStore.h                                 │
│  └── Runtime/Core/Private/IO/IoStore.cpp                              │
│                                                                       │
│  Async Loading:                                                       │
│  ├── Runtime/CoreUObject/Public/UObject/LinkerLoad.h                  │
│  ├── Runtime/CoreUObject/Private/UObject/LinkerLoad.cpp               │
│  ├── Runtime/CoreUObject/Public/Serialization/AsyncLoading.h          │
│  ├── Runtime/CoreUObject/Private/Serialization/AsyncLoading.cpp       │
│  ├── Runtime/CoreUObject/Private/Serialization/AsyncLoading2.cpp      │
│  │   (Zen Loader, UE5)                                                │
│  └── Runtime/CoreUObject/Private/Serialization/AsyncPackageLoader.cpp │
│                                                                       │
│  Platform-Specific:                                                   │
│  ├── Runtime/Core/Private/Windows/WindowsPlatformFile.cpp             │
│  ├── Runtime/Core/Private/Linux/LinuxPlatformFile.cpp                 │
│  ├── Runtime/Core/Private/Android/AndroidPlatformFile.cpp             │
│  └── Runtime/Core/Private/Apple/ApplePlatformFile.cpp                 │
│                                                                       │
│  Compression:                                                         │
│  ├── Runtime/Core/Public/Compression/CompressedBuffer.h               │
│  ├── Runtime/Core/Private/Compression/OodleDataCompression.cpp        │
│  └── ThirdParty/Oodle/                                                │
│                                                                       │
│  Encryption:                                                          │
│  ├── Runtime/Core/Public/Misc/AES.h                                   │
│  └── Runtime/Core/Private/Misc/AES.cpp                                │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 参考

```
• Unreal Engine Source: Runtime/PakFile/, Runtime/Core/Public/IO/
• Epic Games, "Unreal Engine Pak File System" Documentation
• Epic Games, "IO Store" Technical Blog
• Epic Games, "Zen Loader" GDC Presentation
• Unreal Engine 5 Source Code (5.0-5.4)
```