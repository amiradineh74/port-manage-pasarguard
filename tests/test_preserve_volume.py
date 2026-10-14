"""Volume-only reset regression tests on isolated SQLite, never production."""
import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from storage import connect,insert_poll

class PreserveVolumeTests(unittest.TestCase):
    def test_reset_keeps_all_samples_volume_and_counter_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            cfg={'exclude_ports':[],'default_bill_direction':'both','default_price_per_gb':850}
            with connect(Path(td)/'traffic.sqlite3') as db:
                def sample(down,time):
                    insert_poll(db,{'nodes':[{'node_id':7,'node_name':'DE',
                        'address':'192.0.2.5','ports':[{'port':2053,'tag':'abc','uplink':down//10,'downlink':down}]}],
                        'errors':[]},time,cfg)
                sample(10,'2026-10-14T00:00:00+00:00')
                sample(1000000010,'2026-10-14T00:01:00+00:00')
                db.execute("INSERT INTO metadata (node_id,port,provider,price_per_gb) VALUES(7,2053,'example',850)")
                db.execute("INSERT INTO settings(key,value) VALUES('display_currency','ریال')")
                db.execute("""INSERT INTO fixed_expenses(label,category,scope,provider,frequency,amount_rial,start_date)
                   VALUES('Shared panel','panel','general','','monthly',50000,'2026-10-01')""")
                db.commit()
                before=[tuple(x) for x in db.execute(
                  'SELECT collected_at,node_id,port,raw_down,delta_down,delta_up FROM samples ORDER BY id')]
                previous=dict(db.execute("SELECT * FROM port_state").fetchone())
                with db:
                    db.execute('UPDATE samples SET bill_bytes=0,rate_snapshot=0,cost=0')
                    db.execute('DELETE FROM metadata')
                    db.execute('DELETE FROM settings')
                    db.execute('DELETE FROM fixed_expenses')
                    db.execute('DELETE FROM poll_runs')
                after=[tuple(x) for x in db.execute(
                  'SELECT collected_at,node_id,port,raw_down,delta_down,delta_up FROM samples ORDER BY id')]
                self.assertEqual(before,after)
                self.assertEqual(dict(db.execute('SELECT * FROM port_state').fetchone()),previous)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM metadata').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM fixed_expenses').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT COALESCE(SUM(cost),0) FROM samples').fetchone()[0],0)
                # Next sample must add its delta, rather than treating history as a fresh baseline.
                sample(1500000010,'2026-10-14T00:03:00+00:00')
                self.assertEqual(db.execute('SELECT total_down FROM port_state').fetchone()[0],1500000000)
                self.assertEqual(db.execute('SELECT delta_down FROM samples ORDER BY id DESC LIMIT 1').fetchone()[0],500000000)

if __name__=='__main__':unittest.main()
