#!/usr/bin/env bash
# Host the UNO game from this machine (WSL / Linux / macOS).
cd "$(dirname "$0")" || exit 1
command -v python3 >/dev/null 2>&1 || { echo "python3 not found. Install Python 3 first."; exit 1; }
python3 host_game.py "$@"
