import json
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from albion_trade_desk.storage import Store
from albion_trade_desk.catalog import import_catalog
from albion_trade_desk.web import make_server


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        import_catalog(self.store, [{"UniqueName": "T4_BAG", "Index": 1, "LocalizedNames": {"RU-RU": "Сумка", "EN-US": "Bag"}}])
        self.server = make_server(self.store, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.server.jobs.executor.shutdown(wait=True)
        self.temp.cleanup()

    def request(self, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        req = Request(self.base + path, data=data, headers={"Content-Type": "application/json", **(headers or {})})
        return urlopen(req, timeout=10)

    def test_serves_real_catalog_and_assets(self):
        with self.request('/api/market?search=T4_BAG') as r:
            data = json.load(r)
        self.assertEqual(data['rows'][0]['name_ru'], 'Сумка')
        for path in ('/', '/app.js', '/crafting.js', '/craft_batch.js', '/craft_ideas.js', '/craft_summary.js', '/styles.css'):
            with self.request(path) as r:
                self.assertEqual(r.status, 200)
                self.assertGreater(len(r.read()), 200)

    def test_import_export_and_persistence(self):
        body = {'server': 'east', 'kind': 'prices', 'data': [{'item_id': 'T4_BAG', 'city': 'Caerleon', 'quality': 1,
                'sell_price_min': 500, 'sell_price_min_date': '2026-01-01T00:00:00Z'}]}
        with self.request('/api/import', body) as r:
            self.assertEqual(json.load(r)['imported'], 1)
        with self.request('/api/export.csv') as r:
            self.assertIn(b'500', r.read())
        with self.request('/api/favorites', {'id':'T4_BAG','enabled':True}):
            pass
        with self.request('/api/filters', {'name':'Личное', 'filters':{'city':'3005'}}):
            pass
        reopened = Store(self.temp.name)
        self.assertEqual(reopened.settings()['Личное']['city'], '3005')
        with self.request('/api/backup') as r:
            self.assertTrue(r.read().startswith(b'SQLite format 3'))

    def test_cross_origin_and_dns_rebinding_rejected(self):
        for headers in ({'Origin':'https://evil.example'}, {'Host':'evil.example'}):
            with self.assertRaises(HTTPError) as e:
                self.request('/api/status', headers=headers)
            self.assertEqual(e.exception.code, 403)

    def test_bad_json_object_and_quality_rejected(self):
        with self.assertRaises(HTTPError) as e:
            self.request('/api/favorites', [])
        self.assertEqual(e.exception.code, 400)
        with self.assertRaises(HTTPError) as e:
            self.request('/api/market?quality=6')
        self.assertEqual(e.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
