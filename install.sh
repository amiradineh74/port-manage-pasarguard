#!/usr/bin/env bash
# Interactive installer. Does not modify PasarGuard Docker Compose, database, Xray, or firewall.
set -Eeuo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run this installer as root or with sudo.'; exit 1; }
for c in python3 docker systemctl install useradd; do command -v "$c" >/dev/null || { echo "Missing required command: $c"; exit 1; }; done
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$ROOT/app/collector.py" ]] || { echo 'The app directory was not found next to install.sh.'; exit 1; }
# Prompt until the input is valid: an accidental terminal arrow-key escape
# sequence must not terminate an otherwise safe interactive installation.
while true; do
  INSTALL_DIR=''
  if ! IFS= read -r -p 'Installation directory (no spaces) [/opt/pg-traffic-monitor]: ' INSTALL_DIR; then
    echo 'Installation cancelled; no files have been changed.' >&2
    exit 1
  fi
  INSTALL_DIR="${INSTALL_DIR:-/opt/pg-traffic-monitor}"
  if [[ "$INSTALL_DIR" =~ ^/[a-zA-Z0-9_./-]+$ && "$INSTALL_DIR" != '/' ]]; then
    break
  fi
  echo 'Invalid directory. Enter an absolute path (e.g. /opt/pg-traffic-monitor), or press Enter for default.' >&2
done
if [[ -e "$INSTALL_DIR/app/collector.py" ]];then
  if [[ -f "$INSTALL_DIR/config.json" ]];then
    read -r -p 'An installation exists. Update the application files? [y/N]: ' q
    [[ "$q" =~ ^[Yy]$ ]] || exit 0
  elif grep -Fq 'Read-only PasarGuard inbound collector' "$INSTALL_DIR/app/collector.py";then
    # Setup may have been cancelled before saving config.json. Resume only the
    # known monitor installation, never ask a novice to uninstall and retry.
    echo 'Incomplete traffic-monitor setup detected (no config.json). Resuming safely.'
  else
    echo 'Unknown collector found without config.json; refusing to overwrite.' >&2
    exit 1
  fi
fi
if ! id pgtraffic >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin pgtraffic
fi
install -d -m 755 "$INSTALL_DIR" "$INSTALL_DIR/app"
for item in "$ROOT"/app/*; do
  [[ -f "$item" ]] && install -m 644 "$item" "$INSTALL_DIR/app/$(basename "$item")"
done
chmod 755 "$INSTALL_DIR/app/collector.py" "$INSTALL_DIR/app/web.py"
echo 'Next, you will be asked to configure the main settings.'
PGTM_DEFAULT_DIR="$INSTALL_DIR" python3 "$INSTALL_DIR/app/setup.py" "$INSTALL_DIR/config.json"
chown root:pgtraffic "$INSTALL_DIR/config.json"
chmod 640 "$INSTALL_DIR/config.json"
DATA_DIR="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["data_dir"])' "$INSTALL_DIR/config.json")"
[[ "$DATA_DIR" =~ ^/[a-zA-Z0-9_./-]+$ && "$DATA_DIR" != '/' ]] || { echo 'Invalid data directory'; exit 1; }
# Never chmod/chown arbitrary paths that might belong to PasarGuard.
case "$DATA_DIR" in
  "$INSTALL_DIR"/data|"$INSTALL_DIR"/data/*|/var/lib/pgtraffic|/var/lib/pgtraffic/*) ;;
  *) echo 'For safety, data must be under INSTALL_DIR/data or /var/lib/pgtraffic.';exit 1;;
esac
install -d -m 770 -o pgtraffic -g pgtraffic "$DATA_DIR"
chmod g+s "$DATA_DIR"
python3 "$INSTALL_DIR/app/collector.py" init --config "$INSTALL_DIR/config.json"
chown pgtraffic:pgtraffic "$DATA_DIR/traffic.sqlite3"
chmod 660 "$DATA_DIR/traffic.sqlite3"
if [[ -f "$DATA_DIR/traffic.sqlite3-wal" ]];then chown pgtraffic:pgtraffic "$DATA_DIR/traffic.sqlite3-wal";fi
cat > /etc/systemd/system/pgtraffic-collect.service <<EOF
[Unit]
Description=PasarGuard inbound monitoring collector (read only)
After=docker.service network-online.target
Wants=network-online.target
[Service]
Type=oneshot
User=root
Group=pgtraffic
UMask=0007
WorkingDirectory=$INSTALL_DIR/app
ExecStart=/usr/bin/python3 $INSTALL_DIR/app/collector.py once --config $INSTALL_DIR/config.json
TimeoutStartSec=90
Nice=12
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=$DATA_DIR
NoNewPrivileges=true
EOF
INTERVAL="$(python3 -c 'import json,sys;print(int(json.load(open(sys.argv[1]))["poll_interval"]))' "$INSTALL_DIR/config.json")"
cat > /etc/systemd/system/pgtraffic-collect.timer <<EOF
[Unit]
Description=Collect PasarGuard inbound counters every $INTERVAL seconds
[Timer]
OnBootSec=60s
OnUnitInactiveSec=${INTERVAL}s
AccuracySec=5s
Persistent=false
Unit=pgtraffic-collect.service
[Install]
WantedBy=timers.target
EOF
cat > /etc/systemd/system/pgtraffic-web.service <<EOF
[Unit]
Description=PasarGuard independent Persian traffic dashboard
After=network.target
[Service]
Type=simple
User=pgtraffic
Group=pgtraffic
UMask=0007
WorkingDirectory=$INSTALL_DIR/app
ExecStart=/usr/bin/python3 $INSTALL_DIR/app/web.py --config $INSTALL_DIR/config.json
Restart=on-failure
RestartSec=5
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=$DATA_DIR
NoNewPrivileges=true
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
printf '\n*** Files installed. Existing PasarGuard containers were not modified. ***\n'
TEST_OK=no
read -r -p 'Run a one-time test collection now? [y/N]: ' TESTNOW
if [[ "$TESTNOW" =~ ^[Yy]$ ]];then
  if python3 "$INSTALL_DIR/app/collector.py" once --config "$INSTALL_DIR/config.json";then
     TEST_OK=yes
  else
     echo 'Test collection failed; scheduled collection will remain disabled.'
  fi
  read -r -p 'Configure port names and rates now? [y/N]: ' META
  [[ "$META" =~ ^[Yy]$ ]] && python3 "$INSTALL_DIR/app/configure_ports.py" --config "$INSTALL_DIR/config.json" || true
fi
read -r -p 'Enable the web dashboard service now? [y/N]: ' STARTWEB
if [[ "$STARTWEB" =~ ^[Yy]$ ]];then systemctl enable --now pgtraffic-web.service;fi
read -r -p 'Enable automatic collection? (Requires successful test) [y/N]: ' STARTTIMER
if [[ "$STARTTIMER" =~ ^[Yy]$ ]];then
  if [[ "$TEST_OK" == yes ]];then
    systemctl enable --now pgtraffic-collect.timer
  else
    echo 'Automatic collection was NOT enabled; a successful test is required first.'
  fi
fi
PORT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["listen_port"])' "$INSTALL_DIR/config.json")"
printf '\nInstallation complete. If you selected localhost, create an SSH tunnel from your PC:\n  ssh -L %s:127.0.0.1:%s root@SERVER_IP\nThen open in your browser: http://127.0.0.1:%s\n' "$PORT" "$PORT" "$PORT"
echo 'Check status: systemctl status pgtraffic-web pgtraffic-collect.timer --no-pager'
echo
read -r -p 'Publish dashboard on a public IP:port using HTTP? (Optional; unencrypted) [y/N]: ' PUBLISH_NOW
if [[ "$PUBLISH_NOW" =~ ^[Yy]$ ]]; then
  [[ -f "$ROOT/publish.sh" ]] || { echo 'publish.sh not found. Run bootstrap.sh publish later.'; exit 1; }
  bash "$ROOT/publish.sh"
fi
