#!/usr/bin/env bash
# One-time setup for Mac / Linux.
set -e
cd "$(dirname "$0")"

echo "==> Checking tools"
command -v python3 >/dev/null || { echo "Install Python 3.10+ first (https://python.org)"; exit 1; }
if ! command -v ffmpeg >/dev/null; then
  echo "ffmpeg missing. Mac: brew install ffmpeg   Ubuntu: sudo apt install ffmpeg"; exit 1
fi
if ! command -v ollama >/dev/null; then
  echo "Ollama missing. Install from https://ollama.com/download (Mac: brew install ollama)"; exit 1
fi
if ! command -v cargo >/dev/null; then
  echo "==> Installing Rust"
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  . "$HOME/.cargo/env"
fi
if [ "$(uname)" = "Darwin" ]; then
  xcode-select -p >/dev/null 2>&1 || { echo "Run: xcode-select --install   then run setup.sh again"; exit 1; }
else
  if ! pkg-config --exists webkit2gtk-4.1 2>/dev/null; then
    echo "Linux needs: sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev build-essential"
    exit 1
  fi
fi

echo "==> Python environment"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip -q
./.venv/bin/pip install -r requirements.txt

[ -f config.yaml ] || cp config.example.yaml config.yaml

./.venv/bin/python -m playwright install chromium || true
command -v adb >/dev/null || echo "(optional) install adb for the phone: Mac: brew install android-platform-tools  Ubuntu: sudo apt install adb"
echo "Tip: set OLLAMA_NUM_PARALLEL=2 for Ollama so two agents can think at once"
MODEL=$(./.venv/bin/python -c "import sys;sys.path.insert(0,'.');from app import config;print(config.load()['team']['model'])")
echo "==> Downloading AI model $MODEL (one time, a few GB)"
ollama pull "$MODEL"

echo "==> Building the desktop app (first time ~5 min)"
(cd desktop/src-tauri && cargo build --release)
cp desktop/src-tauri/target/release/clipperlocal ./clipperlocal-app

echo
echo "Done! Put your Twitch keys + streamers in config.yaml, then run ./run.sh"
echo "Italy box: see italy-box/README.md"
