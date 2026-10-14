import hashlib
import http.client
from http.server import ThreadingHTTPServer
import json
import secrets
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlencode
from threading import Thread
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import web
from storage import connect,insert_poll

class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        salt=secrets.token_bytes(16)
        digest=hashlib.pbkdf2_hmac('sha256','good-password-long'.encode(),salt,310000)
        web.CFG={'data_dir':cls.tmp.name,'timezone':'Asia/Tehran','username':'admin',
                 'password_hash':f'pbkdf2$310000${salt.hex()}${digest.hex()}',
                 'session_secret':secrets.token_hex(32),'title':'آزمایش',
                 'default_bill_direction':'downlink','default_price_per_gb':1000,'currency':'تومان'}
        with connect(Path(cls.tmp.name)/'traffic.sqlite3') as db:
            sample={'nodes':[{'node_id':5,'node_name':'Germany','address':'192.0.2.1',
                   'ports':[{'port':2053,'tag':'old','uplink':5,'downlink':10}]}], 'errors': []}
            insert_poll(db,sample,'2026-10-13T00:00:00+00:00',web.CFG)
            sample['nodes'][0]['ports'][0]['downlink']=1000000010
            insert_poll(db,sample,'2026-10-13T00:01:00+00:00',web.CFG)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),web.Handler)
        cls.thread=Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.port=cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.tmp.cleanup()

    def request(self,method,path,body=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=4)
        conn.request(method,path,body=body,headers=headers or {})
        resp=conn.getresponse();content=resp.read();headers=dict(resp.getheaders())
        conn.close();return resp.status,headers,content

    def login(self):
        body=urlencode({'username':'admin','password':'good-password-long'})
        st,h,b=self.request('POST','/login',body,{'Content-Type':'application/x-www-form-urlencoded'})
        self.assertEqual(st,303)
        return h['Set-Cookie'].split(';')[0]

    def test_unauthenticated_block(self):
        st,_,_=self.request('GET','/api/dashboard')
        self.assertEqual(st,401)

    def test_login_stats_metadata_and_csv(self):
        cookie=self.login()
        st,h,b=self.request('GET','/api/dashboard?from=2026-10-13&to=2026-10-13',headers={'Cookie':cookie})
        self.assertEqual(st,200)
        data=json.loads(b)
        self.assertEqual(data['ports'][0]['port'],2053)
        self.assertEqual(data['total']['down'],1000000000)
        self.assertEqual(data['total']['cost'],1000)
        update={'node_id':5,'port':2053,'title':'Paqet-Germany','provider':'Paqet',
                'price_per_gb':850,'bill_direction':'downlink', 'enabled':True}
        st,_,b=self.request('POST','/api/metadata',json.dumps(update),{
            'Cookie':cookie,'Content-Type':'application/json','X-CSRF-Token':'bad'})
        self.assertEqual(st,403)
        st,_,b=self.request('POST','/api/metadata',json.dumps(update),{
            'Cookie':cookie,'Content-Type':'application/json','X-CSRF-Token':data['csrf']})
        self.assertEqual(st,200)
        st,_,b=self.request('GET','/api/dashboard?from=2026-10-13&to=2026-10-13',headers={'Cookie':cookie})
        data2=json.loads(b)
        self.assertEqual(data2['ports'][0]['title'],'Paqet-Germany')
        self.assertEqual(data2['total']['cost'],850)  # current rate on the same 1 GB
        self.assertEqual(data2['total']['historical_cost'],1000)  # unchanged snapshot
        st,headers,content=self.request('GET','/api/export.csv?from=2026-10-13&to=2026-10-13',headers={'Cookie':cookie})
        self.assertEqual(st,200)
        self.assertIn('text/csv',headers['Content-Type'])
        self.assertIn('2053',content.decode())


    def test_web_can_manage_visible_ports_and_preferences(self):
        cookie=self.login()
        with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
            sample={'nodes':[
                {'node_id':5,'node_name':'Germany','address':'192.0.2.1',
                 'ports':[{'port':50315,'tag':'other','uplink':0,'downlink':7}]},
                {'node_id':6,'node_name':'Turkey','address':'192.0.2.2',
                 'ports':[{'port':8443,'tag':'turkey','uplink':0,'downlink':17}]}
            ],'errors':[]}
            insert_poll(db,sample,'2026-10-13T00:02:00+00:00',web.CFG)
        st,_,body=self.request('GET','/api/dashboard?from=2026-10-13&to=2026-10-13',
                               headers={'Cookie':cookie})
        self.assertEqual(st,200)
        old=json.loads(body)
        csrf=old['csrf']

        data={'node_id':5,'visible_ports':[2053]}
        # CSRF is still mandatory for these new mutations.
        st,_,_=self.request('POST','/api/visible-ports',json.dumps(data),
                            {'Cookie':cookie,'Content-Type':'application/json'})
        self.assertEqual(st,403)
        hdr={'Cookie':cookie,'Content-Type':'application/json','X-CSRF-Token':csrf}
        st,_,body=self.request('POST','/api/visible-ports',
                               json.dumps({'node_id':5,'visible_ports':[9999]}),hdr)
        self.assertEqual(st,400)
        st,_,body=self.request('POST','/api/visible-ports',json.dumps(data),hdr)
        self.assertEqual(st,200)
        with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
            selected={r['port']:r['enabled'] for r in db.execute(
                'SELECT p.port,COALESCE(m.enabled,1) enabled FROM port_state p '
                'LEFT JOIN metadata m ON p.node_id=m.node_id AND p.port=m.port '
                'WHERE p.node_id=5')}
            turkey=db.execute('SELECT COUNT(*) FROM metadata WHERE node_id=6').fetchone()[0]
        self.assertEqual(selected[2053],1)
        self.assertEqual(selected[50315],0)
        self.assertEqual(turkey,0)  # Other node untouched.

        prefs={'title':'My new title','currency':'Toman','timezone':'UTC'}
        st,_,_=self.request('POST','/api/display-settings',json.dumps(prefs),hdr)
        self.assertEqual(st,200)
        st,_,body=self.request('GET','/api/dashboard?from=2026-10-13&to=2026-10-13',
                               headers={'Cookie':cookie})
        self.assertEqual(st,200)
        new=json.loads(body)
        self.assertEqual(new['title'],'My new title')
        self.assertEqual(new['currency'],'Toman')
        self.assertEqual(new['timezone'],'UTC')
        self.assertEqual([p['enabled'] for p in new['ports'] if p['node_id']==5 and p['port']==50315],[0])
        self.assertEqual(new['total']['down'],1000000000)
        st,_,_=self.request('POST','/api/display-settings',
                            json.dumps({'title':'Bad','currency':'Toman','timezone':'Invalid/Zone'}),hdr)
        self.assertEqual(st,400)

if __name__=='__main__':unittest.main()
