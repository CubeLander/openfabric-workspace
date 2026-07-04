"""App partition planning for DFU-first lowering.

This layer cuts a flat chip-level program into flat app-local op lists.  It does
not own fusion, task partitioning, route planning, runtime image packing, or
binary storage side tables.  If an app boundary needs data handoff, the handoff
is represented by compiler-inserted ChipOp records in the same op plane as the
user's program.

See ``docs/compiler/binary_packaging/research_notes/archive/app-plan-vs-runtime-image.md`` for
the app/image boundary policy this code is intentionally enforcing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gpdpu_compiler.core.program import ChipOp, ChipProgram


@dataclass(frozen=True)
class AppPlanValidation:
    """Verifier-friendly app partition legality report."""

    every_app_has_ops: bool
    app_materialization_ops_are_balanced: bool
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return (
            self.every_app_has_ops
            and self.app_materialization_ops_are_balanced
            and not self.errors
        )

    def to_plan(self) -> dict[str, Any]:
        return {
            "every_app_has_ops": self.every_app_has_ops,
            "app_materialization_ops_are_balanced": (
                self.app_materialization_ops_are_balanced
            ),
            "ok": self.ok,
            "errors": list(self.errors),
        }


class AppPlan:
    """Flat app op-list partition for one chip program."""

    source_program: str
    source_chip_program: ChipProgram
    apps: tuple[tuple[ChipOp, ...], ...]
    app_input_storage_refs: tuple[tuple[str, ...], ...]
    app_output_storage_refs: tuple[tuple[str, ...], ...]
    attrs: dict[str, Any]

    def __init__(self, program: ChipProgram) -> None:
        self.source_program = program.name
        self.source_chip_program = program

        producer_by_tensor: dict[str, ChipOp] = {}
        for op in program.ops:
            for output_id in op.outputs:
                producer_by_tensor[output_id] = op

        # AppPlan is intentionally boring: first cut the flat op stream into app
        # segments, then insert any required boundary ops directly into those
        # segments.  There is no side-table edge language here.  A later pass that
        # needs fusion, task, collective, or tile semantics must read these flat
        # app-local op lists and derive its own IR.
        #
        # A DFU task row is an app-local parallel work slot; it does not provide a
        # general "all tasks finish, cooperate, then continue" semantic barrier.
        # Therefore the naive app splitter closes the current app when it sees a
        # collective op.  Cross-app data must be explicit program actions.  SRAM
        # inputs can be loaded again.  Collective scalar outputs are materialized
        # by compiler-inserted app_materialize_store/load ops.  PE-local tile
        # intermediates do not cross the boundary: the current policy is to
        # recompute tile-local lineage in the later app.  A future cost policy may
        # instead insert explicit SRAM stores/loads for selected tile values.
        cross_app_tile_value_policy = "recompute_tile_local_lineage"
        control_ops = {"declare_sram_tensor"}
        input_storage_refs = tuple(
            tensor_id
            for tensor_id, tensor in sorted(program.sram_tensors.items())
            if tensor.role == "input"
        )
        output_storage_refs = tuple(
            tensor_id
            for tensor_id, tensor in sorted(program.sram_tensors.items())
            if tensor.role == "output"
        )

        executable_ops = [op for op in program.ops if op.op not in control_ops]
        app_segments: list[list[ChipOp]] = [[]]
        for op in executable_ops:
            app_segments[-1].append(op)
            if op.op.startswith("reduce_"):
                app_segments.append([])
        app_segments = [segment for segment in app_segments if segment]
        if not app_segments:
            app_segments = [[]]

        synthetic_index = 0
        if len(app_segments) > 1:
            collective_op = next(
                (
                    op
                    for op in app_segments[0]
                    if op.op.startswith("reduce_") and op.outputs
                ),
                None,
            )
            if collective_op is not None:
                collective_output = collective_op.outputs[0]
                reduce_kind = collective_op.op.removeprefix("reduce_")
                storage_label = (
                    f"global_{reduce_kind}" if reduce_kind else "collective_result"
                )
                storage_id = f"app_storage:{storage_label}:{collective_output}"
                storage_shape = tuple(program.dtensors[collective_output].shape)
                storage_dtype = program.dtensors[collective_output].dtype

                store_op = ChipOp(
                    id=f"app_op_{synthetic_index:04d}",
                    op="app_materialize_store",
                    inputs=(collective_output,),
                    outputs=(storage_id,),
                    attrs={
                        "value_id": collective_output,
                        "storage_id": storage_id,
                        "producer_op": "reduce_store",
                        "materialization_kind": "scalar",
                        "dtype": storage_dtype,
                        "shape": list(storage_shape),
                        "layout": "replicated_scalar",
                        "source_collective_op": collective_op.id,
                        "app_boundary_role": "producer",
                    },
                )
                synthetic_index += 1
                load_op = ChipOp(
                    id=f"app_op_{synthetic_index:04d}",
                    op="app_materialize_load",
                    inputs=(storage_id,),
                    outputs=(collective_output,),
                    attrs={
                        "value_id": collective_output,
                        "storage_id": storage_id,
                        "consumer_op": "broadcast_load",
                        "materialization_kind": "scalar",
                        "dtype": storage_dtype,
                        "shape": list(storage_shape),
                        "layout": "replicated_scalar",
                        "source_collective_op": collective_op.id,
                        "app_boundary_role": "consumer",
                    },
                )

                recompute_ops = [
                    op for op in app_segments[0] if op.id != collective_op.id
                ]
                app_segments[0].append(store_op)
                app_segments[1] = [*recompute_ops, load_op, *app_segments[1]]

        self.apps = tuple(tuple(segment) for segment in app_segments)
        self.app_input_storage_refs = tuple(
            (
                (*input_storage_refs,)
                if app_index == 0
                else (
                    *input_storage_refs,
                    *tuple(
                        op.attrs["storage_id"]
                        for prior_segment in app_segments[:app_index]
                        for op in prior_segment
                        if op.op == "app_materialize_store"
                    ),
                )
            )
            for app_index in range(len(app_segments))
        )
        self.app_output_storage_refs = tuple(
            (
                tuple(
                    op.attrs["storage_id"]
                    for op in segment
                    if op.op == "app_materialize_store"
                )
                or (output_storage_refs if app_index == len(app_segments) - 1 else ())
            )
            for app_index, segment in enumerate(app_segments)
        )
        self.attrs = {
            "implementation_stage": "ir_only_no_binary_behavior_change",
            "app_partition_algorithm": (
                "append_ops_until_collective_then_insert_flat_materialize_ops"
            ),
            "cross_app_tile_value_policy": cross_app_tile_value_policy,
        }

    @property
    def app_count(self) -> int:
        return len(self.apps)

    def validate(self) -> AppPlanValidation:
        errors: list[str] = []
        every_app_has_ops = all(bool(app_ops) for app_ops in self.apps)
        if not every_app_has_ops:
            errors.append("every app must contain at least one op")

        stores = {
            op.attrs.get("storage_id")
            for app_ops in self.apps
            for op in app_ops
            if op.op == "app_materialize_store"
        }
        loads = {
            op.attrs.get("storage_id")
            for app_ops in self.apps
            for op in app_ops
            if op.op == "app_materialize_load"
        }
        app_materialization_ops_are_balanced = stores == loads
        if not app_materialization_ops_are_balanced:
            errors.append("app materialize store/load ops must reference same storage ids")

        return AppPlanValidation(
            every_app_has_ops=every_app_has_ops,
            app_materialization_ops_are_balanced=app_materialization_ops_are_balanced,
            errors=tuple(errors),
        )

    def to_plan(self) -> dict[str, Any]:
        validation = self.validate()
        return {
            "schema_version": 2,
            "ir": "app_plan",
            "source_program": self.source_program,
            "layering_policy": (
                "app_plan_only_partitions_flat_ops_and_inserts_explicit_"
                "boundary_ops;downstream_passes_derive_fusion_task_tile_ir"
            ),
            "apps": {
                f"app{app_index}": {
                    "app_id": app_index,
                    "app_name": f"app{app_index}",
                    "op_ids": [op.id for op in app_ops],
                    "ops": [op.to_plan() for op in app_ops],
                    "input_storage_refs": list(
                        self.app_input_storage_refs[app_index]
                    ),
                    "output_storage_refs": list(
                        self.app_output_storage_refs[app_index]
                    ),
                }
                for app_index, app_ops in enumerate(self.apps)
            },
            "validation": validation.to_plan(),
            "totals": {
                "app_count": len(self.apps),
                "app_op_count": sum(len(app_ops) for app_ops in self.apps),
                "inserted_app_op_count": sum(
                    1
                    for app_ops in self.apps
                    for op in app_ops
                    if op.op.startswith("app_materialize_")
                ),
            },
            "attrs": dict(self.attrs),
        }


__all__ = [
    "AppPlan",
    "AppPlanValidation",
]
