"""Fixed monthly expenses recur by Jalali months at a 30-day daily rate."""
import sys
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from fixed_costs import charge_in_range,validate_expense,expenses_report,fixed_total,expense_breakdown
from persian_calendar import from_date,month_start
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

    def test_months_of_29_30_31_days_keep_fixed_daily_budget(self):
        rate=96500000  # 9,650,000 Toman monthly
        e=self.item(start_date='2026-03-21',amount_rial=rate)
        day_rate=rate/30
        self.assertAlmostEqual(charge_in_range(e,'2026-04-20','2026-04-20'),round(day_rate,2),places=2)
        self.assertAlmostEqual(charge_in_range(e,'2026-03-21','2026-04-20'),round(rate*31/30,2),places=2)
        self.assertEqual(expense_breakdown(e,'2026-03-21','2026-04-20')[0]['calendar_days'],31)
        esfand=self.item(start_date='2026-03-21',amount_rial=930000)
        self.assertEqual(charge_in_range(esfand,'2027-02-20','2027-03-20'),29*31000)
        self.assertEqual(expense_breakdown(esfand,'2027-02-20','2027-03-20')[0]['calendar_days'],29)

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
