"""Supplier wallets and purchased traffic quotas, independent from PasarGuard.

A supplier account starts at a manually recorded balance checkpoint. Port bindings
start when saved; only subsequently collected Xray deltas are counted. Provider
reported balances are comparison snapshots, never automatically treated as credits.
All money is integer IRR; all traffic is decimal GB (1 GB = 1e9 bytes).
"""
from datetime import datetime,timezone
from decimal import Decimal, ROUND_HALF_UP

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
    if db.execute('SELECT 1 FROM supplier_ports WHERE node_id=? AND port=?',
                  (node,port)).fetchone():
        raise ValueError('این نود و پورت قبلاً به حساب دیگری متصل شده؛ اتصال تکراری مجاز نیست')
    direction=data.get('direction')
    if direction not in DIRECTIONS:raise ValueError('جهت ترافیک معتبر نیست')
    rate=require_int(data.get('rate_rial_per_gb',0),'تعرفه ریال بر گیگ',0,10**12)
    if account['kind']=='volume' and rate:raise ValueError('حساب حجمی نیاز به نرخ پولی ندارد')
    db.execute('''INSERT INTO supplier_ports(account_id,node_id,port,started_at,direction,rate_rial_per_gb)
                  VALUES(?,?,?,?,?,?)''',
               (account['id'],node,port,utc_now(),direction,rate))
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]

def assigned_provider_ports(db, provider):
    # Metadata is the single source of truth for provider -> node/port identity.
    # Hidden ports count too: hiding a row cannot make real supplier bills vanish.
    return [(r['node_id'],r['port']) for r in db.execute(
        '''SELECT p.node_id,p.port FROM port_state p JOIN metadata m
        ON p.node_id=m.node_id AND p.port=m.port
        WHERE m.provider=? ORDER BY p.node_id,p.port''',(provider,))]

def sync_provider_bindings(db):
    """Add newly assigned provider ports without ever touching usage samples.

    Existing bindings are never rewritten: their historical checkpoint/rate is
    financially meaningful. Conflicts are skipped, not silently reassigned.
    """
    for link in db.execute('SELECT * FROM supplier_provider_links').fetchall():
        for node_id,port in assigned_provider_ports(db,link['provider']):
            taken=db.execute('SELECT 1 FROM supplier_ports WHERE node_id=? AND port=?',
                             (node_id,port)).fetchone()
            if not taken:
                db.execute('''INSERT INTO supplier_ports
                    (account_id,node_id,port,started_at,direction,rate_rial_per_gb)
                    VALUES(?,?,?,?,?,?)''',
                    (link['account_id'],node_id,port,utc_now(),link['default_direction'],
                     link['default_rate_rial_per_gb']))

def link_provider_account(db,data):
    """Set up a wallet directly on an already existing provider.

    Either adopt an existing account (preserves all prior credit/check history),
    or create exactly one new account without asking for port identities.
    """
    if type(data) is not dict:raise ValueError('درخواست نامعتبر است')
    provider=text_field(data.get('provider'),'ارائه‌دهنده',128,True)
    ports=assigned_provider_ports(db,provider)
    if not ports:raise ValueError('ابتدا ارائه‌دهنده را به یک پورت واقعی اختصاص بدهید')
    existing=db.execute('SELECT account_id FROM supplier_provider_links WHERE provider=?',
                        (provider,)).fetchone()
    if existing:raise ValueError('این ارائه‌دهنده کیف پول دارد؛ دوباره ایجادش نکنید')
    direction=data.get('direction','both')
    if direction not in DIRECTIONS:raise ValueError('جهت مصرف معتبر نیست')
    rate=require_int(data.get('rate_rial_per_gb',0),'تعرفه ریالی',0,10**12)
    old_id=data.get('existing_account_id')
    if old_id is not None:
        account=known_account(db,old_id)
        linked=db.execute('SELECT provider FROM supplier_provider_links WHERE account_id=?',
                          (old_id,)).fetchone()
        if linked:raise ValueError('این حساب قبلاً به ارائه‌دهنده دیگری وصل شده')
        if account['kind']=='volume' and rate:raise ValueError('حساب حجمی تعرفه ریالی ندارد')
        # A manually linked account can be adopted only when its historical ports
        # are all part of this provider; never alter an unrelated wallet.
        old_ports=[(r['node_id'],r['port']) for r in db.execute(
            'SELECT node_id,port FROM supplier_ports WHERE account_id=?',(old_id,))]
        if not set(old_ports).issubset(set(ports)):
            raise ValueError('برخی پورت‌های قبلی این حساب متعلق به این ارائه‌دهنده نیستند')
        account_id=account['id']
    else:
        kind=data.get('kind')
        if kind not in ('money','volume'):raise ValueError('نوع کیف پول معتبر نیست')
        if kind=='volume' and rate:raise ValueError('حساب حجمی تعرفه ریالی ندارد')
        account_id=create_account(db,{'title':provider,'bot_handle':'',
           'kind':kind,'opening_amount':data.get('opening_amount'),'notes':''})
    conflict=db.execute(
        '''SELECT b.account_id FROM supplier_ports b JOIN metadata m
           ON m.node_id=b.node_id AND m.port=b.port
           WHERE m.provider=? AND b.account_id<>? LIMIT 1''',
        (provider,account_id)).fetchone()
    if conflict:raise ValueError('برخی پورت‌ها به کیف پول دیگری وصل‌اند؛ اتصال خودکار متوقف شد')
    db.execute('''INSERT INTO supplier_provider_links
      (provider,account_id,default_direction,default_rate_rial_per_gb)
      VALUES(?,?,?,?)''',(provider,account_id,direction,rate))
    sync_provider_bindings(db)
    return account_id

def provider_paths(db,provider):
    """Metadata is the only authoritative source for provider/port ownership here."""
    return [dict(r) for r in db.execute('''SELECT p.node_id,p.port,
          m.bill_direction,m.price_per_gb
          FROM metadata m JOIN port_state p ON p.node_id=m.node_id AND p.port=m.port
          WHERE m.provider=? ORDER BY p.node_id,p.port''',(provider,))]

def sync_provider_port(db,provider,node_id,port,direction,rate_toman):
    """Bind a freshly configured port without rewriting old sample checkpoints."""
    association=db.execute(
        'SELECT account_id FROM provider_wallet_links WHERE provider=?',(provider,)).fetchone()
    if not association:return
    account_id=association['account_id']
    existing=db.execute('SELECT account_id FROM supplier_ports WHERE node_id=? AND port=?',
                        (node_id,port)).fetchone()
    if existing:
        if existing['account_id']!=account_id:
            raise ValueError('این پورت قبلاً به کیف پول دیگری متصل شده؛ ابتدا اتصال قبلی را بررسی کنید')
        return
    account=known_account(db,account_id)
    if direction not in DIRECTIONS:raise ValueError('جهت ترافیک نامعتبر است')
    rate=0 if account['kind']=='volume' else int((
        Decimal(str(rate_toman))*Decimal(10)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    db.execute('''INSERT INTO supplier_ports
       (account_id,node_id,port,started_at,direction,rate_rial_per_gb)
       VALUES(?,?,?,?,?,?)''',(account_id,node_id,port,utc_now(),direction,rate))

def assign_provider_wallet(db,data):
    """Create or reuse one wallet for an existing provider; never recreate port records."""
    if type(data) is not dict:raise ValueError('اطلاعات ارائه‌دهنده نامعتبر است')
    provider=text_field(data.get('provider'),'نام ارائه‌دهنده',128,True)
    if provider=='بدون ارائه‌دهنده':raise ValueError('ابتدا برای پورت‌ها نام ارائه‌دهنده تنظیم کنید')
    paths=provider_paths(db,provider)
    if not paths:raise ValueError('برای این ارائه‌دهنده هنوز پورتی ثبت نشده است')
    if db.execute('SELECT 1 FROM provider_wallet_links WHERE provider=?',(provider,)).fetchone():
        raise ValueError('این ارائه‌دهنده از قبل کیف پول دارد')
    existing_id=data.get('existing_account_id')
    if existing_id is not None:
        account=known_account(db,existing_id)
        if db.execute('SELECT 1 FROM provider_wallet_links WHERE account_id=?',
                      (existing_id,)).fetchone():
            raise ValueError('این کیف پول به ارائه‌دهنده دیگری اختصاص دارد')
        incompatible=db.execute('''SELECT b.node_id,b.port FROM supplier_ports b
              LEFT JOIN metadata m ON m.node_id=b.node_id AND m.port=b.port
              WHERE b.account_id=? AND COALESCE(m.provider,'')!=? LIMIT 1''',
              (existing_id,provider)).fetchone()
        if incompatible:raise ValueError('این حساب پورت متعلق به ارائه‌دهنده دیگری دارد')
        account_id=existing_id
    else:
        account_id=create_account(db,{
            'kind':data.get('kind'),
            'title':provider,
            'bot_handle':data.get('bot_handle',''),
            'opening_amount':data.get('opening_amount'),
            'notes':data.get('notes','')})
    # Preflight all conflicts BEFORE inserting any links, in a single transaction.
    for row in paths:
        existing=db.execute('SELECT account_id FROM supplier_ports WHERE node_id=? AND port=?',
                            (row['node_id'],row['port'])).fetchone()
        if existing and existing['account_id']!=account_id:
            raise ValueError('پورت '+str(row['port'])+' قبلاً به حساب دیگری متصل است')
    db.execute('INSERT INTO provider_wallet_links(provider,account_id) VALUES(?,?)',
               (provider,account_id))
    for row in paths:
        sync_provider_port(db,provider,row['node_id'],row['port'],
                           row['bill_direction'],row['price_per_gb'])
    return account_id

def add_credit(db,data):
    account=known_account(db,data.get('account_id'))
    amount=require_int(data.get('amount'),'مقدار شارژ/حجم خریداری‌شده',1)
    note=text_field(data.get('note',''),'شرح شارژ',250)
    db.execute('INSERT INTO supplier_credits(account_id,amount,created_at,note) VALUES(?,?,?,?)',
               (account['id'],amount,utc_now(),note))
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]

def report_balance(db,data):
    account=known_account(db,data.get('account_id'))
    amount=require_int(data.get('amount'),'مانده اعلام‌شده',0)
    now=utc_now()
    bindings=[dict(r) for r in db.execute(
        'SELECT * FROM supplier_ports WHERE account_id=?',(account['id'],))]
    estimate=_estimate(db,account,bindings,now)['estimated_balance']
    gap=estimate-amount
    if account['kind']=='money':
        db.execute('UPDATE supplier_accounts SET reported_rial=?,reported_at=? WHERE id=?',
                   (amount,now,account['id']))
    else:
        db.execute('UPDATE supplier_accounts SET reported_bytes=?,reported_at=? WHERE id=?',
                   (amount,now,account['id']))
    db.execute('''INSERT INTO supplier_checks(account_id,checked_at,reported_amount,estimated_amount,difference)
                  VALUES(?,?,?,?,?)''',(account['id'],now,amount,estimate,gap))

def _estimate(db,account,bindings,until=None):
    spent_rial=0
    spent_bytes=0
    per_port=[]
    for row in bindings:
        params=[row['node_id'],row['port'],row['started_at']]
        upper=''
        if until:
            upper=' AND collected_at<=?'
            params.append(until)
        usage=db.execute('''SELECT COALESCE(SUM(delta_down),0),COALESCE(SUM(delta_up),0)
          FROM samples WHERE node_id=? AND port=? AND collected_at>=?'''+upper,params).fetchone()
        down,up=int(usage[0]),int(usage[1])
        bill={'downlink':down,'uplink':up,'both':down+up}[row['direction']]
        charge=int((Decimal(bill)*Decimal(row['rate_rial_per_gb'])/Decimal(10**9))
                   .quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        spent_bytes+=bill
        spent_rial+=charge
        per_port.append(dict(row,down_bytes=down,up_bytes=up,billed_bytes=bill,charge_rial=charge))
    credits=db.execute('''SELECT COALESCE(SUM(amount),0) FROM supplier_credits
      WHERE account_id=? AND created_at>=?'''+(' AND created_at<=?' if until else ''),
      (account['id'],account['started_at'],until) if until else
      (account['id'],account['started_at'])).fetchone()[0]
    initial=account['opening_rial'] if account['kind']=='money' else account['opening_bytes']
    balance=int(initial)+int(credits)-(spent_rial if account['kind']=='money' else spent_bytes)
    return {'estimated_balance':balance,'credited':int(credits),'used_bytes':spent_bytes,
            'spent_rial':spent_rial,'ports':per_port}

def wallet_report(db):
    # Cheap SQLite-only synchronization; node IPs or tags are not used here.
    with db:sync_provider_bindings(db)
    accounts=[]
    for a in db.execute('''SELECT a.*,l.provider linked_provider,
                        l.default_direction,l.default_rate_rial_per_gb
        FROM supplier_accounts a LEFT JOIN supplier_provider_links l
        ON l.account_id=a.id ORDER BY a.id DESC''').fetchall():
        account=dict(a)
        association=db.execute('SELECT provider FROM provider_wallet_links WHERE account_id=?',
                               (a['id'],)).fetchone()
        account['provider']=association['provider'] if association else ''
        bindings=[dict(r) for r in db.execute('''SELECT b.*,p.node_name
           FROM supplier_ports b LEFT JOIN port_state p ON p.node_id=b.node_id AND p.port=b.port
           WHERE b.account_id=? ORDER BY b.node_id,b.port''',(a['id'],))]
        result=_estimate(db,account,bindings)
        reported=(account['reported_rial'] if a['kind']=='money' else account['reported_bytes'])
        checks=[dict(r) for r in db.execute(
            'SELECT * FROM supplier_checks WHERE account_id=? ORDER BY id DESC LIMIT 20',(a['id'],))]
        comparison=checks[0]['difference'] if checks else None
        credits=[dict(r) for r in db.execute(
            'SELECT * FROM supplier_credits WHERE account_id=? ORDER BY id DESC LIMIT 20',(a['id'],))]
        accounts.append(dict(account,**result,reported_balance=reported,
                             comparison_gap=comparison,credit_history=credits,
                             check_history=checks))
    return accounts
