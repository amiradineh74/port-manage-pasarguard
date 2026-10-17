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
from units import BYTES_PER_GIB as GiB

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
            sample['nodes'][0]['ports'][0]['downlink']=(GiB+10)
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

    def test_provider_wallet_uses_preconfigured_ports_and_preserves_usage(self):
        from unittest.mock import patch
        import supplier_wallets
        cookie=self.login()
        st,_,raw=self.request('GET','/api/dashboard?from=2026-10-13&to=2026-10-13',
                               headers={'Cookie':cookie})
        csrf=json.loads(raw)['csrf']
        hdr={'Cookie':cookie,'Content-Type':'application/json','X-CSRF-Token':csrf}
        with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
            before=tuple(db.execute('SELECT COUNT(*),COALESCE(SUM(delta_down),0) FROM samples').fetchone())
            sample={'nodes':[{'node_id':77,'node_name':'SupplierNode','address':'192.0.2.77',
                 'ports':[{'port':55003,'tag':'supplier-port','uplink':0,'downlink':GiB}]}],
                 'errors':[]}
            insert_poll(db,sample,'2026-10-13T00:00:00+00:00',web.CFG)
            db.execute("""INSERT INTO metadata(node_id,port,provider,price_per_gb,bill_direction)
                        VALUES(77,55003,'InvoiceBot',1200,'downlink')""")
            db.commit()
        with patch.object(supplier_wallets,'utc_now',return_value='2026-10-13T00:00:30+00:00'):
            obj={'provider':'InvoiceBot','kind':'money','opening_amount':2437750,'ports':[{'node_id':77,'port':55003}]}
            st,_,raw=self.request('POST','/api/providers/wallet',json.dumps(obj),hdr)
            self.assertEqual(st,200)
            wallet_id=json.loads(raw)['id']
            st,_,_=self.request('POST','/api/providers/wallet',json.dumps(obj),hdr)
            self.assertEqual(st,400)
        with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
            sample['nodes'][0]['ports'][0]['downlink']=3*GiB
            insert_poll(db,sample,'2026-10-13T00:01:00+00:00',web.CFG)
        st,_,raw=self.request('GET','/api/wallets',headers={'Cookie':cookie})
        self.assertEqual(st,200)
        w=next(x for x in json.loads(raw)['accounts'] if x['id']==wallet_id)
        self.assertEqual(w['provider'],'InvoiceBot')
        self.assertEqual(len(w['ports']),1)
        self.assertEqual(w['ports'][0]['rate_rial_per_gb'],12000)
        self.assertEqual(w['estimated_balance'],2413750)
        # A wallet-bound port cannot be silently assigned to another provider.
        rename={'node_id':77,'port':55003,'title':'test','provider':'OtherProvider',
                'bill_direction':'downlink','price_per_gb':1200,'enabled':True}
        st,_,_=self.request('POST','/api/metadata',json.dumps(rename),hdr)
        self.assertEqual(st,400)
        with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
            retained=tuple(db.execute('SELECT COUNT(*),COALESCE(SUM(delta_down),0) FROM samples').fetchone())
            current=db.execute('SELECT provider FROM metadata WHERE node_id=77 AND port=55003').fetchone()[0]
            self.assertEqual(current,'InvoiceBot')
            self.assertEqual(retained[0],before[0]+2)
            self.assertEqual(retained[1],before[1]+2*GiB)
            # WebTests shares one temporary test DB across methods; undo only
            # this synthetic node/provider fixture so subsequent tests stay isolated.
            with db:
                db.execute('DELETE FROM supplier_checks WHERE account_id=?',(wallet_id,))
                db.execute('DELETE FROM supplier_credits WHERE account_id=?',(wallet_id,))
                db.execute('DELETE FROM supplier_port_terms WHERE binding_id IN (SELECT id FROM supplier_ports WHERE account_id=?)',(wallet_id,))
                db.execute('DELETE FROM provider_wallet_links WHERE account_id=?',(wallet_id,))
                db.execute('DELETE FROM supplier_ports WHERE account_id=?',(wallet_id,))
                db.execute('DELETE FROM supplier_accounts WHERE id=?',(wallet_id,))
                db.execute('DELETE FROM metadata WHERE node_id=77')
                db.execute('DELETE FROM samples WHERE node_id=77')
                db.execute('DELETE FROM port_state WHERE node_id=77')

    def test_supplier_wallet_management_http_isolated_and_csrf(self):
        from unittest.mock import patch
        import supplier_wallets
        cookie=self.login()
        st,_,raw=self.request('GET',
            '/api/dashboard?from=2026-10-13&to=2026-10-13',headers={'Cookie':cookie})
        csrf=json.loads(raw)['csrf']
        headers={'Cookie':cookie,'Content-Type':'application/json','X-CSRF-Token':csrf}
        with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
            before=tuple(db.execute('SELECT COUNT(*),COALESCE(SUM(delta_down),0) FROM samples').fetchone())
        account={'kind':'money','title':'Bot wallet','bot_handle':'@placeholder',
                 'opening_amount':2437750}
        st,_,_=self.request('POST','/api/wallets/create',json.dumps(account),
                             {'Cookie':cookie,'Content-Type':'application/json'})
        self.assertEqual(st,403)
        st,_,_=self.request('GET','/api/wallets')
        self.assertEqual(st,401)
        with patch.object(supplier_wallets,'utc_now',return_value='2026-10-13T00:00:01+00:00'):
            st,_,raw=self.request('POST','/api/wallets/create',json.dumps(account),headers)
            self.assertEqual(st,200)
            aid=json.loads(raw)['id']
            st,_,_=self.request('POST','/api/wallets/attach',json.dumps({
                'account_id':aid,'node_id':5,'port':2053,
                'rate_rial_per_gb':12000,'direction':'downlink'}),headers)
            self.assertEqual(st,200)
            st,_,_=self.request('POST','/api/wallets/attach',json.dumps({
                'account_id':aid,'node_id':5,'port':2053,
                'rate_rial_per_gb':12000,'direction':'downlink'}),headers)
            self.assertEqual(st,400)
        st,_,raw=self.request('GET','/api/wallets',headers={'Cookie':cookie})
        self.assertEqual(st,200)
        found=next(a for a in json.loads(raw)['accounts'] if a['id']==aid)
        self.assertEqual(found['spent_rial'],12000)
        self.assertEqual(found['estimated_balance'],2425750)
        with patch.object(supplier_wallets,'utc_now',return_value='2026-10-13T00:03:00+00:00'):
            st,_,_=self.request('POST','/api/wallets/credit',
                json.dumps({'account_id':aid,'amount':500000,'note':'New topup'}),headers)
            self.assertEqual(st,200)
            st,_,_=self.request('POST','/api/wallets/reported',
                json.dumps({'account_id':aid,'amount':2925750}),headers)
            self.assertEqual(st,200)
        st,_,raw=self.request('GET','/api/wallets',headers={'Cookie':cookie})
        found=next(a for a in json.loads(raw)['accounts'] if a['id']==aid)
        self.assertEqual(found['estimated_balance'],2925750)
        self.assertEqual(found['comparison_gap'],0)
        with patch.object(supplier_wallets,'utc_now',return_value='2026-10-13T00:04:00+00:00'):
            st,_,raw=self.request('POST','/api/wallets/reconcile',
                json.dumps({'account_id':aid,'amount':2920000,'note':'bot lower'}),headers)
            self.assertEqual(st,200)
            self.assertEqual(json.loads(raw)['result']['adjustment'],-5750)
        with patch.object(supplier_wallets,'utc_now',return_value='2026-10-13T00:05:00+00:00'):
            st,_,raw=self.request('POST','/api/wallets/reconcile',
                json.dumps({'account_id':aid,'amount':2930000,'note':'bot higher'}),headers)
            self.assertEqual(st,200)
            self.assertEqual(json.loads(raw)['result']['adjustment'],10000)
        st,_,raw=self.request('GET','/api/wallets',headers={'Cookie':cookie})
        found=next(a for a in json.loads(raw)['accounts'] if a['id']==aid)
        self.assertEqual(found['estimated_balance'],2930000)
        self.assertEqual(found['reconciliation_summary']['count'],3)
        self.assertEqual(found['reconciliation_summary']['positive'],10000)
        self.assertEqual(found['reconciliation_summary']['negative'],5750)
        self.assertEqual(found['reconciliation_summary']['net'],4250)
        self.assertEqual(found['reconciliation_history'][0]['note'],'bot higher')
        with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
            after=tuple(db.execute('SELECT COUNT(*),COALESCE(SUM(delta_down),0) FROM samples').fetchone())
        self.assertEqual(before,after)

    def test_reconciliation_csv_requires_login_and_preserves_cancelled_audit(self):
        import csv
        from io import StringIO
        from supplier_wallets import create_account
        self.assertEqual(self.request('GET','/api/wallet-reconciliations.csv')[0],401)
        cookie=self.login()
        with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
            with db:
                aid=create_account(db,{'kind':'money','title':'CSV export test',
                    'bot_handle':'@bot','opening_amount':100000})
                db.execute("INSERT INTO provider_wallet_links(provider,account_id) VALUES(?,?)",
                           ('Example Provider',aid))
                db.execute("""INSERT INTO supplier_reconciliations
                    (account_id,checked_at,reported_amount,estimated_before,adjustment,note)
                    VALUES(?,?,?,?,?,?)""",(aid,'2026-10-17T01:00:00+00:00',
                                           95000,100000,-5000,'provider balance'))
                rid=db.execute('SELECT last_insert_rowid()').fetchone()[0]
                db.execute("""INSERT INTO supplier_reconciliation_voids
                    (reconciliation_id,account_id,voided_at,reason)
                    VALUES(?,?,?,?)""",(rid,aid,'2026-10-17T02:00:00+00:00','wrong checkpoint'))
        try:
            status,headers,body=self.request('GET','/api/wallet-reconciliations.csv',
                                              headers={'Cookie':cookie})
            self.assertEqual(status,200)
            self.assertIn('text/csv',headers['Content-Type'])
            self.assertIn('attachment;',headers['Content-Disposition'])
            self.assertTrue(body.startswith(bytes((0xef,0xbb,0xbf))))
            rows=list(csv.reader(StringIO(body.decode('utf-8-sig'))))
            matches=[row for row in rows[1:] if row[3]==str(rid)]
            self.assertEqual(len(matches),1)
            self.assertEqual(matches[0][0],'Example Provider')
            self.assertEqual(matches[0][2],'money')
            self.assertEqual(matches[0][7],'-5000')
            self.assertEqual(matches[0][11],'لغوشده')
        finally:
            with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
                with db:
                    db.execute('DELETE FROM supplier_reconciliation_voids WHERE account_id=?',(aid,))
                    db.execute('DELETE FROM supplier_reconciliations WHERE account_id=?',(aid,))
                    db.execute('DELETE FROM provider_wallet_links WHERE account_id=?',(aid,))
                    db.execute('DELETE FROM supplier_accounts WHERE id=?',(aid,))

    def test_provider_rename_and_account_label_edit_are_csrf_protected(self):
        from supplier_wallets import create_account
        cookie=self.login()
        st,_,raw=self.request('GET','/api/dashboard?from=2026-10-13&to=2026-10-13',
                               headers={'Cookie':cookie})
        self.assertEqual(st,200)
        csrf=json.loads(raw)['csrf']
        headers={'Cookie':cookie,'Content-Type':'application/json','X-CSRF-Token':csrf}
        with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
            with db:
                aid=create_account(db,{'kind':'money','title':'wrong spelling',
                       'bot_handle':'@wrong','opening_amount':5000000})
                db.execute('INSERT INTO provider_wallet_links(provider,account_id) VALUES(?,?)',
                    ('source-typo',aid))
                db.execute('INSERT INTO metadata(node_id,port,provider) VALUES(?,?,?)',
                    (999,40550,'source-typo'))
                db.execute("""INSERT INTO fixed_expenses
                    (label,category,scope,node_id,provider,frequency,amount_rial,start_date)
                    VALUES('Provider bill','server','provider',NULL,'source-typo','monthly',600000,'2026-10-13')""")
                fixed_id=db.execute('SELECT last_insert_rowid()').fetchone()[0]
            sample_snapshot=tuple(db.execute(
                'SELECT COUNT(*),COALESCE(SUM(delta_down),0) FROM samples').fetchone())
        try:
            payload=json.dumps({'old_provider':'source-typo','new_provider':'source-fixed'})
            self.assertEqual(self.request('POST','/api/providers/rename',payload)[0],401)
            self.assertEqual(self.request('POST','/api/providers/rename',payload,
                {'Cookie':cookie,'Content-Type':'application/json'})[0],403)
            status,_,raw=self.request('POST','/api/providers/rename',payload,headers)
            self.assertEqual(status,200,raw)
            self.assertEqual(json.loads(raw)['result']['updated']['metadata'],1)
            duplicate=json.dumps({'old_provider':'source-fixed','new_provider':'source-fixed'})
            self.assertEqual(self.request('POST','/api/providers/rename',duplicate,headers)[0],400)
            identity=json.dumps({'id':aid,'title':'Correct account',
                'bot_handle':'@correct','notes':'Corrected typo'})
            status,_,raw=self.request('POST','/api/wallets/edit',identity,headers)
            self.assertEqual(status,200,raw)
            with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
                self.assertEqual(db.execute('SELECT provider FROM metadata WHERE node_id=999').fetchone()[0],'source-fixed')
                self.assertEqual(db.execute('SELECT provider FROM fixed_expenses WHERE id=?',
                    (fixed_id,)).fetchone()[0],'source-fixed')
                self.assertEqual(db.execute('SELECT provider FROM provider_wallet_links WHERE account_id=?',
                    (aid,)).fetchone()[0],'source-fixed')
                row=db.execute('SELECT title,bot_handle,opening_rial FROM supplier_accounts WHERE id=?',
                    (aid,)).fetchone()
                self.assertEqual(tuple(row),('Correct account','@correct',5000000))
                self.assertEqual(tuple(db.execute(
                    'SELECT COUNT(*),COALESCE(SUM(delta_down),0) FROM samples').fetchone()),
                    sample_snapshot)
        finally:
            with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
                with db:
                    db.execute('DELETE FROM fixed_expenses WHERE id=?',(fixed_id,))
                    db.execute('DELETE FROM metadata WHERE node_id=999 AND port=40550')
                    db.execute('DELETE FROM provider_wallet_links WHERE account_id=?',(aid,))
                    db.execute('DELETE FROM supplier_accounts WHERE id=?',(aid,))

    def test_cancel_wrong_reconciliation_api_authorization_csrf_and_balances(self):
        cookie=self.login()
        st,_,raw=self.request('GET','/api/dashboard?from=2026-10-13&to=2026-10-13',
            headers={'Cookie':cookie})
        csrf=json.loads(raw)['csrf']
        auth={'Cookie':cookie,'Content-Type':'application/json','X-CSRF-Token':csrf}
        with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
            samples_before=tuple(db.execute(
                'SELECT COUNT(*),COALESCE(SUM(delta_down),0) FROM samples').fetchone())
        st,_,raw=self.request('POST','/api/wallets/create',
            json.dumps({'kind':'money','title':'Undo-API-Test','opening_amount':800000}),auth)
        self.assertEqual(st,200,raw)
        account_id=json.loads(raw)['id']
        try:
            st,_,raw=self.request('POST','/api/wallets/reconcile',
                json.dumps({'account_id':account_id,'amount':700000}),auth)
            self.assertEqual(st,200,raw)
            st,_,raw=self.request('GET','/api/wallets',headers={'Cookie':cookie})
            self.assertEqual(st,200)
            wallet=next(a for a in json.loads(raw)['accounts'] if a['id']==account_id)
            rec_id=wallet['reconciliation_history'][0]['id']
            request=json.dumps({'account_id':account_id,'reconciliation_id':rec_id})
            self.assertEqual(self.request('POST','/api/wallets/reconcile/undo',
                request)[0],401)
            self.assertEqual(self.request('POST','/api/wallets/reconcile/undo',
                request,{'Cookie':cookie,'Content-Type':'application/json'})[0],403)
            st,_,raw=self.request('POST','/api/wallets/reconcile/undo',request,auth)
            self.assertEqual(st,200,raw)
            self.assertEqual(json.loads(raw)['result']['balance_after'],800000)
            st,_,raw=self.request('GET','/api/wallets',headers={'Cookie':cookie})
            wallet=next(a for a in json.loads(raw)['accounts'] if a['id']==account_id)
            self.assertEqual(wallet['estimated_balance'],800000)
            self.assertEqual(wallet['reconciliation_summary']['count'],0)
            self.assertIsNotNone(wallet['reconciliation_history'][0]['voided_at'])
            st,_,raw=self.request('POST','/api/wallets/reconcile/undo',request,auth)
            self.assertEqual(st,400,raw)
            with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
                samples_after=tuple(db.execute(
                    'SELECT COUNT(*),COALESCE(SUM(delta_down),0) FROM samples').fetchone())
                self.assertEqual(samples_before,samples_after)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM supplier_reconciliations WHERE account_id=?',
                    (account_id,)).fetchone()[0],1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM supplier_reconciliation_voids WHERE account_id=?',
                    (account_id,)).fetchone()[0],1)
        finally:
            with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
                with db:
                    db.execute('DELETE FROM supplier_reconciliation_voids WHERE account_id=?',(account_id,))
                    db.execute('DELETE FROM supplier_reconciliations WHERE account_id=?',(account_id,))
                    db.execute('DELETE FROM supplier_accounts WHERE id=?',(account_id,))

    def test_unassign_wrong_provider_port_preserves_raw_samples(self):
        """A mistaken provider entry must be removable without deleting Xray usage."""
        from supplier_wallets import assign_provider_wallet
        cookie=self.login()
        status,_,payload=self.request('GET','/api/dashboard?from=2026-10-13&to=2026-10-13',
                                      headers={'Cookie':cookie})
        self.assertEqual(status,200)
        csrf=json.loads(payload)['csrf']
        headers={'Cookie':cookie,'Content-Type':'application/json','X-CSRF-Token':csrf}
        path=Path(self.tmp.name)/'traffic.sqlite3'
        with connect(path) as db:
            fixture={'nodes':[{'node_id':88,'node_name':'ExtraNode',
                'address':'192.0.2.88','ports':[{'port':50888,'tag':'extra',
                'uplink':0,'downlink':GiB}]}],'errors':[]}
            insert_poll(db,fixture,'2026-10-13T00:00:00+00:00',web.CFG)
            db.execute('''INSERT INTO metadata(node_id,port,title,provider,price_per_gb,enabled)
                VALUES(88,50888,'Mistaken','techvps',420,1)''')
            db.commit()
            raw_before=tuple(db.execute('''SELECT COUNT(*),SUM(delta_down),SUM(cost)
                FROM samples WHERE node_id=88 AND port=50888''').fetchone())
        body=json.dumps({'node_id':88,'port':50888,'provider':'techvps'})
        try:
            status,_,_=self.request('POST','/api/metadata/unassign',body)
            self.assertEqual(status,401)
            status,_,_=self.request('POST','/api/metadata/unassign',body,
                {'Cookie':cookie,'X-CSRF-Token':'invalid'})
            self.assertEqual(status,403)
            status,_,_=self.request('POST','/api/metadata/unassign',
                json.dumps({'node_id':88,'port':50888,'provider':'Wrong'}),headers)
            self.assertEqual(status,400)
            with connect(path) as db:
                wallet_id=assign_provider_wallet(db,{'provider':'techvps',
                    'kind':'money','opening_amount':100000,
                    'ports':[{'node_id':88,'port':50888}]})
                db.commit()
            status,_,error=self.request('POST','/api/metadata/unassign',body,headers)
            self.assertEqual(status,400)
            self.assertIn('حساب اعتباری',json.loads(error)['error'])
            with connect(path) as db:
                # Detach only the temporary test wallet first.
                with db:
                    db.execute('''UPDATE supplier_ports SET ended_at='2026-10-14T00:00:00+00:00'
                        WHERE account_id=?''',(wallet_id,))
            status,_,result=self.request('POST','/api/metadata/unassign',body,headers)
            self.assertEqual(status,200,result)
            with connect(path) as db:
                meta=db.execute('''SELECT title,provider,price_per_gb,enabled
                    FROM metadata WHERE node_id=88 AND port=50888''').fetchone()
                self.assertEqual(tuple(meta),('', '',0.0,0))
                raw_after=tuple(db.execute('''SELECT COUNT(*),SUM(delta_down),SUM(cost)
                    FROM samples WHERE node_id=88 AND port=50888''').fetchone())
                self.assertEqual(raw_before,raw_after)
                self.assertEqual(db.execute('''SELECT COUNT(*) FROM port_state
                    WHERE node_id=88 AND port=50888''').fetchone()[0],1)
                self.assertEqual(db.execute('''SELECT COUNT(*) FROM supplier_ports
                    WHERE account_id=?''',(wallet_id,)).fetchone()[0],1)
            status,_,_=self.request('POST','/api/metadata/unassign',body,headers)
            self.assertEqual(status,400)
        finally:
            with connect(path) as db:
                with db:
                    db.execute('''DELETE FROM supplier_port_terms WHERE binding_id IN
                        (SELECT id FROM supplier_ports WHERE node_id=88)''')
                    db.execute('''DELETE FROM provider_wallet_links WHERE account_id IN
                        (SELECT account_id FROM supplier_ports WHERE node_id=88)''')
                    db.execute('''DELETE FROM supplier_accounts WHERE id IN
                        (SELECT account_id FROM supplier_ports WHERE node_id=88)''')
                    db.execute('DELETE FROM supplier_ports WHERE node_id=88')
                    db.execute('DELETE FROM metadata WHERE node_id=88')
                    db.execute('DELETE FROM samples WHERE node_id=88')
                    db.execute('DELETE FROM port_state WHERE node_id=88')

    def test_unauthenticated_block(self):
        st,_,_=self.request('GET','/api/dashboard')
        self.assertEqual(st,401)

    def test_login_stats_metadata_and_csv(self):
        cookie=self.login()
        st,h,b=self.request('GET','/api/dashboard?from=2026-10-13&to=2026-10-13',headers={'Cookie':cookie})
        self.assertEqual(st,200)
        data=json.loads(b)
        self.assertEqual(data['ports'][0]['port'],2053)
        self.assertEqual(data['total']['down'],GiB)
        self.assertEqual(data['daily_by_provider'][0]['node_id'],5)
        self.assertEqual(data['daily_by_provider'][0]['node_name'],'Germany')
        st,headers,calendar=self.request('GET','/jalali.js',headers={'Cookie':cookie})
        self.assertEqual(st,200)
        self.assertIn(b'const Jalali=',calendar)
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

        with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
            historical_before=db.execute(
                'SELECT COUNT(*),COALESCE(SUM(delta_down),0),COALESCE(SUM(cost),0) FROM samples'
            ).fetchone()
            historical_before=tuple(historical_before)
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
            historical_after=tuple(db.execute(
                'SELECT COUNT(*),COALESCE(SUM(delta_down),0),COALESCE(SUM(cost),0) FROM samples'
            ).fetchone())
        self.assertEqual(historical_before,historical_after)
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
        self.assertEqual(new['total']['down'],GiB)
        st,_,_=self.request('POST','/api/display-settings',
                            json.dumps({'title':'Bad','currency':'Toman','timezone':'Invalid/Zone'}),hdr)
        self.assertEqual(st,400)


    def test_fixed_expense_http_management_keeps_traffic_history(self):
        cookie=self.login()
        st,_,payload=self.request('GET',
            '/api/dashboard?from=2026-10-13&to=2026-10-13',headers={'Cookie':cookie})
        self.assertEqual(st,200)
        csrf=json.loads(payload)['csrf']
        auth={'Cookie':cookie,'Content-Type':'application/json','X-CSRF-Token':csrf}
        item={'label':'DE server','category':'server','scope':'node','node_id':5,
              'provider':'','frequency':'monthly','amount_rial':310000,
              'start_date':'2026-10-01','end_date':'','note':'monthly cost'}
        with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
            snapshot=tuple(db.execute('SELECT COUNT(*),SUM(delta_down) FROM samples').fetchone())
        st,_,_=self.request('POST','/api/fixed-expense',json.dumps(item),
            {'Cookie':cookie,'Content-Type':'application/json'})
        self.assertEqual(st,403)
        invalid=dict(item,node_id=901)
        st,_,_=self.request('POST','/api/fixed-expense',json.dumps(invalid),auth)
        self.assertEqual(st,400)
        st,_,raw=self.request('POST','/api/fixed-expense',json.dumps(item),auth)
        self.assertEqual(st,200)
        expense_id=json.loads(raw)['id']
        st,_,raw=self.request('GET','/api/dashboard?from=2026-10-13&to=2026-10-13',
                              headers={'Cookie':cookie})
        data=json.loads(raw)
        self.assertEqual(st,200)
        self.assertEqual(data['fixed_expenses_total_rial'],10333.33)
        self.assertEqual(data['fixed_expenses'][0]['id'],expense_id)
        self.assertEqual(data['fixed_expenses'][0]['scope'],'node')
        st,headers,csvdata=self.request('GET',
            '/api/expenses.csv?from=2026-10-13&to=2026-10-13',
            headers={'Cookie':cookie})
        self.assertEqual(st,200)
        self.assertIn('text/csv',headers['Content-Type'])
        self.assertTrue(csvdata.startswith(b'\xef\xbb\xbf'))
        self.assertIn('DE server',csvdata.decode('utf-8-sig'))
        self.assertIn(',10333,monthly cost',csvdata.decode('utf-8-sig'))
        self.assertIn('تاریخ شروع شمسی',csvdata.decode('utf-8-sig'))
        self.assertIn('1405/07/09',csvdata.decode('utf-8-sig'))
        item.update({'id':expense_id,'amount_rial':620000})
        st,_,_=self.request('POST','/api/fixed-expense',json.dumps(item),auth)
        self.assertEqual(st,200)
        st,_,raw=self.request('GET','/api/dashboard?from=2026-10-13&to=2026-10-13',
                              headers={'Cookie':cookie})
        self.assertEqual(json.loads(raw)['fixed_expenses_total_rial'],20666.67)
        st,_,_=self.request('POST','/api/fixed-expense/delete',
            json.dumps({'id':expense_id}),auth)
        self.assertEqual(st,200)
        st,_,raw=self.request('GET','/api/dashboard?from=2026-10-13&to=2026-10-13',
                              headers={'Cookie':cookie})
        self.assertEqual(json.loads(raw)['fixed_expenses_total_rial'],0)
        with connect(Path(self.tmp.name)/'traffic.sqlite3') as db:
            self.assertEqual(snapshot,tuple(db.execute(
                'SELECT COUNT(*),SUM(delta_down) FROM samples').fetchone()))

    def test_z_rial_display_provider_trends_and_csv(self):
        cookie=self.login()
        hdr={'Cookie':cookie,'Content-Type':'application/json'}
        st,_,raw=self.request('GET','/api/dashboard?from=2026-10-13&to=2026-10-13',
                              headers={'Cookie':cookie})
        self.assertEqual(st,200)
        csrf=json.loads(raw)['csrf']
        hdr['X-CSRF-Token']=csrf
        st,_,_=self.request('POST','/api/display-settings',
                            json.dumps({'title':'Rial Report','currency':'ریال','timezone':'UTC'}),
                            hdr)
        self.assertEqual(st,200)
        st,_,raw=self.request('GET','/api/dashboard?from=2026-10-13&to=2026-10-13',
                              headers={'Cookie':cookie})
        self.assertEqual(st,200)
        info=json.loads(raw)
        self.assertEqual(info['currency'],'ریال')
        # API money stays in historical internal Toman units; the client converts to Rial.
        self.assertEqual(info['total']['cost'],850)
        self.assertEqual(info['total']['historical_cost'],1000)
        self.assertIn('Paqet',info['providers'])
        self.assertEqual(info['providers']['Paqet']['cost'],850)
        daily=info['daily_by_provider']
        hourly=info['hourly_by_provider']
        self.assertTrue(info['hourly_available'])
        self.assertTrue(daily)
        self.assertTrue(hourly)
        self.assertAlmostEqual(sum(x['cost'] for x in daily),info['total']['cost'])
        self.assertAlmostEqual(sum(x['cost'] for x in hourly),info['total']['cost'])
        self.assertAlmostEqual(sum(x['cost'] for x in daily if x['provider']=='Paqet'),850)
        st,_,raw=self.request('GET','/api/export.csv?from=2026-10-13&to=2026-10-13',
                              headers={'Cookie':cookie})
        self.assertEqual(st,200)
        exported=raw.decode('utf-8-sig')
        self.assertIn('Recorded Rate Rial/Unit',exported)
        self.assertIn('Recorded Cost Rial',exported)
        self.assertIn('10000.0',exported)

if __name__=='__main__':unittest.main()
