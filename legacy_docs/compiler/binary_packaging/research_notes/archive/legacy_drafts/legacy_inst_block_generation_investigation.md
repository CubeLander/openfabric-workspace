# Legacy `inst_block_gen` / Compiler Binary Generation Investigation

## 结论先行

- 截图目录 `simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/inst_blk_gen/` 里显示的原始文件名是 `inst_block_gen.h`。
- 当前仓库实际落地的源码文件名是 `testcase/common_oper/inst_blk_gen.h` 和 `testcase/common_oper/inst_blk_gen.cpp`，内容和截图中的 `inst_block_gen.h` 对得上。
- legacy case 里的 `task*/subtask*/build_so/test_graph_extend.cpp` 使用的是 `#include "inst_block_gen.h"`，所以本地 legacy 构建如果没有 alias/header shim，会在这个 include 上失败。
- 目前 compiler 生成 `config/cbuf_file.bin` / `config/micc_file.bin` 没有调用 legacy 的 `Inst_Block` C++ 流程，而是走 Python serializer 直接写 vendor simulator component blobs，再拼 final blobs。
- 所以：不是“用缺失的 `inst_block_gen.h` 生成了二进制”；而是 compiler 走了另一条二进制写出路径。风险点是这条路径是否完全复刻 legacy `Inst_Block -> map -> exeBlock -> task_print` 语义，仍要对齐验证。

## OCR/人工复原要点

截图中的 `inst_block_gen.h` 内容核心是：

```cpp
#pragma once
#include "csv_oper.h"
#include "common_def.h"

class Exe_Block {
public:
    uint64_t exe_block_idx;
    char valid;
    uint64_t req_activations;
    uint64_t successors_counter;
    uint64_t predecessors_counter;
    uint64_t valid_inst_counter;
    uint64_t valid_cp_inst_cnt;
    successor_t successors[MAX_SUCCESSOR_AMOUNT];
    successor_t predecessors[MAX_PREDECESSOR_AMOUNT];
    vector<Inst> ld_stage_insts;
    vector<Inst> cal_stage_insts;
    vector<Inst> flow_stage_insts;
    vector<Inst> st_stage_insts;
    exeBlock_conf_info_t exeBlock_conf_info;
    Exe_Block();
};

class Inst_Block {
public:
    Csv_Operate csv_oper;
    Exe_Block exe_block;
    Inst_Block();
    void readFromTemplate(string filename);
    void process();
    void instBlockCopy(Inst_Block *pInst_Block_Dst, Inst_Block *pInst_Block_Src);
};

class Inst_Block_Collect {
public:
    vector<Inst_Block> inst_blocks;
    bool m_valid;
    Inst_Block_Collect();
};
```

本地 `inst_blk_gen.h` 等价地定义了这些类；命名差异是 `block` vs `blk`。

## Legacy 生成链路

入口：

- `testcase/application/build_app/run_mtr.sh`
- `testcase/application/build_app/main.cpp`

legacy 流程：

1. `run_mtr.sh` 进入 application case，复制 `main.cpp` / `Makefile`，编译 `build_app`。
2. `build_app main.cpp` 读取一个或多个 `app*.conf`。
3. `Task_Group::readFromTaskFile()` 解析 task/subtask 结构。
4. `Task::subtaskConstruct()` 对每个 subtask 执行：
   - `SubTask::read_inst_block_collect()`
   - `SubTask::subtask_graph_extend()`
   - `SubTask::count_root_block_amount()`
5. `SubTask::read_inst_block_collect()` 读取 `taskX/subtaskY/template/N.csv`，每个 CSV 生成一个 `Inst_Block`：
   - `Inst_Block::readFromTemplate()` 调 `Csv_Operate::readFromCsv()` 和 `Csv_Operate::process()`
   - `Inst_Block::process()` 按 `unit_inst_type` 把指令分成 `ld/cal/flow/st` 四个 stage
6. `SubTask::subtask_graph_extend()` 动态加载每个 subtask 的 `build_so/libsubtask.so`，调用 `generateGraph(...)`。
7. `Graph_Extend::initNode()` 把模板 `Inst_Block` copy 到 graph node 上，并设置 `exe_block.valid = true`。
8. `Task_Group::map()` 调 `INST_BLK_MAP`：
   - 按 graph 拓扑/约束把 node 放到 PE
   - 分配 operand/reg index
   - 修正 copy 指令
   - 统计每个 PE 的 block/inst/operand 资源
9. `exe_block_gen()`：
   - 给每个 PE 内 graph node 分配 `exe_block_idx`
   - 根据 parent/child 填 `successors` / `predecessors`
   - 生成 `exeBlock_conf_info_t`，包括 `req_activations`、各 stage instruction count、`stages_start_pc`
10. `Print_Task_Group` 写 simulator component files：
   - `print_inst()` 写每 PE 的 `tmpinsts_file.bin*`
   - `print_for_micc_rtl()` 汇总为 `simulator_bin/insts_file.bin` 和 `simulator_bin/exeblock_conf_info_file.bin`
   - `print_task_group()` 写 `simulator_bin/tasks_conf_info_file.bin` 和 `simulator_bin/subtasks_conf_info_file.bin`
   - 其他逻辑写/填 `instance_conf_info_file.bin`
11. `run_mtr.sh` 最后拼：
   - `cbuf_file.bin = insts_file.bin + exeblock_conf_info_file.bin + instance_conf_info_file.bin`
   - `micc_file.bin = tasks_conf_info_file.bin + subtasks_conf_info_file.bin`

## Compiler 当前生成链路

入口：

- `compiler/examples/gemm.py`
- `OperatorEnv.generate(output_dir=...)`

compiler 流程：

1. 用户 API 描述 GEMM：mesh、input tensor、`a @ b`、output。
2. `OperatorEnv.to_plan()` 生成中间计划：
   - `tile_backend`
   - `route_lowering`
   - `architecture_backend`
   - `assembly_backend`
   - `dfu_graph`
   - `dfu_packing`
   - `dfu_runtime_frame`
   - `dfu_base_table`
   - `dfu_vendor_exeblock`
   - `dfu_vendor_instance`
   - `dfu_vendor_instruction_range`
   - `dfu_vendor_noncompute_range`
   - `dfu_vendor_graph_abi`
3. serializer 写 component byte image：
   - `dfu_vendor_inst_serializer.py` -> `simulator_bin/insts_file.bin`
   - `dfu_vendor_exeblock_conf_serializer.py` -> `simulator_bin/exeblock_conf_info_file.bin`
   - `dfu_vendor_instance_conf_serializer.py` -> `simulator_bin/instance_conf_info_file.bin`
   - `dfu_vendor_task_conf_serializer.py` -> `simulator_bin/tasks_conf_info_file.bin`
   - `dfu_vendor_subtask_conf_serializer.py` -> `simulator_bin/subtasks_conf_info_file.bin`
4. `dfu_vendor_component_file_writer.py` 实际 `write_bytes()` 写出上述 `simulator_bin/*.bin`。
5. `dfu_vendor_final_blob_writer.py` 拼 final blobs：
   - `config/cbuf_file.bin = insts + exeblock_conf + instance_conf`
   - `config/micc_file.bin = tasks_conf + subtasks_conf`

## 对应关系

| Legacy | Compiler |
| --- | --- |
| `Inst_Block::process()` 分 ld/cal/flow/st stage | `architecture_backend` + `dfu_vendor_instruction_range` + `dfu_vendor_noncompute_range` |
| `Graph_Extend::initNode()` 复制 `Inst_Block` 到 graph node | `dfu_graph` / `dfu_packing` / `dfu_vendor_exeblock` |
| `INST_BLK_MAP::map_subtask()` 放置 graph node 到 PE | `dfu_packing` / `dfu_vendor_aligned_packing` |
| `exe_block_gen()` 填 `exeBlock_conf_info_t` | `dfu_vendor_graph_abi` + `dfu_vendor_exeblock_conf_serializer` |
| `Print_Task_Group::print_inst()` 写 `insts_file.bin` | `dfu_vendor_inst_serializer` |
| `Print_Task_Group::print_task_group()` 写 task/subtask conf | `dfu_vendor_task_conf_serializer` / `dfu_vendor_subtask_conf_serializer` |
| `run_mtr.sh` 拼 `cbuf_file.bin` / `micc_file.bin` | `dfu_vendor_final_blob_writer` |

## 当前缺口/下一步

1. 需要给 legacy 构建补 `inst_block_gen.h -> inst_blk_gen.h` 的兼容 alias，否则 legacy `build_so/test_graph_extend.cpp` 会因为 include 名称失败。
2. 当前 test bundle 只带 compiler 产物和 RISC-V host source，不带 `common_oper`/legacy app 源码；所以不能在甲方机器上从 legacy C++ app build_app 重建 accelerator binary。
3. 要用 legacy 二进制产物排除流程错误，应该先在本地或甲方环境跑 legacy `run_mtr.sh`/workflow 生成 `result/cbuf_file.bin` 和 `result/micc_file.bin`，再用现有 bundle 打包脚本替换 compiler 的 `config/*.bin`。
4. 要证明 compiler 产物不是“形状对但语义错”，需要把 legacy GEMM 产物和 compiler GEMM 产物逐组件比较：文件大小、record count、task/subtask/exeblock 数量、每 PE inst count、root block/activation/successor/predecessor。

