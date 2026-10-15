#!/usr/bin/env python3
"""Read-only PasarGuard inbound collector: one API request per node per sample."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

from storage import connect, insert_poll
from units import selected_unit, selected_bytes_per_unit


def load_config(path):
    with open(path, encoding='utf-8') as f:
        cfg = json.load(f)
    # Strict selection avoids silently monitoring every node if a config is incomplete.
    monitor_all = cfg.get('monitor_all_nodes', False)
    node_ids = cfg.get('node_ids')
    if type(monitor_all) is not bool or type(node_ids) is not list:
        raise ValueError('Please reconfigure node selection: monitor_all_nodes / node_ids')
    if any(type(n) is not int or n < 1 for n in node_ids):
        raise ValueError('node_ids must contain positive integers')
    if monitor_all and node_ids:
        raise ValueError('Choose either all nodes or specific node IDs, not both')
    if not monitor_all and not node_ids:
        raise ValueError('No nodes selected. Re-run interactive setup.')
    return cfg


def collect(config_file):
    cfg = load_config(config_file)
    data_dir = Path(cfg['data_dir'])
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / 'collector.lock'
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o660)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Collector already running; skipping', file=sys.stderr)
            return 0
        bridge_code = (Path(__file__).resolve().parent / 'bridge.py').read_text(encoding='utf-8')
        selection = ['--all'] if cfg['monitor_all_nodes'] else [
            str(node_id) for node_id in cfg['node_ids']
        ]
        command = [
            'docker', 'exec', '-i', cfg['panel_container'],
            cfg['panel_python'], '-', *selection,
        ]
        p = subprocess.run(command, input=bridge_code, capture_output=True, text=True,
                           timeout=max(30, 18 * max(len(cfg['node_ids']), 2)), check=False)
        if p.returncode:
            # Never print stderr, as upstream errors might contain DB credentials.
            raise RuntimeError('Panel bridge failed, return code: %s' % p.returncode)
        payload = json.loads(p.stdout.strip())
        if not isinstance(payload, dict) or not isinstance(payload.get('nodes'), list):
            raise ValueError('Bad bridge response')
        if not payload['nodes']:
            raise RuntimeError('No stats received (no rows will be written)')
        timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
        with connect(data_dir / 'traffic.sqlite3', cfg.get('traffic_unit')) as db:
            count = insert_poll(db, payload, timestamp, cfg)
        print('OK: %s samples | %s node(s) | %s' % (count,len(payload['nodes']),timestamp))
        for error in payload.get('errors',[]):
            print('WARNING:', error)
        for n in payload['nodes']:
            print('  ', n['node_name'], 'ports:', len(n['ports']),
                  'unmapped counters:', n.get('unknown_tags',0))
        return 0 if not payload.get('errors') else 2
    finally:
        os.close(fd)


def show_report(cfg):
    with connect(Path(cfg['data_dir'])/'traffic.sqlite3', cfg.get('traffic_unit')) as db:
        rows = db.execute('''SELECT p.node_name,p.port,p.tag,p.total_down,p.total_up,p.last_seen,
          COALESCE(m.title,''),COALESCE(m.provider,'')
          FROM port_state p LEFT JOIN metadata m ON m.node_id=p.node_id AND m.port=p.port
          ORDER BY p.node_name,p.port''').fetchall()
        divisor=selected_bytes_per_unit(db)
        label=selected_unit(db)
        print('NODE | PORT | TITLE | DOWNLOAD('+label+') | UPLOAD('+label+') | LAST UTC')
        for r in rows:
            print('%s | %s | %s | %.4f | %.4f | %s' %
                 (r[0],r[1],r[6] or '-',r[3]/divisor,r[4]/divisor,r[5]))
        if not rows: print('No collected data yet.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['once','report','init','selftest'])
    p.add_argument('--config',default='/opt/pg-traffic-monitor/config.json')
    args = p.parse_args()
    if args.action=='selftest':
        from tests_self import run
        return run()
    cfg = load_config(args.config)
    if args.action=='once': return collect(args.config)
    if args.action=='init':
        with connect(Path(cfg['data_dir'])/'traffic.sqlite3',cfg.get('traffic_unit')): pass
        print('Database initialized (independent of PasarGuard)')
        return 0
    if args.action=='report': return show_report(cfg)

if __name__=='__main__':
    # Ensure SQLite WAL/SHM files remain group-writable for the unprivileged web service.
    os.umask(0o007)
    try:
        sys.exit(main())
    except Exception as e:
        print('ERROR:',type(e).__name__,str(e),file=sys.stderr)
        sys.exit(1)
