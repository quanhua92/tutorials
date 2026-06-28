#!/usr/bin/env python3
"""Sweep all .md files in section folders for mermaid blocks and check syntax.

Usage:
    python3 scripts/mermaid_check.py                    # check all 20 sections
    python3 scripts/mermaid_check.py systemdesign        # check one section
    python3 scripts/mermaid_check.py systemdesign db     # check specific sections
"""

import re
import sys
from pathlib import Path

ALL_SECTIONS = [
    'systemdesign', 'analytics', 'csfundamentals', 'lowleveldesign',
    'observability', 'interview', 'vector-db',
    'db', 'dist', 'devops', 'dsa', 'algo', 'llm',
    'python', 'go', 'rust', 'ts', 'cpp', 'english', 'frontend',
]

def extract_mermaid_blocks(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()
    return [(m.start(0), m.group(1)) for m in re.finditer(r'```mermaid\n(.*?)```', text, re.S)]

def get_line_number(full_text, offset):
    return full_text[:offset].count('\n') + 1

def check_block(block, filename, line_offset):
    """Return list of (line_in_block, error_msg)."""
    errors = []
    lines = block.split('\n')

    diagram_types = {
        'graph td', 'graph lr', 'graph bt', 'graph rl',
        'flowchart td', 'flowchart lr', 'flowchart bt', 'flowchart rl',
        'sequencediagram', 'classdiagram', 'statediagram', 'statediagram-v2',
        'erdiagram', 'gantt', 'pie', 'journey',
        'quadrantchart', 'requirementdiagram', 'gitgraph',
        'c4context', 'c4container', 'c4component', 'mindmap',
    }

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith('%%'):
            continue

        lower = stripped.lower()

        # Skip diagram type declaration
        if lower in diagram_types:
            continue
        if lower.startswith(('title ', 'accent ', 'direction ')):
            continue

        # --- Check 1: dotted-arrow inline label -.text.> (should be -.->|text|) ---
        if re.search(r'-\.[^|]*\.(?:>|->)', stripped):
            errors.append((i, f"dotted-arrow label syntax: use -.->|label| instead of -.text.>"))

        # --- Check 2: unquoted [] labels with special chars ---
        for m in re.finditer(r'\[([^\]]+)\]', stripped):
            label = m.group(1)
            if label.startswith('"') or label.startswith("'"):
                continue
            if any(k in stripped for k in ('classDef', 'style ', 'linkStyle', 'class ')):
                continue
            clean = re.sub(r'<br\s*/?>', '', label)
            for ch in ['/', '&', '>', '(', ')']:
                if ch in clean:
                    errors.append((i, f"unquoted [{label}] contains special char → quote it: [\"{label}\"]"))

        # --- Check 3: unquoted () labels with / ---
        for m in re.finditer(r'\(([^)]+)\)', stripped):
            label = m.group(1)
            if label.startswith('"') or label.startswith("'"):
                continue
            if len(label) < 4:
                continue
            clean = re.sub(r'<br\s*/?>', '', label)
            if '/' in clean:
                errors.append((i, f"unquoted ({label}) contains slash → quote it"))

        # --- Check 4: subgraph unquoted title with special chars ---
        if lower.startswith('subgraph '):
            title = stripped[len('subgraph '):]
            if not (title.startswith('"') or title.startswith("'")):
                if any(ch in title for ch in '/&()'):
                    errors.append((i, f'unquoted subgraph title: "{title}"'))

        # --- Check 5: bare > in arrow context (not -->, -.->, ==>) ---
        # e.g. "A > B" instead of "A --> B"
        if re.search(r'[A-Za-z\]]\s+>\s+[A-Za-z]', stripped) and '-->' not in stripped and '-.->' not in stripped and '==>' not in stripped:
            if not stripped.startswith(('quadrant', 'x-axis', 'y-axis', 'quadrant-')):
                errors.append((i, f"bare '>' — did you mean '-->'?"))

        # --- Check 6: |pipe labels| with unescaped special sequences ---
        for m in re.finditer(r'\|([^|]+)\|', stripped):
            label = m.group(1)
            if '..' in label:
                errors.append((i, f"edge label |{label}| contains '..'"))

    return errors

def main():
    root = Path(__file__).resolve().parent.parent
    sections = sys.argv[1:] if len(sys.argv) > 1 else ALL_SECTIONS

    total_blocks = 0
    total_errors = 0
    results = {}

    for section in sections:
        section_path = root / section
        if not section_path.exists():
            continue

        md_files = sorted(section_path.glob('**/*.md'))
        section_blocks = 0
        section_errors = []

        for md_file in md_files:
            if 'HOW_TO_RESEARCH' in md_file.name:
                continue

            with open(md_file, 'r', encoding='utf-8', errors='replace') as f:
                full_text = f.read()

            blocks = extract_mermaid_blocks(md_file)
            for idx, (offset, block) in enumerate(blocks):
                section_blocks += 1
                file_line = get_line_number(full_text, offset)
                errs = check_block(block, md_file, file_line)
                for line_in_block, msg in errs:
                    abs_line = file_line + line_in_block
                    rel_path = md_file.relative_to(root)
                    section_errors.append(f"  {rel_path}:L{abs_line} (block#{idx+1}): {msg}")

        total_blocks += section_blocks
        total_errors += len(section_errors)
        if section_errors:
            results[section] = (section_blocks, section_errors)

    # Report
    for section, (nblocks, errs) in sorted(results.items()):
        print(f"\n{'='*60}")
        print(f"{section}/ ({nblocks} blocks, {len(errs)} errors)")
        print(f"{'='*60}")
        for e in errs:
            print(e)

    print(f"\n{'='*60}")
    print(f"Total: {total_blocks} mermaid blocks, {total_errors} errors across {len(results)} sections")
    if total_errors == 0:
        print("ALL CLEAN ✓")

    return 1 if total_errors > 0 else 0

if __name__ == '__main__':
    sys.exit(main())
