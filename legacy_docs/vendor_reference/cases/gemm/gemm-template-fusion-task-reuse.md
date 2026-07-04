# GEMM Template Fusion Task Data Reuse

本文记录对甲方示例 `gemm_template_fusion` 中 `task0..task3` 并发执行和数据复用关系的
调查结论。

分析对象：

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/gemm_template_fusion
```

结论只针对这个 vendor case。这里的 `task0..task3` 是同一个 GEMM tile 计算里的
4 个并发 task，配置里 `TASK_NUM = 4`，`app0.conf..app3.conf` 的
`reuse_input_reg` / `reuse_output_reg` 字段实际为空。数据复用没有通过这些字段表达，
而是编码在 SPM 地址表、CSV 里的 load/store 地址，以及 subtask2 的 graph edge 中。

## 总体结论

`task0..task3` 并发无锁是因为它们之间没有互相生产消费的共享可写数据：

```text
A/input0:
  按 task 分片。
  task0/task1/task2/task3 使用不同 A 地址段。

B/input1:
  跨 task 复用。
  四个 task 从相同 B 地址读取，但 B 是只读输入。

C/output0:
  按 task 分区。
  四个 task 读写不同 C/output 地址段。
```

最终生成目录 `gpdpu_tensor` 中的 CSV 地址范围也符合这个模式：

```text
task0: A 0..15872     B 0..15584  C store 0..31968
task1: A 16384..32256 B 0..15584  C store 32768..64736
task2: A 32768..48640 B 0..15584  C store 65536..97504
task3: A 49152..65024 B 0..15584  C store 98304..130272
```

对应地址表在：

```text
csv_generate/conf_PEmap.h
  taskAddr_per_pe_A
  taskAddr_per_pe_B
  taskAddr_per_pe_C
```

其中 `taskAddr_per_pe_B` 对同一个 PE 给出的 task0/task1/task2/task3 地址相同；
`taskAddr_per_pe_A` 和 `taskAddr_per_pe_C` 则按 task 切成不同地址段。

## B 矩阵是谁读进来的

这里有两层“读”：

```text
DDR -> SPM:
  RISC-V 控制程序 dpuctrl.c 通过 DMA_Transfer_input() 把 GEMM_INPUT2 搬进 SPM。

SPM -> PE local register:
  每个 task 的 subtask2 CSV 用 HLDT 从相同 B SPM 地址读取到自己的
  gemm0_input1_<task_id>_* 符号 operand tag。
```

所以 B 不是由 `task0` 读进来后再交给 `task1..task3`。它先由 RISC-V 控制侧搬到
SPM，然后四个 task 各自从同一片 SPM B tile 中只读加载。

`dpuctrl.c` 的主循环顺序是：

```text
DMA GEMM_INPUT1
DMA GEMM_INPUT2
DMA GEMM_INPUT3 / C
wait previous kernel if needed
DPU_Kernel_Start(..., TASK_NUM, ...)
```

`DMA_Transfer_input()` 内部调用 `DPU_Transfer_Detailed()` 后会等待
`DPU_DMATransferFinish(channel_mask)`。因此，在 `DPU_Kernel_Start()` 之前，
当前 app 的 B tile 已经由 DMA 放入 SPM。四个 task 是 kernel 启动后才开始执行，
所以不存在 task 在 B 尚未 DMA 完成时提前读 B 的情况。

这条保证是 kernel 外部的装载顺序保证，不是 task0..task3 之间的锁。

## B 的 task 内使用顺序

在每个 task 的 `subtask2/template/new_temp.c` 中，生成顺序是：

```text
1. 生成 A 的 HLDT CSV。
2. 生成 A 的 COPYT CSV。
3. 生成 B 的 HLDT 到 calc CSV。
4. 在同一个 calc CSV 中追加 HMUL/RXINT/HMMAL/TRCTT。
```

以 task0 为例，`new_temp.c` 先写：

```text
HLDT ... gemm0_input1_0_* ... taskAddr_per_pe_B[pe_id][0] ...
```

随后同一批 calc CSV 才追加：

```text
HMMAL ... gemm0_input0_0_* , gemm0_input1_0_* ...
```

task1/task2/task3 同理，只是寄存器名里的 task id 变成
`gemm0_input1_1_*` / `gemm0_input1_2_*` / `gemm0_input1_3_*`。

因此，在 CSV / instruction tag 语义上，task0 的 HMMAL 只引用
`gemm0_input1_0_*`，不会引用 task1 的 `gemm0_input1_1_*`。不过这只说明符号
依赖关系，不等价于物理 PE operand RAM 必然分区。

## B 搬到 PE 后是否会串用

更低一层看，当前生成器并没有为 task0..task3 静态切出不同的 PE operand RAM 地址段。

`common_oper/task_create.cpp` 对一个 app 的映射流程是：

```text
start_map_app()
  start_map_task(); map task0; end_map_task()
  start_map_task(); map task1; end_map_task()
  start_map_task(); map task2; end_map_task()
  start_map_task(); map task3; end_map_task()
end_map_app()
```

`common_oper/inst_blk_map.cpp` 中每次 `start_map_task()` 都会新建 `Task_Resource`，
而 `get_app_max_resource()` 对 app 资源取的是每个 task 的最大值：

```text
pApp_res->operand_cnt = max(pApp_res->operand_cnt, pTask_res->operand_cnt)
```

不是把四个 task 的 operand 数量累加。因此，四个 task 在同一个 PE 上可以使用相同
的物理 operand index 编号。

用 PE0 上的代表性 CSV 顺序复现 `Task_Resource::get_reg_idx()` 后，可以看到：

```text
task0 gemm0_input1_0_0 -> operand index 1282
task1 gemm0_input1_1_0 -> operand index 1282
task2 gemm0_input1_2_0 -> operand index 1282
task3 gemm0_input1_3_0 -> operand index 1282
```

也就是说，不能把正确性解释成“task0/task1 的 B 在 PE operand RAM 里静态分到不同
地址”。它们的符号名不同，但物理 index 编号可以相同。

这个例子能成立，必须依赖 MICC / PE 执行模型里存在 task 维度的 coroutine context
隔离，或者等价的保存/恢复机制。代码中也能看到 block 配置携带 task 身份：

```text
exeBlock_conf.task_idx
exeBlock_conf.subtask_idx
exeBlock_conf_t_for_rtl.task_idx : 2 bits
exeBlock_conf_t_for_rtl.subtask_idx : 3 bits
subtask_active_msg_t.task_idx / subtask_idx / instance_idx
```

这说明 runtime/RTL 调度时知道当前执行的是哪个 task/subtask/instance；但闭源 MICC /
RTL 内部如何用 `task_idx` 隔离 operand/tensor tmp 状态，在当前开源生成代码里没有
进一步展开。

所以对“task0 会不会使用 task1 读进 PE 的 B”的最准确回答是：

```text
从 CSV 符号依赖看：不会。
task0 的 HMMAL 引用 task0 自己的 gemm0_input1_0_* tag。

从裸 operand index 看：存在重号。
task0/task1 的 B tag 可以映射到同一个 operand index 编号。

真正避免串用的机制：必须是 runtime/PE 的 task-context 隔离。
这个机制由 task_idx/subtask_idx 配置暗示，但不在 CSV graph edge 中显式表达。
```

因此，编译器里不能把 task0 使用 task1 的 B 当作合法 producer/consumer 关系；也
不能仅靠“operand index 不同”来证明隔离。更稳的 IR 表达应该把并发 task 的 PE-local
operand/tensor tmp 生命周期标上 task context 维度，直到后端确认目标硬件如何实现
这个 context。

## A 的 PE 间复用

A 的复用不是 task 间复用，而是 PE 间复用。

`conf_PEmap.h` 中：

```text
loadA:
  PE 0/4/8/12 直接 load A。

copyA:
  每行 PE 做 0->1->2->3、4->5->6->7、8->9->10->11、12->13->14->15
  的横向 COPYT。
```

`subtask2/build_so/test_graph_extend.cpp` 为这些节点建立依赖边：

```text
ld -> cal
ld -> cp
cp -> cp
cp -> cal
```

因此 A 的 PE 间复用不是无序共享，而是 graph edge 约束下的 local load / copy /
compute 流水。

## C/output 写冲突规避

C/output 不是共享写。`taskAddr_per_pe_C` 对 task0..task3 给出不同地址段，
subtask1 从各自 C 区域读入并乘 beta，subtask3 再把各自的输出写回对应 SPM 区域。

运行时还有 app 级 double-buffer / 流水细节：`OUTPUT_needown_mark` 和
`GEMM_OUTPUT1_spmStartAddr` 使得 app1 启动后回传 app0 的输出区。这是 app 级流水，
不是 task0..task3 之间的数据协作。

## 对编译器建模的启发

这个 case 里需要显式表达三种不同的数据关系：

```text
readonly shared SPM tile:
  B/input1 可被多个 task 同址读取，但不能被建模成某个 task 生产给其他 task。

partitioned task tile:
  A/input0 和 C/output0 在 task 维度有不同地址段。

graph-ordered PE copy:
  A 的 PE 间复用需要 lower 成 COPYT 节点和依赖边，而不是隐式全局共享状态。
```

对 DFU-first 编译器来说，比较稳妥的表达方式是：在 chip-level tensor program 中
显式声明 SPM/SRAM region 和 load/store boundary；在后续 lowering 中再把只读共享、
分区写、PE 间 copy 分别 lower 到对应的 processor / tile / DFU graph 结构。
