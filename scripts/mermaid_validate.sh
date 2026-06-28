#!/bin/bash
# Validate every mermaid block in every .md file using mmdc.
# Usage: nohup bash scripts/mermaid_validate.sh > /tmp/mermaid_results.txt 2>&1 &

set -e
TMPDIR=$(mktemp -d)
PASS=0
FAIL=0
TOTAL=0

process_block() {
    local idx="$1" mdfile="$2" blockfile="$3"
    local outfile="${TMPDIR}/out_${idx}.svg"
    npx @mermaid-js/mermaid-cli -i "$blockfile" -o "$outfile" > /dev/null 2>&1
    if [ -f "$outfile" ]; then
        echo -e "PASS\t${mdfile}\t${idx}"
        rm -f "$outfile"
    else
        echo -e "FAIL\t${mdfile}\t${idx}"
    fi
}

# Extract all mermaid blocks
echo "Extracting mermaid blocks..."
python3 -c "
import re
from pathlib import Path
idx = 0
for md in sorted(Path('.').rglob('*.md')):
    p = str(md)
    if '.git/' in p or 'the-engineers-playbook/' in p or 'HOW_TO_RESEARCH' in md.name:
        continue
    text = md.read_text(errors='replace')
    for m in re.finditer(r'\`\`\`mermaid\n(.*?)\`\`\`', text, re.S):
        with open(f'${TMPDIR}/block_{idx}.mmd', 'w') as f:
            f.write(m.group(1))
        print(f'{idx}\t{p}\t${TMPDIR}/block_{idx}.mmd')
        idx += 1
" > "${TMPDIR}/blocks.txt"

TOTAL=$(wc -l < "${TMPDIR}/blocks.txt")
echo "Found $TOTAL mermaid blocks. Validating..."

# Validate in parallel (4 workers)
while IFS=$'\t' read -r idx mdfile blockfile; do
    process_block "$idx" "$mdfile" "$blockfile" &
    while [ $(jobs -r | wc -l) -ge 4 ]; do sleep 0.2; done
done < "${TMPDIR}/blocks.txt"
wait

echo ""
echo "=============================================="
echo "DONE: $TOTAL blocks validated"
echo "=============================================="
rm -rf "$TMPDIR"
