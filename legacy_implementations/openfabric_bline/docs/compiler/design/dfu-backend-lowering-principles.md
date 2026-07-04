# DFU Backend Lowering Principles

## Two-Layer Lowering Design

The backend should use two layers for lowering:

```text
TileAction / RouteAction
  -> DFUAssemblyRecord (symbolic)
  -> DFUBinaryInstruction (binary)
```

`DFUAssemblyRecord` is a structured record, not a text `.s` file:

```text
opcode=HMMAL
role=gemm_inner_update
source_step=K_TILE_STEP:PE00:task0:inst3
source_route=-
pe=PE00
task=0
subtask=2
instance=3
dst_operand=...
src_operands=...
base_addr_idx=...
offset=...
dtype=...
shape_or_lane_view=...
```

Benefits:
- Easy to dump, diff, and explain.
- Easy to validate against legacy CSV and instruction documents.
- Keeps binary encoding as a narrow target-specific pass.
- Lets symbolic backends be built before every bitfield is confirmed.

## Operand Slots And Base Address Relocation

The DFU execution model uses instance base tables and instruction offsets:

```text
addr = base_addr[base_addr_idx] + imm_offset
```

The compiler should avoid baking absolute tensor addresses into instructions
when instance base tables can carry the runtime address variation.

## Hard Backend Principles

1. **DFUAssemblyRecord is the target-level fact source.**

   Every generated record must be traceable back to the semantic object:

   ```text
   KTileStep / RouteEdge / TileStore
     -> DFUAssemblyRecord
     -> binary encoding
   ```

2. **Task/subtask/instance packing is an independent pass.**

   Packing is a scheduling and resource-allocation problem, not an encoder
   formatting detail. The binary encoder must not opportunistically decide
   task boundaries, subtask boundaries, instance loops, or base table
   assignment.

3. **The binary encoder must stay narrow.**

   Its responsibility is only:

   ```text
   DFUAssemblyRecord -> bitfields / bytes
   ```

   It must not infer semantic roles, choose routes, allocate operands,
   assign base addresses, pack tasks, or rewrite tensor schedules.

## Compute vs Route Separation

```text
gemm_tile_update -> HMMAL/...  answers how a PE computes.
route edge -> COPY/COPYT/DMA   answers how a value becomes visible to a PE group.
```

They should remain separate backend methods and separate debug surfaces.

## DFU Hardware Constraints

```text
task <= 4
subtask <= 8 per task
instance table <= 2048 entries per subtask
PE instruction buffer and operand/register resources are finite
```
