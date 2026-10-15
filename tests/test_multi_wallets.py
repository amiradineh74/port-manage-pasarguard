"""Multi-credit provider accounts: independent money/volume, safe migration/moves."""
import tempfile,unittest,sys,sqlite3
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from storage import connect,insert_poll
import supplier_wallets as w
from units import BYTES_PER_GIB as GiB

class MultiProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.tmp.name)/'traffic.sqlite3')
        self.cfg={'exclude_ports':[],'default_bill_direction':'both','default_price_per_gb':0}
        for p,n,rate in ((55001,3,750),(55002,7,750),(55003,3,1200),(55004,7,1200)):
            self.db.execute('''INSERT INTO port_state(node_id,port,node_name,node_address,tag,last_seen)
               VALUES(?,?,?,?,?,?)''',(n,p,str(n),'192.0.2.1',str(p),'2026-10-14T00:00:00+00:00'))
            self.db.execute('''INSERT INTO metadata(node_id,port,provider,price_per_gb,bill_direction)
               VALUES(?,?,?,?,?)''',(n,p,'SharedSupplier',rate,'downlink'))
        self.db.commit()
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def allocate(self,kind,title,initial,keys,at='2026-10-14T00:01:00+00:00',**flags):
        with patch.object(w,'utc_now',return_value=at):
            with self.db:
                return w.assign_provider_wallet(self.db,{
                    'provider':'SharedSupplier','kind':kind,'title':title,'opening_amount':initial,
                    'ports':[{'node_id':n,'port':p} for n,p in keys],**flags})
    def sample(self,port,node,gb,time):
        self.db.execute('''INSERT INTO samples
            (collected_at,node_id,node_name,port,tag,delta_down,delta_up,
             bill_bytes,rate_snapshot,cost,event)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
            (time,node,str(node),port,str(port),int(gb*GiB),0,0,0,0,'ok'))
        self.db.commit()
    def test_two_volume_and_money_under_same_provider(self):
        cheap=self.allocate('volume','Cheap GiB',20*GiB,[(3,55001),(7,55002)])
        dear=self.allocate('volume','Premium GiB',50*GiB,[(3,55003)])
        money=self.allocate('money','Wallet',500_000,[(7,55004)])
        self.sample(55001,3,5,'2026-10-14T00:02:00+00:00')
        self.sample(55002,7,3,'2026-10-14T00:02:00+00:00')
        self.sample(55003,3,12,'2026-10-14T00:02:00+00:00')
        self.sample(55004,7,2,'2026-10-14T00:02:00+00:00')
        results={a['id']:a for a in w.wallet_report(self.db)}
        self.assertEqual(len(results),3)
        self.assertEqual(results[cheap]['estimated_balance'],12*GiB)
        self.assertEqual(results[dear]['estimated_balance'],38*GiB)
        self.assertEqual(results[money]['estimated_balance'],476_000)
        self.assertEqual(results[money]['spent_rial'],24_000)
        self.assertEqual({a['provider'] for a in results.values()},{'SharedSupplier'})
    def test_explicit_transfer_keeps_old_usage_in_old_account(self):
        cheap=self.allocate('volume','Old volume',20*GiB,[(3,55001)])
        self.sample(55001,3,3,'2026-10-14T00:02:00+00:00')
        with self.assertRaises(ValueError):
            self.allocate('money','Other wallet',250_000,[(3,55001)],at='2026-10-14T00:03:00+00:00')
        # Ensure failed creation transaction does not leave a rogue wallet.
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM supplier_accounts').fetchone()[0],1)
        new=self.allocate('money','Other wallet',250_000,[(3,55001)],
            at='2026-10-14T00:03:00+00:00',confirm_transfer=True)
        self.sample(55001,3,4,'2026-10-14T00:04:00+00:00')
        report={a['id']:a for a in w.wallet_report(self.db)}
        self.assertEqual(report[cheap]['estimated_balance'],17*GiB)
        self.assertEqual(report[new]['estimated_balance'],220_000)
        self.assertEqual(report[new]['spent_rial'],30_000)
        self.assertEqual(report[cheap]['active_port_count'],0)
        self.assertEqual(report[new]['active_port_count'],1)
        old=self.db.execute('SELECT ended_at FROM supplier_ports WHERE account_id=?',(cheap,)).fetchone()
        self.assertEqual(old['ended_at'],'2026-10-14T00:03:00+00:00')
        with self.assertRaises(ValueError):
            self.allocate('money','Bad double link',1,[(3,55001)])
        self.assertEqual(self.db.execute('SELECT SUM(delta_down) FROM samples').fetchone()[0],7*GiB)
    def test_existing_provider_account_can_select_additional_port_without_reset(self):
        old=self.allocate('volume','Node A',100*GiB,[(3,55003)])
        self.sample(55003,3,1,'2026-10-14T00:02:00+00:00')
        with patch.object(w,'utc_now',return_value='2026-10-14T00:03:00+00:00'):
            with self.db:
                w.assign_provider_wallet(self.db,{'provider':'SharedSupplier',
                   'account_id':old,'ports':[{'node_id':3,'port':55003},{'node_id':7,'port':55004}]})
        self.sample(55003,3,2,'2026-10-14T00:04:00+00:00')
        self.sample(55004,7,7,'2026-10-14T00:04:00+00:00')
        result=w.wallet_report(self.db)[0]
        self.assertEqual(result['estimated_balance'],90*GiB)
        self.assertEqual(result['active_port_count'],2)
        self.assertEqual(len(result['ports']),2)

class LegacyMigrationTests(unittest.TestCase):
    def test_migration_keeps_old_wallet_records_and_rate_terms(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'traffic.sqlite3'
            db=connect(path)
            with db:
                db.execute("""INSERT INTO supplier_accounts(id,title,kind,started_at,opening_rial)
                   VALUES(8,'Old Money','money','2026-10-14T00:00:00+00:00',500000)""")
            db.executescript("""
            DROP TABLE supplier_ports;
            CREATE TABLE supplier_ports(
               id INTEGER PRIMARY KEY AUTOINCREMENT,account_id INTEGER NOT NULL,
               node_id INTEGER NOT NULL,port INTEGER NOT NULL,
               started_at TEXT NOT NULL,direction TEXT NOT NULL,
               rate_rial_per_gb INTEGER NOT NULL DEFAULT 0,
               UNIQUE(node_id,port));
            DROP TABLE provider_wallet_links;
            CREATE TABLE provider_wallet_links(
               provider TEXT PRIMARY KEY NOT NULL,account_id INTEGER UNIQUE NOT NULL);
            INSERT INTO supplier_ports VALUES(35,8,7,55003,'2026-10-14T00:01:00+00:00','downlink',12000);
            INSERT INTO provider_wallet_links VALUES('OldProvider',8);
            INSERT INTO supplier_port_terms(binding_id,started_at,direction,rate_rial_per_gb)
             VALUES(35,'2026-10-14T00:02:00+00:00','downlink',13000);
            """)
            db.close()
            db=connect(path)
            self.assertIn('ended_at',{r['name'] for r in db.execute('PRAGMA table_info(supplier_ports)')})
            self.assertEqual(db.execute('SELECT id FROM supplier_ports').fetchone()['id'],35)
            self.assertEqual(db.execute('SELECT binding_id FROM supplier_port_terms').fetchone()['binding_id'],35)
            self.assertEqual(db.execute('SELECT provider FROM provider_wallet_links WHERE account_id=8').fetchone()['provider'],'OldProvider')
            # Reopening is idempotent; old volume/account data must not change.
            db.close()
            db=connect(path)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM supplier_accounts').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM supplier_ports').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM provider_wallet_links').fetchone()[0],1)
            db.close()

if __name__=='__main__':unittest.main()
