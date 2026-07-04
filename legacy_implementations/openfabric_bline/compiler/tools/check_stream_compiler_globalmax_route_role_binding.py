#!/usr/bin/env python3
"""Focused check for GlobalMax route role binding contracts."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpdpu_compiler.core.op_specs import LOG10MAX_SPEC
from gpdpu_compiler.core.stream_compiler.binding import (
    bind_executable_roles_symbolically,
    summarize_role_binding_program,
)
from gpdpu_compiler.core.stream_compiler.executable import (
    FiberExecutableProgram,
    lower_fibers_to_executable_ops,
    summarize_executable_program,
)
from gpdpu_compiler.core.stream_compiler.fiber import Fiber, FiberOp, FragmentRef
from gpdpu_compiler.core.stream_compiler.log10max_fiber_chain import (
    build_log10max_production_fiber,
)
from gpdpu_compiler.core.stream_compiler.route_role_binding import (
    build_route_role_binding_report,
    summarize_route_role_binding_report,
)


def main() -> None:
    failures: list[str] = []
    global_max = FragmentRef.make("GlobalMax", tile=0)
    push = FiberOp(
        id="fiber:globalmax_route:0000:push",
        stream_id="stream:globalmax_route:src",
        fiber_id="fiber:globalmax_route",
        order_index=0,
        op="fragment_route_push",
        inputs=(global_max,),
        attrs={
            "placement": "tile_body",
            "operand": "GlobalMax",
            "source_value_kind": "scalar",
            "destination_value_kind": "scalar",
        },
    )
    recv = FiberOp(
        id="fiber:globalmax_route:0001:recv",
        stream_id="stream:globalmax_route:dst",
        fiber_id="fiber:globalmax_route",
        order_index=1,
        op="fragment_route_recv",
        outputs=(global_max,),
        attrs={
            "placement": "tile_body",
            "operand": "GlobalMax",
            "source_value_kind": "scalar",
            "destination_value_kind": "scalar",
        },
    )
    fiber = Fiber(
        id="fiber:globalmax_route",
        stream_id="stream:globalmax_route",
        m_tile=0,
        n_tile=0,
        ops=(push, recv),
    )
    executable = lower_fibers_to_executable_ops(
        (fiber,),
        executable_role_profile=LOG10MAX_SPEC.executable_role_profile(),
    )
    executable_summary = summarize_executable_program(executable)
    expected_roles = {
        "operand_route_push:GlobalMax": 1,
        "operand_route_recv:GlobalMax": 1,
    }
    if executable_summary["role_counts"] != expected_roles:
        failures.append(
            f"unexpected executable roles: {executable_summary['role_counts']}"
        )
    if executable_summary["diagnostic_count"] != 0:
        failures.append(f"unexpected executable diagnostics: {executable.diagnostics}")

    bindings = bind_executable_roles_symbolically(
        executable,
        template_intents=LOG10MAX_SPEC.template_intent_profile(),
    )
    binding_summary = summarize_role_binding_program(bindings)
    if binding_summary["status_counts"] != {"legacy_template_candidate": 2}:
        failures.append(
            "GlobalMax route roles must bind through existing route template "
            f"evidence, got {binding_summary['status_counts']}"
        )

    fail_closed = build_route_role_binding_report(executable)
    fail_summary = summarize_route_role_binding_report(fail_closed)
    if fail_summary["proof_status"] != "unproven":
        failures.append(f"expected fail-closed proof status, got {fail_summary}")
    if "receiver_owned_destination_binding_missing" not in fail_summary["blockers"]:
        failures.append("missing receiver-owned destination blocker")
    if "route_path_proof_missing" not in fail_summary["blockers"]:
        failures.append("missing route_path proof blocker")
    if fail_summary["runtime_ready"] is not False:
        failures.append("unproven GlobalMax route binding must not be runtime_ready")

    proven_ops = []
    for op in executable.executable_ops:
        if op.role == "operand_route_recv:GlobalMax":
            proven_ops.append(
                replace(
                    op,
                    proof_summary=(
                        {
                            "source_fiber_dependency_id": "dep:globalmax_route",
                            "status": "satisfied",
                            "proven_by": ("route_path",),
                            "expected_satisfaction": "route_or_local_materialization",
                        },
                    ),
                    attrs=dict(
                        op.attrs,
                        receiver_destination_operand="receiver_owned_global_max_scalar_operand",
                        receiver_destination_block="receiver_globalmax_block",
                    ),
                )
            )
        else:
            proven_ops.append(op)
    proven_report = build_route_role_binding_report(
        FiberExecutableProgram(executable_ops=tuple(proven_ops))
    )
    proven_summary = summarize_route_role_binding_report(proven_report)
    if proven_summary["proof_status"] != "proven":
        failures.append(f"expected proven GlobalMax route binding, got {proven_summary}")
    if proven_summary["runtime_ready"] is not True:
        failures.append("complete GlobalMax route binding should be runtime_ready")
    if proven_summary["receiver_owned_destination_binding_count"] != 1:
        failures.append("expected one receiver-owned destination binding")

    production_executable = lower_fibers_to_executable_ops(
        (build_log10max_production_fiber(),),
        executable_role_profile=LOG10MAX_SPEC.executable_role_profile(),
    )
    production_report = build_route_role_binding_report(production_executable)
    production_summary = summarize_route_role_binding_report(production_report)
    if production_summary["proof_status"] != "unresolved":
        failures.append(
            "current production fiber should expose missing GlobalMax route ops, "
            f"got {production_summary}"
        )
    if "route_role_globalmax_ops_missing" not in production_summary["blockers"]:
        failures.append("production report must fail closed before ring emission")

    if failures:
        print("stream compiler GlobalMax route role binding check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler GlobalMax route role binding check OK")
    print(f"synthetic_route_roles={executable_summary['role_counts']}")
    print(f"fail_closed_blockers={fail_summary['blockers']}")
    print(f"proven_summary={proven_summary}")


if __name__ == "__main__":
    main()
