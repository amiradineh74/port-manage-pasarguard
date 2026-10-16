"""New sales API is login-protected and doesn't mutate traffic accounting."""
import hashlib
import http.client
import json
import secrets
import sys
import tempfile
import unittest
from datetime import datetime,timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import web
from storage import connect

class FinanceHTTPTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory()
  salt=secrets.token_bytes(16)
  digest=hashlib.pbkdf2_hmac('sha256',b'a-very-long-password',salt,310000)
  web.CFG={'data_dir':cls.temp.name,'traffic_unit':'GiB','timezone':'Asia/Tehran',
    'username':'admin','password_hash':f'pbkdf2$310000${salt.hex()}${digest.hex()}',
    'session_secret':secrets.token_hex(32),'title':'Test','currency':'Rial',
    'default_bill_direction':'both','default_price_per_gb':0}
  with connect(Path(cls.temp.name)/'traffic.sqlite3','GiB'):
   pass
  cls.server=ThreadingHTTPServer(('127.0.0.1',0),web.Handler)
  cls.thread=Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()

 @classmethod
 def tearDownClass(cls):
  cls.server.shutdown();cls.server.server_close();cls.temp.cleanup()

 def req(self,method,path,body=None,headers=None):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
  c.request(method,path,body=body,headers=headers or {})
  r=c.getresponse();s=r.status;h=dict(r.getheaders());b=r.read();c.close()
  return s,h,b

 def test_auth_write_update_zero_and_read_only_samples(self):
  now=datetime.now(ZoneInfo('Asia/Tehran')).date()
  day=(now-timedelta(days=1)).isoformat()
  path='/api/finance/report?'+urlencode({'from':day,'to':now.isoformat()})
  self.assertEqual(self.req('GET',path)[0],401)
  self.assertEqual(self.req('POST','/api/finance/sale','{}')[0],401)
  s,headers,_=self.req('POST','/login',
    urlencode({'username':'admin','password':'a-very-long-password'}),
    {'Content-Type':'application/x-www-form-urlencoded'})
  self.assertEqual(s,303)
  cookie=headers['Set-Cookie'].split(';')[0]
  session={'Cookie':cookie}
  status,_,body=self.req('GET','/api/dashboard',headers=session)
  self.assertEqual(status,200)
  csrf=json.loads(body)['csrf']
  status,_,raw=self.req('GET',path,headers=session)
  self.assertEqual(status,200,raw)
  before=json.loads(raw)
  self.assertEqual(len(before['days']),2)
  self.assertEqual(before['display_currency'],'Rial')
  self.assertIsNone(before['days'][0]['sales_rial'])
  headers={**session,'Content-Type':'application/json','X-CSRF-Token':csrf}
  obj={'day':day,'amount_rial':0,'accounts_sold':0}
  self.assertEqual(self.req('POST','/api/finance/sale',json.dumps(obj),
                            {**headers,'X-CSRF-Token':'bad'})[0],403)
  status,_,raw=self.req('POST','/api/finance/sale',json.dumps(obj),headers)
  self.assertEqual(status,200,raw)
  status,_,raw=self.req('GET',path,headers=session)
  after=json.loads(raw)
  self.assertEqual(after['days'][0]['status'],'recorded')
  self.assertEqual(after['days'][0]['sales_rial'],0)
  self.assertEqual(after['days'][0]['accounts_sold'],0)
  obj['amount_rial']=125000;obj['accounts_sold']=3
  self.assertEqual(self.req('POST','/api/finance/sale',json.dumps(obj),headers)[0],200)
  with connect(Path(self.temp.name)/'traffic.sqlite3','GiB') as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM daily_sales').fetchone()[0],1)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0],0)
  invalid={**obj,'day':(now+timedelta(days=1)).isoformat()}
  self.assertEqual(self.req('POST','/api/finance/sale',json.dumps(invalid),headers)[0],400)
  self.assertEqual(self.req('GET','/finance.js',headers=session)[0],200)

if __name__=='__main__':unittest.main()
