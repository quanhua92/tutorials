#!/usr/bin/env bash
# scripts/mermaid-check.sh
#
# Extract every ```mermaid fenced block from Markdown files and validate it
# with @mermaid-js/mermaid-cli (`mmdc`). Exits non-zero if any block fails to
# parse, so it can gate pre-commit hooks / CI.
#
# Usage:
#   scripts/mermaid-check.sh                       # scan CWD recursively
#   scripts/mermaid-check.sh interview/            # scan one directory
#   scripts/mermaid-check.sh interview/DESIGN.md   # scan one file
#   scripts/mermaid-check.sh -j 8 interview/       # 8 parallel validators
#
# Requires: `mmdc` on PATH  ->  npm i -g @mermaid-js/mermaid-cli

set -uo pipefail

JOBS=4
PATHS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -j|--jobs) JOBS="${2:?'-j' needs a number}"; shift 2 ;;
    -h|--help) sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)         PATHS+=("$1"); shift ;;
  esac
done
[ ${#PATHS[@]} -eq 0 ] && PATHS=(".")

command -v mmdc >/dev/null 2>&1 || {
  echo "error: 'mmdc' not found.  npm i -g @mermaid-js/mermaid-cli" >&2
  exit 2
}

# Gather markdown files, skipping noise.
FILES=()
while IFS= read -r line; do FILES+=("$line"); done < <(
  find "${PATHS[@]}" -type f -name '*.md' \
    -not -path '*/.git/*' \
    -not -path '*/node_modules/*' \
    -not -path '*/vendor/*' 2>/dev/null
)
[ ${#FILES[@]} -eq 0 ] && { echo "no markdown files found under: ${PATHS[*]}"; exit 0; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
MMD="$WORK/mmd"; SVG="$WORK/svg"; mkdir -p "$MMD" "$SVG"
JOBFILE="$WORK/jobs.txt"; : > "$JOBFILE"

# Extract blocks. awk emits one "src<TAB>idx<TAB>mmdpath" line per closed block.
fid=0
for f in "${FILES[@]}"; do
  fid=$((fid+1))
  awk -v dir="$MMD" -v src="$f" -v fid="$fid" '
    function path(n){ return dir "/b_" fid "_" n ".mmd" }
    /^```[ \t]*mermaid[ \t]*$/ { inb=1; idx++; fn=path(idx); next }
    /^```[ \t]*$/              { if (inb){ print src "\t" idx "\t" fn; inb=0 } next }
    inb                        { print >> fn }
  ' "$f" >> "$JOBFILE"
done

TOTAL=$(wc -l < "$JOBFILE" | tr -d ' ')
[ "$TOTAL" -eq 0 ] && { echo "no mermaid blocks found."; exit 0; }
echo "validating $TOTAL mermaid block(s) across ${#FILES[@]} file(s) with $JOBS workers..."

export SVG WORK
validate_block() {
  local src="$1" idx="$2" mmd="$3" err base
  base="$(basename "$mmd" .mmd)"
  if err="$(mmdc -i "$mmd" -o "$SVG/$base.svg" 2>&1 >/dev/null)"; then
    printf 'ok    %s  #%s\n' "$src" "$idx"
    return 0
  fi
  printf 'FAIL  %s  #%s\n' "$src" "$idx"
  printf '%s\n' "$err" | grep -E 'Parse error|Expecting|^Error|error:' | head -3 | sed 's/^/        /'
  return 1
}
export -f validate_block

worker() { local IFS=$'\t'; set -- $1; validate_block "$1" "$2" "$3"; }
export -f worker

FAILLOG="$WORK/fails.txt"; : > "$FAILLOG"
while IFS= read -r line; do
  printf '%s\0' "$line"
done < "$JOBFILE" \
  | xargs -0 -P "$JOBS" -I{} bash -c 'worker "$@" || echo fail >> "$0"' "$FAILLOG" {}

FAILS=$(wc -l < "$FAILLOG" | tr -d ' ')
echo "-----"
if [ "$FAILS" -eq 0 ]; then
  echo "all $TOTAL block(s) render."
  exit 0
fi
echo "FAILED: $FAILS/$TOTAL block(s) did not render."
exit 1
