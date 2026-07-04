# 任务创建与 generateGraph 调用链

这篇笔记面向学校团队内部讨论，用来解释当前仓库里“算子编译程序”到底如何从 GEMM 模板生成任务、子任务、图节点，最后变成 simulator/RTL 需要的 CBUF/MICC 配置文件。

## 一句话结论

当前这套流程不是在运行 kernel，而是在做离线任务构建：

`app*.conf` 描述 task/subtask -> `template/*.csv` 被读成 `Inst_Block` -> 每个 subtask 的 `build_so/libsubtask.so` 暴露 `generateGraph`，把 `Inst_Block` 组织成 `GRAPH_NODE` 依赖图 -> `INST_BLK_MAP::map_subtask` 把图节点映射到 PE/exeBlock/resource -> `Print_Task_Group` 序列化出 simulator/RTL 的任务配置和指令配置。

也就是说，`subtask_graph_extend` 是一个很关键的边界：它通过动态库把“每个 subtask 自己的图拓扑生成逻辑”插进通用 task 构建流程里。

## 上游输入

以 `gemm_template_fusion` 为例，CSV 和 app 配置来自：

- `testcase/application/CASE/gemm_template_fusion/gpdpu_tensor/task*/subtask*/...`
- 外层 `task0` 到 `task3` 是从 `gpdpu_tensor/task*` 复制出来的构建产物。
- `csv_generate/test_app_conf_generate.c` 会生成 `../app0.conf` 到 `../app3.conf`。

`test_app_conf_generate.c` 里每个 `appN.conf` 代表一个 task：

- `task_name` 是 `task0`、`task1`、`task2`、`task3`。
- `Execute Times` 来自 `task_loop`。
- `subtask_num` 通常是 3；如果有 fused epilogue，会有 `subtask4`。
- 每个 subtask 记录 `Instance Times`、`code_path:template/`、`csv_amount`、`graph height`、`graph width`。

在 GEMM 模板里，我们现在看到的语义大概是：

- `subtask1`：加载 C，并处理 beta scale。
- `subtask2`：加载/复制 A，加载 B，执行 HMMAL GEMM 计算。
- `subtask3`：store C。
- `subtask4`：可选 fusion epilogue。

`task0` 到 `task3` 更像四个并行 task slot / unroll 分片，而不是四个顺序阶段。顺序关系主要在每个 task 内部的 subtask 链上。

## build_app 入口

`testcase/application/build_app/run_mtr.sh` 会把 app case 的代码准备好，然后把多个 app 配置拼成参数：

```sh
./build_app app0.conf app1.conf app2.conf app3.conf
```

随后它把输出文件拼成两套结果：

- simulator:
  - `insts_file.bin`
  - `exeblock_conf_info_file.bin`
  - `instance_conf_info_file.bin`
  - `tasks_conf_info_file.bin`
  - `subtasks_conf_info_file.bin`
  - `data_inst_replace.bin`
- RTL:
  - `cbufData_inst.bin`
  - `cbufData_exeblock.bin`
  - `cbufData_instance.bin`
  - `miccData_task.bin`
  - `miccData_subtask.bin`
  - `instEnable.bin`
  - `taskEnable.bin`

补充确认：`CASE/gemm_template_fusion/build_app` 不是目录，而是一个 Linux x86-64 ELF 可执行文件，带 debug info，未 strip。它不是手写在 case 里的源码，而是由 `application/build_app/run_mtr.sh` 驱动生成的构建产物。

`run_mtr.sh` 的关键流程是：

```text
cd testcase/application/build_app
  -> cp main.cpp ../$app_name
  -> cp Makefile ../$app_name
  -> cd ../$app_name
  -> make clean
  -> make -j
  -> ./build_app app0.conf app1.conf ...
  -> rm main.cpp Makefile
```

所以 case 目录里留下的是编译后的 `build_app` 二进制，而临时复制过来的 `main.cpp` 和 `Makefile` 会在执行结束后被删除。后来我们在 `testcase/application/build_app/main.cpp` 和 `testcase/application/build_app/Makefile` 下找到了 OCR 图片材料，并已把它们还原成真正的源码文件。

这个判断还有两个证据：

- `objdump -p CASE/gemm_template_fusion/build_app` 显示它依赖 `libapp_build_common.so`、`libcommon.so`、`libdl.so.2` 等动态库。
- `nm -C CASE/gemm_template_fusion/build_app` 里 `main` 是本二进制定义的，但 `Task_Group::readFromTaskFile`、`Task_Group::tasksConstruct`、`Task_Group::map`、`Print_Task_Group::*` 都是未定义动态符号，说明这些逻辑来自 `common_oper` 侧共享库。

还有一个历史路径线索：`dwarfdump` 显示这个二进制的编译目录是：

```text
/home/liuzhe/simict/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion
```

而不是当前快照里的：

```text
testcase/application/CASE/gemm_template_fusion
```

这说明它很可能是在原始 `testcase/application/gemm_template_fusion` 目录结构下生成的，之后随 case 目录一起被整理/复制到了现在的 `CASE/gemm_template_fusion`。

从恢复后的 `main.cpp` 和反汇编结果可以确认 build_app 主入口的大致调用顺序：

```text
argv[1..] -> vector<string> app config names
new INST_BLK_MAP
new Print_Task_Group
for each app config:
  new Task_Group
  Task_Group::readFromTaskFile(config)
  Task_Group::tasksConstruct()
  Task_Group::map(inst_blk_map)
  task_groups.push_back(task_group)
exe_block_gen(pes)
for each task_group:
  task_group->task_idx = index
  Print_Task_Group::print_task_group(pes, task_group)
Print_Task_Group::print_inst(pes)
Print_Task_Group::fill_max_inst_per_pe()
Print_Task_Group::fill_task_simulator(task_groups)
Print_Task_Group::task_inst_enable_print(task_groups)
Print_Task_Group::print_for_micc_rtl(task_groups)
```

## Task 配置解析

核心代码在 `testcase/common_oper/task_create.cpp`。

调用链如下：

```text
Task_Group::readFromTaskFile(appN.conf)
  -> Task::create_task(...)
  -> Task::add_subtask(...)
       -> SubTask::create_subtask(...)
```

`Task_Group::readFromTaskFile` 负责读 `appN.conf`，按 `task(...) { subtask(...) ... }` 解析出 `Task` 和 `SubTask`。

`Task::create_task` 解析 task 级字段：

- `task_name`
- `reuse_input_reg`
- `reuse_output_reg`
- `Execute Times`
- `subtask_num`

`SubTask::create_subtask` 解析 subtask 级字段：

- `subTask_name`
- `code_dir = task_name + "/" + subTask_name`
- `reuse_input_reg`
- `reuse_output_reg`
- `Instance Times`
- `code_path`
- `csv_amount`
- `graph_height`
- `graph_width`

注意这里的 `code_dir` 很重要。例如 `task0/subtask2` 后续会直接定位到：

```text
task0/subtask2/template/*.csv
task0/subtask2/build_so/libsubtask.so
```

## SubTask 构建流程

配置解析完成之后，任务构建走：

```text
Task_Group::tasksConstruct()
  -> Task::subtaskConstruct(task_name)
       -> SubTask::read_inst_block_collect(task_name)
       -> SubTask::subtask_graph_extend(task_name)
       -> SubTask::count_root_block_amount(task_name)
```

### 1. 读取 CSV 指令块

`SubTask::read_inst_block_collect` 按 `csv_amount` 遍历：

```text
code_dir + "/template/" + i + ".csv"
```

每个 CSV 会创建一个 `Inst_Block`：

```cpp
pInst_block->readFromTemplate(file_name);
pInst_block->process();
m_Inst_Block_Collect.inst_blocks.push_back(*pInst_block);
```

所以 `template/*.csv` 是真正的指令模板输入；此时还没有图拓扑，只有一组指令块。

### 2. 动态加载 subtask 图生成插件

`SubTask::subtask_graph_extend` 会加载：

```text
taskX/subtaskY/build_so/libsubtask.so
```

然后查找符号：

```cpp
dlsym(handle, "generateGraph")
```

它要求每个 subtask 的动态库暴露这个函数：

```cpp
extern "C" void generateGraph(
    string task_name,
    string subTask_name,
    vector<GRAPH_NODE>& m_nodes,
    Inst_Block_Collect& inst_block_collect,
    uint64_t graph_height,
    uint64_t graph_width);
```

调用时传入：

- 当前 task 名称。
- 当前 subtask 名称。
- `m_nodes`：由插件填充的图节点数组。
- `m_Inst_Block_Collect`：前一步从 CSV 读出来的指令块集合。
- `graph_height` / `graph_width`：app 配置里写入的图尺寸。

调用完成后还会生成 dot 文件：

```text
taskX/subtaskY/template/subtaskY.dot
```

### 3. 统计 root block

`SubTask::count_root_block_amount` 遍历 `m_nodes`，统计没有 parent 的节点数：

```cpp
if (m_nodes[i].m_parent_nodes.size() == 0) {
    root_block_amount++;
}
```

这个数后面会被写进 subtask 配置，runtime/RTL 侧可以据此知道一个 subtask 图里有多少个初始可执行 block。

## generateGraph 到底做什么

以 `task0/subtask2/build_so/test_graph_extend.cpp` 为例，`generateGraph` 会：

1. 从 `inst_block_collect.inst_blocks` 取出 CSV 生成的 `Inst_Block`。
2. 为每个关键动作创建 `GRAPH_NODE`，例如 load A、copy A、load B、compute。
3. 设置每个 node 对应的 `Inst_Block`。
4. 通过 `Graph_Extend::set_relationship_node` 添加 parent/child 依赖。
5. 把节点 push 到 `m_nodes`。

所以 `generateGraph` 是“指令块集合 -> 图拓扑”的插件化编译阶段。不同 subtask 可以各自定义图结构，但最终都输出同一种 `vector<GRAPH_NODE>`。

`GRAPH_NODE` 当前主要承载：

- node 名称和 index。
- parent/child 依赖边。
- graph depth。
- 绑定的 `Inst_Block*`。
- 映射后的位置 `m_pos`，包括 PE index、x/y、graph_idx。
- 可能还有固定 PE 位置字段，例如 `m_pos_idx_df`。

## 图映射

图生成之后，`Task_Group::map` 进入映射阶段：

```text
Task_Group::map(INST_BLK_MAP*)
  -> start_map_app()
  -> for each task:
       start_map_task()
       for each subtask:
         map_subtask(subtask.m_nodes, false, subtask.subTask_name)
       end_map_task()
  -> end_map_app()
```

`INST_BLK_MAP::map_subtask` 目前能读出的核心逻辑是：

```text
sortByDepth(nodes, sort_nodes, true)
map(nodes, sort_nodes)
m_subtasks_name.push_back(subtask_name)
m_graph_idx++
```

也就是先按依赖深度排序，再调用 `map` 把节点放到 PE 上。

`pushNodes` 会设置节点位置：

```text
node->m_pos.pe_idx = pe_idx
node->m_pos.x = pe_idx / PE_ARRAY_Y_LEN
node->m_pos.y = pe_idx % PE_ARRAY_Y_LEN
node->m_pos.graph_idx = graph_idx
pes[pe_idx].m_pGraph_nodes.push_back(node)
```

`map` 里还会尊重已有 PE 放置约束：

- 默认按 `topology_pos_cnt % PE_AMOUNT` 分配。
- 如果 `get_pe_idx(...)` 能找到已有位置，会复用。
- 如果 node 的 `m_pos_idx_df` 不是默认值，会使用这个固定 PE 位置。

这说明 `generateGraph` 输出的不只是拓扑，还可能通过 node 字段影响 placement。映射阶段再把这种图级结构落到 PE/exeBlock/resource 结构上。

## 任务/子任务打印

映射完成后，`Print_Task_Group` 负责把结果序列化。

从 `task_print.cpp` 当前残留逻辑可以读出：

- `print_task` 遍历 task 内部的 subtask。
- 对每个 subtask 调 `print_subtask`，把 PE/exeBlock 相关信息写入配置。
- `instances_amount` 来自 `SubTask::instance_times`。
- `root_block_amount` 来自前面的 `count_root_block_amount`。
- 第一个 subtask 标记 `is_exe_start = true`。
- 最后一个 subtask 标记 `is_exe_end = true`。
- 中间用 `suc_subtasks[0]` 串成顺序链。

也就是说，task 内部的 subtask 是顺序关系；subtask 内部的 `GRAPH_NODE` 才是图依赖关系。

`print_task_group` 对 task 也做类似串联：

- 第一个 task 标记 `is_exe_start`。
- 最后一个 task 标记 `is_exe_end`。
- 多 task 时用 `suc_tasks[0]` 串起来。

但 `print_for_micc_rtl` 里有一句注释很关键：

```cpp
// every task_group has only one task
```

结合 `app0.conf` 到 `app3.conf`，当前 GEMM 模板更像是每个 app/task_group 只有一个 task；多个 `task0..task3` 作为不同 task group/task slot 被 build_app 一起处理。

## 当前理解的层级关系

比较清晰的层级可以写成：

```text
Application/build_app invocation
  -> Task_Group, usually one appN.conf
      -> Task, e.g. task0
          -> SubTask, e.g. subtask1/subtask2/subtask3
              -> GRAPH_NODE dependency graph
                  -> Inst_Block from template/*.csv
                      -> concrete instruction/exe block data
```

和我们之前的架构猜测可以对上：

- task 之间更像并行 slot / 分片关系。
- subtask 是 task 内的顺序阶段。
- subtask 内部才有图依赖，可以并行调度到不同 PE。
- PE/exeBlock/resource 的具体落点由 `INST_BLK_MAP` 决定。

## 对 runtime/driver 问题的影响

这条链路目前看到的是离线编译和配置生成，不是 Linux driver 本身。它最终生成的 `cbuf/micc/spm` 之类 bin 文件，才像是 runtime/driver 或仿真器会消费的控制面输入。

如果甲方说 runtime 和 driver 在 DFU 代码中、由 DMA 驱动体现，那么更可能的关系是：

- 这里的 build_app 负责生成 DFU 可执行的任务/指令/配置 payload。
- DFU runtime/driver 负责把这些 payload 通过 DMA 或寄存器接口下发。
- 当前 testcase 侧主要验证的是 payload 生成、simulator/RTL 消费路径，而不是完整 Linux driver 抽象。

换句话说，我们要继续追“算子怎么编译”，应优先沿着：

```text
CSV generator -> app*.conf -> task_create -> generateGraph -> inst_blk_map -> task_print -> bin outputs
```

而不是一上来做 torch abstraction。

## common_oper OCR 恢复状态

2026-05-31 这一轮已经把 `testcase/common_oper` 里主要 OCR 损坏的源码恢复到“可以重新编译公共构建库”的状态。恢复范围覆盖：

- CSV/指令模板读取：`csv_oper.*`、`csv2bin.*`
- 图结构与 dot 输出：`graph_gen.*`、`graph_extend.*`、`dot_gen.*`
- task/subtask 构建：`task_create.*`
- inst block、PE/exeBlock 映射：`inst_blk_gen.*`、`inst_map_common.*`、`inst_blk_map.*`、`map/inst_blk_map_*`
- task/bin 序列化：`task_print.*`、`write_file.*`
- 公共 build glue：`common_app_build.*`、`Makefile`、`run.sh`
- checkpoint 打印辅助：`checkpoint.h`、`checkpoint_print/*`

验证结果：

```text
cd testcase/common_oper
make clean && make -j2
  -> 通过，生成 libapp_build_common.so

cd testcase/application/build_app
make clean && make -j2
  -> 通过，生成 build_app
```

另外，`map/inst_blk_map_array.cpp` 和 `map/inst_blk_map_random.cpp` 作为 map 变体也已单独用 `g++ -c` 编译通过。它们通过 `INST_BLK_MAP_EXTERNAL_MAP_IMPL` 包含主实现并替换 `INST_BLK_MAP::map(...)`，和主 `inst_blk_map.cpp` 的宏保护是对得上的。

目前仍要谨慎看待的是行为等价性：部分复杂寄存器冲突、链式 copy/reduce、operand reuse 逻辑是按可编译和现有接口做了保守恢复；如果要确认原始性能/调度行为，需要在甲方原 Linux 环境或可执行 subtask `.so` 的环境里跑完整 case 输出对比。

本机平台差异也要注意：

- 新恢复的 `testcase/application/build_app/build_app` 是本机 macOS/arm64 可执行文件。
- `CASE/gemm_template_fusion/build_app` 是原始 Linux x86-64 ELF。

所以直接在 macOS 下执行 case 目录里的旧 `build_app` 会报 `exec format error`。即使换成本机新编出来的 `build_app`，case 内各个 subtask 的 `build_so/libsubtask.so` 也很可能仍是 Linux ELF，完整运行仍需要 Linux 环境验证。

## 待继续确认

1. 需要在 Linux/原始运行环境里跑完整 `gemm_template_fusion`，确认恢复后的公共库是否能加载各个 subtask 的 `build_so/libsubtask.so`。
2. 需要对比恢复前原始二进制输出和恢复后源码输出的 `cbuf/micc` bin，确认行为级等价。
3. `INST_BLK_MAP::map` 中 operand reuse、copy instruction 修正、寄存器链冲突处理仍值得精读；当前恢复以主调用链可编译、可读为优先。
4. 下一步如果继续研究“实际指令如何指定 device/功能单元”，应从 `csv_oper` 解析出的 `Inst` 字段、`inst_def.h` 的 unit/opcode 定义、`exe_block_gen` 的 block 划分继续往下追。

## 临时技术判断

目前最重要的判断是：`generateGraph` 不是普通 helper，而是每个 subtask 的“图生成插件 ABI”。CSV 决定单个指令块内容，`generateGraph` 决定这些指令块之间的依赖拓扑，`INST_BLK_MAP` 决定拓扑怎么落到 PE/exeBlock，`task_print` 决定怎么序列化成硬件/仿真器可读的配置。

这就是当前算子编译链的主干。
