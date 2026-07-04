# Information System Minimal Core and Falsifiability

本文是对前几份 note 的一次主动收缩。

理论开始自我生长时有两种可能：

```text
1. 发现了真实结构
2. 获得了万能比喻
```

两者早期看起来很像。区别不在于它能解释多少东西，而在于它能否被压缩回少数原则，并且允许自己失败。

因此本文先停止扩张，尝试把理论压回三个核心对象：

```text
Information System = (State, Rule, Constraint)
```

其它概念都应尽量作为派生概念处理。

## Minimal Core

### State

`State` 描述系统里当前存在什么。

```text
State:
  any information-bearing condition that can affect or be affected by execution
```

包括但不限于：

```text
data
program
control
resource availability
proof / dependency
ownership
visibility
```

这些不是独立本体，只是 state 的不同 kind 或 role。

### Rule

`Rule` 描述什么变化可以发生。

```text
Rule:
  a conditional state transition
```

形式上：

```text
precondition states + guards
  -> produced / consumed / updated states
```

Program、scheduler、runtime、hardware primitive 都可以被看成 rule 或 rule family 的来源，但不是理论之外的外部魔法。

### Constraint

`Constraint` 描述什么变化不能发生，或者哪些状态轨迹非法。

```text
Constraint:
  restriction on states, rules, co-existence, rates, capacities, or trajectories
```

包括：

```text
capacity
mutual exclusion
bandwidth
lifetime
ordering
representation support
interface protocol
```

Capability envelope 是 constraint system 在某个 boundary 和 abstraction 下诱导出的可行域，而不是单独的新对象。

## Derived Concepts

下面这些概念都应能从 `State / Rule / Constraint` 推出。

### Data

```text
Data = State primarily transformed as object
```

### Program

```text
Program = State that selects, enables, stages, or parameterizes rules
```

### Control

```text
Control = State whose value affects future rule selection
```

### Resource

```text
Resource availability = State participating in rule guards and invariants
```

### Scheduler

```text
Scheduler = Rule system transforming ready/control/resource states
```

### Occupancy

```text
Occupancy = lifetime distribution of some state family
```

### Fabric

```text
Fabric = Rule families + constraints over a state space
```

### Capability Envelope

```text
Capability envelope =
  projection of feasible state trajectories to boundary-visible behavior/cost
```

### Compilation

```text
Compilation =
  rule staging and refinement:
    high-level rule space -> lower-level constrained rule system
```

### Projection / Equivalence / Composition

```text
Projection / equivalence / composition =
  operators or relations between information systems,
  not additional core objects
```

If a new concept cannot be derived from `State / Rule / Constraint`, it must justify why the minimal core is insufficient.

## What The Theory Should Not Try To Do

This theory should not be a universal description language with no predictive bite.

Avoid claims like:

```text
Everything is information.
Everything is a reaction.
Everything is schedulable.
```

Those are too broad to be useful.

The useful claim is narrower:

> For computing systems, execution-relevant phenomena should be modelable as
> state trajectories constrained by rule families and capacity/protocol
> invariants; useful performance bounds arise when those trajectories can be
> projected at a chosen boundary.

## Three Brutal Questions

### 1. What can it not represent?

If the answer is “nothing”, the theory is too broad.

A healthier answer:

```text
The theory only represents phenomena that can be expressed as:
  observable or latent execution states,
  conditional transition rules,
  and constraints over trajectories.
```

It does not directly model:

- analog electrical effects unless lifted into state/rule/cost abstractions.
- thermal, power, or reliability effects unless represented as constraints or state variables.
- human/operator behavior unless explicitly modeled as state/rule processes.
- black-box vendor behavior unless exposed through measurable boundary states, rules, or envelopes.

This is a feature. It forces every extra phenomenon to enter through a precise interface.

### 2. What can it predict?

It should predict:

```text
feasibility:
  can this schedule/rule trajectory happen?

necessary bottlenecks:
  which constraints bound the envelope?

trend:
  how does the envelope change when a rule family or constraint changes?

equivalence:
  are two lowerings boundary-equivalent?

staging tradeoff:
  when does reducing runtime choice increase program-state pressure?
```

It should not initially claim:

```text
exact real latency for arbitrary systems
exact energy for arbitrary systems
complete microarchitectural performance without calibration
```

Exact prediction requires a sufficiently detailed state/rule/constraint model and calibrated costs.

### 3. What would falsify it?

The theory is weak or wrong if:

```text
1. Key performance bottlenecks cannot be represented as state, rule, or constraint
   without ad hoc escape hatches.

2. Rule-family differences fail to predict CPU/GPU/DFU behavior differences
   on dense vs irregular workloads.

3. Constraint summaries cannot be composed; every macro envelope must be
   remeasured from scratch.

4. Fusion/unrolling/staging predictions always say "more fusion is better",
   failing to capture program-state or resource-state explosions.

5. The model can explain outcomes only after the fact but cannot predict trend
   under controlled changes.
```

These are not annoyances; they are the intended attack surface.

## Minimal Experimental Commitments

The current theory should be judged by small, concrete tests.

### Test 1: DFU Rule Enablement

Given a tile compute action, model its required states:

```text
A visible
B visible
Accumulator
ProgramRule
TensorCoreAvailable
DependencyReady
```

Prediction:

```text
remove any required state -> rule not enabled
```

If the validator still allows firing, the model is missing a state or constraint.

### Test 2: Fusion Tradeoff

Compare:

```text
GEMM + Store + Load + ReLU
GEMM_ReLU_Fused
```

Prediction:

```text
fused:
  fewer intermediate data states
  shorter SRAM lifetime
  fewer movement rules
  higher program-state specialization pressure
```

If the model cannot find a regime where fusion loses, it is too one-sided.

### Test 3: Rule Family Difference

Compare dense GEMM and pointer chasing under CPU/GPU/DFU rule families.

Prediction:

```text
dense GEMM:
  benefits from bulk object-rule throughput

pointer chasing:
  depends on runtime data->control role switching
```

If all devices look equivalent after changing only FLOPS/bandwidth, RuleFamily is not doing real work.

### Test 4: Constraint Projection

Start with micro constraints:

```text
TensorCoreSlots
SRAMPorts
RouteCredits
ProgramRows
```

Project to macro constraints:

```text
TileUpdateRate
RequiredSRAM
DispatchOccupancy
ProgramCapacityBound
```

If macro constraints must be hand-written, projection is not yet real.

### Test 5: Composition

Compose two devices with a finite link:

```text
IS_A + Link + IS_B -> IS_macro
```

Prediction:

```text
macro envelope is bounded by device envelopes and interface constraints
```

If the composed system must be remodeled from scratch with no reuse, recursive composition has failed.

## Compression Check

A concept should remain in the theory only if it passes at least one check:

```text
1. It is one of State, Rule, Constraint.
2. It is a derived concept with a clear definition in terms of State/Rule/Constraint.
3. It is an operator or relation over information systems needed for recursion.
4. It is an empirical parameter or cost model used by a rule or constraint.
```

Everything else is likely vocabulary growth.

## Current Minimal Thesis

The strongest compressed thesis is:

> A computing system is a constrained information-state transition system:
> live states enable rules, rules transform states, constraints restrict legal
> trajectories, and useful device capabilities are projections of feasible
> trajectories under fabric-specific rule families.

The recursive version is:

> Computing systems scale because internal state trajectories, rule firings, and
> constraints can sometimes be soundly projected into higher-level states,
> macro rules, and macro constraints.

If most earlier notes can be re-derived from these two statements, the theory is becoming real. If not, the extra concepts are probably untrimmed branches.
