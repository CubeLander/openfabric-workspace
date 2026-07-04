# Environment

本文记录当前 `second_wind` 路线下，围绕 `openfabric/dfu3500` 做 DFU3500 lowering
replay、RISC-V 编译、support binary/package binary 比较所需要的本机环境。

当前重点验证入口：

```text
cmake --build build --target log10max_approved_snapshot_test
```

## Host 工具

需要常规 Linux C/C++ 构建环境：

```sh
python3 --version
bash --version
make --version
gcc --version
g++ --version
```

Ubuntu/Debian 上可用下面的包名补齐：

```sh
sudo apt-get update
sudo apt-get install -y python3 bash make gcc g++
```

脚本会重建并运行 vendor 的 host-side 工具，包括：

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/build_app/
```

运行时需要 `common_oper` 和 `common/src` 里的 shared library。公共 replay
工具会在每次命令执行时自动补 `LD_LIBRARY_PATH`，一般不需要手动 export。

## RISC-V bare-metal 工具链

客户交付包必须使用仓库固定的 xPack/newlib 工具链，不要使用系统
`riscv64-unknown-elf-gcc` 或 Ubuntu/Debian picolibc 生成 `riscv_program`。
picolibc 会产出 `0x10000000` semihost ELF 布局，已知不符合当前
log10max-fp32 approved package 的 SimICT 运行面。

安装固定工具链：

```sh
tools/install_xpack_riscv_toolchain.sh
```

脚本会下载并校验：

```text
xPack GNU RISC-V Embedded GCC 15.2.0-1
```

安装位置：

```text
.tools/xpack-riscv-none-elf-gcc/current/
```

自检：

```sh
tools/install_xpack_riscv_toolchain.sh --check-only
.tools/xpack-riscv-none-elf-gcc/current/bin/riscv-none-elf-gcc --version
```

`log10max-fp32` package builder 会优先使用这个 repo-local 工具链，也可以显式指定：

```sh
export OPENFABRIC_RISCV_TOOLCHAIN_ROOT="$PWD/.tools/xpack-riscv-none-elf-gcc/current"
```

`tools/install_riscv_toolchain_ubuntu.sh` 只保留给诊断或非交付实验使用；不要用它的
picolibc 产物刷新 customer delivery package 或 approved snapshot。

## Approved Snapshot Workflow

完整验证命令：

```sh
cmake --build build --target log10max_approved_snapshot_test
```

成功时退出码为 `0`。当前 repo-local vendor baseline replay 已经退场；
本地检查以 operator-owned snapshot/package fingerprint 为主。当前
refactored GEMM/softmax 已经使用公共 RuntimePlanImage RISC-V executor，
RISC-V runtime-control 行为由 CMake API trace gates 覆盖：

```text
plan API trace
  == RuntimePlanImage interpreted API trace
  == embedded RuntimePlanImage executor API trace
```

Legacy generated-header RISC-V compatibility trace targets have been retired
for the refactored GEMM/softmax cases. The default replay/syntax safety line is
the RuntimePlanImage API trace chain plus package/support binary comparison.

Replay 的权威比较重点是 package/support artifact：

```text
RISC-V binary comparison: SKIPPED for common RuntimePlanImage executor cases
Package binary comparison
Support binary comparison
```

`CSV comparison` 默认跳过。CSV text 是 assembler input 侧的中间材料；
operand symbol materialization 改动后可以稳定不同。replay 仍要求 CSV 与 RISC-V
程序生成成功，但通过条件看 API trace gate、package binary、support binary，而不是
RISC-V binary identity。

其中 package binary 至少包括：

```text
result/cbuf_file.bin
result/micc_file.bin
result/data_inst_replace.bin
```

support binary 至少包括：

```text
simulator_bin/instance_conf_info_file.bin
simulator_bin/tasks_conf_info_file.bin
simulator_bin/subtasks_conf_info_file.bin
rtl_bin/cbufData_instance.bin
```

脚本会在 copied replay case 中显式创建 vendor 期望的输出目录：

```text
simulator_bin/
rtl_bin/
result/
```

package 阶段会把 softmax 的完整 app 配置交给 `build_app`：

```text
app0.conf app1.conf app2.conf app3.conf
```

## 已知 vendor 输出细节

`rtl_bin/cbufData_instance.bin` 由 vendor 的
`instance_conf_info_t_for_rtl` bitfield 文本化输出生成。该 struct 中有 unnamed
padding bitfield；vendor 原始实现没有稳定初始化这些 padding 位，导致 fresh rebuild
之间可能出现 padding-only diff。

因此 workflow 在 CSV/support 生成后，会对 `cbufData_instance.bin` 做一次
canonicalization：清掉 unnamed padding 位，只保留并比较四个 21-bit base address
payload 字段。这个处理只消除 vendor 自身不确定的保留位，不改变
`simulator_bin/instance_conf_info_file.bin`，也不放宽 package binary 比较。

## 生成物

下面这些是本地生成物或本地工具，不应提交：

```text
.tools/
tmp/
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/softmax_vendor_rebuild_case/
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/softmax_refactored_build_case/
simict3500final/gpdpu/users/risc_nn_riscv/testcase/**/.softmax_refactored_logs/
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/obj/
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/libapp_build_common.so
simict3500final/gpdpu/users/risc_nn_riscv/common/src/obj/
simict3500final/gpdpu/users/risc_nn_riscv/common/src/libcommon.so
```
