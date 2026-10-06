#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_lib.sh"
session_exists "$1"
