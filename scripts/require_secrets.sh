#!/usr/bin/env bash
# Used by workflows: fail early, naming every required secret that is empty. Never prints values.
# usage: scripts/require_secrets.sh NAME [NAME...]   (values come from env vars of the same name)
set -euo pipefail
missing=()
for name in "$@"; do
  if [ -z "${!name:-}" ]; then missing+=("$name"); fi
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "::error::Missing repository secret(s): ${missing[*]}. Add them under Settings -> Secrets and variables -> Actions (or run 'make secrets')."
  exit 1
fi
echo "All required secrets present: $*"
