"""Renaming supplier labels cannot alter traffic, credits or reconciliation math."""
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from storage import connect,insert_poll
from supplier_wallets import create_account,rename_provider,update_account,wallet_report
from units import BYTES_PER_GIB

class ProviderRenameTests(unittest.TestCase):
 def test_provider_and_account_renames_preserve_all_quantities(self):
  with tempfile.TemporaryDirectory() as d,connect(Path(d)/'traffic.sqlite3','GiB') as db:
   cfg={'exclude_ports':[],'traffic_unit':'GiB','default_bill_direction':'both',
        'default_price_per_gb':1000}
   poll={'nodes':[{'node_id':7,'node_name':'Germany','address':'192.0.2.77',
      'ports':[{'port':2222,'tag':'sample','uplink':0,'downlink':BYTES_PER_GIB}]}],
      'errors':[]}
   insert_poll(db,poll,'2026-10-14T00:00:00+00:00',cfg)
   db.execute('''INSERT INTO metadata(node_id,port,provider,price_per_gb)
      VALUES(7,2222,'tecvps',250)''')
   db.execute('''INSERT INTO fixed_expenses
       (label,category,scope,node_id,provider,frequency,amount_rial,start_date)
       VALUES('Rent','server','provider',NULL,'tecvps','monthly',50000,'2026-10-14')''')
   aid=create_account(db,{'kind':'volume','title':'wrong bot',
       'bot_handle':'@wrong','opening_amount':50*BYTES_PER_GIB})
   db.execute('INSERT INTO provider_wallet_links(provider,account_id) VALUES(?,?)',('tecvps',aid))
   db.execute('''INSERT INTO supplier_credits(account_id,amount,created_at,note)
       VALUES(?,?,?,?)''',(aid,10*BYTES_PER_GIB,'2026-10-14T00:01:00+00:00','Top up'))
   db.execute('''INSERT INTO supplier_reconciliations
       (account_id,checked_at,reported_amount,estimated_before,adjustment,note)
       VALUES(?,?,?,?,?,?)''',(aid,'2026-10-14T00:02:00+00:00',
        59*BYTES_PER_GIB,60*BYTES_PER_GIB,-BYTES_PER_GIB,'diff'))
   db.commit()
   def sums():
    return {
     'raw':db.execute('SELECT COUNT(*),SUM(delta_down),SUM(raw_down) FROM samples').fetchone()[:],
     'accounts':db.execute('SELECT opening_bytes,opening_rial FROM supplier_accounts WHERE id=?',(aid,)).fetchone()[:],
     'credits':db.execute('SELECT amount FROM supplier_credits WHERE account_id=?',(aid,)).fetchone()[0],
     'recon':db.execute('SELECT reported_amount,estimated_before,adjustment FROM supplier_reconciliations WHERE account_id=?',(aid,)).fetchone()[:],
     'wallet':wallet_report(db)[0]['estimated_balance'],
    }
   before=sums()
   self.assertEqual(rename_provider(db,{'old_provider':'tecvps','new_provider':'techvps'})['updated'],
      {'metadata':1,'provider_wallet_links':1,'fixed_expenses':1})
   self.assertEqual(update_account(db,{'id':aid,'title':'Correct name',
      'bot_handle':'@correct','notes':'Fix typo'}),aid)
   self.assertEqual(sums(),before)
   self.assertEqual(wallet_report(db)[0]['provider'],'techvps')
   self.assertEqual(db.execute('SELECT provider FROM metadata').fetchone()[0],'techvps')
   self.assertEqual(db.execute('SELECT provider FROM fixed_expenses').fetchone()[0],'techvps')
   account=db.execute('SELECT title,bot_handle,notes FROM supplier_accounts WHERE id=?',(aid,)).fetchone()
   self.assertEqual(tuple(account),('Correct name','@correct','Fix typo'))
   with self.assertRaises(ValueError):
    rename_provider(db,{'old_provider':'techvps','new_provider':'بدون ارائه‌دهنده'})
   with self.assertRaises(ValueError):
    rename_provider(db,{'old_provider':'missing','new_provider':'new'})
   db.execute('INSERT INTO metadata(node_id,port,provider) VALUES(7,9876,?)',('another',))
   with self.assertRaises(ValueError):
    rename_provider(db,{'old_provider':'techvps','new_provider':'another'})
   self.assertEqual(sums(),before)

if __name__=='__main__':unittest.main()
