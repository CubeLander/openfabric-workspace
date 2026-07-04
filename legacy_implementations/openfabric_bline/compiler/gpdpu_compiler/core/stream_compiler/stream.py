"""Flat stream-action IR for the experimental stream compiler.

The primary invariant is that dependencies live on downstream actions.  Any
separate dependency graph is a derived view, not a second source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StreamValue:
    """A value visible on one stream after some action suffix."""

    id: str
    logical_tensor_id: str
    stream_id: str
    kind: str
    producer_action_id: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "logical_tensor_id": self.logical_tensor_id,
            "stream_id": self.stream_id,
            "kind": self.kind,
            "producer_action_id": self.producer_action_id,
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class StreamAction:
    """One flat action in one stream.

    `depends_on` is authoritative.  It may reference actions in the same stream
    or in another stream.
    """

    id: str
    stream_id: str
    op: str
    source_chip_op: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stream_id": self.stream_id,
            "op": self.op,
            "source_chip_op": self.source_chip_op,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "depends_on": list(self.depends_on),
            "attrs": self.attrs,
        }


@dataclass
class StreamPlan:
    """Experimental app-local stream plan."""

    app_id: int
    streams: dict[str, list[StreamAction]] = field(default_factory=dict)
    visible_values: dict[tuple[str, str], StreamValue] = field(default_factory=dict)

    def append_action(self, action: StreamAction) -> None:
        self.streams.setdefault(action.stream_id, []).append(action)

    def set_visible_value(self, value: StreamValue) -> None:
        self.visible_values[(value.stream_id, value.logical_tensor_id)] = value

    def visible_value(self, *, stream_id: str, logical_tensor_id: str) -> StreamValue:
        return self.visible_values[(stream_id, logical_tensor_id)]

    def action_by_id(self, action_id: str) -> StreamAction:
        for actions in self.streams.values():
            for action in actions:
                if action.id == action_id:
                    return action
        raise KeyError(action_id)

    def trace_action_dependencies(self, action_id: str) -> tuple[StreamAction, ...]:
        """Return a deterministic dependency trace ending at `action_id`.

        This is a derived view over `StreamAction.depends_on`, not a second route
        graph.  It is intentionally simple and follows all transitive action
        dependencies in stable order.  The stream/fiber projection uses it to
        explain that a fragment-level route recv is isomorphic to the already
        selected stream-level visibility path.
        """

        visited: set[str] = set()
        ordered: list[StreamAction] = []

        def visit(current_id: str) -> None:
            if current_id in visited:
                return
            visited.add(current_id)
            action = self.action_by_id(current_id)
            for dependency_id in action.depends_on:
                if dependency_id:
                    visit(dependency_id)
            ordered.append(action)

        visit(action_id)
        return tuple(ordered)

    def dependency_edges(self) -> tuple[tuple[str, str], ...]:
        """Return a derived dependency graph view as `(src, dst)` pairs."""

        edges: list[tuple[str, str]] = []
        for actions in self.streams.values():
            for action in actions:
                for dependency in action.depends_on:
                    edges.append((dependency, action.id))
        return tuple(edges)

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ir": "experimental_stream_plan",
            "app_id": self.app_id,
            "streams": {
                stream_id: [action.to_plan() for action in actions]
                for stream_id, actions in sorted(self.streams.items())
            },
            "visible_values": {
                f"{stream_id}:{tensor_id}": value.to_plan()
                for (stream_id, tensor_id), value in sorted(self.visible_values.items())
            },
            "dependency_edges_view": [list(edge) for edge in self.dependency_edges()],
        }
