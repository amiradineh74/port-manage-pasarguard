"""Fixed monthly expenses recur by Jalali months with real 29/30/31-day divisors."""
import sys
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from fixed_costs import charge_in_range,validate_expense,expenses_report,fixed_total,expense_breakdown
from persian_calendar import from_date,month_start,following_month
from storage import connect


class FixedExpenseTests(unittest.TestCase):
    def item(self,**overrides):
        x={'label':'VPS monthly','category':'server','scope':'node','node_id':7,
           'provider':'','frequency':'monthly','amount_rial':930000,
           'start_date':'2026-09-23','end_date':'','note':''}
        x.update(overrides)
        return x

    def test_persian_year_and_month_boundaries(self):
        from datetime import date
        self.assertEqual(month_start(1405,7),date(2026,9,23))
        self.assertEqual(month_start(1405,8),date(2026,10,23))
        self.assertEqual(month_start(1405,1),date(2026,3,21))
        self.assertEqual(month_start(1406,1),date(2027,3,21))
        self.assertEqual(month_start(1404,1),date(2025,3,21))
        self.assertEqual(month_start(1403,12),date(2025,2,19))
        self.assertEqual(from_date(date(2026,10,16)),(1405,7,24))
        self.assertEqual(from_date(date(2025,3,20)),(1403,12,30))
        for year in range(1395,1410):
            first=month_start(year,1)
            for month in range(1,13):
                start=month_start(year,month)
                self.assertEqual(from_date(start),(year,month,1))
                nxt=month_start(year+1,1) if month==12 else month_start(year,month+1)
                self.assertIn((nxt-start).days,(29,30,31))
                self.assertEqual(from_date(nxt-timedelta(days=1))[:2],(year,month))
            self.assertIn((month_start(year+1,1)-first).days,(365,366))

    def test_each_day_is_one_thirtieth_across_solar_months(self):
        e=self.item()
        self.assertEqual(charge_in_range(e,'2026-09-23','2026-09-23'),31000)
        self.assertEqual(charge_in_range(e,'2026-10-14','2026-10-23'),310000)
        self.assertEqual(charge_in_range(e,'2026-10-23','2026-10-23'),31000)
        self.assertEqual(charge_in_range(e,'2026-11-14','2026-11-14'),31000)
        self.assertEqual(charge_in_range(e,'2026-09-22','2026-09-22'),0)
        parts=expense_breakdown(e,'2026-10-20','2026-10-25')
        self.assertEqual([(p['month'],p['covered_days'],p['month_days']) for p in parts],
            [('1405/07',3,30),('1405/08',3,30)])
        self.assertEqual([p['calendar_days'] for p in parts],[30,30])

    def test_full_jalali_month_exact_and_daily_weekly_monthly_agree(self):
        # The same recurring monthly bill must sum to exactly the stated
        # amount in ALL 29-, 30- and 31-day Persian months.
        rate=96500000   # 9,650,000 Toman
        e=self.item(start_date='2026-03-21',amount_rial=rate)
        for jy,jm,expected_days in [(1405,1,31),(1405,7,30),(1405,12,29)]:
            first=month_start(jy,jm)
            next_year,next_month=following_month(jy,jm)
            following=month_start(next_year,next_month)
            last=following-timedelta(days=1)
            self.assertEqual((following-first).days,expected_days)
            parts=expense_breakdown(e,first.isoformat(),last.isoformat())
            self.assertEqual(len(parts),1)
            self.assertEqual(parts[0]['month'],f'{jy:04d}/{jm:02d}')
            self.assertEqual(parts[0]['month_days'],expected_days)
            self.assertEqual(parts[0]['calendar_days'],expected_days)
            self.assertEqual(parts[0]['covered_days'],expected_days)
            self.assertEqual(charge_in_range(e,first.isoformat(),last.isoformat()),rate)
            # Individual days must use actual Persian month length. Rounded
            # cumulative values differ by at most one hundredth of a Rial.
            daily=[]
            for i in range(expected_days):
                day=first+timedelta(days=i)
                amount=charge_in_range(e,day.isoformat(),day.isoformat())
                self.assertAlmostEqual(amount,rate/expected_days,delta=0.011)
                daily.append(amount)
            self.assertAlmostEqual(sum(daily),rate,places=2)
            # Split the month into weeks/partial periods. Total must still
            # reconcile to the same invoice rather than accumulate rounding.
            cursor=first
            pieces=[]
            while cursor<=last:
                stop=min(last,cursor+timedelta(days=6))
                pieces.append(charge_in_range(e,cursor.isoformat(),stop.isoformat()))
                cursor=stop+timedelta(days=1)
            self.assertAlmostEqual(sum(pieces),rate,places=2)
        self.assertAlmostEqual(rate/31/10,311290.32,places=2)
        self.assertAlmostEqual(rate/29/10,332758.62,places=2)

    def test_solar_month_boundary_and_partial_start_do_not_overcharge(self):
        rate=96500000
        e=self.item(start_date='2026-10-19',amount_rial=rate)
        lo='2026-10-19'
        hi='2026-10-25'
        pieces=expense_breakdown(e,lo,hi)
        self.assertEqual([(p['month'],p['covered_days'],p['month_days']) for p in pieces],
                         [('1405/07',4,30),('1405/08',3,30)])
        expected=sum(charge_in_range(e,(date).isoformat(),(date).isoformat())
                     for date in (month_start(1405,7)+timedelta(days=i)
                                  for i in range(26,30))) + sum(
                      charge_in_range(e,(date).isoformat(),(date).isoformat())
                      for date in (month_start(1405,8)+timedelta(days=i)
                                   for i in range(3)))
        self.assertAlmostEqual(charge_in_range(e,lo,hi),expected,places=2)
        self.assertEqual(charge_in_range(e,'2026-10-18','2026-10-18'),0)

    def test_start_end_and_once_not_recurring(self):
        e=self.item(start_date='2026-10-15',end_date='2026-10-25')
        self.assertEqual(charge_in_range(e,'2026-10-14','2026-10-14'),0)
        self.assertEqual(charge_in_range(e,'2026-10-15','2026-10-25'),11*31000)
        self.assertEqual(charge_in_range(e,'2026-10-26','2026-11-30'),0)
        once=self.item(frequency='once',start_date='2026-10-14',amount_rial=9000)
        self.assertEqual(charge_in_range(once,'2026-10-01','2026-10-31'),9000)
        self.assertEqual(charge_in_range(once,'2026-11-01','2026-11-30'),0)
        self.assertEqual(validate_expense(self.item(),{7})['node_id'],7)
        for bad in [self.item(node_id=42),self.item(amount_rial=25.5),
                    self.item(amount_rial=-2),self.item(start_date='2026-02-30'),
                    self.item(frequency='once',end_date='2026-10-15'),
                    self.item(scope='provider',provider='')]:
            with self.assertRaises(ValueError):validate_expense(bad,{7})

    def test_existing_volume_untouched_by_costs(self):
        with tempfile.TemporaryDirectory() as temp:
            with connect(Path(temp)/'traffic.sqlite3') as db:
                before=db.execute('SELECT COUNT(*) FROM samples').fetchone()[0]
                e=validate_expense(self.item(),{7})
                columns=list(e)
                with db:
                    db.execute('INSERT INTO fixed_expenses ('+','.join(columns)+') VALUES ('+
                               ','.join('?' for _ in columns)+')',[e[k] for k in columns])
                result=expenses_report(db,'2026-10-14','2026-10-23')
                self.assertEqual(fixed_total(result),310000)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0],before)


if __name__=='__main__':unittest.main()
