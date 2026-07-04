"""Shared helpers for experimental B-line stream compiler tools."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from gpdpu_compiler.core.op_specs import MATMUL_SPEC
from gpdpu_compiler.core.stream_compiler.binary_plan import (
    BinaryLayoutPlan,
    lower_template_ops_to_binary_layout,
)
from gpdpu_compiler.core.stream_compiler.binding import (
    SymbolicRoleBindingProgram,
    bind_executable_roles_symbolically,
)
from gpdpu_compiler.core.stream_compiler.blocks import (
    FiberBlockProjection,
    project_fiber_to_blocks,
)
from gpdpu_compiler.core.stream_compiler.dfu3500_semantics import (
    Dfu3500RoleSemanticReport,
    lower_template_records_to_dfu3500_semantics,
)
from gpdpu_compiler.core.stream_compiler.executable import (
    FiberExecutableProgram,
    lower_fibers_to_executable_ops,
)
from gpdpu_compiler.core.stream_compiler.fiber import Fiber
from gpdpu_compiler.core.stream_compiler.gemm_demo import (
    build_demo_fibers,
    build_demo_gemm_stream_plan,
)
from gpdpu_compiler.core.stream_compiler.schedule import (
    ValidatedFiberExecutionSchedule,
    build_fiber_execution_schedule,
    verify_fiber_execution_schedule,
)
from gpdpu_compiler.core.stream_compiler.stream import StreamPlan
from gpdpu_compiler.core.stream_compiler.template_ops import (
    Diagnostic,
    TemplateOpPlan,
    lower_schedule_to_template_ops,
)
from gpdpu_compiler.core.stream_compiler.template_records import (
    SymbolicTemplateRecordProgram,
    lower_symbolic_bindings_to_template_records,
)

SnapshotProfile = Literal["gemm_relu", "gemm_no_relu"]


@dataclass(frozen=True)
class DemoPipelineArtifacts:
    profile: SnapshotProfile
    include_relu: bool
    requested_runnability_state: str
    stream_plan: StreamPlan
    fibers: tuple[Fiber, ...]
    projections: tuple[FiberBlockProjection, ...]
    executable: FiberExecutableProgram
    bindings: SymbolicRoleBindingProgram
    template_records: SymbolicTemplateRecordProgram
    semantic_report: Dfu3500RoleSemanticReport
    schedule: ValidatedFiberExecutionSchedule
    template_plan: TemplateOpPlan
    binary_layout: BinaryLayoutPlan


def build_demo_pipeline(profile: SnapshotProfile) -> DemoPipelineArtifacts:
    include_relu = profile == "gemm_relu"
    requested_runnability_state = (
        "bline_atomic_fiber_op_chain_missing"
        if include_relu
        else "emittable_debug"
    )
    stream_plan = build_demo_gemm_stream_plan(include_relu=False)
    fibers = build_demo_fibers(stream_plan)
    projections = tuple(
        project_fiber_to_blocks(fiber, stream_plan=stream_plan)
        for fiber in fibers
    )
    executable = lower_fibers_to_executable_ops(
        fibers,
        projections=projections,
        executable_role_profile=MATMUL_SPEC.executable_role_profile(),
    )
    bindings = bind_executable_roles_symbolically(
        executable,
        template_intents=MATMUL_SPEC.template_intent_profile(),
    )
    template_records = lower_symbolic_bindings_to_template_records(bindings)
    semantic_report = lower_template_records_to_dfu3500_semantics(template_records)
    raw_schedule = build_fiber_execution_schedule(executable, semantic_report)
    schedule = verify_fiber_execution_schedule(raw_schedule)
    template_plan = lower_schedule_to_template_ops(
        schedule,
        semantic_report=semantic_report,
        template_records=template_records,
    )
    if include_relu:
        template_plan = _mark_gemm_relu_inside_gemm_fiber_disabled(template_plan)
    binary_layout = lower_template_ops_to_binary_layout(
        template_plan,
        requested_runnability_state=requested_runnability_state,
    )
    return DemoPipelineArtifacts(
        profile=profile,
        include_relu=include_relu,
        requested_runnability_state=requested_runnability_state,
        stream_plan=stream_plan,
        fibers=fibers,
        projections=projections,
        executable=executable,
        bindings=bindings,
        template_records=template_records,
        semantic_report=semantic_report,
        schedule=schedule,
        template_plan=template_plan,
        binary_layout=binary_layout,
    )


def _mark_gemm_relu_inside_gemm_fiber_disabled(
    template_plan: TemplateOpPlan,
) -> TemplateOpPlan:
    return replace(
        template_plan,
        runnability_state="report_only",
        diagnostics=(
            *template_plan.diagnostics,
            Diagnostic(
                severity="error",
                code="gemm_relu_inside_gemm_fiber_disabled",
                subject_id="BLineFiber",
                message=(
                    "GEMM fiber construction cannot contain ReLU; ReLU must "
                    "be represented by an explicit downstream tile op-chain "
                    "stage before B-line-native GEMM+ReLU can be runtime-ready."
                ),
                evidence_refs=(
                    "AGENTS.md:64",
                    "docs/compiler/planB.md",
                ),
            ),
        ),
    )


__all__ = [
    "DemoPipelineArtifacts",
    "SnapshotProfile",
    "build_demo_pipeline",
]
