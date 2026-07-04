# inst_blk_map.cpp arch-13 分析报告

Date: 2026-06-16

Status: 破案完成 — CBUF operand index diff 的根因已确认

## 1. 核心发现：本地版本是阉割 stub

本地 `inst_blk_map.cpp` (711 行) 与 arch-13 远端版本 (~2245 行) 是**完全不同的实现**。

| 函数 | 本地版本 | arch-13 版本 |
|---|---|---|
| `get_reg_idx(element, start)` | `layout_operand_idx(counter + start)` | `alloc_operand_slot(pPe, ...)` — 从 PE 物理池弹出 |
| `fill_reg_idx` | 简单 tag→counter 映射 | 完整：pseudo-tensor 展开 + bank-conflict + end_inst + `extra_fields[2]` |
| `detect_conflict` | `(void)` return 0 | 完整：枚举链组合寻找无冲突三元组 |
| `deal_chain_data` | `(void)` return 0 | 完整：从 free RAM 试探性分配 |
| `reduce_chain_inst` | `(void)` return 0 | 完整：reduce 链替换 |
| `fill_reg_idx_rd` | 委托 `fill_reg_idx` | 完整的 REDUCE 模式入口 |
| `get_reg_idx_element3` | 3 次独立 `get_reg_idx` | 调用 `detect_conflict` 做三操作数 bank-conflict 消解 |

本地版本已被备份为 `inst_blk_map.cpp.local_stub_backup`。

## 2. arch-13 真实分配算法

### 2.1 总体流程

```text
INST_BLK_MAP::end_map_task()
  -> distribute_task_resource()
     -> distribute_operand(pApp_res, pTask_res, pPe)
        -> for each node in PE task window (sorted by graph node order):
           -> fill_reg_idx_rd(pPe, ld_stage, reg_start_idx)
           -> fill_reg_idx_rd(pPe, cal_stage, reg_start_idx)
           -> fill_reg_idx_rd(pPe, flow_stage, reg_start_idx)
           -> fill_reg_idx_rd(pPe, st_stage, reg_start_idx)
  -> rectify_copy_inst()
     -> fill_copy_inst(parent_node)  // COPY dst 来自子节点 TaskResource
     -> alter_local_copy_inst(node)   // LCOPY/LCOPYT -> COPY
  -> counting_task_resource()
  -> get_app_max_resource()
```

### 2.2 `fill_reg_idx_rd` (REDUCE 模式)

对每条有效指令:

```text
1. 检查 extra_fields[2]
   如果非零: 强制分配到指定 RAM group (extra_fields[2] - 1)
   
2. 检查是否为 pseudo-tensor 指令 (HLDT/ILDT/HSTT/ISTT/COPYT/LCOPYT/...)
   如果是:
     a. 改写 opcode (HLDT->LDN, HSTT->STD, COPYT->COPY)
     b. 分配首条指令的 operand
     c. follow 指令 operand = base + lane * OPERANDS_PER_OPERAND_RAM
     d. mem_mode 特例: OPERANDS_PER_GROUP == 2 时 follow inst dst 共享 base
     e. COPYT 额外: update_last_copy() 记录 flow_ack 目标
     f. i += (OPERANDS_PER_GROUP - 1) 跳过 follow 指令
   
3. 普通指令:
   根据操作数数量调用:
     1 operand -> get_reg_idx_element1()
     2 operand -> get_reg_idx_element3(type=0)
     3 operand -> get_reg_idx_element3(type=1)
   
4. bank-conflict 检查 (src0==src1, src0==dst, src1==dst)
5. 3-instruction hazard window 维护 (ram_idx_used_rec_list)
6. 最后有效指令设置 end_inst = 1
7. set_flag2_last_copy() 设置 flow_ack
```

### 2.3 `get_reg_idx` (非 REDUCE 模式)

```cpp
if tag already allocated:
    return existing operand_idx

if tensorReg:
    operand_idx = alloc_operand_slot4tensor(pPe, ram_idx_rest_rec)
else:
    operand_idx = alloc_operand_slot(pPe, ram_idx_rest_rec)

m_reg_idx_list[tag] = operand_idx
m_reg_idx_counter++
return operand_idx
```

关键：`alloc_operand_slot` 从 PE 物理寄存器池 (`m_reg_lists`) 中 pop，**不是简单的 `counter + start`**。

### 2.4 `alloc_operand_slot`

```cpp
if ORDER mode:
    take first available bank from ram_idx_rest_rec
else if HEURISTIC mode:
    pick bank with most free slots
else if RANDOM mode:
    take last from ram_idx_rest_rec

reg_idx = pPe->m_reg_lists[best_bank].back()
pPe->m_reg_lists[best_bank].pop_back()
ram_idx_rest_rec.erase(ram_idx_rest_rec.begin() + pos)

// maintain tensor availability
tensor_reg = get_first_reg_in_tensor_reg(reg_idx)
group = get_group_idx_from_reg_idx(reg_idx)
erase_value_from_tensor_regs_available(group, tensor_reg)

return reg_idx
```

### 2.5 `detect_conflict` — 三操作数 bank-conflict 消解

```text
1. 枚举 chain1 x chain2 x chain3 现有 reg 组合
2. 如果找到 (reg1, reg2, reg3) 使得三者两两不在同一 bank:
   -> 直接复用，count++
3. 否则调用 deal_chain_data() 从 free RAM 分配新 reg
4. deal_chain_data 尝试将新 reg 塞入某条链，做 reduce_chain_inst 替换
```

### 2.6 `fill_copy_inst` — COPY destination 来自子节点

```cpp
pCopy_inst->inst.dst_blocks_idx[0] = pChild_node->m_pos.block_idx;
pCopy_inst->inst.dst_pes_pos[0].x  = pChild_node->m_pos.x;
pCopy_inst->inst.dst_pes_pos[0].y  = pChild_node->m_pos.y;
pCopy_inst->inst.dst_operands_idx[0] =
    pTask_res->retrieve_reg_idx(pCopy_inst->dst_reg_idx_tag);

// COPYT 展开
for each following lane:
    dst_operands_idx[0] = base + lane * OPERANDS_PER_OPERAND_RAM
```

## 3. "按下葫芦浮起瓢" 根因分析

OpenFabric 当前用**静态 seed 表**近似 arch-13 的 operand 分配。

### 3.1 seed 表能做什么

seed 表可以近似 tag→operand 的映射关系，在 graph node order 和 instruction order 固定的情况下，给出一组"大致正确"的 operand index。

### 3.2 seed 表做不了什么

| 缺失行为 | 后果 |
|---|---|
| **PE 物理寄存器池分配** | operand index 的分配顺序取决于 PE 池的当前状态。不同 task/wave 之间的累积状态无法用静态常量模拟 |
| **`extra_fields[2]` RAM group 强制** | CSV 模板通过 `iteration` 列指定某些 tensor operand 必须进入特定 group (0/1/2)，OpenFabric 忽略了这个约束 |
| **`mem_mode` 分支** | `mem_mode==1 && OPERANDS_PER_GROUP==2` 时 follow inst dst 共享 base slot 而非 `+lane*128` |
| **3-instruction hazard window** | 最近 3 条指令的 bank 使用记录影响后续分配，seed 表无法反映这个滑动窗口 |
| **三操作数 bank-conflict 消解** | arch-13 会主动分配新 reg + insert MOVE 指令来消解冲突，seed 表无法预测何时需要 MOVE |

### 3.3 为什么修一个 byte 让另一个 byte 出错

```text
seed 表是全局常量
arch-13 分配器是状态机
```

改变一个 seed 值可以修复特定位置的 byte diff，但同一 seed 值在不同 (task, PE, node, stage) 上下文中会产生不同的 arch-13 分配结果。修一个 case 的 byte 等价于在 seed 表里硬编码了一个 (task, PE, node, stage) 的偏移，在其他上下文必然出错。

### 3.4 具体 byte family 解释

| diff family | seed 表近似 | arch-13 真实原因 |
|---|---|---|
| `COPYT15 dst0 wants -512` | 静态 COPYT dst patch | 子节点 TaskResource.retrieve(tag) 返回的 operand index 与 sender 模板值不同 |
| `wave1 accumulator_prepare src/dst` | 跨 task tensor seed 偏移 | `reg_start_idx` 是 app-level `reg_counter`，跨 task 累积。arch-13 在 task0 分配了 N 个 operand 后 task1 的 seed 偏移 = N |
| `BET group2` | 手动修正 group | CSV `extra_fields[2]` 指定 BET 必须进入 input1/B tensor bank (group 2) |
| `input0_15 group1` | 手动修正 group | CSV `extra_fields[2]` 指定 input0 strip 15 进入 input0/A tensor bank (group 1) |

## 4. 修复方案

### 4.1 不要再调 seed 常量

所有进一步的 byte 修正都应该通过实现 arch-13 分配器行为完成，而不是微调 seed 表。

### 4.2 实现 `LegacyTaskResource` replay pass

Pipeline 位置：

```text
ProgramVendorABI / TemplateBoundInstructions
  -> Dfu3500TaskResourceReplay  (NEW)
  -> ProgramBinRows
  -> ProgramBinComponents
```

核心数据结构：

```python
class LegacyTaskResource:
    pe_pool: list[list[int]]          # m_reg_lists[bank_idx] -> stack of free reg indices
    tensor_available: list[list[int]] # per-group tensor register pool
    tag_to_operand: dict[str, int]    # m_reg_idx_list
    reg_counter: int
    ram_idx_rest_rec: list[int]       # free banks
    ram_idx_used_rec_list: list[list[int]]  # 3-instruction hazard window

class LegacyCopyPatch:
    parent_block_id: int
    child_block_id: int
    child_pe: tuple[int, int]
    copy_instruction_ids: list[int]
    dst_tag: str
```

核心算法：

```python
def replay(vendor_abi, template_instructions):
    for each (task_index, processor) group:
        task_res = LegacyTaskResource(pe_pool_init, reg_start=app.reg_counter)
        
        for each exeBlock in vendor node order:
            for stage in [LD, CAL, FLOW, ST]:
                for each instruction in stage:
                    bind_operands(instruction, task_res)
        
        # after all nodes processed for this (task, PE):
        for each parent->child edge:
            child_res = child TaskResource
            for each COPY/COPYT in parent's flow stage:
                patch_dst(COPY, child_res.retrieve(dst_tag))

def bind_operands(inst, task_res):
    # 1. extra_fields[2] forced group
    # 2. pseudo-tensor expansion
    # 3. normal get_reg_idx / detect_conflict
    # 4. hazard window update
    # 5. end_inst marking
```

### 4.3 验证计划

```bash
# 现有回归测试必须通过
pytest -q tests/test_chip_program_frontend.py -k \
  "legacy_gemm_template_keeps_input0_strip15 or legacy_gemm_compat_bundle or legacy_gemm or program_bin or task_conf"

# 新增验证
# 1. MICC sha256 不变: ab56e64bff6f0d9b469146ef04d4584c2597f4bcbb1b951d49c43601eb2a9980
# 2. CBUF insts diff 字节数大幅下降
# 3. arch-13 完整 diff 确认所有 inst_t field 对齐
```

## 5. arch-13 OCR 源码位置

组装后的完整源码：

```text
tmp/inst_blk_map_arch13.cpp (3498 行)
```

已覆盖本地版本：

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/inst_blk_map.cpp
```

原始 stub 版本备份：

```text
simict3500final/.../common_oper/inst_blk_map.cpp.local_stub_backup
```

## 6. 版本指纹

| 文件 | SHA256 |
|---|---|
| 本地 stub libapp_build_common.so | `246236162a29eb3f45d2abcc324c326931e8944e0638b035dff42bb8aaaa611b` |
| 本地 stub inst_blk_map.cpp | `b97408554aaac91d7adfdace59d1d4dbf9f6c06b4c96d97020d470fac85ae666` |
| arch-13 inst_blk_map.cpp (OCR) | `3f9d7ba6ae5a88277ce3243d1203a98fc8bfb139f9b900bb2fdc93eafaee1f0b` |
| arch-13 libapp_build_common.so | `e46d0f8870a0478133e02747de01297a30a1beb8b06fb413256d565af0d5938d` |

本地 stub 与 arch-13 不是同一个 build。所有 operand 分配行为差异均来源于此。
