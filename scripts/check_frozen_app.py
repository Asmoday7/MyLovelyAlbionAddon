"""Exercise a packaged executable with synthetic native HTTP; never start the game/AOD."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def check(executable):
    with tempfile.TemporaryDirectory() as directory:
        child = subprocess.Popen([str(Path(executable).resolve()), 'serve', '--port', '0', '--data-dir', directory],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8',
                                 env={**os.environ, 'PYTHONUTF8':'1'})
        lines, ready = [], threading.Event()
        def read():
            for line in child.stdout:
                lines.append(line)
                if re.search(r'http://127\.0\.0\.1:\d+', line): ready.set()
        reader=threading.Thread(target=read); reader.start()
        try:
            if not ready.wait(60): raise AssertionError('Application did not start: '+''.join(lines))
            base=re.search(r'http://127\.0\.0\.1:\d+', ''.join(lines))[0]
            def post(path, body):
                with urlopen(Request(base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'}),timeout=20) as r:return json.load(r)
            post('/api/private/start',{'server':'east','experimental_ack':True})
            with urlopen(base+'/api/private/launcher',timeout=20) as r: script=r.read().decode('utf-8-sig')
            path=re.search(r'http://127\.0\.0\.1:\d+/private/east/[A-Za-z0-9_-]+',script)[0].removeprefix(base)
            order={'Id':42,'ItemTypeId':'T4_BAG','LocationId':'3005','QualityLevel':1,'EnchantmentLevel':0,
                   'UnitPriceSilver':1500000,'Amount':7,'AuctionType':'offer','Expires':'2099-01-01T00:00:00Z'}
            post(path+'/marketorders.ingest',{'Orders':[order]})
            post(path+'/marketorders.ingest',{'Orders':[{**order,'Amount':3}]})
            with urlopen(base+'/api/private/orders?server=east',timeout=20) as r: rows=json.load(r)['rows']
            assert len(rows)==1 and rows[0]['amount']==3
            with urlopen(base+'/api/backup',timeout=20) as r: assert r.read().startswith(b'SQLite format 3')
            with urlopen(base+'/api/private/orders.xlsx?server=east',timeout=20) as r: assert r.read().startswith(b'PK')
            with urlopen(base+'/api/status',timeout=20) as r: assert json.load(r)['version']=='0.3.1'
            # Exercise this executable's full result, not just the source module.
            with closing(sqlite3.connect(Path(directory)/'trade-desk.sqlite3')) as db:
                with db:
                    for i in range(305):
                        uid=f'T4_MAIN_CHECK_{i:03}'
                        db.execute('''INSERT INTO items(id,name_ru,name_en,tier,enchantment,search,catalog_at)
                            VALUES(?,?,?,4,0,?,0)''',(uid,uid,uid,uid.casefold()))
                        db.execute('INSERT INTO recipes VALUES(?,0,1,NULL,0,?)',
                            (uid,json.dumps([{'item_id':'T4_RUNE','count':1,'returnable':True}])))
            ideas=post('/api/craft/ideas',{'tier':'all','enchantment':'all','category':'all','show':'all','limit':8})
            assert ideas['evaluated_recipes']==ideas['matched_recipes']==ideas['total']==len(ideas['rows'])==305
            bad=[{**order,'Id':100+i} for i in range(50)]
            bad[-1].update(ItemTypeId='T4_RUNE',QualityLevel=0)
            try:
                post(path+'/marketorders.ingest',{'Orders':bad})
                raise AssertionError('Invalid mixed page was silently accepted')
            except HTTPError as error:
                with error:
                    assert error.code==400
                    assert 'Ордер 50' in json.load(error)['error']
            with urlopen(base+'/api/private/status',timeout=20) as r: status=json.load(r)
            assert status['own_orders']==1 and status['last_rejection']['order']==50
            assert status['last_rejection']['field']=='QualityLevel'
            post('/api/private/stop',{})
            post('/api/app/stop',{})
            assert child.wait(timeout=30)==0, ''.join(lines)
        finally:
            if child.poll() is None: child.kill(); child.wait(timeout=10)
            reader.join(timeout=10);child.stdout.close()
        for path in Path(directory).glob('*.sqlite3*'):path.unlink()
        return {'version':'0.3.1','frozen_http_sqlite_export_shutdown':'passed','sqlite_cleanup':'passed',
                'all_305_recipes_analyzed_and_returned':'passed','mixed_page_rejection_diagnostic':'passed',
                'game':'not run','aod':'not run'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('executable');parser.add_argument('--report')
    args=parser.parse_args(); result=check(args.executable)
    if args.report:Path(args.report).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
