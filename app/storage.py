"""Own SQLite database. No writes whatsoever to the PasarGuard database."""
import sqlite3
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS port_state (
  node_id INTEGER NOT NULL,
  port INTEGER NOT NULL CHECK(port BETWEEN 1 AND 65535),
  node_name TEXT NOT NULL,
  node_address TEXT NOT NULL,
  tag TEXT NOT NULL,
  raw_up INTEGER, raw_down INTEGER,
  total_up INTEGER NOT NULL DEFAULT 0,
  total_down INTEGER NOT NULL DEFAULT 0,
  last_seen TEXT NOT NULL,
  PRIMARY KEY(node_id,port)
);
CREATE TABLE IF NOT EXISTS metadata (
  node_id INTEGER NOT NULL,
  port INTEGER NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  provider TEXT NOT NULL DEFAULT '',
  price_per_gb REAL NOT NULL DEFAULT 0 CHECK(price_per_gb >= 0),
  bill_direction TEXT NOT NULL DEFAULT 'downlink'
    CHECK(bill_direction IN ('downlink','uplink','both')),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
  notes TEXT NOT NULL DEFAULT '',
  billing_since TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(node_id,port)
);
CREATE TABLE IF NOT EXISTS samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  collected_at TEXT NOT NULL,
  node_id INTEGER NOT NULL,
  node_name TEXT NOT NULL,
  port INTEGER NOT NULL,
  tag TEXT NOT NULL,
  raw_up INTEGER, raw_down INTEGER,
  delta_up INTEGER NOT NULL,
  delta_down INTEGER NOT NULL,
  bill_bytes INTEGER NOT NULL,
  rate_snapshot REAL NOT NULL,
  cost REAL NOT NULL,
  event TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samples_at ON samples(collected_at);
CREATE INDEX IF NOT EXISTS idx_samples_node_port_time ON samples(node_id,port,collected_at);
CREATE TABLE IF NOT EXISTS poll_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  collected_at TEXT NOT NULL,
  node_count INTEGER NOT NULL,
  sample_count INTEGER NOT NULL,
  errors_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

def connect(db_file):
    db_file = Path(db_file)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(db_file), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=10000')
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript(DDL)
    return db


def delta(previous, current, tag_changed=False):
    if current is None:
        return previous, 0, 'missing'
    if type(current) is not int or current < 0:
        raise ValueError('Malformed counter')
    if previous is None or tag_changed:
        return current, 0, 'baseline'
    if current < previous:
        # Bytes since reset are real, but part of the gap is unrecoverable.
        return current, current, 'reset'
    return current, current - previous, 'ok'


def insert_poll(db, payload, timestamp, settings):
    count = 0
    with db:
        for node in payload['nodes']:
            for p in node['ports']:
                port, nid, tag = p['port'], node['node_id'], p['tag']
                if port in settings.get('exclude_ports', []):
                    continue
                previous = db.execute('SELECT * FROM port_state WHERE node_id=? AND port=?', (nid, port)).fetchone()
                changed = previous is not None and previous['tag'] != tag
                raw_up, du, eu = delta(previous['raw_up'] if previous else None, p.get('uplink'), changed)
                raw_dn, dd, ed = delta(previous['raw_down'] if previous else None, p.get('downlink'), changed)
                meta = db.execute('SELECT * FROM metadata WHERE node_id=? AND port=?', (nid, port)).fetchone()
                direction = meta['bill_direction'] if meta else settings.get('default_bill_direction','downlink')
                rate = float(meta['price_per_gb']) if meta else float(settings.get('default_price_per_gb',0))
                bill = {'downlink': dd, 'uplink': du, 'both': dd + du}[direction]
                cost = bill * rate / 1_000_000_000
                events = []
                if changed: events.append('tag_changed')
                if 'baseline' in (eu,ed): events.append('baseline')
                if 'reset' in (eu,ed): events.append('counter_reset')
                if 'missing' in (eu,ed): events.append('partial')
                event = ','.join(events) or 'ok'
                db.execute('''INSERT INTO port_state
                (node_id,port,node_name,node_address,tag,raw_up,raw_down,total_up,total_down,last_seen)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(node_id,port) DO UPDATE SET
                node_name=excluded.node_name,node_address=excluded.node_address,
                tag=excluded.tag,raw_up=excluded.raw_up,raw_down=excluded.raw_down,
                total_up=excluded.total_up,total_down=excluded.total_down,last_seen=excluded.last_seen''',
                (nid,port,node['node_name'],node['address'],tag,raw_up,raw_dn,
                 (previous['total_up'] if previous else 0)+du,
                 (previous['total_down'] if previous else 0)+dd,timestamp))
                db.execute('''INSERT INTO samples
                (collected_at,node_id,node_name,port,tag,raw_up,raw_down,delta_up,delta_down,bill_bytes,rate_snapshot,cost,event)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (timestamp,nid,node['node_name'],port,tag,p.get('uplink'),p.get('downlink'),du,dd,bill,rate,cost,event))
                count += 1
        import json
        db.execute('INSERT INTO poll_runs(collected_at,node_count,sample_count,errors_json) VALUES(?,?,?,?)',
                   (timestamp,len(payload['nodes']),count,json.dumps(payload.get('errors',[]),ensure_ascii=False)))
    return count
