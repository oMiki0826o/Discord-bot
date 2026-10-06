#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_lib.sh"
if ! session_exists "$1"; then
  exit 1
fi
tmux send-keys -t "$1" "save-all flush" C-m
