#!/usr/bin/env bash
# Builds dist/ClipperLocal-Setup.exe on Linux: cross-compiles the Windows app, stages the files, runs makensis.
# Needs: rust with the x86_64-pc-windows-gnu target, mingw-w64, nsis, and installer/uv.exe (from the uv PyPI wheel).
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(grep -m1 '"version"' desktop/src-tauri/tauri.conf.json | sed 's/.*: "\(.*\)".*/\1/')
TARGET=x86_64-pc-windows-gnu
echo "==> Windows app $VERSION"
(cd desktop/src-tauri && cargo build --release --target $TARGET)
REL=desktop/src-tauri/target/$TARGET/release
[ -f installer/uv.exe ] || { echo "installer/uv.exe missing: pip download uv --platform win_amd64 --only-binary=:all: --no-deps, unzip, copy uv.exe"; exit 1; }

STAGE=dist/stage
rm -rf "$STAGE" && mkdir -p "$STAGE/tools" "$STAGE/installer"
# app code (what git tracks, minus things Windows doesn't use)
git ls-files -co --exclude-standard \
  | grep -v -E '^(\.github/|setup\.sh|run\.sh|installer/(build_installer\.sh|clipperlocal\.nsi|uv\.exe)|italy-box/(proxy/|italybox\.nsi)|desktop/src-tauri/(icons|capabilities|Cargo\.|build\.rs|gen/))' \
  | while read -r f; do [ -f "$f" ] && mkdir -p "$STAGE/$(dirname "$f")" && cp "$f" "$STAGE/$f"; done
cp "$REL/clipperlocal.exe" "$STAGE/ClipperLocal.exe"
cp "$REL/WebView2Loader.dll" "$STAGE/WebView2Loader.dll"
cp installer/uv.exe "$STAGE/tools/uv.exe"
cp desktop/src-tauri/icons/icon.ico "$STAGE/installer/icon.ico"
find "$STAGE" -name __pycache__ -prune -exec rm -rf {} +
echo "==> Installer"
makensis -V2 -DVERSION="$VERSION" -DSTAGE="$PWD/$STAGE" -NOCD installer/clipperlocal.nsi
mv ClipperLocal-Setup.exe dist/

echo "==> Italy box installer"
(cd italy-box/proxy && cargo build --release --target $TARGET)
IB=dist/italybox-stage
rm -rf "$IB" && mkdir -p "$IB"
cp italy-box/proxy/target/$TARGET/release/italybox-proxy.exe italy-box/setup-italy-box.ps1 italy-box/README.md "$IB/"
cp desktop/src-tauri/icons/icon.ico "$IB/icon.ico"
makensis -V2 -DSTAGE="$PWD/$IB" -NOCD italy-box/italybox.nsi
mv ItalyBox-Setup.exe dist/
ls -la dist/*.exe
