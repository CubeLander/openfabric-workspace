"""Strategy report for log10max collective lowering.

This module is report-only.  It reads the current chip/logical/tile plans and
names the collective strategy that can be defended for customer discussion
without mutating lower IR or pretending that symbolic collectives are physical
DFU routes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import reduce
from operator import mul
from typing import Any

from gpdpu_compiler.core.chip_env import ChipEnv
from gpdpu_compiler.core.ops import (
    add_scalar,
    clamp_min,
    log10,
    maximum,
    mul_scalar,
    reduce_max,
)
from gpdpu_compiler.core.program_runtime import (
    Pe00MaterializedScalarRuntimeOrderContract,
)
from gpdpu_compiler.placements import Shard, TaskShard

from .binding import Pe00ScalarReceiverBindingContract
from .log10max_template_pack import build_pe00_global_scalar_template_contract
from .micc_component_writers import build_pe00_materialized_scalar_micc_lowering_intent


class Log10MaxCollectiveStrategy(str, Enum):
    """Compiler strategy names for the log10max scalar collective."""

    DIRECT_ROUTE_REDUCE_BROADCAST = "direct_route_reduce_broadcast"
    RING_SPMD_ROW_THEN_COL = "ring_spmd_row_then_col"
    PE00_AGGREGATE_MATERIALIZE = "pe00_aggregate_materialize"
    REDUNDANT_SPMD_RECOMPUTE = "redundant_spmd_recompute"


class Log10MaxCustomerLabel(str, Enum):
    """Customer-facing labels, kept distinct from compiler strategy names."""

    PHYSICAL_ROUTE_ALLREDUCE = "physical_route_allreduce"
    SPMD_RING_MATERIALIZED_REDUCE = "spmd_ring_materialized_reduce"
    PE00_MATERIALIZED_SCALAR = "pe00_materialized_scalar"
    INTERNAL_REDUNDANT_RECOMPUTE = "internal_redundant_recompute"


CUSTOMER_LABEL_BY_STRATEGY = {
    Log10MaxCollectiveStrategy.DIRECT_ROUTE_REDUCE_BROADCAST: (
        Log10MaxCustomerLabel.PHYSICAL_ROUTE_ALLREDUCE
    ),
    Log10MaxCollectiveStrategy.RING_SPMD_ROW_THEN_COL: (
        Log10MaxCustomerLabel.SPMD_RING_MATERIALIZED_REDUCE
    ),
    Log10MaxCollectiveStrategy.PE00_AGGREGATE_MATERIALIZE: (
        Log10MaxCustomerLabel.PE00_MATERIALIZED_SCALAR
    ),
    Log10MaxCollectiveStrategy.REDUNDANT_SPMD_RECOMPUTE: (
        Log10MaxCustomerLabel.INTERNAL_REDUNDANT_RECOMPUTE
    ),
}


LOG10MAX_CUSTOMER_SHAPE = (64, 512)
LOG10MAX_CUSTOMER_DTYPE = "fp32"
LOG10MAX_INPUT_OFFSET_BYTES = 0x00000
LOG10MAX_OUTPUT_OFFSET_BYTES = 0x80000
LOG10MAX_SCRATCH_OFFSET_BYTES = 0xA0000
LOG10MAX_SCRATCH_INSTANCE_BASE_ADDR_SOURCE = (
    "dfu3500_sram_byte_offset_to_legacy_base_word32"
)
LOG10MAX_RING_FIRST_TASK_AXIS = 1
LOG10MAX_RING_FIRST_ORDERING_DOMAIN = "single_task_group"
LOG10MAX_RING_FIRST_STRATEGY = (
    Log10MaxCollectiveStrategy.RING_SPMD_ROW_THEN_COL
)
LOG10MAX_RING_FIRST_CUSTOMER_LABEL = (
    Log10MaxCustomerLabel.SPMD_RING_MATERIALIZED_REDUCE
)

RING_FIRST_DELIVERY_BLOCKERS = (
    "route_role_globalmax_unproven",
    "ring_edge_template_missing",
    "ring_phase_order_missing",
    "global_max_distribution_missing",
    "consumer_global_max_binding_missing",
    "consumer_depends_on_global_ready_missing",
    "route_path_proof_missing",
    "dtype_update_op_mismatch",
    "symbolic_global_max_reaches_postprocess",
)

PE00_REMAINING_DELIVERY_BLOCKERS = (
    {
        "blocker_id": "producer_pe00_physical_store_row_bytes_missing",
        "requirement_id": "producer_pe00_physical_store",
        "owner": "tile_store_load_lowering",
        "status": "contract_available_rows_missing",
        "needed_evidence": (
            "reduce_store for global_max_tile lowers to concrete PE00 scalar "
            "scratch store rows with FiberOp provenance"
        ),
        "non_goal": "do not model this as direct physical allreduce",
    },
    {
        "blocker_id": "pe00_fmax_combine_order_row_bytes_missing",
        "requirement_id": "pe00_fmax_combine_order",
        "owner": "pe00_fmax_chain",
        "status": "contract_available_rows_missing",
        "needed_evidence": (
            "ordered FMAX chain over all local_max scalars is emitted before "
            "the PE00 scalar scratch store"
        ),
        "non_goal": "do not expand the FiberOp into hidden fiber-internal stages",
    },
    {
        "blocker_id": "consumer_physical_readback_row_bytes_missing",
        "requirement_id": "consumer_physical_readback",
        "owner": "tile_store_load_lowering",
        "status": "contract_available_rows_missing",
        "needed_evidence": (
            "each consumer reads the PE00 materialized scalar into a "
            "receiver-owned scalar operand"
        ),
        "non_goal": "do not route through legacy symbolic tile collective registry semantics",
    },
    {
        "blocker_id": "runtime_subtask_order_proof_missing",
        "requirement_id": "runtime_subtask_order",
        "owner": "runtime_subtask_order",
        "status": "contract_available_runtime_proof_missing",
        "needed_evidence": (
            "MICC/runtime successor, launch, and wait order prove PE00 "
            "combine/store completes before consumer readback"
        ),
        "non_goal": "do not claim runtime_runnable until this is validated",
    },
    {
        "blocker_id": "receiver_global_scalar_binding_proof_missing",
        "requirement_id": "receiver_binding",
        "owner": "receiver_binding",
        "status": "contract_available_binding_proof_missing",
        "needed_evidence": (
            "every max_with_floor_tile consumes the scalar through explicit "
            "receiver/global-scalar binding"
        ),
        "non_goal": "do not use bundle fields as Fiber or Template semantics",
    },
)


EVIDENCE_SOURCES = (
    {
        "path": "compiler/notes/log10max/README.md",
        "role": (
            "states that current LogicalReduceEdge/symbolic tile collective registry remains "
            "symbolic and recommends redundant SPMD as first runnable path"
        ),
    },
    {
        "path": "docs/vendor_reference/cases/softmax/softmax-current-real-workflow.md",
        "role": (
            "softmax workflow evidence for 64x512, 4 tasks, 16 PE per task, "
            "two staged subtasks, and SPM/SUM intermediate materialization"
        ),
    },
    {
        "path": "docs/vendor_reference/cases/softmax/softmax-case-walkthrough.md",
        "role": (
            "case build sequence evidence: per-PE CSV, build_so, spm_data, "
            "RISC-V control, and outer run_app_riscv launch"
        ),
    },
    {
        "path": "docs/runtime/data/README.md",
        "role": (
            "runtime data-plane boundary: cbuf_file.bin is inst/exeblock/instance "
            "and micc_file.bin is task/subtask"
        ),
    },
    {
        "path": "docs/runtime/control/README.md",
        "role": (
            "runtime order evidence: subtask successor chain, instance base_addr "
            "environment, DPU_Kernel_Start doorbell and wait semantics"
        ),
    },
    {
        "path": "docs/compiler/binary_packaging/README.md",
        "role": (
            "runnable package guard evidence for active rows, route endpoint binding, "
            "capacity checks, and runtime control consistency"
        ),
    },
    {
        "path": "docs/vendor_reference/common_oper/operand-resource-and-route-audit.md",
        "role": (
            "COPY/COPYT evidence: sender executes route but destination block/PE/"
            "operand binding is receiver-owned"
        ),
    },
    {
        "path": "docs/vendor_reference/common_oper/source-fingerprint-index.md",
        "role": (
            "vendor-source fingerprint boundary: evidence must flow through typed "
            "OpenFabric owners and runtime/binary validation"
        ),
    },
    {
        "path": (
            "compiler/gpdpu_compiler/validation/dfu3500_partner_validation/"
            "build_payloads.py"
        ),
        "role": "log10max_single_task customer payload shape and runtime-control builder",
    },
    {
        "path": (
            "compiler/gpdpu_compiler/validation/dfu3500_partner_validation/"
            "payloads/log10max_single_task/MANIFEST.txt"
        ),
        "role": (
            "validation payload status: package complete assets exist, runtime "
            "functional path remains blocked by non-functional instruction rows"
        ),
    },
)


@dataclass(frozen=True)
class StrategyEvaluation:
    """Readiness record for one collective strategy."""

    strategy: Log10MaxCollectiveStrategy
    customer_label: Log10MaxCustomerLabel
    status: str
    blockers: tuple[str, ...]
    evidence: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "strategy": self.strategy.value,
            "customer_label": self.customer_label.value,
            "status": self.status,
            "blockers": list(self.blockers),
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class Pe00MaterializedScalarRequirement:
    """One closure requirement for PE00 staged scalar visibility."""

    requirement_id: str
    status: str
    evidence_path: str
    evidence: str
    missing_reason: str | None = None
    next_owner: str | None = None
    next_files: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "requirement_id": self.requirement_id,
            "status": self.status,
            "evidence_path": self.evidence_path,
            "evidence": self.evidence,
            "missing_reason": self.missing_reason,
            "next_owner": self.next_owner,
            "next_files": list(self.next_files),
        }


@dataclass(frozen=True)
class Pe00ScratchAllocationContract:
    """Source-level scratch contract for the PE00 materialized scalar."""

    contract_id: str
    source_id: str
    source_id_kind: str
    address_space: str
    offset_policy: str
    size_bytes: int
    dtype: str
    shape: tuple[int, ...]
    owner_processor: str
    consumer_processors: tuple[str, ...]
    materialization_pass: str
    address_materialization_status: str

    def to_plan(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "contract_level": "source_b_line_scratch_allocation",
            "source_id": self.source_id,
            "source_id_kind": self.source_id_kind,
            "address_space": self.address_space,
            "offset_policy": self.offset_policy,
            "size_bytes": self.size_bytes,
            "dtype": self.dtype,
            "shape": list(self.shape),
            "owner_processor": self.owner_processor,
            "consumer_processors": list(self.consumer_processors),
            "consumer_count": len(self.consumer_processors),
            "materialization_pass": self.materialization_pass,
            "address_materialization_status": self.address_materialization_status,
        }


@dataclass(frozen=True)
class Pe00ScalarScratchAddressCandidate:
    """Concrete-address candidate for the PE00 materialized scalar source."""

    candidate_id: str
    source_id: str
    source_id_kind: str
    logical_value_id: str
    size_bytes: int
    address_space: str | None
    address_space_status: str
    region_id: str | None
    region_status: str
    offset_bytes: int | None
    offset_status: str
    end_offset_bytes: int | None
    instance_base_addr_source: str | None
    candidate_status: str
    scratch_address_requirement_reason: str
    verification_status: str
    address_source_owner: str
    address_record_status: str
    app_storage_address_record: dict[str, object] | None
    required_source_record_schema: dict[str, object]
    searched_sources: tuple[dict[str, object], ...]

    @property
    def address_record_present(self) -> bool:
        return self.candidate_status == "candidate_address_record_present_but_unverified"

    def to_plan(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "source_id": self.source_id,
            "source_id_kind": self.source_id_kind,
            "logical_value_id": self.logical_value_id,
            "size_bytes": self.size_bytes,
            "address_space": self.address_space,
            "address_space_status": self.address_space_status,
            "region": {
                "region_id": self.region_id,
                "address_space": self.address_space,
                "offset_bytes": self.offset_bytes,
                "end_offset_bytes": self.end_offset_bytes,
                "size_bytes": self.size_bytes,
            },
            "region_id": self.region_id,
            "region_status": self.region_status,
            "offset_bytes": self.offset_bytes,
            "offset_status": self.offset_status,
            "end_offset_bytes": self.end_offset_bytes,
            "instance_base_addr_source": self.instance_base_addr_source,
            "candidate_status": self.candidate_status,
            "scratch_address_requirement_reason": (
                self.scratch_address_requirement_reason
            ),
            "verification_status": self.verification_status,
            "address_source_owner": self.address_source_owner,
            "address_record_status": self.address_record_status,
            "app_storage_address_record": (
                dict(self.app_storage_address_record)
                if self.app_storage_address_record is not None
                else None
            ),
            "required_source_record_schema": self.required_source_record_schema,
            "searched_sources": list(self.searched_sources),
        }


@dataclass(frozen=True)
class Pe00MaterializedScalarPlan:
    """Concrete work item for the PE00 materialized-scalar fallback."""

    status: str
    requirements: tuple[Pe00MaterializedScalarRequirement, ...]
    scratch_allocation_contract: Pe00ScratchAllocationContract
    scratch_address_candidate: Pe00ScalarScratchAddressCandidate
    runtime_order_contract: dict[str, object]
    micc_order_lowering_intent: dict[str, object]
    receiver_binding_contract: dict[str, object]
    global_scalar_template_contract: dict[str, object]
    scalar_visibility_interface: dict[str, object]
    delivery_work_item: dict[str, object]

    @property
    def closed(self) -> bool:
        return all(requirement.status == "available" for requirement in self.requirements)

    @property
    def open_requirement_ids(self) -> tuple[str, ...]:
        return tuple(
            requirement.requirement_id
            for requirement in self.requirements
            if requirement.status != "available"
        )

    def to_plan(self) -> dict[str, object]:
        return {
            "artifact": "pe00_materialized_scalar_plan",
            "strategy": Log10MaxCollectiveStrategy.PE00_AGGREGATE_MATERIALIZE.value,
            "customer_label": Log10MaxCustomerLabel.PE00_MATERIALIZED_SCALAR.value,
            "status": self.status,
            "closed": self.closed,
            "open_requirement_ids": list(self.open_requirement_ids),
            "requirements": [
                requirement.to_plan() for requirement in self.requirements
            ],
            "scratch_allocation_contract": (
                self.scratch_allocation_contract.to_plan()
            ),
            "scratch_address_candidate": self.scratch_address_candidate.to_plan(),
            "runtime_order_contract": self.runtime_order_contract,
            "micc_order_lowering_intent": self.micc_order_lowering_intent,
            "receiver_binding_contract": self.receiver_binding_contract,
            "global_scalar_template_contract": self.global_scalar_template_contract,
            "scalar_visibility_interface": self.scalar_visibility_interface,
            "delivery_work_item": self.delivery_work_item,
            "runtime_ready": False,
            "delivery_blocked": not self.closed,
            "not_a_direct_physical_allreduce": True,
        }


@dataclass(frozen=True)
class Log10MaxCapacityProofReport:
    """Customer-shape capacity and memory visibility report."""

    recommended_delivery_strategy: Log10MaxCollectiveStrategy
    recommended_delivery_customer_label: Log10MaxCustomerLabel
    selected_delivery_strategy: Log10MaxCollectiveStrategy | None
    selected_delivery_customer_label: Log10MaxCustomerLabel | None
    internal_waiver_strategy: Log10MaxCollectiveStrategy | None
    internal_waiver_customer_label: Log10MaxCustomerLabel | None
    delivery_status: str
    delivery_blockers: tuple[str, ...]
    input_tensor: dict[str, object]
    output_tensor: dict[str, object]
    tile_shape: dict[str, object]
    pe_sharding: dict[str, object]
    scratch: dict[str, object]
    runtime_launch: dict[str, object]
    capacity: dict[str, object]
    pe00_materialized_scalar_plan: Pe00MaterializedScalarPlan
    strategy_evaluations: tuple[StrategyEvaluation, ...]
    memory_visibility: tuple[str, ...]
    delivery_profile: dict[str, object]
    diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "log10max_collective_strategy_report",
            "recommended_delivery_strategy": (
                self.recommended_delivery_strategy.value
            ),
            "recommended_delivery_customer_label": (
                self.recommended_delivery_customer_label.value
            ),
            "selected_delivery_strategy": (
                self.selected_delivery_strategy.value
                if self.selected_delivery_strategy
                else None
            ),
            "selected_delivery_customer_label": (
                self.selected_delivery_customer_label.value
                if self.selected_delivery_customer_label
                else None
            ),
            "internal_waiver_strategy": (
                self.internal_waiver_strategy.value
                if self.internal_waiver_strategy
                else None
            ),
            "internal_waiver_customer_label": (
                self.internal_waiver_customer_label.value
                if self.internal_waiver_customer_label
                else None
            ),
            "delivery_status": self.delivery_status,
            "delivery_blockers": list(self.delivery_blockers),
            "runtime_ready": (
                self.selected_delivery_strategy is not None
                and self.runtime_launch.get("runtime_launch_supported") is True
                and not self.delivery_blockers
            ),
            "delivery_blocked": bool(self.delivery_blockers),
            "collective_strategy": self.recommended_delivery_strategy.value,
            "customer_collective_label": (
                self.recommended_delivery_customer_label.value
            ),
            "direct_route_reduce_broadcast": "deferred",
            "task_axis": self.delivery_profile["task_axis"],
            "runtime_ordering_domain": self.delivery_profile[
                "runtime_ordering_domain"
            ],
            "cross_task_one_app_ring": self.delivery_profile[
                "cross_task_one_app_ring"
            ],
            "cross_task_visibility_claim": self.delivery_profile[
                "cross_task_visibility_claim"
            ],
            "task_axis_scope": self.delivery_profile["task_axis_scope"],
            "delivery_profile": self.delivery_profile,
            "ring_first_delivery_status": self.delivery_status,
            "ring_first_delivery_plan": {
                "profile": self.delivery_profile,
                "collective_strategy": LOG10MAX_RING_FIRST_STRATEGY.value,
                "customer_collective_label": (
                    LOG10MAX_RING_FIRST_CUSTOMER_LABEL.value
                ),
                "direct_route_reduce_broadcast": "deferred",
                "task_axis": self.delivery_profile["task_axis"],
                "runtime_ordering_domain": self.delivery_profile[
                    "runtime_ordering_domain"
                ],
                "cross_task_visibility_claim": self.delivery_profile[
                    "cross_task_visibility_claim"
                ],
                "runtime_app_count": self.runtime_launch.get(
                    "required_launch_count"
                ),
                "representative_selection": {
                    "status": "unresolved",
                    "plan": "col0_representative_row_column_reduce_broadcast",
                },
                "ring_edges": [],
                "route_role_bindings": [
                    {
                        "role": "GlobalMax",
                        "route_template_family": "existing_operand_route_family",
                        "source_value_kind": "scalar",
                        "destination_value_kind": "scalar",
                        "template_evidence_id": None,
                        "proof_status": "unresolved",
                    }
                ],
                "phase_order": {"status": "unresolved"},
                "global_max_distribution": {"status": "unresolved"},
                "consumer_global_max_binding": {"status": "unresolved"},
                "consumer_global_max_ready_dependencies": {
                    "status": "unresolved"
                },
                "capacity": {"status": "unproven"},
                "dtype_update_op": {"status": "unresolved"},
                "symbolic_global_max_reaches_postprocess": True,
                "authority": "derived_validation_metadata_only",
            },
            # Backward-compatible aliases now mean delivery selection only.
            "selected_strategy": (
                self.selected_delivery_strategy.value
                if self.selected_delivery_strategy
                else None
            ),
            "selected_customer_label": (
                self.selected_delivery_customer_label.value
                if self.selected_delivery_customer_label
                else None
            ),
            "selection_status": self.delivery_status,
            "input_tensor": self.input_tensor,
            "output_tensor": self.output_tensor,
            "tile_shape": self.tile_shape,
            "pe_sharding": self.pe_sharding,
            "scratch": self.scratch,
            "runtime_launch": self.runtime_launch,
            "capacity": self.capacity,
            "pe00_materialized_scalar_plan": (
                self.pe00_materialized_scalar_plan.to_plan()
            ),
            "strategy_evaluations": [
                evaluation.to_plan() for evaluation in self.strategy_evaluations
            ],
            "rejected_strategies": [
                evaluation.to_plan()
                for evaluation in self.strategy_evaluations
                if evaluation.strategy != self.selected_delivery_strategy
            ],
            "selected_strategy_blockers": _selected_blockers(
                self.selected_delivery_strategy,
                self.strategy_evaluations,
            ),
            "memory_visibility": list(self.memory_visibility),
            "evidence_sources": list(EVIDENCE_SOURCES),
            "diagnostics": list(self.diagnostics),
            "layering_policy": (
                "report_only_consumes_chip_logical_tile_runtime_plans;"
                "symbolic_collective_must_not_be_reported_as_physical_route;"
                "ring_spmd_row_then_col_is_delivery_scoped_not_generic_allreduce;"
                "pe00_aggregate_is_staged_materialized_collective_not_direct_allreduce;"
                "redundant_spmd_is_internal_waiver_not_customer_delivery_strategy;"
                "b_line_allreduce_remains_expected_with_ring_first_strategy_and_pe00_"
                "debug_escape_hatch"
            ),
        }


def build_current_log10max_env() -> ChipEnv:
    """Build the current customer-shape log10max example."""

    env = ChipEnv("log10max_audio_preprocess")
    env.configure_task_axis(task_axis_size=1, physical_mesh_shape=(4, 4))

    mel_sram = env.sram_tensor(
        "mel_spec",
        shape=LOG10MAX_CUSTOMER_SHAPE,
        dtype=LOG10MAX_CUSTOMER_DTYPE,
        offset_bytes=LOG10MAX_INPUT_OFFSET_BYTES,
        role="input",
    )
    out_sram = env.sram_tensor(
        "Y",
        shape=LOG10MAX_CUSTOMER_SHAPE,
        dtype=LOG10MAX_CUSTOMER_DTYPE,
        offset_bytes=LOG10MAX_OUTPUT_OFFSET_BYTES,
        role="output",
    )

    mel = env.load(
        mel_sram,
        placements=[TaskShard("log10max_single_task_tile"), Shard(0), Shard(1)],
    )
    log_spec = log10(clamp_min(mel, min_value=1.0e-10))
    global_max = reduce_max(log_spec)
    threshold = add_scalar(global_max, -8.0)
    clipped = maximum(log_spec, threshold)
    normalized = mul_scalar(add_scalar(clipped, 4.0), 0.25)

    env.store(normalized, out_sram)
    env.output("Y", out_sram)
    return env


def build_current_log10max_plan() -> dict[str, Any]:
    """Generate the current end-to-end structural plan for log10max."""

    return build_current_log10max_env().generate()


def build_log10max_capacity_proof_report(
    full_plan: dict[str, Any],
    *,
    allow_internal_redundant_recompute: bool = True,
) -> Log10MaxCapacityProofReport:
    """Build a fail-closed collective strategy and capacity report."""

    chip_program = full_plan["chip_program"]
    logical_plan = full_plan["processor_logical_program"]
    tile_program = full_plan["processor_tile_program"]
    runtime_plan = full_plan["runtime_package_assignment"]

    input_tensor = _single_sram_tensor_with_role(chip_program, "input")
    output_tensor = _single_sram_tensor_with_role(chip_program, "output")
    logical_reduce = _single_logical_reduce(logical_plan)
    collective_bundle = _single_collective_bundle(tile_program)

    local_input = _local_value_for_tensor(
        logical_plan,
        tensor_id=str(input_tensor["id"]),
        processor=str(logical_reduce["participants"][0]),
    )
    storage_region = _single_app_storage_region(tile_program)
    scratch_bytes = _storage_region_nbytes(storage_region)
    runtime_launch = _runtime_launch_report(runtime_plan)
    runtime_launch["task_axis_size"] = int(
        chip_program.get("task_axis_mesh", {}).get("task_axis_size", 1)
    )
    runtime_launch["runtime_ordering_domain"] = (
        LOG10MAX_RING_FIRST_ORDERING_DOMAIN
        if runtime_launch["task_axis_size"] == LOG10MAX_RING_FIRST_TASK_AXIS
        else "cross_task_requires_app_barrier"
    )
    pe_count = len(logical_reduce["participants"])
    input_bytes = int(input_tensor["nbytes"])
    output_bytes = int(output_tensor["nbytes"])
    local_shard_bytes = _nbytes_for_shape_dtype(
        local_input["local_shape"],
        str(input_tensor["dtype"]),
    )

    evidence = _PlanEvidence(
        logical_reduce=logical_reduce,
        collective_bundle=collective_bundle,
        app_plan=full_plan["app_plan"],
        tile_program=tile_program,
        runtime_plan=runtime_plan,
        runtime_launch=runtime_launch,
        storage_region=storage_region,
    )
    pe00_plan = _build_pe00_materialized_scalar_plan(evidence)
    evaluations = (
        _evaluate_direct_route_reduce_broadcast(evidence),
        _evaluate_ring_spmd_row_then_col(evidence),
        _evaluate_pe00_aggregate_materialize(evidence, pe00_plan),
        _evaluate_redundant_spmd_recompute(
            evidence,
            allow_internal_redundant_recompute=allow_internal_redundant_recompute,
        ),
    )
    recommended_delivery = _evaluation_for_strategy(
        evaluations,
        LOG10MAX_RING_FIRST_STRATEGY,
    )
    selected_delivery = _select_delivery_strategy(evaluations)
    internal_waiver = _select_internal_waiver_strategy(evaluations)
    delivery_status = _delivery_status(recommended_delivery, selected_delivery)

    return Log10MaxCapacityProofReport(
        recommended_delivery_strategy=recommended_delivery.strategy,
        recommended_delivery_customer_label=recommended_delivery.customer_label,
        selected_delivery_strategy=(
            selected_delivery.strategy if selected_delivery else None
        ),
        selected_delivery_customer_label=(
            selected_delivery.customer_label if selected_delivery else None
        ),
        internal_waiver_strategy=(
            internal_waiver.strategy if internal_waiver else None
        ),
        internal_waiver_customer_label=(
            internal_waiver.customer_label if internal_waiver else None
        ),
        delivery_status=delivery_status,
        delivery_blockers=tuple(recommended_delivery.blockers),
        input_tensor=_tensor_report(input_tensor),
        output_tensor=_tensor_report(output_tensor),
        tile_shape={
            "configured_tile_sizes": dict(tile_program["tile_sizes"]),
            "per_pe_local_shape": list(local_input["local_shape"]),
            "per_pe_local_shard_bytes": local_shard_bytes,
            "logical_reduce_scalar_shape": list(storage_region.get("shape", [])),
        },
        pe_sharding={
            "mesh_shape": list(tile_program["processor_shape"]),
            "participant_count": pe_count,
            "participants": list(logical_reduce["participants"]),
            "input_placements": list(local_input["placements"]),
            "per_pe_input_global_offset_example": list(local_input["global_offset"]),
            "reduce_scope": "single_task_4x4_pe_group",
        },
        scratch={
            "storage_id": storage_region.get("storage_id"),
            "value_id": storage_region.get("value_id"),
            "dtype": storage_region.get("dtype"),
            "shape": list(storage_region.get("shape", [])),
            "scratch_bytes": scratch_bytes,
            "region_status": (
                "symbolic_no_address"
                if "offset_bytes" not in storage_region
                else "addressed"
            ),
            "owner_processor": _pe00_owner(tile_program),
            "materialize_action_count": _app_storage_action_count(
                tile_program,
                action_kind="reduce_store",
            ),
            "load_action_count": _app_storage_action_count(
                tile_program,
                action_kind="broadcast_load",
            ),
            "pe00_staged_materialization_evidence": {
                "supported_by_current_ir": (
                    "one PE00 reduce_store action and per-PE broadcast_load actions "
                    "exist as symbolic app storage actions"
                ),
                "softmax_workflow_analogy": (
                    "softmax_1 proves a staged two-subtask workflow with SPM/SUM "
                    "intermediate write then later readback, but not this log10max "
                    "PE00 scalar implementation"
                ),
                "not_a_direct_physical_allreduce": True,
            },
        },
        runtime_launch=runtime_launch,
        capacity={
            "input_bytes": input_bytes,
            "output_bytes": output_bytes,
            "scratch_bytes": scratch_bytes,
            "participant_count": pe_count,
            "sharded_input_read_bytes_per_wave": input_bytes,
            "redundant_recompute_read_bytes_per_pe": input_bytes,
            "redundant_recompute_total_read_bytes": input_bytes * pe_count,
            "output_write_bytes_per_wave": output_bytes,
        },
        pe00_materialized_scalar_plan=pe00_plan,
        strategy_evaluations=evaluations,
        memory_visibility=_memory_visibility(evidence),
        delivery_profile=_ring_first_delivery_profile(full_plan),
        diagnostics=_diagnostics(full_plan),
    )


def summarize_log10max_capacity_proof_report(
    report: Log10MaxCapacityProofReport,
) -> dict[str, object]:
    """Return stable high-level fields for focused checks."""

    plan = report.to_plan()
    status_counts: dict[str, int] = {}
    for evaluation in plan["strategy_evaluations"]:
        status = str(evaluation["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "recommended_delivery_strategy": plan["recommended_delivery_strategy"],
        "recommended_delivery_customer_label": plan[
            "recommended_delivery_customer_label"
        ],
        "selected_delivery_strategy": plan["selected_delivery_strategy"],
        "selected_delivery_customer_label": plan["selected_delivery_customer_label"],
        "internal_waiver_strategy": plan["internal_waiver_strategy"],
        "internal_waiver_customer_label": plan["internal_waiver_customer_label"],
        "delivery_status": plan["delivery_status"],
        "selected_strategy": plan["selected_strategy"],
        "selected_customer_label": plan["selected_customer_label"],
        "selection_status": plan["selection_status"],
        "input_shape": plan["input_tensor"]["shape"],
        "output_shape": plan["output_tensor"]["shape"],
        "dtype": plan["input_tensor"]["dtype"],
        "participant_count": plan["pe_sharding"]["participant_count"],
        "scratch_bytes": plan["scratch"]["scratch_bytes"],
        "runtime_launch_count": plan["runtime_launch"]["required_launch_count"],
        "runtime_launch_supported": plan["runtime_launch"]["runtime_launch_supported"],
        "runtime_ready": plan["runtime_ready"],
        "delivery_blocked": plan["delivery_blocked"],
        "collective_strategy": plan["collective_strategy"],
        "customer_collective_label": plan["customer_collective_label"],
        "direct_route_reduce_broadcast": plan["direct_route_reduce_broadcast"],
        "task_axis": plan["task_axis"],
        "runtime_ordering_domain": plan["runtime_ordering_domain"],
        "cross_task_one_app_ring": plan["cross_task_one_app_ring"],
        "cross_task_visibility_claim": plan["cross_task_visibility_claim"],
        "strategy_status_counts": dict(sorted(status_counts.items())),
        "selected_strategy_blockers": plan["selected_strategy_blockers"],
        "delivery_blocker_count": len(plan["delivery_blockers"]),
        "pe00_plan_status": plan["pe00_materialized_scalar_plan"]["status"],
        "pe00_open_requirement_count": len(
            plan["pe00_materialized_scalar_plan"]["open_requirement_ids"]
        ),
    }


@dataclass(frozen=True)
class _PlanEvidence:
    logical_reduce: dict[str, Any]
    collective_bundle: dict[str, Any]
    app_plan: dict[str, Any]
    tile_program: dict[str, Any]
    runtime_plan: dict[str, Any]
    runtime_launch: dict[str, object]
    storage_region: dict[str, Any]


def _evaluate_direct_route_reduce_broadcast(
    evidence: _PlanEvidence,
) -> StrategyEvaluation:
    blockers: list[str] = []
    route_actions = evidence.tile_program["tile_route_actions"]
    if not route_actions:
        blockers.append("direct_route_evidence_missing")
    if evidence.collective_bundle["collective_kind"].endswith("_symbolic"):
        blockers.append("collective_bundle_is_symbolic")
    if (
        evidence.collective_bundle["attrs"].get("implementation_status")
        == "symbolic_collective_not_physical_route"
    ):
        blockers.append("physical_allreduce_not_implemented")
    if not any(
        action["attrs"].get("logical_reduce_edge_id") == evidence.logical_reduce["id"]
        for action in route_actions.values()
    ):
        blockers.append("no_reduce_route_actions_for_logical_reduce")

    return StrategyEvaluation(
        strategy=Log10MaxCollectiveStrategy.DIRECT_ROUTE_REDUCE_BROADCAST,
        customer_label=Log10MaxCustomerLabel.PHYSICAL_ROUTE_ALLREDUCE,
        status="blocked",
        blockers=tuple(dict.fromkeys(blockers)),
        evidence=(
            "LogicalReduceEdge exists for reduce_max",
            "TileCollectiveBundle exists but is all_reduce_max_symbolic",
        ),
    )


def _evaluate_ring_spmd_row_then_col(
    evidence: _PlanEvidence,
) -> StrategyEvaluation:
    blockers = list(RING_FIRST_DELIVERY_BLOCKERS)
    task_axis_size = evidence.runtime_launch.get("task_axis_size")
    if task_axis_size != LOG10MAX_RING_FIRST_TASK_AXIS:
        blockers.insert(0, "task_axis_scope_unproven")
    return StrategyEvaluation(
        strategy=LOG10MAX_RING_FIRST_STRATEGY,
        customer_label=LOG10MAX_RING_FIRST_CUSTOMER_LABEL,
        status="delivery_selected_blocked_on_route_binding",
        blockers=tuple(dict.fromkeys(blockers)),
        evidence=(
            "RFC bline-log10max-task-local-ring-execution selects "
            "representative row/column reduce+broadcast for first delivery",
            "current log10max compile profile uses task_axis=1 so a one-app "
            "ring stays inside one task-local ordering domain",
            "ring edges must reuse StreamAction(route_push/route_recv), "
            "FiberOp(fragment_route_push/fragment_route_recv), and route_path "
            "dependency proof machinery",
            "no new communication IR and no generic allreduce framework are "
            "introduced by this strategy declaration",
        ),
    )


def _ring_first_delivery_profile(full_plan: dict[str, Any]) -> dict[str, object]:
    chip_program = full_plan["chip_program"]
    task_axis_mesh = chip_program.get("task_axis_mesh", {})
    task_axis = int(
        task_axis_mesh.get("task_axis_size", LOG10MAX_RING_FIRST_TASK_AXIS)
    )
    return {
        "profile_id": "log10max_ring_first_task_axis_1_v1",
        "collective_strategy": LOG10MAX_RING_FIRST_STRATEGY.value,
        "customer_collective_label": LOG10MAX_RING_FIRST_CUSTOMER_LABEL.value,
        "direct_route_reduce_broadcast": "deferred",
        "task_axis": task_axis,
        "required_task_axis": LOG10MAX_RING_FIRST_TASK_AXIS,
        "task_axis_scope": (
            "single_task_group" if task_axis == 1 else "cross_task_forbidden"
        ),
        "runtime_ordering_domain": LOG10MAX_RING_FIRST_ORDERING_DOMAIN,
        "cross_task_one_app_ring": "forbidden",
        "cross_task_visibility_claim": False,
        "cross_task_requires_app_barrier": True,
        "first_delivery_plan": "representative_row_column_reduce_broadcast",
        "full_ring_generalization": "deferred",
        "communication_ir": "existing_stream_route_actions_only",
        "ring_metadata_authority": "derived_validation_metadata_only",
    }


def _build_pe00_materialized_scalar_plan(
    evidence: _PlanEvidence,
) -> Pe00MaterializedScalarPlan:
    materialize_actions = _app_storage_actions(
        evidence.tile_program,
        action_kind="reduce_store",
    )
    load_actions = _app_storage_actions(
        evidence.tile_program,
        action_kind="broadcast_load",
    )
    pe00_materialize = [
        action for action in materialize_actions if action["processor"] == "processor_0_0"
    ]
    participants = tuple(evidence.logical_reduce["participants"])
    storage_shape = list(evidence.storage_region.get("shape", []))
    storage_dtype = str(evidence.storage_region.get("dtype"))
    storage_bytes = _storage_region_nbytes(evidence.storage_region)
    storage_id = str(evidence.storage_region.get("storage_id"))
    value_id = str(evidence.storage_region.get("value_id"))
    scalar_name = str(evidence.logical_reduce["output_logical_tensor_name"])
    address_candidate = _pe00_scratch_address_candidate(
        storage_region=evidence.storage_region,
        app_plan=evidence.app_plan,
        tile_program=evidence.tile_program,
        runtime_plan=evidence.runtime_plan,
        source_id=storage_id,
        value_id=value_id,
        size_bytes=storage_bytes,
    )
    allocation_contract = Pe00ScratchAllocationContract(
        contract_id=f"pe00_scratch_allocation:{storage_id}",
        source_id=storage_id,
        source_id_kind="app_storage_region",
        address_space="sram",
        offset_policy=(
            "compiler_allocated_scratch_offset; materialize offset_bytes and "
            "instance base_addr before tile store/load lowering"
        ),
        size_bytes=storage_bytes,
        dtype=storage_dtype,
        shape=tuple(int(dim) for dim in storage_shape),
        owner_processor="processor_0_0",
        consumer_processors=participants,
        materialization_pass="source_scratch_allocation",
        address_materialization_status=(
            "compiler_allocated_offset_candidate_available"
            if address_candidate.candidate_status
            == "compiler_allocated_address_candidate_available"
            else "pending_offset_bytes_and_instance_base_addr"
            if "offset_bytes" not in evidence.storage_region
            else "available"
        ),
    )
    scratch_slot = _pe00_scratch_slot_name(
        source_id=storage_id,
        offset_bytes=address_candidate.offset_bytes,
        dtype=storage_dtype,
    )
    runtime_order_contract = Pe00MaterializedScalarRuntimeOrderContract(
        source_id=storage_id,
        producer_processor="processor_0_0",
        consumer_processors=participants,
    ).to_plan()
    micc_order_lowering_intent = (
        build_pe00_materialized_scalar_micc_lowering_intent(
            runtime_order_contract
        )
    )
    receiver_binding_contract = Pe00ScalarReceiverBindingContract(
        source_id=storage_id,
        scratch_slot=scratch_slot,
        consumer_processors=participants,
        dtype=storage_dtype,
    ).to_plan()
    global_scalar_template_contract = build_pe00_global_scalar_template_contract(
        source_id=storage_id,
        source_name=scalar_name,
        scratch_slot=scratch_slot,
        scratch_offset_bytes=address_candidate.offset_bytes or 0,
        consumer_processors=participants,
        runtime_order_contract=runtime_order_contract,
        receiver_binding_contract=receiver_binding_contract,
    ).to_artifact()

    requirements = (
        Pe00MaterializedScalarRequirement(
            requirement_id="scratch_region_shape",
            status="available",
            evidence_path="processor_tile_program.app_storage_regions",
            evidence=(
                f"{storage_id} has dtype={storage_dtype}, shape={storage_shape}, "
                f"scratch_bytes={storage_bytes}"
            ),
        ),
        Pe00MaterializedScalarRequirement(
            requirement_id="source_scratch_allocation_contract",
            status="available",
            evidence_path="pe00_materialized_scalar_plan.scratch_allocation_contract",
            evidence=(
                f"{allocation_contract.source_id} is the B-line source id for "
                f"{allocation_contract.size_bytes}B {allocation_contract.dtype} "
                "PE00-owned scratch"
            ),
        ),
        Pe00MaterializedScalarRequirement(
            requirement_id="scratch_address_materialization",
            status=(
                "available"
                if address_candidate.candidate_status
                == "compiler_allocated_address_candidate_available"
                else "missing"
            ),
            evidence_path="pe00_materialized_scalar_plan.scratch_address_candidate",
            evidence=_scratch_address_requirement_evidence(address_candidate),
            missing_reason=(
                None
                if address_candidate.candidate_status
                == "compiler_allocated_address_candidate_available"
                else address_candidate.scratch_address_requirement_reason
            ),
            next_owner=(
                None
                if address_candidate.candidate_status
                == "compiler_allocated_address_candidate_available"
                else "source_scratch_allocation"
            ),
            next_files=()
            if address_candidate.candidate_status
            == "compiler_allocated_address_candidate_available"
            else (
                "compiler/gpdpu_compiler/core/program_tile.py",
                "compiler/gpdpu_compiler/core/program_runtime.py",
            ),
        ),
        Pe00MaterializedScalarRequirement(
            requirement_id="producer_pe00_store_action",
            status="available" if pe00_materialize else "missing",
            evidence_path="processor_tile_program.tile_app_storage_actions",
            evidence=(
                "one processor_0_0 reduce_store app storage action exists"
                if pe00_materialize
                else "no processor_0_0 reduce_store action found"
            ),
            missing_reason=None if pe00_materialize else "PE00 producer store action absent",
        ),
        Pe00MaterializedScalarRequirement(
            requirement_id="producer_pe00_physical_store",
            status=_contract_requirement_status(
                global_scalar_template_contract,
                "producer_pe00_physical_store",
            ),
            evidence_path=(
                "pe00_materialized_scalar_plan.global_scalar_template_contract."
                "producer_pe00_physical_store"
            ),
            evidence=(
                "PE00 scalar store is bound as a global_max_tile template "
                "contract; row bytes remain downstream"
            ),
            missing_reason=_contract_requirement_missing_reason(
                global_scalar_template_contract,
                "producer_pe00_physical_store",
                "needs PE00 scalar store template contract",
            ),
            next_owner=None
            if _contract_requirement_status(
                global_scalar_template_contract,
                "producer_pe00_physical_store",
            )
            == "available"
            else "tile_store_load_lowering",
            next_files=(
                "compiler/gpdpu_compiler/core/stream_compiler/log10max_template_pack.py",
                "compiler/gpdpu_compiler/core/stream_compiler/vendor_components.py",
            )
            if _contract_requirement_status(
                global_scalar_template_contract,
                "producer_pe00_physical_store",
            )
            != "available"
            else (),
        ),
        Pe00MaterializedScalarRequirement(
            requirement_id="consumer_broadcast_load_actions",
            status=(
                "available"
                if len(load_actions) == len(participants) and len(participants) > 0
                else "missing"
            ),
            evidence_path="processor_tile_program.tile_app_storage_actions",
            evidence=(
                f"{len(load_actions)} broadcast_load actions for "
                f"{len(participants)} participants"
            ),
            missing_reason=(
                None
                if len(load_actions) == len(participants) and len(participants) > 0
                else "needs one consumer load action per participant"
            ),
        ),
        Pe00MaterializedScalarRequirement(
            requirement_id="consumer_physical_readback",
            status=_contract_requirement_status(
                global_scalar_template_contract,
                "consumer_physical_readback",
            ),
            evidence_path=(
                "pe00_materialized_scalar_plan.global_scalar_template_contract."
                "consumer_physical_readback"
            ),
            evidence=(
                "per-PE scalar readback is bound as receiver-owned template "
                "contract; row bytes remain downstream"
            ),
            missing_reason=_contract_requirement_missing_reason(
                global_scalar_template_contract,
                "consumer_physical_readback",
                "needs per-PE scalar readback template contract",
            ),
            next_owner=None
            if _contract_requirement_status(
                global_scalar_template_contract,
                "consumer_physical_readback",
            )
            == "available"
            else "tile_store_load_lowering",
            next_files=(
                "compiler/gpdpu_compiler/core/stream_compiler/log10max_template_pack.py",
                "compiler/gpdpu_compiler/core/stream_compiler/vendor_components.py",
            )
            if _contract_requirement_status(
                global_scalar_template_contract,
                "consumer_physical_readback",
            )
            != "available"
            else (),
        ),
        Pe00MaterializedScalarRequirement(
            requirement_id="materialize_before_readback_dependency",
            status=(
                "available"
                if _has_materialize_then_load_dependency(evidence.tile_program)
                else "missing"
            ),
            evidence_path="processor_tile_program.tile_dependencies",
            evidence=(
                "materialized_storage_before_app_load dependencies exist"
                if _has_materialize_then_load_dependency(evidence.tile_program)
                else "no materialized_storage_before_app_load dependency found"
            ),
            missing_reason=(
                None
                if _has_materialize_then_load_dependency(evidence.tile_program)
                else "needs materialize-before-readback dependency edge"
            ),
        ),
        Pe00MaterializedScalarRequirement(
            requirement_id="runtime_subtask_order",
            status=str(runtime_order_contract["status"]),
            evidence_path=(
                "pe00_materialized_scalar_plan.runtime_order_contract"
            ),
            evidence=(
                "B-line runtime order contract pins combine/store before "
                "readback/consume; MICC rows remain downstream"
            ),
            missing_reason=None
            if runtime_order_contract["status"] == "available"
            else (
                "needs concrete task/subtask successor chain, launch count, "
                "and wait order for PE00 write before all-PE readback"
            ),
            next_owner=None
            if runtime_order_contract["status"] == "available"
            else "runtime_subtask_order",
            next_files=(
                "compiler/gpdpu_compiler/core/program_runtime.py",
                "compiler/gpdpu_compiler/core/stream_compiler/micc_component_writers.py",
            )
            if runtime_order_contract["status"] != "available"
            else (),
        ),
        Pe00MaterializedScalarRequirement(
            requirement_id="receiver_binding",
            status=str(receiver_binding_contract["status"]),
            evidence_path=(
                "pe00_materialized_scalar_plan.receiver_binding_contract"
            ),
            evidence=(
                "receiver-owned scalar destination binding is explicit for every "
                "consumer PE"
            ),
            missing_reason=None
            if receiver_binding_contract["status"] == "available"
            else "needs receiver-owned load/visibility binding for every consumer PE",
            next_owner=None
            if receiver_binding_contract["status"] == "available"
            else "receiver_binding",
            next_files=(
                "compiler/gpdpu_compiler/core/stream_compiler/binding.py",
                "compiler/gpdpu_compiler/core/stream_compiler/template_ops.py",
            )
            if receiver_binding_contract["status"] != "available"
            else (),
        ),
        Pe00MaterializedScalarRequirement(
            requirement_id="pe00_fmax_combine_order",
            status=_contract_requirement_status(
                global_scalar_template_contract,
                "pe00_fmax_combine_order",
            ),
            evidence_path=(
                "pe00_materialized_scalar_plan.global_scalar_template_contract."
                "pe00_fmax_combine_order"
            ),
            evidence=(
                "ordered PE00 FMAX combine chain is explicit in the "
                "global_max_tile template contract"
            ),
            missing_reason=_contract_requirement_missing_reason(
                global_scalar_template_contract,
                "pe00_fmax_combine_order",
                "needs ordered PE00 FMAX combine chain over local maxima before store",
            ),
            next_owner=None
            if _contract_requirement_status(
                global_scalar_template_contract,
                "pe00_fmax_combine_order",
            )
            == "available"
            else "pe00_fmax_chain",
            next_files=(
                "compiler/gpdpu_compiler/core/stream_compiler/log10max_template_pack.py",
                "compiler/gpdpu_compiler/core/program_tile.py",
            )
            if _contract_requirement_status(
                global_scalar_template_contract,
                "pe00_fmax_combine_order",
            )
            != "available"
            else (),
        ),
    )
    status = (
        "closed"
        if all(requirement.status == "available" for requirement in requirements)
        else "blocked_missing_requirements"
    )
    return Pe00MaterializedScalarPlan(
        status=status,
        requirements=requirements,
        scratch_allocation_contract=allocation_contract,
        scratch_address_candidate=address_candidate,
        runtime_order_contract=runtime_order_contract,
        micc_order_lowering_intent=micc_order_lowering_intent,
        receiver_binding_contract=receiver_binding_contract,
        global_scalar_template_contract=global_scalar_template_contract,
        scalar_visibility_interface={
            "global_scalar_source_name": scalar_name,
            "logical_reduce_edge_id": evidence.logical_reduce["id"],
            "source_value_id": value_id,
            "delivery_source_id": storage_id,
            "delivery_source_id_kind": "app_storage_region",
            "scratch_slot": {
                "storage_id": storage_id,
                "dtype": storage_dtype,
                "shape": storage_shape,
                "scratch_bytes": storage_bytes,
                "allocation_contract_id": allocation_contract.contract_id,
                "address_candidate_id": address_candidate.candidate_id,
                "template_contract_status": global_scalar_template_contract["status"],
                "owner_processor": "processor_0_0" if pe00_materialize else None,
                "address_status": (
                    "available"
                    if address_candidate.offset_bytes is not None
                    else "missing"
                ),
                "offset_bytes": address_candidate.offset_bytes,
            },
            "producer_contract": {
                "producer_processor": "processor_0_0",
                "action_kind": "reduce_store",
                "requires_ordered_fmax_combine_before_store": True,
            },
            "load_route_consumer_contract": {
                "consumer_processors": list(participants),
                "consumer_count": len(participants),
                "load_action_kind": "broadcast_load",
                "visibility": "materialized_storage_then_per_pe_readback",
                "receiver_binding_required": True,
                "receiver_binding_contract_status": receiver_binding_contract[
                    "status"
                ],
                "physical_route_allreduce": False,
            },
        },
        delivery_work_item={
            "source_id": storage_id,
            "source_id_kind": "app_storage_region",
            "source_contract_id": allocation_contract.contract_id,
            "selected_when": "all_pe00_requirements_available",
            "address_materialization_owner": "source_scratch_allocation",
            "address_materialization_pass": (
                "compiler/gpdpu_compiler/core/program_tile.py "
                "AppStorageRegion allocation before store/load lowering"
            ),
            "minimum_code_owners": _pe00_delivery_minimum_code_owners(),
            "remaining_scope": (
                "lower the selected PE00 contracts into vendor row bytes and "
                "prove runtime execution; B-line template binding is closed"
            ),
            "remaining_blockers": list(PE00_REMAINING_DELIVERY_BLOCKERS),
            "remaining_blocker_count": len(PE00_REMAINING_DELIVERY_BLOCKERS),
        },
    )


def _pe00_scratch_slot_name(
    *,
    source_id: str,
    offset_bytes: int | None,
    dtype: str,
) -> str:
    offset = "unknown" if offset_bytes is None else f"0x{offset_bytes:x}"
    return f"pe00.sram.{source_id}.offset_{offset}.{dtype}"


def _contract_requirement_status(
    contract: dict[str, object],
    key: str,
) -> str:
    item = contract.get(key)
    if not isinstance(item, dict):
        return "missing"
    return str(item.get("status", "missing"))


def _contract_requirement_missing_reason(
    contract: dict[str, object],
    key: str,
    default: str,
) -> str | None:
    status = _contract_requirement_status(contract, key)
    if status == "available":
        return None
    return default


def _pe00_scratch_address_candidate(
    *,
    storage_region: dict[str, Any],
    app_plan: dict[str, Any],
    tile_program: dict[str, Any],
    runtime_plan: dict[str, Any],
    source_id: str,
    value_id: str,
    size_bytes: int,
) -> Pe00ScalarScratchAddressCandidate:
    address_record = _app_storage_address_record_for_source(tile_program, source_id)
    address_source = address_record if address_record is not None else storage_region
    compiler_allocated_source = _compiler_allocated_log10max_scratch_address_source(
        source_id=source_id,
        value_id=value_id,
        size_bytes=size_bytes,
    )
    address_space = _optional_str(address_source.get("address_space"))
    offset_bytes = _optional_int(address_source.get("offset_bytes"))
    end_offset_bytes = _optional_int(
        address_source.get("end_offset_bytes")
        or address_source.get("region", {}).get("end_offset_bytes")
    )
    region_id = _optional_str(
        address_source.get("region_id")
        or address_source.get("region", {}).get("region_id")
        or storage_region.get("region_id")
        or storage_region.get("region", {}).get("region_id")
        or storage_region.get("storage_id")
    )
    instance_base_addr_source = _optional_str(
        address_source.get("instance_base_addr_source")
        or address_source.get("base_addr_source")
        or address_source.get("legacy_base_addr_source")
    )
    if (
        compiler_allocated_source is not None
        and (
            address_space is None
            or offset_bytes is None
            or instance_base_addr_source is None
        )
    ):
        address_space = _optional_str(compiler_allocated_source.get("address_space"))
        offset_bytes = _optional_int(compiler_allocated_source.get("offset_bytes"))
        end_offset_bytes = _optional_int(
            compiler_allocated_source.get("end_offset_bytes")
        )
        instance_base_addr_source = _optional_str(
            compiler_allocated_source.get("instance_base_addr_source")
        )
    has_app_storage_address_record = address_record is not None
    has_complete_address_source = (
        address_space is not None
        and offset_bytes is not None
        and instance_base_addr_source is not None
    )
    if compiler_allocated_source is not None and has_complete_address_source:
        candidate_status = "compiler_allocated_address_candidate_available"
        scratch_address_requirement_reason = (
            "compiler_allocated_offset_candidate_available"
        )
        verification_status = (
            "report-only source_scratch_allocation candidate; physical store/load "
            "validation still required"
        )
    elif has_app_storage_address_record or has_complete_address_source:
        candidate_status = "candidate_address_record_present_but_unverified"
        scratch_address_requirement_reason = (
            "candidate_address_record_present_but_unverified"
        )
        verification_status = (
            "needs concrete offset/base_addr allocation plus physical store/load validation"
        )
    else:
        candidate_status = "blocked_missing_address_source"
        scratch_address_requirement_reason = "address_source_missing"
        verification_status = "not_verifiable_without_address_source"

    return Pe00ScalarScratchAddressCandidate(
        candidate_id=f"pe00_scalar_scratch_address_candidate:{source_id}",
        source_id=source_id,
        source_id_kind="app_storage_region",
        logical_value_id=value_id,
        size_bytes=size_bytes,
        address_space=address_space,
        address_space_status=(
            "present"
            if address_space is not None
            else (
                "missing_in_candidate_address_record"
                if has_app_storage_address_record
                else "missing_address_source"
            )
        ),
        region_id=region_id,
        region_status=(
            "compiler_allocated_region_candidate_available"
            if compiler_allocated_source is not None
            and has_complete_address_source
            else
            "app_storage_address_record_present"
            if has_app_storage_address_record
            else "app_storage_region_record_present"
            if region_id is not None
            else "missing_address_source"
        ),
        offset_bytes=offset_bytes,
        offset_status=(
            "present"
            if offset_bytes is not None
            else (
                "missing_concrete_offset"
                if has_app_storage_address_record
                else "missing_address_source"
            )
        ),
        end_offset_bytes=end_offset_bytes,
        instance_base_addr_source=instance_base_addr_source,
        candidate_status=candidate_status,
        scratch_address_requirement_reason=scratch_address_requirement_reason,
        verification_status=verification_status,
        address_source_owner="source_scratch_allocation",
        address_record_status=(
            "compiler_allocated_address_candidate_available"
            if compiler_allocated_source is not None
            and has_complete_address_source
            else
            str(address_record.get("status"))
            if address_record is not None
            else "missing"
        ),
        app_storage_address_record=address_record,
        required_source_record_schema=_required_address_source_record_schema(
            source_id=source_id,
            value_id=value_id,
            size_bytes=size_bytes,
        ),
        searched_sources=_searched_address_sources(
            app_plan=app_plan,
            tile_program=tile_program,
            runtime_plan=runtime_plan,
            storage_region=storage_region,
            compiler_allocated_source=compiler_allocated_source,
            source_id=source_id,
        ),
    )


def _required_address_source_record_schema(
    *,
    source_id: str,
    value_id: str,
    size_bytes: int,
) -> dict[str, object]:
    return {
        "record_kind": "app_storage_address_record",
        "source_id": source_id,
        "source_id_kind": "app_storage_region",
        "logical_value_id": value_id,
        "owner_processor": "processor_0_0",
        "required_fields": [
            "source_id",
            "source_id_kind",
            "logical_value_id",
            "address_space",
            "region_id",
            "offset_bytes",
            "size_bytes",
            "instance_base_addr_source",
        ],
        "optional_fields": [
            "end_offset_bytes",
            "legacy_base_addr_word",
            "legacy_base_addr_byte",
            "base_addr_slot",
        ],
        "address_space_values": ["sram", "spm"],
        "offset_unit": "bytes",
        "expected_size_bytes": size_bytes,
        "must_not_invent_or_default": [
            "address_space",
            "offset_bytes",
            "instance_base_addr_source",
        ],
    }


def _searched_address_sources(
    *,
    app_plan: dict[str, Any],
    tile_program: dict[str, Any],
    runtime_plan: dict[str, Any],
    storage_region: dict[str, Any],
    compiler_allocated_source: dict[str, object] | None,
    source_id: str,
) -> tuple[dict[str, object], ...]:
    return (
        _app_plan_address_source_search(app_plan, source_id),
        _tile_app_storage_region_address_source_search(storage_region, source_id),
        _tile_app_storage_address_record_search(tile_program, source_id),
        _compiler_allocated_address_source_search(
            compiler_allocated_source,
            source_id,
        ),
        _tile_app_storage_edge_action_address_source_search(tile_program, source_id),
        _runtime_package_address_source_search(runtime_plan, source_id),
        {
            "source_name": "stream_compiler_vendor_instance_base_addr",
            "file_path": (
                "compiler/gpdpu_compiler/core/stream_compiler/vendor_components.py"
            ),
            "plan_path": None,
            "status": "not_usable_for_log10max_app_storage_source",
            "fields_found": [
                "gemm_k_stream_a_b_legacy_base_addr_slots",
                "unresolved_generic_instance_base_addr_slots",
            ],
            "missing_fields": [
                "source_id",
                "app_storage_region_id",
                "log10max_scratch_offset_bytes",
            ],
            "evidence": (
                "base_addr records in this layer are GEMM A/B slot projections or "
                "generic unresolved placeholders, not a source-specific record for "
                f"{source_id}"
            ),
        },
    )


def _compiler_allocated_log10max_scratch_address_source(
    *,
    source_id: str,
    value_id: str,
    size_bytes: int,
) -> dict[str, object] | None:
    expected_source_id = f"app_storage:global_max:{value_id}"
    if source_id != expected_source_id or size_bytes != 4:
        return None
    return {
        "record_kind": "compiler_allocated_app_storage_address",
        "source_id": source_id,
        "source_id_kind": "app_storage_region",
        "logical_value_id": value_id,
        "address_space": "sram",
        "region_id": source_id,
        "offset_bytes": LOG10MAX_SCRATCH_OFFSET_BYTES,
        "end_offset_bytes": LOG10MAX_SCRATCH_OFFSET_BYTES + size_bytes,
        "size_bytes": size_bytes,
        "instance_base_addr_source": LOG10MAX_SCRATCH_INSTANCE_BASE_ADDR_SOURCE,
        "status": "compiler_allocated_offset_candidate_available",
        "evidence": [
            "log10max scratch is a 4B fp32 scalar",
            "offset is after current log10max output SRAM tensor",
            "report_only_physical_store_load_not_validated",
        ],
    }


def _compiler_allocated_address_source_search(
    source: dict[str, object] | None,
    source_id: str,
) -> dict[str, object]:
    required_fields = [
        "address_space",
        "region_id",
        "offset_bytes",
        "size_bytes",
        "instance_base_addr_source",
    ]
    if source is None:
        return {
            "source_name": "stream_compiler_log10max_source_scratch_allocation",
            "file_path": (
                "compiler/gpdpu_compiler/core/stream_compiler/"
                "log10max_collective_strategy.py"
            ),
            "plan_path": "pe00_materialized_scalar_plan.scratch_address_candidate",
            "status": "not_applicable",
            "fields_found": [],
            "missing_fields": required_fields,
            "evidence": f"no compiler allocation candidate for {source_id}",
        }
    fields_found = [field for field in required_fields if source.get(field) is not None]
    missing_fields = [field for field in required_fields if source.get(field) is None]
    return {
        "source_name": "stream_compiler_log10max_source_scratch_allocation",
        "file_path": (
            "compiler/gpdpu_compiler/core/stream_compiler/"
            "log10max_collective_strategy.py"
        ),
        "plan_path": "pe00_materialized_scalar_plan.scratch_address_candidate",
        "status": source.get("status"),
        "fields_found": fields_found,
        "missing_fields": missing_fields,
        "record": dict(source),
        "evidence": (
            "report-only compiler allocated scratch offset for the PE00 "
            "materialized scalar; physical store/load lowering remains separate"
        ),
    }


def _app_plan_address_source_search(
    app_plan: dict[str, Any],
    source_id: str,
) -> dict[str, object]:
    matching_ops: list[dict[str, object]] = []
    for app_name, app in sorted(app_plan.get("apps", {}).items()):
        for op in app.get("ops", []):
            attrs = op.get("attrs", {})
            if attrs.get("storage_id") == source_id:
                matching_ops.append(
                    {
                        "app": app_name,
                        "op_id": op.get("id"),
                        "op": op.get("op"),
                        "fields": sorted(str(key) for key in attrs.keys()),
                    }
                )

    return {
        "source_name": "app_plan_materialize_ops",
        "file_path": "compiler/gpdpu_compiler/core/program_app.py",
        "plan_path": "app_plan.apps.*.ops[*].attrs",
        "status": "storage_reference_present_no_address_record",
        "fields_found": sorted(
            {
                field
                for op in matching_ops
                for field in op["fields"]
                if isinstance(field, str)
            }
        ),
        "missing_fields": [
            "address_space",
            "region_id",
            "offset_bytes",
            "instance_base_addr_source",
        ],
        "matching_ops": matching_ops,
        "evidence": (
            "app_plan inserts balanced app_materialize_store/load ops for the "
            "storage id, but their attrs stop at logical dtype/shape/layout"
        ),
    }


def _tile_app_storage_region_address_source_search(
    storage_region: dict[str, Any],
    source_id: str,
) -> dict[str, object]:
    fields_found = sorted(str(key) for key in storage_region.keys())
    missing_fields = [
        field
        for field in (
            "address_space",
            "region_id",
            "offset_bytes",
            "instance_base_addr_source",
        )
        if field not in storage_region
    ]
    status = (
        "candidate_address_record_present_but_unverified"
        if not missing_fields
        else "region_record_present_missing_address_fields"
    )
    return {
        "source_name": "processor_tile_program_app_storage_regions",
        "file_path": "compiler/gpdpu_compiler/core/program_tile.py",
        "plan_path": f"processor_tile_program.app_storage_regions[{source_id!r}]",
        "status": status,
        "fields_found": fields_found,
        "missing_fields": missing_fields,
        "record": dict(storage_region),
        "evidence": (
            "tile program has the app storage region record, but current "
            "program_tile collection does not assign a scratch address"
        ),
    }


def _tile_app_storage_address_record_search(
    tile_program: dict[str, Any],
    source_id: str,
) -> dict[str, object]:
    record = _app_storage_address_record_for_source(tile_program, source_id)
    required_fields = (
        "source_id",
        "source_id_kind",
        "logical_value_id",
        "address_space",
        "region_id",
        "offset_bytes",
        "size_bytes",
        "instance_base_addr_source",
    )
    if record is None:
        return {
            "source_name": "processor_tile_program_app_storage_address_records",
            "file_path": "compiler/gpdpu_compiler/core/program_tile.py",
            "plan_path": f"processor_tile_program.app_storage_address_records[{source_id!r}]",
            "status": "missing_app_storage_address_record",
            "fields_found": [],
            "missing_fields": list(required_fields),
            "record": None,
            "evidence": (
                "tile program did not emit a report-only app storage address "
                f"record for {source_id}"
            ),
        }

    fields_found = sorted(str(key) for key in record.keys())
    missing_fields = [
        field for field in required_fields if record.get(field) is None
    ]
    return {
        "source_name": "processor_tile_program_app_storage_address_records",
        "file_path": "compiler/gpdpu_compiler/core/program_tile.py",
        "plan_path": f"processor_tile_program.app_storage_address_records[{source_id!r}]",
        "status": str(record.get("status")),
        "fields_found": fields_found,
        "missing_fields": missing_fields,
        "record": dict(record),
        "evidence": (
            "tile lowering emitted a report-only app_storage_address_record "
            "candidate; missing concrete fields remain explicit and unverified"
        ),
    }


def _app_storage_address_record_for_source(
    tile_program: dict[str, Any],
    source_id: str,
) -> dict[str, Any] | None:
    records = tile_program.get("app_storage_address_records", {})
    record = records.get(source_id)
    if isinstance(record, dict):
        return record
    for candidate in records.values():
        if isinstance(candidate, dict) and candidate.get("source_id") == source_id:
            return candidate
    return None


def _tile_app_storage_edge_action_address_source_search(
    tile_program: dict[str, Any],
    source_id: str,
) -> dict[str, object]:
    matching_edges = [
        edge_id
        for edge_id, edge in sorted(tile_program.get("app_storage_edges", {}).items())
        if edge.get("storage_id") == source_id
    ]
    matching_actions = [
        {
            "action_id": action_id,
            "processor": action.get("processor"),
            "action_kind": action.get("action_kind"),
            "implementation_status": action.get("attrs", {}).get(
                "implementation_status"
            ),
        }
        for action_id, action in sorted(
            tile_program.get("tile_app_storage_actions", {}).items()
        )
        if action.get("storage_id") == source_id
    ]
    return {
        "source_name": "processor_tile_program_app_storage_edges_actions",
        "file_path": "compiler/gpdpu_compiler/core/program_tile.py",
        "plan_path": (
            "processor_tile_program.app_storage_edges + "
            "processor_tile_program.tile_app_storage_actions"
        ),
        "status": "symbolic_storage_boundary_no_address_record",
        "fields_found": [
            "app_storage_edge_id",
            "storage_id",
            "value_id",
            "processor",
            "action_kind",
            "implementation_status",
        ],
        "missing_fields": [
            "address_space",
            "region_id",
            "offset_bytes",
            "instance_base_addr_source",
        ],
        "matching_edges": matching_edges,
        "matching_action_count": len(matching_actions),
        "matching_actions": matching_actions,
        "evidence": (
            "tile app storage actions prove PE00 materialize plus per-PE load "
            "intent, but implementation_status remains symbolic"
        ),
    }


def _runtime_package_address_source_search(
    runtime_plan: dict[str, Any],
    source_id: str,
) -> dict[str, object]:
    matching_packages: list[dict[str, object]] = []
    for package_id, package in sorted(runtime_plan.get("packages", {}).items()):
        storage_inputs = list(package.get("storage_inputs", []))
        storage_outputs = list(package.get("storage_outputs", []))
        if source_id in storage_inputs or source_id in storage_outputs:
            matching_packages.append(
                {
                    "package_id": package_id,
                    "storage_inputs": storage_inputs,
                    "storage_outputs": storage_outputs,
                    "binary_emission_status": package.get("binary_emission_status"),
                }
            )

    return {
        "source_name": "runtime_package_assignment_storage_refs",
        "file_path": "compiler/gpdpu_compiler/core/program_runtime.py",
        "plan_path": "runtime_package_assignment.packages.*.storage_inputs_outputs",
        "status": "storage_reference_present_no_address_schema",
        "fields_found": [
            "storage_inputs",
            "storage_outputs",
            "binary_emission_status",
        ],
        "missing_fields": [
            "address_space",
            "region_id",
            "offset_bytes",
            "instance_base_addr_source",
        ],
        "matching_packages": matching_packages,
        "evidence": (
            "runtime package assignment carries storage refs across package "
            "boundaries but does not materialize SRAM/SPM address records"
        ),
    }


def _scratch_address_requirement_evidence(
    candidate: Pe00ScalarScratchAddressCandidate,
) -> str:
    if (
        candidate.candidate_status
        == "compiler_allocated_address_candidate_available"
    ):
        return (
            "compiler allocated PE00 scratch address candidate for "
            f"{candidate.source_id}: address_space={candidate.address_space}, "
            f"offset={candidate.offset_bytes}, "
            f"instance_base_addr_source={candidate.instance_base_addr_source}; "
            "physical store/load validation remains open"
        )
    if candidate.address_record_present:
        return (
            "candidate address record is present for "
            f"{candidate.source_id}, but runtime base_addr and physical "
            "store/load validation have not closed"
        )
    return (
        "source scratch contract exists, but app storage region has no complete "
        "address source: address_space="
        f"{candidate.address_space_status}, offset={candidate.offset_status}, "
        f"instance_base_addr_source={candidate.instance_base_addr_source}"
    )


def _evaluate_pe00_aggregate_materialize(
    evidence: _PlanEvidence,
    pe00_plan: Pe00MaterializedScalarPlan,
) -> StrategyEvaluation:
    return StrategyEvaluation(
        strategy=Log10MaxCollectiveStrategy.PE00_AGGREGATE_MATERIALIZE,
        customer_label=Log10MaxCustomerLabel.PE00_MATERIALIZED_SCALAR,
        status="ready" if pe00_plan.closed else "blocked",
        blockers=pe00_plan.open_requirement_ids,
        evidence=(
            "current tile IR creates one PE00 reduce_store app storage action",
            "current tile IR creates per-PE broadcast_load app storage actions",
            "softmax_1 supports staged write/read workflow shape through subtask "
            "order and SPM/SUM storage",
            "runtime/control shows order must be proven by task/subtask "
            "successors, instance base_addr, kernel start and wait",
            "common_oper COPY/COPYT evidence requires receiver-owned destination "
            "block/PE/operand binding",
            "this is staged materialized collective shape, not direct physical allreduce",
        ),
    )


def _pe00_delivery_minimum_code_owners() -> list[dict[str, object]]:
    return [
        {
            "owner": "source_scratch_allocation",
            "pass_or_file": "compiler/gpdpu_compiler/core/program_tile.py",
            "closes": ["scratch_address_materialization"],
            "minimum_action": (
                "assign offset_bytes/base_addr for the AppStorageRegion source id"
            ),
        },
        {
            "owner": "tile_store_load_lowering",
            "pass_or_file": (
                "compiler/gpdpu_compiler/core/stream_compiler/"
                "log10max_template_pack.py"
            ),
            "closes": [
                "producer_pe00_physical_store",
                "consumer_physical_readback",
            ],
            "minimum_action": (
                "lower reduce_store/broadcast_load into concrete PE00 store and "
                "per-PE scratch readback templates"
            ),
        },
        {
            "owner": "runtime_subtask_order",
            "pass_or_file": "compiler/gpdpu_compiler/core/program_runtime.py",
            "closes": ["runtime_subtask_order"],
            "minimum_action": (
                "emit the write-before-readback package/subtask launch contract"
            ),
        },
        {
            "owner": "receiver_binding",
            "pass_or_file": "compiler/gpdpu_compiler/core/stream_compiler/binding.py",
            "closes": ["receiver_binding"],
            "minimum_action": (
                "bind every consumer PE load to receiver-owned destination operands"
            ),
        },
        {
            "owner": "pe00_fmax_chain",
            "pass_or_file": (
                "compiler/gpdpu_compiler/core/stream_compiler/"
                "log10max_template_pack.py"
            ),
            "closes": ["pe00_fmax_combine_order"],
            "minimum_action": (
                "make the PE00 ordered FMAX combine chain explicit before store"
            ),
        },
    ]


def _evaluate_redundant_spmd_recompute(
    evidence: _PlanEvidence,
    *,
    allow_internal_redundant_recompute: bool,
) -> StrategyEvaluation:
    blockers: list[str] = []
    if not allow_internal_redundant_recompute:
        blockers.append("redundant_spmd_internal_only_waiver_required")
    if (
        evidence.logical_reduce["attrs"].get("implementation_status")
        == "symbolic_collective_not_physical_route"
    ):
        blockers.append("current_ir_still_contains_symbolic_collective")
    if evidence.runtime_launch["semantic_app_count"] != 1:
        blockers.append("current_plan_is_two_semantic_apps_not_same_app_recompute")

    status = "internal_waiver_available" if allow_internal_redundant_recompute else "blocked"
    return StrategyEvaluation(
        strategy=Log10MaxCollectiveStrategy.REDUNDANT_SPMD_RECOMPUTE,
        customer_label=Log10MaxCustomerLabel.INTERNAL_REDUNDANT_RECOMPUTE,
        status=status,
        blockers=tuple(dict.fromkeys(blockers)),
        evidence=(
            "notes/log10max recommends redundant SPMD as first runnable path",
            "strategy avoids claiming physical PE collective route evidence",
            "capacity model makes full-domain reread cost explicit",
        ),
    )


def _evaluation_for_strategy(
    evaluations: tuple[StrategyEvaluation, ...],
    strategy: Log10MaxCollectiveStrategy,
) -> StrategyEvaluation:
    for evaluation in evaluations:
        if evaluation.strategy == strategy:
            return evaluation
    raise ValueError(f"missing strategy evaluation for {strategy.value}")


def _select_delivery_strategy(
    evaluations: tuple[StrategyEvaluation, ...],
) -> StrategyEvaluation | None:
    return _evaluation_for_strategy(evaluations, LOG10MAX_RING_FIRST_STRATEGY)


def _select_internal_waiver_strategy(
    evaluations: tuple[StrategyEvaluation, ...],
) -> StrategyEvaluation | None:
    redundant = _evaluation_for_strategy(
        evaluations,
        Log10MaxCollectiveStrategy.REDUNDANT_SPMD_RECOMPUTE,
    )
    if redundant.status == "internal_waiver_available":
        return redundant
    return None


def _delivery_status(
    recommended_delivery: StrategyEvaluation,
    selected_delivery: StrategyEvaluation | None,
) -> str:
    if selected_delivery is not None:
        if selected_delivery.blockers:
            return "delivery_selected_blocked_on_route_binding"
        return "delivery_selected"
    if recommended_delivery.strategy == Log10MaxCollectiveStrategy.PE00_AGGREGATE_MATERIALIZE:
        return "blocked_on_pe00_evidence"
    return "blocked_no_customer_strategy_ready"


def _selected_blockers(
    selected_strategy: Log10MaxCollectiveStrategy | None,
    evaluations: tuple[StrategyEvaluation, ...],
) -> list[str]:
    if selected_strategy is None:
        return []
    for evaluation in evaluations:
        if evaluation.strategy == selected_strategy:
            return list(evaluation.blockers)
    return []


def _single_sram_tensor_with_role(
    chip_program: dict[str, Any],
    role: str,
) -> dict[str, Any]:
    matches = [
        tensor
        for tensor in chip_program["sram_tensors"].values()
        if tensor.get("role") == role
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one SRAM tensor with role={role}, found {len(matches)}")
    return matches[0]


def _single_logical_reduce(logical_plan: dict[str, Any]) -> dict[str, Any]:
    reduces = list(logical_plan["logical_reduces"].values())
    if len(reduces) != 1:
        raise ValueError(f"expected one logical reduce, found {len(reduces)}")
    return reduces[0]


def _single_collective_bundle(tile_program: dict[str, Any]) -> dict[str, Any]:
    bundles = list(tile_program["collective_bundles"].values())
    if len(bundles) != 1:
        raise ValueError(f"expected one collective bundle, found {len(bundles)}")
    return bundles[0]


def _single_app_storage_region(tile_program: dict[str, Any]) -> dict[str, Any]:
    regions = list(tile_program["app_storage_regions"].values())
    if len(regions) != 1:
        raise ValueError(f"expected one app storage region, found {len(regions)}")
    return regions[0]


def _local_value_for_tensor(
    logical_plan: dict[str, Any],
    *,
    tensor_id: str,
    processor: str,
) -> dict[str, Any]:
    for value in logical_plan["local_values"].values():
        if (
            (
                value["logical_tensor_id"] == tensor_id
                or value.get("source_sram_tensor_id") == tensor_id
            )
            and value["processor"] == processor
        ):
            return value
    raise ValueError(f"missing local value for tensor={tensor_id} processor={processor}")


def _tensor_report(tensor: dict[str, Any]) -> dict[str, object]:
    return {
        "id": tensor["id"],
        "name": tensor["name"],
        "shape": list(tensor["shape"]),
        "dtype": tensor["dtype"],
        "nbytes": tensor["nbytes"],
        "address_space": tensor.get("address_space"),
        "offset_bytes": tensor.get("offset_bytes"),
        "end_offset_bytes": tensor.get("region", {}).get("end_offset_bytes"),
        "role": tensor.get("role"),
    }


def _runtime_launch_report(runtime_plan: dict[str, Any]) -> dict[str, object]:
    validation = runtime_plan["validation"]
    totals = runtime_plan["totals"]
    return {
        "semantic_app_count": totals["semantic_app_count"],
        "package_count": totals["package_count"],
        "required_launch_count": totals["package_count"],
        "runtime_launch_supported": validation["runtime_launch_supported"],
        "complete_program_runnable": validation["complete_program_runnable"],
        "blocking_reasons": list(validation["blocking_reasons"]),
    }


def _storage_region_nbytes(region: dict[str, Any]) -> int:
    return _nbytes_for_shape_dtype(region.get("shape", ()), str(region.get("dtype")))


def _nbytes_for_shape_dtype(shape: object, dtype: str) -> int:
    dims = list(shape) if isinstance(shape, (list, tuple)) else []
    element_count = reduce(mul, dims, 1) if dims else 1
    return element_count * _dtype_nbytes(dtype)


def _dtype_nbytes(dtype: str) -> int:
    sizes = {
        "fp16": 2,
        "float16": 2,
        "bf16": 2,
        "fp32": 4,
        "float32": 4,
        "int32": 4,
    }
    if dtype not in sizes:
        raise ValueError(f"unknown dtype byte width for {dtype!r}")
    return sizes[dtype]


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _app_storage_actions(
    tile_program: dict[str, Any],
    *,
    action_kind: str,
) -> list[dict[str, Any]]:
    return [
        action
        for action in tile_program["tile_app_storage_actions"].values()
        if action["action_kind"] == action_kind
    ]


def _app_storage_action_count(
    tile_program: dict[str, Any],
    *,
    action_kind: str,
) -> int:
    return len(_app_storage_actions(tile_program, action_kind=action_kind))


def _pe00_owner(tile_program: dict[str, Any]) -> str | None:
    actions = _app_storage_actions(tile_program, action_kind="reduce_store")
    if not actions:
        return None
    return str(actions[0]["processor"])


def _has_physical_pe00_combine_action(tile_program: dict[str, Any]) -> bool:
    for action in tile_program["tile_compute_actions"].values():
        if action["processor"] != "processor_0_0":
            continue
        if action["compute_kind"] in {
            "pe00_collective_combine_max",
            "collective_combine_max",
        }:
            return True
    return False


def _has_materialize_then_load_dependency(tile_program: dict[str, Any]) -> bool:
    return any(
        dependency["dependency_kind"] == "materialized_storage_before_app_load"
        and dependency["dependency_value_kind"] == "materialized_storage"
        for dependency in tile_program["tile_dependencies"].values()
    )


def _memory_visibility(evidence: _PlanEvidence) -> tuple[str, ...]:
    return (
        "LogicalReduceEdge visibility_kind=replicated_scalar is semantic only.",
        "TileCollectiveBundle remains all_reduce_max_symbolic; no physical route proof.",
        "PE00 app storage materialize/load is visible in tile IR but symbolic.",
        "Cross-app scalar visibility is represented through materialized storage dependencies.",
        "Redundant SPMD recompute would avoid PE communication by rereading stable SRAM input.",
    )


def _diagnostics(full_plan: dict[str, Any]) -> tuple[str, ...]:
    diagnostics: list[str] = []
    if full_plan.get("status") != "program_bin_package_structural_smoke_ready_functional_blocked":
        diagnostics.append(f"unexpected full_plan status: {full_plan.get('status')}")
    runtime_validation = full_plan["runtime_package_assignment"]["validation"]
    if runtime_validation["blocking_reasons"]:
        diagnostics.extend(
            f"runtime_blocker:{reason}"
            for reason in runtime_validation["blocking_reasons"]
        )
    return tuple(diagnostics)
