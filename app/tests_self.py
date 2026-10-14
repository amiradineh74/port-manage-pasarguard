import tempfile
from pathlib import Path
from storage import connect,insert_poll

def run():
    cfg={'default_bill_direction':'downlink','default_price_per_gb':1000,'exclude_ports':[]}
    def payload(tag='x',nid=1,up=100,down=200):
        return {'nodes':[{'node_id':nid,'node_name':'test','address':'192.0.2.1','ports':[
            {'port':2053,'tag':tag,'uplink':up,'downlink':down}]}], 'errors': []}
    with tempfile.TemporaryDirectory() as t:
        with connect(Path(t)/'data.sqlite3') as db:
            insert_poll(db,payload(), '2026-10-10T00:00:00+00:00',cfg)
            insert_poll(db,payload(up=150,down=300),'2026-10-10T00:01:00+00:00',cfg)
            insert_poll(db,payload(up=10,down=20),'2026-10-10T00:02:00+00:00',cfg)
            insert_poll(db,payload(tag='renamed',up=400,down=500),'2026-10-10T00:03:00+00:00',cfg)
            insert_poll(db,payload(nid=2),'2026-10-10T00:04:00+00:00',cfg)
            rows=db.execute('SELECT total_down,total_up FROM port_state WHERE node_id=1 AND port=2053').fetchone()
            assert tuple(rows)==(120,60),rows
            assert tuple(db.execute('SELECT total_down,total_up FROM port_state WHERE node_id=2 AND port=2053').fetchone())==(0,0)
            events=[x[0] for x in db.execute('SELECT event FROM samples ORDER BY id')]
            assert events==['baseline','ok','counter_reset','tag_changed,baseline','baseline'],events
    print('SELFTEST OK — baseline, delta, reset, tag rename, isolated nodes')
    return 0
