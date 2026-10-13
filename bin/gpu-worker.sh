#!/usr/bin/env bash
# Claudia GPU worker - installer for Linux (NVIDIA) and macOS (Apple Silicon: audio and matte profiles).
#
# Served by the user's OWN box (`slop gpu serve`); the line `slop gpu pair` prints runs it:
#   curl -fsSL -H 'Authorization: Bearer <code>' 'https://<box>.trycloudflare.com/gpu/install.sh' | \
#     SLOPGPU_URL='https://<box>.trycloudflare.com' SLOPGPU_TOKEN='<code>' bash
# Direct mode (no networking: the bot copied this file and slopgpu-worker.zip into ~/.claudia-gpu/kit first):
#   SLOPGPU_MODE=direct bash ~/.claudia-gpu/kit/gpu-worker.sh
#
# Everything goes under ~/.claudia-gpu: no sudo, nothing system-wide, PATH untouched.
#   1. checks for an NVIDIA GPU (nvidia-smi) or Apple Silicon, and free disk space
#   2. downloads uv 0.12.21 from its official GitHub release and checks its SHA-256
#   3. installs a private Python 3.12 with uv
#   4. unpacks the worker code (from the box, or from the kit) into app/
#   5. writes ~/.claudia-gpu/slopgpu, pairs with the box (paired mode) and starts the worker in the background
# Settings (environment): SLOPGPU_URL + SLOPGPU_TOKEN, SLOPGPU_MODE=direct, SLOPGPU_GPU (pin: UUID or index),
# SLOPGPU_HOME. Remove: ~/.claudia-gpu/slopgpu unpair; rm -rf ~/.claudia-gpu
set -euo pipefail

main() {
  local t0 H MODE UV_VERSION OS ARCH TRIPLE SHA
  t0=$(date +%s)
  H="${SLOPGPU_HOME:-$HOME/.claudia-gpu}"
  MODE="${SLOPGPU_MODE:-paired}"
  UV_VERSION=0.12.21
  say() { printf '[slopgpu] %s\n' "$*"; }
  die() { printf '[slopgpu] ERROR: %s\n' "$*" >&2; exit 1; }

  if [ "$MODE" != direct ] && { [ -z "${SLOPGPU_URL:-}" ] || [ -z "${SLOPGPU_TOKEN:-}" ]; }; then
    die "SLOPGPU_URL / SLOPGPU_TOKEN are not set: paste the WHOLE line that 'slop gpu pair' printed"
  fi
  OS=$(uname -s); ARCH=$(uname -m)
  case "$OS-$ARCH" in
    Linux-x86_64)  TRIPLE=x86_64-unknown-linux-gnu;  SHA=23f02075b652bb1df64178cfae41b5caf160822e720e2663568f3f5d63bc52c0 ;;
    Linux-aarch64) TRIPLE=aarch64-unknown-linux-gnu; SHA=030b69227b40af8c1981b7301793dc66e71ed3c796ea8688209dd268bd91ec51 ;;
    Darwin-arm64)  TRIPLE=aarch64-apple-darwin;      SHA=b88bda573e566ef9bced66b155fe0408626fbbc053aee1c30ba686f0728c9447 ;;
    Darwin-x86_64) die "Intel Macs have no supported GPU for Claudia (Apple Silicon or an NVIDIA PC is needed)" ;;
    *) die "unsupported system $OS-$ARCH" ;;
  esac

  # 1. GPU + disk
  if [ "$OS" = Linux ]; then
    command -v nvidia-smi >/dev/null 2>&1 || die "no NVIDIA GPU found (nvidia-smi is missing). Install the NVIDIA driver (570 or newer) first; AMD/ROCm is not supported yet."
    say "GPUs: $(nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader </dev/null | tr '\n' '|')"
  else
    say "Apple Silicon: the audio and matte profiles run on MPS"
  fi
  mkdir -p "$H/bin" "$H/logs" "$H/cache"
  local free_kb
  free_kb=$(df -Pk "$H" | awk 'NR==2 {print $4}')
  if [ "${free_kb:-0}" -lt $((15 * 1024 * 1024)) ]; then say "WARNING: only $((free_kb / 1024 / 1024)) GB free - the GPU profiles need 5-15 GB"; fi

  # 2. uv (pinned, checksum-verified)
  local uv="$H/bin/uv" have=""
  [ -x "$uv" ] && have=$("$uv" --version </dev/null | awk '{print $2}')
  if [ "$have" != "$UV_VERSION" ]; then
    say "downloading uv $UV_VERSION (official release)"
    local tmp
    tmp=$(mktemp -d)
    curl -fsSL "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$TRIPLE.tar.gz" -o "$tmp/uv.tgz" </dev/null
    local got
    if command -v sha256sum >/dev/null 2>&1; then got=$(sha256sum "$tmp/uv.tgz" | awk '{print $1}'); else got=$(shasum -a 256 "$tmp/uv.tgz" | awk '{print $1}'); fi
    [ "$got" = "$SHA" ] || { rm -rf "$tmp"; die "the uv download has the wrong checksum ($got): refusing it"; }
    tar -xzf "$tmp/uv.tgz" -C "$tmp"
    cp "$(find "$tmp" -type f -name uv | head -n 1)" "$uv"
    chmod 0755 "$uv"
    rm -rf "$tmp"
  fi

  # 3. a private Python 3.12
  export UV_PYTHON_INSTALL_DIR="$H/python" UV_CACHE_DIR="$H/cache/uv" UV_PYTHON_PREFERENCE=only-managed UV_NO_CONFIG=1
  say "installing a private Python 3.12"
  "$uv" python install 3.12 </dev/null >/dev/null 2>&1 || die "uv could not install Python 3.12 (network?)"
  local py
  py=$("$uv" python find 3.12 </dev/null)
  [ -x "$py" ] || die "Python 3.12 not found after the install ($py)"

  # 4. the worker code
  local wz
  wz=$(mktemp)
  if [ "$MODE" = direct ]; then
    [ -f "$H/kit/slopgpu-worker.zip" ] || die "missing $H/kit/slopgpu-worker.zip: copy the kit first (slop gpu direct-plan)"
    cp "$H/kit/slopgpu-worker.zip" "$wz"
  else
    curl -fsSL -H "Authorization: Bearer $SLOPGPU_TOKEN" "${SLOPGPU_URL%/}/gpu/worker.zip" -o "$wz" </dev/null
  fi
  [ -x "$H/slopgpu" ] && "$H/slopgpu" stop </dev/null >/dev/null 2>&1 || true
  rm -rf "$H/app.new"
  "$py" -m zipfile -e "$wz" "$H/app.new" </dev/null
  rm -f "$wz"
  rm -rf "$H/app"
  mv "$H/app.new" "$H/app"

  # 5. launcher, pairing, start
  cat > "$H/slopgpu" <<EOF
#!/bin/sh
SLOPGPU_HOME='$H' PYTHONPATH='$H/app' exec '$py' -m slop.gpu.worker "\$@"
EOF
  chmod 0755 "$H/slopgpu"
  if [ -n "${SLOPGPU_GPU:-}" ]; then
    "$H/slopgpu" pin "$SLOPGPU_GPU" </dev/null >/dev/null || die "could not pin GPU $SLOPGPU_GPU (see: $H/slopgpu gpus)"
    say "pinned to GPU $SLOPGPU_GPU"
  fi
  if [ "$MODE" = direct ]; then
    say "installed in $(( $(date +%s) - t0 )) s (direct mode). Next: $H/slopgpu install audio"
  else
    local out
    out=$("$H/slopgpu" pair --url "$SLOPGPU_URL" </dev/null 2>&1) || die "pairing failed: $out"
    unset SLOPGPU_TOKEN
    say "paired and running (installed in $(( $(date +%s) - t0 )) s). Go back to the bot - it checks with: slop gpu status"
    say "this computer: $H/slopgpu status | stop | start | logs"
  fi
}

main "$@"
