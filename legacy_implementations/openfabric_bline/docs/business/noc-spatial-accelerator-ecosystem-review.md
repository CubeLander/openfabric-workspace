# NoC and Spatial Accelerator Ecosystem Review

Date: 2026-06-23

## Short Answer

OpenFabric's B-line idea is relevant beyond DFU3500, but the target is not
"every accelerator." The best fit is hardware where compute is spatially distributed
and the hard part is explicit data movement:

```text
mesh / NoC / fabric / dataflow / chiplet / manycore SRAM
```

For these systems, the compiler is not just choosing instructions. It is deciding:

```text
where data lives
who can see it
when it moves
which tile/core owns an action
which route/multicast/reduction pattern is legal
how to package enough evidence to debug failures
```

That is exactly where OpenFabric's current authority-boundary work matters:

```text
Tile semantic program
  -> execution organization
  -> template expansion
  -> physical resource descriptor
  -> vendor projection
  -> bytes / runtime package
```

## Can This Serve TT-Metal?

Yes, but not as "Tenstorrent needs us to build their compiler."

Tenstorrent already has a serious stack. `tt-metal` includes TT-NN, TT-Metalium,
model demos, technical reports, device/fabric programming material, tooling, and a
large active repository. TT-Metalium exposes explicit low-level concepts that are
very close to OpenFabric's interests: circular buffers, data movement kernels,
compute kernels, NoC async read/write, multicast, semaphores, local L1 memory,
tile registers, matrix engine, vector engine, and explicit pack/unpack behavior.

So the useful relationship is:

```text
TT-Metal as public reference target and validation testbed
not
TT-Metal as replacement-customer
```

### Realistic OpenFabric Uses Around TT-Metal

| Use | Who benefits | Why plausible |
| --- | --- | --- |
| Public NoC backend experiment | OpenFabric team | TT-Metal exposes enough concepts to test mesh/tile/fabric abstractions without NDA. |
| Static resource checker | TT hardware users / research users | TT kernels can fail through circular-buffer, L1, NoC, semaphore, and tile-register mistakes. |
| Replay/provenance bundle | TT users bringing up custom kernels | OpenFabric can package source graph, tile actions, memory windows, NoC ops, logs, hashes. |
| Subgraph lowering prototype | Research / niche customers | OpenFabric could lower a narrow static op-chain into TT-Metalium kernels for experiments. |
| Comparative architecture corpus | OpenFabric architects | TT-Metal is a mature example of NoC/dataflow programming boundaries. |

### What Not To Pitch

- Do not pitch Tenstorrent core team on "we can replace TT-MLIR/TT-NN/TT-Metal."
- Do not try to wrap all of TT-NN as just another backend while OpenFabric is still DFU-first.
- Do not use TT-Metal to justify adding generic multi-backend complexity into the current
  DFU3500 code path.

The clean move is to keep TT-Metal as a lab/reference target:

```text
OpenFabric spatial IR
  -> TT-Metal experimental projection
  -> checker/replay comparison
```

## International Teams Worth Tracking

| Team | Architecture signal | Software openness | OpenFabric opportunity |
| --- | --- | --- | --- |
| Tenstorrent | Tensix cores, NoC APIs, TT-Fabric, TT-Metalium, TT-NN. | Very open; Apache-2.0 stack, docs, examples, model demos. | Best public reference target; weak commercial need. |
| Cerebras | Wafer-scale spatial fabric with massive on-chip memory and compute. | SDK/compiler mostly controlled; publications and docs exist. | Conceptual reference for physical placement, routing, and replay. |
| SambaNova | Reconfigurable Dataflow Unit with on-chip distributed SRAM, HBM, DDR, and inter-RDU scaling. | Mostly closed product stack. | Reference for dataflow compiler/productization; unlikely direct backend. |
| Groq | Deterministic dataflow-like LPU/TSP; compiler-controlled execution. | Cloud/API first, low-level stack controlled. | Reference for deterministic producer-consumer scheduling. |
| Graphcore | IPU with many cores, in-processor memory, Poplar SDK, IPU-Fabric. | SDK/product legacy is visible; current commercial path changed after acquisition. | Strong historical reference for graph compiler + manycore memory. |
| AMD XDNA / AI Engine | Spatial dataflow AI Engine tiles from Xilinx lineage; MLIR-AIE exists. | Strong public docs/tools in parts, but product NPU access varies. | Good public playground for tile/dataflow compiler research. |
| Hailo | Edge dataflow AI accelerator with mature runtime/model zoo. | Runtime/model zoo public, compiler controlled. | Deployment/replay/coverage tooling, not replacement compiler. |
| MemryX | Dataflow accelerator with public developer hub and examples. | Public SDK surface, proprietary core. | Good productization reference and possible edge deployment partner. |
| Axelera AI | Metis/Voyager SDK, edge AI deployment stack. | Public docs/SDK, compiler APIs partly exposed. | Possible integration partner, but stack exists. |
| EdgeCortix | Dynamic neural accelerator / edge inference. | Public product docs, compiler controlled. | Possible long-tail target if extension hooks exist. |
| d-Matrix | Digital in-memory compute / chiplet inference architecture. | Product stack mostly controlled. | Reference for memory-centric physical descriptor thinking. |
| Lightmatter / Lightelligence | Photonic interconnect / optical NoC direction. | Hardware/platform oriented, not open compiler target. | Long-horizon interconnect reference, not near-term compiler customer. |
| NextSilicon | Dataflow accelerator for HPC workloads. | Product stack controlled. | Interesting non-AI dataflow target if partner access exists. |

## China Teams Worth Tracking

| Team | Architecture signal | Software openness | OpenFabric opportunity |
| --- | --- | --- | --- |
| Huawei Ascend | Da Vinci / CANN / AscendC ecosystem. | Large but controlled; public docs/tooling. | Too mature for replacement; useful reference for NPU DSL and validation. |
| Cambricon | MLU chips and BANG C style programming ecosystem. | Public materials exist, but stack is vendor-controlled. | Possible reference for accelerator C/DSL workflow; hard commercial entry. |
| Biren | GPGPU/chiplet AI training/inference products. | Mostly closed. | Not a near-term OpenFabric target unless through integrators. |
| Enflame | DTU AI accelerator ecosystem. | Mostly closed. | Similar to Biren: deployment/integration angle only. |
| MetaX | Domestic GPGPU stack, MACA platform. | Mostly closed. | More CUDA-compat/GPU world than OpenFabric's sweet spot. |
| Moore Threads | Domestic GPU/MUSA stack. | Public developer surface, closed internals. | More GPU compatibility ecosystem than NoC/dataflow target. |
| Iluvatar CoreX | GPU/AI accelerator products. | Mostly closed. | Integrator-side deployment tooling only. |
| Sophgo | TPU-MLIR public stack, BM chips. | Relatively open MLIR compiler. | Strong reference; less likely to need basic compiler help. |
| Rockchip | RKNN NPU edge SoCs. | Public toolkit/runtime/model zoo; compiler closed. | Good deployment/replay/coverage target, as covered separately. |
| Kneron | Edge NPU SoCs/modules. | SDK surface public-ish, compiler controlled. | Potential long-tail deployment target. |
| DEEPX / Rebellions / FuriosaAI | Korea AI accelerator startups. | Public SDK surfaces vary; compiler controlled. | Possible long-tail targets outside China; likely BD-led. |
| Lightelligence / Xizhi | Photonic AI / optical interconnect. | Public corporate materials, low-level stack controlled. | Long-horizon NoC/interconnect reference. |

## Where OpenFabric Is Actually Differentiated

Most of these teams already have an SDK. Many even have a compiler. The gap is usually
not "no compiler at all"; it is:

```text
no clean authority boundary
no explainable physical program object
weak unsupported-op diagnosis
weak local checking before hardware/runtime
poor replay bundles for customer failures
fragile model-specific bring-up
unclear provenance from model op to physical resource use
```

That suggests the product should be:

```text
OpenFabric Spatial Bring-Up / Validation Kit
```

Not:

```text
OpenFabric Universal Backend Compiler
```

## Priority Map

| Priority | Targets | Reason |
| --- | --- | --- |
| A: reference/testbed | Tenstorrent TT-Metal, AMD MLIR-AIE, Sophgo TPU-MLIR | Public enough to study and prototype against. |
| A: deployment tooling | Rockchip RKNN, Hailo, MemryX, Axelera | Production users feel conversion/debug/replay pain. |
| B: BD-led partnerships | EdgeCortix, Kneron, SiMa.ai, DeepX, FuriosaAI, Rebellions | Possible need, but requires access and relationship. |
| C: architecture references | Cerebras, SambaNova, Groq, Graphcore | Excellent ideas, unlikely near-term customers. |
| C: Chinese GPGPU majors | Biren, MetaX, Moore Threads, Iluvatar, Enflame | Mostly GPU/CUDA-compat ecosystems; not OpenFabric's cleanest wedge. |

## Recommended Probe

1. Build a "spatial accelerator traits" checklist:

```text
tile/core topology exposed?
local memory exposed?
NoC/fabric operations exposed?
multicast/reduce exposed?
custom op hook exposed?
runtime package format exposed?
simulator/checker exposed?
profile/perf counters exposed?
```

2. Score TT-Metal, RKNN, Hailo, MemryX, Axelera, Sophgo, AMD MLIR-AIE.

3. Choose one public NoC-ish playground:

```text
TT-Metal if the goal is NoC/tile programming realism.
AMD MLIR-AIE if the goal is compiler IR/lowering research.
Sophgo TPU-MLIR if the goal is MLIR production compiler study.
Rockchip RKNN if the goal is production deployment tooling.
```

4. Keep DFU3500 B-line clean. Any TT/RKNN/Hailo work should live as business/lab
evidence until there is a real product decision.

## Sources

- Tenstorrent `tt-metal`: https://github.com/tenstorrent/tt-metal
- Tenstorrent TT-Metalium compute/dataflow docs: https://docs.tenstorrent.com/tt-metal/latest/tt-metalium/tt_metal/advanced_topics/compute_engines_and_dataflow_within_tensix.html
- Tenstorrent TT-Metalium data movement APIs: https://docs.tenstorrent.com/tt-metal/latest/tt-metalium/tt_metal/apis/kernel_apis/data_movement/data_movement.html
- Graphcore IPU product page: https://www.graphcore.ai/products/ipu
- AMD Ryzen AI page: https://www.amd.com/en/products/processors/consumer/ryzen-ai.html
- AMD MLIR-AIE: https://github.com/Xilinx/mlir-aie
- SambaNova SN40L paper: https://arxiv.org/abs/2405.07518
- Cerebras WSE overview reference: https://en.wikipedia.org/wiki/Cerebras
- Groq LPU/TSP architecture reference: https://en.wikipedia.org/wiki/Groq
- SPADA spatial dataflow programming paper: https://arxiv.org/abs/2511.09447
- Rockchip RKNN ecosystem note: [rockchip-rknn-ecosystem-review.md](rockchip-rknn-ecosystem-review.md)
