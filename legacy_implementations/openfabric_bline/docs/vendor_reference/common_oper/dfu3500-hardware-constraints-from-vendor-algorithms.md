# DFU3500 Hardware Constraints Inferred from Vendor Algorithms

Date: 2026-06-16

Status: inferred constraints / compiler design standard

Scope: DFU3500 / SimICT / `gemm_template_fusion` binary compatibility.

This note extracts the hardware constraints hidden behind vendor `common_oper`
algorithms.  The goal is to separate three things:

```text
1. Real hardware / simulator ABI constraints
2. Vendor assembler algorithms that satisfy those constraints
3. Historical padding / hand-filled compatibility details
```

The first two categories should become OpenFabric compiler standards.  The
third category should stay isolated in the DFU3500 vendor profile / serializer.

## 1. Can “mostly similar” binaries pass the simulator?

Maybe, but we should not assume so.

Current state is encouraging:

```text
MICC/control table: matched in the latest remote config comparison
CBUF/component layout: matched
CBUF/inst stream: mostly matched, remaining diffs are structured
```

However, CBUF `inst_t` operand fields are not harmless metadata.  They are PE
local memory addresses:

```text
src_operands_idx[]
dst_operands_idx[]
dst_pes_pos[]
dst_blocks_idx[]
```

If a remaining diff is in an inactive row, padding field, or legacy count field
that the simulator ignores, it may still pass.  If it is in an active
`HMMAL`/`COPY`/`LDN` operand or route field, it can produce:

```text
wrong data
dead route
operand overwrite
HMMA memory out of range
```

So the right criterion is not:

```text
binary diff is small
```

but:

```text
all active instruction/resource fields consumed by PE/MICC are semantically valid
```

This is why we keep chasing algorithmic parity instead of hard-patching bytes.

## 2. Fixed hardware/ABI capacities

These are hard limits implied by SimICT data structures and CBUF/MICC images.

| Resource | Constraint | Compiler implication |
| --- | --- | --- |
| PE mesh | 16 PEs, logically 4x4 | placement and route lowering target fixed PE coordinates |
| inst memory | 4,352 `inst_t` rows / PE | per-PE instruction layout must capacity-check before serialization |
| exeBlock table | 32 blocks / PE | micro-block packing must not create too many PE-local executable blocks |
| operand RAM | 1,536 operand slots / PE | operand allocation and live range reuse are mandatory |
| operand banks | 12 banks * 128 slots | allocator must account for bank layout / conflict pressure |
| task rows | 4 task rows | current GEMM 4-task profile maps to fixed task slots |
| subtask rows | 8 subtask slots / task | subtask global row = `task * 8 + local_subtask` |
| instance table | 4 * 8 * 2048 rows | physical instance rows are fixed-window, not compact |
| `inst_t` row | 304 bytes | CBUF inst section must be PE-major and fixed-width |
| `exeBlock` row | 520 bytes | CBUF block section must be PE-major and fixed-width |
| instance row | 32 bytes | `base_addr[4]` rows are fixed-width |
| task row | 120 bytes | MICC task rows are fixed-width |
| subtask row | 266,328 bytes | each subtask row embeds a block table |

These sizes are not optimization choices.  They are ABI facts consumed by the
runtime / DMA / MICC / PE simulator stack.

## 3. PE-local operand RAM is a real address space

The most important hardware fact behind the remaining CBUF diffs is:

```text
operand index is PE-local memory address
```

Every PE has its own `0..1535` operand namespace.  The same operand index on two
PEs does not refer to the same data.

Therefore the compiler must track:

```text
(task, PE, symbolic_tag) -> operand index
```

not just:

```text
symbolic_tag -> operand index
```

This explains several vendor behaviors:

- `Task_Resource` is effectively task/PE scoped.
- COPY/COPYT destination operand must be looked up in the receiver/child PE
  resource map.
- A sender can execute a COPY instruction, but the destination operand index
  belongs to the receiver PE's operand RAM.

## 4. Operand bank layout is not arbitrary

The recovered layout function is:

```text
layout_operand_idx(logical_idx)
  = (logical_idx % 12) * 128 + logical_idx / 12
```

This maps consecutive logical operands across the 12 banks:

```text
logical 0 -> bank 0 line 0
logical 1 -> bank 1 line 0
logical 2 -> bank 2 line 0
...
logical 11 -> bank 11 line 0
logical 12 -> bank 0 line 1
```

Compiler implication:

```text
Do not allocate operand slots as plain contiguous integers.
```

The vendor allocator is spreading first-use operands across banks.  The likely
hardware reason is to reduce multi-operand bank conflicts for instructions such
as `HMMAL`, which read multiple operands and write one destination.

This also explains `±1` byte/field drift:

```text
if first-use order differs by one logical allocation,
layout_operand_idx shifts every later physical operand in a structured way
```

## 5. Tensor pseudo operands use lane-strided layout

Pseudo tensor instructions such as `HLDT`, `HSTT`, and `COPYT` are not simple
single-slot loads/stores.  Vendor behavior allocates a base operand and expands
lanes as:

```text
lane_operand = base_operand + lane * 128
```

This means a logical tensor strip spans corresponding lines across operand RAM
banks.  The inferred hardware reason is that tensor/SIMD operations interpret
multiple 1024-bit chunks as one wider logical operand.

Compiler implication:

```text
Tensor tile materialization must allocate a base with group/lane structure,
not independent scalar operand slots.
```

This is the reason many remaining diffs appear as:

```text
delta = 512
```

because `512 = 4 banks * 128 slots`, i.e. one operand RAM group.

## 6. LD / CAL / FLOW / ST are execution-stage boundaries

Vendor graph mapping processes stages in this order:

```text
LD -> CAL -> FLOW -> ST
```

This is not merely pretty printing.  It reflects PE execution components:

- `LD`: materialize data from SPM/instance/base address into operand RAM.
- `CAL`: compute using PE-local operands / RX / tensor pipeline.
- `FLOW`: COPY/COPYT route and cross-PE forwarding.
- `ST`: write results back to SPM/output region.

Compiler implications:

1. Stage order affects operand first-use allocation.
2. ExeBlock stage PC ranges must remain consistent with instruction layout.
3. Route/compute/store micro-blocks should not be merged if that hides stage
   ownership.
4. A tile-loop body can repeat as one subtask, but its internal stage order must
   still be preserved.

This is why `TileMicroBlock` was necessary: a mixed route+compute block causes
false predecessor/successor pressure and wrong stage attribution.

## 7. Route is sender-push but receiver-owned at the destination

The vendor route behavior is subtle:

```text
COPY/COPYT instruction executes on the sender/forwarding PE
destination PE/block is patched from the child/consumer graph node
destination operand is retrieved from the child/consumer TaskResource
```

So route has two ownership axes:

| Aspect | Owner |
| --- | --- |
| executable instruction | sender / `execution_processor` |
| destination visibility | receiver / endpoint processor |
| destination operand index | receiver TaskResource |
| route dependency chain | hop-by-hop along route path |
| compute dependency | local endpoint visibility only |

Compiler implications:

- Do not put the whole route path inside the consumer compute block.
- Do not let compute depend on every route hop directly.
- Route hop dependencies should form a chain.
- Compute should consume the final local visibility endpoint.
- COPY dst operand must be patched from the receiver resource map.

This is a hardware constraint because PE operand RAM is local and route data is
materialized into the receiver's local operand space.

## 8. Subtask instance repeat is the hardware loop

Vendor 原始文档把这件事称为“硬件循环”：当 PE 指令缓冲区或寄存器/operand
资源不够时，不把所有循环展开成更多指令，而是在 PE 上部署一份指令模板，让它重复
执行。每次重复执行叫一次 `instance`。

K-loop folding should use vendor subtask instance repeat:

```text
subtask2.instances_amount = K
```

not:

```text
compute_k0 -> compute_k1 -> compute_k2 -> ...
```

The repeated body is a subtask body template.  Each instance receives its own
`base_addr[4]` row from the instance table.

Compiler implications:

- K recurrence is carried state, not vendor graph fan-in/fan-out.
- Store/finalize should depend on loop exit semantics or subtask order, not on
  every expanded K instance.
- Loop-variant data visibility must be inside the repeated body unless proven
  invariant and live across the loop.
- Instruction template must be instance-isomorphic; only instance/base/offset
  bindings may vary.

This explains why folded VendorABI reduced expanded K rows while keeping runtime
semantics.

### 8.1 Instance base address table

原始文档里的表：

```text
4 task * 8 subtask * 2048 instance entries
each entry = base_addr0, base_addr1, base_addr2, base_addr3
```

对应的源码结构是 `instance_conf_info_t`：

```text
uint64_t base_addr[MAX_BASE_ADDR_PER_SUBTASK]
```

也就是每个 instance 表项有 4 个 base address。PE 指令自身带立即数 offset，
最终访存地址是：

```text
addr = base_addr[base_addr_idx] + offset
```

因此：

- 不同 `instance` 通过不同 base row 访问不同数组区域；
- 不同 PE 通过指令中的不同 offset 访问同一 instance 区域里的不同元素；
- PE 并行来自 PE-local offset / tile placement；
- instance 串行来自 subtask repeat / base row 递进。

For GEMM this maps naturally to:

```text
subtask1: instance_times = 1  // prepare C
subtask2: instance_times = 4  // stream K blocks
subtask3: instance_times = 1  // store C
```

The four `subtask2` instances select four A/B base rows; the instruction offsets
inside each PE select the local tile element handled by that PE.

## 9. Instance rows have two coordinate systems

Vendor behavior split:

```text
MICC control field:
  instances_conf_mem_based_addr is compact in active execution order

CBUF physical instance file:
  row = task * 8 * 2048 + local_subtask * 2048 + instance
```

Compiler implication:

```text
Never derive instances_conf_mem_based_addr directly from physical instance row.
```

The likely hardware reason is that MICC has a compact pointer/offset for current
execution, while the CBUF-side file format reserves a fixed physical table for
all task/subtask/instance slots.

This is exactly the kind of rule that belongs in the DFU3500 vendor profile, not
in generic compiler IR.

## 10. ExeBlock count and dependency pressure are real constraints

Vendor limits:

```text
32 exeBlocks / PE
512 total exeBlock rows
```

Earlier IR shapes generated false predecessor/successor pressure because route,
forward, and compute were coalesced too early.  Splitting them into
`TileMicroBlock` reduced that pressure.

Compiler implications:

- The tile level should decide executable micro-block boundaries.
- Later ASM/VendorABI stages should not rediscover route/compute roles.
- If micro-block count grows too much, coalescing must preserve stage ownership
  and dependency semantics.

This is a hardware/simulator scheduling constraint, not just an aesthetic IR
choice.

## 11. Base address slots are scarce and instance-scoped

`instance_conf_info_t` has:

```text
base_addr[4]
```

The current interpretation is subtask-instance scoped, not PE-local.  All PE
instructions in that subtask instance must derive addresses from the same four
base slots plus static instruction offsets / PE-local layout.

Compiler implications:

- Folded loops can vary addresses through instance rows only if the needed
  variation fits into these four base slots plus immediate offsets.
- Do not assume every PE or every exeBlock gets independent base address slots.
- If a loop-variant field cannot be expressed through instance base slots or
  proven parametric fields, that loop body cannot be folded safely.

This is one of the core binary serializer gates.

## 12. Hardware constraints behind recent OpenFabric fixes

| OpenFabric fix | Hidden hardware/vendor constraint |
| --- | --- |
| Full CBUF/MICC fixed-size emit | runtime DMA/MICC expects fixed component offsets |
| PE-major inst/block layout | PE fetches its own local `inst_list` / block table |
| 4 task * 8 subtask windows | MICC task table uses fixed task/subtask row slots |
| Physical 65536 instance rows | instance CBUF table is fixed-window even if active offsets are compact |
| Folded K-loop VendorABI | subtask instance repeat is the hardware loop primitive |
| TileMicroBlock split | route/compute/store map to different execution-stage/resource semantics |
| COPY receiver patching | destination operand lives in receiver PE operand RAM |
| Seed table / TaskResource work | operand allocation is first-use, task/PE-local, bank-aware |
| `BET` group correction | tensor operands live in group-structured operand RAM |
| Stage count / PC normalization | exeBlock stage ranges and simulator control fields have ABI-specific meaning |

## 13. What should become compiler standards

### 13.1 Placement and routing

- The compiler must represent a 4x4 processor topology for DFU3500.
- Route actions must be sender-executed but receiver-materialized.
- Route dependencies should follow route hops; compute sees only endpoint
  visibility.

### 13.2 Tile and loop lowering

- K loops should lower to closed repeated subtask bodies when the body is
  instance-isomorphic.
- Loop-variant loads/routes belong inside the loop body.
- K recurrence should be carried state, not explicit vendor graph edges.

### 13.3 Resource allocation

- Operand allocation is `(task, PE)` scoped.
- Operand layout must respect 12-bank interleaving.
- Tensor pseudo operands must use lane-strided/group-aware allocation.
- COPY destination operands must come from receiver resource state.
- Graph traversal order is part of resource allocation semantics.

### 13.4 Binary emission

- CBUF/MICC component sizes and row widths are fixed DFU3500 ABI facts.
- Serializer must not invent scheduling or resource decisions.
- Inactive slots/padding/sentinel values belong in the DFU3500 vendor profile.
- Field differences in active `inst_t` rows must be fixed by algorithmic passes,
  not record-index patches.

## 14. Practical simulator-pass checklist

Before saying a bundle “should pass”, check:

1. `micc_file.bin` task/subtask rows match expected control shape.
2. `cbuf_file.bin` component sizes and offsets match.
3. All active `inst_t` rows have operand indices in `0..1535`.
4. COPY/COPYT destination PE/block points to the consumer block.
5. COPY/COPYT destination operand exists in the receiver resource map.
6. HMMAL source/destination operands are initialized in the same PE-local
   operand namespace.
7. K-loop repeated body has valid instance `base_addr[4]` for every iteration.
8. Per-PE inst count <= 4352 and exeBlock count <= 32.
9. Remaining diffs are classified as inactive/padding, or deliberately accepted
   compatibility flags.

If any remaining diff is an active operand/route/base-address field, it can
still break the simulator even if total diff count is small.

## 15. Current conclusion

The current “大同小异” state is meaningful progress:

```text
OpenFabric has recovered the vendor ABI skeleton and much of the executable
instruction envelope.
```

But simulator correctness depends on the last layer:

```text
PE-local resource state + route destination patching + instance base binding
```

Those are not cosmetic.  They are hardware constraints exposed through vendor
`common_oper` algorithms.  OpenFabric should treat these recovered algorithms as
DFU3500 backend standards.

## Related documents

- [openfabric-vs-vendor-compile-flow-report.md](openfabric-vs-vendor-compile-flow-report.md)
- [dfu3500-gemm-binary-replay.md](dfu3500-gemm-binary-replay.md)
- [csv-to-binary-pipeline.md](csv-to-binary-pipeline.md)
- [task-creation-generategraph-chain.md](task-creation-generategraph-chain.md)
- [runtime/data/cbuf.md](../../runtime/data/cbuf.md)
- [architecture/soc-system/data-pathway.md](../../architecture/soc-system/data-pathway.md)
- [architecture/pe-microarchitecture/pe-register-architecture.md](../../architecture/pe-microarchitecture/pe-register-architecture.md)
