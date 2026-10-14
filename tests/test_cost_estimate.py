"""Historical rate mistakes never poison the primary cost estimate."""
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import web
from storage import connect, insert_poll


class CurrentRateTests(unittest.TestCase):
    def test_bad_rate_snapshots_do_not_affect_current_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = web.CFG
            cfg = {'data_dir': tmp, 'timezone': 'UTC', 'title': 'Monitor',
                   'currency': 'Toman', 'default_bill_direction': 'both',
                   'default_price_per_gb': 0, 'exclude_ports': []}
            web.CFG = cfg
            try:
                database = Path(tmp) / 'traffic.sqlite3'
                def sample(up, down, at):
                    with connect(database) as db:
                        node = {'node_id': 3, 'node_name': 'TR-Tunnel',
                                'address': '192.0.2.10',
                                'ports': [{'port': 8443, 'tag': 'Tu-Tr',
                                           'uplink': up, 'downlink': down}]}
                        insert_poll(db, {'nodes': [node], 'errors': []}, at, cfg)

                sample(100, 100, '2026-10-14T10:00:00+00:00')
                with connect(database) as db:
                    with db:
                        db.execute("""INSERT INTO metadata
                          (node_id,port,price_per_gb,bill_direction,provider)
                          VALUES(3,8443,850000,'both','Provider')""")
                sample(100000100, 1000000100, '2026-10-14T10:01:00+00:00')
                with connect(database) as db:
                    with db:
                        db.execute("UPDATE metadata SET price_per_gb=850 WHERE node_id=3 AND port=8443")
                sample(300000100, 3000000100, '2026-10-14T10:02:00+00:00')

                params = {'from': ['2026-10-14'], 'to': ['2026-10-14']}
                data = web.dashboard(params)
                port = data['ports'][0]
                self.assertEqual(port['down'], 3_000_000_000)
                self.assertEqual(port['up'], 300_000_000)
                self.assertEqual(port['billed'], 3_300_000_000)
                self.assertAlmostEqual(port['cost'], 2805.0)
                self.assertAlmostEqual(port['historical_cost'], 936870.0)
                self.assertAlmostEqual(data['total']['cost'], 2805.0)
                self.assertAlmostEqual(data['total']['historical_cost'], 936870.0)
                self.assertAlmostEqual(data['providers']['Provider']['cost'], 2805.0)
                self.assertAlmostEqual(data['daily'][0]['cost'], 2805.0)
                self.assertAlmostEqual(data['daily'][0]['historical_cost'], 936870.0)

                # Changing the billed direction must also recalculate the
                # presentation without ever rewriting raw historical samples.
                with connect(database) as db:
                    with db:
                        db.execute("UPDATE metadata SET bill_direction='downlink' WHERE node_id=3 AND port=8443")
                data = web.dashboard(params)
                self.assertAlmostEqual(data['total']['cost'], 2550.0)
                self.assertAlmostEqual(data['daily'][0]['cost'], 2550.0)
                self.assertAlmostEqual(data['total']['historical_cost'], 936870.0)
                with connect(database) as db:
                    historic = db.execute("SELECT SUM(cost) FROM samples WHERE node_id=3 AND port=8443").fetchone()[0]
                self.assertAlmostEqual(historic, 936870.0)

                # Billing-since only changes the reporting scope (not stored records).
                with connect(database) as db:
                    with db:
                        db.execute("""UPDATE metadata
                            SET billing_since='2026-10-14T10:02:00+00:00'
                            WHERE node_id=3 AND port=8443""")
                data = web.dashboard(params)
                self.assertEqual(data['ports'][0]['down'], 2_000_000_000)
                self.assertAlmostEqual(data['total']['cost'], 1700.0)
                self.assertAlmostEqual(data['total']['historical_cost'], 1870.0)
            finally:
                web.CFG = previous


if __name__ == '__main__':
    unittest.main()
