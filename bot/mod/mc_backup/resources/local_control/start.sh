#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_lib.sh"
session="$1"
shift
if session_exists "$session"; then
  exit 0
fi
tmux new-session -d -s "$session" -- "$@"
