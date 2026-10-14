#!/usr/bin/env python3
"""Optional interactive metadata editor; never reads or writes PasarGuard itself."""
import argparse
from pathlib import Path
import json
from storage import connect

def ask(label,existing):
    value=input('%s [%s]: ' % (label,existing)).strip()
    return value if value else str(existing)

def edit(db,row,cfg,currency):
    nid,port,name=row
    meta=db.execute('SELECT * FROM metadata WHERE node_id=? AND port=?',(nid,port)).fetchone()
    print('\n--- %s / %s ---'%(name,port))
    title=ask('Display name',meta['title'] if meta else name+' : '+str(port))
    provider=ask('Provider name',meta['provider'] if meta else '')
    multiplier = 10 if currency == 'Rial' else 1
    existing_rate = (meta['price_per_gb'] if meta else cfg.get('default_price_per_gb',0)) * multiplier
    while True:
        try:
            entered_rate=float(ask('Rate per GB ('+currency+')',existing_rate))
            if not 0<=entered_rate<=1e13:raise ValueError
            rate=entered_rate / multiplier  # Old SQLite rates use Toman internally.
            break
        except ValueError:print('Invalid number')
    direction=ask('Billed direction (downlink/uplink/both)',meta['bill_direction'] if meta else cfg.get('default_bill_direction','downlink'))
    if direction not in ('downlink','uplink','both'):
        print('Invalid direction; changes cancelled.');return
    notes=ask('Notes',meta['notes'] if meta else '')
    with db:
        db.execute('''INSERT INTO metadata(node_id,port,title,provider,price_per_gb,bill_direction,notes)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(node_id,port) DO UPDATE SET
        title=excluded.title,provider=excluded.provider,price_per_gb=excluded.price_per_gb,
        bill_direction=excluded.bill_direction,notes=excluded.notes''',
        (nid,port,title,provider,rate,direction,notes))
    print('Saved. New rate applies from the next collection.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',default='/opt/pg-traffic-monitor/config.json');a=p.parse_args()
    cfg=json.loads(Path(a.config).read_text(encoding='utf-8'))
    with connect(Path(cfg['data_dir'])/'traffic.sqlite3') as db:
        rows=db.execute('SELECT node_id,port,node_name FROM port_state ORDER BY node_name,port').fetchall()
        if not rows:
            print('Run an initial collection first.');return
        print('\nAvailable ports:')
        for idx,r in enumerate(rows,1):print('%2d) %s  port=%s  node_id=%s'%(idx,r['node_name'],r['port'],r['node_id']))
        choice=input('Select a list number, all for every port, or Enter to exit: ').strip().lower()
        if not choice:return
        if choice=='all':chosen=rows
        else:
            try:chosen=[rows[int(choice)-1]]
            except (ValueError,IndexError):print('Invalid selection');return
        override=db.execute("SELECT value FROM settings WHERE key='display_currency'").fetchone()
        label=override['value'] if override else cfg.get('currency','Rial')
        # Existing installations with old Toman defaults display in Rial in the web UI.
        if not override and label in ('Toman','تومان'): label='Rial'
        currency='Rial' if label in ('Rial','IRR','ریال') else 'Toman'
        for r in chosen:edit(db,r,cfg,currency)

if __name__=='__main__':main()
