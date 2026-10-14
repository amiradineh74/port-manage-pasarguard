#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'با sudo اجرا کنید'; exit 1; }
read -r -p 'مسیر نصب [/opt/pg-traffic-monitor]: ' DIR;DIR="${DIR:-/opt/pg-traffic-monitor}"
[[ -f "$DIR/config.json" ]] || { echo 'فایل تنظیمات پیدا نشد';exit 1; }
read -r -p 'فقط سرویس‌های مستقل مانیتورینگ حذف شوند؟ [y/N]: ' OK
[[ "$OK" =~ ^[Yy]$ ]] || exit 0
systemctl disable --now pgtraffic-collect.timer pgtraffic-web.service 2>/dev/null || true
rm -f /etc/systemd/system/pgtraffic-collect.timer /etc/systemd/system/pgtraffic-collect.service /etc/systemd/system/pgtraffic-web.service
systemctl daemon-reload
echo "سرویس‌ها حذف شدند. فایل‌ها و دیتابیس $DIR حذف نشدند."
echo 'برای حفظ سوابق، دیتابیس را نگه دارید یا از آن نسخه پشتیبان بگیرید.'
