#!/usr/bin/env bash
# run.sh — GreenSync launcher
#
# Exports X11 env vars so sumo-gui can open via XQuartz,
# then runs the Python pipeline (which launches sumo-gui internally via traci.start).
#
# Usage:
#   ./run.sh              → GUI mode  (HEADLESS=False in main.py)
#   ./run.sh --headless   → headless  (overrides main.py setting)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"

# ── X11 / sumo-gui environment (macOS + XQuartz) ──────────────────────────────
export SUMO_HOME="$VENV/lib/python3.12/site-packages/sumo"
export PROJ_DATA="$SUMO_HOME/data/proj"
export FONTCONFIG_FILE="/opt/homebrew/etc/fonts/fonts.conf"
export DISPLAY=":0"
export XAUTHORITY="$HOME/.Xauthority"

# Allow local processes (including Python subprocesses) to connect to XQuartz.
# Without this, sumo-gui launched as a Python subprocess is blocked by X11 auth.
xhost +local: 2>/dev/null || true

source "$VENV/bin/activate"

if [[ "$1" == "--headless" ]]; then
    echo "🚀 Running in headless mode..."
    python -c "
import main
main.HEADLESS = True
main.run()
"
else
    echo "🐍 Starting GreenSync..."
    python main.py
fi
