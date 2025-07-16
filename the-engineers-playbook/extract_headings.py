#!/usr/bin/env python3
"""
Extract headings from INIT.md and create individual markdown files in the ideas folder.
Each heading becomes a separate file with kebab-case, lowercase filename.
"""

import re
import os
from pathlib import Path

def extract_title_and_emoji(heading_line):
    """Extract title and emoji from a heading line."""
    # Remove the ## prefix and strip whitespace
    title = heading_line.replace('##', '').strip()
    
    # Extract emoji if present
    emoji_match = re.search(r'([^\w\s]+)$', title)
    emoji = emoji_match.group(1) if emoji_match else ''
    
    # Remove emoji from title for filename generation
    title_without_emoji = re.sub(r'[^\w\s]+$', '', title).strip()
    
    return title, title_without_emoji, emoji

def title_to_filename(title):
    """Convert title to kebab-case lowercase filename."""
    # Replace spaces and special characters with hyphens
    filename = re.sub(r'[^\w\s-]', '', title)
    filename = re.sub(r'[-\s]+', '-', filename)
    filename = filename.lower().strip('-')
    return f"{filename}.md"

def extract_section_content(lines, start_index):
    """Extract content from start_index until the next ## heading or end of file."""
    content_lines = []
    i = start_index + 1
    
    while i < len(lines):
        line = lines[i]
        # Stop if we hit another ## heading
        if line.startswith('##'):
            break
        content_lines.append(line)
        i += 1
    
    # Remove trailing empty lines
    while content_lines and content_lines[-1].strip() == '':
        content_lines.pop()
    
    return content_lines

def main():
    """Main function to process INIT.md and create individual files."""
    # Read the INIT.md file
    init_file = Path('INIT.md')
    if not init_file.exists():
        print("Error: INIT.md file not found")
        return
    
    with open(init_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Create ideas directory if it doesn't exist
    ideas_dir = Path('ideas')
    ideas_dir.mkdir(exist_ok=True)
    
    # Process each line and extract headings
    for i, line in enumerate(lines):
        if line.startswith('##'):
            # Extract title information
            title, title_without_emoji, emoji = extract_title_and_emoji(line)
            
            # Generate filename
            filename = title_to_filename(title_without_emoji)
            
            # Extract section content
            content_lines = extract_section_content(lines, i)
            
            # Create the markdown file
            file_path = ideas_dir / filename
            with open(file_path, 'w', encoding='utf-8') as f:
                # Write the heading as title
                f.write(f"# {title}\n\n")
                
                # Write the content
                for content_line in content_lines:
                    f.write(content_line)
            
            print(f"Created: {file_path}")
    
    print(f"\nAll files created in the '{ideas_dir}' directory")

if __name__ == "__main__":
    main()