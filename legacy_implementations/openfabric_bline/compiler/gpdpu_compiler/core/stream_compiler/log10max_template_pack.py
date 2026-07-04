"""S6 report-only local template pack for log10max.

This module captures the local elementwise/reduce template binding shape for
the current DFU-first log10max payload without depending on the GEMM template
pack or claiming a completed cross-processor scalar strategy.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import Literal

from gpdpu_compiler.core.program_legacy_inst import (
    INST_RECORD_SIZE_BYTES,
    LEGACY_OPS,
    LegacyInst,
    pack_legacy_inst,
)
from gpdpu_compiler.decoder.dfu3500_isa import annotate_opcode

JsonValue = object
TemplateStatus = Literal["ready_local", "external_symbolic"]
ScalarOrderingEvidenceStatus = Literal["missing", "incomplete", "complete"]

LOG10MAX_PROFILE_ID = "dfu3500_log10max_s6_local_template_pack_v1"
LOG10MAX_DTYPE = "fp32"
LOG10MAX_CLAMP_MIN = 1.0e-10
LOG10MAX_LOG10_2 = 0.3010299956639812
LOG10MAX_GLOBAL_THRESHOLD_OFFSET = -8.0
LOG10MAX_OUTPUT_BIAS = 4.0
LOG10MAX_OUTPUT_SCALE = 0.25
S5_UNRESOLVED_GLOBAL_SCALAR_INPUT = "external_symbolic_until_S5"
ISA_DOCS_ROOT = "docs/architecture/instruction-set/dfu3500-simd"
OPCODE_CONFORMANCE_CHECK = (
    "compiler/gpdpu_compiler/validation/dfu3500_package_checks/"
    "opcode_conformance_check.py"
)
OPCODE_BY_MNEMONIC = {
    "IMM": 0x022,
    "FIMM": 0x023,
    "FADD": 0x024,
    "FMUL": 0x026,
    "FMAX": 0x027,
    "SHFL": 0x029,
    "STD": 0x080,
    "FLOG2": 0x0D4,
    "HSTT": 0x105,
    "ILDMT": 0x107,
}
INST_STRUCT_FORMAT = "<I4xQQ3Q3Q3Q9Q3Q3Q3QQ3B3B2xQQQ3Q"


@dataclass(frozen=True)
class LocalTemplateStep:
    """One report-only local template binding row."""

    id: str
    op: str
    template_family: str
    status: TemplateStatus
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    instruction_intents: tuple[str, ...]
    opcode_evidence: tuple[dict[str, object], ...] = ()
    attrs: tuple[tuple[str, JsonValue], ...] = ()
    notes: tuple[str, ...] = ()

    def to_artifact(self) -> dict[str, object]:
        return {
            "id": self.id,
            "op": self.op,
            "template_family": self.template_family,
            "status": self.status,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "instruction_intents": list(self.instruction_intents),
            "opcode_evidence": [dict(evidence) for evidence in self.opcode_evidence],
            "attrs": dict(self.attrs),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ScalarVisibilitySource:
    """S5-provided PE00 scalar visibility contract consumed by S6b."""

    strategy: str
    source_name: str
    scratch_slot: str
    consumer_load_contract: dict[str, object]
    ordering_evidence_status: ScalarOrderingEvidenceStatus
    dtype: str = LOG10MAX_DTYPE
    producer_processor: str = "processor_0_0"
    source_kind: str = "pe00_materialized_replicated_scalar"

    def is_complete(self) -> bool:
        return not self.blockers()

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.strategy != "pe00_scalar_visibility":
            blockers.append("strategy must be pe00_scalar_visibility")
        if not self.source_name:
            blockers.append("source_name is required")
        if not self.scratch_slot:
            blockers.append("scratch_slot is required")
        if self.dtype != LOG10MAX_DTYPE:
            blockers.append(f"dtype must be {LOG10MAX_DTYPE}")
        if self.ordering_evidence_status != "complete":
            blockers.append("ordering_evidence_status must be complete")
        if not self.consumer_load_contract:
            blockers.append("consumer_load_contract is required")
        else:
            required = {
                "load_kind": "pe00_scalar_load_or_broadcast",
                "consumer": "s6a.step3.maximum_with_symbolic_global_scalar",
                "dtype": LOG10MAX_DTYPE,
            }
            for key, expected in required.items():
                if self.consumer_load_contract.get(key) != expected:
                    blockers.append(
                        f"consumer_load_contract.{key} must be {expected}"
                    )
        return tuple(blockers)

    def to_artifact(self) -> dict[str, object]:
        blockers = self.blockers()
        return {
            "schema_version": 1,
            "artifact_kind": "pe00_scalar_visibility_source",
            "strategy": self.strategy,
            "source_name": self.source_name,
            "scratch_slot": self.scratch_slot,
            "consumer_load_contract": dict(self.consumer_load_contract),
            "ordering_evidence_status": self.ordering_evidence_status,
            "dtype": self.dtype,
            "producer_processor": self.producer_processor,
            "source_kind": self.source_kind,
            "complete": not blockers,
            "blockers": list(blockers),
            "runtime_runnable_claim": False,
            "row_bytes_claim": False,
        }


@dataclass(frozen=True)
class Pe00VendorRowLoweringEntry:
    """One lowerable vendor-row intent for the PE00 scalar FiberOp.

    This is the handoff from B-line template contract to row materialization.
    It does not claim bytes; it names the exact row family and provenance a
    later writer must materialize.
    """

    row_intent_id: str
    stage: str
    template_family: str
    vendor_component: str
    subtask_slot: str
    instruction_intents: tuple[str, ...]
    producer_processor: str
    consumer_processors: tuple[str, ...] = ()
    source_operand: str = "local_max_scalar"
    destination_operand: str = "global_max_scalar"
    scratch_offset_bytes: int = 0
    dtype: str = LOG10MAX_DTYPE
    blocker_id: str = "row_bytes_missing"

    def to_artifact(self) -> dict[str, object]:
        proof_plan = _pe00_row_byte_proof_plan(
            stage=self.stage,
            template_family=self.template_family,
            subtask_slot=self.subtask_slot,
            instruction_intents=self.instruction_intents,
            source_operand=self.source_operand,
            destination_operand=self.destination_operand,
            scratch_offset_bytes=self.scratch_offset_bytes,
            dtype=self.dtype,
            consumer_processors=self.consumer_processors,
            blocker_id=self.blocker_id,
        )
        return {
            "row_intent_id": self.row_intent_id,
            "fiber_op": "global_max_tile",
            "stage": self.stage,
            "template_family": self.template_family,
            "vendor_component": self.vendor_component,
            "subtask_slot": self.subtask_slot,
            "instruction_intents": list(self.instruction_intents),
            "producer_processor": self.producer_processor,
            "consumer_processors": list(self.consumer_processors),
            "source_operand": self.source_operand,
            "destination_operand": self.destination_operand,
            "lowering_status": "contract_lowerable",
            "row_bytes_status": "blocked_missing_row_materializer",
            "blocker_id": self.blocker_id,
            "row_byte_proof_plan": proof_plan,
            "provenance_policy": (
                "primary_fiber_op_id=global_max_tile; no hidden FiberOp "
                "expansion; row materializer preserves stage provenance"
            ),
            "physical_route_allreduce": False,
            "row_bytes_claim": False,
        }


@dataclass(frozen=True)
class Pe00GlobalScalarTemplateContract:
    """Template-binding contract for the `global_max_tile` FiberOp."""

    source_id: str
    source_name: str
    scratch_slot: str
    scratch_offset_bytes: int
    consumer_processors: tuple[str, ...]
    runtime_order_contract: dict[str, object]
    receiver_binding_contract: dict[str, object]
    dtype: str = LOG10MAX_DTYPE
    producer_processor: str = "processor_0_0"

    @property
    def status(self) -> str:
        if not self.consumer_processors:
            return "blocked_missing_consumers"
        if self.runtime_order_contract.get("status") != "available":
            return "blocked_missing_runtime_order"
        if self.receiver_binding_contract.get("status") != "available":
            return "blocked_missing_receiver_binding"
        return "available"

    def scalar_source(self) -> ScalarVisibilitySource:
        return ScalarVisibilitySource(
            strategy="pe00_scalar_visibility",
            source_name=self.source_name,
            scratch_slot=self.scratch_slot,
            consumer_load_contract={
                "load_kind": "pe00_scalar_load_or_broadcast",
                "consumer": "s6a.step3.maximum_with_symbolic_global_scalar",
                "dtype": self.dtype,
                "visibility_kind": "replicated_scalar",
                "threshold_transform": {
                    "op": "add_scalar",
                    "constant": LOG10MAX_GLOBAL_THRESHOLD_OFFSET,
                },
                "source_id": self.source_id,
                "scratch_slot": self.scratch_slot,
                "receiver_binding_contract_status": (
                    self.receiver_binding_contract.get("status")
                ),
            },
            ordering_evidence_status=(
                "complete" if self.status == "available" else "incomplete"
            ),
        )

    def to_artifact(self) -> dict[str, object]:
        vendor_row_lowering_plan = _pe00_vendor_row_lowering_plan(
            source_id=self.source_id,
            scratch_slot=self.scratch_slot,
            scratch_offset_bytes=self.scratch_offset_bytes,
            producer_processor=self.producer_processor,
            consumer_processors=self.consumer_processors,
            dtype=self.dtype,
            contract_status=self.status,
        )
        row_proof_by_stage = {
            str(entry["stage"]): entry["row_byte_proof_plan"]
            for entry in vendor_row_lowering_plan["entries"]
        }
        return {
            "schema_version": 1,
            "artifact_kind": "pe00_global_scalar_template_contract",
            "fiber_op": "global_max_tile",
            "strategy": "pe00_aggregate_materialize",
            "customer_label": "pe00_materialized_scalar",
            "source_id": self.source_id,
            "source_name": self.source_name,
            "scratch_slot": self.scratch_slot,
            "scratch_offset_bytes": self.scratch_offset_bytes,
            "dtype": self.dtype,
            "producer_processor": self.producer_processor,
            "consumer_processors": list(self.consumer_processors),
            "status": self.status,
            "producer_pe00_physical_store": {
                "status": "available" if self.status == "available" else "blocked",
                "template_family": "pe00_scalar_scratch_store",
                "instruction_intents": [
                    "FMAX ordered scalar combine",
                    "STD scalar scratch store",
                ],
                "source_id": self.source_id,
                "scratch_slot": self.scratch_slot,
                "producer_processor": self.producer_processor,
                "row_byte_proof_plan": row_proof_by_stage[
                    "producer_pe00_physical_store"
                ],
                "row_bytes_claim": False,
            },
            "consumer_physical_readback": {
                "status": "available" if self.status == "available" else "blocked",
                "template_family": "pe00_scalar_scratch_readback",
                "instruction_intents": [
                    "ILDMT scalar scratch load",
                    "receiver-owned scalar operand bind",
                ],
                "consumer_processors": list(self.consumer_processors),
                "row_byte_proof_plan": row_proof_by_stage[
                    "consumer_physical_readback"
                ],
                "row_bytes_claim": False,
            },
            "pe00_fmax_combine_order": {
                "status": "available" if self.status == "available" else "blocked",
                "combine_kind": "ordered_fmax_tree_over_local_max_scalars",
                "input_order": list(self.consumer_processors),
                "output": "global_max_scalar",
                "producer_processor": self.producer_processor,
                "row_byte_proof_plan": row_proof_by_stage[
                    "pe00_fmax_combine_order"
                ],
                "row_bytes_claim": False,
            },
            "runtime_order_contract": dict(self.runtime_order_contract),
            "receiver_binding_contract": dict(self.receiver_binding_contract),
            "scalar_visibility_source": self.scalar_source().to_artifact(),
            "vendor_row_lowering_plan": vendor_row_lowering_plan,
            "physical_route_allreduce": False,
            "runtime_runnable_claim": False,
            "row_bytes_claim": False,
        }


def build_pe00_global_scalar_template_contract(
    *,
    source_id: str,
    source_name: str,
    scratch_slot: str,
    scratch_offset_bytes: int,
    consumer_processors: tuple[str, ...],
    runtime_order_contract: dict[str, object],
    receiver_binding_contract: dict[str, object],
) -> Pe00GlobalScalarTemplateContract:
    """Build the S6b template-binding contract for `global_max_tile`."""

    return Pe00GlobalScalarTemplateContract(
        source_id=source_id,
        source_name=source_name,
        scratch_slot=scratch_slot,
        scratch_offset_bytes=scratch_offset_bytes,
        consumer_processors=consumer_processors,
        runtime_order_contract=runtime_order_contract,
        receiver_binding_contract=receiver_binding_contract,
    )


def _pe00_vendor_row_lowering_plan(
    *,
    source_id: str,
    scratch_slot: str,
    scratch_offset_bytes: int,
    producer_processor: str,
    consumer_processors: tuple[str, ...],
    dtype: str,
    contract_status: str,
) -> dict[str, object]:
    entries = (
        Pe00VendorRowLoweringEntry(
            row_intent_id="global_max_tile.pe00_fmax_combine.rows",
            stage="pe00_fmax_combine_order",
            template_family="ordered_fmax_tree_over_local_max_scalars",
            vendor_component="inst_t",
            subtask_slot="subtask_log10max_global_max_pe00_combine",
            instruction_intents=("FMAX",),
            producer_processor=producer_processor,
            consumer_processors=consumer_processors,
            source_operand="local_max_scalar_by_consumer_pe",
            destination_operand="pe00_global_max_scalar_accumulator",
            scratch_offset_bytes=scratch_offset_bytes,
            dtype=dtype,
            blocker_id="pe00_fmax_combine_order_row_bytes_missing",
        ),
        Pe00VendorRowLoweringEntry(
            row_intent_id="global_max_tile.pe00_scalar_store.rows",
            stage="producer_pe00_physical_store",
            template_family="pe00_scalar_scratch_store",
            vendor_component="inst_t",
            subtask_slot="subtask_log10max_global_max_pe00_store",
            instruction_intents=("STD",),
            producer_processor=producer_processor,
            source_operand="pe00_global_max_scalar_accumulator",
            destination_operand=scratch_slot,
            scratch_offset_bytes=scratch_offset_bytes,
            dtype=dtype,
            blocker_id="producer_pe00_physical_store_row_bytes_missing",
        ),
        Pe00VendorRowLoweringEntry(
            row_intent_id="global_max_tile.consumer_scalar_readback.rows",
            stage="consumer_physical_readback",
            template_family="pe00_scalar_scratch_readback",
            vendor_component="inst_t",
            subtask_slot="subtask_log10max_global_max_consumer_readback",
            instruction_intents=("ILDMT",),
            producer_processor=producer_processor,
            consumer_processors=consumer_processors,
            source_operand=scratch_slot,
            destination_operand="receiver_owned_global_max_scalar_operand",
            scratch_offset_bytes=scratch_offset_bytes,
            dtype=dtype,
            blocker_id="consumer_physical_readback_row_bytes_missing",
        ),
    )
    entry_artifacts = [entry.to_artifact() for entry in entries]
    proof_plans = [
        artifact["row_byte_proof_plan"] for artifact in entry_artifacts
    ]
    materialization_requests = [
        plan["materialization_request"] for plan in proof_plans
    ]
    return {
        "schema_version": 1,
        "artifact_kind": "pe00_global_scalar_vendor_row_lowering_plan",
        "fiber_op": "global_max_tile",
        "strategy": "pe00_aggregate_materialize",
        "customer_label": "pe00_materialized_scalar",
        "source_id": source_id,
        "scratch_slot": scratch_slot,
        "scratch_offset_bytes": scratch_offset_bytes,
        "dtype": dtype,
        "status": (
            "vendor_row_intents_available_synthetic_decode_roundtrip_available_active_selector_missing"
            if contract_status == "available"
            else "blocked_missing_template_contract"
        ),
        "entry_count": len(entries),
        "entries": entry_artifacts,
        "row_byte_proof_summary": {
            "schema_version": 1,
            "artifact_kind": "pe00_global_scalar_row_byte_proof_summary",
            "status": (
                "blocked_synthetic_decode_roundtrip_available_"
                "active_selector_missing"
            ),
            "stage_count": len(proof_plans),
            "stages": [str(plan["stage"]) for plan in proof_plans],
            "blocker_ids": [
                str(blocker["blocker_id"])
                for plan in proof_plans
                for blocker in plan["proof_blockers"]
            ],
            "missing_field_counts": {
                str(plan["stage"]): len(plan["missing_fields"])
                for plan in proof_plans
            },
            "materialization_request_count": len(materialization_requests),
            "expected_row_counts": {
                str(request["stage"]): request["expected_row_count"]
                for request in materialization_requests
            },
            "materialization_artifacts": {
                str(request["stage"]): request["required_output_artifacts"]
                for request in materialization_requests
            },
            "row_candidate_recipe_status_counts": {
                "candidate_recipe_available_synthetic_decode_roundtrip_available_active_selector_missing": (
                    len(proof_plans)
                ),
            },
            "row_candidate_recipe_artifacts": {
                str(plan["stage"]): plan["row_candidate_recipe"][
                    "row_candidate_recipe_artifact"
                ]
                for plan in proof_plans
            },
            "runtime_runnable_claim": False,
            "row_bytes_claim": False,
            "physical_route_allreduce": False,
        },
        "remaining_row_byte_blockers": [
            "pe00_fmax_combine_order_row_bytes_missing",
            "producer_pe00_physical_store_row_bytes_missing",
            "consumer_physical_readback_row_bytes_missing",
        ],
        "runtime_runnable_claim": False,
        "row_bytes_claim": False,
        "physical_route_allreduce": False,
        "layering_policy": (
            "global_max_tile is one communication FiberOp; these rows are "
            "downstream template expansion intents, not new FiberOps"
        ),
    }


def _pe00_row_byte_proof_plan(
    *,
    stage: str,
    template_family: str,
    subtask_slot: str,
    instruction_intents: tuple[str, ...],
    source_operand: str,
    destination_operand: str,
    scratch_offset_bytes: int,
    dtype: str,
    consumer_processors: tuple[str, ...],
    blocker_id: str,
) -> dict[str, object]:
    closed_fields = [
        "primary_fiber_op_id",
        "stage",
        "template_family",
        "subtask_slot",
        "instruction_intents",
        "source_operand",
        "destination_operand",
        "scratch_offset_bytes",
        "dtype",
    ]
    missing_by_stage = {
        "pe00_fmax_combine_order": [
            "legacy_fmax_row_selector",
            "active_fmax_template_family_source",
            "exact_local_max_input_operand_order_roundtrip",
            "pe00_accumulator_operand_encoding_roundtrip",
            "expanded_row_sequence_local_order_decode_roundtrip",
        ],
        "producer_pe00_physical_store": [
            "legacy_scalar_store_row_selector",
            "active_scalar_store_template_family_source",
            "scratch_address_operand_encoding_roundtrip",
            "store_memory_scope_flags_roundtrip",
            "store_source_operand_encoding_roundtrip",
        ],
        "consumer_physical_readback": [
            "legacy_scalar_readback_row_selector",
            "active_scalar_readback_template_family_source",
            "per_consumer_destination_operand_indices_roundtrip",
            "scratch_address_operand_encoding_roundtrip",
            "readback_memory_scope_flags_roundtrip",
        ],
    }
    selector_requirements_by_stage = {
        "pe00_fmax_combine_order": {
            "selector_id": "PE00_FMAX_LOCAL_MAX_CHAIN_SELECTOR_V1",
            "legacy_template_family": "FMAX",
            "required_shape": "ordered scalar FMAX chain over every local_max input",
            "row_count_policy": "consumer_count_minus_one_or_single_accumulator_chain",
            "forbidden_shortcut": "direct_route_allreduce",
        },
        "producer_pe00_physical_store": {
            "selector_id": "PE00_SCALAR_SCRATCH_STD_SELECTOR_V1",
            "legacy_template_family": "STD",
            "required_shape": "one PE00 scalar scratch store after FMAX combine",
            "row_count_policy": "exactly_one_store_row",
            "forbidden_shortcut": "store_hidden_inside_compute_op",
        },
        "consumer_physical_readback": {
            "selector_id": "PE00_SCALAR_SCRATCH_READBACK_SELECTOR_V1",
            "legacy_template_family": "ILDMT",
            "required_shape": "one scalar readback row per consumer processor",
            "row_count_policy": "exactly_consumer_count_readback_rows",
            "forbidden_shortcut": "implicit_receiver_broadcast",
        },
    }
    operand_encoding_contract_by_stage = {
        "pe00_fmax_combine_order": {
            "source_encoding": "per_consumer_local_max_scalar_operand",
            "destination_encoding": "pe00_global_max_scalar_accumulator_operand",
            "ordering_key": "consumer_processors",
            "scratch_address_encoding_required": False,
        },
        "producer_pe00_physical_store": {
            "source_encoding": "pe00_global_max_scalar_accumulator_operand",
            "destination_encoding": "scratch_slot_address_operand",
            "ordering_key": "producer_processor",
            "scratch_address_encoding_required": True,
        },
        "consumer_physical_readback": {
            "source_encoding": "scratch_slot_address_operand",
            "destination_encoding": "receiver_owned_global_max_scalar_operand",
            "ordering_key": "consumer_processors",
            "scratch_address_encoding_required": True,
        },
    }
    decode_roundtrip_contract_by_stage = {
        "pe00_fmax_combine_order": {
            "decoded_opcode_sequence": ["FMAX"],
            "decoded_must_reference": [
                "local_max_scalar_by_consumer_pe",
                "pe00_global_max_scalar_accumulator",
            ],
            "roundtrip_artifact": "pe00_fmax_combine_decoded_rows.json",
        },
        "producer_pe00_physical_store": {
            "decoded_opcode_sequence": ["STD"],
            "decoded_must_reference": [
                "pe00_global_max_scalar_accumulator",
                "scratch_offset_bytes",
            ],
            "roundtrip_artifact": "pe00_scalar_store_decoded_rows.json",
        },
        "consumer_physical_readback": {
            "decoded_opcode_sequence": ["ILDMT"],
            "decoded_must_reference": [
                "scratch_offset_bytes",
                "receiver_owned_global_max_scalar_operand",
            ],
            "roundtrip_artifact": "pe00_scalar_readback_decoded_rows.json",
        },
    }
    expected_row_count_by_stage = {
        "pe00_fmax_combine_order": max(len(consumer_processors) - 1, 1),
        "producer_pe00_physical_store": 1,
        "consumer_physical_readback": len(consumer_processors),
    }
    selected_rows_artifact_by_stage = {
        "pe00_fmax_combine_order": "pe00_fmax_combine_selected_rows.json",
        "producer_pe00_physical_store": "pe00_scalar_store_selected_rows.json",
        "consumer_physical_readback": "pe00_scalar_readback_selected_rows.json",
    }
    raw_rows_artifact_by_stage = {
        "pe00_fmax_combine_order": "pe00_fmax_combine_raw_inst_t_rows.bin",
        "producer_pe00_physical_store": "pe00_scalar_store_raw_inst_t_rows.bin",
        "consumer_physical_readback": "pe00_scalar_readback_raw_inst_t_rows.bin",
    }
    raw_hash_artifact_by_stage = {
        "pe00_fmax_combine_order": "pe00_fmax_combine_raw_template_row_sha256.json",
        "producer_pe00_physical_store": "pe00_scalar_store_raw_template_row_sha256.json",
        "consumer_physical_readback": "pe00_scalar_readback_raw_template_row_sha256.json",
    }
    selector = selector_requirements_by_stage[stage]
    operand_contract = operand_encoding_contract_by_stage[stage]
    decode_contract = decode_roundtrip_contract_by_stage[stage]
    row_candidate_recipe = _pe00_row_candidate_recipe(
        stage=stage,
        selector_id=str(selector["selector_id"]),
        expected_row_count=int(expected_row_count_by_stage[stage]),
        subtask_slot=subtask_slot,
        instruction_intents=instruction_intents,
        producer_processor="processor_0_0",
        consumer_processors=consumer_processors,
        source_operand=source_operand,
        destination_operand=destination_operand,
        scratch_offset_bytes=scratch_offset_bytes,
        dtype=dtype,
    )
    materialization_request = {
        "schema_version": 1,
        "artifact_kind": "pe00_global_scalar_row_materialization_request",
        "fiber_op": "global_max_tile",
        "stage": stage,
        "status": (
            "materialization_request_available_synthetic_decode_roundtrip_available_"
            "active_selector_missing"
        ),
        "selector_id": selector["selector_id"],
        "template_family": template_family,
        "instruction_intents": list(instruction_intents),
        "subtask_slot": subtask_slot,
        "expected_row_count": expected_row_count_by_stage[stage],
        "row_count_policy": selector["row_count_policy"],
        "consumer_processors": list(consumer_processors),
        "source_operand": source_operand,
        "destination_operand": destination_operand,
        "operand_encoding_contract": operand_contract,
        "scratch_address": {
            "scratch_offset_bytes": scratch_offset_bytes,
            "encoding_required": operand_contract[
                "scratch_address_encoding_required"
            ],
        },
        "selected_rows_artifact": selected_rows_artifact_by_stage[stage],
        "row_candidate_recipe_artifact": (
            row_candidate_recipe["row_candidate_recipe_artifact"]
        ),
        "row_candidate_recipe_status": row_candidate_recipe["status"],
        "materializer_input_contract": row_candidate_recipe[
            "materializer_input_contract"
        ],
        "raw_rows_artifact": raw_rows_artifact_by_stage[stage],
        "raw_hash_artifact": raw_hash_artifact_by_stage[stage],
        "decode_roundtrip_artifact": decode_contract["roundtrip_artifact"],
        "required_output_artifacts": [
            row_candidate_recipe["row_candidate_recipe_artifact"],
            selected_rows_artifact_by_stage[stage],
            raw_rows_artifact_by_stage[stage],
            raw_hash_artifact_by_stage[stage],
            decode_contract["roundtrip_artifact"],
        ],
        "blocked_on": [
            blocker_id,
        ],
        "runtime_runnable_claim": False,
        "row_bytes_claim": False,
        "physical_route_allreduce": False,
    }
    return {
        "schema_version": 1,
        "artifact_kind": "pe00_global_scalar_row_byte_proof_plan",
        "fiber_op": "global_max_tile",
        "stage": stage,
        "status": (
            "blocked_synthetic_decode_roundtrip_available_active_selector_missing"
        ),
        "template_family": template_family,
        "subtask_slot": subtask_slot,
        "instruction_intents": list(instruction_intents),
        "source_operand": source_operand,
        "destination_operand": destination_operand,
        "scratch_offset_bytes": scratch_offset_bytes,
        "dtype": dtype,
        "consumer_count": len(consumer_processors),
        "closed_fields": closed_fields,
        "missing_fields": missing_by_stage[stage],
        "selector_requirements": selector,
        "operand_encoding_contract": operand_contract,
        "decode_roundtrip_contract": decode_contract,
        "row_candidate_recipe": row_candidate_recipe,
        "materializer_input_contract": row_candidate_recipe[
            "materializer_input_contract"
        ],
        "materialization_request": materialization_request,
        "required_proof_artifacts": [
            row_candidate_recipe["row_candidate_recipe_artifact"],
            selected_rows_artifact_by_stage[stage],
            raw_rows_artifact_by_stage[stage],
            raw_hash_artifact_by_stage[stage],
            decode_contract["roundtrip_artifact"],
        ],
        "proof_blockers": [
            {
                "blocker_id": blocker_id,
                "status": "blocked_missing_exact_selector_and_decode_roundtrip",
                "needed_evidence": (
                    "exact active vendor row selector plus decoded operand/address "
                    "roundtrip for this global_max_tile template expansion"
                ),
            }
        ],
        "runtime_runnable_claim": False,
        "row_bytes_claim": False,
        "physical_route_allreduce": False,
    }


def _pe00_row_candidate_recipe(
    *,
    stage: str,
    selector_id: str,
    expected_row_count: int,
    subtask_slot: str,
    instruction_intents: tuple[str, ...],
    producer_processor: str,
    consumer_processors: tuple[str, ...],
    source_operand: str,
    destination_operand: str,
    scratch_offset_bytes: int,
    dtype: str,
) -> dict[str, object]:
    """Build the selector-level row recipe for a PE00 scalar stage.

    The recipe is intentionally not a row-byte claim.  It names the row shape
    and operand flow that a downstream writer must select and pack.
    """

    if stage == "pe00_fmax_combine_order":
        candidate_rows = [
            {
                "row_id": f"global_max_tile.pe00_fmax_combine.{index:02d}",
                "logical_row_index": index,
                "subtask_slot": subtask_slot,
                "mnemonic": "FMAX",
                "executor_processor": producer_processor,
                "source_a": (
                    consumer_processors[0]
                    if index == 0 and consumer_processors
                    else "pe00_global_max_scalar_accumulator"
                ),
                "source_b": consumer_processors[index + 1]
                if index + 1 < len(consumer_processors)
                else "local_max_scalar_by_consumer_pe",
                "destination": destination_operand,
                "local_order_proposal": index,
                "local_order_status": "proposal_available_exact_legacy_order_missing",
                "operand_role_map": {
                    "src0": "local_max_scalar" if index == 0 else "accumulator",
                    "src1": "local_max_scalar",
                    "dst": "pe00_global_max_scalar_accumulator",
                },
                "expected_decode_skeleton": {
                    "opcode": "FMAX",
                    "must_decode_processor": producer_processor,
                    "must_decode_destination": destination_operand,
                },
                "raw_bytes_status": "blocked_missing_raw_inst_t_row_bytes",
            }
            for index in range(expected_row_count)
        ]
        recipe_kind = "ordered_scalar_fmax_chain"
        row_count_formula = "max(consumer_count - 1, 1)"
    elif stage == "producer_pe00_physical_store":
        candidate_rows = [
            {
                "row_id": "global_max_tile.pe00_scalar_store.00",
                "logical_row_index": 0,
                "subtask_slot": subtask_slot,
                "mnemonic": "STD",
                "executor_processor": producer_processor,
                "source": source_operand,
                "destination": destination_operand,
                "scratch_offset_bytes": scratch_offset_bytes,
                "memory_scope": "pe00_scalar_scratch",
                "local_order_proposal": 0,
                "local_order_status": "proposal_available_exact_legacy_order_missing",
                "operand_role_map": {
                    "src": "pe00_global_max_scalar_accumulator",
                    "dst": "scratch_slot_address_operand",
                },
                "expected_decode_skeleton": {
                    "opcode": "STD",
                    "must_decode_processor": producer_processor,
                    "must_decode_scratch_offset_bytes": scratch_offset_bytes,
                },
                "raw_bytes_status": "blocked_missing_raw_inst_t_row_bytes",
            }
        ]
        recipe_kind = "single_pe00_scalar_scratch_store"
        row_count_formula = "1"
    elif stage == "consumer_physical_readback":
        candidate_rows = [
            {
                "row_id": f"global_max_tile.consumer_readback.{index:02d}",
                "logical_row_index": index,
                "subtask_slot": subtask_slot,
                "mnemonic": "ILDMT",
                "executor_processor": consumer,
                "source": source_operand,
                "destination": destination_operand,
                "scratch_offset_bytes": scratch_offset_bytes,
                "memory_scope": "pe00_scalar_scratch",
                "consumer_fiber_op": "max_with_floor_tile",
                "local_order_proposal": index,
                "local_order_status": "proposal_available_exact_legacy_order_missing",
                "operand_role_map": {
                    "src": "scratch_slot_address_operand",
                    "dst": "receiver_owned_global_max_scalar_operand",
                },
                "expected_decode_skeleton": {
                    "opcode": "ILDMT",
                    "must_decode_processor": consumer,
                    "must_decode_destination": destination_operand,
                    "must_feed_consumer_fiber_op": "max_with_floor_tile",
                },
                "raw_bytes_status": "blocked_missing_raw_inst_t_row_bytes",
            }
            for index, consumer in enumerate(consumer_processors)
        ]
        recipe_kind = "per_consumer_scalar_readback"
        row_count_formula = "consumer_count"
    else:
        candidate_rows = []
        recipe_kind = "unknown_pe00_stage"
        row_count_formula = "unknown"

    raw_row_candidate_request = _pe00_raw_row_candidate_request(
        stage=stage,
        selector_id=selector_id,
        candidate_rows=tuple(candidate_rows),
        scratch_offset_bytes=scratch_offset_bytes,
    )
    materializer_input_contract = {
        "schema_version": 1,
        "artifact_kind": "pe00_global_scalar_materializer_input_contract",
        "fiber_op": "global_max_tile",
        "stage": stage,
        "status": (
            "row_recipe_available_synthetic_decode_roundtrip_available_"
            "active_selector_missing"
        ),
        "row_id_policy": "stable_stage_local_zero_padded_index",
        "subtask_slot": subtask_slot,
        "expected_row_count": expected_row_count,
        "expected_row_ids": [str(row["row_id"]) for row in candidate_rows],
        "expected_mnemonic": list(instruction_intents),
        "raw_row_candidate_request": raw_row_candidate_request,
        "required_selected_row_fields": [
            "row_id",
            "legacy_template_row",
            "local_order",
            "operand_indices",
            "raw_inst_t_row_bytes",
            "raw_template_row_sha256",
        ],
        "closed_fields": [
            "row_id",
            "subtask_slot",
            "mnemonic",
            "executor_processor",
            "operand_role_map",
            "expected_decode_skeleton",
        ],
        "missing_fields": [
            "exact_legacy_template_row",
            "active_template_family_source",
            "active_operand_index_address_decode_roundtrip",
            "active_decoded_row_roundtrip",
        ],
        "narrowed_blockers": raw_row_candidate_request["narrowed_blockers"],
        "runtime_runnable_claim": False,
        "row_bytes_claim": False,
        "physical_route_allreduce": False,
    }

    return {
        "schema_version": 1,
        "artifact_kind": "pe00_global_scalar_row_candidate_recipe",
        "fiber_op": "global_max_tile",
        "stage": stage,
        "status": (
            "candidate_recipe_available_synthetic_decode_roundtrip_available_"
            "active_selector_missing"
        ),
        "selector_id": selector_id,
        "recipe_kind": recipe_kind,
        "row_candidate_recipe_artifact": f"{stage}_row_candidate_recipe.json",
        "expected_row_count": expected_row_count,
        "actual_candidate_row_count": len(candidate_rows),
        "row_count_formula": row_count_formula,
        "instruction_intents": list(instruction_intents),
        "dtype": dtype,
        "candidate_rows": candidate_rows,
        "candidate_row_ids": [str(row["row_id"]) for row in candidate_rows],
        "raw_row_candidate_request": raw_row_candidate_request,
        "materializer_input_contract": materializer_input_contract,
        "closed_recipe_fields": [
            "fiber_op",
            "stage",
            "selector_id",
            "recipe_kind",
            "expected_row_count",
            "candidate_row_ids",
            "subtask_slot",
            "instruction_intents",
            "dtype",
        ],
        "missing_materializer_fields": [
            "exact_legacy_template_row",
            "active_template_family_source",
            "operand_index_address_decode_roundtrip",
            "decoded_row_roundtrip",
        ],
        "narrowed_blockers": raw_row_candidate_request["narrowed_blockers"],
        "runtime_runnable_claim": False,
        "row_bytes_claim": False,
        "physical_route_allreduce": False,
    }


def _pe00_raw_row_candidate_request(
    *,
    stage: str,
    selector_id: str,
    candidate_rows: tuple[dict[str, object], ...],
    scratch_offset_bytes: int,
) -> dict[str, object]:
    """Build the per-row request a raw inst_t selector must satisfy.

    This is the narrowest H4 handoff before byte materialization: every row is
    named and opcode-typed, but exact legacy row bytes remain unclaimed.
    """

    narrowed_by_stage = {
        "pe00_fmax_combine_order": [
            "pe00_fmax_exact_legacy_row_selector_missing",
            "pe00_fmax_active_template_family_source_missing",
            "pe00_fmax_active_operand_index_address_decode_roundtrip_missing",
            "pe00_fmax_active_accumulator_encoding_roundtrip_missing",
        ],
        "producer_pe00_physical_store": [
            "pe00_scalar_store_exact_legacy_row_selector_missing",
            "pe00_scalar_store_active_template_family_source_missing",
            "pe00_scalar_store_active_scratch_address_decode_roundtrip_missing",
            "pe00_scalar_store_memory_scope_flags_roundtrip_missing",
        ],
        "consumer_physical_readback": [
            "pe00_scalar_readback_exact_legacy_row_selector_missing",
            "pe00_scalar_readback_active_template_family_source_missing",
            "pe00_scalar_readback_active_destination_operand_roundtrip_missing",
            "pe00_scalar_readback_active_scratch_address_decode_roundtrip_missing",
        ],
    }
    active_selector_evidence_request = _pe00_active_selector_evidence_request(
        stage=stage,
        selector_id=selector_id,
        expected_row_count=len(candidate_rows),
    )
    per_row_inputs = []
    for row in candidate_rows:
        mnemonic = str(row["mnemonic"])
        opcode = OPCODE_BY_MNEMONIC[mnemonic]
        synthetic_candidate = _pe00_synthetic_raw_inst_t_row_candidate(
            row=row,
            stage=stage,
            scratch_offset_bytes=scratch_offset_bytes,
        )
        per_row_inputs.append(
            {
                "row_id": row["row_id"],
                "logical_row_index": row["logical_row_index"],
                "subtask_slot": row["subtask_slot"],
                "mnemonic": mnemonic,
                "opcode": opcode,
                "opcode_hex": f"0x{opcode:03x}",
                "executor_processor": row["executor_processor"],
                "local_order": row["local_order_proposal"],
                "operand_role_map": row["operand_role_map"],
                "expected_decode_skeleton": row["expected_decode_skeleton"],
                "scratch_offset_bytes": row.get(
                    "scratch_offset_bytes",
                    scratch_offset_bytes,
                ),
                "synthetic_raw_inst_t_row_candidate": synthetic_candidate,
                "synthetic_decode_roundtrip": synthetic_candidate[
                    "synthetic_decode_roundtrip"
                ],
                "required_selector_outputs": [
                    "legacy_template_row",
                    "operand_indices",
                    "raw_inst_t_row_bytes",
                    "raw_template_row_sha256",
                    "decoded_row_roundtrip",
                ],
                "row_candidate_status": (
                    "synthetic_source_backed_row_candidate_decode_roundtrip_available_"
                    "active_selector_missing"
                ),
            }
        )

    return {
        "schema_version": 1,
        "artifact_kind": "pe00_global_scalar_raw_row_candidate_request",
        "fiber_op": "global_max_tile",
        "stage": stage,
        "selector_id": selector_id,
        "status": (
            "candidate_request_available_synthetic_decode_roundtrip_available_"
            "active_selector_missing"
        ),
        "row_count": len(per_row_inputs),
        "row_ids": [str(row["row_id"]) for row in per_row_inputs],
        "per_row_inputs": per_row_inputs,
        "synthetic_candidate_summary": {
            "status": (
                "synthetic_source_backed_raw_inst_t_candidates_decode_roundtrip_available_"
                "active_selector_missing"
            ),
            "row_count": len(per_row_inputs),
            "row_size_bytes": INST_RECORD_SIZE_BYTES,
            "total_byte_count": len(per_row_inputs) * INST_RECORD_SIZE_BYTES,
            "row_candidate_status_counts": {
                "synthetic_source_backed_row_candidate_decode_roundtrip_available_active_selector_missing": (
                    len(per_row_inputs)
                ),
            },
            "source": "LEGACY_OPS opcode table plus B-line PE00 operand role map",
            "synthetic_decode_roundtrip_claim": True,
            "exact_legacy_row_selector_claim": False,
            "active_runtime_family_claim": False,
            "row_bytes_claim": False,
            "physical_route_allreduce": False,
        },
        "active_selector_evidence_request": active_selector_evidence_request,
        "closed_fields": [
            "row_id",
            "mnemonic",
            "opcode",
            "executor_processor",
            "subtask_slot",
            "local_order",
            "operand_role_map",
            "expected_decode_skeleton",
            "scratch_offset_bytes",
            "synthetic_raw_inst_t_row_candidate",
            "synthetic_decode_roundtrip",
        ],
        "missing_fields": [
            "legacy_template_row",
            "active_template_family_selector",
            "active_operand_index_address_decode_roundtrip",
            "active_decoded_row_roundtrip",
        ],
        "active_selector_blocked_on": active_selector_evidence_request[
            "required_external_artifacts"
        ],
        "narrowed_blockers": narrowed_by_stage[stage],
        "row_bytes_claim": False,
        "runtime_runnable_claim": False,
        "physical_route_allreduce": False,
    }


def _pe00_synthetic_raw_inst_t_row_candidate(
    *,
    row: dict[str, object],
    stage: str,
    scratch_offset_bytes: int,
) -> dict[str, object]:
    mnemonic = str(row["mnemonic"])
    legacy_op = LEGACY_OPS[mnemonic]
    logical_row_index = int(row["logical_row_index"])
    src_indices, dst_indices, imms = _pe00_synthetic_operand_indices(
        row=row,
        stage=stage,
        scratch_offset_bytes=scratch_offset_bytes,
    )
    inst = LegacyInst(
        op_name=mnemonic,
        opcode=legacy_op.opcode,
        unit_inst_type=legacy_op.unit_inst_type,
        latency=legacy_op.latency,
        imms=imms,
        src_operands_idx=src_indices,
        dst_operands_idx=dst_indices,
        block_idx=logical_row_index,
    )
    raw_bytes = pack_legacy_inst(inst)
    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    synthetic_decode_roundtrip = _pe00_synthetic_decode_roundtrip(
        row=row,
        stage=stage,
        raw_bytes=raw_bytes,
        src_indices=src_indices,
        dst_indices=dst_indices,
        imms=imms,
        scratch_offset_bytes=scratch_offset_bytes,
    )
    return {
        "schema_version": 1,
        "artifact_kind": "pe00_synthetic_raw_inst_t_row_candidate",
        "row_id": row["row_id"],
        "status": (
            "synthetic_source_backed_row_candidate_decode_roundtrip_available_"
            "active_selector_missing"
        ),
        "source": "LEGACY_OPS opcode table plus B-line PE00 operand role map",
        "op_name": mnemonic,
        "opcode": legacy_op.opcode,
        "opcode_hex": f"0x{legacy_op.opcode:03x}",
        "unit_inst_type": legacy_op.unit_inst_type,
        "latency": legacy_op.latency,
        "src_operands_idx": list(src_indices),
        "dst_operands_idx": list(dst_indices),
        "imms": list(imms),
        "block_idx": logical_row_index,
        "raw_inst_t_row_byte_count": len(raw_bytes),
        "raw_inst_t_row_sha256": raw_sha256,
        "raw_template_row_sha256": raw_sha256,
        "raw_inst_t_row_bytes_hex": raw_bytes.hex(),
        "synthetic_decode_roundtrip": synthetic_decode_roundtrip,
        "synthetic_operand_index_address_roundtrip_claim": True,
        "synthetic_decoded_row_roundtrip_claim": True,
        "exact_legacy_row_selector_claim": False,
        "active_runtime_family_claim": False,
        "operand_index_address_roundtrip_claim": False,
        "decoded_row_roundtrip_claim": False,
        "row_bytes_claim": False,
        "runtime_runnable_claim": False,
        "physical_route_allreduce": False,
    }


def _pe00_synthetic_decode_roundtrip(
    *,
    row: dict[str, object],
    stage: str,
    raw_bytes: bytes,
    src_indices: tuple[int, int, int],
    dst_indices: tuple[int, int, int],
    imms: tuple[int, int, int],
    scratch_offset_bytes: int,
) -> dict[str, object]:
    fields = struct.unpack(INST_STRUCT_FORMAT, raw_bytes)
    decoded = {
        "opcode": int(fields[0]),
        "unit_inst_type": int(fields[1]),
        "latency": int(fields[2]),
        "imms": list(fields[3:6]),
        "src_operands_idx": list(fields[6:9]),
        "dst_operands_idx": list(fields[9:12]),
        "block_idx": int(fields[37]),
        "flow_ack": int(fields[38]),
        "end_inst": int(fields[39]),
    }
    mnemonic = str(row["mnemonic"])
    legacy_op = LEGACY_OPS[mnemonic]
    expected = {
        "opcode": legacy_op.opcode,
        "unit_inst_type": legacy_op.unit_inst_type,
        "latency": legacy_op.latency,
        "imms": list(imms),
        "src_operands_idx": list(src_indices),
        "dst_operands_idx": list(dst_indices),
        "block_idx": int(row["logical_row_index"]),
    }
    mismatches = [
        field
        for field, expected_value in expected.items()
        if decoded[field] != expected_value
    ]
    role_roundtrip = _pe00_operand_role_roundtrip(
        row=row,
        stage=stage,
        decoded=decoded,
        scratch_offset_bytes=scratch_offset_bytes,
    )
    if role_roundtrip["status"] != "synthetic_operand_roles_decode_roundtrip_available":
        mismatches.append("operand_role_roundtrip")
    return {
        "schema_version": 1,
        "artifact_kind": "pe00_synthetic_inst_t_decode_roundtrip",
        "row_id": row["row_id"],
        "stage": stage,
        "status": (
            "synthetic_decode_roundtrip_available_active_selector_missing"
            if not mismatches
            else "blocked_synthetic_decode_roundtrip_mismatch"
        ),
        "decoded": decoded,
        "expected": expected,
        "operand_role_roundtrip": role_roundtrip,
        "mismatches": mismatches,
        "synthetic_decode_roundtrip_claim": not mismatches,
        "active_template_family_claim": False,
        "row_bytes_claim": False,
        "runtime_runnable_claim": False,
        "physical_route_allreduce": False,
    }


def _pe00_operand_role_roundtrip(
    *,
    row: dict[str, object],
    stage: str,
    decoded: dict[str, object],
    scratch_offset_bytes: int,
) -> dict[str, object]:
    src = tuple(int(value) for value in decoded["src_operands_idx"])
    dst = tuple(int(value) for value in decoded["dst_operands_idx"])
    imms = tuple(int(value) for value in decoded["imms"])
    logical_row_index = int(row["logical_row_index"])
    scratch_word_offset = int(scratch_offset_bytes) // 4
    accumulator_operand = 256
    receiver_scalar_base_operand = 512

    if stage == "pe00_fmax_combine_order":
        expected_roles = {
            "local_max_or_accumulator_src": (
                logical_row_index if logical_row_index == 0 else accumulator_operand
            ),
            "next_local_max_src": logical_row_index + 1,
            "accumulator_dst": accumulator_operand,
        }
        decoded_roles = {
            "local_max_or_accumulator_src": src[0],
            "next_local_max_src": src[1],
            "accumulator_dst": dst[0],
        }
    elif stage == "producer_pe00_physical_store":
        expected_roles = {
            "accumulator_src": accumulator_operand,
            "scratch_address_operand": scratch_word_offset,
            "scratch_offset_immediate_bytes": int(scratch_offset_bytes),
        }
        decoded_roles = {
            "accumulator_src": src[0],
            "scratch_address_operand": dst[0],
            "scratch_offset_immediate_bytes": imms[0],
        }
    elif stage == "consumer_physical_readback":
        expected_roles = {
            "scratch_address_operand": scratch_word_offset,
            "receiver_destination_operand": (
                receiver_scalar_base_operand + logical_row_index
            ),
            "scratch_offset_immediate_bytes": int(scratch_offset_bytes),
        }
        decoded_roles = {
            "scratch_address_operand": src[0],
            "receiver_destination_operand": dst[0],
            "scratch_offset_immediate_bytes": imms[0],
        }
    else:
        raise ValueError(f"unsupported PE00 materialized scalar stage: {stage}")

    mismatches = [
        role
        for role, expected_value in expected_roles.items()
        if decoded_roles[role] != expected_value
    ]
    return {
        "schema_version": 1,
        "artifact_kind": "pe00_synthetic_operand_role_roundtrip",
        "row_id": row["row_id"],
        "stage": stage,
        "status": (
            "synthetic_operand_roles_decode_roundtrip_available"
            if not mismatches
            else "blocked_synthetic_operand_role_mismatch"
        ),
        "expected_roles": expected_roles,
        "decoded_roles": decoded_roles,
        "mismatches": mismatches,
        "active_operand_decode_claim": False,
        "row_bytes_claim": False,
    }


def _pe00_active_selector_evidence_request(
    *,
    stage: str,
    selector_id: str,
    expected_row_count: int,
) -> dict[str, object]:
    required_by_stage = {
        "pe00_fmax_combine_order": [
            "active A-line/vendor PE00 FMAX reduction-chain template rows",
            "decoded row artifact showing accumulator/local-max operand indices",
            "runtime source tying those rows to global_max_tile PE00 combine",
        ],
        "producer_pe00_physical_store": [
            "active A-line/vendor scalar scratch STD template row",
            "decoded row artifact showing scratch address operand/immediate",
            "runtime source tying the row to PE00 materialized global scalar store",
        ],
        "consumer_physical_readback": [
            "active A-line/vendor scalar scratch ILDMT/readback template rows",
            "decoded row artifact showing per-consumer destination operands",
            "max_with_floor_tile operand-link artifact consuming those operands",
        ],
    }
    return {
        "schema_version": 1,
        "artifact_kind": "pe00_active_selector_evidence_request",
        "stage": stage,
        "selector_id": selector_id,
        "status": "blocked_missing_active_vendor_or_aline_artifact",
        "expected_row_count": expected_row_count,
        "required_external_artifacts": required_by_stage[stage],
        "synthetic_candidate_available": True,
        "synthetic_candidate_is_not_final_row_bytes": True,
        "active_runtime_family_claim": False,
        "row_bytes_claim": False,
        "runtime_runnable_claim": False,
        "physical_route_allreduce": False,
    }


def _pe00_synthetic_operand_indices(
    *,
    row: dict[str, object],
    stage: str,
    scratch_offset_bytes: int,
) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    logical_row_index = int(row["logical_row_index"])
    scratch_word_offset = int(scratch_offset_bytes) // 4
    accumulator_operand = 256
    scratch_address_operand = scratch_word_offset
    receiver_scalar_base_operand = 512

    if stage == "pe00_fmax_combine_order":
        src0 = logical_row_index if logical_row_index == 0 else accumulator_operand
        src1 = logical_row_index + 1
        return (src0, src1, 0), (accumulator_operand, 0, 0), (0, 0, 0)
    if stage == "producer_pe00_physical_store":
        return (
            (accumulator_operand, 0, 0),
            (scratch_address_operand, 0, 0),
            (scratch_offset_bytes, 0, 0),
        )
    if stage == "consumer_physical_readback":
        return (
            (scratch_address_operand, 0, 0),
            (receiver_scalar_base_operand + logical_row_index, 0, 0),
            (scratch_offset_bytes, 0, 0),
        )
    raise ValueError(f"unsupported PE00 materialized scalar stage: {stage}")


@dataclass(frozen=True)
class Log10MaxTemplatePack:
    """S6 local template pack plus scalar visibility and numerical contract."""

    profile_id: str
    local_template_steps: tuple[LocalTemplateStep, ...]
    scalar_visibility_binding: dict[str, object]
    numerical_contract: dict[str, object]

    def to_artifact(self) -> dict[str, object]:
        uploadable = bool(self.scalar_visibility_binding["uploadable"])
        uploadable_blockers = list(self.scalar_visibility_binding["blockers"])
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_local_template_pack",
            "profile_id": self.profile_id,
            "producer": "S6_log10max_local_elementwise_reduce_template_binding",
            "pipeline_position": {
                "S6a_local_template_pack": "complete_report_only",
                "S6b_scalar_visibility_binding": (
                    "shape_defined_waiting_for_S5_selected_strategy"
                ),
            },
            "source_expression": {
                "payload_case": "log10max_single_task",
                "expression": (
                    "Y=(maximum(log10(clamp_min(X,1e-10)), "
                    "max(log10(X))-8)+4)*0.25"
                ),
                "local_expression": (
                    "local_log10 = FLOG2(clamp_min(X,1e-10))*log10(2); "
                    "local_max = local_reduce_max(local_log10); "
                    "Y = (maximum(local_log10, global_max-8)+4)*0.25"
                ),
            },
            "local_template_pack": {
                "status": "complete_report_only",
                "uploadable": uploadable,
                "uploadable_blockers": uploadable_blockers,
                "steps": [step.to_artifact() for step in self.local_template_steps],
            },
            "scalar_visibility_binding": dict(self.scalar_visibility_binding),
            "numerical_contract": dict(self.numerical_contract),
            "layering_policy": (
                "S6 local template pack describes local elementwise/reduce/store "
                "template intent only; it does not select physical scalar "
                "visibility, mutate op-time PE programs, or emit vendor binaries"
            ),
        }


def build_log10max_template_pack(
    *,
    global_scalar_input: str = S5_UNRESOLVED_GLOBAL_SCALAR_INPUT,
    scalar_source: ScalarVisibilitySource | None = None,
) -> Log10MaxTemplatePack:
    """Build the report-only S6 artifact for log10max."""

    if scalar_source is None:
        scalar_source = _external_symbolic_scalar_source(global_scalar_input)
    scalar_uploadable = scalar_source.is_complete()
    scalar_binding_status = (
        "pe00_scalar_visibility_contract_complete"
        if scalar_uploadable
        else "blocked_waiting_for_S5_scalar_visibility"
    )
    threshold_binding_status = (
        "pe00_scalar_threshold_contract_complete"
        if scalar_uploadable
        else "scalar_visibility_external_until_S5"
    )
    maximum_step_status: TemplateStatus = (
        "ready_local" if scalar_uploadable else "external_symbolic"
    )
    steps = (
        LocalTemplateStep(
            id="s6a.step0.clamp_min",
            op="clamp_min",
            template_family="local_elementwise",
            status="ready_local",
            inputs=("X_tile",),
            outputs=("x_clamped_tile",),
            instruction_intents=("FMAX immediate clamp_min",),
            opcode_evidence=(
                _opcode_evidence(
                    "FMAX",
                    opcode_metadata_status="known_active_opcode",
                    template_binding_status="local_template_shape_ready",
                    role="lane-wise fp32 max for clamp_min",
                    evidence_refs=(
                        f"{ISA_DOCS_ROOT}/instruction_cards.jsonl:FMAX",
                        "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:FMAX",
                        OPCODE_CONFORMANCE_CHECK,
                    ),
                ),
                _constant_evidence(
                    "clamp_min",
                    LOG10MAX_CLAMP_MIN,
                    binding_status="constant_operand_policy_unbound",
                ),
            ),
            attrs=(
                ("constant", LOG10MAX_CLAMP_MIN),
                ("dtype", LOG10MAX_DTYPE),
            ),
        ),
        LocalTemplateStep(
            id="s6a.step1.flog2_times_log10_2",
            op="FLOG2*log10(2)",
            template_family="local_elementwise",
            status="ready_local",
            inputs=("x_clamped_tile",),
            outputs=("local_log10_tile",),
            instruction_intents=("FLOG2", "FMUL scalar log10(2)"),
            opcode_evidence=(
                _opcode_evidence(
                    "FLOG2",
                    opcode_metadata_status="known_active_opcode",
                    template_binding_status="local_template_shape_ready",
                    role="fp32 lane-wise log2",
                    evidence_refs=(
                        f"{ISA_DOCS_ROOT}/instruction_cards.jsonl:FLOG2",
                        "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:FLOG2",
                        OPCODE_CONFORMANCE_CHECK,
                    ),
                ),
                _opcode_evidence(
                    "FMUL",
                    opcode_metadata_status="known_active_opcode",
                    template_binding_status="local_template_shape_ready",
                    role="scale log2(x) by log10(2)",
                    evidence_refs=(
                        f"{ISA_DOCS_ROOT}/instruction_cards.jsonl:FMUL",
                        "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:FMUL",
                        OPCODE_CONFORMANCE_CHECK,
                    ),
                ),
                _constant_evidence(
                    "log10_2",
                    LOG10MAX_LOG10_2,
                    binding_status="constant_operand_policy_unbound",
                ),
            ),
            attrs=(
                ("source_chip_op", "log10"),
                ("lowering", "FLOG2*log10(2)"),
                ("constant_log10_2", LOG10MAX_LOG10_2),
                ("dtype", LOG10MAX_DTYPE),
            ),
        ),
        LocalTemplateStep(
            id="s6a.step2.local_reduce_max",
            op="local_reduce_max",
            template_family="local_reduce",
            status="ready_local",
            inputs=("local_log10_tile",),
            outputs=("local_max_scalar",),
            instruction_intents=("FMAX_REDUCE_LOCAL",),
            opcode_evidence=(
                _opcode_evidence(
                    "SHFL",
                    opcode_metadata_status="known_active_opcode",
                    template_binding_status="candidate_reduce_skeleton",
                    role="horizontal lane movement for local reduce",
                    evidence_refs=(
                        "compiler/notes/log10max/README.md:SHFL+FMAX",
                        f"{ISA_DOCS_ROOT}/instruction_cards.jsonl:SHFL",
                        "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:SHFL",
                        OPCODE_CONFORMANCE_CHECK,
                    ),
                ),
                _opcode_evidence(
                    "FMAX",
                    opcode_metadata_status="known_active_opcode",
                    template_binding_status="candidate_reduce_skeleton",
                    role="fp32 max combine after SHFL",
                    evidence_refs=(
                        "compiler/notes/log10max/README.md:SHFL+FMAX",
                        f"{ISA_DOCS_ROOT}/instruction_cards.jsonl:FMAX",
                        "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:FMAX",
                        OPCODE_CONFORMANCE_CHECK,
                    ),
                ),
            ),
            attrs=(
                ("source_chip_op", "reduce_max"),
                ("identity_value", "-inf"),
                ("visibility_kind", "local_scalar"),
                ("dtype", LOG10MAX_DTYPE),
            ),
        ),
        LocalTemplateStep(
            id="s6a.step3.maximum_with_symbolic_global_scalar",
            op="maximum",
            template_family="local_elementwise_with_scalar_broadcast",
            status=maximum_step_status,
            inputs=("local_log10_tile", "global_threshold_scalar"),
            outputs=("clipped_tile",),
            instruction_intents=("FMAX vector_scalar",),
            opcode_evidence=(
                _opcode_evidence(
                    "FMAX",
                    opcode_metadata_status="known_active_opcode",
                    template_binding_status=scalar_binding_status,
                    role="fp32 lane-wise max against replicated threshold scalar",
                    evidence_refs=(
                        f"{ISA_DOCS_ROOT}/instruction_cards.jsonl:FMAX",
                        "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:FMAX",
                        OPCODE_CONFORMANCE_CHECK,
                    ),
                ),
                _constant_evidence(
                    "threshold_offset",
                    LOG10MAX_GLOBAL_THRESHOLD_OFFSET,
                    binding_status=threshold_binding_status,
                ),
            ),
            attrs=(
                ("global_scalar_input", scalar_source.source_name),
                ("scalar_visibility_strategy", scalar_source.strategy),
                ("scalar_visibility_scratch_slot", scalar_source.scratch_slot),
                ("threshold_expr", "global_max_scalar + (-8.0)"),
                ("uploadable", scalar_uploadable),
                ("dtype", LOG10MAX_DTYPE),
            ),
            notes=(
                "The maximum template shape is local, but its scalar input "
                "must be bound by the S5 selected collective/app-storage strategy.",
            ),
        ),
        LocalTemplateStep(
            id="s6a.step4.add_scalar",
            op="add_scalar",
            template_family="local_elementwise",
            status="ready_local",
            inputs=("clipped_tile",),
            outputs=("biased_tile",),
            instruction_intents=("FADD scalar",),
            opcode_evidence=(
                _opcode_evidence(
                    "FADD",
                    opcode_metadata_status="known_active_opcode",
                    template_binding_status="local_template_shape_ready",
                    role="add output bias",
                    evidence_refs=(
                        f"{ISA_DOCS_ROOT}/instruction_cards.jsonl:FADD",
                        "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:FADD",
                        OPCODE_CONFORMANCE_CHECK,
                    ),
                ),
                _constant_evidence(
                    "output_bias",
                    LOG10MAX_OUTPUT_BIAS,
                    binding_status="constant_operand_policy_unbound",
                ),
            ),
            attrs=(
                ("constant", LOG10MAX_OUTPUT_BIAS),
                ("dtype", LOG10MAX_DTYPE),
            ),
        ),
        LocalTemplateStep(
            id="s6a.step5.mul_scalar",
            op="mul_scalar",
            template_family="local_elementwise",
            status="ready_local",
            inputs=("biased_tile",),
            outputs=("normalized_tile",),
            instruction_intents=("FMUL scalar",),
            opcode_evidence=(
                _opcode_evidence(
                    "FMUL",
                    opcode_metadata_status="known_active_opcode",
                    template_binding_status="local_template_shape_ready",
                    role="multiply output scale",
                    evidence_refs=(
                        f"{ISA_DOCS_ROOT}/instruction_cards.jsonl:FMUL",
                        "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:FMUL",
                        OPCODE_CONFORMANCE_CHECK,
                    ),
                ),
                _constant_evidence(
                    "output_scale",
                    LOG10MAX_OUTPUT_SCALE,
                    binding_status="constant_operand_policy_unbound",
                ),
            ),
            attrs=(
                ("constant", LOG10MAX_OUTPUT_SCALE),
                ("dtype", LOG10MAX_DTYPE),
            ),
        ),
        LocalTemplateStep(
            id="s6a.step6.store",
            op="store",
            template_family="tile_store",
            status="ready_local",
            inputs=("normalized_tile",),
            outputs=("Y_sram_tile",),
            instruction_intents=("STD",),
            opcode_evidence=(
                _opcode_evidence(
                    "STD",
                    opcode_metadata_status="known_active_opcode",
                    template_binding_status="memory_template_base_slot_unbound",
                    role="store output tile to SRAM/SPM",
                    evidence_refs=(
                        f"{ISA_DOCS_ROOT}/MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md",
                        "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:STD",
                        OPCODE_CONFORMANCE_CHECK,
                    ),
                ),
                _opcode_evidence(
                    "HSTT",
                    opcode_metadata_status="pseudo_assembler_only",
                    template_binding_status="must_expand_before_binary_accounting",
                    role="store pseudo template evidence; final CBUF must use physical rows",
                    evidence_refs=(
                        f"{ISA_DOCS_ROOT}/MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md",
                        "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:HSTT",
                        OPCODE_CONFORMANCE_CHECK,
                    ),
                ),
            ),
            attrs=(
                ("output_tensor", "Y"),
                ("dtype", LOG10MAX_DTYPE),
            ),
        ),
    )
    return Log10MaxTemplatePack(
        profile_id=LOG10MAX_PROFILE_ID,
        local_template_steps=steps,
        scalar_visibility_binding=_scalar_visibility_binding(
            scalar_source=scalar_source,
        ),
        numerical_contract=_numerical_contract(),
    )


def bind_scalar_visibility(
    pack: Log10MaxTemplatePack,
    scalar_source: ScalarVisibilitySource,
) -> Log10MaxTemplatePack:
    """Return a pack with an S5-provided PE00 scalar visibility source bound."""

    rebound = build_log10max_template_pack(scalar_source=scalar_source)
    return Log10MaxTemplatePack(
        profile_id=pack.profile_id,
        local_template_steps=rebound.local_template_steps,
        scalar_visibility_binding=rebound.scalar_visibility_binding,
        numerical_contract=pack.numerical_contract,
    )


def summarize_log10max_template_pack(
    pack: Log10MaxTemplatePack,
) -> dict[str, object]:
    """Return stable focused-check counts for the S6 artifact."""

    status_counts: dict[str, int] = {}
    opcode_metadata_status_counts: dict[str, int] = {}
    template_binding_status_counts: dict[str, int] = {}
    op_sequence: list[str] = []
    symbolic_unresolved = 0

    for step in pack.local_template_steps:
        status_counts[step.status] = status_counts.get(step.status, 0) + 1
        op_sequence.append(step.op)
        if step.status == "external_symbolic":
            symbolic_unresolved += 1
        for evidence in step.opcode_evidence:
            opcode_status = str(evidence.get("opcode_metadata_status"))
            binding_status = str(evidence.get("template_binding_status"))
            opcode_metadata_status_counts[opcode_status] = (
                opcode_metadata_status_counts.get(opcode_status, 0) + 1
            )
            template_binding_status_counts[binding_status] = (
                template_binding_status_counts.get(binding_status, 0) + 1
            )

    scalar_binding = pack.scalar_visibility_binding
    uploadable = bool(scalar_binding.get("uploadable"))
    symbolic_unresolved_count_for_uploadable = (
        0 if uploadable else symbolic_unresolved
    )
    return {
        "profile_id": pack.profile_id,
        "artifact_kind": "log10max_local_template_pack",
        "local_template_step_count": len(pack.local_template_steps),
        "op_sequence": op_sequence,
        "status_counts": dict(sorted(status_counts.items())),
        "opcode_metadata_status_counts": dict(
            sorted(opcode_metadata_status_counts.items())
        ),
        "template_binding_status_counts": dict(
            sorted(template_binding_status_counts.items())
        ),
        "s6a_local_template_pack_status": "complete_report_only",
        "s6b_scalar_visibility_binding_status": scalar_binding["status"],
        "global_scalar_input": scalar_binding["global_scalar_input"],
        "scalar_visibility_strategy": scalar_binding["strategy"],
        "scalar_visibility_source_complete": scalar_binding["source_complete"],
        "runtime_runnable_claim": scalar_binding["runtime_runnable_claim"],
        "row_bytes_claim": scalar_binding["row_bytes_claim"],
        "uploadable": uploadable,
        "symbolic_unresolved_count_for_uploadable": (
            symbolic_unresolved_count_for_uploadable
        ),
        "numerical_contract_dtype": pack.numerical_contract["dtype"],
        "tolerance": pack.numerical_contract["tolerance"],
    }


def build_log10max_status_report(
    *,
    global_scalar_input: str = S5_UNRESOLVED_GLOBAL_SCALAR_INPUT,
    scalar_source: ScalarVisibilitySource | None = None,
) -> dict[str, object]:
    """Build a JSON-stable status report suitable for focused checks."""

    pack = build_log10max_template_pack(
        global_scalar_input=global_scalar_input,
        scalar_source=scalar_source,
    )
    summary = summarize_log10max_template_pack(pack)
    return {
        "schema_version": 1,
        "artifact_kind": "local_template_pack.status.json",
        "summary": summary,
        "artifact": pack.to_artifact(),
    }


def _opcode_evidence(
    mnemonic: str,
    *,
    opcode_metadata_status: str,
    template_binding_status: str,
    role: str,
    evidence_refs: tuple[str, ...],
) -> dict[str, object]:
    opcode = OPCODE_BY_MNEMONIC[mnemonic]
    annotation = annotate_opcode(opcode)
    return {
        "kind": "opcode",
        "mnemonic": mnemonic,
        "opcode": opcode,
        "opcode_hex": f"0x{opcode:03x}",
        "opcode_metadata_status": opcode_metadata_status,
        "template_binding_status": template_binding_status,
        "role": role,
        "category": annotation["category"],
        "latency": annotation["latency"],
        "src_count": annotation["src_count"],
        "unit_inst_type": annotation["unit_inst_type"],
        "pseudo": annotation["pseudo"],
        "decoder_source": annotation["source"],
        "evidence_refs": list(evidence_refs),
    }


def _constant_evidence(
    name: str,
    value: float,
    *,
    binding_status: str,
) -> dict[str, object]:
    return {
        "kind": "constant",
        "name": name,
        "value": value,
        "dtype": LOG10MAX_DTYPE,
        "opcode_metadata_status": "constant_value_from_payload_contract",
        "template_binding_status": binding_status,
        "materialization_candidates": [
            _opcode_evidence(
                "FIMM",
                opcode_metadata_status="known_active_opcode",
                template_binding_status="candidate_constant_materialization",
                role="fp32 immediate constant materialization",
                evidence_refs=(
                    f"{ISA_DOCS_ROOT}/README.md",
                    "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:FIMM",
                    OPCODE_CONFORMANCE_CHECK,
                ),
            ),
            _opcode_evidence(
                "IMM",
                opcode_metadata_status="known_active_opcode",
                template_binding_status="candidate_constant_materialization",
                role="integer/immediate constant materialization",
                evidence_refs=(
                    f"{ISA_DOCS_ROOT}/README.md",
                    "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:IMM",
                    OPCODE_CONFORMANCE_CHECK,
                ),
            ),
        ],
        "evidence_refs": [
            "compiler/gpdpu_compiler/validation/dfu3500_partner_validation/"
            "build_payloads.py:log10max_reference_values",
            "compiler/notes/log10max/README.md:target expression",
        ],
    }


def _scalar_visibility_binding(
    *,
    scalar_source: ScalarVisibilitySource,
) -> dict[str, object]:
    blockers = scalar_source.blockers()
    uploadable = not blockers
    status = (
        "pe00_scalar_visibility_contract_complete"
        if uploadable
        else "blocked_waiting_for_S5_selected_strategy"
    )
    return {
        "schema_version": 1,
        "artifact_kind": "scalar_visibility_binding",
        "status": status,
        "strategy": scalar_source.strategy,
        "global_scalar_name": "global_max_scalar",
        "global_scalar_input": scalar_source.source_name,
        "global_scalar_dtype": LOG10MAX_DTYPE,
        "consumer_template_step_id": "s6a.step3.maximum_with_symbolic_global_scalar",
        "source": scalar_source.to_artifact(),
        "source_complete": uploadable,
        "binding_shape": {
            "producer": "local_reduce_max across all contributing processors",
            "consumer": "local vector-scalar maximum threshold",
            "threshold_transform": {
                "op": "add_scalar",
                "constant": LOG10MAX_GLOBAL_THRESHOLD_OFFSET,
            },
            "visibility_kind": "replicated_scalar",
        },
        "uploadable": uploadable,
        "blockers": list(blockers),
        "runtime_runnable_claim": False,
        "row_bytes_claim": False,
    }


def _external_symbolic_scalar_source(
    global_scalar_input: str,
) -> ScalarVisibilitySource:
    return ScalarVisibilitySource(
        strategy="external_symbolic_until_S5",
        source_name=global_scalar_input,
        scratch_slot="",
        consumer_load_contract={},
        ordering_evidence_status="missing",
        source_kind="unresolved_external_symbolic",
    )


def _numerical_contract() -> dict[str, object]:
    return {
        "schema_version": 1,
        "artifact_kind": "numerical_contract.json",
        "op": "log10max",
        "dtype": LOG10MAX_DTYPE,
        "formula": (
            "Y=(maximum(log10(clamp_min(X,1e-10)), "
            "global_max(log10(clamp_min(X,1e-10)))-8)+4)*0.25"
        ),
        "constants": {
            "clamp_min": LOG10MAX_CLAMP_MIN,
            "log10_2": LOG10MAX_LOG10_2,
            "threshold_offset": LOG10MAX_GLOBAL_THRESHOLD_OFFSET,
            "output_bias": LOG10MAX_OUTPUT_BIAS,
            "output_scale": LOG10MAX_OUTPUT_SCALE,
        },
        "constant_fields": {
            "clamp_min_1e_10": {
                "symbol": "1e-10",
                "value": LOG10MAX_CLAMP_MIN,
                "role": "lower clamp before logarithm",
            },
            "log10_of_2": {
                "symbol": "log10(2)",
                "value": LOG10MAX_LOG10_2,
                "role": "FLOG2 result scale for log10 lowering",
            },
            "threshold_offset_minus_8": {
                "symbol": "-8.0",
                "value": LOG10MAX_GLOBAL_THRESHOLD_OFFSET,
                "role": "offset from global max before maximum",
            },
            "output_bias_plus_4": {
                "symbol": "+4.0",
                "value": LOG10MAX_OUTPUT_BIAS,
                "role": "post-maximum output bias",
            },
            "output_scale_0_25": {
                "symbol": "0.25",
                "value": LOG10MAX_OUTPUT_SCALE,
                "role": "post-bias output scale",
            },
        },
        "constant_evidence_status": {
            "value_source": "payload_reference_contract_and_log10max_notes",
            "opcode_candidates": ["FIMM", "IMM"],
            "operand_materialization_status": (
                "constant values fixed; final operand/register/immediate binding "
                "not selected by S6"
            ),
            "global_threshold_scalar_status": (
                "threshold_offset is fixed, but global_max scalar visibility "
                "waits for S5 selected strategy"
            ),
        },
        "domain": {
            "input": "all fp32 values accepted at API boundary",
            "log_input": "max(X, 1e-10), strictly positive after clamp",
            "log_lower_bound": "log10(1e-10) == -10",
        },
        "nan_inf": {
            "nan_input": "IEEE maximum/clamp behavior must be target-defined before runtime claim",
            "positive_inf_input": "log10(+inf) stays +inf; global max may become +inf",
            "negative_inf_input": "clamped to 1e-10 before log",
            "negative_or_zero_input": "clamped to 1e-10 before log",
        },
        "tolerance": {
            "comparison": "absolute_or_relative",
            "atol": 1.0e-5,
            "rtol": 1.0e-5,
            "basis": "fp32 reference with FLOG2*log10(2) lowering",
        },
        "evidence_refs": [
            "compiler/notes/log10max/README.md",
            "compiler/gpdpu_compiler/validation/dfu3500_partner_validation/"
            "build_payloads.py:log10max_reference_values",
            f"{ISA_DOCS_ROOT}/instruction_cards.jsonl:FLOG2",
            f"{ISA_DOCS_ROOT}/instruction_cards.jsonl:FMAX",
            f"{ISA_DOCS_ROOT}/instruction_cards.jsonl:FADD",
            f"{ISA_DOCS_ROOT}/instruction_cards.jsonl:FMUL",
        ],
    }


__all__ = [
    "LOG10MAX_PROFILE_ID",
    "S5_UNRESOLVED_GLOBAL_SCALAR_INPUT",
    "LocalTemplateStep",
    "Log10MaxTemplatePack",
    "Pe00GlobalScalarTemplateContract",
    "Pe00VendorRowLoweringEntry",
    "ScalarVisibilitySource",
    "bind_scalar_visibility",
    "build_log10max_status_report",
    "build_log10max_template_pack",
    "build_pe00_global_scalar_template_contract",
    "summarize_log10max_template_pack",
]
