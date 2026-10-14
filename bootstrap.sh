#!/usr/bin/env bash
# Install and update directly from GitHub
# Download repository files temporarily and launch the interactive installer.
set -Eeuo pipefail

if (( EUID != 0 )); then
  echo 'ERROR: Run this command as root or with sudo.' >&2
  exit 1
fi

MODE="${1:-install}"
case "$MODE" in
  install|update) ;;
  *)
    echo 'Usage: bootstrap.sh [install|update]' >&2
    exit 2
    ;;
esac

for cmd in curl tar mktemp bash; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: Missing required command: $cmd" >&2
    exit 1
  fi
done

REPO='amiradineh74/port-manage-pasarguard'
BRANCH='main'
ARCHIVE_URL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
TMP_DIR="$(mktemp -d -t pgtraffic-bootstrap.XXXXXXXX)"
trap 'rm -rf -- "$TMP_DIR"' EXIT
mkdir -p "$TMP_DIR/source"

echo '=== Downloading latest project from GitHub ==='
if ! curl --fail --location --silent --show-error --retry 3 --connect-timeout 15 \
    --max-time 120 "$ARCHIVE_URL" -o "$TMP_DIR/source.tar.gz"; then
  echo 'Download failed. PasarGuard was not modified.' >&2
  exit 1
fi

if ! tar -xzf "$TMP_DIR/source.tar.gz" -C "$TMP_DIR/source" --strip-components=1; then
  echo 'Downloaded archive is invalid. Installation was not started.' >&2
  exit 1
fi

if [[ ! -f "$TMP_DIR/source/app/bridge.py" || ! -f "$TMP_DIR/source/app/collector.py" ]]; then
  echo 'Required project files are missing. Installation was not started.' >&2
  exit 1
fi

if [[ "$MODE" == install ]]; then
  echo '=== Starting interactive installation ==='
  [[ -f "$TMP_DIR/source/install.sh" ]] || { echo 'install.sh was not found.' >&2; exit 1; }
  bash -n "$TMP_DIR/source/install.sh"
  bash "$TMP_DIR/source/install.sh"
else
  echo '=== Starting interactive update ==='
  [[ -f "$TMP_DIR/source/update.sh" ]] || { echo 'update.sh was not found.' >&2; exit 1; }
  bash -n "$TMP_DIR/source/update.sh"
  bash "$TMP_DIR/source/update.sh"
fi

echo '=== Operation finished ==='
