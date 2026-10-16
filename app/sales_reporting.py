"""Daily sales and approximate operating profit for the standalone monitor.

Sales are intentionally entered by the user, never inferred from PasarGuard.
Traffic uses the existing dashboard's CURRENT per-port rates and direction;
fixed costs use real 29/30/31-day Solar Hijri months.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fixed_costs import expenses_report
from units import selected_bytes_per_unit

MAX_REPORT_DAYS=62

def validate_day(value):
    if type(value) is not str or len(value)!=10:
        raise ValueError('تاریخ فروش نامعتبر است')
    try:
        parsed=date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError('تاریخ فروش نامعتبر است') from exc
    if parsed.isoformat()!=value:
        raise ValueError('تاریخ فروش نامعتبر است')
    return parsed


def save_daily_sale(db,payload,tz_name):
    if type(payload) is not dict:
        raise ValueError('اطلاعات فروش نامعتبر است')
    day=validate_day(payload.get('day'))
    today=datetime.now(ZoneInfo(tz_name)).date()
    if day>today:
        raise ValueError('فروش روزهای آینده قابل ثبت نیست')
    amount=payload.get('amount_rial')
    count=payload.get('accounts_sold')
    if type(amount) is not int or not 0<=amount<=100000000000000:
        raise ValueError('فروش روز باید مبلغ صحیح و نامنفی به ریال باشد')
    if type(count) is not int or not 0<=count<=10000000:
        raise ValueError('تعداد اکانت باید عدد صحیح و نامنفی باشد')
    note=payload.get('note','')
    if type(note) is not str or len(note)>500:
        raise ValueError('توضیحات حداکثر ۵۰۰ کاراکتر است')
    now=datetime.now(timezone.utc).isoformat(timespec='seconds')
    with db:
        db.execute("""INSERT INTO daily_sales
            (day,amount_rial,accounts_sold,note,created_at,updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(day) DO UPDATE SET
            amount_rial=excluded.amount_rial,accounts_sold=excluded.accounts_sold,
            note=excluded.note,updated_at=excluded.updated_at""",
            (day.isoformat(),amount,count,note.strip(),now,now))
    return {'day':day.isoformat(),'amount_rial':amount,'accounts_sold':count}


def financial_days(db,lo,hi,tz_name,default_direction,default_rate):
    """Return at most 62 local-day reports. Never modify collector counters."""
    begin=validate_day(lo)
    end=validate_day(hi)
    if begin>end or (end-begin).days>=MAX_REPORT_DAYS:
        raise ValueError('بازه گزارش فروش باید حداکثر ۶۲ روز باشد')
    tz=ZoneInfo(tz_name)
    today=datetime.now(tz).date()
    first=db.execute('SELECT MIN(collected_at) FROM poll_runs').fetchone()[0]
    tracking_start=(datetime.fromisoformat(first).astimezone(tz).date()
                    if first else today)
    divisor=selected_bytes_per_unit(db)
    expenses=expenses_report(db,begin.isoformat(),end.isoformat())
    sales={r['day']:dict(r) for r in db.execute(
        'SELECT day,amount_rial,accounts_sold,note,updated_at FROM daily_sales WHERE day>=? AND day<=?',
        (lo,hi))}
    # A SQLite SUM per *local day* keeps DST and half-hour offset boundaries
    # accurate and avoids sending millions of raw samples into Python.
    sql='''SELECT COALESCE(SUM(
        (CASE COALESCE(m.bill_direction,?)
          WHEN 'downlink' THEN s.delta_down
          WHEN 'uplink' THEN s.delta_up
          ELSE s.delta_down+s.delta_up END)
          *COALESCE(m.price_per_gb,?)/?),0)
        FROM samples s LEFT JOIN metadata m
         ON s.node_id=m.node_id AND s.port=m.port
        WHERE s.collected_at>=? AND s.collected_at<?
          AND COALESCE(m.enabled,1)=1
          AND (m.billing_since IS NULL OR m.billing_since=''
               OR s.collected_at>=m.billing_since)'''
    result=[]
    current=begin
    while current<=end:
        tomorrow=current+timedelta(days=1)
        lower=datetime.combine(current,time.min,tzinfo=tz).astimezone(timezone.utc).isoformat(timespec='seconds')
        upper=datetime.combine(tomorrow,time.min,tzinfo=tz).astimezone(timezone.utc).isoformat(timespec='seconds')
        traffic_toman=float(db.execute(sql,(default_direction,default_rate,
                                        float(divisor),lower,upper)).fetchone()[0])
        traffic_rial=round(traffic_toman*10,2)
        fixed_rial=round(sum(x['period_rial'] for x in
             expenses_report_day(expenses,current.isoformat())),2)
        sale=sales.get(current.isoformat())
        status=('future' if current>today else
                'recorded' if sale else
                'before_tracking' if current<tracking_start else
                'missing' if current<today else 'pending_today')
        result.append({
            'day':current.isoformat(),'status':status,
            'sales_rial':sale['amount_rial'] if sale else None,
            'accounts_sold':sale['accounts_sold'] if sale else None,
            'note':sale['note'] if sale else '',
            'traffic_rial':traffic_rial,
            'fixed_rial':fixed_rial,
            'expenses_rial':round(traffic_rial+fixed_rial,2),
            'profit_rial':(round(sale['amount_rial']-traffic_rial-fixed_rial,2)
                           if sale else None),
        })
        current=tomorrow
    yesterday=(today-timedelta(days=1)).isoformat()
    yesterday_missing=(yesterday>=tracking_start.isoformat() and
                       not db.execute('SELECT 1 FROM daily_sales WHERE day=?',(yesterday,)).fetchone())
    return {'days':result,'today':today.isoformat(),
            'tracking_started_on':tracking_start.isoformat(),
            'yesterday_missing':yesterday_missing,'currency':'Rial',
            'cost_basis':'current_port_rates',
            'fixed_cost_month':'jalali_actual_days'}


def expenses_report_day(expenses,day):
    """Return today's share using the same source and formula as fixed costs."""
    from fixed_costs import charge_in_range
    return ({'period_rial':charge_in_range(item,day,day)} for item in expenses
            if item['period_rial'] or item['frequency']=='monthly')
