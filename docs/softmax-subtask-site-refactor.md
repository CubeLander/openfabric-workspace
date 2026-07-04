# Softmax Subtask Site Refactor

Status: completed implementation note.

## Direction

GEMM should be treated as the expression superset, and softmax should move
toward the GEMM-shaped site model instead of GEMM inheriting softmax's older
per-PE template shape.

The shared unit should be a `(task, subtask)` site. The site owns the current
subtask writing surface, while `activate_pe(pe_id)` only changes the current
program subject. A PE program should then be able to issue normal register and
fiber actions against the active context.

## Instruction Block Boundary

Vendor assembler inputs still require one CSV instruction file per graph node,
and in the current softmax case that graph-node block is numerically the PE id.
That fact should be explicit at the fiber-program call surface:

```cpp
site.activate_pe(pe_id);
site.begin_instruction_block(instruction_block_id);
...
site.write_instruction_block(instruction_block_id);
```

For softmax today:

```cpp
const int instruction_block_id = pe_id;
```

Keeping the block id in the main program is intentional. It exposes the atomic
vendor-visible block boundary instead of hiding it in a layout table or a
secondary emitter object.

## Refactor Scope

Move these responsibilities from softmax `main.cpp` into the subtask site:

- `InstructionStreams`
- instruction `count`
- clearing the current block
- writing the current block to the vendor CSV file

Then softmax main should only express:

- task and subtask loops
- PE activation
- explicit instruction block id
- DTensor tile refs
- fiber/register actions
- block write boundary

This aligns softmax with the GEMM direction without forcing GEMM to use the
softmax buffered `InstructionStreams` backend. GEMM can keep its direct FILE
writer while both sides converge on the same site-level responsibility split.

## Completed In This Pass

- `VendorEmitSite` owns `InstructionStreams` and instruction `count`.
- Softmax main explicitly uses `instruction_block_id`.
- Softmax main no longer directly clears streams or calls `write_csv`.
- The softmax `write_csv` backend parameter now names the vendor file number as
  `instruction_block_id`.

## Later Cleanup

- Look for remaining single-call helpers in softmax after the site owns block
  lifecycle.
- After softmax and GEMM both stabilize, extract only the site facts that are
  truly shared: active PE, tensor tile lookup, block boundary, and target sink
  ownership.
