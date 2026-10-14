#!/usr/bin/env bash
# راه‌انداز نصب و به‌روزرسانی مستقیم از GitHub
# فقط فایل‌های مخزن را موقتاً دانلود می‌کند و نصب‌کننده تعاملی را اجرا می‌کند.
set -Eeuo pipefail

if (( EUID != 0 )); then
  echo 'خطا: این دستور را به‌عنوان root یا با sudo اجرا کنید.' >&2
  exit 1
fi

MODE="${1:-install}"
case "$MODE" in
  install|update) ;;
  *)
    echo 'روش استفاده: bootstrap.sh [install|update]' >&2
    exit 2
    ;;
esac

for cmd in curl tar mktemp bash; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "خطا: ابزار موردنیاز نصب نیست: $cmd" >&2
    exit 1
  fi
done

REPO='amiradineh74/port-manage-pasarguard'
BRANCH='main'
ARCHIVE_URL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
TMP_DIR="$(mktemp -d -t pgtraffic-bootstrap.XXXXXXXX)"
trap 'rm -rf -- "$TMP_DIR"' EXIT
mkdir -p "$TMP_DIR/source"

echo '=== دریافت آخرین نسخه پروژه از GitHub ==='
if ! curl --fail --location --silent --show-error --retry 3 --connect-timeout 15 \
    --max-time 120 "$ARCHIVE_URL" -o "$TMP_DIR/source.tar.gz"; then
  echo 'دانلود ناموفق بود. روی PasarGuard هیچ تغییری انجام نشد.' >&2
  exit 1
fi

if ! tar -xzf "$TMP_DIR/source.tar.gz" -C "$TMP_DIR/source" --strip-components=1; then
  echo 'فایل دانلودشده معتبر نیست؛ نصب انجام نشد.' >&2
  exit 1
fi

if [[ ! -f "$TMP_DIR/source/app/bridge.py" || ! -f "$TMP_DIR/source/app/collector.py" ]]; then
  echo 'فایل‌های اصلی پروژه ناقص هستند؛ نصب انجام نشد.' >&2
  exit 1
fi

if [[ "$MODE" == install ]]; then
  echo '=== اجرای نصب‌کننده تعاملی فارسی ==='
  [[ -f "$TMP_DIR/source/install.sh" ]] || { echo 'install.sh پیدا نشد.' >&2; exit 1; }
  bash -n "$TMP_DIR/source/install.sh"
  bash "$TMP_DIR/source/install.sh"
else
  echo '=== اجرای به‌روزرسانی تعاملی ==='
  [[ -f "$TMP_DIR/source/update.sh" ]] || { echo 'update.sh پیدا نشد.' >&2; exit 1; }
  bash -n "$TMP_DIR/source/update.sh"
  bash "$TMP_DIR/source/update.sh"
fi

echo '=== عملیات به پایان رسید ==='
