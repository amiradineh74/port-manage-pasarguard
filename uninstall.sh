#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root or with sudo'; exit 1; }
read -r -p 'Installation directory [/opt/pg-traffic-monitor]: ' DIR;DIR="${DIR:-/opt/pg-traffic-monitor}"
[[ -f "$DIR/config.json" ]] || { echo 'Configuration file not found';exit 1; }
read -r -p 'Remove only the independent monitoring services? [y/N]: ' OK
[[ "$OK" =~ ^[Yy]$ ]] || exit 0
systemctl disable --now pgtraffic-collect.timer pgtraffic-web.service 2>/dev/null || true
rm -f /etc/systemd/system/pgtraffic-collect.timer /etc/systemd/system/pgtraffic-collect.service /etc/systemd/system/pgtraffic-web.service
systemctl daemon-reload
echo "Monitoring services removed. Application files and database at $DIR were NOT deleted."
echo 'Keep the database or create a backup to preserve history.'
