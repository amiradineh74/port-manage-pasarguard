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
    def test_provider_uses_existing_metadata_and_legacy_balances(self):
        # Provider rate and direction are already known from ordinary port metadata.
        self.db.execute("""INSERT INTO metadata(node_id,port,provider,price_per_gb,bill_direction)
            VALUES(7,47307,'Pooya',1200,'both')""")
        with patch.object(wallets,'utc_now',return_value='2026-10-14T01:01:00+00:00'):
            account_id=wallets.assign_provider_wallet(self.db,{
                'provider':'Pooya','kind':'money','opening_amount':2437750})
        self.db.commit()
        bindings=self.db.execute('SELECT * FROM supplier_ports WHERE account_id=?',
                                 (account_id,)).fetchall()
        self.assertEqual(len(bindings),1)
        self.assertEqual(bindings[0]['rate_rial_per_gb'],12000)
        self.assertEqual(bindings[0]['direction'],'both')
        self.assertEqual(wallets.wallet_report(self.db)[0]['estimated_balance'],2437750)
        # Earlier consumption is not charged to the new checkpoint.
        self.poll(4000000000,750000000,'2026-10-14T01:02:00+00:00')
        a=wallets.wallet_report(self.db)[0]
        self.assertEqual(a['spent_rial'],15000)
        self.assertEqual(a['provider'],'Pooya')
        with self.assertRaises(ValueError):
            wallets.assign_provider_wallet(self.db,{
                'provider':'Pooya','kind':'money','opening_amount':100})
        self.assertEqual(self.db.execute(
            'SELECT COUNT(*) FROM supplier_accounts WHERE id=?',(account_id,)).fetchone()[0],1)

    def test_provider_rate_change_applies_only_to_future_samples(self):
        self.db.execute("""INSERT INTO metadata(node_id,port,provider,price_per_gb,bill_direction)
            VALUES(7,47307,'Pooya',1200,'both')""")
        with patch.object(wallets,'utc_now',return_value='2026-10-14T01:01:00+00:00'):
            wallets.assign_provider_wallet(self.db,{
                'provider':'Pooya','kind':'money','opening_amount':2437750})
        self.poll(4000000000,750000000,'2026-10-14T01:02:00+00:00')
        self.assertEqual(wallets.wallet_report(self.db)[0]['spent_rial'],15000)
        with patch.object(wallets,'utc_now',return_value='2026-10-14T01:03:00+00:00'):
            wallets.sync_provider_port(self.db,'Pooya',7,47307,'both',1500)
        self.poll(5000000000,750000000,'2026-10-14T01:04:00+00:00')
        self.assertEqual(wallets.wallet_report(self.db)[0]['spent_rial'],30000)
        self.assertEqual(wallets.wallet_report(self.db)[0]['estimated_balance'],2407750)
        terms=self.db.execute('SELECT COUNT(*) FROM supplier_port_terms').fetchone()[0]
        self.assertEqual(terms,1)

    def test_link_existing_wallet_without_restarting_or_charging_old_traffic(self):
        self.db.execute("""INSERT INTO metadata(node_id,port,provider,price_per_gb,bill_direction)
            VALUES(7,47307,'Pooya',1200,'both')""")
        with patch.object(wallets,'utc_now',return_value='2026-10-14T01:00:01+00:00'):
            old=wallets.create_account(self.db,{
                'kind':'money','title':'Old balance','opening_amount':2437750})
            wallets.attach_port(self.db,{'account_id':old,'node_id':7,'port':47307,
                 'direction':'downlink','rate_rial_per_gb':12000})
            wallets.add_credit(self.db,{'account_id':old,'amount':50000,'note':'old topup'})
        self.db.commit()
        existing=self.db.execute('SELECT started_at,rate_rial_per_gb FROM supplier_ports').fetchone()
        with patch.object(wallets,'utc_now',return_value='2026-10-14T01:10:00+00:00'):
            result=wallets.assign_provider_wallet(self.db,{
                'provider':'Pooya','existing_account_id':old})
        self.assertEqual(result,old)
        new=self.db.execute('SELECT started_at,rate_rial_per_gb FROM supplier_ports').fetchone()
        self.assertEqual(tuple(existing),tuple(new))
        acc=wallets.wallet_report(self.db)[0]
        self.assertEqual(acc['provider'],'Pooya')
        self.assertEqual(acc['credited'],50000)

    def test_new_provider_port_follows_existing_provider_binding(self):
        self.db.execute("""INSERT INTO metadata(node_id,port,provider,price_per_gb,bill_direction)
            VALUES(7,47307,'Pooya',1200,'both')""")
        with patch.object(wallets,'utc_now',return_value='2026-10-14T01:01:00+00:00'):
            account_id=wallets.assign_provider_wallet(self.db,{
                'provider':'Pooya','kind':'volume','opening_amount':50000000000})
        self.db.execute("""INSERT INTO port_state(node_id,port,node_name,node_address,tag,last_seen)
          VALUES(7,47308,'Germany','192.0.2.7','new-tag','2026-10-14T01:05:00+00:00')""")
        with patch.object(wallets,'utc_now',return_value='2026-10-14T01:05:01+00:00'):
            wallets.sync_provider_port(self.db,'Pooya',7,47308,'downlink',1200)
        self.assertEqual(self.db.execute(
            'SELECT COUNT(*) FROM supplier_ports WHERE account_id=?',(account_id,)).fetchone()[0],2)
        # Fresh binding starts at its own checkpoint and never back-charges old samples.
        self.assertEqual(wallets.wallet_report(self.db)[0]['estimated_balance'],50000000000)

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
