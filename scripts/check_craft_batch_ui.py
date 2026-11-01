"""Disposable mixed-craft shopping/profit scenario; no real API or game traffic."""
import os
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit,unquote

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_crafting import seed,add_price,STAFF,MATERIALS
from albion_trade_desk import feeds
from albion_trade_desk.domain import utcnow
from albion_trade_desk.storage import Store
from albion_trade_desk.web import make_server

with tempfile.TemporaryDirectory() as directory:
    store=Store(directory);seed(store);now=utcnow();end=int(now//3600)*3600
    for uid,price in [*zip(MATERIALS,[10,20,100]),(STAFF,1000),('T4_MEAL_STEW',50)]:
        add_price(store,uid,price,observed=now-10)
    with store.connect() as db:
        db.execute("UPDATE items SET name_en='Pine Planks',name_ru='Сосновые брусья' WHERE id='T4_PLANKS'")
        db.execute("UPDATE items SET name_en='Fine Cloth',name_ru='Изящная ткань' WHERE id='T4_CLOTH'")
        numeric=db.execute("SELECT numeric_id FROM items WHERE id='T4_MEAL_STEW'").fetchone()[0]
    for index,qty in [(1,1),(numeric,10)]:
        feeds.ingest(store,'markethistories.ingest',{'AlbionId':index,'LocationId':'1000','QualityLevel':1,'Timescale':1,
            'MarketHistories':[{'Timestamp':(end-i*21600)*10000000+621355968000000000,'ItemAmount':qty,'SilverAmount':qty*10000000}
                for i in range(28)]},'east')
    def opener(request,**kwargs):
        url=urlsplit(request.full_url);params=parse_qs(url.query);ids=unquote(url.path.rsplit('/',1)[-1]).removesuffix('.json').split(',')
        values={**dict(zip(MATERIALS,[10,20,100])),STAFF:1100,'T4_MEAL_STEW':50}
        city=params['locations'][0];q=int(params['qualities'][0])
        if '/prices/' in url.path:
            payload=[{'item_id':uid,'city':city,'quality':q,'sell_price_min':values[uid],
                'sell_price_min_date':datetime.now(timezone.utc).isoformat()} for uid in ids]
        elif '/history/' in url.path:
            scale=int(params['time-scale'][0]);seconds=scale*3600
            payload=[{'item_id':uid,'location':city,'quality':q,'data':[
                {'timestamp':end//seconds*seconds-seconds,'item_count':3,'avg_price':values[uid]}]} for uid in ids]
        else:raise AssertionError('Unexpected outbound request in isolated fixture')
        response=io.BytesIO(json.dumps(payload).encode());response.headers={};return response
    with patch('albion_trade_desk.transport.urlopen',side_effect=opener):
        server=make_server(store,0);thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            subprocess.run(['node','tests/browser_craft_batch.cjs'],check=True,timeout=100,
                env={**os.environ,'ALBION_SMOKE_URL':f'http://127.0.0.1:{server.server_port}'})
        finally:
            server.shutdown();thread.join();server.server_close()
