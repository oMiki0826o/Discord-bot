#!/usr/bin/env bash
set -euo pipefail

session_exists() {
  tmux has-session -t "$1" 2>/dev/null
}
