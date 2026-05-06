#!/usr/bin/env bash
# run.sh — GreenSync unified launcher
#
# Starts ONE sumo-gui instance + the Streamlit dashboard in a single process.
# The Streamlit SimController owns the TraCI connection — no second simulation.
#
# Usage:
#   ./run.sh              → SUMO GUI + Streamlit dashboard (default)
#   ./run.sh --headless   → headless mode (no sumo-gui window)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"

# ── X11 / sumo-gui environment (macOS + XQuartz) ─────────────────────────────
export SUMO_HOME="$VENV/lib/python3.12/site-packages/sumo"
export PROJ_DATA="$SUMO_HOME/data/proj"
export FONTCONFIG_FILE="/opt/homebrew/etc/fonts/fonts.conf"
export DISPLAY=":0"
export XAUTHORITY="$HOME/.Xauthority"

# Ensure project root is on PYTHONPATH so all nav/rsu/simulation imports work
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

# Allow Python subprocesses (sumo-gui) to connect to XQuartz
xhost +local: 2>/dev/null || true

source "$VENV/bin/activate"

if [[ "$1" == "--headless" ]]; then
    echo "Starting GreenSync in headless mode..."
    export GREENSYNC_HEADLESS=1
else
    echo "Starting GreenSync — SUMO GUI + Streamlit dashboard..."
    export GREENSYNC_HEADLESS=0
fi

# Single entry point: Streamlit dashboard drives everything
streamlit run "$SCRIPT_DIR/nav/navigation_dashboard.py" \
    --server.headless false \
    --server.port 8501
