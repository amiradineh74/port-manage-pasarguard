"""Only the independent monitor chooses one installation-wide unit."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from storage import connect, insert_poll
from units import selected_unit, selected_bytes_per_unit, BYTES_PER_GIB, LEGACY_BYTES_PER_GB

class GlobalUnitTests(unittest.TestCase):
    def test_either_install_choice_applies_to_traffic_cost_and_persists(self):
        for choice,divisor in [('GB',LEGACY_BYTES_PER_GB),('GiB',BYTES_PER_GIB)]:
            with self.subTest(choice=choice),tempfile.TemporaryDirectory() as td:
                path=Path(td)/'traffic.sqlite3'
                cfg={'traffic_unit':choice,'default_price_per_gb':1000,
                     'default_bill_direction':'downlink','exclude_ports':[]}
                with connect(path,choice) as db:
                    self.assertEqual(selected_unit(db),choice)
                    self.assertEqual(selected_bytes_per_unit(db),divisor)
                    def payload(down):
                        return {'nodes':[{'node_id':9,'node_name':'Test',
                          'address':'192.0.2.9','ports':[{'port':1234,'tag':'t','uplink':0,'downlink':down}]}],
                          'errors':[]}
                    insert_poll(db,payload(0),'2026-10-16T00:00:00+00:00',cfg)
                    insert_poll(db,payload(divisor),'2026-10-16T00:01:00+00:00',cfg)
                    result=db.execute("""SELECT bill_bytes,cost,rate_unit FROM samples
                        ORDER BY id DESC LIMIT 1""").fetchone()
                    self.assertEqual(result['bill_bytes'],divisor)
                    self.assertEqual(result['cost'],1000)
                    self.assertEqual(result['rate_unit'],choice)
                with connect(path,choice) as db:
                    self.assertEqual(selected_unit(db),choice)
                with self.assertRaisesRegex(ValueError,'locked'):
                    connect(path,'GB' if choice=='GiB' else 'GiB')
    def test_old_install_does_not_silently_switch_units(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db.sqlite'
            with connect(path,'GB') as db:
                self.assertEqual(selected_unit(db),'GB')
            with self.assertRaisesRegex(ValueError,'locked'):
                connect(path,'GiB')

if __name__=='__main__':
    unittest.main()
