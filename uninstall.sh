#!/usr/bin/env bash
# Uninstall only the independent PasarGuard traffic monitoring app.
# NEVER stops/changes PasarGuard, its Docker containers or its user accounting.
set -Eeuo pipefail
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ $EUID == 0 ]] || fail 'Run as root or with sudo.'

read -r -p 'Installation directory [/opt/pg-traffic-monitor]: ' DIR
DIR="${DIR:-/opt/pg-traffic-monitor}"
[[ "$DIR" == /opt/pg-traffic-monitor || "$DIR" =~ ^/opt/pgtraffic-[a-zA-Z0-9_-]+$ ]] || fail 'Full uninstaller only accepts a known standalone /opt/pgtraffic directory.'
[[ ! -L "$DIR" ]] || fail 'Installation directory cannot be a symlink.'
[[ -f "$DIR/app/collector.py" || -f "$DIR/config.json" ]] || fail 'Monitor installation was not found.'
[[ ! -L "$DIR/config.json" ]] || fail 'Configuration file cannot be a symlink.'

DATA_DIR="$DIR/data"
if [[ -f "$DIR/config.json" ]]; then
  DATA_DIR="$(python3 - "$DIR/config.json" <<'PY'
import json,sys
with open(sys.argv[1],encoding='utf-8') as file:
    print(json.load(file)['data_dir'])
PY
)"
fi
case "$DATA_DIR" in
  "$DIR"/data|/var/lib/pgtraffic) ;;
  *) fail 'Unexpected data directory; no files removed. Review the config and remove manually.' ;;
esac
[[ ! -L "$DATA_DIR" ]] || fail 'Data directory cannot be a symlink.'
[[ ! -L "$DIR/app" ]] || fail 'App directory cannot be a symlink.'

printf '\n=== PasarGuard traffic monitor uninstall ===\n'
echo '1) Remove monitor systemd services, KEEP app files and history'
echo '2) FULL PURGE: services + config + SQLite history + app files + monitor user'
echo '0) Cancel'
read -r -p 'Select [0]: ' MODE
case "$MODE" in
  1) echo 'Stopping and removing only pgtraffic services.' ;;
  2) echo 'WARNING: All traffic-monitor history, configuration, and backups in the installation directory will be permanently deleted.' ;;
  *) echo 'Cancelled; nothing changed.'; exit 0 ;;
esac

if [[ "$MODE" == 2 ]]; then
  printf 'Installation: %s\nMonitor data: %s\n' "$DIR" "$DATA_DIR"
  read -r -p 'Type DELETE PGTRAFFIC to confirm permanent removal: ' CONFIRM
  [[ "$CONFIRM" == 'DELETE PGTRAFFIC' ]] || { echo 'Cancelled; nothing changed.'; exit 0; }
else
  read -r -p 'Remove only monitor services? [y/N]: ' CONFIRM
  [[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo 'Cancelled; nothing changed.'; exit 0; }
fi

# These fixed units belong to this project only. Never touch PasarGuard units.
for unit in pgtraffic-collect.timer pgtraffic-collect.service pgtraffic-web.service pgtraffic-public.service; do
  systemctl disable --now "$unit" >/dev/null 2>&1 || true
done
rm -f -- /etc/systemd/system/pgtraffic-collect.timer \
  /etc/systemd/system/pgtraffic-collect.service \
  /etc/systemd/system/pgtraffic-web.service \
  /etc/systemd/system/pgtraffic-public.service
systemctl daemon-reload
systemctl reset-failed pgtraffic-collect.service pgtraffic-web.service pgtraffic-public.service >/dev/null 2>&1 || true

if [[ "$MODE" == 1 ]]; then
  printf '\nMonitor-only services removed. Config and data remain at: %s\n' "$DIR"
  exit 0
fi

# Strictly guarded paths established before stopping services.
if [[ "$DATA_DIR" != "$DIR/data" && -d "$DATA_DIR" ]]; then
  rm -rf -- "$DATA_DIR"
fi
rm -rf -- "$DIR"
if id pgtraffic >/dev/null 2>&1; then
  if pgrep -u pgtraffic >/dev/null 2>&1; then
    echo 'WARNING: Processes still use pgtraffic user; user account was kept.'
  else
    userdel pgtraffic || echo 'WARNING: Could not remove pgtraffic user.'
  fi
fi

# Optional source checkout: clean, verified GitHub clone only, never a modified repo.
CHECKOUT=/root/port-manage-pasarguard
if [[ -d "$CHECKOUT/.git" && ! -L "$CHECKOUT" ]] && command -v git >/dev/null 2>&1; then
  ORIGIN="$(git -C "$CHECKOUT" remote get-url origin 2>/dev/null || true)"
  case "$ORIGIN" in
    https://github.com/amiradineh74/port-manage-pasarguard|https://github.com/amiradineh74/port-manage-pasarguard.git|git@github.com:amiradineh74/port-manage-pasarguard.git)
      read -r -p 'Also remove CLEAN /root/port-manage-pasarguard source checkout? [y/N]: ' CLONE
      if [[ "$CLONE" =~ ^[Yy]$ ]]; then
        if [[ -z "$(git -C "$CHECKOUT" status --porcelain --untracked-files=all)" ]]; then
          read -r -p 'Type DELETE SOURCE to confirm: ' SURE
          if [[ "$SURE" == 'DELETE SOURCE' ]]; then
            rm -rf -- "$CHECKOUT"
            echo 'Verified clean source checkout removed.'
          fi
        else
          echo 'Source checkout contains modifications/untracked files; it was NOT removed.'
        fi
      fi
      ;;
  esac
fi

echo 'FULL PURGE completed for the standalone traffic monitor.'
echo 'PasarGuard core, node services, user quotas, Docker, and server firewall are untouched.'
echo 'Independent backups manually saved elsewhere are not deleted.'
