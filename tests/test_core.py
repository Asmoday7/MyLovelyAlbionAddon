import copy
import gzip
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError
from zipfile import ZipFile

from albion_trade_desk.storage import Store
from albion_trade_desk.catalog import import_catalog
from albion_trade_desk import analytics, ingestion
from albion_trade_desk.export import csv_bytes, xlsx_bytes, COLUMNS
from albion_trade_desk.transport import HttpClient, batches

NOW = 1760005800  # non-aligned wall-clock time; window ends at previous hour boundary
END = NOW // 3600 * 3600


def names():
    return [{"UniqueName": "T4_BAG", "Index": "1", "LocalizedNames": {"RU-RU": "Сумка знатока", "EN-US": "Adept's Bag"}},
            {"UniqueName": "T4_BAG@1", "Index": "2", "LocalizedNames": {"RU-RU": "Сумка знатока .1", "EN-US": "Adept's Bag .1"}}]


def quote(price=100, city="Caerleon", q=1, when=END-10):
    iso = datetime.fromtimestamp(when, timezone.utc).isoformat()
    return [{"item_id": "T4_BAG", "city": city, "quality": q, "sell_price_min": price,
             "sell_price_min_date": iso, "buy_price_max": 80, "buy_price_max_date": iso}]


def history(hours=24, qty=10, q=1):
    return [{"item_id": "T4_BAG", "location": "Caerleon", "quality": q,
             "data": [{"timestamp": END - 3600 * (i + 1), "item_count": qty, "avg_price": 100 + i}
                      for i in range(hours)]}]


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(self.directory.name)
        import_catalog(self.store, names())

    def row(self, **filters):
        return analytics.market(self.store, {"search": "T4_BAG", **filters}, now=NOW)["rows"][0]


class IngestionTests(DatabaseCase):
    def test_servers_markets_qualities_are_separate(self):
        ingestion.prices(self.store, quote(100))
        ingestion.prices(self.store, quote(200), "west")
        ingestion.prices(self.store, quote(300, q=2))
        ingestion.prices(self.store, quote(400, city="Black Market"))
        self.assertEqual(self.row()["quotes"]["sell_price_min"]["price"], 100)
        self.assertEqual(self.row(server="west")["quotes"]["sell_price_min"]["price"], 200)
        self.assertEqual(self.row(quality=2)["quotes"]["sell_price_min"]["price"], 300)
        bm = self.row(city="3003")
        self.assertNotIn("sell_price_min", bm["quotes"])
        self.assertEqual(bm["quotes"]["buy_price_max"]["price"], 80)

    def test_missing_price_and_sentinel_are_not_zero(self):
        data = quote(0)
        data[0]["buy_price_max_date"] = "0001-01-01T00:00:00"
        ingestion.prices(self.store, data)
        self.assertEqual(self.row()["quotes"], {})
        self.assertIsNone(self.row()["spread"])

    def test_old_response_never_replaces_newer_price(self):
        ingestion.prices(self.store, quote(200, when=END-5))
        ingestion.prices(self.store, quote(1, when=END-20))
        self.assertEqual(self.row()["quotes"]["sell_price_min"]["price"], 200)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM market_snapshots').fetchone()[0], 4)
        ingestion.prices(self.store, quote(200, when=END-5))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM market_snapshots').fetchone()[0], 4)

    def test_received_time_does_not_refresh_observation(self):
        ingestion.prices(self.store, quote(200, when=END-3600*48))
        self.assertFalse(self.row()["quotes"]["sell_price_min"]["fresh"])

    def test_history_is_upsert_not_accumulated(self):
        ingestion.history(self.store, history())
        ingestion.history(self.store, history(qty=12))
        result = self.row()["volumes"]["24h"]
        self.assertEqual(result["volume"], 288)
        self.assertEqual(self.store.status()["history"], 24)

    def test_invalid_batch_rolls_back(self):
        bad = quote() + quote(-1)
        with self.assertRaises(ValueError):
            ingestion.prices(self.store, bad)
        self.assertEqual(self.store.status()["quotes"], 0)

    def test_nan_negative_and_invalid_quality_rejected(self):
        for price in (float("nan"), -1, float("inf")):
            with self.assertRaises(ValueError):
                ingestion.prices(self.store, quote(price))
        with self.assertRaises(ValueError):
            ingestion.prices(self.store, quote(q=6))

    def test_local_order_units_dedupe_enchantment_expiry(self):
        payload = {"Orders": [{"Id": 123, "ItemTypeId": "T4_BAG", "EnchantmentLevel": 1,
                               "LocationId": "3005", "QualityLevel": 1, "UnitPriceSilver": 1500000,
                               "Amount": 1, "AuctionType": "offer", "Expires": "2099-01-01T00:00:00Z"}]}
        ingestion.local_orders(self.store, payload)
        ingestion.local_orders(self.store, payload)
        self.assertEqual(self.store.status()["orders"], 1)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM quotes").fetchone()
            self.assertEqual(row["price"], 150)
            self.assertEqual(row["item_id"], "T4_BAG@1")
            self.assertIn("partial", row["limitation"])
        payload["Orders"][0]["Id"] = 124
        payload["Orders"][0]["ItemTypeId"] = "T4_BAG"
        payload["Orders"][0]["EnchantmentLevel"] = 0
        payload["Orders"][0]["Expires"] = "2001-01-01T00:00:00Z"
        ingestion.local_orders(self.store, payload)
        self.assertEqual(self.row()["quotes"], {})

    def test_local_history_ticks_units_and_unsupported_timescale(self):
        payload = {"AlbionId": 1, "LocationId": "3005", "QualityLevel": 1, "Timescale": 0,
                   "MarketHistories": [{"Timestamp": (END-3600)*10000000+621355968000000000,
                                        "ItemAmount": 2, "SilverAmount": 2000000}]}
        ingestion.local_history(self.store, payload)
        self.assertEqual(self.row()["vwap"], 100)
        payload["Timescale"] = 1
        with self.assertRaises(ValueError):
            ingestion.local_history(self.store, payload)


class AnalyticsTests(DatabaseCase):
    def test_no_history_is_not_zero_sales(self):
        p = self.row()["volumes"]["1h"]
        self.assertIsNone(p["volume"])
        self.assertIsNone(p["known_quantity"])
        self.assertEqual(p["coverage"], 0)

    def test_exact_window_excludes_open_and_boundary_bins(self):
        data = history(25)
        data[0]["data"].append({"timestamp": END, "item_count": 999, "avg_price": 1})
        ingestion.history(self.store, data)
        self.assertEqual(self.row()["volumes"]["24h"]["volume"], 240)
        self.assertEqual(self.row()["volumes"]["1h"]["volume"], 10)

    def test_gaps_and_coarse_intervals_not_double_counted(self):
        ingestion.history(self.store, history(23))
        coarse = history(1)
        coarse[0]["data"][0]["timestamp"] = END//86400*86400 - 86400
        coarse[0]["data"][0]["item_count"] = 1000000
        ingestion.history(self.store, coarse, seconds=86400)
        p = self.row()["volumes"]["24h"]
        self.assertIsNone(p["volume"])
        self.assertEqual(p["known_quantity"], 230)
        self.assertEqual(p["known_hours"], 23)

    def test_real_observed_zero_is_distinct(self):
        ingestion.history(self.store, history(1, qty=0))
        self.assertEqual(self.row()["volumes"]["1h"]["volume"], 0)

    def test_vwap_weighted_and_anomaly_never_substituted(self):
        points = history(3)
        points[0]["data"][0].update(item_count=10, avg_price=100)
        points[0]["data"][1].update(item_count=30, avg_price=200)
        points[0]["data"][2].update(item_count=10, avg_price=100)
        ingestion.history(self.store, points)
        ingestion.prices(self.store, quote(1000))
        r = self.row()
        self.assertEqual(r["vwap"], 160)
        self.assertTrue(r["anomaly"])
        self.assertEqual(r["quotes"]["sell_price_min"]["price"], 1000)

    def test_unicode_search_and_pagination(self):
        result = analytics.market(self.store, {"search": "СУМКА"}, 1, now=NOW)
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(analytics.market(self.store, {"search": "' OR 1=1 --"})["total"], 0)


class ExportTests(DatabaseCase):
    def test_csv_utf8_schema_and_missing_values(self):
        r = self.row()
        r["name_ru"] = '=HYPERLINK("bad")'
        body = csv_bytes([r]).decode("utf-8-sig")
        self.assertTrue(body.startswith(",".join(COLUMNS)))
        self.assertIn("'=HYPERLINK", body)
        self.assertNotIn("None", body)

    def test_xlsx_is_valid_xml_with_typed_booleans_and_blanks(self):
        ingestion.prices(self.store, quote())
        body = xlsx_bytes([self.row()])
        with ZipFile(io.BytesIO(body)) as z:
            self.assertIn("xl/worksheets/sheet1.xml", z.namelist())
            for name in z.namelist():
                ET.fromstring(z.read(name))
            sheet = z.read("xl/worksheets/sheet1.xml").decode()
            self.assertIn('t="b"', sheet)
            self.assertNotIn('<v>False</v>', sheet)
            self.assertNotIn('<f>', sheet)

    def test_catalog_multi_output_nonreturnable_and_enchantment(self):
        raw = {"items": {"equipmentitem": [{"@uniquename": "T4_BAG", "@shopcategory": "bags",
                    "craftingrequirements": {"@amountcrafted": "10", "craftresource": [
                        {"@uniquename": "T4_CLOTH", "@count": "8"},
                        {"@uniquename": "ARTIFACT", "@count": "1", "@maxreturnamount": "0"}]}}]}}
        import_catalog(self.store, names(), raw)
        with self.store.connect() as db:
            recipe = db.execute("SELECT * FROM recipes").fetchone()
            self.assertEqual(recipe["output"], 10)
            self.assertFalse(json.loads(recipe["resources"])[1]["returnable"])
        self.assertEqual(self.row(search="T4_BAG@1")["enchantment"], 1)


class FakeResponse(io.BytesIO):
    def __init__(self, data, compressed=False):
        raw = json.dumps(data).encode()
        super().__init__(gzip.compress(raw) if compressed else raw)
        self.headers = {"Content-Encoding": "gzip"} if compressed else {}


class TransportTests(DatabaseCase):
    def test_compression_and_persistent_cache(self):
        calls = []
        def opener(request, **kwargs):
            calls.append(request)
            self.assertEqual(request.get_header("Accept-encoding"), "gzip")
            self.assertIsNotNone(kwargs["context"])
            return FakeResponse([{"a": 1}], True)
        client = HttpClient(self.store, opener=opener, sleep=lambda _: None)
        self.assertEqual(client.get("https://example.org/prices"), [{"a": 1}])
        self.assertEqual(client.get("https://example.org/prices"), [{"a": 1}])
        self.assertEqual(len(calls), 1)

    def test_retry_429_epoch_reset_and_transient_error(self):
        clock = [1000]
        sleeps = []
        calls = []
        def sleep(n):
            sleeps.append(n)
            clock[0] += n
        def opener(request, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                headers = Message(); headers['RateLimit-Reset'] = '1005'
                raise HTTPError(request.full_url, 429, 'rate limit', headers, None)
            return FakeResponse([])
        client = HttpClient(self.store, opener=opener, sleep=sleep, clock=lambda: clock[0])
        self.assertEqual(client.get("https://example.org"), [])
        self.assertIn(5, sleeps)
        self.assertEqual(len(calls), 2)

    def test_403_not_retried_or_hidden(self):
        def opener(request, **kwargs):
            raise HTTPError(request.full_url, 403, 'denied', Message(), None)
        with self.assertRaises(HTTPError):
            HttpClient(self.store, opener=opener).get("https://example.org")

    def test_batches_under_url_limit_and_no_duplicates(self):
        ids = [f"T8_LONG_ITEM_NAME_{i}@4" for i in range(800)]
        urls = list(batches("east", "prices", ids + ids, ["3005", "3003"], [1,2,3,4,5]))
        self.assertGreater(len(urls), 1)
        self.assertTrue(all(len(u) < 4096 for u in urls))
        self.assertEqual(sum(u.count('T8_LONG') for u in urls), 800)


if __name__ == '__main__':
    unittest.main()
