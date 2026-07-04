"""Coverage declarations for DFU decoder knowledge areas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CoverageStatus = Literal[
    "implemented",
    "diagnostic_only",
    "documentation_only",
    "out_of_scope",
]


@dataclass(frozen=True)
class DecoderCoverageItem:
    area: str
    status: CoverageStatus
    owner: str
    source_docs: tuple[str, ...]
    notes: str

    def to_json(self) -> dict[str, object]:
        return {
            "area": self.area,
            "status": self.status,
            "owner": self.owner,
            "source_docs": list(self.source_docs),
            "notes": self.notes,
        }


DFU3500_COVERAGE_ITEMS: tuple[DecoderCoverageItem, ...] = (
    DecoderCoverageItem(
        area="cbuf_combined_image_layout",
        status="implemented",
        owner="compiler/gpdpu_compiler/decoder/profiles/dfu3500.py",
        source_docs=("docs/runtime/data/cbuf.md",),
        notes="CBUF sections, row sizes, dimensions, offset lookup, row decode, and size guards.",
    ),
    DecoderCoverageItem(
        area="micc_combined_image_layout",
        status="implemented",
        owner="compiler/gpdpu_compiler/decoder/profiles/dfu3500.py",
        source_docs=("docs/runtime/data/micc.md",),
        notes="MICC task/subtask sections plus DFU3500 active-ish control diagnostics.",
    ),
    DecoderCoverageItem(
        area="component_file_layouts",
        status="implemented",
        owner="compiler/gpdpu_compiler/decoder/profiles/dfu3500.py",
        source_docs=("docs/compiler/binary_packaging/README.md",),
        notes="Component file kinds share the same source-backed structs as combined CBUF/MICC images.",
    ),
    DecoderCoverageItem(
        area="struct_field_offsets",
        status="implemented",
        owner="compiler/gpdpu_compiler/decoder/profiles/dfu3500.py",
        source_docs=(
            "docs/compiler/binary_packaging/research_notes/binary/"
            "2026-06-20_vendor_struct_layout_audit.md",
        ),
        notes="Known fields are source-backed; padding and unknown ranges stay explicit.",
    ),
    DecoderCoverageItem(
        area="source_fingerprints",
        status="diagnostic_only",
        owner="compiler/gpdpu_compiler/decoder/profiles/dfu3500.py",
        source_docs=("docs/vendor_reference/common_oper/source-fingerprint-index.md",),
        notes="Audited hashes are embedded; automatic local source verification is future work.",
    ),
    DecoderCoverageItem(
        area="field_aware_lookup_and_diff",
        status="implemented",
        owner="compiler/gpdpu_compiler/decoder/binary_decoder.py",
        source_docs=(
            "docs/compiler/binary_packaging/research_notes/enhancements/"
            "rfc-dfu-binary-decoder.md",
        ),
        notes="Offset lookup, row decode, field-aware diff, padding diff, and length diff.",
    ),
    DecoderCoverageItem(
        area="active_rows_vs_padded_capacity",
        status="diagnostic_only",
        owner="compiler/gpdpu_compiler/decoder/dfu3500_diagnostics.py",
        source_docs=(
            "docs/runtime/data/micc.md",
            "docs/compiler/binary_packaging/research_notes/binary/"
            "2026-06-20_a_line_pain_retrospective.md",
        ),
        notes="Reports suspicious active-ish rows but does not decide runtime launch truth.",
    ),
    DecoderCoverageItem(
        area="auxiliary_sidecars",
        status="documentation_only",
        owner="docs/runtime/data/auxiliary-artifacts.md",
        source_docs=("docs/runtime/data/auxiliary-artifacts.md",),
        notes="data_inst_replace.bin and enable files are known sidecars; decoding is not implemented.",
    ),
    DecoderCoverageItem(
        area="rtl_narrow_instruction_encoding",
        status="documentation_only",
        owner="docs/runtime/data/rtl.md",
        source_docs=("docs/runtime/data/rtl.md",),
        notes="Current decoder handles wide SimICT inst_t rows, not RTL bitfield projections.",
    ),
    DecoderCoverageItem(
        area="runtime_messages",
        status="out_of_scope",
        owner="ignored for decoder payload workflow",
        source_docs=("docs/runtime/data/messages.md",),
        notes="Runtime in-flight structs are not payload artifacts; keep them out of decoder priority.",
    ),
    DecoderCoverageItem(
        area="opcode_mnemonic_annotation",
        status="implemented",
        owner="compiler/gpdpu_compiler/decoder/dfu3500_isa.py",
        source_docs=("docs/architecture/instruction-set/dfu3500-simd/README.md",),
        notes="inst_t.opCode values are annotated with DFU3500 mnemonics for diagnostics.",
    ),
    DecoderCoverageItem(
        area="operand_and_template_semantics",
        status="out_of_scope",
        owner="template/package verifier",
        source_docs=(
            "docs/architecture/instruction-set/dfu3500-simd/README.md",
            "docs/architecture/instruction-set/dfu3500-simd/MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md",
        ),
        notes="Decoder names opcodes but does not prove operand ownership, pseudo expansion, or template legality.",
    ),
    DecoderCoverageItem(
        area="route_endpoint_and_resource_semantics",
        status="out_of_scope",
        owner="package/template verifier",
        source_docs=(
            "docs/vendor_reference/common_oper/operand-resource-and-route-audit.md",
        ),
        notes="Decoder exposes fields; semantic route/resource proof belongs outside generic decode.",
    ),
    DecoderCoverageItem(
        area="task_subtask_exeblock_graph_legality",
        status="diagnostic_only",
        owner="future DFU3500 package/control verifier",
        source_docs=(
            "docs/compiler/binary_packaging/research_notes/binary/"
            "2026-06-20_common_oper_task_graph_exeblock_audit.md",
        ),
        notes="Fields are decodable; full graph legality is future verifier work.",
    ),
    DecoderCoverageItem(
        area="riscv_runtime_control_contract",
        status="out_of_scope",
        owner="runtime control validator",
        source_docs=("docs/vendor_reference/runtime_evidence/README.md",),
        notes="Decoder does not validate DMA/start/wait/finish control programs.",
    ),
    DecoderCoverageItem(
        area="manifest_runtime_readiness",
        status="diagnostic_only",
        owner="compiler/tools/compare_dfu_payloads.py",
        source_docs=("docs/compiler/binary_packaging/README.md",),
        notes="Payload compare catches conformance issues; runtime_runnable truth is outside decoder.",
    ),
)


def make_coverage_report(profile_id: str) -> dict[str, object]:
    counts: dict[str, int] = {
        "implemented": 0,
        "diagnostic_only": 0,
        "documentation_only": 0,
        "out_of_scope": 0,
    }
    for item in DFU3500_COVERAGE_ITEMS:
        counts[item.status] += 1
    return {
        "schema_version": "dfu_binary_decoder_coverage_v1",
        "profile_id": profile_id,
        "status_counts": counts,
        "items": [item.to_json() for item in DFU3500_COVERAGE_ITEMS],
    }
