#!/usr/bin/env python3
"""Persian, dependency-free web dashboard. Bind to localhost by default."""
import argparse
import base64
import csv
from datetime import datetime, date, time, timedelta, timezone
from io import StringIO
import hashlib
import hmac
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import ssl
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from storage import connect
from units import selected_unit, selected_bytes_per_unit
from fixed_costs import validate_expense, expenses_report, fixed_total
from supplier_wallets import (wallet_report,create_account,update_account,attach_port,
    add_credit,report_balance,reconcile_balance,assign_provider_wallet,sync_provider_port)

CFG = None
ROOT = Path(__file__).resolve().parent
SESSION_AGE = 12 * 3600


def secure_password(candidate):
    try:
        _, rounds, salt, digest = CFG['password_hash'].split('$')
        computed = hashlib.pbkdf2_hmac('sha256',candidate.encode('utf-8'),bytes.fromhex(salt),int(rounds))
        return hmac.compare_digest(computed,bytes.fromhex(digest))
    except (ValueError,KeyError): return False


def mac(payload):
    return hmac.new(bytes.fromhex(CFG['session_secret']),payload.encode(),hashlib.sha256).hexdigest()


def make_token():
    payload='%s:%s' % (int(datetime.now(timezone.utc).timestamp())+SESSION_AGE,secrets.token_hex(16))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip('=')+'.'+mac(payload)


def verify_token(token):
    try:
        b,sig=token.rsplit('.',1)
        payload=base64.urlsafe_b64decode(b+'='*(-len(b)%4)).decode()
        expiry=int(payload.split(':',1)[0])
        return len(token)<512 and hmac.compare_digest(mac(payload),sig) and expiry>datetime.now(timezone.utc).timestamp()
    except (ValueError,IndexError,UnicodeError):return False


def display_preferences(db):
    """Mutable presentation settings live in the monitor SQLite, not PasarGuard."""
    defaults={'title':CFG.get('title','مدیریت ترافیک'),
              'currency':CFG.get('currency','تومان'),
              'timezone':CFG.get('timezone','Asia/Tehran')}
    values={r['key']:r['value'] for r in
            db.execute("SELECT key,value FROM settings WHERE key IN ('display_title','display_currency','display_timezone')")}
    # Legacy installations used Toman as their default display label. Show Rial by
    # default without changing the stored Toman rates or any historical snapshots.
    if 'display_currency' not in values and defaults['currency'] in ('Toman','تومان'):
        defaults['currency']='ریال'
    return {key:values.get('display_'+key,default) for key,default in defaults.items()}


def utc_bounds(params, timezone_name=None):
    tz=ZoneInfo(timezone_name or CFG.get('timezone','Asia/Tehran'))
    now=datetime.now(tz).date()
    lo=params.get('from',[(now-timedelta(days=6)).isoformat()])[0]
    hi=params.get('to',[now.isoformat()])[0]
    try:
        d1=date.fromisoformat(lo); d2=date.fromisoformat(hi)
    except ValueError:raise ValueError('تاریخ نامعتبر است')
    if d1>d2 or (d2-d1).days>365*5:raise ValueError('بازه تاریخ نامعتبر است')
    start=datetime.combine(d1,time.min,tzinfo=tz).astimezone(timezone.utc).isoformat(timespec='seconds')
    end=datetime.combine(d2+timedelta(days=1),time.min,tzinfo=tz).astimezone(timezone.utc).isoformat(timespec='seconds')
    return start,end,lo,hi


def dashboard(params):
    with connect(Path(CFG['data_dir'])/'traffic.sqlite3', CFG.get('traffic_unit')) as db:
        divisor=selected_bytes_per_unit(db)
        preferences=display_preferences(db)
        begin,end,lo,hi=utc_bounds(params,preferences['timezone'])
        ports=db.execute('''SELECT p.node_id,p.port,p.node_name,p.node_address,p.tag,p.last_seen,
         p.total_down,p.total_up,COALESCE(m.title,'') title,COALESCE(m.provider,'') provider,
         COALESCE(m.price_per_gb,?) price_per_gb,
         COALESCE(m.bill_direction,?) bill_direction,
         COALESCE(m.enabled,1) enabled,COALESCE(m.notes,'') notes,
         COALESCE(m.billing_since,'') billing_since
         FROM port_state p LEFT JOIN metadata m ON m.node_id=p.node_id AND m.port=p.port
         ORDER BY p.node_name,p.port''',
         (CFG.get('default_price_per_gb',0),CFG.get('default_bill_direction','downlink'))).fetchall()
        groups=db.execute('''SELECT s.node_id,s.port,
         SUM(s.delta_down) down, SUM(s.delta_up) up,
         SUM(s.bill_bytes) historical_billed, SUM(s.cost) historical_cost, COUNT(*) samples,
         SUM(CASE WHEN s.event!='ok' THEN 1 ELSE 0 END) events
         FROM samples s LEFT JOIN metadata m ON m.node_id=s.node_id AND m.port=s.port
         WHERE s.collected_at>=? AND s.collected_at<?
           AND COALESCE(m.enabled,1)=1
           AND (m.billing_since IS NULL OR m.billing_since='' OR s.collected_at>=m.billing_since)
         GROUP BY s.node_id,s.port''', (begin,end)).fetchall()
        lookup={(r['node_id'],r['port']):dict(r) for r in groups}
        combined=[]
        for row in ports:
            p=dict(row)
            p.update(lookup.get((p['node_id'],p['port']),
                {'down':0,'up':0,'historical_billed':0,'historical_cost':0,'samples':0,'events':0}))
            # Current-rate estimate recalculates all recorded traffic within the
            # reporting window with the *current* direction and rate. Historical
            # accounting stays untouched, including incorrectly entered old rates.
            p['billed']={'downlink':p['down'],'uplink':p['up'],
                         'both':p['down']+p['up']}[p['bill_direction']]
            p['cost']=p['billed']*p['price_per_gb']/divisor
            combined.append(p)
        # Daily totals, aggregated at SQLite layer (UTC bucket; browser converts labels).
        times=db.execute(f'''SELECT substr(s.collected_at,1,10) day,
         SUM(s.delta_down) down,SUM(s.delta_up) up,
         SUM(CASE COALESCE(m.bill_direction,?)
             WHEN 'downlink' THEN s.delta_down
             WHEN 'uplink' THEN s.delta_up
             ELSE s.delta_up + s.delta_down END) billed,
         SUM((CASE COALESCE(m.bill_direction,?)
             WHEN 'downlink' THEN s.delta_down
             WHEN 'uplink' THEN s.delta_up
             ELSE s.delta_up + s.delta_down END)
             * COALESCE(m.price_per_gb,?) / {divisor}.0) cost,
         SUM(s.cost) historical_cost
         FROM samples s LEFT JOIN metadata m ON m.node_id=s.node_id AND m.port=s.port
         WHERE s.collected_at>=? AND s.collected_at<?
           AND COALESCE(m.enabled,1)=1
           AND (m.billing_since IS NULL OR m.billing_since='' OR s.collected_at>=m.billing_since)
         GROUP BY substr(s.collected_at,1,10) ORDER BY day''',
         (CFG.get('default_bill_direction','downlink'),
          CFG.get('default_bill_direction','downlink'),
          CFG.get('default_price_per_gb',0),begin,end)).fetchall()
        # Per-provider UTC buckets for historical trend and cost drilldowns.
        # Rates/directions in this chart match the current-price estimate.
        provider_time_query = f'''SELECT substr(s.collected_at,1,BUCKET_LEN) period,
          s.node_id,MAX(s.node_name) node_name,
          COALESCE(NULLIF(m.provider,''),'بدون ارائه‌دهنده') provider,
          SUM(s.delta_down) down, SUM(s.delta_up) up,
          SUM(CASE COALESCE(m.bill_direction,?)
            WHEN 'downlink' THEN s.delta_down
            WHEN 'uplink' THEN s.delta_up
            ELSE s.delta_up+s.delta_down END) billed,
          SUM((CASE COALESCE(m.bill_direction,?)
            WHEN 'downlink' THEN s.delta_down
            WHEN 'uplink' THEN s.delta_up
            ELSE s.delta_up+s.delta_down END)
            * COALESCE(m.price_per_gb,?) / {divisor}.0) cost,
          SUM(s.cost) historical_cost
          FROM samples s LEFT JOIN metadata m
            ON m.node_id=s.node_id AND m.port=s.port
          WHERE s.collected_at>=? AND s.collected_at<?
            AND COALESCE(m.enabled,1)=1
            AND (m.billing_since IS NULL OR m.billing_since='' OR s.collected_at>=m.billing_since)
          GROUP BY period,provider,s.node_id ORDER BY period,provider,s.node_id'''
        provider_params=(CFG.get('default_bill_direction','downlink'),
                         CFG.get('default_bill_direction','downlink'),
                         CFG.get('default_price_per_gb',0),begin,end)
        daily_by_provider=[dict(row) for row in db.execute(
            provider_time_query.replace('BUCKET_LEN','10'),provider_params).fetchall()]
        # Hourly drilldown is useful for short periods only; avoid transferring
        # tens of thousands of groups for year-long reports.
        show_hourly=(date.fromisoformat(hi)-date.fromisoformat(lo)).days<=31
        hourly_by_provider=[dict(row) for row in db.execute(
            provider_time_query.replace('BUCKET_LEN','13'),provider_params).fetchall()] if show_hourly else []
        last=db.execute('SELECT collected_at,node_count,sample_count,errors_json FROM poll_runs ORDER BY id DESC LIMIT 1').fetchone()
        providers={}
        for p in combined:
            if not p['enabled']: continue
            name=p['provider'] or 'بدون ارائه‌دهنده'
            v=providers.setdefault(name,{'billed':0,'cost':0,'down':0,'up':0,
                                         'historical_cost':0})
            for col in v:v[col]+=p[col]
        total={x:sum(p[x] for p in combined if p['enabled'])
               for x in ('down','up','billed','cost','historical_cost')}
        fixed_expenses=expenses_report(db,lo,hi)
        return {'ports':combined,'daily':[dict(t) for t in times],
                'daily_by_provider':daily_by_provider,
                'hourly_by_provider':hourly_by_provider,
                'hourly_available':show_hourly,
                'providers':providers,
                'total':total,'period':{'from':lo,'to':hi},
                'last_run':dict(last) if last else None,
                'title':preferences['title'],'currency':preferences['currency'],
                'timezone':preferences['timezone'],
                'fixed_expenses':fixed_expenses,
                'fixed_expenses_total_rial':fixed_total(fixed_expenses),
                'wallets':wallet_report(db), 'traffic_unit':selected_unit(db)}


def csrf_for(token):return mac('csrf:'+token)


def html_response(page):return (ROOT/page).read_bytes()

class Handler(BaseHTTPRequestHandler):
    server_version='TrafficMonitor/1.0'
    def log_message(self, format, *args):
        # Avoid leaking headers/cookies. URI excludes credentials (in POST body).
        if not self.path.startswith('/api/'):
            super().log_message(format,*args)

    def headers_base(self, status=200, ctype='application/json; charset=utf-8', extra=None):
        self.send_response(status)
        self.send_header('Content-Type',ctype)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; style-src 'self' 'unsafe-inline'; script-src 'self'")
        if extra:
            for k,v in extra.items():self.send_header(k,v)
        self.end_headers()

    def send_bytes(self,data,status=200,ctype='text/html; charset=utf-8',extra=None):
        self.headers_base(status,ctype,extra)
        self.wfile.write(data)

    def send_json(self,data,status=200):
        self.send_bytes(json.dumps(data,ensure_ascii=False,default=str).encode('utf-8'),status,'application/json; charset=utf-8')

    def token(self):
        cookie=SimpleCookie()
        try: cookie.load(self.headers.get('Cookie',''))
        except Exception:return ''
        tok=cookie.get('pgtraffic_session')
        val=tok.value if tok else ''
        return val if verify_token(val) else ''

    def read_body(self):
        size=int(self.headers.get('Content-Length','0'))
        if size<0 or size>16384:raise ValueError('درخواست بیش از حد بزرگ است')
        return self.rfile.read(size)

    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/login':return self.send_bytes(html_response('login.html'))
        token=self.token()
        if not token:return self.redirect('/login') if path in ('/','/index.html') else self.send_json({'error':'ورود لازم است'},401)
        if path in ('/','/index.html'):return self.send_bytes(html_response('dashboard.html'))
        if path=='/dashboard.js':return self.send_bytes(html_response('dashboard.js'),ctype='application/javascript; charset=utf-8')
        if path=='/jalali.js':return self.send_bytes(html_response('jalali.js'),ctype='application/javascript; charset=utf-8')
        if path=='/style.css':return self.send_bytes(html_response('style.css'),ctype='text/css; charset=utf-8')
        if path=='/api/wallets':
            with connect(Path(CFG['data_dir'])/'traffic.sqlite3') as db:
                return self.send_json({'accounts':wallet_report(db)})
        if path=='/api/dashboard':
            try:
                params=parse_qs(urlsplit(self.path).query)
                data=dashboard(params)
                data['csrf']=csrf_for(token)
                return self.send_json(data)
            except ValueError as e:return self.send_json({'error':str(e)},400)
        if path=='/api/export.csv':return self.export_csv(parse_qs(urlsplit(self.path).query))
        if path=='/api/expenses.csv':return self.export_expenses_csv(parse_qs(urlsplit(self.path).query))
        return self.send_json({'error':'یافت نشد'},404)

    def redirect(self,where,extra=None):
        self.send_response(303)
        self.send_header('Location',where)
        self.send_header('Cache-Control','no-store')
        for k,v in (extra or {}).items():self.send_header(k,v)
        self.end_headers()

    def do_POST(self):
        path=urlsplit(self.path).path
        if path=='/login':
            try:
                f=parse_qs(self.read_body().decode('utf-8'))
                ok=hmac.compare_digest(f.get('username',[''])[0],CFG['username']) and secure_password(f.get('password',[''])[0])
            except (ValueError,UnicodeDecodeError,KeyError):ok=False
            if ok:
                t=make_token()
                c='pgtraffic_session=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%s' % (t,SESSION_AGE)
                if CFG.get('ssl_cert'):c+='; Secure'
                return self.redirect('/',{'Set-Cookie':c})
            return self.send_bytes('<html lang="fa" dir="rtl"><meta charset="utf-8"><p>نام کاربری یا رمز اشتباه است. <a href="/login">بازگشت</a></p></html>'.encode(),401)
        token=self.token()
        if not token:return self.send_json({'error':'ورود لازم است'},401)
        if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),csrf_for(token)):
            return self.send_json({'error':'خطای تأیید درخواست'},403)
        if path=='/api/logout':
            return self.redirect('/login',{'Set-Cookie':'pgtraffic_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict'})
        # These mutations affect only this independent monitor's SQLite,
        # never PasarGuard accounts, bots, or live Xray quota counters.
        if path=='/api/providers/wallet':
            try:
                payload=json.loads(self.read_body())
                with connect(Path(CFG['data_dir'])/'traffic.sqlite3') as db:
                    with db:
                        account_id=assign_provider_wallet(db,payload)
                return self.send_json({'ok':True,'id':account_id})
            except (ValueError,TypeError,KeyError,OverflowError) as exc:
                return self.send_json({'error':str(exc)},400)
            except __import__('sqlite3').IntegrityError:
                return self.send_json({'error':'این ارائه‌دهنده قبلاً حساب اعتبار دارد'},400)
        if path in ('/api/wallets/create','/api/wallets/edit',
                    '/api/wallets/attach','/api/wallets/credit',
                    '/api/wallets/reported','/api/wallets/reconcile'):
            try:
                payload=json.loads(self.read_body())
                if type(payload) is not dict:raise ValueError('درخواست نامعتبر است')
                handlers={
                  '/api/wallets/create':create_account,
                  '/api/wallets/edit':update_account,
                  '/api/wallets/attach':attach_port,
                  '/api/wallets/credit':add_credit,
                  '/api/wallets/reported':report_balance,
                  '/api/wallets/reconcile':reconcile_balance,
                }
                with connect(Path(CFG['data_dir'])/'traffic.sqlite3') as db:
                    with db:
                        if path in ('/api/wallets/reconcile','/api/wallets/reported'):
                            db.execute('BEGIN IMMEDIATE')  # lock consistent balance snapshot
                        result=handlers[path](db,payload)
                return self.send_json({'ok':True,'id':result if type(result) is int else result.get('account_id'), 'result':result})
            except (ValueError,TypeError,KeyError,OverflowError) as err:
                return self.send_json({'error':str(err)},400)
            except __import__('sqlite3').IntegrityError:
                return self.send_json({'error':'این اتصال یا اطلاعات از قبل ثبت شده است'},400)
        if path=='/api/visible-ports':
            try:
                obj=json.loads(self.read_body())
                if type(obj) is not dict: raise ValueError('Invalid request')
                node_id=obj.get('node_id')
                visible=obj.get('visible_ports')
                if type(node_id) is not int or node_id < 1: raise ValueError('Invalid node ID')
                if type(visible) is not list or len(visible)>65535 or any(
                    type(p) is not int or p < 1 or p > 65535 for p in visible
                ) or len(set(visible)) != len(visible):
                    raise ValueError('Invalid port selection')
                with connect(Path(CFG['data_dir'])/'traffic.sqlite3') as db:
                    available={r['port'] for r in db.execute(
                        'SELECT port FROM port_state WHERE node_id=?',(node_id,))}
                    if not available or not set(visible).issubset(available):
                        raise ValueError('Unknown node or port')
                    with db:
                        for port in available:
                            db.execute('''INSERT INTO metadata(node_id,port,enabled)
                                VALUES(?,?,?) ON CONFLICT(node_id,port)
                                DO UPDATE SET enabled=excluded.enabled''',
                                (node_id,port,int(port in visible)))
                return self.send_json({'ok':True,'message':'پورت‌های نمایشی ذخیره شدند.'})
            except (ValueError,TypeError,KeyError) as exc:
                return self.send_json({'error':str(exc)},400)
        if path=='/api/fixed-expense':
            try:
                obj=json.loads(self.read_body())
                with connect(Path(CFG['data_dir'])/'traffic.sqlite3') as db:
                    node_ids={r['node_id'] for r in db.execute('SELECT DISTINCT node_id FROM port_state')}
                    detail=validate_expense(obj,node_ids)
                    record_id=obj.get('id',None)
                    if record_id is not None and (type(record_id) is not int or record_id<=0):
                        raise ValueError('شناسه هزینه نامعتبر است')
                    columns=['label','category','scope','node_id','provider','frequency',
                             'amount_rial','start_date','end_date','note']
                    with db:
                        if record_id:
                            exists=db.execute('SELECT 1 FROM fixed_expenses WHERE id=?',(record_id,)).fetchone()
                            if not exists:raise ValueError('هزینه پیدا نشد')
                            values=[detail[k] for k in columns]
                            values.append(record_id)
                            db.execute('UPDATE fixed_expenses SET '+
                                       ','.join(k+'=?' for k in columns)+' WHERE id=?',values)
                            expense_id=record_id
                        else:
                            db.execute('INSERT INTO fixed_expenses ('+','.join(columns)+
                                       ') VALUES ('+','.join('?' for _ in columns)+')',
                                       [detail[k] for k in columns])
                            expense_id=db.execute('SELECT last_insert_rowid()').fetchone()[0]
                return self.send_json({'ok':True,'id':expense_id})
            except (ValueError,TypeError,KeyError,OverflowError) as exc:
                return self.send_json({'error':str(exc)},400)
        if path=='/api/fixed-expense/delete':
            try:
                obj=json.loads(self.read_body())
                expense_id=obj.get('id') if type(obj) is dict else None
                if type(expense_id) is not int or expense_id<=0:raise ValueError('شناسه نامعتبر است')
                with connect(Path(CFG['data_dir'])/'traffic.sqlite3') as db:
                    with db:
                        removed=db.execute('DELETE FROM fixed_expenses WHERE id=?',(expense_id,))
                    if removed.rowcount!=1:raise ValueError('هزینه پیدا نشد')
                return self.send_json({'ok':True})
            except (ValueError,TypeError,KeyError) as exc:
                return self.send_json({'error':str(exc)},400)
        if path=='/api/display-settings':
            try:
                obj=json.loads(self.read_body())
                if type(obj) is not dict: raise ValueError('Invalid request')
                title=obj.get('title')
                currency=obj.get('currency')
                tz=obj.get('timezone')
                if type(title) is not str or not 1<=len(title.strip())<=100:
                    raise ValueError('عنوان معتبر نیست')
                if currency not in ('ریال','تومان','Toman','Rial','IRR'):
                    raise ValueError('واحد پول باید ریال یا تومان باشد')
                if type(tz) is not str or not 1<=len(tz)<=80:
                    raise ValueError('منطقه زمانی معتبر نیست')
                try: ZoneInfo(tz)
                except (ValueError,KeyError): raise ValueError('منطقه زمانی ناشناخته است')
                with connect(Path(CFG['data_dir'])/'traffic.sqlite3') as db:
                    with db:
                        for key,value in (('title',title.strip()),('currency',currency.strip()),('timezone',tz)):
                            db.execute('''INSERT INTO settings(key,value) VALUES(?,?)
                                ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
                                ('display_'+key,value))
                return self.send_json({'ok':True,'message':'تنظیمات نمایش ذخیره شدند.'})
            except (ValueError,KeyError,TypeError) as exc:
                return self.send_json({'error':str(exc)},400)
        if path=='/api/metadata/unassign':
            # Remove ONLY the monitor's provider assignment and custom display
            # settings. Raw traffic samples and PasarGuard remain untouched.
            try:
                obj=json.loads(self.read_body())
                if type(obj) is not dict:raise ValueError('درخواست نامعتبر است')
                nid=obj.get('node_id');port=obj.get('port')
                provider=obj.get('provider')
                if (type(nid) is not int or nid<=0 or
                    type(port) is not int or not 1<=port<=65535 or
                    type(provider) is not str or not provider.strip()):
                    raise ValueError('شناسه نود، پورت یا ارائه‌دهنده نامعتبر است')
                with connect(Path(CFG['data_dir'])/'traffic.sqlite3') as db:
                    with db:
                        db.execute('BEGIN IMMEDIATE')
                        current=db.execute('''SELECT provider FROM metadata
                            WHERE node_id=? AND port=?''',(nid,port)).fetchone()
                        if current is None or current['provider']!=provider:
                            raise ValueError('انتساب این پورت تغییر کرده است؛ گزارش را تازه‌سازی کنید.')
                        linked=db.execute('''SELECT 1 FROM supplier_ports
                            WHERE node_id=? AND port=? AND ended_at='' LIMIT 1''',
                            (nid,port)).fetchone()
                        if linked:
                            raise ValueError('این پورت به حساب اعتباری متصل است. ابتدا آن را از حساب جدا کنید.')
                        # Hide only the incorrect monitor entry; Xray port and
                        # full monitoring samples/counter baselines are retained.
                        db.execute('''UPDATE metadata
                            SET title='',provider='',price_per_gb=0,enabled=0,
                                notes='',billing_since=''
                            WHERE node_id=? AND port=?''',(nid,port))
                return self.send_json({'ok':True,'message':'انتساب حذف شد؛ آمار خام محفوظ است.'})
            except (ValueError,TypeError,KeyError,OverflowError) as exc:
                return self.send_json({'error':str(exc)},400)
        if path=='/api/metadata':
            try:
                obj=json.loads(self.read_body())
                nid=int(obj['node_id']);port=int(obj['port'])
                if nid<0 or not 1<=port<=65535:raise ValueError('شناسه نامعتبر')
                title=str(obj.get('title','')).strip()[:128]
                provider=str(obj.get('provider','')).strip()[:128]
                notes=str(obj.get('notes','')).strip()[:1000]
                direction=obj.get('bill_direction','downlink')
                if direction not in ('downlink','uplink','both'):raise ValueError('جهت نامعتبر')
                rate=float(obj.get('price_per_gb',0))
                if not 0<=rate<=1e12:raise ValueError('تعرفه نامعتبر')
                enabled=1 if obj.get('enabled',True) else 0
                since=str(obj.get('billing_since','')).strip()
                if since:
                    dt=datetime.fromisoformat(since)
                    if dt.tzinfo is None:raise ValueError('زمان شروع باید دارای منطقه زمانی باشد')
                    since=dt.astimezone(timezone.utc).isoformat(timespec='seconds')
                with connect(Path(CFG['data_dir'])/'traffic.sqlite3') as db:
                    known=db.execute('SELECT 1 FROM port_state WHERE node_id=? AND port=?',(nid,port)).fetchone()
                    if not known:raise ValueError('پورت در آمار یافت نشد')
                    linked=db.execute('''SELECT l.provider FROM supplier_ports b
                        JOIN provider_wallet_links l ON b.account_id=l.account_id
                        WHERE b.node_id=? AND b.port=?''',(nid,port)).fetchone()
                    if linked and linked['provider']!=provider:
                        raise ValueError('این پورت به کیف پول ارائه‌دهنده «'+
                            linked['provider']+'» متصل است. تغییر نام ارائه‌دهنده پس از اتصال کیف پول نیاز به انتقال کنترل‌شده اعتبار دارد.')
                    with db:
                        db.execute('''INSERT INTO metadata(node_id,port,title,provider,price_per_gb,bill_direction,enabled,notes,billing_since)
                         VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(node_id,port) DO UPDATE SET
                         title=excluded.title,provider=excluded.provider,price_per_gb=excluded.price_per_gb,
                         bill_direction=excluded.bill_direction,enabled=excluded.enabled,notes=excluded.notes,
                         billing_since=excluded.billing_since''',
                         (nid,port,title,provider,rate,direction,enabled,notes,since))
                        if provider:
                            sync_provider_port(db,provider,nid,port,direction,rate)
                return self.send_json({'ok':True,'message':'تغییرات ذخیره شد؛ تعرفه جدید از نمونه‌برداری بعدی اعمال می‌شود.'})
            except (ValueError,KeyError,TypeError,OverflowError) as e:
                return self.send_json({'error':str(e)},400)
        return self.send_json({'error':'یافت نشد'},404)

    def export_expenses_csv(self,params):
        try:
            with connect(Path(CFG['data_dir'])/'traffic.sqlite3') as db:
                tz=display_preferences(db)['timezone']
                _,_,lo,hi=utc_bounds(params,tz)
                expenses=expenses_report(db,lo,hi)
        except ValueError as exc:
            return self.send_json({'error':str(exc)},400)
        out=StringIO();writer=csv.writer(out)
        writer.writerow(['عنوان هزینه','دسته','نوع تخصیص','Node ID','ارائه‌دهنده',
                         'دوره','مبلغ پایه ریال','تاریخ شروع ISO','تاریخ پایان ISO',
                         'هزینه در بازه ریال','یادداشت'])
        for e in expenses:
            fields=[e['label'],e['category'],e['scope'],e['node_id'],e['provider'],
                    e['frequency'],e['amount_rial'],e['start_date'],e['end_date'],
                    round(e['period_rial']),e['note']]
            for i in (0,1,2,4,5,10):
                if isinstance(fields[i],str) and fields[i].startswith(('=','+','-','@','\t','\r')):
                    fields[i]="'"+fields[i]
            writer.writerow(fields)
        writer.writerow(['جمع هزینه ثابت در بازه','','','','','','','','',round(fixed_total(expenses)),''])
        return self.send_bytes(('\ufeff'+out.getvalue()).encode('utf-8'),
                               ctype='text/csv; charset=utf-8',
                               extra={'Content-Disposition':'attachment; filename="pgtraffic-fixed-expenses.csv"'})

    def export_csv(self,params):
        try:
            with connect(Path(CFG['data_dir'])/'traffic.sqlite3') as db:
                timezone_name=display_preferences(db)['timezone']
            begin,end,_,_=utc_bounds(params,timezone_name)
        except ValueError as e:return self.send_json({'error':str(e)},400)
        nid=params.get('node_id',[''])[0]
        port=params.get('port',[''])[0]
        try:
            if nid: nid=str(int(nid))
            if port: port=str(int(port))
        except ValueError:
            return self.send_json({'error':'شناسه نود یا پورت نامعتبر است'},400)
        query='''SELECT s.collected_at,s.node_name,s.node_id,s.port,s.tag,
          s.raw_down,s.raw_up,s.delta_down,s.delta_up,s.bill_bytes,s.rate_snapshot,s.cost,s.event,s.rate_unit
          FROM samples s WHERE s.collected_at>=? AND s.collected_at<?'''
        vals=[begin,end]
        if nid:
            query+=' AND s.node_id=?';vals.append(int(nid))
        if port:
            query+=' AND s.port=?';vals.append(int(port))
        query+=' ORDER BY s.collected_at,s.node_id,s.port LIMIT 150000'
        out=StringIO();w=csv.writer(out)
        w.writerow(['زمان UTC','نود','شناسه نود','پورت','Tag','Downlink Raw B','Uplink Raw B','Downlink Delta B','Uplink Delta B','Billable Bytes','Recorded Rate Toman/Unit','Recorded Cost Toman','Event','Recorded Rate Rial/Unit','Recorded Cost Rial','Pricing Unit'])
        with connect(Path(CFG['data_dir'])/'traffic.sqlite3') as db:
            for row in db.execute(query,vals):
                fields=list(row)
                # Block spreadsheet formula injection in text-like fields.
                for idx in (1,4,12):
                    if str(fields[idx]).startswith(('=','+','-','@','\t','\r')):fields[idx]="'"+str(fields[idx])
                # Keep original legacy units for audit and add explicit Rial equivalents.
                fields.extend((float(row[10])*10, float(row[11])*10, row[13]))
                fields.pop(13)  # keep the extra pricing-unit column at the end
                w.writerow(fields)
        return self.send_bytes(('\ufeff'+out.getvalue()).encode('utf-8'),ctype='text/csv; charset=utf-8',
                               extra={'Content-Disposition':'attachment; filename="pasarguard-traffic.csv"'})


def main():
    global CFG
    p=argparse.ArgumentParser()
    p.add_argument('--config',default='/opt/pg-traffic-monitor/config.json')
    a=p.parse_args()
    CFG=json.loads(Path(a.config).read_text(encoding='utf-8'))
    h=CFG['listen_host'];port=int(CFG['listen_port'])
    server=ThreadingHTTPServer((h,port),Handler)
    if CFG.get('ssl_cert'):
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(CFG['ssl_cert'],CFG['ssl_key'])
        server.socket=context.wrap_socket(server.socket,server_side=True)
    print('Dashboard listening on %s:%d (TLS=%s)' % (h,port,bool(CFG.get('ssl_cert'))),flush=True)
    server.serve_forever(poll_interval=1)

if __name__=='__main__':main()
