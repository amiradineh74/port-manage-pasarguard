#!/usr/bin/env python3
"""Choose which node+port pairs appear in the dashboard and financial totals.

Only the monitor's independent SQLite metadata is changed. Raw samples and
PasarGuard's configuration, node services, user quotas and accounting remain untouched.
"""
import argparse
import json
from pathlib import Path

from storage import connect


def parse_ports(choice, available, selected):
    if not choice:
        return set(selected)
    if choice.lower() == 'all':
        return set(available)
    if choice.lower() == 'none':
        return set()
    try:
        parsed = [int(value.strip()) for value in choice.split(',')]
        if len(parsed) != len(set(parsed)) or not all(p in available for p in parsed):
            raise ValueError
        return set(parsed)
    except (ValueError, TypeError):
        raise ValueError('Enter valid listed ports, all, or none.') from None


def set_visibility(db, targets):
    """Targets maps node ID to a set of visible port numbers."""
    with db:
        for node_id, ports in targets.items():
            rows = db.execute('SELECT port FROM port_state WHERE node_id=?', (node_id,)).fetchall()
            for row in rows:
                port = row['port']
                db.execute('''INSERT INTO metadata(node_id,port,enabled)
                    VALUES(?,?,?) ON CONFLICT(node_id,port)
                    DO UPDATE SET enabled=excluded.enabled''',
                    (node_id,port,1 if port in ports else 0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/opt/pg-traffic-monitor/config.json')
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding='utf-8'))
    with connect(Path(cfg['data_dir']) / 'traffic.sqlite3') as db:
        rows = db.execute('''SELECT p.node_id,p.port,p.node_name,COALESCE(m.enabled,1) enabled
            FROM port_state p LEFT JOIN metadata m
              ON m.node_id=p.node_id AND m.port=p.port
            ORDER BY p.node_name,p.port''').fetchall()
        if not rows:
            print('No samples found. Run collector once first.')
            return 1
        groups = {}
        for row in rows:
            group = groups.setdefault(row['node_id'],{'name':row['node_name'],
                'available':set(),'selected':set()})
            group['available'].add(row['port'])
            if row['enabled']:group['selected'].add(row['port'])
        print('\n=== Select dashboard ports per node ===')
        print('Only visible ports count toward dashboard totals. Historical samples stay intact.')
        print('Enter comma-separated port numbers; Enter keeps current choice.')
        print('Use all to show every listed port or none to hide all on one node.')
        targets={}
        for node_id,group in groups.items():
            print('\nNode ID %d: %s' % (node_id,group['name']))
            print('Available: '+','.join(map(str,sorted(group['available']))))
            current=','.join(map(str,sorted(group['selected']))) or 'none'
            while True:
                choice=input('Visible ports [%s]: ' % current).strip()
                try:
                    targets[node_id]=parse_ports(choice,group['available'],group['selected'])
                    break
                except ValueError as exc:
                    print(exc)
        print('\n=== New dashboard selection ===')
        for node_id,ports in targets.items():
            print('%s (ID %d): %s' % (groups[node_id]['name'],node_id,
                ','.join(map(str,sorted(ports))) or '(none)'))
        decision=input('Save selection to monitoring database only? [y/N]: ').strip().lower()
        if decision not in ('y','yes'):
            print('Cancelled; nothing changed.')
            return 0
        set_visibility(db,targets)
        print('Saved. Hidden ports remain in the database and can be shown later.')
        return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (EOFError,KeyboardInterrupt):
        print('\nCancelled; nothing changed.')
        raise SystemExit(130)
