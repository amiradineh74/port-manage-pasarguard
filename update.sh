#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root or with sudo';exit 1; }
ROOT="$(cd "$(dirname "$0")" && pwd)"
read -r -p 'Existing installation directory [/opt/pg-traffic-monitor]: ' DIR;DIR="${DIR:-/opt/pg-traffic-monitor}"
[[ -f "$DIR/config.json" && -f "$DIR/app/collector.py" ]] || { echo 'Installation not found';exit 1; }
echo 'Existing configuration and database will be preserved; only application code is updated.'
read -r -p 'Update project files? [y/N]: ' ANS
[[ "$ANS" =~ ^[Yy]$ ]] || exit 0
# Online SQLite backup keeps all past traffic even while the independent timer is active.
# Backups are stored outside the installation directory and are root-only.
python3 - "$DIR/config.json" <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3
import sys

config = Path(sys.argv[1])
settings = json.loads(config.read_text(encoding="utf-8"))
source = Path(settings["data_dir"]) / "traffic.sqlite3"
if not source.is_file() or source.is_symlink():
    raise SystemExit("ERROR: Monitoring database is missing/invalid. Update stopped.")
base = Path("/var/backups/pgtraffic")
base.mkdir(mode=0o700, parents=True, exist_ok=True)
if base.is_symlink():
    raise SystemExit("ERROR: Backup directory must not be a symlink.")
os.chmod(base, 0o700)
name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
destination = base / name
destination.mkdir(mode=0o700)
try:
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=20) as original:
        with sqlite3.connect(str(destination / "traffic.sqlite3"), timeout=20) as copy:
            original.backup(copy)
    shutil.copyfile(config, destination / "config.json")
    for file in destination.iterdir():
        os.chmod(file, 0o600)
except Exception:
    shutil.rmtree(destination)
    raise
print("Independent monitoring DB and config backed up to:", destination)
PY
# Only own services are restarted, never PasarGuard or nodes.
WAS_ACTIVE=no
if systemctl is-active --quiet pgtraffic-web.service; then
  WAS_ACTIVE=yes
  systemctl stop pgtraffic-web.service
fi
for item in "$ROOT"/app/*;do [[ -f "$item" ]] && install -m 644 "$item" "$DIR/app/$(basename "$item")";done
if [[ "$WAS_ACTIVE" == yes ]];then
  systemctl start pgtraffic-web.service || echo 'The dashboard failed to start. Check journalctl.'
fi
echo 'Update finished. PasarGuard services were not modified.'
