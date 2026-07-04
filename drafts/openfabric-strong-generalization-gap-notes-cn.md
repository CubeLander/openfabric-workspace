# OpenFabric 强泛化剩余缺口

Status: active gap list.

这份文件只保留还没完全落实的强泛化方向。已经落地或已沉淀到 `docs/` 的历史推理
不再留在 draft 里。

## 已经落地的方向

- GEMM+ReLU 把 ReLU 表达为 plan-declared unary op 和 storage alias，而不是 GEMM
  尾部私有分支。
- `OpenFabricRuntimeActionPlan`、RuntimePlanImage、image interpreter、common
  RISC-V executor trace gate 已经成为 runtime 顺序安全绳。
- `TensorAccessRef`、`TensorAccessSpmBinding`、`RuntimeSpmWindowProjection`、
  `StageBaseRowProjection`、`TileMemoryAccess` 已经把地址消费者边界显式化。
- common site/value/operand 层已经覆盖 `SubtaskSiteBase`、`ContextTileView`、
  `FiberEndpoint`、`InstructionBlockRef` 和 operand allocator。
- dump-only address explanation harness 已完成历史使命并已从 config generation 中
  移除；长期检查依赖 replay、support binary、RuntimePlanImage trace 和 source-owned
  projections。

## 仍然开放的缺口

1. **ChipProgramPlan 薄入口**

   当前 `DistributedPlan`、runtime action plan、graph trace、artifact wiring 仍由各
   算子入口组合。下一步不是设计大 IR，而是提供薄入口：

   ```text
   ChipProgramPlan {
     DistributedPlan device;
     RuntimeActionPlan runtime;
     ArtifactManifest artifacts;
   }
   ```

2. **StageShard / TileAccessPlan**

   GEMM/GEMM+ReLU 的 stage base row、ReLU window、CSV tile access 已经有公共投影积木，
   但 subtask/stage intent 到 tensor window scopes 的映射还在 GEMM 分支里。下一步
   应先服务 base-row/CSV address binding，不做自动 scheduler。

3. **CollectivePlan**

   GEMM A broadcast、softmax partial summary、log10max naive global max 都说明 route /
   reduce / broadcast 需要一等表达。当前不要把 COPYT 或 reduce 伪装成普通 PE-local
   fiber op；先保留显式 topology / endpoint / graph evidence。

4. **ArtifactManifest**

   CMake/replay 仍知道太多算子产物路径。后续新算子需要声明哪些 artifacts 必须生成、
   哪些 trace/check 要跑、哪些 vendor surfaces 是比较权威。

5. **GEMM tile FiberOp**

   `gemm_tile -> optional epilogue -> store_tile` 仍是正确目标，但当前不急着实现
   `ChipProgramPlan -> fiber actions` 自动 lowering。GEMM fiber action 先继续作为
   operator-authored materializer。

## 暂缓

```text
ChipProgramPlan / StagePlan / TensorAccess
  -> automatic target fiber actions
  -> automatic CSV rows / instance rows / graph edges
```

自动 lowering 需要先有稳定的 stage access、tile value、collective、address lifetime、
artifact manifest 和 target capability registry。现在继续用 comparison-backed 的
operator-authored lowering 更稳。
