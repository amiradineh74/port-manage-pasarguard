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
CREATE TABLE IF NOT EXISTS fixed_expenses (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 128),
 category TEXT NOT NULL DEFAULT 'other',
 scope TEXT NOT NULL CHECK(scope IN ('general','node','provider')),
 node_id INTEGER,
 provider TEXT NOT NULL DEFAULT '',
 frequency TEXT NOT NULL CHECK(frequency IN ('monthly','once')),
 amount_rial INTEGER NOT NULL CHECK(amount_rial >= 0 AND amount_rial <= 100000000000000),
 start_date TEXT NOT NULL,
 end_date TEXT NOT NULL DEFAULT '',
 note TEXT NOT NULL DEFAULT '',
 CHECK((scope='node' AND node_id IS NOT NULL AND node_id > 0 AND provider='')
    OR (scope='provider' AND node_id IS NULL AND length(provider)>0)
    OR (scope='general' AND node_id IS NULL AND provider=''))
);
CREATE INDEX IF NOT EXISTS idx_fixed_expenses_dates ON fixed_expenses(start_date,end_date);

CREATE TABLE IF NOT EXISTS supplier_accounts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 128),
 bot_handle TEXT NOT NULL DEFAULT '',
 kind TEXT NOT NULL CHECK(kind IN ('money','volume')),
 started_at TEXT NOT NULL,
 opening_rial INTEGER NOT NULL DEFAULT 0 CHECK(opening_rial>=0),
 opening_bytes INTEGER NOT NULL DEFAULT 0 CHECK(opening_bytes>=0),
 reported_rial INTEGER,
 reported_bytes INTEGER,
 reported_at TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS supplier_ports (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 account_id INTEGER NOT NULL REFERENCES supplier_accounts(id),
 node_id INTEGER NOT NULL,
 port INTEGER NOT NULL CHECK(port BETWEEN 1 AND 65535),
 started_at TEXT NOT NULL,
 direction TEXT NOT NULL CHECK(direction IN ('downlink','uplink','both')),
 rate_rial_per_gb INTEGER NOT NULL DEFAULT 0 CHECK(rate_rial_per_gb>=0),
 UNIQUE(node_id,port)
);
CREATE INDEX IF NOT EXISTS idx_supplier_ports_account ON supplier_ports(account_id);
CREATE TABLE IF NOT EXISTS supplier_credits (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 account_id INTEGER NOT NULL REFERENCES supplier_accounts(id),
 amount INTEGER NOT NULL CHECK(amount>0),
 created_at TEXT NOT NULL,
 note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_supplier_credits_account ON supplier_credits(account_id);


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
                address_changed = previous is not None and previous['node_address'] != node['address']
                # New IP may mean a new Xray instance. Start a safe new baseline instead
                # of accidentally counting bytes from an unrelated counter lifetime.
                new_baseline = changed or address_changed
                raw_up, du, eu = delta(previous['raw_up'] if previous else None, p.get('uplink'), new_baseline)
                raw_dn, dd, ed = delta(previous['raw_down'] if previous else None, p.get('downlink'), new_baseline)
                meta = db.execute('SELECT * FROM metadata WHERE node_id=? AND port=?', (nid, port)).fetchone()
                direction = meta['bill_direction'] if meta else settings.get('default_bill_direction','downlink')
                rate = float(meta['price_per_gb']) if meta else float(settings.get('default_price_per_gb',0))
                bill = {'downlink': dd, 'uplink': du, 'both': dd + du}[direction]
                cost = bill * rate / 1_000_000_000
                events = []
                if changed: events.append('tag_changed')
                if address_changed: events.append('address_changed')
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
                # Keep state/baselines and all significant events even with no traffic.
                # For low-overhead installations, avoid a zero-byte sample every
                # minute for every idle port (highly beneficial with 20+ nodes).
                if settings.get('sparse_samples',False) and not du and not dd and event=='ok':
                    continue
                db.execute('''INSERT INTO samples
                (collected_at,node_id,node_name,port,tag,raw_up,raw_down,delta_up,delta_down,bill_bytes,rate_snapshot,cost,event)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (timestamp,nid,node['node_name'],port,tag,p.get('uplink'),p.get('downlink'),du,dd,bill,rate,cost,event))
                count += 1
        import json
        db.execute('INSERT INTO poll_runs(collected_at,node_count,sample_count,errors_json) VALUES(?,?,?,?)',
                   (timestamp,len(payload['nodes']),count,json.dumps(payload.get('errors',[]),ensure_ascii=False)))
    return count
