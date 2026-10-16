"""Daily profit is independent of PasarGuard and aligned to local dates."""
from datetime import datetime,timedelta,time,timezone
from pathlib import Path
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from sales_reporting import save_daily_sale,financial_days,validate_day
from persian_calendar import month_start
from storage import connect,insert_poll
from units import BYTES_PER_GIB

TZ=ZoneInfo('Asia/Tehran')

class FinanceTests(unittest.TestCase):
 def test_sales_are_idempotent_and_zero_is_real(self):
  with tempfile.TemporaryDirectory() as d,connect(Path(d)/'db.sqlite3','GiB') as db:
   day=(datetime.now(TZ).date()-timedelta(days=1)).isoformat()
   save_daily_sale(db,{'day':day,'amount_rial':0,'accounts_sold':0},'Asia/Tehran')
   self.assertEqual(db.execute('SELECT COUNT(*) FROM daily_sales').fetchone()[0],1)
   save_daily_sale(db,{'day':day,'amount_rial':90000,'accounts_sold':5,'note':'edit'},'Asia/Tehran')
   self.assertEqual(db.execute('SELECT COUNT(*) FROM daily_sales').fetchone()[0],1)
   row=db.execute('SELECT amount_rial,accounts_sold,note FROM daily_sales').fetchone()
   self.assertEqual(tuple(row),(90000,5,'edit'))
   zero=(datetime.now(TZ).date()-timedelta(days=2)).isoformat()
   save_daily_sale(db,{'day':zero,'amount_rial':0,'accounts_sold':0},'Asia/Tehran')
   self.assertEqual(db.execute('SELECT COUNT(*) FROM daily_sales').fetchone()[0],2)
   for bad in [
      {'day':day,'amount_rial':-1,'accounts_sold':0},
      {'day':day,'amount_rial':1.5,'accounts_sold':0},
      {'day':day,'amount_rial':True,'accounts_sold':1},
      {'day':day,'amount_rial':1,'accounts_sold':-1},
      {'day':day,'amount_rial':1,'accounts_sold':1.5},
      {'day':(datetime.now(TZ).date()+timedelta(days=1)).isoformat(),'amount_rial':1,'accounts_sold':1},
   ]:
    with self.assertRaises(ValueError):save_daily_sale(db,bad,'Asia/Tehran')
   with self.assertRaises(ValueError):validate_day('2026-02-30')

 def test_daily_port_cost_monthly_share_and_missing_distinction(self):
  day=datetime.now(TZ).date()-timedelta(days=2)
  prior=day-timedelta(days=1)
  start=datetime(day.year,day.month,1).date()
  amount=30*31000  # solar-month recurrence uses fixed 30-day rate
  def at(d,hour):
   return datetime.combine(d,time(hour,0),tzinfo=TZ).astimezone(timezone.utc).isoformat(timespec='seconds')
  cfg={'default_price_per_gb':250,'default_bill_direction':'both',
       'exclude_ports':[],'traffic_unit':'GiB'}
  def packet(n):
   return {'nodes':[{'node_id':7,'node_name':'N','address':'192.0.2.7',
           'ports':[{'port':2077,'tag':'x','uplink':0,'downlink':n}]}],'errors':[]}
  with tempfile.TemporaryDirectory() as d,connect(Path(d)/'db.sqlite3','GiB') as db:
   db.execute("""INSERT INTO fixed_expenses
      (label,category,scope,node_id,provider,frequency,amount_rial,start_date)
      VALUES('Server','server','general',NULL,'','monthly',?,?)""",(amount,start.isoformat()))
   db.execute("""INSERT INTO fixed_expenses
      (label,category,scope,node_id,provider,frequency,amount_rial,start_date)
      VALUES('One time','other','general',NULL,'','once',9000,?)""",(day.isoformat(),))
   db.commit()
   insert_poll(db,packet(0),at(prior,12),cfg)
   insert_poll(db,packet(BYTES_PER_GIB),at(day,9),cfg)
   db.execute('''INSERT INTO metadata(node_id,port,price_per_gb,bill_direction,enabled)
     VALUES(7,2077,250,'both',1)''')
   db.commit()
   save_daily_sale(db,{'day':day.isoformat(),'amount_rial':80000,'accounts_sold':4},'Asia/Tehran')
   out=financial_days(db,prior.isoformat(),day.isoformat(),'Asia/Tehran','both',0)
   prior_row,today_row=out['days']
   self.assertEqual(prior_row['status'],'missing')
   self.assertIsNone(prior_row['profit_rial'])
   self.assertEqual(today_row['status'],'recorded')
   self.assertEqual(today_row['traffic_rial'],2500)
   self.assertEqual(today_row['fixed_rial'],40000)
   self.assertEqual(today_row['expenses_rial'],42500)
   self.assertEqual(today_row['profit_rial'],37500)
   self.assertEqual(today_row['accounts_sold'],4)
   save_daily_sale(db,{'day':prior.isoformat(),'amount_rial':0,'accounts_sold':0},'Asia/Tehran')
   out=financial_days(db,prior.isoformat(),day.isoformat(),'Asia/Tehran','both',0)
   self.assertEqual(out['days'][0]['status'],'recorded')
   self.assertEqual(out['days'][0]['profit_rial'],-31000)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0],2)

 def test_finance_report_reconciles_full_29_and_31_day_jalali_months(self):
  # 1404/12 is 29 days; 1405/01 is 31 days. Both are before Oct 2026.
  import datetime as dt
  first=month_start(1404,12)
  middle=month_start(1405,1)
  last=month_start(1405,2)-dt.timedelta(days=1)
  self.assertEqual((middle-first).days,29)
  self.assertEqual((last-middle).days+1,31)
  monthly=96500000
  with tempfile.TemporaryDirectory() as d,connect(Path(d)/'db.sqlite3','GiB') as db:
   db.execute("""INSERT INTO fixed_expenses
    (label,category,scope,node_id,provider,frequency,amount_rial,start_date)
    VALUES('Hosting','server','general',NULL,'','monthly',?,?)""",
    (monthly,first.isoformat()))
   db.commit()
   save_daily_sale(db,{'day':middle.isoformat(),'amount_rial':4000000,'accounts_sold':2},'Asia/Tehran')
   rows=financial_days(db,first.isoformat(),last.isoformat(),'Asia/Tehran','both',0)['days']
   self.assertEqual(len(rows),60)
   self.assertAlmostEqual(sum(row['fixed_rial'] for row in rows[:29]),monthly,places=2)
   self.assertAlmostEqual(sum(row['fixed_rial'] for row in rows[29:]),monthly,places=2)
   self.assertAlmostEqual(rows[0]['fixed_rial'],monthly/29,delta=0.011)
   self.assertAlmostEqual(rows[29]['fixed_rial'],monthly/31,delta=0.011)
   self.assertEqual(rows[29]['accounts_sold'],2)
   self.assertAlmostEqual(rows[29]['profit_rial'],4000000-rows[29]['fixed_rial'],places=2)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0],0)

 def test_report_maximum_days(self):
  with tempfile.TemporaryDirectory() as d,connect(Path(d)/'db.sqlite3') as db:
   today=datetime.now(TZ).date()
   with self.assertRaises(ValueError):
    financial_days(db,(today-timedelta(days=70)).isoformat(),today.isoformat(),'Asia/Tehran','both',0)

if __name__=='__main__':unittest.main()
