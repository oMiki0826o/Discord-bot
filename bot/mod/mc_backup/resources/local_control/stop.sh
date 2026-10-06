#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_lib.sh"
session="$1"
if ! session_exists "$session"; then
  exit 0
fi
if [[ "${2:-}" == "--kill" ]]; then
  tmux kill-session -t "$session"
  exit 0
fi
tmux send-keys -t "$session" "stop" C-m
