#!/usr/bin/env bash
# Publish only the independent traffic dashboard via plain HTTP on an IPv4:port.
# This DOES NOT modify PasarGuard, its containers, user accounting, or the firewall.
set -Eeuo pipefail

fail() { echo "ERROR: $*" >&2; exit 1; }
[[ $EUID == 0 ]] || fail 'Run as root or with sudo.'
for cmd in python3 systemctl ss curl mktemp cp mv chmod; do
  command -v "$cmd" >/dev/null 2>&1 || fail "Missing required command: $cmd"
done

DEFAULT_DIR="${PGTM_DEFAULT_DIR:-/opt/pg-traffic-monitor}"
read -r -p "Existing monitoring installation directory [$DEFAULT_DIR]: " DIR
DIR="${DIR:-$DEFAULT_DIR}"
[[ "$DIR" =~ ^/[a-zA-Z0-9_./-]+$ && "$DIR" != '/' ]] || fail 'Invalid installation directory.'
CONFIG="$DIR/config.json"
[[ -f "$CONFIG" && -f "$DIR/app/web.py" ]] || fail 'Monitoring app/config not found.'

CURRENT_PORT="$(python3 - "$CONFIG" <<'PY'
import json,sys
cfg=json.load(open(sys.argv[1], encoding='utf-8'))
print(cfg['listen_port'])
PY
)"
read -r -p 'Public IPv4 address (for displaying the URL): ' IP
python3 - "$IP" <<'PY' || fail 'Enter a valid public IPv4 address.'
import ipaddress,sys
try:
    ip=ipaddress.IPv4Address(sys.argv[1])
    assert ip.is_global
except (ValueError,AssertionError):
    sys.exit(1)
PY

read -r -p "Public dashboard port [${CURRENT_PORT}]: " PORT
PORT="${PORT:-$CURRENT_PORT}"
[[ "$PORT" =~ ^[0-9]+$ ]] || fail 'Port must be numeric.'
(( 1024 <= 10#$PORT && 10#$PORT <= 65535 )) || fail 'Port must be between 1024 and 65535.'
PORT="$((10#$PORT))"

CURRENT_HOST="$(python3 - "$CONFIG" <<'PY'
import json,sys
cfg=json.load(open(sys.argv[1], encoding='utf-8'))
print(cfg['listen_host'])
PY
)"
read -r CURRENT_SSL_CERT CURRENT_SSL_KEY < <(python3 - "$CONFIG" <<'PY'
import json,sys
cfg=json.load(open(sys.argv[1], encoding='utf-8'))
print(cfg.get('ssl_cert','') or 'NONE',cfg.get('ssl_key','') or 'NONE')
PY
)
[[ "$CURRENT_SSL_CERT" == NONE && "$CURRENT_SSL_KEY" == NONE ]] || fail 'Existing TLS configuration detected. Public HTTP setup will not disable it.'

# A first-time publication legitimately reuses the current web listener:
# pgtraffic-web already binds 127.0.0.1:CURRENT_PORT. A listener owned by
# another service (or an unidentifiable PID) must still block publication.
# Check every listener, including those bound to another interface.
LISTENERS="$(ss -H -ltnp "( sport = :$PORT )")"
if [[ -n "$LISTENERS" ]]; then
  OWNER_PID=''
  if [[ "$PORT" == "$CURRENT_PORT" ]] && systemctl is-active --quiet pgtraffic-web.service; then
    OWNER_PID="$(systemctl show -p MainPID --value pgtraffic-web.service)"
  fi
  if [[ ! "$OWNER_PID" =~ ^[1-9][0-9]*$ ]]; then
    fail "Port $PORT is already in use by an unverified service. Choose another port."
  fi
  while IFS= read -r LISTENER; do
    if [[ "$LISTENER" != *"pid=$OWNER_PID,"* ]]; then
      fail "Port $PORT has a listener not owned by pgtraffic-web.service. Choose another port."
    fi
  done <<< "$LISTENERS"
  echo "Port $PORT is already bound by this dashboard; it can be reused safely."
fi

printf '\n=== Publish dashboard via public HTTP ===\n'
printf 'URL:        http://%s:%s\n' "$IP" "$PORT"
printf 'Application: %s\n' "$DIR/app/web.py"
echo 'WARNING: HTTP is NOT encrypted. Passwords and sessions can be intercepted.'
echo 'Use a unique password, not one shared with SSH/PasarGuard.'
echo 'Only the monitor service/config will be changed; firewall rules remain unchanged.'
read -r -p 'Expose the monitoring dashboard publicly via HTTP? [y/N]: ' OK
[[ "$OK" =~ ^[Yy]$ ]] || { echo 'Cancelled; nothing changed.'; exit 0; }

BACKUP="$(mktemp "$DIR/.config-before-public.XXXXXXXX")"
cp -p -- "$CONFIG" "$BACKUP"
chmod 600 "$BACKUP"
TEMP="$(mktemp "$DIR/.config-public.XXXXXXXX")"
trap 'rm -f -- "$TEMP"' EXIT
cp -p -- "$CONFIG" "$TEMP"
python3 - "$TEMP" "$PORT" <<'PY'
import json,sys
p=sys.argv[1]
with open(p,encoding='utf-8') as f: cfg=json.load(f)
cfg['listen_host']='0.0.0.0'
cfg['listen_port']=int(sys.argv[2])
with open(p,'w',encoding='utf-8') as f:
    json.dump(cfg,f,ensure_ascii=False,indent=2)
    f.write('\n')
PY
mv -f -- "$TEMP" "$CONFIG"

if ! systemctl restart pgtraffic-web.service; then
  cp -p -- "$BACKUP" "$CONFIG"
  systemctl restart pgtraffic-web.service || true
  fail 'Dashboard restart failed. Original configuration restored.'
fi
sleep 2
if ! systemctl is-active --quiet pgtraffic-web.service; then
  cp -p -- "$BACKUP" "$CONFIG"
  systemctl restart pgtraffic-web.service || true
  fail 'Dashboard exited. Original configuration restored.'
fi
LOCAL_CODE="$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/" || true)"
if [[ "$LOCAL_CODE" != 303 && "$LOCAL_CODE" != 200 ]]; then
  cp -p -- "$BACKUP" "$CONFIG"
  systemctl restart pgtraffic-web.service || true
  fail "Dashboard HTTP probe failed ($LOCAL_CODE). Original configuration restored."
fi
systemctl enable pgtraffic-web.service >/dev/null

printf '\n=== Dashboard is listening on public port %s ===\n' "$PORT"
printf 'Open: http://%s:%s\n' "$IP" "$PORT"
echo 'If it is not reachable from the internet, check your hosting provider firewall.'
echo "Local config backup (root only): $BACKUP"
echo 'Collection timer was not enabled or modified.'
