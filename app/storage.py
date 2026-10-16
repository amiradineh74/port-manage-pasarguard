"""Own SQLite database. No writes whatsoever to the PasarGuard database."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from units import BYTES_PER_GIB, bytes_per_unit, check_unit, selected_unit, selected_bytes_per_unit

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
  rate_unit TEXT NOT NULL DEFAULT 'GiB',
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

-- Sales entries live ONLY in the monitoring application's private SQLite.
-- A recorded zero differs from a missing row; one editable entry per local day.
CREATE TABLE IF NOT EXISTS daily_sales (
 day TEXT PRIMARY KEY,
 amount_rial INTEGER NOT NULL CHECK(amount_rial BETWEEN 0 AND 100000000000000),
 accounts_sold INTEGER NOT NULL CHECK(accounts_sold BETWEEN 0 AND 10000000),
 note TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);


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
 bytes_per_unit INTEGER NOT NULL DEFAULT 1073741824,
 ended_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_supplier_ports_account ON supplier_ports(account_id);

CREATE TABLE IF NOT EXISTS supplier_port_terms (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 binding_id INTEGER NOT NULL REFERENCES supplier_ports(id),
 started_at TEXT NOT NULL,
 direction TEXT NOT NULL CHECK(direction IN ('downlink','uplink','both')),
 rate_rial_per_gb INTEGER NOT NULL CHECK(rate_rial_per_gb>=0),
 bytes_per_unit INTEGER NOT NULL DEFAULT 1073741824,
 UNIQUE(binding_id,started_at)
);
CREATE INDEX IF NOT EXISTS idx_supplier_terms_binding ON supplier_port_terms(binding_id,started_at);

CREATE TABLE IF NOT EXISTS supplier_credits (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 account_id INTEGER NOT NULL REFERENCES supplier_accounts(id),
 amount INTEGER NOT NULL CHECK(amount>0),
 created_at TEXT NOT NULL,
 note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_supplier_credits_account ON supplier_credits(account_id);

CREATE TABLE IF NOT EXISTS provider_wallet_links (
 provider TEXT NOT NULL CHECK(length(provider)>0),
 account_id INTEGER PRIMARY KEY REFERENCES supplier_accounts(id)
);
CREATE TABLE IF NOT EXISTS supplier_checks (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 account_id INTEGER NOT NULL REFERENCES supplier_accounts(id),
 checked_at TEXT NOT NULL,
 reported_amount INTEGER NOT NULL,
 estimated_amount INTEGER NOT NULL,
 difference INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_supplier_checks_account ON supplier_checks(account_id,checked_at);
CREATE TABLE IF NOT EXISTS supplier_reconciliations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 account_id INTEGER NOT NULL REFERENCES supplier_accounts(id),
 checked_at TEXT NOT NULL,
 reported_amount INTEGER NOT NULL CHECK(reported_amount>=0),
 estimated_before INTEGER NOT NULL,
 adjustment INTEGER NOT NULL,
 note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_supplier_reconciliations_account
 ON supplier_reconciliations(account_id,checked_at,id);




"""

def migrate_supplier_wallets(db):
    """Idempotent upgrade of supplier tables; old port IDs and history remain."""
    cols={r['name'] for r in db.execute('PRAGMA table_info(supplier_ports)')}
    old_link=db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='provider_wallet_links'").fetchone()
    old_provider=bool(old_link and 'PROVIDER TEXT PRIMARY KEY' in old_link['sql'].upper())
    if 'ended_at' not in cols or old_provider:
        db.execute('BEGIN IMMEDIATE')
        try:
            if 'ended_at' not in cols:
                db.execute("""CREATE TABLE supplier_ports_upgrade(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL REFERENCES supplier_accounts(id),
                    node_id INTEGER NOT NULL,
                    port INTEGER NOT NULL CHECK(port BETWEEN 1 AND 65535),
                    started_at TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK(direction IN ('downlink','uplink','both')),
                    rate_rial_per_gb INTEGER NOT NULL DEFAULT 0 CHECK(rate_rial_per_gb>=0),
                    ended_at TEXT NOT NULL DEFAULT ''
                )""")
                db.execute("""INSERT INTO supplier_ports_upgrade
                    (id,account_id,node_id,port,started_at,direction,rate_rial_per_gb)
                    SELECT id,account_id,node_id,port,started_at,direction,rate_rial_per_gb
                    FROM supplier_ports""")
                db.execute('DROP TABLE supplier_ports')
                db.execute('ALTER TABLE supplier_ports_upgrade RENAME TO supplier_ports')
            if old_provider:
                db.execute("""CREATE TABLE provider_wallet_links_upgrade(
                    provider TEXT NOT NULL CHECK(length(provider)>0),
                    account_id INTEGER PRIMARY KEY REFERENCES supplier_accounts(id)
                )""")
                db.execute("""INSERT INTO provider_wallet_links_upgrade(provider,account_id)
                    SELECT provider,account_id FROM provider_wallet_links""")
                db.execute('DROP TABLE provider_wallet_links')
                db.execute('ALTER TABLE provider_wallet_links_upgrade RENAME TO provider_wallet_links')
            db.commit()
        except BaseException:
            db.rollback()
            raise
    db.execute('CREATE INDEX IF NOT EXISTS idx_supplier_ports_account ON supplier_ports(account_id)')
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_supplier_port_current
       ON supplier_ports(node_id,port) WHERE ended_at=''""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_provider_wallet_links_provider ON provider_wallet_links(provider)')


def migrate_traffic_unit(db, preferred_unit=None):
    """Freeze a single global accounting unit in this independent monitor DB.

    Legacy history always keeps its original decimal-GB pricing. An existing
    database must not be silently converted to binary units on software update.
    A different desired unit requires a separate/new monitor database.
    """
    if preferred_unit is not None:
        check_unit(preferred_unit)
    current=db.execute("SELECT value FROM settings WHERE key='traffic_unit'").fetchone()
    if current:
        locked=check_unit(current[0])
        if preferred_unit is not None and locked != preferred_unit:
            raise ValueError('Traffic unit is locked to '+locked+
                '. Use a new independent monitor database to select '+preferred_unit)
    else:
        sample_cols={row['name'] for row in db.execute('PRAGMA table_info(samples)')}
        port_cols={row['name'] for row in db.execute('PRAGMA table_info(supplier_ports)')}
        old_schema=('rate_unit' not in sample_cols or 'bytes_per_unit' not in port_cols)
        has_history=bool(db.execute('SELECT 1 FROM samples LIMIT 1').fetchone() or
                         db.execute('SELECT 1 FROM supplier_accounts LIMIT 1').fetchone())
        if old_schema and has_history:
            locked='GB'
            if preferred_unit not in (None,'GB'):
                raise ValueError('Existing decimal-GB monitor data found. '+
                    'Create a new independent monitor DB to select GiB.')
        else:
            locked=preferred_unit or 'GiB'

    # Schema maintenance touches ONLY the monitor SQLite.
    cols={row['name'] for row in db.execute('PRAGMA table_info(samples)')}
    if 'rate_unit' not in cols:
        db.execute("ALTER TABLE samples ADD COLUMN rate_unit TEXT NOT NULL DEFAULT 'GB'")
    cols={row['name'] for row in db.execute('PRAGMA table_info(supplier_ports)')}
    if 'bytes_per_unit' not in cols:
        db.execute("ALTER TABLE supplier_ports ADD COLUMN bytes_per_unit INTEGER NOT NULL DEFAULT 1000000000")
    cols={row['name'] for row in db.execute('PRAGMA table_info(supplier_port_terms)')}
    if 'bytes_per_unit' not in cols:
        db.execute("ALTER TABLE supplier_port_terms ADD COLUMN bytes_per_unit INTEGER NOT NULL DEFAULT 1000000000")

    if not current:
        db.execute("INSERT INTO settings(key,value) VALUES('traffic_unit',?)",(locked,))
        db.commit()


def connect(db_file, traffic_unit=None):
    db_file = Path(db_file)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(db_file), timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA busy_timeout=10000')
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(DDL)
        migrate_supplier_wallets(db)
        migrate_traffic_unit(db, traffic_unit)
        return db
    except BaseException:
        db.close()
        raise


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
                cost = bill * rate / selected_bytes_per_unit(db)
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
                (collected_at,node_id,node_name,port,tag,raw_up,raw_down,delta_up,delta_down,bill_bytes,rate_snapshot,cost,rate_unit,event)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (timestamp,nid,node['node_name'],port,tag,p.get('uplink'),p.get('downlink'),du,dd,bill,rate,cost,selected_unit(db),event))
                count += 1
        import json
        db.execute('INSERT INTO poll_runs(collected_at,node_count,sample_count,errors_json) VALUES(?,?,?,?)',
                   (timestamp,len(payload['nodes']),count,json.dumps(payload.get('errors',[]),ensure_ascii=False)))
    return count
