#!/usr/bin/env bash
# Reconfigure independent monitor while retaining historical upload/download samples.
# No changes to PasarGuard, Docker, Xray, node services, or user quotas.
set -Eeuo pipefail
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ $EUID == 0 ]] || fail 'Run as root or sudo.'
for cmd in python3 systemctl; do command -v "$cmd" >/dev/null || fail "Missing $cmd"; done

read -r -p 'Monitor installation directory [/opt/pg-traffic-monitor]: ' DIR
[[ -n "$DIR" ]] || DIR='/opt/pg-traffic-monitor'
[[ "$DIR" == /opt/pg-traffic-monitor || "$DIR" =~ ^/opt/pgtraffic-[a-zA-Z0-9_-]+$ ]] || fail 'Installation path is not in allowlist.'
[[ ! -L "$DIR" && -f "$DIR/config.json" && ! -L "$DIR/config.json" && -d "$DIR/app" ]] || fail 'Monitor config missing or unsafe path.'
CONFIG="$DIR/config.json"
DATA_DIR="$(python3 - "$CONFIG" <<'PY'
import json,sys
with open(sys.argv[1],encoding='utf-8') as f: print(json.load(f)['data_dir'])
PY
)"
case "$DATA_DIR" in
  "$DIR"/data|/var/lib/pgtraffic) ;;
  *) fail 'Unexpected data directory. No changes performed.' ;;
esac
[[ ! -L "$DATA_DIR" && ! -L "$DATA_DIR/traffic.sqlite3" && -f "$DATA_DIR/traffic.sqlite3" ]] || fail 'Unsafe or missing monitoring SQLite.'
echo
echo '=== KEEP TRAFFIC VOLUME / RESET ONLY MONITOR CONFIGURATION ==='
echo "App: $DIR"
echo "Database: $DATA_DIR/traffic.sqlite3"
echo 'Retain: every sample timestamp, node, port, down/up bytes, Xray counter baselines.'
echo 'Reset: monitoring display settings, provider labels, monetary snapshots and password/config.'
echo 'The standalone monitor web and timer will remain disabled until manually reconfigured.'
echo 'PasarGuard, its accounting and node traffic are untouched.'
read -r -p 'Type KEEP TRAFFIC RESET SETTINGS to confirm: ' ANSWER
[[ "$ANSWER" == 'KEEP TRAFFIC RESET SETTINGS' ]] || { echo 'Cancelled.'; exit 0; }

STAMP="$(date -u +%Y%m%dT%H%M%S)-$$"
BACKUP="/var/backups/pgtraffic/preserve-traffic-$STAMP"
[[ ! -L /var/backups/pgtraffic ]] || fail 'Backup path is a symlink.'
install -d -m 700 /var/backups/pgtraffic "$BACKUP"
python3 - "$CONFIG" "$DATA_DIR/traffic.sqlite3" "$BACKUP" <<'PY'
import json,os,sqlite3,sys
from pathlib import Path
config,source,target=map(Path,sys.argv[1:])
with sqlite3.connect(f'file:{source}?mode=ro',uri=True,timeout=30) as original:
    with sqlite3.connect(str(target/'traffic.sqlite3'),timeout=30) as copy:
        original.backup(copy)
with sqlite3.connect(str(target/'traffic.sqlite3')) as db:
    if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
        raise SystemExit('Backup integrity check failed')
    history=db.execute('SELECT COUNT(*),COALESCE(SUM(delta_down),0),COALESCE(SUM(delta_up),0) FROM samples').fetchone()
    states=db.execute('SELECT COUNT(*),COALESCE(SUM(total_down),0),COALESCE(SUM(total_up),0) FROM port_state').fetchone()
(target/'counts.json').write_text(json.dumps({'samples':history,'port_state':states}))
(target/'config.json').write_bytes(config.read_bytes())
for child in target.iterdir():os.chmod(child,0o600)
print('Verified full independent backup:',target)
print('Existing volume samples:',history[0],'; paths:',states[0])
PY

systemctl disable --now pgtraffic-collect.timer pgtraffic-web.service >/dev/null 2>&1 || true
systemctl stop pgtraffic-collect.service >/dev/null 2>&1 || true

python3 - "$DATA_DIR/traffic.sqlite3" "$BACKUP/counts.json" <<'PY'
import json,sqlite3,sys
from pathlib import Path
source,summary=map(Path,sys.argv[1:])
reference=json.loads(summary.read_text())
with sqlite3.connect(str(source),timeout=30) as db:
    db.execute('PRAGMA busy_timeout=30000')
    db.execute('BEGIN IMMEDIATE')
    before=db.execute('SELECT COUNT(*),COALESCE(SUM(delta_down),0),COALESCE(SUM(delta_up),0) FROM samples').fetchone()
    if before[0]<reference['samples'][0]:
        raise SystemExit('Historical samples missing since backup. Aborted.')
    db.execute('UPDATE samples SET bill_bytes=0,rate_snapshot=0,cost=0')
    db.execute('DELETE FROM metadata')
    db.execute('DELETE FROM settings')
    db.execute('DELETE FROM poll_runs')
    after=db.execute('SELECT COUNT(*),COALESCE(SUM(delta_down),0),COALESCE(SUM(delta_up),0) FROM samples').fetchone()
    assert before==after, 'Traffic volume changed; transaction rolled back.'
    print('Retained',after[0],'per-port volume samples and existing Xray baselines.')
PY
rm -f -- "$CONFIG"
echo "Full backup: $BACKUP"
echo 'Settings reset; recorded download/upload preserved. Monitor services disabled.'
echo 'Run GitHub bootstrap install, select same app/data directory, answer Y to update app files.'
echo 'The installer will ask for new settings and password. Do NOT perform full purge.'
