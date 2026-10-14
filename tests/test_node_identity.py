"""Regression tests: stable node IDs survive address changes.

All tests use fake nodes and a temporary independent SQLite database.
No connection to a production PasarGuard node is made.
"""
import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from collector import load_config
from storage import connect, insert_poll


class NodeIdentityTests(unittest.TestCase):
    def test_filter_node_ids_ignores_ip_changes(self):
        # Extract only this pure helper (bridge module itself runs inside the panel).
        source = ast.parse((ROOT / 'app' / 'bridge.py').read_text(encoding='utf-8'))
        function = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'filter_nodes')
        module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
        namespace = {}
        exec(compile(module, 'bridge-filter', 'exec'), namespace)
        select = namespace['filter_nodes']

        current = [{'id': 12, 'address': '192.0.2.60'}, {'id': 30, 'address': '198.51.100.10'}]
        selected, missing = select(current, {12}, False)
        self.assertEqual([r['id'] for r in selected], [12])
        self.assertEqual(missing, [])
        # Same stable ID, new address supplied by PasarGuard.
        current[0]['address'] = '203.0.113.42'
        selected, missing = select(current, {12}, False)
        self.assertEqual(selected[0]['address'], '203.0.113.42')
        self.assertEqual(missing, [])
        self.assertEqual(select(current, {999}, False), ([], [999]))

    def test_no_unintentional_all_nodes_on_missing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            for obj in ({}, {'node_ips': ['192.0.2.100']},
                        {'node_ids': [], 'monitor_all_nodes': False},
                        {'node_ids': [True], 'monitor_all_nodes': False}):
                path.write_text(json.dumps(obj), encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_config(path)
            path.write_text(json.dumps({'node_ids': [12], 'monitor_all_nodes': False}), encoding='utf-8')
            self.assertEqual(load_config(path)['node_ids'], [12])
            path.write_text(json.dumps({'node_ids': [], 'monitor_all_nodes': True}), encoding='utf-8')
            self.assertTrue(load_config(path)['monitor_all_nodes'])

    def test_ip_change_preserves_history_and_rebaselines(self):
        with tempfile.TemporaryDirectory() as tmp:
            with connect(Path(tmp) / 'test.sqlite3') as db:
                cfg = {'exclude_ports': [], 'default_bill_direction': 'downlink',
                       'default_price_per_gb': 1200}
                def put(address, down, timestamp):
                    item = {'node_id': 12, 'node_name': 'GER', 'address': address,
                            'ports': [{'port': 2053, 'tag': 'tag-A',
                                       'uplink': down // 10, 'downlink': down}]}
                    insert_poll(db, {'nodes': [item], 'errors': []}, timestamp, cfg)
                put('192.0.2.60', 100, '2026-10-01T00:00:00+00:00')
                put('192.0.2.60', 200, '2026-10-01T00:01:00+00:00')
                put('203.0.113.42', 5000, '2026-10-01T00:02:00+00:00')
                put('203.0.113.42', 5250, '2026-10-01T00:03:00+00:00')

                record = db.execute('SELECT total_down,node_address FROM port_state').fetchone()
                self.assertEqual(record['total_down'], 350)
                self.assertEqual(record['node_address'], '203.0.113.42')
                events = [x[0] for x in db.execute('SELECT event FROM samples ORDER BY id')]
                self.assertEqual(events, ['baseline', 'ok', 'address_changed,baseline', 'ok'])
                self.assertEqual([x[0] for x in db.execute(
                    'SELECT delta_down FROM samples ORDER BY id')], [0, 100, 0, 250])


if __name__ == '__main__':
    unittest.main()
