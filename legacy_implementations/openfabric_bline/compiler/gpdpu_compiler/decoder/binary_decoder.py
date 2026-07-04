"""Generic, profile-driven DFU binary decoder."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from .binary_layout import (
    DfuBinaryProfile,
    FieldLayout,
    FileLayout,
    SCALAR_SIZES,
    SectionLayout,
)
from .dfu3500_isa import annotate_opcode
from .profiles import BUILTIN_PROFILES, DFU3500_SIMICT_LEGACY_PROFILE

LookupClassification = Literal[
    "known_field",
    "known_padding",
    "unknown_range",
    "out_of_bounds",
    "size_mismatch",
]


@dataclass(frozen=True)
class OffsetLookup:
    classification: LookupClassification
    path: str | None
    path_tokens: tuple[dict[str, Any], ...]
    input_offset: int
    file_kind: str
    section: str | None = None
    section_offset: int | None = None
    row_index: int | None = None
    row_indices: dict[str, int] | None = None
    row_offset: int | None = None
    struct: str | None = None
    field: str | None = None
    field_type: str | None = None
    field_abs_offset: int | None = None
    field_row_offset: int | None = None
    byte_index_in_field: int | None = None
    field_size: int | None = None
    value: int | None = None
    raw_hex: str | None = None
    annotation: dict[str, Any] | None = None
    diagnostic: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "path": self.path,
            "path_tokens": list(self.path_tokens),
            "input_offset": self.input_offset,
            "file_kind": self.file_kind,
            "section": self.section,
            "section_offset": self.section_offset,
            "row_index": self.row_index,
            "row_indices": self.row_indices,
            "row_offset": self.row_offset,
            "struct": self.struct,
            "field": self.field,
            "field_type": self.field_type,
            "field_abs_offset": self.field_abs_offset,
            "field_row_offset": self.field_row_offset,
            "byte_index_in_field": self.byte_index_in_field,
            "field_size": self.field_size,
            "value": self.value,
            "raw_hex": self.raw_hex,
            "annotation": self.annotation,
            "diagnostic": self.diagnostic,
        }


def get_profile(profile_id: str | None = None) -> DfuBinaryProfile:
    if profile_id is None:
        return DFU3500_SIMICT_LEGACY_PROFILE
    try:
        return BUILTIN_PROFILES[profile_id]
    except KeyError as exc:
        available = ", ".join(sorted(BUILTIN_PROFILES))
        raise KeyError(f"unknown DFU binary profile {profile_id!r}; available: {available}") from exc


def list_profiles() -> tuple[DfuBinaryProfile, ...]:
    return tuple(BUILTIN_PROFILES[name] for name in sorted(BUILTIN_PROFILES))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_decode_report(
    data: bytes,
    *,
    file_kind: str,
    profile: DfuBinaryProfile | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    selected_profile = profile or get_profile()
    return {
        "schema_version": "dfu_binary_decode_report_v1",
        "tool": {
            "name": "decode_dfu_binary",
            "version": "0.1.0",
        },
        "profile": {
            "profile_id": selected_profile.profile_id,
            "profile_sha256": selected_profile.profile_sha256(),
            "target": selected_profile.target,
            "source_fingerprints": dict(
                sorted(selected_profile.source_fingerprints.items())
            ),
        },
        "input": {
            "path": path,
            "sha256": sha256_bytes(data),
            "size": len(data),
            "kind": file_kind,
        },
        "status": "ok",
        "diagnostics": [],
    }


def decode_summary(
    data: bytes,
    *,
    file_kind: str,
    profile: DfuBinaryProfile | None = None,
    only_nonzero: bool = False,
) -> dict[str, Any]:
    selected_profile = profile or get_profile()
    file_layout = _file_layout(selected_profile, file_kind)
    report = make_decode_report(data, file_kind=file_layout.kind, profile=selected_profile)
    expected_size = file_layout.size(selected_profile)
    diagnostics: list[dict[str, Any]] = []
    if len(data) != expected_size:
        diagnostics.append(
            {
                "severity": "error",
                "classification": "size_mismatch",
                "message": (
                    f"{file_layout.kind} size mismatch: got {len(data)}, "
                    f"expected {expected_size}"
                ),
            }
        )

    sections: list[dict[str, Any]] = []
    for section in file_layout.sections:
        section_size = section.size(selected_profile)
        section_bytes = data[section.offset : section.offset + section_size]
        row_size = section.row_size(selected_profile)
        rows: list[dict[str, Any]] = []
        nonzero_count = 0
        for row_index in range(section.row_count()):
            start = row_index * row_size
            row_bytes = section_bytes[start : start + row_size]
            is_nonzero = any(row_bytes)
            if is_nonzero:
                nonzero_count += 1
            if only_nonzero and is_nonzero:
                rows.append(
                    {
                        "row_index": row_index,
                        "indices": section.indices_for_row(row_index),
                        "nonzero": True,
                    }
                )
        sections.append(
            {
                **section.to_json(selected_profile),
                "active_ish": {
                    "summary_kind": "heuristic_nonzero_markers",
                    "control_semantics_verified": False,
                    "nonzero_row_count": nonzero_count,
                },
                "rows": rows,
            }
        )
    report["sections"] = sections
    report["diagnostics"] = diagnostics
    report["status"] = "error" if diagnostics else "ok"
    return report


def decode_row(
    data: bytes,
    *,
    file_kind: str,
    row_index: int,
    section_name: str | None = None,
    profile: DfuBinaryProfile | None = None,
    max_array_elements: int = 16,
) -> dict[str, Any]:
    selected_profile = profile or get_profile()
    file_layout = _file_layout(selected_profile, file_kind)
    report = make_decode_report(data, file_kind=file_layout.kind, profile=selected_profile)
    expected_size = file_layout.size(selected_profile)
    if len(data) != expected_size:
        report["status"] = "error"
        report["diagnostics"] = [
            {
                "severity": "error",
                "classification": "size_mismatch",
                "message": (
                    f"{file_layout.kind} size mismatch: got {len(data)}, "
                    f"expected {expected_size}"
                ),
            }
        ]
        return report

    section = _select_section(file_layout, section_name)
    if row_index < 0 or row_index >= section.row_count():
        report["status"] = "error"
        report["diagnostics"] = [
            {
                "severity": "error",
                "classification": "out_of_bounds",
                "message": (
                    f"row {row_index} outside {section.name} row count "
                    f"{section.row_count()}"
                ),
            }
        ]
        return report

    row_size = section.row_size(selected_profile)
    row_offset = section.offset + row_index * row_size
    row_bytes = data[row_offset : row_offset + row_size]
    indices = section.indices_for_row(row_index)
    path_tokens: list[dict[str, Any]] = [
        {"kind": "file", "name": file_layout.kind},
        {"kind": "section", "name": section.name},
    ]
    for name, value in indices.items():
        path_tokens.append({"kind": "index", "name": name, "value": value})
    path = _path_from_tokens(path_tokens)

    report["row"] = {
        "path": path,
        "path_tokens": path_tokens,
        "section": section.name,
        "row_index": row_index,
        "row_indices": indices,
        "row_abs_offset": row_offset,
        "row_size": row_size,
        "row_nonzero": any(row_bytes),
        "struct": section.row_struct,
        "fields": _decode_struct_fields(
            data=data,
            profile=selected_profile,
            struct_name=section.row_struct,
            base_offset=row_offset,
            path=path,
            path_tokens=tuple(path_tokens),
            max_array_elements=max_array_elements,
        ),
    }
    return report


def lookup_offset(
    data: bytes,
    *,
    file_kind: str,
    offset: int,
    profile: DfuBinaryProfile | None = None,
) -> OffsetLookup:
    selected_profile = profile or get_profile()
    file_layout = _file_layout(selected_profile, file_kind)
    if offset < 0 or offset >= len(data):
        return OffsetLookup(
            classification="out_of_bounds",
            path=None,
            path_tokens=(
                {"kind": "file", "name": file_layout.kind},
            ),
            input_offset=offset,
            file_kind=file_layout.kind,
            diagnostic=f"offset {offset} outside input size {len(data)}",
        )
    expected_size = file_layout.size(selected_profile)
    if len(data) != expected_size:
        return OffsetLookup(
            classification="size_mismatch",
            path=None,
            path_tokens=(
                {"kind": "file", "name": file_layout.kind},
            ),
            input_offset=offset,
            file_kind=file_layout.kind,
            diagnostic=f"input size {len(data)} does not match expected {expected_size}",
        )

    section = file_layout.section_for_offset(selected_profile, offset)
    if section is None:
        return OffsetLookup(
            classification="unknown_range",
            path=None,
            path_tokens=(
                {"kind": "file", "name": file_layout.kind},
            ),
            input_offset=offset,
            file_kind=file_layout.kind,
            diagnostic="offset is not covered by a source-backed section",
        )

    section_offset = offset - section.offset
    row_size = section.row_size(selected_profile)
    row_index = section_offset // row_size
    row_offset = section_offset % row_size
    indices = section.indices_for_row(row_index)
    path_tokens: list[dict[str, Any]] = [
        {"kind": "file", "name": file_layout.kind},
        {"kind": "section", "name": section.name},
    ]
    for name, value in indices.items():
        path_tokens.append({"kind": "index", "name": name, "value": value})

    base_path = _path_from_tokens(path_tokens)
    lookup = _lookup_struct_field(
        data=data,
        profile=selected_profile,
        struct_name=section.row_struct,
        row_base_offset=offset - row_offset,
        relative_offset=row_offset,
        path_tokens=tuple(path_tokens),
        path=base_path,
    )
    return _with_section_context(
        lookup,
        file_layout=file_layout,
        section=section,
        section_offset=section_offset,
        row_index=row_index,
        indices=indices,
        row_offset=row_offset,
    )


def _decode_struct_fields(
    *,
    data: bytes,
    profile: DfuBinaryProfile,
    struct_name: str,
    base_offset: int,
    path: str,
    path_tokens: tuple[dict[str, Any], ...],
    max_array_elements: int,
) -> list[dict[str, Any]]:
    struct = profile.structs[struct_name]
    fields: list[dict[str, Any]] = []
    for field in struct.sorted_fields():
        field_size = field.size(profile)
        field_abs_offset = base_offset + field.offset
        field_path = f"{path}.{field.name}"
        field_tokens = (
            *path_tokens,
            {"kind": "field", "name": field.name},
        )
        element_size = field.element_size(profile)
        if field.count > max_array_elements:
            field_bytes = data[field_abs_offset : field_abs_offset + field_size]
            fields.append(
                {
                    "path": field_path,
                    "path_tokens": list(field_tokens),
                    "field": field.name,
                    "field_type": field.type_name,
                    "struct_name": field.struct_name,
                    "offset": field.offset,
                    "abs_offset": field_abs_offset,
                    "size": field_size,
                    "count": field.count,
                    "status": field.status,
                    "decode_status": "array_summary",
                    "nonzero_element_count": _count_nonzero_elements(
                        field_bytes,
                        element_size,
                        field.count,
                    ),
                }
            )
            continue
        if field.type_name == "struct":
            elements = []
            for element_index in range(field.count):
                element_abs_offset = field_abs_offset + element_index * element_size
                element_path = (
                    f"{field_path}[{element_index}]"
                    if field.count > 1
                    else field_path
                )
                element_tokens = field_tokens
                if field.count > 1:
                    element_tokens = (
                        *element_tokens,
                        {
                            "kind": "element_index",
                            "name": field.name,
                            "value": element_index,
                        },
                    )
                elements.append(
                    {
                        "path": element_path,
                        "path_tokens": list(element_tokens),
                        "abs_offset": element_abs_offset,
                        "struct": field.struct_name,
                        "fields": _decode_struct_fields(
                            data=data,
                            profile=profile,
                            struct_name=field.struct_name or "",
                            base_offset=element_abs_offset,
                            path=element_path,
                            path_tokens=element_tokens,
                            max_array_elements=max_array_elements,
                        ),
                    }
                )
            fields.append(
                {
                    "path": field_path,
                    "path_tokens": list(field_tokens),
                    "field": field.name,
                    "field_type": field.type_name,
                    "struct_name": field.struct_name,
                    "offset": field.offset,
                    "abs_offset": field_abs_offset,
                    "size": field_size,
                    "count": field.count,
                    "status": field.status,
                    "decode_status": "decoded",
                    "elements": elements,
                }
            )
            continue
        values = []
        for element_index in range(field.count):
            element_abs_offset = field_abs_offset + element_index * element_size
            raw = data[element_abs_offset : element_abs_offset + element_size]
            value = int.from_bytes(raw, byteorder=profile.endian, signed=False)
            element_path = (
                f"{field_path}[{element_index}]"
                if field.count > 1
                else field_path
            )
            decoded_value = {
                "path": element_path,
                "value": value,
                "raw_hex": raw.hex(),
                "abs_offset": element_abs_offset,
            }
            annotation = _field_annotation(
                struct_name=struct_name,
                field_name=field.name,
                value=value,
            )
            if annotation:
                decoded_value["annotation"] = annotation
            values.append(decoded_value)
        fields.append(
            {
                "path": field_path,
                "path_tokens": list(field_tokens),
                "field": field.name,
                "field_type": field.type_name,
                "offset": field.offset,
                "abs_offset": field_abs_offset,
                "size": field_size,
                "count": field.count,
                "status": field.status,
                "decode_status": "decoded",
                "values": values,
            }
        )
    return fields


def _count_nonzero_elements(data: bytes, element_size: int, count: int) -> int:
    nonzero = 0
    for element_index in range(count):
        start = element_index * element_size
        if any(data[start : start + element_size]):
            nonzero += 1
    return nonzero


def _field_annotation(
    *,
    struct_name: str,
    field_name: str,
    value: int,
) -> dict[str, Any] | None:
    if struct_name == "inst_t" and field_name == "opCode":
        return annotate_opcode(value)
    return None


def _with_section_context(
    lookup: OffsetLookup,
    *,
    file_layout: FileLayout,
    section: SectionLayout,
    section_offset: int,
    row_index: int,
    indices: dict[str, int],
    row_offset: int,
) -> OffsetLookup:
    return OffsetLookup(
        **{
            **lookup.to_json(),
            "file_kind": file_layout.kind,
            "section": section.name,
            "section_offset": section_offset,
            "row_index": row_index,
            "row_indices": indices,
            "row_offset": row_offset,
        }
    )


def _lookup_struct_field(
    *,
    data: bytes,
    profile: DfuBinaryProfile,
    struct_name: str,
    row_base_offset: int,
    relative_offset: int,
    path_tokens: tuple[dict[str, Any], ...],
    path: str,
) -> OffsetLookup:
    struct = profile.structs[struct_name]
    for field in struct.sorted_fields():
        field_size = field.size(profile)
        if field.offset <= relative_offset < field.offset + field_size:
            field_rel = relative_offset - field.offset
            element_size = field.element_size(profile)
            element_index = field_rel // element_size
            element_rel = field_rel % element_size
            field_tokens = list(path_tokens)
            field_tokens.append({"kind": "field", "name": field.name})
            field_path = f"{path}.{field.name}"
            if field.count > 1:
                field_tokens.append(
                    {"kind": "element_index", "name": field.name, "value": element_index}
                )
                field_path = f"{field_path}[{element_index}]"
            field_abs_offset = row_base_offset + field.offset + element_index * element_size
            if field.type_name == "struct":
                return _lookup_struct_field(
                    data=data,
                    profile=profile,
                    struct_name=field.struct_name or "",
                    row_base_offset=field_abs_offset,
                    relative_offset=element_rel,
                    path_tokens=tuple(field_tokens),
                    path=field_path,
                )

            raw = data[field_abs_offset : field_abs_offset + element_size]
            value = int.from_bytes(raw, byteorder=profile.endian, signed=False)
            field_tokens.append({"kind": "scalar", "type": field.type_name})
            annotation = _field_annotation(
                struct_name=struct.name,
                field_name=field.name,
                value=value,
            )
            return OffsetLookup(
                classification=(
                    "unknown_range" if field.status == "unknown" else "known_field"
                ),
                path=field_path,
                path_tokens=tuple(field_tokens),
                input_offset=row_base_offset + relative_offset,
                file_kind="",
                struct=struct.name,
                field=field.name,
                field_type=field.type_name,
                field_abs_offset=field_abs_offset,
                field_row_offset=field.offset + element_index * element_size,
                byte_index_in_field=element_rel,
                field_size=element_size,
                value=value,
                raw_hex=raw.hex(),
                annotation=annotation,
            )

    return OffsetLookup(
        classification="known_padding",
        path=f"{path}.__padding__",
        path_tokens=(
            *path_tokens,
            {"kind": "padding", "struct": struct.name},
        ),
        input_offset=row_base_offset + relative_offset,
        file_kind="",
        struct=struct.name,
        diagnostic=f"offset {relative_offset} is padding in {struct.name}",
    )


def _file_layout(profile: DfuBinaryProfile, file_kind: str) -> FileLayout:
    if file_kind in profile.files:
        return profile.files[file_kind]
    for layout in profile.files.values():
        if file_kind in layout.aliases:
            return layout
    available = ", ".join(sorted(profile.files))
    raise KeyError(f"unknown file kind {file_kind!r}; available: {available}")


def _select_section(file_layout: FileLayout, section_name: str | None) -> SectionLayout:
    if section_name is None:
        if len(file_layout.sections) == 1:
            return file_layout.sections[0]
        available = ", ".join(section.name for section in file_layout.sections)
        raise ValueError(
            f"{file_layout.kind} has multiple sections; choose one with --section "
            f"({available})"
        )
    for section in file_layout.sections:
        if section.name == section_name:
            return section
    available = ", ".join(section.name for section in file_layout.sections)
    raise ValueError(
        f"unknown section {section_name!r} for {file_layout.kind}; available: {available}"
    )


def _path_from_tokens(tokens: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for token in tokens:
        if token["kind"] in {"file", "section"}:
            parts.append(token["name"])
        elif token["kind"] == "index":
            parts[-1] = f"{parts[-1]}[{token['name']}={token['value']}]"
    return ".".join(parts)
