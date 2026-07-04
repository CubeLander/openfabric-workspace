"""Small experimental GEMM stream-action demo.

This is a debug/prototyping helper for the new stream compiler line.  It is not
wired into the production DFU lowering path.
"""

from __future__ import annotations

from math import prod

from gpdpu_compiler.core.dfu3500 import DFU3500_DEFAULT_TILE, DFU3500_GEMM_REGIONS
from gpdpu_compiler.core.op_specs import MATMUL_SPEC

from .blocks import (
    FiberBlockProjection,
    probe_tile_micro_block_compat,
    project_fiber_to_blocks,
    summarize_fiber_block_projections,
    summarize_legacy_like_sequence,
    validate_fiber_block_projection,
)
from .binding import bind_executable_roles_symbolically, summarize_role_binding_program
from .dfu3500_semantics import (
    lower_template_records_to_dfu3500_semantics,
    summarize_dfu3500_semantic_report,
)
from .executable import lower_fibers_to_executable_ops, summarize_executable_program
from .fiber import (
    Fiber,
    FragmentVisibilityKind,
    build_atomic_gemm_fiber,
    build_expanded_gemm_bridge_fiber,
)
from .fiber_patterns import build_matmul_sequential_reduction_pattern
from .schedule import build_fiber_execution_schedule, summarize_fiber_execution_schedule
from .stream import StreamAction, StreamPlan, StreamValue
from .template_records import (
    lower_symbolic_bindings_to_template_records,
    summarize_template_record_program,
)


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def _shape(name: str) -> tuple[int, int]:
    shape = DFU3500_GEMM_REGIONS[name].shape
    if shape is None or len(shape) != 2:
        raise ValueError(f"expected rank-2 GEMM region shape for {name}")
    return shape


def _stream_matrix_attrs(
    *,
    tensor: str,
    global_shape: tuple[int, int],
    local_shape: tuple[int, int],
    global_offset: tuple[int, int],
    tile_axes: tuple[str, str],
    tile_shape: tuple[int, int],
) -> dict[str, object]:
    tile_counts = tuple(
        _ceil_div(local_dim, tile_dim)
        for local_dim, tile_dim in zip(local_shape, tile_shape, strict=True)
    )
    return {
        "tensor": tensor,
        "global_shape": global_shape,
        "local_shape": local_shape,
        "global_offset": global_offset,
        "tile_axes": tile_axes,
        "tile_shape": tile_shape,
        "tile_counts": tile_counts,
        "tile_count": prod(tile_counts),
    }


def _linear_work_index(
    coord: dict[str, int],
    shape: dict[str, int],
    axis_order: tuple[str, ...],
) -> int:
    index = 0
    stride = 1
    for axis in reversed(axis_order):
        index += int(coord[axis]) * stride
        stride *= int(shape[axis])
    return index


def _assigned_output_tile_coords(
    *,
    task_id: int,
    output_tile_counts: tuple[int, int],
    work_axis_order: tuple[str, ...] = ("m_tile", "n_tile"),
) -> tuple[dict[str, int], ...]:
    work_shape = {
        "m_tile": int(output_tile_counts[0]),
        "n_tile": int(output_tile_counts[1]),
    }
    all_coords = tuple(
        {"m_tile": m_tile, "n_tile": n_tile}
        for m_tile in range(work_shape["m_tile"])
        for n_tile in range(work_shape["n_tile"])
    )
    return tuple(
        coord
        for coord in all_coords
        if _linear_work_index(coord, work_shape, work_axis_order) == task_id
    )


def _parse_stream_id(stream_id: str) -> tuple[int, int, int]:
    task_text, pe_text = stream_id.split("_pe", 1)
    return int(task_text.removeprefix("t")), int(pe_text[0]), int(pe_text[1])


def build_demo_gemm_stream_plan(
    *,
    task_count: int = 4,
    mesh_shape: tuple[int, int] = (4, 4),
    include_relu: bool = True,
) -> StreamPlan:
    """Build a toy GEMM+ReLU+store stream plan.

    Policy used by this demo:
    - A is read by y=0 anchors and forwarded across each row.
    - B is read by x=0 anchors and forwarded down each column.
    - Each forward hop consumes the current stream-visible value, not the root
      source value.  This keeps the action wiring honest and local.
    """

    rows, cols = mesh_shape
    a_global_shape = _shape("A")
    b_global_shape = _shape("B")
    c_global_shape = _shape("C")
    a_local_shape = (a_global_shape[0] // rows, a_global_shape[1])
    b_local_shape = (b_global_shape[0], b_global_shape[1] // cols)
    c_local_shape = (c_global_shape[0] // rows, c_global_shape[1] // cols)
    k_tile = int(DFU3500_DEFAULT_TILE["matmul_k"])
    m_tile = int(DFU3500_DEFAULT_TILE["matmul_m"])
    n_tile = int(DFU3500_DEFAULT_TILE["matmul_n"])
    streams = [
        f"t{task}_pe{x}{y}"
        for task in range(task_count)
        for x in range(rows)
        for y in range(cols)
    ]
    plan = StreamPlan(app_id=0)
    counters = {"action": 0, "value": 0}

    def new_action_id(prefix: str) -> str:
        counters["action"] += 1
        return f"{prefix}_{counters['action']:04d}"

    def new_value_id(tensor: str, stream_id: str) -> str:
        counters["value"] += 1
        return f"v_{tensor}_{stream_id}_{counters['value']:04d}"

    def a_attrs(task: int, x: int, y: int) -> dict[str, object]:
        attrs = _stream_matrix_attrs(
            tensor="A",
            global_shape=a_global_shape,
            local_shape=a_local_shape,
            global_offset=(x * a_local_shape[0], 0),
            tile_axes=("m_tile", "reduction_fragment"),
            tile_shape=(m_tile, k_tile),
        )
        attrs.update({"role": "A", "task": task, "x": x, "y": y})
        return attrs

    def b_attrs(task: int, x: int, y: int) -> dict[str, object]:
        attrs = _stream_matrix_attrs(
            tensor="B",
            global_shape=b_global_shape,
            local_shape=b_local_shape,
            global_offset=(0, y * b_local_shape[1]),
            tile_axes=("reduction_fragment", "n_tile"),
            tile_shape=(k_tile, n_tile),
        )
        attrs.update({"role": "B", "task": task, "x": x, "y": y})
        return attrs

    def c_attrs(tensor: str, task: int, x: int, y: int) -> dict[str, object]:
        attrs = _stream_matrix_attrs(
            tensor=tensor,
            global_shape=c_global_shape,
            local_shape=c_local_shape,
            global_offset=(x * c_local_shape[0], y * c_local_shape[1]),
            tile_axes=("m_tile", "n_tile"),
            tile_shape=(m_tile, n_tile),
        )
        attrs.update({"role": tensor, "task": task, "x": x, "y": y})
        return attrs

    def append(
        stream_id: str,
        op: str,
        source_chip_op: str,
        *,
        inputs: tuple[str, ...] = (),
        outputs: tuple[str, ...] = (),
        depends_on: tuple[str, ...] = (),
        attrs: dict[str, object] | None = None,
    ) -> StreamAction:
        action = StreamAction(
            id=new_action_id(op),
            stream_id=stream_id,
            op=op,
            source_chip_op=source_chip_op,
            inputs=inputs,
            outputs=outputs,
            depends_on=depends_on,
            attrs=attrs or {},
        )
        plan.append_action(action)
        return action

    for task in range(task_count):
        for x in range(rows):
            source_stream = f"t{task}_pe{x}0"
            source_value_id = new_value_id("A", source_stream)
            read = append(
                source_stream,
                "sram_read_A",
                "chip_op_load_A",
                outputs=(source_value_id,),
                attrs={"tensor": "A", "role": "A", "task": task, "x": x, "y": 0},
            )
            current_stream = source_stream
            current_value_id = source_value_id
            current_action = read
            plan.set_visible_value(
                StreamValue(
                    current_value_id,
                    "A_dtensor",
                    current_stream,
                    "sram_read",
                    current_action.id,
                    a_attrs(task, x, 0),
                )
            )
            for y in range(1, cols):
                next_stream = f"t{task}_pe{x}{y}"
                push = append(
                    current_stream,
                    "route_push_A",
                    "chip_op_load_A",
                    inputs=(current_value_id,),
                    depends_on=(current_action.id,),
                    attrs={"tensor": "A", "dst": next_stream, "task": task},
                )
                next_value_id = new_value_id("A", next_stream)
                recv = append(
                    next_stream,
                    "route_recv_A",
                    "chip_op_load_A",
                    inputs=(current_value_id,),
                    outputs=(next_value_id,),
                    depends_on=(push.id,),
                    attrs={"tensor": "A", "src": current_stream, "task": task},
                )
                current_stream = next_stream
                current_value_id = next_value_id
                current_action = recv
                plan.set_visible_value(
                    StreamValue(
                        current_value_id,
                        "A_dtensor",
                        current_stream,
                        "route_recv",
                        current_action.id,
                        a_attrs(task, x, y),
                    )
                )

        for y in range(cols):
            source_stream = f"t{task}_pe0{y}"
            source_value_id = new_value_id("B", source_stream)
            read = append(
                source_stream,
                "sram_read_B",
                "chip_op_load_B",
                outputs=(source_value_id,),
                attrs={"tensor": "B", "role": "B", "task": task, "x": 0, "y": y},
            )
            current_stream = source_stream
            current_value_id = source_value_id
            current_action = read
            plan.set_visible_value(
                StreamValue(
                    current_value_id,
                    "B_dtensor",
                    current_stream,
                    "sram_read",
                    current_action.id,
                    b_attrs(task, 0, y),
                )
            )
            for x in range(1, rows):
                next_stream = f"t{task}_pe{x}{y}"
                push = append(
                    current_stream,
                    "route_push_B",
                    "chip_op_load_B",
                    inputs=(current_value_id,),
                    depends_on=(current_action.id,),
                    attrs={"tensor": "B", "dst": next_stream, "task": task},
                )
                next_value_id = new_value_id("B", next_stream)
                recv = append(
                    next_stream,
                    "route_recv_B",
                    "chip_op_load_B",
                    inputs=(current_value_id,),
                    outputs=(next_value_id,),
                    depends_on=(push.id,),
                    attrs={"tensor": "B", "src": current_stream, "task": task},
                )
                current_stream = next_stream
                current_value_id = next_value_id
                current_action = recv
                plan.set_visible_value(
                    StreamValue(
                        current_value_id,
                        "B_dtensor",
                        current_stream,
                        "route_recv",
                        current_action.id,
                        b_attrs(task, x, y),
                    )
                )

    for stream_id in streams:
        task = int(stream_id[1])
        x = int(stream_id[-2])
        y = int(stream_id[-1])
        a_value = plan.visible_value(stream_id=stream_id, logical_tensor_id="A_dtensor")
        b_value = plan.visible_value(stream_id=stream_id, logical_tensor_id="B_dtensor")
        c_value_id = new_value_id("C", stream_id)
        matmul = append(
            stream_id,
            "matmul",
            "chip_op_matmul",
            inputs=(a_value.id, b_value.id),
            outputs=(c_value_id,),
            depends_on=(a_value.producer_action_id or "", b_value.producer_action_id or ""),
            attrs={"lowering_hint": "dfu_summa_gemm"},
        )
        plan.set_visible_value(
            StreamValue(c_value_id, "C_dtensor", stream_id, "matmul", matmul.id, c_attrs("C", task, x, y))
        )

        if include_relu:
            y_value_id = new_value_id("Y", stream_id)
            relu = append(
                stream_id,
                "relu",
                "chip_op_relu",
                inputs=(c_value_id,),
                outputs=(y_value_id,),
                depends_on=(matmul.id,),
            )
            plan.set_visible_value(
                StreamValue(y_value_id, "Y_dtensor", stream_id, "relu", relu.id, c_attrs("Y", task, x, y))
            )
            store_input = y_value_id
            store_dependency = relu.id
            store_attrs = {"tensor": "Y", "profile": "gemm_relu_store"}
        else:
            store_input = c_value_id
            store_dependency = matmul.id
            store_attrs = {"tensor": "Y", "profile": "gemm_no_relu_store_c_as_y"}
        append(
            stream_id,
            "sram_store_Y",
            "chip_op_store_Y",
            inputs=(store_input,),
            depends_on=(store_dependency,),
            attrs=store_attrs,
        )

    return plan


def print_demo_streams(plan: StreamPlan, *, task: int = 0) -> None:
    print(
        "streams="
        f"{len(plan.streams)} actions={sum(len(actions) for actions in plan.streams.values())} "
        f"derived_edges={len(plan.dependency_edges())}"
    )
    print(f"\n=== task {task}, all streams ===")
    task_prefix = f"t{task}_"
    for stream_id in sorted(stream for stream in plan.streams if stream.startswith(task_prefix)):
        print(f"\n[{stream_id}]")
        for action in plan.streams[stream_id]:
            print(
                f"  {action.id:20s} {action.op:14s} "
                f"in={list(action.inputs)} out={list(action.outputs)} deps={list(action.depends_on)}"
            )


def print_demo_stream_matrix_shapes(plan: StreamPlan) -> None:
    tensors = ("A_dtensor", "B_dtensor", "C_dtensor", "Y_dtensor")
    print(
        "streams="
        f"{len(plan.streams)} actions={sum(len(actions) for actions in plan.streams.values())} "
        f"derived_edges={len(plan.dependency_edges())}"
    )
    print("\n=== per-stream matrix/tile shape signatures ===")
    for tensor in tensors:
        values = [
            value
            for (stream_id, logical_tensor_id), value in sorted(plan.visible_values.items())
            if logical_tensor_id == tensor
        ]
        tiles_per_stream = values[0].attrs["tile_count"] if values else "n/a"
        local_shapes = sorted({tuple(value.attrs["local_shape"]) for value in values})
        tile_counts = sorted({tuple(value.attrs["tile_counts"]) for value in values})
        offsets = sorted({tuple(value.attrs["global_offset"]) for value in values})
        print(
            f"{tensor:10s} streams={len(values):2d} "
            f"same_local_shape={len(local_shapes) == 1} local_shape={local_shapes} "
            f"tile_counts={tile_counts} tiles_per_stream={tiles_per_stream} "
            f"unique_offsets={len(offsets)}"
        )

    c_value = plan.visible_value(stream_id=sorted(plan.streams)[0], logical_tensor_id="C_dtensor")
    a_value = plan.visible_value(stream_id=sorted(plan.streams)[0], logical_tensor_id="A_dtensor")
    c_tile_counts = tuple(int(dim) for dim in c_value.attrs["tile_counts"])
    k_steps = int(a_value.attrs["tile_counts"][1])
    print(
        "\n=== GEMM stream-visible envelope vs task-assigned work ===\n"
        f"stream_visible_output_tiles={c_tile_counts[0] * c_tile_counts[1]} "
        f"k_steps={k_steps}\n"
        "TaskShard(gemm_output_tiles) filters the 2x2 local output tile envelope: "
        "each task owns one local C tile, so each soft stream has one fiber with "
        "4 K-update steps."
    )
    for task_id in range(4):
        assigned = _assigned_output_tile_coords(
            task_id=task_id,
            output_tile_counts=c_tile_counts,
        )
        k_update_count = len(assigned) * k_steps
        print(
            f"task{task_id}: assigned_output_tiles={list(assigned)} "
            f"assigned_tile_count={len(assigned)} k_updates={k_update_count}"
        )

    print(
        "\n=== per-stream matrix/tile shapes ===\n"
        "A/B/C/Y are stream-visible envelopes. assigned_C shows the local output "
        "tile(s) selected by the task axis before fiber planning."
    )
    for stream_id in sorted(plan.streams):
        task_id, _, _ = _parse_stream_id(stream_id)
        assigned = _assigned_output_tile_coords(
            task_id=task_id,
            output_tile_counts=c_tile_counts,
        )
        parts = []
        for tensor in tensors:
            value = plan.visible_value(stream_id=stream_id, logical_tensor_id=tensor)
            attrs = value.attrs
            parts.append(
                f"{tensor.removesuffix('_dtensor')}:"
                f"off={attrs['global_offset']} local={attrs['local_shape']} "
                f"tiles={attrs['tile_counts']}"
            )
        print(f"{stream_id:8s} assigned_C={list(assigned)} | " + " | ".join(parts))


def build_demo_fibers(
    plan: StreamPlan,
) -> tuple[Fiber, ...]:
    """Build B-line atomic fiber op sequences for current GEMM demo streams."""

    first_stream = sorted(plan.streams)[0]
    c_value = plan.visible_value(stream_id=first_stream, logical_tensor_id="C_dtensor")
    c_tile_counts = tuple(int(dim) for dim in c_value.attrs["tile_counts"])
    fibers: list[Fiber] = []

    def visibility_kind(value: StreamValue) -> FragmentVisibilityKind:
        if value.kind == "sram_read":
            return "sram_read"
        if value.kind == "route_recv":
            return "route_recv"
        raise ValueError(f"unsupported stream visibility kind for fiber lowering: {value.kind}")

    for stream_id in sorted(plan.streams):
        task_id, _, _ = _parse_stream_id(stream_id)
        a_stream_value = plan.visible_value(stream_id=stream_id, logical_tensor_id="A_dtensor")
        b_stream_value = plan.visible_value(stream_id=stream_id, logical_tensor_id="B_dtensor")
        for coord in _assigned_output_tile_coords(
            task_id=task_id,
            output_tile_counts=c_tile_counts,
        ):
            fibers.append(
                build_atomic_gemm_fiber(
                    stream_id=stream_id,
                    m_tile=int(coord["m_tile"]),
                    n_tile=int(coord["n_tile"]),
                    a_visibility_kind=visibility_kind(a_stream_value),
                    b_visibility_kind=visibility_kind(b_stream_value),
                    a_visibility_action_id=a_stream_value.producer_action_id,
                    b_visibility_action_id=b_stream_value.producer_action_id,
                )
            )
    return tuple(fibers)


def build_demo_expanded_gemm_bridge_fibers(
    plan: StreamPlan,
) -> tuple[Fiber, ...]:
    """Build the legacy expanded GEMM bridge fiber sequence.

    This path is intentionally separate from `build_demo_fibers`.  It is only
    for old debug/projection/binary work that has not yet moved GEMM expansion
    below the fiber layer.
    """

    first_stream = sorted(plan.streams)[0]
    c_value = plan.visible_value(stream_id=first_stream, logical_tensor_id="C_dtensor")
    a_value = plan.visible_value(stream_id=first_stream, logical_tensor_id="A_dtensor")
    c_tile_counts = tuple(int(dim) for dim in c_value.attrs["tile_counts"])
    k_steps = int(a_value.attrs["tile_counts"][1])
    fiber_pattern_plan = build_matmul_sequential_reduction_pattern()
    fibers: list[Fiber] = []

    def visibility_kind(value: StreamValue) -> FragmentVisibilityKind:
        if value.kind == "sram_read":
            return "sram_read"
        if value.kind == "route_recv":
            return "route_recv"
        raise ValueError(f"unsupported stream visibility kind for bridge lowering: {value.kind}")

    for stream_id in sorted(plan.streams):
        task_id, _, _ = _parse_stream_id(stream_id)
        a_stream_value = plan.visible_value(stream_id=stream_id, logical_tensor_id="A_dtensor")
        b_stream_value = plan.visible_value(stream_id=stream_id, logical_tensor_id="B_dtensor")
        for coord in _assigned_output_tile_coords(
            task_id=task_id,
            output_tile_counts=c_tile_counts,
        ):
            fibers.append(
                build_expanded_gemm_bridge_fiber(
                    stream_id=stream_id,
                    m_tile=int(coord["m_tile"]),
                    n_tile=int(coord["n_tile"]),
                    k_steps=k_steps,
                    a_visibility_kind=visibility_kind(a_stream_value),
                    b_visibility_kind=visibility_kind(b_stream_value),
                    a_visibility_action_id=a_stream_value.producer_action_id,
                    b_visibility_action_id=b_stream_value.producer_action_id,
                    fiber_pattern_plan=fiber_pattern_plan,
                )
            )
    return tuple(fibers)


def print_demo_fibers(plan: StreamPlan) -> None:
    fibers = build_demo_fibers(plan)
    print("\n=== flat fiber op sequence summary ===")
    print(f"fibers={len(fibers)}")
    strategies = sorted({fiber.attrs["strategy_id"] for fiber in fibers})
    print(f"strategies={strategies}")
    op_counts = sorted({len(fiber.ops) for fiber in fibers})
    print(f"ops_per_fiber={op_counts}")
    placement_roles = sorted(
        {
            (op.attrs.get("placement"), op.op, op.attrs.get("subtask_role"))
            for fiber in fibers
            for op in fiber.ops
        }
    )
    print("placement/op/subtask roles:")
    for placement, op, subtask_role in placement_roles:
        print(f"  {placement:9s} {op:22s} subtask={subtask_role}")

    print("\n=== representative flat fiber op sequences ===")
    representatives: dict[int, Fiber] = {}
    for fiber in fibers:
        task_id, _, _ = _parse_stream_id(fiber.stream_id)
        representatives.setdefault(task_id, fiber)
    for task_id, fiber in sorted(representatives.items()):
        print(
            f"\n[{fiber.stream_id}] task{task_id} "
            f"strategy={fiber.attrs['strategy_id']} fiber={fiber.id}"
        )
        for op in fiber.ops:
            inputs = ", ".join(fragment.label() for fragment in op.inputs) or "-"
            outputs = ", ".join(fragment.label() for fragment in op.outputs) or "-"
            deps = ", ".join(dependency.label() for dependency in op.depends_on) or "-"
            placement = op.attrs.get("placement")
            print(
                f"  #{op.order_index:02d} {op.op:22s} placement={placement:9s} "
                f"in=[{inputs}] out=[{outputs}] deps=[{deps}]"
            )


def build_demo_block_projections(plan: StreamPlan) -> tuple[FiberBlockProjection, ...]:
    """Project demo fibers to block-sized validation views."""

    return tuple(
        project_fiber_to_blocks(fiber, stream_plan=plan)
        for fiber in build_demo_fibers(plan)
    )


def print_demo_block_projections(plan: StreamPlan) -> None:
    projections = build_demo_block_projections(plan)
    fibers = build_demo_fibers(plan)
    validations = [
        validate_fiber_block_projection(fiber, projection)
        for fiber, projection in zip(fibers, projections, strict=True)
    ]
    print("\n=== fiber block projection summary ===")
    print(f"projections={len(projections)}")
    block_counts = sorted({len(projection.blocks) for projection in projections})
    dependency_counts = sorted({len(projection.dependencies) for projection in projections})
    print(f"blocks_per_projection={block_counts}")
    print(f"deps_per_projection={dependency_counts}")
    block_kinds = sorted(
        {
            block.block_kind
            for projection in projections
            for block in projection.blocks
        }
    )
    print(f"block_kinds={block_kinds}")
    proof_statuses = sorted(
        {
            dependency.proof.status if dependency.proof is not None else "missing"
            for projection in projections
            for dependency in projection.dependencies
        }
    )
    print(f"proof_statuses={proof_statuses}")
    validation_ok = all(report.ok for report in validations)
    validation_diagnostics = sum(len(report.diagnostics) for report in validations)
    print(f"validation_ok={validation_ok} validation_diagnostics={validation_diagnostics}")
    proof_kinds = sorted(
        {
            proof_kind
            for projection in projections
            for dependency in projection.dependencies
            if dependency.proof is not None
            for proof_kind in dependency.proof.proven_by
        }
    )
    print(f"proof_kinds={proof_kinds}")
    aggregate = summarize_fiber_block_projections(projections)
    print("\n=== aggregate projection report ===")
    print(
        "totals="
        f"streams={aggregate['stream_count']} "
        f"fibers={aggregate['fiber_count']} "
        f"blocks={aggregate['total_blocks']} "
        f"deps={aggregate['total_dependencies']}"
    )
    print(f"block_kind_counts={aggregate['block_kind_counts']}")
    print(f"placement_counts={aggregate['placement_counts']}")
    print(f"proof_kind_counts={aggregate['proof_kind_counts']}")
    print(f"route_trace_lengths={aggregate['route_trace_lengths']}")
    print("loop_instance_counts:")
    for loop_key, by_kind in aggregate["loop_instance_counts"].items():
        print(f"  {loop_key}: {by_kind}")
    compat_probe = probe_tile_micro_block_compat(projections)
    print("\n=== TileMicroBlock compat probe ===")
    print(f"mapped_kind_counts={compat_probe['mapped_kind_counts']}")
    print(f"unsupported_kind_counts={compat_probe['unsupported_kind_counts']}")
    print(f"missing_field_counts={compat_probe['missing_field_counts']}")
    print(f"notes_counts={compat_probe['notes_counts']}")
    print("example compat rows:")
    for row in compat_probe["example_rows"][:4]:
        print(
            f"  {row['block_kind']} -> {row['compat_block_kind']} "
            f"missing={row['missing_fields']} notes={row['notes']}"
        )
    legacy_like = summarize_legacy_like_sequence(projections)
    print("\n=== legacy-like sequence report ===")
    print(f"pre_loop_counts={legacy_like['pre_loop_counts']}")
    print(f"k_loop_is_uniform={legacy_like['k_loop_is_uniform']}")
    print(f"canonical_k_body_shapes={legacy_like['canonical_k_body_shapes']}")
    print(f"k_loop_counts={legacy_like['k_loop_counts']}")
    print(f"post_loop_counts={legacy_like['post_loop_counts']}")
    print(f"unsupported_post_loop_counts={legacy_like['unsupported_post_loop_counts']}")

    representative = next(
        (
            projection
            for projection in projections
            if any(
                dependency.proof is not None and dependency.proof.stream_plan_edge_ids
                for dependency in projection.dependencies
            )
        ),
        projections[0],
    )
    print(
        f"\n[representative projection] stream={representative.stream_id} "
        f"fiber={representative.fiber_id}"
    )
    for block in representative.blocks:
        inputs = ", ".join(fragment.label() for fragment in block.input_fragments) or "-"
        outputs = ", ".join(fragment.label() for fragment in block.output_fragments) or "-"
        print(
            f"  {block.id} kind={block.block_kind:24s} "
            f"placement={block.placement:9s} loop_i={block.loop_instance_id} "
            f"in=[{inputs}] out=[{outputs}]"
        )
    print("  dependencies:")
    for dependency in representative.dependencies:
        proof = dependency.proof.label() if dependency.proof is not None else "missing"
        route_trace = (
            list(dependency.proof.stream_plan_edge_ids)
            if dependency.proof is not None and dependency.proof.stream_plan_edge_ids
            else []
        )
        route_text = f" route_trace={route_trace}" if route_trace else ""
        print(
            f"    {dependency.src_block_id} -> {dependency.dst_block_id} "
            f"expected={dependency.expected_satisfaction} proof={proof}{route_text}"
        )


def print_demo_executable_program(plan: StreamPlan) -> None:
    fibers = build_demo_fibers(plan)
    projections = build_demo_block_projections(plan)
    program = lower_fibers_to_executable_ops(
        fibers,
        projections=projections,
        executable_role_profile=MATMUL_SPEC.executable_role_profile(),
    )
    summary = summarize_executable_program(program)
    print("\n=== B-line executable fiber program summary ===")
    print(
        "totals="
        f"executable_ops={summary['executable_op_count']} "
        f"unique_sources={summary['unique_source_fiber_op_count']} "
        f"diagnostics={summary['diagnostic_count']} "
        f"forbidden_tile_micro_block_fields={summary['forbidden_tile_micro_block_field_count']}"
    )
    print(f"role_counts={summary['role_counts']}")
    print(f"placement_counts={summary['placement_counts']}")
    print(f"source_fiber_op_kind_counts={summary['source_fiber_op_kind_counts']}")
    print(f"proof_status_counts={summary['proof_status_counts']}")
    binding_program = bind_executable_roles_symbolically(
        program,
        template_intents=MATMUL_SPEC.template_intent_profile(),
    )
    binding_summary = summarize_role_binding_program(binding_program)
    print("\n=== B-line symbolic role binding summary ===")
    print(
        "totals="
        f"bindings={binding_summary['binding_count']} "
        f"diagnostics={binding_summary['diagnostic_count']} "
        f"forbidden_tile_micro_block_fields="
        f"{binding_summary['forbidden_tile_micro_block_field_count']}"
    )
    print(f"status_counts={binding_summary['status_counts']}")
    print(f"template_role_counts={binding_summary['template_role_counts']}")
    print(f"unsupported_role_counts={binding_summary['unsupported_role_counts']}")
    template_records = lower_symbolic_bindings_to_template_records(binding_program)
    template_summary = summarize_template_record_program(template_records)
    print("\n=== B-line symbolic template record summary ===")
    print(
        "totals="
        f"records={template_summary['record_count']} "
        f"diagnostics={template_summary['diagnostic_count']} "
        f"forbidden_tile_micro_block_fields="
        f"{template_summary['forbidden_tile_micro_block_field_count']}"
    )
    print(f"status_counts={template_summary['status_counts']}")
    print(f"stage_counts={template_summary['stage_counts']}")
    print(f"template_role_counts={template_summary['template_role_counts']}")
    print(f"symbolic_role_counts={template_summary['symbolic_role_counts']}")
    semantic_report = lower_template_records_to_dfu3500_semantics(template_records)
    semantic_summary = summarize_dfu3500_semantic_report(semantic_report)
    print("\n=== B-line DFU3500 role semantic report ===")
    print(
        "totals="
        f"records={semantic_summary['record_count']} "
        f"diagnostics={semantic_summary['diagnostic_count']} "
        f"forbidden_tile_micro_block_fields="
        f"{semantic_summary['forbidden_tile_micro_block_field_count']}"
    )
    print(f"proof_status_counts={semantic_summary['proof_status_counts']}")
    print(f"semantic_kind_counts={semantic_summary['semantic_kind_counts']}")
    print(f"unproven_role_counts={semantic_summary['unproven_role_counts']}")
    schedule = build_fiber_execution_schedule(program, semantic_report)
    schedule_summary = summarize_fiber_execution_schedule(schedule)
    print("\n=== B-line fiber execution schedule summary ===")
    print(
        "totals="
        f"steps={schedule_summary['step_count']} "
        f"fibers={schedule_summary['fiber_count']} "
        f"deps={schedule_summary['dependency_ref_count']} "
        f"diagnostics={schedule_summary['diagnostic_count']} "
        f"forbidden_tile_micro_block_fields="
        f"{schedule_summary['forbidden_tile_micro_block_field_count']}"
    )
    print(f"steps_per_fiber={schedule_summary['steps_per_fiber']}")
    print(f"phase_counts={schedule_summary['phase_counts']}")
    print(f"loop_instance_counts={schedule_summary['loop_instance_counts']}")
    print(f"proof_status_counts={schedule_summary['proof_status_counts']}")
    print(f"unproven_role_counts={schedule_summary['unproven_role_counts']}")


if __name__ == "__main__":
    demo_plan = build_demo_gemm_stream_plan()
    print_demo_stream_matrix_shapes(demo_plan)
    print_demo_fibers(demo_plan)
    print_demo_block_projections(demo_plan)
    print_demo_executable_program(demo_plan)
