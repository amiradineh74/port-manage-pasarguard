#!/usr/bin/env bash
# Public HTTPS for the standalone traffic dashboard, without changing PasarGuard.
# Caddy runs in a dedicated monitor-only systemd service.
set -Eeuo pipefail

fail() { echo "ERROR: $*" >&2; exit 1; }
[[ $EUID == 0 ]] || fail 'Run this command as root or with sudo.'
for cmd in python3 ss getent systemctl install; do
  command -v "$cmd" >/dev/null 2>&1 || fail "Missing required command: $cmd"
done

DEFAULT_DIR="\${PGTM_DEFAULT_DIR:-/opt/pg-traffic-monitor}"
read -r -p "Existing installation directory [$DEFAULT_DIR]: " DIR
DIR="\${DIR:-$DEFAULT_DIR}"
[[ "$DIR" =~ ^/[a-zA-Z0-9_./-]+$ && "$DIR" != '/' ]] || fail 'Invalid installation directory.'
[[ -f "$DIR/config.json" && -f "$DIR/app/web.py" ]] || fail 'Monitoring installation not found.'

read -r BACKEND_HOST BACKEND_PORT < <(python3 - "$DIR/config.json" <<'PY'
import json,sys
cfg=json.load(open(sys.argv[1], encoding='utf-8'))
print(cfg['listen_host'],cfg['listen_port'])
PY
)
[[ "$BACKEND_HOST" == '127.0.0.1' ]] || fail 'Dashboard must listen on 127.0.0.1 before publishing.'
[[ "$BACKEND_PORT" =~ ^[0-9]+$ && $BACKEND_PORT -ge 1024 && $BACKEND_PORT -le 65535 ]] || fail 'Invalid internal dashboard port.'
if [[ -e /etc/systemd/system/pgtraffic-public.service ]]; then
  fail 'Public HTTPS is already configured. No existing proxy will be overwritten.'
fi

read -r -p 'Public subdomain (existing A record pointing to this server): ' DOMAIN
DOMAIN="\${DOMAIN,,}"
python3 - "$DOMAIN" <<'PY' || fail 'Invalid public subdomain.'
import re,sys
value=sys.argv[1]
assert 4 <= len(value) <= 253
assert '.' in value and not value.endswith('.')
assert all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in value.split('.'))
assert not value.endswith(('.local','.localhost','.internal','.test','.invalid','.example'))
PY

read -r -p 'Public HTTPS port [443]: ' PUBLIC_PORT
PUBLIC_PORT="\${PUBLIC_PORT:-443}"
[[ "$PUBLIC_PORT" =~ ^[0-9]{1,5}$ ]] || fail 'Public HTTPS port must be numeric.'
(( PUBLIC_PORT == 443 || (PUBLIC_PORT >= 1024 && PUBLIC_PORT <= 65535) )) || fail 'Use 443 or a port between 1024 and 65535.'
(( PUBLIC_PORT != BACKEND_PORT )) || fail 'Public port must differ from the local dashboard port.'

DNS_IPS="$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u | paste -sd , - || true)"
[[ -n "$DNS_IPS" ]] || fail 'Domain has no resolvable A record. Configure DNS first.'

# Existing sites and listeners are never stopped or modified.
for port in 80 443 "$PUBLIC_PORT"; do
  if ss -H -ltn "( sport = :$port )" | grep -q .; then
    fail "Port $port is in use. Existing web services will not be modified."
  fi
done
if systemctl is-active --quiet caddy.service 2>/dev/null; then
  fail 'An existing Caddy service is active. This tool will not change it.'
fi

printf '\n=== Confirm public HTTPS setup ===\n'
printf 'Subdomain:     %s\n' "$DOMAIN"
printf 'DNS IPv4:      %s\n' "$DNS_IPS"
printf 'Internal app:  http://127.0.0.1:%s\n' "$BACKEND_PORT"
printf 'Public URL:    https://%s%s\n' "$DOMAIN" "$([[ "$PUBLIC_PORT" == 443 ]] || printf ':%s' "$PUBLIC_PORT")"
printf 'Needs inbound: TCP 80, 443%s (firewall/provider rules are not modified)\n' "$([[ "$PUBLIC_PORT" == 443 ]] || printf ', %s' "$PUBLIC_PORT")"
echo 'May install Caddy and creates only the monitor-owned pgtraffic-public.service.'
echo 'PasarGuard containers, node settings, and user quota accounting are untouched.'
read -r -p 'Proceed? [y/N]: ' OK
[[ "$OK" =~ ^[Yy]$ ]] || { echo 'Cancelled; nothing changed.'; exit 0; }

CADDY_INSTALLED_BY_US=no
if ! command -v caddy >/dev/null 2>&1; then
  command -v apt-get >/dev/null 2>&1 || fail 'Caddy is missing and apt-get is unavailable.'
  echo '=== Installing Caddy from system packages ==='
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y caddy
  CADDY_INSTALLED_BY_US=yes
fi
CADDY_BIN="$(command -v caddy)"
[[ -x "$CADDY_BIN" ]] || fail 'Caddy executable not found.'
if [[ "$CADDY_INSTALLED_BY_US" == yes ]]; then
  # Stop only the stock caddy.service installed by this invocation.
  systemctl disable --now caddy.service 2>/dev/null || true
fi
for port in 80 443 "$PUBLIC_PORT"; do
  if ss -H -ltn "( sport = :$port )" | grep -q .; then
    fail "Port $port became busy. No existing service will be stopped."
  fi
done

PROXY_DIR="$DIR/public-proxy"
CERT_DATA='/var/lib/pgtraffic-caddy'
install -d -m 755 "$PROXY_DIR"
install -d -m 750 -o pgtraffic -g pgtraffic "$CERT_DATA"
SITE="https://$DOMAIN"
[[ "$PUBLIC_PORT" == 443 ]] || SITE="$SITE:$PUBLIC_PORT"
cat > "$PROXY_DIR/Caddyfile.tmp" <<EOF
{
    admin off
}
$SITE {
    reverse_proxy 127.0.0.1:$BACKEND_PORT
}
EOF
"$CADDY_BIN" validate --config "$PROXY_DIR/Caddyfile.tmp" --adapter caddyfile || fail 'Generated Caddy configuration is invalid.'
install -m 644 "$PROXY_DIR/Caddyfile.tmp" "$PROXY_DIR/Caddyfile"
rm -f "$PROXY_DIR/Caddyfile.tmp"

cat > /etc/systemd/system/pgtraffic-public.service <<EOF
[Unit]
Description=Public HTTPS reverse proxy for PasarGuard traffic monitor
After=network-online.target pgtraffic-web.service
Wants=network-online.target
Requires=pgtraffic-web.service
[Service]
Type=simple
User=pgtraffic
Group=pgtraffic
Environment=HOME=$CERT_DATA
Environment=XDG_DATA_HOME=$CERT_DATA/data
Environment=XDG_CONFIG_HOME=$CERT_DATA/config
WorkingDirectory=$PROXY_DIR
ExecStart=$CADDY_BIN run --config $PROXY_DIR/Caddyfile --adapter caddyfile
Restart=on-failure
RestartSec=5
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=$CERT_DATA
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now pgtraffic-web.service
systemctl enable --now pgtraffic-public.service
if ! systemctl is-active --quiet pgtraffic-public.service; then
  fail 'Proxy did not start. Check: journalctl -u pgtraffic-public.service -n 50 --no-pager'
fi
printf '\n=== Public proxy started ===\nURL: https://%s%s\n' "$DOMAIN" "$([[ "$PUBLIC_PORT" == 443 ]] || printf ':%s' "$PUBLIC_PORT")"
echo 'Caddy requests and renews HTTPS certificates automatically if DNS and inbound ports work.'
echo 'Verify externally in a browser. A running service does not prove TLS issuance succeeded.'
echo 'Logs: journalctl -u pgtraffic-public.service -n 40 --no-pager'
