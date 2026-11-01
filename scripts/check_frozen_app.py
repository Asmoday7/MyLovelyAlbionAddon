"""Exercise a packaged executable with synthetic native HTTP; never start the game/AOD."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from urllib.request import Request, urlopen


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
            post('/api/private/stop',{})
            post('/api/app/stop',{})
            assert child.wait(timeout=30)==0, ''.join(lines)
        finally:
            if child.poll() is None: child.kill(); child.wait(timeout=10)
            reader.join(timeout=10);child.stdout.close()
        for path in Path(directory).glob('*.sqlite3*'):path.unlink()
        return {'frozen_http_sqlite_export_shutdown':'passed','sqlite_cleanup':'passed','game':'not run','aod':'not run'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('executable');parser.add_argument('--report')
    args=parser.parse_args(); result=check(args.executable)
    if args.report:Path(args.report).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
