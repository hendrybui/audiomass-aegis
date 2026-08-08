#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PORT="${AUDIOMASS_PORT:-5055}"
VENV_DIR=".venv"

setup() {
    echo "=== AudioMass + Splinter-X Setup ==="

    # Check ffmpeg
    if ! command -v ffmpeg &>/dev/null; then
        echo "Installing ffmpeg..."
        sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg
    fi
    echo "ffmpeg: $(ffmpeg -version 2>&1 | head -1)"

    # Check demucs
    if ! command -v demucs &>/dev/null; then
        echo "Installing demucs..."
        pip install demucs
    fi
    echo "demucs: $(demucs --version 2>&1 || echo 'installed')"

    # Create venv and install deps
    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating Python venv..."
        python3 -m venv "$VENV_DIR"
    fi

    echo "Installing Python dependencies..."
    "$VENV_DIR/bin/pip" install -r backend/requirements.txt -q

    echo ""
    echo "Setup complete! Run: ./run.sh start"
}

start() {
    echo "=== Starting AudioMass (plain stdlib server + HTDemucs stems, no FastAPI) on port $PORT ==="
    # Resolve venv python to an ABSOLUTE path before cd src — run.sh runs from
    # the project root, but the server itself runs from src/.
    PY="$(cd "$(dirname "$0")" && pwd)/$VENV_DIR/bin/python"
    if [ ! -x "$PY" ]; then
        echo "venv python not found at $PY — falling back to system python3 (stems will NOT work without torch/demucs)" >&2
        PY="python3"
    fi
    cd src
    exec "$PY" audiomass-server.py
}

case "${1:-start}" in
    setup)  setup ;;
    start)  shift 2>/dev/null; start "$@" ;;
    *)      echo "Usage: $0 {setup|start}"; exit 1 ;;
esac
