"""Recurring fixed-cost accounting in real Solar Hijri calendar months.

Monthly costs are prorated by each Jalali month's ACTUAL length (29/30/31
days). Cumulative rounding ensures that daily, weekly and full-month
reports reconcile to the original monthly amount exactly, even for partial
ranges. All database dates stay Gregorian ISO for existing data compatibility.
"""
from datetime import date,timedelta
from persian_calendar import from_date, month_start, following_month

VALID_SCOPES={'node','provider','general'}
VALID_FREQUENCIES={'monthly','once'}

def date_value(text,required=True):
    if not text and not required:return None
    if type(text) is not str or len(text)!=10:raise ValueError('تاریخ باید معتبر باشد')
    try:
        result=date.fromisoformat(text)
    except ValueError as exc:raise ValueError('تاریخ نامعتبر است') from exc
    if result.isoformat()!=text:raise ValueError('تاریخ نامعتبر است')
    return result

def validate_expense(obj,node_ids):
    if type(obj) is not dict:raise ValueError('اطلاعات هزینه نامعتبر است')
    label=obj.get('label')
    category=obj.get('category','other')
    scope=obj.get('scope')
    frequency=obj.get('frequency')
    provider=obj.get('provider','')
    node_id=obj.get('node_id')
    amount=obj.get('amount_rial')
    if type(label) is not str or not 1<=len(label.strip())<=128:
        raise ValueError('عنوان هزینه معتبر نیست')
    if type(category) is not str or not 1<=len(category.strip())<=60:
        raise ValueError('دسته‌بندی معتبر نیست')
    if scope not in VALID_SCOPES:raise ValueError('نوع تخصیص هزینه نامعتبر است')
    if frequency not in VALID_FREQUENCIES:raise ValueError('نوع دوره هزینه نامعتبر است')
    if type(amount) is not int or amount<0 or amount>100000000000000:
        raise ValueError('مبلغ ریالی باید عدد صحیح و نامنفی باشد')
    if type(provider) is not str or len(provider)>128:raise ValueError('نام ارائه‌دهنده نامعتبر است')
    if scope=='node':
        if type(node_id) is not int or node_id not in node_ids:raise ValueError('نود ناشناخته است')
        provider=''
    elif scope=='provider':
        if not provider.strip():raise ValueError('نام ارائه‌دهنده را وارد کنید')
        node_id=None
        provider=provider.strip()
    else:
        node_id=None
        provider=''
    start=date_value(obj.get('start_date'))
    end=date_value(obj.get('end_date',''),False)
    if end and end<start:raise ValueError('پایان قبل از شروع است')
    if frequency=='once' and end is not None:raise ValueError('برای هزینه یکباره پایان وارد نکنید')
    note=obj.get('note','')
    if type(note) is not str or len(note)>1000:raise ValueError('یادداشت بیش از حد طولانی است')
    return {'label':label.strip(),'category':category.strip(),
      'scope':scope,'node_id':node_id,'provider':provider,'frequency':frequency,
      'amount_rial':amount,'start_date':start.isoformat(),
      'end_date':end.isoformat() if end else '', 'note':note.strip()}

def expense_breakdown(expense,lo,hi):
    """Audit per-month shares: monthly IRR / actual Jalali days.

    Each day's share is the change in the two-decimal rounded cumulative
    amount, ensuring adjacent date windows sum exactly to the monthly bill.
    """
    start=date_value(expense['start_date'])
    until=date_value(expense['end_date'],False)
    lower=date_value(lo)
    upper=date_value(hi)
    if lower>upper:return []
    a=max(lower,start)
    b=min(upper,until) if until else upper
    if a>b:return []
    if expense['frequency']=='once':
        if not lower<=start<=upper:return []
        return [{'frequency':'once','date':start.isoformat(),
                 'rial':expense['amount_rial']}]
    entries=[]
    current=a
    while current<=b:
        jy,jm,_=from_date(current)
        following_year,following_number=following_month(jy,jm)
        following_start=month_start(following_year,following_number)
        actual_days=(following_start-month_start(jy,jm)).days
        last=min(b,following_start-timedelta(days=1))
        covered=(last-current).days+1
        first_day_index=(current-month_start(jy,jm)).days
        last_day_index=first_day_index+covered
        amount=expense['amount_rial']
        # Calculate from month-start cumulative shares (not an independent
        # rounded slice) so totals match across daily, weekly, monthly, and
        # arbitrary report windows, including 29/31-day Solar Hijri months.
        cost=round(round(amount*last_day_index/actual_days,2)
                   -round(amount*first_day_index/actual_days,2),2)
        entries.append({
            'frequency':'monthly','month':f'{jy:04d}/{jm:02d}',
            'covered_days':covered,'month_days':actual_days,
            'calendar_days':actual_days,
            'rial':cost})
        current=following_start
    return entries


def charge_in_range(expense,lo,hi):
    """Fixed expense share (IRR) for inclusive days in a Solar Hijri period."""
    return round(sum(part['rial'] for part in expense_breakdown(expense,lo,hi)),2)


def expenses_report(db,lo,hi):
    expenses=[dict(r) for r in db.execute('SELECT * FROM fixed_expenses ORDER BY scope,label,id')]
    for expense in expenses:
        expense['period_rial']=charge_in_range(expense,lo,hi)
        expense['breakdown']=expense_breakdown(expense,lo,hi)
    return expenses

def fixed_total(expenses):
    return round(sum(x['period_rial'] for x in expenses),2)
