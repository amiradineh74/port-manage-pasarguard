#!/usr/bin/env bash
# نصب تعاملی؛ هیچ تغییری در Docker Compose / دیتابیس / Xray / فایروال PasarGuard نمی‌دهد.
set -Eeuo pipefail
[[ $(id -u) == 0 ]] || { echo 'این نصب‌کننده را با sudo اجرا کنید.'; exit 1; }
for c in python3 docker systemctl install useradd; do command -v "$c" >/dev/null || { echo "ابزار موردنیاز پیدا نشد: $c"; exit 1; }; done
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$ROOT/app/collector.py" ]] || { echo 'پوشه app کنار install.sh پیدا نشد.'; exit 1; }
read -r -p 'مسیر نصب (بدون فاصله) [/opt/pg-traffic-monitor]: ' INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-/opt/pg-traffic-monitor}"
[[ "$INSTALL_DIR" =~ ^/[a-zA-Z0-9_./-]+$ ]] || { echo 'مسیر باید مطلق و بدون فاصله باشد.'; exit 1; }
[[ "$INSTALL_DIR" != '/' ]] || exit 1
if [[ -e "$INSTALL_DIR/app/collector.py" ]];then
  read -r -p 'نصب قبلی وجود دارد. فقط فایل‌های برنامه به‌روزرسانی شوند؟ [y/N]: ' q
  [[ "$q" =~ ^[Yy]$ ]] || exit 0
fi
if ! id pgtraffic >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin pgtraffic
fi
install -d -m 755 "$INSTALL_DIR" "$INSTALL_DIR/app"
for item in "$ROOT"/app/*; do
  [[ -f "$item" ]] && install -m 644 "$item" "$INSTALL_DIR/app/$(basename "$item")"
done
chmod 755 "$INSTALL_DIR/app/collector.py" "$INSTALL_DIR/app/web.py"
echo 'در مرحله بعد همه تنظیمات اصلی پرسیده می‌شوند.'
PGTM_DEFAULT_DIR="$INSTALL_DIR" python3 "$INSTALL_DIR/app/setup.py" "$INSTALL_DIR/config.json"
chown root:pgtraffic "$INSTALL_DIR/config.json"
chmod 640 "$INSTALL_DIR/config.json"
DATA_DIR="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["data_dir"])' "$INSTALL_DIR/config.json")"
[[ "$DATA_DIR" =~ ^/[a-zA-Z0-9_./-]+$ && "$DATA_DIR" != '/' ]] || { echo 'مسیر data نامعتبر است'; exit 1; }
# Never chmod/chown arbitrary paths that might belong to PasarGuard.
case "$DATA_DIR" in
  "$INSTALL_DIR"/data|"$INSTALL_DIR"/data/*|/var/lib/pgtraffic|/var/lib/pgtraffic/*) ;;
  *) echo 'برای جلوگیری از تغییر مجوز پوشه‌های PasarGuard، داده باید زیر مسیر نصب/data یا /var/lib/pgtraffic باشد.';exit 1;;
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
printf '\n*** نصب فایل‌ها انجام شد؛ هیچ تغییری در کانتینرهای پنل داده نشده. ***\n'
TEST_OK=no
read -r -p 'یک نمونه‌برداری آزمایشی الان انجام شود؟ [y/N]: ' TESTNOW
if [[ "$TESTNOW" =~ ^[Yy]$ ]];then
  if python3 "$INSTALL_DIR/app/collector.py" once --config "$INSTALL_DIR/config.json";then
     TEST_OK=yes
  else
     echo 'نمونه‌برداری موفق نبود؛ زمان‌بندی فعال نخواهد شد.'
  fi
  read -r -p 'نام/تعرفه پورت‌ها را تعاملی تنظیم می‌کنید؟ [y/N]: ' META
  [[ "$META" =~ ^[Yy]$ ]] && python3 "$INSTALL_DIR/app/configure_ports.py" --config "$INSTALL_DIR/config.json" || true
fi
read -r -p 'سرویس داشبورد وب فعال شود؟ [y/N]: ' STARTWEB
if [[ "$STARTWEB" =~ ^[Yy]$ ]];then systemctl enable --now pgtraffic-web.service;fi
read -r -p 'آمارگیری دوره‌ای فعال شود؟ (فقط بعد از تست موفق) [y/N]: ' STARTTIMER
if [[ "$STARTTIMER" =~ ^[Yy]$ ]];then
  if [[ "$TEST_OK" == yes ]];then
    systemctl enable --now pgtraffic-collect.timer
  else
    echo 'زمان‌بندی فعال نشد؛ ابتدا نمونه‌برداری دستی موفق لازم است.'
  fi
fi
PORT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["listen_port"])' "$INSTALL_DIR/config.json")"
printf '\nپایان نصب. اگر localhost انتخاب کردید، از سیستم خودتان SSH tunnel بزنید:\n  ssh -L %s:127.0.0.1:%s root@SERVER_IP\nسپس مرورگر: http://127.0.0.1:%s\n' "$PORT" "$PORT" "$PORT"
echo 'وضعیت: systemctl status pgtraffic-web pgtraffic-collect.timer --no-pager'
