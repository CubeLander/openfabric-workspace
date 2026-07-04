"""Legacy DFU architecture backend.

This module owns vendor/architecture-specific symbolic instruction expansion.
It deliberately stays outside ``gpdpu_compiler.core`` so the compiler core can
remain device-independent, and so private hardware backends can later be split
into separately distributed packages.

VENDOR_BOUNDARY: legacy_dfu. This is the current target backend, not portable
compiler core.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from gpdpu_compiler.arch.base import ArchitectureBackend


class LegacyDFUBackend(ArchitectureBackend):
    """Symbolic backend for the legacy DFU tensor instruction path."""

    name = "legacy_dfu"

    def expand(self, tile_backend: dict[str, Any]) -> dict[str, Any]:
        templates: dict[str, dict[str, Any]] = {}
        instances: list[dict[str, Any]] = []

        for pe, program in sorted(tile_backend.get("tile_programs", {}).items()):
            for phase in program.get("phases", []):
                if phase.get("phase_kind") == "local_gemm_summa":
                    template = self.expand_gemm_tile_update(phase)
                    templates.setdefault(template["template_id"], template)
                    for update in phase.get("payload", {}).get("k_block_updates", []):
                        instances.append(_gemm_instruction_instance(pe, phase, update, template))
                else:
                    template = _legacy_dfu_generic_template(phase)
                    templates.setdefault(template["template_id"], template)
                    instances.append(_generic_instruction_instance(pe, phase, template))

        return {
            "backend": self.name,
            "lowering_boundary": "ktile_step_program -> architecture_specific_instruction_template",
            "route_independent": True,
            "instruction_templates": templates,
            "instruction_instances": instances,
            "totals": {
                "template_count": len(templates),
                "instance_count": len(instances),
                "expanded_instruction_count": sum(
                    int(instance["instruction_count"]) for instance in instances
                ),
            },
        }

    def expand_gemm_tile_update(self, phase: dict[str, Any]) -> dict[str, Any]:
        return _legacy_dfu_gemm_template(phase)


def build_architecture_backend_plan(tile_backend: dict[str, Any]) -> dict[str, Any]:
    """Build a symbolic legacy-DFU instruction-template plan.

    The returned records are still symbolic. They are concrete enough for human
    review and later CSV emission, but they do not pretend to be packed binary
    instructions.
    """

    return LegacyDFUBackend().expand(tile_backend)


def build_assembly_backend_plan(
    tile_backend: dict[str, Any],
    route_lowering: dict[str, Any],
    architecture_backend: dict[str, Any],
) -> dict[str, Any]:
    """Build structured DFU assembly records.

    This is the target-level fact source for later binary encoding. It remains
    symbolic: records are tied to tasks, subtasks, instances, operands, tile
    refs, and route refs, but no bitfields are emitted here.
    """

    compute_records = _compute_assembly_records(architecture_backend)
    route_records = _route_edge_assembly_records(route_lowering)
    store_records = _store_tile_assembly_records(tile_backend)
    templates = _assembly_template_refs(architecture_backend)
    all_records = compute_records + route_records + store_records

    role_counts: dict[str, int] = {}
    for record in all_records:
        role = str(record.get("role", "-"))
        role_counts[role] = role_counts.get(role, 0) + 1

    return {
        "schema_version": 1,
        "backend": "legacy_dfu",
        "lowering_boundary": "architecture_expansion + route_lowering -> structured_dfu_assembly_records",
        "record_model": "template_records_plus_instance_bindings",
        "binary_encoded": False,
        "assembly_roles": [
            "gemm_inner_update",
            "conv2d_virtual_im2col",
            "elementwise_compute",
            "local_reduce",
            "materialize_route_edge",
            "store_tile",
        ],
        "templates": templates,
        "compute_records": compute_records,
        "route_edge_records": route_records,
        "store_records": store_records,
        "totals": {
            "template_count": len(templates),
            "compute_record_count": len(compute_records),
            "route_edge_record_count": len(route_records),
            "store_record_count": len(store_records),
            "assembly_record_count": len(all_records),
            "expanded_instruction_record_count": sum(
                int(record.get("instruction_count", 0)) for record in compute_records
            ),
        },
        "role_counts": dict(sorted(role_counts.items())),
    }


def _legacy_dfu_gemm_template(phase: dict[str, Any]) -> dict[str, Any]:
    payload = phase.get("payload", {})
    tile_sizes = payload.get("tile_sizes", {})
    tile_m = int(tile_sizes.get("m", 64) or 64)
    tile_n = int(tile_sizes.get("n", 64) or 64)
    tile_k = int(tile_sizes.get("k", 64) or 64)
    tmp_regs = _ceildiv(tile_m, 4)
    type_regs = _ceildiv(tile_k, 4)
    template_kind = str(payload.get("template_kind", "summa_gemm_64x64x64_fp16"))
    template_id = f"legacy_dfu:{template_kind}:{tile_m}x{tile_n}x{tile_k}"
    records = _legacy_dfu_gemm_template_records(
        template_id=template_id,
        tile_m=tile_m,
        tile_n=tile_n,
        tile_k=tile_k,
        tmp_regs=tmp_regs,
        type_regs=type_regs,
    )
    counts = Counter(str(record["opcode"]) for record in records)
    return {
        "template_id": template_id,
        "backend": "legacy_dfu",
        "semantic_op": "gemm_tile_update",
        "template_kind": template_kind,
        "tile_shape": f"{tile_m}x{tile_n}x{tile_k}",
        "record_counts": dict(sorted(counts.items())),
        "instruction_count": len(records),
        "register_model": {
            "tmp_regs": tmp_regs,
            "type_regs": type_regs,
            "accumulator_view": "tile_scope_member_values",
        },
        "records": records,
    }


def _legacy_dfu_gemm_template_records(
    *,
    template_id: str,
    tile_m: int,
    tile_n: int,
    tile_k: int,
    tmp_regs: int,
    type_regs: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def append(opcode: str, role: str, **fields: Any) -> None:
        records.append(
            {
                "pc": len(records),
                "template_id": template_id,
                "opcode": opcode,
                "role": role,
                **fields,
            }
        )

    for type_idx in range(type_regs):
        append(
            "B_HLDT",
            "load_b_strip",
            dst=f"type_reg[{type_idx}]",
            src="B_tile",
            k_frag=type_idx,
            n_span=f"0:{tile_n}",
        )

    for tmp_idx in range(tmp_regs):
        append(
            "HMUL_A",
            "prepare_a_strip",
            dst=f"tmp_reg[{tmp_idx}]",
            src="A_tile",
            m_frag=tmp_idx,
            k_span=f"0:{tile_k}",
        )

    for tmp_idx in range(tmp_regs):
        append(
            "RXINT",
            "init_accumulator_fragment",
            dst=f"acc_frag[{tmp_idx}]",
            src="zero_or_previous_accumulator",
            m_frag=tmp_idx,
        )

    for tmp_idx in range(tmp_regs):
        for type_idx in range(type_regs):
            for lane_pass in range(2):
                append(
                    "HMMAL",
                    "mma_fragment_update",
                    dst=f"acc_frag[{tmp_idx}]",
                    src_a=f"tmp_reg[{tmp_idx}]",
                    src_b=f"type_reg[{type_idx}]",
                    m_frag=tmp_idx,
                    k_frag=type_idx,
                    lane_pass=lane_pass,
                )

    for tmp_idx in range(tmp_regs):
        append(
            "TRCTT",
            "export_accumulator_fragment",
            dst="tile_scope_member_value",
            src=f"acc_frag[{tmp_idx}]",
            m_frag=tmp_idx,
        )

    return records


def _legacy_dfu_generic_template(phase: dict[str, Any]) -> dict[str, Any]:
    payload = phase.get("payload", {})
    local_ops = phase.get("local_ops", [])
    op_kind = str(local_ops[0]) if isinstance(local_ops, list) and local_ops else str(phase.get("phase_kind", "generic"))
    template_id = f"legacy_dfu:generic:{op_kind}"
    records = _legacy_dfu_generic_template_records(template_id, op_kind, payload)
    counts = Counter(str(record["opcode"]) for record in records)
    return {
        "template_id": template_id,
        "backend": "legacy_dfu",
        "semantic_op": op_kind,
        "template_kind": f"generic_{op_kind}",
        "tile_shape": "local_shard_or_scalar",
        "record_counts": dict(sorted(counts.items())),
        "instruction_count": len(records),
        "register_model": {
            "operand_model": "symbolic_local_tile_or_scalar",
            "tensor_tmp_registers": "backend_selected",
        },
        "records": records,
    }


def _legacy_dfu_generic_template_records(
    template_id: str,
    op_kind: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    attrs = payload.get("attrs", {}) if isinstance(payload, dict) else {}
    records: list[dict[str, Any]] = []

    def append(opcode: str, role: str, **fields: Any) -> None:
        records.append(
            {
                "pc": len(records),
                "template_id": template_id,
                "opcode": opcode,
                "role": role,
                **fields,
            }
        )

    if op_kind == "clamp_min":
        append("FMAX", "elementwise_clamp_min", scalar=attrs.get("min_value", "-"))
    elif op_kind == "log10":
        append("FLOG2", "elementwise_log2", dst="tmp_log2", src="input")
        append("FMUL", "elementwise_log10_scale", scalar="log10(2)")
    elif op_kind == "reduce_max":
        append("FMAX_REDUCE_SYMBOLIC", "local_reduce_max")
    elif op_kind == "maximum":
        append("FMAX", "elementwise_maximum")
    elif op_kind == "add_scalar":
        append("FADD", "elementwise_add_scalar", scalar=attrs.get("scalar", "-"))
    elif op_kind == "mul_scalar":
        append("FMUL", "elementwise_mul_scalar", scalar=attrs.get("scalar", "-"))
    elif op_kind == "affine":
        append("FMUL", "elementwise_affine_scale", scalar=attrs.get("scale", "-"))
        append("FADD", "elementwise_affine_bias", scalar=attrs.get("bias", "-"))
    elif op_kind == "conv2d":
        append("VIM2COL_VIEW_SYMBOLIC", "activation_window_view")
        append("HMMAL_SYMBOLIC", "virtual_im2col_gemm_update")
    elif op_kind == "relu":
        append("FMAX", "elementwise_relu", scalar=0.0)
    else:
        append("GENERIC_ELEMENTWISE_SYMBOLIC", f"generic_{op_kind}")
    return records


def _gemm_instruction_instance(
    pe: str,
    phase: dict[str, Any],
    update: dict[str, Any],
    template: dict[str, Any],
) -> dict[str, Any]:
    a_tile = update.get("a_tile", {})
    b_tile = update.get("b_tile", {})
    return {
        "instance_id": _instruction_instance_id(pe, phase, update),
        "backend": "legacy_dfu",
        "pe": pe,
        "phase_id": phase.get("phase_id", "-"),
        "task_id": phase.get("task_id", "-"),
        "k_instance_id": update.get("instance_id", "-"),
        "semantic_op": "gemm_tile_update",
        "template_id": template["template_id"],
        "instruction_count": template["instruction_count"],
        "record_counts": template["record_counts"],
        "bindings": {
            "A_tile": a_tile.get("tile_ref", "-"),
            "B_tile": b_tile.get("tile_ref", "-"),
            "accumulator_view": update.get("accumulator_view_ref", "-"),
            "member_value": update.get("member_value_ref", "-"),
            "row_visibility_instance": update.get("row_broadcast_bundle_id", "-"),
            "column_visibility_instance": update.get("column_broadcast_bundle_id", "-"),
        },
    }


def _generic_instruction_instance(
    pe: str,
    phase: dict[str, Any],
    template: dict[str, Any],
) -> dict[str, Any]:
    payload = phase.get("payload", {})
    input_values = payload.get("input_values", []) if isinstance(payload, dict) else []
    output_values = payload.get("output_values", []) if isinstance(payload, dict) else []
    local_ops = phase.get("local_ops", [])
    op_kind = str(local_ops[0]) if isinstance(local_ops, list) and local_ops else str(phase.get("phase_kind", "generic"))
    phase_id = str(phase.get("phase_id", "-"))
    return {
        "instance_id": f"{pe}:{phase_id}:local",
        "backend": "legacy_dfu",
        "pe": pe,
        "phase_id": phase_id,
        "task_id": phase.get("task_id", "-"),
        "k_instance_id": "local",
        "semantic_op": op_kind,
        "template_id": template["template_id"],
        "instruction_count": template["instruction_count"],
        "record_counts": template["record_counts"],
        "bindings": {
            "input_tiles": [
                value.get("tile_ref", "-")
                for value in input_values
                if isinstance(value, dict)
            ],
            "output_tiles": [
                value.get("tile_ref", "-")
                for value in output_values
                if isinstance(value, dict)
            ],
            "collective_refs": list(phase.get("collective_refs", [])),
            "attrs": payload.get("attrs", {}) if isinstance(payload, dict) else {},
        },
    }


def _compute_assembly_records(architecture_backend: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for instance in architecture_backend.get("instruction_instances", []):
        if instance.get("semantic_op") != "gemm_tile_update":
            records.append(_generic_compute_assembly_record(instance))
            continue
        bindings = instance.get("bindings", {})
        phase_id = str(instance.get("phase_id", "-"))
        pe = str(instance.get("pe", "-"))
        k_instance_id = instance.get("k_instance_id", "-")
        row_bundle = bindings.get("row_visibility_instance", "-")
        column_bundle = bindings.get("column_visibility_instance", "-")
        row_route = _route_ref_from_bundle_id(row_bundle)
        column_route = _route_ref_from_bundle_id(column_bundle)
        a_tile = bindings.get("A_tile", "-")
        b_tile = bindings.get("B_tile", "-")
        accumulator_view = bindings.get("accumulator_view", "-")
        member_value = bindings.get("member_value", "-")
        records.append(
            {
                "assembly_id": f"asm:compute:{pe}:{phase_id}:k{k_instance_id}",
                "backend": "legacy_dfu",
                "opcode": "TEMPLATE_CALL",
                "role": "gemm_inner_update",
                "source_step": f"K_TILE_STEP:{pe}:{phase_id}:inst{k_instance_id}",
                "source_route_refs": [row_route, column_route],
                "deps": [row_route, column_route],
                "pe": pe,
                "phase_id": phase_id,
                "wave_id": _wave_id(phase_id),
                "task_id": instance.get("task_id", "-"),
                "subtask_id": 1,
                "instance_id": k_instance_id,
                "k_id": k_instance_id,
                "template_id": instance.get("template_id", "-"),
                "instruction_count": instance.get("instruction_count", 0),
                "record_counts": instance.get("record_counts", {}),
                "inputs": [
                    {"operand": "A", "tile": a_tile, "route_ref": row_route},
                    {"operand": "B", "tile": b_tile, "route_ref": column_route},
                ],
                "output": {
                    "accumulator_view": accumulator_view,
                    "member_value": member_value,
                },
                "operands": {
                    "A_tile": a_tile,
                    "B_tile": b_tile,
                    "accumulator_view": accumulator_view,
                    "member_value": member_value,
                },
                "base_addr_refs": {
                    "base0": "A_tile_runtime_base",
                    "base1": "B_tile_runtime_base",
                    "base2": "accumulator_or_workspace_base",
                    "base3": "reserved",
                },
                "binary_status": "unencoded",
            }
        )
    return records


def _generic_compute_assembly_record(instance: dict[str, Any]) -> dict[str, Any]:
    bindings = instance.get("bindings", {})
    phase_id = str(instance.get("phase_id", "-"))
    pe = str(instance.get("pe", "-"))
    op_kind = str(instance.get("semantic_op", "generic"))
    collective_refs = [str(ref) for ref in bindings.get("collective_refs", [])]
    route_refs = [_route_ref_from_bundle_id(ref) for ref in collective_refs]
    if op_kind == "conv2d":
        role = "conv2d_virtual_im2col"
    elif "reduce" in op_kind:
        role = "local_reduce"
    else:
        role = "elementwise_compute"
    return {
        "assembly_id": f"asm:compute:{pe}:{phase_id}:local",
        "backend": "legacy_dfu",
        "opcode": "TEMPLATE_CALL",
        "role": role,
        "source_step": f"GENERIC_TILE_OP:{pe}:{phase_id}",
        "source_route_refs": [],
        "deps": [],
        "pe": pe,
        "phase_id": phase_id,
        "wave_id": _wave_id(phase_id),
        "task_id": instance.get("task_id", "-"),
        "subtask_id": 0 if role == "local_reduce" else 1,
        "instance_id": "local",
        "k_id": "local",
        "semantic_op": op_kind,
        "tile_op_id": f"op:{op_kind}:{pe}:{phase_id}",
        "template_id": instance.get("template_id", "-"),
        "instruction_count": instance.get("instruction_count", 0),
        "record_counts": instance.get("record_counts", {}),
        "inputs": [
            {"operand": f"input{index}", "tile": tile, "route_ref": "-"}
            for index, tile in enumerate(bindings.get("input_tiles", []))
        ],
        "output": {
            "tiles": list(bindings.get("output_tiles", [])),
            "collective_refs": collective_refs,
            "route_refs": route_refs,
        },
        "operands": {
            "input_tiles": list(bindings.get("input_tiles", [])),
            "output_tiles": list(bindings.get("output_tiles", [])),
            "attrs": bindings.get("attrs", {}),
        },
        "base_addr_refs": {
            "base0": "generic_input_runtime_base",
            "base1": "generic_output_runtime_base",
            "base2": "generic_scalar_or_workspace_base",
            "base3": "reserved",
        },
        "binary_status": "unencoded",
    }


def _route_edge_assembly_records(route_lowering: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    routes = route_lowering.get("routes", {})
    if not isinstance(routes, dict):
        return records

    for route_id, route in sorted(routes.items()):
        obligation_key = route.get("obligation_key", "-")
        task_id, instance_id = _parse_obligation_task_instance(obligation_key)
        route_key = str(route_id).removeprefix("route:")
        operand = _parse_obligation_operand(obligation_key)
        tile_coord = _parse_source_tile_identity(route.get("source_tile_identity", "-"))
        for edge_idx, edge in enumerate(route.get("edges", [])):
            src = str(edge.get("from", "-"))
            dst = str(edge.get("to", "-"))
            records.append(
                {
                    "assembly_id": f"asm:route_edge:{route_key}:edge{edge_idx}",
                    "backend": "legacy_dfu",
                    "opcode": "COPYT_SYMBOLIC",
                    "role": "materialize_route_edge",
                    "source_step": "-",
                    "source_route": route_id,
                    "deps": [route_id],
                    "route_edge": f"{src}->{dst}",
                    "route": {
                        "src": src,
                        "dst": dst,
                        "edge_index": edge_idx,
                    },
                    "visibility": route.get("visibility", "-"),
                    "operand": operand,
                    "tile_coord": tile_coord,
                    "source_tile_identity": route.get("source_tile_identity", "-"),
                    "pe": src,
                    "task_id": task_id,
                    "subtask_id": 1,
                    "instance_id": instance_id,
                    "src_pe": src,
                    "dst_pe": dst,
                    "base_addr_refs": {
                        "base0": "route_source_tile_base",
                        "base1": "route_destination_tile_base",
                    },
                    "binary_status": "unencoded",
                }
            )
    return records


def _store_tile_assembly_records(tile_backend: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    output_tensors = tile_backend.get("output_tensors", {})
    if not isinstance(output_tensors, dict):
        output_tensors = {}
    for pe, program in sorted(tile_backend.get("tile_programs", {}).items()):
        for phase in program.get("phases", []):
            if phase.get("phase_kind") != "local_gemm_summa":
                records.extend(_generic_store_tile_records(pe, phase, output_tensors))
                continue
            payload = phase.get("payload", {})
            c_tile = payload.get("c_tile_wave", {})
            k_updates = payload.get("k_block_updates", [])
            last_k = k_updates[-1].get("instance_id", "-") if k_updates else "-"
            output_refs = phase.get("output_refs", [])
            phase_id = str(phase.get("phase_id", "-"))
            input_view = c_tile.get("accumulator_tile_ref", "-")
            output = output_refs[0] if output_refs else "-"
            last_compute_dep = f"asm:compute:{pe}:{phase_id}:k{last_k}" if last_k != "-" else "-"
            records.append(
                {
                    "assembly_id": f"asm:store:{pe}:{phase_id}",
                    "backend": "legacy_dfu",
                    "opcode": "STORE_TILE_SYMBOLIC",
                    "role": "store_tile",
                    "source_step": f"TILE_SCOPE:{pe}:{phase_id}:output",
                    "source_route": "-",
                    "deps": [last_compute_dep] if last_compute_dep != "-" else [],
                    "pe": pe,
                    "phase_id": phase_id,
                    "wave_id": _wave_id(phase_id),
                    "task_id": phase.get("task_id", "-"),
                    "subtask_id": 2,
                    "instance_id": 0,
                    "src_acc": input_view,
                    "dst_global": output,
                    "operands": {
                        "input_view": input_view,
                        "output": output,
                    },
                    "base_addr_refs": {
                        "base0": "output_tile_runtime_base",
                    },
                    "binary_status": "unencoded",
                }
            )
    return records


def _generic_store_tile_records(
    pe: str,
    phase: dict[str, Any],
    output_tensors: dict[str, Any],
) -> list[dict[str, Any]]:
    payload = phase.get("payload", {})
    if not isinstance(payload, dict):
        return []
    phase_id = str(phase.get("phase_id", "-"))
    output_values = [
        value for value in payload.get("output_values", [])
        if isinstance(value, dict)
    ]
    records: list[dict[str, Any]] = []
    for value in output_values:
        tensor = str(value.get("tensor", ""))
        output_name = output_tensors.get(tensor)
        if not output_name:
            continue
        input_view = str(value.get("tile_ref", "-"))
        compute_dep = f"asm:compute:{pe}:{phase_id}:local"
        records.append(
            {
                "assembly_id": f"asm:store:{pe}:{phase_id}:generic",
                "backend": "legacy_dfu",
                "opcode": "STORE_TILE_SYMBOLIC",
                "role": "store_tile",
                "source_step": f"GENERIC_TILE_OP:{pe}:{phase_id}:output",
                "source_route": "-",
                "deps": [compute_dep],
                "pe": pe,
                "phase_id": phase_id,
                "wave_id": _wave_id(phase_id),
                "task_id": 0,
                "subtask_id": 2,
                "instance_id": 0,
                "src_acc": input_view,
                "dst_global": str(output_name),
                "operands": {
                    "input_view": input_view,
                    "output": str(output_name),
                },
                "base_addr_refs": {
                    "base0": "output_tile_runtime_base",
                },
                "binary_status": "unencoded",
            }
        )
    return records


def _assembly_template_refs(architecture_backend: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    templates = architecture_backend.get("instruction_templates", {})
    if not isinstance(templates, dict):
        return result
    for template_id, template in sorted(templates.items()):
        result[str(template_id)] = {
            "template_id": template.get("template_id", template_id),
            "backend": template.get("backend", "-"),
            "semantic_op": template.get("semantic_op", "-"),
            "template_kind": template.get("template_kind", "-"),
            "tile_shape": template.get("tile_shape", "-"),
            "instruction_count": template.get("instruction_count", 0),
            "record_counts": template.get("record_counts", {}),
            "record_source": "architecture_backend.instruction_templates",
        }
    return result


def _route_ref_from_bundle_id(bundle_id: Any) -> str:
    return f"route:{_short_bundle_id(bundle_id)}"


def _short_bundle_id(bundle_id: Any) -> str:
    text = str(bundle_id)
    marker = ":lg0:"
    if marker in text:
        return text.split(marker, 1)[1]
    if text.startswith("bundle:"):
        return text.removeprefix("bundle:")
    return text


def _parse_obligation_task_instance(obligation_key: Any) -> tuple[int | str, int | str]:
    task_id: int | str = 0
    instance_id: int | str = 0
    for part in str(obligation_key).split(":"):
        if part.startswith("task"):
            try:
                task_id = int(part.removeprefix("task"))
            except ValueError:
                task_id = part
        elif part.startswith("k"):
            try:
                instance_id = int(part.removeprefix("k"))
            except ValueError:
                instance_id = part
    return task_id, instance_id


def _parse_obligation_operand(obligation_key: Any) -> str:
    parts = str(obligation_key).split(":")
    for part in parts:
        if part in {"A", "B", "C"}:
            return part
    return "-"


def _parse_source_tile_identity(source_tile_identity: Any) -> dict[str, Any]:
    parts = str(source_tile_identity).split(":")
    if len(parts) < 5 or parts[0] != "tile":
        return {"identity": str(source_tile_identity)}
    role = parts[2]
    coord0 = _parse_int(parts[3])
    coord1 = _parse_int(parts[4])
    coord_names = ("m_start", "k_start") if role == "A" else ("k_start", "n_start")
    return {
        "identity": str(source_tile_identity),
        "tensor": parts[1],
        "operand": role,
        coord_names[0]: coord0,
        coord_names[1]: coord1,
    }


def _wave_id(phase_id: Any) -> str:
    text = str(phase_id)
    if ":" in text:
        return text.rsplit(":", 1)[-1]
    return text


def _parse_int(value: Any) -> int | str:
    try:
        return int(str(value))
    except ValueError:
        return str(value)


def _instruction_instance_id(pe: str, phase: dict[str, Any], update: dict[str, Any]) -> str:
    return (
        f"{pe}:"
        f"{phase.get('phase_id', '-')}:"
        f"k{update.get('instance_id', '-')}"
    )


def _ceildiv(lhs: int, rhs: int) -> int:
    return (lhs + rhs - 1) // rhs
