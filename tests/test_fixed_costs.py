"""Independent cost accounting: monthly prorating, one-off expenses, scope safety."""
import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from fixed_costs import charge_in_range, validate_expense,expenses_report,fixed_total
from storage import connect

class FixedExpenseTests(unittest.TestCase):
    def item(self,**overrides):
        x={'label':'VPS monthly','category':'server','scope':'node','node_id':7,
           'provider':'','frequency':'monthly','amount_rial':310000,'start_date':'2026-10-01',
           'end_date':'','note':''}
        x.update(overrides)
        return x
    def test_month_31_and_partial_prorating(self):
        e=self.item()
        self.assertEqual(charge_in_range(e,'2026-10-01','2026-10-31'),310000)
        self.assertEqual(charge_in_range(e,'2026-10-14','2026-10-23'),100000)
        self.assertEqual(charge_in_range(e,'2026-09-01','2026-09-30'),0)
        self.assertEqual(charge_in_range(e,'2026-10-30','2026-11-02'),40666.67)
    def test_february_leap_and_one_time(self):
        e=self.item(start_date='2028-02-01',amount_rial=290000)
        self.assertEqual(charge_in_range(e,'2028-02-01','2028-02-29'),290000)
        self.assertEqual(charge_in_range(e,'2028-02-01','2028-02-14'),140000)
        e=self.item(frequency='once',start_date='2026-10-14',amount_rial=9000)
        self.assertEqual(charge_in_range(e,'2026-10-01','2026-10-31'),9000)
        self.assertEqual(charge_in_range(e,'2026-11-01','2026-11-30'),0)
    def test_end_date_and_validation(self):
        e=self.item(end_date='2026-10-10')
        self.assertEqual(charge_in_range(e,'2026-10-01','2026-10-31'),100000)
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
                self.assertEqual(fixed_total(result),100000)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0],before)

if __name__=='__main__':unittest.main()
