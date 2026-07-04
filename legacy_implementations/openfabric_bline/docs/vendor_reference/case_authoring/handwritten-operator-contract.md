# 甲方手写算子职责清单

日期：2026-06-26

本文回答一个比“assembler 输入是什么”更靠前的问题：

```text
甲方工程师写一个算子 case 时，真正手写或手工维护了哪些语义工作？
OpenFabric 应该自动化哪一部分？
```

结论先放前面：OpenFabric 第一阶段不应该替代 `common_oper/build_app`
这个 assembler/packer，而应该替代甲方算子作者手写 case 的工作。也就是从
operator/shape/placement 意图出发，自动生成当前 vendor flow 所需的 case
contract、PE template、subtask graph、数据准备和控制程序输入，再继续交给
vendor assembler 打包。

## 当前证据范围

当前仓库保留并验证过的 case：

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/softmax_1
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion
```

主要参考文档：

```text
docs/vendor_reference/case_authoring/operator-case-development.md
docs/vendor_reference/case_authoring/manual-vs-generated.md
docs/vendor_reference/case_authoring/elementwise-template-frontend-chain.md
docs/vendor_reference/cases/softmax/softmax-current-real-workflow.md
docs/vendor_reference/cases/gemm/gemm-template-fusion-task-reuse.md
docs/vendor_reference/common_oper/task-creation-generategraph-chain.md
docs/vendor_reference/common_oper/openfabric-vs-vendor-compile-flow-report.md
simict3500final/gpdpu/users/risc_nn_riscv/testcase/workflow/CSV_CONFIG_GENERATOR.md
simict3500final/gpdpu/users/risc_nn_riscv/testcase/workflow/GEMM_COPYT_PIPELINE.md
simict3500final/gpdpu/users/risc_nn_riscv/testcase/workflow/PE_OPERAND_MODEL.md
```

老笔记里有时出现 `application/CASE/<case>`，这是旧快照或旧整理路径。
当前工作分支上的直接 case 路径是 `application/<case>`。

## 一句话模型

甲方原始流程更像这样：

```text
甲方算子作者手写 case contract / PE template / graph hook / control material
  -> case 脚本生成 app*.conf、CSV、libsubtask.so、input/SPM 数据、RISC-V 程序
  -> common_oper/build_app 解析 CSV + graph，做 operand/resource/COPY 修补
  -> 输出 cbuf_file.bin、micc_file.bin、input_data.bin、riscv_program
```

OpenFabric 应该先自动化第一行，也就是“手写 case”的那组职责。不要一开始就把
`common_oper` 当成要推翻的对象。

## 职责清单

| 职责 | 当前手写或手工维护入口 | 语义内容 | OpenFabric 对应抽象 | 自动化优先级 |
| --- | --- | --- | --- | --- |
| 算子形状和 case contract | `csv_generate/conf.h`、`csv_generate/conf_PEmap.h` | tensor size、shape、task/subtask 数、instance 数、SPM/DDR 地址、PE 切分、case name | `OperatorShapePlan`、`CaseConfigPlan`、`MemoryLayoutPlan` | P0 |
| task/subtask/instance 切分 | `conf.h`、`conf_PEmap.h`、`test_app_conf_generate.c` 内的 case-specific 逻辑 | 一个 op 分成几个 task，每个 task 几个 subtask，每个 subtask 执行多少 instance | `TaskPartitionPlan`、`SubtaskPipelinePlan`、`InstancePlan` | P0 |
| PE 工作划分 | `conf_PEmap.h` | 每个 PE 处理哪些 row/tile/unroll，GEMM 中每个 PE 的 A/B/C tile 地址 | `PEWorkPartition`、`TileOwnershipPlan` | P0 |
| SPM/DDR/DMA 规划 | `conf.h`、`spm_data/*.c`、`riscv/testarm.c` | input/output 地址、SPM base slot、DMA 分片、host input/golden/check 数据 | `MemoryAccessPlan`、`DataStagingPlan`、`RuntimeControlPlan` | P0 |
| per-PE microprogram 模板 | `gpdpu_TestOp/task*/subtask*/template/*.cpp` 或 `gpdpu_tensor/task*/subtask*/template/*.c/.cpp` | 按 task/subtask/PE 生成 `template/<pe>.csv`；包括 HLDT、COPYT、HMMAL、FEXP2、FDIV、HSTT 等 | `TemplateCsvProgram`、`TemplateOpPlan` | P1 |
| subtask 内部 dataflow graph | `task*/subtask*/build_so/test_graph_extend.cpp` | 把 CSV block 包装成 `GRAPH_NODE`，指定 PE 位置和 node 依赖，尤其 COPY/COPYT producer-consumer 边 | `SubtaskGraphPlan`、`GraphPluginBuildPlan` | P1 |
| RISC-V 控制程序 | `riscv/testarm.c` | CBUF/MICC 装载、DMA input/output、kernel start/wait、app finish | `RuntimeControlPlan` | P1 |
| 输入、golden、检查数据 | `spm_data/data_generate.c`、`result_check.c`、`input_data_convert.c` | 生成 `input_data.bin`、SPM/RTL 辅助文件、检查逻辑 | `CaseDataPlan`、`ValidationPlan` | P2 |
| assembler/packer 后端 | `testcase/common_oper/*`、`application/build_app/*` | CSV 解析、pseudo-op 展开、PE-local operand 分配、COPY/COPYT 目标修补、task/exeBlock/subtask 序列化 | vendor backend dependency, not first automation target | 暂不替代 |
| closed runtime | `core/bin/runtime`、`top.so`、`topPara.so` | SimICT host runtime 和模块图 | out of scope for case authoring | 不替代 |

## softmax_1：手写职责实例

当前 softmax case 的最高层输入是：

```text
application/softmax_1/csv_generate/conf.h
application/softmax_1/csv_generate/conf_PEmap.h
application/softmax_1/riscv/testarm.c
application/softmax_1/spm_data/data_generate.c
application/softmax_1/gpdpu_TestOp/task*/subtask*/template/*.cpp
application/softmax_1/task*/subtask*/build_so/test_graph_extend.cpp
```

可见语义：

```text
input/output shape:
  64 x 512

task split:
  TASK_NUM = 4
  each task handles 16 rows
  each task uses 16 PEs
  each PE handles 1 row

subtask pipeline:
  subtask1: load input, exp/partial sum/intermediate materialization
  subtask2: load sum/intermediate, divide/pack/store output

graph shape:
  mostly one graph node per active PE CSV block
  no complex inter-PE graph edge in the current non-large-scale path
```

这说明 softmax 是最适合做第一版 OpenFabric 自动化的 case：

```text
op = softmax(axis=-1)
shape = [64, 512]
  -> row-wise PE partition
  -> task/subtask config
  -> symbolic per-PE CSV template
  -> simple per-PE graph plugin
  -> vendor assembler package
```

注意：`riscv_main.cpp` / `elementwise_template.cpp` 里有类似自动生成
`conf.h/conf_PEmap.h/testarm.c` 的残留逻辑，但当前 `softmax_1/run.sh` 不调用它。
因此它们只能作为“可能的历史前端线索”，不能当成当前 runnable flow 的事实入口。

## gemm_template_fusion：手写职责实例

当前 GEMM case 的最高层输入是：

```text
application/gemm_template_fusion/csv_generate/conf.h
application/gemm_template_fusion/csv_generate/conf_PEmap.h
application/gemm_template_fusion/riscv/testarm.c
application/gemm_template_fusion/gpdpu_tensor/task*/subtask*/template/*.c/.cpp
application/gemm_template_fusion/task*/subtask*/build_so/test_graph_extend.cpp
```

可见语义：

```text
task split:
  task0..task3 are parallel task slots / tile slices in the GEMM case

subtask pipeline:
  subtask1: prepare/load C, beta path when present
  subtask2: load A/B, COPYT A between PEs, HMMAL compute
  subtask3: store C
  subtask4: optional fused epilogue

data relationship:
  A is partitioned by task and reused across PEs through COPYT
  B is readonly shared SPM tile read independently by each task
  C/output is partitioned by task and written to non-overlapping address ranges

PE copy plan:
  loadA and copyA in conf_PEmap.h describe row-wise A injection and fanout
  test_graph_extend.cpp turns copy relationships into graph dependencies
  common_oper later patches final COPY/COPYT target PE/block/operand fields
```

这说明 GEMM 自动化不能只生成 CSV 行。它至少要显式表达三类关系：

```text
readonly shared SPM tile
partitioned task tile
graph-ordered PE copy
```

否则很容易把 B 的只读共享误建模成 task 间 producer/consumer，或者把 A 的 PE 间
copy 当成无序共享状态。

## 哪些文件不是手写语义

以下文件不应该被 OpenFabric 当作“算子作者输入”：

```text
csv_generate/app_build
csv_generate/app*.conf
csv_generate/task*.conf
csv_generate/subtask*.conf
csv_generate/tempfile.h
csv_generate/instance_conf_info_file*.bin

gpdpu_TestOp/app_build
gpdpu_tensor/app_build
task*/subtask*/template/*.csv
task*/subtask*/build_so/libsubtask.so
task*/subtask*/simulator_bin/*
task*/subtask*/rtl_bin/*

result/cbuf_file.bin
result/micc_file.bin
result/input_data.bin
riscv/riscv
riscv/riscv.lst
```

判断规则：

```text
被 run.sh 删除后重建的，多半是生成物。
被多个阶段 include 的 conf.h/conf_PEmap.h，多半是 case contract。
template/*.cpp 是源码；template/*.csv 是生成物。
build_so/libsubtask.so 是 graph plugin 的编译产物，不是 graph 源码。
result/config/runtime output 是 package 或运行产物，不是手写算子语义。
```

## OpenFabric 自动化路线

推荐顺序：

### P0：先自动化 case contract

目标：从 OpenFabric operator/shape/tiling plan 生成可审查的 manifest，并能解释现有
`conf.h/conf_PEmap.h`。

产物：

```text
CaseConfigPlan
TaskPartitionPlan
MemoryLayoutPlan
PEWorkPartition
VendorCaseInputManifest
```

验收：

```text
softmax_1:
  shape/task/PE/row split 能从 OpenFabric plan 解释现有 conf.h/conf_PEmap.h。

gemm_template_fusion:
  A/B/C 地址分区、B readonly sharing、A copyA fanout 能被显式表达。
```

### P1：再生成 vendor assembler 输入

目标：生成当前 `build_app` 能消费的输入，而不是最终二进制。

产物：

```text
app*.conf
task*/subtask*/template/*.csv
task*/subtask*/build_so/test_graph_extend.cpp
run_assembler.sh
```

验收：

```text
make package CASE=application/softmax_1
make package CASE=application/gemm_template_fusion

生成的 cbuf_file.bin/micc_file.bin 与 baseline package 字节一致；
如果不一致，diff 必须能归因到明确的 template/graph/resource 差异。
```

### P2：最后补 runnable case 外围

目标：把可运行 case 的 input/golden/control material 也变成 OpenFabric 可生成对象。

产物：

```text
spm_data/data_generate.c or generated input_data.bin
riscv/testarm.c or RuntimeControlPlan projection
validation/check material
```

验收：

```text
不要求 closed runtime 文档或源码；
但生成的 runtime package surface 保持：
  config/cbuf_file.bin
  config/micc_file.bin
  config/input_data.bin
  config/riscv_program
```

## 不要自动化错对象

下面这些方向是高风险的：

```text
不要从 OpenFabric 直接手写最终 cbuf/micc 字节作为主路径。
不要把 CSV 里的 operand tag 当成最终 hardware operand index。
不要绕过 generateGraph；它是 subtask graph ABI，不是普通 helper。
不要把 testarm.c、conf.h、package scripts 折成一个“大 runtime abstraction”。
不要把 softmax 的简单 per-PE graph 过拟合成所有算子的 graph 形态。
不要把 GEMM 的 task0..task3 当成顺序阶段；它们更像并行 task slot / tile slice。
```

正确边界：

```text
OpenFabric owns:
  operator intent
  shape and tile partition
  memory/data movement plan
  PE work ownership
  template and graph intent
  runtime control intent

vendor toolchain owns, at least for now:
  CSV parse
  pseudo-op expansion
  PE-local operand allocation
  COPY/COPYT final endpoint patching
  task/exeBlock/subtask binary serialization
```

## 评审结论

这份清单当前可以作为 OpenFabric 第二阶段重启的工作边界，理由是：

```text
1. 它把“甲方手写算子”和“甲方 assembler/packer”分开了。
2. 它把 softmax 和 GEMM 的差异显式写出来，避免从一个 case 过拟合。
3. 它保留 common_oper 作为可信后端，降低重新踩 binary ABI 泥潭的概率。
4. 它给 OpenFabric 找到了从底向上长抽象的入口：先解释 conf/PE map/task split，
   再生成 CSV/graph，最后才考虑 binary parity。
```

主要风险：

```text
1. 当前只用两个 case 做证据，抽象还不能声称覆盖所有 vendor 算子。
2. softmax 的 graph plugin 太简单，不能代表 COPY/reduce/fusion 类复杂依赖。
3. GEMM 的 copyA/loadA 是否来自更早的自动 planner 仍未找到完整证据；
   当前只能把它们当作 developer-authored source configuration。
4. RISC-V control skeleton 大体固定，但地址表、DMA 分片、app layout 仍随 case 浮动。
```

建议下一步：

```text
1. 给 softmax_1 和 gemm_template_fusion 各生成一个只读 VendorCaseInputManifest。
2. Manifest 先记录文件角色、hash、生成/手写分类、OpenFabric owner。
3. 对 softmax 先尝试从 OpenFabric plan 重新生成 conf.h/conf_PEmap.h 的等价 JSON 视图。
4. 对 GEMM 先把 loadA/copyA/taskAddr_per_pe_A/B/C 提升成显式 PE dataflow plan。
5. 任何改动都先跑 make package，并与当前 baseline package 做字节对比。
```

