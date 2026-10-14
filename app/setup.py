#!/usr/bin/env python3
"""Interactive setup. All configurable values are prompted and documented."""
import getpass
import hashlib
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT = {
 'panel_container':'pasarguard-pasarguard-1',
 'panel_python':'/code/.venv/bin/python',
 'node_ids':[],
 'monitor_all_nodes':False,
 'data_dir':os.environ.get('PGTM_DEFAULT_DIR','/opt/pg-traffic-monitor')+'/data',
 'poll_interval':60,
 'listen_host':'127.0.0.1',
 'listen_port':8791,
 'timezone':'Asia/Tehran',
 'title':'Port Traffic & Cost Monitor',
 'default_bill_direction':'downlink',
 'default_price_per_gb':0,
 'currency':'Toman',
 'exclude_ports':[22022],
 'ssl_cert':'', 'ssl_key':'',
}

def ask(prompt,default='', validator=None, convert=str):
    while True:
        val=input('%s [%s]: ' % (prompt,default)).strip()
        if not val: val=str(default)
        try:
            out=convert(val)
            if validator and not validator(out): raise ValueError('invalid')
            return out
        except (TypeError,ValueError):
            print('Invalid value. Please try again.')

def yesno(prompt,default=False):
    label='Y/n' if default else 'y/N'
    while True:
        s=input('%s [%s]: ' % (prompt,label)).strip().lower()
        if not s:return default
        if s in ('y','yes','بله','آره'):return True
        if s in ('n','no','نه'):return False
        print('Please enter y or n.')

def list_nodes(panel_container, panel_python):
    """Discover IDs and display names, without exposing node API credentials."""
    code=Path(__file__).with_name('discover_nodes.py').read_text(encoding='utf-8')
    result=subprocess.run(
        ['docker','exec','-i',panel_container,panel_python,'-'],
        input=code, capture_output=True, text=True, timeout=25, check=False
    )
    if result.returncode:
        raise RuntimeError('Could not read PasarGuard node list from the panel container.')
    try:
        nodes=json.loads(result.stdout.strip())
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError('Invalid response from the panel container.') from exc
    if not isinstance(nodes,list) or not all(
        isinstance(n,dict) and type(n.get('id')) is int and n['id'] > 0
        and isinstance(n.get('name'),str) for n in nodes
    ):
        raise RuntimeError('Invalid node list format.')
    if not nodes:
        raise RuntimeError('No PasarGuard nodes found. Cannot continue setup.')
    return nodes


def choose_nodes(cfg, nodes):
    """Require explicit node choice; selection is bound to stable node IDs."""
    available={n['id'] for n in nodes}
    print('\n=== Available PasarGuard nodes ===')
    for node in nodes:
        print('ID %s: %s' % (node['id'],node['name']))
    if cfg.get('node_ips'):
        print('NOTE: Previous IP-based selection is obsolete. Select node IDs below.')
    selected=cfg.get('node_ids',[])
    previous='all' if cfg.get('monitor_all_nodes',False) else ','.join(map(str,selected))
    while True:
        choice=input('Node IDs (comma-separated), or all [%s]: ' % (previous or 'required')).strip()
        if not choice:
            choice=previous
        if choice.lower()=='all':
            cfg['monitor_all_nodes']=True
            cfg['node_ids']=[]
            break
        try:
            ids=[int(x.strip()) for x in choice.split(',')]
            if not ids or len(ids)!=len(set(ids)) or not all(x in available for x in ids):
                raise ValueError
        except (ValueError,TypeError):
            print('Invalid selection. Enter listed node IDs or all.')
            continue
        cfg['monitor_all_nodes']=False
        cfg['node_ids']=ids
        break
    cfg.pop('node_ips',None)


def main():
    dest=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/opt/pg-traffic-monitor/config.json')
    cfg=dict(DEFAULT)
    if dest.exists():
        with dest.open(encoding='utf-8') as f: old=json.load(f)
        cfg.update(old)
        if not yesno('Edit existing settings?',False):
            print('No changes made');return 0
        from datetime import datetime
        import shutil
        backup=dest.with_name('config.backup-'+datetime.now().strftime('%Y%m%d%H%M%S')+'.json')
        shutil.copy2(dest,backup)
        print('Backup saved:',backup)
    print('\n=== Interactive setup | Main settings ===\n')
    cfg['panel_container']=ask('PasarGuard panel container name',cfg['panel_container'])
    cfg['panel_python']=ask('Python path inside the panel container',cfg['panel_python'])
    print('Reading available nodes from PasarGuard (read-only)...')
    try:
        nodes=list_nodes(cfg['panel_container'],cfg['panel_python'])
    except (OSError,subprocess.TimeoutExpired,RuntimeError) as exc:
        raise SystemExit('Node discovery failed: %s No settings were saved.' % exc)
    choose_nodes(cfg,nodes)
    cfg['data_dir']=ask('Independent database directory',cfg['data_dir'],lambda s:s.startswith('/'))
    cfg['poll_interval']=ask('Collection interval in seconds (minimum 60)',cfg['poll_interval'],lambda n:60<=n<=86400,int)
    cfg['title']=ask('Dashboard title',cfg['title'])
    def timezone_ok(value):
        try:ZoneInfo(value);return True
        except Exception:return False
    cfg['timezone']=ask('Reporting timezone',cfg['timezone'],timezone_ok)
    cfg['listen_host']=ask('Web listen address (127.0.0.1 recommended)',cfg['listen_host'])
    cfg['listen_port']=ask('Dashboard port',cfg['listen_port'],lambda n:1024<=n<=65535,int)
    cfg['currency']=ask('Currency label',cfg['currency'])
    cfg['default_bill_direction']=ask('Default billed direction: downlink/uplink/both',cfg['default_bill_direction'],lambda s:s in ('downlink','uplink','both'))
    cfg['default_price_per_gb']=ask('Default rate per GB (0 = configure later per port)',cfg['default_price_per_gb'],lambda n:0<=n<1e12,float)
    ports=ask('Excluded ports (comma-separated)',' ,'.join(map(str,cfg['exclude_ports'])))
    cfg['exclude_ports']=[int(x.strip()) for x in ports.split(',') if x.strip()]
    if cfg['listen_host'] not in ('127.0.0.1','::1','localhost'):
        print('\nWARNING: Public access must use HTTPS. Public HTTP is insecure.')
        if not yesno('Do you have a valid TLS certificate for this application?',False):
            raise SystemExit('Setup stopped. Choose localhost for a safer initial installation.')
        cfg['ssl_cert']=ask('Absolute path to TLS certificate',cfg.get('ssl_cert',''),lambda s:Path(s).is_file())
        cfg['ssl_key']=ask('Absolute path to TLS private key (readable by service user)',cfg.get('ssl_key',''),lambda s:Path(s).is_file())
    else:
        cfg['ssl_cert']='';cfg['ssl_key']=''
    cfg['username']=ask('Dashboard login username',cfg.get('username','admin'),lambda s:1<=len(s)<=48)
    print('The password will not be displayed in the terminal.')
    while True:
        p1=getpass.getpass('Password (minimum 12 characters; blank = keep existing): ')
        if not p1 and cfg.get('password_hash'): break
        if len(p1)<12:
            print('Password is too short.');continue
        p2=getpass.getpass('Confirm password: ')
        if p1!=p2:
            print('Passwords do not match.');continue
        salt=secrets.token_bytes(16)
        iterations=310000
        pw=hashlib.pbkdf2_hmac('sha256',p1.encode('utf-8'),salt,iterations)
        cfg['password_hash']='pbkdf2$%s$%s$%s' % (iterations,salt.hex(),pw.hex())
        break
    if not cfg.get('session_secret'): cfg['session_secret']=secrets.token_hex(32)
    if dest.parent.exists() is False: dest.parent.mkdir(parents=True,exist_ok=True)
    temp=dest.with_suffix('.json.tmp')
    temp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.chmod(temp,0o640)
    os.replace(temp,dest)
    print('\nConfiguration saved:',dest)
    print('Password is stored as a secure hash only.')
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (EOFError,KeyboardInterrupt):print('\nSetup cancelled.');sys.exit(130)
