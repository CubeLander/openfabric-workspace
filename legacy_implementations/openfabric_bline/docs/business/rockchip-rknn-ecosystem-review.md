# Rockchip RKNN Ecosystem Review

Date: 2026-06-23

## Executive View

Rockchip is not a "no compiler" target. It has a complete productized deployment
stack:

```text
ONNX / PyTorch / TensorFlow / Caffe / Darknet model
  -> RKNN-Toolkit2 conversion, quantization, optimization, evaluation
  -> .rknn model
  -> RKNN Runtime C/C++ API or RKNN Toolkit Lite2 Python API on board
  -> RKNPU kernel driver
```

The public interface is good enough for production integration, but not open enough
for instruction-level backend work. The compiler internals, `.rknn` format, and
runtime implementation are effectively proprietary. The kernel driver is public,
headers and examples are public, and the runtime ships as binary libraries.

OpenFabric should treat Rockchip as a mature edge-NPU ecosystem where the opportunity
is subgraph packaging, unsupported-op handling, validation, replay, and customer
delivery discipline, not replacing RKNN.

## Public Surface

| Layer | Public status | Notes |
| --- | --- | --- |
| Model converter | Public Python toolkit packages and docs | RKNN-Toolkit2 handles conversion, inference, and performance evaluation. |
| Model format | Opaque | Users generate `.rknn`; format is not a stable public compiler target. |
| Runtime API | Public headers/examples, binary runtime library | C/C++ API via `librknnrt.so`; Python deployment via Toolkit Lite2. |
| Kernel driver | Public in Rockchip kernel tree | Official README says the RKNPU kernel driver is open source in Rockchip kernel code. |
| Custom op | Public demo/header exists | Useful extension point, but the boundary is vendor-defined. |
| MatMul primitive | Public demo/header exists | Exposes direct MatMul API types, including FP16, INT8, INT4 variants. |
| Simulator | No public cycle/model simulator found | Tooling supports connected-board execution through `rknn_server`. |
| Support | Public GitHub plus gated Redmine/FAE and QQ groups | Redmine account requires sales or FAE contact. |

## Supported Chips and Workloads

RKNN-Toolkit2 currently lists support for:

- RK3588 series
- RK3576 series
- RK3566/RK3568 series
- RK3562 series
- RV1103/RV1106 and RV1103B/RV1106B
- RV1126B
- RK2118

Older RK1808, RV1109, RV1126, and RK3399Pro use older RKNN/RKNPU repositories.

The official model zoo is broad: classification, detection, segmentation, face
landmarks, license plate recognition, OCR, translation, CLIP, speech recognition,
Whisper, Zipformer, TTS, and other common edge workloads. This matters because
Rockchip's pain is probably not "can we run MobileNet"; it is the messy edge around
newer transformer/VLM graphs, model-specific conversion failures, dynamic shape,
quantization, unsupported ops, memory pressure, and delivery reproducibility.

## Recent Direction

The RKNN changelog shows a clear push beyond classic CNN:

- v2.3.2: RV1126B support, einsum and Norm improvements, automatic mixed precision,
  graph optimization.
- v2.3.0: ARM64 toolkit support, W4A16 quantization for RK3576, LayerNorm/LSTM/
  Transpose/MatMul optimization.
- v2.2.0: transformer performance optimization and MatMul/Softmax improvements.
- v2.1.0: Flash Attention on RK3562/RK3576, more fusion, improved MatMul API.
- v2.0.0-beta0: RK3576, SDPA, custom operators, PyTorch 2.1, QAT improvements.
- v1.4.0: RK3588 SRAM placement for weights/features and multi-core single-model
  execution.

RKNN-LLM is a separate signal in the same direction. It converts LLM models into
RKLLM format and runs them through a C API. The public README lists RK3588, RK3576,
RK3562, and RV1126B, and model families such as Llama, Qwen, Phi, ChatGLM, Gemma,
InternLM, MiniCPM, VLM variants, DeepSeek-R1-Distill, and RWKV.

## What Is Actually Open

The useful public pieces are:

- `rknn_api.h`, `rknn_custom_op.h`, and `rknn_matmul_api.h` in the runtime include
  directories.
- Linux and Android runtime packages with `librknnrt.so`.
- `rknn_server`, a board-side proxy that lets PC tools call board runtime APIs over
  USB/ADB for connected-board debugging.
- Demos for normal inference, zero-copy, internal memory reuse, dynamic shape,
  custom op, benchmark, and MatMul API.
- Operator support list for ONNX/PyTorch/Caffe/TensorFlow/Darknet.
- Model zoo with end-to-end conversion plus C/Python deployment examples.

The important non-open pieces are:

- RKNN compiler internals.
- `.rknn` binary/model format semantics.
- Runtime implementation behind `librknnrt.so`.
- Instruction encoding, scheduling, memory allocation internals, and a true local
  hardware simulator.

That makes Rockchip an L2-L3 openness target: public converter/runtime/custom hooks,
not a full backend target.

## Pain Points Visible From Public Docs

1. Operator coverage is broad but still restrictive.
   The ONNX support list includes many unsupported ops such as control-flow-heavy,
   sequence, random, dynamic, sparse, and special math operators. Some supported
   operators have constraints, for example `Softmax` batch size, `Slice` batch size,
   `Tile` broadcast, `RoiAlign` batch size, and resize modes.

2. Model conversion is still a project, not a button.
   The model zoo exists because real deployment needs model-specific export,
   preprocessing, postprocessing, quantization, and platform notes.

3. Board-connected debugging is central.
   `rknn_server` receives PC-side USB protocol traffic and executes runtime APIs on
   the board. That is practical, but it means reproducibility depends on runtime
   versions, board libraries, server logs, and target storage/memory state.

4. Memory pressure is real on smaller chips.
   The `rknn_server_proxy` doc explicitly discusses OOM, dump directory relocation,
   storage limits, and special runtime library handling for RV1103/RV1106/RV1103B.

5. Transformer and LLM support is moving quickly.
   MatMul, LayerNorm, Norm, SDPA, Flash Attention, W4A16, INT4, custom op, and RKNN-LLM
   all show active expansion. Fast-moving support increases the need for regression
   reports and artifact provenance.

## OpenFabric Insertion Points

### 1. RKNN Coverage and Partition Report

Input:

```text
ONNX / PyTorch-exported graph
```

Output:

```text
supported_by_rknn
unsupported_ops
restricted_ops
shape-risk nodes
quantization-risk nodes
candidate subgraphs for RKNN
candidate subgraphs for OpenFabric/custom-op fallback
```

This is the safest first product. It does not require reverse-engineering RKNN and
does not compete with Rockchip. It answers a painful production question: "Why will
this model not deploy cleanly?"

### 2. Custom-Op Packaging Assistant

If RKNN custom op hooks are usable for a given deployment, OpenFabric can compile
small unsupported static subgraphs into:

```text
custom op shared library
metadata manifest
input/output layout contract
golden vectors
runtime validation report
```

This is a plausible fit for elementwise chains, reductions, normalization variants,
or model-specific tensor transforms that are awkward in RKNN but too small to justify
manual vendor work.

### 3. MatMul/Attention Primitive Harness

The public MatMul API demo exposes a direct primitive layer with FP16, INT8, and INT4
variants. OpenFabric can build a shape/performance/accuracy harness around this:

```text
Q/K/V projection shapes
prefill/decode GEMM/GEMV shapes
batch and sequence sweep
core mask sweep
layout sweep
quantization mode sweep
```

This would not be a full Rockchip backend. It would be an empirical tuner and report
generator for "which Rockchip primitive route is stable and fast enough for this
model slice?"

### 4. Replay Bundle for RKNN Deployment

Rockchip already has connected-board execution. OpenFabric can add the discipline:

```text
model source hash
toolkit version
runtime library hash
rknn_server version
target chip
operator coverage report
input/output golden tensors
runtime logs
per-layer performance dump when available
known limitations
```

This directly matches OpenFabric's B-line direction: artifacts should be observable,
validated, and replayable.

### 5. ONNX Runtime Execution Provider Wrapper

If we want production embedding, the cleanest outer shell is:

```text
ONNX Runtime EP
  -> RKNN for supported subgraphs
  -> CPU/GPU fallback for normal unsupported subgraphs
  -> OpenFabric custom-op/subgraph package for selected static islands
```

This is much more realistic than trying to make Rockchip consume OpenFabric IR.

## What Not To Do

- Do not reverse-engineer `.rknn` as a first move.
- Do not pitch Rockchip as needing a compiler replacement.
- Do not build a generic multi-backend OpenFabric layer just for Rockchip.
- Do not assume RKNN custom op means instruction-level scheduling freedom.
- Do not put Rockchip-specific complexity into the current DFU-first compiler spine.

## Business Assessment

| Question | Assessment |
| --- | --- |
| Is the NPU interface open? | Partially. Runtime APIs, headers, examples, docs, model zoo, and kernel driver are public. Compiler internals and model binary format are closed. |
| Is the ecosystem production-oriented? | Yes. It has board runtime, model zoo, benchmarks, docs, Android/Linux flows, and FAE/QQ support. |
| Does Rockchip need OpenFabric as a compiler vendor? | Probably no. |
| Does the Rockchip ecosystem need better deployment tooling? | Yes, especially coverage, fallback, replay, validation, and model-specific subgraph handling. |
| Is this a good OpenFabric reference target? | Yes, because it is a real edge-NPU stack with public enough APIs and visible production pain. |
| Is this a good near-term revenue target? | Maybe through board vendors, product integrators, or model deployment teams; less likely through Rockchip core compiler team. |

## Recommended 30/60/90 Day Probe

### 30 days: Evidence capture

- Pick one RK3588 board and one smaller RV/RK356x-class board.
- Run official model zoo demos: MobileNet, YOLOv8/YOLO11, PPOCR, Whisper or Zipformer,
  and one RKNN-LLM quickstart if hardware permits.
- Record toolkit/runtime/server versions, model hashes, conversion logs, runtime logs,
  performance, and accuracy deltas.
- Build an internal "RKNN deployment artifact manifest" from public APIs only.

### 60 days: Coverage and replay prototype

- Implement ONNX operator coverage scanner against RKNN's public support list.
- Emit a report with unsupported ops, restricted ops, and candidate partitions.
- Package one model deployment with replay metadata and golden tensors.
- Compare "official demo only" versus "OpenFabric replay bundle" debugging quality.

### 90 days: Extension experiment

- Try one custom-op or MatMul primitive path for a narrow unsupported/static subgraph.
- Build an ONNX Runtime EP proof-of-concept wrapper only if the replay/coverage work
  proves useful.
- Decide whether the business target is Rockchip itself, Rockchip board vendors, or
  downstream product teams shipping RKNN-based applications.

## Sources

- RKNN Toolkit2 README: https://github.com/airockchip/rknn-toolkit2
- RKNN Toolkit2 changelog: https://github.com/airockchip/rknn-toolkit2/blob/master/CHANGELOG.md
- RKNN Toolkit2 docs directory: https://github.com/airockchip/rknn-toolkit2/tree/master/doc
- RKNN operator support list: https://github.com/airockchip/rknn-toolkit2/blob/master/doc/RKNNToolKit2_OP_Support-2.3.2.md
- RKNPU2 runtime/examples inside RKNN Toolkit2: https://github.com/airockchip/rknn-toolkit2/tree/master/rknpu2
- RKNPU2 historical repository: https://github.com/airockchip/rknpu2
- RKNN Model Zoo: https://github.com/airockchip/rknn_model_zoo
- RKNN server proxy doc: https://github.com/airockchip/rknn-toolkit2/blob/master/doc/rknn_server_proxy.md
- RKNN-LLM: https://github.com/airockchip/rknn-llm
- Rockchip kernel repository: https://github.com/rockchip-linux/kernel
