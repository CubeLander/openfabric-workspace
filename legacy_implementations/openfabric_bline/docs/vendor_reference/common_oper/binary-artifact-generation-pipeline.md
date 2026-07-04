# DPU 测试产物生成链路笔记

日期：2026-05-31

这条笔记记录一个方向切换：不再优先从闭源 `runtime/module` 里追踪 `.bin` 如何被读入和消费，而是从我们关心的产物反向追踪它们是如何生成出来的。这样更适合当前源码不完整的情况，也更接近“算子如何编译成 device 侧执行材料”的问题。

## 当前结论

`result/cbuf_file.bin`、`result/micc_file.bin`、`result/data_inst_replace.bin` 不是运行时直接生成的，而是 `testcase/application/build_app/run_mtr.sh` 调用 case 本地的 `build_app` 后，把 `simulator_bin/` 下的中间文件按固定顺序拼接出来。

核心拼接关系：

```text
result/cbuf_file.bin
  = simulator_bin/insts_file.bin
  + simulator_bin/exeblock_conf_info_file.bin
  + simulator_bin/instance_conf_info_file.bin

result/micc_file.bin
  = simulator_bin/tasks_conf_info_file.bin
  + simulator_bin/subtasks_conf_info_file.bin

result/data_inst_replace.bin
  = simulator_bin/data_inst_replace.bin
```

RTL 侧有对应的文本/RTL 产物：

```text
rtl_bin/cbufData.bin
  = rtl_bin/cbufData_inst.bin
  + rtl_bin/cbufData_exeblock.bin
  + rtl_bin/cbufData_instance.bin

rtl_bin/miccData.bin
  = rtl_bin/miccData_task.bin
  + rtl_bin/miccData_subtask.bin
```

源码定位：

- `testcase/application/build_app/run_mtr.sh`：复制 `main.cpp/Makefile` 到 case 目录，构建并运行 `./build_app app*.conf`，随后拼接 `cbuf_file.bin/micc_file.bin`。
- `testcase/application/build_app/main.cpp`：`build_app` 入口，读取 `app*.conf`，构造 task graph，map 到 PE，生成 execute block，再调用 `Print_Task_Group` 输出各类二进制。
- `testcase/common_oper/task_print.cpp`：真正输出 instruction、exeblock、task、subtask 等二进制结构的位置。

## 生成侧总图

从一个 case，例如 `softmax_1`，大致可以分成四条生成线：

```text
手写/预生成 case contract
  -> csv_generate/conf.h
  -> csv_generate/conf_PEmap.h
  -> riscv/testarm.c
  -> gpdpu_TestOp/task*/subtask*/template/*.cpp

CASE/<op>/run.sh
  -> csv_generate/run.sh
       -> test_app_conf_generate.c
       -> simulator_bin/instance_conf_info_file.bin
       -> rtl_bin/cbufData_instance.bin
       -> gpdpu_TestOp/run.sh
       -> task*/subtask*/build_so/run.sh
       -> spm_data/run.sh

  -> riscv/makefile
       -> testarm.c + dpuapi/DpuAPI.c
       -> riscv
       -> riscv.lst

application/build_app/run_mtr.sh <op> <duplicate> <app_num>
  -> copy build_app/main.cpp + Makefile into CASE/<op>/
  -> make build_app
  -> ./build_app app0.conf app1.conf ...
       -> insts_file.bin
       -> exeblock_conf_info_file.bin
       -> tasks_conf_info_file.bin
       -> subtasks_conf_info_file.bin
       -> data_inst_replace.bin
  -> concatenate final result/*.bin
```

其中：

- 对当前 `softmax_1`，`conf.h`、`conf_PEmap.h`、`riscv/testarm.c` 和 `gpdpu_TestOp/task*/subtask*/template/*.cpp` 是可运行流程的输入。当前 `run.sh` 不生成它们；可以把它们视为手写/预生成 case contract。
- `riscv` 是 CPU/RISC-V 侧程序，由 `riscv/testarm.c` 和 `dpuapi/DpuAPI.c` 编译出来。
- `input_data.bin/output_data.bin` 由 `spm_data/data_generate.c` 生成。
- `instance_conf_info_file.bin` 由 `csv_generate/test_app_conf_generate.c` 生成，并由 `csv_generate/run.sh` 把 `instance_conf_info_file0..N.bin` 拼成总文件。
- `task*/subtask*/build_so/*.so` 是每个 subtask 的 kernel graph 扩展/编译程序，`csv_generate/run.sh` 会逐个进入 `task$i/subtask$j/build_so` 执行 `run.sh`。
- `insts_file.bin` 和 `exeblock_conf_info_file.bin` 由 `build_app` 通过 `Print_Task_Group` 生成。
- `tasks_conf_info_file.bin` 和 `subtasks_conf_info_file.bin` 由 `build_app` 根据 `Task_Group` 的 task/subtask 拓扑生成。

## build_app 内部链路

`main.cpp` 的主流程：

```text
for each app*.conf:
  Task_Group::readFromTaskFile(...)
  Task_Group::tasksConstruct()
  Task_Group::map(pInst_blk_map)

exe_block_gen(pInst_blk_map->m_pes)

for each Task_Group:
  Print_Task_Group::print_task_group(...)

Print_Task_Group::print_inst(...)
Print_Task_Group::fill_max_inst_per_pe()
Print_Task_Group::fill_task_simulator(...)
Print_Task_Group::task_inst_enable_print(...)
Print_Task_Group::print_for_micc_rtl(...)
```

含义：

- `readFromTaskFile` 读 `app*.conf`，得到应用级 task/subtask 描述。
- `tasksConstruct` 应该会沿着 task/subtask 的 `build_so` 或 graph extend 逻辑把算子 graph 构出来。
- `map` 把 graph node 映射到 PE。
- `exe_block_gen` 把 graph node/inst block 进一步组织成 execute block。
- `Print_Task_Group` 把内部结构序列化成 simulator/RTL 所需的二进制或文本材料。

## insts_file.bin 如何生成

`Print_Task_Group::print_inst(PE *pes)` 遍历所有 PE 的 graph node：

```text
for each PE:
  for each GRAPH_NODE in PE:
    if exe_block.valid:
      依次输出 ld/cal/flow/st stage 指令
      exeBlock_conf.inst_mem_based_addr = 当前 PE 内指令起始 byte offset
  写入 simulator_bin/tmpinsts_file.bin<pe_idx>
```

随后 `fill_max_inst_per_pe()`：

```text
for each PE:
  把 tmpinsts_file.bin<pe_idx> padding 到 MAX_INST_AMOUT_PER_PE

for each PE:
  依次把 tmpinsts_file.bin<pe_idx> 追加到 simulator_bin/insts_file.bin
```

所以 `insts_file.bin` 的布局基本是“按 PE 顺序排列，每个 PE 固定槽位数，每个槽位一个 `inst_t`”。

## exeblock_conf_info_file.bin 如何生成

`print_subtask()` 调 `print_block_conf()`。后者遍历所有 PE 里的 graph node，筛出当前 `task_name/subTask_name` 对应的 node：

```text
for each PE:
  for each GRAPH_NODE:
    if node.task_name == task_name && node.subTask_name == subTask_name:
      拷贝 Exe_Block::exeBlock_conf_info
      patch task_idx/subtask_idx/block_idx/instances_amount
      patch stage_start_pc，使 PC 对齐当前 PE 的累计 instruction count
      写 simulator_bin/blockexeblock_conf_info_file.bin<pe_idx>
```

随后 `fill_max_inst_per_pe()`：

```text
for each PE:
  把 blockexeblock_conf_info_file.bin<pe_idx> padding 到 MAX_INST_BLOCK_AMOUNT_PER_PE

for each PE:
  依次追加到 simulator_bin/exeblock_conf_info_file.bin
```

所以 exeblock 配置也是按 PE 固定槽位布局。

## tasks/subtasks conf 如何生成

`Print_Task_Group::print_task_group()` 为每个 `Task_Group` 生成：

- `task_conf_info_t`
- `sub_task_conf_info_t`

关键行为：

- task 之间被设置为顺序链：第一个 `is_exe_start=true`，前一个 task 的 `suc_tasks[0]` 指向下一个，最后一个 `is_exe_end=true`。
- subtask 之间也被设置为顺序链：第一个 `is_exe_start=true`，前一个 subtask 的 `suc_subtasks[0]` 指向下一个，最后一个 `is_exe_end=true`。
- subtask 会记录 `instances_conf_mem_based_addr`，指向 `instance_conf_info_file.bin` 中当前 subtask 的 instance 配置起始偏移。
- `fill_task_simulator()` 会把 task/subtask 配置 padding 到 `MAX_CUR_TASK_CONF_PER_APP` 和 `MAX_SUBTASK_PER_TASK` 对应的固定容量。

这和前面架构猜测吻合：task 之间在当前生成逻辑里主要体现为应用内任务链，subtask 在 task 内顺序执行；真正跨 PE 的并行性体现在 graph node / execute block 被 map 到多个 PE。

## data_inst_replace.bin

`Print_Task_Group::task_inst_enable_print()` 会写：

```text
rtl_bin/instEnable.bin
rtl_bin/taskEnable.bin
simulator_bin/data_inst_replace.bin
```

当前还原出来的 `data_inst_replace.bin` 是文本格式，类似：

```text
1 1
```

它更像 simulator 的控制/替换开关，而不是 device instruction 的主体。

## softmax_1 的 case 本地流程

`CASE/softmax_1/run.sh`：

```text
./clean.sh
cd csv_generate && ./run.sh
cd riscv && make
```

注意：这个脚本里的 `build_app/run_mtr.sh` 调用是注释掉的。因此，单独跑 `softmax_1/run.sh` 只生成 case 本地材料和 RISC-V 程序，不一定生成最终 `result/cbuf_file.bin/micc_file.bin`。最终打包通常要外层调用：

```text
testcase/application/build_app/run_mtr.sh <case_name> <duplicate> <app_num>
```

`csv_generate/run.sh` 做的事：

- 编译并运行 `test_app_conf_generate.c`，生成 instance 配置。
- 拼接 `instance_conf_info_file0..3.bin` 为 `instance_conf_info_file.bin`。
- 运行 `gpdpu_TestOp/run.sh` 生成/展开 task/subtask 代码。
- 遍历 `task0..task3`、`subtask1..subtask2`，逐个执行 `build_so/run.sh`。
- 把 `gpdpu_TestOp/task$i` 复制到 case 外层的 `task$i`。
- 进入 `spm_data/run.sh` 生成输入数据和 RTL SPM 数据。

`riscv/makefile` 做的事：

```text
riscv64-unknown-elf-gcc -mabi=lp64d -march=rv64gcv -static \
  -o riscv testarm.c ../../../../dpuapi/DpuAPI.c ...
riscv64-unknown-elf-objdump -D riscv > riscv.lst
```

所以 `riscv/testarm.c` 是 CPU 侧程序，`dpuapi/DpuAPI.c` 是 CPU 调 DPU/DMA API 的薄层，device 侧真正执行材料在 `result/*.bin` 和相关 simulator/RTL bin 里。

## 下一步建议

接下来应该沿着“产物生成者”逐个追，而不是再从闭源 runtime 消费路径硬钻：

1. 追 `app*.conf` 是谁写出来的，以及它如何表达 task/subtask。
2. 追 `Task_Group::readFromTaskFile -> tasksConstruct -> subtask_graph_extend/generateGraph`，确认每个 subtask 的 `.so` 如何参与 graph 生成。
3. 追 `inst_blk_gen/exe_block_gen`，确认 graph node 到 instruction block / execute block 的 lowering 规则。
4. 对 `inst_t` 结构和 `opCode` 枚举做一份字段解释表。
5. 对 `insts_file.bin`、`exeblock_conf_info_file.bin`、`tasks_conf_info_file.bin`、`subtasks_conf_info_file.bin` 写一个 decoder，直接从二进制反解析，和源码结构互相校验。

当前最值得优先做的是第 2 和第 5：前者解释“算子怎么变成 graph”，后者让我们不依赖闭源 runtime，也能直接验证最终 device 包的内容。
