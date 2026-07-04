# Falsification Cases

This file is a deliberate attack surface for the theory. The goal is to prevent
the framework from becoming a universal metaphor.

The minimal theory is:

```text
Information System = (State, Rule, Constraint)
```

The theory should fail loudly when state, rule, constraint, projection, or equivalence is
missing or too weak.

## Case 1: Data Exists But Visibility Is Missing

Scenario:

```text
A_tile exists at PE_0
GEMMUpdate wants A_tile at PE_7
no route endpoint or visibility token at PE_7
```

Expected prediction:

```text
GEMMUpdate not enabled
```

Theory failure:

```text
The model treats value existence as sufficient for consumption.
```

Missing concept:

```text
visibility state / ownership state / route endpoint state
```

## Case 2: Data Exists But Program State Is Missing

Scenario:

```text
A_tile visible
B_tile visible
Acc visible
no resident instruction / vendor task row / dispatch descriptor
```

Expected prediction:

```text
compute rule not enabled
```

Theory failure:

```text
data automatically computes without program-as-state.
```

Missing concept:

```text
program state as rule-enabling reactant
```

## Case 3: Resource Availability Is Treated As External Magic

Scenario:

```text
all data and program states exist
TensorCoreAvailable missing
```

Expected prediction:

```text
GEMMUpdate not enabled
```

Theory failure:

```text
resource availability is outside the field, so the model cannot explain stalls.
```

Missing concept:

```text
resource-availability state / state invariant
```

## Case 4: Fusion Is Always Predicted Better

Scenario:

```text
compare:
  GEMM + Store + Load + ReLU
  GEMM_ReLU_Fused

increase:
  unroll factor
  fused post-op count
  vendor descriptor size
```

Expected prediction:

```text
fusion initially helps by reducing intermediate states,
then fails or loses when program-state / dispatch / register / vendor-table
constraints dominate.
```

Theory failure:

```text
model only counts data movement and always prefers fusion.
```

Missing concept:

```text
program-state constraint / staged-rule cost / resource-state occupancy
```

## Case 5: Unroll Is Always Predicted Better

Scenario:

```text
looped schedule vs partially unrolled vs fully unrolled
```

Expected prediction:

```text
unroll trades runtime rule-selection cost for program-state growth.
```

Theory failure:

```text
model ignores instruction cache, vendor program rows, code size, dispatch slots.
```

Missing concept:

```text
rule staging cost
```

## Case 6: CPU/GPU/DFU Differ Only By FLOPS And Bandwidth

Scenario:

```text
workloads:
  dense GEMM
  pointer chasing
  sparse gather
```

Expected prediction:

```text
dense GEMM:
  GPU/DFU benefit from bulk object-rule throughput

pointer chasing:
  CPU benefits from runtime data->control role switching

sparse gather:
  depends on metadata/control movement and rule-selection constraints
```

Theory failure:

```text
model cannot explain why irregular path selection hurts GPU/DFU.
```

Missing concept:

```text
rule family / runtime control constraint
```

## Case 7: Macro Envelope Cannot Be Composed

Scenario:

```text
DeviceA + finite link + DeviceB
```

Expected prediction:

```text
macro envelope bounded by DeviceA envelope, DeviceB envelope, and interface
constraints.
```

Theory failure:

```text
must reopen and remodel all micro rules from scratch.
```

Missing concept:

```text
sound projection / interface constraint / macro constraint projection
```

## Case 8: Macro Rule Has No Refinement

Scenario:

```text
declare macro rule:
  GEMMTileUpdate(A, B, Acc) -> Acc'

but no legal internal trajectory satisfies route, visibility, compute, and
resource constraints.
```

Expected prediction:

```text
macro rule invalid
```

Theory failure:

```text
macro abstraction is accepted without refinement witness.
```

Missing concept:

```text
refinement / semantic soundness / constraint soundness
```

## Case 9: Constraint Projection Is Hand-Written

Scenario:

```text
micro constraints:
  TensorCoreSlots = 16
  SRAMPorts = 4
  LinkCredits = 2

macro claim:
  TileUpdateRate <= X
```

Expected prediction:

```text
macro constraint comes from projection or conservative derivation.
```

Theory failure:

```text
X is hand-written with no relation to micro constraints.
```

Missing concept:

```text
constraint projection
```

## Case 10: Boundary Information Is Incomplete

Scenario:

```text
macro projection exposes value but hides:
  representation
  location
  visibility
  ownership
  consistency
```

Expected prediction:

```text
downstream composition invalid or under-specified.
```

Theory failure:

```text
macro rules compose despite missing interface states.
```

Missing concept:

```text
interface completeness
```

## Case 11: Black-Box Vendor Behavior

Scenario:

```text
vendor simulator has hidden queue or descriptor constraint
not exposed in state/rule/constraint model
```

Expected prediction:

```text
model cannot claim exact bound; hidden behavior must be represented as measured
boundary envelope or unknown constraint.
```

Theory failure:

```text
model pretends to predict exact behavior without exposed states or calibration.
```

Missing concept:

```text
boundary measurement / uncertainty / calibrated cost model
```

## Case 12: Exact Latency Is Claimed Without Cost Calibration

Scenario:

```text
model has qualitative rules but no calibrated latency/cost parameters
```

Expected prediction:

```text
model may predict feasibility, bottleneck class, and trend,
but not exact latency.
```

Theory failure:

```text
paper claims precise performance prediction without calibrated costs.
```

Missing concept:

```text
cost model scope
```

## Case 13: State Explosion Makes Projection Useless

Scenario:

```text
projection is as detailed as micro execution,
so upper layers cannot use it.
```

Expected prediction:

```text
projection should preserve only boundary-relevant state and envelope information.
```

Theory failure:

```text
no abstraction benefit; every layer replays all micro states.
```

Missing concept:

```text
abstraction choice / coarse-graining
```

## Case 14: Projection Is Too Coarse To Predict

Scenario:

```text
projection exposes only:
  output value

hides:
  cost
  lifetime
  resource occupancy
  program-state pressure
```

Expected prediction:

```text
projection valid for functional semantics only, not performance envelope.
```

Theory failure:

```text
uses functional projection to make performance claims.
```

Missing concept:

```text
abstraction-specific soundness
```

## Use In Review

Any proposed extension should answer:

```text
Which falsification cases does it address?
Which cases does it still fail?
Does it add a core concept, or derive from State/Rule/Constraint?
Can it predict a controlled trend before measurement?
```

If the answer is unclear, the extension is probably vocabulary growth.
