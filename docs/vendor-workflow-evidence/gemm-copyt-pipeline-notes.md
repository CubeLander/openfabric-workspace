# GEMM COPYT Pipeline Notes

这份文档记录当前在 `gemm_template_fusion` 例子里观察到的 COPY/COPYT
现象，以及 COPYT 指令从静态 PE 规划到最终 runtime 二进制的可见编译链路。

重点结论：

```text
copyA 决定哪些 PE 之间需要传 A tile。
new_temp.c 根据 copyA 生成 COPYT CSV。
test_graph_extend.cpp 根据 copyA 建图，把 copy 节点和 cal 节点接起来。
common_oper/build_app 解析 CSV、建依赖图、映射到 PE、修正 COPYT 目标。
task_print.cpp 把 COPYT 归一后的 COPY 写进 insts_file.bin。
insts_file.bin 最终拼入 cbuf_file.bin，成为闭源 runtime 消费的输入。
```

## 当前可见边界

在当前恢复出的源码里，`copyA` 已经是一个生成好的静态 plan：

```text
application/CASE/gemm_template_fusion/csv_generate/conf_PEmap.h
```

其中：

```c
static map<int ,vector<pair<int ,int>>> copyA = {
  {0, {{0,1},{1,2},{2,3},{4,5},{5,6},{6,7},{8,9},{9,10},{10,11},{12,13},{13,14},{14,15}}},
  ...
};
```

同一个文件还有：

```c
static map<int ,vector<int>> loadA = {
  {0, {0,1,2,3}},
  {4, {0,1,2,3}},
  {8, {0,1,2,3}},
  {12, {0,1,2,3}}
};
```

这说明当前 GEMM 的 A tile 复用策略是：

```text
1. PE 0/4/8/12 先加载 A。
2. A 沿着每行相邻 PE 传播：
   0->1->2->3
   4->5->6->7
   8->9->10->11
   12->13->14->15
3. 每个 PE 再使用自己的 A/B tile 做 HMMAL。
```

目前判断：当前 example 中的 `copyA` 是开发者手写在 `conf_PEmap.h`
里的 PE 间数据复用计划，不是由一个已经接入 workflow 的更高层框架自动决定。
也就是说，算子开发者需要显式决定：

```text
哪些 PE 先通过 HLDT 加载可复用数据
哪些 PE 通过 COPYT 把数据传给邻居
这些 copy 关系如何服务后续 HMMAL 计算
```

`OperatorGemm.h` 里虽然声明了 `get_Load_Copy_info()` /
`gen_confh_pemaph(...)` 这类看起来像上游规划器的接口，但当前目录下只看到
声明，没有看到接入本 example 的完整实现链路。对我们要重建的 workflow 来说，
可靠边界应当设在 `conf_PEmap.h`：它是开发者输入的一部分，workflow 只负责
消费其中的 `loadA` / `copyA` 并编译进 runtime package。

## 现象一：COPYT 只出现在 subtask2

恢复出的分析目录：

```text
former testcase/build_out/gemm_template_fusion_new_temp_analysis/sources/
```

其中 `task0_1.c`、`task1_1.c`、`task2_1.c`、`task3_1.c` 对应原始：

```text
gpdpu_tensor/task*/subtask2/template/new_temp.c
```

这些文件是 COPYT 最明确的位置。它们都 `extern` 了：

```c
extern map<int, vector<int>> loadA;
extern map<int, vector<pair<int, int>>> copyA;
```

然后在 `subtask2` 里按这个顺序生成 CSV：

```text
load A  -> HLDT
copy A  -> COPYT
load B  -> HLDT
compute -> HMMAL / RXINT / TRCTT 等
```

## 现象二：COPYT CSV 是按 copyA 的 source PE 生成的

`new_temp.c` 的核心逻辑是：

```c
for (int pe_id = 0; pe_id < taskAddr_per_pe_A.size(); pe_id++) {
  for (const auto& p : copyA[unroll_i]) {
    if (p.first == pe_id) {
      fprintf(fp[index], "COPYT,...");
    }
  }
}
```

也就是说：

```text
copyA pair = (source_pe, dest_pe)
当前 pe_id == source_pe 时，生成 COPYT
```

当前 CSV 行里没有直接写出 `p.second`，而是把 COPYT 放进 source PE 对应的
copy node，再通过 graph edge 决定它真正指向哪个 child node/PE。

这点很关键：`copyA` 不只是决定是否生成 COPYT，还会在后面的
`test_graph_extend.cpp` 里决定 node 之间的边，从而让 common_oper 有机会把
COPYT 修正到正确目标 PE。

## 现象三：subtask2 的 CSV 数量不是简单 16 个 PE

`app*.conf` 里每个 GEMM task 都有：

```text
subtask2(...; Instance Times : 4; code_path:template/; csv_amount:32; graph height:4; graph width:4)
```

这说明 `subtask2` 不是“每个 PE 一个 CSV”这么简单。以 task0 为例，生成器里
实际分成几类 CSV/node：

```text
load A node       来自 loadA，只有部分 PE
copy A node       来自 copyA，只有作为 source 的 PE
load B + cal node 每个 PE 都有
```

所以 `csv_amount:32` 表示这个 subtask 内的 instruction block 数量，而不是
物理 PE 数量。`graph height:4` / `graph width:4` 才对应 4x4 PE mesh。

## COPYT 编译链路

### 1. 手写静态 PE 规划

输入：

```text
csv_generate/conf_PEmap.h
```

关键数据：

```text
taskAddr_per_pe_A
taskAddr_per_pe_B
taskAddr_per_pe_C
loadA
copyA
HASCP2CP
```

其中 `copyA` 是 COPYT 规划的源头。当前工作假设是：它由算子开发者手动维护，
不是本地 workflow 自动生成。

### 2. 生成 app 配置和 instance 配置

入口：

```text
csv_generate/test_app_conf_generate.c
```

它读取 `loadA` / `copyA`，并据此计算 `subtask2` 的 `csv_amount`。它还生成：

```text
app0.conf ... app3.conf
instance_conf_info_file*.bin
instance_conf_info_for_rtl_file*.bin
```

这些文件告诉后续 `build_app`：每个 task 有哪些 subtask、每个 subtask 有多少
CSV instruction block、图尺寸是多少。

### 3. 生成 COPYT CSV

入口：

```text
gpdpu_tensor/task*/subtask2/template/new_temp.c
```

它根据 `copyA[unroll_i]` 写出：

```text
task*/subtask2/template/<index>.csv
```

COPYT 行形如：

```csv
COPYT,COPYT0,gemm0_input0_0_0,,gemm0_input0_0_0,1,,1,,,2
```

字段语义按 CSV header：

```text
inst_name      = COPYT
inst_tag_name  = COPYT0
src_reg_idx0   = gemm0_input0_0_0
dst_reg_idx    = gemm0_input0_0_0
dst_pe_idx     = 1
iteration      = 1
extra_fields   = 0,0,2
```

当前观察：`dst_pe_idx` 在 CSV 中先是一个临时/类型字段。真正的目标 PE 会在图
构建和映射阶段由 child node 的 PE 坐标覆盖。

### 4. 生成 subtask 图

入口：

```text
gpdpu_tensor/task*/subtask2/build_so/test_graph_extend.cpp
```

它同样读取 `loadA` / `copyA`，创建三类节点：

```text
ld node
cp node
ld + cal node
```

然后建立依赖边：

```text
PE 内 ld -> cal
PE 内 ld -> cp
PE 间 cp -> cp
PE 间 cp -> cal
```

`Graph_Extend::set_relationship_node(parent, child, type)` 会扫描 parent
node 里的 flow-stage instructions，把 `dst_pes_pos[0].x == type` 的 copy
instruction 挂到这条 parent->child 边上。

因此 `type` 是连接 COPYT CSV 和图边的桥。后续映射阶段会根据这条边把 COPYT
的目标 block、目标 PE 坐标、目标寄存器补完整。

### 5. build_app 解析 CSV 和建图

入口：

```text
application/build_app/main.cpp
```

主要流程：

```text
Task_Group::readFromTaskFile(app*.conf)
Task_Group::tasksConstruct()
Task_Group::map(...)
Print_Task_Group::print_inst(...)
```

`common_oper/task_create.cpp` 里，`SubTask::read_inst_block_collect()` 按
`csv_amount` 读取：

```text
taskX/subtaskY/template/0.csv
taskX/subtaskY/template/1.csv
...
```

每个 CSV 经由：

```text
Inst_Block::readFromTemplate()
Csv_Operate::readFromCsv()
Csv_Operate::process()
```

转成内部 `Inst` 列表。

### 6. CSV 层 COPYT 归一化

`common_oper/csv_oper.cpp` 注册了：

```text
COPYT -> OP_COPYT, needPeIdx = true, FLOW_UNIT_INST_TYPE
COPY  -> OP_COPY,  needPeIdx = true, FLOW_UNIT_INST_TYPE
```

解析 CSV 时：

```text
dst_pe_idx -> inst.dst_pes_pos[0].x
src/dst register tag -> internal register index
extra_fields -> inst.extra_fields
```

`Csv_Operate::process()` 会把伪/模板类指令展开成底层指令名。对 `COPYT` 而言，
第一条和后续展开出来的指令都会变成底层 `COPY` 形态。这个展开和
`OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE` 有关，所以一条 tensor COPYT 可能对应
多条底层 COPY。

### 6.1 CSV 寄存器字符串如何变成指令地址

CSV 里的寄存器字段不是最终指令里的字符串。它们是符号化的 operand tag，例如：

```text
gemm0_input0_0_0
gemm0_input1_0_7
gemm0_output0_0_3
ALPHA
BET
```

第一轮解析发生在 `common_oper/csv_oper.cpp`：

```text
Csv_Operate::constructOneCsvItem()
  src_reg_idx0_tag = CSV 第 3 列
  src_reg_idxl_tag = CSV 第 4 列
  dst_reg_idx_tag  = CSV 第 5 列
  getRegIdx(tag)   = 给同一个 CSV block 内的 tag 分配小整数
```

这一步会得到临时的：

```text
src_operands_idx[0]
src_operands_idx[1]
dst_operands_idx[0]
```

同时字符串 tag 仍然保存在 `Inst` 对象里，供后面的 PE/task 资源映射阶段使用。

第二轮分配发生在 `common_oper/inst_blk_map.cpp`：

```text
Task_Resource::fill_reg_idx()
  get_reg_idx(tag, reg_start_idx)
  layout_operand_idx(...)
```

这里会按当前 PE/task 的资源起点 `reg_start_idx` 重新把 tag 映射为最终 operand
index。最终写入二进制的是整数：

```text
src_operands_idx0
src_operands_idx1
dst_operands_idx0
```

字符串不会进入 `insts_file.bin`。它们只存在于 CSV / build_app 内部 IR 中，用来
表达数据依赖和虚拟寄存器身份。

PE-local operand RAM 的完整布局、12-bank 交错分配公式、以及 COPY 的源/目的
operand index 所属 PE 语义，记录在：

```text
pe-operand-index-model.md
```

### 7. 图映射阶段修正 COPY 目标

`common_oper/inst_blk_map.cpp` 的 `rectify_copy_inst()` 会进一步处理 COPY：

```text
fill_copy_inst(parent_node)
alter_local_copy_inst(node)
```

`fill_copy_inst()` 对跨节点 copy 做关键修正：

```text
dst_blocks_idx[0]      = child_node.block_idx
dst_pes_pos[0].x/y     = child_node PE 坐标
dst_operands_idx[0]    = child PE 上对应寄存器编号
OP_COPYT               -> OP_COPY
```

这一步说明：COPYT CSV 里的 `dst_pe_idx` 不是最终物理目标的唯一来源。最终目标
由 `test_graph_extend.cpp` 建出来的 parent->child 依赖边和 PE 映射结果共同
决定。

### 8. 打印进 runtime 二进制

`common_oper/task_print.cpp` 在遇到底层 `OP_COPY` 时写出：

```c
inst_t_copy_for_rtl copy_inst;
copy_inst.opCode = tmp_inst.opCode;
copy_inst.base_addr_idx = tmp_inst.flow_ack;
copy_inst.src_operands_idx0 = tmp_inst.src_operands_idx[0];
copy_inst.dst_operands_idx0 = tmp_inst.dst_operands_idx[0];
copy_inst.pos_x = tmp_inst.dst_pes_pos[0].x;
copy_inst.pos_y = tmp_inst.dst_pes_pos[0].y;
copy_inst.end_inst_flag = tmp_inst.end_inst;
copy_inst.block_idx = tmp_inst.block_idx;
```

也就是说最终 runtime/RTL 看到的不是文本 CSV，而是已经补全：

```text
copy opcode
源寄存器
目标寄存器
目标 PE 坐标
目标 block
flow ack / dependency index
```

的二进制 instruction record。

### 9. 进入 runtime package

`build_app` 先生成：

```text
simulator_bin/insts_file.bin
simulator_bin/exeblock_conf_info_file.bin
simulator_bin/instance_conf_info_file.bin
simulator_bin/tasks_conf_info_file.bin
simulator_bin/subtasks_conf_info_file.bin
```

随后 workflow/legacy run_mtr 逻辑会拼接：

```text
cbuf_file.bin = insts_file.bin
              + exeblock_conf_info_file.bin
              + instance_conf_info_file.bin

micc_file.bin = tasks_conf_info_file.bin
              + subtasks_conf_info_file.bin
```

所以 COPYT/COPY 的最终位置在：

```text
runtime_packages/<case>/config/cbuf_file.bin
```

更具体地说，它来自 `cbuf_file.bin` 前半部分的 `insts_file.bin`。

## 当前结论

当前例子中，COPY 指令的确定和编译可以分成两句话：

```text
开发者手写的 copyA 决定 copy 的拓扑意图：哪些 PE 的 A tile 要传给哪些邻居。
test_graph_extend + common_oper 决定 copy 的可执行落点：目标 PE 坐标、目标 block、目标寄存器。
```

我们已经能在本地完全复现“从 `conf_PEmap.h` 的 `copyA` 到
`runtime_package/config/cbuf_file.bin`”的编译链路。

尚未闭环的是：

```text
1. 是否存在厂商内部/历史版本的 copyA 自动生成器。
2. COPYT CSV 中 dst_pe_idx/type 字段的完整 ISA 语义。
3. 闭源 runtime/硬件如何根据 dependency 和 flow_ack 实际调度 COPY 与计算。
```

这些未知点不阻止我们重构 workflow，因为 runtime package 构造阶段只需要稳定
消费已有 `copyA`、`new_temp.c`、`test_graph_extend.cpp` 和 common_oper。
