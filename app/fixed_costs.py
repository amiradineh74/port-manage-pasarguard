"""Cost accounting using only the independent SQLite fixed_expenses table.

Monthly fixed charges use Gregorian calendar months and are prorated by inclusive
days within the selected reporting range. Payment cadence and currency are not
inferred from Xray counters; amounts are integer IRR.
"""
import calendar
from datetime import date,timedelta
from math import isfinite

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

def month_after(day):
    y=day.year+(day.month==12)
    m=day.month%12+1
    return date(y,m,1)

def charge_in_range(expense,lo,hi):
    """Calculate a fixed expense in IRR for inclusive local calendar dates."""
    start=date_value(expense['start_date'])
    end=date_value(expense['end_date'],False)
    a=max(date_value(lo),start)
    b=min(date_value(hi),end) if end else date_value(hi)
    if a>b:return 0
    amount=expense['amount_rial']
    if expense['frequency']=='once':
        return amount if a<=start<=b else 0
    result=0.0
    cursor=a
    while cursor<=b:
        following=month_after(cursor)
        segment_end=min(b,following-timedelta(days=1))
        days=(segment_end-cursor).days+1
        result+=amount*days/calendar.monthrange(cursor.year,cursor.month)[1]
        cursor=following
    return round(result,2)

def expense_breakdown(expense,lo,hi):
    """Small audit description per covered Gregorian month (no DB writes)."""
    start=date_value(expense['start_date'])
    until=date_value(expense['end_date'],False)
    a=max(date_value(lo),start)
    b=min(date_value(hi),until) if until else date_value(hi)
    if a>b:return []
    if expense['frequency']=='once':
        return [{'frequency':'once','date':start.isoformat(),
                 'rial':expense['amount_rial']}]
    parts=[]
    cursor=a
    while cursor<=b:
        next_month=month_after(cursor)
        last=min(b,next_month-timedelta(days=1))
        count=(last-cursor).days+1
        month_days=calendar.monthrange(cursor.year,cursor.month)[1]
        parts.append({'frequency':'monthly','month':cursor.strftime('%Y-%m'),
                      'covered_days':count,'month_days':month_days,
                      'rial':round(expense['amount_rial']*count/month_days,2)})
        cursor=next_month
    return parts

def expenses_report(db,lo,hi):
    expenses=[dict(r) for r in db.execute('SELECT * FROM fixed_expenses ORDER BY scope,label,id')]
    for expense in expenses:
        expense['period_rial']=charge_in_range(expense,lo,hi)
        expense['breakdown']=expense_breakdown(expense,lo,hi)
    return expenses

def fixed_total(expenses):
    return round(sum(x['period_rial'] for x in expenses),2)
