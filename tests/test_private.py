from contextlib import closing
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from albion_trade_desk.analytics import market
from albion_trade_desk.catalog import import_catalog
from albion_trade_desk.feeds import ingest, resolve_history
from albion_trade_desk.ingestion import history, prices
from albion_trade_desk.private_scanner import PrivateScanner
from albion_trade_desk.public_nats import read_messages
from albion_trade_desk.storage import Store
from albion_trade_desk.web import make_server

NOW = 1760005800
END = NOW // 3600 * 3600


def orders(price=1500000):
    return {'Orders': [{'Id': 42, 'ItemTypeId': 'T4_BAG', 'ItemGroupTypeId': 'T4_BAG', 'LocationId': '3005',
                        'QualityLevel': 1, 'EnchantmentLevel': 0, 'UnitPriceSilver': price, 'Amount': 1,
                        'AuctionType': 'offer', 'Expires': '2099-01-01T00:00:00Z'}]}


def native(scale=0, numeric=1):
    return {'AlbionId': numeric, 'LocationId': '3005', 'QualityLevel': 1, 'Timescale': scale,
            'MarketHistories': [{'Timestamp': (END-3600)*10000000+621355968000000000,
                                 'ItemAmount': 2, 'SilverAmount': 2000000}]}


class PrivateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        import_catalog(self.store, [{'UniqueName': 'T4_BAG', 'Index': 1, 'LocalizedNames': {'RU-RU':'Сумка', 'EN-US':'Bag'}}])
        self.scanner = PrivateScanner(self.store, 8766)

    def test_disabled_by_default_and_requires_explicit_opt_in(self):
        self.assertFalse(self.scanner.status()['enabled'])
        with self.assertRaises(ValueError):
            self.scanner.start('east')
        self.scanner.start('east', True)
        self.assertFalse(self.scanner.status()['network_verified'])
        self.assertFalse(self.scanner.status()['rules_permission_confirmed'])

    def test_local_only_source_and_deduplicated_packet(self):
        self.scanner.start('east', True)
        # Ingress/analytics do not need any outbound transport, even for catalogue misses.
        with patch('socket.create_connection', side_effect=AssertionError('unexpected uplink')):
            result = self.scanner.receive('east', self.scanner.token, 'marketorders.ingest', orders())
            duplicate = self.scanner.receive('east', self.scanner.token, 'marketorders.ingest', orders())
        self.assertEqual(result['accepted'], 1)
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(self.scanner.status()['duplicates'], 1)
        self.assertEqual(self.scanner.status()['records'], 1)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT source FROM orders").fetchone()[0], 'private-client')

    def test_mixed_50_order_page_is_accepted_without_item_selection(self):
        self.scanner.start('east',True)
        rows=[]
        for i in range(50):
            row=dict(orders()['Orders'][0],Id=100+i,
                ItemTypeId=['T4_BAG','T4_RUNE','T4_SKILLBOOK_STANDARD'][i%3],
                QualityLevel=1 if i%3 else i%5+1)
            rows.append(row)
        payload={'Orders':rows}
        self.assertEqual(self.scanner.receive('east',self.scanner.token,'marketorders.ingest',payload)['accepted'],50)
        self.assertEqual(self.store.status()['orders'],50)
        self.assertIsNone(self.scanner.status()['last_rejection'])

    def test_rejected_mixed_page_reports_exact_record_without_partial_commit_or_private_values(self):
        self.scanner.start('east',True)
        self.scanner.receive('east',self.scanner.token,'marketorders.ingest',orders())
        rows=[dict(orders()['Orders'][0],Id=100+i) for i in range(50)]
        rows[-1].update(ItemTypeId='T4_RUNE',QualityLevel=0)
        with self.assertLogs('albion_trade_desk.private_scanner',level='WARNING') as logs:
            with self.assertRaisesRegex(ValueError,'Ордер 50 .*T4_RUNE.*QualityLevel.*получено 0'):
                self.scanner.receive('east',self.scanner.token,'marketorders.ingest',{'Orders':rows})
        rejection=self.scanner.status()['last_rejection']
        self.assertEqual((rejection['order'],rejection['field'],rejection['item_id']),(50,'QualityLevel','T4_RUNE'))
        self.assertEqual(self.store.status()['orders'],1)
        self.assertEqual(self.scanner.status()['rejected'],1)
        self.assertNotIn(self.scanner.token,' '.join(logs.output))
        self.assertNotIn('Orders',rejection['message'])
        # Another field with arbitrary text must never be echoed in diagnostics.
        bad=orders();bad['Orders'][0]['UnitPriceSilver']='private-input-marker'
        with self.assertRaises(ValueError):self.scanner.receive('east',self.scanner.token,'marketorders.ingest',bad)
        self.assertNotIn('private-input-marker',json.dumps(self.scanner.status()['last_rejection']))
        # Valid later packets continue to be accepted, keeping the last rejection for diagnosis.
        self.assertEqual(self.scanner.receive('east',self.scanner.token,'marketorders.ingest',orders(2000000))['accepted'],1)
        self.scanner.stop();self.scanner.start('east',True)
        self.assertIsNone(self.scanner.status()['last_rejection'])

    def test_identity_conflict_reports_position_and_rolls_back_earlier_records(self):
        self.scanner.start('east',True)
        self.scanner.receive('east',self.scanner.token,'marketorders.ingest',orders())
        rows=[dict(orders()['Orders'][0],Id=99),dict(orders()['Orders'][0],ItemTypeId='T4_RUNE')]
        with self.assertRaisesRegex(ValueError,'Ордер 2 .*T4_RUNE.*конфликтует'):
            self.scanner.receive('east',self.scanner.token,'marketorders.ingest',{'Orders':rows})
        self.assertEqual(self.store.status()['orders'],1)
        self.assertEqual(self.scanner.status()['last_rejection']['field'],'Id')

    def test_wrong_region_bad_token_old_session_stopped_session_rejected(self):
        self.scanner.start('east', True)
        token = self.scanner.token
        for server, secret in [('west', token), ('east', 'bad')]:
            with self.assertRaises(PermissionError):
                self.scanner.receive(server, secret, 'marketorders.ingest', orders())
        self.scanner.stop()
        with self.assertRaises(PermissionError):
            self.scanner.receive('east', token, 'marketorders.ingest', orders())
        self.scanner.start('east', True)
        with self.assertRaises(PermissionError):
            self.scanner.receive('east', token, 'marketorders.ingest', orders())

    def test_no_automatic_resume_after_restart(self):
        self.scanner.start('east', True)
        restarted = PrivateScanner(self.store, 8766)
        self.assertFalse(restarted.status()['enabled'])
        with self.store.connect() as db:
            self.assertIsNotNone(db.execute('SELECT stopped_at FROM private_sessions').fetchone()[0])

    def test_personalized_topics_and_fields_are_rejected(self):
        self.scanner.start('east', True)
        for topic, payload in [('skills.ingest', {'CharacterName':'private'}),
                               ('marketorders.ingest', {**orders(), 'CharacterId':'private'}),
                               ('markethistories.ingest', {**native(), 'CharacterName':'private'})]:
            with self.assertRaises(ValueError):
                self.scanner.receive('east', self.scanner.token, topic, payload)
        self.assertEqual(self.scanner.status()['rejected'], 3)
        self.assertEqual(self.store.status()['orders'], 0)

    def test_all_native_scales_retained_only_hours_normalized(self):
        for scale in (0, 1, 2):
            ingest(self.store, 'markethistories.ingest', native(scale), 'east')
        aggregate=native(); aggregate['QualityLevel']=0
        ingest(self.store, 'markethistories.ingest', aggregate, 'east')
        self.assertEqual(self.scanner.status()['own_native_history'], 4)
        self.assertEqual(self.store.status()['history'], 1)
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM history').fetchone()
            self.assertEqual(row['quantity'], 2)
            self.assertEqual(row['average'], 100)
            self.assertEqual(row['source'], 'private-client')

    def test_catalogue_miss_preserved_and_later_resolved(self):
        ingest(self.store, 'markethistories.ingest', native(numeric=99), 'east')
        self.assertEqual(self.scanner.status()['unmapped_history'], 1)
        self.assertEqual(self.store.status()['history'], 0)
        import_catalog(self.store, [{'UniqueName':'T4_BAG@1','Index':99,'LocalizedNames':{'RU-RU':'Сумка .1','EN-US':'Bag .1'}}])
        resolve_history(self.store)
        self.assertEqual(self.scanner.status()['unmapped_history'], 0)
        self.assertEqual(self.store.status()['history'], 1)

    def test_public_and_own_history_never_overwrite_or_double_count(self):
        ingest(self.store, 'markethistories.ingest', native(), 'east')
        history(self.store, [{'item_id':'T4_BAG','location':'Caerleon','quality':1,
                             'data':[{'timestamp':END-3600,'item_count':8,'avg_price':300}]}])
        self.assertEqual(self.store.status()['history'], 2)
        own = market(self.store, {'scope':'private'}, now=NOW)['rows'][0]
        public = market(self.store, {'scope':'public'}, now=NOW)['rows'][0]
        both = market(self.store, {'scope':'all'}, now=NOW)['rows'][0]
        self.assertEqual(own['volumes']['1h']['volume'], 2)
        self.assertEqual(public['volumes']['1h']['volume'], 8)
        self.assertIn(both['volumes']['1h']['volume'], (2,8))
        self.assertNotEqual(both['vwap'], 260)  # no weighted mixing of duplicate hours

    def test_public_orders_already_normalized_and_scope_filter_correct(self):
        ingest(self.store, 'marketorders.ingest', orders(), 'east')
        public = orders(200)['Orders'][0]
        ingest(self.store, 'marketorders.deduped', public, 'east', 'aodp-nats')
        own = market(self.store, {'scope':'private','priced':'true'})['rows'][0]
        shared = market(self.store, {'scope':'public','priced':'true'})['rows'][0]
        self.assertEqual(own['quotes']['sell_price_min']['price'], 150)
        self.assertEqual(shared['quotes']['sell_price_min']['price'], 200)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM orders').fetchone()[0], 2)

    def test_normalized_nats_history_not_divided_twice(self):
        p = native(); p['MarketHistories'][0]['SilverAmount'] = 200
        ingest(self.store, 'markethistories.deduped', p, 'east', 'aodp-nats')
        row = market(self.store, {'scope':'public'}, now=NOW)['rows'][0]
        self.assertEqual(row['vwap'], 100)

    def test_bad_batch_rolls_back_before_any_orders(self):
        p = orders(); p['Orders'].append({**p['Orders'][0], 'Id':43,'CharacterId':'private'})
        with self.assertRaises(ValueError):
            ingest(self.store, 'marketorders.ingest', p, 'east')
        self.assertEqual(self.store.status()['orders'], 0)

    def test_launcher_uses_actual_port_not_anki_port_and_empty_private_ingest(self):
        self.scanner.start('east', True)
        script = self.scanner.launcher().decode('utf-8-sig')
        self.assertIn(self.scanner.destination(), script)
        self.assertIn('127.0.0.1:8766/private/east/', script)
        self.assertNotIn('http://127.0.0.1:8765/api/', script)
        self.assertIn("$arguments = @('-i', $destination, '-p=')", script)
        self.assertNotIn('https+pow://albion-online-data.com', script)


class MigrationTests(unittest.TestCase):
    def test_v1_history_and_order_data_survive_source_key_migration_and_repeat_open(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'trade-desk.sqlite3'
            with closing(sqlite3.connect(p)) as db:
                db.executescript('''CREATE TABLE history(server TEXT,location TEXT,item_id TEXT,quality INTEGER,start REAL,
                    seconds INTEGER,quantity INTEGER,average REAL,received_at REAL,source TEXT,
                    PRIMARY KEY(server,location,item_id,quality,start,seconds));
                    INSERT INTO history VALUES('east','3005','T4_BAG',1,1000,3600,5,200,1001,'aodp-rest');
                    CREATE TABLE orders(server TEXT,id TEXT,item_id TEXT,location TEXT,quality INTEGER,side TEXT,
                    price REAL,amount INTEGER,expires REAL,received_at REAL,PRIMARY KEY(server,id));
                    INSERT INTO orders VALUES('east','1','T4_BAG','3005',1,'offer',150,1,2000,1001);
                    PRAGMA user_version=1;''')
            store=Store(directory)
            self.assertTrue((Path(directory)/'before-private-scanner-v2.sqlite3').exists())
            store=Store(directory)
            with store.connect() as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3)
                self.assertEqual(db.execute('SELECT quantity FROM history').fetchone()[0],5)
                self.assertEqual(db.execute('SELECT source FROM orders').fetchone()[0],'data-client')


class PrivateHttpTests(unittest.TestCase):
    def test_opt_in_http_bridge_without_outbound_calls_legacy_disabled_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            server=make_server(store,0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def post(path,body):
                request=Request(base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                with urlopen(request) as response: return json.load(response)
            try:
                with self.assertRaises(HTTPError) as e:
                    post('/api/private/start',{'server':'east'})
                self.assertEqual(e.exception.code,400)
                post('/api/private/start',{'server':'east','experimental_ack':True})
                path=server.private_scanner.destination().removeprefix(base)
                self.assertEqual(post(path+'/marketorders.ingest',orders())['accepted'],1)
                post(path+'/markethistories.ingest',native())
                with urlopen(base+'/api/private/history') as response:
                    raw=json.load(response)['rows'][0]
                    self.assertIsInstance(raw['ticks'],str)
                    self.assertEqual(raw['observed_at'],END-3600)
                with self.assertRaises(HTTPError) as e:
                    post('/ingest/east/marketorders.ingest',orders())
                self.assertEqual(e.exception.code,403)
                post('/api/private/stop',{})
                with self.assertRaises(HTTPError) as e:
                    post(path+'/marketorders.ingest',orders())
                self.assertEqual(e.exception.code,403)
            finally:
                server.shutdown();thread.join();server.server_close();server.jobs.executor.shutdown();server.public_nats.stop()


class ReadOnlyNatsTests(unittest.TestCase):
    def test_wire_only_subscribes_and_pongs_no_market_publish(self):
        # Recording real TCP broker, not just checks of interface flags.
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
        recorded=[]; stop=threading.Event(); received=[]
        def broker():
            connection,_=listener.accept()
            with connection:
                connection.sendall(b'INFO {"max_payload":16777216}\r\n')
                stream=connection.makefile('rb')
                for _ in range(3): recorded.append(stream.readline())
                connection.sendall(b'PING\r\n')
                recorded.append(stream.readline())
                payload=json.dumps(orders(200)['Orders'][0]).encode()
                connection.sendall(b'MSG marketorders.deduped 1 '+str(len(payload)).encode()+b'\r\n'+payload+b'\r\n')
                stop.wait(3)
                stream.close()
        thread=threading.Thread(target=broker,daemon=True);thread.start()
        connection=socket.create_connection(listener.getsockname())
        try:
            def receive(topic,payload):
                received.append((topic,payload));stop.set()
            read_messages(connection,receive,stop)
            self.assertEqual(len(received),1)
            self.assertTrue(recorded[0].startswith(b'CONNECT '))
            self.assertEqual(recorded[1:],[b'SUB marketorders.deduped 1\r\n',b'SUB markethistories.deduped 2\r\n',b'PONG\r\n'])
            self.assertFalse(any(r.startswith((b'PUB ',b'HPUB ')) for r in recorded))
        finally:
            stop.set();connection.close();listener.close();thread.join()


@unittest.skipUnless(os.name=='nt','Windows PowerShell syntax validation runs in Windows CI')
class WindowsSyntaxTests(unittest.TestCase):
    def test_downloaded_launcher_parses_in_windows_powershell(self):
        script=Path(__file__).resolve().parents[1]/'albion_trade_desk/windows/Start-PrivateScanner.ps1'
        command='$t=$null; $e=$null; [System.Management.Automation.Language.Parser]::ParseFile($env:ALBION_PS_PARSE_PATH,[ref]$t,[ref]$e) | Out-Null; if($e.Count){$e | Out-String | Write-Error; exit 1}'
        env={**os.environ,'ALBION_PS_PARSE_PATH':str(script)}
        result=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,text=True,env=env)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
