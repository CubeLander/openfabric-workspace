# OpenFabric GEMM 上传甲方前置任务梳理

日期：2026-06-12

## 结论先行

当前 compiler 已经可以为普通 GEMM 生成 accelerator-side 二进制：

```text
tmp/gpdpu_compiler_examples/gemm/config/cbuf_file.bin
tmp/gpdpu_compiler_examples/gemm/config/micc_file.bin
tmp/gpdpu_compiler_examples/gemm/simulator_bin/*.bin
```

但这还不是甲方 SimICT runtime 可直接 replay 的完整测试包。甲方 workflow/runtime 期望完整 runtime package 至少包含：

```text
config/cbuf_file.bin
config/micc_file.bin
config/input_data.bin
config/riscv_program 或 riscv_case/ 源码现场构建路径
```

此外，如果要让甲方“一键启动测试并判断对错”，还要带上或复用答案检查链路：

```text
spm_data/result_check.c
spm_data/check.sh
```

原始 `gemm_template_fusion` 没有发现一个独立预生成的 golden answer `.bin` 文件。它的答案模式是：

```text
input_data.bin + result_check.c
  -> 运行时重新读 A/B/C
  -> CPU/MPFR 路径计算 reference
  -> 读取 runtime 输出 gpdpu_data
  -> 逐元素打印 Result Correct / Result Error
```

所以 bundle 里至少要解决两类东西：

```text
1. runtime 运行所需四件套
2. 运行后检查所需 reference/check 脚本和输入一致性
```

## 原始 GEMM 数据生成链路

相关目录：

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/gemm_template_fusion/spm_data/
```

关键文件：

```text
data_generate.cpp
input_data_convert.c
result_check.c
run.sh
check.sh
data.h
```

### data_generate.cpp

路径：

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/gemm_template_fusion/spm_data/data_generate.cpp
```

职责：

```text
生成 ../input_data.bin
初始化 3MB SPM 镜像
写入 GEMM_INPUT1 / GEMM_INPUT2 / GEMM_INPUT3
```

关键地址关系：

```text
MEM_GEMM_INPUT1_ADDR = 0x00000000
MEM_GEMM_INPUT2_ADDR = INPUT1 后面
MEM_GEMM_INPUT3_ADDR = INPUT2 后面
MEM_GEMM_OUTPUT1_ADDR = 0x00000000
```

主函数实际执行：

```text
fopen("../input_data.bin", "wb+")
init_spm(file_input_bin)
init_gemm_input1(file_input_bin)
init_gemm_input2(file_input_bin)
init_gemm_input3(file_input_bin)
```

注意：当前文件名是 `data_generate.cpp`，旧 workflow 脚本里有地方写的是 `data_generate.c`。针对 GEMM bundle 工具时应显式兼容 `.cpp`，不要照搬脚本假设。

### input_data_convert.c

路径：

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/gemm_template_fusion/spm_data/input_data_convert.c
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/template/input_data_convert.c
```

职责：

```text
input_data.bin -> spmData.bin
gpdpu_data     -> spmResult.bin
```

它主要服务 RTL/SPM layout dump，不是 SimICT runtime replay 的必要输入。runtime replay 直接消费：

```text
config/input_data.bin
```

但如果我们希望 bundle 也支持甲方跑完后转换/保存 SPM result，应该带上这个脚本或在 run 脚本里可选执行。

### result_check.c / check.sh

路径：

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/gemm_template_fusion/spm_data/result_check.c
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/gemm_template_fusion/spm_data/check.sh
```

职责：

```text
读取 ../input_data.bin
读取 ./gpdpu_data
从 input_data.bin 解析 A/B/C
执行 gemm() / gpgpu_gemm()
生成 output_short_c reference
逐元素比较 output_short_c 和 gpdpu_data
打印 Result Correct / Result Error
打印平均绝对误差和相对误差
```

也就是说，原始答案不是单独文件，而是 check 程序动态计算。上传包如果只带 `cbuf/micc/input/riscv`，甲方可以跑 runtime，但不能自动判定结果是否正确。要做到一键测试，需要带 check runner。

## shape / ABI 对齐风险

原始 GEMM case 的 shape 来自：

```text
csv_generate/conf_PEmap.h
```

关键宏：

```text
GEMM_INPUT1_HEIGHT      512
GEMM_INPUT1_WIDTH       256
GEMM_INPUT2_HEIGHT      256
GEMM_INPUT2_WIDTH       1024
GEMM_INPUT3_HEIGHT      512
GEMM_INPUT3_WIDTH       1024

GEMM_INPUT1_HEIGHT_app  512
GEMM_INPUT1_WIDTH_app   256
GEMM_INPUT2_HEIGHT_app  256
GEMM_INPUT2_WIDTH_app   512
GEMM_INPUT3_HEIGHT_app  512
GEMM_INPUT3_WIDTH_app   512

PE_ROW                  4
PE_COL                  4
TASK_NUM                4
app_M                   1
app_K                   1
app_N                   2
```

当前 OpenFabric 普通 GEMM 示例是：

```text
A: 512 x 256
B: 256 x 512
C: 512 x 512
mesh: 4 x 4
```

这和 `*_app` shape 对齐，但原始 full buffer 宏里 `GEMM_INPUT2_WIDTH` / `GEMM_INPUT3_WIDTH` 是 1024。上传测试前必须确认：

```text
1. OpenFabric cbuf/micc 的地址/stride 解释是否按 512 输出处理。
2. input_data.bin 生成器是否应该继续使用原始 1024 full buffer。
3. result_check.c 是否需要裁剪成 OpenFabric 当前 512 输出，还是保持 legacy 1024 检查。
```

如果不处理这个问题，可能出现 runtime 能启动，但 check 读错范围或比较错 shape。

## 当前 bundle 缺口清单

### A. runtime 四件套

已生成：

```text
config/cbuf_file.bin
config/micc_file.bin
```

待补：

```text
config/input_data.bin
config/riscv_program
```

建议 v1 策略：

```text
input_data.bin:
  从 legacy gemm_template_fusion/spm_data/data_generate.cpp 编译生成，
  或允许用户通过 --input-data 指定。

riscv_program:
  v1 在 bundle 内放最小 riscv_case 源码，甲方服务器现场 make。
  也允许用户通过 --riscv-program 指定预编译 ELF。
  后续再建 compiler 自己的 host/RISC-V plan。
```

### B. 答案检查链路

待补 bundle 内容：

```text
check/result_check.c
check/check.sh
check/input_data_convert.c          # 可选，用于 spmData/spmResult 转换
check/README.md
```

待补 run 脚本逻辑：

```text
1. 调用甲方 runtime replay。
2. 将 run_out/<case>/gpdpu_data 复制到 check/gpdpu_data。
3. 将 config/input_data.bin 复制/链接到 check/../input_data.bin 或调整 result_check 路径。
4. 编译 result_check.c。
5. 执行检查并保存 check.log。
6. 如果 check.log 出现 Result Error，则脚本退出非 0。
```

注意：`result_check.c` 依赖 GMP/MPFR 路径，旧 `check.sh` 使用：

```text
$HOME/fake_root_5.1/gmp
$HOME/fake_root_5.1/mpfr
```

甲方服务器如果已有完整环境，可以复用；否则一键脚本要检测并给出清晰错误。

### C. 一键启动脚本

bundle 根目录建议带：

```text
run_on_customer.sh
```

职责：

```text
Usage: ./run_on_customer.sh /path/to/simict3500final [--case openfabric_gemm]

1. 定位 testcase 根目录：
   <simict>/gpdpu/users/risc_nn_riscv/testcase

2. 安装 package：
   testcase/runtime_packages/<case>/config/*

3. 校验四件套非空：
   cbuf_file.bin
   micc_file.bin
   input_data.bin
   riscv_program

4. 调用：
   testcase/workflow/scripts/replay_package.sh <case>

5. 收集输出：
   testcase/run_out/<case>/gpdpu_data
   testcase/run_out/<case>/run.log
   stat/rtl_trace/sim_trace

6. 可选执行答案检查：
   check/run_check.sh <run_out>/<case>/gpdpu_data
```

### D. manifest / 可追溯性

bundle 应带：

```text
manifest.json
```

建议字段：

```json
{
  "schema_version": 1,
  "case_name": "openfabric_gemm",
  "operator": "gemm",
  "shape": {
    "A": [512, 256],
    "B": [256, 512],
    "C": [512, 512],
    "mesh": [4, 4]
  },
  "runtime_files": {
    "config/cbuf_file.bin": {"size": 0, "sha256": "..."},
    "config/micc_file.bin": {"size": 0, "sha256": "..."},
    "config/input_data.bin": {"size": 0, "sha256": "..."},
    "config/riscv_program": {"size": 0, "sha256": "..."}
  },
  "check": {
    "mode": "legacy_result_check_runtime_reference",
    "source": "gemm_template_fusion/spm_data/result_check.c"
  }
}
```

## 推荐压缩包结构

```text
openfabric_gemm_bundle/
  manifest.json
  README.md
  run_on_customer.sh

  config/
    cbuf_file.bin
    micc_file.bin
    input_data.bin        # v1 可由 bundle tool 生成或用户提供
    riscv_program         # 可由用户提供；默认由 bundle/riscv_case 现场构建

  simulator_bin/
    insts_file.bin
    exeblock_conf_info_file.bin
    instance_conf_info_file.bin
    tasks_conf_info_file.bin
    subtasks_conf_info_file.bin

  check/
    result_check.c
    input_data_convert.c
    run_check.sh
    README.md

  debug/
    plan.json             # 可选，建议保留
    debug_ir/             # 可选，可大；对外包可通过 --include-debug 控制
```

压缩为：

```text
openfabric_gemm_bundle.tar.gz
```

## 本地 bundle 工具建议

新增工具：

```text
compiler/tools/make_simict_bundle.py
```

建议命令：

```sh
python3 compiler/tools/make_simict_bundle.py \
  --case-name openfabric_gemm \
  --compiler-output tmp/gpdpu_compiler_examples/gemm \
  --legacy-case simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/gemm_template_fusion \
  --output tmp/openfabric_gemm_bundle.tar.gz \
  --include-debug
```

v1 行为：

```text
1. 从 compiler-output 拷贝 cbuf/micc/simulator_bin/plan.json。
2. 编译并运行 legacy-case/spm_data/data_generate.cpp 生成 input_data.bin。
3. 拷贝 legacy-case/riscv + csv_generate/conf.h + spm_data/data.h 到 riscv_case。
4. runner 在甲方服务器现场 make riscv/riscv 并安装为 config/riscv_program。
5. 拷贝 result_check.c / input_data_convert.c。
6. 生成 run_on_customer.sh / check/run_check.sh / manifest.json。
7. 打 tar.gz。
```

当前工具仍支持显式提供预编译 `riscv_program`：

```text
--riscv-program /path/to/riscv
```

## 上传前任务列表

### P0 必须完成

```text
[ ] 明确 runtime package 四件套来源。
[ ] 生成 openfabric_gemm_bundle.tar.gz。
[x] bundle 内包含 run_all_bundles.sh。
[x] run_all_bundles.sh 能安装到 testcase/runtime_packages/<case>/config。
[x] run_all_bundles.sh 能调用甲方 runtime replay 子流程。
[x] input_data.bin 由 legacy data_generate.cpp 生成并打入 bundle。
[x] riscv_program 来源确认：优先用户提供，否则用 bundle/riscv_case 在甲方服务器现场构建。
```

### P1 强烈建议完成

```text
[x] bundle 内包含 result_check.c（当前 GEMM）。
[x] bundle 内包含 scripts/run_check.sh。
[x] run_all_bundles.sh 支持 runtime 后自动 check。
[x] check 失败时脚本返回非 0。
[x] manifest.json 记录四件套 sha256 和大小。
[x] README.md 写清楚甲方服务器执行命令。
```

### P2 后续增强

```text
[ ] compiler 原生生成 input_data.bin。
[ ] compiler 原生生成或选择 host/RISC-V program。
[ ] result_check.c 由 compiler 按 operator/shape 自动生成。
[ ] 支持只打最小包或带 debug_ir 的完整包。
[ ] 支持多 case bundle。
```

## 建议下一步实现顺序

```text
1. 已写 make_simict_test_archive.py 的 v1 版本。
2. 已支持 --input-data 和 --riscv-program 外部传入。
3. 已支持 legacy data_generate.cpp 自动生成 input_data.bin。
4. 已支持 bundle/riscv_case 在甲方服务器现场构建 riscv_program。
5. 已接入 GEMM result_check.c 自动 check。
```

这样即使 host/RISC-V 和 golden/check 还没完全 compiler 化，也可以先把“compiler 二进制上传甲方服务器跑起来”的闭环打通。

## 2026-06-12 对齐后的实现约定

当前已补一个实际打包工具：

```text
compiler/tools/make_simict_test_archive.py
```

默认命令：

```sh
python3 compiler/tools/make_simict_test_archive.py \
  --output openfabric_simict_test_bundles.tar.gz
```

默认会寻找：

```text
tmp/gpdpu_compiler_examples/gemm
tmp/gpdpu_compiler_examples/gemm_relu
```

并打成一个与 `simict3500final` 平行放置的压缩包：

```text
openfabric_simict_test_bundles.tar.gz
```

压缩包解开后的根目录：

```text
openfabric_simict_test_bundles/
  run_all_bundles.sh
  manifest.json
  README.md
  scripts/
    run_check.sh
  bundles/
    gemm/
    gemm_relu/
```

### 压缩包 runner 行为

`run_all_bundles.sh` 实现的是甲方 `test/run_app_riscv.sh` 的 runtime/check 子集：

```text
不再进入 testcase/application/<app> 执行 run.sh
不再进入 testcase/application/build_app 执行 run_mtr.sh
不再从源码重新生成 cbuf/micc

而是：
  1. 遍历 bundles/*
  2. 将 bundle/config/* 安装到 testcase/runtime_packages/<case>/config
  3. 如果 config/riscv_program 不存在，则将 bundle/riscv_case 安装到 testcase/runtime_packages/<case>
  4. 在甲方服务器环境里调用 riscv64-unknown-elf-gcc / objdump 构建 riscv/riscv
  5. 将同一 config 复制到 gpdpu/users/risc_nn_riscv/config
  6. 调用闭源 runtime：
       gpdpu/core/bin/runtime ./ top.so topPara.so common/src/libcommon.so
  7. 收集 run.log/stat/rtl_trace/sim_trace/gpdpu_data 到压缩包根目录 run_out/<case>
  8. 如果 bundle 带 check/result_check.c，则调用 scripts/run_check.sh
```

甲方服务器执行方式：

```sh
tar -xzf openfabric_simict_test_bundles.tar.gz
cd openfabric_simict_test_bundles
./run_all_bundles.sh ../simict3500final
```

如果解压目录不是和 `simict3500final` 平行，则显式传绝对路径：

```sh
./run_all_bundles.sh /path/to/simict3500final
```

### 跨机器一键上传运行

压缩包根目录还包含：

```text
upload_and_run_remote.sh
```

用于从第一层 Linux 上传 bundle 到甲方运行机、远端启动模拟器，并把输出拉回第一层 Linux。默认远端为：

实际链路是：

```text
Windows 云桌面
  -> 通过 etx 连接第一层 Linux
  -> 在第一层 Linux 解压 bundle 并执行 upload_and_run_remote.sh
  -> 脚本自动 ssh/scp 到 arch-13
  -> arch-13 对应目录自动运行 simict3500final workflow
  -> run_out/manifest 被拉回第一层 Linux 的 remote_out/<timestamp>/
```

也就是说，只需要手动把压缩包搬到第一层 Linux，不需要手动搬到 `arch-13`。

```text
user: huake01
host: arch-13
auth: 纯交互式 ssh/scp；不安装 SSH key，不依赖 sshpass
simict root: /project/home-new/huake01/simict3500final
remote work base: /project/home-new/huake01/openfabric_test_bundles
```

执行方式：

```sh
tar -xzf openfabric_simict_test_bundles.tar.gz
cd openfabric_simict_test_bundles
./upload_and_run_remote.sh
```

执行过程中 `ssh/scp` 会按需提示输入 `huake01@arch-13` 密码；这些密码提示不代表脚本已结束，后续还会继续上传、远端启动模拟器、拉回输出。脚本不保存密码、不写 `authorized_keys`，也不要求第一层 Linux 安装 `sshpass`。

如果只想上传并手动 ssh 到 `arch-13` 调试，则显式执行：

```sh
./upload_and_run_remote.sh --upload-only
```

upload-only 模式会打印类似：

```sh
ssh huake01@arch-13
cd '/project/home-new/huake01/openfabric_test_bundles/openfabric_simict_test_bundles_<timestamp>'
./run_all_bundles.sh '/project/home-new/huake01/simict3500final' 2>&1 | tee run_manual.log
```

脚本行为：

```text
1. 将当前解压目录重新打成临时 tar.gz。
2. ssh/scp 上传到 huake01@arch-13。
3. 在远端解压到 openfabric_test_bundles/<bundle>_<timestamp>。
4. 默认远端执行 ./run_all_bundles.sh /project/home-new/huake01/simict3500final。
5. 本地 tee 保存远端 stdout/stderr 到 remote_out/<timestamp>/remote_run.log。
6. 将远端 run_out/manifest/各 bundle manifest 打包拉回 remote_out/<timestamp>/remote_result。
7. 仅在 --upload-only 模式下上传后停止并打印远端手动调试命令。
```

临时上传 tar.gz 写到第一层 Linux 的 `/tmp`，不会写进 bundle 目录内部；这样避免 `tar` 打包时读到自己正在写的文件并报 `file changed as we read it`。

runtime 不再直接在共享的 `simict3500final/gpdpu/users/risc_nn_riscv` 目录里运行；每个 bundle 会使用自己的 `testcase/runtime_packages/<case>/runtime_work`。该目录会 symlink `risc_nn_riscv` 顶层依赖（例如 `top.so/topPara.so/common/mem`），因此 runtime 仍能按相对路径打开 `mem/libmem.so`，同时避开共享 `sim_trace` 目录上 `rm -rf` 偶发 `Directory not empty` 的问题。

可覆盖变量：

```text
SIMICT_REMOTE_USER
SIMICT_REMOTE_HOST
SIMICT_REMOTE_SIMICT_ROOT
SIMICT_REMOTE_BASE
SIMICT_REMOTE_LOCAL_OUT
SIMICT_REMOTE_KEEP=0        # 运行后清理远端工作目录
SIMICT_REMOTE_SSH_OPTS
```

### riscv_program 策略

当前压缩包不再依赖甲方服务器存在 legacy CASE 示例库。每个 bundle 默认携带最小 RISC-V CASE 源码：

```text
bundles/<case>/riscv_case/
  riscv/testarm.c
  riscv/makefile
  csv_generate/conf.h
  spm_data/data.h
```

runner 会把这份源码复制到：

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/runtime_packages/<case>/
```

这个目录到 `dpuapi/` 和 `common/src/` 的相对层级与原始 `testcase/application/<app>/riscv` 一致，所以原 makefile 里的：

```text
../../../../dpuapi/DpuAPI.c
../../../../common/src/
```

仍然能引用甲方 `simict3500final` 里的真实 runtime/API 资源。

runner 会优先使用已打包的 `config/riscv_program`；如果没有，则现场构建。它会自动尝试甲方脚本里的 `fake_root_5.1` 工具链位置：

```text
$SIMICT_TOOL_HOME/fake_root_5.1
$HOME/fake_root_5.1
/project/home-new/huake01/fake_root_5.1
```

如果服务器工具链不在这些位置，执行前设置：

```sh
export SIMICT_TOOL_HOME=/path/to/tool-home
```

### 当前样例包状态

当前已生成：

```text
openfabric_simict_test_bundles.tar.gz
```

包内 bundle：

```text
bundles/gemm
bundles/gemm_relu
```

其中：

```text
gemm:
  带 cbuf/micc/input_data
  带 riscv_case 源码，服务器现场构建 riscv_program
  带 legacy result_check.c
  支持运行后自动 check

gemm_relu:
  带 cbuf/micc/input_data
  带 riscv_case 源码，服务器现场构建 riscv_program
  暂不带 check
  原因：legacy gemm_template_fusion/result_check.c 是纯 GEMM reference，
       不能直接验证 ReLU 后处理输出
```

本地只做了结构验证；闭源 runtime 文件在当前 checkout 中缺失：

```text
simict3500final/gpdpu/core/bin/runtime
simict3500final/gpdpu/users/risc_nn_riscv/top.so
simict3500final/gpdpu/users/risc_nn_riscv/topPara.so
simict3500final/gpdpu/users/risc_nn_riscv/common/src/libcommon.so
```

因此真正 runtime replay 需要在甲方完整服务器上执行。
