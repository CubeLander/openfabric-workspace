# 本地 mock runtime 设计

## 目标

本地 mock runtime 的目标是替代闭源 `core/bin/runtime` 的最小必要能力，让远程机器上的算子 examples 拷贝到本机后，可以在本机完成：

```text
编译
CSV 生成
common_oper 打包
本地运行
数值校验
trace/debug
```

第一阶段不追求 cycle accurate，也不追求完整硬件复刻。它首先服务算子开发：让开发者修改 `template/*.cpp`、`conf.h`、`conf_PEmap.h`、`riscv/testarm.c` 或 common_oper 后，不需要反复登录远程机器就能看到结果对不对。

## 要替代的闭源能力

当前顶层脚本最终会调用：

```sh
../../core/bin/runtime ./ top.so topPara.so common/src/libcommon.so
```

这个闭源 runtime 做的事情可以粗略分成两类。

第一类是 SimICT 框架能力：

```text
加载 top.so / topPara.so
加载各个 module shared object
创建 object / port / thread graph
调度 timed messages
提供 command mode
```

第二类是 DPU 模拟器能力：

```text
加载 config/result/cbuf_file.bin
加载 config/result/micc_file.bin
加载 config/input_data.bin
执行 config/riscv_program
响应 DpuAPI MMIO/DMA/MICC/CBUF/SPM 访问
驱动 PE 执行 packed instruction
生成输出和 trace
```

本地 mock runtime 第一阶段不需要复刻完整 SimICT 框架。它只需要替代 DPU 模拟器对 examples 有用的行为：

```text
读取同一批生成物
模拟内存和 DMA
模拟 CBUF/MICC/instance 配置加载
执行 PE 指令子集
产出 result/golden 可比对的数据
```

## MVP 输入输出

MVP 的输入应尽量兼容现有 examples 的生成物路径。

输入：

```text
testcase/application/CASE/<case>/result/cbuf_file.bin
testcase/application/CASE/<case>/result/micc_file.bin
testcase/application/CASE/<case>/input_data.bin
testcase/application/CASE/<case>/gpdpu_TestOp/task*/subtask*/template/*.csv
testcase/application/CASE/<case>/task*/subtask*/simulator_bin/*
testcase/application/CASE/<case>/csv_generate/conf.h
testcase/application/CASE/<case>/csv_generate/conf_PEmap.h
```

实际第一版可以在两种入口之间选一个。

### 入口 A：CSV 解释入口

```text
template/*.csv
  -> 解析 CSV
  -> 展开 pseudo instruction
  -> 执行 PE 指令子集
```

优点：

```text
实现快
容易 debug
能直接定位 CSV 生成问题
不依赖 packed binary 格式完全还原
```

缺点：

```text
绕过 common_oper 的 mapping/packing 细节
不能验证 simulator_bin/result binary 是否正确
```

### 入口 B：packed binary 入口

```text
result/cbuf_file.bin + result/micc_file.bin
  -> 解析 instance/task/subtask/exeBlock/inst
  -> 执行 PE 指令
```

优点：

```text
更接近闭源 runtime
能验证 common_oper 打包结果
后续更容易替代 core/bin/runtime
```

缺点：

```text
需要先还原 binary layout
调试成本更高
```

建议路线：

```text
MVP 先支持 CSV 解释入口，快速跑通 softmax_1。
随后接 packed binary 入口，把 common_oper 生成物纳入验证。
```

输出：

```text
mock_output.bin
mock_check.log
mock_trace.jsonl
mock_memory_dump/
mock_profile.json
```

其中 trace 至少记录：

```text
DMA copy: src/dst/bytes
instance_conf.base_addr[]
task/subtask 启动顺序
PE id
block id
instruction count
关键 load/store 地址
错误位置
```

## 最小模块模型

### DDR

DDR 是 host 侧 byte array，用于承载：

```text
input_data.bin
cbuf_file.bin
micc_file.bin
输出结果
```

第一版可以用固定地址窗口模拟：

```text
CBUF_DDR_ADDR = 0x10000000
MICC_DDR_ADDR = 0x30000000
SPM_DDR_ADDR  = 0x40000000
SPM_RST_DDR_ADDR = 0x50000000
```

这些地址来自现有 common headers 和 RISC-V 控制程序习惯。mock 内部不需要真的分配到这些虚拟地址，只需要维护地址到 buffer slice 的映射。

### SPM

SPM 是本地 DPU 片上内存模型。mock 需要支持：

```text
按 byte 读写
按 half/float/int 解释
按 base_addr_idx + imm 访问
越界检查
dump 指定 range
```

重点是实现当前 kernel 的访问模型：

```text
effective_addr = instance_conf.base_addr[base_addr_idx] + inst_offset
```

### DMA

DMA 第一版只做同步 copy：

```text
DDR -> SPM
SPM -> DDR
SPM reset / init
```

不需要模拟带宽、队列、interrupt。每次 copy 记录 trace 即可。

### CBUF / MICC / instance

mock 需要从 CSV 或 packed binary 中获得：

```text
task/subtask 数量
每个 subtask 的 PE 列表
每个 PE 的 instruction list
instance_conf.base_addr[]
启动顺序
```

第一版如果走 CSV 入口，可以先从 `conf.h`、`tempfile.h`、CSV 和 case 目录结构推导这些信息。走 packed binary 入口后，再把 `cbuf_file.bin`、`micc_file.bin` 解析作为主路径。

### PE executor

PE executor 是 MVP 的核心。它需要解释当前 examples 实际用到的指令子集。

优先支持：

```text
LDN / LDM
STD / STM
COPY / LCOPY
IMM
H2FP / FP2H
FADD / FSUB / FMUL / FDIV
FEXP2 / FLOG2 / FSQRT
MAX / ADD / MUL
```

CSV 中的 pseudo instruction 需要先展开或等价执行：

```text
HLDT / ILDT  -> LDN
ILDMT / SLDM -> LDM
HSTT / ISTT  -> STD
COPYT        -> COPY
LCOPYT       -> LCOPY
```

第一版可以采用 functional execution：

```text
不模拟 pipeline
不模拟 latency
不模拟 stall/forwarding
只保证最终数值结果和内存行为正确
```

## 与 RISC-V 控制程序的关系

第一版 mock runtime 可以绕开 `riscv/riscv`，直接执行 `testarm.c` 里隐含的控制流程：

```text
加载 CBUF
加载 MICC
DMA input DDR -> SPM
kernel start
wait finish
DMA output SPM -> DDR
app finish
```

这能最快替代闭源 runtime 对算子 examples 的关键能力。

后续再做控制面验证：

```text
QEMU RISC-V guest
  -> 执行 riscv/riscv
  -> DpuAPI.c 写 MMIO
  -> mock DFU device 响应寄存器
  -> 复用同一个 PE executor
```

因此 QEMU 是第二阶段或第三阶段，不是第一阶段前置条件。

## 兼容现有 examples 的策略

为了让远程 examples 拷回本机后尽量少改脚本，mock runtime 应提供两个入口。

### 独立 CLI

```sh
local_mock_runtime run \
  --case testcase/application/CASE/softmax_1 \
  --entry csv \
  --check
```

或：

```sh
local_mock_runtime run \
  --case testcase/application/CASE/softmax_1 \
  --entry packed \
  --check
```

### runtime 兼容 wrapper

提供一个脚本或二进制，能接近原始调用方式：

```sh
local_mock_runtime ./ top.so topPara.so common/src/libcommon.so
```

wrapper 不需要真正使用 `top.so`，但可以利用当前工作目录找到：

```text
config/result/
config/input_data.bin
config/riscv_program
```

这样现有 `run_app_riscv.sh` 后续可以通过环境变量切换：

```sh
SIM_RUNTIME=local_mock_runtime ./run_app_riscv.sh softmax_1
```

## 验收标准

MVP 验收：

```text
1. softmax_1 example 在本机完成 CSV 生成和 common_oper 打包。
2. mock runtime 不调用 core/bin/runtime。
3. mock runtime 读取 example 生成物并执行。
4. 输出结果与 golden 或 CPU reference 对齐。
5. 失败时能指出出错 PE、指令、地址或 tensor range。
```

扩展验收：

```text
1. 支持多个从远程拷回来的算子 examples。
2. 每个 example 都可以通过同一条 CLI 运行。
3. 指令覆盖率、地址访问、DMA copy 都有 trace。
4. packed binary 入口和 CSV 入口结果一致。
5. 支持 CI 中批量跑 examples。
```

## 非目标

第一阶段暂不做：

```text
cycle accurate 仿真
SimICT timed message scheduler
readline command mode
完整 QEMU SoC
真实 Linux driver
真实 DMA/IOMMU/cache coherency
多芯片通信性能模型
token/s 性能预测
```

这些能力重要，但不应该阻塞本地算子开发闭环。

## 实施顺序

建议按下面顺序开工：

```text
1. 固化 softmax_1 的本地构建命令和生成物清单。
2. 实现 CSV parser，复用或对齐 common_oper 的 8 列 CSV 格式。
3. 建立 DDR/SPM memory model。
4. 支持 softmax_1 实际使用到的 pseudo instruction 和 PE 指令。
5. 跑通 softmax_1 数值校验。
6. 增加 trace 和错误定位。
7. 接 packed binary parser。
8. 批量导入远程 examples，按缺失指令逐个补 executor。
9. 再评估是否接 QEMU 控制面。
```

## 关键判断

这条路线的核心判断是：

```text
本地开发最需要的是快速验证算子行为，
不是第一天就复制完整硬件或完整 SimICT。
```

只要 mock runtime 能忠实执行 examples 依赖的内存、DMA、instance/base_addr 和 PE 指令语义，就足以显著加速算子开发。等 examples 覆盖面扩大后，再把同一个 executor 放进更完整的 runtime、driver 或 QEMU 控制面里。
