#!/usr/bin/env python3
"""Extract vendor seed tables from CSV files.

This tool reads the vendor's CSV template files and generates seed tables
that exactly match the vendor's tag encounter order. This ensures our
operand allocation matches the vendor's TaskResource behavior.
"""

import csv
from pathlib import Path
from typing import List, Tuple, Dict


def extract_tags_from_csv(csv_path: Path) -> List[str]:
    """Extract unique tags from a CSV file in encounter order.
    
    Vendor CSV columns:
    0: inst_name (opcode like HLDT, IMM, HMUL)
    1: inst_tag_name (instruction tag like HLDT0, IMM16)
    2: src_reg_idx0 (source register 0 - can be tensor tag)
    3: src_reg_idx1 (source register 1 - can be tensor tag)
    4: dst_reg_idx (destination register - can be tensor tag like ALPHA, BET)
    
    We need to scan columns 2, 3, 4 for tensor operand tags.
    """
    tags = []
    seen = set()
    
    with open(csv_path, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        
        for row in reader:
            if len(row) < 5:
                continue
            
            # Scan src0, src1, dst columns for tensor tags
            for col_idx in [2, 3, 4]:
                if col_idx < len(row):
                    tag = row[col_idx].strip()
                    if tag and tag not in seen:
                        # Filter: only tensor tags (not numeric register indices)
                        if _is_tensor_tag(tag):
                            tags.append(tag)
                            seen.add(tag)
    
    return tags


def _is_tensor_tag(tag: str) -> bool:
    """Check if a string is a tensor tag (not a numeric register index)."""
    if not tag:
        return False
    # Numeric values are register indices, not tags
    if tag.isdigit() or tag.replace('-', '').isdigit():
        return False
    # Tensor tags have specific prefixes or are ALPHA/BET
    return (tag.startswith('gemm0_') or 
            tag in ('ALPHA', 'BET') or
            tag.startswith('ALPHA@') or 
            tag.startswith('BET@'))


def group_for_tag(tag: str) -> int:
    """Determine tensor group for a tag.
    
    Vendor mapping:
    - Group 0: output tensors (gemm0_output0_*)
    - Group 1: ALPHA, BET, input0 tensors (gemm0_input0_*)
    - Group 2: input1 tensors (gemm0_input1_*)
    """
    if tag.startswith('gemm0_output0_'):
        return 0
    elif tag in ('ALPHA', 'BET') or tag.startswith('gemm0_input0_'):
        return 1
    elif tag.startswith('gemm0_input1_'):
        return 2
    elif tag.startswith('ALPHA@') or tag.startswith('BET@'):
        return 1  # Task-specific ALPHA/BET go in group 1
    else:
        return -1  # unknown


def build_seed_tables(vendor_case_dir: Path, task_idx: int = 0) -> Dict[int, List[str]]:
    """Build seed tables for a given task by reading vendor CSVs.
    
    The seed tables contain all tags encountered in prior tasks,
    ordered by their first appearance in vendor CSV processing order.
    """
    # Collect all tags from prior tasks
    all_tags_by_group: Dict[int, List[str]] = {0: [], 1: [], 2: []}
    
    for prior_task in range(task_idx):
        # Read subtask1, subtask2, subtask3 in order
        for subtask in [1, 2, 3]:
            subtask_dir = vendor_case_dir / f'task{prior_task}' / f'subtask{subtask}' / 'template'
            if not subtask_dir.exists():
                continue
            
            # Read CSV files in numerical order (0.csv, 1.csv, ...)
            csv_files = sorted(subtask_dir.glob('*.csv'), 
                             key=lambda p: int(p.stem) if p.stem.isdigit() else 0)
            
            for csv_file in csv_files:
                tags = extract_tags_from_csv(csv_file)
                for tag in tags:
                    group = group_for_tag(tag)
                    if group >= 0 and tag not in all_tags_by_group[group]:
                        all_tags_by_group[group].append(tag)
    
    return all_tags_by_group


def generate_seed_code(seeds: Dict[int, List[str]], task_idx: int) -> str:
    """Generate Python code for seed tables."""
    lines = [
        f'def _legacy_gemm_tensor_seed_before_input0(task_idx: int = 0) -> dict:',
        f'    """Seed tables for task {task_idx}."""',
        f'    if task_idx != {task_idx}:',
        f'        raise NotImplementedError(f"Seeds not implemented for task {{task_idx}}")',
        f'    ',
        f'    return {{',
    ]
    
    for group in [0, 1, 2]:
        tags = seeds[group]
        lines.append(f'        {group}: (')
        for tag in tags:
            lines.append(f'            "{tag}",')
        lines.append(f'        ),')
    
    lines.append(f'    }}')
    return '\n'.join(lines)


def main():
    vendor_case_dir = Path('/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion')
    
    # Generate seeds for tasks 0-3
    for task_idx in range(4):
        print(f'\n{"="*60}')
        print(f'Task {task_idx} seed tables')
        print(f'{"="*60}\n')
        
        seeds = build_seed_tables(vendor_case_dir, task_idx)
        
        for group in [0, 1, 2]:
            print(f'Group {group}: {len(seeds[group])} tags')
            for i, tag in enumerate(seeds[group]):
                print(f'  [{i:2d}] {tag}')
        
        # Generate code
        code = generate_seed_code(seeds, task_idx)
        print(f'\nGenerated code:\n{code}\n')


if __name__ == '__main__':
    main()
