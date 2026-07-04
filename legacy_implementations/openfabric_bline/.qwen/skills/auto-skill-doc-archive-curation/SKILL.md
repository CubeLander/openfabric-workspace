---
name: doc-archive-curation
description: Curate scattered documentation archives by classifying, extracting knowledge, and cleaning up ephemeral content
source: auto-skill
extracted_at: '2026-06-16T11:15:00.000Z'
---

# Documentation Archive Curation

When consolidating scattered documentation into an organized structure, use this systematic approach to separate durable knowledge from ephemeral tracking content.

## Procedure

1. **Enumerate and survey**: List all files in the target archive directory to understand scope and structure

2. **Read and classify each document** into these categories:
   - **Ephemeral status/tracking**: Stage reports, progress updates, milestone tracking, implementation status snapshots
   - **RFCs with outcomes**: Request-for-comments where the decision/implementation already exists in code
   - **Durable technical knowledge**: Design principles, architectural decisions, algorithm descriptions, technical insights that remain valuable
   - **Mixed documents**: Files containing both ephemeral and durable content

3. **Present classification to user**: Show a clear summary table with:
   - File count by category
   - Which files will be deleted vs kept vs extracted
   - Target locations for reorganized content
   - Get explicit confirmation before any deletions

4. **Execute the plan**:
   - **Keep as-is**: Copy durable knowledge documents to appropriate organized directories
   - **Extract**: For mixed documents, read key technical insights and write them into new focused documents in the organized structure
   - **Delete**: Remove all ephemeral/status/RFC files after knowledge extraction
   - **Clean up**: Remove empty directories

## Key Insights

- **Use parallel reading for large batches**: When surveying 20+ files, use subagents or batch-read multiple files in parallel rather than reading sequentially. This dramatically speeds up the classification phase.

- **Status reports are ephemeral**: Stage reports and progress snapshots document a moment in time but lose value once the work is complete. The actual implementation in code is the source of truth.

- **RFCs with implemented outcomes**: If an RFC describes a design decision that's already implemented, the RFC itself becomes redundant. The code and organized design docs capture the knowledge.

- **Design principles are durable**: Documents explaining architectural decisions, algorithmic approaches, or technical tradeoffs remain valuable for future reference and onboarding.

- **Mixed documents require judgment**: Some files contain both status tracking and genuine insights. Extract the insights before deletion.

- **Always confirm before deletion**: Present the plan to the user and get explicit confirmation. This is a destructive operation.

- **Cross-reference current codebase architecture before placement**: Before deciding where extracted docs go, read the actual source code structure (e.g. `core/__init__.py`, key module files). Documents about a *vendor's legacy toolchain* (CSV generators, vendor assemblers, vendor runtime) are fundamentally different from documents about *your project's own compiler/runtime pipeline*. Don't force vendor reference material into your project's compiler/runtime directories just because the topic sounds similar. If the content describes a different system than what your code implements, create a separate top-level section like `vendor_reference/` to keep the boundary explicit.

- **Existing directory stubs ≠ correct placement**: An empty `README.md` placeholder in `compiler/binary_packaging/` or `runtime/simulator/` doesn't mean vendor toolchain docs belong there. Check whether the directory's intended scope matches the document's actual subject before proposing it as a target.

- **Reference docs about external systems can move as-is**: When a directory contains well-organized reference material about an external system (vendor toolchain, third-party SDK, etc.), move the files intact to a dedicated reference section rather than extracting knowledge piece by piece. Create a new section like `vendor_reference/` with an index README explaining what the reference covers and when to consult it.

- **Cross-reference updates are mandatory when moving docs**: After relocating documents, grep for old paths in other docs and update them. Broken references defeat the purpose of consolidation. Use patterns like `docs/0[0-9]` to find stale paths efficiently.

- **Distinguish "your docs" from "reference docs"**: Your project's design docs describe systems you build. Reference docs describe external systems you integrate with or target. Mixing them creates confusion about what's authoritative. Keep them in separate top-level sections.

- **OCR-restored source code belongs at original paths**: When archive directories contain OCR-restored source files (e.g., `notes/ocr_restored/simict3500final/gpdpu/core/include/list.h`), move them to their intended location in the main repository tree, not leave them as notes. These are reconstructed source code, not documentation.

- **Delete operational/credential docs**: Documents containing network access chains, login credentials, server IPs, or operational procedures that change frequently are not durable knowledge. Delete them.

- **Delete research comparison notes**: Notes comparing external papers or research projects to your work (e.g., "how Strata's CUDA I/O compares to our DMA") are interesting but not project-specific durable knowledge. They belong in personal notes, not project docs.

- **Delete team internal observations**: Discussion notes, architecture observations, or internal team communications that have been superseded by organized architecture documentation should be deleted. The organized docs are the source of truth.

- **Delete redundant summary versions**: When both a detailed technical document and a condensed "group share" or "summary for team" version exist, keep the detailed version and delete the summary. The detailed version contains all the knowledge.

- **Delete project planning/roadmap documents**: Technology selection plans, gap analyses, milestone roadmaps, and "what we should build next" documents tied to specific project phases are not durable. They become outdated quickly and don't help future maintainers understand the system.

- **Vendor toolchain call chain docs are valuable**: Detailed traces of how vendor build/compile chains work (e.g., "how `task_creation` calls `generateGraph`", "how `subtask_graph_compile_chain` works") are valuable vendor reference material. They help understand the external system you're integrating with.

- **ISA/memory system reconstruction docs are gold**: Documents that reconstruct vendor hardware behavior, instruction sets, memory layouts, or execution models from available evidence are among the most valuable durable documents. They capture hard-won understanding of opaque systems.

- **Runtime architecture design docs are durable**: Documents describing runtime programming models, kernel/runtime work splits, relocatable kernel implementations, and hardware relocation mechanisms describe systems you're building. These belong in `docs_refactored/runtime/control/` or similar directories.

## Classification Heuristics

**Likely ephemeral (delete):**
- Files with names like `stage-report-*`, `status-*`, `progress-*`
- Documents that are primarily checklists, TODOs, or milestone tracking
- RFCs where the implementation is complete and documented elsewhere
- Network access chains, credentials, server connection instructions
- Research paper comparisons or external project analyses
- Team internal discussion notes or architecture observations
- Condensed "summary for team" versions when detailed versions exist
- Technology selection plans, gap analyses, or project roadmaps
- OCR image inventories or restoration progress trackers

**Likely durable (keep):**
- Files explaining core concepts, algorithms, or design principles
- Documents describing architectural boundaries or technical tradeoffs
- Technical reference material (API designs, data structures, protocols)
- Vendor toolchain call chain traces (how external build/compile systems work)
- ISA, instruction set, or execution model reconstructions
- Memory system layouts, address maps, or hardware behavior documentation
- Runtime programming models, kernel/runtime architecture designs
- Relocatable kernel implementations or hardware relocation mechanisms

**Likely mixed (extract then delete):**
- Files that mix status updates with technical insights
- Long documents where only certain sections contain reusable knowledge

## Vendor OCR Source Assembly

When reconstructing vendor source code from screenshot-based OCR files:

1. **Enumerate numbered screenshots**: OCR screenshots are typically stored as numbered markdown files (`1.md`, `2.md`, ..., `14.md`). Each contains `cpp` fenced code blocks mixed with human commentary.

2. **Extract code blocks in order**: Use a shell one-liner to concatenate code blocks from all screenshots in numeric order:
   ```bash
   for f in $(ls *.md | sort -t. -k1 -n); do
     echo "// ===== $f ====="
     sed -n '/^```cpp/,/^```/p' "$f" | sed '1d;$d'
   done > assembled_source.cpp
   ```

3. **Verify completeness**: After assembly, `grep` for key function names to confirm all important functions are present in the assembled file. Look for function signatures, not just names.

4. **Compare against local versions**: The local repo may contain a **stub implementation** (functions with `(void)` casts and early returns) while the OCR'd version contains the full algorithm. This is a critical difference — always compare line counts and key function signatures before deciding whether to overwrite.

5. **Backup before overwriting**: Always `cp` the local version to a `.local_stub_backup` file before replacing with the OCR-assembled version.

6. **Update all copies**: Check for multiple copies of the file (e.g., in `build_out/.../worktree/` directories) and update all of them.

7. **Watch for screenshot boundaries**: OCR screenshots often cut off mid-function. Look for incomplete code blocks and cross-reference adjacent screenshots to fill gaps.

## Binary Diff Root Cause Analysis Pattern

When debugging "fix one byte, break another" (按下葫芦浮起瓢) patterns in vendor binary alignment:

1. **Recognize the anti-pattern**: If every byte-level fix causes new diffs elsewhere, the root cause is not a wrong constant — it's a missing algorithm. Static lookup tables cannot approximate a dynamic state machine.

2. **Find the vendor allocator source**: The missing behavior is almost always in a vendor resource allocator (register/operand/memory). Check `common_oper/`, `build_app/`, or equivalent vendor build tool source.

3. **Compare stub vs real**: Local vendor source may be stubbed. The real implementation on remote hardware contains the full allocation logic. Key signs: `(void)param; return 0;` patterns, missing `#ifdef` branches, simplified tag→counter mappings instead of physical pool allocation.

4. **Document the root cause before coding**: Write a structured analysis report (source file, function-by-function comparison, specific byte families explained) before implementing fixes. This prevents future agents from repeating the byte-fitting approach.

5. **Implement the vendor allocator, not byte patches**: The correct fix shape is always to model the vendor's allocation state machine (tag→pool→operand mapping, hazard windows, conflict resolution, child-node queries) and replay it over your program IR, rather than tuning constants in a static approximation.

## Stub vs Real Implementation Detection

A common pattern in vendor codebases: the local repo has a simplified/stubbed version of critical vendor source files (e.g., 711 lines with all complex functions stubbed), while the actual runtime on remote hardware uses the full implementation (e.g., 2245 lines with complete register allocation, bank-conflict detection, and reduce-chain optimization).

Key signs of a stub version:
- Functions containing only `(void)param; return 0;`
- Simplified logic that ignores edge cases present in the full version
- Missing `#ifdef REDUCE` / `#ifdef ORDER` branches
- Missing pseudo-tensor instruction expansion logic
- Missing `extra_fields[2]` RAM group constraint handling

When this pattern exists, **binary diffs against vendor output will never fully resolve** by tuning constants — they require implementing the real algorithm.

## Vendor Binary Diff Field Mapping

When you have raw byte-level diff output from a vendor binary comparison (offsets and byte values), map them to struct fields to understand **what's wrong**, not just **where it differs**.

### Procedure

1. **Parse diff offsets into (record, byte_in_record) pairs**:
   ```python
   RECORD_SIZE = 304  # inst_t struct size
   record_num = offset // RECORD_SIZE
   byte_in_record = offset % RECORD_SIZE
   ```

2. **Map byte_in_record to field name** using the known struct layout:
   ```python
   INST_FIELD_LAYOUT = [
       (0, 4, "opcode"), (48, 8, "src0"), (56, 8, "src1"),
       (64, 8, "src2"), (72, 8, "dst0"), (80, 8, "dst1"),
       (96, 8, "dst_pe0_x"), (168, 8, "dst_block0"),
       (240, 8, "iter_exe_cond"), (272, 8, "end_inst"),
       # ... complete layout from diff script
   ]
   ```

3. **Compute operand delta**: `delta = local_value - remote_value`. The sign and magnitude reveal the root cause.

4. **Classify delta patterns**:

   | Delta magnitude | Meaning | Root cause |
   |---|---|---|
   | ±1 | Sequential counter drift | Tag encounter order differs between local allocator and vendor graph walk |
   | ±128 | One operand slot shift | Bank assignment off by 1 |
   | ±512 (4 × 128) | One tensor group shift | Operand assigned to wrong tensor RAM group (group 0/1/2) |
   | ±1536 (12 × 128) | Full group boundary | Complete group misclassification |
   | Combined (e.g., -1 + 512 = +511) | Two problems overlapping | Counter drift + group shift |

5. **Check stride patterns**: If diffs appear at regular stride (e.g., every 304 bytes = every record), the problem is systematic (affects all instructions in a micro-block). If diffs cluster at specific record ranges, the problem is localized to a specific (task, PE, stage) window.

6. **Write field-level summary table** before implementing fixes:
   ```text
   offset   rec#  byte  field  local  remote  delta
   2689257  8846    73  dst0       2       0   +512
   3178088 10454    72  dst0      92      93     -1
   ```

This turns raw byte noise into actionable field-level diagnoses.

## Regression Lock Before Binary Alignment Changes

Before modifying any operand allocation logic (seed tables, TaskResource replay, COPY patching):

1. **Generate current output** and record SHA256 hashes of all binary components (cbuf, micc, insts).

2. **Extract operand values at every known diff position**: Decode the struct at each diff record and record the exact `src0`, `src1`, `dst0` values.

3. **Write regression assertions** that lock these exact values:
   ```python
   assert hashlib.sha256(cbuf).hexdigest() == "71d8b0..."
   assert unpack_rec(8846)[9] == 623  # dst0 at known diff position
   assert unpack_rec(980)[9] == 621   # known-good position matching vendor
   ```

4. **Include both diff positions AND known-good positions**: Known-good assertions prevent regressions in areas that already match vendor.

5. **After making changes**, update the regression test with new values and the new SHA256. The old hash in the docstring serves as a historical anchor.

This pattern prevents the "fix one diff, break three others" cycle that plagues binary alignment work.

## TaskResource Replay Pass Implementation Pattern

When implementing a vendor allocator replay pass (replacing static seed tables with dynamic allocation):

### Pipeline insertion
```text
VendorABI (template-bound instructions + exeBlocks)
    ↓
replay_task_resource()          ← NEW pass
    ↓
lower_to_bin_rows()
```

### Core data structure
```python
@dataclass
class LegacyTaskResource:
    pe_pool: list[list[int]]        # per-bank stacks of free operand indices
    tensor_pool: list[list[int]]    # per-group tensor register pools
    tag_to_operand: dict[str, int]  # memoized allocations
    reg_counter: int
    ram_idx_rest_rec: list[int]     # free bank indices
    ram_idx_used_rec_list: list[list[int]]  # 3-instruction hazard window
```

### Key algorithm steps
1. Group instructions by `(task_index, processor)`
2. For each group, create a fresh `TaskResource`
3. Walk exeBlocks in vendor node order (`pe_local_block_idx`)
4. For each exeBlock, walk stages in order: LD → CAL → FLOW → ST
5. For each instruction, bind tags to operand indices via `get_reg_idx(tag)`
6. Handle pseudo-tensor expansion: rewrite opcode + lane offsets
7. Maintain 3-instruction hazard window
8. After all nodes processed, patch COPY destinations from child TaskResource

### Critical pitfall: stub vs real allocator
The local vendor source may have `get_reg_idx(tag, start)` as a simple `layout_operand_idx(counter + start)`, while the arch-13 version uses `alloc_operand_slot(pPe, ...)` from a physical pool. **Always check the OCR'd remote version**, not the local checkout.

### Critical pitfall: REDUCE mode matters
The vendor source has `#define REDUCE 1` and `#define REDUCE 0` paths. The GEMM case uses `REDUCE 0` (non-REDUCE), which means the allocator uses **counter-based `layout_operand_idx(counter + start)`** with `alloc_operand_slot` for PE pool allocation — NOT the full reduce-chain optimizer. If your replay pass models the wrong mode, it will diverge from vendor behavior.

### ID namespace mapping
ExeBlock `instruction_ids` use `asm_inst:*` namespace, while `template_bound_instructions` use `template_inst:*` namespace. They are **different ID spaces with 0 overlap**. To find template instructions from exeBlocks:

```text
exeBlock.instruction_range_ids
  → instruction_ranges[range_id].template_bound_instruction_ids
  → template_bound_instructions[tid]
```

Do NOT iterate `exeBlock.instruction_ids` and look them up in `template_bound_instructions` — they will never match.

### Replay pass can make things worse
If the vendor uses counter-based allocation (non-REDUCE mode), your seed tables may already closely approximate the vendor's behavior. A pool-based replay pass that allocates from PE physical pools will produce **different** operand indices because:

1. Pool pop order ≠ counter increment order
2. Bank-conflict resolution changes allocation sequence
3. Hazard window re-freeing affects which banks are available

**Empirical evidence**: Full pool replay increased diff from 14944 → 280912 bytes. COPY-only patching increased it to 283520 bytes. Both worse than the seed table approach.

**When to use a no-op replay pass**: If both full replay and partial patching make diffs worse, make the pass a no-op and document why. Remaining diffs should be fixed by adjusting seed table constants, not algorithmic replay.

### Local vendor reference ≠ arch-13 vendor output
The local `simict3500final/.../result/cbuf_file.bin` may differ from arch-13's vendor runtime output by a different amount than your compiler output. You can only validate final alignment against the actual arch-13 vendor binary, not the local reference copy. Local byte-diff counts are not comparable to arch-13 diff counts.

### Gate by vendor_inst_mode
```python
if vendor_inst_mode == "legacy_gemm_compat":
    vendor_abi = replay_legacy_task_resource(vendor_abi)
```
This ensures the pass only runs for legacy compatibility, not for the generic symbolic path.

### Seed tables vs replay passes — when simpler is better
If the vendor uses counter-based allocation (non-REDUCE mode with `layout_operand_idx`),
static seed tables that assign tags to operand indices via the same counter formula
already closely approximate vendor behavior. In this case, a replay pass that uses
PE pool allocation (`alloc_operand_slot`) will produce **different** results because
pool pop order ≠ counter increment order. Empirically:

- Seed tables alone: 14944 byte diff vs vendor
- Full pool replay: 280912 byte diff (19x worse)
- COPY-only child-resource patching: 283520 byte diff (19x worse)

**Rule of thumb**: If remaining diffs are small (<< 1% of binary size) and concentrated
in specific fields (operand indices, block indices), the seed table approach is likely
already correct. Remaining diffs should be fixed by adjusting seed constants or node
traversal order, not by implementing the full vendor allocator.

### Node traversal order as a source of counter drift
The vendor operand counter depends on the order in which graph nodes are visited
during `distribute_operand()`. Vendor visits nodes in `m_pGraph_nodes` push order,
which is determined by `sortByDepth` (topological sort in `inst_blk_map.cpp::map()`).

OpenFabric sorts exeBlocks by `_block_sort_key`:
```python
(task_index, processor, subtask_index, instance_key_index, legacy_micro_block_order, block_id)
```

If these two orderings differ for the same (task, PE), tags will be encountered in
a different order, causing ±1 counter drift across all subsequent operand indices.
This is a systematic error that affects many records with small deltas.

To diagnose: print the block order for one (task, PE) from both systems and compare.
If the orderings diverge within a subtask (e.g., vendor puts route_source before
route_forward for the same K instance, but OpenFabric interleaves them differently),
the counter drift will propagate to all downstream allocations.

### K-stream instance semantics from app0.conf
Vendor `app0.conf` declares `Instance Times: N` per subtask. This means the runtime
replays the subtask N times with different `instance_conf.base_addr[]` entries —
**NOT** that N separate node sets are created at compile time.

The compiler creates ONE set of graph nodes per subtask. `distribute_operand()` walks
those nodes once. The K-stream folding happens at runtime via the instance table.

If your compiler creates separate instruction ranges per K instance (e.g., k0, k1,
k2, k3 as separate blocks), the seed tables must reuse the same tags across instances
so the counter doesn't advance. Otherwise operand indices will drift by the number
of tags per instance × number of prior instances.

## Seed Table Tensor Group Fix Pattern

When the arch-13 `inst_field_diff_summary` shows a systematic operand index shift
(e.g., 6528 records with `src1=1134 vs 622`, delta=512=4×128=1 tensor group):

### Diagnosis

1. **Identify the shifted operand**: Look at the field name and value pair.
   `src1=1134` (local) vs `src1=622` (vendor) with delta=512 means the operand
   is in the wrong tensor group. 512 = OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE × OPERANDS_PER_OPERAND_RAM = 4 × 128.

2. **Find which tag produces the value**: Check seed tables for the tag that
   maps to the local operand index. `1134 = group 2 × 512 + slot`, while
   `622 = group 1 × 512 + slot`. The tag is in the wrong group.

3. **Fix the group assignment**: Move the tag from the wrong group to the
   correct group in ALL seed functions (`_before_input0`, `_after_input0`,
   `_after_input1`) and the `_group_for_tag` lookup function.

### Critical pitfalls when fixing group assignments

1. **Don't pre-seed dynamic tags for the task that first encounters them**:
   If vendor dynamically allocates a tag (e.g., "BET") when it first appears
   in the CSV template, pre-seeding it shifts all subsequent tag indices by 1,
   breaking existing alignments (e.g., COPYT15 dst0 goes from 623 to 624).

   **Fix**: Only pre-seed the tag from *prior* tasks (where it was already
   allocated), not from the current task. The current task's tag should be
   dynamically allocated when first encountered in the CSV.

2. **Cross-task seed propagation**: When a tag uses a bare name in task 0
   (e.g., "BET") and a task-suffixed name in later tasks (e.g., "BET@task1"),
   the seed functions for later tasks must include the bare name from task 0
   using the correct tag function (e.g., `_legacy_gemm_task_bet_tag(0)` which
   returns "BET", not "BET@task0").

3. **Seed ordering within a group determines operand values**: Tags are
   allocated descending within each group. The first tag in the seed tuple
   gets the highest operand index, the last gets the lowest. Changing the
   order shifts all indices in that group.

4. **Update ALL test assertions**: Group fixes change operand indices across
   the entire binary. Tests asserting specific values at specific record
   positions will fail and must be updated with new values. Record the old
   hash in the regression test docstring as a historical anchor.

### Verification workflow

```python
# 1. Check group assignment
assert _legacy_gemm_tensor_group_for_tag("BET") == 1  # was 2

# 2. Check operand index in seed encoder
enc = LegacyCsvEncoder(initial_tensor_tags_by_group=seed_fn(1))
assert enc._tensor_idx_by_tag["BET"] == 622  # group 1, not 1134 (group 2)

# 3. Check that task 0 known-good records are unchanged
route = legacy_gemm_micro_block_template("route_forward", task_index=0, template_index=10)
assert route[60].dst_operands_idx[0] == 623  # COPYT15 must not shift

# 4. Check that cross-task HMUL now matches vendor
acc = legacy_gemm_micro_block_template("accumulator_prepare", task_index=1, template_index=0)
assert acc[67].src_operands_idx == (110, 622, 0)  # src1=BET=622, not 1134
```

## Reading `inst_field_diff_summary` for Actionable Fixes

The arch-13 diff script (`byte_diff_old_python.py`) produces a field-level summary
that groups diffs by `inst_t` field name and shows sample records with decoded values.

### Key fields and what they reveal

| Field | Byte offset | What diffs mean |
|---|---|---|
| `src0` | 48 | Source operand 0 wrong — tag assigned to wrong counter position |
| `src1` | 56 | Source operand 1 wrong — often a scalar constant (ALPHA/BET) in wrong group |
| `dst0` | 72 | Destination operand wrong — same as src0, or COPY destination patch needed |
| `dst_pe0_x` | 96 | COPY destination PE wrong — graph edge routing error |
| `dst_block0` | 168 | COPY destination block wrong — exeBlock ordering mismatch |
| `end_inst` | 272 | Stage end flag wrong — last-instruction marking logic |

### Reading sample records

```text
sample rec=13892
local { opcode=0x52 src0=111 src1=1134 dst0=111 }
remote { opcode=0x52 src0=110 src1=622 dst0=110 }
```

This tells you:
1. **opcode 0x52 = HMUL**: it's a scalar multiply instruction
2. **src1=1134 vs 622**: BET operand is in wrong tensor group (delta=512)
3. **src0/dst0 differ by 1**: counter drift cascading from the group error
4. **Continuous range** (13892-13907): affects all HMUL instructions in this subtask

### Actionable fix mapping

| Pattern in summary | Fix location |
|---|---|
| `src1` field, delta=±512, scalar tag (ALPHA/BET) | Fix tensor group assignment in seed tables |
| `src0`/`dst0` field, delta=±1, continuous range | Seed ordering within group, or node traversal order |
| `dst_pe0_x`/`dst_block0`, COPY records only | Graph edge routing or COPY destination patching |
| `end_inst`, sparse single records | Stage-end flag marking logic |
| `src0` field, delta=±512, tensor load tag | Tensor group assignment for HLDT/HSTT source |

## Example Outcome

Across four archive directories:
- `compiler/notes/archive/` (51 files): 18 durable documents extracted/reorganized, 33 ephemeral status/RFC files deleted
- `docs/` (11 files): 10 vendor toolchain reference docs moved to `docs_refactored/vendor_reference/`, 1 redundant README deleted
- `notes/` (21 files): 4 runtime design docs moved to `docs_refactored/runtime/control/`, 2 architecture docs moved to `docs_refactored/architecture/`, 9 vendor reference docs moved to `docs_refactored/vendor_reference/`, 1 OCR-restored source file placed at original path, 8 ephemeral files deleted
- `compiler/notes/binary/` (3 files): kept as-is (active investigation notes), plus 1 new analysis report added after OCR source assembly

Total: 86 files surveyed, 44 durable documents preserved, 2 source files restored (1 from notes, 1 from OCR screenshots), 42 ephemeral files deleted. All cross-references in organized docs updated to point to new locations.

OCR source assembly: 14 screenshot markdown files → 3498-line `inst_blk_map.cpp` (arch-13 version), replacing a 711-line local stub. This enabled root-cause analysis of CBUF binary diffs and implementation of a `LegacyTaskResource` replay pass.
