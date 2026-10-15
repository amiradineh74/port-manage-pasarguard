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
 'sparse_samples':True,
 'listen_host':'127.0.0.1',
 'listen_port':8791,
 'timezone':'Asia/Tehran',
 'title':'Port Traffic & Cost Monitor',
 'default_bill_direction':'downlink',
 'default_price_per_gb':0,
 'currency':'Rial',
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



def running_docker_containers():
    """Read running container names only; no Docker or panel state is changed."""
    result=subprocess.run(['docker','ps','--format','{{.Names}}'],
        capture_output=True,text=True,timeout=10,check=False)
    if result.returncode:
        raise RuntimeError('Could not list running Docker containers. '
                           'Check Docker access and run: docker ps --format "{{.Names}}"')
    return sorted({name.strip() for name in result.stdout.splitlines() if name.strip()})


def probable_pasarguard_panel(name):
    """Suggest likely app containers, not PasarGuard's database/Redis/node services."""
    import re
    tokens=set(re.split(r'[-_.]+',name.lower()))
    if 'pasarguard' not in tokens:
        return False
    non_panels={'db','database','mysql','mariadb','postgres','postgresql',
                'redis','cache','node','xray','nginx','proxy','worker'}
    return not bool(tokens & non_panels)


def discover_panel_connection(cfg):
    """Let users choose a detected container and verify it with a SELECT-only probe.

    Never guess a running container if the panel is ambiguous. A wrong selection
    is retried instead of exiting setup or writing incomplete config.json.
    """
    try:
        names=running_docker_containers()
    except (OSError,subprocess.TimeoutExpired,RuntimeError) as exc:
        raise SystemExit('Cannot discover Docker containers: '+str(exc)) from exc
    if not names:
        raise SystemExit('No running Docker containers detected. '
                         'Start the existing PasarGuard panel separately and retry.')

    candidates=[name for name in names if probable_pasarguard_panel(name)]
    preferred=cfg.get('panel_container')
    suggested=(preferred if preferred in names else
               candidates[0] if len(candidates)==1 else '')
    print('\n=== Running Docker containers (read-only docker ps) ===')
    for index,name in enumerate(names,1):
        hint=' [possible PasarGuard panel]' if name in candidates else ''
        print('%s) %s%s' % (index,name,hint))
    if suggested:
        print('Suggested PasarGuard panel: '+suggested)
    else:
        print('Multiple/no obvious panels: choose a container number from the list.')
    print('This is NOT the dashboard title. Dashboard title is asked later.')
    print('Manual lookup: docker ps --format "table {{.Names}}\\t{{.Status}}"')
    while True:
        answer=input('Select PasarGuard panel container (number/name)%s: ' %
                     (' ['+suggested+']' if suggested else '')).strip()
        if not answer:
            if not suggested:
                print('Select a number or exact container name from the list.')
                continue
            selected=suggested
        elif answer.isdecimal():
            n=int(answer)
            if not 1<=n<=len(names):
                print('Invalid number. Choose a listed container.')
                continue
            selected=names[n-1]
        elif answer in names:
            selected=answer
        else:
            print('Unknown container. Select a listed Docker name, not a new dashboard name.')
            continue

        interpreter=ask('Python path inside selected container',
                        cfg.get('panel_python',DEFAULT['panel_python']),
                        lambda p:p.startswith('/') and ' ' not in p)
        print('Checking PasarGuard node list (SELECT only; no changes)...')
        try:
            nodes=list_nodes(selected,interpreter)
        except (OSError,subprocess.TimeoutExpired,RuntimeError) as exc:
            print('Could not read nodes from '+selected+': '+str(exc))
            print('Choose another listed container or check its Python path.')
            continue
        cfg['panel_container']=selected
        cfg['panel_python']=interpreter
        print('Verified read-only panel access:',selected)
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
    nodes=discover_panel_connection(cfg)
    choose_nodes(cfg,nodes)
    cfg['data_dir']=ask('Independent database directory',cfg['data_dir'],lambda s:s.startswith('/'))
    cfg['poll_interval']=ask('Collection interval in seconds (minimum 60)',cfg['poll_interval'],lambda n:60<=n<=86400,int)
    cfg['sparse_samples']=yesno('Skip idle zero-byte samples to save disk? (counter baselines kept)',cfg.get('sparse_samples',True))
    cfg['title']=ask('Dashboard title',cfg['title'])
    def timezone_ok(value):
        try:ZoneInfo(value);return True
        except Exception:return False
    cfg['timezone']=ask('Reporting timezone',cfg['timezone'],timezone_ok)
    cfg['listen_host']=ask('Web listen address (127.0.0.1 recommended)',cfg['listen_host'])
    cfg['listen_port']=ask('Dashboard port',cfg['listen_port'],lambda n:1024<=n<=65535,int)
    # One immutable choice per independent installation: no provider/port overrides.
    # Old configs get an explicit choice when setup is run, never a silent conversion.
    if 'traffic_unit' not in cfg:
        print('Traffic/accounting unit: GB = 1,000,000,000 bytes (1000); '
              'GiB = 1,073,741,824 bytes (1024).')
        cfg['traffic_unit']=ask('Choose ONE traffic unit for the whole installation: GB or GiB',
                                'GiB',lambda x:x in ('GB','GiB'))
    else:
        from units import check_unit
        check_unit(cfg['traffic_unit'])
        print('Traffic unit (locked for this installation):',cfg['traffic_unit'])
    cfg['currency']=ask('Display currency: Rial or Toman',cfg['currency'],
         lambda name:name in ('Rial','Toman','ریال','تومان'))
    cfg['default_bill_direction']=ask('Default billed direction: downlink/uplink/both',cfg['default_bill_direction'],lambda s:s in ('downlink','uplink','both'))
    # Keep all stored rates in Toman for backwards-compatible SQLite snapshots;
    # the installer accepts Rial when the selected display currency is Rial.
    use_rial=cfg['currency'] in ('Rial','ریال')
    shown_rate=cfg['default_price_per_gb'] * (10 if use_rial else 1)
    entered_rate=ask('Default rate per '+cfg['traffic_unit']+' in '+('Rial' if use_rial else 'Toman')+
        ' (0 = configure later per port)',shown_rate,lambda n:0<=n<1e13,float)
    cfg['default_price_per_gb']=entered_rate/(10 if use_rial else 1)
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
