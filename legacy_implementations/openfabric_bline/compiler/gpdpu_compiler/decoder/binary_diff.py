"""Small field-aware diff helpers for DFU diagnostic binaries."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from .binary_decoder import lookup_offset, make_decode_report
from .binary_layout import DfuBinaryProfile


def diff_binary_bytes(
    left: bytes,
    right: bytes,
    *,
    file_kind: str,
    profile: DfuBinaryProfile,
    max_diffs: int = 200,
) -> dict[str, Any]:
    """Return a bounded field-aware byte diff report.

    This is intentionally diagnostic: it groups changed byte offsets through the
    decoder profile but does not decide serializer correctness.
    """

    same_size = len(left) == len(right)
    scan_size = min(len(left), len(right))
    diff_groups: OrderedDict[tuple[str, str | None, int, int], dict[str, Any]] = (
        OrderedDict()
    )
    byte_diff_count = abs(len(left) - len(right))
    diff_kind_counts = {
        "value_diff": 0,
        "raw_only_diff": 0,
        "padding_diff": 0,
        "unknown_range_diff": 0,
        "length_diff": 0 if same_size else 1,
        "section_diff": 0,
    }
    for offset in range(scan_size):
        if left[offset] == right[offset]:
            continue
        byte_diff_count += 1
        lookup = lookup_offset(left, file_kind=file_kind, offset=offset, profile=profile)
        if lookup.classification == "known_field":
            diff_kind = "value_diff"
            group_offset = lookup.field_abs_offset or offset
            group_size = lookup.field_size or 1
        elif lookup.classification == "known_padding":
            diff_kind = "padding_diff"
            group_offset = offset
            group_size = 1
        elif lookup.classification == "unknown_range":
            diff_kind = "unknown_range_diff"
            group_offset = offset
            group_size = 1
        else:
            diff_kind = lookup.classification
            group_offset = offset
            group_size = 1
        diff_kind_counts[diff_kind] = diff_kind_counts.get(diff_kind, 0) + 1

        key = (diff_kind, lookup.path, group_offset, group_size)
        if key not in diff_groups:
            left_raw = left[group_offset : group_offset + group_size]
            right_raw = right[group_offset : group_offset + group_size]
            group = {
                "diff_kind": diff_kind,
                "path": lookup.path,
                "classification": lookup.classification,
                "field_abs_offset": group_offset,
                "field_size": group_size,
                "byte_offsets": [],
                "byte_diff_count": 0,
                "left": {
                    "value": lookup.value if diff_kind == "value_diff" else None,
                    "raw_hex": left_raw.hex(),
                },
                "right": {
                    "value": (
                        int.from_bytes(right_raw, byteorder=profile.endian, signed=False)
                        if diff_kind == "value_diff"
                        else None
                    ),
                    "raw_hex": right_raw.hex(),
                },
                "lookup": lookup.to_json(),
            }
            diff_groups[key] = group
        diff_groups[key]["byte_offsets"].append(offset)
        diff_groups[key]["byte_diff_count"] += 1

    all_diffs = list(diff_groups.values())
    emitted_diffs = all_diffs[:max_diffs]

    report = {
        "schema_version": "dfu_binary_diff_report_v1",
        "left": make_decode_report(left, file_kind=file_kind, profile=profile)["input"],
        "right": make_decode_report(right, file_kind=file_kind, profile=profile)["input"],
        "same_size": same_size,
        "byte_diff_count": byte_diff_count,
        "diff_group_count": len(all_diffs),
        "emitted_diff_group_count": len(emitted_diffs),
        "field_diff_count": sum(
            1 for diff in all_diffs if diff["diff_kind"] == "value_diff"
        ),
        "padding_diff_count": sum(
            1 for diff in all_diffs if diff["diff_kind"] == "padding_diff"
        ),
        "unknown_range_diff_count": sum(
            1 for diff in all_diffs if diff["diff_kind"] == "unknown_range_diff"
        ),
        "diff_byte_kind_counts": diff_kind_counts,
        "diffs": emitted_diffs,
    }
    if not same_size:
        report["length_diff"] = {
            "left_size": len(left),
            "right_size": len(right),
        }
    return report
