"""Supplier wallets and purchased traffic quotas, independent from PasarGuard.

A supplier account starts at a manually recorded balance checkpoint. Port bindings
start when saved; only subsequently collected Xray deltas are counted. Provider
reported balances are comparison snapshots, never automatically treated as credits.
All money is integer IRR. Volume and rate units use the single installation-wide
GB/GiB choice; historical rate terms retain their original divisor for audit.
"""
from datetime import datetime,timezone
from decimal import Decimal, ROUND_HALF_UP
from units import selected_bytes_per_unit

MAX_AMOUNT=10**15
DIRECTIONS=('downlink','uplink','both')

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def require_int(value, name, minimum=0, maximum=MAX_AMOUNT):
    if type(value) is not int or not minimum<=value<=maximum:
        raise ValueError(name+' باید عدد صحیح معتبر باشد')
    return value

def text_field(value,name,maximum=128,required=False):
    if type(value) is not str or len(value.strip())>maximum or (required and not value.strip()):
        raise ValueError(name+' معتبر نیست')
    return value.strip()

def known_account(db, account_id):
    require_int(account_id,'شناسه حساب',1)
    row=db.execute('SELECT * FROM supplier_accounts WHERE id=?',(account_id,)).fetchone()
    if row is None:raise ValueError('حساب تأمین‌کننده پیدا نشد')
    return dict(row)

def create_account(db,data):
    if type(data) is not dict:raise ValueError('داده نامعتبر است')
    kind=data.get('kind')
    if kind not in ('money','volume'):raise ValueError('نوع حساب باید پولی یا حجمی باشد')
    title=text_field(data.get('title'),'عنوان',128,True)
    handle=text_field(data.get('bot_handle',''),'شناسه ربات',128)
    notes=text_field(data.get('notes',''),'یادداشت',1000)
    initial=require_int(data.get('opening_amount'),'موجودی اولیه')
    # The current balance checkpoint ALREADY includes previous purchases/topups.
    now=utc_now()
    db.execute('''INSERT INTO supplier_accounts
      (title,bot_handle,kind,started_at,opening_rial,opening_bytes,notes)
      VALUES(?,?,?,?,?,?,?)''',
      (title,handle,kind,now,initial if kind=='money' else 0,
       initial if kind=='volume' else 0,notes))
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]

def update_account(db,data):
    account=known_account(db,data.get('id'))
    title=text_field(data.get('title'),'عنوان',128,True)
    handle=text_field(data.get('bot_handle',''),'شناسه ربات',128)
    notes=text_field(data.get('notes',''),'یادداشت',1000)
    db.execute('UPDATE supplier_accounts SET title=?,bot_handle=?,notes=? WHERE id=?',
               (title,handle,notes,account['id']))
    return account['id']

def attach_port(db,data):
    account=known_account(db,data.get('account_id'))
    node=require_int(data.get('node_id'),'شناسه نود',1,2**31-1)
    port=require_int(data.get('port'),'شماره پورت',1,65535)
    if db.execute('SELECT 1 FROM port_state WHERE node_id=? AND port=?',
                  (node,port)).fetchone() is None:
        raise ValueError('ابتدا باید این نود و پورت در مانیتور مشاهده شده باشد')
    if _current_port(db,node,port):
        raise ValueError('این نود و پورت قبلاً به حساب دیگری متصل شده؛ اتصال تکراری مجاز نیست')
    direction=data.get('direction')
    if direction not in DIRECTIONS:raise ValueError('جهت ترافیک معتبر نیست')
    rate=require_int(data.get('rate_rial_per_gb',0),'تعرفه ریال بر گیگ',0,10**12)
    if account['kind']=='volume' and rate:raise ValueError('حساب حجمی نیاز به نرخ پولی ندارد')
    db.execute('''INSERT INTO supplier_ports
        (account_id,node_id,port,started_at,direction,rate_rial_per_gb,bytes_per_unit)
        VALUES(?,?,?,?,?,?,?)''',
        (account['id'],node,port,utc_now(),direction,rate,selected_bytes_per_unit(db)))
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]

def provider_paths(db,provider):
    """Metadata is the only authoritative source for provider/port ownership here."""
    return [dict(r) for r in db.execute('''SELECT p.node_id,p.port,
          m.bill_direction,m.price_per_gb
          FROM metadata m JOIN port_state p ON p.node_id=m.node_id AND p.port=m.port
          WHERE m.provider=? ORDER BY p.node_id,p.port''',(provider,))]

def _current_port(db,node,port):
    return db.execute("""SELECT * FROM supplier_ports
        WHERE node_id=? AND port=? AND ended_at=''""",(node,port)).fetchone()

def sync_provider_port(db,provider,node_id,port,direction,rate_toman):
    """Reprice only *assigned* active ports; never attach unassigned ports implicitly."""
    row=_current_port(db,node_id,port)
    if row is None:return
    linked=db.execute('SELECT provider FROM provider_wallet_links WHERE account_id=?',
                      (row['account_id'],)).fetchone()
    if not linked or linked['provider']!=provider:return
    account=known_account(db,row['account_id'])
    if direction not in DIRECTIONS:raise ValueError('جهت ترافیک نامعتبر است')
    rate=0 if account['kind']=='volume' else int((
        Decimal(str(rate_toman))*Decimal(10)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    latest=db.execute('''SELECT direction,rate_rial_per_gb,bytes_per_unit FROM supplier_port_terms
       WHERE binding_id=? ORDER BY started_at DESC,id DESC LIMIT 1''',(row['id'],)).fetchone()
    previous_direction=latest['direction'] if latest else row['direction']
    previous_rate=latest['rate_rial_per_gb'] if latest else row['rate_rial_per_gb']
    previous_unit=latest['bytes_per_unit'] if latest else row['bytes_per_unit']
    if previous_direction!=direction or previous_rate!=rate or previous_unit!=selected_bytes_per_unit(db):
        db.execute('''INSERT INTO supplier_port_terms
          (binding_id,started_at,direction,rate_rial_per_gb,bytes_per_unit) VALUES(?,?,?,?,?)
          ON CONFLICT(binding_id,started_at) DO UPDATE SET
             direction=excluded.direction,rate_rial_per_gb=excluded.rate_rial_per_gb,
             bytes_per_unit=excluded.bytes_per_unit''',
          (row['id'],utc_now(),direction,rate,selected_bytes_per_unit(db)))

def _selected_paths(db,provider,ports):
    if not isinstance(ports,list) or len(ports)>200:
        raise ValueError('فهرست پورت‌ها معتبر نیست')
    available={(r['node_id'],r['port']):r for r in provider_paths(db,provider)}
    selected=[]
    seen=set()
    for entry in ports:
        if type(entry) is not dict:raise ValueError('مشخصات پورت معتبر نیست')
        node=require_int(entry.get('node_id'),'شناسه نود',1,2**31-1)
        port=require_int(entry.get('port'),'شماره پورت',1,65535)
        key=(node,port)
        if key not in available:raise ValueError('پورت '+str(port)+' متعلق به این ارائه‌دهنده نیست')
        if key in seen:raise ValueError('پورت تکراری است')
        seen.add(key)
        selected.append(available[key])
    return selected

def _apply_ports(db,account_id,provider,selected,now,allow_transfer=False):
    """Close prior active intervals and open new intervals; NEVER rewrite past usage."""
    selected_keys={(p['node_id'],p['port']) for p in selected}
    previous=db.execute('''SELECT * FROM supplier_ports
        WHERE account_id=? AND ended_at='' ''',(account_id,)).fetchall()
    for old in previous:
        if (old['node_id'],old['port']) not in selected_keys:
            db.execute("UPDATE supplier_ports SET ended_at=? WHERE id=?",(now,old['id']))
    for p in selected:
        active=_current_port(db,p['node_id'],p['port'])
        if active and active['account_id']==account_id:
            continue
        if active:
            if not allow_transfer:
                raise ValueError('انتقال پورت از حساب دیگر نیاز به تأیید صریح دارد')
            # Explicit transfer preserves old account's consumed bytes and rate terms.
            other_provider=db.execute('''SELECT provider FROM provider_wallet_links
                WHERE account_id=?''',(active['account_id'],)).fetchone()
            if not other_provider or other_provider['provider']!=provider:
                raise ValueError('این پورت به حسابی خارج از این ارائه‌دهنده متصل است')
            db.execute('UPDATE supplier_ports SET ended_at=? WHERE id=?',
                       (now,active['id']))
        direction=p['bill_direction']
        account=known_account(db,account_id)
        rate=0 if account['kind']=='volume' else int((
            Decimal(str(p['price_per_gb']))*Decimal(10)).quantize(
                Decimal('1'),rounding=ROUND_HALF_UP))
        db.execute('''INSERT INTO supplier_ports
            (account_id,node_id,port,started_at,direction,rate_rial_per_gb,bytes_per_unit)
            VALUES(?,?,?,?,?,?,?)''',(account_id,p['node_id'],p['port'],now,direction,rate,selected_bytes_per_unit(db)))

def assign_provider_wallet(db,data):
    """Create/link/edit an independent account and explicitly choose its ports.

    Existing provider accounts and port intervals remain; transferring a port
    ends one interval and starts another at the SAME timestamp.
    """
    if type(data) is not dict:raise ValueError('اطلاعات اعتبار نامعتبر است')
    provider=text_field(data.get('provider'),'ارائه‌دهنده',128,True)
    if provider=='بدون ارائه‌دهنده':raise ValueError('ابتدا نام ارائه‌دهنده ثبت کنید')
    paths=provider_paths(db,provider)
    if not paths:raise ValueError('برای این ارائه‌دهنده پورتی ثبت نشده است')
    selected=_selected_paths(db,provider,data.get('ports'))
    existing_id=data.get('existing_account_id')
    editing_id=data.get('account_id')
    if existing_id is not None and editing_id is not None:
        raise ValueError('فقط یک نوع عملیات حساب مجاز است')
    if existing_id is not None or editing_id is not None:
        account_id=existing_id if existing_id is not None else editing_id
        account=known_account(db,account_id)
        old_link=db.execute('SELECT provider FROM provider_wallet_links WHERE account_id=?',
                            (account_id,)).fetchone()
        if old_link and old_link['provider']!=provider:
            raise ValueError('حساب به ارائه‌دهنده دیگری تعلق دارد')
        if not old_link:
            incompatible=db.execute('''SELECT 1 FROM supplier_ports b
                LEFT JOIN metadata m ON m.node_id=b.node_id AND m.port=b.port
                WHERE b.account_id=? AND COALESCE(m.provider,'')!=? LIMIT 1''',
                (account_id,provider)).fetchone()
            if incompatible:raise ValueError('حساب قدیمی پورت متعلق به ارائه‌دهنده دیگری دارد')
    else:
        account_id=create_account(db,{
            'kind':data.get('kind'),
            'title':data.get('title') or provider,
            'bot_handle':data.get('bot_handle',''),
            'opening_amount':data.get('opening_amount'),
            'notes':data.get('notes','')})
    # Prevent transfer from unlinked manually-created accounts; link those first.
    for p in selected:
        active=_current_port(db,p['node_id'],p['port'])
        if active and active['account_id']!=account_id:
            link=db.execute('SELECT provider FROM provider_wallet_links WHERE account_id=?',
                            (active['account_id'],)).fetchone()
            if not link or link['provider']!=provider:
                raise ValueError('پورت به کیف پول دیگری که متعلق به این ارائه‌دهنده نیست متصل است')
    db.execute('INSERT OR IGNORE INTO provider_wallet_links(provider,account_id) VALUES(?,?)',
               (provider,account_id))
    if type(data.get('confirm_transfer',False)) is not bool:
        raise ValueError('تأیید انتقال نامعتبر است')
    _apply_ports(db,account_id,provider,selected,utc_now(),data.get('confirm_transfer',False))
    return account_id

def add_credit(db,data):
    account=known_account(db,data.get('account_id'))
    amount=require_int(data.get('amount'),'مقدار شارژ/حجم خریداری‌شده',1)
    note=text_field(data.get('note',''),'شرح شارژ',250)
    db.execute('INSERT INTO supplier_credits(account_id,amount,created_at,note) VALUES(?,?,?,?)',
               (account['id'],amount,utc_now(),note))
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]

def reconcile_balance(db,data):
    """Append a signed correction without mutating recorded traffic or credits.

    Caller holds a SQLite write transaction so the measured balance, journal
    entry and provider-reported reference form one consistent snapshot.
    """
    if type(data) is not dict:raise ValueError('اطلاعات همسان‌سازی معتبر نیست')
    account=known_account(db,data.get('account_id'))
    reported=require_int(data.get('amount'),'مانده اعلام‌شده ربات',0)
    note=text_field(data.get('note',''),'توضیح همسان‌سازی',250)
    now=utc_now()
    bindings=[dict(row) for row in db.execute(
        'SELECT * FROM supplier_ports WHERE account_id=?',(account['id'],))]
    before=_estimate(db,account,bindings,now)['estimated_balance']
    adjustment=reported-before     # signed: positive=bot had more; negative=bot had less
    db.execute('''INSERT INTO supplier_reconciliations
      (account_id,checked_at,reported_amount,estimated_before,adjustment,note)
      VALUES(?,?,?,?,?,?)''',(account['id'],now,reported,before,adjustment,note))
    if account['kind']=='money':
        db.execute('UPDATE supplier_accounts SET reported_rial=?,reported_at=? WHERE id=?',
                   (reported,now,account['id']))
    else:
        db.execute('UPDATE supplier_accounts SET reported_bytes=?,reported_at=? WHERE id=?',
                   (reported,now,account['id']))
    # Return the adjustment for user feedback; no supplier bot is contacted.
    return {'account_id':account['id'],'adjustment':adjustment,
            'estimated_before':before,'reported_balance':reported,
            'balance_after':reported}

def undo_reconciliation(db,data):
    """Cancel only the latest active correction; retain the original audit row.

    Caller must hold BEGIN IMMEDIATE so the latest-entry check, void record,
    reported snapshot and balance are a single atomic operation. Requiring
    newest first prevents silently invalidating later balance checkpoints.
    """
    if type(data) is not dict:raise ValueError('درخواست لغو همسان‌سازی نامعتبر است')
    account=known_account(db,data.get('account_id'))
    reconcile_id=require_int(data.get('reconciliation_id'),'شناسه همسان‌سازی',1)
    reason=text_field(data.get('reason',''),'دلیل لغو',250)
    target=db.execute('''SELECT id,adjustment FROM supplier_reconciliations
        WHERE id=? AND account_id=?''',(reconcile_id,account['id'])).fetchone()
    if target is None:raise ValueError('همسان‌سازی متعلق به این حساب پیدا نشد')
    already=db.execute('''SELECT 1 FROM supplier_reconciliation_voids
        WHERE reconciliation_id=?''',(reconcile_id,)).fetchone()
    if already:raise ValueError('این همسان‌سازی قبلاً لغو شده است')
    latest=db.execute('''SELECT r.id FROM supplier_reconciliations r
        LEFT JOIN supplier_reconciliation_voids v ON v.reconciliation_id=r.id
        WHERE r.account_id=? AND v.reconciliation_id IS NULL
        ORDER BY r.checked_at DESC,r.id DESC LIMIT 1''',(account['id'],)).fetchone()
    if latest is None or latest['id']!=reconcile_id:
        raise ValueError('برای حفظ ترتیب حسابداری، ابتدا همسان‌سازی‌های جدیدتر را لغو کنید')
    bindings=[dict(row) for row in db.execute(
        'SELECT * FROM supplier_ports WHERE account_id=?',(account['id'],))]
    balance_before=_estimate(db,account,bindings)['estimated_balance']
    db.execute('''INSERT INTO supplier_reconciliation_voids
        (reconciliation_id,account_id,voided_at,reason) VALUES(?,?,?,?)''',
        (reconcile_id,account['id'],utc_now(),reason))
    previous=db.execute('''SELECT r.reported_amount,r.checked_at
        FROM supplier_reconciliations r
        LEFT JOIN supplier_reconciliation_voids v ON v.reconciliation_id=r.id
        WHERE r.account_id=? AND v.reconciliation_id IS NULL
        ORDER BY r.checked_at DESC,r.id DESC LIMIT 1''',(account['id'],)).fetchone()
    reported_column='reported_rial' if account['kind']=='money' else 'reported_bytes'
    db.execute('UPDATE supplier_accounts SET '+reported_column+
               '=?,reported_at=? WHERE id=?',
               (previous['reported_amount'] if previous else None,
                previous['checked_at'] if previous else '',account['id']))
    balance_after=_estimate(db,account,bindings)['estimated_balance']
    return {'account_id':account['id'],'reconciliation_id':reconcile_id,
            'reversed_adjustment':-target['adjustment'],
            'balance_before':balance_before,'balance_after':balance_after}


def report_balance(db,data):
    """Backwards-compatible endpoint now performs a genuine synchronization."""
    return reconcile_balance(db,data)

def _estimate(db,account,bindings,until=None):
    spent_rial=0
    spent_bytes=0
    per_port=[]
    for row in bindings:
        terms=[{'started_at':row['started_at'],
                'direction':row['direction'],'rate_rial_per_gb':row['rate_rial_per_gb'],
                'bytes_per_unit':row['bytes_per_unit']}]
        history=db.execute('''SELECT started_at,direction,rate_rial_per_gb,bytes_per_unit
            FROM supplier_port_terms WHERE binding_id=? ORDER BY started_at,id''',
            (row['id'],)).fetchall()
        for term in history:
            if not until or term['started_at']<=until:
                terms.append(dict(term))
        port_down=port_up=port_bill=port_charge=0
        for index,term in enumerate(terms):
            lower=max(row['started_at'],term['started_at'])
            upper=terms[index+1]['started_at'] if index+1<len(terms) else None
            if until and lower>until:continue
            filters=['node_id=?','port=?','collected_at>=?']
            params=[row['node_id'],row['port'],lower]
            if upper:
                filters.append('collected_at<?');params.append(upper)
            if row['ended_at']:
                filters.append('collected_at<?');params.append(row['ended_at'])
            if until:
                filters.append('collected_at<=?');params.append(until)
            down,up=db.execute('''SELECT COALESCE(SUM(delta_down),0),
                COALESCE(SUM(delta_up),0) FROM samples WHERE '''+
                ' AND '.join(filters),params).fetchone()
            down,up=int(down),int(up)
            billed={'downlink':down,'uplink':up,'both':down+up}[term['direction']]
            charge=int((Decimal(billed)*Decimal(term['rate_rial_per_gb'])/Decimal(term['bytes_per_unit']))
                       .quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            port_down+=down;port_up+=up;port_bill+=billed;port_charge+=charge
        spent_bytes+=port_bill;spent_rial+=port_charge
        last=terms[-1]
        per_port.append(dict(row,down_bytes=port_down,up_bytes=port_up,
                 billed_bytes=port_bill,charge_rial=port_charge,
                 direction=last['direction'],rate_rial_per_gb=last['rate_rial_per_gb']))
    credits=db.execute('''SELECT COALESCE(SUM(amount),0) FROM supplier_credits
      WHERE account_id=? AND created_at>=?'''+(' AND created_at<=?' if until else ''),
      (account['id'],account['started_at'],until) if until else
      (account['id'],account['started_at'])).fetchone()[0]
    initial=account['opening_rial'] if account['kind']=='money' else account['opening_bytes']
    adjustments=db.execute('''SELECT COALESCE(SUM(r.adjustment),0)
        FROM supplier_reconciliations r
        LEFT JOIN supplier_reconciliation_voids v ON v.reconciliation_id=r.id
        WHERE r.account_id=? AND v.reconciliation_id IS NULL'''+
        (' AND r.checked_at<=?' if until else ''),
        (account['id'],until) if until else (account['id'],)).fetchone()[0]
    balance=int(initial)+int(credits)+int(adjustments)-(
        spent_rial if account['kind']=='money' else spent_bytes)
    return {'estimated_balance':balance,'credited':int(credits),'adjustments':int(adjustments),
            'used_bytes':spent_bytes,'spent_rial':spent_rial,'ports':per_port}

def wallet_report(db):
    accounts=[]
    for a in db.execute('SELECT * FROM supplier_accounts ORDER BY id DESC').fetchall():
        account=dict(a)
        association=db.execute('SELECT provider FROM provider_wallet_links WHERE account_id=?',
                               (a['id'],)).fetchone()
        account['provider']=association['provider'] if association else ''
        account['active_port_count']=db.execute("SELECT COUNT(*) FROM supplier_ports WHERE account_id=? AND ended_at=''",(a['id'],)).fetchone()[0]
        bindings=[dict(r) for r in db.execute('''SELECT b.*,p.node_name
           FROM supplier_ports b LEFT JOIN port_state p ON p.node_id=b.node_id AND p.port=b.port
           WHERE b.account_id=? ORDER BY b.node_id,b.port''',(a['id'],))]
        result=_estimate(db,account,bindings)
        reported=(account['reported_rial'] if a['kind']=='money' else account['reported_bytes'])
        checks=[dict(r) for r in db.execute(
            'SELECT * FROM supplier_checks WHERE account_id=? ORDER BY id DESC LIMIT 20',(a['id'],))]
        history=[dict(r) for r in db.execute(
            '''SELECT r.*,v.voided_at,v.reason AS void_reason
               FROM supplier_reconciliations r
               LEFT JOIN supplier_reconciliation_voids v ON v.reconciliation_id=r.id
               WHERE r.account_id=?
               ORDER BY r.checked_at DESC,r.id DESC LIMIT 2000''',(a['id'],))]
        active_history=[h for h in history if not h['voided_at']]
        comparison=active_history[0]['adjustment'] if active_history else (
            checks[0]['difference'] if checks else None)
        totals=db.execute('''SELECT COUNT(*),
          COALESCE(SUM(CASE WHEN r.adjustment>0 THEN r.adjustment ELSE 0 END),0),
          COALESCE(SUM(CASE WHEN r.adjustment<0 THEN -r.adjustment ELSE 0 END),0),
          COALESCE(SUM(r.adjustment),0)
          FROM supplier_reconciliations r
          LEFT JOIN supplier_reconciliation_voids v ON v.reconciliation_id=r.id
          WHERE r.account_id=? AND v.reconciliation_id IS NULL''',(a['id'],)).fetchone()
        reconciliation_summary={'count':totals[0],'positive':totals[1],
            'negative':totals[2],'net':totals[3]}

        credits=[dict(r) for r in db.execute(
            'SELECT * FROM supplier_credits WHERE account_id=? ORDER BY id DESC LIMIT 20',(a['id'],))]
        accounts.append(dict(account,**result,reported_balance=reported,
                             comparison_gap=comparison,credit_history=credits,
                             check_history=checks,
                             reconciliation_history=history,
                             latest_active_reconciliation_id=(
                                 active_history[0]['id'] if active_history else None),
                             reconciliation_summary=reconciliation_summary))
    return accounts
