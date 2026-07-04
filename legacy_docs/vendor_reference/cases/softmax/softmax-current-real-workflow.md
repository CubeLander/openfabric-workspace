# softmax_1 当前真实工作流

日期：2026-05-31

这篇笔记只记录当前可运行路径。结论先放前面：

```text
预置 conf/testarm/template
  -> softmax_1/run.sh
  -> csv_generate/run.sh
  -> 生成 app.conf / instance config / tempfile.h
  -> gpdpu_TestOp/app_build 生成 per-PE CSV
  -> build_so 生成 libsubtask.so
  -> spm_data 生成输入/SPM 数据
  -> riscv/make 编译 RISC-V 控制程序
  -> 外层 build_app/run_mtr.sh 打包 cbuf/micc
  -> run_app_riscv.sh 把 result/riscv/input 交给仿真器
```

`riscv_main.cpp`、`elementwise_template.cpp`、`exec.sh` 不在当前真实 softmax 路径里。`execute_elementwise(...)` 没有可见调用点，当前应视为死代码、历史残留或旁路生成器线索。

## 0. 预置 case contract

当前可运行 flow 从这些文件开始：

```text
csv_generate/conf.h
csv_generate/conf_PEmap.h
riscv/testarm.c
gpdpu_TestOp/task*/subtask*/template/*.cpp
gpdpu_TestOp/task*/subtask*/build_so/test_graph_extend.cpp
spm_data/data_generate.c
spm_data/result_check.c
```

这些文件不是 `softmax_1/run.sh` 生成的。现在最稳妥的理解是：它们是手写或预生成的 case contract。

其中 `conf.h` 提供：

```text
softmax0_input0_SIZE = 32768
softmax0_output0_SIZE = 32768
softmax_batch = 64
LARGE_SCALE = 0
SUBTASK_NUM = 2
TASK_NUM = 4
PER_TASK_PE_NUMBER = {16,16,16,16}
PER_TASK_INSTANCE_NUMBER = {1,1,1,1}
PER_INSTANCE_STATEMENT_NUMBER = {64}
SPM / DDR 地址和 DMA 分片数组
```

`conf_PEmap.h` 提供：

```text
Secondary_Fusion_Array
name2arraysize
pe_task_unrollid_start2end
mark_op = "SOFTMAX"
min_unit = 512
real_unit = 512
case_name = "softmax"
```

所以 softmax 当前 case 的 shape 可以从产物反推为 batch 64、last dim 512，即等价于 `{64, 512}`，但这个 shape 不是从当前可见前端源码重新生成出来的。

## 0.1 softmax 输入 shape 和 PE 切分

当前 softmax 的输入/输出尺寸相同：

```text
softmax0_input0  = 64 x 512
softmax0_output0 = 64 x 512
```

依据是：

```text
softmax0_input0_SIZE  = 32768
softmax0_output0_SIZE = 32768
softmax_batch         = 64
min_unit              = 512
real_unit             = 512
```

也就是：

```text
32768 elements = 64 rows * 512 elements/row
```

softmax 沿最后一维做，因此语义是：

```text
对 64 行中的每一行，取这一行的 512 个元素做一次 softmax。
输入 shape  = 64 x 512
输出 shape  = 64 x 512
```

当前任务切分非常整齐：

```text
TASK_NUM = 4
PER_TASK_PE_NUMBER = {16,16,16,16}
pe_task_unrollid_start2end[pe][task] = {0,0}
```

所以可以理解成：

```text
总共 64 行
  = 4 个 task
  = 每个 task 处理 16 行
  = 每个 task 使用 16 个 PE
  = 每个 PE 处理 1 行
```

行到 task/PE 的映射为：

```text
task0: row 0  ~ row 15  -> PE0 ~ PE15
task1: row 16 ~ row 31  -> PE0 ~ PE15
task2: row 32 ~ row 47  -> PE0 ~ PE15
task3: row 48 ~ row 63  -> PE0 ~ PE15
```

每个 PE 内部处理一整行，也就是 512 个 FP16 元素。CSV 中每个 PE 会对这一行发两条 `HLDT`：

```text
offset base + 0
offset base + 128
```

这里 CSV 的 offset 以 32-bit word 为单位，而数据是 FP16，所以：

```text
512 FP16 elements = 512 * 16 / 32 = 256 offset units
两条 HLDT 各覆盖 128 offset units = 256 FP16 elements
```

实际 CSV 地址也能对上：

```text
task0 PE0  first HLDT offset = 0      -> row 0
task0 PE15 first HLDT offset = 3840   -> row 15
task1 PE0  first HLDT offset = 4096   -> row 16
task2 PE0  first HLDT offset = 8192   -> row 32
task3 PE0  first HLDT offset = 12288  -> row 48
```

其中每行跨度是：

```text
512 FP16 elements = 256 offset units
```

所以 row 16 的起始 offset 是：

```text
16 * 256 = 4096
```

一句话总结：

```text
当前 softmax 是每个 PE 做一行 512 元素 softmax，
每个 task 做 16 行，
4 个 task 做完 64 行。
```

## 1. case 本地入口

`CASE/softmax_1/run.sh` 内容很短：

```sh
./clean.sh

cd csv_generate/
./run.sh
cd -

cd riscv/
make
cd -
```

注意：末尾调用外层 `build_app/run_mtr.sh` 的代码是注释掉的。因此单独跑 `softmax_1/run.sh` 只完成 case 内部材料生成和 RISC-V 程序编译，不完成最终 `result/cbuf_file.bin`、`result/micc_file.bin` 打包。

## 2. csv_generate/run.sh

`csv_generate/run.sh` 当前写死：

```sh
task_num=4
subtask_num=2
```

它的真实流程是：

```text
g++ test_app_conf_generate.c ../../../common_oper/write_file.cpp -o app_build ...
./app_build

cat instance_conf_info_file0..3.bin -> instance_conf_info_file.bin
cat instance_conf_info_for_rtl_file0..3.bin -> cbufData_instance.bin
mv instance_conf_info_file.bin ../simulator_bin/
mv cbufData_instance.bin ../rtl_bin/

cd ../gpdpu_TestOp
./run.sh

for task0..3:
  for subtask1..2:
    cd task<i>/subtask<j>/build_so
    ./run.sh

copy gpdpu_TestOp/task<i> -> outer task<i>

cd spm_data
./run.sh
```

这里的 subtask 循环只跑 `subtask1` 和 `subtask2`。虽然目录里存在 `subtask3/subtask4`，但当前 `LARGE_SCALE=0` 且 `subtask_num=2`，所以它们不参与当前 softmax。

## 3. test_app_conf_generate.c

`test_app_conf_generate.c` 读取：

```c
#include "conf.h"
#include "conf_PEmap.h"
```

它生成：

```text
app0.conf
app1.conf
app2.conf
app3.conf
instance_conf_info_file0.bin ... instance_conf_info_file3.bin
instance_conf_info_for_rtl_file0.bin ... instance_conf_info_for_rtl_file3.bin
csv_generate/tempfile.h
```

`app*.conf` 描述 task/subtask 壳：

```text
taskN
  subtask1
    Instance Times : 1
    code_path : template/
    csv_amount : 16
    graph height : 4
    graph width : 4
  subtask2
    Instance Times : 1
    code_path : template/
    csv_amount : 16
    graph height : 4
    graph width : 4
```

`tempfile.h` 记录数组名到 base slot 的映射。当前 softmax 为：

```text
SUM -> 0
softmax0_input0 -> 1
softmax0_output0 -> 2
```

`instance_conf_info_file*.bin` 则记录每个 task/subtask/instance 的 base address。对当前 non-large-scale softmax，它按照 `PER_INSTANCE_STATEMENT_NUMBER[k]`、`min_unit` 和 `256` 推进 `SUM/input/output` 的 base 地址。

## 4. gpdpu_TestOp/app_build 生成 CSV

`gpdpu_TestOp/run.sh`：

```sh
make clean
rm task*/subtask*/template/*.csv
make -j
./app_build
```

`gpdpu_TestOp/Makefile` 会把这些源码编进 `app_build`：

```text
task_main.cpp
task*/subtask*/template/*.cpp
```

`task_main.cpp` 从 `conf_PEmap.h::case_name` 选择算子。当前：

```cpp
case_name == "softmax"
```

于是它构造：

```cpp
op softmax;
softmax.op_owner = "softmax";
softmax.op_type = OpType::SOFTMAX;
softmax.allInput = {"softmax0_input0"};
softmax.allOutput = {"softmax0_output0"};
```

然后调用：

```text
do_task0_subtask1(all_ops)
do_task1_subtask1(all_ops)
do_task2_subtask1(all_ops)
do_task3_subtask1(all_ops)

do_task0_subtask2(all_ops)
do_task1_subtask2(all_ops)
do_task2_subtask2(all_ops)
do_task3_subtask2(all_ops)
```

因为 `LARGE_SCALE=0`，不会调用 subtask3/subtask4。

这些 `do_taskX_subtaskY` 函数读取 `conf.h/conf_PEmap.h/tempfile.h`，根据 PE map 和 `OpType::SOFTMAX` 生成：

```text
gpdpu_TestOp/task0/subtask1/template/0.csv ... 15.csv
gpdpu_TestOp/task0/subtask2/template/0.csv ... 15.csv
...
gpdpu_TestOp/task3/subtask2/template/0.csv ... 15.csv
```

CSV 就是 PE 侧 microprogram。典型指令包括：

```text
HLDT / ILDMT
H2FP
FMUL
FMIN
FEXP2
FADD
FDIV
SHFL
FP2H
HSTT
```

当前 softmax 大致分两段：

```text
subtask1: 读取输入，计算 exp / partial sum，写 SUM 或中间值
subtask2: 读取 SUM 和中间值，做 div / pack / store 输出
```

## 5. build_so 生成 libsubtask.so

`csv_generate/run.sh` 会进入：

```text
task0/subtask1/build_so
task0/subtask2/build_so
...
task3/subtask2/build_so
```

每个目录执行 `./run.sh`，本质是：

```sh
make clean
make -j
```

`build_so/test_graph_extend.cpp` 暴露：

```cpp
extern "C" void generateGraph(...)
```

`generateGraph(...)` 把对应 subtask 的 CSV stream 包装成 `GRAPH_NODE`，并指定 graph node 的 PE 位置。这里生成的是 host-side 编译插件 `libsubtask.so`，不是最终 device 指令本体。

### build_so 为什么每个 subtask 都有一份

`build_app` 的接口设计是：每个 subtask 目录下都应该有：

```text
template/<pe_id>.csv
build_so/libsubtask.so
```

其中：

```text
template/*.csv
  -> 每个 PE 的指令 block

build_so/libsubtask.so
  -> 这个 subtask 的 graph 生成插件
  -> 暴露 extern "C" generateGraph(...)
```

`build_app` 在 `task_create.cpp` 里会做两件事：

```text
read_inst_block_collect(...)
  -> 读取 code_dir/template/0.csv ... 15.csv
  -> 把 CSV 解析成 Inst_Block

subtask_graph_extend(...)
  -> dlopen code_dir/build_so/libsubtask.so
  -> dlsym generateGraph
  -> generateGraph(task_name, subTask_name, nodes, inst_block_collect, ...)
```

所以 `build_so` 不是把 CSV 翻译成二进制的地方。真正把 CSV/graph 打包成二进制的是后面的 `build_app`。`build_so` 只是提供一个 hook，告诉 `build_app`：

```text
这个 subtask 有多少个 graph node；
每个 node 对应哪个 CSV/Inst_Block；
每个 node 放在哪个 PE 位置；
node 之间有没有依赖关系。
```

当前 softmax 的 `test_graph_extend.cpp` 非常简单。每个 subtask 基本都是：

```cpp
m_nodes.resize(graph_height * graph_width);
for each node:
  m_node_name = "node<i>";
  m_pos_idx_df = i * graph_width + j;
  initNode(m_nodes[index], index, true, inst_block_collect);
```

也就是说，一个 graph node 基本对应一个 PE 的 CSV block，没有复杂 graph edge。对比所有 `task*/subtask*/build_so/test_graph_extend.cpp` 后，差异几乎只有：

```text
task0 使用 PER_TASK_PE_NUMBER[0]
task1 使用 PER_TASK_PE_NUMBER[1]
task2 使用 PER_TASK_PE_NUMBER[2]
task3 使用 PER_TASK_PE_NUMBER[3]

subtask1 使用 PER_TASK_PE_NUMBER[task] * PE_NUM_BASE
subtask2/3/4 使用 PER_TASK_PE_NUMBER[task]
```

把 task 下标和 `* PE_NUM_BASE` 归一化之后，当前 softmax 所有 `test_graph_extend.cpp` 内容相同。

所以这里“每个 subtask 都有 build_so”更多是工具链统一结构，而不是因为每个 subtask 都需要完全不同的 graph 程序。复杂算子/复杂 graph 中，`generateGraph(...)` 可以真的不同，例如添加 node 依赖、copy 边、特殊 PE 布局等；但当前 softmax 只是最简单的一 node 一 CSV block 模式。

### node 依赖的作用域

正常工具链里，node-to-node 依赖是 subtask 内部的。

原因是 `build_app` 加载 `libsubtask.so` 时调用的接口是：

```cpp
generateGraph(task_name,
              subTask_name,
              m_nodes,
              m_Inst_Block_Collect,
              graph_height,
              graph_width);
```

这里传进去的 `m_nodes` 是当前 subtask 的 node 列表。也就是说，一个 `taskX/subtaskY/build_so/libsubtask.so` 只能自然地给这个 subtask 内部的 nodes 建边。

如果 `generateGraph(...)` 调用：

```cpp
m_graph_extend.set_relationship_node(parent_node, child_node, type);
```

那么这个 parent/child 会进入：

```text
GRAPH_NODE::m_child_nodes
GRAPH_NODE::m_parent_nodes
```

随后 `exe_block_gen(...)` 会把它们转成 exe block 的：

```text
predecessors
successors
req_activations
```

这就是设备侧 block 级 activation/synchronization 的来源。

跨 subtask / 跨 task 的顺序不是通过 node edge 表达，而是由 task/subtask 配置表达。`task_print.cpp` 会给 subtask/task 配置写：

```text
suc_subtasks
suc_tasks
is_exe_start
is_exe_end
```

所以可以把调度层级理解成：

```text
task/subtask config:
  负责宏观顺序，例如 subtask1 -> subtask2

GRAPH_NODE edge:
  负责一个 subtask 内部 block/node 之间的依赖

Inst_Block 内部:
  负责单个 PE 指令序列内部的顺序执行
```

当前 softmax 中，`test_graph_extend.cpp` 没有调用 `set_relationship_node(...)`，所以 subtask 内部 16 个 PE node 之间没有显式 graph edge。`subtask1` 到 `subtask2` 的关系由 subtask 顺序表达；每个 PE 内部的中间结果则靠同 PE 指令顺序、寄存器/operand 状态，以及 `SUM` 的 SPM/中间区读写衔接。

## 6. spm_data 生成输入和 RTL SPM 数据

`spm_data/run.sh` 做：

```sh
./clean.sh
g++ data_generate.c -o data ...
./data

cp ../input_data.bin ./
cp ../../template/input_data_convert.c .
g++ input_data_convert.c ../../../common_oper/write_file.cpp -o data_convert ...
./data_convert

cp spm* ../rtl_bin/
```

所以它负责：

```text
input_data.bin
spmData.bin
spmResult.bin
其他 spm* RTL 辅助文件
```

`result_check.c` 是检查用 scaffolding，不是 device 指令生成核心。

## 7. riscv/make 编译 CPU 控制程序

`riscv/makefile` 编译：

```text
riscv/testarm.c
dpuapi/DpuAPI.c
```

命令形态：

```text
riscv64-unknown-elf-gcc -mabi=lp64d -march=rv64gcv -static \
  -o riscv testarm.c ../../../../dpuapi/DpuAPI.c ...

riscv64-unknown-elf-objdump -D riscv > riscv.lst
```

`testarm.c` 是 RISC-V/CPU 侧控制程序。它负责：

```text
DPU_CbufTransfer(...)
DPU_MiccTransfer(...)
DMA_Transfer_inoutArray(...)
DPU_Kernel_Start(...)
DPU_Wait(...)
DPU_App_Finish(...)
```

也就是说，`testarm.c` 消费 `conf.h` 里的 DMA 分片数组和地址配置，负责控制 DMA、装载 cbuf/micc、启动 kernel。它不生成 PE/device 指令。

## 8. 外层 build_app/run_mtr.sh 打包 cbuf/micc

`softmax_1/run.sh` 本身没有完成最终打包。外层 `test/run_app_riscv.sh` 会继续：

```text
cd testcase/application/build_app
./run_mtr.sh ${app_name} ${Duplicate_Application_Amount} ${app_num}
```

`build_app/run_mtr.sh` 会：

```text
copy build_app/main.cpp + Makefile -> CASE/<app_name>/
make build_app
./build_app app0.conf app1.conf ...
```

`build_app` 读取：

```text
app*.conf
task*/subtask*/build_so/libsubtask.so
task*/subtask*/template/*.csv
```

然后生成 simulator/RTL 中间二进制：

```text
simulator_bin/insts_file.bin
simulator_bin/exeblock_conf_info_file.bin
simulator_bin/tasks_conf_info_file.bin
simulator_bin/subtasks_conf_info_file.bin
simulator_bin/data_inst_replace.bin

rtl_bin/cbufData_inst.bin
rtl_bin/cbufData_exeblock.bin
rtl_bin/miccData_task.bin
rtl_bin/miccData_subtask.bin
...
```

随后 `run_mtr.sh` 拼接：

```text
insts_file.bin
exeblock_conf_info_file.bin
instance_conf_info_file.bin
  -> simulator_bin_multi_app/cbuf_file.bin

tasks_conf_info_file.bin
subtasks_conf_info_file.bin
  -> simulator_bin_multi_app/micc_file.bin
```

最后复制到：

```text
result/cbuf_file.bin
result/micc_file.bin
result/data_inst_replace.bin
```

这两个文件才是后续 `DPU_CbufTransfer` / `DPU_MiccTransfer` 装载的主要 device 配置和指令包。

## 9. run_app_riscv.sh 交给仿真器

外层 `test/run_app_riscv.sh` 的关键阶段是：

```text
cd testcase/application/${app_name}
./run.sh

cd testcase/application/build_app
./run_mtr.sh ${app_name} ${Duplicate_Application_Amount} ${app_num}

cp testcase/application/${app_name}/result ./config -r
cp testcase/application/${app_name}/riscv/riscv ./config/riscv_program
cp testcase/application/${app_name}/input_data_m.bin ./config/input_data.bin
```

然后仿真器启动时消费：

```text
config/result/cbuf_file.bin
config/result/micc_file.bin
config/result/data_inst_replace.bin
config/riscv_program
config/input_data.bin
```

RISC-V 程序通过 DPU API 写寄存器/触发 DMA；仿真器或 runtime 负责把这些文件对应到设备侧内存。

## 10. 明确排除项

当前不要再把这条链当成事实：

```text
op + shape
  -> execute_elementwise(...)
  -> elementwise_split(...)
  -> 自动生成 conf.h/conf_PEmap.h/testarm.c
```

原因：

```text
softmax_1/run.sh 不调用 exec.sh
csv_generate/run.sh 不调用 riscv_main.cpp / elementwise_template.cpp
riscv/makefile 只编译 testarm.c + DpuAPI.c
全仓未找到 execute_elementwise(...) 调用点
直接 g++ riscv_main.cpp elementwise_template.cpp 会因为缺 main 链接失败
```

所以当前最稳妥的工程模型是：

```text
conf.h / conf_PEmap.h 是 softmax case 的最高层实际输入。
gpdpu_TestOp/template/*.cpp 是 softmax 算子 lowering 的主要源码。
CSV 是 PE microprogram。
build_so/libsubtask.so 是 host-side graph 扩展插件。
build_app 是 assembler/packer。
riscv/testarm.c 是 CPU 控制程序。
cbuf_file.bin / micc_file.bin 是最终给 device/仿真器装载的配置和指令包。
```
