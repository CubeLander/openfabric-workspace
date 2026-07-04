# Subtask Graph 编译链路笔记

日期：2026-05-31

这条笔记继续沿着“产物如何生成”往前追，重点覆盖：

```text
app*.conf
  -> Task_Group::readFromTaskFile
  -> Task::subtaskConstruct
  -> SubTask::read_inst_block_collect
  -> SubTask::subtask_graph_extend
  -> libsubtask.so::generateGraph
  -> INST_BLK_MAP::map_subtask
  -> exe_block_gen
  -> task_print 输出 bin
```

## app*.conf 是什么

以 `CASE/softmax_1/app0.conf` 为例：

```text
task(task_name:task0;reuse_input_reg:;reuse_output_reg:;Execute Times : 1;subtask_num:2)
{
subtask(subtask_name:subtask1;reuse_input_reg:;reuse_output_reg:;Instance Times : 1;code_path:template/;csv_amount:16;graph height:4;graph width:4)
subtask(subtask_name:subtask2;reuse_input_reg:;reuse_output_reg:;Instance Times : 1;code_path:template/;csv_amount:16;graph height:4;graph width:4)
}
```

它不是直接描述 device 指令，而是描述应用中的 task/subtask 容器：

- task name
- task execute times
- subtask 数量
- 每个 subtask 的 instance times
- 每个 subtask 的 csv 模板数量
- 每个 subtask 的 graph height / graph width

`Task_Group::readFromTaskFile()` 用非常直接的文本解析方式读取这个格式：遇到 `task(...)` 就解析 task 参数，再读取 `{...}` 里面的 `subtask(...)` 列表。

## Task/SubTask 构造

`Task_Group::tasksConstruct()` 只是遍历 task：

```text
for each task:
  Task::subtaskConstruct(task_name)
```

`Task::subtaskConstruct()` 对每个 subtask 做三步：

```text
SubTask::read_inst_block_collect(task_name)
SubTask::subtask_graph_extend(task_name)
SubTask::count_root_block_amount(task_name)
```

这说明 subtask 的编译分两段：

1. 先把 `template/*.csv` 读成 `Inst_Block_Collect`。
2. 再由 `libsubtask.so::generateGraph` 把这些 block 组织成 graph node。

## CSV 到 Inst_Block

`SubTask::read_inst_block_collect()` 对 `csv_amount` 做循环：

```text
taskX/subtaskY/template/0.csv
taskX/subtaskY/template/1.csv
...
taskX/subtaskY/template/N.csv
```

每个 CSV 会进入：

```text
Inst_Block::readFromTemplate(file)
  -> Csv_Operate::readFromCsv(file)
  -> Csv_Operate::process()

Inst_Block::process()
  -> 按 unit_inst_type 切成四段:
       ld_stage_insts
       cal_stage_insts
       flow_stage_insts
       st_stage_insts
```

CSV 的字段格式是：

```text
inst_name,inst_tag_name,src_reg_idx0,src_reg_idx1,dst_reg_idx,dst_pe_idx,imm,iteration
```

例子：

```text
HLDT,HLDT0,,,softmax0_input0_0_0_0,0,0,1
IMM,IMM2,,,rShflF0,,16,0
FMUL,FMUL11,FP0_softmax0_input0_0_0_0,rLog2E,FP0_softmax0_input0_0_0_0,,,1
FEXP2,FEXP213,FP0_softmax0_input0_0_0_0,,FP0_softmax0_input0_0_0_0,,,1
HSTT,HSTT40,,,sum_tmp_0_0,0,0,0
```

`Csv_Operate::process()` 做的主要事情：

- 把 `inst_name` 映射成 `opCode`。
- 填 `unit_inst_type`、latency、imm、iteration 条件。
- 把字符串寄存器名映射成局部 operand index。
- 处理部分伪/向量化指令展开，例如 `HLDT/HSTT/COPYT` 等会展开成底层 `LDN/STD/COPY` 类指令。

这里的 CSV 已经非常接近 device instruction IR。也就是说，当前“算子编译”的前端很大一部分工作发生在更早的模板代码生成阶段；`build_app` 主要做打包、映射、资源分配和结构序列化。

## libsubtask.so 和 generateGraph

`SubTask::subtask_graph_extend()` 会动态加载：

```text
taskX/subtaskY/build_so/libsubtask.so
```

然后用 `dlsym` 找：

```cpp
extern "C" void generateGraph(
    string task_name,
    string subTask_name,
    vector<GRAPH_NODE>& m_nodes,
    Inst_Block_Collect& inst_block_collect,
    uint64_t graph_height,
    uint64_t graph_width);
```

对 `softmax_1` 来说，`generateGraph()` 的典型逻辑非常薄：

```text
PE_NUM = PER_TASK_PE_NUMBER[task_id] * PE_NUM_BASE

if PE_NUM * INPUT_BATCH_SIZE < 16:
  m_nodes.resize(PE_NUM * INPUT_BATCH_SIZE)
  for i in PE_NUM:
    m_nodes[i].m_pos_idx_df = PE[i]
    Graph_Extend::initNode(m_nodes[i], i, true, inst_block_collect)
else:
  m_nodes.resize(graph_height * graph_width)
  for i,j in graph grid:
    index = i * graph_width + j
    m_nodes[index].m_pos_idx_df = i * graph_width + j
    Graph_Extend::initNode(m_nodes[index], index, true, inst_block_collect)
```

`Graph_Extend::initNode()` 会：

- new 一个 `Inst_Block`
- 从 `inst_block_collect.inst_blocks[blk_type]` 拷贝对应 block
- 标记 `exe_block.valid = true`
- 把这个 `Inst_Block` 挂到 `GRAPH_NODE::m_pInst_Block`
- 设置 `node.m_node_type = to_string(blk_type)`

也就是说，在 softmax 当前 case 里，graph node 和 CSV block 基本是一一对应的：一个 node 挂一个 cloned `Inst_Block`，node 的目标 PE 由 `m_pos_idx_df` 指定。

## graph relationship

`Graph_Extend::set_relationship_node()` 可以建立 node 间父子关系，并把 parent flow stage 里的 copy 指令绑定到这条边。

不过在当前 `softmax_1` 已生成的 `build_so/test_graph_extend.cpp` 中，没有看到调用 `set_relationship_node()`。这意味着这个 case 的 subtask graph 更像一组并列 node，依赖关系主要不在 graph edge 层表达，而可能由：

- task/subtask 顺序配置表达；
- 每个 node 内部 CSV 指令序列表达；
- SPM/instance 地址规划表达。

这点需要后面在 `gemm_template_fusion` 或服务器上的 `TestOp_SIMD128_COND` 再验证。更复杂算子很可能会用 `set_relationship_node()`。

## map 到 PE

`Task_Group::map()`：

```text
start_map_app()
for each task:
  start_map_task()
  for each subtask:
    map_subtask(subtask.m_nodes, false, subtask.subTask_name)
  end_map_task()
end_map_app()
```

`INST_BLK_MAP::map_subtask()`：

```text
sortByDepth(nodes, sort_nodes, true)
map(nodes, sort_nodes)
m_subtasks_name.push_back(subtask_name)
m_graph_idx++
```

默认 `INST_BLK_MAP::map()` 里，如果 node 设置了 `m_pos_idx_df`，就直接用它作为 `pe_idx`：

```text
if node.m_pos_idx_df != 0xFFFFFFFF:
  pe_idx = node.m_pos_idx_df
push_node_to_pe(m_pes, node, pe_idx, m_graph_idx)
```

`push_node_to_pe()` 会给 node 填：

- `m_pos.pe_idx`
- `m_pos.x/y`
- `m_pos.graph_idx`
- `m_pos.block_idx`

然后把 node 指针放进对应 `PE::m_pGraph_nodes`。

所以在 softmax 中，`generateGraph()` 已经提前指定了 PE 布局，mapper 基本是在确认和登记位置。

## 资源分配和 copy 指令修正

`end_map_task()` 会做：

```text
distribute_task_resource()
rectify_copy_inst()
counting_task_resource()
get_app_max_resource()
```

关键点：

- `distribute_task_resource()` 会重新分配 block index，并调用 `distribute_operand()`。
- `distribute_operand()` 把 CSV 中的字符串寄存器 tag 转成最终 operand index，并为每条 instruction 写入 `block_idx`。
- `rectify_copy_inst()` 会修正跨 node/跨 PE copy 指令的目标 block、PE 坐标和目标 operand。

由于 `softmax_1` 当前 graph edge 很少或没有，copy 修正的价值在这个 case 里可能不明显；复杂 graph 才会更关键。

## exe_block_gen

`exe_block_gen(PE *pes)` 做三件事：

1. 给每个 PE 上的新 graph node 分配 `exe_block_idx`。
2. 根据 graph parent/child relationship 填 `successors/predecessors` 和 `req_activations`。
3. 生成 `exeBlock_conf_info_t`，包括：
   - PE 位置；
   - block index；
   - successor/predecessor；
   - ld/cal/flow/st 四个 stage 的 instruction 数量；
   - 每个 stage 的 start pc；
   - block end pc。

后面 `task_print.cpp` 会把这些 `exeBlock_conf_info_t` padding 后写成 `exeblock_conf_info_file.bin`。

## 当前体系理解

更准确地说，当前源码里的“kernel 编译”分层是：

```text
手写/预生成 case contract
  -> csv_generate/conf.h
  -> csv_generate/conf_PEmap.h
  -> riscv/testarm.c
  -> gpdpu_TestOp/task*/subtask*/template/*.cpp

csv_generate/run.sh
  -> test_app_conf_generate.c 读取 conf.h/conf_PEmap.h
  -> 生成 app.conf / instance_conf_info_file.bin / tempfile.h
  -> gpdpu_TestOp/app_build 生成 CSV 指令模板

build_so/libsubtask.so
  -> generateGraph: 把 CSV block 组织成 subtask graph，并指定 PE 位置

build_app
  -> 读取 app.conf
  -> dlopen libsubtask.so
  -> 读 CSV 为 Inst_Block
  -> graph node map 到 PE
  -> 资源/operand/block index 分配
  -> exe_block_gen
  -> 打包 inst/exeblock/task/subtask/instance 配置
```

所以我们现在已经能比较明确地说：

- device 侧“指令主体”来自 CSV 模板。
- `libsubtask.so` 不是最终 device 代码，而是 host-side 编译插件，用来生成 graph。
- `build_app` 是 assembler/packer，把 graph、instruction、task/subtask 配置打包成 simulator/device 能读的二进制。
- `riscv/testarm.c` 是 CPU 侧控制程序，调用 DPU API 触发 DMA/执行；它不生成 device 指令。

## 下一步

最值得继续追的两个点：

1. 各 `gpdpu_TestOp/task*/subtask*/template/*.cpp` 如何生成 CSV。这是当前可运行路径里真正的算子模板 lowering。
2. 写一个 decoder 反解 `insts_file.bin` 和 `exeblock_conf_info_file.bin`，把二进制内容和 CSV/build_app 内部结构对上。

如果目标是理解“算子怎么编译”，下一步应该优先看第 1 点；如果目标是验证我们对 device 包布局的理解，应该优先做第 2 点。

## 继续往前：CSV 是谁生成的

现在又确认了一层：`template/*.csv` 不是手写文件，而是 `gpdpu_TestOp/app_build` 生成的。

`CASE/softmax_1/csv_generate/run.sh` 会：

```text
cd ../gpdpu_TestOp
./run.sh
```

`gpdpu_TestOp/run.sh` 很短：

```text
make clean
rm task*/subtask*/template/*.csv
make -j
./app_build
```

`gpdpu_TestOp/Makefile` 会把这些源一起编进 `app_build`：

```text
task_main.cpp
task*/subtask*/template/*.cpp
```

`task_main.cpp` 负责根据 `case_name` 构造 `vector<op> all_ops`。对于 `softmax_1`，`conf_PEmap.h` 里写着：

```text
static string case_name = "softmax";
```

所以 `task_main.cpp` 会构造：

```text
op softmax
  op_owner = "softmax"
  op_type = OpType::SOFTMAX
  allInput = {"softmax0_input0"}
  allOutput = {"softmax0_output0"}
```

然后调用：

```text
do_task0_subtask1(all_ops)
do_task1_subtask1(all_ops)
do_task2_subtask1(all_ops)
do_task3_subtask1(all_ops)

如果是 SOFTMAX/RMSNORM:
  do_task0_subtask2(all_ops)
  do_task1_subtask2(all_ops)
  do_task2_subtask2(all_ops)
  do_task3_subtask2(all_ops)

如果是 LARGE_SCALE 的 SOFTMAX:
  继续生成 subtask3/subtask4
```

`do_task0_subtask1()` 这一类函数在：

```text
gpdpu_TestOp/task0/subtask1/template/task0_subtask1.cpp
```

它的核心行为是：

```text
for each pe_id:
  根据 task_order / PER_TASK_PE_NUMBER / pe_task_unrollid_start2end 计算本 PE 对应的数据片段
  根据 op_type 生成 ld_insts/cal_insts/st_insts
  写 task<task_id>/subtask<subtask_id>/template/<pe_id>.csv
```

写 CSV 时顺序固定：

```text
先写 LD 指令
再写 CAL 指令
最后写 ST 指令
```

这刚好对应后面 `Inst_Block::process()` 对 CSV 的要求：CSV 中的指令必须先 LD、再 CAL、再 FLOW、再 ST，否则 `Inst_Block::process()` 会按 stage 顺序切分失败。

因此当前 softmax 的完整可运行编译链可以再补全为：

```text
手写/预生成 case contract
  -> csv_generate/conf.h
  -> csv_generate/conf_PEmap.h
  -> riscv/testarm.c
  -> gpdpu_TestOp/task*/subtask*/template/*.cpp

csv_generate/test_app_conf_generate.c
  -> 读取 conf.h/conf_PEmap.h
  -> 生成 app*.conf
  -> 生成 instance_conf_info_file*.bin
  -> 生成 tempfile.h

gpdpu_TestOp/app_build
  -> task_main.cpp 根据 case_name 构造 op 列表
  -> do_taskX_subtaskY 根据 PE 切分和 op_type 写 template/<pe_id>.csv

build_so/libsubtask.so
  -> generateGraph 把每个 CSV block 包成 GRAPH_NODE

build_app
  -> 读 app*.conf
  -> 读 CSV 为 Inst_Block
  -> map 到 PE
  -> exe_block_gen
  -> 输出 cbuf/micc 所需中间 bin
```

这说明我们真正要理解“算子 lowering”的话，下一层要读的是：

- `conf.h/conf_PEmap.h`：当前 case 的手写/预生成 contract，描述 shape、SPM/DDR、task/subtask/PE map。
- `gpdpu_TestOp/task*/subtask*/template/*.cpp`：把 op 语义 lower 成 CSV 指令序列。

补充修正：`CASE/softmax_1/run.sh` 不调用 `exec.sh`，也不编译 `riscv_main.cpp` / `elementwise_template.cpp`。全仓搜索没有找到 `execute_elementwise(...)` 的调用点；直接编译 `riscv_main.cpp elementwise_template.cpp` 也会因为缺 `main` 链接失败。因此 `elementwise_template.cpp` 只能作为历史/残留生成器线索，不能再放进当前 softmax 的实际编译链。
