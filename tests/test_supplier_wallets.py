"""Checkpoints, money-vs-GB units, supplier reports and historical volume safety."""
import sys, tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from storage import connect,insert_poll
import supplier_wallets as wallets

class WalletTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.folder.name)/'traffic.sqlite3')
        self.settings={'exclude_ports':[],'default_bill_direction':'both','default_price_per_gb':0}
        self.poll(0,0,'2026-10-14T00:00:00+00:00')
        self.poll(3000000000,500000000,'2026-10-14T01:00:00+00:00')
    def tearDown(self):
        self.db.close();self.folder.cleanup()
    def poll(self,down,up,when):
        insert_poll(self.db,{'nodes':[{'node_id':7,'node_name':'Germany',
            'address':'192.0.2.7','ports':[{'port':47307,'tag':'port',
            'downlink':down,'uplink':up}]}],'errors':[]},when,self.settings)
    def test_money_checkpoint_no_retro_and_fresh_credit(self):
        with patch.object(wallets,'utc_now',return_value='2026-10-14T01:01:00+00:00'):
            aid=wallets.create_account(self.db,{'kind':'money','title':'Supplier',
                'bot_handle':'@example','opening_amount':2437750})
            wallets.attach_port(self.db,{'account_id':aid,'node_id':7,'port':47307,
                'direction':'both','rate_rial_per_gb':12000})
        self.db.commit()
        self.assertEqual(wallets.wallet_report(self.db)[0]['estimated_balance'],2437750)
        self.poll(4000000000,750000000,'2026-10-14T01:02:00+00:00')
        self.db.commit()
        a=wallets.wallet_report(self.db)[0]
        self.assertEqual(a['used_bytes'],1250000000)
        self.assertEqual(a['spent_rial'],15000)
        self.assertEqual(a['estimated_balance'],2422750)
        # A payment included in the opening 243775 Toman must NOT be entered again.
        with patch.object(wallets,'utc_now',return_value='2026-10-14T01:03:00+00:00'):
            wallets.add_credit(self.db,{'account_id':aid,'amount':2000000,'note':'later new topup'})
            wallets.report_balance(self.db,{'account_id':aid,'amount':4420000})
        self.db.commit()
        a=wallets.wallet_report(self.db)[0]
        self.assertEqual(a['estimated_balance'],4422750)
        self.assertEqual(a['comparison_gap'],2750)
        self.poll(5000000000,750000000,'2026-10-14T01:04:00+00:00')
        self.db.commit()
        # Past comparison is pegged to reported-at, not today's new traffic.
        a=wallets.wallet_report(self.db)[0]
        self.assertEqual(a['comparison_gap'],2750)
        self.assertEqual(a['estimated_balance'],4410750)
        # Volume historical records are still intact.
        self.assertEqual(self.db.execute('SELECT SUM(delta_down) FROM samples').fetchone()[0],5000000000)
    def test_port_quota_and_duplicate_binding(self):
        with patch.object(wallets,'utc_now',return_value='2026-10-14T01:01:00+00:00'):
            volume=wallets.create_account(self.db,{'kind':'volume','title':'Quota',
                'opening_amount':100000000000})
            wallets.attach_port(self.db,{'account_id':volume,'node_id':7,
                'port':47307,'direction':'downlink','rate_rial_per_gb':0})
            with self.assertRaises(ValueError):
                wallets.attach_port(self.db,{'account_id':volume,'node_id':7,'port':47307,
                    'direction':'both','rate_rial_per_gb':0})
            with self.assertRaises(ValueError):
                wallets.attach_port(self.db,{'account_id':volume,'node_id':7,'port':9999,
                    'direction':'both','rate_rial_per_gb':0})
        self.poll(15500000000,800000000,'2026-10-14T01:02:00+00:00')
        with patch.object(wallets,'utc_now',return_value='2026-10-14T01:03:00+00:00'):
            wallets.add_credit(self.db,{'account_id':volume,'amount':20000000000})
            wallets.report_balance(self.db,{'account_id':volume,'amount':108000000000})
        self.db.commit()
        a=wallets.wallet_report(self.db)[0]
        self.assertEqual(a['estimated_balance'],107500000000)
        self.assertEqual(a['comparison_gap'],-500000000)
        with self.assertRaises(ValueError):
            wallets.add_credit(self.db,{'account_id':volume,'amount':0})
        with self.assertRaises(ValueError):
            wallets.create_account(self.db,{'kind':'money','title':'Bad','opening_amount':1.5})
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM supplier_accounts').fetchone()[0],1)

if __name__=='__main__':unittest.main()
