# TT-Metal Simulator Lessons For OpenFabric

本文记录从本地 `tmp/tt-metal` 里观察到的 hardware simulator / mock /
replay 体系，以及它对 OpenFabric 自建 chip 之上全栈的启发。

结论先行：TT-Metal 不是只有一个“模拟器”。它把不同真实性层级拆开：

- `TargetDevice::Mock`：用 cluster descriptor 建一个无硬件的拓扑/设备壳，
  主要验证设备发现、allocator、fabric/control-plane 和分布式路径。
- `TargetDevice::Emule`：软件 emulation mode，仍走 runtime/device 接口，但背后是
  software-emulated chip 和真实 memory I/O。
- `TargetDevice::Simulator`：外部 functional simulator，例如 `ttsim`，通过
  `TT_METAL_SIMULATOR` 接入，目标是端到端正确性和 CI coverage。
- `LightMetal`：capture/replay host API 调用序列，关注可重放 artifact，而不是解释
  kernel 语义。
- `GraphProcessor` / `NO_DISPATCH`：捕获 op、buffer、program、device info，必要时
  阻断真实 dispatch。
- `noc_estimator`：基于经验数据的 NoC latency/bandwidth estimator，是性能模型，不是
  功能模拟器。

这对 OpenFabric 的启发是：先定义 simulator 分层和 artifact contract，再逐层补真实度。
不要一开始就追求 cycle-accurate，也不要把 functional correctness、resource legality、
vendor binary replay 和性能估计混在一个类里。

## TT-Metal 的分层做法

### Runtime Target 是一等概念

`tmp/tt-metal/tt_metal/llrt/tt_target_device.hpp` 定义了：

```cpp
enum class TargetDevice : uint8_t {
    Silicon = 0,
    Simulator = 1,
    Mock = 2,
    Emule = 3,
};
```

`rtoptions` 通过环境变量选择 target：

- `TT_METAL_SIMULATOR=/path/to/libttsim_*.so` 进入 simulator。
- `TT_METAL_MOCK_CLUSTER_DESC_PATH=...` 进入 mock。
- `TT_METAL_EMULE_MODE=1` 进入 emule，并要求提供 mock cluster descriptor。
- `TT_METAL_SIMULATOR_DIRECT_TENSOR_WRITES=1` 为 simulator preload 提供特殊直写路径。

值得学的是命名清楚：mock、emule、simulator 各自表达不同承诺。OpenFabric 也应该避免一个
`Simulator=True` 同时代表所有事情。

### Mock Cluster Descriptor 支撑无硬件开发

`tmp/tt-metal/tests/tt_metal/tt_fabric/custom_mock_cluster_descriptors/README.md`
说明 mock cluster descriptor 可以从真实硬件序列化，也可以手写，用于在没有硬件时测试
fabric routing、control plane、distributed features。

这对 OpenFabric 很直接：当前 DFU3500 的硬件事实集中在
`compiler/gpdpu_compiler/core/dfu3500`。下一步应该让这些事实也能被 simulator/resource
checker 消费，而不是只服务 lowering。先从一个 `Dfu3500ChipModel` 或等价 descriptor
开始，包含：

- 逻辑拓扑、物理 PE mesh、可用 PE 集合。
- SRAM/SPM region、offset、容量、对齐规则。
- route / DMA / load-store 能力边界。
- vendor blob capacity 和 legacy base address 换算。

### ttsim 是 Functional Chip Simulator

`tmp/tt-metal/tt_metal/tt-llk/tests/TTSIM.md` 把 `ttsim` 描述为 functional simulator，
可在普通 x86_64 host 上端到端模拟 Wormhole/Blackhole，无需硅片。它需要：

- `libttsim_{wh,bh}.so`
- 放在 `.so` 旁边的 `soc_descriptor.yaml`
- slow dispatch
- 对未实现 ISA 明确报 `UnimplementedFunctionality`

它的定位也很克制：用于 correctness 和 CI coverage，不用于性能。OpenFabric 第一版也应该这样：
能解释 program、能复现实验、能给出稳定 failure taxonomy，比“像真硬件一样快”更重要。

### Simulator Tests 先验证硬件接口

`tmp/tt-metal/tests/tt_metal/tt_metal/device/test_simulator_device.cpp` 只做很基础的事情：
初始化 device、访问 allocator/base address、对 TLB/L1 做 read/write。这不是算子正确性测试，
而是 runtime-device contract 测试。

OpenFabric 可以对应建立一组非常低层的 simulator smoke tests：

- chip model 可创建。
- SRAM tensor region 可声明、地址可计算。
- load/store boundary 可执行或被解释。
- 每个 PE/SPM region 的读写、越界、重叠检测行为稳定。
- physical program descriptor 能被 simulator 接受或给出结构化错误。

### LightMetal 把一次运行变成可重放 Artifact

`tmp/tt-metal/tt_metal/impl/lightmetal` 使用 FlatBuffer 捕获 buffer/program/kernel/CB/runtime
args/command 序列，并用 global id 在 replay 时重建对象关系。它当前有不少 TODO 和被禁用路径，
但方向很重要：capture/replay 是调试硬件栈的核心能力。

OpenFabric 应该尽早拥有类似 artifact：

```text
ChipEnv source metadata
  + chip-level program dump
  + ProcessorLogicalProgram
  + ProcessorTileProgram
  + DfuPhysicalProgramDescriptor
  + vendor rows / binary package
  + SRAM input/output snapshots
  + simulator verdict / SimICT verdict
```

这样我们和甲方对齐问题时，不只给“某个 Python case 失败”，而是给可复现 bundle。

### Graph Capture 和 NO_DISPATCH 是轻量 Mocking

`tmp/tt-metal/ttnn/core/graph/graph_processor.cpp` 可以捕获 op/tensor/buffer/program/device
信息。`RunMode::NO_DISPATCH` 通过 hook 阻断 allocation、read/write、program run，只留下图和
资源视图。

OpenFabric Bline 可以学这个模式：在 compile pipeline 每层都提供 `dump/validate/no_execute`
入口。比如：

```text
env.generate(no_execute=True)
compile_to_tile_program(dump=True)
lower_to_physical(validate_only=True)
pack_vendor_bundle(capture_artifact=True)
```

### NoC Estimator 是独立性能模型

`tmp/tt-metal/tt_metal/api/tt-metalium/experimental/noc_estimator/README.md`
把 NoC estimator 定义成基于经验数据插值的 latency/bandwidth 工具。它服务 kernel/data movement
设计，但不承担 correctness。

OpenFabric 后面也应该把 performance estimator 放在 simulator 旁边，而不是塞进 functional
simulator。第一版只需要粗粒度 route/load/store 计数和 capacity warning；等有真实 DFU 数据后，
再引入经验表。

## OpenFabric 建议路线

### S0: Mock Chip / Resource Simulator

目标：不执行算子，只验证 chip facts、placement、SRAM/SPM、route 和 vendor capacity。

输入：

- `ProcessorTileProgram`
- `DfuPhysicalProgramDescriptor`
- DFU3500 chip model

输出：

- resource report
- illegal placement / overlapping region / out-of-bounds / unsupported route 的结构化错误
- 每个 PE 的 tile action、memory window、vendor row capacity 摘要

这是最应该先做的一层，因为它直接服务 Bline 的分层 refactor，也能减少依赖甲方调试。

### S1: Functional IR Interpreter

目标：在 CPU 上解释 chip-level / tile-level 语义，验证数值正确性。

建议从 first-class tile op chain 做起：

```text
TileRouteAction
  -> TileComputeAction(gemm_tile)
  -> TileComputeAction(relu / bias_add / gelu / log10max / ...)
  -> TileStoreAction
```

解释器只理解 FiberOp / TileAction 的语义，不理解 vendor row 的微结构。GEMM 的 K-loop、
accumulator prepare/finalize、subtask/instance layout 仍然属于 template/physical lowering。

### S2: Physical Descriptor Simulator

目标：消费 Bline physical program，验证 template expansion 和 vendor rows 的结构正确性。

它可以模拟：

- row provenance 是否能追溯到原始 FiberOp。
- runtime patch values 是否覆盖完整。
- row ordering / dependency 是否满足 tile dependency graph。
- vendor blob capacity / residency 是否合法。

它不需要数值执行，也不应该把 vendor rows 反向变成新的 semantic IR。

### S3: Replay / Regression Bundle

目标：把一次 compile、pack、SimICT/vendor 调用变成可重放包。

建议每个 bundle 包含：

- textual IR dumps
- binary artifact
- SRAM input/output snapshot
- simulator verdict
- SimICT verdict
- provenance map
- tool/version/chip-model hash

这层会成为团队协作和甲方对齐的关键抓手。

### S4: Performance Estimator

目标：基于真实数据逐步估计 route、load/store、compute、packing cost。

不要把它作为 simulator P0。先让 correctness/resource/replay 稳住，再用经验表接近真实性能。

## 对 Bline 的具体落点

建议在 `compiler/gpdpu_compiler/core` 下形成类似结构：

```text
core/
  dfu3500/
    chip_model.py
    memory_model.py
    route_model.py
  sim/
    target.py
    resource_checker.py
    tile_interpreter.py
    physical_descriptor_checker.py
    replay_bundle.py
  artifacts/
    schema.py
    dump.py
```

这里的 `sim/` 不应该被 `ChipEnv` op-time 调用。正确入口是在显式 lowering 产物之后：

```text
ChipEnv.generate()
  -> lower_to_processor_logical()
  -> lower_to_tile_program()
  -> sim.resource_check(tile_program)
  -> lower_to_physical()
  -> sim.physical_check(physical_program)
  -> pack_vendor_bundle()
  -> sim/replay/SimICT compare
```

## 不建议照搬的点

- 不要照搬 TTNN 的用户 API；OpenFabric 当前仍然是 DFU-first。
- 不要把 mock/emule/simulator 合成一个全局开关。
- 不要在 functional simulator 里展开 GEMM K-loop 或 vendor rows，把 Bline 语义污染回去。
- 不要第一版就做 cycle-accurate simulator。
- 不要只有 pass/fail，要有 dump、provenance、memory snapshot 和结构化错误。

## 一句话判断

TT-Metal 值得学的不是某一个 simulator 实现，而是它承认硬件软件栈需要多种“可运行的假真实”：
mock 拓扑、functional chip simulator、no-dispatch graph capture、replay artifact、性能估计各司其职。
OpenFabric 如果要做 chip 之上的全栈，也应该先建立这些分层 contract，再逐层提高真实性。
