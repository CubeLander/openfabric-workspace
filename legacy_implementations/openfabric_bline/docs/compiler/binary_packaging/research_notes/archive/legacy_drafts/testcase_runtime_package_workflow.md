# Testcase Runtime Package 工作流草案

日期：2026-06-05

## 背景

远程 `application/` 目录里有大量 examples。它们的旧工作流把开发者源码、中间产物、构建产物、runtime 输入、运行输出混在同一个 app 目录中，例如：

```text
conf.h / conf_PEmap.h
template/*.cpp
test_graph_extend.cpp
testarm.c
data_generate.c / result_check.c
*.csv
*.bin
*.so
obj/
result/
simulator_bin/
rtl_bin/
simulator_bin_multi_app/
rtl_bin_multi_app/
riscv/riscv
input_data.bin
output_data.bin
```

直接重构所有 examples 不现实，也不适合乙方当前权限边界。我们应该尽量保持旧 examples 原状，只在 `testcase/` 内增加一层薄封装，把“产出闭源 runtime 可消费二进制目录”的过程变得清晰、可重复、可团队协作。

## 核心判断

闭源 runtime 只负责消费和执行，不参与构造 runtime 输入文件。

runtime 最终消费的核心文件集合是：

```text
config/cbuf_file.bin
config/micc_file.bin
config/input_data.bin
config/riscv_program
```

构造这些文件所需的主要组件是：

```text
application/<case>/run.sh
application/<case>/csv_generate/*
application/<case>/task*/subtask*/template/*.cpp
application/<case>/task*/subtask*/build_so/*
application/<case>/spm_data/*
application/<case>/riscv/*
application/build_app/*
testcase/common_oper/*
common/src/*
dpuapi/*
gcc/g++/make
riscv64-unknown-elf-gcc
GMP/MPFR
```

没有发现构造 `cbuf_file.bin`、`micc_file.bin`、`input_data.bin`、`riscv_program` 必须调用闭源 SimICT runtime、`top.so`、`topPara.so` 或 Scheme runtime graph 生成器。

## 设计原则

```text
1. 改动范围尽量只放在 testcase/ 内。
2. 不大改远程拷回来的 application examples。
3. 不重写 common_oper，不重写算子编译器。
4. 第一版用 staging 副本跑旧流程，避免污染源码目录。
5. 最终产物明确收敛到 runtime_package。
6. 后续再逐步抽象公共编译步骤。
```

## 建议目录结构

只在 `simict3500final/gpdpu/users/risc_nn_riscv/testcase/` 内新增：

```text
testcase/
  README.md
  Makefile

  common_oper/
    # 旧公共打包工具，先不大改。

  application/
    # 旧 examples，先保留。

  package_flow/
    config.mk
    scripts/
      common.sh
      build_runtime_package.sh
      stage_case.sh
      run_legacy_build.sh
      collect_package.sh
      replay_package.sh
      clean_package.sh
    templates/
      metadata.template.json

  build_out/
    <case_name>/
      legacy_work/
      logs/
      manifests/

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
      stat/
      rtl_trace/
      sim_trace/
      gpdpu_data
      check.log
```

## 为什么使用 staging 副本

旧脚本大量使用固定相对路径和原地输出：

```text
./simulator_bin
./rtl_bin
./result
./riscv/riscv
./spm_data
task*/subtask*/build_so/libsubtask.so
```

第一版如果强行改成 out-of-tree build，会牵动太多旧脚本。更稳的做法是：

```text
1. 复制 application/<case> 到 build_out/<case>/legacy_work/application/<case>
2. 同步复制 application/build_app、common_oper 等必要公共目录
3. 在 legacy_work 中按旧相对路径执行原 run.sh/run_mtr.sh
4. 从 legacy_work 收集最终 runtime package 文件
5. 原始 application/<case> 源码不被污染
```

这样旧脚本仍然“以为自己在旧目录工作”，但真实写入的是 staging 工作区。

## 顶层命令设计

建议在 `testcase/Makefile` 提供：

```sh
make package CASE=application/CASE/softmax_1
make package CASE=application/TestOp_SIMD128_COND
make replay CASE=softmax_1
make clean-package CASE=softmax_1
make list-packages
```

由于旧 examples 目录布局可能不同，`CASE` 应支持相对路径：

```text
application/CASE/softmax_1
application/TestOp_SIMD128_COND
```

package name 默认取路径 basename：

```text
application/CASE/softmax_1 -> softmax_1
application/TestOp_SIMD128_COND -> TestOp_SIMD128_COND
```

## build_runtime_package 流程

`package_flow/scripts/build_runtime_package.sh <case_path>` 做：

```text
1. 解析 case 路径和 package 名。
2. 创建 build_out/<case_name>/legacy_work/。
3. 复制必要目录到 legacy_work：
   - application/<case>
   - application/build_app
   - common_oper
   - ../common/src
   - ../dpuapi
4. 在 legacy_work/application/<case> 中执行旧 ./run.sh。
5. 在 legacy_work/application/build_app 中执行旧 ./run_mtr.sh。
6. 收集 runtime 最终输入：
   - application/<case>/result/cbuf_file.bin
   - application/<case>/result/micc_file.bin
   - application/<case>/input_data.bin
   - application/<case>/riscv/riscv
7. 写入 runtime_packages/<case_name>/config/：
   - cbuf_file.bin
   - micc_file.bin
   - input_data.bin
   - riscv_program
8. 生成 metadata.json。
9. 生成 source_manifest.txt。
10. 保存 build.log。
```

## runtime_package 规范

最小 runtime package：

```text
runtime_packages/<case_name>/
  config/
    cbuf_file.bin
    micc_file.bin
    input_data.bin
    riscv_program
```

推荐完整 package：

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
  check/
```

`metadata.json` 建议记录：

```json
{
  "case_name": "softmax_1",
  "source_case": "application/CASE/softmax_1",
  "legacy_build": true,
  "package_files": {
    "config/cbuf_file.bin": {"size": 0, "sha256": "..."},
    "config/micc_file.bin": {"size": 0, "sha256": "..."},
    "config/input_data.bin": {"size": 0, "sha256": "..."},
    "config/riscv_program": {"size": 0, "sha256": "..."}
  },
  "build_command": "make package CASE=application/CASE/softmax_1"
}
```

## 公共过程抽象

第一版只抽象流程，不抽象算子逻辑。

建议 `package_flow/scripts/common.sh` 提供：

```text
resolve_case_path
case_name_from_path
prepare_stage_workspace
copy_legacy_inputs
run_case_build
run_common_pack
collect_runtime_package
write_metadata
write_source_manifest
sha256_file
```

第二阶段再考虑抽象旧 `csv_generate/run.sh` 中的公共编译步骤：

```text
compile_app_conf
build_csv_generator
generate_csv
build_subtask_so
generate_spm_data
build_riscv_control
pack_cbuf_micc
```

## replay_package 流程

后续可新增：

```sh
make replay CASE=softmax_1
```

流程：

```text
1. 清理 ../test/config、stat、trace。
2. 复制 runtime_packages/<case>/config/* 到 ../test/config/。
3. 调用闭源 runtime。
4. 将 run.log、stat、rtl_trace、sim_trace、gpdpu_data 收集到 run_out/<case>/。
5. 可选执行原 check.sh。
```

第一阶段可以只做 `package`，`replay` 后续再接。

## 优点

```text
改动范围只在 testcase 内。
不重构大量远程 examples。
不改变旧 common_oper 的行为。
不用一开始理解所有旧脚本。
能快速产出整洁 runtime_package。
源码目录不会被新 workflow 污染。
后续可以逐步替换旧编译阶段。
```

## 风险和注意点

```text
1. staging 副本必须保持旧相对路径，否则旧脚本会找不到 common_oper/common/src/dpuapi。
2. RISC-V 交叉编译器和 GMP/MPFR 需要在本地 Linux 环境补齐。
3. 部分旧 examples 可能依赖 application/ 下的 sibling template 目录。
4. 有些 examples 可能修改了 run.sh 路径假设，需要 package flow 支持 case-specific fallback。
5. 当前本机缺少闭源 runtime 执行阶段所需的 runtime/top.so/topPara.so，package 构造可以先做，replay 后续补。
```

## 第一版落地范围

建议第一版只新增：

```text
testcase/Makefile
testcase/package_flow/scripts/common.sh
testcase/package_flow/scripts/build_runtime_package.sh
testcase/runtime_packages/.gitkeep
testcase/build_out/.gitkeep
```

第一版先支持一个本地已有 case：

```text
application/CASE/softmax_1
```

跑通后再支持远程的：

```text
application/TestOp_SIMD128_COND
```

## 当前决策

大方向已经明确：

```text
不大改仓库。
不重构所有 examples。
不先重写编译器。
先在 testcase 内增加 runtime_package 构造工作流。
用 staging 副本保护旧源码目录。
把闭源 runtime 最终消费的二进制目录结构标准化。
```

后续讨论重点：

```text
1. staging workspace 应该复制哪些目录，哪些可以 symlink。
2. runtime_package 是否需要包含 checker/golden。
3. package metadata 需要记录哪些字段。
4. 第一版是否只做 package，还是同时做 replay。
5. 如何容器化本地构造环境。
```
