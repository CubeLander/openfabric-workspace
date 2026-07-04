# RuntimePlanImage

Status: current protocol guidance. The source ABI remains
`common_app_builder/openfabric_runtime_plan_image.h`.

`RuntimePlanImage` is the target runtime action stream emitted from an operator
plan. It is not a high-level operator IR and it is not a replacement for device
CSV, graph trace, app config, or instance config. Its job is to drive a common
RISC-V-style executor through effective target actions:

```text
package preload
tensor/materialization transfer
kernel wait
kernel launch
app finish
```

## Protocol Shape

The image contains fixed tables plus an ordered action stream:

```text
header
package preload table
transfer table
kernel launch table
action table
```

The action table is the only execution-order owner. Payload tables only store
the effective parameters referenced by actions.

## Package Preload

Package preloads describe target package material, such as CBUF and MICC input
addresses. These are not tensor data addresses. They belong to the DFU3500 target
package protocol and should come from target/package binding, not from tensor
layout.

## Transfer

Transfers store effective DPU API parameters:

```text
mem_addr[2]
spm_addr[2]
x_slice / y_slice / x_full
direction
mode / channel / regular fields
```

Operators may build these from tensor access projections, materialization
requests, static windows, or ping-pong windows, but the executor should not
reconstruct GEMM/softmax/log10max control logic from vendor macro names.

## Kernel Launch

Kernel launch records the effective launch parameters:

```text
inst_reload
task_count
cbuf_base
micc_base
slot
time_type
```

Ping-pong slot and CBUF base are runtime lowering facts. They should be emitted
once into the action stream and checked through API traces.

## Validation

The current safety boundary is API trace equivalence:

```text
operator plan
  -> RuntimeActionPlan API trace
  -> RuntimePlanImage
  -> interpreted image API trace
  -> common executor API trace
```

These traces must match for the effective runtime actions. Replay package and
support binary comparison remain the guardrail for vendor-visible package
material. RISC-V ELF byte identity is not a long-term requirement once the
common executor owns behavior.

## Boundary

Do not put these into RuntimePlanImage:

- graph ops or high-level tensor algebra;
- CSV rows or instance-conf rows;
- app-conf generation rules;
- debug-only dumps;
- vendor macro names as semantic facts.

The image is deliberately small and target-facing. Higher-level facts should
stay in the operator/chip plan and lower into this action stream.
