#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'با sudo اجرا کنید';exit 1; }
ROOT="$(cd "$(dirname "$0")" && pwd)"
read -r -p 'مسیر نصب فعلی [/opt/pg-traffic-monitor]: ' DIR;DIR="${DIR:-/opt/pg-traffic-monitor}"
[[ -f "$DIR/config.json" && -f "$DIR/app/collector.py" ]] || { echo 'نصب پیدا نشد';exit 1; }
echo 'تنظیمات و دیتابیس موجود حفظ می‌شوند؛ فقط کد برنامه عوض می‌شود.'
read -r -p 'آیا فایل‌های پروژه را به‌روزرسانی کنیم؟ [y/N]: ' ANS
[[ "$ANS" =~ ^[Yy]$ ]] || exit 0
# Only own services are restarted, never PasarGuard or nodes.
WAS_ACTIVE=no
if systemctl is-active --quiet pgtraffic-web.service; then
  WAS_ACTIVE=yes
  systemctl stop pgtraffic-web.service
fi
for item in "$ROOT"/app/*;do [[ -f "$item" ]] && install -m 644 "$item" "$DIR/app/$(basename "$item")";done
if [[ "$WAS_ACTIVE" == yes ]];then
  systemctl start pgtraffic-web.service || echo 'داشبورد بالا نیامد؛ با journalctl بررسی کنید.'
fi
echo 'به‌روزرسانی کد تمام شد؛ سرویس‌های PasarGuard دست‌نخورده‌اند.'
