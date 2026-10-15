"""A real pre-GiB SQLite upgrade must retain raw bytes and past rate epochs."""
import sqlite3
import tempfile
import unittest
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from storage import connect
from supplier_wallets import wallet_report
from units import BYTES_PER_GIB, LEGACY_BYTES_PER_GB


class LegacyUnitUpgradeTests(unittest.TestCase):
    def test_old_install_remains_decimal_gb_after_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'monitor.sqlite3'
            db=connect(path)
            db.executescript("""
            DELETE FROM settings WHERE key IN ('traffic_unit','traffic_unit_adopted_at');
            DROP TABLE supplier_port_terms;
            DROP TABLE supplier_ports;
            DROP TABLE samples;
            CREATE TABLE supplier_ports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL, node_id INTEGER NOT NULL,
                port INTEGER NOT NULL, started_at TEXT NOT NULL,
                direction TEXT NOT NULL, rate_rial_per_gb INTEGER NOT NULL,
                ended_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE supplier_port_terms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                binding_id INTEGER NOT NULL, started_at TEXT NOT NULL,
                direction TEXT NOT NULL, rate_rial_per_gb INTEGER NOT NULL,
                UNIQUE(binding_id,started_at)
            );
            CREATE TABLE samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collected_at TEXT NOT NULL, node_id INTEGER NOT NULL,
                node_name TEXT NOT NULL, port INTEGER NOT NULL, tag TEXT NOT NULL,
                raw_up INTEGER, raw_down INTEGER,
                delta_up INTEGER NOT NULL,delta_down INTEGER NOT NULL,
                bill_bytes INTEGER NOT NULL,rate_snapshot REAL NOT NULL,
                cost REAL NOT NULL,event TEXT NOT NULL
            );
            INSERT INTO supplier_accounts (id,title,kind,started_at,opening_rial)
              VALUES(5,'Historic money','money','2026-10-14T00:00:00+00:00',500000);
            INSERT INTO supplier_accounts (id,title,kind,started_at,opening_bytes,reported_bytes)
              VALUES(6,'Historic volume','volume','2026-10-14T00:00:00+00:00',220000000000,220000000000);
            INSERT INTO supplier_ports(id,account_id,node_id,port,started_at,direction,rate_rial_per_gb)
              VALUES(7,5,3,55003,'2026-10-14T00:00:00+00:00','downlink',12000);
            INSERT INTO supplier_port_terms(binding_id,started_at,direction,rate_rial_per_gb)
              VALUES(7,'2026-10-14T01:00:00+00:00','downlink',13000);
            INSERT INTO samples(collected_at,node_id,node_name,port,tag,
              delta_up,delta_down,bill_bytes,rate_snapshot,cost,event)
              VALUES('2026-10-15T00:00:00+00:00',3,'TR',55003,'x',
              0,1000000000,1000000000,1300,1300,'ok');
            """)
            db.close()
            db=connect(path)
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='traffic_unit'").fetchone()[0],'GB')
            volume=db.execute('SELECT opening_bytes,reported_bytes FROM supplier_accounts WHERE id=6').fetchone()
            self.assertEqual(tuple(volume),(220000000000,220000000000))
            old=db.execute('SELECT delta_down,cost,rate_unit FROM samples ORDER BY id').fetchone()
            self.assertEqual(tuple(old),(1000000000,1300.0,'GB'))
            terms=db.execute('SELECT rate_rial_per_gb,bytes_per_unit FROM supplier_port_terms WHERE binding_id=7 ORDER BY started_at').fetchall()
            self.assertEqual([tuple(t) for t in terms],[(13000,LEGACY_BYTES_PER_GB)])
            future='2026-10-16T00:00:00+00:00'
            db.execute("""INSERT INTO samples(collected_at,node_id,node_name,port,tag,
              delta_up,delta_down,bill_bytes,rate_snapshot,cost,rate_unit,event)
              VALUES(?,3,'TR',55003,'x',0,?,?,1300,1300,'GB','ok')""",
              (future,LEGACY_BYTES_PER_GB,LEGACY_BYTES_PER_GB))
            self.assertEqual(next(a for a in wallet_report(db) if a['id']==5)['spent_rial'],26000)
            db.commit()
            db.close()
            db=connect(path)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM supplier_port_terms WHERE binding_id=7').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT SUM(delta_down) FROM samples').fetchone()[0],
                             2*LEGACY_BYTES_PER_GB)
            db.close()


if __name__=='__main__':
    unittest.main()
