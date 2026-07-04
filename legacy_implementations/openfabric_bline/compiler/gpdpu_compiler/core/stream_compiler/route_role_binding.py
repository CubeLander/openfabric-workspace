"""Route role binding contracts for B-line route FiberOps.

This report is deliberately narrow.  It consumes existing executable route
roles such as ``operand_route_push:A/B`` and
``operand_route_recv:GlobalMax`` and reports whether a role generalization can
reuse the existing route template family.  It does not create communication IR,
route graphs, scheduling authority, instruction rows, or package bytes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

from .executable import ExecutableFiberOp, FiberExecutableProgram

RouteRoleProofStatus = Literal["proven", "unproven", "unresolved"]
RouteDirection = Literal["push", "recv"]
RouteValueKind = Literal["tile_fragment", "scalar", "scratch_scalar", "unknown"]

GLOBALMAX_TEMPLATE_EVIDENCE_ID = (
    "dfu3500_route_forward_globalmax_role_generalization_v1"
)
DEFAULT_ROUTE_TEMPLATE_FAMILY = "route_forward"


@dataclass(frozen=True)
class RouteRoleBindingRecord:
    """One route role binding proof record."""

    record_id: str
    role: str
    executable_role: str
    direction: RouteDirection
    source_executable_op_id: str
    source_fiber_op_id: str
    route_template_family: str
    source_value_kind: RouteValueKind
    destination_value_kind: RouteValueKind
    template_evidence_id: str
    proof_status: RouteRoleProofStatus
    receiver_owned_destination_binding: bool = False
    receiver_destination_operand: str | None = None
    receiver_destination_block: str | None = None
    blockers: tuple[str, ...] = ()
    route_path_proven: bool = False
    notes: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "role": self.role,
            "executable_role": self.executable_role,
            "direction": self.direction,
            "source_executable_op_id": self.source_executable_op_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "route_template_family": self.route_template_family,
            "source_value_kind": self.source_value_kind,
            "destination_value_kind": self.destination_value_kind,
            "template_evidence_id": self.template_evidence_id,
            "proof_status": self.proof_status,
            "receiver_owned_destination_binding": (
                self.receiver_owned_destination_binding
            ),
            "receiver_destination_operand": self.receiver_destination_operand,
            "receiver_destination_block": self.receiver_destination_block,
            "route_path_proven": self.route_path_proven,
            "blockers": list(self.blockers),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class RouteRoleBindingReport:
    """Fail-closed route role binding report."""

    profile_id: str
    role: str
    records: tuple[RouteRoleBindingRecord, ...]
    diagnostics: tuple[str, ...] = ()
    attrs: Mapping[str, object] = field(default_factory=dict)

    @property
    def proof_status(self) -> RouteRoleProofStatus:
        if not self.records:
            return "unresolved"
        if all(record.proof_status == "proven" for record in self.records):
            return "proven"
        if any(record.proof_status == "unproven" for record in self.records):
            return "unproven"
        return "unresolved"

    @property
    def runtime_ready(self) -> bool:
        return self.proof_status == "proven" and not self.diagnostics

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.records:
            blockers.append(f"route_role_{self.role.lower()}_ops_missing")
        for record in self.records:
            blockers.extend(record.blockers)
        return tuple(_dedupe_preserve_order(blockers))

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "route_role_binding_report",
            "profile_id": self.profile_id,
            "role": self.role,
            "proof_status": self.proof_status,
            "runtime_ready": self.runtime_ready,
            "blockers": list(self.blockers),
            "records": [record.to_plan() for record in self.records],
            "diagnostics": list(self.diagnostics),
            "attrs": dict(self.attrs),
            "layering_policy": (
                "route_role_binding_report_consumes_existing_executable_route_"
                "roles;does_not_create_communication_ir_or_scheduling_authority"
            ),
        }


def build_route_role_binding_report(
    program: FiberExecutableProgram,
    *,
    role: str = "GlobalMax",
    profile_id: str = "dfu3500_route_role_binding_v1",
) -> RouteRoleBindingReport:
    """Build route role binding proof records for one route role."""

    dependent_route_path_proofs = _route_path_proofs_by_dependency_source(program)
    records = tuple(
        _record_for_route_op(
            op,
            role=role,
            dependent_route_path_proofs=dependent_route_path_proofs.get(
                op.source_fiber_op_id,
                (),
            ),
        )
        for op in program.executable_ops
        if op.role in {f"operand_route_push:{role}", f"operand_route_recv:{role}"}
    )
    return RouteRoleBindingReport(
        profile_id=profile_id,
        role=role,
        records=records,
        diagnostics=program.diagnostics,
        attrs={
            "communication_ir_created": False,
            "scheduling_authority": "StreamAction.depends_on",
            "route_graph_authority": "derived_validation_metadata_only",
        },
    )


def summarize_route_role_binding_report(
    report: RouteRoleBindingReport,
) -> dict[str, object]:
    """Return stable counts and gate fields for local checks."""

    direction_counts: dict[str, int] = {}
    proof_status_counts: dict[str, int] = {}
    template_family_counts: dict[str, int] = {}
    blocker_counts: dict[str, int] = {}
    receiver_owned_count = 0

    for record in report.records:
        direction_counts[record.direction] = direction_counts.get(record.direction, 0) + 1
        proof_status_counts[record.proof_status] = (
            proof_status_counts.get(record.proof_status, 0) + 1
        )
        template_family_counts[record.route_template_family] = (
            template_family_counts.get(record.route_template_family, 0) + 1
        )
        if record.receiver_owned_destination_binding:
            receiver_owned_count += 1
        for blocker in record.blockers:
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1

    return {
        "record_count": len(report.records),
        "role": report.role,
        "proof_status": report.proof_status,
        "runtime_ready": report.runtime_ready,
        "direction_counts": dict(sorted(direction_counts.items())),
        "proof_status_counts": dict(sorted(proof_status_counts.items())),
        "template_family_counts": dict(sorted(template_family_counts.items())),
        "receiver_owned_destination_binding_count": receiver_owned_count,
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "blockers": list(report.blockers),
        "diagnostic_count": len(report.diagnostics),
    }


def _record_for_route_op(
    op: ExecutableFiberOp,
    *,
    role: str,
    dependent_route_path_proofs: tuple[dict[str, object], ...] = (),
) -> RouteRoleBindingRecord:
    direction = _route_direction(op.role)
    source_value_kind = _value_kind(op, "source_value_kind")
    destination_value_kind = _value_kind(op, "destination_value_kind")
    route_template_family = str(
        op.attrs.get("route_template_family") or DEFAULT_ROUTE_TEMPLATE_FAMILY
    )
    template_evidence_id = str(
        op.attrs.get("template_evidence_id") or GLOBALMAX_TEMPLATE_EVIDENCE_ID
    )
    receiver_destination_operand = _optional_str(
        op.attrs.get("receiver_destination_operand")
    )
    receiver_destination_block = _optional_str(
        op.attrs.get("receiver_destination_block")
    )
    receiver_owned = bool(receiver_destination_operand and receiver_destination_block)
    route_path_proven = _route_path_proven(op, dependent_route_path_proofs)
    blockers = _record_blockers(
        direction=direction,
        route_template_family=route_template_family,
        template_evidence_id=template_evidence_id,
        source_value_kind=source_value_kind,
        destination_value_kind=destination_value_kind,
        receiver_owned=receiver_owned,
        route_path_proven=route_path_proven,
    )
    proof_status: RouteRoleProofStatus = "proven" if not blockers else "unproven"
    return RouteRoleBindingRecord(
        record_id=f"route_role_binding:{op.id}",
        role=role,
        executable_role=op.role,
        direction=direction,
        source_executable_op_id=op.id,
        source_fiber_op_id=op.source_fiber_op_id,
        route_template_family=route_template_family,
        source_value_kind=source_value_kind,
        destination_value_kind=destination_value_kind,
        template_evidence_id=template_evidence_id,
        proof_status=proof_status,
        receiver_owned_destination_binding=receiver_owned,
        receiver_destination_operand=receiver_destination_operand,
        receiver_destination_block=receiver_destination_block,
        blockers=tuple(blockers),
        route_path_proven=route_path_proven,
        notes=(
            "GlobalMax is a route role generalization over the existing "
            "operand route primitive; this record is a gate contract, not a "
            "new communication path",
        ),
    )


def _route_direction(role: str) -> RouteDirection:
    if role.startswith("operand_route_push:"):
        return "push"
    return "recv"


def _value_kind(op: ExecutableFiberOp, attr_name: str) -> RouteValueKind:
    value = op.attrs.get(attr_name)
    if value in {"tile_fragment", "scalar", "scratch_scalar"}:
        return value  # type: ignore[return-value]
    return "scalar" if op.role.endswith(":GlobalMax") else "unknown"


def _route_path_proofs_by_dependency_source(
    program: FiberExecutableProgram,
) -> dict[str, tuple[dict[str, object], ...]]:
    by_source: dict[str, list[dict[str, object]]] = {}
    for op in program.executable_ops:
        route_path_proofs = tuple(
            proof for proof in op.proof_summary if _is_satisfied_route_path(proof)
        )
        if not route_path_proofs:
            continue
        for source_id in op.dependency_source_ids:
            by_source.setdefault(source_id, []).extend(route_path_proofs)
    return {key: tuple(value) for key, value in by_source.items()}


def _route_path_proven(
    op: ExecutableFiberOp,
    dependent_route_path_proofs: tuple[dict[str, object], ...] = (),
) -> bool:
    for proof in (*op.proof_summary, *dependent_route_path_proofs):
        if _is_satisfied_route_path(proof):
            return True
    return False


def _is_satisfied_route_path(proof: Mapping[str, object]) -> bool:
    if proof.get("status") != "satisfied":
        return False
    proven_by = proof.get("proven_by", ())
    if isinstance(proven_by, (list, tuple)) and "route_path" in proven_by:
        return True
    return False


def _record_blockers(
    *,
    direction: RouteDirection,
    route_template_family: str,
    template_evidence_id: str,
    source_value_kind: RouteValueKind,
    destination_value_kind: RouteValueKind,
    receiver_owned: bool,
    route_path_proven: bool,
) -> list[str]:
    blockers: list[str] = []
    if route_template_family != DEFAULT_ROUTE_TEMPLATE_FAMILY:
        blockers.append("route_template_family_not_existing_route_forward")
    if not template_evidence_id:
        blockers.append("template_evidence_id_missing")
    if source_value_kind == "unknown":
        blockers.append("source_value_kind_unknown")
    if destination_value_kind == "unknown":
        blockers.append("destination_value_kind_unknown")
    if direction == "recv":
        if not receiver_owned:
            blockers.append("receiver_owned_destination_binding_missing")
        if not route_path_proven:
            blockers.append("route_path_proof_missing")
    return blockers


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


__all__ = [
    "RouteRoleBindingRecord",
    "RouteRoleBindingReport",
    "build_route_role_binding_report",
    "summarize_route_role_binding_report",
]
