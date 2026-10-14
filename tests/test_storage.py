import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from storage import connect, insert_poll, delta

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.temp.name)/'d.sqlite3')
        self.cfg={'default_bill_direction':'downlink','default_price_per_gb':1200,'exclude_ports':[]}
    def tearDown(self):
        self.db.close();self.temp.cleanup()
    def put(self, tag, up, down, at):
        n={'node_id':1,'node_name':'GER','address':'192.0.2.1','ports':[{'port':2053,'tag':tag,'uplink':up,'downlink':down}]}
        return insert_poll(self.db,{'nodes':[n],'errors':[]},at,self.cfg)
    def test_baseline_delta_cost_and_rate_snapshot(self):
        self.put('A',10,100,'2026-10-01T00:00:00+00:00')
        self.put('A',20,1000000100,'2026-10-01T00:01:00+00:00')
        self.db.execute('''INSERT INTO metadata(node_id,port,price_per_gb,bill_direction) VALUES(1,2053,500,'both')''');self.db.commit()
        self.put('A',1000000020,2000000100,'2026-10-01T00:02:00+00:00')
        rows=self.db.execute('SELECT bill_bytes,rate_snapshot,cost,event FROM samples ORDER BY id').fetchall()
        self.assertEqual(rows[0]['bill_bytes'],0)
        self.assertEqual(rows[1]['bill_bytes'],1000000000)
        self.assertEqual(rows[1]['cost'],1200)
        self.assertEqual(rows[2]['bill_bytes'],2000000000)
        self.assertEqual(rows[2]['cost'],1000)
    def test_counter_reset_and_tag_change(self):
        self.put('A',100,100,'2026-10-01T00:00:00+00:00')
        self.put('A',20,20,'2026-10-01T00:01:00+00:00')
        self.put('B',300,300,'2026-10-01T00:02:00+00:00')
        self.assertEqual([r[0] for r in self.db.execute('SELECT event FROM samples')],['baseline','counter_reset','tag_changed,baseline'])
        self.assertEqual(self.db.execute('SELECT total_down FROM port_state').fetchone()[0],20)
    def test_sparse_history_keeps_last_seen_and_future_bytes(self):
        self.cfg['sparse_samples']=True
        self.put('A',10,100,'2026-10-01T00:00:00+00:00')
        self.put('A',10,100,'2026-10-01T00:01:00+00:00')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM samples').fetchone()[0],1)
        seen=self.db.execute('SELECT last_seen FROM port_state').fetchone()[0]
        self.assertEqual(seen,'2026-10-01T00:01:00+00:00')
        self.put('A',30,200,'2026-10-01T00:02:00+00:00')
        self.assertEqual([r[0] for r in self.db.execute('SELECT delta_down FROM samples ORDER BY id')],[0,100])
        self.assertEqual(self.db.execute('SELECT total_down FROM port_state').fetchone()[0],100)

    def test_missing_keeps_previous_baseline(self):
        self.put('A',100,200,'2026-10-01T00:00:00+00:00')
        self.put('A',None,300,'2026-10-01T00:01:00+00:00')
        self.put('A',120,350,'2026-10-01T00:02:00+00:00')
        p=self.db.execute('SELECT total_up,total_down FROM port_state').fetchone()
        self.assertEqual(tuple(p),(20,150))

if __name__=='__main__':unittest.main()
