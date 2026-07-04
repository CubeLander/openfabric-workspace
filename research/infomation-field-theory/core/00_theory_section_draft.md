# Theory Section Draft: Constrained Information-State Transition Systems

This draft compresses the current theory notes into a paper-style theory section.
It intentionally keeps only three first-level objects:

```text
State
Rule
Constraint
```

All other terms, including data, program, control, resource, scheduler, fabric,
capability envelope, compilation, and fusion, should be derived from these or
treated as operators over these objects.

## 1. Core Model

A computing system is a constrained information-state transition system:

```text
IS = (S, R, C)
```

where:

- `S` is a space of information states.
- `R` is a set of conditional transition rules.
- `C` is a constraint system over states, rules, and trajectories.

An execution is a state trajectory:

```text
S_0 -> S_1 -> ... -> S_T
```

Each transition is produced by firing one or more enabled rules:

```text
enabled(r, S_t, C) = true
S_{t+1} = fire(r, S_t)
```

A rule is enabled only when its required states are present and its constraints
are satisfied. This makes data, program, control, scheduler state, and resource
availability part of the same semantic universe.

## 2. State

A state is any information-bearing condition that can affect or be affected by
execution.

Examples:

```text
TensorTile(A, location=SRAM0)
VisibilityToken(A visible at PE7)
ProgramRow(gemm_update, resident=true)
DispatchSlotFree(slot=2)
TensorCoreBusy(pe=7, until=t+8)
DependencyToken(dep17, ready=true)
```

The labels `data`, `program`, `control`, `resource`, and `proof` are not
separate ontologies. They are roles of information states:

```text
data:
  state primarily transformed as object

program:
  state that selects, enables, stages, or parameterizes rules

control:
  state whose value affects future rule selection

resource availability:
  state participating in rule guards and invariants

proof/dependency:
  state constraining visibility, ordering, ownership, or validity
```

The lifetime of any state is a worldline. Tensor lifetime, program residency,
visibility lifetime, and resource occupancy are all worldline accounting over
different state families.

## 3. Rule

A rule is a conditional state transition:

```text
Rule r = (
  preconditions,
  guards,
  consumed_states,
  read_states,
  produced_states,
  updated_states,
  cost
)
```

Example:

```text
GEMMUpdate:
  preconditions:
    A_tile visible at PE_i
    B_tile visible at PE_i
    Acc state at PE_i
    ProgramRow(gemm_update) resident
    TensorCoreAvailable(PE_i)
  guards:
    dependency token ready
    representation supported
  consumed/updated:
    TensorCoreAvailable -> TensorCoreBusy(until=t+latency)
    Acc -> AccUpdateInFlight
  produced:
    completion obligation
```

Completion is also a rule:

```text
GEMMComplete:
  preconditions:
    TensorCoreBusy(until <= now)
    AccUpdateInFlight
  produced:
    TensorCoreAvailable
    Acc'
```

There is no external magic in this model. If something happens, it should be
representable as a rule firing. A scheduler is therefore also a rule system: it
consumes ready states, resource-availability states, priority states, and
ownership states, then produces dispatch tokens, reserved slots, and updated
queues.

## 4. Constraint

A constraint restricts legal states, rule firings, or trajectories.

Examples:

```text
capacity:
  live SRAM bytes <= capacity

mutual exclusion:
  two rules cannot consume the same TensorCoreAvailable state

rate:
  at most N route transfers per time window

representation:
  this tensor core supports only specific dtype/layout pairs

interface protocol:
  consumer may fire only after visibility token and ownership are established
```

Device differences arise primarily from rule families and constraint families:

```text
CPU:
  strong runtime rule selection and data->control switching;
  constrained by ROB, MSHR, branch prediction, cache/TLB effects.

GPU:
  strong bulk object-rule throughput;
  constrained by divergence, coalescing, occupancy, memory hierarchy.

DFU / spatial accelerator:
  strong staged rule execution;
  constrained by static program capacity, explicit visibility, task slots,
  route endpoints, and weak runtime rule selection.

FPGA:
  rule topology materialized into fabric;
  constrained by area, timing, routing, and control fabric cost.
```

This is deliberately more precise than saying devices differ only by FLOPS,
bandwidth, or cache size.

## 5. Boundary And Observation

The same internal trajectory can be observed through different boundaries. A
boundary defines which states, effects, and costs are externally visible.

For example, an AllReduce can be observed as:

```text
single-device boundary:
  communication-heavy movement

cluster boundary:
  distributed reduction transformation
```

The behavior is not changed; the projection is changed.

## 6. Projection, Equivalence, And Composition

Large systems cannot be analyzed by expanding every low-level rule. Therefore
the theory needs operators over information systems:

```text
project(IS_internal, boundary, abstraction) -> IS_macro
compose(IS_1, IS_2, interface_constraints) -> IS_macro
refine(IS_macro) -> IS_internal
```

where:

```text
IS_internal = (S, R, C)
IS_macro = (S_macro, R_macro, C_macro)
```

These operators map or relate:

```text
internal states      -> macro states
internal rule traces -> macro rules
internal constraints -> macro constraints
```

The macro system is not a fourth kind of object. It is another `(S, R, C)`
system related to the internal system by projection, equivalence, composition,
or refinement.

Example:

```text
Load + Route + MAC + Store
  -> GEMMTileUpdate

GEMMTileUpdate*
  -> GEMMKernel

Attention + MLP + Norm + Residual
  -> TransformerLayer

TransformerLayer* + Sampling
  -> DecodeStep
```

This is the recursive structure that connects:

```text
Instruction -> Kernel -> Layer -> Model -> Service
PE -> Device -> Node -> Cluster -> Datacenter
```

## 7. Soundness Conditions

A projection or composition is not arbitrary compression. It is valid only if it
satisfies at least the following conditions.

### Semantic Soundness

The macro rule must preserve the boundary-visible behavior of the internal
execution:

```text
observe_boundary(execute_internal(S))
  == apply_macro_rule(observe_boundary(S))
```

Conservative over-approximation is allowed only when its direction is explicit.

### Constraint Soundness

Macro constraints must be sound projections of internal constraints:

```text
if macro behavior is feasible:
  there exists an internal feasible trajectory

if macro gives a lower bound:
  no internal trajectory can beat it

if macro gives an upper bound:
  there exists an implementation with that cost
```

### Cost Soundness

Cost projections must be conservative:

```text
lower_bound <= true_cost <= known_upper_bound
```

### Interface Completeness

The projected system must expose all downstream interface states needed for
composition:

```text
representation
location
visibility
ownership
lifetime
consistency
rate/capacity contract
program/control protocol
```

## 8. Capability Envelope

A capability envelope is not a first-class primitive. It is a projection of
feasible state trajectories:

```text
Capability(IS, boundary, abstraction)
  = project(feasible_trajectories(IS), boundary, behavior_and_cost_space)
```

For a target behavior `B`:

```text
min_cost(B, IS)
  = minimal cost of a legal trajectory whose boundary projection realizes B
```

This definition explains why capability is not a single scalar. It is a feasible
region induced by state space, rules, constraints, rule families, and the chosen
boundary.

## 9. Compilation

Compilation is rule staging and refinement:

```text
high-level rule space
  -> staged specialized lower-level rule system
  -> lower runtime selection cost
  -> higher program-state / specialization cost
```

This view unifies:

```text
loop unrolling
fusion
scheduling
route planning
template expansion
vendor program generation
kernel specialization
fabric configuration
```

Fusion is not merely "remove an intermediate tensor". It transforms state
trajectories:

```text
benefit:
  fewer intermediate data states
  shorter lifetimes
  fewer movement rules
  lower runtime rule-firing overhead

cost:
  larger staged program states
  more specialized rules
  tighter constraints
  possible instruction/cache/vendor-table/dispatch pressure
```

## 10. Falsifiability

The theory is not meant to explain everything after the fact. It should fail
when its core objects are insufficient or its summaries are unsound.

It is weakened if:

```text
1. Important bottlenecks cannot be represented as state, rule, or constraint
   without ad hoc escape hatches.

2. Rule-family differences fail to predict dense vs irregular workload trends
   across CPU, GPU, DFU, and FPGA.

3. Macro envelopes cannot be composed; every larger system must be remeasured
   from scratch.

4. Fusion, unrolling, or specialization are always predicted as beneficial,
   ignoring program-state and resource-state pressure.

5. The model explains only completed measurements and cannot predict trend
   under controlled changes.
```

## 11. Thesis

The compressed thesis is:

> A computing system is a constrained information-state transition system:
> live states enable rules, rules transform states, constraints restrict legal
> trajectories, and useful device capabilities are projections of feasible
> trajectories under fabric-specific rule families.

The recursive thesis is:

> Computing systems scale because internal state trajectories, rule firings, and
> constraints can sometimes be soundly projected into higher-level states,
> macro rules, and macro constraints.

These two statements should be sufficient to re-derive the derived concepts:
data, program, control, resource availability, scheduler, occupancy, fabric,
capability envelope, compilation, fusion, and multi-level IR.
