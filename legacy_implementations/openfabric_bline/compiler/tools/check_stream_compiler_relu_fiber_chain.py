#!/usr/bin/env python3
"""Lightweight check for explicit GEMM -> ReLU -> store fiber chains."""

from __future__ import annotations

from gpdpu_compiler.core.program_legacy_inst import (
    INST_RECORD_SIZE_BYTES,
    LegacyCsvEncoder,
    pack_legacy_inst,
)
from gpdpu_compiler.core.op_specs import MATMUL_SPEC
from gpdpu_compiler.core.stream_compiler.binary_plan import (
    lower_template_ops_to_binary_layout,
    summarize_binary_layout_plan,
)
from gpdpu_compiler.core.stream_compiler.inst_writers import (
    build_template_evidence_binding_report,
    summarize_template_evidence_binding_report,
)
from gpdpu_compiler.core.stream_compiler.binding import (
    bind_executable_roles_symbolically,
    summarize_role_binding_program,
)
from gpdpu_compiler.core.stream_compiler.dfu3500_semantics import (
    lower_template_records_to_dfu3500_semantics,
    summarize_dfu3500_semantic_report,
)
from gpdpu_compiler.core.stream_compiler.executable import (
    lower_fibers_to_executable_ops,
    summarize_executable_program,
)
from gpdpu_compiler.core.stream_compiler.gemm_demo import build_demo_gemm_stream_plan
from gpdpu_compiler.core.stream_compiler.relu_fiber_chain import (
    build_gemm_relu_fiber_chain_report,
    summarize_relu_fiber_chain_report,
)
from gpdpu_compiler.core.stream_compiler.relu_binding import (
    bind_explicit_relu_subtasks,
    summarize_explicit_relu_subtask_binding_report,
)
from gpdpu_compiler.core.stream_compiler.schedule import (
    build_fiber_execution_schedule,
    summarize_fiber_execution_schedule,
)
from gpdpu_compiler.core.stream_compiler.template_ops import (
    lower_schedule_to_template_ops,
    summarize_template_op_plan,
)
from gpdpu_compiler.core.stream_compiler.template_records import (
    lower_symbolic_bindings_to_template_records,
    summarize_template_record_program,
)


def main() -> None:
    plan = build_demo_gemm_stream_plan(include_relu=True)
    report = build_gemm_relu_fiber_chain_report(plan)
    summary = summarize_relu_fiber_chain_report(report)
    executable = lower_fibers_to_executable_ops(
        report.fibers,
        executable_role_profile=MATMUL_SPEC.executable_role_profile(),
    )
    executable_summary = summarize_executable_program(executable)
    bindings = bind_executable_roles_symbolically(
        executable,
        template_intents=MATMUL_SPEC.template_intent_profile(),
    )
    binding_summary = summarize_role_binding_program(bindings)
    template_records = lower_symbolic_bindings_to_template_records(bindings)
    template_record_summary = summarize_template_record_program(template_records)
    semantic_report = lower_template_records_to_dfu3500_semantics(template_records)
    semantic_summary = summarize_dfu3500_semantic_report(semantic_report)
    schedule = build_fiber_execution_schedule(executable, semantic_report)
    schedule_summary = summarize_fiber_execution_schedule(schedule)
    template_plan = lower_schedule_to_template_ops(
        schedule,
        semantic_report=semantic_report,
        template_records=template_records,
    )
    template_summary = summarize_template_op_plan(template_plan)
    relu_binding_report = bind_explicit_relu_subtasks(template_plan)
    relu_binding_summary = summarize_explicit_relu_subtask_binding_report(
        relu_binding_report
    )
    layout = lower_template_ops_to_binary_layout(
        template_plan,
        requested_runnability_state="emittable_debug",
    )
    layout_summary = summarize_binary_layout_plan(layout)
    writer_evidence = build_template_evidence_binding_report(layout)
    writer_summary = summarize_template_evidence_binding_report(writer_evidence)
    failures: list[str] = []

    if summary["fiber_count"] != 64:
        failures.append(f"expected 64 fibers, got {summary['fiber_count']}")
    if summary["op_sequence_counts"] != {"gemm_tile->relu_tile->store_tile": 64}:
        failures.append(f"unexpected op chains: {summary['op_sequence_counts']}")
    if summary["op_counts"] != {"gemm_tile": 64, "relu_tile": 64, "store_tile": 64}:
        failures.append(f"unexpected op counts: {summary['op_counts']}")
    if summary["relu_template_binding_status_counts"] != {
        "production_mapping_concrete_writer_blocked": 64
    }:
        failures.append(
            "ReLU report should expose concrete production mapping with writer block, got "
            f"{summary['relu_template_binding_status_counts']}"
        )
    if summary["template_binding_gap_count"] != 1:
        failures.append(
            "expected one remaining ReLU production writer gap, got "
            f"{summary['template_binding_gap_count']}"
        )
    if summary["diagnostic_count"] != 0:
        failures.append(f"unexpected diagnostics: {report.diagnostics}")

    forbidden_op_names = {
        "accumulator_prepare",
        "gemm_update",
        "finalize_accumulator",
        "store_fragment",
    }
    for fiber in report.fibers:
        ops = tuple(str(op.op) for op in fiber.ops)
        if any(op in forbidden_op_names for op in ops):
            failures.append(f"{fiber.id}: chain contains non-atomic bridge op {ops}")
        if fiber.ops[1].depends_on[0].source_op_id != fiber.ops[0].id:
            failures.append(f"{fiber.id}: relu_tile does not depend on gemm_tile")
        if fiber.ops[2].depends_on[0].source_op_id != fiber.ops[1].id:
            failures.append(f"{fiber.id}: store_tile does not depend on relu_tile")
        relu_output = fiber.ops[1].outputs[0]
        store_input = fiber.ops[2].inputs[0]
        if relu_output != store_input:
            failures.append(f"{fiber.id}: store does not consume ReLU output")
        if relu_output.role != "Y":
            failures.append(f"{fiber.id}: expected ReLU output role Y, got {relu_output.role}")

    if executable_summary["role_counts"] != {
        "compute_core:gemm_tile": 64,
        "tile_op:relu": 64,
        "tile_store": 64,
    }:
        failures.append(
            "unexpected production executable roles: "
            f"{executable_summary['role_counts']}"
        )
    if executable_summary["placement_counts"] != {"tile_body": 128, "tile_store": 64}:
        failures.append(
            "ReLU must stay in tile_body before tile_store, got "
            f"{executable_summary['placement_counts']}"
        )
    if binding_summary["status_counts"] != {"legacy_template_candidate": 192}:
        failures.append(f"unexpected binding statuses: {binding_summary['status_counts']}")
    if binding_summary["unsupported_role_counts"] != {}:
        failures.append(
            "ReLU should have a production template candidate now, got "
            f"{binding_summary['unsupported_role_counts']}"
        )
    if template_record_summary["stage_counts"] != {"post_loop": 64, "tile_body": 128}:
        failures.append(
            "template records should place GEMM/ReLU in tile_body and store later, got "
            f"{template_record_summary['stage_counts']}"
        )
    if semantic_summary["unproven_role_counts"] != {}:
        failures.append(
            "ReLU target semantics should be proven at local tile-op level, got "
            f"{semantic_summary['unproven_role_counts']}"
        )
    if schedule_summary["phase_counts"] != {"tile_body": 128, "tile_store": 64}:
        failures.append(f"unexpected schedule phases: {schedule_summary['phase_counts']}")
    if template_summary["status_counts"] != {"concrete_template": 192}:
        failures.append(f"unexpected template statuses: {template_summary['status_counts']}")
    if template_summary["unresolved_role_counts"] != {}:
        failures.append(
            "ReLU should no longer be an unresolved TemplateOp role, got "
            f"{template_summary['unresolved_role_counts']}"
        )
    if relu_binding_summary["binding_status"] != "fail_closed":
        failures.append(
            "ReLU binding must remain fail_closed until row bytes close, got "
            f"{relu_binding_summary['binding_status']}"
        )
    if relu_binding_summary["binding_count"] != 64:
        failures.append(
            f"expected 64 explicit ReLU binding seeds, got {relu_binding_summary['binding_count']}"
        )
    if relu_binding_summary["concrete_relu_template_count"] != 64:
        failures.append(
            "expected 64 concrete ReLU template rows before writer bytes, got "
            f"{relu_binding_summary['concrete_relu_template_count']}"
        )
    if "relu_p0:template_row_evidence" not in relu_binding_summary["p0_blocker_ids"]:
        failures.append(
            "ReLU writer must still report template row evidence blocker, got "
            f"{relu_binding_summary['p0_blocker_ids']}"
        )
    if relu_binding_summary["exact_row_evidence_status_counts"] != {"p0_blocked": 64}:
        failures.append(
            "ReLU exact row evidence must stay fail-closed per tile, got "
            f"{relu_binding_summary['exact_row_evidence_status_counts']}"
        )
    if relu_binding_summary["exact_row_selector_status_counts"] != {
        "candidate_hmax_materializer_bline_activation_closed_runtime_selector_missing": 64
    }:
        failures.append(
            "ReLU exact selector should expose an explicit HMAX materializer "
            "candidate while blocking active selector, got "
            f"{relu_binding_summary['exact_row_selector_status_counts']}"
        )
    if relu_binding_summary["row_byte_proof_plan_status_counts"] != {
        "candidate_hmax_materializer_bline_activation_closed_runtime_selector_missing": 64
    }:
        failures.append(
            "ReLU row-byte proof plan should expose candidate rows while staying "
            "blocked on active HMAX selector, got "
            f"{relu_binding_summary['row_byte_proof_plan_status_counts']}"
        )
    if relu_binding_summary["row_byte_proof_requirement_status_counts"] != {
        "available": 128,
        "closed": 512,
        "p0_blocked": 64,
    }:
        failures.append(
            "unexpected ReLU row-byte proof requirement statuses: "
            f"{relu_binding_summary['row_byte_proof_requirement_status_counts']}"
        )
    proof_missing = relu_binding_summary["row_byte_proof_missing_artifact_counts"]
    expected_active_selector_artifacts = {
        "active_relu_template_family_selector_proof": 64,
        "active_subtask4_runtime_selector_trace": 64,
    }
    if proof_missing != expected_active_selector_artifacts:
        failures.append(
            "ReLU row-byte proof should block only on concrete active selector "
            f"selector proof, got {proof_missing}"
        )
    exact_missing = relu_binding_summary["exact_row_missing_writer_input_counts"]
    if exact_missing != expected_active_selector_artifacts:
        failures.append(
            "ReLU exact row evidence should block only on concrete active selector "
            f"selector proof, got {exact_missing}"
        )
    if layout_summary["runnability_state"] != "emittable_debug":
        failures.append(
            "layout can now place ReLU rows but bytes remain writer-blocked, got "
            f"{layout_summary['runnability_state']}"
        )
    if layout_summary["instruction_row_count"] != 192:
        failures.append(
            "GEMM, ReLU, and store rows should be allocated before byte writer closes, got "
            f"{layout_summary['instruction_row_count']}"
        )
    relu_rows = [row for row in layout.instruction_rows if row.role == "tile_op:relu"]
    if len(relu_rows) != 64:
        failures.append(f"expected 64 ReLU layout rows, got {len(relu_rows)}")
    if sum(1 for row in relu_rows if row.opcode == "HMAX") != 64:
        failures.append(
            "ReLU should allocate 64 HMAX layout rows, got "
            f"{[row.opcode for row in relu_rows[:4]]}"
        )
    if any(row.subtask_slot != "subtask4_relu_candidate" for row in relu_rows):
        failures.append("ReLU rows must stay in explicit subtask4 ReLU slot")
    if writer_summary["binding_status_counts"].get(
        "candidate_relu_tile_template_span"
    ) != 64:
        failures.append(
            "inst writer must expose 64 ReLU template-span candidates, got "
            f"{writer_summary['binding_status_counts']}"
        )
    if writer_summary["unmatched_template_evidence_count"] != 0:
        failures.append(
            "ReLU writer entry should be matched-but-blocked, not unmatched; got "
            f"{writer_summary['unmatched_template_evidence_count']}"
        )
    relu_writer_rows = writer_summary["role_opcode_candidate_raw_row_counts"].get(
        "tile_op:relu|HMAX"
    )
    if not relu_writer_rows or relu_writer_rows["row_count"] != 64:
        failures.append(
            "writer summary should carry 64 tile_op:relu|HMAX rows, got "
            f"{writer_summary['role_opcode_candidate_raw_row_counts']}"
        )
    doc_hmax_rows = LegacyCsvEncoder().parse_rows(
        (["HMAX", "HMAX15", "A1", "A2", "B4", "", "", "0"],)
    )
    if len(doc_hmax_rows) != 1:
        failures.append(f"expected one doc HMAX row, got {len(doc_hmax_rows)}")
    elif doc_hmax_rows[0].opcode != 0x53:
        failures.append(f"unexpected doc HMAX opcode: {doc_hmax_rows[0].opcode:#x}")
    elif len(pack_legacy_inst(doc_hmax_rows[0])) != INST_RECORD_SIZE_BYTES:
        failures.append("doc HMAX row does not pack to one inst_t record")
    candidate = (
        relu_binding_report.bindings[0]
        .exact_row_evidence
        .row_byte_proof_plan
        .materializer_candidate
    )
    if candidate is None:
        failures.append("expected ReLU HMAX materializer candidate")
    else:
        if candidate.status != (
            "candidate_bytes_and_bline_activation_closed_runtime_selector_missing"
        ):
            failures.append(f"unexpected ReLU candidate status: {candidate.status}")
        if candidate.expected_ops != ("IMM", "HMAX"):
            failures.append(f"unexpected ReLU candidate ops: {candidate.expected_ops}")
        if candidate.row_count != 2:
            failures.append(f"expected 2 ReLU candidate rows, got {candidate.row_count}")
        if (
            candidate.input_operand_index,
            candidate.zero_operand_index,
            candidate.output_operand_index,
        ) != (0, 128, 256):
            failures.append(
                "unexpected ReLU candidate operand indexes: "
                f"{candidate.input_operand_index}, {candidate.zero_operand_index}, "
                f"{candidate.output_operand_index}"
            )
        if candidate.to_plan()["max_operand_roles"] != {
            "src0": "zero",
            "src1": "input",
        }:
            failures.append(
                "ReLU candidate must mirror vendor subtask4 HMAX operand order, got "
                f"{candidate.to_plan()['max_operand_roles']}"
            )
        if candidate.local_order != (0, 1):
            failures.append(f"unexpected ReLU candidate local_order: {candidate.local_order}")
        if candidate.raw_inst_t_byte_count != 2 * INST_RECORD_SIZE_BYTES:
            failures.append(
                "unexpected ReLU candidate byte count: "
                f"{candidate.raw_inst_t_byte_count}"
            )
        if candidate.active_selector_claim:
            failures.append("ReLU candidate must not claim active selector")
        if len(candidate.raw_template_row_sha256) != 64:
            failures.append("ReLU candidate payload hash must be sha256 hex")
        if not candidate.candidate_row_bytes_claim:
            failures.append("ReLU candidate should claim candidate row bytes")
        if not candidate.candidate_raw_template_row_sha256_claim:
            failures.append("ReLU candidate should claim candidate row hash")
        activation = candidate.activation_record
        if activation.status != (
            "bline_explicit_activation_candidate_runtime_selector_missing"
        ):
            failures.append(
                "unexpected ReLU activation record status: "
                f"{activation.status}"
            )
        if activation.source_kind != "bline_explicit_relu_tile_task_activation":
            failures.append(
                "ReLU activation must be explicit B-line relu_tile task, got "
                f"{activation.source_kind}"
            )
        if activation.subtask_slot != "subtask4_relu_explicit":
            failures.append(
                f"unexpected ReLU activation subtask slot: {activation.subtask_slot}"
            )
        if activation.generated_csv_candidate_status != "closed":
            failures.append("ReLU generated subtask4 CSV candidate should be closed")
        if activation.explicit_task_activation_status != "closed":
            failures.append("ReLU explicit task activation should be closed")
        if activation.op_chain_activation_status != "closed":
            failures.append("ReLU op-chain activation should be closed")
        if activation.local_decode_roundtrip_status != "closed":
            failures.append("ReLU local IMM/HMAX decode roundtrip should be closed")
        if activation.runtime_selector_trace_status != "p0_blocked":
            failures.append(
                "ReLU runtime selector trace should stay blocked, got "
                f"{activation.runtime_selector_trace_status}"
            )
        if activation.remaining_artifacts != ("active_subtask4_runtime_selector_trace",):
            failures.append(
                "unexpected ReLU activation remaining artifacts: "
                f"{activation.remaining_artifacts}"
            )
        if activation.decoded_ops != ("IMM", "HMAX"):
            failures.append(f"unexpected decoded ReLU ops: {activation.decoded_ops}")
        if activation.decoded_opcode_values != (0x22, 0x53):
            failures.append(
                "unexpected decoded ReLU opcodes: "
                f"{activation.decoded_opcode_values}"
            )
        if activation.decoded_src_operands[1][:2] != (128, 0):
            failures.append(
                "decoded HMAX should consume zero then input, got "
                f"{activation.decoded_src_operands[1]}"
            )
        if activation.decoded_dst_operands[1][0] != 256:
            failures.append(
                "decoded HMAX output should bind to ReLU output operand 256, got "
                f"{activation.decoded_dst_operands[1]}"
            )

    if failures:
        print("stream compiler ReLU fiber chain check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler ReLU fiber chain check OK")
    print(f"fiber_count={summary['fiber_count']}")
    print(f"op_sequence_counts={summary['op_sequence_counts']}")
    print(
        "relu_template_binding_status_counts="
        f"{summary['relu_template_binding_status_counts']}"
    )
    print(f"template_binding_gaps={summary['template_binding_gaps']}")
    print(f"production_role_counts={executable_summary['role_counts']}")
    print(f"template_status_counts={template_summary['status_counts']}")
    print(f"relu_binding_status={relu_binding_summary['binding_status']}")
    print(f"relu_writer_blockers={relu_binding_summary['p0_blocker_ids']}")
    print(
        "relu_exact_row_selector_status_counts="
        f"{relu_binding_summary['exact_row_selector_status_counts']}"
    )
    print(
        "relu_row_byte_proof_plan_status_counts="
        f"{relu_binding_summary['row_byte_proof_plan_status_counts']}"
    )
    print(f"writer_binding_status_counts={writer_summary['binding_status_counts']}")
    print(f"layout_runnability_state={layout_summary['runnability_state']}")


if __name__ == "__main__":
    main()
