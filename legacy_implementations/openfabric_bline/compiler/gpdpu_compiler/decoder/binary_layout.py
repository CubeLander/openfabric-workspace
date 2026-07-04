"""Profile-driven binary layout metadata for DFU diagnostic decoding.

The generic decoder consumes these descriptors.  Target-specific details such
as DFU3500 CBUF/MICC sections belong in profile modules, not decoder logic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import reduce
from operator import mul
from typing import Any, Literal


ScalarType = Literal["u8", "u16", "u32", "u64"]
FieldStatus = Literal["source_backed", "derived", "unknown"]

SCALAR_SIZES: dict[str, int] = {
    "u8": 1,
    "u16": 2,
    "u32": 4,
    "u64": 8,
}


@dataclass(frozen=True)
class SourceRef:
    """Human-readable provenance for a profile or field fact."""

    file: str
    symbol: str | None = None
    evidence: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "symbol": self.symbol,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class FieldLayout:
    """A field inside a binary struct row."""

    name: str
    offset: int
    type_name: ScalarType | Literal["struct"]
    count: int = 1
    struct_name: str | None = None
    status: FieldStatus = "source_backed"
    source_ref: SourceRef | None = None

    def element_size(self, profile: DfuBinaryProfile) -> int:
        if self.type_name == "struct":
            if self.struct_name is None:
                raise ValueError(f"{self.name} is struct field without struct_name")
            return profile.structs[self.struct_name].size
        return SCALAR_SIZES[self.type_name]

    def size(self, profile: DfuBinaryProfile) -> int:
        return self.element_size(profile) * self.count

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "offset": self.offset,
            "type_name": self.type_name,
            "count": self.count,
            "struct_name": self.struct_name,
            "status": self.status,
            "source_ref": self.source_ref.to_json() if self.source_ref else None,
        }


@dataclass(frozen=True)
class StructLayout:
    """A fixed-size C-like struct row."""

    name: str
    size: int
    fields: tuple[FieldLayout, ...]
    source_ref: SourceRef | None = None

    def sorted_fields(self) -> tuple[FieldLayout, ...]:
        return tuple(sorted(self.fields, key=lambda field: field.offset))

    def validate(self, profile: DfuBinaryProfile) -> tuple[str, ...]:
        errors: list[str] = []
        for field in self.fields:
            if field.offset < 0:
                errors.append(f"{self.name}.{field.name} has negative offset")
                continue
            end = field.offset + field.size(profile)
            if end > self.size:
                errors.append(
                    f"{self.name}.{field.name} ends at {end}, beyond {self.size}"
                )
            if field.type_name == "struct" and field.struct_name not in profile.structs:
                errors.append(
                    f"{self.name}.{field.name} references unknown struct "
                    f"{field.struct_name!r}"
                )
        return tuple(errors)

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size": self.size,
            "source_ref": self.source_ref.to_json() if self.source_ref else None,
            "fields": [field.to_json() for field in self.sorted_fields()],
        }


@dataclass(frozen=True)
class DimensionLayout:
    """A logical row-index dimension for a repeated section."""

    name: str
    size: int
    coordinate_status: Literal["index_only", "source_backed"] = "index_only"

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size": self.size,
            "coordinate_status": self.coordinate_status,
        }


@dataclass(frozen=True)
class SectionLayout:
    """A named section inside a binary file kind."""

    name: str
    offset: int
    row_struct: str
    dimensions: tuple[DimensionLayout, ...]
    component_file_names: tuple[str, ...] = ()

    def row_count(self) -> int:
        if not self.dimensions:
            return 1
        return reduce(mul, (dimension.size for dimension in self.dimensions), 1)

    def row_size(self, profile: DfuBinaryProfile) -> int:
        return profile.structs[self.row_struct].size

    def size(self, profile: DfuBinaryProfile) -> int:
        return self.row_count() * self.row_size(profile)

    def end_offset(self, profile: DfuBinaryProfile) -> int:
        return self.offset + self.size(profile)

    def indices_for_row(self, row_index: int) -> dict[str, int]:
        indices: dict[str, int] = {}
        remaining = row_index
        for dimension in reversed(self.dimensions):
            indices[dimension.name] = remaining % dimension.size
            remaining //= dimension.size
        return {
            dimension.name: indices[dimension.name]
            for dimension in self.dimensions
        }

    def to_json(self, profile: DfuBinaryProfile) -> dict[str, Any]:
        return {
            "name": self.name,
            "offset": self.offset,
            "size": self.size(profile),
            "row_struct": self.row_struct,
            "row_size": self.row_size(profile),
            "row_count": self.row_count(),
            "dimensions": [dimension.to_json() for dimension in self.dimensions],
            "component_file_names": list(self.component_file_names),
        }


@dataclass(frozen=True)
class FileLayout:
    """A full binary file kind made of one or more sections."""

    kind: str
    sections: tuple[SectionLayout, ...]
    aliases: tuple[str, ...] = ()

    def size(self, profile: DfuBinaryProfile) -> int:
        if not self.sections:
            return 0
        return max(section.end_offset(profile) for section in self.sections)

    def section_for_offset(
        self, profile: DfuBinaryProfile, offset: int
    ) -> SectionLayout | None:
        for section in self.sections:
            if section.offset <= offset < section.end_offset(profile):
                return section
        return None

    def to_json(self, profile: DfuBinaryProfile) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "aliases": list(self.aliases),
            "size": self.size(profile),
            "sections": [section.to_json(profile) for section in self.sections],
        }


@dataclass(frozen=True)
class DfuBinaryProfile:
    """A concrete binary layout profile for one DFU target/package ABI."""

    profile_id: str
    target: str
    schema_version: str
    endian: Literal["little", "big"]
    layout_status: Literal["partial", "complete_for_known_fields"]
    structs: dict[str, StructLayout]
    files: dict[str, FileLayout]
    source_refs: tuple[SourceRef, ...] = ()
    source_fingerprints: dict[str, str] = field(default_factory=dict)

    def canonical_json(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "target": self.target,
            "schema_version": self.schema_version,
            "endian": self.endian,
            "layout_status": self.layout_status,
            "source_refs": [ref.to_json() for ref in self.source_refs],
            "source_fingerprints": dict(sorted(self.source_fingerprints.items())),
            "structs": {
                name: self.structs[name].to_json()
                for name in sorted(self.structs)
            },
            "files": {
                name: self.files[name].to_json(self)
                for name in sorted(self.files)
            },
        }

    def profile_sha256(self) -> str:
        payload = json.dumps(
            self.canonical_json(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        for struct in self.structs.values():
            errors.extend(struct.validate(self))
        for file_layout in self.files.values():
            for section in file_layout.sections:
                if section.row_struct not in self.structs:
                    errors.append(
                        f"{file_layout.kind}.{section.name} references unknown "
                        f"struct {section.row_struct!r}"
                    )
                if section.offset < 0:
                    errors.append(
                        f"{file_layout.kind}.{section.name} has negative offset"
                    )
        return tuple(errors)

    def to_json(self) -> dict[str, Any]:
        payload = self.canonical_json()
        payload["profile_sha256"] = self.profile_sha256()
        return payload
