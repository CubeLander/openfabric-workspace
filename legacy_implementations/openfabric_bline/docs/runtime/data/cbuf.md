# CBUF 数据面

CBUF 这页专门讲 `insts_file.bin`、`exeblock_conf_info_file.bin`、`instance_conf_info_file.bin`。

这里反复出现的 `pe_dst` / `src_pe_pos` 都是 `position_t`，也就是：

```text
position_t = { x: uint64_t, y: uint64_t, z: uint64_t }
size = 24 bytes
```

它们在运行时会被拼进同一个镜像：

```text
cbuf_file.bin = insts_file.bin
              + exeblock_conf_info_file.bin
              + instance_conf_info_file.bin
```

## 1. CBUF 区间图

```text
CBUF region
  [insts]   -> CBUF_INST_BASE
  [blocks]  -> CBUF_BLCK_BASE
  [instc]   -> CBUF_ISTC_BASE
  [const]   -> CBUF_ISTC_CONST_BASE
```

逻辑边界定义在：

- [dma_com_def.h](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/common/src/dma_com_def.h)

## 2. 文件尺寸

| 文件 | 固定尺寸 | 说明 |
|---|---|---|
| `insts_file.bin` | 21,168,128 B | `16 PE * 4352 inst/PE * 304 B` |
| `exeblock_conf_info_file.bin` | 266,240 B | `16 PE * 32 block/PE * 520 B` |
| `instance_conf_info_file.bin` | 2,097,152 B | `4 task * 8 subtask * 2048 instance * 32 B` |

合起来，`cbuf_file.bin` 的主线固定镜像大小是：

```text
23,531,520 bytes
```

## 3. `insts_file.bin`

`insts_file.bin` 装的是 `inst_t`。

### `inst_t` 总尺寸

```text
sizeof(inst_t) = 304 bytes
```

### 字节布局

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `opCode` | 4 B | 操作码 |
| 8 | `unit_inst_type` | 8 B | 执行单元类别 |
| 16 | `latency` | 8 B | 逻辑延迟 |
| 24 | `imms[0..2]` | 24 B | 最多 3 个 immediate |
| 48 | `src_operands_idx[0..2]` | 24 B | 最多 3 个 source operand index |
| 72 | `dst_operands_idx[0..2]` | 24 B | 最多 3 个 destination operand index |
| 96 | `dst_pes_pos[0..2]` | 72 B | 最多 3 个目标 PE 坐标 |
| 168 | `dst_blocks_idx[0..2]` | 24 B | 目标 block 索引 |
| 192 | `forwarding_bits[0..2]` | 24 B | forwarding 元数据 |
| 216 | `bypass_bits[0..2]` | 24 B | bypass 元数据 |
| 240 | `iter_exe_cond` | 8 B | iteration / base_addr_idx 语义来源 |
| 248 | `src_operands_fetched[0..2]` | 3 B | source fetched 状态 |
| 251 | `dst_operands_fetched[0..2]` | 3 B | destination fetched 状态 |
| 256 | `block_idx` | 8 B | 所属 block |
| 264 | `flow_ack` | 8 B | flow ack |
| 272 | `end_inst` | 8 B | 结束标记 |
| 280 | `extra_fields[0..2]` | 24 B | 扩展字段 |

### 这条布局线怎么读

`inst_t` 是宽结构，它保留了：

- 语义字段
- mapper / scheduler 元数据
- PE 坐标
- block 归属信息

所以它更像“编译器和 simulator 共享的执行记录”，不是硬件窄指令。

### 这些值是怎么填进去的

`inst_t` 的值不是一次性写死的，而是经过三段式加工：

先把顺序说死，这一点很重要：

```text
指令占位 / 图结构
  -> PE / block 放置
  -> 寄存器起点快照
  -> 绝对寄存器编号回填
  -> copy / forwarding / bypass 修正
  -> print 落盘
```

也就是说，编译器在 cbuf 数据面上不是先分配寄存器再放置指令，而是先把指令和 block 的位置关系、占位关系铺好，再用 `m_start_reg_idx` 这类快照把寄存器编号补成绝对值。

1. **CSV 原始字段**先进入 `CsvItem`。
   - `csv_oper.cpp` 里 `constructOneCsvItem()` 读取：
     - `op_name`
     - `op_tag_name`
     - `src_reg_idx0_tag` / `src_reg_idxl_tag`
     - `dst_reg_idx_tag`
     - `dst_pe_idx`
     - `imms`
     - `iter_exe_cond`
     - `extra_fields[]`
   - 然后 `process()` 把这些原始值拷到 `Inst::inst`：
     - `opCode`
     - `unit_inst_type`
     - `latency`
     - `imms[0]`
     - `src_operands_idx[0..1]`
     - `dst_operands_idx[0]`
     - `dst_pes_pos[0]`
     - `iter_exe_cond`
     - `extra_fields[]`

2. **mapper / graph 层**再做位置和依赖修正。
   - `inst_map_common.cpp` 里的 `fillRegIdx()` 会把 PE 的 `m_start_reg_idx` 加到每条指令的 `src_operands_idx[]` / `dst_operands_idx[]` 上。
   - `fillCpInst()` / `setACKInst()` 会把 copy 类指令补成真正的跨 block 形式：
     - `dst_blocks_idx[0]`
     - `dst_pes_pos[0].x/y`
     - `dst_operands_idx[0]`
     - `flow_ack`
   - `inst_blk_map.cpp` 里的 `set_inst_block_idx()` 会把 `block_idx` 写到每条指令上。
   - `fillLocalCpInst()` 会把本地 copy 统一改成 `COPY`，并把目标 block / PE 重新挂上。
   - `set_forwarding_bypass()` 会根据前后两条 CAL 指令的寄存器关系，写入 `bypass_bits[]` / `forwarding_bits[]`。

`m_start_reg_idx` 这件事要单独拎出来看，因为它经常被误以为是 PE 自己的一个长期状态。实际上它更像是“节点在该 PE 上拿到的寄存器起始快照”，也正是这个值把“先占位、后回填寄存器”这条顺序串起来了：

- 定义在 `GRAPH_NODE` 里，初始值是 `0`。
- 在 `setNodes(PE pes[PE_AMOUNT], GRAPH_NODE *node, uint64_t pe_idx, uint64_t graph_idx)` 里赋值：

```text
node->m_start_reg_idx = pes[pe_idx].m_reg_counter
```

- 紧接着，如果这个 node 挂了 `Inst_Block`，`PE::m_reg_counter` 会按该 block 的去重寄存器数继续前推：

```text
pes[pe_idx].m_reg_counter += node->m_pInst_Block->csv_oper.m_reg_idx_list.size()
```

- 所以它的语义是：

```text
node 的寄存器起点 = 这个 PE 在接收当前 node 之前，已经分配出去的寄存器总数
```

- 后续 `fillRegIdx(vector<GRAPH_NODE>&)` 再把这个快照加到块内每条指令上，得到该 node 的绝对 operand index。
- 在 app / task 资源统计阶段，`start_map_app()` 还会把 `PE::m_reg_counter` 复制到 `APP_Resource::reg_start_idx`，然后 `distribute_app_resource()` 用它和 `operand_cnt` 回写 `PE::m_reg_counter`，让这个游标继续代表“该 PE 已经占用到哪里了”。

换句话说，`m_start_reg_idx` 是节点级快照，`m_reg_counter` 是 PE 级游标，`reg_start_idx` 则是 app/task 阶段拿来接续这条游标的基准值。

3. **print 阶段**只负责把最终宽指令镜像落盘。
   - `task_print.cpp` 里的 `print_inst_stage()` 会把各 stage 的指令按 PE 依次串起来，外层的 `print_task()` / `print_task_group()` 负责把这些段组织成最终文件。
   - 这一步不会再做语义计算，只会把已经整理好的 `inst_t` 写到 `insts_file.bin`。

有几个字段我在当前搜索路径里没找到显式写入点，文档里先保守处理：

- `src_operands_fetched[]`
- `dst_operands_fetched[]`
- `end_inst`

也就是说，现有可见链路里它们更像预留位或上游透传位，而不是在这里被系统性改写的主字段。

### 先记住一个总原则

`insts_file.bin` 里的 `inst_t` 是宽语义记录，给 simulator 和编译器共享使用。真正的 RTL 窄格式不在这一页展开，单独放在 [RTL 编码层](rtl.md)。

这一页只保留两件事：

1. `inst_t` 的宽字段骨架。
2. `inst_t` 在 simulator 侧的使用边界。

### 这条线怎么读

如果你现在关心的是“模拟器吃什么”，答案是：

```text
simulator_bin/insts_file.bin
  -> inst_t 宽结构
  -> simulator / PE 调度逻辑消费
```

如果你关心的是“RTL 怎么被打包”，请直接去 [RTL 编码层](rtl.md)。

## 4. `exeblock_conf_info_file.bin`

`exeblock_conf_info_file.bin` 装的是 `exeBlock_conf_info_t`。

### `exeBlock_conf_info_t` 总尺寸

```text
sizeof(exeBlock_conf_info_t) = 520 bytes
```

### 字节布局

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `valid` | 1 B | block 是否有效 |
| 8 | `block_idx` | 8 B | block 编号 |
| 16 | `pe_dst` | 24 B | 目标 PE 坐标 |
| 40 | `priority` | 8 B | 调度优先级 |
| 48 | `exeBlock_conf` | 472 B | block 详细配置 |

### `exeBlock_conf_t` 总尺寸

```text
sizeof(exeBlock_conf_t) = 472 bytes
```

### `exeBlock_conf_t` 字节布局

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `req_activations` | 8 B | 需要多少次激活 |
| 8 | `has_stages[0..3]` | 4 B | LD/CAL/FLOW/ST 是否存在 |
| 16 | `stages_start_pc[0..4]` | 40 B | stage 入口 PC |
| 56 | `predecessors[0..3]` | 160 B | 前驱 block |
| 216 | `successors[0..3]` | 160 B | 后继 block |
| 376 | `block_idx` | 8 B | block 编号 |
| 384 | `subtask_idx` | 8 B | subtask 编号 |
| 392 | `task_idx` | 8 B | task 编号 |
| 400 | `instances_amount` | 8 B | instance 数 |
| 408 | `child_amount` | 8 B | 子 block 数 |
| 416 | `block_class` | 8 B | block 分类 |
| 424 | `inst_mem_based_addr` | 8 B | 指令内存基址 |
| 432 | `ld_stage_inst_amount` | 8 B | LD 指令数 |
| 440 | `cal_stage_inst_amount` | 8 B | CAL 指令数 |
| 448 | `flow_stage_inst_amount` | 8 B | FLOW 指令数 |
| 456 | `st_stage_inst_amount` | 8 B | ST 指令数 |
| 464 | `is_leaf` | 1 B | 是否叶子 |

### 这条布局线怎么读

`exeBlock_conf_t` 不是简单的指令区间，它还带着：

- 图边关系
- task/subtask 归属
- stage 入口
- instance 数量

所以它是“可调度的执行片段”，不是裸 block。

### 这些值是怎么填进去的

`exeBlock_conf_info_t` / `exeBlock_conf_t` 的值主要分两步：

1. **图生成阶段**先把 block 的静态骨架组织出来。
   - `exe_block_gen.cpp` 里的 `organize_block_conf()` 会写：
     - `valid`
     - `pe_dst`
     - `block_idx`
     - `priority`
     - `req_activations`
     - `successors[]`
     - `predecessors[]`
     - `child_amount`
     - 各 stage 的指令数
     - `has_stages[]`
     - `stages_start_pc[]`
   - 这里的 `stages_start_pc[]` 是按 stage 累加出来的局部 PC，先只表示“这个 block 内部从哪条指令开始”。
   - `inst_mem_based_addr` 还没有在这里定下来，它是在 print 阶段按 PE 的累计指令数写入的。

2. **print 阶段**再把 task / subtask 的上下文压进去。
   - `task_print.cpp` 里的 `print_block_conf()` 会拷贝一份 `exeBlock_conf_info_t`，然后改写：
     - `exeBlock_conf.instances_amount`
     - `exeBlock_conf.task_idx`
     - `exeBlock_conf.subtask_idx`
     - `exeBlock_conf.block_idx`
   - 它还会根据当前 PE 已经打印了多少条指令，修正 `stages_start_pc[]`，让每个 block 的 stage 起点变成 CBUF 里的绝对偏移。
   - 接着它把 simulator 侧的 `exeBlock_conf_info_t` 写进 `blockexeblock_conf_info_file.bin<pe>`，再转换成 RTL 侧的 `exeBlock_conf_t_for_rtl` 写到 `rtl_bin/`。

所以这里的核心规律是：

```text
exe_block_gen.cpp 负责“这块长什么样”
task_print.cpp     负责“这块最后落到哪个 PE 的哪段文件里”
```

### 字段是谁决定的

`exeBlock_conf_t` 这组字段，当前可见链路里不是同一时刻填完的，而是分层补齐：

| 字段 | 谁决定 | 怎么填 |
|---|---|---|
| `req_activations` | 图关系 | `Exe_Block::req_activations` 初始为 0，`set_parent_successor()` 每接上一条父边就 `+1` |
| `has_stages[]` | block 内容 | `organize_block_conf()` 根据各 stage 的有效指令数判断是否存在 |
| `stages_start_pc[]` | block 内容 + print 偏移 | 先在 `organize_block_conf()` 里按 stage 累加，再在 `print_block_conf()` 里按 PE 已写入长度整体平移 |
| `predecessors[]` | 图关系 | `add_predecessor()` 把父 block 的 `block_idx` 和 `pe_pos` 写进去 |
| `successors[]` | 图关系 | `add_successor()` 把子 block 的 `block_idx` 和 `pe_pos` 写进去 |
| `block_idx` | 放置结果 | `exe_block_gen.cpp` 先给 `Exe_Block` 编号，`print_block_conf()` 再同步到落盘结构 |
| `subtask_idx` | task/subtask 归属 | `print_task()` 从当前 subtask 编号写入 |
| `task_idx` | task/subtask 归属 | `print_task()` 从当前 task 编号写入 |
| `instances_amount` | subtask 配置 | `print_task()` 取 `task.m_subtasks[i].instance_times`，`set_instance_amount_to_exeblock()` 再同步到每个 block |
| `child_amount` | 图关系 | `organize_block_conf()` 直接取 `Exe_Block::successors_counter` |
| `block_class` | 当前链路未见显式 writer | `exeBlock_conf_info_t` 在生成时先 `memset` 清零，当前可见路径里没有再写它 |
| `inst_mem_based_addr` | print 时的 PE 累计指令偏移 | `print_inst()` 里按 `insts_counter_per_pe * sizeof(inst_t)` 写入 |
| `ld_stage_inst_amount` | block 内容 | `organize_block_conf()` 用有效 LD 指令数填写 |
| `cal_stage_inst_amount` | block 内容 | `organize_block_conf()` 用有效 CAL 指令数填写 |
| `flow_stage_inst_amount` | block 内容 | `organize_block_conf()` 用有效 FLOW 指令数填写 |
| `st_stage_inst_amount` | block 内容 | `organize_block_conf()` 用有效 ST 指令数填写 |
| `is_leaf` | 当前链路未见显式 writer | `GRAPH_NODE::m_isLeaf` 只在图遍历/扩展里用，`exeBlock_conf_t` 这一字段在当前可见路径里没有被写入 |

两点值得额外强调：

1. `req_activations` 不是配置文件里手填的常量，它是图边数驱动出来的“到齐才能执行”的计数。
2. `block_class` / `is_leaf` 在当前这条生成链路里看起来是保留位。也就是说，文档里可以先把它们标成“预留/未显式使用”，不要硬解释成已有语义。

`exeBlock_conf_info_t` 外层那几个包装字段也有明确来源：

- `valid`：`organize_block_conf()` 直接置 `true`
- `block_idx`：来自 `Exe_Block::exe_block_idx`
- `pe_dst`：来自当前 PE 的 `OP_POS`
- `priority`：当前实现里固定写 `0`

## 5. `instance_conf_info_file.bin`

`instance_conf_info_file.bin` 装的是 `instance_conf_info_t`。

### `instance_conf_info_t` 总尺寸

```text
sizeof(instance_conf_info_t) = 32 bytes
```

### 字节布局

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `base_addr[0]` | 8 B | base slot 0 |
| 8 | `base_addr[1]` | 8 B | base slot 1 |
| 16 | `base_addr[2]` | 8 B | base slot 2 |
| 24 | `base_addr[3]` | 8 B | base slot 3 |

### 这条布局线怎么读

当前硬件语义里，LD/ST 类访存一般是：

```text
effective_addr = base_addr[base_addr_idx] + imm
```

也就是说，instance 表不是“附属信息”，它直接决定当前 instance 看到的地址环境。

### 这些值是怎么填进去的

`instance_conf_info_t` 是这三类里最“场景化”的一类，它的值通常不是编译器通用层算出来的，而是由具体 testcase 里的 `csv_generate/test_app_conf_generate.c` 按任务模板生成。

当前仓库里能看到两条主线：

1. **`softmax_1` 这条模板**。
   - 它先把 `base_addr[]` 初始化成 `Secondary_Fusion_Array` 里对应的基址，或者填成 `0xffffffff`。
   - 然后按每个 subtask 的语义去改写 base slot。
   - 在循环推进 instance 时，会用诸如 `PER_INSTANCE_STATEMENT_NUMBER[]`、`min_unit`、`input_group_base[]`、`output_group_base[]` 这样的参数做增量。
   - 这说明 `base_addr[]` 不是静态常量表，而是“每个 instance 的地址窗口”。

2. **`gemm_template_fusion` 这条模板**。
   - 它会根据 subtask 的角色，给 `base_addr[0..3]` 填不同的 SPM 基址。
   - 例如有的 subtask 只用一个输入源，有的同时用两个输入源。
   - 对于需要沿 instance 递进的 subtask，会按固定 stride 增加：

```text
base_addr += per_instance_stride
```

   - 当 `Secondary_Fusion_Array` 存在时，某些 base slot 会直接从这个映射里取值，再写成 `tempfile.h` 可复用的常量映射。

另外还有一个总的落盘约束：

- `instances_conf_mem_based_addr` 由 `print_task()` 按全局 instance 表偏移写入。
- `instance_conf_info_file.bin` 最终按固定槽位表写满，不是按“有多少就写多少”的压缩格式。

换句话说，`instance_conf_info_t` 的值填充逻辑更像：

```text
task template
  -> subtask role
  -> per-instance stride
  -> fixed-slot table entry
```

## 6. 固定槽位提醒

当前源码中既有紧凑偏移写法，也有 padded table 生成写法。结合文件尺寸和架构资料，主线更应该把 `instance_conf_info_file.bin` 理解成固定槽位表。

也就是说，`cbuf` 里最关键的不是“文件顺序”，而是：

1. 每个文件的逻辑区域
2. 每个结构体的字节骨架
3. 每个字段的 offset

## 7. 任务调度模型

如果把上面的三个表放回执行模型里，它们对应的是同一条调度链的不同粒度：

```text
app / task group
  -> tasks
      -> subtasks (serial chain inside each task)
          -> instance repetitions
              -> subtask-local graph of PE blocks
                  -> exeBlock / stage layout
```

在当前 GEMM / SimICT 工作流里，最稳妥的理解是：

- `app` 或 `task group` 是最外层控制容器。
- `task` 在当前 GEMM 例子里更像并行 slot / 数据分片，不应先假设它们彼此严格串行。
- 每个 `task` 内部的 `subtask` 是顺序阶段，靠 `suc_subtasks[0]` 串起来。
- 每个 `subtask` 还能通过 `instance_times` 做硬件循环重复，重复次数对应同一子图 / 同一 block program 的多次执行。
- `subtask` 内部则是 `GRAPH_NODE` 依赖图，节点对应 PE-local 的 `exeBlock`，边对应 `predecessors[]` / `successors[]`。

这条模型和 CBUF 里的字段是直接对齐的：

| 执行层级 | 主要字段 | 含义 |
|---|---|---|
| task group | `task_conf_info_t.subtasks_idx`, `suc_tasks`, `is_exe_start`, `is_exe_end` | task 级链路和边界 |
| task | `task_idx`, `execute_times` | task 归属和 task 级重复次数 |
| subtask | `sub_task_conf_info_t.subtask_idx`, `instances_amount`, `instances_conf_mem_based_addr`, `root_block_amount`, `block_amount`, `suc_subtasks` | subtask 级串行链路、instance 重复和图规模 |
| instance | `instance_conf_info_t.base_addr[]` | 同一 subtask 的一次执行所用 base slot |
| block graph | `exeBlock_conf_info_t.pe_dst`, `block_idx`, `priority`, `valid` | block 放置和落盘包装 |
| block execution | `exeBlock_conf_t.req_activations`, `predecessors[]`, `successors[]`, `stages_start_pc[]`, `inst_mem_based_addr`, `*_stage_inst_amount` | block 内部依赖、stage 划分和 PE-local 指令布局 |

几个很重要的对应关系：

1. `execute_times` 是 task 级重复，`instances_amount` 是 subtask 级重复。前者更像外层控制循环，后者更像同一 subtask 图在不同 base address 下的重复执行。
2. `root_block_amount` 统计的是一个 subtask 图里没有 parent 的初始 block 数，说明这张图一启动时有多少入口点。
3. `child_amount`、`predecessors[]`、`successors[]` 描述的是 subtask 内部 block 图，而不是 task/subtask 之间的串联。
4. `stages_start_pc[]` 和 `inst_mem_based_addr` 只是在 PE-local 指令内存里描述 block 的位置，不是 task/subtask 级的控制链。

所以，从“读懂 CBUF 字段”的角度，应该先把 runtime 记成：

```text
task group 负责外层并行槽
task       负责序列化的控制单元
subtask    负责一个可重复的 dataflow 阶段
instance   负责该阶段的不同 base address 视图
exeBlock   负责落到 PE 上的具体 block 与 stage 划分
```

在当前 GEMM case 里，这个模型还能再细一点：

- `task0..task3` 更像四个并行分片，而不是四个严格顺序阶段。
- 每个 `task` 内部的 `subtask1 -> subtask2 -> subtask3` 是顺序链。
- `subtask2` 这类高密度计算阶段可能有 `instance_times > 1`，这就是“硬件循环”的来源。
- 同一个 `subtask` 内部的 `GRAPH_NODE` 则可以在多个 PE 上形成并行依赖图，最终映射成多个 `exeBlock`。

## 8. 相关写入入口

- [csv_oper.cpp](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/csv_oper.cpp)
- [inst_map_common.cpp](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/inst_map_common.cpp)
- [inst_blk_map.cpp](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/inst_blk_map.cpp)
- [exe_block_gen.cpp](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/exe_block_gen.cpp)
- [task_print.cpp](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/task_print.cpp)
- [softmax_1/test_app_conf_generate.c](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/softmax_1/csv_generate/test_app_conf_generate.c)
- [gemm_template_fusion/test_app_conf_generate.c](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/csv_generate/test_app_conf_generate.c)
- [DpuAPI.c](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/dpuapi/DpuAPI.c)
