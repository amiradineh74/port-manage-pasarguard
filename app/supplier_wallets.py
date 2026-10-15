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
    if account['kind']=='money':
        db.execute('UPDATE supplier_accounts SET reported_rial=?,reported_at=? WHERE id=?',
                   (amount,now,account['id']))
    else:
        db.execute('UPDATE supplier_accounts SET reported_bytes=?,reported_at=? WHERE id=?',
                   (amount,now,account['id']))

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
    accounts=[]
    for a in db.execute('SELECT * FROM supplier_accounts ORDER BY id DESC').fetchall():
        account=dict(a)
        bindings=[dict(r) for r in db.execute('''SELECT b.*,p.node_name
           FROM supplier_ports b LEFT JOIN port_state p ON p.node_id=b.node_id AND p.port=b.port
           WHERE b.account_id=? ORDER BY b.node_id,b.port''',(a['id'],))]
        result=_estimate(db,account,bindings)
        reported=(account['reported_rial'] if a['kind']=='money' else account['reported_bytes'])
        comparison=None
        if reported is not None and account['reported_at']:
            historical=_estimate(db,account,bindings,account['reported_at'])
            comparison=historical['estimated_balance']-reported
        credits=[dict(r) for r in db.execute(
            'SELECT * FROM supplier_credits WHERE account_id=? ORDER BY id DESC LIMIT 20',(a['id'],))]
        accounts.append(dict(account,**result,reported_balance=reported,
                             comparison_gap=comparison,credit_history=credits))
    return accounts
