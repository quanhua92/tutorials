#!/usr/bin/env python3
"""Auto-fix common mermaid syntax errors in .md files."""

import re
import sys
from pathlib import Path

ALL_SECTIONS = [
    'systemdesign', 'analytics', 'csfundamentals', 'lowleveldesign',
    'observability', 'interview', 'vector-db',
    'db', 'dist', 'devops', 'dsa', 'algo', 'llm',
    'python', 'go', 'rust', 'ts', 'cpp', 'english', 'frontend',
]

def fix_mermaid_block(block):
    """Fix common mermaid syntax errors in a block. Returns (fixed_block, num_fixes)."""
    fixes = 0
    lines = block.split('\n')
    fixed_lines = []
    
    for line in lines:
        original = line
        
        # Fix 1: -.text.> → -.->|text| (dotted arrow with inline label)
        # Pattern: -.some text.> or -.some text.->
        m = re.search(r'-\.(.+?)\.(?:>|->)', line)
        if m and '|' not in m.group(0):
            label = m.group(1)
            line = line.replace(f'-.{label}.>', f'-.->|{label}|')
            line = line.replace(f'-.{label}.->', f'-.->|{label}|')
            if line != original:
                fixes += 1
        
        original2 = line
        
        # Fix 2: quote unquoted node labels containing ( ) that aren't already in [("...")] 
        # Only fix [label with (parens)] that aren't quoted → ["label with (parens)"]
        # But DON'T touch [("...")] (DB/cylinder shape) — those are valid mermaid
        def quote_label(m):
            nonlocal fixes
            bracket_content = m.group(0)  # e.g. [Some text (with parens)]
            inner = m.group(1)
            # Skip if already starts with quote
            if inner.startswith('"') or inner.startswith("'"):
                return bracket_content
            # Skip DB/cylinder shapes [(...)]
            if inner.startswith('(') and inner.endswith(')') and '("' not in inner:
                return bracket_content
            # Skip if it's a style/classDef line
            # Check if the content actually has problematic chars
            clean = re.sub(r'<br\s*/?>', '', inner)
            if '(' in clean or ')' in clean:
                fixes += 1
                return f'["{inner}"]'
            if '/' in clean and not clean.startswith('('):
                fixes += 1
                return f'["{inner}"]'
            return bracket_content
        
        line = re.sub(r'\[([^\]]+)\]', quote_label, line)
        
        if line != original2:
            pass  # already counted in fixes
        
        fixed_lines.append(line)
    
    return '\n'.join(fixed_lines), fixes

def main():
    root = Path(__file__).resolve().parent.parent
    sections = sys.argv[1:] if len(sys.argv) > 1 else ALL_SECTIONS
    
    total_fixes = 0
    files_fixed = 0
    
    for section in sections:
        section_path = root / section
        if not section_path.exists():
            continue
        
        for md_file in sorted(section_path.glob('**/*.md')):
            if 'HOW_TO_RESEARCH' in md_file.name:
                continue
            
            with open(md_file, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
            
            # Find and fix mermaid blocks
            def fix_block_match(m):
                nonlocal total_fixes
                prefix = m.group(1)  # ```mermaid\n
                block = m.group(2)
                suffix = m.group(3)  # ```
                fixed, nfixes = fix_mermaid_block(block)
                total_fixes += nfixes
                return f'{prefix}{fixed}{suffix}'
            
            pattern = r'(```mermaid\n)(.*?)(```)'
            new_text = re.sub(pattern, fix_block_match, text, flags=re.S)
            
            if new_text != text:
                with open(md_file, 'w', encoding='utf-8') as f:
                    f.write(new_text)
                files_fixed += 1
                print(f"  Fixed: {md_file.relative_to(root)}")
    
    print(f"\n{'='*60}")
    print(f"Total: {total_fixes} fixes across {files_fixed} files")

if __name__ == '__main__':
    main()
