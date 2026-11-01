"""Synthetic native AOD messages over real HTTP, never live game traffic."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from zipfile import ZipFile
import io

from albion_trade_desk import ingestion
from albion_trade_desk.aod_process import AodProcess
from albion_trade_desk.storage import Store
from albion_trade_desk.web import make_server
from test_private import orders


class ReceiverLifecycleTests(unittest.TestCase):
    def test_concurrent_native_posts_restart_backup_export_and_windows_file_cleanup(self):
        # TemporaryDirectory cleanup must fail visibly if a DB handle remains open on Windows.
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            server = make_server(store, 0)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            base = 'http://127.0.0.1:' + str(server.server_port)
            def post(path, body):
                with urlopen(Request(base+path, data=json.dumps(body).encode(), headers={'Content-Type':'application/json'}),timeout=15) as r:
                    return json.load(r)
            try:
                post('/api/private/start', {'server':'east','experimental_ack':True})
                path = server.private_scanner.destination().removeprefix(base)+'/marketorders.ingest'
                def send(n):
                    payload = orders(1000000+n)
                    payload['Orders'][0]['Id'] = n % 10
                    return post(path,payload)
                with ThreadPoolExecutor(max_workers=8) as executor:
                    self.assertEqual(len(list(executor.map(send,range(60)))),60)
                with store.connect() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],10)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM items').fetchone()[0],1)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM market_snapshots').fetchone()[0],0)
                # A bad batch is rejected entirely, not acknowledged before SQLite commit.
                bad=orders(); bad['Orders'] += [{**bad['Orders'][0], 'Id':90, 'Amount':-3}]
                with self.assertRaises(HTTPError) as failed:post(path,bad)
                self.assertEqual(failed.exception.code,400)
                for _ in range(3):
                    with urlopen(base+'/api/backup') as r: backup=r.read()
                    p=Path(folder)/'roundtrip.sqlite3';p.write_bytes(backup)
                    with closing(sqlite3.connect(p)) as db:
                        self.assertEqual(db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],10)
                    p.unlink()  # Windows sharing violation is a test failure, never ignored.
                with urlopen(base+'/api/private/orders.xlsx?server=east') as r:
                    with ZipFile(io.BytesIO(r.read())) as workbook:
                        self.assertIn(b'Orders',workbook.read('xl/workbook.xml'))
                with urlopen(base+'/api/market?server=east&city=Caerleon&scope=private') as r:
                    self.assertEqual(json.load(r)['rows'][0]['id'],'T4_BAG')
                post('/api/private/stop', {})
                with self.assertRaises(HTTPError):post(path,orders())
            finally:
                server.shutdown();thread.join(5);server.server_close()
            self.assertFalse(thread.is_alive())
            reopened=Store(folder)
            self.assertEqual(reopened.status()['orders'],10)
            self.assertFalse(make_status(reopened)['enabled'])
            # Delete actual WAL/main files after all HTTP request threads and jobs have joined.
            for p in Path(folder).glob('*.sqlite3*'):
                p.unlink()

    def test_native_ingress_and_status_do_not_need_public_network(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            from albion_trade_desk.private_scanner import PrivateScanner
            scanner=PrivateScanner(store,0);scanner.start('east',True)
            with patch('socket.create_connection', side_effect=AssertionError('uplink')):
                scanner.receive('east',scanner.token,'marketorders.ingest',orders())
                self.assertEqual(scanner.status()['unique_orders'],1)
            scanner.stop()

    def test_public_api_off_until_explicitly_enabled(self):
        with tempfile.TemporaryDirectory() as folder:
            server=make_server(Store(folder),0)
            try:
                with urlopen_context(server) as base:
                    with urlopen(base+'/api/status') as r:self.assertFalse(json.load(r)['public_api_enabled'])
                    body=json.dumps({'enabled':True}).encode()
                    with urlopen(Request(base+'/api/settings/public-api',data=body)) as r:self.assertTrue(json.load(r)['enabled'])
            finally:server.server_close()


def make_status(store):
    from albion_trade_desk.private_scanner import PrivateScanner
    return PrivateScanner(store,0).status()


from contextlib import contextmanager
@contextmanager
def urlopen_context(server):
    thread=threading.Thread(target=server.serve_forever);thread.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)
    finally:server.shutdown();thread.join()


class OrderStateTests(unittest.TestCase):
    def test_late_processing_does_not_replace_newer_observation_or_mix_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            t=1800000000
            with patch('albion_trade_desk.ingestion.utcnow',return_value=t+100):
                ingestion.local_orders(store,orders(3000000),source='private-client',observed_at=t+20)
                self.assertEqual(ingestion.local_orders(store,orders(1000000),source='private-client',observed_at=t),0)
                with store.connect() as db:
                    self.assertEqual(db.execute('SELECT price FROM orders').fetchone()[0],300)
                collision=orders();collision['Orders'][0]['QualityLevel']=5
                with self.assertRaises(ValueError):ingestion.local_orders(store,collision,source='private-client')
                # The same id on another server is a separate order.
                ingestion.local_orders(store,collision,'europe','private-client')
                ingestion.local_orders(store,collision,'west','private-client')
                self.assertEqual(store.status()['orders'],3)

    def test_raw_location_enchantment_and_partial_snapshot_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            p=orders(); p['Orders'][0].update(LocationId='3013-Auction2',EnchantmentLevel=2)
            ingestion.local_orders(store,p,source='private-client')
            p['Orders'][0].update(Id=43,LocationId='3003',AuctionType='request')
            ingestion.local_orders(store,p,source='private-client')
            ingestion.local_orders(store,{'Orders':[]},source='private-client')
            with store.connect() as db:
                rows=db.execute('SELECT * FROM orders ORDER BY id').fetchall()
                self.assertEqual(rows[0]['raw_location'],'3013-Auction2')
                self.assertEqual(rows[0]['location'],'3005')
                self.assertEqual(rows[0]['item_id'],'T4_BAG@2')
                self.assertEqual(rows[1]['market_type'],'black-market')
                self.assertEqual(len(rows),2)


class SupervisorTests(unittest.TestCase):
    def test_supervised_process_arguments_stop_and_error_reporting(self):
        class Fake:
            returncode=None
            def poll(self):return self.returncode
            def wait(self,timeout):self.returncode=0
        with tempfile.TemporaryDirectory() as folder:
            runner=AodProcess(Store(folder)); fake=Fake()
            with patch.object(runner,'supported',True), patch('albion_trade_desk.aod_process.subprocess.Popen',return_value=fake) as popen:
                runner.start('http://127.0.0.1:1234/private/east/secret','session')
                self.assertEqual(popen.call_args.args[0][:2],['powershell.exe','-NoProfile'])
                self.assertLess(len(' '.join(popen.call_args.args[0])),32000)
                self.assertTrue(runner.status()['active'])
                with self.assertRaises(ValueError):runner.start('unused','session')
                (runner.folder/'state.json').write_text(json.dumps({'state':'waiting','pid':7,'sha256':'verified','client_path':'C:/aod.exe'}))
                self.assertEqual(runner.status()['pid'],7)
                (runner.folder/'albiondata-client.log').write_text('sent to http://127.0.0.1:1234/private/east/secret')
                self.assertNotIn('secret',' '.join(runner.logs()))
                runner.stop()
                self.assertTrue((runner.folder/'stop').exists())
                self.assertFalse(runner.status()['active'])

    def test_supervisor_reports_stop_timeout_without_killing_other_processes(self):
        class Slow:
            returncode=None
            def poll(self):return None
            def wait(self,timeout):raise subprocess.TimeoutExpired('supervisor',timeout)
        with tempfile.TemporaryDirectory() as folder:
            runner=AodProcess(Store(folder));runner.process=Slow();runner.folder=Path(folder)
            self.assertIn('не подтверждена',runner.stop()['error'])


class InstanceTests(unittest.TestCase):
    def test_second_instance_refused_and_restart_releases_lock(self):
        from albion_trade_desk.instance import InstanceLock
        with tempfile.TemporaryDirectory() as directory:
            first, second = InstanceLock(directory), InstanceLock(directory)
            try:
                first.acquire()
                with self.assertRaises(ValueError): second.acquire()
            finally: first.close(); second.close()
            second.acquire();second.close()


@unittest.skipUnless(os.name == 'nt', 'Generated PowerShell parsed by Windows CI')
class ManagedWindowsSyntaxTests(unittest.TestCase):
    def test_generated_bootstrap_and_supervisor_parse(self):
        import base64
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as directory:
            runner=AodProcess(Store(directory))
            with patch('albion_trade_desk.aod_process.subprocess.Popen') as popen:
                popen.return_value.poll.return_value=None
                runner.start('http://127.0.0.1:1234/private/east/secret','session')
                bootstrap=base64.b64decode(popen.call_args.args[0][-1]).decode('utf-16le')
            generated=base64.b64decode((runner.folder/'guardian.command').read_text()).decode('utf-16le')
            for text in (bootstrap, generated):
                path=Path(directory)/'generated.ps1';path.write_text(text,encoding='utf-8-sig')
                command="$t=$null;$e=$null;[System.Management.Automation.Language.Parser]::ParseFile($env:ATD_PARSE_FILE,[ref]$t,[ref]$e)|Out-Null;if($e.Count){$e|Out-String|Write-Error;exit 1}"
                result=subprocess.run(['powershell.exe','-NoProfile','-Command',command],env={**os.environ,'ATD_PARSE_FILE':str(path)},capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
