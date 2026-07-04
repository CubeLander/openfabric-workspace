# DFU GEMM Tile Case: Minimal Formalization

This note attacks the theory with a concrete DFU-first case:

```text
GEMM tile update
```

The goal is not to model all DFU behavior. The goal is to force the minimal
core to explain one real scheduling unit using only:

```text
State
Rule
Constraint
```

## Boundary

Choose a tile-level boundary:

```text
input boundary states:
  A_tile(m, k) available at source or visible at consumer
  B_tile(k, n) available at source or visible at consumer
  Acc(m, n, k-1) at consumer PE

output boundary state:
  Acc(m, n, k) at consumer PE
```

At this boundary, internal route steps, SRAM port usage, vendor descriptors, and
temporary visibility endpoints may be hidden only if the projection preserves their
semantic and cost effects.

## Required States

A legal GEMM tile update rule requires more than tensors.

### Object States

```text
A_tile(m, k, representation, location)
B_tile(k, n, representation, location)
Acc(m, n, k-1, location=consumer_pe)
```

### Visibility States

```text
A_visible_at(consumer_pe)
B_visible_at(consumer_pe)
```

These may be produced by local SRAM load, route/copy, or previous staged
materialization. They are separate from the existence of A/B as values.

### Program States

```text
ProgramRow(gemm_update, resident=true)
LoopDescriptor(k_loop, current=k)
VendorTaskProjection(task_id, subtask_role_map)
```

These states select and parameterize the hardware rule. Without them, A and B do
not multiply themselves.

### Control / Proof States

```text
DependencyToken(A_ready)
DependencyToken(B_ready)
DependencyToken(Acc_ready)
OwnershipToken(consumer_pe owns Acc update)
```

### Resource-Availability States

These are ordinary information states, not an external resource model:

```text
TensorCoreAvailable(consumer_pe)
SRAMReadPortAvailable(bank)
DispatchSlotAvailable(consumer_pe)
RouteCredit(edge)              # if route is internal to this macro rule
ProgramRowCapacityAvailable    # if rule staging is being validated
```

## Micro Rules

### Load / Materialize A

```text
Rule LoadA:
  preconditions:
    A_sram_state
    ProgramRow(load_or_route_A)
    SRAMReadPortAvailable
  guards:
    address/offset valid
    layout supported
  produces:
    A_visible_at(consumer_pe)
  updates:
    SRAMReadPortAvailable -> SRAMReadPortBusy(until=t+latency)
```

### Load / Materialize B

```text
Rule LoadB:
  preconditions:
    B_sram_state
    ProgramRow(load_or_route_B)
    SRAMReadPortAvailable
  guards:
    address/offset valid
    layout supported
  produces:
    B_visible_at(consumer_pe)
  updates:
    SRAMReadPortAvailable -> SRAMReadPortBusy(until=t+latency)
```

### Route A/B

If A or B is not local, visibility is produced by route rules:

```text
Rule RouteOperand:
  preconditions:
    source_tile_visible_at(sender_pe)
    ProgramRow(copy_or_copyt)
    RouteCredit(sender_pe -> receiver_pe)
    EndpointCapacity(receiver_pe)
  produces:
    operand_visible_at(receiver_pe)
  updates:
    RouteCredit -> RouteInFlight
```

Important DFU semantic point:

```text
the executable route action lives on the sender,
but the produced visibility endpoint belongs to the receiver.
```

The model must represent this sender/receiver split.

### GEMM Update

```text
Rule GEMMUpdate:
  preconditions:
    A_visible_at(consumer_pe)
    B_visible_at(consumer_pe)
    Acc(m, n, k-1)
    ProgramRow(gemm_update)
    LoopDescriptor(k)
    TensorCoreAvailable(consumer_pe)
    DependencyToken(A_ready)
    DependencyToken(B_ready)
    DependencyToken(Acc_ready)
  guards:
    dtype/layout supported
    ownership permits Acc update
  updates:
    TensorCoreAvailable -> TensorCoreBusy(until=t+compute_latency)
    Acc(m, n, k-1) -> AccUpdateInFlight(m, n, k)
```

### GEMM Complete

```text
Rule GEMMComplete:
  preconditions:
    TensorCoreBusy(until <= now)
    AccUpdateInFlight(m, n, k)
  produces:
    TensorCoreAvailable(consumer_pe)
    Acc(m, n, k)
```

## Constraints

### Visibility Constraint

```text
GEMMUpdate cannot fire unless:
  A_visible_at(consumer_pe)
  B_visible_at(consumer_pe)
```

Tensor existence at a source PE is insufficient.

### Accumulator-Carry Constraint

```text
Acc(m, n, k) depends on Acc(m, n, k-1)
```

K-loop iterations cannot be reordered unless the alternative rule proves an
equivalent reduction/association transformation.

### Resource-State Invariant

```text
TensorCoreAvailable + TensorCoreBusy = TensorCoreTotal
SRAMReadPortAvailable + SRAMReadPortBusy = SRAMReadPortTotal
RouteCredit + RouteInFlight = RouteCreditTotal
```

These are state invariants over ordinary information states.

### Program-State Constraint

```text
resident program rows <= vendor program capacity
dispatch slots used <= dispatch capacity
```

Fusion, unroll, or staging may fail here even if data movement decreases.

### Interface Constraint

The macro tile update can hide internal route/load details only if it exposes:

```text
Acc(m, n, k) location
representation/layout
ownership
visibility
cost projection
dependencies discharged
```

## Macro Rule As Projected Equivalent System

The internal trajectory:

```text
Load/Route A
Load/Route B
GEMMUpdate
GEMMComplete
```

may be projected as:

```text
MacroRule GEMMTileUpdate:
  preconditions:
    A_tile(m, k) reachable or visible
    B_tile(k, n) reachable or visible
    Acc(m, n, k-1)
    staged program/control states
    required resource-state envelope
  effects:
    Acc(m, n, k)
  cost_projection:
    route_cost(A) + route_cost(B) + compute_cost + program/dispatch cost
  constraints:
    visibility before compute
    accumulator carry
    resource capacity
    program capacity
```

This is not a new fourth object. `GEMMTileUpdate` is another rule in a projected
`(State, Rule, Constraint)` system. Its validity comes from equivalence to at
least one legal internal trajectory and from conservative projection of internal
constraints.

## Soundness Obligations

### State Closure

Internal states such as:

```text
RouteInFlight
SRAMReadPortBusy
A_visible_temp
B_visible_temp
TensorCoreBusy
```

must be consumed, hidden, or projected into macro states. If a downstream rule needs them, they
must be exposed.

### Constraint Closure

The macro rule is valid only if internal constraints are either discharged or
projected:

```text
route credits available
SRAM ports available
program row resident
dependency tokens ready
```

### Cost Closure

The macro cost must conservatively account for:

```text
operand materialization / route
compute latency
program-state residency
dispatch occupancy
resource-state occupancy
```

## Minimal Falsification Tests

### Missing Visibility

Remove:

```text
A_visible_at(consumer_pe)
```

Prediction:

```text
GEMMUpdate not enabled
```

If the model allows update because A exists somewhere, it fails.

### Missing Program Row

Remove:

```text
ProgramRow(gemm_update)
```

Prediction:

```text
GEMMUpdate not enabled
```

If data alone enables compute, program-as-state is not modeled.

### Missing Tensor Core State

Remove:

```text
TensorCoreAvailable
```

Prediction:

```text
GEMMUpdate not enabled
```

If resource availability is external magic, the model fails.

### Program Capacity Explosion

Increase fusion/unroll until:

```text
resident program rows > vendor program capacity
```

Prediction:

```text
staged macro rule infeasible
```

If the model still predicts fusion is better, it misses program-state
constraints.

### Route Endpoint Confusion

Represent COPY as receiver-side execution only.

Prediction:

```text
sender/receiver ownership and visibility constraints become unsound
```

If the model cannot distinguish sender action from receiver endpoint, it is too
coarse for DFU.

## Connection To Existing OpenFabric IR

Current IR concepts can map into this case:

```text
LogicalRouteEdge:
  route-level visibility rule family

TileRouteAction:
  sender-side route rule

TileVisibilityRef:
  receiver-side visibility state

TileComputeAction:
  GEMMUpdate rule instance

TileDependency:
  proof/control state over legal ordering

VendorTaskProjection:
  staged program state
```

This mapping should be implemented first as a read-only extractor. It should not
mutate `ChipEnv` or op-time frontend graph construction.
