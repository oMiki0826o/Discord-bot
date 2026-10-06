#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_lib.sh"
session="$1"
server_dir="$2"
shift 2
if session_exists "$session"; then
  exit 0
fi
cd "$server_dir"
tmux new-session -d -s "$session" -- "$@"
