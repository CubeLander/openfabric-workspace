# Vendor ExeBlock And Subtask Struct Definitions

The simulator component serializers `exeBlock_conf_info_t` and
`sub_task_conf_info_t` carry the vendor dataflow graph ABI, including PE-local
block dependencies, leaf-node state, stage PCs, instance counts, and embedded
exeBlock rows.

## Struct Definitions

From vendor header `pe_com_def.h`:

```c
typedef struct _successor_t {
    position_t pe_pos;
    uint64_t block_idx;
    uint64_t valid;
} successor_t;

typedef successor_t predecessor_t;
```

```c
typedef struct _exeBlock_conf_t {
    uint64_t req_activations;
    char has_stages[MAX_COMPONENT_AMOUNT];
    uint64_t stages_start_pc[MAX_COMPONENT_AMOUNT];
    predecessor_t predecessors[MAX_PREDECESSOR_AMOUNT];
    successor_t successors[MAX_SUCCESSOR_AMOUNT];
    uint64_t block_idx;
    uint64_t subtask_idx;
    uint64_t task_idx;
    uint64_t instances_amount;
    uint64_t child_amount;
    uint64_t block_class;
    uint64_t inst_mem_based_addr;
    uint64_t ld_stage_inst_amount;
    uint64_t cal_stage_inst_amount;
    uint64_t flow_stage_inst_amount;
    uint64_t st_stage_inst_amount;
    char is_leaf;
} exeBlock_conf_t;
```

```c
typedef struct _exeBlock_conf_info_t {
    char valid;
    uint64_t block_idx;
    position_t pe_dst;
    uint64_t priority;
    exeBlock_conf_t exeBlock_conf;
} exeBlock_conf_info_t;
```

```c
typedef struct _sub_task_conf_info_t {
    char is_exe_start;
    char is_exe_end;
    uint64_t instances_amount;
    uint64_t instances_conf_mem_based_addr;
    uint64_t suc_subtasks[MAX_SUBTASK_FOLLOW_PER_SUBTASK];
    uint64_t root_block_amount;
    uint64_t block_amount;
    exeBlock_conf_info_t exeBlocks_conf_info[MAX_EXE_BLOCK];
    uint64_t subtask_idx;
    uint64_t task_idx;
} sub_task_conf_info_t;
```

## Observed Struct Sizes

```text
exeBlock_conf_info_t: 520 bytes
sub_task_conf_info_t: 266328 bytes
```

`sub_task_conf_info_t` is large because it embeds `512 * exeBlock_conf_info_t`:

```text
512 * 520 = 266240 bytes
```

The remaining 88 bytes are subtask-level flags, instance metadata, successor
subtasks, root/block counts, and task/subtask indices.

## Graph Edge Encoding

Three related but distinct concepts exist in the vendor flow:

### 1. Placement Sentinel: `GRAPH_NODE::m_pos_idx_df`

`m_pos_idx_df = 0xFFFFFFFF` means "no fixed PE placement before mapping".
After PE index is chosen, the node gets a concrete position. This is only a
pre-mapping placement sentinel, not the runtime predecessor/successor ABI.

### 2. Relationship `type`: Selecting COPY Arcs In Templates

`set_relationship_node(parent, child, type)` records logical parent/child
relationships and scans FLOW-stage instructions. `0xffffffff` is used for
local dependency edges that don't select a numbered COPY arc. Cross-PE COPY
relationships use small numbered type values (0, 1).

### 3. Final ExeBlock Predecessor/Successor ABI

The final runtime graph ABI is explicit and PE-local:

```c
typedef struct _successor_t {
    position_t pe_pos;
    uint64_t block_idx;
    uint64_t valid;
} successor_t;
```

Invalid slots are zeroed and gated by `valid`, not by `0xffffffff`.

## COPY Destination Rewriting

After mapping, the vendor flow rewrites COPY instructions to real destinations:

```c
pCopy_inst->inst.dst_blocks_idx[0] = pChild_node->m_pos.block_idx;
pCopy_inst->inst.dst_pes_pos[0].x = pChild_node->m_pos.x;
pCopy_inst->inst.dst_pes_pos[0].y = pChild_node->m_pos.y;
```

## Stage Fields

Stage order is LD, CAL, FLOW, ST, END. `has_stages[]` marks which segments
are present, `stages_start_pc[]` records each segment's PE-local PC range:

```c
pExeBlock_conf->stages_start_pc[LD_COMPONENT_IDX] = inst_start_pos;
if (ld_inst_amount > 0) {
    pExeBlock_conf->has_stages[LD_COMPONENT_IDX] = true;
    inst_start_pos += ld_inst_amount;
}
```

## Correct Lowering Order

```text
DFU Graph Skeleton
  -> vendor graph edge / leaf projection
  -> vendor exeBlock stage PC plan
  -> exeBlock_conf_info_t byte serializer
  -> sub_task_conf_info_t byte serializer
```

`sub_task_conf_info_t` serialization must come after `exeBlock_conf_info_t`,
because each subtask row embeds the final exeBlock rows.
