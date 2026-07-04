# Vector Accelerator Ecosystem Radar

Date: 2026-06-23

## Position

OpenFabric should not pitch itself as a generic replacement for CUDA, CANN, TensorRT,
TVM, IREE, ONNX Runtime, or mature vendor SDKs. The realistic product position is:

```text
OpenFabric Subgraph Bring-up Kit
  -> model/subgraph coverage analysis
  -> tile/dataflow lowering skeleton
  -> physical resource descriptor
  -> package manifest
  -> local checker/simulator/replay bundle
  -> runtime C ABI or ONNX Runtime EP shell
```

The best target is not the top-tier accelerator vendor with a full compiler team.
The best target is the long-tail hardware or SoC team that has an NPU/vector/dataflow
unit and a deployable runtime, but still struggles with unsupported operators,
memory planning, model conversion failures, fallback composition, validation, and
customer delivery packages.

## Target Categories

| Category | Why it matters | Fit for OpenFabric |
| --- | --- | --- |
| Edge SoC vendors with NPU SDKs | They have deployment demand and fragmented model support. | High, if the SDK has a stable runtime API but weak compiler extensibility. |
| Industrial vision / camera SoC vendors | Their workloads are static, shape-bounded, and deployment-heavy. | High for operator/package validation and model-zoo coverage work. |
| MCU / TinyML NPU vendors | They often have tight memory and limited compiler capacity. | Medium-high, but OpenFabric must stay small and static-shape first. |
| RISC-V vector/tensor-extension teams | Hardware is often ahead of software. | High for early bring-up, but requires ISA-level documentation or NDA access. |
| FPGA / eFPGA / configurable dataflow teams | Data movement and placement are first-order concerns. | High if OpenFabric's physical descriptor becomes target-neutral enough. |
| Mature AI accelerator companies | They already own compiler, runtime, and model zoo. | Mostly reference/learning, not near-term customer. |

## Company Radar

| Company / ecosystem | Public NPU interface | Cooperation posture | OpenFabric angle |
| --- | --- | --- | --- |
| GreenWaves GAP8/GAP9 | `gap_sdk` is open source and includes toolchain, NNTOOL, Autotiler, GVSOC simulator, profiler. | Very open developer posture. | Good reference for small-chip bring-up, simulator, and memory planning. |
| Canaan / Kendryte K210/K230 | `nncase` is open source, but newer backend pieces are partly closed. | Open shell plus closed backend. | Good example of "open frontend, proprietary device lowering." |
| Rockchip RKNN | Toolkit, runtime headers/libs, examples, model zoo, docs, and kernel driver are public; compiler internals and RKNN format are not. | Public GitHub plus Redmine through sales/FAE and QQ groups. | Strong candidate for ecosystem integration study, not direct replacement. |
| Sophgo TPU-MLIR | MLIR-based compiler stack is public and relatively strong. | Open technical posture. | More reference/benchmark than customer. |
| Hailo | HailoRT and model zoo are public; compiler/dev zone pieces are controlled. | Mature and developer-friendly. | Reference for runtime packaging and deployment discipline. |
| MemryX | Public docs and examples; compiler/runtime productized. | Developer-friendly, proprietary core. | Reference for dataflow accelerator productization. |
| Axelera AI | Voyager SDK, docs, examples, compiler CLI/API are public-facing. | Open developer posture. | Reference and possible integration partner, less likely to need foundational compiler work. |
| Qualcomm QNN/HTP | QNN SDK is proprietary; ONNX Runtime QNN EP is public. | Big-vendor ecosystem. | Reference for ORT EP shape, not a likely customer. |
| Arm Ethos-U ecosystem | TOSA / Vela / CMSIS-NN pieces are public. | Open IP ecosystem, but IP licensees vary. | Good downstream target shape for small static operators. |
| Kneron, SiMa.ai, Blaize, DeepX, FuriosaAI, EdgeCortix, Rebellions | Public docs vary; many expose SDKs but not compiler internals. | BD/FAE-first rather than open-source-first. | Possible later business outreach if OpenFabric has a demoable bring-up kit. |

## Interface Openness Scale

| Level | Meaning | What OpenFabric can do |
| --- | --- | --- |
| L0 closed runtime only | Only opaque model binaries and app APIs are exposed. | Limited to wrapper/runtime orchestration. |
| L1 public runtime ABI | C/Python APIs, examples, profiler, and model loader are public. | Build package validators, ORT EP shell, replay bundles, fallback routing. |
| L2 public converter/toolkit | Model conversion API and operator support lists are public. | Add coverage analyzer, graph rewrite assistant, custom-op packaging. |
| L3 public custom op or matmul API | Vendor exposes extension hooks or primitive APIs. | Compile unsupported subgraphs into vendor custom op or primitive call sequence. |
| L4 public compiler IR/lowering | Vendor compiler internals are open. | Direct backend integration or shared lowering. |
| L5 public ISA/physical format | Instruction encoding, memory model, and simulator are public. | Full OpenFabric backend is possible. |

The best near-term business fit is L1-L3. L4-L5 is technically attractive but rare.

## Practical Product Entry

The production story should be:

```text
ONNX / PyTorch export
  -> OpenFabric coverage and partition report
  -> vendor SDK for supported subgraphs
  -> OpenFabric-generated custom subgraph package when the vendor has an extension hook
  -> runtime-side fallback orchestration
  -> local replay / validation bundle
```

This avoids a frontal war with existing vendor compilers. It sells something teams
actually feel: fewer model conversion failures, clearer unsupported-op reports,
reproducible customer bundles, and faster bring-up for new model families.

## Sources

- GreenWaves GAP SDK: https://github.com/GreenWaves-Technologies/gap_sdk
- Canaan / Kendryte nncase: https://github.com/kendryte/nncase
- Rockchip RKNN Toolkit2: https://github.com/airockchip/rknn-toolkit2
- Rockchip RKNN Model Zoo: https://github.com/airockchip/rknn_model_zoo
- Sophgo TPU-MLIR: https://github.com/sophgo/tpu-mlir
- HailoRT: https://github.com/hailo-ai/hailort
- Hailo Model Zoo: https://github.com/hailo-ai/hailo_model_zoo
- MemryX Developer Hub: https://developer.memryx.com/get_started/overview.html
- MemryX examples: https://github.com/memryx/MemryX_eXamples
- Axelera Voyager SDK: https://github.com/axelera-ai-hub/voyager-sdk
- Qualcomm QNN Execution Provider in ONNX Runtime: https://onnxruntime.ai/docs/execution-providers/QNN-ExecutionProvider.html
