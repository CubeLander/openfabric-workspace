# Vendor Node Traversal Order 与 Operand Counter 分析

Date: 2026-06-16

## 核心发现

Vendor GEMM 的 operand 分配使用**单计数器**模式，不是 seed 表的分组递减模式。

### Vendor 分配模型

```text
每 (task, PE) 一个 Task_Resource
  → 一个 reg_idx_counter
  → 跨 subtask1/subtask2/subtask3 共享
  → 新 tag: operand_idx = layout_operand_idx(counter + reg_start_idx)
  → counter++
```

`layout_operand_idx(raw) = (raw % 12) * 128 + raw / 12`

### 与 Seed 表的关键差异

| | Vendor | Seed 表 |
|---|---|---|
| 计数器 | 一个连续计数器跨所有 subtask | 每个 block 独立预分配 |
| 分配模式 | interleaved: 0, 128, 256, 384... | 分组递减: 639, 638, 637... |
| input0_0_15 | counter=33 → idx=111 (group 0) | idx=623 (group 1) |
| 差异 | - | +512 = 1 tensor group |

### Vendor subtask2 节点结构 (from generateGraph)

```text
subtask2 (compute, instance_times=4):
  nodes 0-3:   ld-A (PE 0,4,8,12 only)
  nodes 4-7:   cp-A (PE 0,1,2,3 only, first per row)
  nodes 8-23:  ld-B+cal (all 16 PEs)
```

PE00 的节点: node0 (ld-A), node4 (cp), node20 (compute)

### PE00 task0 的 counter 轨迹

```text
subtask1 (16 accumulator_prepare nodes, all PEs):
  PE00 processes node0 → tags: output0_0_0..15, ALPHA, BET
  counter: 0 → 18

subtask2 (PE00 processes nodes 0, 4, 20):
  node0 (ld-A) → CSV template tags (may reuse or allocate)
  node4 (cp)   → CSV template tags
  node20 (compute) → input0_0_0..15 = NEW tags
    counter: 18 → 34
    input0_0_15: counter=33, layout(33) = (33%12)*128 + 33/12 = 9*128+2 = 1154
```

### OpenFabric 的 block 排序

```text
_block_sort_key = (task_index, processor, subtask_index, instance_key, micro_block_order, id)
```

PE00 task0 的 block 顺序:
```text
[0]  subtask0 prepare        (accumulator_prepare)
[1]  subtask1 k0             (route_source_materialize)
[2]  subtask1 k0             (route_source_materialize)
[3]  subtask1 k0             (route_forward)
[4]  subtask1 k0             (route_forward)
[5]  subtask1 k0             (compute_update)
[6-10]  subtask1 k1          (same pattern)
[11-15] subtask1 k2
[16-20] subtask1 k3
[21] subtask2 final          (tile_store)
```

### 正确的 replay pass 策略

1. 对每个 (task, PE)，按 vendor node 顺序收集所有 template instructions
2. 用单个 counter 顺序分配，layout_operand_idx(counter)
3. 新 tag 首次遇到时分配，后续遇到返回已分配值
4. COPY destination 从 receiver (child) 的 tag map 获取
5. pseudo-tensor 展开：base operand + lane * 128
