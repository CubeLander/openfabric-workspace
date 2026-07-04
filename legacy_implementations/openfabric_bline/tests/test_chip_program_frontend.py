from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "compiler"))

from gpdpu_compiler.core import (
    AppPlan,
    ChipEnv,
    DFU3500_GEMM_REGIONS,
    DFU3500_SIMICT_LEGACY_RUNTIME_PROFILE,
    LogicalPlan,
    TaskPartitionPlan,
    assign_app_plan_to_runtime_packages,
)
from gpdpu_compiler.core.op_specs import MATMUL_SPEC
from gpdpu_compiler.core.ops import (
    add,
    add_scalar,
    clamp_min,
    log10,
    maximum,
    mul_scalar,
    reduce_max,
    relu,
)
from gpdpu_compiler.core.program_legacy_inst import (
    OPERANDS_PER_OPERAND_RAM,
    legacy_gemm_micro_block_template,
    pack_legacy_inst,
    parse_legacy_csv_template,
)
from gpdpu_compiler.core.program_bin import lower_vendor_abi_to_program_bin_rows
from gpdpu_compiler.core.program_bin_diff import compare_simulator_bundles
from gpdpu_compiler.core.program_serializer import lower_program_bin_rows_to_components
from gpdpu_compiler.core.program_tile import lower_processor_logical_to_tile_program
from gpdpu_compiler.core.dfu3500.task_resource_replay import (
    Dfu3500TaskResourceState,
    TASK_RESOURCE_REPLAY_ENV,
    layout_operand_idx,
    replay_legacy_task_resource,
)
from gpdpu_compiler.core.program_vendor_abi import ProgramVendorABI
from gpdpu_compiler.core.dfu3500.operand_visibility import (
    dfu3500_operand_visibility_policy_for,
    dfu3500_summa_operand_visibility_policy,
)
from gpdpu_compiler.placements import (
    Replicate,
    Shard,
    TaskPartial,
    TaskReplicate,
    TaskShard,
)


def test_matmul_spec_frontend_contract_matches_current_dfu_path() -> None:
    semantic_contract = MATMUL_SPEC.semantic_contract()
    lowering_contract = MATMUL_SPEC.dfu3500_lowering_contract()
    parallel_profile = MATMUL_SPEC.parallel_profile()
    tile_profile = MATMUL_SPEC.tile_lowering_profile()

    assert semantic_contract.shape_rule == "rank2_mk_kn_to_mn"
    assert semantic_contract.dtype_policy == "lhs_rhs_same_dtype"
    assert lowering_contract.lowering_kind == "summa_gemm"
    assert lowering_contract.target == "dfu3500"
    assert lowering_contract.target_profile_id == "dfu3500_simict_legacy_gemm"
    assert lowering_contract.supported_lhs_placements == (Shard(0), Replicate())
    assert lowering_contract.supported_rhs_placements == (Replicate(), Shard(1))
    assert lowering_contract.supported_output_placements == (Shard(0), Shard(1))
    assert lowering_contract.attrs() == {
        "lowering_hint": "dfu_summa_gemm",
        "execution_model": "spmd",
    }

    assert parallel_profile.primary_schedule_kind == "gemm_output_tiles"
    assert parallel_profile.requires_global_merge is False
    assert parallel_profile.result_visibility == "independent_output_tiles"
    assert parallel_profile.task_decomposition.partition_kind == "gemm_output_tiles"
    assert parallel_profile.task_decomposition.max_task_rows == 4
    assert parallel_profile.task_decomposition.required_subtask_roles == (
        "accumulator_prepare",
        "k_stream",
        "finalize_store",
    )
    assert parallel_profile.fusion.allowed_post_op_kinds == ("relu",)
    assert parallel_profile.fusion.dependency_requirement == (
        "tile_local_primary_output_only"
    )
    assert parallel_profile.fusion.forbids_cross_pe_collective is True
    assert parallel_profile.fusion.forbids_app_storage_load is True
    assert parallel_profile.fusion.output_store_position == "after_epilogue"
    assert [
        requirement.__dict__
        for requirement in parallel_profile.state_lifetimes
    ] == [
        {
            "value_role": "primary_outputs",
            "state_kind": "APP_LOCAL_EXPLICIT",
            "required_scope": "same_app",
            "proof": "gemm_accumulator_lives_inside_task_subtask_instance_profile",
        }
    ]
    assert {
        **{
            key: value
            for key, value in tile_profile.__dict__.items()
            if key != "compute_micro_blocks"
        },
        "compute_micro_blocks": [
            entry.__dict__ for entry in tile_profile.compute_micro_blocks
        ],
    } == {
        "phase_kind": "local_gemm_summa",
        "template_kind": "summa_gemm_64x64x64_fp16",
        "source_compute_kind": "matmul",
        "accumulator_prepare_kind": "accumulator_prepare",
        "k_update_kind": "gemm_k_update",
        "local_prepare_op": "init_c",
        "local_k_stream_op": "stream_k_gemm",
        "local_store_op": "store_c",
        "loop_axis": "K",
        "loop_fold_policy": "vendor_instance_repeat_candidate",
        "loop_closure_shape": "closed_repeated_tile_body",
        "compute_micro_blocks": [
            {
                "compute_kind": "accumulator_prepare",
                "micro_block_kind": "accumulator_prepare",
            },
            {
                "compute_kind": "gemm_k_update",
                "micro_block_kind": "compute_update",
            },
        ],
    }


def test_dfu3500_summa_operand_visibility_policy_matches_current_processor_path() -> None:
    route_policy = dfu3500_summa_operand_visibility_policy()

    assert [route.__dict__ for route in route_policy.operand_routes] == [
        {
            "operand_index": 0,
            "operand_role": "A",
            "route_kind": "row_broadcast",
            "visibility_kind": "row_visibility",
            "fabric_scope": "row",
            "group_dim": 0,
            "axis_name": "row",
        },
        {
            "operand_index": 1,
            "operand_role": "B",
            "route_kind": "column_broadcast",
            "visibility_kind": "column_visibility",
            "fabric_scope": "column",
            "group_dim": 1,
            "axis_name": "col",
        },
    ]
    assert (
        dfu3500_operand_visibility_policy_for(
            lowering_hint="dfu_summa_gemm",
            operand_count=2,
        )
        == route_policy
    )
    assert (
        dfu3500_operand_visibility_policy_for(
            lowering_hint=None,
            operand_count=2,
        )
        is None
    )


def test_chip_env_records_manual_task_axis_partition_metadata() -> None:
    env = ChipEnv("manual_task_axis")
    env.configure_task_axis(task_axis_size=4, physical_mesh_shape=(4, 4))

    a_sram = env.sram_tensor_from_region("A", DFU3500_GEMM_REGIONS["A"])
    b_sram = env.sram_tensor_from_region("B", DFU3500_GEMM_REGIONS["B"])

    a = env.load(
        a_sram,
        placements=[TaskReplicate(), Shard(0), Replicate()],
    )
    b = env.load(
        b_sram,
        placements=[TaskReplicate(), Replicate(), Shard(1)],
    )
    y = a @ b

    env.set_task_placement(
        y,
        TaskShard("gemm_output_tiles", work_axis_order=("m_tile", "n_tile")),
    )

    chip_plan = env.to_chip_plan()
    assert chip_plan["task_axis_mesh"]["task_axis_size"] == 4
    assert chip_plan["task_axis_mesh"]["physical_mesh_shape"] == [4, 4]
    assert chip_plan["task_axis_placements"][y.id]["kind"] == "task_shard"

    task_plan = TaskPartitionPlan(AppPlan(env.program), env.chip).to_plan()
    assert task_plan["task_axis_mesh"]["soft_mesh_shape"] == [4, 4, 4]
    assert task_plan["validation"]["ok"] is True
    assert task_plan["apps"]["app0"]["value_scope"] == (
        "PELocal(app_id, task_id, physical_pe_id)"
    )

    app_plan = AppPlan(env.program)
    task_partition_plan = TaskPartitionPlan(app_plan, env.chip)
    processor_plan = LogicalPlan(
        app_plan,
        env.chip,
        task_partition_plan=task_partition_plan,
    ).to_plan()
    assert processor_plan["soft_processor_mesh"]["task_axis_size"] == 4
    assert len(processor_plan["apps"]["app0"]["soft_processors"]) == 64
    assert processor_plan["apps"]["app0"]["soft_processors"][
        "task3:processor_3_3"
    ]["value_scope"] == "PELocal(app_id, task_id, physical_pe_id)"


def test_chip_env_rejects_task_axis_physical_mesh_mismatch() -> None:
    env = ChipEnv("bad_task_axis")

    try:
        env.configure_task_axis(task_axis_size=4, physical_mesh_shape=(2, 8))
    except ValueError as exc:
        assert "physical_mesh_shape must match chip logical fabric" in str(exc)
    else:
        raise AssertionError("task-axis physical mesh mismatch must be rejected")


def test_chip_env_rejects_task_axis_partial_and_nonleading_task_descriptor() -> None:
    env = ChipEnv("bad_task_placement")
    env.configure_task_axis(task_axis_size=4, physical_mesh_shape=(4, 4))
    a_sram = env.sram_tensor_from_region("A", DFU3500_GEMM_REGIONS["A"])

    try:
        env.load(
            a_sram,
            placements=[TaskPartial("sum", "all_tasks"), Shard(0), Replicate()],
        )
    except ValueError as exc:
        assert "TaskPartial is not allowed in placement axis 0 yet" in str(exc)
    else:
        raise AssertionError("TaskPartial on task axis must be rejected")

    try:
        env.load(
            a_sram,
            placements=[Shard(0), TaskReplicate(), Replicate()],
        )
    except TypeError as exc:
        assert "only placement axis 0 may use TaskAxisPlacement" in str(exc)
    else:
        raise AssertionError("task descriptor outside axis 0 must be rejected")


def test_op_specs_do_not_import_downstream_ir_modules() -> None:
    op_specs_root = ROOT / "compiler/gpdpu_compiler/core/op_specs"
    forbidden = (
        "gpdpu_compiler.core.program_app",
        "gpdpu_compiler.core.logical_plan",
        "gpdpu_compiler.core.program_tile",
        "gpdpu_compiler.core.program_nodes",
        "gpdpu_compiler.core.program_packing",
        "gpdpu_compiler.core.program_asm",
        "gpdpu_compiler.core.program_vendor_abi",
        "gpdpu_compiler.core.program_bin",
        "gpdpu_compiler.core.program_serializer",
        "gpdpu_compiler.core.dfu3500.legacy_templates",
    )
    for path in sorted(op_specs_root.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert not any(module in text for module in forbidden), path


def test_dfu3500_runtime_profile_and_single_app_assignment() -> None:
    assert DFU3500_SIMICT_LEGACY_RUNTIME_PROFILE.to_plan() == {
        "profile_id": "dfu3500_simict_legacy_single_package",
        "max_runtime_apps_per_package": 1,
        "max_task_rows_per_package": 4,
        "max_subtask_rows_per_task": 8,
        "max_subtask_rows_per_package": 32,
        "max_instances_per_subtask": 2048,
        "supports_single_package_multi_semantic_app": False,
        "supports_multi_package_launch": False,
        "supports_inter_package_storage_handoff": False,
        "package_policy": "single_runtime_app_image",
    }

    app_plan = AppPlan(ChipEnv("single_app_smoke").program)
    assignment = assign_app_plan_to_runtime_packages(
        app_plan,
        DFU3500_SIMICT_LEGACY_RUNTIME_PROFILE,
    ).to_plan()
    assert assignment["totals"] == {
        "semantic_app_count": 1,
        "package_count": 1,
    }
    assert assignment["packages"]["package0"]["semantic_app_ids"] == [0]
    assert assignment["validation"]["complete_program_runnable"] is True


def test_tile_task_report_wraps_output_waves_without_task4() -> None:
    env = ChipEnv("tile_task_report")
    env.configure_task_axis(task_axis_size=4, physical_mesh_shape=(4, 4))
    a_sram = env.sram_tensor_from_region("A", DFU3500_GEMM_REGIONS["A"])
    b_sram = env.sram_tensor_from_region("B", DFU3500_GEMM_REGIONS["B"])
    y_sram = env.sram_tensor_from_region("Y", DFU3500_GEMM_REGIONS["C"])

    a = env.load(a_sram, placements=[TaskReplicate(), Shard(0), Replicate()])
    b = env.load(b_sram, placements=[TaskReplicate(), Replicate(), Shard(1)])
    y = env.set_task_placement(
        a @ b,
        TaskShard("gemm_output_tiles", work_axis_order=("m_tile", "n_tile")),
    )
    env.store(y, y_sram)

    app_plan = AppPlan(env.program)
    task_partition_plan = TaskPartitionPlan(app_plan, env.chip)
    processor_program = LogicalPlan(
        app_plan,
        env.chip,
        task_partition_plan=task_partition_plan,
    )
    tile_program = lower_processor_logical_to_tile_program(
        processor_program,
        env.chip,
        app_plan=app_plan,
    ).to_plan()
    processor_task_plan = tile_program["vendor_task_projection"]["processor_task_plan"]
    assert tile_program["totals"]["processor_count"] == 64
    assert {
        tuple(phase["phase_kind"] for phase in program["phases"])
        for program in tile_program["programs"].values()
    } == {("local_gemm_summa", "store_sram_tensor")}
    assert processor_task_plan["ir"] == "vendor_task_projection_report"
    assert processor_task_plan["source_of_truth"] == "restricted_soft_task_axis"
    assert "task4" not in {
        assignment["task_name"]
        for assignment in processor_task_plan["assignments"].values()
    }
    assert {
        assignment["assignment_source"]
        for assignment in processor_task_plan["assignments"].values()
    } == {"task_axis_shard"}
    assert {
        assignment["launch_group_id"]
        for assignment in processor_task_plan["assignments"].values()
    } == {0}
    assert {
        assignment["task_axis_work_domain"]
        for assignment in processor_task_plan["assignments"].values()
    } == {"gemm_output_tiles"}
    assert processor_task_plan["validation"] == {
        "all_task_ids_within_vendor_limit": True,
        "single_launch_group_supported": True,
    }


def test_tile_task_report_rejects_task_shard_partition_count_mismatch() -> None:
    env = ChipEnv("tile_task_partition_count")
    env.configure_task_axis(task_axis_size=4, physical_mesh_shape=(4, 4))
    a_sram = env.sram_tensor_from_region("A", DFU3500_GEMM_REGIONS["A"])
    b_sram = env.sram_tensor_from_region("B", DFU3500_GEMM_REGIONS["B"])
    y_sram = env.sram_tensor_from_region("Y", DFU3500_GEMM_REGIONS["C"])

    a = env.load(a_sram, placements=[TaskReplicate(), Shard(0), Replicate()])
    b = env.load(b_sram, placements=[TaskReplicate(), Replicate(), Shard(1)])
    y = env.set_task_placement(
        a @ b,
        TaskShard(
            "gemm_output_tiles",
            partition_count=2,
            work_axis_order=("m_tile", "n_tile"),
        ),
    )
    env.store(y, y_sram)

    app_plan = AppPlan(env.program)
    task_partition_plan = TaskPartitionPlan(app_plan, env.chip)
    processor_program = LogicalPlan(
        app_plan,
        env.chip,
        task_partition_plan=task_partition_plan,
    )
    try:
        lower_processor_logical_to_tile_program(
            processor_program,
            env.chip,
            app_plan=app_plan,
        )
    except ValueError as exc:
        assert "one output-tile work unit per task-axis rank" in str(exc)
    else:
        raise AssertionError("GEMM task-axis partition/work mismatch must fail")


def test_tile_task_report_consumes_task_shard_work_axis_order() -> None:
    env = ChipEnv("tile_task_work_axis_order")
    env.configure_task_axis(task_axis_size=4, physical_mesh_shape=(4, 4))
    a_sram = env.sram_tensor_from_region("A", DFU3500_GEMM_REGIONS["A"])
    b_sram = env.sram_tensor_from_region("B", DFU3500_GEMM_REGIONS["B"])
    y_sram = env.sram_tensor_from_region("Y", DFU3500_GEMM_REGIONS["C"])

    a = env.load(a_sram, placements=[TaskReplicate(), Shard(0), Replicate()])
    b = env.load(b_sram, placements=[TaskReplicate(), Replicate(), Shard(1)])
    y = env.set_task_placement(
        a @ b,
        TaskShard("gemm_output_tiles", work_axis_order=("n_tile", "m_tile")),
    )
    env.store(y, y_sram)

    app_plan = AppPlan(env.program)
    task_partition_plan = TaskPartitionPlan(app_plan, env.chip)
    processor_program = LogicalPlan(
        app_plan,
        env.chip,
        task_partition_plan=task_partition_plan,
    )
    tile_program = lower_processor_logical_to_tile_program(
        processor_program,
        env.chip,
        app_plan=app_plan,
    ).to_plan()
    processor_task_plan = tile_program["vendor_task_projection"]["processor_task_plan"]
    assignments = {
        (assignment["m_tile"], assignment["n_tile"]): assignment
        for assignment in processor_task_plan["assignments"].values()
        if assignment["processor"].endswith("processor_0_0")
    }
    assert assignments[(0, 0)]["work_index"] == 0
    assert assignments[(1, 0)]["work_index"] == 1
    assert assignments[(0, 1)]["work_index"] == 2
    assert assignments[(1, 1)]["work_index"] == 3
    assert assignments[(1, 0)]["task_name"] == "task1"
    assert assignments[(0, 1)]["task_name"] == "task2"
    assert {
        tuple(assignment["work_axis_order"])
        for assignment in assignments.values()
    } == {("n_tile", "m_tile")}


def test_app_plan_has_single_constructor_from_chip_program() -> None:
    try:
        AppPlan(  # type: ignore[call-arg]
            source_program="bad_cross_app",
            fusion_regions=(),
            apps=(),
        )
    except TypeError:
        pass
    else:
        raise AssertionError("AppPlan must be constructed from a ChipProgram only")


def test_log10max_audio_preprocess_lowers_to_two_app_plan() -> None:
    env = ChipEnv("log10max_audio_preprocess")
    mel_sram = env.sram_tensor(
        "mel_spec",
        shape=(128, 512),
        dtype="fp32",
        offset_bytes=0x00000,
        role="input",
    )
    out_sram = env.sram_tensor(
        "Y",
        shape=(128, 512),
        dtype="fp32",
        offset_bytes=0x80000,
        role="output",
    )

    mel = env.load(mel_sram, placements=[Shard(0), Shard(1)])
    log_spec = log10(clamp_min(mel, min_value=1.0e-10))
    global_max = reduce_max(log_spec)
    threshold = add_scalar(global_max, -8.0)
    clipped = maximum(log_spec, threshold)
    normalized = mul_scalar(add_scalar(clipped, 4.0), 0.25)
    env.store(normalized, out_sram)
    env.output("Y", out_sram)

    chip_plan = env.to_chip_plan()
    assert [op["op"] for op in chip_plan["ops"]] == [
        "declare_sram_tensor",
        "declare_sram_tensor",
        "load_sram_tensor",
        "clamp_min",
        "log10",
        "reduce_max",
        "add_scalar",
        "maximum",
        "add_scalar",
        "mul_scalar",
        "store_sram_tensor",
    ]

    app_plan = AppPlan(env.program).to_plan()
    assert app_plan["ir"] == "app_plan"
    assert app_plan["schema_version"] == 2
    assert app_plan["totals"] == {
        "app_count": 2,
        "app_op_count": 14,
        "inserted_app_op_count": 2,
    }
    assert app_plan["validation"]["ok"] is True
    assert [op["op"] for op in app_plan["apps"]["app0"]["ops"]] == [
        "load_sram_tensor",
        "clamp_min",
        "log10",
        "reduce_max",
        "app_materialize_store",
    ]
    assert [op["op"] for op in app_plan["apps"]["app1"]["ops"]] == [
        "load_sram_tensor",
        "clamp_min",
        "log10",
        "app_materialize_load",
        "add_scalar",
        "maximum",
        "add_scalar",
        "mul_scalar",
        "store_sram_tensor",
    ]
    store_op = app_plan["apps"]["app0"]["ops"][-1]
    load_op = app_plan["apps"]["app1"]["ops"][3]
    assert store_op["op"] == "app_materialize_store"
    assert load_op["op"] == "app_materialize_load"
    assert store_op["attrs"] == {
        "value_id": "dtensor_0003",
        "storage_id": "app_storage:global_max:dtensor_0003",
        "producer_op": "reduce_store",
        "materialization_kind": "scalar",
        "dtype": "fp32",
        "shape": [],
        "layout": "replicated_scalar",
        "source_collective_op": "chip_op_0005",
        "app_boundary_role": "producer",
    }
    assert load_op["attrs"] == {
        "value_id": "dtensor_0003",
        "storage_id": "app_storage:global_max:dtensor_0003",
        "consumer_op": "broadcast_load",
        "materialization_kind": "scalar",
        "dtype": "fp32",
        "shape": [],
        "layout": "replicated_scalar",
        "source_collective_op": "chip_op_0005",
        "app_boundary_role": "consumer",
    }
    assert load_op["outputs"] == ["dtensor_0003"]
    assert app_plan["apps"]["app0"]["output_storage_refs"] == [
        "app_storage:global_max:dtensor_0003"
    ]
    assert app_plan["apps"]["app1"]["input_storage_refs"] == [
        mel_sram.id,
        "app_storage:global_max:dtensor_0003",
    ]

    runtime_assignment = assign_app_plan_to_runtime_packages(
        AppPlan(env.program),
        DFU3500_SIMICT_LEGACY_RUNTIME_PROFILE,
    ).to_plan()
    assert runtime_assignment["ir"] == "runtime_package_assignment"
    assert runtime_assignment["runtime_profile"]["profile_id"] == (
        "dfu3500_simict_legacy_single_package"
    )
    assert runtime_assignment["totals"] == {
        "semantic_app_count": 2,
        "package_count": 2,
    }
    assert runtime_assignment["validation"] == {
        "all_apps_assigned_once": True,
        "packages_within_runtime_app_capacity": True,
        "requires_runtime_launch_plan": True,
        "runtime_launch_supported": False,
        "single_package_multi_app_supported": True,
        "complete_program_runnable": False,
        "blocking_reasons": [
            "runtime profile does not support multi-package launch"
        ],
        "ok": False,
    }
    assert runtime_assignment["packages"]["package0"]["semantic_app_ids"] == [0]
    assert runtime_assignment["packages"]["package0"]["app_names"] == ["app0"]
    assert runtime_assignment["packages"]["package0"]["binary_emission_status"] == (
        "requires_runtime_launch_plan"
    )
    assert runtime_assignment["packages"]["package1"]["semantic_app_ids"] == [1]
    assert runtime_assignment["packages"]["package1"]["app_names"] == ["app1"]
    assert runtime_assignment["packages"]["package1"]["binary_emission_status"] == (
        "requires_runtime_launch_plan"
    )

    full_plan = env.generate()
    assert full_plan["runtime_package_assignment"] == runtime_assignment
    processor_program = full_plan["processor_logical_program"]
    assert processor_program["totals"]["logical_reduce_count"] == 1
    assert processor_program["totals"]["logical_route_count"] == 0
    logical_reduce = processor_program["logical_reduces"]["logical_reduce_0000"]
    assert logical_reduce["source_chip_op"] == "chip_op_0005"
    assert logical_reduce["reduce_op"] == "max"
    assert logical_reduce["identity_value"] == "-inf"
    assert logical_reduce["visibility_kind"] == "replicated_scalar"
    assert logical_reduce["source_policy"] == "all_processors_contribute"
    assert len(logical_reduce["participants"]) == 16
    assert logical_reduce["attrs"]["implementation_status"] == (
        "symbolic_collective_not_physical_route"
    )

    tile_program = full_plan["processor_tile_program"]
    assert tile_program["validation"]["cross_app_dependencies_are_materialized_storage"]
    assert tile_program["totals"]["collective_bundle_count"] == 1
    assert tile_program["totals"]["app_storage_region_count"] == 1
    assert tile_program["totals"]["app_storage_edge_count"] == 1
    assert tile_program["totals"]["tile_app_storage_action_count"] == 17
    collective = tile_program["collective_bundles"][
        "tile_collective_reduce:logical_reduce_0000"
    ]
    assert collective["collective_kind"] == "all_reduce_max_symbolic"
    assert collective["attrs"]["logical_reduce_edge_id"] == "logical_reduce_0000"
    assert collective["attrs"]["visibility_kind"] == "replicated_scalar"
    reduce_actions = [
        action
        for action in tile_program["tile_compute_actions"].values()
        if action["source_chip_op"] == "chip_op_0005"
    ]
    assert len(reduce_actions) == 16
    assert {action["compute_kind"] for action in reduce_actions} == {
        "local_reduce_max"
    }
    assert {
        action["attrs"]["collective_result_kind"] for action in reduce_actions
    } == {"REPLICATED_APP_SCALAR"}
    storage_actions = tile_program["tile_app_storage_actions"]
    materialize_actions = [
        action for action in storage_actions.values()
        if action["action_kind"] == "reduce_store"
    ]
    load_actions = [
        action for action in storage_actions.values()
        if action["action_kind"] == "broadcast_load"
    ]
    assert len(materialize_actions) == 1
    assert materialize_actions[0]["processor"] == "processor_0_0"
    assert materialize_actions[0]["attrs"]["implementation_status"] == (
        "symbolic_app_storage_materialize"
    )
    assert len(load_actions) == 16
    assert {action["consumer_app_id"] for action in load_actions} == {1}
    cross_app_storage_deps = [
        dependency for dependency in tile_program["tile_dependencies"].values()
        if dependency["crosses_app_boundary"]
    ]
    assert len(cross_app_storage_deps) == 16
    assert {
        dependency["dependency_value_kind"] for dependency in cross_app_storage_deps
    } == {"materialized_storage"}


def test_chip_env_records_explicit_sram_load_compute_store_program(tmp_path: Path) -> None:
    env = ChipEnv("gemm_chip_program")

    a_region = DFU3500_GEMM_REGIONS["A"]
    b_region = DFU3500_GEMM_REGIONS["B"]
    y_region = DFU3500_GEMM_REGIONS["C"]
    a_sram = env.sram_tensor_from_region("A", a_region)
    b_sram = env.sram_tensor_from_region("B", b_region)
    y_sram = env.sram_tensor_from_region("Y", y_region)

    a = env.load(a_sram, placements=[Shard(0), Replicate()])
    b = env.load(b_sram, placements=[Replicate(), Shard(1)])
    y = relu(a @ b)
    env.store(y, y_sram)
    env.output("Y", y_sram)

    plan = env.generate(output_dir=tmp_path)
    chip_program = plan["chip_program"]
    ops = chip_program["ops"]

    assert plan["status"] == "program_bin_package_structural_smoke_ready_functional_blocked"
    assert plan["chip"]["name"] == "dfu3500"
    assert plan["chip"]["logical_fabric"]["shape"] == [4, 4]
    assert plan["chip"]["sram_regions"]["C"]["offset_bytes"] == 0x80000
    assert (tmp_path / "chip_program.json").is_file()
    assert (tmp_path / "simulator_bin/exeblock_conf_info_file.bin").is_file()
    assert (tmp_path / "simulator_bin/insts_file.bin").is_file()
    assert (tmp_path / "simulator_bin/instance_conf_info_file.bin").is_file()
    assert (tmp_path / "simulator_bin/subtasks_conf_info_file.bin").is_file()
    assert (tmp_path / "simulator_bin/tasks_conf_info_file.bin").is_file()
    assert (tmp_path / "config/cbuf_file.bin").is_file()
    assert (tmp_path / "config/micc_file.bin").is_file()
    assert chip_program["execution_model"] == "spmd"
    assert chip_program["totals"] == {
        "fabric_count": 1,
        "sram_tensor_count": 3,
        "dtensor_count": 4,
        "op_count": 8,
        "output_count": 1,
    }
    assert [op["op"] for op in ops] == [
        "declare_sram_tensor",
        "declare_sram_tensor",
        "declare_sram_tensor",
        "load_sram_tensor",
        "load_sram_tensor",
        "matmul",
        "relu",
        "store_sram_tensor",
    ]
    assert chip_program["outputs"] == {"Y": y_sram.id}
    assert chip_program["sram_tensors"][a_sram.id]["region"] == {
        "address_space": "sram",
        "offset_bytes": a_region.offset_bytes,
        "nbytes": 512 * 256 * 2,
        "end_offset_bytes": 512 * 256 * 2,
    }
    assert chip_program["sram_tensors"][b_sram.id]["region"]["offset_bytes"] == b_region.offset_bytes
    assert chip_program["sram_tensors"][y_sram.id]["region"]["offset_bytes"] == y_region.offset_bytes
    assert ops[3]["attrs"]["src_region"]["offset_bytes"] == a_region.offset_bytes
    assert ops[-1]["attrs"]["dst_region"]["offset_bytes"] == y_region.offset_bytes
    assert all("PE" not in str(op) for op in ops)
    assert all("subtask" not in str(op).lower() for op in ops)

    app_plan = plan["app_plan"]
    assert app_plan["ir"] == "app_plan"
    assert app_plan["schema_version"] == 2
    assert app_plan["totals"] == {
        "app_count": 1,
        "app_op_count": 5,
        "inserted_app_op_count": 0,
    }
    assert app_plan["validation"] == {
        "every_app_has_ops": True,
        "app_materialization_ops_are_balanced": True,
        "ok": True,
        "errors": [],
    }
    app0 = app_plan["apps"]["app0"]
    assert app0["input_storage_refs"] == [a_sram.id, b_sram.id]
    assert app0["output_storage_refs"] == [y_sram.id]
    assert app0["op_ids"] == [
        ops[3]["id"],
        ops[4]["id"],
        ops[5]["id"],
        ops[6]["id"],
        ops[7]["id"],
    ]
    assert [op["op"] for op in app0["ops"]] == [
        "load_sram_tensor",
        "load_sram_tensor",
        "matmul",
        "relu",
        "store_sram_tensor",
    ]

    processor_program = plan["processor_logical_program"]
    assert processor_program["chip"] == "dfu3500"
    assert processor_program["processor_shape"] == [4, 4]
    assert processor_program["totals"] == {
        "processor_count": 16,
        "app_count": 1,
        "local_value_count": 64,
        "action_count": 80,
        "logical_route_count": 8,
        "logical_route_step_count": 32,
        "logical_reduce_count": 0,
        "logical_dependency_count": 64,
        "output_count": 1,
    }
    assert processor_program["ir"] == "logical_plan"
    assert processor_program["apps"]["app0"]["ir"] == "logical_app"
    assert processor_program["soft_processor_mesh"] == {
        "axis_order": ["task", "x", "y"],
        "task_axis_size": 1,
        "physical_processor_shape": [4, 4],
        "value_scope": "PELocal(app_id, task_id, physical_pe_id)",
        "implementation_stage": "logical_plan_owned_soft_mesh",
    }
    assert processor_program["soft_mesh"]["processor_1_2"]["coord"] == [0, 1, 2]
    assert processor_program["soft_mesh"]["processor_1_2"]["axis_names"] == [
        "task",
        "x",
        "y",
    ]
    assert len(processor_program["logical_routes"]) == 8
    assert len(processor_program["logical_dependencies"]) == 64
    first_route = processor_program["logical_routes"]["logical_route_0000"]
    assert first_route["operand_role"] == "A"
    assert first_route["route_kind"] == "row_broadcast"
    assert first_route["fabric_scope"] == "row"
    assert first_route["group_key"] == "row:0"
    assert "logical_route_is_already_a_path_propagation_program" in first_route["dependency_policy"]
    assert "no_extra_tail_to_root_dependency" in first_route["dependency_policy"]
    assert first_route["attrs"]["tile_dependency_shape"] == {
        "route_action_dependencies": "expand_logical_route_steps",
        "source_dependency": "source_tile_available_before_source_endpoint",
        "hop_dependency": "dst_hop_depends_on_previous_route_hop",
        "compute_dependency": "compute_depends_on_local_visibility_endpoint",
        "forbidden_dependency": "route_tail_must_not_also_depend_on_route_root",
    }
    assert [step["attrs"]["edge"] for step in first_route["route_steps"]] == [
        "processor_0_0->processor_0_0",
        "processor_0_0->processor_0_1",
        "processor_0_1->processor_0_2",
        "processor_0_2->processor_0_3",
    ]
    assert first_route["route_steps"][0]["depends_on"] == [f"logical_shard:{a.id}:row:0"]
    assert first_route["route_steps"][1]["depends_on"] == [first_route["route_steps"][0]["id"]]
    assert first_route["endpoint_by_processor"]["processor_0_3"] == first_route["route_steps"][3]["id"]
    assert first_route["participants"] == [
        "processor_0_0",
        "processor_0_1",
        "processor_0_2",
        "processor_0_3",
    ]
    assert first_route["source_shard"]["ref"] == f"logical_shard:{a.id}:row:0"
    assert len(first_route["consumer_action_ids"]) == 4

    processor_1_2 = processor_program["streams"]["processor_1_2"]
    assert processor_1_2["coordinate"] == [1, 2]
    assert processor_1_2["vendor_processor_id"] == "PE12"
    assert [action["op"] for action in processor_1_2["actions"]] == [
        "load_sram_tensor",
        "load_sram_tensor",
        "matmul",
        "relu",
        "store_sram_tensor",
    ]

    local_values = processor_program["local_values"]
    a_view = _local_value_for(local_values, logical_tensor_id=a.id, processor="processor_1_2")
    b_view = _local_value_for(local_values, logical_tensor_id=b.id, processor="processor_1_2")
    y_view = _local_value_for(local_values, logical_tensor_id=y.id, processor="processor_1_2")
    assert a_view["logical_tensor_name"] == "A"
    assert a_view["local_shape"] == [128, 256]
    assert a_view["global_offset"] == [128, 0]
    assert a_view["source_sram_tensor_id"] == a_sram.id
    assert a_view["producer_chip_op"] == ops[3]["id"]
    assert b_view["local_shape"] == [256, 128]
    assert b_view["global_offset"] == [0, 256]
    assert b_view["source_sram_tensor_id"] == b_sram.id
    assert y_view["logical_tensor_name"] == y.name
    assert y_view["local_shape"] == [128, 128]
    assert y_view["global_offset"] == [128, 256]
    assert y_view["producer_chip_op"] == ops[6]["id"]

    store_action = processor_1_2["actions"][-1]
    assert store_action["inputs"] == [y_view["id"]]
    assert store_action["attrs"]["dst_sram_tensor_id"] == y_sram.id

    tile_program = plan["processor_tile_program"]
    assert tile_program["chip"] == "dfu3500"
    assert tile_program["tile_sizes"] == {"k": 64, "m": 64, "n": 64}
    assert tile_program["totals"] == {
        "processor_count": 16,
        "phase_count": 80,
        "collective_bundle_count": 128,
        "tile_route_action_count": 512,
        "tile_compute_action_count": 320,
        "tile_store_action_count": 64,
        "tile_app_storage_action_count": 0,
        "app_storage_region_count": 0,
        "app_storage_edge_count": 0,
        "tile_visibility_ref_count": 512,
        "tile_micro_block_count": 896,
        "tile_block_dependency_count": 1216,
        "action_to_micro_block_count": 896,
        "tile_loop_region_count": 64,
        "processor_tile_action_count": 896,
        "tile_dependency_count": 1344,
        "output_count": 1,
    }
    assert tile_program["validation"] == {
        "all_actions_have_micro_blocks": True,
        "all_compute_blocks_owned_by_compute_processor": True,
        "all_route_blocks_owned_by_execution_processor": True,
        "all_store_blocks_owned_by_store_processor": True,
        "cross_app_dependencies_are_materialized_storage": True,
    }
    processor_task_plan = tile_program["vendor_task_projection"]["processor_task_plan"]
    assert tile_program["vendor_task_projection"]["totals"] == {
        "assignment_count": 64,
        "launch_group_count": 1,
        "task_plan_count": 4,
    }
    assert processor_task_plan["ir"] == "vendor_task_projection_report"
    assert processor_task_plan["source_of_truth"] == "restricted_soft_task_axis"
    assert processor_task_plan["policy"] == {
        "policy_name": "soft_task_axis_legacy_gemm_output_work_projection",
        "max_vendor_tasks": 4,
        "task_axis": "soft_task_axis",
        "work_index_source": "TaskShard.work_axis_order",
        "legacy_wave_alias": "work_index",
        "overflow_policy": "explicit_task_shard_requires_one_work_unit_per_task",
        "supports_multi_launch": False,
    }
    assert processor_task_plan["validation"] == {
        "all_task_ids_within_vendor_limit": True,
        "single_launch_group_supported": True,
    }
    assert processor_task_plan["totals"] == {
        "assignment_count": 64,
        "launch_group_count": 1,
    }
    assert {
        assignment["assignment_source"]
        for assignment in processor_task_plan["assignments"].values()
    } == {"legacy_fallback_no_task_axis_shard"}
    processor_1_2_assignments = [
        assignment
        for assignment in processor_task_plan["assignments"].values()
        if assignment["processor"] == "processor_1_2"
    ]
    assert [
        (
            assignment["virtual_work_id"],
            assignment["legacy_wave_id"],
            assignment["launch_group_id"],
            assignment["task_id"],
            assignment["task_name"],
            assignment["m_tile"],
            assignment["n_tile"],
        )
        for assignment in sorted(
            processor_1_2_assignments,
            key=lambda row: row["virtual_work_id"],
        )
    ] == [
        (0, 0, 0, 0, "task0", 0, 0),
        (1, 1, 0, 1, "task1", 0, 1),
        (2, 2, 0, 2, "task2", 1, 0),
        (3, 3, 0, 3, "task3", 1, 1),
    ]

    tile_stream_1_2 = tile_program["programs"]["processor_1_2"]
    assert [phase["phase_kind"] for phase in tile_stream_1_2["phases"]] == [
        "local_gemm_summa",
        "local_gemm_summa",
        "local_gemm_summa",
        "local_gemm_summa",
        "store_sram_tensor",
    ]
    assert [item["item_kind"] for item in tile_stream_1_2["program_sequence"]] == [
        "tile_loop",
        "tile_loop",
        "tile_loop",
        "tile_loop",
        "tile_phase",
    ]
    first_gemm_phase = tile_stream_1_2["phases"][0]
    assert first_gemm_phase["local_ops"] == ["init_c", "stream_k_gemm", "relu", "store_c"]
    assert first_gemm_phase["output_refs"] == [y_view["id"]]
    assert first_gemm_phase["payload"]["fused_chip_ops"] == [ops[6]["id"]]
    assert len(first_gemm_phase["payload"]["k_block_updates"]) == 4
    assert len(first_gemm_phase["route_prefix_refs"]) == 8
    first_update = first_gemm_phase["payload"]["k_block_updates"][0]
    assert first_update["a_tile"]["global_m"] == {"start": 128, "end": 192, "padded_end": 192}
    assert first_update["b_tile"]["global_n"] == {"start": 256, "end": 320, "padded_end": 320}
    assert first_update["tile_compute_action_id"].startswith("tile_compute:processor_1_2:")
    first_compute_action = tile_program["tile_compute_actions"][
        first_update["tile_compute_action_id"]
    ]
    assert first_compute_action["compute_kind"] == "gemm_k_update"
    assert first_compute_action["processor"] == "processor_1_2"
    assert [prefix["operand_role"] for prefix in first_update["route_prefix_actions"]] == ["A", "B"]
    a_prefix = first_update["route_prefix_actions"][0]
    b_prefix = first_update["route_prefix_actions"][1]
    loop_id = first_gemm_phase["payload"]["tile_loop_region_id"]
    first_loop_region = tile_program["tile_loop_regions"][loop_id]
    assert first_loop_region["processor"] == "processor_1_2"
    assert first_loop_region["source_phase_id"] == first_gemm_phase["phase_id"]
    assert first_loop_region["loop_axis"] == "K"
    assert first_loop_region["repeat_count"] == 4
    assert first_loop_region["closure_shape"] == "closed_repeated_tile_body"
    assert first_loop_region["fold_policy"] == "vendor_instance_repeat_candidate"
    assert first_loop_region["grouping"] == {
        "kind": "single_accumulator",
        "group_size": 1,
        "shared_side": None,
        "future_pass": "multi_accumulator_body_grouping",
    }
    assert first_loop_region["carried_refs"] == [
        first_gemm_phase["payload"]["c_tile_wave"]["accumulator_view_ref"],
        first_gemm_phase["payload"]["c_tile_wave"]["accumulator_tile_ref"],
    ]
    assert len(first_loop_region["body_instances"]) == 4
    first_loop_instance = first_loop_region["body_instances"][0]
    assert first_loop_instance["instance_id"] == 0
    assert first_loop_instance["depends_on_previous_instance"] is False
    assert first_loop_instance["compute_action_ids"] == [first_update["tile_compute_action_id"]]
    assert first_loop_instance["micro_block_ids"]
    assert set(first_loop_instance["route_action_ids"]) == {
        *a_prefix["route_action_ids"],
        *b_prefix["route_action_ids"],
    }
    assert first_update["tile_compute_action_id"] in first_loop_instance["action_ids"]
    assert first_update["a_tile"]["tile_ref"] in first_loop_region["loop_variant_refs"]
    assert first_update["b_tile"]["tile_ref"] in first_loop_region["loop_variant_refs"]
    second_loop_instance = first_loop_region["body_instances"][1]
    assert second_loop_instance["instance_id"] == 1
    assert second_loop_instance["depends_on_previous_instance"] is True
    assert a_prefix["logical_route_edge_id"] == "logical_route_0001"
    assert a_prefix["dependency_policy"] == "expanded_from_logical_route_steps_path_propagation"
    assert a_prefix["endpoint_action_id"] in first_gemm_phase["route_prefix_refs"]
    assert len(a_prefix["route_action_ids"]) == 4
    a_route_actions = [
        tile_program["tile_route_actions"][action_id]
        for action_id in a_prefix["route_action_ids"]
    ]
    assert [action["attrs"]["edge"] for action in a_route_actions] == [
        "processor_1_0->processor_1_0",
        "processor_1_0->processor_1_1",
        "processor_1_1->processor_1_2",
        "processor_1_2->processor_1_3",
    ]
    assert [action["execution_processor"] for action in a_route_actions] == [
        "processor_1_0",
        "processor_1_0",
        "processor_1_1",
        "processor_1_2",
    ]
    assert [action["endpoint_processor"] for action in a_route_actions] == [
        "processor_1_0",
        "processor_1_1",
        "processor_1_2",
        "processor_1_3",
    ]
    assert a_route_actions[2]["attrs"]["execution_model"] == "sender_push_copyt"
    assert a_route_actions[0]["depends_on"] == [first_update["a_tile"]["tile_ref"]]
    assert a_route_actions[2]["depends_on"] == [a_route_actions[1]["id"]]
    compute_dep = tile_program["tile_dependencies"][a_prefix["compute_dependency_id"]]
    assert compute_dep["dependency_kind"] == "tile_visibility_endpoint_before_compute"
    assert compute_dep["src"] == a_prefix["endpoint_action_id"]
    assert compute_dep["dst"] == first_update["tile_compute_action_id"]
    prepare_action_id = first_gemm_phase["payload"]["accumulator_prepare_action_id"]
    assert first_compute_action["depends_on"] == [
        a_prefix["endpoint_action_id"],
        b_prefix["endpoint_action_id"],
        prepare_action_id,
    ]
    second_update = first_gemm_phase["payload"]["k_block_updates"][1]
    second_compute_action = tile_program["tile_compute_actions"][
        second_update["tile_compute_action_id"]
    ]
    assert first_update["tile_compute_action_id"] in second_compute_action["depends_on"]
    assert len(first_gemm_phase["collective_refs"]) == 8
    store_phase = tile_stream_1_2["phases"][-1]
    assert store_phase["input_refs"] == [y_view["id"]]
    assert len(store_phase["payload"]["tile_store_action_ids"]) == 4
    assert [record["tile_coord"] for record in store_phase["payload"]["tile_store_actions"]] == [
        {"m_tile": 0, "n_tile": 0},
        {"m_tile": 0, "n_tile": 1},
        {"m_tile": 1, "n_tile": 0},
        {"m_tile": 1, "n_tile": 1},
    ]
    assert [
        tile_program["tile_store_actions"][store_action_id]["depends_on"][0]
        for store_action_id in store_phase["payload"]["tile_store_action_ids"]
    ] == [
        tile_stream_1_2["phases"][wave_index]["payload"]["k_block_updates"][-1][
            "tile_compute_action_id"
        ]
        for wave_index in range(4)
    ]
    store_action_id = store_phase["payload"]["tile_store_action_ids"][0]
    store_action = tile_program["tile_store_actions"][store_action_id]
    assert store_action["attrs"]["logical_input_refs"] == [y_view["id"]]
    assert store_action["attrs"]["store_granularity"] == "one_output_tile"
    assert store_action["attrs"]["source_final_tile"]["tile_ref"] == (
        "tile:dtensor_0003:processor_1_2:Y:128:256"
    )
    action_stream = tile_program["processor_action_streams"]["processor_1_2"]["actions"]
    assert {"route", "compute", "store"} <= {
        action_ref["action_kind"] for action_ref in action_stream
    }
    assert set(store_phase["payload"]["tile_store_action_ids"]) <= {
        action_ref["action_id"] for action_ref in action_stream
    }

    program_nodes = plan["program_nodes"]
    assert program_nodes["source_ir"] == "processor_tile_program"
    assert program_nodes["totals"] == {
        "processor_count": 16,
        "node_count": 896,
        "edge_count": 1216,
        "external_precondition_count": 128,
        "action_to_node_count": 896,
        "graphable_tile_dependency_count": 1216,
        "loop_region_count": 64,
        "micro_block_count": 896,
        "micro_block_membership_count": 896,
        "loop_membership_count": 2304,
        "node_counts": {
            "route_materialize": 512,
            "tile_compute": 320,
            "tile_store": 64,
        },
        "edge_counts": {
            "accumulator_dependency": 192,
            "route_step_order": 384,
            "store_dependency": 64,
            "tile_accumulator_prepare_before_compute": 64,
            "visibility_dependency": 512,
        },
    }
    assert program_nodes["validation"] == {
        "all_actions_have_nodes": True,
        "all_loop_body_actions_have_nodes": True,
        "all_micro_block_actions_have_nodes": True,
        "is_acyclic": True,
    }
    assert len(program_nodes["per_processor_nodes"]) == 16
    assert all(program_nodes["per_processor_nodes"].values())

    node_loop_region = program_nodes["loop_regions"][loop_id]
    assert node_loop_region["processor"] == "processor_1_2"
    assert node_loop_region["source_phase_id"] == first_gemm_phase["phase_id"]
    assert node_loop_region["loop_axis"] == "K"
    assert node_loop_region["repeat_count"] == 4
    assert node_loop_region["fold_policy"] == "vendor_instance_repeat_candidate"
    assert node_loop_region["missing_action_ids"] == []
    assert node_loop_region["action_ids_by_instance"]["k0"] == first_loop_instance[
        "action_ids"
    ]
    assert node_loop_region["micro_block_ids_by_instance"]["k0"] == first_loop_instance[
        "micro_block_ids"
    ]

    route_action = a_route_actions[2]
    route_micro_block_id = tile_program["action_to_micro_block"][route_action["id"]]
    route_micro_block = tile_program["tile_micro_blocks"][route_micro_block_id]
    assert route_micro_block["block_kind"] == "route_forward"
    assert route_micro_block["processor"] == route_action["execution_processor"]
    assert route_micro_block["route_action_ids"] == [route_action["id"]]
    assert route_micro_block["compute_action_ids"] == []
    assert route_action["produces_endpoint_ref"] in route_micro_block["output_visibility_refs"]
    route_visibility_ref = tile_program["tile_visibility_refs"][
        route_action["produces_endpoint_ref"]
    ]
    assert route_visibility_ref["producer_action_id"] == route_action["id"]
    assert route_visibility_ref["endpoint_processor"] == route_action["endpoint_processor"]

    compute_micro_block_id = tile_program["action_to_micro_block"][
        first_update["tile_compute_action_id"]
    ]
    compute_micro_block = tile_program["tile_micro_blocks"][compute_micro_block_id]
    assert compute_micro_block["block_kind"] == "compute_update"
    assert compute_micro_block["processor"] == "processor_1_2"
    assert compute_micro_block["route_action_ids"] == []
    assert compute_micro_block["store_action_ids"] == []
    assert compute_micro_block["compute_action_ids"] == [first_update["tile_compute_action_id"]]
    assert set(compute_micro_block["input_visibility_refs"]) == {
        tile_program["tile_route_actions"][a_prefix["endpoint_action_id"]][
            "produces_endpoint_ref"
        ],
        tile_program["tile_route_actions"][b_prefix["endpoint_action_id"]][
            "produces_endpoint_ref"
        ],
    }
    route_node_id = program_nodes["action_to_node"][route_action["id"]]
    route_node = program_nodes["nodes"][route_node_id]
    assert route_node["node_kind"] == "route_materialize"
    assert route_node["processor"] == route_action["execution_processor"]
    assert route_node["payload"]["endpoint_processor"] == route_action["endpoint_processor"]
    assert route_node["payload"]["produces_endpoint_ref"] == route_action["produces_endpoint_ref"]
    assert route_node["payload"]["tile_micro_block_id"] == route_micro_block_id
    assert route_node["payload"]["tile_micro_block_kind"] == "route_forward"
    assert route_node["payload"]["tile_micro_block_processor"] == (
        route_action["execution_processor"]
    )
    assert route_node["payload"]["loop_role"] == "route"
    assert route_node["payload"]["loop_membership_count"] == 4
    assert loop_id in route_node["payload"]["loop_region_ids"]
    assert route_node_id in node_loop_region["node_ids_by_instance"]["k0"]

    compute_node_id = program_nodes["action_to_node"][first_update["tile_compute_action_id"]]
    assert compute_node_id in node_loop_region["node_ids_by_instance"]["k0"]
    compute_node = program_nodes["nodes"][compute_node_id]
    assert compute_node["payload"]["task_assignment"]["task_name"] == "task0"
    assert compute_node["payload"]["task_assignment"]["task_id"] == 0
    assert compute_node["payload"]["task_assignment"]["assignment_key"] == [
        "soft_task_axis_legacy_gemm_output_work_projection",
        0,
        0,
        0,
        0,
        0,
    ]
    assert compute_node["payload"]["tile_micro_block_id"] == compute_micro_block_id
    assert compute_node["payload"]["tile_micro_block_kind"] == "compute_update"
    assert compute_node["payload"]["tile_micro_block_processor"] == "processor_1_2"
    assert set(compute_node["payload"]["tile_micro_block_input_visibility_refs"]) == set(
        compute_micro_block["input_visibility_refs"]
    )
    assert compute_node["payload"]["loop_region_id"] == loop_id
    assert compute_node["payload"]["loop_region_ids"] == [loop_id]
    assert compute_node["payload"]["loop_instance_id"] == "k0"
    assert compute_node["payload"]["loop_axis"] == "K"
    assert compute_node["payload"]["loop_role"] == "compute"
    assert compute_node["payload"]["loop_fold_policy"] == (
        "vendor_instance_repeat_candidate"
    )
    assert compute_node["payload"]["loop_membership_count"] == 1
    assert compute_node["payload"]["debug_origin"]["program_sequence_index"] == 0
    assert compute_node["payload"]["debug_origin"]["tile_action_id"] == (
        first_update["tile_compute_action_id"]
    )
    assert "role=compute" in compute_node["payload"]["source_region_path"]
    incoming_visibility_edges = [
        edge
        for edge in program_nodes["edges"].values()
        if edge["dst_node"] == compute_node_id
        and edge["edge_kind"] == "visibility_dependency"
    ]
    assert {
        edge["payload"]["src_action_id"] for edge in incoming_visibility_edges
    } == {
        a_prefix["endpoint_action_id"],
        b_prefix["endpoint_action_id"],
    }
    assert {
        program_nodes["nodes"][edge["src_node"]]["node_kind"]
        for edge in incoming_visibility_edges
    } == {"route_materialize"}

    first_store_node_id = program_nodes["action_to_node"][store_action_id]
    first_store_node = program_nodes["nodes"][first_store_node_id]
    assert first_store_node["payload"]["loop_region_id"] is None
    assert first_store_node["payload"]["loop_region_ids"] == []
    assert first_store_node["payload"]["loop_membership_count"] == 0
    assert first_store_node["payload"]["debug_origin"] is None
    incoming_store_edges = [
        edge
        for edge in program_nodes["edges"].values()
        if edge["dst_node"] == first_store_node_id
    ]
    assert len(incoming_store_edges) == 1
    assert incoming_store_edges[0]["edge_kind"] == "store_dependency"
    assert incoming_store_edges[0]["src_node"] == program_nodes["action_to_node"][
        tile_stream_1_2["phases"][0]["payload"]["k_block_updates"][-1][
            "tile_compute_action_id"
        ]
    ]

    dfu_packing = plan["dfu_packing_program"]
    assert dfu_packing["source_ir"] == "program_nodes"
    assert dfu_packing["totals"] == {
        "task_count": 4,
            "container_count": 192,
            "instance_count": 384,
            "node_binding_count": 896,
            "micro_block_binding_count": 896,
            "edge_binding_count": 1216,
        "loop_folding_candidate_count": 64,
        "repeated_loop_template_count": 64,
        "repeated_body_template_count": 64,
            "vendor_graph_eligible_edge_count": 1024,
        "loop_carried_edge_count": 192,
            "container_role_counts": {
                "accumulator_prepare": 64,
                "finalize_store": 64,
                "k_stream": 64,
            },
            "instance_role_counts": {
                "accumulator_prepare": 64,
                "finalize_store": 64,
                "k_stream": 256,
            },
            "edge_scope_counts": {
                "cross_processor_same_task": 640,
                "cross_subtask": 128,
                "internal_instance": 256,
                "internal_subtask": 192,
            },
        "edge_class_counts": {
            "internal_template_edge": 512,
            "loop_carried_edge": 192,
                "normal_graph_edge": 512,
        },
    }
    assert dfu_packing["validation"] == {
        "all_nodes_bound": True,
        "all_loop_containers_have_repeat_metadata": True,
        "all_node_bindings_keep_micro_block_identity": True,
        "all_repeated_loop_templates_are_metadata_only": True,
        "loop_carried_edges_are_absorbed": True,
        "no_unbound_edges": True,
    }
    assert dfu_packing["edge_legalization_report"] == {
            "total_edges_before": 1216,
            "normal_graph_edges": 512,
            "internal_template_edges": 512,
            "loop_carried_edges": 192,
            "vendor_graph_eligible_edges": 1024,
            "vendor_edges_after": 1024,
        "absorbed_counts": {"loop_carried_state": 192},
        "policy": (
            "preserve_original_edge_bindings;"
            "absorb_loop_carried_edges_into_repeated_body_carried_state"
        ),
    }
    assert dfu_packing["tasks"]["task0"]["packing_kind"] == "output_tile_work_unit_region"
    assert "task0:processor_1_2:subtask1" in dfu_packing["tasks"]["task0"]["container_ids"]
    k_stream_container = dfu_packing["containers"]["task0:processor_1_2:subtask1"]
    assert k_stream_container["subtask_role"] == "k_stream"
    assert k_stream_container["authoritative_view"] == "folded_template"
    assert k_stream_container["loop_region_id"] == loop_id
    assert k_stream_container["repeat_semantics"] == "vendor_instance_repeat"
    assert k_stream_container["repeat_count"] == 4
    assert k_stream_container["carried_refs"] == first_loop_region["carried_refs"]
    assert k_stream_container["body_template"]["loop_region_id"] == loop_id
    assert k_stream_container["body_template"]["repeat_count"] == 4
    assert k_stream_container["body_template"]["body_shape"] == (
        "expanded_debug_instances_are_template_instances"
    )
    assert k_stream_container["body_template"]["instance_bindings"] == [
        "k0",
        "k1",
        "k2",
        "k3",
    ]
    assert k_stream_container["body_template"]["micro_block_ids_by_instance"] == (
        node_loop_region["micro_block_ids_by_instance"]
    )
    assert k_stream_container["expanded_debug_instances"]["k0"] == (
        node_loop_region["node_ids_by_instance"]["k0"]
    )
    repeated_template_id = f"repeated_loop_template:{loop_id}"
    repeated_template = dfu_packing["repeated_loop_templates"][repeated_template_id]
    assert repeated_template["loop_region_id"] == loop_id
    assert repeated_template["task_id"] == "task0"
    assert repeated_template["processor"] == "processor_1_2"
    assert repeated_template["loop_axis"] == "K"
    assert repeated_template["repeat_count"] == 4
    assert repeated_template["fold_policy"] == "vendor_instance_repeat_candidate"
    assert repeated_template["body_micro_block_ids"] == (
        first_loop_instance["micro_block_ids"]
    )
    assert repeated_template["body_micro_block_kinds"] == [
        "route_source_materialize",
        "route_forward",
        "route_forward",
        "route_forward",
        "route_source_materialize",
        "route_forward",
        "route_forward",
        "route_forward",
        "compute_update",
    ]
    assert repeated_template["expanded_debug_instance_keys"] == ["k0", "k1", "k2", "k3"]
    assert repeated_template["instance_isomorphism"]["instance_isomorphic"] is True
    assert repeated_template["attrs"] == {
        "folded_repeat_mode": "metadata_only",
        "expanded_debug_instance_count": 4,
        "folded_vendor_row_estimate": 9,
        "expanded_vendor_row_count": 36,
        "template_scope": "per_loop_region_per_processor",
        "binary_facing": False,
    }
    assert dfu_packing["containers"]["task0:processor_1_2:subtask0"]["subtask_role"] == "accumulator_prepare"
    assert dfu_packing["containers"]["task0:processor_1_2:subtask2"]["subtask_role"] == "finalize_store"
    assert dfu_packing["containers"]["task0:processor_1_2:subtask2"][
        "is_final_runtime_container"
    ]

    compute_binding = dfu_packing["node_bindings"][compute_node_id]
    assert compute_binding["task_id"] == "task0"
    assert compute_binding["subtask_id"] == "subtask1"
    assert compute_binding["subtask_role"] == "k_stream"
    assert compute_binding["instance_key"] == "k0"
    assert compute_binding["instance_id"] == "task0:processor_1_2:subtask1:inst0"
    assert compute_binding["tile_micro_block_id"] == compute_micro_block_id
    assert compute_binding["tile_micro_block_kind"] == "compute_update"

    store_binding = dfu_packing["node_bindings"][first_store_node_id]
    assert store_binding["task_id"] == "task0"
    assert store_binding["subtask_id"] == "subtask2"
    assert store_binding["subtask_role"] == "finalize_store"
    assert store_binding["instance_key"] == "final"
    assert store_binding["instance_id"] == "task0:processor_1_2:subtask2:inst_final"
    assert store_binding["tile_micro_block_kind"] == "tile_store"
    store_edge_binding = dfu_packing["edge_bindings"][incoming_store_edges[0]["id"]]
    final_compute_micro_block_id = tile_program["action_to_micro_block"][
        tile_stream_1_2["phases"][0]["payload"]["k_block_updates"][-1][
            "tile_compute_action_id"
        ]
    ]
    assert store_edge_binding["scope"] == "cross_subtask"
    assert store_edge_binding["reason"] == "tile_store_waits_for_final_output_tile"
    assert store_edge_binding["src_micro_block"] == final_compute_micro_block_id
    assert store_edge_binding["src_micro_block_kind"] == "compute_update"
    assert store_edge_binding["dst_micro_block_kind"] == "tile_store"
    loop_carried_edge_binding = next(
        binding
        for binding in dfu_packing["edge_bindings"].values()
        if binding["legalized_edge_class"] == "loop_carried_edge"
        and binding["src_node"] == compute_node_id
    )
    assert loop_carried_edge_binding["edge_kind"] == "accumulator_dependency"
    assert loop_carried_edge_binding["scope"] == "internal_subtask"
    assert loop_carried_edge_binding["vendor_graph_eligible"] is False
    assert loop_carried_edge_binding["absorbed_by"] == "loop_carried_state"
    assert (
            dfu_packing["loop_folding_candidates"]["loop_fold:task0:processor_1_2:subtask1"][
            "instance_keys"
        ]
        == ["k0", "k1", "k2", "k3"]
    )
    loop_candidate = dfu_packing["loop_folding_candidates"][
        "loop_fold:task0:processor_1_2:subtask1"
    ]
    assert loop_candidate["loop_region_id"] == loop_id
    assert loop_candidate["authoritative_view"] == "folded_template"
    assert loop_candidate["repeat_semantics"] == "vendor_instance_repeat"
    assert loop_candidate["repeat_count"] == 4
    assert loop_candidate["status"] == (
        "structural_tile_loop_region_candidate_not_binary_folded"
    )
    assert "TileLoopRegion_is_authoritative" in loop_candidate["reason"]

    program_asm = plan["program_asm"]
    assert program_asm["source_ir"] == "dfu_packing_program"
    assert program_asm["totals"] == {
            "block_count": 896,
            "instruction_count": 896,
            "dependency_count": 1216,
            "node_to_instruction_count": 896,
            "edge_to_dependency_count": 1216,
            "template_bound_instruction_count": 201856,
            "template_bound_instruction_to_asm_instruction_count": 201856,
            "stage_counts": {
                "CAL": 320,
                "FLOW": 192,
                "LD": 320,
                "ST": 64,
            },
            "opcode_counts": {
                "DFU_COPYT_ROUTE_TILE": 512,
                "DFU_HMMAL_TILE": 256,
                "DFU_LOCAL_ACCUMULATOR_PREPARE": 64,
                "DFU_STORE_TILE_TO_SRAM": 64,
            },
            "block_role_counts": {
                "accumulator_prepare": 64,
                "finalize_store": 64,
                "k_stream": 768,
            },
            "dependency_scope_counts": {
                "cross_processor_block": 640,
                "cross_subtask_block": 128,
                "same_container_cross_block": 192,
                "same_instance_cross_block": 256,
            },
            "dependency_class_counts": {
                "internal_template_edge": 512,
                "loop_carried_edge": 192,
                "normal_graph_edge": 512,
            },
            "vendor_graph_eligible_dependency_count": 1024,
            "loop_carried_dependency_count": 192,
        }
    assert program_asm["validation"] == {
        "all_blocks_nonempty": True,
        "all_bound_edges_have_dependencies": True,
        "all_bound_nodes_have_instructions": True,
        "template_bound_metadata_attached": True,
    }
    assert program_asm["repeated_loop_templates"][repeated_template_id] == repeated_template
    compute_instruction_id = program_asm["node_to_instruction"][compute_node_id]
    compute_instruction = program_asm["instructions"][compute_instruction_id]
    assert compute_instruction["opcode"] == "DFU_HMMAL_TILE"
    assert compute_instruction["stage"] == "CAL"
    assert compute_instruction["stage_source"] == (
        "mixed_template_bound_segments_symbolic_fallback"
    )
    assert compute_instruction["asm_block_id"].startswith(
        "asm_block:task0:processor_1_2:subtask1:inst0:"
    )
    assert compute_instruction["source_tile_micro_block_id"] == compute_micro_block_id
    assert compute_instruction["source_tile_micro_block_kind"] == "compute_update"
    assert compute_instruction["template_bound_instruction_count"] == 624
    assert len(compute_instruction["template_bound_instruction_ids"]) == 624
    first_bound_instruction = plan["dfu3500_template_bound_program"]["instructions"][
        compute_instruction["template_bound_instruction_ids"][0]
    ]
    middle_bound_instruction = plan["dfu3500_template_bound_program"]["instructions"][
        compute_instruction["template_bound_instruction_ids"][96]
    ]
    last_bound_instruction = plan["dfu3500_template_bound_program"]["instructions"][
        compute_instruction["template_bound_instruction_ids"][-1]
    ]
    assert first_bound_instruction["source_tile_micro_block_id"] == compute_micro_block_id
    assert first_bound_instruction["source_tile_micro_block_kind"] == "compute_update"
    assert first_bound_instruction["legacy_op"] == "LDN"
    assert first_bound_instruction["stage"] == "LD"
    assert middle_bound_instruction["legacy_op"] == "HMMAL"
    assert middle_bound_instruction["stage"] == "CAL"
    assert last_bound_instruction["legacy_op"] == "TRCTT"
    assert last_bound_instruction["stage"] == "CAL"
    assert compute_instruction["symbolic_operands"]["a_tile_ref"] == "tile:dtensor_0000:A:128:0"
    assert compute_instruction["symbolic_operands"]["b_tile_ref"] == "tile:dtensor_0001:B:0:256"
    compute_asm_block = program_asm["blocks"][compute_instruction["asm_block_id"]]
    assert compute_micro_block_id in compute_asm_block["source_tile_micro_block_ids"]
    assert "compute_update" in compute_asm_block["source_tile_micro_block_kinds"]

    store_instruction_id = program_asm["node_to_instruction"][first_store_node_id]
    store_instruction = program_asm["instructions"][store_instruction_id]
    assert store_instruction["opcode"] == "DFU_STORE_TILE_TO_SRAM"
    assert store_instruction["stage"] == "ST"
    assert store_instruction["source_tile_micro_block_kind"] == "tile_store"
    assert store_instruction["asm_block_id"].startswith(
        "asm_block:task0:processor_1_2:subtask2:inst_final:"
    )
    assert store_instruction["symbolic_operands"]["source_final_tile_ref"] == (
        "tile:dtensor_0003:processor_1_2:Y:128:256"
    )
    store_asm_dependency = program_asm["dependencies"][
        program_asm["edge_to_dependency"][incoming_store_edges[0]["id"]]
    ]
    assert store_asm_dependency["src_instruction"] == program_asm["node_to_instruction"][
        incoming_store_edges[0]["src_node"]
    ]
    assert store_asm_dependency["dst_instruction"] == store_instruction_id
    assert store_asm_dependency["scope"] == "cross_subtask_block"
    loop_carried_asm_dependency = program_asm["dependencies"][
        program_asm["edge_to_dependency"][loop_carried_edge_binding["edge_id"]]
    ]
    assert loop_carried_asm_dependency["legalized_edge_class"] == "loop_carried_edge"
    assert loop_carried_asm_dependency["vendor_graph_eligible"] is False
    assert loop_carried_asm_dependency["absorbed_by"] == "loop_carried_state"

    program_vendor_abi = plan["program_vendor_abi"]
    assert program_vendor_abi["source_ir"] == "program_asm"
    assert program_vendor_abi["totals"] == {
        "vendor_task_count": 4,
        "vendor_subtask_count": 12,
        "vendor_instance_count": 12,
        "vendor_exeblock_count": 256,
        "instruction_range_count": 256,
        "vendor_graph_edge_count": 112,
        "repeated_loop_template_count": 64,
        "assigned_instruction_count": 256,
        "pe_instruction_image_count": 16,
        "stage_counts": {
            "CAL": 128,
            "FLOW": 48,
            "LD": 16,
            "ST": 64,
        },
        "exeblock_role_counts": {
            "accumulator_prepare": 64,
            "finalize_store": 64,
            "k_stream": 128,
        },
        "edge_scope_counts": {
            "cross_processor_block": 80,
            "same_instance_cross_block": 32,
        },
        "predecessor_overflow_count": 0,
        "successor_overflow_count": 0,
    }
    assert program_vendor_abi["validation"] == {
        "all_vendor_emitted_asm_blocks_have_exeblocks": True,
        "all_vendor_emitted_asm_instructions_have_ranges": True,
        "all_graph_edges_have_known_exeblocks": True,
        "all_repeated_loop_templates_are_emit_vendor_rows": True,
        "k_stream_subtasks_use_folded_repeat": True,
        "binary_emitted": False,
    }
    folded_report = program_vendor_abi["folded_vendor_report"]
    assert folded_report == {
        "folded_repeat_mode": "emit_vendor_rows",
        "folded_repeat_unit": "whole_subtask_body",
        "expanded_asm_block_count": 896,
        "expanded_k_stream_block_count": 768,
        "expanded_finalize_store_block_count": 64,
        "folded_vendor_exeblock_count": 256,
        "folded_k_stream_exeblock_count": 128,
        "folded_finalize_store_exeblock_count": 64,
        "expanded_symbolic_instruction_count": 896,
        "folded_symbolic_instruction_count": 256,
        "symbolic_instruction_semantics": (
            "ProgramAsm instruction_count is symbolic ProgramNode-level rows;"
            "not final expanded inst_t count"
        ),
        "expanded_asm_dependency_count": 1216,
        "expanded_vendor_graph_eligible_dependency_count": 1024,
        "emitted_vendor_graph_dependency_count_before_dedup": 112,
        "folded_vendor_graph_edge_count": 112,
        "deduplicated_vendor_graph_edge_count": 0,
        "template_internal_edge_count": 512,
        "emitted_template_internal_edge_count": 64,
        "normal_vendor_graph_edge_count": 48,
        "loop_carried_edge_count": 192,
        "absorbed_loop_carried_edges": 192,
        "loop_exit_edge_count": 128,
        "absorbed_cross_subtask_store_edges": 128,
        "debug_expanded_edge_count": 784,
        "asm_dependency_class_counts": {
            "internal_template_edge": 512,
            "loop_carried_edge": 192,
            "normal_graph_edge": 512,
        },
        "asm_dependency_scope_counts": {
            "cross_processor_block": 640,
            "cross_subtask_block": 128,
            "same_container_cross_block": 192,
            "same_instance_cross_block": 256,
        },
        "vendor_graph_edge_scope_counts": {
            "cross_processor_block": 80,
            "same_instance_cross_block": 32,
        },
        "symbolic_vendor_instance_row_count": 12,
        "vendor_instance_count_semantics": (
            "counts symbolic VendorInstanceRow records;"
            "effective repeated executions are represented by VendorSubtaskRow.instances_amount"
        ),
        "effective_k_stream_repeated_execution_count": 16,
        "variant_binding_status": "symbolic_only_not_binary_bound",
        "variant_binding_required_before_binary": [
            "spm_addr_offset",
            "base_addr_row_selection",
            "route_bundle_id",
            "visibility_ref_id",
            "symbolic_immediate_fields",
        ],
    }
    vendor_repeated_template = program_vendor_abi["repeated_loop_templates"][
        repeated_template_id
    ]
    assert vendor_repeated_template["body_micro_block_ids"] == (
        repeated_template["body_micro_block_ids"]
    )
    assert vendor_repeated_template["attrs"] == {
        **repeated_template["attrs"],
        "source_folded_repeat_mode": "metadata_only",
        "folded_repeat_mode": "emit_vendor_rows",
        "folded_repeat_unit": "whole_subtask_body",
        "vendor_row_facing": True,
    }
    assert program_vendor_abi["vendor_tasks"]["task0"]["active_subtask_ids"] == [
        "task0:vendor_subtask0",
        "task0:vendor_subtask1",
        "task0:vendor_subtask2",
    ]
    assert program_vendor_abi["vendor_tasks"]["task0"]["valid_exeblock_count"] == 64
    assert program_vendor_abi["vendor_tasks"]["task0"]["instance_count"] == 3
    prepare_vendor_subtask = program_vendor_abi["vendor_subtasks"][
        "task0:vendor_subtask0"
    ]
    assert prepare_vendor_subtask["role"] == "accumulator_prepare"
    assert prepare_vendor_subtask["instance_keys"] == ["prepare"]
    assert prepare_vendor_subtask["instances_amount"] == 1
    assert prepare_vendor_subtask["valid_exe_blocks"] == 16
    assert prepare_vendor_subtask["repeat_mode"] == "single_pass"
    k_stream_vendor_subtask = program_vendor_abi["vendor_subtasks"][
        "task0:vendor_subtask1"
    ]
    assert k_stream_vendor_subtask["instance_keys"] == ["k0", "k1", "k2", "k3"]
    assert k_stream_vendor_subtask["instances_amount"] == 4
    assert k_stream_vendor_subtask["valid_exe_blocks"] == 32
    assert k_stream_vendor_subtask["repeat_mode"] == "emit_vendor_rows"
    assert k_stream_vendor_subtask["repeat_semantics"] == (
        "vendor_instance_repeat_whole_subtask_body"
    )
    assert k_stream_vendor_subtask["template_instance_key"] == "k0"
    assert k_stream_vendor_subtask["folded_from_instance_keys"] == [
        "k0",
        "k1",
        "k2",
        "k3",
    ]
    assert program_vendor_abi["vendor_subtasks"]["task0:vendor_subtask2"][
        "instance_keys"
    ] == ["final"]
    assert program_vendor_abi["vendor_subtasks"]["task0:vendor_subtask2"][
        "repeat_mode"
    ] == "single_pass"
    compute_exeblock_id = program_vendor_abi["asm_block_to_exeblock"][
        compute_instruction["asm_block_id"]
    ]
    compute_exeblock = program_vendor_abi["vendor_exeblocks"][compute_exeblock_id]
    assert compute_exeblock["pe"] == "PE12"
    assert compute_exeblock["pe_pos"] == [1, 2, 0]
    assert compute_micro_block_id in compute_exeblock["source_tile_micro_block_ids"]
    assert "compute_update" in compute_exeblock["source_tile_micro_block_kinds"]
    assert compute_exeblock["ld_stage_inst_amount"] == 0
    assert compute_exeblock["cal_stage_inst_amount"] == 1
    assert compute_exeblock["instruction_count"] == 1
    assert program_vendor_abi["asm_instruction_to_range"][compute_instruction_id] in (
        compute_exeblock["instruction_range_ids"]
    )
    second_compute_node_id = program_nodes["action_to_node"][
        second_update["tile_compute_action_id"]
    ]
    second_compute_instruction_id = program_asm["node_to_instruction"][second_compute_node_id]
    second_compute_asm_block_id = program_asm["instructions"][second_compute_instruction_id][
        "asm_block_id"
    ]
    assert second_compute_asm_block_id not in program_vendor_abi["asm_block_to_exeblock"]
    store_exeblock_id = program_vendor_abi["asm_block_to_exeblock"][
        store_instruction["asm_block_id"]
    ]
    store_exeblock = program_vendor_abi["vendor_exeblocks"][store_exeblock_id]
    assert store_exeblock["role"] == "finalize_store"
    assert "tile_store" in store_exeblock["source_tile_micro_block_kinds"]
    assert store_exeblock["st_stage_inst_amount"] == 1

    program_bin_rows = plan["program_bin_rows"]
    assert program_bin_rows["source_ir"] == "program_vendor_abi"
    assert program_bin_rows["task_successor_policy"] == "independent_start_end"
    assert program_bin_rows["instances_conf_mem_based_addr_unit"] == "bytes"
    assert program_bin_rows["binary_policy"] == {
        "schema_version": "binary_policy.v1",
        "component_bytes_emitted": False,
        "complete_runtime_package_emitted": False,
        "program_bin_role": "row_planning_only",
        "vendor_inst_modes": ["native_symbolic"],
        "native_symbolic_semantics": "structural_smoke_only",
    }
    assert program_bin_rows["compat_diagnostics"] == {
        "schema_version": "compat_diagnostics.v1",
        "legacy_gemm_compat_semantics": (
            "real_vendor_inst_t_encoding_runtime_validation_blocked"
        ),
        "legacy_template_compat_semantics": (
            "real_vendor_inst_t_encoding_without_gemm_resource_replay"
        ),
    }
    assert program_bin_rows["totals"] == {
        "bin_component_count": 0,
        "effective_k_stream_repeated_execution_count": 16,
        "effective_subtask_instance_count": 24,
        "exe_block_bin_row_count": 256,
        "full_emission_blocked": True,
        "inst_bin_row_count": 256,
        "instance_conf_bin_row_count": 65536,
        "instruction_layout_row_count": 256,
        "source_repeated_loop_template_count": 64,
        "source_vendor_exeblock_count": 256,
        "source_vendor_graph_edge_count": 112,
        "source_vendor_instance_count": 12,
        "source_vendor_instruction_range_count": 256,
        "source_vendor_subtask_count": 12,
        "source_vendor_task_count": 4,
        "subtask_conf_bin_row_count": 12,
        "task_conf_bin_row_count": 4,
        "variant_binding_count": 512,
    }
    assert program_bin_rows["validation"] == {
        "folded_vendor_report_consumed": True,
        "folded_abi_contract_ready": True,
        "variant_binding_ready": False,
        "address_variant_binding_ready": True,
        "instance_conf_rows_ready": True,
        "task_conf_rows_ready": True,
        "exe_block_conf_rows_ready": True,
        "subtask_conf_rows_ready": True,
        "embedded_exe_block_rows_consistent": True,
        "instruction_layout_ready": True,
        "instance_conf_address_unit_is_bytes": True,
        "task_successor_policy_explicit": True,
        "full_component_emission_allowed": False,
        "binary_components_emitted": False,
        "complete_runtime_package_emitted": False,
        "blocking_reasons": [
            "variant_binding_symbolic_only_not_binary_bound",
            "route_visibility_variant_binding_not_started",
            "component_serializers_not_started",
        ],
    }
    assert program_bin_rows["variant_binding_report"] == {
        "binding_count": 512,
        "operand_role_counts": {
            "A": 256,
            "B": 256,
        },
        "binding_target_kind_counts": {
            "instance_base_addr": 512,
        },
        "target_proof_status_counts": {
            "legacy_confirmed": 512,
        },
        "address_equation_count": 512,
        "address_equation_audit_status": (
            "legacy_base_addr_equations_symbolically_audited"
        ),
    }
    first_binding_id = (
        "variant_binding:"
        "repeated_loop_template_tile_loop_processor_0_0_processor_action_0032_wave0:"
        "k0:A"
    )
    first_binding = program_bin_rows["variant_bindings"][first_binding_id]
    assert first_binding["operand_role"] == "A"
    assert first_binding["instance_key"] == "k0"
    assert first_binding["source_tile_refs"] == ["tile:dtensor_0000:A:0:0"]
    assert first_binding["binding_target_kind"] == "instance_base_addr"
    assert first_binding["target_proof_status"] == "legacy_confirmed"
    assert first_binding["base_addr_slot_bindings"] == {
        "0": "0x00000 + k_index*0x20 = 0x00000",
    }
    assert first_binding["immediate_bindings"] == {
        "word_offset": "m_start*0x80 = 0x00000",
    }
    assert first_binding["logical_address_expr"] == "A[k0, m_start=0]"
    assert first_binding["effective_address_expr"] == (
        "4 * (base_addr_word[0]=0x00000 + k_index*0x20 = 0x00000 + "
        "imm_word_offset=m_start*0x80 = 0x00000) = 0x00000000 bytes"
    )
    assert first_binding["binary_bound"] is True
    k3_b_binding = program_bin_rows["variant_bindings"][
        "variant_binding:"
        "repeated_loop_template_tile_loop_processor_0_0_processor_action_0032_wave0:"
        "k3:B"
    ]
    assert k3_b_binding["source_tile_refs"] == ["tile:dtensor_0001:B:192:0"]
    assert k3_b_binding["base_addr_slot_bindings"] == {
        "1": "0x10000 + k_index*0x4000 = 0x1c000",
    }
    assert k3_b_binding["effective_address_expr"].endswith("= 0x00070000 bytes")
    assert program_bin_rows["instance_conf_report"] == {
        "row_count": 65536,
        "physical_instance_row_count": 65536,
        "semantic_active_instance_row_count": 24,
        "role_filled_window_row_count": 24576,
        "nonsemantic_role_filled_window_row_count": 24552,
        "inactive_filler_row_count": 40960,
        "row_kind_counts": {
            "inactive_filler": 40960,
            "role_filled_window": 24552,
            "semantic_active": 24,
        },
        "legacy_fixed_window_layout": True,
        "record_size_bytes": 32,
        "capacity": 65536,
        "padded_component_size_bytes": 2097152,
        "instances_conf_mem_based_addr_unit": "bytes",
        "unused_slot_sentinel": "0xffffffff",
        "filled_slot_counts": {
            "0": 24576,
            "1": 8192,
        },
        "component_bytes_emitted": False,
    }
    first_instance_row = program_bin_rows["instance_rows"][
        "instance_conf:task0:vendor_subtask1:k0"
    ]
    assert first_instance_row["global_row_index"] == 2048
    assert first_instance_row["component_byte_offset"] == 65536
    assert first_instance_row["record_size_bytes"] == 32
    assert first_instance_row["physical_task_index"] == 0
    assert first_instance_row["physical_subtask_slot_index"] == 1
    assert first_instance_row["physical_instance_slot_index"] == 0
    assert first_instance_row["row_kind"] == "semantic_active"
    assert first_instance_row["is_semantic_active"] is True
    assert first_instance_row["semantic_row_index"] == 1
    assert first_instance_row["semantic_component_byte_offset"] == 32
    assert first_instance_row["base_addr_words"] == [
        0,
        0x10000,
        0xFFFFFFFF,
        0xFFFFFFFF,
    ]
    assert first_instance_row["base_addr_words_hex"] == [
        "0x00000000",
        "0x00010000",
        "0xffffffff",
        "0xffffffff",
    ]
    assert first_instance_row["source_binding_count"] == 32
    assert first_binding_id in first_instance_row["source_binding_ids"]
    k3_instance_row = program_bin_rows["instance_rows"][
        "instance_conf:task0:vendor_subtask1:k3"
    ]
    assert k3_instance_row["global_row_index"] == 2051
    assert k3_instance_row["component_byte_offset"] == 65632
    assert k3_instance_row["base_addr_words"] == [
        0x60,
        0x1C000,
        0xFFFFFFFF,
        0xFFFFFFFF,
    ]
    finalize_instance_row = program_bin_rows["instance_rows"][
        "instance_conf:task0:vendor_subtask2:final"
    ]
    assert finalize_instance_row["global_row_index"] == 4096
    assert finalize_instance_row["component_byte_offset"] == 131072
    assert finalize_instance_row["base_addr_words"] == [
        0x20000,
        0xFFFFFFFF,
        0xFFFFFFFF,
        0xFFFFFFFF,
    ]
    assert finalize_instance_row["semantic_row_index"] == 5
    assert finalize_instance_row["semantic_component_byte_offset"] == 160
    assert finalize_instance_row["source_binding_ids"] == []
    assert finalize_instance_row["source_vendor_instance_ids"] == ["vinst:task0:s2:i0"]
    assert program_bin_rows["task_conf_report"] == {
        "row_count": 4,
        "record_size_bytes": 120,
        "capacity": 4,
        "padded_component_size_bytes": 480,
        "task_successor_policy": "independent_start_end",
        "start_task_count": 4,
        "end_task_count": 4,
        "successor_edge_count": 0,
        "subtask_slot_count": 8,
        "successor_slot_count": 4,
        "component_bytes_emitted": False,
    }
    task0_row = program_bin_rows["task_rows"]["task_conf:task0"]
    assert task0_row["global_row_index"] == 0
    assert task0_row["component_byte_offset"] == 0
    assert task0_row["record_size_bytes"] == 120
    assert task0_row["task_index"] == 0
    assert task0_row["is_exe_start"] is True
    assert task0_row["is_exe_end"] is True
    assert task0_row["execute_times"] == 1
    assert task0_row["active_subtask_ids"] == [
        "task0:vendor_subtask0",
        "task0:vendor_subtask1",
        "task0:vendor_subtask2",
    ]
    assert task0_row["active_subtask_indices"] == [0, 1, 2]
    assert task0_row["subtasks_idx_slots"] == [
        0,
        1,
        2,
        0,
        0,
        0,
        0,
        0,
    ]
    assert task0_row["successor_task_indices"] == []
    assert task0_row["suc_tasks_slots"] == [
        0,
        0,
        0,
        0,
    ]
    assert task0_row["task_successor_policy"] == "independent_start_end"
    task1_row = program_bin_rows["task_rows"]["task_conf:task1"]
    assert task1_row["active_subtask_indices"] == [0, 1, 2]
    assert task1_row["subtasks_idx_slots"] == [0, 1, 2, 0, 0, 0, 0, 0]
    assert task1_row["suc_tasks_slots"] == [0, 0, 0, 0]
    assert program_bin_rows["exe_block_conf_report"] == {
        "row_count": 256,
        "record_size_bytes": 520,
        "capacity": 512,
        "padded_component_size_bytes": 266240,
        "role_counts": {
            "accumulator_prepare": 64,
            "finalize_store": 64,
            "k_stream": 128,
        },
        "stage_instruction_counts": {
            "CAL": 128,
            "FLOW": 48,
            "LD": 16,
            "ST": 64,
        },
        "edge_slot_count": 4,
        "max_predecessor_count": 1,
        "max_successor_count": 2,
        "component_bytes_emitted": False,
    }
    compute_exeblock_row = program_bin_rows["exe_block_rows"][
        f"exeblock_conf:{compute_exeblock_id}"
    ]
    assert compute_exeblock_row["vendor_exeblock_id"] == compute_exeblock_id
    assert compute_exeblock_row["source_asm_block_id"] == compute_instruction[
        "asm_block_id"
    ]
    assert compute_exeblock_row["role"] == "k_stream"
    assert compute_exeblock_row["processor"] == "processor_1_2"
    assert compute_exeblock_row["pe"] == "PE12"
    assert compute_exeblock_row["instance_key"] == "k0"
    assert compute_exeblock_row["source_tile_micro_block_kinds"] == ["compute_update"]
    assert compute_exeblock_row["instruction_ids"] == [compute_instruction_id]
    assert compute_exeblock_row["cal_stage_inst_amount"] == 1
    assert compute_exeblock_row["ld_stage_inst_amount"] == 0
    assert compute_exeblock_row["st_stage_inst_amount"] == 0
    assert compute_exeblock_row["req_activations"] == 1
    assert compute_exeblock_row["child_amount"] == 0
    assert len(compute_exeblock_row["predecessor_slots"]) == 4
    assert len(compute_exeblock_row["successor_slots"]) == 4
    assert compute_exeblock_row["successor_slots"] == [
        "__unused__",
        "__unused__",
        "__unused__",
        "__unused__",
    ]
    assert compute_exeblock_row["record_size_bytes"] == 520
    store_exeblock_row = program_bin_rows["exe_block_rows"][
        f"exeblock_conf:{store_exeblock_id}"
    ]
    assert store_exeblock_row["role"] == "finalize_store"
    assert store_exeblock_row["source_tile_micro_block_kinds"] == ["tile_store"]
    assert store_exeblock_row["instruction_ids"] == [store_instruction_id]
    assert store_exeblock_row["st_stage_inst_amount"] == 1
    assert store_exeblock_row["req_activations"] == 0
    assert store_exeblock_row["child_amount"] == 0
    assert program_bin_rows["subtask_conf_report"] == {
        "row_count": 12,
        "record_size_bytes": 266328,
        "capacity": 32,
        "padded_component_size_bytes": 8522496,
        "embedded_exe_block_slot_count": 512,
        "role_counts": {
            "accumulator_prepare": 4,
            "finalize_store": 4,
            "k_stream": 4,
        },
        "valid_exe_blocks_total": 256,
        "max_valid_exe_blocks": 32,
        "embedded_exe_block_source": "ProgramBinRows.exe_block_rows",
        "component_bytes_emitted": False,
    }
    prepare_subtask_row = program_bin_rows["subtask_rows"][
        "subtask_conf:task0:vendor_subtask0"
    ]
    assert prepare_subtask_row["global_row_index"] == 0
    assert prepare_subtask_row["component_byte_offset"] == 0
    assert prepare_subtask_row["record_size_bytes"] == 266328
    assert prepare_subtask_row["role"] == "accumulator_prepare"
    assert prepare_subtask_row["is_exe_start"] is True
    assert prepare_subtask_row["is_exe_end"] is False
    assert prepare_subtask_row["instances_amount"] == 1
    assert prepare_subtask_row["instances_conf_mem_based_addr"] == 0
    assert prepare_subtask_row["instance_conf_row_ids"] == [
        "instance_conf:task0:vendor_subtask0:prepare",
    ]
    assert prepare_subtask_row["valid_exe_blocks"] == 16
    assert prepare_subtask_row["repeat_mode"] == "single_pass"
    assert prepare_subtask_row["repeat_semantics"] is None

    k_stream_subtask_row = program_bin_rows["subtask_rows"][
        "subtask_conf:task0:vendor_subtask1"
    ]
    assert k_stream_subtask_row["global_row_index"] == 1
    assert k_stream_subtask_row["component_byte_offset"] == 266328
    assert k_stream_subtask_row["record_size_bytes"] == 266328
    assert k_stream_subtask_row["role"] == "k_stream"
    assert k_stream_subtask_row["is_exe_start"] is False
    assert k_stream_subtask_row["is_exe_end"] is False
    assert k_stream_subtask_row["instances_amount"] == 4
    assert k_stream_subtask_row["instances_conf_mem_based_addr"] == 32
    assert k_stream_subtask_row["instance_conf_row_ids"] == [
        "instance_conf:task0:vendor_subtask1:k0",
        "instance_conf:task0:vendor_subtask1:k1",
        "instance_conf:task0:vendor_subtask1:k2",
        "instance_conf:task0:vendor_subtask1:k3",
    ]
    assert k_stream_subtask_row["valid_exe_blocks"] == 32
    assert k_stream_subtask_row["repeat_mode"] == "emit_vendor_rows"
    assert k_stream_subtask_row["repeat_semantics"] == (
        "vendor_instance_repeat_whole_subtask_body"
    )
    assert k_stream_subtask_row["template_instance_key"] == "k0"
    assert len(k_stream_subtask_row["embedded_exe_block_slots"]) == 512
    assert k_stream_subtask_row["embedded_exe_block_slots"][:3] == (
        k_stream_subtask_row["embedded_exe_block_row_ids"][:3]
    )
    assert k_stream_subtask_row["embedded_exe_block_slots"][32] == "__unused__"
    assert compute_exeblock_row["id"] in k_stream_subtask_row[
        "embedded_exe_block_row_ids"
    ]
    finalize_subtask_row = program_bin_rows["subtask_rows"][
        "subtask_conf:task0:vendor_subtask2"
    ]
    assert finalize_subtask_row["global_row_index"] == 2
    assert finalize_subtask_row["component_byte_offset"] == 532656
    assert finalize_subtask_row["role"] == "finalize_store"
    assert finalize_subtask_row["is_exe_start"] is False
    assert finalize_subtask_row["is_exe_end"] is True
    assert finalize_subtask_row["instances_amount"] == 1
    assert finalize_subtask_row["instances_conf_mem_based_addr"] == 160
    assert finalize_subtask_row["instance_conf_row_ids"] == [
        "instance_conf:task0:vendor_subtask2:final",
    ]
    assert finalize_subtask_row["valid_exe_blocks"] == 16
    assert finalize_subtask_row["repeat_mode"] == "single_pass"
    assert finalize_subtask_row["repeat_semantics"] is None
    assert store_exeblock_row["id"] in finalize_subtask_row[
        "embedded_exe_block_row_ids"
    ]
    assert program_bin_rows["inst_conf_report"] == {
        "row_count": 256,
        "record_size_bytes": 304,
        "capacity": 69632,
        "padded_component_size_bytes": 21168128,
        "max_inst_amount_per_pe": 4352,
        "stage_counts": {
            "CAL": 128,
            "FLOW": 48,
            "LD": 16,
            "ST": 64,
        },
        "pe_instruction_counts": {
            "PE00": 20,
            "PE01": 16,
            "PE02": 16,
            "PE03": 12,
            "PE10": 20,
            "PE11": 16,
            "PE12": 16,
            "PE13": 12,
            "PE20": 20,
            "PE21": 16,
            "PE22": 16,
            "PE23": 12,
            "PE30": 20,
            "PE31": 16,
            "PE32": 16,
            "PE33": 12,
        },
        "vendor_inst_mode_counts": {
            "native_symbolic": 256,
        },
        "component_semantics_counts": {
            "structural_smoke_only": 256,
        },
        "functional_inst_row_count": 0,
        "functional_encoding": False,
        "component_bytes_emitted": False,
    }
    first_inst_row = program_bin_rows["inst_rows"]["inst:PE00:pc0000"]
    assert first_inst_row["source_instruction_id"] == "asm_inst:000000"
    assert first_inst_row["stage"] == "CAL"
    assert first_inst_row["opcode_name"] == "OP_GINST"
    assert first_inst_row["opcode_value"] == 0xC1
    assert first_inst_row["unit_inst_type"] == 0x40
    assert first_inst_row["latency"] == 1
    assert first_inst_row["block_idx"] == 0
    assert first_inst_row["end_inst"] is True
    assert first_inst_row["imms"] == [2, 0, 0]
    assert first_inst_row["extra_fields"] == [0, 0, 0]
    assert first_inst_row["functional_encoding"] is False
    assert program_bin_rows["folded_vendor_report"] == folded_report
    assert len(program_bin_rows["instruction_layout_rows"]) == 256
    first_instruction_layout = program_bin_rows["instruction_layout_rows"][
        "instruction_layout:000000"
    ]
    assert first_instruction_layout["vendor_inst_mode"] == "native_symbolic"
    assert first_instruction_layout["component_semantics"] == "structural_smoke_only"
    assert first_instruction_layout["complete_runtime_package_semantics"] is False
    assert first_instruction_layout["vendor_instruction_range_id"] == "vir:000000"
    assert program_bin_rows["reverse_map"][
        "instruction_layout_to_vendor_range"
    ]["instruction_layout:000000"] == "vir:000000"
    assert program_bin_rows["reverse_map"]["bin_row_to_vendor_row"][
        f"exeblock_conf:{compute_exeblock_id}"
    ] == compute_exeblock_id
    assert program_bin_rows["reverse_map"]["bin_row_to_vendor_row"][
        "subtask_conf:task0:vendor_subtask0"
    ] == "task0:vendor_subtask0"
    assert program_bin_rows["reverse_map"]["byte_row_reverse_map_complete"] is False

    program_bin_components = plan["program_bin_components"]
    assert program_bin_components["source_ir"] == "program_bin_rows"
    assert program_bin_components["serialization_policy"] == (
        "program_serializer_consumes_program_bin_rows_only;"
        "no_loop_route_dependency_or_tile_semantics_are_rederived"
    )
    assert program_bin_components["totals"] == {
        "component_count": 5,
        "total_size_bytes": 32054496,
        "active_row_count": 66064,
    }
    assert program_bin_components["validation"] == {
        "component_bytes_emitted": True,
        "package_bytes_emitted": True,
        "instance_conf_info_file_ready": True,
        "tasks_conf_info_file_ready": True,
        "exeblock_conf_info_file_ready": True,
        "subtasks_conf_info_file_ready": True,
        "insts_file_ready": True,
        "cbuf_file_ready": True,
        "micc_file_ready": True,
        "complete_runtime_package_semantics": "structural_smoke_only",
    }
    assert program_bin_components["package_totals"] == {
        "package_count": 2,
        "total_size_bytes": 32054496,
    }
    assert program_bin_components["packages"] == {
        "config/cbuf_file.bin": {
            "path": "config/cbuf_file.bin",
            "size_bytes": 23531520,
            "sha256": "368dcefac4079df86fa062a15cdab0f093f1f282daa6bd94bdac7d10f5ab0979",
            "source_component_paths": [
                "simulator_bin/insts_file.bin",
                "simulator_bin/exeblock_conf_info_file.bin",
                "simulator_bin/instance_conf_info_file.bin",
            ],
            "composer": "legacy_cbuf_layout:insts+exeblock_conf+instance_conf",
            "semantics": "native_symbolic_structural_smoke_only",
            "content_in_plan": False,
        },
        "config/micc_file.bin": {
            "path": "config/micc_file.bin",
            "size_bytes": 8522976,
            "sha256": "94a8113bb597a9d0bd83d37faebfa63245a937f7d59f3f7b9acd5c53d9aacd37",
            "source_component_paths": [
                "simulator_bin/tasks_conf_info_file.bin",
                "simulator_bin/subtasks_conf_info_file.bin",
            ],
            "composer": "legacy_micc_layout:tasks_conf+subtasks_conf",
            "semantics": "native_symbolic_structural_smoke_only",
            "content_in_plan": False,
        },
    }
    exeblock_component = program_bin_components["components"][
        "simulator_bin/exeblock_conf_info_file.bin"
    ]
    assert exeblock_component["path"] == "simulator_bin/exeblock_conf_info_file.bin"
    assert exeblock_component["size_bytes"] == 266240
    assert exeblock_component["sha256"] == (
        "3469c8f49d4acde801a34bf674ee25f96c34d97b13bd5db7d6841b81f4d40fbe"
    )
    assert exeblock_component["record_size_bytes"] == 520
    assert exeblock_component["capacity"] == 512
    assert exeblock_component["active_row_count"] == 256
    assert len(exeblock_component["source_row_ids"]) == 256
    assert exeblock_component["source_row_ids"][0].startswith(
        "exeblock_conf:veb:task0:PE00:subtask0:prepare:"
    )
    assert exeblock_component["source_row_ids"][-1].startswith(
        "exeblock_conf:veb:task3:PE33:subtask2:final:"
    )
    assert exeblock_component["serializer"] == (
        "legacy_struct:exeBlock_conf_info_t:v0_symbolic_edges_zeroed"
    )
    assert exeblock_component["content_in_plan"] is False
    subtask_component = program_bin_components["components"][
        "simulator_bin/subtasks_conf_info_file.bin"
    ]
    assert subtask_component["path"] == "simulator_bin/subtasks_conf_info_file.bin"
    assert subtask_component["size_bytes"] == 8522496
    assert subtask_component["sha256"] == (
        "2b19c212414d4e7616fc625e6c6312257f46fcc13287f910eef1ba6c2fe354ec"
    )
    assert subtask_component["record_size_bytes"] == 266328
    assert subtask_component["capacity"] == 32
    assert subtask_component["active_row_count"] == 12
    assert subtask_component["source_row_ids"] == [
        f"subtask_conf:task{task_index}:vendor_subtask{subtask_index}"
        for task_index in range(4)
        for subtask_index in range(3)
    ]
    assert subtask_component["serializer"] == (
        "legacy_struct:sub_task_conf_info_t:"
        "embedded_exeBlocks_conf_info_from_program_bin_rows"
    )
    assert subtask_component["content_in_plan"] is False
    insts_component = program_bin_components["components"][
        "simulator_bin/insts_file.bin"
    ]
    assert insts_component["path"] == "simulator_bin/insts_file.bin"
    assert insts_component["size_bytes"] == 21168128
    assert insts_component["sha256"] == (
        "6bfb35b484cea84d38771cf4ea510014357986d1d9f59d1596c266a7e52b8419"
    )
    assert insts_component["record_size_bytes"] == 304
    assert insts_component["capacity"] == 69632
    assert insts_component["active_row_count"] == 256
    assert insts_component["source_row_ids"][0] == "inst:PE00:pc0000"
    assert insts_component["source_row_ids"][-1] == "inst:PE33:pc0011"
    assert insts_component["serializer"] == (
        "legacy_struct:inst_t:native_symbolic_structural_smoke_only"
    )
    assert insts_component["content_in_plan"] is False
    instance_component = program_bin_components["components"][
        "simulator_bin/instance_conf_info_file.bin"
    ]
    assert instance_component["path"] == "simulator_bin/instance_conf_info_file.bin"
    assert instance_component["size_bytes"] == 2097152
    assert instance_component["sha256"] == (
        "3b9d70247acc9832d71d73ec88f044d5b083aea7f07a42c191e90fb994b19414"
    )
    assert instance_component["record_size_bytes"] == 32
    assert instance_component["capacity"] == 65536
    assert instance_component["active_row_count"] == 65536
    assert len(instance_component["source_row_ids"]) == 65536
    assert instance_component["serializer"] == "struct:<4Q"
    assert instance_component["content_in_plan"] is False
    assert instance_component["source_row_ids"][0] == (
        "instance_conf:task0:vendor_subtask0:prepare"
    )
    assert instance_component["source_row_ids"][2048] == (
        "instance_conf:task0:vendor_subtask1:k0"
    )
    assert instance_component["source_row_ids"][2051] == (
        "instance_conf:task0:vendor_subtask1:k3"
    )
    assert instance_component["source_row_ids"][4096] == (
        "instance_conf:task0:vendor_subtask2:final"
    )
    assert instance_component["source_row_ids"][6144] == (
        "instance_conf:task0:slot3:i0000"
    )
    task_component = program_bin_components["components"][
        "simulator_bin/tasks_conf_info_file.bin"
    ]
    assert task_component == {
        "path": "simulator_bin/tasks_conf_info_file.bin",
        "size_bytes": 480,
        "sha256": "2cb27a71c30553ee1c639225f235ca8a606a87a09d8b592ead0aea91985a5a0b",
        "record_size_bytes": 120,
        "capacity": 4,
        "active_row_count": 4,
        "source_row_ids": [
            "task_conf:task0",
            "task_conf:task1",
            "task_conf:task2",
            "task_conf:task3",
        ],
        "serializer": "struct:<BB6xQQ8Q4Q",
        "content_in_plan": False,
    }
    exeblock_bytes = (tmp_path / "simulator_bin/exeblock_conf_info_file.bin").read_bytes()
    assert len(exeblock_bytes) == 266240
    assert struct.unpack_from("<B7xQ3QQ", exeblock_bytes, 0) == (
        1,
        0,
        0,
        0,
        0,
        0,
    )
    assert struct.unpack_from("<Q", exeblock_bytes, 48) == (0,)
    assert struct.unpack_from("<5B", exeblock_bytes, 56) == (0, 1, 0, 0, 0)
    assert struct.unpack_from("<5Q", exeblock_bytes, 64) == (0, 0, 1, 1, 1)
    assert struct.unpack_from("<11Q", exeblock_bytes, 424) == (
        0,
        0,
        0,
        1,
        0,
        0,
        0,
        0,
        1,
        0,
        0,
    )
    assert struct.unpack_from("<B", exeblock_bytes, 520) == (1,)
    subtask_bytes = (tmp_path / "simulator_bin/subtasks_conf_info_file.bin").read_bytes()
    assert len(subtask_bytes) == 8522496
    assert struct.unpack_from("<BB6xQQ4QQQ", subtask_bytes, 0) == (
        1,
        0,
        1,
        0,
        1,
        0,
        0,
        0,
        16,
        16,
    )
    assert subtask_bytes[72 : 72 + 520] == exeblock_bytes[:520]
    assert struct.unpack_from("<QQ", subtask_bytes, 266312) == (0, 0)
    assert struct.unpack_from("<BB6xQQ4QQQ", subtask_bytes, 266328) == (
        0,
        0,
        4,
        32,
        2,
        0,
        0,
        0,
        4,
        32,
    )
    assert struct.unpack_from("<QQ", subtask_bytes, 266328 + 266312) == (1, 0)
    assert struct.unpack_from("<BB6xQQ4QQQ", subtask_bytes, 532656) == (
        0,
        1,
        1,
        160,
        0,
        0,
        0,
        0,
        16,
        16,
    )
    assert struct.unpack_from("<QQ", subtask_bytes, 532656 + 266312) == (2, 0)
    insts_bytes = (tmp_path / "simulator_bin/insts_file.bin").read_bytes()
    assert len(insts_bytes) == 21168128
    assert struct.unpack_from("<I4xQQ3Q", insts_bytes, 0) == (
        0xC1,
        0x40,
        1,
        2,
        0,
        0,
    )
    assert struct.unpack_from("<QQQ3Q", insts_bytes, 256) == (
        0,
        0,
        1,
        0,
        0,
        0,
    )
    instance_bytes = (tmp_path / "simulator_bin/instance_conf_info_file.bin").read_bytes()
    assert len(instance_bytes) == 2097152
    assert struct.unpack_from("<4Q", instance_bytes, 0) == (
        0x20000,
        0xFFFFFFFF,
        0xFFFFFFFF,
        0xFFFFFFFF,
    )
    assert struct.unpack_from("<4Q", instance_bytes, 32) == (
        0x20000,
        0xFFFFFFFF,
        0xFFFFFFFF,
        0xFFFFFFFF,
    )
    assert struct.unpack_from("<4Q", instance_bytes, 2048 * 32) == (
        0,
        0x10000,
        0xFFFFFFFF,
        0xFFFFFFFF,
    )
    assert struct.unpack_from("<4Q", instance_bytes, 2051 * 32) == (
        0x60,
        0x1C000,
        0xFFFFFFFF,
        0xFFFFFFFF,
    )
    assert struct.unpack_from("<4Q", instance_bytes, 4096 * 32) == (
        0x20000,
        0xFFFFFFFF,
        0xFFFFFFFF,
        0xFFFFFFFF,
    )
    assert struct.unpack_from("<4Q", instance_bytes, 6144 * 32) == (
        0xFFFFFFFF,
        0xFFFFFFFF,
        0xFFFFFFFF,
        0xFFFFFFFF,
    )
    task_bytes = (tmp_path / "simulator_bin/tasks_conf_info_file.bin").read_bytes()
    assert len(task_bytes) == 480
    assert struct.unpack_from("<BB6xQQ8Q4Q", task_bytes, 0) == (
        1,
        1,
        3,
        1,
        0,
        1,
        2,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )
    cbuf_bytes = (tmp_path / "config/cbuf_file.bin").read_bytes()
    micc_bytes = (tmp_path / "config/micc_file.bin").read_bytes()
    assert cbuf_bytes == exeblock_bytes[:0] + insts_bytes + exeblock_bytes + instance_bytes
    assert micc_bytes == task_bytes + subtask_bytes


def _local_value_for(
    local_values: dict[str, dict[str, object]],
    *,
    logical_tensor_id: str,
    processor: str,
) -> dict[str, object]:
    matches = [
        value
        for value in local_values.values()
        if value["logical_tensor_id"] == logical_tensor_id and value["processor"] == processor
    ]
    assert len(matches) == 1
    return matches[0]


def test_generic_tile_compute_actions_feed_store(tmp_path: Path) -> None:
    env = ChipEnv("add_chip_program")
    x_sram = env.sram_tensor("X", shape=(128, 128), dtype="float16", offset_bytes=0)
    z_sram = env.sram_tensor("Z", shape=(128, 128), dtype="float16", offset_bytes=0x10000)
    y_sram = env.sram_tensor(
        "Y",
        shape=(128, 128),
        dtype="float16",
        offset_bytes=0x20000,
        role="output",
    )

    x = env.load(x_sram, placements=[Shard(0), Shard(1)])
    z = env.load(z_sram, placements=[Shard(0), Shard(1)])
    y = add(x, z)
    env.store(y, y_sram)

    plan = env.generate(output_dir=tmp_path)
    tile_program = plan["processor_tile_program"]
    assert tile_program["vendor_task_projection"]["processor_task_plan"]["totals"] == {
        "assignment_count": 0,
        "launch_group_count": 0,
    }
    assert tile_program["totals"] == {
        "processor_count": 16,
        "phase_count": 32,
        "collective_bundle_count": 0,
        "tile_route_action_count": 0,
        "tile_compute_action_count": 16,
        "tile_store_action_count": 16,
        "tile_app_storage_action_count": 0,
        "app_storage_region_count": 0,
        "app_storage_edge_count": 0,
        "tile_visibility_ref_count": 0,
        "tile_micro_block_count": 32,
        "tile_block_dependency_count": 16,
        "action_to_micro_block_count": 32,
        "tile_loop_region_count": 0,
        "processor_tile_action_count": 32,
        "tile_dependency_count": 48,
        "output_count": 0,
    }

    processor_1_2 = plan["processor_logical_program"]["streams"]["processor_1_2"]
    add_action = next(action for action in processor_1_2["actions"] if action["op"] == "add")
    store_action = next(
        action for action in processor_1_2["actions"] if action["op"] == "store_sram_tensor"
    )
    tile_stream = tile_program["programs"]["processor_1_2"]
    assert tile_program["tile_loop_regions"] == {}
    assert [item["item_kind"] for item in tile_stream["program_sequence"]] == [
        "tile_phase",
        "tile_phase",
    ]
    compute_phase = tile_stream["phases"][0]
    store_phase = tile_stream["phases"][1]
    compute_action_id = compute_phase["payload"]["tile_compute_action_id"]
    store_action_id = store_phase["payload"]["tile_store_action_id"]

    compute_action = tile_program["tile_compute_actions"][compute_action_id]
    tile_store_action = tile_program["tile_store_actions"][store_action_id]
    assert compute_action["compute_kind"] == "add"
    assert compute_action["source_action"] == add_action["id"]
    assert compute_action["input_refs"] == add_action["inputs"]
    assert compute_action["output_refs"] == add_action["outputs"]
    assert tile_store_action["source_action"] == store_action["id"]
    assert tile_store_action["depends_on"] == [compute_action_id]


def test_legacy_csv_encoder_matches_vendor_gemm_template_shape() -> None:
    template = (
        ROOT
        / "simict3500final/gpdpu/users/risc_nn_riscv/testcase/build_out"
        / "gemm_template_fusion/worktree/gpdpu/users/risc_nn_riscv/testcase"
        / "application/gemm_template_fusion/task1/subtask2/template/0.csv"
    )

    insts = parse_legacy_csv_template(template)

    assert len(insts) == 64
    assert [inst.op_name for inst in insts[:4]] == ["LDN", "LDN", "LDN", "LDN"]
    assert [inst.imms[0] for inst in insts[:4]] == [16384, 16512, 16640, 16768]
    assert [inst.dst_pes_pos[0][0] for inst in insts[:4]] == [3, 3, 3, 3]
    assert insts[0].opcode == 0x40
    assert insts[0].unit_inst_type == 0x8
    assert insts[0].latency == 1
    assert insts[0].extra_fields == (0, 0, 2)

    packed = pack_legacy_inst(insts[0])
    fields = struct.unpack("<I4xQQ3Q3Q3Q9Q3Q3Q3QQ3B3B2xQQQ3Q", packed)
    assert len(packed) == 304
    assert fields[0] == 0x40
    assert fields[1] == 0x8
    assert fields[2] == 1
    assert fields[3:6] == (16384, 0, 0)
    assert fields[12:15] == (3, 0, 0)
    assert fields[40:43] == (0, 0, 2)


def test_legacy_csv_encoder_supports_current_gemm_op_set() -> None:
    template_root = (
        ROOT
        / "simict3500final/gpdpu/users/risc_nn_riscv/testcase/build_out"
        / "gemm_template_fusion/worktree/gpdpu/users/risc_nn_riscv/testcase"
        / "application/gemm_template_fusion"
    )

    total_insts = 0
    op_counts: dict[str, int] = {}
    for template in template_root.glob("task*/subtask*/template/*.csv"):
        for inst in parse_legacy_csv_template(template):
            total_insts += 1
            op_counts[inst.op_name] = op_counts.get(inst.op_name, 0) + 1

    assert total_insts == 53376
    assert op_counts == {
        "COPY": 3072,
        "HMMAL": 32768,
        "HMUL": 2048,
        "IMM": 128,
        "LDN": 9216,
        "RXINT": 1024,
        "STD": 4096,
        "TRCTT": 1024,
    }


def test_program_bin_does_not_own_legacy_template_selection() -> None:
    source = (ROOT / "compiler/gpdpu_compiler/core/program_bin.py").read_text()

    assert "legacy_gemm_micro_block_template" not in source
    assert "_LEGACY_TEMPLATE_CACHE" not in source
    assert "_legacy_inst_template_for_" not in source


def test_tile_micro_ops_and_dfu3500_template_bound_shadow_ir() -> None:
    env = ChipEnv("template_bound_shadow_ir")

    a_sram = env.sram_tensor_from_region("A", DFU3500_GEMM_REGIONS["A"])
    b_sram = env.sram_tensor_from_region("B", DFU3500_GEMM_REGIONS["B"])
    y_sram = env.sram_tensor_from_region("Y", DFU3500_GEMM_REGIONS["C"])

    a = env.load(a_sram, placements=[Shard(0), Replicate()])
    b = env.load(b_sram, placements=[Replicate(), Shard(1)])
    y = relu(a @ b)
    env.store(y, y_sram)

    generated = env.generate()
    micro_op_plan = generated["tile_micro_op_program"]
    assert micro_op_plan["totals"] == {
        "micro_op_count": 896,
        "source_micro_block_count": 896,
        "processor_count": 16,
        "role_counts": {
            "accumulator_prepare": 64,
            "compute_core": 256,
            "operand_materialize:A": 64,
            "operand_materialize:B": 64,
            "route_forward": 384,
            "tile_store": 64,
        },
        "source_micro_block_kind_counts": {
            "accumulator_prepare": 64,
            "compute_update": 256,
            "route_forward": 384,
            "route_source_materialize": 128,
            "tile_store": 64,
        },
    }
    assert micro_op_plan["validation"] == {
        "all_micro_ops_mapped_from_micro_blocks": True,
        "all_micro_blocks_have_micro_ops": True,
    }

    template_plan = generated["dfu3500_template_bound_program"]
    assert template_plan["totals"] == {
        "segment_count": 1216,
        "template_bound_instruction_count": 201856,
        "micro_op_count": 896,
        "unsupported_micro_op_count": 0,
        "stage_counts": {
            "CAL": 144512,
            "FLOW": 12288,
            "LD": 40960,
            "ST": 4096,
        },
        "legacy_op_counts": {
            "COPY": 12288,
            "HMMAL": 131072,
            "HMUL": 5120,
            "IMM": 128,
            "LDN": 40960,
            "RXINT": 4096,
            "STD": 4096,
            "TRCTT": 4096,
        },
        "role_instruction_counts": {
            "accumulator_prepare": 5248,
            "compute_core": 159744,
            "operand_materialize:A": 4096,
            "operand_materialize:B": 4096,
            "route_forward": 24576,
            "tile_store": 4096,
        },
    }
    assert template_plan["validation"] == {
        "all_instructions_owned_by_segments": True,
        "all_instructions_mapped_to_micro_ops": True,
        "all_micro_ops_have_template_bindings": True,
        "unsupported_micro_op_count": 0,
    }
    assert template_plan["layering_policy"] == (
        "dfu3500_template_bound_program_consumes_tile_micro_ops;"
        "owns_legacy_csv_template_selection_and_stage_attribution;"
        "program_bin_rows_must_not_rediscover_template_selection"
    )


def test_legacy_gemm_compat_mode_uses_vendor_inst_encoding(tmp_path: Path) -> None:
    env = ChipEnv("legacy_gemm_compat_program")

    a_region = DFU3500_GEMM_REGIONS["A"]
    b_region = DFU3500_GEMM_REGIONS["B"]
    y_region = DFU3500_GEMM_REGIONS["C"]
    a_sram = env.sram_tensor_from_region("A", a_region)
    b_sram = env.sram_tensor_from_region("B", b_region)
    y_sram = env.sram_tensor_from_region("Y", y_region)

    a = env.load(a_sram, placements=[Shard(0), Replicate()])
    b = env.load(b_sram, placements=[Replicate(), Shard(1)])
    y = relu(a @ b)
    env.store(y, y_sram)

    generated = env.generate(
        output_dir=tmp_path,
        vendor_inst_mode="legacy_gemm_compat",
    )
    row_plan = generated["program_bin_rows"]

    assert row_plan["totals"]["legacy_runtime_projection"] == (
        "full_vendor_task_set"
    )
    assert row_plan["totals"]["emitted_vendor_task_count"] == 4
    assert row_plan["totals"]["emitted_vendor_subtask_count"] == 12
    assert row_plan["totals"]["emitted_vendor_exeblock_count"] == 256
    assert row_plan["totals"]["task_conf_bin_row_count"] == 4
    assert row_plan["totals"]["subtask_conf_bin_row_count"] == 12
    assert row_plan["totals"]["inst_bin_row_count"] == 53376
    assert row_plan["totals"]["instruction_layout_row_count"] == 384
    assert row_plan["inst_conf_report"]["functional_inst_row_count"] == 53376
    assert row_plan["inst_conf_report"]["functional_encoding"] is True
    assert row_plan["inst_conf_report"]["vendor_inst_mode_counts"] == {
        "legacy_gemm_compat": 53376
    }
    assert max(row_plan["inst_conf_report"]["pe_instruction_counts"].values()) == 3592
    assert row_plan["inst_conf_report"]["stage_counts"] == {
        "CAL": 36992,
        "FLOW": 3072,
        "LD": 9216,
        "ST": 4096,
    }

    insts_bytes = (tmp_path / "simulator_bin/insts_file.bin").read_bytes()
    first_inst = struct.unpack_from(
        "<I4xQQ3Q3Q3Q9Q3Q3Q3QQ3B3B2xQQQ3Q",
        insts_bytes,
        0,
    )
    assert first_inst[0] == 0x40
    assert first_inst[1] == 0x8
    assert first_inst[2] == 1
    assert first_inst[37] == 0
    assert first_inst[39] == 0


def test_legacy_gemm_template_keeps_input0_strip15_in_input_bank() -> None:
    route = legacy_gemm_micro_block_template(
        "route_forward",
        task_index=0,
        template_index=10,
    )
    compute = legacy_gemm_micro_block_template(
        "compute_update",
        task_index=0,
        template_index=16,
    )
    accumulator = legacy_gemm_micro_block_template(
        "accumulator_prepare",
        task_index=1,
        template_index=0,
    )

    assert route[60].op_tag_name == "COPYT15"
    assert route[60].src_reg_idx0_tag == "gemm0_input0_0_15"
    assert route[60].dst_reg_idx_tag == "gemm0_input0_0_15"
    assert [inst.dst_operands_idx[0] for inst in route[60:64]] == [
        622,
        750,
        878,
        1006,
    ]

    assert compute[615].op_name == "HMMAL"
    assert compute[615].src_reg_idx0_tag == "gemm0_input0_0_15"
    assert compute[615].src_operands_idx[0] == 622

    assert accumulator[0].op_name == "LDN"
    assert accumulator[0].dst_operands_idx[0] == 111
    assert accumulator[67].op_name == "HMUL"
    assert accumulator[67].src_operands_idx == (110, 638, 0)

    task1_source = legacy_gemm_micro_block_template(
        "route_source_materialize",
        task_index=1,
        template_index=0,
    )
    assert task1_source[0].op_name == "LDN"
    assert task1_source[0].dst_operands_idx[0] == 621


def test_chip_env_generate_can_emit_legacy_gemm_compat_bundle(tmp_path: Path) -> None:
    env = ChipEnv("legacy_gemm_compat_bundle")

    a_sram = env.sram_tensor_from_region("A", DFU3500_GEMM_REGIONS["A"])
    b_sram = env.sram_tensor_from_region("B", DFU3500_GEMM_REGIONS["B"])
    y_sram = env.sram_tensor_from_region("Y", DFU3500_GEMM_REGIONS["C"])

    a = env.load(a_sram, placements=[Shard(0), Replicate()])
    b = env.load(b_sram, placements=[Replicate(), Shard(1)])
    y = relu(a @ b)
    env.store(y, y_sram)

    plan = env.generate(
        output_dir=tmp_path,
        vendor_inst_mode="legacy_gemm_compat",
    )

    assert plan["status"] == (
        "program_bin_package_legacy_gemm_compat_ready_runtime_validation_blocked"
    )
    assert plan["vendor_inst_mode"] == "legacy_gemm_compat"
    assert plan["program_bin_rows"]["totals"]["legacy_runtime_projection"] == (
        "full_vendor_task_set"
    )
    assert plan["program_bin_rows"]["totals"]["source_vendor_task_count"] == 4
    assert plan["program_bin_rows"]["totals"]["inst_bin_row_count"] == 53376
    assert plan["program_bin_rows"]["inst_conf_report"]["functional_encoding"] is True
    assert plan["program_bin_components"]["validation"][
        "complete_runtime_package_semantics"
    ] == "legacy_gemm_compat_real_inst_t_runtime_validation_blocked"
    assert plan["program_bin_components"]["packages"]["config/cbuf_file.bin"][
        "semantics"
    ] == "legacy_gemm_compat_real_inst_t_runtime_validation_blocked"

    insts_bytes = (tmp_path / "simulator_bin/insts_file.bin").read_bytes()
    legacy_inst_fmt = "<I4xQQ3Q3Q3Q9Q3Q3Q3QQ3B3B2xQQQ3Q"
    first_inst = struct.unpack_from(
        legacy_inst_fmt,
        insts_bytes,
        0,
    )
    assert first_inst[0] == 0x40
    assert first_inst[1] == 0x8
    assert first_inst[2] == 1

    # Regression locks for arch-13 CBUF byte-diff fixes.  The offsets are in
    # config/cbuf_file.bin's leading insts section, whose record size is 304B.
    # They intentionally assert both decoded fields and byte positions: decoded
    # fields explain the allocator semantics, byte offsets guard the artifact
    # diff used in the remote workflow.
    cbuf_bytes = (tmp_path / "config/cbuf_file.bin").read_bytes()
    task0_copyt15 = struct.unpack_from(legacy_inst_fmt, insts_bytes, 206 * 304)
    assert task0_copyt15[6] == 622
    assert task0_copyt15[9] == 622
    assert cbuf_bytes[0xF4D1] == 2
    assert cbuf_bytes[0xF4E9] == 2

    task1_bet_imm = struct.unpack_from(legacy_inst_fmt, insts_bytes, 963 * 304)
    assert task1_bet_imm[9] == 638
    assert cbuf_bytes[0x477D8] == 126
    assert cbuf_bytes[0x477D9] == 2

    task1_bet_hmul = struct.unpack_from(legacy_inst_fmt, insts_bytes, 964 * 304)
    assert task1_bet_hmul[6] == 111
    assert task1_bet_hmul[7] == 638
    assert task1_bet_hmul[9] == 111

    task1_input0_load = struct.unpack_from(legacy_inst_fmt, insts_bytes, 980 * 304)
    assert task1_input0_load[9] == 621
    assert cbuf_bytes[0x48C08] == 109
    assert cbuf_bytes[0x48C09] == 2
    assert (tmp_path / "config/cbuf_file.bin").is_file()
    assert (tmp_path / "config/micc_file.bin").is_file()


def test_legacy_gemm_compat_bundle_diff_against_vendor_build_out(tmp_path: Path) -> None:
    legacy_root = (
        ROOT
        / "simict3500final/gpdpu/users/risc_nn_riscv/testcase/build_out"
        / "gemm_template_fusion/worktree/gpdpu/users/risc_nn_riscv/testcase"
        / "application/gemm_template_fusion/simulator_bin"
    )
    env = ChipEnv("legacy_gemm_compat_diff")

    a_sram = env.sram_tensor_from_region("A", DFU3500_GEMM_REGIONS["A"])
    b_sram = env.sram_tensor_from_region("B", DFU3500_GEMM_REGIONS["B"])
    y_sram = env.sram_tensor_from_region("Y", DFU3500_GEMM_REGIONS["C"])

    a = env.load(a_sram, placements=[Shard(0), Replicate()])
    b = env.load(b_sram, placements=[Replicate(), Shard(1)])
    y = relu(a @ b)
    env.store(y, y_sram)
    env.generate(output_dir=tmp_path, vendor_inst_mode="legacy_gemm_compat")

    report = compare_simulator_bundles(
        legacy_root=legacy_root,
        candidate_root=tmp_path,
        top_n=4,
    )
    diff = report["diff"]

    assert diff["component_sizes"] == {
        "exeblocks": {
            "legacy": 266240,
            "candidate": 266240,
            "equal": True,
            "delta": 0,
        },
        "instances": {
            "legacy": 2097152,
            "candidate": 2097152,
            "equal": True,
            "delta": 0,
        },
        "insts": {
            "legacy": 21168128,
            "candidate": 21168128,
            "equal": True,
            "delta": 0,
        },
        "subtasks": {
            "legacy": 8522496,
            "candidate": 8522496,
            "equal": True,
            "delta": 0,
        },
        "tasks": {
            "legacy": 480,
            "candidate": 480,
            "equal": True,
            "delta": 0,
        },
    }
    assert diff["exeblocks"]["active_exeblock_count"] == {
        "legacy": 256,
        "candidate": 256,
        "delta": 0,
    }
    assert diff["inst"]["active_inst_count"] == {
        "legacy": 53376,
        "candidate": 53376,
        "delta": 0,
    }
    assert diff["inst"]["opcode_counts"]["HMMAL"] == {
        "legacy": 32768,
        "candidate": 32768,
        "equal": True,
        "delta": 0,
    }
    assert diff["inst"]["opcode_counts"]["STD"] == {
        "legacy": 4096,
        "candidate": 4096,
        "equal": True,
        "delta": 0,
    }
    assert diff["inst"]["opcode_counts"]["RXINT"] == {
        "legacy": 1024,
        "candidate": 1024,
        "equal": True,
        "delta": 0,
    }
    assert diff["inst"]["opcode_counts"]["TRCTT"] == {
        "legacy": 1024,
        "candidate": 1024,
        "equal": True,
        "delta": 0,
    }
    assert diff["inst"]["opcode_counts"]["COPY"] == {
        "legacy": 3072,
        "candidate": 3072,
        "equal": True,
        "delta": 0,
    }
    assert diff["inst"]["opcode_counts"]["LDN"] == {
        "legacy": 9216,
        "candidate": 9216,
        "equal": True,
        "delta": 0,
    }
    assert diff["inst"]["opcode_counts"]["HMUL"] == {
        "legacy": 2048,
        "candidate": 2048,
        "equal": True,
        "delta": 0,
    }
    assert diff["inst"]["opcode_counts"]["IMM"] == {
        "legacy": 128,
        "candidate": 128,
        "equal": True,
        "delta": 0,
    }
    assert diff["exeblocks"]["stage_instruction_counts"] == {
        "CAL": {
            "legacy": 36992,
            "candidate": 0,
            "equal": False,
            "delta": -36992,
        },
        "FLOW": {
            "legacy": 3072,
            "candidate": 0,
            "equal": False,
            "delta": -3072,
        },
        "LD": {
            "legacy": 9216,
            "candidate": 0,
            "equal": False,
            "delta": -9216,
        },
        "ST": {
            "legacy": 4096,
            "candidate": 0,
            "equal": False,
            "delta": -4096,
        },
    }
    assert diff["row_diff"]["tasks"]["matching_shared_row_count"] == 1
    assert diff["row_diff"]["tasks"]["mismatched_shared_row_count"] == 3
    assert diff["row_diff"]["subtasks"]["matching_shared_row_count"] == 0
    assert diff["row_diff"]["subtasks"]["mismatched_shared_row_count"] == 12
    assert diff["row_diff"]["subtasks"]["only_legacy_row_count"] == 0
    assert diff["row_diff"]["subtasks"]["only_candidate_row_count"] == 0


def test_legacy_gemm_task_resource_replay_regression_lock(tmp_path: Path) -> None:
    """Regression lock for the TaskResource replay pass output.

    This test captures the exact binary output after the
    ``replay_legacy_task_resource`` pass runs.  Any future change to the
    replay pass, seed tables, or operand allocation must keep these assertions
    passing or explicitly update them with an explanation.

    BET group fix (2026-06-16):
        BET moved from tensor group 2 to group 1 (vendor-compatible).
        cbuf sha256 = 5a3eeb32968bed14aac2f0bb4a99cf8f9be2b2fa4858f98957a6f88b3bb0597d
        micc sha256 = ab56e64bff6f0d9b469146ef04d4584c2597f4bcbb1b951d49c43601eb2a9980
    """
    import hashlib

    env = ChipEnv("task_resource_replay_regression")

    a_sram = env.sram_tensor_from_region("A", DFU3500_GEMM_REGIONS["A"])
    b_sram = env.sram_tensor_from_region("B", DFU3500_GEMM_REGIONS["B"])
    y_sram = env.sram_tensor_from_region("Y", DFU3500_GEMM_REGIONS["C"])

    a = env.load(a_sram, placements=[Shard(0), Replicate()])
    b = env.load(b_sram, placements=[Replicate(), Shard(1)])
    y = relu(a @ b)
    env.store(y, y_sram)

    env.generate(output_dir=tmp_path, vendor_inst_mode="legacy_gemm_compat")

    cbuf = (tmp_path / "config/cbuf_file.bin").read_bytes()
    micc = (tmp_path / "config/micc_file.bin").read_bytes()
    insts = (tmp_path / "simulator_bin/insts_file.bin").read_bytes()

    # --- Component sizes ---
    assert len(cbuf) == 23531520
    assert len(micc) == 8522976
    assert len(insts) == 21168128

    # --- SHA256 hashes ---
    assert hashlib.sha256(cbuf).hexdigest() == (
        "809a447dec84db46026c8ffc6dada8aff0b5644dc57362d88d8823e29c2e2506"
    )
    assert hashlib.sha256(micc).hexdigest() == (
        "ab56e64bff6f0d9b469146ef04d4584c2597f4bcbb1b951d49c43601eb2a9980"
    )

    # --- Operand index values at diff record positions ---
    legacy_inst_fmt = "<I4xQQ3Q3Q3Q9Q3Q3Q3QQ3B3B2xQQQ3Q"
    REC = 304

    def unpack_rec(rec_num: int) -> tuple:
        return struct.unpack_from(legacy_inst_fmt, insts, rec_num * REC)

    # COPY records (previously ±512 diff, now corrected by BET group fix)
    assert unpack_rec(8846)[9] == 622
    assert unpack_rec(8847)[9] == 750
    assert unpack_rec(8848)[9] == 878
    assert unpack_rec(8849)[9] == 1006

    assert unpack_rec(9680)[9] == 606
    assert unpack_rec(9681)[9] == 734

    assert unpack_rec(10454)[9] == 605
    assert unpack_rec(10455)[9] == 733

    assert unpack_rec(11349)[9] == 702
    assert unpack_rec(11350)[9] == 830

    # LDN records
    assert unpack_rec(13826)[9] == 111
    assert unpack_rec(13827)[9] == 239

    # HMMAL records
    assert unpack_rec(14295)[6] == 610
    assert unpack_rec(14299)[6] == 606

    # --- Known-good records ---
    assert unpack_rec(206)[6] == 622   # task0 COPYT15 src0
    assert unpack_rec(206)[9] == 622   # task0 COPYT15 dst0

    assert unpack_rec(963)[9] == 638   # task1 BET IMM dst0 (group 1)

    assert unpack_rec(964)[6] == 111   # task1 BET HMUL src0
    assert unpack_rec(964)[7] == 638   # task1 BET HMUL src1 (group 1)
    assert unpack_rec(964)[9] == 111   # task1 BET HMUL dst0

    assert unpack_rec(980)[9] == 621   # task1 input0 LDN dst0


def test_dfu3500_task_resource_state_matches_vendor_regular_layout() -> None:
    """Lock the source-derived non-REDUCE Task_Resource allocation rule."""

    resource = Dfu3500TaskResourceState(reg_start_idx=2)

    assert [layout_operand_idx(index) for index in range(6)] == [
        0,
        128,
        256,
        384,
        512,
        640,
    ]

    assert resource.get_reg_idx("a") == layout_operand_idx(2)
    assert resource.get_reg_idx("b") == layout_operand_idx(3)
    assert resource.get_reg_idx("a") == layout_operand_idx(2)
    assert resource.reg_idx_counter == 2


def test_dfu3500_task_resource_state_allocates_tensor_lanes_by_group() -> None:
    """Pseudo tensor operands allocate high-to-low bases inside a RAM group."""

    resource = Dfu3500TaskResourceState()

    base = resource.seed_tensor("gemm0_input0_0_15", 1)
    next_base = resource.seed_tensor("gemm0_input0_0_14", 1)

    assert base == 1 * 4 * OPERANDS_PER_OPERAND_RAM + 127
    assert next_base == 1 * 4 * OPERANDS_PER_OPERAND_RAM + 126
    assert resource.tensor_lane_operand(base, 0) == base
    assert resource.tensor_lane_operand(base, 3) == base + 3 * OPERANDS_PER_OPERAND_RAM


def test_dfu3500_task_resource_order_pool_matches_vendor_pe_pool() -> None:
    resource = Dfu3500TaskResourceState(allocation_mode="order_pool")
    resource.begin_stage()

    a = resource.get_reg_idx("a")
    b = resource.get_reg_idx("b")
    c = resource.get_reg_idx("c")

    assert (a, b, c) == (
        OPERANDS_PER_OPERAND_RAM - 1,
        2 * OPERANDS_PER_OPERAND_RAM - 1,
        3 * OPERANDS_PER_OPERAND_RAM - 1,
    )

    resource.finish_instruction((a, b, c))

    tensor = resource.seed_tensor("t", 1)
    assert tensor == 1 * 4 * OPERANDS_PER_OPERAND_RAM + 127


def test_dfu3500_task_resource_receiver_lookup_is_strict() -> None:
    """COPY/COPYT dst patching must consult the child/receiver resource."""

    sender = Dfu3500TaskResourceState()
    receiver = Dfu3500TaskResourceState()

    sender.seed_tensor("gemm0_input0_0_15", 1)
    receiver_base = receiver.seed_tensor("gemm0_input0_0_15", 0)

    assert sender.retrieve_reg_idx("gemm0_input0_0_15") != receiver_base
    assert receiver.retrieve_reg_idx("gemm0_input0_0_15") == receiver_base

    try:
        receiver.retrieve_reg_idx("missing")
    except KeyError as exc:
        assert "missing" in str(exc)
    else:  # pragma: no cover - defensive assertion for strict vendor semantics
        raise AssertionError("receiver lookup should fail for missing tags")


def test_dfu3500_task_resource_replay_is_opt_in() -> None:
    vendor_abi = ProgramVendorABI(
        chip="dfu3500",
        source_program="unit",
        source_ir="program_asm",
        processor_shape=(4, 4),
        vendor_tasks={},
        vendor_subtasks={},
        vendor_instances={},
        vendor_exeblocks={},
        instruction_ranges={},
        vendor_graph_edges={},
        asm_block_to_exeblock={},
        asm_instruction_to_range={},
        repeated_loop_templates={},
        folded_vendor_report={},
        pe_instruction_images={},
        template_bound_instructions={},
    )

    old_env = os.environ.pop(TASK_RESOURCE_REPLAY_ENV, None)
    try:
        assert replay_legacy_task_resource(vendor_abi) is vendor_abi

        os.environ[TASK_RESOURCE_REPLAY_ENV] = "1"
        replayed = replay_legacy_task_resource(vendor_abi)
        assert replayed is not vendor_abi
        assert replayed.folded_vendor_report["task_resource_replay"]["enabled"] is True
        assert (
            replayed.folded_vendor_report["task_resource_replay"][
                "copy_destination_pe_block_patched_by_serializer"
            ]
            is True
        )
    finally:
        if old_env is None:
            os.environ.pop(TASK_RESOURCE_REPLAY_ENV, None)
        else:
            os.environ[TASK_RESOURCE_REPLAY_ENV] = old_env
