"""Regression: coarse game history and public 6h history disappeared from charts."""
from datetime import datetime, timezone
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from albion_trade_desk import feeds, history_view, ingestion
from albion_trade_desk.catalog import import_catalog
from albion_trade_desk.storage import Store
from test_core import names, history, NOW, END


class HistoryRegressionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(temp.name)
        import_catalog(self.store, names())
        self.query = {'id': 'T4_BAG', 'server': 'east', 'city': '3005',
                      'quality': 1, 'scope': 'private', 'hours': 168}

    def native(self, scale, count=28, spacing=21600, q=1):
        return {'AlbionId': 1, 'LocationId': '3005', 'QualityLevel': q, 'Timescale': scale,
            'MarketHistories': [{'Timestamp': (END-i*spacing)*10000000+621355968000000000,
                                'ItemAmount': 2, 'SilverAmount': 2000000}
                               for i in range(count)]}

    def test_week_chart_shows_saved_coarse_points_instead_of_three_hourly_points(self):
        ingestion.history(self.store, history(3, qty=1), source='private-client')
        feeds.ingest(self.store, 'markethistories.ingest', self.native(1), 'east')
        data = history_view.series(self.store, self.query, NOW)
        self.assertEqual(data['coverage_model'], 'native-points')
        self.assertEqual(data['point_count'], 28)
        self.assertEqual(data['known_quantity'], 56)
        self.assertEqual(data['vwap'], 100)
        self.assertIsNone(data['known_hours'])  # A point count is not hourly coverage.
        self.assertIsNone(data['volume'])
        self.assertEqual(self.store.status()['history'], 3)  # No invented hourly rows.
        self.assertEqual(history_view.series(self.store, {**self.query, 'hours': 24}, NOW)['known_hours'], 3)

    def test_month_and_week_select_one_game_scale_without_overlapping_volumes(self):
        for scale, spacing in ((1, 21600), (2, 86400)):
            feeds.ingest(self.store, 'markethistories.ingest', self.native(scale, spacing=spacing), 'east')
        week = history_view.series(self.store, self.query, NOW)
        month = history_view.series(self.store, {**self.query, 'hours': 672}, NOW)
        self.assertEqual((week['native_timescale'], week['known_quantity']), (1, 56))
        self.assertEqual((month['native_timescale'], month['known_quantity']), (2, 56))
        self.assertEqual(month['points'][0]['start'], END-27*86400)

    def test_native_quality_source_and_region_are_separate_and_public_copy_not_added_twice(self):
        payload = self.native(1)
        feeds.ingest(self.store, 'markethistories.ingest', payload, 'east')
        public = self.native(1)
        for point in public['MarketHistories']:
            point['SilverAmount'] /= 10000
        feeds.ingest(self.store, 'markethistories.deduped', public, 'east', 'aodp-nats')
        feeds.ingest(self.store, 'markethistories.ingest', self.native(1, q=5), 'east')
        data = history_view.series(self.store, {**self.query, 'scope': 'all'}, NOW)
        self.assertEqual((data['known_quantity'], data['vwap']), (56, 100))
        self.assertEqual(history_view.series(self.store, {**self.query, 'scope': 'public'}, NOW)['known_quantity'], 56)
        self.assertIsNone(history_view.series(self.store, {**self.query, 'quality': 4}, NOW)['known_quantity'])
        self.assertIsNone(history_view.series(self.store, {**self.query, 'server': 'west'}, NOW)['known_quantity'])

    def test_existing_native_points_become_visible_after_catalogue_resolution(self):
        with self.store.connect() as db:
            db.execute('DELETE FROM items')
        feeds.ingest(self.store, 'markethistories.ingest', self.native(2, spacing=86400), 'east')
        self.assertIsNone(history_view.series(self.store, self.query, NOW)['known_quantity'])
        import_catalog(self.store, names())
        feeds.resolve_history(self.store)
        data = history_view.series(self.store, {**self.query, 'hours': 672}, NOW)
        self.assertEqual(data['point_count'], 28)

    def test_public_refresh_fetches_both_resolutions_and_preserves_six_hour_duration(self):
        class Client:
            store = self.store
            def __init__(self): self.requests = []
            def get(client, url, ttl):
                params = parse_qs(urlsplit(url).query)
                client.requests.append(params)
                if params['time-scale'] == ['1']:
                    return []
                point = END//21600*21600-21600
                return [{'item_id': 'T4_BAG', 'location': 'Caerleon', 'quality': 1,
                         'data': [{'timestamp': point, 'item_count': 7, 'avg_price': 90}]}]
        client = Client()
        with patch('albion_trade_desk.history_view.utcnow', return_value=NOW):
            result = history_view.refresh(client, {**self.query, 'scope': 'public'})
        self.assertEqual([r['time-scale'] for r in client.requests], [['1'], ['6']])
        self.assertEqual(result['history'], 1)
        for params in client.requests:
            datetime.strptime(params['date'][0], '%Y-%m-%d')
            self.assertGreater(datetime.strptime(params['end_date'][0], '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp(), END)
        data = history_view.series(self.store, {**self.query, 'scope': 'public'}, NOW)
        self.assertEqual((data['known_quantity'], data['known_hours']), (7, 6))


if __name__ == '__main__':
    unittest.main()
