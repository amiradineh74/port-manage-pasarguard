#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root or with sudo';exit 1; }
ROOT="$(cd "$(dirname "$0")" && pwd)"
read -r -p 'Existing installation directory [/opt/pg-traffic-monitor]: ' DIR;DIR="${DIR:-/opt/pg-traffic-monitor}"
[[ -f "$DIR/config.json" && -f "$DIR/app/collector.py" ]] || { echo 'Installation not found';exit 1; }
echo 'Existing configuration and database will be preserved; only application code is updated.'
read -r -p 'Update project files? [y/N]: ' ANS
[[ "$ANS" =~ ^[Yy]$ ]] || exit 0
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
