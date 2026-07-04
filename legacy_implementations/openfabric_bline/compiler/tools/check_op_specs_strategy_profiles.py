#!/usr/bin/env python3
"""Focused validation for operator strategy descriptors.

This is a Phase 0/1 guard.  It validates metadata and ownership boundaries only;
it does not migrate or execute B-line stream/fiber lowering.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from gpdpu_compiler.core.op_specs import ELEMENTWISE_FAMILY_SPEC, MATMUL_SPEC


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPILER_ROOT = REPO_ROOT / "compiler"
OP_SPECS_ROOT = REPO_ROOT / "compiler/gpdpu_compiler/core/op_specs"
FOLDING_PATH = REPO_ROOT / "compiler/gpdpu_compiler/core/stream_compiler/folding.py"
FIBER_PATH = REPO_ROOT / "compiler/gpdpu_compiler/core/stream_compiler/fiber.py"
EXECUTABLE_PATH = REPO_ROOT / "compiler/gpdpu_compiler/core/stream_compiler/executable.py"
BINDING_PATH = REPO_ROOT / "compiler/gpdpu_compiler/core/stream_compiler/binding.py"
STREAM_COMPILER_ROOT = REPO_ROOT / "compiler/gpdpu_compiler/core/stream_compiler"
BACKEND_PROJECTION_PATHS = (
    REPO_ROOT / "compiler/gpdpu_compiler/core/stream_compiler/vendor_components.py",
    REPO_ROOT / "compiler/gpdpu_compiler/core/stream_compiler/folded_components.py",
)
FIBER_PATTERN_ALLOWED_CONSUMERS = {
    REPO_ROOT / "compiler/gpdpu_compiler/core/stream_compiler/__init__.py",
    REPO_ROOT / "compiler/gpdpu_compiler/core/stream_compiler/fiber.py",
    REPO_ROOT / "compiler/gpdpu_compiler/core/stream_compiler/fiber_patterns.py",
    REPO_ROOT / "compiler/gpdpu_compiler/core/stream_compiler/gemm_demo.py",
}

EXPECTED_MATMUL_ROLE_TEXTS = {
    "accumulator_finalize",
    "accumulator_prepare",
    "compute_core:gemm_update",
    "operand_materialize:A",
    "operand_materialize:B",
    "operand_route_push:A",
    "operand_route_push:B",
    "operand_route_recv:A",
    "operand_route_recv:B",
    "tile_store",
}

FORBIDDEN_OP_SPEC_IMPORT_PREFIXES = (
    "gpdpu_compiler.core.stream_compiler",
    "gpdpu_compiler.core.program_",
)
FORBIDDEN_OP_SPEC_IMPORT_NAMES = {
    "gpdpu_compiler.core.program_app",
    "gpdpu_compiler.core.program_tile",
    "gpdpu_compiler.core.program_processor",
    "gpdpu_compiler.core.logical_plan",
}
DIAGNOSTIC_SHAPE_TOKENS = {
    "loop_body_shape",
    "stream_body_shape_counts",
}
BACKEND_PROOF_DECISION_FIELDS = {
    "binary_encoded",
    "instances_amount",
    "projection_status",
    "target_fold_projection_proof",
    "target_projection_status",
}
BACKEND_ROLE_SHORTCUT_STRINGS = {
    "compute_core:gemm_update",
    "operand_materialize:",
    "operand_route_recv:",
}


def main() -> None:
    failures: list[str] = []

    _check_import_boundaries(failures)
    _check_folding_boundary(failures)
    _check_stream_owned_fiber_pattern_boundary(failures)
    _check_stream_pass_descriptor_injection_boundary(failures)
    _check_deprecated_phase_api_quarantine(failures)
    _check_no_deprecated_op_spec_api(failures)
    _check_backend_projection_boundary(failures)
    _check_k_block_compat_boundary(failures)
    _check_fiber_pattern_consumption_boundary(failures)
    _check_matmul_profiles(failures)
    _check_elementwise_profiles(failures)
    _check_json_friendly_profiles(failures)

    if failures:
        print("op specs strategy profile check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("op specs strategy profile check OK")
    print(f"matmul_roles={len(MATMUL_SPEC.executable_role_profile().roles)}")
    print(f"elementwise_roles={len(ELEMENTWISE_FAMILY_SPEC.executable_role_profile().roles)}")


def _check_import_boundaries(failures: list[str]) -> None:
    for path in sorted(OP_SPECS_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            module: str | None = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    _check_import_name(path, alias.name, failures)
                continue
            if module is not None:
                _check_import_name(path, module, failures)
            if (
                path.name != "lowering_profiles.py"
                and isinstance(node, ast.Call)
                and _call_name(node) == "TemplateEvidenceProfile"
            ):
                failures.append(f"{path} creates concrete TemplateEvidenceProfile")


def _check_folding_boundary(failures: list[str]) -> None:
    source = FOLDING_PATH.read_text()
    tree = ast.parse(source, filename=str(FOLDING_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("gpdpu_compiler.core.op_specs"):
                failures.append(f"{FOLDING_PATH} imports operator specs module {node.module}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("gpdpu_compiler.core.op_specs"):
                    failures.append(f"{FOLDING_PATH} imports operator specs module {alias.name}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in {
                "sequential_k_matmul",
                "k_block",
                "compute_core:gemm_update",
                "operand_materialize:",
                "operand_route_recv:",
            }:
                failures.append(
                    f"{FOLDING_PATH} contains forbidden folding shortcut string {node.value!r}"
                )
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "startswith"
        ):
            failures.append(f"{FOLDING_PATH} contains forbidden startswith heuristic")
    if "ensure_validated_fiber_execution_schedule" in source:
        failures.append(f"{FOLDING_PATH} trusts pre-existing schedule validation status")
    if "verify_fiber_execution_schedule(schedule)" not in source:
        failures.append(f"{FOLDING_PATH} must re-verify schedule facts at folding entry")
    if "folding_requires_resource_verified_schedule" not in source:
        failures.append(f"{FOLDING_PATH} must gate folding on verifier-owned status")


def _check_stream_owned_fiber_pattern_boundary(failures: list[str]) -> None:
    tree = ast.parse(FIBER_PATH.read_text(), filename=str(FIBER_PATH))
    for node in ast.walk(tree):
        module: str | None = None
        if isinstance(node, ast.ImportFrom):
            module = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("gpdpu_compiler.core.op_specs"):
                    failures.append(f"{FIBER_PATH} imports op specs module {alias.name}")
            continue
        if module and module.startswith("gpdpu_compiler.core.op_specs"):
            failures.append(f"{FIBER_PATH} imports op specs module {module}")


def _check_stream_pass_descriptor_injection_boundary(failures: list[str]) -> None:
    for path in (EXECUTABLE_PATH, BINDING_PATH):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "gpdpu_compiler.core.op_specs":
                    failures.append(f"{path} imports concrete op spec registry")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "gpdpu_compiler.core.op_specs":
                        failures.append(f"{path} imports concrete op spec registry")


def _check_deprecated_phase_api_quarantine(failures: list[str]) -> None:
    allowed_roots = {
        OP_SPECS_ROOT,
    }
    allowed_files = {
        Path(__file__).resolve(),
    }
    deprecated_calls = {"fiber_graph_profile", "folding_profile"}
    for path in sorted(COMPILER_ROOT.rglob("*.py")):
        resolved = path.resolve()
        if resolved in allowed_files:
            continue
        if any(root in resolved.parents for root in allowed_roots):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in deprecated_calls
            ):
                failures.append(
                    f"{path} calls deprecated op-spec phase API "
                    f"{node.func.attr}()"
                )


def _check_no_deprecated_op_spec_api(failures: list[str]) -> None:
    deprecated_attrs = {
        "fiber_graph_profile",
        "folding_profile",
        "graph_kind_allowlist",
    }
    for name, spec in (
        ("MatMul", MATMUL_SPEC),
        ("Elementwise", ELEMENTWISE_FAMILY_SPEC),
    ):
        for attr in deprecated_attrs:
            if hasattr(spec, attr):
                failures.append(f"{name} spec still exposes deprecated {attr}()")


def _check_backend_projection_boundary(failures: list[str]) -> None:
    """Keep projection eligibility separated from diagnostic body-shape text."""

    for path in BACKEND_PROJECTION_PATHS:
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                test_source = ast.get_source_segment(source, node.test) or ""
                if _contains_any(test_source, DIAGNOSTIC_SHAPE_TOKENS):
                    failures.append(
                        f"{path} branches on diagnostic fold body shape: "
                        f"{test_source.strip()}"
                    )
            elif isinstance(node, ast.Dict):
                _check_backend_decision_dict(path, source, node, failures)
            elif isinstance(node, ast.Call):
                _check_backend_decision_call(path, source, node, failures)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                _check_backend_decision_assignment(path, source, node, failures)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in BACKEND_ROLE_SHORTCUT_STRINGS:
                    failures.append(
                        f"{path} contains forbidden backend projection role shortcut "
                        f"{node.value!r}"
                    )

        if (
            path.name == "vendor_components.py"
            and "target_fold_projection_proof" not in source
        ):
            failures.append(
                f"{path} must carry target projection eligibility as an explicit proof"
            )
        if (
            path.name == "vendor_components.py"
            and "target_projection_eligibility_consumes_loop_uniformity_proof"
            not in source
        ):
            failures.append(
                f"{path} target projection proof must state it consumes loop proof"
            )


def _check_k_block_compat_boundary(failures: list[str]) -> None:
    """Keep k_block as an executable/report compatibility label only."""

    executable_source = EXECUTABLE_PATH.read_text()
    if '"k_block": reduction_fragment_index' not in executable_source:
        failures.append(
            f"{EXECUTABLE_PATH} must synthesize k_block only from "
            "reduction_fragment_index"
        )

    for path in sorted(STREAM_COMPILER_ROOT.glob("*.py")):
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value == "k_block"
            ):
                continue
            if path == EXECUTABLE_PATH:
                continue
            failures.append(
                f"{path} contains forbidden stream compiler k_block compat string"
            )


def _check_fiber_pattern_consumption_boundary(failures: list[str]) -> None:
    """Keep FiberPatternPlan as construction metadata, not proof authority."""

    forbidden_pattern_strings = {
        "FiberPatternPlan",
        "TransitionalPatternId",
        "fiber_pattern_plan",
        "matmul_sequential_reduction_transitional",
    }
    for path in sorted(STREAM_COMPILER_ROOT.glob("*.py")):
        if path in FIBER_PATTERN_ALLOWED_CONSUMERS:
            continue
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.endswith("fiber_patterns"):
                    failures.append(f"{path} imports construction-only fiber_patterns")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.endswith("fiber_patterns"):
                        failures.append(f"{path} imports construction-only fiber_patterns")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in forbidden_pattern_strings:
                    failures.append(
                        f"{path} consumes construction-only fiber pattern metadata "
                        f"{node.value!r}"
                    )


def _check_backend_decision_dict(
    path: Path,
    source: str,
    node: ast.Dict,
    failures: list[str],
) -> None:
    for key_node, value_node in zip(node.keys, node.values):
        key = _literal_string(key_node)
        if key not in BACKEND_PROOF_DECISION_FIELDS:
            continue
        value_source = ast.get_source_segment(source, value_node) or ""
        if _contains_any(value_source, DIAGNOSTIC_SHAPE_TOKENS):
            failures.append(
                f"{path} derives backend projection field {key!r} from diagnostic "
                f"fold body shape"
            )


def _check_backend_decision_call(
    path: Path,
    source: str,
    node: ast.Call,
    failures: list[str],
) -> None:
    for keyword in node.keywords:
        if keyword.arg not in BACKEND_PROOF_DECISION_FIELDS:
            continue
        value_source = ast.get_source_segment(source, keyword.value) or ""
        if _contains_any(value_source, DIAGNOSTIC_SHAPE_TOKENS):
            failures.append(
                f"{path} derives backend projection argument {keyword.arg!r} from "
                "diagnostic fold body shape"
            )


def _check_backend_decision_assignment(
    path: Path,
    source: str,
    node: ast.Assign | ast.AnnAssign,
    failures: list[str],
) -> None:
    targets: list[ast.expr]
    value: ast.expr | None
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
        value = node.value
    else:
        targets = [node.target]
        value = node.value
    if value is None:
        return
    target_names = {
        name
        for target in targets
        for name in _assigned_names(target)
    }
    if not target_names.intersection(BACKEND_PROOF_DECISION_FIELDS):
        return
    value_source = ast.get_source_segment(source, value) or ""
    if _contains_any(value_source, DIAGNOSTIC_SHAPE_TOKENS):
        failures.append(
            f"{path} assigns backend projection field from diagnostic fold body shape: "
            f"{sorted(target_names.intersection(BACKEND_PROOF_DECISION_FIELDS))}"
        )


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _assigned_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Tuple | ast.List):
        names: set[str] = set()
        for item in node.elts:
            names.update(_assigned_names(item))
        return names
    return set()


def _contains_any(text: str, tokens: set[str]) -> bool:
    return any(token in text for token in tokens)


def _check_import_name(path: Path, module: str, failures: list[str]) -> None:
    if module in FORBIDDEN_OP_SPEC_IMPORT_NAMES:
        failures.append(f"{path} imports forbidden downstream module {module}")
    if any(module.startswith(prefix) for prefix in FORBIDDEN_OP_SPEC_IMPORT_PREFIXES):
        failures.append(f"{path} imports forbidden downstream module {module}")
    if "serializer" in module or "binary_plan" in module:
        failures.append(f"{path} imports forbidden binary/backend module {module}")


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _check_matmul_profiles(failures: list[str]) -> None:
    access = MATMUL_SPEC.access_profile()
    access_text = repr(access)
    if "k_block" in access_text:
        failures.append("MatMul OperatorAccessProfile must not mention k_block")
    if len(access.reductions) != 1:
        failures.append(
            "MatMul access profile must declare one reduction, got "
            f"{len(access.reductions)}"
        )
    else:
        reduction = access.reductions[0]
        if reduction.axis != "k":
            failures.append(
                "MatMul reduction axis should be mathematical k, got "
                f"{reduction.axis!r}"
            )
        if reduction.ordering != "strict_sequential":
            failures.append(
                "MatMul reduction must use explicit strict ordering, got "
                f"{reduction.ordering!r}"
            )
        if reduction.associativity != "not_reassociable":
            failures.append(
                f"MatMul reduction must not allow reassociation, got {reduction.associativity!r}"
            )
        if reduction.numeric_policy.allowed_reassociation:
            failures.append("MatMul numeric policy must not allow reassociation")

    roles = MATMUL_SPEC.executable_role_profile()
    role_texts = {role.role.text() for role in roles.roles}
    if role_texts != EXPECTED_MATMUL_ROLE_TEXTS:
        failures.append(f"unexpected MatMul executable roles: {sorted(role_texts)}")

    _check_role_intent_coverage(
        name="MatMul",
        roles=roles.roles,
        intent_roles={
            intent.executable_role.text()
            for intent in MATMUL_SPEC.template_intent_profile().intents
        },
        failures=failures,
    )

    scopes = MATMUL_SPEC.stream_visibility_profile().scopes
    if {scope.kind for scope in scopes} != {"row_visible", "column_visible"}:
        failures.append(f"unexpected MatMul visibility kinds: {[scope.kind for scope in scopes]}")
    for scope in scopes:
        if "k_block" in repr(scope):
            failures.append(
                "MatMul stream visibility profile must use semantic fragment "
                f"axes, got schedule-ish k_block in {scope}"
            )
        if not scope.consumer_space or not scope.consumer_axes or not scope.visibility_group_axes:
            failures.append(f"MatMul visibility scope lacks consumer/group details: {scope}")
    row_scope = next((scope for scope in scopes if scope.kind == "row_visible"), None)
    column_scope = next((scope for scope in scopes if scope.kind == "column_visible"), None)
    if row_scope is not None and row_scope.producer_fragment_axes != (
        "m_tile",
        "reduction_fragment",
    ):
        failures.append(f"unexpected MatMul row visibility axes: {row_scope}")
    if column_scope is not None and column_scope.producer_fragment_axes != (
        "reduction_fragment",
        "n_tile",
    ):
        failures.append(f"unexpected MatMul column visibility axes: {column_scope}")


def _check_elementwise_profiles(failures: list[str]) -> None:
    access = ELEMENTWISE_FAMILY_SPEC.access_profile()
    if access.reductions:
        failures.append("Elementwise access profile must not declare reductions")
    access_text = repr(access)
    for token in ("A(", "B(", "k_block", "acc"):
        if token in access_text:
            failures.append(
                "Elementwise access profile unexpectedly contains GEMM token "
                f"{token!r}"
            )

    roles = ELEMENTWISE_FAMILY_SPEC.executable_role_profile()
    role_texts = {role.role.text() for role in roles.roles}
    expected = {"operand_materialize:X", "elementwise:apply", "tile_store"}
    if role_texts != expected:
        failures.append(f"unexpected Elementwise executable roles: {sorted(role_texts)}")

    _check_role_intent_coverage(
        name="Elementwise",
        roles=roles.roles,
        intent_roles={
            intent.executable_role.text()
            for intent in ELEMENTWISE_FAMILY_SPEC.template_intent_profile().intents
        },
        failures=failures,
    )


def _check_role_intent_coverage(
    *,
    name: str,
    roles: tuple[object, ...],
    intent_roles: set[str],
    failures: list[str],
) -> None:
    role_texts = {role.role.text() for role in roles}  # type: ignore[attr-defined]
    empty_sources = [
        role.role.text()  # type: ignore[attr-defined]
        for role in roles
        if not role.source_step_ids  # type: ignore[attr-defined]
    ]
    if empty_sources:
        failures.append(f"{name} roles missing source step ids: {sorted(empty_sources)}")
    missing_intents = role_texts - intent_roles
    if missing_intents:
        failures.append(f"{name} roles missing template intent: {sorted(missing_intents)}")


def _check_json_friendly_profiles(failures: list[str]) -> None:
    profiles = (
        MATMUL_SPEC.access_profile(),
        MATMUL_SPEC.stream_visibility_profile(),
        MATMUL_SPEC.executable_role_profile(),
        MATMUL_SPEC.template_intent_profile(),
        ELEMENTWISE_FAMILY_SPEC.access_profile(),
        ELEMENTWISE_FAMILY_SPEC.stream_visibility_profile(),
        ELEMENTWISE_FAMILY_SPEC.executable_role_profile(),
        ELEMENTWISE_FAMILY_SPEC.template_intent_profile(),
    )
    for profile in profiles:
        if not is_dataclass(profile):
            failures.append(f"profile is not a dataclass: {profile!r}")
            continue
        try:
            _assert_jsonish(asdict(profile))
        except TypeError as exc:
            failures.append(f"profile is not JSON-friendly: {profile!r}: {exc}")


def _assert_jsonish(value: Any) -> None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_jsonish(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"non-string key {key!r}")
            _assert_jsonish(item)
        return
    raise TypeError(f"unsupported value {value!r}")


if __name__ == "__main__":
    main()
