#!/usr/bin/env bash
# sweep.sh — full verification sweep over every bundle in bundles/.
# Runs: ground-truth capture + run + check-count + lint + typecheck +
#       output.txt presence + reference.txt presence.
# Adapted from concept-builder SKILL.md §14.
set -u
cd "$(dirname "$0")/.."

SECTION=bundles
STEMS=$(ls "$SECTION"/*.ts 2>/dev/null | sed 's#.*/##; s#\.ts$##' | sort)

if [ -z "$STEMS" ]; then
  echo "no bundles in $SECTION/"
  exit 0
fi

for name in $STEMS; do
  echo "===== $name ====="
  out="$SECTION/${name}_output.txt"
  ref="$SECTION/${name}_reference.txt"

  # run (exit code)
  if pnpm exec tsx "$SECTION/${name}.ts" >/tmp/"$name".out 2>/tmp/"$name".err; then
    echo "  run: OK"
  else
    echo "  run: FAIL"; cat /tmp/"$name".err
    continue
  fi

  # checks printed
  n=$(grep -c "\[check\]" /tmp/"$name".out 2>/dev/null || echo 0)
  echo "  checks printed: $n"
  [ "$n" -ge 2 ] || echo "  WARN: fewer than 2 [check] lines"

  # typecheck (whole project, once is enough but cheap to repeat)
  # (run once after the loop instead — skipped here per-bundle)

  # output.txt presence + byte-stability
  if [ -s "$out" ]; then
    if diff -q "$out" /tmp/"$name".out >/dev/null 2>&1; then
      echo "  output.txt: present + byte-stable"
    else
      echo "  output.txt: DRIFT (re-run differs from committed) — run: just out $name"
    fi
  else
    echo "  output.txt: MISSING — run: just out $name"
  fi

  # reference.txt presence
  if [ -s "$ref" ]; then
    urls=$(grep -cE "^https?://" "$ref" 2>/dev/null || echo 0)
    echo "  reference.txt: present ($urls URLs)"
  else
    echo "  reference.txt: MISSING"
  fi
done

echo "===== typecheck (whole project) ====="
if pnpm run --silent check 2>/tmp/tsc.err; then
  echo "  tsc --noEmit: OK"
else
  echo "  tsc --noEmit: FAIL"; cat /tmp/tsc.err
fi

echo "===== lint (whole project) ====="
if pnpm run --silent lint 2>/tmp/eslint.err; then
  echo "  eslint: OK"
else
  echo "  eslint: FAIL (see below)"; cat /tmp/eslint.err
fi

echo "===== mermaid blocks (NAME.md) ====="
if [ -f scripts/mermaid_check.mjs ]; then
  node scripts/mermaid_check.mjs . || true
fi

echo "===== html runtime smoke (bundle .html) ====="
if [ -f scripts/html_runtime_check.js ]; then
  node scripts/html_runtime_check.js "$SECTION" || true
fi

echo "===== sweep done ====="
