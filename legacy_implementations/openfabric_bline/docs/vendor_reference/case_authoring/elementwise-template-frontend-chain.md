# Elementwise Template 前端生成链路笔记

日期：2026-05-31

这条笔记继续往 `build_app` 上游追，覆盖 `softmax_1` 的 case 生成链路。需要先修正一个判断：`softmax_1/run.sh` 实际不调用 `riscv_main.cpp`，当前目录里的 `execute_elementwise(...)` 基本可以视为未接入/死代码。

现在实际 `run.sh` 流程可以拆成两级：

```text
run.sh
  -> clean.sh
  -> csv_generate/run.sh
       -> 消费现成 csv_generate/conf.h
       -> 消费现成 csv_generate/conf_PEmap.h
       -> 生成 app*.conf
       -> 生成 instance_conf_info_file*.bin
       -> 生成 csv_generate/tempfile.h
       -> gpdpu_TestOp/run.sh
       -> task*/subtask*/build_so/run.sh
       -> spm_data/run.sh
  -> test_app_conf_generate.c
  -> gpdpu_TestOp/app_build 生成 task*/subtask*/template/<pe_id>.csv
```

## run.sh

`CASE/softmax_1/run.sh` 内容是：

```text
./clean.sh

cd csv_generate/
./run.sh
cd -

cd riscv/
make
cd -
```

因此实际被调用的是：

1. `csv_generate/run.sh`
2. `riscv/makefile`

`riscv/makefile` 只编译 `riscv/testarm.c` 和 `dpuapi/DpuAPI.c`：

```text
Source = testarm.c
API_SOURCE = ../../../../dpuapi/DpuAPI.c
riscv64-unknown-elf-gcc ... testarm.c DpuAPI.c ...
```

它不会编译 `riscv_main.cpp`。

## exec.sh / execute_elementwise 当前状态

`CASE/softmax_1/exec.sh` 内容虽然是：

```text
g++ riscv_main.cpp elementwise_template.cpp
./a.out
rm -rf a.out
```

但当前源码中 `riscv_main.cpp` 只有 `execute_elementwise(...)`，没有真正的 `main()`。直接编译会因为缺 `main` 链接失败：

```text
Undefined symbols for architecture arm64:
  "_main"
```

全仓搜索也只看到 `execute_elementwise(...)` 的定义，没有调用点。所以在当前 softmax_1 路径里，`riscv_main.cpp` 和 `elementwise_template.cpp` 不是实际运行链路的一部分，更像是未爬全、废弃、或从别的 case 拷过来的前端生成器残留。

## riscv_main.cpp 做什么

`execute_elementwise(vector<op> &all_ops, string case_name)` 如果被接入，理论上会：

1. 收集所有输入/输出 tensor 名称和 shape。
2. 判断算子类型。
3. 估算每个 scalar/vector statement 需要的指令数和寄存器数。
4. 调用 `elementwise_split(...)`。

对 `SOFTMAX`：

```text
mark_op = "SOFTMAX"
min_unit = ceil(last_dim / 256) * 256
cal_register_num += (15 + min_unit / 256 * 2) * 4
cal_instructions_num += 35 + min_unit / 256 * 15
```

随后估算：

```text
ld_st_instructions_num
every_instructions_num = ld_st_instructions_num + cal_instructions_num
every_insts_register_num = ld_st_instructions_num + cal_register_num
```

这两个值会进入 `elementwise_split`，用来判断单 PE 是否资源超限。但对当前 `softmax_1/run.sh` 而言，这段逻辑不执行。

## elementwise_split 做什么

`elementwise_split(...)` 是这一层核心入口。它内部维护：

```text
inoutArray_ddrandspm_size       // 每个数组 DDR/SPM size
inoutArray_ddrandspm_addr       // 每个数组 DDR/SPM 起始地址
allarray_dmatrans_info          // 生成 testarm.c 的 DMA 传输描述
pe_task_unrollid_start2end      // peid, taskid -> unroll id range
instanceNum_per_task
peNum_per_task
statementNum_per_instance
```

关键资源阈值：

```text
if every_instructions_num > 4352 || every_insts_register_num > 1536:
  large_scale = 1
```

也就是说，这里显式使用了单 PE 的指令槽和寄存器槽上限：

- instruction slots: `4352`
- register/operand budget: `1536`

普通路径调用：

```text
get_pe_task_num(...)
```

large-scale softmax 路径调用：

```text
get_pe_task_num_large_scale(...)
```

最后输出：

```text
gen_confh(...)
get_all_array_dmatransinfo(...)
gen_confpemaph(...)
gen_testarm(...)
```

## get_pe_task_num：PE/task/instance 切分

`get_pe_task_num(...)` 先计算：

```text
all_statement_num_app = ceil(output_app_size / min_unit)
pe_num = min(16, all_statement_num_app)
max_statement_num_pe = ceil(all_statement_num_app / pe_num)
max_unrollNum_inst = 4352 / every_instructions_num
max_unrollNum_reg = 1536 / every_insts_register_num
max_unrollNum_per_pe = min(max_unrollNum_inst, max_unrollNum_reg)
```

之后分两种情况：

1. 如果 `max_statement_num_pe > max_unrollNum_per_pe`，说明单 PE 的一个 task 放不下，需要 instance 或更细 task 切分。
2. 如果不超限，则 task 数量最多取 4，或者取 `max_statement_num_pe`。

最终会产生：

- `task_num`
- `peNum_per_task`
- `instanceNum_per_task`
- `pe_task_unrollid_start2end`
- `statementNum_per_instance`

这些值会直接影响：

- `conf.h` 中 `TASK_NUM/PER_TASK_PE_NUMBER/PER_TASK_INSTANCE_NUMBER/task_order`
- `conf_PEmap.h` 中每个 PE、每个 task 负责的 unroll 范围
- `app*.conf` 中每个 subtask 的 instance times 和 csv_amount
- `gpdpu_TestOp` 生成每个 PE CSV 时的循环范围

## gen_confh

`gen_confh(...)` 写：

```text
../elementwise_template_fusion/csv_generate/conf.h
```

在当前 `softmax_1` 目录中，实际对应生成后的 `csv_generate/conf.h`。

它写入：

- 每个 tensor 的总大小：`*_SIZE`
- 每个 app 分片大小：`*_SIZE_app`
- DDR 地址：`MEM_*_ADDR`
- SPM 地址：`SPM_*_ADDR`
- `SPM_SUM_ADDR`
- `LARGE_SCALE`
- `APP_NUM`
- `SUBTASK_NUM`
- `TASK_NUM`
- `PE_NUM_BASE`
- `PE[]`
- `PER_TASK_PE_NUMBER[]`
- `PER_TASK_INSTANCE_NUMBER[]`
- `task_order[]`
- `PER_INSTANCE_STATEMENT_NUMBER[]`

同时它还会打开 `csv_generate/run.sh`，覆盖开头两行：

```text
task_num=<task_num>
subtask_num=<subtask_num>
```

这解释了 `csv_generate/run.sh` 为什么知道要遍历多少 `task*/subtask*`。

## gen_confpemaph

`gen_confpemaph(...)` 写：

```text
../elementwise_template_fusion/csv_generate/conf_PEmap.h
```

内容包括：

- `Secondary_Fusion_Array`：数组名到 DDR/SPM 地址。
- `name2arraysize`：数组名到大小。
- `pe_task_unrollid_start2end`：每个 PE 在每个 task 中处理哪些 unroll id。
- `mark_op`
- `min_unit`
- `real_unit`
- `case_name`

`gpdpu_TestOp/task_main.cpp` 后面就是靠 `case_name` 决定构造哪个 `op`，靠 `pe_task_unrollid_start2end` 决定每个 PE 生成哪些 CSV 指令。

## gen_testarm

`gen_testarm(...)` 写：

```text
../elementwise_template_fusion/riscv/testarm.c
```

它生成 CPU/RISC-V 侧控制程序。核心结构是：

```text
DPU_CbufTransfer(CBUF_DDR_ADDR)
DPU_MiccTransfer(MICC_DDR_ADDR)

for app_num in APP_NUM:
  DMA input mem -> spm
  wait previous kernel if needed
  DPU_Kernel_Start(inst_reload, TASK_NUM, ...)
  DMA previous output spm -> mem if needed

wait last kernel
DMA last output
DPU_App_Finish()
```

这里再次确认：`testarm.c` 不生成 device 指令，它消费 `conf.h` 里的 DMA 分片信息，负责搬输入/输出和启动 kernel。

## test_app_conf_generate.c

`csv_generate/run.sh` 编译并运行：

```text
test_app_conf_generate.c
```

它读取 `conf.h` 和 `conf_PEmap.h`，生成：

```text
../app0.conf
../app1.conf
...
instance_conf_info_file0.bin
instance_conf_info_file1.bin
...
instance_conf_info_for_rtl_file0.bin
...
tempfile.h
```

`app*.conf` 的关键字段来自：

```text
task_num = TASK_NUM
subtask_num = SUBTASK_NUM
subtask_instance_times[y] = PER_TASK_INSTANCE_NUMBER[x]
subtask_csv_amount[y] = PER_TASK_PE_NUMBER[x] * PE_NUM_BASE
graph height = 4
graph width = 4
```

也就是说，`app*.conf` 是从 `conf.h` 派生出来的 task/subtask 壳配置，不是手写输入。

`instance_conf_info_file*.bin` 则是每个 task/subtask/instance 的 base address 表。对 softmax，base addr 会随着 `PER_INSTANCE_STATEMENT_NUMBER[k]` 推进：

```text
SUM
softmax0_input0
softmax0_output0
```

`tempfile.h` 记录数组名到 base slot 的映射，例如：

```text
{"SUM", 0}, {"softmax0_input0", 1}, {"softmax0_output0", 2}
```

后续 `gpdpu_TestOp/task_main.h` include 这个文件，CSV 生成器就能把数组名映射成 load/store base index。

## 当前完整生成链

现在 softmax 的实际链路更准确地写成：

```text
现成 csv_generate/conf.h
现成 csv_generate/conf_PEmap.h
现成 riscv/testarm.c

run.sh
  -> csv_generate/test_app_conf_generate.c
  -> app*.conf
  -> instance_conf_info_file.bin
  -> tempfile.h

gpdpu_TestOp/app_build
  -> task_main.cpp: case_name -> op
  -> task*/subtask*/template/*.cpp: op + PE map -> CSV

build_so/libsubtask.so
  -> CSV block -> GRAPH_NODE

build_app
  -> GRAPH_NODE/Inst_Block -> insts/exeblock/task/subtask bins
  -> result/cbuf_file.bin, result/micc_file.bin
```

因此，当前能确认的是：`softmax_1` 的实际入口消费的是已经生成好的 `conf.h/conf_PEmap.h/testarm.c`，而不是从 op/shape 重新生成这些文件。

## softmax 最高层原始输入缺口

如果从“这些现成 `conf.h/conf_PEmap.h/testarm.c` 最初怎么来”这个问题继续往上追，`execute_elementwise(...)` 仍然像是一个可能的前端生成器设计残留；但当前它没有可运行入口。

当前本地这份 `riscv_main.cpp` 只定义了：

```cpp
void execute_elementwise(vector<op> &all_ops, string case_name)
```

`elementwise_template.cpp` 也只是模板生成/切分逻辑。它会把字符串形式的 `int main()` 写进生成后的 `riscv/testarm.c`，但它自己不是 host 侧入口。因此，真正构造 `all_ops`、填入 tensor shape、再调用 `execute_elementwise(...)` 的 host-side `main()`，在当前 OCR/爬取下来的源码中是缺失的；也可能根本没有被这个 `softmax_1/run.sh` 使用。

这里要区分两个层级：

1. `gpdpu_TestOp/task_main.cpp` 会根据 `case_name == "softmax"` 构造一个 `op softmax`，但只填：

```cpp
softmax.op_owner = "softmax";
softmax.op_type = OpType::SOFTMAX;
softmax.allInput = {"softmax0_input0"};
softmax.allOutput = {"softmax0_output0"};
```

它没有填 `input_name/output_name` 的 shape。这一层已经是在 `conf.h/conf_PEmap.h/tempfile.h` 存在之后，用来生成 PE CSV kernel 程序的。

2. `riscv_main.cpp::execute_elementwise(...)` 如果被接入，则要求传入的 `all_ops[i].input_name` 和 `all_ops[i].output_name` 已经带 shape。它依赖这些 shape 生成 `inoutArray_alldimsize`，再决定 `min_unit`、`TASK_NUM`、`SUBTASK_NUM`、PE map、DMA 描述和 `testarm.c`。

但当前更稳的判断是：对可运行的 `softmax_1/run.sh` 来说，最高层实际输入就是手写/预生成的 case contract：

```text
csv_generate/conf.h
csv_generate/conf_PEmap.h
riscv/testarm.c
gpdpu_TestOp/task*/subtask*/template/*.cpp
```

`execute_elementwise(...)` 代表的是一个可能存在过的生成器设计，而不是当前 softmax flow 的真实入口。下面这段只能作为“如果它曾经接入，理论上 driver 可能长这样”的历史线索，不能当成当前流程事实：

```cpp
int main() {
  vector<op> all_ops;
  op softmax;
  softmax.op_owner = "softmax";
  softmax.op_type = OpType::SOFTMAX;
  softmax.input_name["softmax0_input0"] = {64, 512};
  softmax.output_name["softmax0_output0"] = {64, 512};
  softmax.allInput = {"softmax0_input0"};
  softmax.allOutput = {"softmax0_output0"};
  all_ops.push_back(softmax);
  execute_elementwise(all_ops, "softmax");
}
```

这个 `{64, 512}` 是从生成产物反推的，不是当前源码里直接看到的。依据是 `csv_generate/conf.h`：

```c
#define softmax0_input0_SIZE 32768
#define softmax0_output0_SIZE 32768
#define softmax_batch 64
#define PER_INSTANCE_STATEMENT_NUMBER[1] = {64}
```

对 softmax 来说，`softmax_batch` 是最后一维之外的 batch 数，`min_unit/real_unit` 对应最后一维。当前产物等价于 batch 64、last dim 512，也就是最可能的原始 shape 为 `{64, 512}`。

## 一个重要判断

当前可运行路径里，`elementwise_template.cpp` 不执行。`test_app_conf_generate.c` 读取已经存在的 `conf.h/conf_PEmap.h`，再生成 `app*.conf` 和 instance 配置。

因此，如果后面要做一个更可靠的编译器抽象，比较自然的抽象边界不是从 `app*.conf` 开始，而是从：

```text
case contract / tensor shape / fusion graph
```

开始，经过：

```text
task/subtask/instance/PE map -> CSV IR -> bin pack
```

这才是当前工具链真实的前端到后端分层。
