#!/usr/bin/env python3
"""Interactive setup. All configurable values are prompted and documented."""
import getpass
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT = {
 'panel_container':'pasarguard-pasarguard-1',
 'panel_python':'/code/.venv/bin/python',
 'node_ips':[],
 'data_dir':os.environ.get('PGTM_DEFAULT_DIR','/opt/pg-traffic-monitor')+'/data',
 'poll_interval':60,
 'listen_host':'127.0.0.1',
 'listen_port':8791,
 'timezone':'Asia/Tehran',
 'title':'مدیریت مصرف و هزینه پورت‌ها',
 'default_bill_direction':'downlink',
 'default_price_per_gb':0,
 'currency':'تومان',
 'exclude_ports':[22022],
 'ssl_cert':'', 'ssl_key':'',
}

def ask(prompt,default='', validator=None, convert=str):
    while True:
        val=input('%s [%s]: ' % (prompt,default)).strip()
        if not val: val=str(default)
        try:
            out=convert(val)
            if validator and not validator(out): raise ValueError('invalid')
            return out
        except (TypeError,ValueError):
            print('مقدار معتبر نیست؛ دوباره وارد کنید.')

def yesno(prompt,default=False):
    label='Y/n' if default else 'y/N'
    while True:
        s=input('%s [%s]: ' % (prompt,label)).strip().lower()
        if not s:return default
        if s in ('y','yes','بله','آره'):return True
        if s in ('n','no','نه'):return False
        print('لطفاً y یا n وارد کنید.')

def main():
    dest=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/opt/pg-traffic-monitor/config.json')
    cfg=dict(DEFAULT)
    if dest.exists():
        with dest.open(encoding='utf-8') as f: old=json.load(f)
        cfg.update(old)
        if not yesno('تنظیمات موجود ویرایش شود؟',False):
            print('بدون تغییر');return 0
        from datetime import datetime
        import shutil
        backup=dest.with_name('config.backup-'+datetime.now().strftime('%Y%m%d%H%M%S')+'.json')
        shutil.copy2(dest,backup)
        print('نسخه پشتیبان:',backup)
    print('\n=== نصب تعاملی | همه تنظیمات اصلی ===\n')
    cfg['panel_container']=ask('نام کانتینر پنل PasarGuard',cfg['panel_container'])
    cfg['panel_python']=ask('مسیر پایتون داخل کانتینر',cfg['panel_python'])
    ips=ask('IP نودها، جدا با ویرگول (all=همه نودها)',','.join(cfg['node_ips']) or 'all')
    cfg['node_ips']=[x.strip() for x in ips.split(',') if x.strip()] if ips.lower() not in ('all','همه','-') else []
    cfg['data_dir']=ask('مسیر نگهداری دیتابیس مستقل',cfg['data_dir'],lambda s:s.startswith('/'))
    cfg['poll_interval']=ask('فاصله آمارگیری به ثانیه (حداقل ۶۰)',cfg['poll_interval'],lambda n:60<=n<=86400,int)
    cfg['title']=ask('عنوان داشبورد',cfg['title'])
    def timezone_ok(value):
        try:ZoneInfo(value);return True
        except Exception:return False
    cfg['timezone']=ask('منطقه زمانی گزارش‌ها',cfg['timezone'],timezone_ok)
    cfg['listen_host']=ask('آدرس گوش‌دادن وب (127.0.0.1 امن‌تر)',cfg['listen_host'])
    cfg['listen_port']=ask('پورت داشبورد',cfg['listen_port'],lambda n:1024<=n<=65535,int)
    cfg['currency']=ask('واحد پول',cfg['currency'])
    cfg['default_bill_direction']=ask('جهت محاسبه پیش‌فرض: downlink/uplink/both',cfg['default_bill_direction'],lambda s:s in ('downlink','uplink','both'))
    cfg['default_price_per_gb']=ask('هزینه پیش‌فرض هر GB (صفر=بعداً برای هر پورت)',cfg['default_price_per_gb'],lambda n:0<=n<1e12,float)
    ports=ask('پورت‌های مستثنی از آمارگیری، جدا با ویرگول',' ,'.join(map(str,cfg['exclude_ports'])))
    cfg['exclude_ports']=[int(x.strip()) for x in ports.split(',') if x.strip()]
    if cfg['listen_host'] not in ('127.0.0.1','::1','localhost'):
        print('\nهشدار: اتصال عمومی باید پشت HTTPS محافظت شود. وب HTTP عمومی امن نیست.')
        if not yesno('گواهی TLS معتبر برای خود برنامه دارید؟',False):
            raise SystemExit('نصب متوقف شد؛ برای امنیت ابتدا localhost را انتخاب کنید.')
        cfg['ssl_cert']=ask('مسیر مطلق فایل گواهی TLS',cfg.get('ssl_cert',''),lambda s:Path(s).is_file())
        cfg['ssl_key']=ask('مسیر مطلق کلید TLS (دسترسی فقط کاربر سرویس)',cfg.get('ssl_key',''),lambda s:Path(s).is_file())
    else:
        cfg['ssl_cert']='';cfg['ssl_key']=''
    cfg['username']=ask('نام کاربری ورود به داشبورد',cfg.get('username','admin'),lambda s:1<=len(s)<=48)
    print('رمز عبور در ترمینال نمایش داده نمی‌شود.')
    while True:
        p1=getpass.getpass('رمز عبور (حداقل ۱۲ کاراکتر؛ خالی=حفظ قبلی): ')
        if not p1 and cfg.get('password_hash'): break
        if len(p1)<12:
            print('رمز کوتاه است.');continue
        p2=getpass.getpass('تکرار رمز: ')
        if p1!=p2:
            print('دو رمز یکسان نیستند.');continue
        salt=secrets.token_bytes(16)
        iterations=310000
        pw=hashlib.pbkdf2_hmac('sha256',p1.encode('utf-8'),salt,iterations)
        cfg['password_hash']='pbkdf2$%s$%s$%s' % (iterations,salt.hex(),pw.hex())
        break
    if not cfg.get('session_secret'): cfg['session_secret']=secrets.token_hex(32)
    if dest.parent.exists() is False: dest.parent.mkdir(parents=True,exist_ok=True)
    temp=dest.with_suffix('.json.tmp')
    temp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.chmod(temp,0o640)
    os.replace(temp,dest)
    print('\nتنظیمات ذخیره شد:',dest)
    print('رمز عبور فقط به صورت هش ذخیره شده است.')
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (EOFError,KeyboardInterrupt):print('\nنصب لغو شد.');sys.exit(130)
