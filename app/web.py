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
    with connect(Path(CFG['data_dir'])/'traffic.sqlite3') as db:
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
         SUM(s.bill_bytes) billed, SUM(s.cost) cost, COUNT(*) samples,
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
            p.update(lookup.get((p['node_id'],p['port']),{'down':0,'up':0,'billed':0,'cost':0,'samples':0,'events':0}))
            combined.append(p)
        # Daily totals, aggregated at SQLite layer (UTC bucket; browser converts labels).
        times=db.execute('''SELECT substr(s.collected_at,1,10) day,
         SUM(s.delta_down) down,SUM(s.delta_up) up,SUM(s.bill_bytes) billed,SUM(s.cost) cost
         FROM samples s LEFT JOIN metadata m ON m.node_id=s.node_id AND m.port=s.port
         WHERE s.collected_at>=? AND s.collected_at<?
           AND COALESCE(m.enabled,1)=1
           AND (m.billing_since IS NULL OR m.billing_since='' OR s.collected_at>=m.billing_since)
         GROUP BY substr(s.collected_at,1,10) ORDER BY day''',(begin,end)).fetchall()
        last=db.execute('SELECT collected_at,node_count,sample_count,errors_json FROM poll_runs ORDER BY id DESC LIMIT 1').fetchone()
        providers={}
        for p in combined:
            if not p['enabled']: continue
            name=p['provider'] or 'بدون ارائه‌دهنده'
            v=providers.setdefault(name,{'billed':0,'cost':0,'down':0,'up':0})
            for col in v:v[col]+=p[col]
        total={x:sum(p[x] for p in combined if p['enabled']) for x in ('down','up','billed','cost')}
        return {'ports':combined,'daily':[dict(t) for t in times], 'providers':providers,
                'total':total,'period':{'from':lo,'to':hi},
                'last_run':dict(last) if last else None,
                'title':preferences['title'],'currency':preferences['currency'],
                'timezone':preferences['timezone']}


def csrf_for(token):return mac('csrf:'+token)


def html_response(page):return (ROOT/page).read_bytes()

class Handler(BaseHTTPRequestHandler):
    server_version='TrafficMonitor/0.2'
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
        if path=='/style.css':return self.send_bytes(html_response('style.css'),ctype='text/css; charset=utf-8')
        if path=='/api/dashboard':
            try:
                params=parse_qs(urlsplit(self.path).query)
                data=dashboard(params)
                data['csrf']=csrf_for(token)
                return self.send_json(data)
            except ValueError as e:return self.send_json({'error':str(e)},400)
        if path=='/api/export.csv':return self.export_csv(parse_qs(urlsplit(self.path).query))
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
        if path=='/api/display-settings':
            try:
                obj=json.loads(self.read_body())
                if type(obj) is not dict: raise ValueError('Invalid request')
                title=obj.get('title')
                currency=obj.get('currency')
                tz=obj.get('timezone')
                if type(title) is not str or not 1<=len(title.strip())<=100:
                    raise ValueError('عنوان معتبر نیست')
                if type(currency) is not str or not 1<=len(currency.strip())<=20:
                    raise ValueError('واحد پول معتبر نیست')
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
                    with db:
                        db.execute('''INSERT INTO metadata(node_id,port,title,provider,price_per_gb,bill_direction,enabled,notes,billing_since)
                         VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(node_id,port) DO UPDATE SET
                         title=excluded.title,provider=excluded.provider,price_per_gb=excluded.price_per_gb,
                         bill_direction=excluded.bill_direction,enabled=excluded.enabled,notes=excluded.notes,
                         billing_since=excluded.billing_since''',
                         (nid,port,title,provider,rate,direction,enabled,notes,since))
                return self.send_json({'ok':True,'message':'تغییرات ذخیره شد؛ تعرفه جدید از نمونه‌برداری بعدی اعمال می‌شود.'})
            except (ValueError,KeyError,TypeError,OverflowError) as e:
                return self.send_json({'error':str(e)},400)
        return self.send_json({'error':'یافت نشد'},404)

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
          s.raw_down,s.raw_up,s.delta_down,s.delta_up,s.bill_bytes,s.rate_snapshot,s.cost,s.event
          FROM samples s WHERE s.collected_at>=? AND s.collected_at<?'''
        vals=[begin,end]
        if nid:
            query+=' AND s.node_id=?';vals.append(int(nid))
        if port:
            query+=' AND s.port=?';vals.append(int(port))
        query+=' ORDER BY s.collected_at,s.node_id,s.port LIMIT 150000'
        out=StringIO();w=csv.writer(out)
        w.writerow(['زمان UTC','نود','شناسه نود','پورت','Tag','Downlink Raw B','Uplink Raw B','Downlink Delta B','Uplink Delta B','Billable Bytes','Rate Toman Per GB','Cost Toman','Event'])
        with connect(Path(CFG['data_dir'])/'traffic.sqlite3') as db:
            for row in db.execute(query,vals):
                fields=list(row)
                # Block spreadsheet formula injection in text-like fields.
                for idx in (1,4,12):
                    if str(fields[idx]).startswith(('=','+','-','@','\t','\r')):fields[idx]="'"+str(fields[idx])
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
