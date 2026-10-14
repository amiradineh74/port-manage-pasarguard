"""Per-node visible-port selection must not remove counters, samples or pricing."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from storage import connect,insert_poll
from select_ports import parse_ports,set_visibility


class PortVisibilityTests(unittest.TestCase):
    def test_parser_validates_existing_ports(self):
        available={2053,47307,50315}
        self.assertEqual(parse_ports('2053,50315',available,set()),{2053,50315})
        self.assertEqual(parse_ports('',available,{2053}),{2053})
        self.assertEqual(parse_ports('none',available,available),set())
        self.assertEqual(parse_ports('all',available,set()),available)
        for choice in ('2053,2053','9999','2053,','abc'):
            with self.assertRaises(ValueError):
                parse_ports(choice,available,set())

    def test_per_node_visibility_preserves_metadata_and_history(self):
        with tempfile.TemporaryDirectory() as directory:
            with connect(Path(directory)/'data.sqlite3') as db:
                cfg={'exclude_ports':[],'default_bill_direction':'both','default_price_per_gb':0}
                records=[
                   {'node_id':3,'node_name':'Turkey','address':'198.51.100.2',
                    'ports':[{'port':8443,'tag':'tu','uplink':100,'downlink':500},
                             {'port':2053,'tag':'gr','uplink':0,'downlink':0}]},
                   {'node_id':7,'node_name':'Germany','address':'198.51.100.7',
                    'ports':[{'port':2053,'tag':'gr','uplink':100,'downlink':500},
                             {'port':8443,'tag':'tr','uplink':0,'downlink':0}]}
                ]
                insert_poll(db,{'nodes':records,'errors':[]},'2026-10-14T07:00:00+00:00',cfg)
                with db:
                    db.execute('INSERT INTO metadata(node_id,port,title,provider,price_per_gb) VALUES(3,8443,?,?,?)',
                               ('Tunnel Turkey','provider-A',850))
                set_visibility(db,{3:{8443},7:{2053}})
                enabled={(r['node_id'],r['port']):r['enabled'] for r in
                    db.execute('SELECT node_id,port,enabled FROM metadata')}
                self.assertEqual(enabled,{(3,8443):1,(3,2053):0,(7,8443):0,(7,2053):1})
                title=db.execute('SELECT title,provider,price_per_gb FROM metadata WHERE node_id=3 AND port=8443').fetchone()
                self.assertEqual(tuple(title),('Tunnel Turkey','provider-A',850.0))
                self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0],4)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM port_state').fetchone()[0],4)


if __name__=='__main__':
    unittest.main()
