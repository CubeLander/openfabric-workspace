# DTensor / StageShard 地址计划

日期：2026-06-27

这份文档是当前活的 DTensor / StageShard 地址原则文档，取代早期
softmax 内存模板与 DTensor memory model 草稿，专门记录：

```text
如何用 DTensor / tile / PE work 语义绕开 vendor 老模板里的地址游标。
```

它不是要替代甲方 assembler 或二进制 serializer。它只定义一个更清楚的
编译期地址语义层，最后仍然投影回 vendor 需要的：

```text
instance_conf_info.base_addr[base_addr_idx] + imm
```

## 问题：地址游标不是长期语义

现在 `softmax_instance_config_program.c` 里还能看到一类 legacy helper：

```cpp
add_base_addr_delta(...)
advance_legacy_non_softmax_base_row(...)
```

它们表达的是甲方老模板里的做法：

```text
写出当前 instance row；
然后把 base_addr[0..3] 按某个 stride 往后推；
下一轮 instance 继续用被推过的 base_addr。
```

这个味道很坏，因为它把“当前执行要访问哪个 tile / shard”藏进了一个可变游标。
更稳的模型应该反过来：

```text
先知道当前阶段要处理哪个 shard / tile；
再根据 shard / tile 计算 base row；
最后投影成甲方的 base_addr[slot] + imm。
```

## instance row 到底决定什么

更准确地说，`instance_conf_info` 的一行不是“某个 PE 的地址”，也不是完整
tile 语义。它决定的是：

```text
某个 task/subtask 阶段、某次 hardware repeat instance 的大 shard 基址表。
```

可以这样理解：

```text
subtask:
  当前执行阶段，例如 softmax 第一阶段 / 第二阶段，或 GEMM 的某段 K-loop body。

instance:
  这个阶段被硬件 repeat 的第几次。

instance row:
  这个阶段这一次 repeat 看到的一组 base_addr[0..3]。
```

这一行里的 `base_addr[0..3]` 更像“四个阶段局部的大地址寄存器”：

```text
base_addr[0] = 当前阶段当前 shard 的 SUM / scratch 基址
base_addr[1] = 当前阶段当前 shard 的 input 基址
base_addr[2] = 当前阶段当前 shard 的 output 基址
base_addr[3] = 当前阶段当前 shard 的参数 / 临时区基址
```

具体哪个槽绑定哪个 buffer，由编译期的 slot binding 决定，不是硬件天然知道。

PE 不应该决定 instance row 的大基址。PE 更合理的职责是：

```text
在同一个阶段 shard 里面，决定自己读写 shard 内的哪个 lane / row / element。
```

所以地址应该拆成两层：

```text
instance row:
  决定阶段 shard 的大基址。

PE-local instruction imm:
  决定这个 PE 在 shard 内部访问哪个小位置。
```

对应公式是：

```text
effective_addr =
  stage_shard_base_addr[base_addr_idx]
  + pe_local_or_tile_inner_imm
```

这也解释了为什么不要把 PE 偷偷塞进 `base_addr_idx`：

```text
base_addr_idx 是选当前 instance row 里的哪个基址槽；
PE 差异应该体现在 tile/lane 坐标和 imm 公式里。
```

如果未来某个布局确实需要 PE 影响大基址，也应该显式写成：

```text
TileCoord includes pe_coord / shard_coord
AddressPlan uses pe_coord to compute row or imm
```

而不是让 `base_addr += delta` 或 `base_addr_idx` 承担隐藏语义。

## OpenFabric 应该接管的边界

甲方 ABI 仍然保留：

```text
CSV memory op:
  base_addr_idx
  imm

instance_conf_info row:
  base_addr[0..3]

effective_addr:
  base_addr[base_addr_idx] + imm
```

OpenFabric 不应该一开始就替代 assembler 或最终二进制 serializer。
OpenFabric 应该先接管这件事：

```text
从 DTensor / tile / PE work partition 语义，
生成一致的 base row 和 CSV address operands。
```

推荐的分层是：

```text
DTensor / TensorRegion
  有哪些逻辑张量，shape/dtype/layout 是什么。

TileSpace / TileCoord
  每个算子阶段处理哪个逻辑 tile 或 shard。

StageShard
  某个 subtask 阶段、某个 instance 对应的大 shard。

PEWorkPartition
  每个 PE 在 shard 内负责哪些 lane / row / element。

TileAccessPlan
  当前阶段程序要读写哪些 tensor tile。

VendorAddressProjection
  把 TileAccessPlan 投影为 base_addr[slot] + imm。
```

这条链里，`instance row` 对应的是 `StageShard` 的 vendor 投影：

```text
StageShard(task, subtask, instance, logical_tile)
  -> base_addr[0..3]
```

PE 对应的是 `PEWorkPartition` 和 tile 内 offset：

```text
PEWorkPartition(pe_id, logical_tile)
  -> imm / operand lane / CSV row variant
```

二者分开以后，地址公式就不再依赖“上一次加到了哪里”。

## softmax 的最小落地形态

当前 softmax 可以先做一个很小的闭环：

```text
TensorRegion:
  X   = softmax0_input0
  SUM = SUM
  Y   = softmax0_output0

StageShard:
  placement = (task_id, subtask_id, instance_id)
  tile      = LogicalTile(statement_index, large_scale_chunk_index)

BaseSlotBinding:
  SUM -> slot 0
  X   -> slot 1
  Y   -> slot 2

TileAccessPlan:
  subtask1 reads X(tile), writes SUM(tile)
  subtask2 reads X(tile), reads SUM(tile), writes Y(tile)

VendorAddressProjection:
  row.base_addr[slot(SUM)] = address_of(SUM, tile)
  row.base_addr[slot(X)]   = address_of(X, tile)
  row.base_addr[slot(Y)]   = address_of(Y, tile)
```

这里 `subtask_id` 是否影响 tile 坐标，可以先保持当前事实：

```text
softmax 当前 base row 对同一 task/instance 不依赖 subtask_id；
subtask_id 主要决定执行哪段 CSV 程序。
```

但类型上应该把 `subtask_id` 放进 `VendorExecutionPlacement`，这样以后某个阶段
确实需要不同 tile 映射时，不会再把执行编号散落进地址公式。

### 当前 softmax 二进制 dump 证据

可以用这个工具直接查看当前产物里的 instance 基地址表：

```bash
python3 simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/softmax_refactored/tools/dump_instance_base_rows.py
```

也可以用这个工具查看 CSV memory 指令如何在这组大基址里选择具体位置：

```bash
python3 simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/softmax_refactored/tools/dump_memory_csv_addresses.py
```

如果想看逐条 PE 指令：

```bash
python3 simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/softmax_refactored/tools/dump_memory_csv_addresses.py --details
```

当前 replay 生成的 `softmax_refactored_build_case` 的表大小是：

```text
65536 rows * 32 bytes = 2097152 bytes
```

这正好对应：

```text
4 task * 8 subtask slots * 2048 instance rows
```

从 `SoftmaxDistributedPlan` 的 SPM slot binding 和 generated
`openfabric_softmax_runtime_config.h` 对齐出来的 slot binding 是：

```text
slot0: SUM              initial_base = 32768
slot1: softmax0_input0  initial_base = 0
slot2: softmax0_output0 initial_base = 16384
slot3: INVALID
```

当前 active 配置是：

```text
TASK_NUM = 4
SUBTASK_NUM = 2
PER_TASK_INSTANCE_NUMBER = {1, 1, 1, 1}
PER_INSTANCE_STATEMENT_NUMBER = {64}
min_unit = 512
```

所以真正会被当前硬件 repeat 用到的是每个 active subtask 的 `inst0`。
这些 active rows 都是同一个阶段 shard 基址：

```text
task0 subtask0 inst0 -> (32768, 0, 16384, INVALID)
task0 subtask1 inst0 -> (32768, 0, 16384, INVALID)
task1 subtask0 inst0 -> (32768, 0, 16384, INVALID)
task1 subtask1 inst0 -> (32768, 0, 16384, INVALID)
...
```

这说明当前 softmax 里：

```text
task_id 的差异没有体现在 instance row 大基址里。
不同 task / PE 的实际访问位置主要由 CSV 模板里的 imm / lane / statement
坐标承担。
```

CSV memory 指令 dump 进一步确认了这一点。当前 `inst0` 下，summary 是：

```text
task0 subtask1 HLDT  input  imm 0..3968      effective 0..3968
task1 subtask1 HLDT  input  imm 4096..8064   effective 4096..8064
task2 subtask1 HLDT  input  imm 8192..12160  effective 8192..12160
task3 subtask1 HLDT  input  imm 12288..16256 effective 12288..16256

task0 subtask2 HSTT  output imm 0..3968      effective 16384..20352
task1 subtask2 HSTT  output imm 4096..8064   effective 20480..24448
task2 subtask2 HSTT  output imm 8192..12160  effective 24576..28544
task3 subtask2 HSTT  output imm 12288..16256 effective 28672..32640
```

PE 维度也在 CSV imm 里展开。例如 task0/subtask1：

```text
PE0  HLDT input imm 0, 128
PE1  HLDT input imm 256, 384
PE2  HLDT input imm 512, 640
...
PE15 HLDT input imm 3840, 3968
```

对应的 SUM scratch store 是：

```text
PE0  HSTT SUM imm 0
PE1  HSTT SUM imm 128
PE2  HSTT SUM imm 256
...
PE15 HSTT SUM imm 1920
```

subtask2 再从 SUM 读取每个 PE 的四个 reduction scratch slot：

```text
PE0 ILDMT SUM imm 0, 32, 64, 96
PE1 ILDMT SUM imm 128, 160, 192, 224
...
```

所以当前地址职责可以写得更准：

```text
instance row:
  绑定 SUM / input / output 这些阶段 shard 的大基址。

CSV memory instruction:
  用 base_addr_idx 选择哪个大基址；
  用 imm 表达 task / PE / lane / scratch slot 在 shard 内的位置。
```

### 从 dump 反推 softmax tile 划分

当前 vendor 地址单位不是普通元素下标。源码里有：

```cpp
half_addr(element_offset) = element_offset * 16 / 32
```

也就是：

```text
vendor_addr_unit = element_offset / 2
element_offset   = vendor_addr_unit * 2
```

对 input/output 来说，dump 的规律是：

```text
task0 PE0  imm 0, 128
task0 PE1  imm 256, 384
...
task0 PE15 imm 3840, 3968

task1 PE0  imm 4096, 4224
...
```

把 vendor 地址单位还原成元素 offset：

```text
input_element_offset =
  2 * (task_id * 4096 + pe_id * 256 + lane_id * 128)

= task_id * 8192 + pe_id * 512 + lane_id * 256
```

因为 `min_unit = 512`，所以可以直接读成：

```text
row = task_id * 16 + pe_id
col = lane_id * 256
```

当前 softmax 的 input/output tile 划分就是：

```text
X, Y shape = [64, 512]

task tile:
  task0 -> rows 0..15
  task1 -> rows 16..31
  task2 -> rows 32..47
  task3 -> rows 48..63

PE tile:
  PE0  -> task 内第 0 行
  PE1  -> task 内第 1 行
  ...
  PE15 -> task 内第 15 行

lane / vector chunk:
  lane0 -> cols 0..255
  lane1 -> cols 256..511
```

所以 input load / output store 可以映射成 DTensor 风格：

```text
for task_id in 0..3:
  task_shard = X[task_id * 16 : (task_id + 1) * 16, 0:512]

  for pe_id in 0..15:
    row = task_id * 16 + pe_id

    PE(pe_id) reads:
      X[row, 0:256]
      X[row, 256:512]

    PE(pe_id) writes:
      Y[row, 0:256]
      Y[row, 256:512]
```

这说明原始实现里其实已经有一个很清楚的 DTensor 语义：

```text
DTensor X[64,512]
  shard dim0 by task into 4 shards of 16 rows
  shard each task row-shard by PE into 16 single-row PE tiles
  split each PE row tile into 2 vector chunks of 256 columns
```

SUM scratch 的 dump 规律是：

```text
task0 PE0  HSTT SUM imm 0
task0 PE1  HSTT SUM imm 128
...
task1 PE0  HSTT SUM imm 2048

subtask2 PE0 ILDMT SUM imm 0, 32, 64, 96
subtask2 PE1 ILDMT SUM imm 128, 160, 192, 224
...
```

还原成元素 offset：

```text
sum_element_offset =
  2 * (task_id * 2048 + pe_id * 128 + slot_id * 32)

= task_id * 4096 + pe_id * 256 + slot_id * 64
```

因此 SUM 更像一个 per-row reduction scratch：

```text
SUM shape ~= [64, 256]

task_id -> 16 行
pe_id   -> 1 行
slot_id -> 4 个 64-element scratch slot
```

这里要保留一点谨慎：`HSTT SUM imm row_base` 只出现一条 store 指令，但
subtask2 用四条 `ILDMT` 从 `row_base + {0, 32, 64, 96}` 读回。这很像 vendor
store/load 指令本身带有向量宽度，subtask1 写出一整段 256-element scratch，
subtask2 再按 4 个 64-element slot 读回。

对应的 DTensor / scratch 语义可以先写成：

```text
SUM[row, 0:256] = reduction_scratch_for_softmax(X[row, 0:512])

subtask1:
  PE(row) reads X[row, 0:512]
  PE(row) writes SUM[row, 0:256]

subtask2:
  PE(row) reads SUM[row, 0:256] as 4 slots
  PE(row) writes Y[row, 0:512]
```

### tile 内部寻址：连续，但按 vector chunk 暴露

继续往 tile 内部看，当前 softmax 的地址不是任意 scatter。它更像：

```text
连续 row tile
  -> 按 PE 分行
  -> 每个 PE 行内按固定 vector chunk 读写
```

对 input/output 来说，一个 PE 负责一整行：

```text
X[row, 0:512]
Y[row, 0:512]
```

CSV 里只暴露两个 chunk 起点：

```text
lane0 imm = half_addr(row * 512 + 0)
lane1 imm = half_addr(row * 512 + 256)
```

还原成元素坐标：

```text
lane0 -> cols 0..255
lane1 -> cols 256..511
```

所以 input/output 的 tile 内部是连续的：

```text
PE(row) owns X[row, 0:512]
  chunk0 = X[row, 0:256]
  chunk1 = X[row, 256:512]
```

相邻 PE 之间也是连续行：

```text
PE0: X[task_base + 0, 0:512]
PE1: X[task_base + 1, 0:512]
...
PE15: X[task_base + 15, 0:512]
```

对 SUM scratch 来说，一个 PE row 的 scratch 区可以看成：

```text
SUM[row, 0:256]
```

subtask1 写 SUM 时，CSV 只出现一个 `HSTT` 起点：

```text
HSTT SUM imm = half_addr(row * 256)
```

subtask2 读 SUM 时，CSV 显式读四个 slot：

```text
ILDMT SUM imm = half_addr(row * 256 + 0)
ILDMT SUM imm = half_addr(row * 256 + 64)
ILDMT SUM imm = half_addr(row * 256 + 128)
ILDMT SUM imm = half_addr(row * 256 + 192)
```

所以 SUM 的内部布局也像连续 scratch row：

```text
SUM[row, 0:256]
  slot0 = SUM[row, 0:64]
  slot1 = SUM[row, 64:128]
  slot2 = SUM[row, 128:192]
  slot3 = SUM[row, 192:256]
```

这里需要注意一层 vendor 后端细节：`HLDT / ILDMT / HSTT` 是 pseudo memory op。
`common_oper/csv_oper.cpp` 会把它们展开成底层：

```text
HLDT  -> LDN
ILDMT -> LDM
HSTT  -> STD
```

并追加若干 operand group 指令。当前配置里：

```text
OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE = 4
```

追加指令还会继续调整 `imm`。所以 CSV 中的一条 memory op 更像一个
vector/chunk 搬运入口，而不是单个 scalar 读写。对 OpenFabric 的抽象来说，
更稳妥的表达是：

```text
TileAccess:
  tensor = X / Y / SUM
  row
  chunk_start
  chunk_extent

VendorCsvAddress:
  base_slot
  imm = half_addr(row-major element offset of chunk_start)
```

也就是说：

```text
高层看 tile/chunk 是否连续；
CSV 只写 chunk 起点；
vendor pseudo expansion 再把 chunk 搬运拆成底层指令。
```

当前能确认的健康抽象边界是：

```text
DTensor tile:
  连续的 row/chunk 语义。

CSV memory op:
  chunk 起点 + base slot。

common_oper:
  pseudo op 展开成底层 LDN/LDM/STD 序列。
```

### softmax 的 SUM 是 SPM 内部中间 DTensor

这个发现很重要：当前 softmax 并不是纯粹一段 PE 内部计算。它显式使用了
SPM 里的一个中间存储区域：

```text
SUM
```

从 `SoftmaxDistributedPlan`、generated runtime header 和 base row dump 看：

```text
SUM initial_base = 32768
SUM -> base_addr slot0
```

从 CSV memory dump 看：

```text
subtask1:
  HSTT sum_tmp_* -> SUM

subtask2:
  ILDMT SUM -> sum_tmp_*_slot
```

所以这个 `SUM` 的真实语义是：

```text
SPM-resident reduction scratch
```

它在两个 vendor subtask 之间传递 softmax 的中间归约结果：

```text
X[row, 0:512]
  -> subtask1 / PE local exp + partial sum
  -> SUM[row, 0:256] in SPM
  -> subtask2 reads SUM slots
  -> normalize and write Y[row, 0:512]
```

这和 OpenFabric 前面的高层抽象是吻合的。可以把它映射成：

```text
DTensor X[64,512]
DTensor SUM_scratch[64,256]  // SPM internal, not user-visible output
DTensor Y[64,512]

stage softmax_reduce:
  reads  X[row, :]
  writes SUM_scratch[row, :]

stage softmax_normalize:
  reads  X[row, :]
  reads  SUM_scratch[row, :]
  writes Y[row, :]
```

注意这里的 `SUM_scratch` 不是普通最终 tensor，也不是 runtime 输出。
它是算子内部的编译期 buffer：

```text
生命周期:
  只在 softmax kernel 内部有效。

位置:
  SPM。

可见性:
  跨 subtask 可见；
  对 host / RISC-V app 不是最终结果。

地址实现:
  instance row 绑定 SUM 大基址；
  CSV imm 选择 row / PE / scratch slot。
```

因此以后抽象 softmax 不能只写：

```text
Y = softmax(X)
```

中间层应该显式知道有一个 internal scratch：

```text
Y, scratch = lower_softmax(X)
```

或者更贴近编译器 IR：

```text
scratch = alloc_spm_scratch("SUM", shape=[64, 256])
softmax_reduce(X, scratch)
softmax_normalize(X, scratch, Y)
```

这样 OpenFabric 往下生成 vendor 输入时，就有一个合法来源去生成：

```text
generated runtime/slot projection:
  "SUM" -> SPM base

instance_conf_info:
  base_addr[slot(SUM)] = SUM stage-shard base

CSV:
  HSTT / ILDMT with base_addr_idx = slot(SUM)
```

人话讲：

```text
SUM 是 softmax 的内部 SPM DTensor。
vendor 只是把它暴露成一个 base_addr slot 和若干 HSTT/ILDMT 指令。
```

这也解释了为什么 active instance row 不需要按 task 变化：

```text
instance row 只说：
  X base = 0
  Y base = 16384
  SUM base = 32768

task / PE / lane 的 tile 坐标全部在 CSV imm 里完成。
```

所以我们接下来做抽象时，不能只建 `StageShard -> base row`。
还必须建一层：

```text
TileAccess -> PE-local CSV imm
```

当前 softmax 的第一版公式可以是：

```text
row = task_id * rows_per_task + pe_id

input/output lane:
  col = lane_id * 256
  imm = half_addr(row * 512 + col)

SUM scratch slot:
  slot_col = slot_id * 64
  imm = half_addr(row * 256 + slot_col)
```

这就是从 vendor dump 反推回来的 DTensor 地址语义。

表里 `inst1..inst2047` 也被填了可预测的下一 shard 行：

```text
inst1 -> (40960, 16384, 32768, INVALID)
```

这是因为生成器按当前 softmax tile 公式计算了 `statement_prefix = 64`：

```text
SUM delta    = half_addr(64 * 256) = 8192
input delta  = half_addr(64 * 512) = 16384
output delta = half_addr(64 * 512) = 16384
```

不过在当前 app.conf 里每个 task 的 `Instance Times` 是 1，所以这些后续 rows
不是当前执行路径里的 active repeat。它们更像 vendor 固定表宽下的备用行。

inactive subtask slot 则是全 INVALID：

```text
task0 subtask2 inst0 -> (INVALID, INVALID, INVALID, INVALID)
task1 subtask2 inst0 -> (INVALID, INVALID, INVALID, INVALID)
...
```

这份 dump 给我们的目标约束是：

```text
Active row:
  row.base_addr[slot(SUM)]    = SPM_SUM_ADDR
  row.base_addr[slot(input)]  = SPM_softmax0_input0_ADDR
  row.base_addr[slot(output)] = SPM_softmax0_output0_ADDR

Unused / later row:
  row.base_addr[slot(buffer)] =
    SPM_buffer_ADDR + layout_offset(statement_prefix)

Inactive subtask:
  row.base_addr[*] = INVALID
```

也就是说，后续 `StageShard -> VendorAddressProjection` 的第一拳应该打在这里：

```text
不要先碰 CSV / PE 模板；
先让 config_program 用显式 StageShard 计算出完全相同的 base row。
```

这样二进制可比性最强，风险也最小。

## GEMM 的对应心智模型

GEMM 更能说明为什么 DTensor / tile 抽象必要：

```text
GEMM fiber(m, n, k):
  reads  A(m, k)
  reads  B(k, n)
  updates C(m, n)
```

对应到 DFU3500 vendor ABI，可以先这样想：

```text
subtask prepare:
  instance row 决定 C(m, n) shard 的初始化 / accumulator 基址。

subtask k-loop body:
  每个 instance 对应一个 k_tile。
  instance row 决定这一轮 A(m, k)、B(k, n)、C(m, n) 的大 shard 基址。

subtask store:
  instance row 决定最终 C/Y(m, n) shard 的输出基址。
```

PE 则在这些 shard 里面分工：

```text
PE(row, col)
  通过 CSV 模板和 imm 访问 A/B/C shard 内部自己的 lane / micro-tile。
```

所以 GEMM 也不应该靠：

```text
base_addr[A] += A_stride
base_addr[B] += B_stride
base_addr[C] += C_stride
```

来表达 `k_tile` 推进。更好的表达是：

```text
k_instance -> k_tile
address_of(A, m_tile, k_tile)
address_of(B, k_tile, n_tile)
address_of(C, m_tile, n_tile)
```

最后再投影成 vendor row。

## 代码重构路线

这部分应该慢慢做，每一步都跑二进制一致性测试。

第一步：只在 `config_program` 里把命名立住。

```cpp
struct VendorExecutionPlacement {
  int task_id;
  int subtask_id;
  int instance_id;
};

struct StageShard {
  VendorExecutionPlacement placement;
  LogicalTile tile;
};

struct BaseSlotBinding {
  string buffer_name;
  int base_slot;
};
```

第二步：把 softmax 的 base row 生成改成读 plan。

```text
make_softmax_stage_shard(placement)
make_softmax_base_slot_bindings(...)
emit_softmax_base_row(stage_shard, bindings)
```

第三步：把 CSV memory emitter 里的 `mem_base(array_name)` 和 config generator 的
slot binding 收敛到同一份 plan。

```text
同一个 BaseSlotBinding 同时服务：
  tempfile.h / array_name_to_base_num
  CSV base_addr_idx
  instance_conf_info row
```

第四步：保留 legacy 分支，但降级成 fallback。

```text
advance_legacy_non_softmax_base_row(...)
  只用于还没迁移到 tile-based AddressPlan 的 vendor 通用模板。
```

代码注释上应该明确：

```text
这是兼容旧模板的地址游标推进，不是 OpenFabric 地址语义。
```

第五步：迁移 GEMM 或下一个算子时，不复制 softmax 的公式，而是补充新的
`TileAccessPlan`：

```text
elementwise:
  fiber(tile) reads X(tile), writes Y(tile)

softmax:
  stage1 reads X(row_tile), writes SUM(row_tile)
  stage2 reads X(row_tile), reads SUM(row_tile), writes Y(row_tile)

gemm:
  fiber(m, n, k) reads A(m,k), reads B(k,n), updates C(m,n)
```

## 判断一段代码是不是又走回坏路

如果代码里出现这些味道，就说明又在往地址游标退化：

```text
用 instance_id 直接乘 stride 到处算地址。
不同文件各自维护 array_name -> base slot。
CSV 里的 base_addr_idx 和 instance row 的 slot binding 来源不同。
PE 被隐式编码进 base_addr_idx。
一个 helper 同时知道 task/subtask/instance、PE、buffer layout、vendor CSV 字段。
```

比较健康的形态应该是：

```text
VendorExecutionPlacement -> StageShard
StageShard + TensorRegion -> base row
PEWorkPartition + TileAccess -> imm
BaseSlotBinding -> base_addr_idx
VendorAddressProjection -> vendor fields
```

这就是我们从旧 OpenFabric DTensor 设计里应该继承的部分：

```text
保留 DTensor / tile / PE work 的语义分层；
不再自顶向下替代 vendor 工具链；
只在最窄、最可验证的地方接管地址语义生成。
```
