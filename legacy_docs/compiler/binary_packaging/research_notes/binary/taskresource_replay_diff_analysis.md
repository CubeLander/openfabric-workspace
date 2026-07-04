# TaskResource Replay Pass — arch-13 Diff 分析

Date: 2026-06-16

## 1. 当前 diff 数据

arch-13 对比结果 (`tmp/diff_16_1036.md`):

```text
cbuf sha256 local  = 71d8b0218653551fc543ab1cd5bb7a1cf7b1480237a09c163fcfa0fcf6c185cb
cbuf sha256 remote = c0911c6146a44a779dd1cae2aec583088197a8b057b79bb3e6fdce568b456a6e
diff_byte_count = 14944
micc sha256 = ab56e64bff6f0d9b469146ef04d4584c2597f4bcbb1b951d49c43601eb2a9980 (MATCH)
```

## 2. Diff 分类

所有 diff 都在 `insts_file.bin` 的 `inst_t` 记录内，stride = 304 bytes。
涉及的字段只有 3 个：`dst0` (byte 72-79), `src0` (byte 48-55), `src1` (byte 56-63)。

### Pattern A: dst0 高字节偏移 +512

```text
records 8846-8849, 9680-9683:
  dst0 byte 73: local=2/3, remote=0/1
  operand delta = +512 = 1 tensor group
```

本地 dst0 = 623/751/879/1007 (group 1, bank 4-7)
Vendor dst0 = 111/239/367/495 (group 0, bank 0-3)

**根因**: route_forward 微块的 COPY dst 来自子节点 TaskResource，但子节点的
operand 分配使用了不同的 group 分配逻辑。本地把 dst 放到了 group 1 (input0/A bank)，
vendor 把它放在 group 0 (output/C bank)。

### Pattern B: dst0 低字节偏移 -1

```text
records 10454-10459:
  dst0 byte 72: local=92/220/91/219/90/218, remote=93/221/92/220/91/219
  operand delta = -1
```

**根因**: sequential counter 分配顺序差异。本地 seed 表按固定 tag 列表顺序分配，
vendor 按 graph node 遍历顺序分配。当一个 tag 在 vendor 中先被遇到时，它获得更小的
operand index，导致后续所有 tag 的 index 都偏移 1。

### Pattern C: dst0 双字节差异

```text
records 11349-11350:
  byte 72: -1, byte 73: +2
  combined delta = -1 + 512 = +511
```

Pattern A 和 Pattern B 的组合。

### Pattern D: LDN dst0 +1

```text
records 13826-13827:
  dst0: local=111/239, remote=110/238
  operand delta = +1
```

**根因**: 与 Pattern B 相同，counter drift 方向相反。

### Pattern E: HMMAL src0/src1 +512

```text
records 14295-14307:
  src0 byte 49: local=2, remote=0
  operand delta = +512 = 1 tensor group
```

**根因**: 与 Pattern A 相同，tensor group 分配错误。

## 3. 当前 replay pass 的局限性

当前 `LegacyTaskResource.get_reg_idx()` 实现:

```python
def get_reg_idx(self, tag, *, tensor=False, forced_group=None):
    if tag in self.tag_to_operand:
        return self.tag_to_operand[tag]
    if tensor:
        operand_idx = self.alloc_operand_slot4tensor(forced_group)
    else:
        operand_idx = self.alloc_operand_slot()  # <-- 从 PE pool 弹出
    ...
```

问题在于 `fill_reg_idx()` 中的普通指令路径调用 `get_reg_idx(tag)` 时
**没有传递 `tensor=True`**。只有伪 tensor 展开路径（HLDT/HSTT/COPYT）
才通过 `alloc_operand_slot4tensor()` 走 tensor group 分配。

但 vendor 的 REDUCE 模式（`fill_reg_idx_rd`）中，所有指令都通过
`get_reg_idx_element3` 分配，该函数使用 `detect_conflict` 做三操作数
bank-conflict 消解，并从 PE 物理池分配——不是简单的 `layout_operand_idx(counter)`。

## 4. 需要修复的两个问题

### 问题 1: Tensor group 分配错误 (+512 diffs)

route_forward COPY 的 dst operand 应该来自子节点的 tensor 分配，
但当前子节点可能把 output tag 分配到了错误的 tensor group。

需要检查:
1. `_patch_copy_destinations()` 中 `child_res.retrieve_reg_idx(dst_tag)` 返回的值
2. 子节点的 tensor group 分配是否把 output tag 放到了 group 0

### 问题 2: Sequential counter drift (±1 diffs)

vendor 的 REDUCE 模式从 PE 物理池分配 operand（`alloc_operand_slot`），
不是从 `counter + layout` 分配。

当前 replay pass 的 `alloc_operand_slot()` 从 `pe_pool[bank].pop()` 分配，
但 `get_reg_idx()` 对普通指令没有调用它——只有 `tensor=True` 时才走 tensor pool。
普通指令走的是 `alloc_operand_slot()` 但没有 bank-conflict 消解。

需要: 让所有指令都走 PE pool 分配 + bank-conflict 检测。

## 5. 回归测试

当前行为已锁定在:
```text
test_legacy_gemm_task_resource_replay_regression_lock
```

该测试断言:
- cbuf/micc/insts 文件大小
- cbuf/micc SHA256 哈希
- 18 个 diff 位置的具体 operand 值
- 4 个已知匹配 vendor 的位置
