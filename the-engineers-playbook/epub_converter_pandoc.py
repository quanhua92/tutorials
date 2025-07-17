#!/usr/bin/env python3
"""
Pandoc-based EPUB converter for The Engineer's Playbook
Uses pandoc for proper EPUB generation with working internal links
"""

import os
import subprocess
import argparse
from pathlib import Path
from typing import List, Dict
import tempfile
import re

class PandocEPUBConverter:
    def __init__(self, base_dir: str, output_file: str = "the-engineers-playbook-quanhua92.epub"):
        self.base_dir = Path(base_dir)
        self.tutorials_dir = self.base_dir / "tutorials"
        self.output_file = output_file
        self.temp_dir = Path("temp_epub_pandoc")
        self.tutorial_to_anchor = {}  # Maps tutorial name to heading anchor
        self.file_to_anchor = {}  # Maps full file path to heading anchor
        
    def check_pandoc(self) -> bool:
        """Check if pandoc is installed"""
        try:
            result = subprocess.run(['pandoc', '--version'], 
                                  capture_output=True, text=True)
            return result.returncode == 0
        except FileNotFoundError:
            return False
    
    def get_tutorial_order(self) -> List[str]:
        """Get tutorials in a logical reading order"""
        tutorial_order = [
            "data-structures-algorithms-101",
            "system-design-101",
            
            # Core Data Structures
            "hashing-the-universal-filing-system",
            "sorting-creating-order-from-chaos",
            "heap-data-structures-the-priority-expert",
            "trie-structures-the-autocomplete-expert",
            "b-trees",
            "bloom-filters",
            "skip-lists-the-probabilistic-search-tree",
            "union-find-the-social-network-analyzer",
            "fenwick-trees-the-efficient-summation-machine",
            "segment-trees-the-range-query-specialist",
            "adaptive-data-structures",
            "rope-data-structures-the-string-splicer",
            "radix-trees-the-compressed-prefix-tree",
            "suffix-arrays-the-string-search-specialist",
            "merkle-trees-the-fingerprint-of-data",
            "copy-on-write",
            "delta-compression",
            "lockless-data-structures-concurrency-without-waiting",
            
            # System Optimization
            "caching",
            "batching",
            "compression",
            "columnar-storage",
            "indexing-the-ultimate-table-of-contents",
            "inverted-indexes-the-heart-of-search-engines",
            "ring-buffers-the-circular-conveyor-belt",
            "lsm-trees-making-writes-fast-again",
            "partitioning-the-art-of-slicing-data",
            "sharding-slicing-the-monolith",
            "spatial-indexing-finding-your-place-in-the-world",
            "time-series-databases-the-pulse-of-data",
            
            # Distributed Systems
            "consistent-hashing",
            "append-only-logs",
            "crdts-agreeing-without-asking",
            "event-sourcing",
            "in-memory-storage-the-need-for-speed",
            "materialized-views-the-pre-calculated-answer",
            "probabilistic-data-structures-good-enough-is-perfect",
            "replication-dont-put-all-your-eggs-in-one-basket",
            "write-ahead-logging-wal-durability-without-delay",
        ]
        
        # Add any missing tutorials
        existing_tutorials = [d.name for d in self.tutorials_dir.iterdir() if d.is_dir()]
        for tutorial in existing_tutorials:
            if tutorial not in tutorial_order:
                tutorial_order.append(tutorial)
        
        return tutorial_order
    
    def create_pandoc_heading_id(self, text: str) -> str:
        """Create heading ID exactly like pandoc does"""
        # Pandoc's algorithm:
        # 1. Convert to lowercase
        # 2. Keep only alphanumeric, hyphens, underscores, periods
        # 3. Replace spaces with hyphens
        # 4. Replace multiple consecutive hyphens with single hyphen
        # 5. Remove leading/trailing hyphens
        
        # Convert to lowercase
        text = text.lower()
        
        # Keep only alphanumeric, spaces, hyphens, underscores, periods, colons
        text = re.sub(r'[^\w\s\-.:]+', '', text)
        
        # Replace spaces and colons with hyphens
        text = re.sub(r'[\s:]+', '-', text)
        
        # Replace multiple hyphens with single hyphen
        text = re.sub(r'-+', '-', text)
        
        # Remove leading/trailing hyphens
        text = text.strip('-')
        
        return text
    
    def preprocess_markdown_content(self, content: str, file_path: Path) -> str:
        """Preprocess markdown content to fix internal links"""
        # Replace tutorial directory links with anchors
        def replace_tutorial_link(match):
            tutorial_name = match.group(1)
            if tutorial_name in self.tutorial_to_anchor:
                return f"#{self.tutorial_to_anchor[tutorial_name]}"
            return match.group(0)  # Return original if not found
        
        # Replace links like tutorials/tutorial-name/ with #anchor
        content = re.sub(r'tutorials/([^/\)]+)/?', replace_tutorial_link, content)
        
        # Convert .md file links to proper internal anchors
        if 'tutorials/' in str(file_path):
            def replace_md_link(match):
                link_text = match.group(1)
                md_filename = match.group(2)
                
                # Create the full path for this md file
                tutorial_dir = file_path.parent
                full_md_path = tutorial_dir / md_filename
                
                # Look up the anchor for this file
                if str(full_md_path) in self.file_to_anchor:
                    anchor = self.file_to_anchor[str(full_md_path)]
                    return f'[{link_text}](#{anchor})'
                
                # Fallback: create anchor from filename
                anchor = self.create_pandoc_heading_id(md_filename.replace('.md', ''))
                return f'[{link_text}](#{anchor})'
            
            # Convert relative markdown links to section anchors
            content = re.sub(r'\[([^\]]+)\]\(([^)]+\.md)\)', replace_md_link, content)
        
        return content
    
    def collect_and_preprocess_markdown_files(self) -> List[Path]:
        """Collect all markdown files, preprocess them, and save to temp directory"""
        if self.temp_dir.exists():
            import shutil
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True)
        
        processed_files = []
        
        # First pass: build tutorial to anchor mapping and file to anchor mapping
        tutorial_order = self.get_tutorial_order()
        for tutorial_name in tutorial_order:
            tutorial_path = self.tutorials_dir / tutorial_name
            if not tutorial_path.exists():
                continue
                
            readme_path = tutorial_path / "README.md"
            if readme_path.exists():
                # Read the first heading from README to create anchor
                with open(readme_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Find first heading
                    match = re.search(r'^# (.+)$', content, re.MULTILINE)
                    if match:
                        title = match.group(1)
                        anchor = self.create_pandoc_heading_id(title)
                        self.tutorial_to_anchor[tutorial_name] = anchor
                        self.file_to_anchor[str(readme_path)] = anchor
            
            # Map other files in the tutorial
            file_order = [
                "01-concepts-01-the-core-problem.md",
                "01-concepts-02-the-guiding-philosophy.md", 
                "01-concepts-03-key-abstractions.md",
                "02-guides-01-getting-started.md",
                "02-guides-02-essential-patterns.md",
                "03-deep-dive-01-complexity-analysis.md",
                "03-deep-dive-02-data-structure-design.md",
                "04-python-implementation.md",
                "05-rust-implementation.md",
                "06-go-implementation.md",
                "07-cpp-implementation.md",
                "04-rust-implementation.md",
                "04-sql-examples.md"
            ]
            
            # Add any other files not in the standard order
            existing_files = [f.name for f in tutorial_path.iterdir() 
                            if f.is_file() and f.name.endswith('.md') and f.name != 'README.md']
            for file in existing_files:
                if file not in file_order:
                    file_order.append(file)
            
            # Process files to get their headings
            for filename in file_order:
                file_path = tutorial_path / filename
                if file_path.exists():
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Find first heading
                        match = re.search(r'^# (.+)$', content, re.MULTILINE)
                        if match:
                            title = match.group(1)
                            anchor = self.create_pandoc_heading_id(title)
                            self.file_to_anchor[str(file_path)] = anchor
                        else:
                            # Fallback to filename-based anchor
                            anchor = self.create_pandoc_heading_id(filename.replace('.md', ''))
                            self.file_to_anchor[str(file_path)] = anchor
        
        # Second pass: process and save files
        # Add main README first
        readme_path = self.base_dir / "README.md"
        if readme_path.exists():
            with open(readme_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            processed_content = self.preprocess_markdown_content(content, readme_path)
            
            processed_file = self.temp_dir / "README.md"
            with open(processed_file, 'w', encoding='utf-8') as f:
                f.write(processed_content)
            processed_files.append(processed_file)
        
        # Add tutorials in order
        for tutorial_name in tutorial_order:
            tutorial_path = self.tutorials_dir / tutorial_name
            if not tutorial_path.exists():
                continue
                
            # Add tutorial README first
            readme_path = tutorial_path / "README.md"
            if readme_path.exists():
                with open(readme_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                processed_content = self.preprocess_markdown_content(content, readme_path)
                
                processed_file = self.temp_dir / f"{tutorial_name}-README.md"
                with open(processed_file, 'w', encoding='utf-8') as f:
                    f.write(processed_content)
                processed_files.append(processed_file)
            
            # Add other files in order
            file_order = [
                "01-concepts-01-the-core-problem.md",
                "01-concepts-02-the-guiding-philosophy.md", 
                "01-concepts-03-key-abstractions.md",
                "02-guides-01-getting-started.md",
                "02-guides-02-essential-patterns.md",
                "03-deep-dive-01-complexity-analysis.md",
                "03-deep-dive-02-data-structure-design.md",
                "04-python-implementation.md",
                "05-rust-implementation.md",
                "06-go-implementation.md",
                "07-cpp-implementation.md",
                "04-rust-implementation.md",
                "04-sql-examples.md"
            ]
            
            # Add any other files not in the standard order
            existing_files = [f.name for f in tutorial_path.iterdir() 
                            if f.is_file() and f.name.endswith('.md') and f.name != 'README.md']
            for file in existing_files:
                if file not in file_order:
                    file_order.append(file)
            
            # Add files in order
            for filename in file_order:
                file_path = tutorial_path / filename
                if file_path.exists():
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    processed_content = self.preprocess_markdown_content(content, file_path)
                    
                    processed_file = self.temp_dir / f"{tutorial_name}-{filename}"
                    with open(processed_file, 'w', encoding='utf-8') as f:
                        f.write(processed_content)
                    processed_files.append(processed_file)
        
        return processed_files
    
    def create_title_file(self) -> Path:
        """Create title file with YAML metadata"""
        title_content = '''---
title: "The Engineer's Playbook: Fundamental Data Structures and Algorithms"
author: 
  - Quan Hua
  - Claude Code
rights: "© 2025 Quan Hua. All rights reserved."
language: en-US
description: "Deep, intuitive understanding of the core data structures and algorithms that power modern software systems. Each tutorial follows the Feynman approach: making complex topics feel simple through first-principles thinking, real-world analogies, and hands-on implementation."
subject: 
  - "Computer Science"
  - "Data Structures" 
  - "Algorithms"
  - "System Design"
  - "Programming"
publisher: "Quan Hua"
date: "2025"
...
'''
        
        title_file = self.base_dir / "title.txt"
        with open(title_file, 'w', encoding='utf-8') as f:
            f.write(title_content)
        
        return title_file
    
    def convert(self):
        """Main conversion process using pandoc"""
        print("Checking pandoc installation...")
        if not self.check_pandoc():
            print("ERROR: pandoc is not installed or not found in PATH")
            print("Please install pandoc:")
            print("  macOS: brew install pandoc")
            print("  Ubuntu/Debian: sudo apt install pandoc")
            print("  Windows: Download from https://pandoc.org/installing.html")
            return False
        
        print("Collecting and preprocessing markdown files...")
        markdown_files = self.collect_and_preprocess_markdown_files()
        print(f"Found {len(markdown_files)} markdown files")
        
        print("Creating title file...")
        title_file = self.create_title_file()
        
        print("Converting to EPUB with pandoc...")
        
        # Build pandoc command
        cmd = [
            'pandoc',
            '-o', self.output_file,
            str(title_file)
        ]
        
        # Add all markdown files
        cmd.extend(str(f) for f in markdown_files)
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.base_dir)
            
            if result.returncode == 0:
                print(f"✅ EPUB created successfully: {self.output_file}")
                print(f"📚 Total files processed: {len(markdown_files)}")
                
                # Clean up title file and temp directory
                title_file.unlink()
                if self.temp_dir.exists():
                    import shutil
                    shutil.rmtree(self.temp_dir)
                
                return True
            else:
                print("❌ Error during conversion:")
                print(f"STDOUT: {result.stdout}")
                print(f"STDERR: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Error running pandoc: {e}")
            return False

def main():
    parser = argparse.ArgumentParser(description="Convert Engineer's Playbook to EPUB using pandoc")
    parser.add_argument("--input", "-i", default=".", help="Input directory (default: current directory)")
    parser.add_argument("--output", "-o", default="the-engineers-playbook-quanhua92.epub", help="Output EPUB file")
    
    args = parser.parse_args()
    
    converter = PandocEPUBConverter(args.input, args.output)
    success = converter.convert()
    
    if success:
        print("\n🎉 Conversion completed successfully!")
        print(f"📖 Your EPUB is ready: {args.output}")
        print("\nThe EPUB now has proper internal links that work in most e-readers.")
    else:
        print("\n💥 Conversion failed. Please check the error messages above.")
        exit(1)

if __name__ == "__main__":
    main()