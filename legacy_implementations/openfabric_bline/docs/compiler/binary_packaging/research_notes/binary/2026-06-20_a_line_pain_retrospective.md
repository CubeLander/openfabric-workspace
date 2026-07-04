# A-Line Pain Retrospective: Why The Functional Probe Was So Hard

Date: 2026-06-20

Status: architecture pain note / postmortem

Related note:

```text
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_functional_probe_manual_abi_assumptions.md
```

## Summary

The A-line `functional_maximum_single_app` probe eventually ran through remote
SimICT, and that is a real milestone.  But the path was much harder than the
operator deserved.

The workload was intentionally tiny:

```text
Y = maximum(X, 3.5)
```

Yet we still had to fight:

```text
task count drift
subtask slot ambiguity
terminal flag / successor confusion
legacy template pseudo expansion
operand slot allocation
instance base slot mismatch
fixed MICC/CBUF package capacity
runtime control consistency
manifest/runtime status split
stale payload selection
vendor reference case uncertainty
```

That is not normal compiler complexity for a single lane-wise max.  It is a
signal that the current A-line architecture is too artifact-shaped and too
implicit to keep scaling.

This note intentionally names the pain.  The goal is not to shame earlier work:
the A-line was useful because it proved the remote runtime path and exposed the
right failure modes.  The goal is to stop pretending that the current structure
is a comfortable foundation for more ops.

## Strong Conclusion

The A-line should be treated as a successful probe and a compatibility reference,
not as the main place to continue feature development.

It proved:

```text
OpenFabric current core can generate a runnable non-GEMM functional package.
```

It also proved:

```text
Adding more functionality on this path will keep multiplying hidden ABI debt.
```

If we continue by adding `affine`, `log10`, `reduce`, `broadcast`, and multi-app
semantics directly into the A-line style, we will keep paying the same tax:

```text
one small semantic change
  -> many low-level edits
  -> remote runtime hang
  -> byte diff archaeology
  -> new guard
  -> repeat
```

That loop is not a healthy development model.

## Pain Point 1: Task/Subtask Semantics Were Too Fragile

The probe is one semantic task and two vendor subtasks:

```text
subtask0 = load + local_compute
subtask1 = store/final
```

But the existing path had GEMM-shaped assumptions nearby:

```text
GEMM store -> subtask2
functional probe store -> subtask1
```

This small mismatch is brutal because the runtime failure is not a clear
compiler exception.  It appears as:

```text
MicC rest does not reach zero
PE block DONE/ACK pattern looks suspicious
process_init_msg or wait-finish stalls
```

The underlying semantic error is tiny, but the observable symptom is a runtime
hang.

### What Caused The Pain

Task/subtask identity is currently distributed across multiple layers:

```text
packing node assignment
task row generation
subtask row generation
exeblock embedding
MICC layout
runtime DPU_Kernel_Start task_num
manifest
generated conf.h
generated testarm.c
```

There is no single object that says:

```text
This program has exactly one runnable vendor task.
That task has exactly subtasks [0, 1].
Subtask0 is non-terminal.
Subtask1 is terminal.
```

We added guards after getting burned.  The guards are useful, but the need for
them exposes the architectural weakness.

### Blame

The A-line inherited GEMM as the reference shape.  GEMM has:

```text
prepare / k-stream / store
```

and that accidentally encouraged the idea that vendor subtask slots can be
implicitly reused by convention.  That convention does not survive even the
first non-GEMM probe.

## Pain Point 2: Template Binding Is Not Yet A Real Op Lowering Contract

For `maximum_scalar`, we had to manually preserve:

```text
scalar attr
input ref
output ref
operand role
compute_kind
compute_attrs
```

through:

```text
ChipOp
  -> tile action
  -> TileMicroBlock
  -> TileMicroOp
  -> legacy template binder
  -> LegacyInst rows
```

This worked, but it is not elegant.  It is a wire threaded through several
layers by hand.

### What Caused The Pain

The current path does not yet have a typed executable-role contract such as:

```text
maximum_scalar:
  inputs:
    x: local tile value
    threshold: fp32 immediate
  outputs:
    y: local tile value
  required template:
    ILDMT + IMM + FMAX
  memory:
    no collective
    no app storage
```

Instead, the meaning is reconstructed from:

```text
op name
attrs dict
micro block kind
template-bound instruction list
legacy CSV encoder behavior
```

That is why a simple scalar max felt like soldering a circuit board.

### Blame

This is the direct cost of bootstrapping from a GEMM byte-compat path.  GEMM
compat focused on reproducing vendor artifacts.  That was necessary for the
first runtime breakthrough, but it did not create a general op-template
interface.

## Pain Point 3: Memory Layout / Base Slot Semantics Were Implicit

The worst bug was not a fancy instruction issue.  It was this:

```text
STD used iter_exe_cond = 2
therefore STD read base_addr2
but we had populated the wrong base slot
```

That is a very small field-level mistake.  But it can stop completion in a way
that looks like execution or control-plane failure.

### What Caused The Pain

The memory op did not explicitly carry:

```text
storage region
base slot
offset unit
direction
subtask lifetime
```

The instance table was filled by mode-specific compatibility logic:

```text
if legacy_template_compat and local_subtask_index == ...
```

That is fragile.  It makes memory correctness depend on matching a template's
hidden `iter_exe_cond`.

### Blame

We were still thinking in terms of “make the component look vendor-like” instead
of “derive memory table rows from memory operations.”  Byte-level compatibility
helped us debug, but it also tempted us to copy field shapes without a real
source-of-truth model.

## Pain Point 4: Runtime Package Size Is A Hardware/Profile Fact, Not A Local Optimization

We were tempted by short generated files:

```text
tasks_conf_info_file.bin    = 120
subtasks_conf_info_file.bin = 2130624
micc_file.bin               = 2130744
```

But the runtime path expects the fixed package layout:

```text
tasks_conf_info_file.bin    = 480
subtasks_conf_info_file.bin = 8522496
micc_file.bin               = 8522976
```

### What Caused The Pain

The simulator/runtime uses fixed capacity package layout, while local component
logic can easily generate “only active rows.”  Both look plausible until runtime
preload/transfer behavior disagrees.

### Blame

The DFU3500 runtime profile facts were not centralized early enough as hard
package constraints.  We had constants and evidence, but they were not yet
treated as an unbreakable profile contract.

## Pain Point 5: Validation Truth Was Split Across Too Many Statuses

At one point we had:

```text
program_status:
  runtime_validation_blocked

program_bin_rows.validation:
  component_serializers_not_started

program_bin_components.validation:
  package_bytes_emitted = true

MANIFEST.txt:
  runtime_runnable = 1
```

That is too many mouths speaking at once.

### What Caused The Pain

The pipeline evolved in layers:

```text
row plans first
component serializers later
runtime-control assets later
manifest gates later
```

Each layer kept its own status vocabulary.  The vocabulary did not get retired
or unified when the lower layer became real.

### Blame

We let diagnostic strings become quasi-contracts.  They were useful while the
pipeline was structural-smoke-only, but after component emission became real,
some of those strings became stale lies.

## Pain Point 6: Stale Payload Selection Was An Embarrassing But Predictable Failure

We lost time because the payload being run was not the payload we thought we had
rebuilt.

This should never be possible.

### What Caused The Pain

The validation workflow had multiple directories with similar meanings:

```text
payloads/<case>/
run_payload_selection/<case>/
temporary generated payloads
remote uploaded payload
```

Without an entrypoint guard, it was easy to validate one tree and package
another.

### Blame

The workflow relied on human discipline in a remote/OCR-heavy loop.  That is the
wrong place to rely on discipline.  The guard should have existed as soon as
`run.sh` started selecting generated payloads.

The new guard is good:

```text
compiler/tools/check_partner_validation_entrypoint.py
```

But the fact that it caught a real class of mistake means the workflow was
previously under-guarded.

## Pain Point 7: Vendor Reference Cases Are Useful But Dangerous

The hand-built vendor-like case helped compare:

```text
insts_file.bin
exeblock_conf_info_file.bin
tasks_conf_info_file.bin
subtasks_conf_info_file.bin
instance_conf_info_file.bin
```

But it also almost misled us.

### What Caused The Pain

A vendor-generated component can be byte-useful without being a perfect runtime
oracle for our generated package.  If the copied vendor case was made with a
slightly wrong config, then copying its metadata copies its mistake.

### Blame

We were forced into artifact archaeology because the ABI model was incomplete.
Artifact archaeology is sometimes necessary, but it must be treated as evidence,
not law.

## Pain Point 8: `app_name=CASE/softmax_1` Is A Smell

The functional maximum payload still says:

```text
app_name=CASE/softmax_1
```

That is a runtime shell hook, not semantic truth.

### What Caused The Pain

The validation harness still expects vendor-style case names.  Generated
OpenFabric runtime bundles are not yet fully first-class in the remote workflow.

### Blame

This is integration debt.  It is not fatal, but it keeps semantic names and
runtime staging names tangled together.  That confusion showed up directly when
we discussed whether we were using vendor softmax or OpenFabric current core.

## Pain Point 9: A-Line Encourages Cross-Layer Patching

The A-line made it too easy to patch a field where the symptom appeared:

```text
instruction row looks wrong -> patch encoder
runtime hangs -> patch subtask rows
store bad -> patch instance table
manifest wrong -> patch packaging
```

Some of those patches were correct.  But the workflow itself encourages local
fixes instead of asking:

```text
Which IR object should have owned this semantic fact?
```

### What Caused The Pain

The path lacks strong intermediate contracts for:

```text
task plan
memory op layout
executable role
template binding
runtime package plan
runtime control plan
```

So facts drift downward until the binary serializer has to know too much.

### Blame

This is the cost of growing the compiler from a runnable GEMM compatibility
path.  Compatibility paths naturally pull semantics downward because the first
observable target is a byte blob.

## Pain Point 10: Remote Debugging Magnifies Every Implicit Assumption

The remote loop is slow:

```text
build locally
package
upload
run on arch-13
OCR / copy logs back
infer hang reason
repeat
```

In that environment, every implicit assumption becomes expensive.

### What Caused The Pain

Runtime hangs rarely identify the true layer:

```text
wrong task count
wrong MICC size
wrong base slot
wrong terminal subtask
wrong instruction encoding
wrong runtime control
```

can all look like:

```text
rest(1)
timeout
process_init_msg stuck
Kernel_Wait_Finish never returns
```

### Blame

We did not have enough local structural guards before remote execution.  The
later guards helped a lot.  They should be considered mandatory infrastructure,
not nice-to-have tests.

## What A-Line Did Right

This note is deliberately harsh, but the A-line was not wasted.

It gave us:

```text
1. A known-runnable non-GEMM current-core probe.
2. A generated RISC-V control path.
3. Runtime manifest gates that distinguish runnable from structural.
4. Guard scripts that prevent stale-payload and task-count mistakes.
5. Concrete evidence that template/task/memory layout debt is real.
6. A minimal vendor-side reference case for byte-level comparison.
```

That is valuable.  The point is that the A-line should now be frozen as a
learning artifact and compatibility baseline, not stretched into a full compiler
architecture.

## What We Should Stop Doing

Stop adding features by extending compatibility conditionals like:

```text
if vendor_inst_mode == legacy_template_compat:
if local_subtask_index in {1, 2}:
if block_kind == tile_store and task_assignment is None:
```

Stop treating `attrs` dictionaries as a long-distance semantic transport.

Stop making runtime upload decisions without a fresh-build comparison guard.

Stop treating vendor-generated byte blobs as complete semantic proof.

Stop using `program_status` strings as authoritative runtime readiness.

Stop letting memory base slots be inferred indirectly from template rows.

## What The Next Architecture Must Make Explicit

The next serious path should have first-class objects for:

```text
Task / soft-processor plan:
  task count
  task axis
  subtask roles
  terminal order

Executable role:
  operation kind
  input/output value refs
  immediate attrs
  legal template families

Memory op layout:
  storage region
  base slot
  byte offset
  instance table row ownership

Template binding:
  typed operand contract
  fixed small templates first
  fail-closed unsupported ops

Runtime package:
  fixed profile capacities
  component file readiness
  package byte layout

Runtime control:
  DMA groups
  launch task count
  output collection
  reference comparison metadata
```

Each of these should be inspectable before binary serialization.

## Practical Rule For Future Work

If adding one simple op requires changing more than one or two of these layers:

```text
task/subtask assignment
instance base table
legacy template encoder
program serializer
runtime control generator
manifest gates
```

then the implementation is probably extending A-line debt rather than building
the right abstraction.

That pain should be treated as a design signal, not as something to heroically
push through.

## Final Take

The A-line succeeded because we were stubborn enough to chase every byte and
runtime field.  It also showed exactly why that style cannot be the future.

The honest conclusion is:

```text
A-line is a runnable compatibility bridge.
Bigger operator work needs a cleaner semantic lowering path.
```

That is not a retreat.  It is the project learning where the real floor is.
