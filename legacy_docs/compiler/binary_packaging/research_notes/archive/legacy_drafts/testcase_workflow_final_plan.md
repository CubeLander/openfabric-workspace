# Testcase Runtime Package Workflow 定稿方案

日期：2026-06-05

## 目标

在：

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/
```

下新增一个公共编译/打包 workflow，用来支持远程 `application/` 目录下大量旧 examples。

核心目标：

```text
不大改 application/ 下的旧算子 examples，
不重写 common_oper，
不依赖远程机器残留中间产物，
通过 staging 副本运行旧构建流程，
最终产出闭源 runtime 可消费的标准 runtime_package。
```

最终我们希望让下面这个过程稳定可重复：

```text
testcase/application/<case>
  -> testcase/build_out/<case>/legacy_work
  -> 旧 run.sh / run_mtr.sh
  -> testcase/runtime_packages/<case>/config/*
```

## 非目标

第一阶段不做：

```text
不整理每一个旧 application example 的内部结构。
不把所有旧脚本改成 out-of-tree build。
不重写 CSV/common_oper 编译器。
不替代闭源 runtime。
不要求所有 examples 第一版都能成功。
```

第一阶段只做一个可靠外壳：

```text
staging
legacy build
artifact collection
runtime package standardization
metadata/log/report
```

## 目标目录结构

只在 `testcase/` 下新增：

```text
testcase/
  README.md
  Makefile

  application/
    # 甲方旧 examples 原样保留。

  common_oper/
    # 旧公共编译/打包代码，第一阶段不大改。

  workflow/
    README.md
    config.mk
    scripts/
      common.sh
      list_cases.sh
      inspect_case.sh
      build_package.sh
      build_many.sh
      collect_package.sh
      replay_package.sh
      clean_workflow.sh
    templates/
      metadata.template.json

  build_out/
    <case_name>/
      legacy_work/
        gpdpu/users/risc_nn_riscv/
          testcase/application/<case>
          testcase/application/build_app
          testcase/common_oper
          common/src
          dpuapi
      logs/
        build.log
      manifests/
        source_manifest.txt
        artifact_manifest.txt

  runtime_packages/
    <case_name>/
      config/
        cbuf_file.bin
        micc_file.bin
        input_data.bin
        riscv_program
      metadata.json
      source_manifest.txt
      build.log

  run_out/
    <case_name>/
      run.log
      check.log
      stat/
      rtl_trace/
      sim_trace/
      gpdpu_data
```

## 为什么 workflow 放在 testcase/ 下

远程 `application/` 下 examples 很多，且目录结构历史包袱重。我们不应该把新 workflow 放进 `application/`，避免再次和旧 examples 混在一起。

放在 `testcase/` 下的好处：

```text
application/ 保持甲方旧代码原样。
workflow/ 表示我们新增的公共流程。
build_out/ 表示临时构建副本。
runtime_packages/ 表示闭源 runtime 最终输入。
run_out/ 表示执行结果。
```

这能清楚区分：

```text
旧源码
新流程
中间产物
最终 runtime 输入
运行输出
```

## 核心原则

### 1. 旧 examples 原样保留

不要直接修改：

```text
testcase/application/<case>/run.sh
testcase/application/<case>/csv_generate/*
testcase/application/<case>/task*/subtask*/*
testcase/application/<case>/spm_data/*
testcase/application/<case>/riscv/*
```

第一版所有构建都在 staging 副本里发生。

### 2. staging 副本模拟旧相对路径

旧脚本依赖大量相对路径，例如：

```text
../../../common_oper
../../../../common/src
../../../../dpuapi
../spm_data
./simulator_bin
./rtl_bin
./result
task*/subtask*/build_so/libsubtask.so
```

因此 staging 不能只复制单个 case 目录。它必须构造一个足够接近旧工程的局部目录。

建议 staging 根为：

```text
testcase/build_out/<case_name>/legacy_work/gpdpu/users/risc_nn_riscv/
```

其中放：

```text
testcase/application/<case>
testcase/application/build_app
testcase/common_oper
common/src
dpuapi
```

这样旧脚本仍然按原相对路径工作，但不会污染真实 `application/`。

### 3. 最终只收敛 runtime package

构建成功后，只把下面 4 个核心文件收敛到标准目录：

```text
runtime_packages/<case_name>/config/cbuf_file.bin
runtime_packages/<case_name>/config/micc_file.bin
runtime_packages/<case_name>/config/input_data.bin
runtime_packages/<case_name>/config/riscv_program
```

其他中间产物留在：

```text
build_out/<case_name>/
```

运行结果留在：

```text
run_out/<case_name>/
```

## runtime_package 规范

最小包：

```text
runtime_packages/<case_name>/
  config/
    cbuf_file.bin
    micc_file.bin
    input_data.bin
    riscv_program
```

推荐完整包：

```text
runtime_packages/<case_name>/
  config/
    cbuf_file.bin
    micc_file.bin
    input_data.bin
    riscv_program
  metadata.json
  source_manifest.txt
  build.log
```

`metadata.json` 建议格式：

```json
{
  "schema_version": 1,
  "case_name": "softmax_1",
  "source_case": "application/CASE/softmax_1",
  "package_root": "runtime_packages/softmax_1",
  "legacy_build": true,
  "build_command": "make package CASE=application/CASE/softmax_1",
  "toolchain": {
    "gcc": "...",
    "g++": "...",
    "riscv64_unknown_elf_gcc": "...",
    "uname": "..."
  },
  "package_files": {
    "config/cbuf_file.bin": {
      "size": 0,
      "sha256": "..."
    },
    "config/micc_file.bin": {
      "size": 0,
      "sha256": "..."
    },
    "config/input_data.bin": {
      "size": 0,
      "sha256": "..."
    },
    "config/riscv_program": {
      "size": 0,
      "sha256": "..."
    }
  }
}
```

## 顶层 Makefile 接口

在 `testcase/Makefile` 提供：

```sh
make list-cases
make inspect CASE=application/CASE/softmax_1
make package CASE=application/CASE/softmax_1
make package CASE=application/TestOp_SIMD128_COND
make package-many
make replay CASE=softmax_1
make clean-workflow
```

说明：

```text
CASE 支持 application/ 下的相对路径。
package 名默认取 CASE 的 basename。
```

示例：

```text
CASE=application/CASE/softmax_1
  -> case_name=softmax_1
  -> runtime_packages/softmax_1

CASE=application/TestOp_SIMD128_COND
  -> case_name=TestOp_SIMD128_COND
  -> runtime_packages/TestOp_SIMD128_COND
```

## workflow 脚本职责

### common.sh

公共函数库。

建议提供：

```text
repo_root
testcase_root
resolve_case_path
case_name_from_path
prepare_stage_workspace
copy_or_sync
run_logged
sha256_file
file_size
write_metadata
write_source_manifest
assert_file
```

### list_cases.sh

扫描 `application/` 下疑似 examples。

判定规则第一版可以很保守：

```text
目录下存在 run.sh
或者存在 csv_generate/
或者存在 riscv/
或者存在 spm_data/
```

输出：

```text
case_path
case_name
has_run_sh
has_csv_generate
has_riscv
has_spm_data
status
```

后续可以输出 JSONL：

```text
workflow/manifests/cases.jsonl
```

### inspect_case.sh

检查单个 case 是否适合 package workflow。

检查项：

```text
run.sh
clean.sh
csv_generate/
riscv/
spm_data/
task/subtask/build_so 或 gpdpu*/task/subtask/build_so
```

输出：

```text
OK / WARN / FAIL
缺失项
建议 fallback
```

### build_package.sh

主入口。

流程：

```text
1. 解析 CASE。
2. 计算 case_name。
3. 清理并创建 build_out/<case_name>/legacy_work。
4. 构造 staging 目录。
5. 复制 application/<case>。
6. 复制 application/build_app。
7. 复制 testcase/common_oper。
8. 复制 common/src。
9. 复制 dpuapi。
10. 在 staging 中执行 application/<case>/run.sh。
11. 在 staging 中执行 application/build_app/run_mtr.sh。
12. 收集 runtime package 文件。
13. 写 metadata/source_manifest/build.log。
```

### collect_package.sh

从 staging 中提取：

```text
application/<case>/result/cbuf_file.bin
application/<case>/result/micc_file.bin
application/<case>/input_data.bin
application/<case>/riscv/riscv
```

写到：

```text
runtime_packages/<case_name>/config/cbuf_file.bin
runtime_packages/<case_name>/config/micc_file.bin
runtime_packages/<case_name>/config/input_data.bin
runtime_packages/<case_name>/config/riscv_program
```

### build_many.sh

批量尝试多个 cases。

输入：

```text
workflow/manifests/cases.jsonl
或 application/ 自动扫描结果
```

输出：

```text
build_out/batch_report.jsonl
build_out/batch_report.md
```

报告字段：

```text
case_name
case_path
status
duration
missing_files
error_summary
package_path
```

### replay_package.sh

后续可接。

流程：

```text
1. 读取 runtime_packages/<case_name>/config。
2. 准备 ../test/config。
3. 调用闭源 runtime。
4. 收集 run.log/stat/rtl_trace/sim_trace/gpdpu_data。
5. 写入 run_out/<case_name>。
6. 可选执行 check。
```

第一阶段可以先只做 package，不强制做 replay。

## 构建阶段事实表

### input_data.bin

来源：

```text
application/<case>/input_data.bin
```

典型生成：

```text
application/<case>/spm_data/run.sh
```

依赖：

```text
data_generate.c
input_data_convert.c
common_oper/write_file.cpp
GMP/MPFR
```

### riscv_program

来源：

```text
application/<case>/riscv/riscv
```

典型生成：

```text
application/<case>/riscv/makefile
```

依赖：

```text
testarm.c
dpuapi/DpuAPI.c
common/src headers
riscv64-unknown-elf-gcc
```

### cbuf_file.bin

来源：

```text
application/<case>/result/cbuf_file.bin
```

拼接来源：

```text
simulator_bin/insts_file.bin
simulator_bin/exeblock_conf_info_file.bin
simulator_bin/instance_conf_info_file.bin
```

### micc_file.bin

来源：

```text
application/<case>/result/micc_file.bin
```

拼接来源：

```text
simulator_bin/tasks_conf_info_file.bin
simulator_bin/subtasks_conf_info_file.bin
```

## 本地环境要求

package 构造阶段需要：

```text
Linux x86_64 容器或 VM
gcc
g++
make
riscv64-unknown-elf-gcc
riscv64-unknown-elf-objdump
GMP/MPFR headers and libs
```

闭源 runtime replay 阶段还需要：

```text
core/bin/runtime
core/bin/runtime_verbose
top.so
topPara.so
common/src/libcommon.so
```

当前本机 Mac 环境缺：

```text
riscv64-unknown-elf-gcc
GMP/MPFR
脚本期望路径下的 core/bin/runtime、top.so、topPara.so
```

因此第一阶段可以先实现 workflow 脚本和目录结构，再在 Linux/远程环境验证。

## 对甲方的沟通口径

可以这样说明：

```text
我们不会重构贵方 application 目录下的大量历史 examples。
我们会在 testcase 层增加统一 workflow。
旧 example 仍然按原脚本和原相对路径构建。
新 workflow 只负责 staging、日志、产物收集和 runtime package 标准化。
这样既保留贵方现有验证资产，又让后续本地复现、批量回归和团队协作变得可靠。
```

## 第一版实施范围

第一版建议只做：

```text
testcase/Makefile
testcase/workflow/README.md
testcase/workflow/scripts/common.sh
testcase/workflow/scripts/list_cases.sh
testcase/workflow/scripts/inspect_case.sh
testcase/workflow/scripts/build_package.sh
testcase/workflow/scripts/collect_package.sh
testcase/build_out/.gitkeep
testcase/runtime_packages/.gitkeep
testcase/run_out/.gitkeep
```

先支持：

```text
application/CASE/gemm_template_fusion
application/CASE/softmax_1
```

然后支持远程：

```text
application/TestOp_SIMD128_COND
```

再逐步批量扫描远程 `application/` 下的 examples。

## 验收标准

对单个 case，满足：

```text
1. 不直接修改 source application/<case>。
2. staging 内能跑旧 run.sh。
3. staging 内能跑 run_mtr.sh。
4. runtime_packages/<case>/config/cbuf_file.bin 存在且非空。
5. runtime_packages/<case>/config/micc_file.bin 存在且非空。
6. runtime_packages/<case>/config/input_data.bin 存在且非空。
7. runtime_packages/<case>/config/riscv_program 存在且非空。
8. metadata.json 记录文件 size/sha256。
9. source_manifest.txt 记录输入源码。
10. build.log 保留完整构建日志。
```

对批量 cases，满足：

```text
1. 能扫描 application/ 下所有候选 examples。
2. 每个 case 有 OK/WARN/FAIL 状态。
3. 失败 case 有明确缺失项或错误摘要。
4. 成功 case 产出标准 runtime_package。
```

## 当前定稿方向

我们要做的是：

```text
testcase 内的公共 runtime package 构造 workflow。
```

不是：

```text
全仓库重构。
application examples 重构。
common_oper 重写。
闭源 runtime 替代。
```

这个方案能最大化保留甲方现有 examples，同时给我们提供干净、可靠、可批量复现的 runtime 二进制目录结构。
