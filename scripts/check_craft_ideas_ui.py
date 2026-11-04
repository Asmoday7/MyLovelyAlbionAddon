"""UI acceptance for automatic craft ideas. Only disposable quotes/history and fake REST."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from datetime import datetime,timezone
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs,unquote

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_craft_ideas import CraftIdeasTests,STAFF,MATERIALS,AXE,HELM,BOOK,NOW
from albion_trade_desk.domain import utcnow
from albion_trade_desk.transport import HttpClient
from albion_trade_desk.web import make_server

fixture=CraftIdeasTests('test_signed_sort_both_directions_keeps_missing_values_last');fixture.setUp()
large_ids=fixture.large_market(priced=True,tier=8)
fixture.history(504,1,50)
now=utcnow();end=int(now//3600)*3600
with fixture.store.connect() as db:
    db.execute('UPDATE quotes SET observed_at=?,received_at=?',(now-10,now-10))
    db.execute('UPDATE native_history SET ticks=ticks+?,received_at=?',((end-int(NOW//3600)*3600)*10000000,now-10))
    for uid,en,ru in [(AXE,'Battleaxe','Боевой топор'),(HELM,'Soldier Helmet','Солдатский шлем'),(BOOK,'Tome','Книга'),
                      ('T4_PLANKS','Pine Planks','Сосновые брусья'),('T4_CLOTH','Fine Cloth','Изящная ткань')]:
        db.execute('UPDATE items SET name_en=?,name_ru=? WHERE id=?',(en,ru,uid))
calls=Path(fixture.store.directory)/'calls.json'
recorded=[]
def opener(request,**kwargs):
    url=urlsplit(request.full_url);params=parse_qs(url.query);ids=unquote(url.path.rsplit('/',1)[-1]).removesuffix('.json').split(',')
    q=int(params['qualities'][0]);city=params['locations'][0]
    recorded.append({'kind':'prices' if '/prices/' in url.path else 'history','q':q,'ids':ids});calls.write_text(json.dumps(recorded))
    prices={STAFF:{1:1000,2:900,3:1100,4:1050,5:999999},AXE:{1:100},HELM:{1:2000},BOOK:{5:1000000},
            **{uid:{1:p} for uid,p in zip(MATERIALS,(10,20,100))}}
    if '/prices/' in url.path:
        payload=[{'item_id':uid,'city':city,'quality':q,'sell_price_min':prices[uid][q],
            'sell_price_min_date':datetime.now(timezone.utc).isoformat()} for uid in ids if q in prices.get(uid,{})]
    elif '/history/' in url.path:
        scale=int(params['time-scale'][0]);step=scale*3600
        payload=[{'item_id':uid,'location':city,'quality':q,'data':[
            {'timestamp':end//step*step-i*step,'item_count':(1 if uid==STAFF and q<5 else 0)*scale,'avg_price':1000}
            for i in range(1,168//scale+1)]} for uid in ids]
    else:raise AssertionError('Unexpected outbound fixture request')
    response=io.BytesIO(json.dumps(payload).encode());response.headers={};return response
class FixtureClient(HttpClient):
    def __init__(self,store):super().__init__(store,opener=opener,sleep=lambda _:None)
try:
    with patch('albion_trade_desk.web.HttpClient',FixtureClient):
        server=make_server(fixture.store,0);thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            subprocess.run(['node','tests/browser_craft_ideas.cjs'],check=True,timeout=100,
                env={**os.environ,'ALBION_SMOKE_URL':f'http://127.0.0.1:{server.server_port}','ALBION_IDEAS_CALLS':str(calls),
                     'ALBION_IDEAS_LAST_ITEM':large_ids[-1]})
        finally:server.shutdown();thread.join();server.server_close()
finally:fixture.doCleanups()
