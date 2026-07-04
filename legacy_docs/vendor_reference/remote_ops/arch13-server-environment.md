# arch-13 服务器环境与打包指南

本文档描述 DFU3500 模拟器所在的远程服务器网络拓扑、文件上传路径、
runtime 验证流程，以及本地打包规范。

## 当前正式验证入口

旧的 `gemmfix_*` / `run_diff_on_arch13.sh` / `build_stop_and_diff_on_arch13.sh`
是 binary diff bring-up 阶段的历史工具。当前合作方长期使用的正式入口已经迁移到：

```text
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/
```

本地打包：

```bash
python3 compiler/gpdpu_compiler/validation/dfu3500_partner_validation/build_payloads.py
./compiler/gpdpu_compiler/validation/dfu3500_partner_validation/scripts/package_upload_bundle.sh \
  dfu3500-validation.tgz
```

`package_upload_bundle.sh` 会先运行 entrypoint guard，确认 `run.sh` 实际选择的
`payloads/<case>/` 和 fresh build 完全一致，避免“本地验证了临时 payload，远端
却运行旧 payload”的事故。

arch-13 验证：

```bash
cd /home/huake02
tar -xzf dfu3500-validation.tgz
cd dfu3500_partner_validation
./validate_on_arch13.sh
```

默认不再追逐 byte-level diff。只有 runtime regression 需要定位底层差异时，才启用：

```bash
RUN_DIFF=1 ./validate_on_arch13.sh
```

## 1. 网络拓扑（三层链路）

```text
┌──────────────────────────────────────────────────────────────────┐
│  Layer 0: 本地开发机 (macOS / Linux)                              │
│  - OpenFabric 编译器仓库                                         │
│  - 生成 validation payloads                                      │
└────────────────────────┬─────────────────────────────────────────┘
                         │ VPN + scp
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 1: VPN → 华为云桌面 Windows                                │
│  - FusionAccess: 192.17.7.17                                    │
│  - 远程桌面: 192.17.7.107                                        │
│  - 用户: huake02                                                │
│  - 限制: 只能上传，不能下载                                        │
└────────────────────────┬─────────────────────────────────────────┘
                         │ ETX (port 8080) 上传
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 2: ETX → Linux 中转主机                                    │
│  - 地址: 192.10.1.19:8080                                       │
│  - 用户: huake02                                                │
│  - 限制: 只能上传，不能下载                                        │
│  - 用途: 文件中转站，从此处 scp 到内网 arch-13                     │
└────────────────────────┬─────────────────────────────────────────┘
                         │ scp / ssh (内网)
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 3: arch-13 Linux 主机 (模拟器环境)                         │
│  - 用户: huake02                                                │
│  - 模拟器根目录:                                                 │
│    /project/home-new/huake02/simict3500final                    │
│  - GEMM 案例目录:                                                │
│    .../gpdpu/users/risc_nn_riscv/testcase/application/          │
│    gemm_template_fusion                                          │
│  - 甲方 common_oper 源码:                                        │
│    .../testcase/common_oper/                                    │
└──────────────────────────────────────────────────────────────────┘
```

## 2. 上传路径

```text
本地
  ↓ scp (via VPN tunnel)
Windows 桌面 (FusionAccess)
  ↓ ETX 客户端上传 (port 8080)
Linux 中转机 (192.10.1.19)
  ↓ scp (内网)
arch-13 (~)
```

### 具体步骤

1. **本地 → Windows**:
   ```bash
   scp dfu3500-validation.tgz huake02@192.17.7.107:~/Desktop/
   ```

2. **Windows → Linux 中转**:
   在 Windows 上使用 ETX 客户端，上传到 `192.10.1.19:8080`

3. **Linux 中转 → arch-13**:
   ```bash
   ssh huake02@192.10.1.19
   scp ~/dfu3500-validation.tgz huake02@arch-13:~/
   ```

## 3. arch-13 上执行

```bash
ssh huake02@arch-13
cd ~
tar -xzf dfu3500-validation.tgz
cd dfu3500_partner_validation
./validate_on_arch13.sh
```

### 环境变量

```bash
SIMICT_ROOT=/project/home-new/huake02/simict3500final
PAYLOADS_DIR=$PWD/payloads
RUN_DIFF=0
REFRESH_VENDOR=0
STOP_ON_FAIL=0
```

### 期望输出

```text
run/summary.tsv
run/<case>/run.log
run/<case>/runtime.log
```

主要验收信号：

```text
runtime_rc=0
```

## 4. 历史旧打包规范（不要作为当前入口）

下面内容保留为 binary diff bring-up 阶段的历史证据，方便追溯当时如何手工
构造 `gemmfix_*` 包。当前合作方验证请使用本文开头的
`dfu3500_partner_validation` 正式入口。

### 打包脚本

```bash
# 在 dpu_project 根目录执行
cd /home/flecther/workspace/dpu_project

# 1. 生成 local binary output
PYTHONPATH=compiler:$PYTHONPATH python3 -c "
from pathlib import Path
from gpdpu_compiler.core.chip_env import ChipEnv
from gpdpu_compiler.core.dfu3500 import DFU3500_GEMM_REGIONS
from gpdpu_compiler.core.placement_types import Shard, Replicate
from gpdpu_compiler.core.ops import relu

env = ChipEnv('gemm_bundle')
a_sram = env.sram_tensor_from_region('A', DFU3500_GEMM_REGIONS['A'])
b_sram = env.sram_tensor_from_region('B', DFU3500_GEMM_REGIONS['B'])
y_sram = env.sram_tensor_from_region('Y', DFU3500_GEMM_REGIONS['C'])
a = env.load(a_sram, placements=[Shard(0), Replicate()])
b = env.load(b_sram, placements=[Replicate(), Shard(1)])
y = relu(a @ b)
env.store(y, y_sram)
env.generate(output_dir='/tmp/gemmfix_new/local', vendor_inst_mode='legacy_gemm_compat')
"

# 2. 复制 diff 脚本
cp tools/diff_scripts/byte_diff_old_python.py /tmp/gemmfix_new/
cp tools/diff_scripts/run_diff_on_arch13.sh /tmp/gemmfix_new/
cp tools/diff_scripts/build_stop_and_diff_on_arch13.sh /tmp/gemmfix_new/

# 3. 添加兼容符号链接
cd /tmp/gemmfix_new/local && ln -sf config result && cd -

# 4. 计算哈希
cd /tmp/gemmfix_new
sha256sum local/config/*.bin local/simulator_bin/*.bin > sha256.txt

# 5. 打包
cd /tmp && tar -czf ~/workspace/dpu_project/gemmfix_new.tgz gemmfix_new/
```

### Payload 结构

```text
gemmfix_*/
  README.md
  sha256.txt
  sizes.txt
  run_diff_on_arch13.sh
  build_stop_and_diff_on_arch13.sh
  byte_diff_old_python.py
  local/
    config/
      cbuf_file.bin          # 23531520 bytes
      micc_file.bin          # 8522976 bytes
    simulator_bin/
      insts_file.bin         # 21168128 bytes (304 bytes/record x 69632)
      exeblock_conf_info_file.bin
      instance_conf_info_file.bin
      subtasks_conf_info_file.bin
      tasks_conf_info_file.bin
    result -> config         # 兼容旧脚本路径
```

### 文件大小参考

| 文件 | 大小 | 记录数 |
|---|---|---|
| cbuf_file.bin | 23,531,520 | insts(69632) + exeblocks(512) + instances(65536) |
| micc_file.bin | 8,522,976 | tasks(4) + subtasks(32) |
| insts_file.bin | 21,168,128 | 69632 records x 304 bytes |
| exeblock_conf_info_file.bin | 266,240 | 512 records x 520 bytes |
| instance_conf_info_file.bin | 2,097,152 | 65536 records x 32 bytes |
| subtasks_conf_info_file.bin | 8,522,496 | 32 records x 266328 bytes |
| tasks_conf_info_file.bin | 480 | 4 records x 120 bytes |

## 5. 甲方源码参考路径

arch-13 上的关键源码文件:

```text
$SIMICT_ROOT/gpdpu/users/risc_nn_riscv/testcase/
  common_oper/
    inst_blk_map.cpp         # operand 分配器（~2245行）
    csv_oper.cpp             # CSV 解析器
    graph_extend.cpp         # 图边 + COPY 关系
    task_create.cpp          # task/subtask 映射
    task_print.cpp           # binary 序列化
    inst_blk_gen.cpp         # exeBlock 生成
  application/gemm_template_fusion/
    simulator_bin/            # vendor 生成的 binary 输出
    csv_generate/             # conf.h / conf_PEmap.h 生成器
    build_app/                # 编译产物
```

## 6. 版本指纹对照

| 文件 | 本地 stub SHA256 | arch-13 SHA256 |
|---|---|---|
| inst_blk_map.cpp | `b97408...` | `3f9d7b...` |
| libapp_build_common.so | `246236...` | `e46d0f...` |
| task_print.cpp | `d9c1af...` | - |
| graph_extend.cpp | `cd5a21...` | - |

本地 stub 与 arch-13 不是同一个 build。当前已将本地版本替换为 arch-13 OCR 版本。
