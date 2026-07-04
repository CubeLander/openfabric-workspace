"""DFU3500 SimICT legacy binary decoder profile."""

from __future__ import annotations

from gpdpu_compiler.decoder.binary_layout import (
    DfuBinaryProfile,
    DimensionLayout,
    FieldLayout,
    FileLayout,
    SectionLayout,
    SourceRef,
    StructLayout,
)


AUDIT = SourceRef(
    file=(
        "docs/compiler/binary_packaging/research_notes/binary/"
        "2026-06-20_vendor_struct_layout_audit.md"
    ),
    evidence="local_header_layout_audit_2026_06_20",
)


def _field(
    name: str,
    offset: int,
    type_name: str,
    *,
    count: int = 1,
    struct_name: str | None = None,
    symbol: str | None = None,
) -> FieldLayout:
    return FieldLayout(
        name=name,
        offset=offset,
        type_name=type_name,  # type: ignore[arg-type]
        count=count,
        struct_name=struct_name,
        source_ref=SourceRef(
            file=AUDIT.file,
            symbol=symbol,
            evidence=AUDIT.evidence,
        ),
    )


POSITION_T = StructLayout(
    name="position_t",
    size=24,
    source_ref=AUDIT,
    fields=(
        _field("x", 0, "u64", symbol="position_t::x"),
        _field("y", 8, "u64", symbol="position_t::y"),
        _field("z", 16, "u64", symbol="position_t::z"),
    ),
)

INST_T = StructLayout(
    name="inst_t",
    size=304,
    source_ref=AUDIT,
    fields=(
        _field("opCode", 0, "u32", symbol="inst_t::opCode"),
        _field("unit_inst_type", 8, "u64", symbol="inst_t::unit_inst_type"),
        _field("latency", 16, "u64", symbol="inst_t::latency"),
        _field("imms", 24, "u64", count=3, symbol="inst_t::imms"),
        _field(
            "src_operands_idx",
            48,
            "u64",
            count=3,
            symbol="inst_t::src_operands_idx",
        ),
        _field(
            "dst_operands_idx",
            72,
            "u64",
            count=3,
            symbol="inst_t::dst_operands_idx",
        ),
        _field(
            "dst_pes_pos",
            96,
            "struct",
            count=3,
            struct_name="position_t",
            symbol="inst_t::dst_pes_pos",
        ),
        _field(
            "dst_blocks_idx",
            168,
            "u64",
            count=3,
            symbol="inst_t::dst_blocks_idx",
        ),
        _field(
            "forwarding_bits",
            192,
            "u64",
            count=3,
            symbol="inst_t::forwarding_bits",
        ),
        _field(
            "bypass_bits",
            216,
            "u64",
            count=3,
            symbol="inst_t::bypass_bits",
        ),
        _field("iter_exe_cond", 240, "u64", symbol="inst_t::iter_exe_cond"),
        _field(
            "src_operands_fetched",
            248,
            "u8",
            count=3,
            symbol="inst_t::src_operands_fetched",
        ),
        _field(
            "dst_operands_fetched",
            251,
            "u8",
            count=3,
            symbol="inst_t::dst_operands_fetched",
        ),
        _field("block_idx", 256, "u64", symbol="inst_t::block_idx"),
        _field("flow_ack", 264, "u64", symbol="inst_t::flow_ack"),
        _field("end_inst", 272, "u64", symbol="inst_t::end_inst"),
        _field("extra_fields", 280, "u64", count=3, symbol="inst_t::extra_fields"),
    ),
)

INSTANCE_CONF_INFO_T = StructLayout(
    name="instance_conf_info_t",
    size=32,
    source_ref=AUDIT,
    fields=(
        _field(
            "base_addr",
            0,
            "u64",
            count=4,
            symbol="instance_conf_info_t::base_addr",
        ),
    ),
)

EXEBLOCK_CONF_T = StructLayout(
    name="exeBlock_conf_t",
    size=472,
    source_ref=AUDIT,
    fields=(
        _field(
            "req_activations",
            0,
            "u64",
            symbol="exeBlock_conf_t::req_activations",
        ),
        _field("has_stages", 8, "u8", count=5, symbol="exeBlock_conf_t::has_stages"),
        _field(
            "stages_start_pc",
            16,
            "u64",
            count=5,
            symbol="exeBlock_conf_t::stages_start_pc",
        ),
        _field(
            "predecessors",
            56,
            "u64",
            count=20,
            symbol="exeBlock_conf_t::predecessors",
        ),
        _field(
            "successors",
            216,
            "u64",
            count=20,
            symbol="exeBlock_conf_t::successors",
        ),
        _field("block_idx", 376, "u64", symbol="exeBlock_conf_t::block_idx"),
        _field("subtask_idx", 384, "u64", symbol="exeBlock_conf_t::subtask_idx"),
        _field("task_idx", 392, "u64", symbol="exeBlock_conf_t::task_idx"),
        _field(
            "instances_amount",
            400,
            "u64",
            symbol="exeBlock_conf_t::instances_amount",
        ),
        _field("child_amount", 408, "u64", symbol="exeBlock_conf_t::child_amount"),
        _field("block_class", 416, "u64", symbol="exeBlock_conf_t::block_class"),
        _field(
            "inst_mem_based_addr",
            424,
            "u64",
            symbol="exeBlock_conf_t::inst_mem_based_addr",
        ),
        _field(
            "ld_stage_inst_amount",
            432,
            "u64",
            symbol="exeBlock_conf_t::ld_stage_inst_amount",
        ),
        _field(
            "cal_stage_inst_amount",
            440,
            "u64",
            symbol="exeBlock_conf_t::cal_stage_inst_amount",
        ),
        _field(
            "flow_stage_inst_amount",
            448,
            "u64",
            symbol="exeBlock_conf_t::flow_stage_inst_amount",
        ),
        _field(
            "st_stage_inst_amount",
            456,
            "u64",
            symbol="exeBlock_conf_t::st_stage_inst_amount",
        ),
        _field("is_leaf", 464, "u8", symbol="exeBlock_conf_t::is_leaf"),
    ),
)

EXEBLOCK_CONF_INFO_T = StructLayout(
    name="exeBlock_conf_info_t",
    size=520,
    source_ref=AUDIT,
    fields=(
        _field("valid", 0, "u8", symbol="exeBlock_conf_info_t::valid"),
        _field("block_idx", 8, "u64", symbol="exeBlock_conf_info_t::block_idx"),
        _field(
            "pe_dst",
            16,
            "struct",
            struct_name="position_t",
            symbol="exeBlock_conf_info_t::pe_dst",
        ),
        _field("priority", 40, "u64", symbol="exeBlock_conf_info_t::priority"),
        _field(
            "exeBlock_conf",
            48,
            "struct",
            struct_name="exeBlock_conf_t",
            symbol="exeBlock_conf_info_t::exeBlock_conf",
        ),
    ),
)

TASK_CONF_INFO_T = StructLayout(
    name="task_conf_info_t",
    size=120,
    source_ref=AUDIT,
    fields=(
        _field("is_exe_start", 0, "u8", symbol="task_conf_info_t::is_exe_start"),
        _field("is_exe_end", 1, "u8", symbol="task_conf_info_t::is_exe_end"),
        _field(
            "subtasks_amount",
            8,
            "u64",
            symbol="task_conf_info_t::subtasks_amount",
        ),
        _field("execute_times", 16, "u64", symbol="task_conf_info_t::execute_times"),
        _field(
            "subtasks_idx",
            24,
            "u64",
            count=8,
            symbol="task_conf_info_t::subtasks_idx",
        ),
        _field("suc_tasks", 88, "u64", count=4, symbol="task_conf_info_t::suc_tasks"),
    ),
)

SUB_TASK_CONF_INFO_T = StructLayout(
    name="sub_task_conf_info_t",
    size=266328,
    source_ref=AUDIT,
    fields=(
        _field(
            "is_exe_start",
            0,
            "u8",
            symbol="sub_task_conf_info_t::is_exe_start",
        ),
        _field("is_exe_end", 1, "u8", symbol="sub_task_conf_info_t::is_exe_end"),
        _field(
            "instances_amount",
            8,
            "u64",
            symbol="sub_task_conf_info_t::instances_amount",
        ),
        _field(
            "instances_conf_mem_based_addr",
            16,
            "u64",
            symbol="sub_task_conf_info_t::instances_conf_mem_based_addr",
        ),
        _field(
            "suc_subtasks",
            24,
            "u64",
            count=4,
            symbol="sub_task_conf_info_t::suc_subtasks",
        ),
        _field(
            "root_block_amount",
            56,
            "u64",
            symbol="sub_task_conf_info_t::root_block_amount",
        ),
        _field(
            "block_amount",
            64,
            "u64",
            symbol="sub_task_conf_info_t::block_amount",
        ),
        _field(
            "exeBlocks_conf_info",
            72,
            "struct",
            count=512,
            struct_name="exeBlock_conf_info_t",
            symbol="sub_task_conf_info_t::exeBlocks_conf_info",
        ),
        _field(
            "subtask_idx",
            266312,
            "u64",
            symbol="sub_task_conf_info_t::subtask_idx",
        ),
        _field("task_idx", 266320, "u64", symbol="sub_task_conf_info_t::task_idx"),
    ),
)

STRUCTS = {
    struct.name: struct
    for struct in (
        POSITION_T,
        INST_T,
        INSTANCE_CONF_INFO_T,
        EXEBLOCK_CONF_T,
        EXEBLOCK_CONF_INFO_T,
        TASK_CONF_INFO_T,
        SUB_TASK_CONF_INFO_T,
    )
}

CBUF_INST_BYTES = 21_168_128
CBUF_EXEBLOCK_BYTES = 266_240
CBUF_INSTANCE_BYTES = 2_097_152
MICC_TASK_BYTES = 480

CBUF_FILE = FileLayout(
    kind="cbuf",
    aliases=("cbuf_file.bin",),
    sections=(
        SectionLayout(
            name="insts",
            offset=0,
            row_struct="inst_t",
            dimensions=(
                DimensionLayout("pe_index", 16),
                DimensionLayout("inst_idx", 4352),
            ),
            component_file_names=("insts_file.bin",),
        ),
        SectionLayout(
            name="exeblocks",
            offset=CBUF_INST_BYTES,
            row_struct="exeBlock_conf_info_t",
            dimensions=(
                DimensionLayout("pe_index", 16),
                DimensionLayout("block_idx", 32),
            ),
            component_file_names=("exeblock_conf_info_file.bin",),
        ),
        SectionLayout(
            name="instances",
            offset=CBUF_INST_BYTES + CBUF_EXEBLOCK_BYTES,
            row_struct="instance_conf_info_t",
            dimensions=(
                DimensionLayout("task", 4),
                DimensionLayout("subtask", 8),
                DimensionLayout("instance", 2048),
            ),
            component_file_names=("instance_conf_info_file.bin",),
        ),
    ),
)

MICC_FILE = FileLayout(
    kind="micc",
    aliases=("micc_file.bin",),
    sections=(
        SectionLayout(
            name="tasks",
            offset=0,
            row_struct="task_conf_info_t",
            dimensions=(DimensionLayout("task", 4),),
            component_file_names=("tasks_conf_info_file.bin",),
        ),
        SectionLayout(
            name="subtasks",
            offset=MICC_TASK_BYTES,
            row_struct="sub_task_conf_info_t",
            dimensions=(
                DimensionLayout("task", 4),
                DimensionLayout("subtask", 8),
            ),
            component_file_names=("subtasks_conf_info_file.bin",),
        ),
    ),
)

FILES = {
    "cbuf": CBUF_FILE,
    "micc": MICC_FILE,
    "insts": FileLayout(
        kind="insts",
        aliases=("insts_file.bin",),
        sections=(SectionLayout(
            name="insts",
            offset=0,
            row_struct="inst_t",
            dimensions=CBUF_FILE.sections[0].dimensions,
            component_file_names=("insts_file.bin",),
        ),),
    ),
    "exeblocks": FileLayout(
        kind="exeblocks",
        aliases=("exeblock_conf_info_file.bin",),
        sections=(SectionLayout(
            name="exeblocks",
            offset=0,
            row_struct="exeBlock_conf_info_t",
            dimensions=CBUF_FILE.sections[1].dimensions,
            component_file_names=("exeblock_conf_info_file.bin",),
        ),),
    ),
    "instances": FileLayout(
        kind="instances",
        aliases=("instance_conf_info_file.bin",),
        sections=(SectionLayout(
            name="instances",
            offset=0,
            row_struct="instance_conf_info_t",
            dimensions=CBUF_FILE.sections[2].dimensions,
            component_file_names=("instance_conf_info_file.bin",),
        ),),
    ),
    "tasks": FileLayout(
        kind="tasks",
        aliases=("tasks_conf_info_file.bin",),
        sections=(SectionLayout(
            name="tasks",
            offset=0,
            row_struct="task_conf_info_t",
            dimensions=MICC_FILE.sections[0].dimensions,
            component_file_names=("tasks_conf_info_file.bin",),
        ),),
    ),
    "subtasks": FileLayout(
        kind="subtasks",
        aliases=("subtasks_conf_info_file.bin",),
        sections=(SectionLayout(
            name="subtasks",
            offset=0,
            row_struct="sub_task_conf_info_t",
            dimensions=MICC_FILE.sections[1].dimensions,
            component_file_names=("subtasks_conf_info_file.bin",),
        ),),
    ),
}

DFU3500_SIMICT_LEGACY_PROFILE = DfuBinaryProfile(
    profile_id="dfu3500_simict_legacy_2026_06_20",
    target="dfu3500",
    schema_version="dfu_binary_profile_v1",
    endian="little",
    layout_status="complete_for_known_fields",
    structs=STRUCTS,
    files=FILES,
    source_refs=(AUDIT,),
    source_fingerprints={
        AUDIT.file: "tracked_repo_note",
        "common/src/inst_def.h": (
            "b263f25e62403d4f1e365aafcec046e76c0c0030f1b6590ac4fb0d90aaa04a4a"
        ),
        "common/src/pe_com_def.h": (
            "2d06ba8afb6f84cc50d120f3a9c6e3612d0b3fe2f48f42349ff27b211099bcae"
        ),
        "common/src/dma_com_def.h": (
            "42bd0593d6dfc4b7e361c49d8191049addb2f851162bccec66575b36fe31fa8b"
        ),
        "common/src/basic_def.h": (
            "a336aca7dec1f40a666f1ef45affb5048e3dcf3e79bb155663faef8c8f1218b7"
        ),
    },
)
