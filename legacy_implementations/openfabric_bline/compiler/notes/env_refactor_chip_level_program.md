# Env Refactor: Explicit Chip-Level Program

## Core idea

`OperatorEnv` should not directly maintain lower-level PE / Tensor Core / DFU
programs while user ops are being called. Its first responsibility is to record
an explicit chip-level program.

This chip-level program should model more than DTensor operators. At the current
DFU-first stage, the only chip-side tensor declaration we should introduce is an
SRAM/SPM tensor declaration. Before a value becomes a DTensor/tile computation
input, the program should explicitly load it from SRAM.

In particular, SRAM-resident tensors should be first-class program values.
DTensor values should be derived from SRAM loads, not declared as independent
inputs from nowhere.

## Why SRAM tensors matter

The current frontend mostly starts from DTensor inputs and then immediately
projects into PE-local values. That hides an important boundary:

```text
external/runtime input
  -> SRAM tensor
  -> logical DTensor / tile values
  -> compute
  -> SRAM tensor
  -> external/runtime output
```

For the DFU/SimICT workflow, runtime-visible files and buffers are not just an
implementation detail. `input_data`, SPM/SRAM regions, CBUF/MICC, and final
`gpdpu_data`/output checks are part of the observable program boundary.

Therefore the chip-level IR should be able to represent:

```text
declare_sram_tensor(name, shape, dtype, layout, address_space)
load_sram_tensor(src=sram_tensor, dst=dtensor_or_tile_view)
compute(...)
store_sram_tensor(src=dtensor_or_tile_view, dst=sram_tensor)
```

This makes input/output movement explicit instead of implicit in backend-side
base-address or runtime-file generation.

## Suggested chip-level layers

A cleaner `env.generate()` pipeline can start from a chip-level program like:

```text
ChipProgram
  - Tensor declarations
    - SRAM tensors with explicit address-space region and offset
  - Explicit data movement ops
    - load SRAM -> logical tensor / tile view
    - store logical tensor / tile view -> SRAM
  - Compute ops
    - matmul / relu / conv / elementwise
  - Output bindings
```

Then compilation lowers this program step by step:

```text
ChipProgram
  -> ProcessorLogicalProgram
  -> LogicalTileProgram
  -> LogicalFabric / placement plan
  -> DFU physical program
  -> DFU graph / packing / residency
  -> vendor serializers / SimICT bundle
```

The important rule is that these transformations happen after `env.generate()`
starts compilation, not during op construction.

## Frontend API implication

A future API might make SRAM boundaries explicit, for example:

```python
env = ChipEnv("gemm")  # loads the current dfu3500 chip config

x_sram = env.sram_tensor(
    "input_data",
    shape=(512, 256),
    dtype="fp16",
    offset_bytes=0x00000,
)
x = env.load(x_sram, placements=[Shard(0), Replicate()])

w_sram = env.sram_tensor(
    "weight_data",
    shape=(256, 512),
    dtype="fp16",
    offset_bytes=0x40000,
)
w = env.load(w_sram, placements=[Replicate(), Shard(1)])

y = x @ w

out_sram = env.sram_tensor(
    "output_data",
    shape=(512, 512),
    dtype="fp16",
    offset_bytes=0xC0000,
    role="output",
)
env.store(y, out_sram)
env.output("Y", out_sram)
```

This is only a direction note, not an immediate API commitment. The near-term
refactor should first separate chip-level recording from lower-level DFU program
construction.

The frontend user should not declare or fetch a fabric directly. The active
chip config owns the logical fabric/topology facts, and `ChipEnv` loads those
facts when it is constructed. User code describes SRAM tensors, placements, and
ops; the env/chip config decides the fabric those placements live on.

For now, avoid APIs like `env.input(...)` that create DTensor inputs directly.
The explicit shape should be:

```text
env.sram_tensor(...)
env.load(...)
ops...
env.store(...)
env.output(...)
```

Both input and output SRAM tensors should carry an explicit offset/region. For
outputs, first declare the output SRAM tensor region, then store the logical
Tensor/DTensor result into that region. This keeps the runtime-visible memory
boundary explicit before any DFU base-address lowering.

## DFU-first interpretation

This is still a DFU-first project. The goal is not to invent a universal memory
IR for every backend. The goal is to make the customer DFU workflow explicit and
reviewable:

- what tensors are visible at the chip/runtime boundary;
- which SRAM/SPM regions they live in;
- when they are loaded into logical compute space;
- when results are stored back;
- how those declarations later become DFU base addresses, instance tables, and
  SimICT package files.

## Current chip configuration

For now, topology and memory layout can be hardcoded for the active target. The
current chip facts live in:

```text
compiler/gpdpu_compiler/core/dfu3500
```

That module is the small configuration center for DFU3500:

- logical SPMD fabric: currently a `4 x 4` grid;
- physical DFU topology: currently a `4 x 4` PE mesh;
- SRAM/SPM layout: named regions with byte offsets and legacy word32 base
  addresses;
- vendor limits and observed simulator struct sizes;
- current GEMM-oriented tile defaults.

`ChipEnv` may load this config directly as its default chip. The first lowering
step should produce `ProcessorLogicalProgram`, where processor-local DTensor
views reference their source logical DTensors and source chip ops. The next
lowering step should produce `ProcessorTileProgram`, where processor-local
logical ops are decomposed into tile phases, K-block updates, tile refs, and
logical collective bundles. Later, if we need multiple chips, this can grow into
a `ChipConfig` loading layer. The important rule is that chip facts should stay
in the chip config, not leak into random op builders or frontend env state.

## Refactor checkpoint

When refactoring `env`, check for this smell:

```text
user op call mutates both chip-level graph and PE-level program
```

The target shape is:

```text
user op call records only ChipProgram facts
compile pipeline derives PE/DFU program later
```
