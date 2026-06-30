#!/usr/bin/env python3
"""Auto-fix common mermaid parse errors in fenced ```mermaid blocks of .md files.

Rules (only touch currently-broken constructs):
  1. Unquoted edge labels `|label|` containing ( ) [ ] { }  -> wrap in double quotes.
     Only matches labels preceded by an arrowhead '>'. Never touches node-text pipes.
  2. Escaped double-quotes inside node text  \"  ->  &quot;

Idempotent. Operates only inside ```mermaid fences. Reports files changed.
"""
import re, sys, pathlib

SPECIAL = set("()[]{}")
FENCE_OPEN = re.compile(r"```mermaid\n")

def quote_edge_labels(block: str) -> str:
    def repl(m):
        label = m.group("label")
        inner = label.strip()
        if inner.startswith('"') and inner.endswith('"'):
            return m.group(0)            # already quoted
        if any(c in SPECIAL for c in label):
            esc = label.replace('"', "&quot;")
            return f'|"{esc}"|'
        return m.group(0)
    # a '>' (arrowhead) then optional spaces then |label|
    return re.sub(r'(?<=>)(?P<ws>\s*)\|(?P<label>[^|\n]*?)\|', repl, block)

def fix_escapes(block: str) -> str:
    return block.replace('\\"', '&quot;')

def fix_block(block: str) -> str:
    b = fix_escapes(block)
    b = quote_edge_labels(b)
    return b

def process_file(path: pathlib.Path) -> bool:
    text = path.read_text()
    if "```mermaid" not in text:
        return False
    out = []
    i = 0
    changed = False
    for m in FENCE_OPEN.finditer(text):
        out.append(text[i:m.end()])           # keep fence line
        start = m.end()
        end = text.find("\n```\n", start)
        if end == -1:                         # last block, EOF
            body = text[start:]
            rest = ""
        else:
            body = text[start:end]
            rest = "\n```\n"
        fixed = fix_block(body)
        if fixed != body:
            changed = True
        out.append(fixed)
        out.append(rest)
        i = end + len("\n```\n") if end != -1 else len(text)
    out.append(text[i:])
    new = "".join(out)
    if changed:
        path.write_text(new)
    return changed

if __name__ == "__main__":
    changed = 0
    for arg in sys.argv[1:]:
        for p in pathlib.Path(arg).rglob("*.md"):
            if "/node_modules/" in str(p) or "/.git/" in str(p):
                continue
            if process_file(p):
                print(f"fixed: {p}")
                changed += 1
    print(f"\n{changed} file(s) changed")
