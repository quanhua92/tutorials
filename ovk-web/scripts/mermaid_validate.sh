#!/usr/bin/env bash
# mermaid_validate.sh — thin wrapper around the Node-based validator.
# (Kept for compatibility with the concept-builder SKILL §15.1 reference path.)
set -u
cd "$(dirname "$0")/.."
node scripts/mermaid_check.mjs .
