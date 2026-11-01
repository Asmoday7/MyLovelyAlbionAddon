"""Disposable history regression fixtures. No AOD/game or real API requests."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from albion_trade_desk import feeds, ingestion
from albion_trade_desk.catalog import import_catalog
from albion_trade_desk.domain import utcnow
from albion_trade_desk.storage import Store
from albion_trade_desk.web import make_server


with tempfile.TemporaryDirectory() as directory:
    store = Store(directory)
    end = int(utcnow()//3600)*3600
    import_catalog(store, [{'UniqueName': 'T4_BAG', 'Index': 1,
                           'LocalizedNames': {'RU-RU': 'Сумка · тест истории', 'EN-US': 'Bag · history fixture'}}])
    for scale, count, spacing in ((0, 3, 3600), (1, 28, 21600), (2, 28, 86400)):
        feeds.ingest(store, 'markethistories.ingest', {
            'AlbionId': 1, 'LocationId': '3005', 'QualityLevel': 4, 'Timescale': scale,
            'MarketHistories': [{'Timestamp': (end-i*spacing)*10000000+621355968000000000,
                                'ItemAmount': 2, 'SilverAmount': 2000000}
                               for i in range(1, count+1)]}, 'east')
    def opener(request, **kwargs):
        params = parse_qs(urlsplit(request.full_url).query)
        if '/api/v2/stats/history/T4_BAG.json' not in request.full_url:
            raise AssertionError('Unexpected outbound request in isolated fixture')
        payload = [] if params['time-scale'] == ['1'] else [{
            'item_id': 'T4_BAG', 'location': 'Caerleon', 'quality': 4,
            'data': [{'timestamp': end//21600*21600-21600, 'item_count': 7, 'avg_price': 90}]}]
        response = io.BytesIO(json.dumps(payload).encode())
        response.headers = {}
        return response
    with patch('albion_trade_desk.transport.urlopen', side_effect=opener):
        server = make_server(store, 0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            subprocess.run(['node', 'tests/browser_history.cjs'], check=True, timeout=75,
                env={**os.environ, 'ALBION_SMOKE_URL': f'http://127.0.0.1:{server.server_port}'})
        finally:
            server.shutdown(); thread.join(); server.server_close()
